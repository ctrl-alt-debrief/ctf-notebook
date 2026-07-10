# Changelog

All notable changes to CTF Solver are documented here.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).
Versions follow `MAJOR.MINOR.PATCH` — increments on meaningful features, not every commit.

---

## [Unreleased]

> Features in progress but not yet complete.

Nothing — see stretch goals in CLAUDE.md.

---

## [0.5.6] — 2026-04-15

### Added
- **Input length validation** (`notebook/database.py`) — `write_page()` and `update_page()`
  now reject fields that exceed per-field character limits defined in `MAX_FIELD_LENGTHS`.
  Prevents disk/memory exhaustion from pathologically large inputs (e.g. a `working_solution`
  with gigabytes of padding). Limits are generous for real use: `working_solution` allows up
  to 100,000 chars; `key_insight` and `challenge_name` are capped at 1,000 and 200 respectively.

- **CLI chapter validation** (`main.py`) — `--chapter` now uses `argparse`'s `choices=` to
  reject unknown chapter IDs immediately at argument-parse time, before any session or database
  code runs. Previously an invalid value was handled gracefully by ChromaDB (returning zero
  results) but could trigger an unhandled `ValueError` if it reached `get_all_pages()`.

- **Absolute path resolution** (`solver/session.py`, `notebook/search.py`) — `DEFAULT_DB_PATH`
  and `DEFAULT_INDEX_PATH` are now resolved to absolute paths using `pathlib`, anchored to the
  project root via `Path(__file__).resolve()`. Previously they were relative paths
  (`"notebook/solves.db"`), meaning the database would be silently created in the wrong
  location if the tool was run from any directory other than the project root.

### Tests
- New `tests/test_security.py` with 18 tests across three areas:
  - `TestFieldLengthLimitsOnWrite` / `TestFieldLengthLimitsOnUpdate` — every capped field
    tested over its limit (must reject) and exactly at its limit (must accept).
  - `TestCLIChapterValidation` — verifies that invalid chapters produce a `SystemExit(2)`
    and valid ones are accepted, testing the argparse configuration in isolation.
  - `TestAbsolutePaths` — asserts that both default paths are absolute and land inside
    `notebook/` regardless of working directory.

---

## [0.5.5] — 2026-04-13

### Fixed
- **Tags display wrapping** (`solver/hints.py`, `solver/lessons.py`) — tag strings with many
  entries were rendering as a single unbroken line and getting cut off at the terminal edge.
  Fix: tags are now formatted with `", ".join(page.tags.split(","))` at render time so Rich
  can soft-wrap at word boundaries. Storage and search are unaffected — `page.tags` is never
  mutated, so SQLite and ChromaDB still receive the no-space normalized format
  (`"heap,use-after-free,tcache"`).

---

## [0.5.4] — 2026-04-11

### Added
- **`!q` cancel token** — typing `!q` at any prompt during a write-up or edit
  session immediately abandons the operation with nothing saved or modified.
  Works at every point: single-line fields, multi-line fields, chapter/difficulty
  pickers, and the page-id prompt in edit mode.
  - Added `CANCEL_TOKEN = "!q"` constant and `CancelSession` exception class to
    `solver/lessons.py`. The exception propagates naturally up through nested
    collectors — only `capture_lessons()` and `edit_existing_page()` need a
    `try/except` block. No intermediate function needs to know about it.
  - `!q` hint added to: chapter picker prompt, difficulty picker prompt, multi-line
    field instructions, and page-id prompt in edit mode.
  - Intro text in `capture_lessons()` now mentions `!q` upfront so users know
    the escape hatch exists before they start typing.

### Design note — why `!q` not `x`
Single-letter tokens conflict with real field content — a challenge named `x`,
a tag like `x86`, a tool abbreviated `x`. `!q` cannot appear in a field value
by accident and is recognizable from vim / REPL conventions.

---

## [0.5.3] — 2026-04-11

