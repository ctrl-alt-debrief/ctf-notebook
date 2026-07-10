"""
solver/lessons.py

Lessons capture — collects what we learned after a challenge is solved and
writes it permanently to the notebook.

Responsibilities:
  1. Walk the user through filling in every SolvePage field interactively.
  2. Show a preview Panel of the completed page before committing.
  3. Call write_page() first (gets the SQLite id), then index_page() (needs that id).
  4. Confirm success with a summary Panel.

Why the order of write → index matters:
  index_page() checks that page.id is not None before touching ChromaDB —
  it calls update_search_fingerprint(conn, page.id, ...) to write back to SQLite,
  which would fail with no id. write_page() is what triggers SQLite to assign the id
  (via INTEGER PRIMARY KEY auto-increment). You cannot index a page that hasn't been
  saved yet.

Design rule: every function that produces output takes a `console: Console`
parameter. See hints.py for the full rationale.

Output conventions:
  [green]✓[/green]  — field accepted / save succeeded
  [yellow]![/yellow] — reminder or tip the user should notice
  [red]✗[/red]      — validation error, user must re-enter
"""

from __future__ import annotations

import sqlite3
from typing import Optional

import chromadb
from rich.console import Console, Group
from rich.panel import Panel
from rich.prompt import Confirm, Prompt
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text

from notebook.database import (
    SolvePage,
    VALID_CHAPTERS,
    VALID_DIFFICULTIES,
    write_page,
    update_page,
    get_page,
    get_all_pages,
)
from notebook.search import index_page


# ---------------------------------------------------------------------------
# Cancel token
# ---------------------------------------------------------------------------

# Typing this exact string at any prompt abandons the current write-up with
# nothing saved. Chosen to be visually distinct and impossible to enter by
# accident — unlike a single letter, which could appear in real field content.
CANCEL_TOKEN = "!q"


class CancelSession(Exception):
    """
    Raised by any field collector when the user types the cancel token (!q).

    Using a custom exception lets the signal travel up through nested calls
    (e.g. _collect_field → capture_lessons) without any intermediate function
    needing to check for it. capture_lessons() catches it once at the top and
    returns None cleanly. Nothing is written to SQLite or ChromaDB.
    """


# ---------------------------------------------------------------------------
# Single-line field collector
# ---------------------------------------------------------------------------

def _collect_field(
    label: str,
    console: Console,
    hint: Optional[str] = None,
) -> str:
    """
    Prompt the user for a single-line text field. Re-prompts until non-empty.

    Args:
        label:   Display name shown in the prompt (e.g. "Challenge name").
        console: Rich Console — hint text is printed through this.
        hint:    Optional guidance printed above the prompt in dim style.
                 Use this to remind the user what good input looks like.
    """

    if hint:
        console.print(f"  [dim]{hint}[/dim]")

    while True:
        # Prompt.ask() prints "label: " and waits for input.
        # It integrates with Rich's Console so styling is consistent.
        value = Prompt.ask(f"  [bold]{label}[/bold]")

        # Cancel token — abandon the whole write-up, nothing saved.
        if value.strip() == CANCEL_TOKEN:
            raise CancelSession

        if value.strip():
            return value.strip()

        # Empty input — remind and loop.
        console.print(f"  [red]✗[/red] {label} cannot be empty. Try again.")


# ---------------------------------------------------------------------------
# Multi-line field collector
# ---------------------------------------------------------------------------

