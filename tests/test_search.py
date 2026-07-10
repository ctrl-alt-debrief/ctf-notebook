"""
tests/test_search.py

Tests for the vector search layer (notebook/search.py).

Run with:
    pytest tests/test_search.py -v

These tests use real ChromaDB and real embeddings (no mocking) so they are
slower than the database tests — the embedding model runs on each indexed page.
"""

import pytest
from notebook.database import write_page, SolvePage
from notebook.search import index_page, flip_to


# ---------------------------------------------------------------------------
# index_page
# ---------------------------------------------------------------------------

class TestIndexPage:

    def test_collection_count_increments(self, search_fixtures, sample_page):
        """After index_page(), ChromaDB should contain one more item."""
        conn, collection = search_fixtures
        write_page(conn, sample_page)

        assert collection.count() == 0
        index_page(conn, collection, sample_page)
        assert collection.count() == 1

    def test_fingerprint_written_to_sqlite(self, search_fixtures, sample_page):
        """index_page() should write the document text back to the SQLite row."""
        conn, collection = search_fixtures
        write_page(conn, sample_page)
        index_page(conn, collection, sample_page)

        from notebook.database import get_page
        saved = get_page(conn, sample_page.id)
        assert saved.search_fingerprint is not None
        # The fingerprint should contain the fields we embed — spot-check two.
        assert "binary" in saved.search_fingerprint
        assert sample_page.key_insight in saved.search_fingerprint

    def test_upsert_is_idempotent(self, search_fixtures, sample_page):
        """Calling index_page() twice on the same page should not duplicate it."""
        conn, collection = search_fixtures
        write_page(conn, sample_page)

        index_page(conn, collection, sample_page)
        index_page(conn, collection, sample_page)  # second call — should upsert, not add

        assert collection.count() == 1

    def test_raises_if_page_has_no_id(self, search_fixtures, sample_page):
        """index_page() should raise ValueError if the page hasn't been saved to SQLite yet."""
        conn, collection = search_fixtures
        # sample_page.id is None because write_page() was never called.
        with pytest.raises(ValueError, match="write_page"):
            index_page(conn, collection, sample_page)


# ---------------------------------------------------------------------------
# flip_to
# ---------------------------------------------------------------------------

class TestFlipTo:

    def test_empty_notebook_returns_empty_list(self, search_fixtures):
        """flip_to() on a blank notebook should return [] without raising."""
        conn, collection = search_fixtures
        result = flip_to(conn, collection, "buffer overflow challenge")
        assert result == []

    def test_returns_list_of_tuples(self, indexed_page):
        """flip_to() should return a list of (SolvePage, float) tuples."""
        conn, collection, _ = indexed_page
        results = flip_to(conn, collection, "buffer overflow with a win function")

        assert isinstance(results, list)
        assert len(results) == 1
        page, distance = results[0]
        assert isinstance(page, SolvePage)
        assert isinstance(distance, float)

    def test_distance_is_non_negative(self, indexed_page):
        """Distance values should always be >= 0 (they are geometric distances)."""
        conn, collection, _ = indexed_page
        results = flip_to(conn, collection, "stack smashing return address overwrite")
        _, distance = results[0]
        assert distance >= 0

    def test_relevant_query_scores_lower_than_unrelated(self, search_fixtures):
        """
        A query that matches a page's domain should score lower (more similar)
        than a query about a completely different domain.

        We write one binary page and compare distances for a binary query vs
        a web/SQL query — the binary query should be closer.
        """
        conn, collection = search_fixtures

        binary_page = SolvePage(
            challenge_name="stack_smash",
            chapter="binary",
            tags="buffer-overflow,ret2win",
            difficulty="easy",
            what_we_tried="Fuzzed the input.",
            what_worked="Overflowed the buffer to redirect execution to win().",
            key_insight="The buffer was smaller than the read() limit — saved return address was overwritable.",
            tools_used="pwntools,gdb",
            working_solution="payload = b'A' * 40 + p64(win)",
        )
        write_page(conn, binary_page)
        index_page(conn, collection, binary_page)

        binary_results = flip_to(conn, collection, "stack overflow overwrite return address win function")
        web_results    = flip_to(conn, collection, "SQL injection login bypass authentication")

        _, binary_distance = binary_results[0]
        _, web_distance    = web_results[0]

        # The binary query should be semantically closer (lower distance).
        assert binary_distance < web_distance

    def test_chapter_filter_restricts_results(self, search_fixtures):
        """flip_to() with a chapter filter should only return pages from that chapter."""
        conn, collection = search_fixtures

        # Index one binary page and one web page.
        binary_page = SolvePage(
            challenge_name="pwn_one", chapter="binary", tags="rop",
            difficulty="medium", what_we_tried="Tried ret2libc.",
            what_worked="Built a ROP chain to call system('/bin/sh').",
            key_insight="NX was enabled so shellcode didn't run — ROP chains execute existing code instead.",
            tools_used="ropper,pwntools", working_solution="chain = rop.chain()",
        )
        web_page = SolvePage(
            challenge_name="web_one", chapter="web", tags="xss",
            difficulty="easy", what_we_tried="Tried SQL injection.",
            what_worked="Injected a script tag into an unsanitized input field.",
            key_insight="The comment field rendered HTML directly — no output encoding applied.",
            tools_used="burpsuite", working_solution="<script>alert(1)</script>",
        )
        for p in [binary_page, web_page]:
            write_page(conn, p)
            index_page(conn, collection, p)

        results = flip_to(conn, collection, "exploit with code reuse", chapter="binary")

        assert len(results) == 1
        page, _ = results[0]
        assert page.chapter == "binary"

    def test_n_results_respected(self, search_fixtures):
        """flip_to() should return at most n_results pages."""
        conn, collection = search_fixtures

        # Index three pages.
        for i, chapter in enumerate(["binary", "web", "crypto"]):
            p = SolvePage(
                challenge_name=f"challenge_{i}", chapter=chapter, tags="test",
                difficulty="easy", what_we_tried="Tried things.",
                what_worked="Something worked.", key_insight=f"Insight for {chapter} challenge.",
                tools_used="python", working_solution="flag{}",
            )
            write_page(conn, p)
            index_page(conn, collection, p)

        results = flip_to(conn, collection, "any challenge", n_results=2)
        assert len(results) <= 2

    def test_n_results_clamped_to_available(self, search_fixtures, sample_page):
        """
        Asking for more results than exist should not crash — it should return
        however many pages are available.
        """
        conn, collection = search_fixtures
        write_page(conn, sample_page)
        index_page(conn, collection, sample_page)

        # Ask for 10 results when only 1 page is indexed.
        results = flip_to(conn, collection, "any challenge", n_results=10)
        assert len(results) == 1