### Added
- **Edit existing pages** — `python main.py --edit` opens the notebook in edit
  mode. Lists all saved pages by id and name, lets the user pick one, shows the
  current preview, and runs the same save/edit/cancel loop as the capture step.
  Both SQLite and ChromaDB are updated atomically: `update_page()` rewrites the
  row, then `index_page()` upserts the new vector (same page id = old vector is
  replaced, not duplicated).
  - `notebook/database.py` — `update_page(conn, page)`: updates all user-editable
    fields on an existing row. Applies the same validation and normalization as
    `write_page()`. Does not touch `date_solved` (keeps the original solve date).
    Raises `ValueError` if the page id doesn't exist or is `None`.
  - `solver/lessons.py` — `edit_existing_page(conn, collection, console)`: lists
    pages, prompts for an id, loads the page, runs the preview/edit/cancel loop,
    then calls `update_page()` + `index_page()`. Choosing cancel leaves the
    original page untouched.
  - `solver/session.py` — `run_edit(db_path, index_path)`: same open/close
    pattern as `run()`, routes to `edit_existing_page()`.
  - `main.py` — `--edit` flag (`action="store_true"`): routes to `run_edit()`
    instead of the normal session flow.

### Tests
- Added `TestUpdatePage` (6 tests): field change persists, date unchanged,
  whitespace normalization, invalid chapter rejection, missing id, None id.
- Total: 41 tests, all passing (up from 35).

---

## [0.5.2] — 2026-04-11

### Added
- **Edit field at preview step** (`solver/lessons.py`) — at the save/edit/discard
  prompt, choosing `e` shows a numbered menu of all 9 editable fields. The user
  re-enters just the one field they want to fix, then sees the corrected preview
  before confirming. The loop repeats until they save or discard, so multiple
  fields can be corrected in one pass.
  - Added `_edit_field(page, console)` — renders the field menu, routes to the
    correct collector (`_pick_chapter`, `_pick_difficulty`, `_collect_field`, or
    `_collect_multiline`), and updates the page in-place.
  - Replaced the single `Confirm.ask()` with a `Prompt.ask(choices=["s","e","d"])`
    loop — Rich validates the input automatically, no manual re-prompt logic needed.

### Fixed
- **Ctrl+C during multi-line input no longer crashes the session** (`solver/lessons.py`)
  — `_collect_multiline()` now catches `KeyboardInterrupt` and treats it the same as
  typing `.`: accepts whatever was entered so far and moves to the next field.
  Previously, hitting Ctrl+C mid-field killed the whole session with a traceback and
  lost all entered data.
  - Updated the instruction hint to mention `Ctrl+C` as an alternative terminator.

---

## [0.5.1] — 2026-04-10

### Fixed

- **`database.py` — raw `print()` in `open_notebook()` bled through Rich spinner.**
  `open_notebook()` ended with `print(f"Notebook open: {db_path}")`. In `session.py`,
  this call sits inside a `console.status()` spinner block — the raw print fires *during*
  the spinner animation and corrupts the terminal output. Same class of bug fixed in
  `search.py` in v0.4.1. Fix: removed the print. `session.py` already prints
  `"✓ Notebook open."` after the spinner resolves.

- **`search.py` — `import warnings` was nested inside a `for` loop in `flip_to()`.**
  Python caches imports so this didn't cause a correctness bug, but placing an import
  inside a loop obscures the module's dependencies and is flagged by every linter.
  Fix: moved `import warnings` to the top of the file with the other imports.

- **`database.py` — `count_pages()` silently accepted invalid chapter names.**
  `get_all_pages(conn, chapter="bianry")` raises `ValueError` on an unknown chapter.
  `count_pages(conn, chapter="bianry")` returned `0` silently — a typo looked
  identical to "no pages in that chapter yet." Fix: added the same `VALID_CHAPTERS`
  guard that `get_all_pages()` already has.

### Tests

- Added `TestCountPages::test_count_rejects_invalid_chapter` — covers the new
  validation in `count_pages()`. The docstring explains the original silent-failure
  behaviour so the intent of the test is clear.
- Total: 35 tests, all passing (up from 34).

---

## [0.5.0] — 2026-04-10

