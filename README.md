# PDF_page_reader_iaf

Turn a whole book — EPUB or PDF — into structured Markdown reading notes, by actually
looking at every page.

The pipeline rasterizes the book one page at a time, sends the pages to a vision
model in overlapping 20-page windows, and has the model write a note per window.
Once every window is done, a second stage reads all the notes back and writes a
book guide and a standalone condensed edition. The final deliverable is a merged
Markdown document in which every claim carries the page it came from, so you can
always go back to the source and check it.

Built on the IAF shell convention: `chain.py` is the engine entry point,
`IAF_AI/dispatch/*` holds the agents, and `prompt_base/` holds the authoritative
prompts. Only one script is meant to be run by hand: `run_books.py`.

## Why page images rather than extracted text

Text extraction loses the thing the notes are built on — the printed page number.
It also loses tables, figure captions and the layout cues that tell you where a
chapter starts. Sending the rendered page keeps all of it, and lets the prompt
insist that every citation comes from a number actually printed on the page
rather than one the model inferred.

## Pipeline

```
books/inbox/*.epub ──epub_to_pdf.py──> same-name .pdf
books/inbox/*.pdf  ──pdf_to_png.py──> output/{book}/png/ + manifest.json
                                        │
                                        └─make_chunks.py─> chunks.json  (window 20 / step 15 / overlap 5)
                                                             │
                              read_page dispatch (agent core) ┘   20 PNGs per call
                                        │
                                        └──> output/{book}/notes/NN_pages_XXX-YYY.md
                                                             │
                   whole_book_report dispatch ───────────────┤
                     agent guide  ──> 00_全书导读.md          │
                     agent digest ──> {book}_浓缩版.md        │
                                                             │
                              merge_notes.py ────────────────┴──> {book}.md
                                                                   │
                                                                   └──> deliverables/{book}/
```

Chunks overlap by five pages. The overlap exists so the model can understand
context and write the hand-off to the next chunk; those pages are not extracted
twice.

## Requirements

- Python 3.10+
- An API key for a provider whose model **can see images**
- `PyMuPDF` for rendering, plus the engine's own dependencies

```bash
cd IAF_AI
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install PyMuPDF
cd ..
```

`run_books.py` re-executes itself under `IAF_AI/.venv` when it finds one, so
after this you can call it with any `python3` and still get the right interpreter.

## Configure

`config_base/config.json` ships with placeholder keys. Put a real key for one
provider into it, then push it into the engine:

```bash
python sync_config.py
```

`config_base/` is the authoritative copy; `sync_config.py` pushes it to
`IAF_AI/config.json` and translates the prompt paths in each
`dispatch_config.json`. Edit `config_base/`, never the copy under `IAF_AI/`.

The key field is named `api_key` for some providers and `key` for others; the
engine accepts either. Which model each agent uses is set per agent in
`config_base/{dispatch}/dispatch_config.json`.

Both config files are tracked, so once you have put a real key in, keep it out of
commits:

```bash
git update-index --skip-worktree config_base/config.json IAF_AI/config.json
```

**The model must be vision-capable.** This is the one failure worth knowing about
in advance: if you point `read_page` at a text-only model, the server treats the
attached images as an unknown parameter and answers anyway. You get notes that
read perfectly well and describe a book nobody looked at. Verify with one cheap
call before starting a long run:

```bash
python chain.py --dispatch template --agent core --message "What number is printed at the bottom of this page?" --image /path/to/a/page.png
```

## Run

Drop books into `books/inbox/` and run:

```bash
python run_books.py
```

That is the whole normal workflow. Every EPUB in the inbox is reflowed into a
same-name PDF first, every PDF is then processed in turn, and finished documents
land in `deliverables/{book}/`. Books are processed serially because
`workspace/read_page/task.json` is shared.

Useful variants:

```bash
python run_books.py --dry-run                      # print the plan, call no model, write nothing
python run_books.py --book My_Book                 # just this one
python run_books.py --book My_Book --force         # redo it from scratch
python run_books.py --book My_Book --report-only   # notes are fine, redo guide + digest
python run_books.py --book My_Book --merge-only    # no model calls, just re-merge
python run_books.py --cleanup-only --dry-run       # show what intermediate data could be freed
```

Per-book metadata goes in a sidecar JSON next to the book — see
[`books/README.md`](books/README.md). Full flag reference and resume semantics
are in [`BOOK_PIPELINE.md`](BOOK_PIPELINE.md).

## What you get

```
deliverables/{book}/
├── {book}.md             # guide + every chunk note, merged, with a table of contents
├── {book}_浓缩版.md       # standalone condensed edition, readable on its own
├── 00_全书导读.md         # the guide as its own file
├── run_log.json          # per-chunk status, character counts, durations
└── 交付说明.md            # filenames, character counts, processing date
```

Intermediate data under `output/{book}/` is deleted automatically once a book is
delivered — pass `--keep-output` to keep it. Engine session history is cleared
too, because each chunk's history holds twenty base64-encoded page images and
that, not the notes, is what makes the directory large.

## Language of the generated notes

The prompts are written in English; the notes they produce are in Chinese, with
English quotations kept verbatim and translated underneath. That is deliberate —
the tool was built to read English-language books into Chinese notes.

To get English notes instead, change the "Output language" section at the end of
these two files and re-run `python sync_config.py`:

- `prompt_base/read_page/rules/persona.md`
- `prompt_base/whole_book_report/rules/persona.md`

The section headings inside `prompt_base/read_page/rules/note_template.md`,
`guide_task.md` and `digest_task.md` are the literal output format, so translate
those too if you want English headings. The three delivered filenames
(`00_全书导读.md`, `{book}_浓缩版.md`, `交付说明.md`) are enforced by path fences
in `run_books.py`, `write_book_guide_tools.py` and `write_book_digest_tools.py`;
change all of them together or the write tool will reject the path.

## Repository layout

- `run_books.py` — the only entry point: scans the inbox, runs each book end to end, delivers
- `chain.py` — IAF engine entry: loads a dispatch, builds the context, runs the tool loop
- `sync_config.py` — pushes `config_base/` and `prompt_base/` into `IAF_AI/`
- `book_pipeline/` — standalone scripts with no engine dependency (EPUB→PDF, PDF→PNG, chunking, merging, cleanup)
- `prompt_base/{dispatch}/rules/` — authoritative prompts
- `config_base/` — authoritative config
- `IAF_AI/` — the engine and the synced dispatch copies
- `books/` — the inbox
- `output/`, `workspace/`, `deliverables/` — created on first run

## Known limits

- **The report stage is one large-context call.** The fuse is
  `--report-max-chars` (default 600000); exceed it and the pipeline errors out
  rather than silently truncating. The model's real context window is still the
  hard ceiling above that. Two-stage chapter-level summarization is not
  implemented.
- **Context compaction is off.** `compaction.py` needs POSIX `fcntl`, and both
  dispatches set `compaction.enabled: false`. Reading a chunk is a single
  stateless call, so there is no history to compact.
- **Tool calls are not forced.** Some providers do not support
  `tool_choice: required`; the prompt, `exit_on_tools` and `max_tool_loops` are
  what make the model actually call the write tool. If it answers with text only,
  the tool loop retries.

## License

Apache License 2.0 — see [LICENSE.txt](LICENSE.txt).