def _collect_multiline(
    label: str,
    console: Console,
    hint: Optional[str] = None,
) -> str:
    """
    Collect a multi-line text field. The user types lines freely and enters
    a single '.' on its own line to finish.

    Used for fields where a single sentence isn't enough:
      - what_we_tried   (might list several failed approaches)
      - what_worked     (should explain the technique, not just the command)
      - working_solution (the exploit script — often many lines of Python)

    We fall back to Python's built-in input() for line-by-line reading because
    Rich's Prompt doesn't support multi-line entry. The label and hint are
    printed through the Rich Console so formatting stays consistent.
    """

    console.print(f"\n  [bold]{label}[/bold]")
    if hint:
        console.print(f"  [dim]{hint}[/dim]")
    console.print(
        "  [dim]Type your text. Enter [bold].[/bold] on its own line when done, "
        "[bold]Ctrl+C[/bold] to finish the field early, "
        "or [bold]!q[/bold] to cancel the whole write-up.[/dim]"
    )

    lines: list[str] = []

    while True:
        try:
            line = input()
        except EOFError:
            # Handles non-interactive environments (e.g. piped input in tests).
            break
        except KeyboardInterrupt:
            # User hit Ctrl+C mid-field. Accept whatever was typed so far and
            # move on rather than crashing the whole session and losing everything.
            # Print a newline first so the next console.print() starts on a clean line.
            print()
            console.print(f"  [yellow]![/yellow] Field ended early — using what was entered so far.")
            break

        # Cancel token — abandon the whole write-up, nothing saved.
        if line.strip() == CANCEL_TOKEN:
            raise CancelSession

        if line.strip() == ".":
            break

        lines.append(line)

    value = "\n".join(lines).strip()

    if not value:
        # An empty multi-line field is allowed but worth flagging.
        # Note: what_we_tried is NOT indexed into the search fingerprint (it pollutes
        # the signal), so leaving it blank has no effect on hint quality.
        # what_worked and working_solution DO affect quality — warn for those.
        if "what worked" in label.lower() or "working solution" in label.lower():
            console.print(
                f"  [yellow]![/yellow] {label} is blank — "
                "this field is indexed for search, so leaving it empty will reduce future hint quality."
            )
        else:
            console.print(f"  [yellow]![/yellow] {label} is blank.")

    return value


# ---------------------------------------------------------------------------
# Chapter picker
# ---------------------------------------------------------------------------

def _pick_chapter(console: Console) -> str:
    """
    Display a numbered menu of valid chapters and return the user's choice.

    Uses a Rich Table for the menu so chapter IDs and display names are
    aligned in columns. Re-prompts until a valid number is entered.
    """

    # Build a numbered list from VALID_CHAPTERS (a dict, so order is stable in Python 3.7+).
    chapters = list(VALID_CHAPTERS.items())  # [(id, display_name), ...]

    menu = Table.grid(padding=(0, 3))
    menu.add_column(style="bold cyan", justify="right")   # number
    menu.add_column(style="bold")                          # chapter id
    menu.add_column(style="dim")                           # display name

    for i, (chapter_id, display_name) in enumerate(chapters, start=1):
        menu.add_row(str(i), chapter_id, display_name)

    console.print("\n  [bold]Chapter[/bold] — which domain does this challenge belong to?")
    console.print(menu)

    while True:
        raw = Prompt.ask("  [bold]Enter number[/bold] [dim](or !q to cancel)[/dim]")

        if raw.strip() == CANCEL_TOKEN:
            raise CancelSession

        if raw.isdigit():
            idx = int(raw) - 1
            if 0 <= idx < len(chapters):
                chosen_id = chapters[idx][0]
                console.print(f"  [green]✓[/green] Chapter set to [bold]{chosen_id}[/bold].")
                return chosen_id

        console.print(f"  [red]✗[/red] Enter a number between 1 and {len(chapters)}.")


# ---------------------------------------------------------------------------
# Difficulty picker
# ---------------------------------------------------------------------------

def _pick_difficulty(console: Console) -> str:
    """
    Display the three difficulty options and return the user's choice.

    Re-prompts until a valid option is typed. Accepts full words only —
    no abbreviations — to keep validation simple.
    """

    # Sort for consistent display order: easy, hard, medium → easy, medium, hard.
    options = sorted(VALID_DIFFICULTIES)
    options_str = " / ".join(f"[bold]{d}[/bold]" for d in options)

    console.print(f"\n  [bold]Difficulty[/bold] — {options_str}")

    while True:
        raw = Prompt.ask("  [bold]Enter difficulty[/bold] [dim](or !q to cancel)[/dim]").strip().lower()

        if raw == CANCEL_TOKEN:
            raise CancelSession

        if raw in VALID_DIFFICULTIES:
            console.print(f"  [green]✓[/green] Difficulty set to [bold]{raw}[/bold].")
            return raw

        console.print(f"  [red]✗[/red] Must be one of: {', '.join(options)}.")


