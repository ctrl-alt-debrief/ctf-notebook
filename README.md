# CTF Notebook

**A CLI tool that learns every time you solve a CTF challenge.**

Describe a challenge, get hints from your past solves, capture what you learned.
The notebook compounds — the more you use it, the faster you solve.

Built in Python. Runs offline. No API key needed.

---

## The Problem It Solves

Every CTF competitor hits the same wall: you've solved a buffer overflow before, you know
you used `cyclic()` to find the offset, but you can't remember the exact approach —
so you start Googling from scratch again.

This tool fixes that. Every solve gets written into a structured page with the key insight,
what didn't work, the final exploit script, and tags. Before your next challenge, the notebook
searches those pages semantically — not by keyword, but by meaning — and surfaces the most
relevant technique from your own history.

---

## Full Walkthrough

### Starting a Session

```
$ python main.py --chapter binary

──────────────────────── CTF Notebook ────────────────────────
  Your personal notebook for CTF solves.
  Describe the challenge — relevant past pages will appear as hints.

─────────────────────── New Challenge ────────────────────────
  Describe the challenge: 64-bit ELF, no canary, win() visible in Ghidra,
                          segfaults on long input

✓ Smart index loaded — 6 pages indexed.
```

### Hint Cards (Vector Search in Action)

The notebook converts your description into an embedding and finds the closest
matches from your past solves — even when the wording is completely different.

```
──────────────────────── Hint Finder ─────────────────────────
✓ Found 2 relevant pages.

╭─────────────────────────────────────────────────────────────╮
│ #1  baby_bof_2023  —  ✓ strong match  (0.41)                │
│                                                             │
│  Chapter     binary                                         │
│  Difficulty  easy                                           │
│  Tags        ret2win, no-canary, 64-bit                     │
│  Tools       pwntools, gdb-peda                             │
│  Solved      2024-03-15                                     │
│                                                             │
│  Key Insight  Find the offset with cyclic(), then jump      │
│               straight to win() — no need to leak libc.     │
│                                                             │
│  What Worked  checksec confirmed no canary, no PIE.         │
│               cyclic(200) + gdb gave offset = 40.           │
│               p64(win_addr) overwrote the return address.   │
╰─────────────────────────────────────────────────────────────╯

╭─────────────────────────────────────────────────────────────╮
│ #2  ret2win_practice  —  ~ partial match  (0.93)            │
│                                                             │
│  Chapter     binary                                         │
│  Difficulty  easy                                           │
│  Tags        ret2win, 32-bit, gets-vuln                     │
│  Tools       pwntools, pwndbg                               │
│  Solved      2024-02-28                                     │
│                                                             │
│  Key Insight  32-bit calling convention — arguments go on   │
│               the stack, not registers. Don't forget the    │
│               extra padding after the saved return address. │
╰─────────────────────────────────────────────────────────────╯

──────────────────────── Solve Time ──────────────────────────
  The notebook is open — go work the challenge.

  Did you get the flag? [Y/n]:
```

### Writing a New Page (After Getting the Flag)

