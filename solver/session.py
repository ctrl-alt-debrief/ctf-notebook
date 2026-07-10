"""
solver/session.py

Session conductor — owns the full lifecycle of one CTF challenge from start to finish.

This is the file that ties every other module together. It:
  1. Opens the database and search index (once, at startup).
  2. Prompts you to describe the current challenge.
  3. Runs the hint finder to surface relevant past solves.
  4. Waits while you work on the challenge.
  5. Optionally captures what you learned and writes it to the notebook.

Key design concept — dependency injection:
  This file opens one SQLite connection and one ChromaDB collection, then passes
  them down to every function that needs them (show_hints, capture_lessons, etc.).
  None of those functions open their own connections. This matters because:
    - SQLite connections are not free to create — opening one per call is wasteful.
    - It keeps control of the database lifecycle in one place.
    - It makes testing easier — you can pass a test connection in, no monkey-patching.
  The pattern is: "create the resource once, pass it everywhere that needs it."

Console ownership:
  One Rich Console is created here and passed to every function.
  See hints.py for the full rationale. Short version: one Console = one output stream.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

from rich.console import Console
from rich.prompt import Confirm, Prompt
from rich.rule import Rule

from notebook.database import open_notebook
from notebook.search import DEFAULT_INDEX_PATH
from solver.hints import load_search_index, show_hints, WEAK_MATCH_THRESHOLD
from solver.lessons import capture_lessons, edit_existing_page


# ---------------------------------------------------------------------------
# Default paths
# ---------------------------------------------------------------------------

# Resolve absolute paths relative to this file's location so the tool works
# correctly regardless of which directory the user runs `python main.py` from.
# Path(__file__) is solver/session.py → .parent is solver/ → .parent is the project root.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Where the SQLite database lives.
DEFAULT_DB_PATH = str(_PROJECT_ROOT / "notebook" / "solves.db")


# ---------------------------------------------------------------------------
# Banner
# ---------------------------------------------------------------------------

def _print_banner(console: Console) -> None:
    """
    Print the welcome banner shown at the start of every session.

    The Rule() widget draws a horizontal line with centred text — it's the
    standard Rich way to create a section divider without any extra packages.
    """

    console.print()
    console.print(Rule("[bold cyan]CTF Notebook[/bold cyan]", style="cyan"))
    console.print(
        "  Your personal notebook for CTF solves.\n"
        "  Describe the challenge below — relevant past solves will appear as hints.\n"
    )


# ---------------------------------------------------------------------------
# Challenge description collector
# ---------------------------------------------------------------------------

def _describe_challenge(console: Console, chapter: Optional[str]) -> tuple[str, str]:
    """
    Ask the user to describe the current challenge. Returns (description, chapter).

    The description is used as the search query for the hint finder.
    The more detail you include — category, what you observe, file types, error
    messages — the better the hints will be.

    If --chapter was passed on the command line, that value is used directly and
    the user is not prompted for it again. Otherwise they pick from a short menu.

    Returns:
        (description, chapter) — both non-empty strings.
    """

    # --- Challenge description ---
    # Prompt.ask() is a single-line input. The description doesn't need to be
    # multi-line — a short paragraph is enough for a meaningful semantic search.
    console.print()
    console.rule("[bold cyan]New Challenge[/bold cyan]")
    console.print(
        "\n  [dim]Describe the challenge in plain English.\n"
        "  Include: category, what you see, any file types, error messages, "
        "or tools that seem relevant.[/dim]\n"
    )

    description = ""
    while not description.strip():
        description = Prompt.ask("  [bold]Describe the challenge[/bold]")
        if not description.strip():
            console.print("  [red]✗[/red] Description cannot be empty.")

    # --- Chapter ---
    # If the caller already knows the chapter (passed via --chapter flag),
    # confirm it rather than asking again. This avoids the redundant prompt.
    if chapter:
        console.print(f"  [dim]Chapter filter: [bold]{chapter}[/bold][/dim]")
    else:
        # Keep it simple — the user can type a chapter id or press Enter to skip.
        # We don't validate here: show_hints() handles an invalid chapter gracefully
        # (returns [] with a helpful message), and it's not worth duplicating logic.
        raw = Prompt.ask(
            "  [bold]Chapter filter[/bold] [dim](optional — press Enter to search all)[/dim]",
            default="",
        )
        chapter = raw.strip() or None

    return description.strip(), chapter


# ---------------------------------------------------------------------------
# Solve-time waiting prompt
# ---------------------------------------------------------------------------

def _wait_for_solve(console: Console) -> bool:
    """
    Pause the session while the user works on the challenge.

    Returns True if the user solved it and wants to capture lessons.
    Returns False if they want to skip saving (gave up, partial solve, etc.).

    This is the "human in the loop" step — the tool does nothing here except
    wait. All the actual CTF work happens outside the tool during this pause.
    """

    console.print()
    console.rule("[bold]Solve Time[/bold]", style="dim")
    console.print(
        "\n  [yellow]![/yellow] The notebook is open — go work the challenge.\n"
        "  Come back here when you have the flag (or want to record what you learned).\n"
    )

    # Confirm.ask() shows [y/n] and returns a bool.
    # default=True means pressing Enter counts as "yes, I solved it."
    solved = Confirm.ask("  Did you get the flag?", default=True)
    return solved


# ---------------------------------------------------------------------------
# Main session runner
# ---------------------------------------------------------------------------

def run(
    db_path: str = DEFAULT_DB_PATH,
    index_path: str = DEFAULT_INDEX_PATH,
    chapter: Optional[str] = None,
) -> None:
    """
    Run one full CTF challenge session from start to finish.

    This is the function main.py calls. The chapter argument comes from the
    --chapter command-line flag, if the user passed one.

    Session flow:
      1. Print the welcome banner.
      2. Open the database and load the search index (both with spinners).
      3. Ask the user to describe the current challenge.
      4. Show hint cards from relevant past solves.
      5. Wait while the user works on the challenge.
      6. If solved: run capture_lessons() to write a new page.
      7. If not solved: acknowledge and exit cleanly.

    Args:
        db_path:    Path to the SQLite database. Created automatically if missing.
        index_path: Path to the ChromaDB index directory. Created if missing.
        chapter:    Optional chapter filter forwarded from --chapter flag.
                    If given, hints are restricted to this chapter.
    """

    # One Console for the whole session. Rich's Console manages terminal width,
    # colour support detection, and output buffering — creating multiple instances
    # can cause interleaved output. One instance, passed everywhere.
    console = Console()

    _print_banner(console)

    # --- Open the database ---
    # open_notebook() creates the schema if the database file doesn't exist yet,
    # so this is safe to call on first run. Returns a sqlite3.Connection.
    # The `with` block ensures the connection is closed even if an exception occurs.
    with console.status("[bold cyan]Opening notebook...[/bold cyan]", spinner="dots"):
        conn = open_notebook(db_path)

    console.print("[green]✓[/green] Notebook open.")

    # --- Load the search index ---
    # This is the ChromaDB collection. load_search_index() wraps open_search_index()
    # with a spinner and prints the current page count. It also warns if the index
    # is empty so the user knows hints won't appear on the first run.
    collection = load_search_index(index_path, console)

    # --- Describe the challenge ---
    # description → used as the hint finder search query
    # chapter     → optional filter so hints are from the right domain
    description, chapter = _describe_challenge(console, chapter)

    # --- Show hints ---
    # show_hints() converts the description to a vector, finds the closest pages,
    # and renders them as Rich Panels. Returns the raw (page, distance) list so
    # we could inspect match quality here if needed in the future.
    show_hints(conn, collection, description, console, chapter=chapter)

    # --- Wait for the user to solve the challenge ---
    solved = _wait_for_solve(console)

    if solved:
        # --- Capture lessons ---
        # capture_lessons() walks the user through filling in every SolvePage field,
        # shows a preview, asks for confirmation, then writes to SQLite and ChromaDB.
        # Returns the saved SolvePage, or None if the user declined to save.
        page = capture_lessons(conn, collection, console)

        if page is None:
            # User reached the confirmation step and chose not to save.
            console.print(
                "\n  [yellow]![/yellow] No page saved. "
                "You can re-run the session to capture lessons later.\n"
            )
        else:
            console.print(
                f"\n  [green]✓[/green] Page [bold]{page.challenge_name}[/bold] "
                "added to the notebook. Good solve.\n"
            )
    else:
        # The user didn't flag the challenge this session. That's fine —
        # they can re-run and save a partial page with what they learned so far.
        console.print(
            "\n  [yellow]![/yellow] No flag yet — that's OK. "
            "Re-run the session when you get it and capture what you learned.\n"
        )

    # --- Close the database ---
    # conn.close() flushes any pending writes and releases the file lock.
    # In WAL mode (which open_notebook() sets), this also checkpoints the WAL file.
    conn.close()
    console.print("[dim]Notebook closed. See you next solve.[/dim]\n")


def run_edit(
    db_path: str = DEFAULT_DB_PATH,
    index_path: str = DEFAULT_INDEX_PATH,
) -> None:
    """
    Open the notebook in edit mode — lets the user correct an existing page.

    Same setup as run(): one Console, one DB connection, one ChromaDB collection,
    all opened once and passed down. The only difference is we go straight to
    edit_existing_page() instead of the normal session flow.

    Run with: python main.py --edit
    """

    console = Console()

    console.print()
    console.print(Rule("[bold cyan]CTF Notebook — Edit Mode[/bold cyan]", style="cyan"))
    console.print()

    with console.status("[bold cyan]Opening notebook...[/bold cyan]", spinner="dots"):
        conn = open_notebook(db_path)

    console.print("[green]✓[/green] Notebook open.")

    collection = load_search_index(index_path, console)

    edit_existing_page(conn, collection, console)

    conn.close()
    console.print("[dim]Notebook closed.[/dim]\n")
