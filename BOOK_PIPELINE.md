# Whole-book pipeline: EPUB/PDF → chunk notes → guide + condensed + merged

The pipeline turns one book into four kinds of artifact:

0. an EPUB is reflowed into a PDF first (skipped when the inbox item is already a PDF);
1. one PNG per page;
2. a chunk note per 20 pages (sliding window 20/15/5 — only the 15 new pages are written up);
3. a book guide, synthesized by the model from all the chunk notes;
4. two final documents: the merged `{book}.md` and the standalone `{book}_浓缩版.md`.

The entry point is `run_books.py` at the shell root. It is the only entry point.
It uses two dispatches:

- `read_page` / agent `core` — reads 20 page PNGs per call, writes that chunk's note, via `write_note`
- `whole_book_report` / agent `guide` — reads all chunk notes, writes `00_全书导读.md`, via `write_book_guide`
- `whole_book_report` / agent `digest` — reads all chunk notes plus the guide, writes the condensed edition, via `write_book_digest`

"All notes into the model" is implemented by the directory entry
`workspace/whole_book_report/input_notes` in `whole_book_report`'s
`context_files`: before the run, `notes/NN_pages_*.md` are copied in, and the
engine expands the directory into its files at startup.

> After editing a prompt under `prompt_base/`, run `python sync_config.py`.
> The engine's cross-turn compaction loads `compact_v4.md` from
> `IAF_AI/dispatch/*/rules/`, which only exists because sync put it there.

---

## The inbox (the normal way to use this)

```bash
# put a PDF or an EPUB into books/inbox/, then:
python run_books.py
```

- Input: `books/inbox/*.pdf` and `books/inbox/*.epub`, each optionally paired with a same-name `.json` carrying title / author / page offset.
- **EPUB is converted first.** Before any work starts the inbox is scanned and every EPUB is reflowed in place into a same-name `.pdf`. On success the EPUB is deleted (`--keep-epub` keeps it). When a same-name PDF already exists, nothing is converted and nothing is deleted — that PDF may be a proper edition from elsewhere, so the choice is left to you.
- Intermediate data: `output/{book}/` (PNGs, chunk notes, chunks.json, run_log.json).
- Deliverables: `deliverables/{book}/` (merged, condensed, guide, delivery note).
- An already-delivered book is skipped by default. On success the inbox PDF and its sidecar are deleted; `--keep-pdf` keeps them, `--archive` moves them to `books/processed/`.
- **Intermediate data is cleaned automatically after a successful delivery**: `output/{book}/` is removed, `workspace/` is emptied except `workspace/current/STATUS.md`, and `IAF_AI/dispatch/*/sessions/` is cleared. `--keep-output` / `--keep-sessions` override this.
- `--force` redoes a book; `--deliver-only` re-copies deliverables without calling the model; `--cleanup-only` only reclaims intermediate data.
- Books are processed serially, to avoid two runs colliding over the shared `workspace/`.

See [`books/README.md`](books/README.md) for the sidecar format.

---

## Running a single book

Title, author and page offset come from the same-name `.json` in the inbox (see
`books/README.md`). `--book` narrows the round to one book. When the inbox no
longer holds that book — the source file is deleted after delivery — but
`output/{book}/` still exists, `--book` is automatically treated as a resume, and
you do not need to supply a path.

```bash
# 1. only this book from the inbox
python run_books.py --book My_Book

# 2. resume with existing PNGs / notes (anything already good enough is skipped)
python run_books.py --book My_Book --skip-png

# 3. redo just one missing chunk
python run_books.py --book My_Book --skip-png --from 6 --to 6

# 4. notes are complete — redo the guide and the condensed edition only
python run_books.py --book My_Book --report-only --force

# 5. no model calls, just re-merge
python run_books.py --book My_Book --merge-only

# 6. see the plan, write nothing
python run_books.py --book My_Book --skip-png --dry-run
```

`--report-only` and `--merge-only` act on one book, so they require `--book`.

The intermediate root is fixed at `output/` under the shell root: the path fences
in the three write tools are hard-coded to `output/{book}/`, so it is not
configurable.

---

## Artifact layout

```
output/{book}/
├── png/{book}_001.png ...          # one image per page
├── manifest.json                   # page count, DPI, PNG list
├── chunks.json                     # the chunk plan
├── notes/
│   ├── 00_全书导读.md              # written by agent guide
│   ├── 01_pages_001-020.md         # written by read_page
│   ├── 02_pages_016-035.md
│   └── ...
├── {book}.md                       # merged (guide + all notes)
├── {book}_浓缩版.md                # standalone condensed edition
└── run_log.json                    # per-chunk status, character count, duration
```

`run_books.py` copies the finished documents into the delivery directory
(`deliverables/` by default, `--deliver` to change it):

```
deliverables/{book}/
├── {book}.md             # merged
├── {book}_浓缩版.md       # standalone condensed edition
├── 00_全书导读.md         # the guide on its own
├── run_log.json           # run log, for traceability
└── 交付说明.md            # filenames, character counts, processing date
```

Transient state lives in `workspace/`:

```
workspace/read_page/task.json              # this chunk's book / note_path / page range
workspace/read_page/tool_calls_*.json      # tool call trace
workspace/whole_book_report/task.json      # stage=guide|digest + the three fixed paths
workspace/whole_book_report/input_notes/   # copies of all notes, for the report stage
```

> **Cleanup.** After each successful delivery `run_books.py` calls
> `book_pipeline/cleanup.py`: it removes `output/{book}/`, empties `workspace/`
> down to `workspace/current/STATUS.md`, and clears the session history under
> `IAF_AI/dispatch/*/sessions/`. That last one matters — each chunk's history
> holds twenty base64-encoded PNGs, and it is the real driver of directory size.
> Add `--keep-output` / `--keep-sessions` to preserve the scene, or run
> `python run_books.py --cleanup-only [--dry-run]` on its own.

