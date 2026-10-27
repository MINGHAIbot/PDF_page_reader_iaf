# Task: write the condensed edition (《全书浓缩版》)

Your context holds every chunk note for this book. The user message may also carry the already-generated 《全书导读》 — you may build on it, but do not copy its section structure. Write a 20,000–25,000 character condensed edition **in Chinese**, using the section structure below verbatim — the headings are the output format, so keep them exactly as written.

## 一、全书一句话

## 二、这本书解决什么问题

## 三、章节地图

- **第 1 章 · {章名}**：{主题}；核心问题：{...}；关键方法：{...}（PDF xx，正文 yy）
- **第 2 章 · {章名}**：...

## 四、逐章核心内容

### 第 1 章：{章名}

- Core argument
- Key methods / cases
- Lines worth remembering

### 第 2 章：{章名}

- ...

(Cover every chapter. Do not skip any.)

## 五、贯穿全书的原则

## 六、全流程操作清单

## 七、不同对象 / 节目形态速查清单

- **{对象 / 形态}**：关键策略 —— {...}；主要风险 —— {...}

## 八、伦理与法规红线

## 九、金句摘录

## 十、如何使用这份浓缩版

## Requirements

1. **No Markdown tables anywhere.** Do not use Markdown table syntax, and do not substitute an HTML `<table>`. Side-by-side information always becomes a list, one item per line: `- **名称**：字段一；字段二；字段三`.
2. This is a **standalone** account of the book: someone who has read neither the original nor the chunk notes should finish it holding the main content.
3. The per-chapter section must cover every chapter, not just the first few. Give each chapter at least 1,500 characters.
4. Page citations come from the notes, in the form `PDF xx（正文 yy）`.
5. Methods that can be followed directly become numbered steps; put concept glosses in parentheses.
6. Call the `write_book_digest` tool exactly once, passing the complete Markdown as `content`.
7. Do not emit the full text in chat.
