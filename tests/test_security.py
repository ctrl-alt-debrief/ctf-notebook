"""
tests/test_security.py

Security-focused tests for the CTF Notebook.

These tests verify defensive measures that go beyond functional correctness:
  - Input length limits (prevents disk/memory exhaustion from huge field values)
  - Chapter validation at the CLI entry point (defense-in-depth)
  - Absolute path resolution (prevents database landing in unexpected locations)

Run with:
    pytest tests/test_security.py -v

Why a separate file?
  Security tests have a different failure mode than functional tests — a failure
  here means a protective boundary was removed, not just a bug. Keeping them
  separate makes them easy to run as a dedicated gate in CI or code review.
"""

import argparse
import subprocess
import sys
from pathlib import Path

import pytest

from notebook.database import (
    MAX_FIELD_LENGTHS,
    SolvePage,
    write_page,
    update_page,
)
from notebook.search import DEFAULT_INDEX_PATH
from solver.session import DEFAULT_DB_PATH


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_page(**overrides) -> SolvePage:
    """
    Return a valid SolvePage with all fields at safe lengths.

    Any field keyword argument overrides the default so individual tests can
    substitute a specific value (e.g. an oversized string) without repeating
    all the boilerplate.
    """
    base = dict(
        challenge_name="test_challenge",
        chapter="binary",
        tags="buffer-overflow,ret2win",
        difficulty="easy",
        what_we_tried="Tried fuzzing.",
        what_worked="Found win() function.",
        key_insight="The buffer was smaller than the read() limit.",
        tools_used="pwntools,gdb",
        working_solution="payload = b'A' * 40 + p64(win)",
    )
    base.update(overrides)
    return SolvePage(**base)


# ---------------------------------------------------------------------------
# Input length limits — write_page()
# ---------------------------------------------------------------------------