```
─────────────────────── Write New Page ───────────────────────
  Let's write up what you learned. Type !q at any point to cancel.

  Challenge name: bof_warmup_2024
  Difficulty [easy/medium/hard]: easy
  Tags (comma-separated): ret2win, no-canary, 64-bit, stack-overflow

  What did you try that didn't work?
  (Type each line, then . on its own line to finish)
  > Tried padding of 32 first — off by 8.
  > Forgot to check if PIE was enabled — wasted 10 min on that.
  > .

  What actually worked?
  > checksec showed no canary, no PIE, no RELRO.
  > cyclic(200) → corefile → cyclic_find(corefile.fault_addr) = 40.
  > Sent 40 'A's + p64(win_addr). Got the flag.
  > .

  Key insight (one sentence — make it count):
  > Run checksec before anything else — knowing the mitigations
  > tells you exactly which attack class to use.

  Tools used: pwntools, gdb-peda, checksec

  Working solution / exploit script:
  > from pwn import *
  > p = process('./bof_warmup_2024')
  > offset = 40
  > win = p.elf.symbols['win']
  > payload = b'A' * offset + p64(win)
  > p.sendline(payload)
  > p.interactive()
  > .

╭─────────────── Preview — bof_warmup_2024 ───────────────────╮
│  Chapter     binary         Difficulty  easy                 │
│  Tags        ret2win, no-canary, 64-bit, stack-overflow      │
│  Tools       pwntools, gdb-peda, checksec                    │
│                                                             │
│  Key Insight  Run checksec before anything else — knowing    │
│               the mitigations tells you exactly which        │
│               attack class to use.                           │
╰─────────────────────────────────────────────────────────────╯

  Save this page? [s=save / e=edit a field / d=discard]: s

⠋ Writing page to notebook...
✓ Page written.
⠋ Updating smart index...
✓ Smart index updated. (7 pages indexed)
```

### Edit Mode — Fix a Page Any Time

```
$ python main.py --edit

──────────────────────── Edit Mode ───────────────────────────
  Pages in your notebook:

  ID  Challenge             Chapter    Difficulty
  ─────────────────────────────────────────────────
   1  baby_bof_2023         binary     easy
   2  ret2win_practice      binary     easy
   3  sqli_login_bypass     web        medium
   4  rsa_small_e           crypto     hard
   5  png_steghide          forensics  easy
   6  caesar_warmup         crypto     easy
   7  bof_warmup_2024       binary     easy

  Edit page ID: 4

  Which field?
   1. challenge_name    5. what_we_tried
   2. chapter           6. what_worked
   3. difficulty        7. key_insight
   4. tags              8. tools_used
                        9. working_solution

  Field: 7

  Key insight (current): RSA with small e — try cube root of ciphertext directly.
  New value: RSA with e=3 and no padding — if m³ < n, the ciphertext is just m³
             and you can recover m with an integer cube root. No need to factor n.

✓ Page updated. Smart index re-synced.
```

---

## How the Search Works

The hint finder does not match keywords. It uses **vector similarity search**:

```
Your description  ──► embedding model ──► vector
                                              │
                                       ChromaDB index
                                              │
Past page #1 ─────────────────────────► vector ─┐
Past page #2 ─────────────────────────► vector ─┼─ distances compared
Past page #3 ─────────────────────────► vector ─┘
                                              │
                                  Closest pages returned
```

The embedding model (`all-MiniLM-L6-v2`) runs **100% locally** — no API call,
no network, no cost. Weights (~79 MB) are downloaded once and cached.
This is intentional: CTFs are often run at venues with restricted internet.

SQLite is the **source of truth**. ChromaDB is a **rebuild-able index** — if the
index is lost or corrupted, every page can be re-embedded from the SQLite rows.

---

## Notes on the Code

**One connection, passed everywhere** — the database and search index are opened
once at the start of a session and passed down to every function that needs them.
Nothing re-opens its own connection mid-session. Simpler to reason about and faster.

**SQL injection prevention** — every database query uses parameterized placeholders
(`?`), never string formatting or concatenation. The CHANGELOG has a section on this
with the vulnerable pattern and the safe pattern side by side, since it's a common
mistake worth documenting.

**Input is validated before anything gets saved** — chapter and difficulty are checked
against a fixed list of valid values, tag strings are normalized (whitespace around
commas stripped), and each field has a length limit. A typo in a chapter name raises
an error immediately instead of silently saving bad data.

**All output goes through one place** — every function that prints anything receives
the same output object rather than creating its own. When that's not the case,
a stray `print()` inside a loading spinner corrupts the terminal animation. This was
a real bug — see v0.5.1 in the CHANGELOG.

