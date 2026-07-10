"""
tests/test_playbook.py

Tests for the database layer (notebook/database.py).

Run with:
    pytest tests/test_playbook.py -v -k database

Each test function receives fixtures from conftest.py by parameter name.
pytest wires them up automatically — no imports of fixtures needed.
"""

import pytest
from notebook.database import (
    write_page,
    get_page,
    get_all_pages,
    count_pages,
    update_page,
    update_search_fingerprint,
    SolvePage,
)


# ---------------------------------------------------------------------------
# open_notebook
# ---------------------------------------------------------------------------

class TestOpenNotebook:

    def test_schema_created(self, notebook_conn):
        """
        After open_notebook(), the pages table should exist.
        We verify by querying sqlite_master — SQLite's internal table that
        lists all tables, indexes, and views in the database.
        """
        cursor = notebook_conn.cursor()
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='pages'"
        )
        row = cursor.fetchone()
        assert row is not None, "Expected 'pages' table to exist after open_notebook()"

    def test_empty_notebook_has_no_pages(self, notebook_conn):
        """A freshly opened notebook should contain zero pages."""
        assert count_pages(notebook_conn) == 0


# ---------------------------------------------------------------------------
# write_page
# ---------------------------------------------------------------------------

class TestWritePage:

    def test_returns_integer_id(self, notebook_conn, sample_page):
        """write_page() should return an integer id assigned by SQLite."""
        page_id = write_page(notebook_conn, sample_page)
        assert isinstance(page_id, int)
        assert page_id > 0

    def test_assigns_id_to_page(self, notebook_conn, sample_page):
        """After write_page(), the page object itself should have its id set."""
        write_page(notebook_conn, sample_page)
        assert sample_page.id is not None
        assert sample_page.id > 0

    def test_ids_increment(self, notebook_conn, sample_page):
        """Each new page should get a higher id than the last."""
        id_one = write_page(notebook_conn, sample_page)

        second_page = SolvePage(
            challenge_name="second_challenge",
            chapter="web",
            tags="sqli",
            difficulty="medium",
            what_we_tried="Manual testing",
            what_worked="Union-based injection",
            key_insight="The id parameter was directly interpolated into the SQL query.",
            tools_used="sqlmap,burpsuite",
            working_solution="' UNION SELECT null,flag FROM secrets--",
        )
        id_two = write_page(notebook_conn, second_page)
        assert id_two > id_one

    def test_rejects_invalid_chapter(self, notebook_conn, sample_page):
        """write_page() should raise ValueError for an unknown chapter."""
        sample_page.chapter = "not_a_real_chapter"
        with pytest.raises(ValueError, match="Invalid chapter"):
            write_page(notebook_conn, sample_page)

    def test_rejects_invalid_difficulty(self, notebook_conn, sample_page):
        """write_page() should raise ValueError for an unknown difficulty."""
        sample_page.difficulty = "legendary"
        with pytest.raises(ValueError, match="Invalid difficulty"):
            write_page(notebook_conn, sample_page)

    def test_normalizes_tags_whitespace(self, notebook_conn, sample_page):
        """
        Tags with inconsistent spacing around commas should be normalized.
        "heap , use-after-free,  tcache" → "heap,use-after-free,tcache"
        """
        sample_page.tags = "heap , use-after-free,  tcache"
        write_page(notebook_conn, sample_page)
        saved = get_page(notebook_conn, sample_page.id)
        assert saved.tags == "heap,use-after-free,tcache"

    def test_normalizes_tools_whitespace(self, notebook_conn, sample_page):
        """tools_used should get the same normalization as tags."""
        sample_page.tools_used = "gdb , pwntools,  ropper"
        write_page(notebook_conn, sample_page)
        saved = get_page(notebook_conn, sample_page.id)
        assert saved.tools_used == "gdb,pwntools,ropper"


# ---------------------------------------------------------------------------
# get_page
# ---------------------------------------------------------------------------

