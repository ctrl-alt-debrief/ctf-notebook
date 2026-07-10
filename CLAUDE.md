# CTF Solver – Project Context for Claude Code

## Who I Am
I'm a cybersecurity student building this project to learn hands-on security skills and
to have something real and practical to show on my resume. I'm comfortable with Python and
general programming, but I want to build a tool for CTFs Please explain your
reasoning as we go — I want to understand what we're doing, not just copy-paste solutions.

## What This Project Is
A personal command-line tool that helps me solve Capture The Flag (CTF) security challenges.
The big idea: every time we solve a challenge together, the tool learns from it. Over time it
builds up a notebook of techniques — organized into chapters by CTF domain — so that future
similar challenges go faster.

**The metaphor is a notebook. Use it everywhere.**
- Categories/domains → **Chapters**
- Entries/records → **Pages**
- The database → **The Notebook**
- Searching → **Flipping to**
- The database is empty → **Blank notebook**
- Adding a solve → **Writing a new page**
- The AI reasoning layer → **The smart index**

This isn't just a style preference — the notebook metaphor should appear in CLI output,
variable names, function names, comments, and the README. It makes the project memorable
and self-explanatory to anyone who reads the code or sees the repo.

---

## Naming Rules — Keep It Simple and Consistent

This is a resume project. Names should be readable by anyone, including non-security people
who might look at the repo. The **notebook metaphor** is the guiding theme — use it in
names, CLI output, comments, and the README.

| Instead of...         | Use...                    |
|-----------------------|---------------------------|
| `KnowledgeBaseEntry`  | `SolvePage`               |
| `Category`            | `Chapter`                 |
| `Database`            | `Notebook`                |
| `EmbeddingVector`     | `SearchFingerprint`       |
| `RAGPipeline`         | `SmartIndex`              |
| `CorpusIngestion`     | `WriteNewPage`            |
| `SemanticRetrieval`   | `FlipTo`                  |
| `TechniqueRepository` | `Notebook`                |
| `ExploitPayload`      | `WorkingSolution`         |
| `PostMortemExtract`   | `LessonsLearned`          |
| `empty database`      | `blank notebook`          |
| `search results`      | `relevant pages`          |

When in doubt: name things what they *do*, and use the notebook metaphor if it fits.

---

## Project Structure (Plain English)

```
ctf-solver/
│
├── CLAUDE.md                  ← you are here
├── README.md                  ← project overview for GitHub / resume
│
├── main.py                    ← entry point, run this to start a session
│
├── playbook/                  ← the "brain" — stores everything we've learned
│   ├── database.py            ← reads/writes to the local database file
│   ├── search.py              ← finds past solves relevant to current challenge
│   └── solves.db              ← the actual database file (SQLite)
│
├── solver/                    ← the active problem-solving session logic
│   ├── session.py             ← manages one CTF challenge from start to finish
│   ├── hints.py               ← pulls relevant hints from the playbook before we start
│   └── lessons.py             ← after solving, extracts what we learned and saves it
│
├── tools/                     ← wrappers around common CTF tools
│   ├── run_command.py         ← safely runs shell commands (gdb, binwalk, etc.)
│   └── common_checks.py       ← quick reusable checks (file type, strings, entropy...)
│
└── tests/                     ← basic tests so the project doesn't break as it grows
    └── test_playbook.py
```

---

## The Notebook — Chapters and Pages

The notebook is organized into **Chapters** — one per CTF domain. Every solved challenge
becomes a **Page** in the appropriate chapter.

### Chapters (CTF Domains)

| Chapter ID | Chapter Name | What It Covers |
|---|---|---|
| `general` | General Skills | Command line, encodings, file formats, basic scripting |
| `web` | Web Exploitation | SQL injection, XSS, SSRF, auth bypasses, cookies |
| `crypto` | Cryptography | RSA, AES, hashing, padding oracles, classical ciphers |
| `binary` | Binary Exploitation | Buffer overflows, ROP chains, heap exploitation, shellcode |
| `forensics` | Forensics | File carving, steganography, memory dumps, packet analysis |
| `reversing` | Reverse Engineering | Disassembly, decompilation, anti-debug, unpacking |
| `misc` | Miscellaneous | Anything that doesn't fit above |

New chapters can be added as new domains appear — the notebook grows with the competition.

### What a Page Looks Like

Each Page (`SolvePage`) stored in the notebook has these fields:

