# Task: write the book guide (《全书导读》)

Your context holds every chunk note for this book (filenames start with `NN_pages_`). Write a 6,000–10,000 character guide **in Chinese**, using the section structure below verbatim — the headings are the output format, so keep them exactly as written.

## 一、这本书在讲什么

- The book's subject, the author's background, why it was written, who it suits.
- 3–5 paragraphs. Do not turn it into a restatement of the table of contents.

## 二、章节地图

- **第 1 章 · {章名}**：{主题}；核心问题：{...}（PDF xx，正文 yy）
- **第 2 章 · {章名}**：...

## 三、贯穿全书的 N 条原则

- Distil 5–7 principles from the whole set of notes. Each one needs an explanation and a page citation.
- The principles must relate to each other logically; this is not a grab-bag list.

## 四、从准备到产出的全流程清单

### 阶段一：开始前

### 阶段二：进行中

### 阶段三：结束后

## 五、不同对象 / 节目形态速查清单

- **{对象 / 形态}**：关键策略 —— {...}；主要风险 —— {...}

## 六、伦理与法规红线

- Organise by topic, not by chapter.
- Give a page citation for each entry.

## 七、如何使用这份笔记

- How to read it the first time, how to look up a method, how to use it when preparing, how to use it in review.

## 八、一句话总结

## Requirements

1. **No Markdown tables anywhere.** Do not use Markdown table syntax, and do not substitute an HTML `<table>`. Side-by-side information always becomes a list, one item per line: `- **名称**：字段一；字段二；字段三`.
2. The guide synthesises only. It does not restate the notes chunk by chunk — the detail belongs to the chunk notes that follow it.
3. Every page number in the chapter map must be checkable against the notes.
4. The lookup list must cover the main subjects / formats that appear in the notes. Do not stop at three.
5. Call the `write_book_guide` tool exactly once, passing the complete Markdown as `content`.
6. Do not emit the full text in chat.
