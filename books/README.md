# books/ — the inbox

## What you do

1. Put a PDF or an EPUB into **`books/inbox/`**.
2. From the shell root, run:

```bash
python run_books.py
```

3. Finished documents appear in **`deliverables/{book}/`**.
4. On success the inbox PDF and its same-name `.json` are deleted automatically.

You do not convert formats, rasterize pages, edit config or choose chunk
boundaries yourself. The script processes every book in the inbox, one after
another.

## EPUB

EPUBs go straight into the inbox alongside PDFs. Before any work starts the
script scans the inbox and reflows each EPUB in place into a same-name `.pdf`;
**on a successful conversion the EPUB is deleted** (`--keep-epub` keeps it), and
from there the pipeline only deals with PDFs. If a same-name PDF is already
sitting there, nothing is converted and nothing is deleted — that PDF may be a
proper edition from somewhere else, so you decide which one to keep.

An EPUB has no pages; pages only come into being when it is laid out, which means
the font size decides how much text ends up on each one. The default is
396x612pt (a 5.5x8.5 inch paperback trim) at 12pt, giving roughly 2300 characters
per page — the same order of magnitude as a printed book. For a looser layout
pass `--epub-fontsize 13`, or put `"epub_fontsize": 13` in the sidecar.

A reflowed page carries no printed page number of its own, so the PDF page number
is stamped into the footer. The model is instructed to trust only numbers that
appear on the page; without the stamp every citation would degrade to
"正文页码待核". For books that came in as EPUB, leave `page_offset` at 0.

## Optional: title, author, page offset

Put a **same-name** `.json` next to the book — `books/inbox/MyBook.pdf` pairs with
`books/inbox/MyBook.json`:

```json
{
  "book": "My_Book",
  "title": "My Book",
  "author": "Author Name",
  "publisher": "Publisher, 2024",
  "page_offset": 13
}
```

- `book` — directory name, PNG prefix, final filenames. Defaults to the PDF filename.
- `title` — the document H1 and the title given to the model. Defaults to the PDF filename.
- `author` — note metadata. Empty if omitted.
- `publisher` — note metadata. Empty if omitted.
- `page_offset` — `body page = PDF page − page_offset`. Defaults to 0.

Leave `page_offset` out when you are unsure; the model will label front matter
from the layout instead. You can also set `"dpi"`, `"window"`, `"step"` and
`"report_max_chars"` to override the defaults (`report_max_chars` defaults to
600000). For an EPUB, `"epub_fontsize"` is honoured too (reflow font size,
default 12).

Sidecars pair by **filename**, and an EPUB and the PDF it converts into share a
name — so one `.json` serves both.

## Directory convention

```
books/
├── inbox/          ← put a PDF or an EPUB here
├── processed/      ← with --archive, finished PDFs are moved here
└── README.md

output/{book}/       ← intermediate: PNGs, chunk notes, chunks.json, run_log.json
deliverables/{book}/ ← finished: merged, condensed, guide, delivery note
```

`output/` is the pipeline's workspace — do not edit it by hand. `deliverables/`
is what you take away. After a book is delivered, `output/{book}/` is removed
automatically, `workspace/` is reduced to `current/STATUS.md`, and the engine's
session history is cleared. Nothing in `deliverables/` is affected.

## Common commands

```bash
# process every book in the inbox (EPUBs are converted to PDF first)
python run_books.py

# see the plan: no model calls, no files written
python run_books.py --dry-run

# just one book (by book name or by PDF filename)
python run_books.py --book My_Book

# deliver somewhere else
python run_books.py --deliver /path/to/delivery

# no model calls; just re-copy finished documents from output/ to deliverables/
python run_books.py --deliver-only
python run_books.py --deliver-only --book My_Book

# redo a book (re-reads every page, re-writes guide and condensed edition)
python run_books.py --book My_Book --force

# keep the inbox PDF afterwards (it is deleted by default)
python run_books.py --keep-pdf

# keep the inbox EPUB after conversion (it is deleted by default)
python run_books.py --keep-epub

# move the PDF to books/processed/ instead of deleting it
python run_books.py --archive

# reclaim intermediate data only, no model calls (dry-run first to see the size)
python run_books.py --cleanup-only --dry-run
python run_books.py --cleanup-only
```

## Behaviour

- **An already-delivered book is skipped.** If `deliverables/{book}/{book}.md` exists the book is not re-run, and the matching inbox PDF is cleaned up on the way past.
- **EPUB is converted first.** On success the EPUB is deleted (`--keep-epub` keeps it). On a failed conversion the original is left alone and counts against this round's failures.
- **The inbox is cleaned on success.** The PDF and its same-name `.json` are deleted by default; `--keep-pdf` keeps them, `--archive` moves them to `books/processed/`. A failed book is left untouched so you can re-run it.
- **Intermediate data is cleaned after delivery.** `output/{book}/` is removed, `workspace/` is reduced to `current/STATUS.md`, and the base64 image history under `IAF_AI/dispatch/*/sessions/` is cleared. `--keep-output` / `--keep-sessions` override this; a failed cleanup never affects what was already delivered.
- **Serial processing.** Two books cannot run at once, because `workspace/read_page/task.json` is shared.
- **Keep going on failure.** A failed book does not stop the round; `--stop-on-error` makes it stop immediately.
- **Resume.** Notes written by a failed book are kept, so re-running the same command skips what is already done. After delivery the inbox source is gone, and at that point `--book <name>` automatically resumes against `output/{book}/` instead (`--report-only`, `--merge-only` and `--skip-png --from N --to N` all take this path).
- **Guide only.** Pass `--skip-digest`.
- **A failed condensed edition** still counts as done by default, since the merged document exists. `--strict` makes the exit code non-zero.
