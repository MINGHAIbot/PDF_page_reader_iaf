#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 EPUB 排成 PDF，交给 pdf_to_png.py 逐页渲染。

用法:
    python epub_to_pdf.py 书.epub
    python epub_to_pdf.py 书.epub -o 书.pdf --fontsize 11
    python epub_to_pdf.py 书.epub --no-page-numbers

EPUB 是回流版式，本身没有「页」。这里按固定开本重排出页来，所以排版参数
直接决定每页装多少字，也就决定了下游「每段读 20 页」实际读进去多少内容：
同一本书排成 A4/11pt 是 115 页、排成 396x612pt/12pt 是 241 页，后者每页
约 2300 字符，与纸书每页字数同量级。开本定小一点，模型每张图要啃的量才
和真书 PDF 对得上。

页脚印页码：read_page 的提示词要求页码「来自页面本身」，重排出来的页一个
印刷数字都没有，不印的话全书引用会整体退化成「正文页码待核」。印上之后
PDF 页码与页面上的数字逐一相同，page_offset 取 0 就是对的。
"""
from __future__ import annotations

import argparse
import os
import sys
import tempfile
from pathlib import Path

import pymupdf

# 5.5x8.5 英寸，平装书常见开本。
DEFAULT_WIDTH = 396.0
DEFAULT_HEIGHT = 612.0
DEFAULT_FONTSIZE = 12.0

# MuPDF 排 EPUB 时正文铺满整个 rect，页脚得另外垫出来，否则页码会压在正文上。
FOOTER_HEIGHT = 36.0
FOLIO_FONT = "helv"
FOLIO_SIZE = 9.0
FOLIO_COLOR = (0.35, 0.35, 0.35)

# convert_to_pdf() 不带元数据过来，得逐项搬；pdf_to_png.py 要靠 title/author 写 manifest。
META_KEYS = ("title", "author", "subject", "keywords", "creator")


def convert(epub_path, pdf_path, width: float = DEFAULT_WIDTH,
            height: float = DEFAULT_HEIGHT, fontsize: float = DEFAULT_FONTSIZE,
            page_numbers: bool = True) -> dict:
    """把 epub_path 排成 pdf_path，返回 {pages, bytes, title, author}。

    原子落盘：先写同目录临时文件再 os.replace，中途失败不会留下半本 PDF
    被下一轮当成「已经转好了」。
    """
    epub_path = Path(epub_path)
    pdf_path = Path(pdf_path)
    pdf_path.parent.mkdir(parents=True, exist_ok=True)

    src = pymupdf.open(str(epub_path))
    try:
        if src.is_reflowable:
            src.layout(rect=pymupdf.Rect(0, 0, width, height), fontsize=fontsize)
        meta = {k: (src.metadata or {}).get(k) or "" for k in META_KEYS}
        body = pymupdf.open("pdf", src.convert_to_pdf())
    finally:
        src.close()

    out = pymupdf.open()
    try:
        for index in range(body.page_count):
            rect = body[index].rect
            foot = FOOTER_HEIGHT if page_numbers else 0.0
            page = out.new_page(width=rect.width, height=rect.height + foot)
            page.show_pdf_page(pymupdf.Rect(0, 0, rect.width, rect.height), body, index)
            if page_numbers:
                folio = str(index + 1)
                text_width = pymupdf.get_text_length(
                    folio, fontname=FOLIO_FONT, fontsize=FOLIO_SIZE
                )
                page.insert_text(
                    ((rect.width - text_width) / 2, rect.height + foot * 0.55),
                    folio, fontname=FOLIO_FONT, fontsize=FOLIO_SIZE, color=FOLIO_COLOR,
                )
        out.set_metadata(meta)
        pages = out.page_count

        fd, tmp = tempfile.mkstemp(dir=str(pdf_path.parent), suffix=".pdf.tmp")
        os.close(fd)
        try:
            out.save(tmp, garbage=4, deflate=True)
            os.replace(tmp, pdf_path)
        except Exception:
            if os.path.exists(tmp):
                os.unlink(tmp)
            raise
    finally:
        out.close()
        body.close()

    return {
        "pages": pages,
        "bytes": pdf_path.stat().st_size,
        "title": meta["title"],
        "author": meta["author"],
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="EPUB 重排成 PDF")
    ap.add_argument("epub", help="EPUB 文件路径")
    ap.add_argument("-o", "--output", default=None,
                    help="PDF 落点（默认与 EPUB 同名同目录）")
    ap.add_argument("--width", type=float, default=DEFAULT_WIDTH,
                    help=f"页宽，pt（默认 {DEFAULT_WIDTH:g}）")
    ap.add_argument("--height", type=float, default=DEFAULT_HEIGHT,
                    help=f"页高，pt（默认 {DEFAULT_HEIGHT:g}）")
    ap.add_argument("--fontsize", type=float, default=DEFAULT_FONTSIZE,
                    help=f"正文字号，pt（默认 {DEFAULT_FONTSIZE:g}）")
    ap.add_argument("--no-page-numbers", action="store_true",
                    help="不在页脚印页码")
    args = ap.parse_args(argv)

    epub = Path(args.epub).expanduser().resolve()
    if not epub.is_file():
        print(f"[错误] 找不到 EPUB: {epub}", file=sys.stderr)
        return 1
    pdf = Path(args.output).expanduser() if args.output else epub.with_suffix(".pdf")

    info = convert(epub, pdf, width=args.width, height=args.height,
                   fontsize=args.fontsize, page_numbers=not args.no_page_numbers)
    print(f"书名: {info['title'] or epub.stem}")
    print(f"作者: {info['author'] or '（EPUB 未写）'}")
    print(f"完成: {info['pages']} 页，{info['bytes'] // 1024} KB → {pdf}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