# ---------------------------------------------------------------------------
# Page preview
# ---------------------------------------------------------------------------

def _preview_page(page: SolvePage, console: Console) -> None:
    """
    Render the completed SolvePage as a Rich Panel before the user confirms saving.

    This is the user's last chance to spot a mistake — a typo in tags, a missing
    tool, a key_insight that's too vague — before the page is written to disk.

    Uses the same layout as _render_hint_card() in hints.py so the preview looks
    exactly like what future hint searches will show.
    """

    # --- Metadata grid ---
    meta = Table.grid(padding=(0, 3))
    meta.add_column(style="bold dim", no_wrap=True)
    meta.add_column()
    meta.add_row("Chapter",    page.chapter)
    meta.add_row("Difficulty", page.difficulty)
    meta.add_row("Tags",       ", ".join(page.tags.split(",")))
    meta.add_row("Tools",      page.tools_used)

    # --- Text fields ---
    tried_label = Text("What We Tried  ", style="bold dim")
    tried_text  = Text(page.what_we_tried)
    tried_line  = Text.assemble(tried_label, tried_text)

    worked_label = Text("What Worked    ", style="bold green")
    worked_text  = Text(page.what_worked)
    worked_line  = Text.assemble(worked_label, worked_text)

    insight_label = Text("Key Insight    ", style="bold yellow")
    insight_text  = Text(page.key_insight)
    insight_line  = Text.assemble(insight_label, insight_text)

    # --- Working solution (syntax-highlighted) ---
    solution_heading = Text("Working Solution", style="bold blue")
    solution_block   = Syntax(
        page.working_solution,
        lexer="python",
        theme="monokai",
        line_numbers=False,
        word_wrap=True,
    )

    content = Group(
        meta,
        Text(""),
        tried_line,
        Text(""),
        worked_line,
        Text(""),
        insight_line,
        Text(""),
        solution_heading,
        solution_block,
    )

    console.print(Panel(
        content,
        title=f"[bold cyan]{page.challenge_name}[/bold cyan]",
        border_style="cyan",
        padding=(1, 2),
    ))


# ---------------------------------------------------------------------------
# Field editor — used at the preview step to fix a single field
# ---------------------------------------------------------------------------

