#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把分段笔记合并成一份完整阅读文件。

用法:
    python merge_notes.py output/书名/notes --out output/书名/书名.md
    python merge_notes.py notes --out final.md --intro 00_全书导读.md
"""
import argparse
import re
from datetime import date
from pathlib import Path


def merge(notes_dir, out, title=None, intro=None) -> Path:
    """合并 notes_dir 下的 Markdown，可选把 intro 放在最前。

    Args:
        notes_dir: 笔记目录（按文件名排序）
        out:       最终 Markdown 路径
        title:     书名（默认取 notes_dir 的父目录名）
        intro:     导读文件路径（可选；自动从排序列表中去重并置顶）

    Returns:
        最终文件 Path
    """
    notes_dir = Path(notes_dir).expanduser().resolve()
    if not notes_dir.is_dir():
        raise FileNotFoundError(f"笔记目录不存在: {notes_dir}")

    files = sorted(notes_dir.glob("*.md"))
    intro_path = Path(intro).expanduser().resolve() if intro else None
    if intro_path:
        if not intro_path.is_file():
            raise FileNotFoundError(f"导读文件不存在: {intro_path}")
        files = [intro_path] + [f for f in files if f.resolve() != intro_path]
    if not files:
        raise FileNotFoundError(f"没有找到笔记: {notes_dir}")

    title = title or notes_dir.parent.name
    parts = [f"# {title}｜完整阅读笔记\n"]
    parts.append(f"> 整合日期：{date.today().isoformat()}")
    parts.append(f"> 分段数量：{len(files)}（含导读）" if intro_path else f"> 分段数量：{len(files)}")
    parts.append("\n---\n")

    # 目录
    toc = []
    for f in files:
        text = f.read_text(encoding="utf-8")
        m = re.search(r"^#\s+(.+)$", text, re.MULTILINE)
        heading = m.group(1) if m else f.stem
        toc.append(f"- [{heading}](#{_anchor(heading)})")
    parts.append("## 目录\n\n" + "\n".join(toc) + "\n\n---\n")

    for f in files:
        text = f.read_text(encoding="utf-8").strip()
        parts.append(text)
        parts.append("\n\n---\n")

    out = Path(out).expanduser().resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(parts).rstrip() + "\n", encoding="utf-8")
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="合并分段笔记")
    ap.add_argument("notes_dir", help="笔记目录")
    ap.add_argument("--out", required=True, help="最终 Markdown 路径")
    ap.add_argument("--title", default=None, help="书名（默认取目录名）")
    ap.add_argument("--intro", default=None, help="全书导读文件（可选，放在最前）")
    args = ap.parse_args()

    out = merge(args.notes_dir, args.out, title=args.title, intro=args.intro)
    print(f"已合并 -> {out}")
    return 0


def _anchor(text: str) -> str:
    """GitHub 风格锚点（保留中文、字母、数字、连字符）。"""
    text = text.strip().lower()
    text = re.sub(r"[^\w一-鿿\- ]", "", text)
    return text.replace(" ", "-")


if __name__ == "__main__":
    raise SystemExit(main())