### Added
- `solver/session.py` — session conductor; ties every module together
  - `run(db_path, index_path, chapter)` — full session lifecycle: banner → open DB
    → load index → describe challenge → `show_hints()` → solve pause →
    `capture_lessons()` → close DB. Entry point for `main.py`.
  - `_print_banner(console)` — welcome Rule header shown at startup
  - `_describe_challenge(console, chapter)` — prompts for a free-text challenge
    description (the hint finder search query) and an optional chapter filter;
    skips the chapter prompt if `--chapter` was already passed on the CLI
  - `_wait_for_solve(console)` — pauses the session with a `Confirm.ask()` while
    the user works the challenge; returns True (save lessons) or False (skip)
- `main.py` — CLI entry point (~45 lines including comments)
  - `argparse` parser with one optional flag: `--chapter CHAPTER`
  - `if __name__ == "__main__"` guard — safe to import without triggering a session

### Design Notes — session.py and main.py

- **Dependency injection:** `open_notebook()` and `load_search_index()` are called
  once in `run()`. The resulting `conn` and `collection` are passed to every
  downstream function — none of them open their own connections. One resource,
  created once, passed everywhere. This is cheap to reason about, easy to test,
  and avoids the latency of re-opening a ChromaDB collection on every hint search.
- **Single Console:** `Console()` is instantiated once in `run()` and passed to
  every function. Rich's Console manages terminal width detection, colour support,
  and output buffering — multiple instances can interleave output unpredictably.
- **Graceful first-run:** on an empty notebook, `load_search_index()` warns that
  the index is blank and `show_hints()` returns `[]` immediately — no crash,
  no confusing error, the session continues to the solve step normally.
- **Non-solve exit:** if the user answers "no" to "Did you get the flag?", the
  session exits cleanly with a friendly message. Partial progress is still
  valuable — the user can re-run later and fill in a page with what they learned.
- **`--chapter` flag:** forwarded from `main.py` → `session.run()` → `_describe_challenge()`
  → `show_hints()`. A single optional string threads through the whole stack; no
  global state needed.

### MVP Status
All five MVP checklist items from CLAUDE.md are now complete:
- [x] Can start a session and describe a challenge
- [x] Hint finder surfaces relevant past solves (handles blank notebook gracefully)
- [x] After solving, lessons are saved to the playbook
- [x] On 2nd/3rd similar challenge, relevant hints appear and are useful
- [x] README explains what the project is and how to run it

---

## [0.4.1] — 2026-04-10

### Fixed
- Removed `print()` calls from `search.py` that bled through Rich spinners
  (`open_search_index`, `index_page`, `flip_to`) — replaced orphaned-page warning with `warnings.warn()`
- `show_hints()` empty-results message now distinguishes blank notebook / chapter filter miss / unexpected empty
- Blank-field warning in `_collect_multiline()` incorrectly fired for `what_we_tried`,
  which isn't indexed — warning now only fires for `what_worked` and `working_solution`
- `page.date_solved` was always `None` in the success summary — fixed by fetching the saved
  row back with `get_page()` to get the real SQLite timestamp

### Changed
- Removed working solution code block from hint cards — too noisy for quick scanning
- `flip_to()` call in `show_hints()` now wrapped in a `console.status()` spinner

---

## [0.4.0] — 2026-04-10

### Added
- `solver/hints.py` — hint finder module; first piece of the active session layer
  - `load_search_index(index_path, console)` — wraps `open_search_index()` with a
    `console.status()` spinner; prints indexed page count on success, warns if blank
  - `show_hints(conn, collection, query, console, chapter, n_results)` — runs
    `flip_to()` and renders results as Rich Panels; returns the raw results list
    so `session.py` can inspect distances or suppress low-quality hints
  - `_render_hint_card(page, distance, rank, console)` — renders one SolvePage as a
    Panel: metadata grid (Table.grid), key insight + what worked (Text.assemble),
    syntax-highlighted working solution (Syntax, monokai theme)
  - `_distance_label(distance)` — maps L2 distance to a coloured Text label
  - `STRONG_MATCH_THRESHOLD = 0.80`, `WEAK_MATCH_THRESHOLD = 1.40` — exported
    constants so session.py can apply its own quality gates

