"""
notebook/database.py

SQLite layer for the CTF Notebook. Handles all reads and writes to the local
database file (notebook.db). Each solved challenge is stored as a SolvePage.

SQLite is a file-based database — no server, no setup. The entire notebook
lives in one .db file that you can inspect, copy, or delete like any other file.
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import Optional
import sqlite3


# --- Validation constants ---

# Maps short chapter IDs (used in the database and CLI) to display names (shown in menus).
# Using a dict means we validate against "binary" but can display "Binary Exploitation".
# To add a new chapter: add one entry here — everything else picks it up automatically.
VALID_CHAPTERS: dict[str, str] = {
    "general":   "General Skills",
    "web":       "Web Exploitation",
    "crypto":    "Cryptography",
    "binary":    "Binary Exploitation",
    "forensics": "Forensics",
    "reversing": "Reverse Engineering",
    "misc":      "Miscellaneous",
}

# A set is the right structure here — we only need "is this value allowed?",
# not any associated data. Set membership checks (x in VALID_DIFFICULTIES) are O(1).
VALID_DIFFICULTIES: set[str] = {"easy", "medium", "hard"}

# Maximum character length allowed for each user-supplied text field.
# These limits prevent disk/memory exhaustion from pathologically large inputs
# (e.g. a working_solution with a gigabyte of padding) while staying generous
# for legitimate use. chapter and difficulty are omitted — they're validated
# against whitelists, not length.
MAX_FIELD_LENGTHS: dict[str, int] = {
    "challenge_name":  200,
    "tags":           1_000,
    "key_insight":    1_000,
    "tools_used":       500,
    "what_we_tried":  50_000,
    "what_worked":    50_000,
    "working_solution": 100_000,
}


def _validate_field_lengths(page: "SolvePage") -> None:
    """
    Raise ValueError if any user-supplied field exceeds its allowed length.

    Called at the start of write_page() and update_page() before any data
    touches the database. This is a second layer of defence — the interactive
    prompts already limit what a typical user can type, but the database layer
    should not trust that the caller went through the prompts.

    Raises ValueError with the field name and limits so the caller can show
    a clear message (e.g. "challenge_name is too long: 250 chars, max 200").
    """
    for field, max_len in MAX_FIELD_LENGTHS.items():
        value = getattr(page, field, "") or ""
        if len(value) > max_len:
            raise ValueError(
                f"Field '{field}' is too long: {len(value)} chars (max {max_len})."
            )


@dataclass
class SolvePage:
    """
    One page in the notebook — represents a single solved CTF challenge.

    Fields with Optional[...] = None are filled in automatically:
      - id:                 assigned by SQLite when the page is saved
      - date_solved:        set to the current timestamp on save
      - search_fingerprint: added later when the page is indexed into ChromaDB

    All other fields must be provided by the user during the solve session.
    """

    # --- User-provided fields ---
    challenge_name: str          # e.g. "baby_pwn_2024"
    chapter: str                 # one of VALID_CHAPTERS (e.g. "binary")
    tags: str                    # comma-separated: "heap, use-after-free, tcache"
    difficulty: str              # one of VALID_DIFFICULTIES: easy / medium / hard
    what_we_tried: str           # approaches that didn't work and why
    what_worked: str             # the actual solution, including why it worked
    key_insight: str             # one sentence — the "aha" moment
    tools_used: str              # comma-separated: "pwntools, gdb-peda, ropper"
    working_solution: str        # the exploit script or payload that got the flag

    # --- Auto-filled fields (set to None until assigned) ---
    id: Optional[int] = None                  # assigned by SQLite on insert
    date_solved: Optional[str] = None         # ISO timestamp, set on write
    search_fingerprint: Optional[str] = None  # JSON string, set after ChromaDB indexing


# ---------------------------------------------------------------------------
# Database connection
# ---------------------------------------------------------------------------

def open_notebook(db_path: str) -> sqlite3.Connection:
    """
    Open (or create) the notebook database at db_path and return a connection.

    On the very first run, the database file doesn't exist yet — sqlite3.connect()
    creates it automatically. Then we create the pages table if it doesn't exist yet.
    On every run after that, the file and table already exist, so nothing is overwritten.

    Returns the connection object, which is passed to all other database functions.
    """

    # sqlite3.connect() opens the file at db_path.
    # If the file doesn't exist, SQLite creates it (an empty database).
    # check_same_thread=False is needed if the connection is ever shared across
    # threads — not required now, but safe to include.
    conn = sqlite3.connect(db_path)

    # WAL (Write-Ahead Log) journal mode.
    # By default, SQLite writes directly to the database file and uses a rollback
    # journal to undo changes if something goes wrong. The risk: a crash mid-write
    # can leave the file in a partially modified state.
    #
    # WAL flips this: new data is written to a separate .wal file first. The main
    # database file is only updated during a checkpoint (which happens automatically).
    # A crash mid-write leaves the main file completely untouched — the incomplete
    # WAL entry is simply discarded on next open.
    #
    # PRAGMA is SQLite's way of setting configuration options at runtime.
    # This must be set before any reads or writes happen.
    conn.execute("PRAGMA journal_mode=WAL")

    # This tells SQLite to return rows as objects we can access by column name
    # (row["challenge_name"]) instead of by index (row[0]).
    # It makes the code much easier to read and harder to break when columns shift.
    conn.row_factory = sqlite3.Row

    # A cursor is the object that actually sends SQL to the database.
    # Think of the connection as the open file, and the cursor as the pen.
    cursor = conn.cursor()

    # CREATE TABLE IF NOT EXISTS is the key phrase here.
    # It creates the table on the first run. On every run after, SQLite sees the
    # table already exists and skips this silently. No data is ever lost.
    #
    # Column breakdown:
    #   INTEGER PRIMARY KEY  — SQLite auto-assigns a unique integer id for each row.
    #                          This becomes the page's id in SolvePage.
    #   TEXT NOT NULL        — a required string field.
    #   TEXT                 — an optional string field (can be NULL / None).
    #   CURRENT_TIMESTAMP    — SQLite fills this in automatically when a row is inserted.
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS pages (
            id                INTEGER PRIMARY KEY,
            challenge_name    TEXT NOT NULL,
            chapter           TEXT NOT NULL,
            tags              TEXT NOT NULL,
            difficulty        TEXT NOT NULL,
            what_we_tried     TEXT NOT NULL,
            what_worked       TEXT NOT NULL,
            key_insight       TEXT NOT NULL,
            tools_used        TEXT NOT NULL,
            working_solution  TEXT NOT NULL,
            date_solved       TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            search_fingerprint TEXT
        )
    """)

    # Write the schema change to disk.
    # In SQLite, changes are not saved until you call conn.commit().
    # For CREATE TABLE this is a one-time setup step.
    conn.commit()

    return conn


