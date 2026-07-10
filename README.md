# CTF Notebook

A command-line notebook for solving Capture The Flag (CTF) security challenges —
organized by domain, and gets smarter every time you use it.

> Built as a portfolio project to apply hands-on security skills and demonstrate
> real-world software and AI engineering practices.

---

## What Is This?

CTF (Capture The Flag) competitions are cybersecurity challenges where you find hidden
"flags" by exploiting vulnerabilities, reversing programs, breaking encryption, analyzing
network traffic, and more. They're how most security engineers sharpen their skills.

This tool is a **personal notebook** for those challenges. Every time you solve one,
the key technique and insight get written into the notebook as a new page. The next time
a similar challenge appears, the notebook surfaces what worked before — organized by
chapter, searchable by meaning — so solutions get faster and smarter over time.

```
Describe a challenge
        ↓
Notebook flips to relevant past pages
        ↓
Solve it
        ↓
Write what you learned into a new page
        ↓
Repeat — the notebook grows
```

---

## The Notebook is Organized into Chapters

Each chapter covers a domain of CTF challenges:

| Chapter | What It Covers |
|---|---|
| `general` | Command line, encodings, file formats, basic scripting |
| `web` | SQL injection, XSS, SSRF, auth bypasses, cookies |
| `crypto` | RSA, AES, hashing, padding oracles, classical ciphers |
| `binary` | Buffer overflows, ROP chains, heap exploitation, shellcode |
| `forensics` | File carving, steganography, memory dumps, packet analysis |
| `reversing` | Disassembly, decompilation, anti-debug, unpacking |
| `misc` | Anything that doesn't fit above |

---

## Features

- **Chapters** — every solve is saved as a page in the right chapter, tagged with the technique used
- **Flip-to** — before starting a new challenge, the notebook finds the most relevant past pages using vector similarity search
- **Smart index** — runs 100% locally using `all-MiniLM-L6-v2` (no API key, no internet needed during a live CTF)
- **Interactive lessons** — after solving, a guided prompt walks you through writing a high-quality page
- **Compounds over time** — the more challenges you solve, the more useful the hints become

---

## Tech Stack

| Tool | Role |
|---|---|
| Python | Core language — standard for CTF scripting |
| SQLite | Local notebook storage — no server needed, inspectable with any SQL tool |
| ChromaDB | Vector similarity search — finds related pages even without exact tag matches |
| Rich | Clean, readable terminal output with panels and spinners |
| sentence-transformers | Local embedding model — converts challenge descriptions to vectors |

---

## How a Session Works

1. **Start** — `python main.py` (optionally pass `--chapter binary` to scope hints)
2. **Describe** — type a plain-English description of the challenge (file type, symptoms, tools you see)
3. **Hints** — the notebook finds the most similar past pages and shows them as cards
4. **Solve** — go work the challenge; come back when you have the flag (or want to record progress)
5. **Write** — a guided prompt collects everything: what failed, what worked, the one-sentence insight, the final script
6. **Done** — the new page is saved and immediately indexed for future searches

---

## Project Structure

```
ctf-notebook/
│
├── main.py                  ← run this to open the notebook
│
├── notebook/                ← stores and searches everything we've learned
│   ├── database.py          ← reads and writes pages (SQLite layer)
│   ├── search.py            ← vector search — flips to relevant past pages
│   └── solves.db            ← the notebook file (created on first run)
│
├── solver/                  ← manages an active challenge session
│   ├── session.py           ← orchestrates one challenge start to finish
│   ├── hints.py             ← loads the index and renders hint cards
│   └── lessons.py           ← interactive page-writing after solving
│
├── tools/                   ← wrappers around common CTF tools (in progress)
│
└── tests/                   ← 35 tests covering the database and search layers
```

---

## Getting Started

### Prerequisites

- Python 3.10+
- No API key needed — the embedding model runs locally

### Install

```bash
git clone https://github.com/ctrl-alt-debrief/ctf-notebook.git
cd ctf-notebook
pip install -r requirements.txt
```

### Run

```bash
# Start a session (searches all chapters)
python main.py

# Scope hints to one chapter
python main.py --chapter binary

# Run the test suite
pytest tests/
```

The database and search index are created automatically on first run inside `notebook/`.

---

## Example Session

```
───────────────── CTF Notebook ─────────────────
  Your personal notebook for CTF solves.
  Describe the challenge below — relevant past solves will appear as hints.

──────────────── New Challenge ──────────────────
  Describe the challenge: 64-bit ELF, segfaults on long input, win() visible in Ghidra

✓ Smart index loaded — 4 pages indexed.

──────────────── Hint Finder ────────────────────
✓ Found 2 relevant pages.

╭────────────────────────────────────────────────╮
│ #1  baby_bof_2023  —  ✓ strong match  (0.41)   │
│                                                 │
│ Chapter     binary                              │
│ Difficulty  easy                                │
│ Tags        ret2win,no-canary,64-bit            │
│ Tools       pwntools,gdb-peda                   │
│                                                 │
│ Key Insight  Find offset with cyclic(), then    │
│              overwrite return address with win()│
│ What Worked  Checked ASLR with checksec first.  │
│              40-byte offset confirmed in gdb.   │
╰────────────────────────────────────────────────╯

──────────────── Solve Time ─────────────────────
  The notebook is open — go work the challenge.

  Did you get the flag? [Y/n]:
```

---

## Roadmap

### MVP — complete as of v0.5.1
- [x] Project structure and notebook schema
- [x] Chapter organization with all 7 domains
- [x] SQLite layer with full CRUD and validation
- [x] Vector similarity search with ChromaDB (local, no API key)
- [x] Session flow: describe → hint cards → solve pause → write page
- [x] Interactive lessons with preview before saving
- [x] 35 passing tests across the database and search layers

### Next — AI integration
- [ ] Claude API integration for strategy suggestions (what to try first, likely vuln class)
- [ ] Auto-tag new challenges by chapter using Claude instead of manual selection

### Stretch goals
- [ ] Solve history view — page count per chapter, tag frequency breakdown
- [ ] Pre-seed notebook from public CTF writeups
- [ ] Export notebook to readable Markdown or PDF

---

## Why I Built This

I'm a cybersecurity student competing in CTF events across multiple domains — web,
binary, crypto, forensics, and more. The problem I kept running into: every competition
felt like starting from scratch, even when I'd solved similar challenges before.

This project is my answer to that. It applies real software and AI engineering concepts —
vector similarity search, local embedding models, structured knowledge bases — to a problem
that's genuinely useful to me. The more I compete, the smarter it gets.

It also doubles as a living portfolio piece: the code, the commit history, and the notebook
itself all tell the story of what I've learned.

---

## License

MIT — use it, fork it, learn from it.
