"""
notebook/search.py

Vector search layer for the CTF Notebook. Handles indexing solved challenges
and finding similar past solves when starting a new challenge.

How it fits into the bigger picture:
  - SQLite (database.py) is the source of truth — every page lives there.
  - ChromaDB (this file) is the search index — it stores vector representations
    of each page so we can find "similar" pages by meaning, not just keywords.

Why two databases?
  SQLite is great at structured queries ("give me all binary pages") but terrible
  at "find me pages that feel similar to this new challenge description." ChromaDB
  is built for exactly that — it stores embeddings (lists of numbers that encode
  meaning) and can find the closest ones to a query in milliseconds.

The flow:
  1. A page is written to SQLite via write_page().
  2. index_page() converts that page to a vector and stores it in ChromaDB.
  3. flip_to() takes a natural-language challenge description, converts it to a
     vector, and asks ChromaDB: "what stored vectors are closest to this?"
  4. The matching page ids are used to fetch full SolvePage objects from SQLite.
"""

from __future__ import annotations

import warnings
from pathlib import Path
import chromadb
from chromadb.utils import embedding_functions

from typing import Optional
from notebook.database import SolvePage, get_page, update_search_fingerprint


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# The name of our ChromaDB collection — think of it as the table name.
# One collection holds all indexed pages regardless of chapter.
COLLECTION_NAME = "ctf_notebook"

# Resolve the index path to an absolute location relative to this file so the
# tool works correctly regardless of which directory the user runs it from.
# Path(__file__) is notebook/search.py → .parent is notebook/ → .parent is project root.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_INDEX_PATH = str(_PROJECT_ROOT / "notebook" / "search_index")

# How many similar pages to return from a search by default.
# Returning 3 is enough to surface useful patterns without overwhelming the user.
# The caller can override this for edge cases (e.g. "show me everything on heap").
DEFAULT_N_RESULTS = 3

# The embedding model used to convert text into vectors.
#
# We use ChromaDB's built-in sentence-transformers model (all-MiniLM-L6-v2).
# This runs 100% locally — no API key, no network, no cost per call.
# The model produces 384-dimensional vectors, which is more than enough for
# a personal notebook at this scale.
#
# Why not use the Claude/Voyage API for embeddings?
# Better embedding models exist (e.g. voyage-3 from Anthropic's partner Voyage AI),
# but the quality difference only matters at large scale. For a personal notebook
# with dozens of pages, the local model is indistinguishable in practice —
# and it works offline, which matters during a live CTF.
#
# To swap in a different model later, change this constant and re-index.
# Nothing else in this file needs to change — that's the point of isolating it here.
EMBEDDING_FUNCTION = embedding_functions.DefaultEmbeddingFunction()


# ---------------------------------------------------------------------------
# Search index connection
# ---------------------------------------------------------------------------

def open_search_index(index_path: str = DEFAULT_INDEX_PATH) -> chromadb.Collection:
    """
    Open (or create) the ChromaDB search index at index_path and return the collection.

    On the very first run, ChromaDB creates the directory and an empty collection.
    On every run after, it opens the existing collection — no data is lost.
    This is the same "connect or create" pattern as open_notebook() in database.py.

    Returns the Collection object, which is passed to index_page() and flip_to().
    """

    # PersistentClient writes ChromaDB's data to disk at the given path.
    # The alternative (chromadb.Client()) is in-memory only — data is gone
    # when the process ends, which makes it useless as a search index.
    client = chromadb.PersistentClient(path=index_path)

    # get_or_create_collection() is idempotent:
    #   - First run: creates a new empty collection with this name.
    #   - Every run after: opens the existing collection.
    # This is ChromaDB's equivalent of SQLite's CREATE TABLE IF NOT EXISTS.
    #
    # embedding_function tells ChromaDB which model to use when converting
    # text to vectors. This must be the same model on every call — vectors
    # from different models live in different mathematical spaces and are
    # not comparable. Binding it here (at the collection level) enforces that.
    collection = client.get_or_create_collection(
        name=COLLECTION_NAME,
        embedding_function=EMBEDDING_FUNCTION,
    )

    return collection


# ---------------------------------------------------------------------------
# Indexing pages
# ---------------------------------------------------------------------------

def _build_document(page: SolvePage) -> str:
    """
    Convert a SolvePage into a single text document for embedding.

    We only include fields that carry semantic meaning about the solve technique.
    ChromaDB will embed this text — the quality of future search results depends
    directly on what we put here.

    Fields included and why:
      chapter      — grounds the vector in a domain (binary vs web vs crypto)
      tags         — the most concentrated signal: "heap, use-after-free, tcache"
      key_insight  — one sentence capturing the "aha" moment; highly distinctive
      what_worked  — explains the technique in natural language; rich semantic content
      tools_used   — tools cluster by domain and technique (pwntools → binary)

    Fields excluded and why:
      working_solution — code, not natural language; embeds as noise
      what_we_tried    — what *didn't* work; pollutes the signal
      challenge_name   — arbitrary string with no semantic meaning ("baby_pwn_2024")
      date_solved      — irrelevant to similarity
    """

    return (
        f"chapter: {page.chapter}\n"
        f"tags: {page.tags}\n"
        f"key insight: {page.key_insight}\n"
        f"what worked: {page.what_worked}\n"
        f"tools: {page.tools_used}"
    )


