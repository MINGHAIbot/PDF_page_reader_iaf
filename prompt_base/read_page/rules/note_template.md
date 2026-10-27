# Chunk note template

The output must follow the structure below exactly. Replace the braced placeholders with this chunk's real values; do not leave the braces in.

```markdown
# {NN}｜PDF 第 {new_start}–{new_end} 页（正文第 {A}–{B} 页）

> 书名：{书名}
> 作者：{作者}
> 出版：{出版信息}
> 阅读范围：PDF {read_start}–{read_end} 页；本份笔记覆盖新增的 {new_start}–{new_end} 页（前 {overlap} 页仅用于衔接）
> 阅读方式：逐页 PNG

## 本段速览

- 3–5 条，概括本段主线
- 每条一句话，不做细节展开

## 一、{主题一}

### 1. {小节}

- 要点 + 页码引用
- 方法、步骤、案例、注意事项

## 二、{主题二}

...

## 关键概念

- **{概念}**：{一句话解释}（PDF xx，正文 yy）

## 可直接使用的方法与清单

1. ...
2. ...

## 金句摘录

> "English quote."（PDF xx，正文 yy）
> 中文翻译。

## 与下一段的衔接

- 本段停在哪里，下一段从哪开始；如果本段是最后一段，改为「与全书导读的衔接」。
```

## Structure requirements

- **No Markdown tables anywhere.** Do not use Markdown table syntax, and do not substitute an HTML `<table>`. Concepts, comparisons and lookup information all become lists, one item per line: `- **名称**：字段一；字段二`.
- The H1 must use the format `# {NN}｜PDF 第 {new_start}–{new_end} 页（正文第 {A}–{B} 页）` verbatim, where `{NN}` is a two-digit index and `{new_start}–{new_end}` is the **new** range, not the reading range that includes overlap.
- The metadata block must keep all five fields: 书名, 作者, 出版, 阅读范围, 阅读方式.
- Name the `## 一、`, `## 二、` topic headings after the actual content. Their number follows the content; do not pad to hit a count.
- 「关键概念」must be a list with at least one entry, one concept per entry.
- 「可直接使用的方法与清单」must be a numbered list.
- 「金句摘录」needs at least one entry: the English source sentence plus a Chinese translation.
- In the last chunk, rename the final section to `## 与全书导读的衔接` and use it to explain how this chunk returns to the book's through-line.
- Do not open or close the note with filler such as "以下是笔记" or "希望对你有帮助".