### Design Notes — hints.py and lessons.py

- **Console ownership rule:** every function that produces output takes a
  `console: Console` parameter. No function creates its own Console. The caller
  owns the Console and passes it down — this keeps all output going to one place
  and makes output redirectable for testing or logging.
- **Output symbols:** `[green]✓[/green]` success, `[yellow]![/yellow]` warning,
  `[red]✗[/red]` error — used consistently throughout the solver layer.
- **Distance thresholds:** `< 0.80` strong match, `0.80–1.40` partial match,
  `>= 1.40` weak match. Based on L2 distances from `all-MiniLM-L6-v2`. Exported
  as module constants so the session layer can filter on them.
- **Blank notebook:** handled before any ChromaDB call — `show_hints()` returns `[]`
  immediately with a friendly warning, never crashes on first run.
- **write → index order:** `write_page()` must run before `index_page()` because
  `index_page()` calls `update_search_fingerprint(conn, page.id, ...)` — `page.id`
  is `None` until SQLite assigns it during `write_page()`. Both calls are wrapped in
  `console.status()` spinners so the user sees progress during I/O.
- **Field collection:** single-line fields use `rich.prompt.Prompt.ask()`; multi-line
  fields (`what_we_tried`, `what_worked`, `working_solution`) use a custom
  `_collect_multiline()` helper that reads until the user types `.` on its own line.
- **Preview before save:** `_preview_page()` renders the full page as a Panel using
  the same layout as hint cards in `hints.py` — what you see in the preview is exactly
  what future hint searches will show.

---

## [0.3.0] — 2026-04-09

### Added
- `notebook/search.py` — full vector search layer on top of ChromaDB
  - `COLLECTION_NAME`, `DEFAULT_INDEX_PATH`, `DEFAULT_N_RESULTS`, `EMBEDDING_FUNCTION`
    constants at module level — embedding model and ChromaDB config isolated so swapping
    models requires no changes to indexing or search logic
  - `open_search_index(index_path)` — creates or opens a persistent ChromaDB collection;
    idempotent (safe to call on every startup), prints indexed page count on open
  - `_build_document(page)` — converts a `SolvePage` to embedding text; includes chapter,
    tags, key_insight, what_worked, tools_used; excludes working_solution (code embeds as
    noise) and what_we_tried (failure paths pollute the signal)
  - `index_page(conn, collection, page)` — upserts into ChromaDB via `upsert()` (safe to
    call multiple times on the same page); writes the document back to SQLite via
    `update_search_fingerprint()` so the index can be fully rebuilt from SQLite if lost
  - `flip_to(conn, collection, query, chapter, n_results)` — converts a natural-language
    challenge description to a vector and returns the closest matching `SolvePage` objects
    ranked by distance; handles empty notebook and n_results > indexed count without crashing;
    supports optional chapter filter via ChromaDB metadata query
- `tests/test_search.py` — 11 tests covering index_page and flip_to
- Updated `tests/conftest.py` with `search_fixtures` and `indexed_page` fixtures

### Design Notes — search.py

- Embedding model: `all-MiniLM-L6-v2` via ChromaDB's `DefaultEmbeddingFunction`.
  Runs 100% locally — no API key, no network, no per-call cost. Model weights (~79MB)
  are downloaded once and cached. Swapping to a higher-quality model (e.g. Voyage AI)
  is a one-line change to the `EMBEDDING_FUNCTION` constant.
- Distance metric: L2 (Euclidean). Lower = more similar. Scores near 0.7 are strong
  matches; scores near 2.0 are likely noise. Session logic can use this threshold to
  decide whether to surface hints at all.
- SQLite is the source of truth. ChromaDB is a rebuild-able index. The `search_fingerprint`
  column in SQLite stores exactly what was embedded, enabling full index reconstruction.

### Tests
- 11 search tests: index count, fingerprint write-back, upsert idempotency, empty notebook
  cold-start, result shape, distance sign, semantic ranking, chapter filtering, n_results
  clamping