**`!q` cancels a write-up cleanly** — typing `!q` at any prompt abandons the session
with nothing saved. Single letters like `q` or `x` would conflict with real field
content (`x86`, `xss`). `!q` can't appear in a field value by accident.

---

## Tech Stack

| Tool | Role |
|---|---|
| Python 3.10+ | Core language — standard for CTF scripting |
| SQLite | Local storage — no server, inspectable with any SQL browser |
| ChromaDB | Vector similarity search — finds related pages without exact tag matches |
| sentence-transformers | Local embedding model — `all-MiniLM-L6-v2`, no API key needed |
| Rich | Terminal UI — panels, spinners, tables, syntax highlighting |
| pytest | 53 tests across the database, search, and security layers |

---

## Project Structure

```
ctf-notebook/
│
├── main.py                  ← entry point — argparse, routes to session or edit mode
│
├── notebook/                ← the storage and search layer
│   ├── database.py          ← reads and writes pages (SQLite)
│   └── search.py            ← converts pages to vectors and searches them (ChromaDB)
│
├── solver/                  ← the active session layer
│   ├── session.py           ← orchestrates one challenge from start to finish
│   ├── hints.py             ← loads index, renders hint cards as Rich panels
│   └── lessons.py           ← interactive page-writing with preview + edit loop
│
├── tools/                   ← CTF tool wrappers (in progress)
│
└── tests/
    ├── test_playbook.py     ← 23 database layer tests
    ├── test_search.py       ← 12 vector search tests
    └── test_security.py     ← 18 input validation and path security tests
```

---

## Getting Started

**Prerequisites:** Python 3.10+. No API key. No external accounts.

```bash
git clone https://github.com/ctrl-alt-debrief/ctf-notebook.git
cd ctf-notebook
pip install -r requirements.txt
```

```bash
# Start a session
python main.py

# Scope hints to one chapter
python main.py --chapter binary

# Edit an existing page
python main.py --edit

# Run the test suite
pytest tests/
```

The database and search index are created automatically on first run inside `notebook/`.

---

## Chapters

| Chapter | What It Covers |
|---|---|
| `general` | Command line, encodings, file formats, basic scripting |
| `web` | SQL injection, XSS, SSRF, auth bypasses, cookies |
| `crypto` | RSA, AES, hashing, padding oracles, classical ciphers |
| `binary` | Buffer overflows, ROP chains, heap exploitation, shellcode |
| `forensics` | File carving, steganography, memory dumps, packet analysis |
| `reversing` | Disassembly, decompilation, anti-debug, unpacking |
| `misc` | Anything that doesn't fit neatly above |

---

## Roadmap

### Complete — v0.5.6

- [x] SQLite layer with full CRUD, validation, and field-length limits
- [x] ChromaDB vector search with local embedding model
- [x] Session flow: describe → hint cards → solve → write page
- [x] Interactive write-up with preview and per-field edit
- [x] Edit mode (`--edit`) with ChromaDB re-sync
- [x] `!q` cancel token — abandon a write-up at any point without saving
- [x] 53 passing tests: database, search, security, CLI validation
- [x] Absolute path resolution — works regardless of working directory

### Next

- [ ] Claude API integration — strategy suggestions based on challenge description
- [ ] Auto-tagging — infer chapter and tags from description using Claude
- [ ] Solve history dashboard — page count per chapter, tag frequency, solve timeline

---

## Why I Built This

I compete in CTF events across binary exploitation, web, crypto, and forensics.
The problem I kept running into: every competition felt like starting from scratch,
even when I'd solved something similar before. Notes scattered across text files,
writeups buried in browser tabs, techniques half-remembered.

This project is my answer. It applies real software engineering — vector similarity
search, local embedding models, structured storage — to a problem I actually have.
Every design decision is documented in the CHANGELOG, which reads as a log of what
I thought through and why.

The notebook gets more useful the longer I use it. So does the code.

---

## License

MIT — use it, fork it, learn from it.