---

## Chunking rule

Window 20, step 15, overlap 5 by default:

```
01 reads 001-020  new 001-020
02 reads 016-035  new 021-035
03 reads 031-050  new 036-050
...
11 reads 151-164  new 151-164
```

- The five overlapping pages are only for context and for writing the hand-off to the next chunk. They are **not** extracted twice.
- Each note's H1 carries both the PDF page numbers and the body page numbers.
- `--page-offset N` means `body page = PDF page − N`.
- The final chunk closes the book out instead of writing a hand-off.

---

## Flags

Paths and selection:

- `--inbox` (default `books/inbox/`) — where to look for input
- `--deliver` (default `deliverables/`) — where finished documents go; an absolute path is fine
- `--book` — process only this book name or filename; if the inbox has no match but `output/{book}/` exists, resume that one

Mode:

- `--dry-run` — print the plan; call no model, write no file
- `--force` — redo a finished book and overwrite its deliverables (re-runs every model call)
- `--deliver-only` — no model calls; just re-copy from `output/` to the delivery directory
- `--cleanup-only` — no model calls; only reclaim intermediate data
- `--skip-png` — reuse existing PNGs
- `--skip-report` — read pages only; no guide, no condensed edition
- `--skip-digest` — guide only
- `--report-only` — skip `read_page`, build the report from existing notes (needs `--book`)
- `--merge-only` — merge only, no model calls (needs `--book`)
- `--from N` / `--to N` — run only chunks N through N, 1-based and inclusive
- `--stop-on-error` — stop after a failed book instead of continuing to the next

Retention:

- `--keep-pdf` — keep the inbox PDF after success (mutually exclusive with `--archive`)
- `--keep-epub` — keep the inbox EPUB after a successful conversion
- `--archive` — move the PDF and its sidecar to `books/processed/` instead of deleting
- `--keep-output` — keep `output/{book}/` after delivery
- `--keep-sessions` — keep workspace and engine session traces

Rendering and chunking:

- `--dpi` (default 150) — PNG resolution
- `--window` (default 20) — pages read per chunk
- `--step` (default 15) — pages advanced per chunk; must be `<= window`
- `--page-offset` (default 0) — default page offset; a sidecar's `page_offset` wins
- `--epub-fontsize` (default 12.0) — EPUB reflow font size in pt; this is what decides how much text lands on a page

Thresholds:

- `--min-note-chars` (default 800) — a chunk note below this counts as failed
- `--max-note-chars` (default 12000) — target ceiling, written into the prompt; not a hard truncation
- `--min-guide-chars` (default 2000) — guide acceptance floor
- `--min-digest-chars` (default 8000) — condensed edition acceptance floor
- `--report-max-chars` (default 600000) — ceiling on total note characters fed to the report stage
- `--retries` (default 2) — retries per stage
- `--strict` — a failed condensed edition fails the book

---

## Resume and acceptance

- **Chunk notes**: skipped when the file exists and has at least `--min-note-chars` characters; otherwise re-run.
- **Guide / condensed edition**: skipped when the file exists and meets its floor.
- **`--force`**: nothing is skipped, but the target file must have been rewritten after this attempt started (an mtime check), so a stale file cannot pass itself off as success.
- **Retries**: each attempt clears the previous half-written artifact. Only after the last attempt still falls short is the chunk recorded as `failed`.
- **Report stage**: if the guide fails, the condensed edition is not attempted; existing notes are still merged and the exit code is 1. A failed condensed edition does not block by default — pass `--strict` to make it fail the book.

Every run updates `output/{book}/run_log.json` with each chunk's `status`,
`chars`, `duration_ms` and error text, plus the results for guide, condensed
edition and merged document.

---

## Path fences

None of the three write tools accepts a `path` argument. The destination comes
from `task.json`:

- `write_note` → `output/{book}/notes/NN_pages_XXX-YYY.md`
- `write_book_guide` → `output/{book}/notes/00_全书导读.md`
- `write_book_digest` → `output/{book}/{book}_浓缩版.md`

A tool rejects absolute paths, `..`, a wrong filename, and anything resolving
outside its fence. Writes go through a temporary file in the same directory plus
`os.replace`, UTF-8, with a trailing newline added.

`write_book_guide` and `write_book_digest` additionally refuse to run when
`workspace/whole_book_report/input_notes/` holds no `NN_pages_*.md`, so the model
cannot invent a guide from an empty context.

---

## Reference run

*Interviewing for Radio* (Jim Beaman, Routledge 2011), 164-page PDF, page offset 13.
150 DPI, window 20 / step 15 / overlap 5, `--report-max-chars 220000`.

- PDF → PNG: 164 pages, first render
- Chunk notes 01–11: 11/11 ok, 147,577 characters, about 11.5 minutes
- Book guide: ok, 9,434 characters, 47.7s
- Condensed edition: ok on the second attempt, 24,213 characters, 94.2s
- Merged document: ok, 157,946 characters, immediate

Per-chunk character counts: 17,017 / 12,164 / 11,566 / 15,454 / 14,551 / 13,420 /
14,630 / 13,646 / 12,716 / 11,041 / 11,372.

Chunk 06 wrote nothing on its first attempt and succeeded on retry; the condensed
edition's first attempt stopped at `finish_reason=length` and succeeded on the
second. About 17 minutes end to end. Useful as an order-of-magnitude expectation:
roughly a minute per chunk note, and a book of this size is a sub-half-hour job.
