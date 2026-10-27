#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""按「窗口 + 步进」切分阅读段落。

默认每段读 20 页、前进 15 页（相邻段重叠 5 页用于衔接）。
每段只提炼「新增页」，重叠页用于保持上下文连贯，避免最终整合时重复。

用法:
    python make_chunks.py --pages 164 --book Interviewing_for_Radio
    python make_chunks.py --pages 164 --window 20 --step 15 --out chunks.json
"""
import argparse
import json
from pathlib import Path


def build_chunks(pages: int, window: int, step: int, book: str):
    """把 pages 页切成重叠窗口。

    step > window 会在两段之间留下从未被读到的页（new_start 直接跳过），
    因此直接拒绝；step == window 表示无重叠。
    """
    if pages < 0:
        raise ValueError("pages 不能为负数")
    if window < 1 or step < 1:
        raise ValueError("window / step 必须为正整数")
    if step > window:
        raise ValueError("step 不能大于 window，否则会漏读页面")
    chunks = []
    start = 1
    prev_end = 0
    idx = 1
    while start <= pages:
        end = min(start + window - 1, pages)
        new_start = 1 if idx == 1 else prev_end + 1
        new_end = end
        if new_start > new_end:
            break
        cid = f"{idx:02d}"
        chunks.append(
            {
                "id": cid,
                "read_start": start,
                "read_end": end,
                "read_count": end - start + 1,
                "new_start": new_start,
                "new_end": new_end,
                "note_file": f"{cid}_pages_{new_start:03d}-{new_end:03d}.md",
                "png_files": [
                    f"{book}_{p:03d}.png" for p in range(start, end + 1)
                ],
            }
        )
        prev_end = end
        start += step
        idx += 1
    return chunks


def main() -> int:
    ap = argparse.ArgumentParser(description="生成分段阅读清单")
    ap.add_argument("--pages", type=int, required=True, help="PDF 总页数")
    ap.add_argument("--window", type=int, default=20, help="每段阅读页数（默认 20）")
    ap.add_argument("--step", type=int, default=15, help="相邻段起始页步进（默认 15）")
    ap.add_argument("--book", default="book", help="书名（用于匹配 PNG 文件名）")
    ap.add_argument("--out", default="chunks.json", help="输出 JSON 路径")
    args = ap.parse_args()

    try:
        chunks = build_chunks(args.pages, args.window, args.step, args.book)
    except ValueError as e:
        raise SystemExit(str(e))

    data = {
        "book": args.book,
        "total_pages": args.pages,
        "window": args.window,
        "step": args.step,
        "overlap": max(0, args.window - args.step),
        "chunks": chunks,
    }
    out = Path(args.out).expanduser().resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"共 {len(chunks)} 段，输出: {out}")
    for c in chunks:
        print(
            f"  {c['id']}: 读 {c['read_start']:>3}-{c['read_end']:<3} "
            f"(新增 {c['new_start']:>3}-{c['new_end']:<3}) -> {c['note_file']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
