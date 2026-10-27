# book_pipeline — standalone scripts: whole-book EPUB/PDF → Markdown

None of these scripts depends on the IAF engine, and each runs on its own.
`run_books.py` is just the thing that strings them together with the two
dispatches.

```
EPUB ─epub_to_pdf.py─> PDF
                         │
PDF ──pdf_to_png.py──> png/ + manifest.json
                         │
                         └──make_chunks.py──> chunks.json  (20/15/5 chunking)
                                                │
                          read_page dispatch ───┘
                                 │
                                 └── notes/NN_pages_XXX-YYY.md
                                                │
                         merge_notes.py ────────┴──> {book}.md
```

## 1. epub_to_pdf.py

Reflows an EPUB into a PDF. An EPUB is a reflowable format with no inherent
notion of a page — pages only come into existence when it is laid out — so the
**layout parameters decide how much text lands on a page**, and therefore how
much content the downstream "20 pages per chunk" actually takes in. The same book
laid out at A4/11pt is 115 pages; at the default 396x612pt/12pt it is 241 pages,
about 2300 characters per page, the same order of magnitude as a printed book.

Page numbers are stamped into the footer. The `read_page` prompt requires that a
page number come "from the page itself", and a reflowed page carries no printed
digits at all; without the stamp every citation in the book degrades to
"正文页码待核". With it, the PDF page number and the number on the page agree
one-for-one, and `page_offset` of 0 is correct.

```bash
python book_pipeline/epub_to_pdf.py book.epub
python book_pipeline/epub_to_pdf.py book.epub -o book.pdf --fontsize 11
# output: a .pdf with the same name as the EPUB, carrying the EPUB's title and author metadata
```

Options: `--width` / `--height` (page size in pt), `--fontsize` (body size in pt),
`--no-page-numbers` (do not stamp the footer).

The write is atomic: a temporary file in the same directory, then a replace. A
failure partway through cannot leave half a PDF behind for the next round to
mistake for a finished conversion.

## 2. pdf_to_png.py

Renders a PDF one page at a time to PNG and writes `manifest.json`. A page that
is already rendered at the right size is skipped unless `--force` is given.

```bash
python book_pipeline/pdf_to_png.py book.pdf \
  --output output --name BookName --dpi 150
# output: output/BookName/png/BookName_001.png ... BookName_164.png
#         output/BookName/manifest.json
```

Options:

- `--output` / `-o` (default `output`) — output root
- `--name` (default: the PDF filename) — book and directory name; letters, digits, underscore, hyphen and CJK only
- `--dpi` (default 150) — render resolution; 150 is enough for 20 pages per request
- `--force` — re-render pages that already exist

## 3. make_chunks.py

Slices the page range into a sliding window: 20 pages per window, advancing 15,
overlapping 5.

```
01: reads 1-20    new 1-20
02: reads 16-35   new 21-35
03: reads 31-50   new 36-50
...
11: reads 151-164 new 151-164
```

The overlapping pages are only for understanding context and writing the hand-off
to the next chunk; they are not extracted twice.

```bash
python book_pipeline/make_chunks.py 164 --window 20 --step 15 --book BookName \
  --out output/BookName/chunks.json
```

Or from code:

```python
from book_pipeline.make_chunks import build_chunks
chunks = build_chunks(pages=164, window=20, step=15, book="BookName")
```

Constraint: `step <= window`, otherwise pages would be missed — it raises
`ValueError` instead.

## 4. merge_notes.py

Merges `notes/*.md` in filename order, optionally placing the book guide first.
A table of contents and the anchors are generated automatically.

```bash
python book_pipeline/merge_notes.py output/BookName/notes \
  --out output/BookName/BookName.md \
  --title "BookName" \
  --intro output/BookName/notes/00_全书导读.md
```

From code:

```python
from book_pipeline.merge_notes import merge
merge("output/BookName/notes", "output/BookName/BookName.md",
      title="BookName", intro="output/BookName/notes/00_全书导读.md")
```

## 5. cleanup.py

Reclaims intermediate data after a book is delivered, so PNGs and base64 image
history do not inflate the project. `run_books.py` calls it automatically; it can
also be imported directly:

```python
from book_pipeline.cleanup import cleanup_after_book
cleanup_after_book("BookName", deliver_root=Path("deliverables"))
```

What it covers:

- `output/{book}/` — only when `deliverables/{book}/{book}.md` already exists;
- everything under `workspace/` except `current/STATUS.md`;
- `IAF_AI/dispatch/*/sessions/` and `staging/` — engine session history, where a single chunk holds twenty base64 PNGs.

`cleanup_workspace()`, `cleanup_engine_sessions()` and `cleanup_output()` all
accept `dry_run=True` to count without deleting.

## Page number convention

`--page-offset` in `run_books.py` (or `page_offset` in a sidecar) means:

```
body page = PDF page - page_offset
```

For a 164-page sample book with `--page-offset 13`, PDF 14 is body page 1. Front
matter numbered in Roman numerals is labelled by the model from the layout rather
than through this formula. Each note's H1 carries both the PDF page and the body
page, so a claim can be traced back either way.
