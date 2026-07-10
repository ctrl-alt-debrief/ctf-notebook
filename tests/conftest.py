"""
tests/conftest.py

Shared pytest fixtures for the CTF Notebook test suite.

Fixtures defined here are automatically available to every test file in this
directory — no imports needed. pytest discovers them by name.
"""

import pytest
import tempfile
import os

from notebook.database import open_notebook, write_page, SolvePage
from notebook.search import open_search_index, index_page


@pytest.fixture
def notebook_conn():
    """
    Open a fresh notebook database in a temporary file for each test.

    Using a real file (not :memory:) because WAL mode requires a file path —
    in-memory SQLite databases don't support WAL journal mode.

    The 'yield' hands the connection to the test. Everything after 'yield'
    runs as teardown once the test finishes — even if the test fails or raises.
    This guarantees the temp file is always cleaned up.
    """

    # tempfile.mkstemp() creates a real temporary file and returns a file
    # descriptor (fd) and its path. We close the fd immediately — sqlite3
    # will open the file itself.
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)

    conn = open_notebook(path)

    yield conn  # <-- test runs here

    # Teardown: close the connection and delete the temp file.
    conn.close()
    os.unlink(path)

    # WAL mode creates two sidecar files alongside the .db: .db-wal and .db-shm.
    # Clean those up too if they exist.
    for sidecar in [path + "-wal", path + "-shm"]:
        if os.path.exists(sidecar):
            os.unlink(sidecar)


@pytest.fixture
def search_fixtures(notebook_conn):
    """
    A (conn, collection) pair backed by a temporary ChromaDB directory.

    Yields (conn, collection) — both isolated per test, both cleaned up after.
    Depends on notebook_conn so the SQLite database is also fresh and temporary.
    """
    index_dir = tempfile.mkdtemp()
    collection = open_search_index(index_dir)

    yield notebook_conn, collection

    # Teardown: remove the ChromaDB directory and all its contents.
    import shutil
    shutil.rmtree(index_dir, ignore_errors=True)


@pytest.fixture
def indexed_page(search_fixtures, sample_page):
    """
    A sample_page that has been written to SQLite and indexed into ChromaDB.

    Returns (conn, collection, page) ready for search tests.
    """
    conn, collection = search_fixtures
    write_page(conn, sample_page)
    index_page(conn, collection, sample_page)
    return conn, collection, sample_page


@pytest.fixture
def sample_page():
    """
    A fully populated SolvePage with realistic CTF data.

    id, date_solved, and search_fingerprint are left as None — they are
    auto-filled by write_page() and index_page() respectively.
    Used by any test that needs a valid page to write or inspect.
    """

    return SolvePage(
        challenge_name="baby_pwn_2024",
        chapter="binary",
        tags="buffer-overflow,ret2win,no-canary",
        difficulty="easy",
        what_we_tried="Tried fuzzing input length. Tried reading the binary with strings.",
        what_worked="Found win() function in Ghidra. Overflowed buffer by 40 bytes to overwrite return address.",
        key_insight="The buffer was 32 bytes but the read() call allowed 72 — the 40-byte gap overwrites the saved return address directly.",
        tools_used="ghidra,pwntools,gdb-peda",
        working_solution="from pwn import *\np = process('./baby_pwn')\npayload = b'A' * 40 + p64(win_addr)\np.sendline(payload)\np.interactive()",
    )