- Full suite: 34 tests, all passing

## [0.2.1] — 2026-04-09

### Fixed
- `get_all_pages(chapter=...)` now raises `ValueError` for invalid chapter names instead
  of silently returning an empty list — a typo like `"binray"` now fails loudly
- `update_search_fingerprint()` now raises `ValueError` if the target page id doesn't
  exist — previously the `UPDATE` would silently touch 0 rows and commit nothing
- Removed `check_same_thread=False` from `sqlite3.connect()` in `open_notebook()` —
  it was disabling SQLite's thread-safety guard with no current benefit

### Tests
- Added `test_chapter_filter_rejects_invalid_chapter` — covers new validation in `get_all_pages()`
- Added `test_fingerprint_raises_on_missing_page` — covers new `rowcount` guard in `update_search_fingerprint()`
- Total: 23 tests, all passing (up from 21)

---

## [0.2.0] — 2026-04-08

### Added
- `notebook/database.py` — full SQLite layer with WAL journal mode
  - `SolvePage` dataclass — the core data model for a solved challenge
  - `VALID_CHAPTERS` and `VALID_DIFFICULTIES` constants — single source of truth for validation
  - `open_notebook(db_path)` — creates schema on first run, safe to call on every startup
  - `write_page(conn, page)` — validates chapter/difficulty, normalizes comma fields, returns assigned id
  - `get_page(conn, page_id)` — returns `SolvePage` or `None` (never raises on missing)
  - `get_all_pages(conn, chapter=None)` — returns full list, supports chapter filter
  - `count_pages(conn, chapter=None)` — aggregate count query
  - `update_search_fingerprint(conn, page_id, fingerprint_json)` — ChromaDB sync bridge
- `tests/conftest.py` — shared pytest fixtures (`notebook_conn`, `sample_page`)
- `tests/test_playbook.py` — 21 database layer tests, all passing

### Tests
- 21 tests covering schema creation, write/read round-trips, validation, normalization,
  chapter filtering, count accuracy, and fingerprint storage

### Design Notes — database.py

- `tags` and `tools_used` are stored as plain comma-separated strings (e.g. `"heap, use-after-free, tcache"`).
  This is intentional for Phase 1 simplicity — SQLite has no native array type.
  **Consequence:** search and filter on these fields is string matching, not list queries.
  Searching for `"heap"` will match `"heap, overflow"` but also accidentally match `"heap_spray"`.
  This is acceptable for a personal notebook at this scale.
- **Consistency rule (enforced in `write_page()`):** before saving, strip whitespace around
  every comma in `tags` and `tools_used`. Input `"heap , use-after-free,  tcache"` is
  normalized to `"heap,use-after-free,tcache"`. This keeps filter logic predictable.
  Phase 2 option: migrate these fields to a separate tags table with a foreign key join.

### Security Note — SQL Injection Prevention

All database queries use **parameterized queries** (`?` placeholders), never string
formatting or concatenation.

**The vulnerable pattern (never do this):**
```python
# This allows SQL injection — a user-controlled value is injected directly into the query string.
cursor.execute(f"SELECT * FROM pages WHERE chapter = '{chapter}'")
```
If `chapter` were set to `' OR '1'='1`, the query becomes:
```sql
SELECT * FROM pages WHERE chapter = '' OR '1'='1'
```
...which returns every row in the table regardless of chapter.

**The safe pattern (what we use):**
```python
# SQLite receives the query and the values separately.
# It handles all escaping — the value can never alter the query structure.
cursor.execute("SELECT * FROM pages WHERE chapter = ?", (chapter,))
```
This applies to every `INSERT`, `SELECT`, and `UPDATE` in `database.py`.
SQL injection is an OWASP Top 10 vulnerability — parameterized queries are the standard fix.

---

## [0.1.0] — Project Start

### Added
- Initial project structure and folder layout
- `CLAUDE.md` — context file for Claude Code sessions
- `README.md` — project overview and setup instructions
- `CHANGELOG.md` — this file

### Notes
- Playbook database schema defined, implementation in progress
- No working code yet — this is the foundation commit
