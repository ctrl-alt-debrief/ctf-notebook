"""
solver/hints.py

Hint finder — surfaces relevant past solves before starting a new challenge.

Responsibilities:
  1. load_search_index() — open ChromaDB with a spinner so the user knows
     something is happening (the model loads can take a second or two).
  2. show_hints()       — query the notebook and render results as Rich Panels.

Design rule: every function that produces output takes a `console: Console`
parameter. Nothing in this file creates its own Console — the caller owns it
and passes it down. This keeps all output going to one place, which matters
when the caller wants to redirect output (e.g. to a log file or a test buffer).

Output conventions used throughout this file:
  [green]✓[/green]  — something succeeded or a strong match was found
  [yellow]![/yellow] — a warning the user should notice but doesn't need to act on
  [red]✗[/red]      — an error or a match so weak it's probably noise
"""

from __future__ import annotations

import sqlite3
from typing import Optional

import chromadb
from rich.console import Console, Group
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from notebook.database import SolvePage
from notebook.search import open_search_index, flip_to, DEFAULT_N_RESULTS


# ---------------------------------------------------------------------------
# Distance thresholds
# ---------------------------------------------------------------------------

# The embedding model (all-MiniLM-L6-v2) produces L2 distances.
# Lower distance = more similar. These thresholds were chosen empirically:
#
#   < STRONG  → almost certainly the same technique or domain
#   < WEAK    → related area, worth reading even if not an exact match
#   >= WEAK   → probably noise — the notebook doesn't have a close match yet
#
# These are constants so callers can import them to apply their own filtering
# (e.g. session.py might suppress hints entirely if all distances are >= WEAK).
STRONG_MATCH_THRESHOLD = 0.80
WEAK_MATCH_THRESHOLD   = 1.40


# ---------------------------------------------------------------------------
# Index loader
# ---------------------------------------------------------------------------

def load_search_index(index_path: str, console: Console) -> chromadb.Collection:
    """
    Open (or create) the ChromaDB search index, showing a spinner while it loads.

    ChromaDB's PersistentClient and the sentence-transformers embedding model
    both do file I/O on startup — it can take 1–3 seconds. The spinner tells
    the user the tool is working, not frozen.

    Returns the Collection object that index_page() and flip_to() expect.
    Raises if ChromaDB fails to open (e.g. corrupted index directory).
    """

    # console.status() is a context manager that shows an animated spinner
    # for the duration of the `with` block. It stops automatically when the
    # block exits — whether by normal return or by exception.
    #
    # The spinner replaces the cursor line while running, then disappears.
    # Any console.print() calls inside the block still work normally.
    with console.status(
        "[bold cyan]Loading smart index...[/bold cyan]",
        spinner="dots",
    ):
        collection = open_search_index(index_path)

    page_count = collection.count()

    if page_count == 0:
        # An empty index isn't an error — it just means the notebook is blank.
        # We warn rather than fail so the session can still proceed.
        console.print("[yellow]![/yellow] Smart index is empty — notebook has no pages yet.")
    else:
        console.print(
            f"[green]✓[/green] Smart index loaded — "
            f"[bold]{page_count}[/bold] page{'s' if page_count != 1 else ''} indexed."
        )

    return collection


# ---------------------------------------------------------------------------
# Distance label helper
# ---------------------------------------------------------------------------

def _distance_label(distance: float) -> Text:
    """
    Return a coloured Rich Text label that tells the user how good a match is.

    This is purely cosmetic — the raw distance is also shown in the panel header
    for anyone who wants to interpret the number themselves.
    """
    if distance < STRONG_MATCH_THRESHOLD:
        return Text("✓ strong match", style="bold green")
    elif distance < WEAK_MATCH_THRESHOLD:
        return Text("! partial match", style="bold yellow")
    else:
        return Text("✗ weak match", style="bold red")


# ---------------------------------------------------------------------------
# Single hint card renderer
# ---------------------------------------------------------------------------

