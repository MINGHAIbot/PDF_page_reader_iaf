#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 PDF 每一页渲染成一张 PNG，命名 <书名>_<页码>.png

用法:
    python pdf_to_png.py 书.pdf
    python pdf_to_png.py 书.pdf --dpi 200 --start 1 --end 50
    python pdf_to_png.py 书.pdf -o output --name "Interviewing for Radio"
"""
import argparse
import json
import re
import sys
from pathlib import Path

import pymupdf

INVALID = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def safe_name(name: str) -> str:
    """把书名变成可用作文件名的形式。"""
    name = INVALID.sub("", name or "").strip()
    name = re.sub(r"\s+", "_", name)
    return name.strip("._") or "book"


def main() -> int:
    ap = argparse.ArgumentParser(description="PDF 逐页转 PNG")
    ap.add_argument("pdf", help="PDF 文件路径")
    ap.add_argument("-o", "--output", default="output", help="输出根目录（默认 ./output）")
    ap.add_argument("--dpi", type=int, default=150, help="渲染分辨率（默认 150）")
    ap.add_argument("--name", default=None, help="书名（默认取 PDF 元数据标题）")
    ap.add_argument("--start", type=int, default=1, help="起始页（1 起，默认 1）")
    ap.add_argument("--end", type=int, default=None, help="结束页（含，默认最后一页）")
    ap.add_argument("--force", action="store_true", help="覆盖已存在的 PNG")
    args = ap.parse_args()

    pdf_path = Path(args.pdf).expanduser().resolve()
    if not pdf_path.is_file():
        print(f"[错误] 找不到 PDF: {pdf_path}", file=sys.stderr)
        return 1

    doc = pymupdf.open(pdf_path)
    book = safe_name(args.name or doc.metadata.get("title") or pdf_path.stem)
    book_dir = Path(args.output).expanduser().resolve() / book
    png_dir = book_dir / "png"
    png_dir.mkdir(parents=True, exist_ok=True)

    start = max(1, args.start)
    end = min(args.end or doc.page_count, doc.page_count)
    if start > end:
        print(f"[错误] 页码范围无效: {start}-{end}", file=sys.stderr)
        return 1

    print(f"书名: {book}")
    print(f"页数: {end - start + 1} / 共 {doc.page_count} 页，DPI: {args.dpi}")
    print(f"输出: {png_dir}")

    files = []
    rendered = skipped = 0
    for pno in range(start, end + 1):
        out = png_dir / f"{book}_{pno:03d}.png"
        files.append(out.name)
        if out.exists() and not args.force:
            skipped += 1
            continue
        page = doc[pno - 1]
        pix = page.get_pixmap(dpi=args.dpi, alpha=False)
        pix.save(out)
        rendered += 1
        if rendered % 20 == 0:
            print(f"  已渲染 {rendered} 页 ...")

    manifest = {
        "book": book,
        "source_pdf": str(pdf_path),
        "pdf_title": doc.metadata.get("title"),
        "pdf_author": doc.metadata.get("author"),
        "pdf_pages": doc.page_count,
        "range": [start, end],
        "dpi": args.dpi,
        "naming": f"{book}_{{page:03d}}.png",
        "files": files,
    }
    manifest_path = book_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    doc.close()

    print(f"完成: 新渲染 {rendered} 页，跳过 {skipped} 页。")
    print(f"清单: {manifest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