def _edit_field(page: SolvePage, console: Console) -> None:
    """
    Show a numbered menu of all editable fields and re-collect the one the
    user picks. Updates the page object in-place — no return value needed.

    Called from the save/edit/discard loop in capture_lessons() when the user
    spots a mistake in the preview (typo in tags, wrong difficulty, etc.).
    Re-uses the same collectors as the initial collection step so behaviour
    is identical — same hints, same validation, same multi-line terminator.
    """

    # Build the menu. Each entry is (display label, field name on SolvePage).
    # Single-line fields and multi-line fields are mixed — the collector chosen
    # below is what distinguishes them, not anything in this list.
    fields = [
        ("Challenge name",    "challenge_name"),
        ("Chapter",           "chapter"),
        ("Difficulty",        "difficulty"),
        ("Tags",              "tags"),
        ("Tools used",        "tools_used"),
        ("Key insight",       "key_insight"),
        ("What we tried",     "what_we_tried"),
        ("What worked",       "what_worked"),
        ("Working solution",  "working_solution"),
    ]

    menu = Table.grid(padding=(0, 3))
    menu.add_column(style="bold cyan", justify="right")
    menu.add_column(style="bold")

    for i, (label, _) in enumerate(fields, start=1):
        menu.add_row(str(i), label)

    console.print("\n  [bold]Which field do you want to edit?[/bold]")
    console.print(menu)

    # Keep prompting until a valid number is entered.
    while True:
        raw = Prompt.ask("  [bold]Enter number[/bold]")
        if raw.isdigit():
            idx = int(raw) - 1
            if 0 <= idx < len(fields):
                label, attr = fields[idx]
                break
        console.print(f"  [red]✗[/red] Enter a number between 1 and {len(fields)}.")

    # Re-collect the chosen field using the same collector as the initial pass.
    # chapter and difficulty have their own pickers (menus); everything else is
    # either single-line (_collect_field) or multi-line (_collect_multiline).
    if attr == "chapter":
        setattr(page, attr, _pick_chapter(console))

    elif attr == "difficulty":
        setattr(page, attr, _pick_difficulty(console))

    elif attr in ("what_we_tried", "what_worked", "working_solution"):
        hints = {
            "what_we_tried":    "Be honest about dead ends — they help future-you avoid the same traps.",
            "what_worked":      "Explain the technique so you could repeat it on a similar challenge.",
            "working_solution": "Paste the final script that got the flag.",
        }
        setattr(page, attr, _collect_multiline(label, console, hint=hints[attr]))

    else:
        hints = {
            "challenge_name": "e.g. baby_pwn_2024 — use the exact name from the CTF platform.",
            "tags":           "Comma-separated. e.g. buffer-overflow,ret2win,no-canary — use hyphens, no spaces.",
            "tools_used":     "Comma-separated. e.g. ghidra,pwntools,gdb-peda",
            "key_insight":    "One sentence — the 'aha' moment. Should make sense with no other context.",
        }
        setattr(page, attr, _collect_field(label, console, hint=hints.get(attr)))

    console.print(f"  [green]✓[/green] [bold]{label}[/bold] updated.")


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def capture_lessons(
    conn: sqlite3.Connection,
    collection: chromadb.Collection,
    console: Console,
) -> Optional[SolvePage]:
    """
    Walk the user through writing a new page to the notebook.

    Collects every SolvePage field interactively, shows a preview Panel,
    asks for confirmation, then saves to SQLite and indexes into ChromaDB.

    Returns the saved SolvePage (with its assigned id) on success.
    Returns None if the user declines to save at the confirmation step.

    The write → index sequence:
      1. write_page(conn, page)         — SQLite assigns page.id
      2. index_page(conn, collection, page)  — ChromaDB stores the vector;
                                              update_search_fingerprint() writes
                                              it back to SQLite using page.id

    Reversing this order would crash at step 2 because index_page() guards
    against page.id being None.
    """

    console.print()
    console.rule("[bold cyan]Lessons Learned[/bold cyan]")
    console.print(
        "\n  [yellow]![/yellow] Write a good page now and future hints will actually be useful.\n"
        "  [dim]The key_insight field matters most — make it one complete sentence "
        "that explains the 'aha' moment without any other context.\n"
        "  Type [bold]!q[/bold] at any prompt to cancel and discard everything.[/dim]\n"
    )

    # --- Collect fields ---
    # CancelSession may be raised by any collector below if the user types !q.
    # It is caught at the end of this block — nowhere in between needs to handle it.
    try:
        challenge_name = _collect_field(
            "Challenge name",
            console,
            hint="e.g. baby_pwn_2024 — use the exact name from the CTF platform.",
        )

        chapter = _pick_chapter(console)

        difficulty = _pick_difficulty(console)

        tags = _collect_field(
            "Tags",
            console,
            hint="Comma-separated. e.g. buffer-overflow,ret2win,no-canary — use hyphens, no spaces.",
        )

        tools_used = _collect_field(
            "Tools used",
            console,
            hint="Comma-separated. e.g. ghidra,pwntools,gdb-peda",
        )

        key_insight = _collect_field(
            "Key insight",
            console,
            hint="One sentence — the 'aha' moment. Should make sense with no other context.",
        )

        what_we_tried = _collect_multiline(
            "What we tried (approaches that didn't work and why)",
            console,
            hint="Be honest about dead ends — they help future-you avoid the same traps.",
        )

        what_worked = _collect_multiline(
            "What worked (include why it worked, not just the commands)",
            console,
            hint="Explain the technique so you could repeat it on a similar challenge.",
        )

        working_solution = _collect_multiline(
            "Working solution (paste your exploit script or payload)",
            console,
            hint="Paste the final script that got the flag.",
        )

    except CancelSession:
        console.print("\n  [yellow]![/yellow] Write-up cancelled — nothing was saved.\n")
        return None

    # --- Build the SolvePage ---
    # id, date_solved, and search_fingerprint are all None here.
    # write_page() will assign id and date_solved automatically.
    # index_page() will set search_fingerprint via update_search_fingerprint().
    page = SolvePage(
        challenge_name=challenge_name,
        chapter=chapter,
        tags=tags,
        difficulty=difficulty,
        what_we_tried=what_we_tried,
        what_worked=what_worked,
        key_insight=key_insight,
        tools_used=tools_used,
        working_solution=working_solution,
    )

    # --- Preview / edit loop ---
    # Show the preview, then ask save / edit / discard.
    # If the user chooses edit, _edit_field() updates the page in-place and
    # the loop restarts so they see the corrected preview before confirming.
    # This repeats until they save or discard — no limit on edit rounds.
    while True:
        console.print()
        console.rule("[bold]Page Preview[/bold]")
        console.print()
        _preview_page(page, console)

        # Prompt.ask() with choices= validates input automatically and re-prompts
        # if anything other than s/e/d is entered. No manual validation needed.
        console.print()
        choice = Prompt.ask(
            "  [bold]Save, edit a field, or discard?[/bold] "
            "[dim]\\[s=save / e=edit / d=discard][/dim]",
            choices=["s", "e", "d"],
            default="s",
        )

        if choice == "s":
            break  # fall through to write + index

        if choice == "d":
            console.print("[yellow]![/yellow] Page discarded — nothing was saved.")
            return None

        # choice == "e": let the user fix one field, then loop back to preview.
        _edit_field(page, console)

    # --- Write to SQLite ---
    # write_page() validates chapter and difficulty (raises ValueError on bad input —
    # can't happen here since we collected through _pick_chapter/_pick_difficulty,
    # but the guard exists in the database layer regardless).
    # After this call, page.id is set to the auto-assigned SQLite row id.
    with console.status("[bold cyan]Writing page to notebook...[/bold cyan]", spinner="dots"):
        page_id = write_page(conn, page)

    console.print(f"[green]✓[/green] Page written to notebook (id={page_id}).")

    # --- Index into ChromaDB ---
    # Now that page.id is set, index_page() can safely call update_search_fingerprint().
    # This step generates the embedding vector and stores it in ChromaDB so
    # flip_to() can find this page in future hint searches.
    with console.status("[bold cyan]Indexing page into smart index...[/bold cyan]", spinner="dots"):
        index_page(conn, collection, page)

    console.print(f"[green]✓[/green] Page indexed — it will appear in future hint searches.\n")

    # --- Success summary ---
    # Fetch the saved page from SQLite to get the real date_solved timestamp.
    # write_page() sets it via DEFAULT CURRENT_TIMESTAMP on the database side,
    # but doesn't read it back onto the dataclass — so page.date_solved is still
    # None at this point. get_page() gives us the fully populated row.
    saved = get_page(conn, page.id)
    date_display = saved.date_solved if saved else "just now"

    summary = Table.grid(padding=(0, 3))
    summary.add_column(style="bold dim", no_wrap=True)
    summary.add_column()
    summary.add_row("Page id",    str(page.id))
    summary.add_row("Challenge",  page.challenge_name)
    summary.add_row("Chapter",    page.chapter)
    summary.add_row("Difficulty", page.difficulty)
    summary.add_row("Saved",      date_display)

    console.print(Panel(
        summary,
        title="[bold green]✓ New page written[/bold green]",
        border_style="green",
        padding=(1, 2),
    ))

    return page


