"""
main.py

Entry point — run this file to start a CTF notebook session.

Usage:
    python main.py                    # start a new challenge session
    python main.py --chapter binary   # restrict hints to the 'binary' chapter
    python main.py --edit             # edit an existing page in the notebook

This file is intentionally short. Its only job is to parse command-line
arguments and hand control to session.run() or session.run_edit(). All real
logic lives in solver/.

Why argparse:
    Python's standard library argument parser. No extra dependencies.
    For a small set of flags like these, it's the right tool —
    something heavier (click, typer) would be over-engineering.
"""

import argparse

from notebook.database import VALID_CHAPTERS
from solver import session


def main() -> None:
    # --- Argument parser ---
    # ArgumentParser description appears in --help output.
    parser = argparse.ArgumentParser(
        description="CTF Notebook — a personal solver that learns from past challenges.",
    )

    # --chapter is optional. If omitted, hints search across all chapters.
    # choices= validates the value at the argparse level so an invalid chapter
    # is caught immediately with a clear error message, before any session logic runs.
    valid_chapter_list = list(VALID_CHAPTERS.keys())
    parser.add_argument(
        "--chapter",
        metavar="CHAPTER",
        default=None,
        choices=valid_chapter_list,
        help=(
            "Restrict hints to a specific chapter. "
            f"Options: {', '.join(valid_chapter_list)}"
        ),
    )

    # --edit skips the normal session flow and goes straight to the page editor.
    # store_true means the flag is a boolean switch — present = True, absent = False.
    parser.add_argument(
        "--edit",
        action="store_true",
        default=False,
        help="Edit an existing page in the notebook.",
    )

    args = parser.parse_args()

    # --- Route to the right flow ---
    if args.edit:
        session.run_edit()
    else:
        session.run(chapter=args.chapter)


# ---------------------------------------------------------------------------
# Standard Python entry-point guard
# ---------------------------------------------------------------------------
#
# `if __name__ == "__main__"` means: only run main() when this file is
# executed directly (`python main.py`), not when it's imported as a module.
# This is standard Python convention — without it, `import main` anywhere
# would immediately start a session, which is never what you want.
if __name__ == "__main__":
    main()