class TestGetPage:

    def test_roundtrip(self, notebook_conn, sample_page):
        """
        A page written with write_page() should come back intact from get_page().
        This is a round-trip test — write then read and compare all fields.
        """
        write_page(notebook_conn, sample_page)
        retrieved = get_page(notebook_conn, sample_page.id)

        assert retrieved is not None
        assert retrieved.id == sample_page.id
        assert retrieved.challenge_name == sample_page.challenge_name
        assert retrieved.chapter == sample_page.chapter
        assert retrieved.tags == sample_page.tags
        assert retrieved.difficulty == sample_page.difficulty
        assert retrieved.what_we_tried == sample_page.what_we_tried
        assert retrieved.what_worked == sample_page.what_worked
        assert retrieved.key_insight == sample_page.key_insight
        assert retrieved.tools_used == sample_page.tools_used
        assert retrieved.working_solution == sample_page.working_solution

    def test_date_solved_auto_filled(self, notebook_conn, sample_page):
        """date_solved should be set automatically by SQLite on insert."""
        write_page(notebook_conn, sample_page)
        retrieved = get_page(notebook_conn, sample_page.id)
        assert retrieved.date_solved is not None

    def test_returns_none_for_missing_id(self, notebook_conn):
        """get_page() should return None for an id that doesn't exist."""
        result = get_page(notebook_conn, 99999)
        assert result is None


# ---------------------------------------------------------------------------
# get_all_pages
# ---------------------------------------------------------------------------

class TestGetAllPages:

    def test_empty_notebook_returns_empty_list(self, notebook_conn):
        """get_all_pages() on a blank notebook should return [], not None."""
        result = get_all_pages(notebook_conn)
        assert result == []

    def test_returns_all_pages(self, notebook_conn, sample_page):
        """After writing two pages, get_all_pages() should return both."""
        write_page(notebook_conn, sample_page)

        second = SolvePage(
            challenge_name="web_challenge",
            chapter="web",
            tags="sqli",
            difficulty="medium",
            what_we_tried="Manual testing",
            what_worked="Union injection",
            key_insight="Input was unsanitized.",
            tools_used="burpsuite",
            working_solution="' OR 1=1--",
        )
        write_page(notebook_conn, second)

        pages = get_all_pages(notebook_conn)
        assert len(pages) == 2

    def test_chapter_filter(self, notebook_conn, sample_page):
        """get_all_pages(chapter='binary') should only return binary pages."""
        write_page(notebook_conn, sample_page)  # chapter = "binary"

        web_page = SolvePage(
            challenge_name="web_challenge",
            chapter="web",
            tags="sqli",
            difficulty="medium",
            what_we_tried="Manual testing",
            what_worked="Union injection",
            key_insight="Input was unsanitized.",
            tools_used="burpsuite",
            working_solution="' OR 1=1--",
        )
        write_page(notebook_conn, web_page)

        binary_pages = get_all_pages(notebook_conn, chapter="binary")
        assert len(binary_pages) == 1
        assert binary_pages[0].chapter == "binary"

    def test_chapter_filter_no_match_returns_empty(self, notebook_conn, sample_page):
        """Filtering by a chapter with no pages should return [], not None."""
        write_page(notebook_conn, sample_page)  # chapter = "binary"
        result = get_all_pages(notebook_conn, chapter="crypto")
        assert result == []

    def test_chapter_filter_rejects_invalid_chapter(self, notebook_conn):
        """get_all_pages() should raise ValueError for an unknown chapter."""
        with pytest.raises(ValueError, match="Invalid chapter"):
            get_all_pages(notebook_conn, chapter="not_a_chapter")


# ---------------------------------------------------------------------------
# count_pages
# ---------------------------------------------------------------------------