# ---------------------------------------------------------------------------
# Edit an existing page
# ---------------------------------------------------------------------------

def edit_existing_page(
    conn: sqlite3.Connection,
    collection: chromadb.Collection,
    console: Console,
) -> Optional[SolvePage]:
    """
    Let the user pick an existing page, edit any fields, and save the changes.

    Keeps SQLite and ChromaDB in sync:
      1. update_page()  — overwrites the SQLite row (same validation as write_page)
      2. index_page()   — upserts into ChromaDB, overwriting the old vector with
                          one built from the corrected content

    Returns the updated SolvePage on success, or None if the notebook is empty
    or the user cancels.

    Why upsert keeps things consistent:
      ChromaDB uses the page's SQLite id as the document id. Calling index_page()
      on an already-indexed page triggers an upsert — the old vector is replaced,
      not duplicated. So there's no cleanup step needed; we just re-index and
      the stale vector is gone.
    """

    console.print()
    console.rule("[bold cyan]Edit a Page[/bold cyan]")
    console.print()

    # --- List all pages ---
    # get_all_pages() returns newest-first. We show id + challenge name so the
    # user can identify which page to edit without reading the full content.
    pages = get_all_pages(conn)

    if not pages:
        console.print("[yellow]![/yellow] The notebook is blank — no pages to edit.")
        return None

    page_list = Table.grid(padding=(0, 3))
    page_list.add_column(style="bold cyan", justify="right")   # id
    page_list.add_column(style="bold")                          # challenge name
    page_list.add_column(style="dim")                           # chapter

    for p in pages:
        page_list.add_row(str(p.id), p.challenge_name, p.chapter)

    console.print("  [bold]Pages in the notebook:[/bold]")
    console.print(page_list)

    # --- Pick a page by id ---
    while True:
        raw = Prompt.ask("\n  [bold]Enter page id to edit[/bold] [dim](or !q to cancel)[/dim]")
        if raw.strip() == CANCEL_TOKEN:
            console.print("[yellow]![/yellow] Edit cancelled.")
            return None
        if raw.isdigit():
            page = get_page(conn, int(raw))
            if page is not None:
                break
        console.print(f"  [red]✗[/red] No page with id={raw}. Enter an id from the list above.")

    # --- Edit / preview loop ---
    # Reuse the same loop pattern as capture_lessons() — show preview, then
    # save / edit / cancel. "cancel" here means "abandon edits", not "discard
    # the page" — the original is still in the database untouched.
    while True:
        console.print()
        console.rule("[bold]Page Preview[/bold]")
        console.print()
        _preview_page(page, console)

        console.print()
        choice = Prompt.ask(
            "  [bold]Save changes, edit a field, or cancel?[/bold] "
            "[dim]\\[s=save / e=edit / c=cancel][/dim]",
            choices=["s", "e", "c"],
            default="s",
        )

        if choice == "c":
            console.print("[yellow]![/yellow] Edit cancelled — original page unchanged.")
            return None

        if choice == "e":
            try:
                _edit_field(page, console)
            except CancelSession:
                console.print("[yellow]![/yellow] Edit cancelled — original page unchanged.")
                return None
            continue  # loop back to preview

        # choice == "s": save changes
        break

    # --- Update SQLite ---
    with console.status("[bold cyan]Saving changes...[/bold cyan]", spinner="dots"):
        update_page(conn, page)

    console.print(f"[green]✓[/green] Page updated in notebook.")

    # --- Re-index into ChromaDB ---
    # index_page() uses upsert() — same page id, so the old vector is replaced,
    # not added alongside it. After this call, the search index reflects the
    # corrected content.
    with console.status("[bold cyan]Re-indexing page...[/bold cyan]", spinner="dots"):
        index_page(conn, collection, page)

    console.print("[green]✓[/green] Smart index updated — search results will reflect the changes.\n")

    return page