```
SolvePage
─────────────────────────────────────────
id                  auto-assigned number
challenge_name      e.g. "baby_pwn_2024"
chapter             one of the Chapter IDs above
tags                comma-separated: "heap, use-after-free, tcache"
difficulty          easy / medium / hard
what_we_tried       free text — approaches that didn't work and why
what_worked         free text — the actual solution / technique
key_insight         one sentence: the "aha" moment
tools_used          comma-separated: "pwntools, gdb-peda, ropper"
working_solution    the exploit script or payload that got the flag
date_solved         auto-filled timestamp
search_fingerprint  a vector (list of numbers) for similarity search
```

**Writing good pages matters.** The quality of future hints depends on how well pages are
written. Write `key_insight` as a complete sentence that makes sense without any other
context. Write `what_worked` to include *why* it worked, not just what commands you ran.
Tags should be consistent — decide on a format and stick to it (e.g. always `use-after-free`
not `uaf` or `UAF`).

---

## How a Session Works (Step by Step)

1. **Start** — I describe the challenge (category, what I see, any files)
2. **Hint Finder runs** — searches the playbook for similar past solves and surfaces relevant techniques
3. **We solve it together** — Claude Code helps me run tools, write scripts, iterate
4. **Lessons Learned** — after the flag, Claude helps me fill in the `PastSolve` entry
5. **Save to Playbook** — entry is stored so future sessions can learn from it

---

## Tech Stack (and Why)

| Tool | Why We're Using It |
|---|---|
| Python | Standard for CTF scripting; pwntools lives here |
| SQLite | Simple local database, no server needed, easy to inspect |
| ChromaDB | Local vector search — lets us find "similar challenges" even if tags don't match |
| pwntools | The standard CTF exploit library |
| Rich | Makes terminal output readable and clean |
| Claude API | Powers the AI reasoning and embeddings |

---

## Coding Style Guidelines

- **Comments over cleverness** — if it's not obvious, explain it in a comment
- **Short functions** — each function should do one thing with a clear name
- **No magic numbers** — name your constants
- **Print progress** — the tool should narrate what it's doing in plain English as it runs
- **Fail loudly** — if something breaks, say what broke and why, don't silently fail

---

## Documentation Rules — Do This Every Session

This is a portfolio project. Documentation is not optional. At the end of every working session
or whenever something meaningful is added, changed, or fixed — **Claude Code must prompt me to
update the following before we close out.**

### CHANGELOG.md — Update When:
- A new feature is working (even partially)
- A bug is fixed
- A dependency is added or changed
- The database schema changes
- The session flow changes in any way

**Format to follow:**
```
## [version or date] — YYYY-MM-DD

### Added
- Short plain-English description of what's new

### Changed
- What was modified and why

### Fixed
- What broke and how it was resolved

### Tests
- What test was added or updated to cover this
```

Start at version `0.1.0` and increment the middle number (`0.2.0`, `0.3.0`...) for each
meaningful feature. Only hit `1.0.0` when the MVP checklist is fully complete.

---

### README.md — Update When:
- The setup/install steps change
- A new feature is added that a user would need to know about
- The project structure changes
- A new screenshot or demo is available

The README is the first thing a recruiter or interviewer sees. Keep it accurate.

---

### Tests — Add or Update When:
- A new function is added to `playbook/` or `solver/`
- A bug is fixed (write a test that would have caught it)
- The database schema changes

Even one simple test per feature is enough. Tests live in `tests/` and should be runnable
with `pytest` from the project root.

**Claude Code reminder:** At the end of any session where code changed, say:
> "Before we close out — do you want to update the CHANGELOG and check if any tests need adding?"

---

## Resume / GitHub Presentation Notes

- The README should explain the project to someone who has never done a CTF
- Include a short demo GIF or screenshot in the README when the project is working
- Commit messages should be descriptive: `"Add similarity search to hint finder"` not `"fix stuff"`
- Keep the repo clean — no flags, no CTF challenge files committed (add to .gitignore)
- Every commit that touches a feature should also touch CHANGELOG.md

---

## What "Done" Looks Like (MVP)

- [ ] Can start a session and describe a challenge
- [ ] Hint finder surfaces relevant past solves (even on first run, gracefully handles empty playbook)
- [ ] After solving, lessons are saved to the playbook
- [ ] On the 2nd or 3rd similar challenge, relevant hints actually appear and are useful
- [ ] README explains what the project is and how to run it

Stretch goals (post-MVP):
- [ ] Auto-tag challenges using Claude instead of manual tags
- [ ] Web scrape CTF writeups to pre-seed the playbook
- [ ] Simple dashboard showing solve history and category breakdown