class TestCountPages:

    def test_count_zero_on_empty(self, notebook_conn):
        assert count_pages(notebook_conn) == 0

    def test_count_increments(self, notebook_conn, sample_page):
        """count_pages() should reflect each new write."""
        write_page(notebook_conn, sample_page)
        assert count_pages(notebook_conn) == 1

    def test_count_chapter_filter(self, notebook_conn, sample_page):
        """count_pages(chapter='binary') should only count binary pages."""
        write_page(notebook_conn, sample_page)  # chapter = "binary"
        assert count_pages(notebook_conn, chapter="binary") == 1
        assert count_pages(notebook_conn, chapter="web") == 0

    def test_count_rejects_invalid_chapter(self, notebook_conn):
        """
        count_pages() should raise ValueError for an unknown chapter — same as get_all_pages().

        Bug fixed: previously count_pages(chapter="typo") silently returned 0,
        making a typo look identical to "no pages in that chapter yet".
        """
        with pytest.raises(ValueError, match="Invalid chapter"):
            count_pages(notebook_conn, chapter="not_a_chapter")


# ---------------------------------------------------------------------------
# update_page
# ---------------------------------------------------------------------------

class TestUpdatePage:

    def test_field_change_persists(self, notebook_conn, sample_page):
        """A field changed via update_page() should be readable back from SQLite."""
        write_page(notebook_conn, sample_page)
        sample_page.tools_used = "file,mmls,fls,strings,grep"
        update_page(notebook_conn, sample_page)

        retrieved = get_page(notebook_conn, sample_page.id)
        assert retrieved.tools_used == "file,mmls,fls,strings,grep"

    def test_date_solved_unchanged(self, notebook_conn, sample_page):
        """update_page() must not alter the original solve date."""
        write_page(notebook_conn, sample_page)
        original = get_page(notebook_conn, sample_page.id)

        sample_page.key_insight = "Updated insight."
        update_page(notebook_conn, sample_page)

        updated = get_page(notebook_conn, sample_page.id)
        assert updated.date_solved == original.date_solved

    def test_normalizes_tools_whitespace(self, notebook_conn, sample_page):
        """update_page() should apply the same normalization as write_page()."""
        write_page(notebook_conn, sample_page)
        sample_page.tools_used = "file , mmls,  grep"
        update_page(notebook_conn, sample_page)

        retrieved = get_page(notebook_conn, sample_page.id)
        assert retrieved.tools_used == "file,mmls,grep"

    def test_rejects_invalid_chapter(self, notebook_conn, sample_page):
        """update_page() should raise ValueError for an unknown chapter."""
        write_page(notebook_conn, sample_page)
        sample_page.chapter = "not_a_chapter"
        with pytest.raises(ValueError, match="Invalid chapter"):
            update_page(notebook_conn, sample_page)

    def test_raises_on_missing_id(self, notebook_conn, sample_page):
        """update_page() should raise ValueError if the page id doesn't exist."""
        write_page(notebook_conn, sample_page)
        sample_page.id = 99999
        with pytest.raises(ValueError, match="No page with id="):
            update_page(notebook_conn, sample_page)

    def test_raises_if_id_is_none(self, notebook_conn, sample_page):
        """update_page() should raise ValueError if called before write_page()."""
        with pytest.raises(ValueError, match="no id"):
            update_page(notebook_conn, sample_page)


# ---------------------------------------------------------------------------
# update_search_fingerprint
# ---------------------------------------------------------------------------

class TestUpdateSearchFingerprint:

    def test_fingerprint_stored(self, notebook_conn, sample_page):
        """After update_search_fingerprint(), the page should have the fingerprint set."""
        write_page(notebook_conn, sample_page)
        update_search_fingerprint(notebook_conn, sample_page.id, '{"vector": [0.1, 0.2, 0.3]}')

        retrieved = get_page(notebook_conn, sample_page.id)
        assert retrieved.search_fingerprint == '{"vector": [0.1, 0.2, 0.3]}'

    def test_fingerprint_initially_null(self, notebook_conn, sample_page):
        """A freshly written page should have no fingerprint yet."""
        write_page(notebook_conn, sample_page)
        retrieved = get_page(notebook_conn, sample_page.id)
        assert retrieved.search_fingerprint is None

    def test_fingerprint_raises_on_missing_page(self, notebook_conn):
        """update_search_fingerprint() should raise ValueError for a non-existent id."""
        with pytest.raises(ValueError, match="No page with id="):
            update_search_fingerprint(notebook_conn, 99999, '{"vector": [0.1]}')