class TestFieldLengthLimitsOnWrite:
    """
    write_page() must reject any field that exceeds MAX_FIELD_LENGTHS.

    Each test overrides exactly one field with a string that is one character
    longer than its maximum. The others stay at safe lengths so we know which
    field triggered the error.
    """

    def test_challenge_name_too_long(self, notebook_conn):
        """challenge_name over 200 chars should raise ValueError."""
        page = _make_page(challenge_name="x" * (MAX_FIELD_LENGTHS["challenge_name"] + 1))
        with pytest.raises(ValueError, match="challenge_name"):
            write_page(notebook_conn, page)

    def test_tags_too_long(self, notebook_conn):
        """tags over 1000 chars should raise ValueError."""
        page = _make_page(tags="a," * (MAX_FIELD_LENGTHS["tags"] // 2 + 1))
        with pytest.raises(ValueError, match="tags"):
            write_page(notebook_conn, page)

    def test_key_insight_too_long(self, notebook_conn):
        """key_insight over 1000 chars should raise ValueError."""
        page = _make_page(key_insight="x" * (MAX_FIELD_LENGTHS["key_insight"] + 1))
        with pytest.raises(ValueError, match="key_insight"):
            write_page(notebook_conn, page)

    def test_tools_used_too_long(self, notebook_conn):
        """tools_used over 500 chars should raise ValueError."""
        page = _make_page(tools_used="tool," * (MAX_FIELD_LENGTHS["tools_used"] // 5 + 1))
        with pytest.raises(ValueError, match="tools_used"):
            write_page(notebook_conn, page)

    def test_what_we_tried_too_long(self, notebook_conn):
        """what_we_tried over 50,000 chars should raise ValueError."""
        page = _make_page(what_we_tried="x" * (MAX_FIELD_LENGTHS["what_we_tried"] + 1))
        with pytest.raises(ValueError, match="what_we_tried"):
            write_page(notebook_conn, page)

    def test_what_worked_too_long(self, notebook_conn):
        """what_worked over 50,000 chars should raise ValueError."""
        page = _make_page(what_worked="x" * (MAX_FIELD_LENGTHS["what_worked"] + 1))
        with pytest.raises(ValueError, match="what_worked"):
            write_page(notebook_conn, page)

    def test_working_solution_too_long(self, notebook_conn):
        """working_solution over 100,000 chars should raise ValueError."""
        page = _make_page(working_solution="x" * (MAX_FIELD_LENGTHS["working_solution"] + 1))
        with pytest.raises(ValueError, match="working_solution"):
            write_page(notebook_conn, page)

    def test_exactly_at_limit_is_accepted(self, notebook_conn):
        """A field exactly at its max length should be accepted without error."""
        page = _make_page(challenge_name="x" * MAX_FIELD_LENGTHS["challenge_name"])
        # Should not raise — max length is the boundary, not max + 1.
        page_id = write_page(notebook_conn, page)
        assert page_id > 0

    def test_error_message_includes_field_name(self, notebook_conn):
        """The ValueError message should name the offending field."""
        page = _make_page(key_insight="x" * (MAX_FIELD_LENGTHS["key_insight"] + 1))
        with pytest.raises(ValueError, match="key_insight"):
            write_page(notebook_conn, page)


# ---------------------------------------------------------------------------
# Input length limits — update_page()
# ---------------------------------------------------------------------------

class TestFieldLengthLimitsOnUpdate:
    """
    update_page() must apply the same length validation as write_page().

    A page that was written at safe lengths should still be rejected if it
    is later updated with an oversized field.
    """

    def test_oversized_field_rejected_on_update(self, notebook_conn):
        """update_page() should raise ValueError for an oversized field."""
        page = _make_page()
        write_page(notebook_conn, page)

        # Now attempt to update with an oversized key_insight.
        page.key_insight = "x" * (MAX_FIELD_LENGTHS["key_insight"] + 1)
        with pytest.raises(ValueError, match="key_insight"):
            update_page(notebook_conn, page)

    def test_valid_update_still_works(self, notebook_conn):
        """update_page() should not interfere with normal updates within limits."""
        page = _make_page()
        write_page(notebook_conn, page)

        page.key_insight = "A short, valid insight."
        update_page(notebook_conn, page)  # should not raise


# ---------------------------------------------------------------------------
# CLI chapter validation
# ---------------------------------------------------------------------------

class TestCLIChapterValidation:
    """
    The --chapter flag in main.py should reject unknown chapter IDs at the
    argparse level, before any session or database code runs.

    We rebuild a minimal parser that mirrors main.py's configuration so we can
    test it in-process without spawning a subprocess.
    """

    def _build_parser(self) -> argparse.ArgumentParser:
        """Replicate the argparse setup from main.py so we can test it directly."""
        from notebook.database import VALID_CHAPTERS
        valid_chapter_list = list(VALID_CHAPTERS.keys())
        parser = argparse.ArgumentParser()
        parser.add_argument(
            "--chapter",
            metavar="CHAPTER",
            default=None,
            choices=valid_chapter_list,
        )
        parser.add_argument("--edit", action="store_true", default=False)
        return parser

    def test_valid_chapter_accepted(self):
        """All known chapter IDs should be accepted by argparse."""
        from notebook.database import VALID_CHAPTERS
        parser = self._build_parser()
        for chapter_id in VALID_CHAPTERS:
            args = parser.parse_args(["--chapter", chapter_id])
            assert args.chapter == chapter_id

    def test_invalid_chapter_rejected(self):
        """An unknown chapter ID should cause argparse to exit with a non-zero code."""
        parser = self._build_parser()
        # parse_args calls sys.exit(2) on an invalid choice — pytest catches this
        # as SystemExit. We verify exit code 2 (argparse error), not 0 (success).
        with pytest.raises(SystemExit) as exc_info:
            parser.parse_args(["--chapter", "not_a_real_chapter"])
        assert exc_info.value.code == 2

    def test_no_chapter_flag_defaults_to_none(self):
        """Omitting --chapter should default to None (search all chapters)."""
        parser = self._build_parser()
        args = parser.parse_args([])
        assert args.chapter is None


# ---------------------------------------------------------------------------
# Absolute path resolution
# ---------------------------------------------------------------------------

class TestAbsolutePaths:
    """
    DEFAULT_DB_PATH and DEFAULT_INDEX_PATH should be absolute paths anchored
    to the project root, not relative paths that depend on the working directory.

    A relative path like "notebook/solves.db" is dangerous: if you run
    `python main.py` from the wrong directory, the database is silently created
    in a completely different location.
    """

    def test_db_path_is_absolute(self):
        """DEFAULT_DB_PATH must be an absolute filesystem path."""
        assert Path(DEFAULT_DB_PATH).is_absolute(), (
            f"DEFAULT_DB_PATH is not absolute: {DEFAULT_DB_PATH!r}\n"
            "Use pathlib to resolve it relative to session.py, not the working directory."
        )

    def test_index_path_is_absolute(self):
        """DEFAULT_INDEX_PATH must be an absolute filesystem path."""
        assert Path(DEFAULT_INDEX_PATH).is_absolute(), (
            f"DEFAULT_INDEX_PATH is not absolute: {DEFAULT_INDEX_PATH!r}\n"
            "Use pathlib to resolve it relative to search.py, not the working directory."
        )

    def test_db_path_inside_project(self):
        """DEFAULT_DB_PATH must live inside the project's notebook/ directory."""
        db_path = Path(DEFAULT_DB_PATH)
        # The path should end with notebook/solves.db regardless of where the
        # project lives on disk.
        assert db_path.parts[-2:] == ("notebook", "solves.db"), (
            f"Unexpected DB path structure: {DEFAULT_DB_PATH!r}"
        )

    def test_index_path_inside_project(self):
        """DEFAULT_INDEX_PATH must live inside the project's notebook/ directory."""
        index_path = Path(DEFAULT_INDEX_PATH)
        assert index_path.parts[-2:] == ("notebook", "search_index"), (
            f"Unexpected index path structure: {DEFAULT_INDEX_PATH!r}"
        )