def _render_hint_card(
    page: SolvePage,
    distance: float,
    rank: int,
    console: Console,
) -> None:
    """
    Render one SolvePage as a Rich Panel hint card.

    Layout (top to bottom inside the panel):
      • Header line  — rank, challenge name, match quality label, raw distance
      • Metadata     — chapter / difficulty / tags / tools (grid table)
      • Key Insight  — the one-sentence "aha" moment (yellow label)
      • What Worked  — the technique explanation (green label)
      • Working Solution — syntax-highlighted Python code block

    Args:
        page:     The SolvePage to display.
        distance: L2 similarity distance — lower is more similar.
        rank:     1-based position in the results list (shown as #1, #2, …).
        console:  Rich Console — all output goes through this.
    """

    # --- Header line ---
    # Assembled as a Text object so each segment can have its own style
    # without needing to nest markup strings.
    header = Text()
    header.append(f"#{rank}  ", style="bold white")
    header.append(page.challenge_name, style="bold cyan")
    header.append("  —  ")
    header.append(_distance_label(distance))
    header.append(f"  (score: {distance:.3f})", style="dim")

    # --- Metadata grid ---
    # Table.grid() is a Table with no borders — just aligned columns.
    # We use it here as a simple two-column key/value display.
    # padding=(0, 2) adds 2 spaces of horizontal padding between columns.
    meta = Table.grid(padding=(0, 2))
    meta.add_column(style="bold dim", no_wrap=True)
    meta.add_column()
    meta.add_row("Chapter",    page.chapter)
    meta.add_row("Difficulty", page.difficulty)
    meta.add_row("Tags",       ", ".join(page.tags.split(",")))
    meta.add_row("Tools",      page.tools_used)

    # --- Key insight ---
    # This is the one sentence that should make a future solve faster.
    # Yellow label draws the eye — it's the most important field to read.
    insight_label = Text("Key Insight  ", style="bold yellow")
    insight_text  = Text(page.key_insight)
    insight_line  = Text.assemble(insight_label, insight_text)

    # --- What worked ---
    worked_label = Text("What Worked  ", style="bold green")
    worked_text  = Text(page.what_worked)
    worked_line  = Text.assemble(worked_label, worked_text)

    # --- Assemble panel content ---
    # Group() stacks Rich renderables vertically inside the Panel.
    # Each item in the Group is rendered in order, top to bottom.
    # Text("") is a blank line spacer — cleaner than "\n" in a Text object.
    #
    # The working solution code block is intentionally excluded from hints —
    # a wall of code is noise when you're trying to quickly orient yourself.
    # The full solution is always available by looking up the page in the notebook.
    content = Group(
        header,
        Text(""),
        meta,
        Text(""),
        insight_line,
        Text(""),
        worked_line,
    )

    console.print(Panel(
        content,
        border_style="blue",
        padding=(1, 2),
    ))


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def show_hints(
    conn: sqlite3.Connection,
    collection: chromadb.Collection,
    query: str,
    console: Console,
    chapter: Optional[str] = None,
    n_results: int = DEFAULT_N_RESULTS,
) -> list[tuple[SolvePage, float]]:
    """
    Search the notebook for relevant past solves and display them as hint cards.

    This is the function session.py calls at the start of a solve session.
    It runs flip_to() to get ranked results, then renders each result as a
    Panel using _render_hint_card().

    Returns the raw results list so the caller can inspect distances or decide
    whether to suppress low-quality hints (e.g. if all distances >= WEAK_MATCH_THRESHOLD).
    Returns an empty list if the notebook is blank or no pages match.

    Args:
        conn:       SQLite connection — used by flip_to() to fetch full SolvePage objects.
        collection: ChromaDB collection — the search index to query against.
        query:      Natural-language description of the current challenge.
                    e.g. "binary challenge with a format string bug and ASLR enabled"
        console:    Rich Console — all output goes through this.
        chapter:    Optional chapter filter. If given, only pages from that chapter
                    are considered (e.g. "binary", "web"). None = search everything.
        n_results:  Maximum number of hint cards to display. Defaults to DEFAULT_N_RESULTS (3).
    """

    console.print()
    console.rule("[bold cyan]Hint Finder[/bold cyan]")
    console.print()

    # --- Run the search ---
    # Wrap in a spinner — the embedding model converts the query text to a vector
    # before any search happens, which takes a noticeable moment on first call.
    # flip_to() returns [] for a blank notebook, never raises.
    # It also handles n_results > indexed count gracefully.
    with console.status("[bold cyan]Searching the notebook...[/bold cyan]", spinner="dots"):
        results = flip_to(
            conn,
            collection,
            query,
            chapter=chapter,
            n_results=n_results,
        )

    # --- Handle empty results ---
    # There are three distinct reasons results can be empty — each deserves its
    # own message so the user knows what's actually happening.
    if not results:
        if collection.count() == 0:
            # The index has never had anything added to it.
            console.print(
                "[yellow]![/yellow] The notebook is blank — "
                "solve a challenge and save a page to get hints next time."
            )
        elif chapter is not None:
            # The index has pages, but none are in the requested chapter.
            console.print(
                f"[yellow]![/yellow] No pages found in chapter [bold]{chapter}[/bold] yet. "
                "Try searching without a chapter filter, or solve a challenge in this domain first."
            )
        else:
            # The index has pages but the query returned nothing (shouldn't happen
            # with ChromaDB unless something is corrupted).
            console.print("[red]✗[/red] Search returned no results — the index may need rebuilding.")
        console.print()
        return []

    # --- Summary line ---
    count = len(results)
    chapter_note = f" in chapter [bold]{chapter}[/bold]" if chapter else ""
    console.print(
        f"[green]✓[/green] Found [bold]{count}[/bold] "
        f"relevant page{'s' if count != 1 else ''}{chapter_note}.\n"
    )

    # --- Render each result as a hint card ---
    for rank, (page, distance) in enumerate(results, start=1):
        _render_hint_card(page, distance, rank, console)

    # --- Overall quality warning ---
    # If every result is a weak match, the user should know the notebook
    # doesn't have a close match for this challenge yet.
    all_weak = all(distance >= WEAK_MATCH_THRESHOLD for _, distance in results)
    if all_weak:
        console.print(
            "[yellow]![/yellow] All matches are weak — "
            "the notebook may not have a close match for this challenge type yet. "
            "These hints are still worth skimming, but don't rely on them heavily."
        )

    console.print()
    return results