def index_page(
    conn,
    collection: chromadb.Collection,
    page: SolvePage,
) -> None:
    """
    Index a SolvePage into ChromaDB and write the fingerprint back to SQLite.

    Steps:
      1. Build a text document from the page's meaningful fields.
      2. Upsert it into ChromaDB — ChromaDB generates the embedding automatically.
      3. Write the document text back to SQLite via update_search_fingerprint().

    Why upsert (not add)?
      upsert() inserts if the id is new, updates if it already exists.
      This makes index_page() safe to call multiple times on the same page —
      useful if a page is edited after the fact, or if the index is rebuilt.
      add() would raise an error on a duplicate id.

    Why write the document back to SQLite?
      SQLite is the source of truth. Storing what we indexed there means
      the ChromaDB search index can always be fully reconstructed from SQLite
      alone — if the index directory is deleted, nothing is permanently lost.
    """

    if page.id is None:
        raise ValueError("Cannot index a page that hasn't been written to SQLite yet. Call write_page() first.")

    # Step 1: build the text document we'll embed.
    document = _build_document(page)

    # Step 2: upsert into ChromaDB.
    #
    # ChromaDB collection items have four parts:
    #   ids       — unique string identifier per item (we use the SQLite page id)
    #   documents — the raw text; ChromaDB runs it through EMBEDDING_FUNCTION
    #   embeddings — generated automatically from documents (we don't pass these)
    #   metadatas — structured fields stored alongside the vector for filtering
    #
    # Metadata lets us later say "only search within chapter=binary" — same as
    # a WHERE clause in SQL, but applied after the vector search step.
    collection.upsert(
        ids=[str(page.id)],
        documents=[document],
        metadatas=[{
            "chapter":        page.chapter,
            "difficulty":     page.difficulty,
            "challenge_name": page.challenge_name,
            "tags":           page.tags,
        }],
    )

    # Step 3: write the document back to SQLite for durability.
    # If ChromaDB is ever deleted, this is what we'd use to rebuild the index.
    update_search_fingerprint(conn, page.id, document)


# ---------------------------------------------------------------------------
# Searching pages
# ---------------------------------------------------------------------------

def flip_to(
    conn,
    collection: chromadb.Collection,
    query: str,
    chapter: Optional[str] = None,
    n_results: int = DEFAULT_N_RESULTS,
) -> list[tuple[SolvePage, float]]:
    """
    Find the most similar past solves to a natural-language challenge description.

    Takes a plain-English query (e.g. "binary challenge with a stack overflow and
    a win function") and returns the closest matching pages from the notebook,
    ranked by similarity.

    Returns a list of (SolvePage, distance) tuples — lower distance means more
    similar. Returns an empty list if the notebook is blank or no pages are indexed.
    Never raises on an empty notebook — the cold-start case is handled gracefully.

    Args:
        conn:       SQLite connection — used to fetch full SolvePage objects by id.
        collection: ChromaDB collection — the search index to query.
        query:      Natural-language description of the current challenge.
        chapter:    Optional chapter filter (e.g. "binary"). If given, only pages
                    from that chapter are considered.
        n_results:  Maximum number of results to return. Defaults to DEFAULT_N_RESULTS.
    """

    # --- Cold-start guard ---
    # ChromaDB throws if you query an empty collection or ask for more results
    # than exist. We handle both cases here before touching ChromaDB.
    total_indexed = collection.count()

    if total_indexed == 0:
        return []

    # Clamp n_results to however many pages actually exist.
    # Asking for 3 results when only 1 page is indexed would otherwise crash.
    safe_n = min(n_results, total_indexed)

    # --- Build the metadata filter ---
    # ChromaDB's where clause lets us restrict the search to a subset of vectors
    # based on metadata fields we stored at index time. This is applied *before*
    # the vector similarity search — it's like a SQL WHERE clause, but for vectors.
    # If no chapter is specified, we search the whole collection.
    where = {"chapter": chapter} if chapter is not None else None

    # --- Query ChromaDB ---
    # ChromaDB converts `query` to a vector using EMBEDDING_FUNCTION (same model
    # used at index time), then computes the distance from that vector to every
    # stored vector (filtered by `where` if set), and returns the closest `safe_n`.
    #
    # Result shape (ChromaDB supports batch queries, so results are nested):
    #   results["ids"]       → [["1", "3", "2"]]       — page ids, best first
    #   results["distances"] → [[0.12, 0.45, 0.89]]    — lower = more similar
    #
    # We always query one string at a time, so we access index [0] to unwrap
    # the outer list.
    query_kwargs = {
        "query_texts": [query],
        "n_results": safe_n,
    }
    if where is not None:
        query_kwargs["where"] = where

    results = collection.query(**query_kwargs)

    ids        = results["ids"][0]        # list of string ids, best match first
    distances  = results["distances"][0]  # parallel list of float distances

    # --- Fetch full SolvePage objects from SQLite ---
    # ChromaDB only stores ids and metadata — not the full page content.
    # We use the returned ids to look up the complete SolvePage in SQLite.
    # SQLite is the source of truth; ChromaDB is just the index.
    pages: list[tuple[SolvePage, float]] = []

    for page_id_str, distance in zip(ids, distances):
        page = get_page(conn, int(page_id_str))

        if page is None:
            # This shouldn't happen in normal operation — it means a page was
            # indexed in ChromaDB but deleted from SQLite without re-indexing.
            # Use warnings.warn so the message surfaces without disrupting Rich output.
            warnings.warn(
                f"Indexed page id={page_id_str} not found in SQLite — skipping.",
                RuntimeWarning,
                stacklevel=2,
            )
            continue

        pages.append((page, distance))

    return pages