# ---------------------------------------------------------------------------
# Writing pages
# ---------------------------------------------------------------------------

def write_page(conn: sqlite3.Connection, page: SolvePage) -> int:
    """
    Insert a SolvePage into the notebook and return the assigned id.

    Validates chapter and difficulty before writing. Normalizes tags and
    tools_used so comma-separated values are always stored consistently.
    """

    # --- Normalize comma-separated fields ---
    # Strip whitespace around every comma before saving.
    # "heap , use-after-free,  tcache" → "heap,use-after-free,tcache"
    # This keeps filter and search logic predictable — see CHANGELOG design note.
    page.tags = ",".join(t.strip() for t in page.tags.split(","))
    page.tools_used = ",".join(t.strip() for t in page.tools_used.split(","))

    # --- Validate field lengths ---
    # Reject inputs that exceed per-field maximums before touching the database.
    # See MAX_FIELD_LENGTHS for the rationale behind each limit.
    _validate_field_lengths(page)

    # --- Validate chapter and difficulty ---
    # Raising ValueError here means the problem is caught immediately at the call
    # site, with a clear message, rather than silently storing bad data.
    if page.chapter not in VALID_CHAPTERS:
        valid = ", ".join(VALID_CHAPTERS.keys())
        raise ValueError(f"Invalid chapter '{page.chapter}'. Must be one of: {valid}")

    if page.difficulty not in VALID_DIFFICULTIES:
        valid = ", ".join(sorted(VALID_DIFFICULTIES))
        raise ValueError(f"Invalid difficulty '{page.difficulty}'. Must be one of: {valid}")

    cursor = conn.cursor()

    # --- Parameterized INSERT ---
    # The ? placeholders are filled in order by the tuple of values passed as the
    # second argument. SQLite handles all escaping — this is safe from SQL injection.
    # See CHANGELOG security note for the vulnerable alternative and why we avoid it.
    # We do NOT include id or date_solved — SQLite assigns id automatically via
    # INTEGER PRIMARY KEY, and date_solved defaults to CURRENT_TIMESTAMP.
    cursor.execute("""
        INSERT INTO pages (
            challenge_name,
            chapter,
            tags,
            difficulty,
            what_we_tried,
            what_worked,
            key_insight,
            tools_used,
            working_solution
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        page.challenge_name,
        page.chapter,
        page.tags,
        page.difficulty,
        page.what_we_tried,
        page.what_worked,
        page.key_insight,
        page.tools_used,
        page.working_solution,
    ))

    conn.commit()

    # cursor.lastrowid is the id SQLite auto-assigned to the row we just inserted.
    # We attach it to the page object so the caller's SolvePage now has its id set.
    page.id = cursor.lastrowid
    return page.id


# ---------------------------------------------------------------------------
# Reading pages
# ---------------------------------------------------------------------------

def get_page(conn: sqlite3.Connection, page_id: int) -> Optional[SolvePage]:
    """
    Fetch a single page by its id. Returns None if no page with that id exists.

    We never raise on a missing page — None is the expected return for "not found."
    The caller decides what to do (show an error, try another id, etc.).
    """

    cursor = conn.cursor()

    # SELECT with a WHERE clause on id. The ? is the parameterized placeholder.
    # Note the trailing comma in (page_id,) — required to make it a tuple,
    # not just parentheses around a value.
    cursor.execute("SELECT * FROM pages WHERE id = ?", (page_id,))

    row = cursor.fetchone()  # Returns one sqlite3.Row, or None if not found.

    if row is None:
        return None

    # Map the database row back into a SolvePage dataclass.
    # Because we set conn.row_factory = sqlite3.Row in open_notebook(), we can
    # access columns by name (row["challenge_name"]) instead of index (row[0]).
    return SolvePage(
        id=row["id"],
        challenge_name=row["challenge_name"],
        chapter=row["chapter"],
        tags=row["tags"],
        difficulty=row["difficulty"],
        what_we_tried=row["what_we_tried"],
        what_worked=row["what_worked"],
        key_insight=row["key_insight"],
        tools_used=row["tools_used"],
        working_solution=row["working_solution"],
        date_solved=row["date_solved"],
        search_fingerprint=row["search_fingerprint"],
    )


def get_all_pages(conn: sqlite3.Connection, chapter: Optional[str] = None) -> list[SolvePage]:
    """
    Return all pages in the notebook, optionally filtered by chapter.

    Always returns a list — empty list if the notebook is blank or no pages
    match the filter. Never raises. The caller never needs to handle None.
    """

    cursor = conn.cursor()

    if chapter is None:
        # No filter — return every page, newest first.
        cursor.execute("SELECT * FROM pages ORDER BY date_solved DESC")
    else:
        # Validate chapter before querying — a typo here would silently return an
        # empty list, which looks the same as "no pages in that chapter yet".
        if chapter not in VALID_CHAPTERS:
            valid = ", ".join(VALID_CHAPTERS.keys())
            raise ValueError(f"Invalid chapter '{chapter}'. Must be one of: {valid}")
        # Filter by chapter. Parameterized as always — see CHANGELOG security note.
        cursor.execute(
            "SELECT * FROM pages WHERE chapter = ? ORDER BY date_solved DESC",
            (chapter,)
        )

    # fetchall() returns a list of sqlite3.Row objects.
    # If no rows match, it returns an empty list — not None, not an error.
    rows = cursor.fetchall()

    # Map each row into a SolvePage dataclass, same pattern as get_page().
    return [
        SolvePage(
            id=row["id"],
            challenge_name=row["challenge_name"],
            chapter=row["chapter"],
            tags=row["tags"],
            difficulty=row["difficulty"],
            what_we_tried=row["what_we_tried"],
            what_worked=row["what_worked"],
            key_insight=row["key_insight"],
            tools_used=row["tools_used"],
            working_solution=row["working_solution"],
            date_solved=row["date_solved"],
            search_fingerprint=row["search_fingerprint"],
        )
        for row in rows
    ]


def count_pages(conn: sqlite3.Connection, chapter: Optional[str] = None) -> int:
    """
    Return the total number of pages in the notebook, optionally filtered by chapter.

    Used for the summary line: "Notebook has N pages across X chapters."
    Raises ValueError for an invalid chapter name — same behaviour as get_all_pages().
    """

    cursor = conn.cursor()

    if chapter is None:
        # COUNT(*) counts every row in the table regardless of column values.
        cursor.execute("SELECT COUNT(*) FROM pages")
    else:
        # Validate before querying — a typo would silently return 0 otherwise,
        # which looks identical to "no pages in that chapter yet".
        if chapter not in VALID_CHAPTERS:
            valid = ", ".join(VALID_CHAPTERS.keys())
            raise ValueError(f"Invalid chapter '{chapter}'. Must be one of: {valid}")
        cursor.execute("SELECT COUNT(*) FROM pages WHERE chapter = ?", (chapter,))

    # A COUNT query always returns exactly one row with one value.
    # We use row[0] here — aggregate results don't have named columns,
    # so row_factory doesn't help us. Index access is the correct approach.
    row = cursor.fetchone()
    return row[0]


# ---------------------------------------------------------------------------
# Updating pages
# ---------------------------------------------------------------------------

def update_page(conn: sqlite3.Connection, page: SolvePage) -> None:
    """
    Overwrite all user-editable fields on an existing page.

    Applies the same validation and normalization as write_page() — invalid
    chapter/difficulty raises ValueError, tags and tools_used are normalized.
    Raises ValueError if the page id doesn't exist in the database.

    Does NOT touch date_solved (keep the original solve date) or
    search_fingerprint (the caller must re-index via index_page() after
    this to keep ChromaDB in sync with the updated content).
    """

    if page.id is None:
        raise ValueError("Cannot update a page with no id — was it saved first?")

    # Same normalization as write_page().
    page.tags = ",".join(t.strip() for t in page.tags.split(","))
    page.tools_used = ",".join(t.strip() for t in page.tools_used.split(","))

    # Same length validation as write_page().
    _validate_field_lengths(page)

    if page.chapter not in VALID_CHAPTERS:
        valid = ", ".join(VALID_CHAPTERS.keys())
        raise ValueError(f"Invalid chapter '{page.chapter}'. Must be one of: {valid}")

    if page.difficulty not in VALID_DIFFICULTIES:
        valid = ", ".join(sorted(VALID_DIFFICULTIES))
        raise ValueError(f"Invalid difficulty '{page.difficulty}'. Must be one of: {valid}")

    cursor = conn.cursor()

    # UPDATE every user-editable column. The WHERE clause targets a specific row
    # by id — only one row is ever touched. Parameterized as always.
    cursor.execute("""
        UPDATE pages SET
            challenge_name   = ?,
            chapter          = ?,
            tags             = ?,
            difficulty       = ?,
            what_we_tried    = ?,
            what_worked      = ?,
            key_insight      = ?,
            tools_used       = ?,
            working_solution = ?
        WHERE id = ?
    """, (
        page.challenge_name,
        page.chapter,
        page.tags,
        page.difficulty,
        page.what_we_tried,
        page.what_worked,
        page.key_insight,
        page.tools_used,
        page.working_solution,
        page.id,
    ))

    if cursor.rowcount == 0:
        raise ValueError(f"No page with id={page.id} — nothing was updated.")

    conn.commit()


def update_search_fingerprint(conn: sqlite3.Connection, page_id: int, fingerprint_json: str) -> None:
    """
    Store the ChromaDB search fingerprint (as a JSON string) on an existing page.

    Called after a page has been indexed into ChromaDB. Keeps SQLite as the
    single source of truth — if ChromaDB is ever deleted, the fingerprint is
    still here and rebuild_search_index() can reconstruct the index from it.

    Returns None — this is a fire-and-forget update, no data comes back.
    """

    cursor = conn.cursor()

    # UPDATE modifies one column on one specific row, identified by id.
    # The two ? placeholders map in order to (fingerprint_json, page_id).
    cursor.execute(
        "UPDATE pages SET search_fingerprint = ? WHERE id = ?",
        (fingerprint_json, page_id)
    )

    # cursor.rowcount tells us how many rows the UPDATE actually touched.
    # If it's 0, the page_id doesn't exist — fail loudly rather than silently.
    if cursor.rowcount == 0:
        raise ValueError(f"No page with id={page_id} — fingerprint not saved.")

    conn.commit()
