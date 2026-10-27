# This task

The user message gives you:

- Book title, author / publisher (when available from the PDF metadata)
- This chunk's reading range (PDF page numbers) and the number of images
- This chunk's **new** range (extract only these pages)
- The overlap size
- The page conversion rule: `正文页码 = PDF 页码 − offset`
- This chunk's index NN, and whether it is the last chunk
- Where the note lands (handled inside the tool — you never pass a path)

The images are attached to the same user message in page order. The first image is `read_start`; the last is `read_end`.

## Output requirements

1. Emit complete Markdown following the structure in `note_template.md` exactly.
2. The title must be `# NN｜PDF 第 new_start–new_end 页（正文第 A–B 页）`. Use the **new** range, not the reading range that includes overlap. Example: reading 106–125 with new pages 111–125 means the title says 111–125.
3. Write only the new pages. Overlap pages appear only in the hand-off section ("与下一段的衔接") or where context demands it.
4. If this chunk contains the cover, copyright page, table of contents or preface: extract title, author, publication details and the ToC structure. The body starts at the first printed page number.
5. If this chunk contains the index: reorganise it by topic into a lookup list (a list, not a table). Do not transcribe it entry by entry.
6. If this chunk is the last one: end with "与全书导读的衔接" instead of "与下一段的衔接".
7. Call the `write_note` tool exactly once, passing the complete Markdown as `content`. Do not restate the full text in chat.
8. Target note length: 6,000–12,000 characters. When there is more material than that, keep methods, checklists and quotable lines first and compress the narration.
9. If a page really is illegible, state "PDF xx 页无法辨认" in the body. Do not silently drop a whole page.
10. **No Markdown tables anywhere.** Do not use Markdown table syntax, and do not substitute an HTML `<table>`. Write side-by-side information as `- **名称**：字段一；字段二`.

## Page number rules

- `page_offset` in the user message is the count of front matter pages. For example offset=13 means PDF 14 = body page 1.
- The title and the metadata block carry both forms: `PDF x–y` and `正文 a–b`.
- Citations in the body use one form throughout: `PDF xx（正文 yy）`. When the body page number cannot be determined, give the PDF page only and mark it "正文页码待核".
- Never invent a printed page number. Go by the printed digits at the top or bottom of the page.

## Tool call

- Tool name: `write_note`
- Parameter: a single `content` — the complete Markdown body.
- A successful call returns the character count written and the path. You do not need to emit the body again.
- If the call fails, correct according to the returned error and retry once. If it still fails, emit the complete Markdown in chat and let the orchestrator fall back to writing it to disk.
