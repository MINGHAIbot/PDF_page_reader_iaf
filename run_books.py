#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""run_books.py —— 唯一入口：扫 books/inbox/，整本处理，交付到 deliverables/。

每本书走的流程：
    EPUB ──epub_to_pdf.py──> PDF（仅当 inbox 里是 epub）
    PDF  ──pdf_to_png.py──> PNG 文件夹
         ──make_chunks.py──> 20/15 分段
         ──read_page dispatch──> 每段一份 NN_pages_XXX-YYY.md
         ──whole_book_report dispatch──> 导读（guide）+ 浓缩版（digest）
         ──merge_notes.py──> {书名}.md
         ──────────────────> deliverables/{书名}/

只设置两个 dispatch：read_page、whole_book_report。EPUB 转换、PDF 转图、
分段与合并都是 book_pipeline/ 下不依赖引擎的独立脚本。

用法：
    python run_books.py                    # 处理 inbox 里的全部书（默认行为）
    python run_books.py --dry-run          # 只看计划，不调 LLM、不写任何文件
    python run_books.py --book My_Book     # 只处理一本（inbox 里没有就按续跑处理）
    python run_books.py --book My_Book --report-only --force   # 重写导读与浓缩版
    python run_books.py --book My_Book --merge-only            # 只重新合并
    python run_books.py --book My_Book --skip-png --from 6 --to 6  # 重跑第 6 段
    python run_books.py --deliver-only     # 不跑 LLM，只把 output/ 成品复制到 deliverables/
    python run_books.py --keep-pdf         # 成功后保留 inbox 文件（默认删除）
    python run_books.py --archive          # 成功后把 PDF 移到 books/processed/
    python run_books.py --deliver "D:/交付" # 成品换到别的目录
    python run_books.py --cleanup-only     # 只清中间产物，不跑 LLM

输入：
    books/inbox/*.pdf
    books/inbox/*.epub        （开工前先转成同名 .pdf，转成功即删掉 epub）
    books/inbox/*.json        （可选，同名元数据，见 books/README.md）

输出：
    output/{book}/...         中间产物（PNG、分段笔记、chunks、run_log）
    deliverables/{book}/...   最终成品（完整版、浓缩版、导读、交付说明）
    books/inbox/              成功后默认删除对应 PDF 与同名 sidecar

清理：
    交付成功后自动删 output/{book}/、workspace/（只留 current/STATUS.md）
    和引擎会话档，避免 PNG 与 base64 图片历史把项目撑大。
    --keep-output / --keep-sessions 可保留。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import traceback
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

SHELL_ROOT = Path(__file__).resolve().parent
if str(SHELL_ROOT) not in sys.path:
    sys.path.insert(0, str(SHELL_ROOT))

# ---------------------------------------------------------------------------
# 重入框架自带的 venv
#
# 流水线跑在本进程里（不再 spawn 子进程），而 pymupdf 与引擎依赖都装在
# IAF_AI/.venv 下。用系统 Python 敲 `python run_books.py` 会在下面 import chain
# 那一行当场炸掉，所以先换解释器再 import。必须在任何引擎 import 之前做。
# ---------------------------------------------------------------------------

_VENV_GUARD = "RUN_BOOKS_IN_VENV"


def _venv_python() -> str | None:
    for candidate in (SHELL_ROOT / "IAF_AI" / ".venv" / "Scripts" / "python.exe",
                      SHELL_ROOT / "IAF_AI" / ".venv" / "bin" / "python"):
        if candidate.is_file():
            return str(candidate)
    return None


if __name__ == "__main__" and os.environ.get(_VENV_GUARD) != "1":
    _exe = _venv_python()
    if _exe and Path(_exe).resolve() != Path(sys.executable).resolve():
        os.environ[_VENV_GUARD] = "1"
        os.execv(_exe, [_exe, str(Path(__file__).resolve())] + sys.argv[1:])

import chain
from book_pipeline.cleanup import (
    cleanup_after_book,
    cleanup_engine_sessions,
    cleanup_output,
    cleanup_workspace,
    human_size,
)
from book_pipeline.epub_to_pdf import convert as convert_epub
from book_pipeline.make_chunks import build_chunks
from book_pipeline.merge_notes import merge

# 与 tools/_shared/image_parts.py 保持同步；import 失败时用同一组默认值。
try:
    import image_parts
    MAX_IMAGE_BYTES = image_parts.MAX_IMAGE_BYTES
    MAX_TOTAL_RAW_BYTES = image_parts.MAX_TOTAL_RAW_BYTES
except Exception:  # pragma: no cover - 仅防御性回退
    MAX_IMAGE_BYTES = 32 * 1024 * 1024
    MAX_TOTAL_RAW_BYTES = 36 * 1024 * 1024

# 两个写入工具的围栏固定为 output/{book}/，产物根因此不可配置。
OUTPUT_ROOT = SHELL_ROOT / "output"
DEFAULT_INBOX = SHELL_ROOT / "books" / "inbox"
DEFAULT_ARCHIVE = SHELL_ROOT / "books" / "processed"
DEFAULT_DELIVER = SHELL_ROOT / "deliverables"

READ_PAGE_WS = SHELL_ROOT / "workspace" / "read_page"
REPORT_WS = SHELL_ROOT / "workspace" / "whole_book_report"
INPUT_NOTES = REPORT_WS / "input_notes"

NOTE_RE = re.compile(r"^\d{2}_pages_\d{3}-\d{3}\.md$")
GUIDE_NAME = "00_全书导读.md"
SAFE_RE = re.compile(r"[^\w-]+", re.UNICODE)
FENCE_RE = re.compile(r"^\s*```[A-Za-z]*\s*\n(.*?)\n```\s*$", re.DOTALL)


class PipelineError(RuntimeError):
    """流水线可预期的失败（不打印 traceback）。"""


# ---------------------------------------------------------------------------
# 基础工具
# ---------------------------------------------------------------------------

def log(message: str = ""):
    print(message, flush=True)


def safe_book_name(name: str) -> str:
    """把书名换成可安全用作目录名/工具 book 字段的形式。

    只保留 Unicode 字母、数字、下划线与连字符；空格、点号、斜杠等一律变下划线。
    """
    cleaned = SAFE_RE.sub("_", (name or "").strip())
    return cleaned.strip("_") or "book"


def book_filter(raw: str) -> str:
    """--book 既可写书名，也可写 PDF/EPUB 文件名。"""
    path = Path(raw)
    if path.suffix.lower() in (".pdf", ".epub"):
        raw = path.stem
    return safe_book_name(raw)


def atomic_write_text(path, text: str):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
            if not text.endswith("\n"):
                f.write("\n")
        os.replace(tmp, path)
    except Exception:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def atomic_write_json(path, data):
    atomic_write_text(path, json.dumps(data, ensure_ascii=False, indent=2))


def atomic_copy(src: Path, dst: Path):
    dst.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(dst.parent), suffix=".tmp")
    os.close(fd)
    try:
        shutil.copy2(src, tmp)
        os.replace(tmp, dst)
    except Exception:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def read_text(path) -> str:
    return Path(path).read_text(encoding="utf-8")


def text_len(path) -> int:
    try:
        return len(read_text(path))
    except FileNotFoundError:
        return 0


def _written_since(path, since_ns: int) -> bool:
    """文件是否在本次尝试开始后被（重新）写过。

    --force 重跑时旧文件仍在；不能只看「文件够长」就判定成功，
    否则一次失败的重跑会被旧产物伪装成成功。
    """
    try:
        return Path(path).stat().st_mtime_ns >= since_ns
    except FileNotFoundError:
        return False


def strip_fence(text: str) -> str:
    """去掉模型偶尔包在全文外面的 Markdown 代码围栏。"""
    text = (text or "").strip()
    match = FENCE_RE.match(text)
    return match.group(1).strip() if match else text


def rel_shell(path) -> str:
    """转成相对框架根的 POSIX 风格路径，供 task.json 使用。"""
    try:
        return Path(path).resolve().relative_to(SHELL_ROOT).as_posix()
    except ValueError:
        return str(Path(path).resolve())


def resolve_path(raw: str) -> Path:
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = SHELL_ROOT / path
    return path.resolve()


def _unlink(path: Path):
    """删除文件；Windows 上先去掉只读属性再删。"""
    try:
        path.unlink()
    except PermissionError:
        os.chmod(path, stat.S_IWRITE)
        path.unlink()


def _save_log(path: Path, data: dict):
    atomic_write_json(path, data)


def _load_manifest(book_dir: Path) -> dict | None:
    path = book_dir / "manifest.json"
    if not path.is_file():
        return None
    return json.loads(read_text(path))


def _infer_pages(png_dir: Path, book: str) -> int:
    """manifest 缺失时，从 PNG 文件名推断最大页码。"""
    numbers = []
    for p in png_dir.glob(f"{book}_*.png"):
        m = re.search(r"_(\d{3})\.png$", p.name)
        if m:
            numbers.append(int(m.group(1)))
    if not numbers:
        raise PipelineError(f"无法推断页数：{png_dir} 下没有 {book}_NNN.png")
    return max(numbers)


def _pdf_page_count(pdf_path: Path) -> int:
    import pymupdf
    doc = pymupdf.open(str(pdf_path))
    try:
        return doc.page_count
    finally:
        doc.close()


# ---------------------------------------------------------------------------
# 阶段：EPUB → PDF（开工前先把 inbox 统一成 PDF）
# ---------------------------------------------------------------------------

def find_epubs(inbox: Path) -> list[Path]:
    if not inbox.is_dir():
        return []
    return sorted(p for p in inbox.iterdir()
                  if p.is_file() and p.suffix.lower() == ".epub")


def convert_inbox_epubs(inbox: Path, args) -> int:
    """把 inbox 里的 EPUB 就地排成同名 PDF，成功后删掉 EPUB。返回失败本数。

    同名 PDF 已存在时不转也不删：那份 PDF 可能是别处来的正式版，
    盖掉就没了；此时把 EPUB 留在原地，由人来决定留哪一份。
    """
    epubs = find_epubs(inbox)
    if not epubs:
        return 0

    log("=" * 60)
    log(f"[epub] 发现 {len(epubs)} 本 EPUB，先转 PDF")
    failed = 0
    for epub in epubs:
        pdf = epub.with_suffix(".pdf")
        if pdf.exists():
            log(f"[skip] {pdf.name} 已存在，不转换也不删除 {epub.name}；"
                "请自行决定保留哪一份")
            continue
        if args.dry_run:
            log(f"[dry-run] {epub.name} → {pdf.name}（并删除 EPUB）")
            continue
        try:
            fontsize = int_field(load_sidecar(epub), "epub_fontsize", args.epub_fontsize)
            info = convert_epub(epub, pdf, fontsize=fontsize)
        except Exception as e:
            log(f"[fail] EPUB 转换失败，保留原文件：{epub.name}：{e}")
            failed += 1
            continue
        log(f"[epub] {epub.name} → {pdf.name}"
            f"（{info['pages']} 页，{info['bytes'] // 1024} KB，{fontsize:g}pt）")
        if args.keep_epub:
            log(f"[keep] 保留 inbox EPUB：{epub.name}")
            continue
        try:
            _unlink(epub)
            log(f"[clean] 已从 inbox 删除：{epub.name}")
        except OSError as e:
            log(f"[warn] 删除 EPUB 失败（PDF 已生成）：{e}")
    return failed


# ---------------------------------------------------------------------------
# 阶段：PDF → PNG
# ---------------------------------------------------------------------------

def run_pdf_to_png(pdf: Path, output_root: Path, book: str, dpi: int, force: bool):
    script = SHELL_ROOT / "book_pipeline" / "pdf_to_png.py"
    if not script.is_file():
        raise PipelineError(f"找不到 {script}")
    if not pdf.is_file():
        raise PipelineError(f"找不到 PDF：{pdf}")

    cmd = [
        sys.executable, str(script), str(pdf),
        "-o", str(output_root),
        "--name", book,
        "--dpi", str(dpi),
    ]
    if force:
        cmd.append("--force")

    log(f"[png] {pdf.name} → {output_root / book / 'png'} (dpi={dpi})")
    result = subprocess.run(cmd, cwd=str(SHELL_ROOT))
    if result.returncode != 0:
        raise PipelineError(f"pdf_to_png.py 退出码 {result.returncode}")


# ---------------------------------------------------------------------------
# 阶段：read_page
# ---------------------------------------------------------------------------

def _selected_chunks(chunks: list, from_chunk: int, to_chunk: int | None) -> list:
    if from_chunk < 1:
        raise PipelineError("--from 必须从 1 开始")
    last = len(chunks) if to_chunk is None else to_chunk
    if last > len(chunks):
        raise PipelineError(f"--to={last} 超出总段数 {len(chunks)}")
    if from_chunk > last:
        raise PipelineError(f"--from={from_chunk} 大于 --to={last}")
    return chunks[from_chunk - 1:last]


def check_pngs(png_dir: Path, chunks: list):
    """预检 PNG 是否齐全、单张与单段总字节是否超限。"""
    missing = []
    for chunk in chunks:
        total = 0
        for name in chunk["png_files"]:
            path = png_dir / name
            if not path.is_file():
                missing.append(name)
                continue
            size = path.stat().st_size
            if size > MAX_IMAGE_BYTES:
                raise PipelineError(
                    f"单张 PNG 超过 {MAX_IMAGE_BYTES // (1024 * 1024)} MiB：{name}"
                )
            total += size
        if total > MAX_TOTAL_RAW_BYTES:
            raise PipelineError(
                f"第 {chunk['id']} 段 PNG 总字节 {total / (1024 * 1024):.1f} MiB "
                f"超过 {MAX_TOTAL_RAW_BYTES // (1024 * 1024)} MiB；"
                "请降低 --dpi 或减小 --window。"
            )
    if missing:
        shown = ", ".join(missing[:20])
        more = f" 等 {len(missing)} 张" if len(missing) > 20 else ""
        raise PipelineError(f"缺少 PNG：{shown}{more}；请先运行 pdf_to_png.py 或去掉 --skip-png。")


def _read_page_message(ctx, chunk, is_last: bool, max_note_chars: int) -> str:
    overlap = chunk["read_count"] - (chunk["new_end"] - chunk["new_start"] + 1)
    offset = ctx.page_offset
    lines = [
        f"书名：{ctx.title}",
        f"作者：{ctx.author or '（见封面/版权页）'}",
        f"出版：{ctx.publisher or '（见版权页）'}",
        "",
        f"本段：{chunk['id']}",
        f"阅读范围：PDF 第 {chunk['read_start']}–{chunk['read_end']} 页"
        f"（共 {chunk['read_count']} 张 PNG，按顺序对应第 {chunk['read_start']}–{chunk['read_end']} 页）",
        f"新增范围：第 {chunk['new_start']}–{chunk['new_end']} 页",
        f"重叠页：{overlap} 页" if overlap else "重叠页：0 页（本段无重叠）",
    ]
    if offset:
        lines.append(f"页码换算：正文页码 = PDF 页码 − {offset}")
    else:
        lines.append("页码换算：请根据页面上的印刷页码自行判断，并在引用中注明")
    lines.append(f"是否最后一段：{'是' if is_last else '否'}")
    lines.append("")
    lines.append(
        f"任务：按 note_template.md 逐页提炼新增页，调用 write_note 一次。"
        f"笔记目标长度 6,000–{max_note_chars} 字符。"
    )
    return "\n".join(lines)


def _run_read_chunk(ctx, chunk, is_last: bool, args) -> dict:
    note_path = ctx.notes_dir / chunk["note_file"]
    if note_path.is_file() and not args.force:
        chars = text_len(note_path)
        if chars >= args.min_note_chars:
            log(f"[{chunk['id']}] 已存在，跳过（{chars} chars）")
            return {"id": chunk["id"], "status": "skipped", "chars": chars, "duration_ms": 0}
        log(f"[{chunk['id']}] 已存在但过短（{chars} chars），重做")

    task = {
        "book": ctx.book,
        "book_title": ctx.title,
        "chunk_id": chunk["id"],
        "read_start": chunk["read_start"],
        "read_end": chunk["read_end"],
        "new_start": chunk["new_start"],
        "new_end": chunk["new_end"],
        "note_path": rel_shell(note_path),
        "page_offset": args.page_offset,
    }
    atomic_write_json(READ_PAGE_WS / "task.json", task)

    images = [str(ctx.png_dir / name) for name in chunk["png_files"]]
    base_message = _read_page_message(ctx, chunk, is_last, args.max_note_chars)

    last_error = ""
    last_chars = 0
    for attempt in range(args.retries + 1):
        message = base_message
        if attempt:
            message += (
                f"\n\n【重试 {attempt}/{args.retries}】上一次没有写出合格的笔记"
                f"（{last_error}）。请重新逐页阅读，补全内容后再次调用 write_note；"
                "必须写完整 Markdown。"
            )
        t0 = time.time()
        attempt_start_ns = time.time_ns()
        result = chain.run(
            dispatch_name="read_page",
            user_message=message,
            agent_name="core",
            image_paths=images,
        )
        duration = result.get("duration_ms") or int((time.time() - t0) * 1000)
        chars = text_len(note_path)
        last_chars = chars
        if chars >= args.min_note_chars and _written_since(note_path, attempt_start_ns):
            return {
                "id": chunk["id"], "status": "ok", "chars": chars,
                "duration_ms": duration, "attempts": attempt + 1,
            }

        # 工具没写成功、但模型把完整笔记当文本输出 → 编排器兜底落盘。
        fallback = strip_fence(result.get("text_response", ""))
        if len(fallback) >= args.min_note_chars:
            atomic_write_text(note_path, fallback)
            return {
                "id": chunk["id"], "status": "fallback", "chars": len(fallback),
                "duration_ms": duration, "attempts": attempt + 1,
            }

        last_error = (
            f"文件 {chars} 字符（下限 {args.min_note_chars}），"
            f"文本回退 {len(fallback)} 字符"
        )
        log(f"[{chunk['id']}] 第 {attempt + 1} 次未通过：{last_error}")

    return {
        "id": chunk["id"], "status": "failed", "chars": last_chars,
        "error": last_error, "duration_ms": 0,
    }


# ---------------------------------------------------------------------------
# 阶段：whole_book_report（guide + digest）
# ---------------------------------------------------------------------------

def prepare_report_notes(notes_dir: Path) -> tuple[int, int]:
    """把 notes_dir 下的 NN_pages_*.md 复制到 input_notes，返回 (数量, 总字符)。"""
    INPUT_NOTES.mkdir(parents=True, exist_ok=True)
    for item in INPUT_NOTES.iterdir():
        if item.is_dir() and not item.is_symlink():
            shutil.rmtree(item)
        else:
            item.unlink()

    files = sorted(p for p in notes_dir.glob("*.md") if NOTE_RE.match(p.name))
    total = 0
    for path in files:
        shutil.copy2(path, INPUT_NOTES / path.name)
        total += text_len(path)
    return len(files), total


def _guide_message(ctx, note_count: int, note_chars: int) -> str:
    return (
        f"书名：{ctx.title}\n"
        f"分段笔记：{note_count} 份，共 {note_chars} 字符\n\n"
        "任务：通读上下文中的全部分段笔记，按 guide_task.md 的结构写《全书导读》，"
        "调用 write_book_guide 一次。\n"
        "目标长度：6,000–10,000 字符；笔记总量较少时按实际内容写，不要凭空补页。\n"
        "不要在聊天里输出全文。"
    )


def _digest_message(ctx, note_count: int, note_chars: int, guide_text: str) -> str:
    guide_block = ""
    if guide_text.strip():
        guide_block = (
            "\n\n下面是已生成的《全书导读》，可以在此基础上扩写，"
            "但不要照抄它的章节结构：\n\n---\n"
            + guide_text.strip()
            + "\n---"
        )
    return (
        f"书名：{ctx.title}\n"
        f"分段笔记：{note_count} 份，共 {note_chars} 字符{guide_block}\n\n"
        "任务：通读上下文中的全部分段笔记，按 digest_task.md 的结构写《全书浓缩版》，"
        "调用 write_book_digest 一次。\n"
        "目标长度：20,000–25,000 字符；逐章覆盖，不要只写开头几章。\n"
        "不要在聊天里输出全文。"
    )


def _run_report_agent(ctx, agent: str, stage: str, message: str,
                      target: Path, min_chars: int, args) -> dict:
    if target.is_file() and not args.force:
        chars = text_len(target)
        if chars >= min_chars:
            log(f"[report:{stage}] 已存在，跳过（{chars} chars）")
            return {"status": "skipped", "chars": chars, "duration_ms": 0}
        log(f"[report:{stage}] 已存在但过短（{chars} chars），重做")

    last_error = ""
    for attempt in range(args.retries + 1):
        attempt_message = message
        if attempt:
            attempt_message += (
                f"\n\n【重试 {attempt}/{args.retries}】上一次没有写出合格的产物"
                f"（{last_error}）。请再次调用写入工具，提交完整 Markdown。"
            )
        t0 = time.time()
        attempt_start_ns = time.time_ns()
        result = chain.run(
            dispatch_name="whole_book_report",
            user_message=attempt_message,
            agent_name=agent,
        )
        duration = result.get("duration_ms") or int((time.time() - t0) * 1000)
        chars = text_len(target)
        if chars >= min_chars and _written_since(target, attempt_start_ns):
            return {
                "status": "ok", "chars": chars,
                "duration_ms": duration, "attempts": attempt + 1,
            }

        fallback = strip_fence(result.get("text_response", ""))
        if len(fallback) >= min_chars:
            atomic_write_text(target, fallback)
            return {
                "status": "fallback", "chars": len(fallback),
                "duration_ms": duration, "attempts": attempt + 1,
            }

        last_error = (
            f"文件 {chars} 字符（下限 {min_chars}），"
            f"文本回退 {len(fallback)} 字符"
        )
        log(f"[report:{stage}] 第 {attempt + 1} 次未通过：{last_error}")

    return {"status": "failed", "chars": text_len(target), "error": last_error,
            "duration_ms": 0}


# ---------------------------------------------------------------------------
# 单本流水线
# ---------------------------------------------------------------------------

def _build_ctx(args) -> SimpleNamespace:
    book = safe_book_name(args.book)
    title = args.title or book.replace("_", " ")
    book_dir = OUTPUT_ROOT / book
    notes_dir = book_dir / "notes"
    return SimpleNamespace(
        book=book,
        title=title,
        output_root=OUTPUT_ROOT,
        book_dir=book_dir,
        png_dir=book_dir / "png",
        notes_dir=notes_dir,
        guide_path=notes_dir / GUIDE_NAME,
        digest_path=book_dir / f"{book}_浓缩版.md",
        final_path=book_dir / f"{book}.md",
        page_offset=args.page_offset,
        author=args.author or "",
        publisher=args.publisher or "",
    )


def _list_note_files(notes_dir: Path) -> list[Path]:
    if not notes_dir.is_dir():
        return []
    return sorted(p for p in notes_dir.glob("*.md") if NOTE_RE.match(p.name))


def _do_merge(ctx) -> tuple[Path, int]:
    intro = ctx.guide_path if ctx.guide_path.is_file() else None
    out = merge(ctx.notes_dir, ctx.final_path, title=ctx.title, intro=intro)
    return out, text_len(out)


def run_one_book(args) -> int:
    """跑完一本：PNG → 分段笔记 → 导读/浓缩版 → 合并。返回退出码。"""
    ctx = _build_ctx(args)

    # ── 只合并 ──────────────────────────────────────────────
    if args.merge_only:
        notes = _list_note_files(ctx.notes_dir)
        if not notes:
            raise PipelineError(f"没有可合并的笔记：{ctx.notes_dir}")
        out, chars = _do_merge(ctx)
        log(f"[merge] {len(notes)} 份笔记 → {out}（{chars} chars）")
        if ctx.digest_path.is_file():
            log(f"[final] 浓缩版：{ctx.digest_path}（{text_len(ctx.digest_path)} chars）")
        return 0

    # ── 决定页数/作者/出版 ──────────────────────────────────
    manifest = None
    pages = None
    if not args.report_only:
        # dry-run 不渲染、不写任何产物；只读 manifest / PDF 页数来出计划。
        if not args.dry_run and not args.skip_png:
            if not args.pdf:
                raise PipelineError("需要 inbox 里的 PDF，或加 --skip-png 复用已有 PNG")
            run_pdf_to_png(Path(args.pdf).expanduser().resolve(),
                           ctx.output_root, ctx.book, args.dpi, args.force)
        manifest = _load_manifest(ctx.book_dir)
        if manifest:
            pages = int(manifest.get("pdf_pages") or 0) or None
            ctx.author = args.author or (manifest.get("pdf_author") or "")
        if pages is None:
            if args.pdf:
                pages = _pdf_page_count(Path(args.pdf).expanduser().resolve())
            elif ctx.png_dir.is_dir():
                pages = _infer_pages(ctx.png_dir, ctx.book)
            else:
                raise PipelineError(
                    f"找不到 {ctx.book_dir / 'manifest.json'}，也无法推断页数；"
                    "请把 PDF 放回 inbox，或先运行 pdf_to_png.py。"
                )

    # ── 分段计划 ────────────────────────────────────────────
    chunks = []
    selected = []
    if not args.report_only:
        try:
            chunks = build_chunks(pages, args.window, args.step, ctx.book)
        except ValueError as e:
            raise PipelineError(str(e))
        if not chunks:
            raise PipelineError(f"页数 {pages} 无法生成任何分段")
        selected = _selected_chunks(chunks, args.from_chunk, args.to_chunk)

    # ── dry-run：只打印 ─────────────────────────────────────
    if args.dry_run:
        log(f"[dry-run] 书名：{ctx.title}  book={ctx.book}")
        log(f"[dry-run] 目录：{ctx.book_dir}")
        if args.report_only:
            notes = _list_note_files(ctx.notes_dir)
            log(f"[dry-run] report-only：已有 {len(notes)} 份分段笔记")
            for p in notes:
                log(f"  - {p.name} ({text_len(p)} chars)")
            log(f"[dry-run] 导读：{ctx.guide_path}")
            log(f"[dry-run] 浓缩版：{ctx.digest_path}")
            log(f"[dry-run] 合并产物：{ctx.final_path}")
            return 0
        log(f"[dry-run] 总页数：{pages}；分段 {len(chunks)} 段；本次选 {len(selected)} 段")
        if selected:
            missing = sum(
                1 for c in selected for name in c["png_files"]
                if not (ctx.png_dir / name).is_file()
            )
            log(f"[dry-run] PNG 缺失：{missing} 张（实际运行时才会报错）")
        for c in selected:
            is_last = c["id"] == chunks[-1]["id"]
            log(f"  {c['id']}: 读 {c['read_start']:>3}-{c['read_end']:<3} "
                f"新增 {c['new_start']:>3}-{c['new_end']:<3} "
                f"→ {c['note_file']}{'（最后一段）' if is_last else ''}")
        log(f"[dry-run] 导读：{ctx.guide_path}")
        log(f"[dry-run] 浓缩版：{ctx.digest_path}")
        log(f"[dry-run] 合并产物：{ctx.final_path}")
        return 0

    # ── 正式运行：建目录 + 预检 ─────────────────────────────
    ctx.notes_dir.mkdir(parents=True, exist_ok=True)
    READ_PAGE_WS.mkdir(parents=True, exist_ok=True)
    REPORT_WS.mkdir(parents=True, exist_ok=True)
    INPUT_NOTES.mkdir(parents=True, exist_ok=True)

    run_log = {
        "book": ctx.book,
        "title": ctx.title,
        "page_offset": args.page_offset,
        "window": args.window,
        "step": args.step,
        "chunks": [],
        "guide": None,
        "digest": None,
        "final": None,
    }
    run_log_path = ctx.book_dir / "run_log.json"

    if not args.report_only:
        atomic_write_json(ctx.book_dir / "chunks.json", {
            "book": ctx.book,
            "total_pages": pages,
            "window": args.window,
            "step": args.step,
            "overlap": max(0, args.window - args.step),
            "chunks": chunks,
        })
        check_pngs(ctx.png_dir, selected)

        for chunk in selected:
            is_last = chunk["id"] == chunks[-1]["id"]
            log("=" * 60)
            log(f"[{chunk['id']}/{len(chunks)}] read_page  "
                f"读 {chunk['read_start']}-{chunk['read_end']}  "
                f"新增 {chunk['new_start']}-{chunk['new_end']}"
                f"{'（最后一段）' if is_last else ''}")
            entry = _run_read_chunk(ctx, chunk, is_last, args)
            run_log["chunks"].append(entry)
            _save_log(run_log_path, run_log)
            if entry["status"] == "failed":
                log(f"[{chunk['id']}] 失败：{entry.get('error', '')}")
                if not args.keep_going:
                    raise PipelineError(
                        f"第 {chunk['id']} 段失败；已完成的笔记保留，"
                        "可重跑该段。"
                    )
            else:
                log(f"[{chunk['id']}] {entry['status']}  {entry['chars']} chars  "
                    f"{entry['duration_ms'] / 1000:.1f}s")

    notes = _list_note_files(ctx.notes_dir)
    if not notes:
        raise PipelineError(f"没有找到任何分段笔记：{ctx.notes_dir}")

    # ── 报告阶段 ────────────────────────────────────────────
    guide_ok = False
    digest_ok = False
    report_failed = False

    if args.skip_report:
        log("[report] --skip-report：跳过导读与浓缩版")
        guide_ok = ctx.guide_path.is_file()
    else:
        note_count, note_chars = prepare_report_notes(ctx.notes_dir)
        if note_count < 1:
            raise PipelineError("input_notes 为空，无法生成报告")
        if note_chars > args.report_max_chars:
            raise PipelineError(
                f"笔记总量 {note_chars} 字符超过上限 {args.report_max_chars}；"
                "请提高 --report-max-chars，或先做章级汇总。"
            )
        log("=" * 60)
        log(f"[report] {note_count} 份笔记 / {note_chars} chars → input_notes")

        task = {
            "stage": "guide",
            "book": ctx.book,
            "book_title": ctx.title,
            "guide_path": rel_shell(ctx.guide_path),
            "digest_path": rel_shell(ctx.digest_path),
            "final_path": rel_shell(ctx.final_path),
            "note_count": note_count,
            "note_chars": note_chars,
        }
        atomic_write_json(REPORT_WS / "task.json", task)

        guide_result = _run_report_agent(
            ctx, "guide", "guide",
            _guide_message(ctx, note_count, note_chars),
            ctx.guide_path, args.min_guide_chars, args,
        )
        run_log["guide"] = guide_result
        _save_log(run_log_path, run_log)
        guide_ok = guide_result["status"] in ("ok", "fallback", "skipped") and ctx.guide_path.is_file()
        if not guide_ok:
            report_failed = True
            log(f"[report:guide] 失败：{guide_result.get('error', '')}")
            if not args.keep_going:
                log("[report] 导读失败，跳过浓缩版；将继续合并现有笔记。")

        if guide_ok and not args.skip_digest:
            guide_text = read_text(ctx.guide_path) if ctx.guide_path.is_file() else ""
            task["stage"] = "digest"
            atomic_write_json(REPORT_WS / "task.json", task)
            digest_result = _run_report_agent(
                ctx, "digest", "digest",
                _digest_message(ctx, note_count, note_chars, guide_text),
                ctx.digest_path, args.min_digest_chars, args,
            )
            run_log["digest"] = digest_result
            _save_log(run_log_path, run_log)
            digest_ok = digest_result["status"] in ("ok", "fallback", "skipped") and ctx.digest_path.is_file()
            if not digest_ok:
                log(f"[report:digest] 失败：{digest_result.get('error', '')}")
        elif args.skip_digest:
            log("[report] --skip-digest：跳过浓缩版")
        elif not guide_ok:
            log("[report] 无导读，跳过浓缩版")

    # ── 合并 ────────────────────────────────────────────────
    log("=" * 60)
    out, final_chars = _do_merge(ctx)
    run_log["final"] = {"path": rel_shell(out), "chars": final_chars}
    if ctx.digest_path.is_file():
        run_log["digest_final"] = {
            "path": rel_shell(ctx.digest_path),
            "chars": text_len(ctx.digest_path),
        }
    _save_log(run_log_path, run_log)
    log(f"[merge] {len(_list_note_files(ctx.notes_dir))} 份笔记 → {out}（{final_chars} chars）")

    # ── 汇总 ────────────────────────────────────────────────
    failed_chunks = [c["id"] for c in run_log["chunks"] if c["status"] == "failed"]
    log("=" * 60)
    log(f"[summary] 分段失败：{failed_chunks or '无'}")
    log(f"[summary] 导读：{text_len(ctx.guide_path) if ctx.guide_path.is_file() else 0} chars")
    log(f"[summary] 浓缩版：{text_len(ctx.digest_path) if ctx.digest_path.is_file() else 0} chars")
    log(f"[summary] 完整版：{final_chars} chars → {out}")

    if failed_chunks or report_failed:
        return 1
    if args.strict and not digest_ok and not args.skip_digest:
        return 1
    return 0


# ---------------------------------------------------------------------------
# 批处理层：入料、交付、清理
# ---------------------------------------------------------------------------

def find_pdfs(inbox: Path) -> list[Path]:
    if not inbox.is_dir():
        return []
    return sorted(
        p for p in inbox.iterdir()
        if p.is_file() and p.suffix.lower() == ".pdf"
    )


def load_sidecar(source: Path) -> dict:
    """读同名 .json 元数据；EPUB 与转出来的 PDF 同 stem，所以共用一份。"""
    sidecar = source.with_suffix(".json")
    if not sidecar.is_file():
        return {}
    try:
        data = json.loads(sidecar.read_text(encoding="utf-8"))
    except Exception as e:
        raise ValueError(f"读取 {sidecar.name} 失败：{e}") from e
    if not isinstance(data, dict):
        raise ValueError(f"{sidecar.name} 必须是 JSON 对象")
    return data


def str_field(meta: dict, key: str) -> str:
    value = meta.get(key)
    return str(value).strip() if value is not None else ""


def int_field(meta: dict, key: str, default: int) -> int:
    value = meta.get(key, default)
    try:
        return int(value)
    except (TypeError, ValueError) as e:
        raise ValueError(f"元数据 {key} 必须是整数，实际为 {value!r}") from e


def book_args(pdf: Path | None, meta: dict, book: str, args) -> SimpleNamespace:
    """把批处理参数 + sidecar 合成单本流水线要的那套参数。

    sidecar 优先于命令行：命令行给的是整批的缺省值，sidecar 是针对这一本的。
    keep_going 恒为真——批处理层已有 --stop-on-error 管到书这一级，
    段级失败在这里一律继续，让这本书把能写的笔记写完。
    """
    return SimpleNamespace(
        pdf=str(pdf) if pdf is not None else None,
        book=book,
        title=str_field(meta, "title") or (pdf.stem if pdf is not None else book),
        author=str_field(meta, "author"),
        publisher=str_field(meta, "publisher"),
        page_offset=int_field(meta, "page_offset", args.page_offset),
        dpi=int_field(meta, "dpi", args.dpi),
        window=int_field(meta, "window", args.window),
        step=int_field(meta, "step", args.step),
        report_max_chars=int_field(meta, "report_max_chars", args.report_max_chars),
        skip_png=args.skip_png,
        skip_report=args.skip_report,
        skip_digest=args.skip_digest,
        report_only=args.report_only,
        merge_only=args.merge_only,
        from_chunk=args.from_chunk,
        to_chunk=args.to_chunk,
        force=args.force,
        dry_run=args.dry_run,
        keep_going=True,
        strict=args.strict,
        retries=args.retries,
        max_note_chars=args.max_note_chars,
        min_note_chars=args.min_note_chars,
        min_guide_chars=args.min_guide_chars,
        min_digest_chars=args.min_digest_chars,
    )


def read_run_log(book_dir: Path) -> dict:
    path = book_dir / "run_log.json"
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def deliver_book(book: str, title: str, source_pdf: Path | None,
                 deliver_root: Path) -> tuple[bool, str]:
    """把 output/{book}/ 的成品复制到 deliver_root/{book}/。"""
    book_dir = OUTPUT_ROOT / book
    final_src = book_dir / f"{book}.md"
    if not final_src.is_file():
        return False, f"缺少完整版：{final_src}"

    dest_dir = deliver_root / book
    dest_dir.mkdir(parents=True, exist_ok=True)

    source_name = source_pdf.name if source_pdf is not None else ""
    if not source_name:
        manifest = book_dir / "manifest.json"
        if manifest.is_file():
            try:
                raw = json.loads(manifest.read_text(encoding="utf-8")).get("source_pdf")
            except Exception:
                raw = None
            if raw:
                source_name = Path(str(raw)).name

    candidates = [
        (final_src, dest_dir / f"{book}.md"),
        (book_dir / f"{book}_浓缩版.md", dest_dir / f"{book}_浓缩版.md"),
        (book_dir / "notes" / GUIDE_NAME, dest_dir / GUIDE_NAME),
        (book_dir / "run_log.json", dest_dir / "run_log.json"),
    ]
    copied: list[tuple[str, int]] = []
    for src, dst in candidates:
        if src.is_file():
            atomic_copy(src, dst)
            copied.append((dst.name, text_len(dst)))

    copies = {name: chars for name, chars in copied}
    lines = [
        f"# {title}｜交付说明",
        "",
        f"- 处理日期：{datetime.now().strftime('%Y-%m-%d')}",
    ]
    if source_name:
        lines.append(f"- 源 PDF：`{source_name}`")
    lines.append(f"- 书名目录：`{book}`")
    lines += ["", "## 成品", ""]
    lines.append(f"- `{book}.md`（{copies.get(f'{book}.md', 0)} 字符）")
    if f"{book}_浓缩版.md" in copies:
        lines.append(f"- `{book}_浓缩版.md`（{copies[f'{book}_浓缩版.md']} 字符）")
    else:
        lines.append("- `{0}_浓缩版.md`：未生成".format(book))
    if GUIDE_NAME in copies:
        lines.append(f"- `{GUIDE_NAME}`（{copies[GUIDE_NAME]} 字符）")
    else:
        lines.append(f"- `{GUIDE_NAME}`：未生成")
    if "run_log.json" in copies:
        lines.append("- `run_log.json`（运行日志，含每段字符数与耗时）")
    lines += [
        "",
        f"> 中间产物（PNG、分段笔记、chunks.json）在 `output/{book}/`。",
    ]
    atomic_write_text(dest_dir / "交付说明.md", "\n".join(lines) + "\n")
    return True, str(dest_dir)


def archive_pdf(pdf: Path, archive_dir: Path) -> Path:
    archive_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    dest = archive_dir / pdf.name
    if dest.exists():
        dest = archive_dir / f"{pdf.stem}_{stamp}{pdf.suffix}"
    shutil.move(str(pdf), str(dest))

    sidecar = pdf.with_suffix(".json")
    if sidecar.is_file():
        side_dest = archive_dir / sidecar.name
        if side_dest.exists():
            side_dest = archive_dir / f"{sidecar.stem}_{stamp}.json"
        shutil.move(str(sidecar), str(side_dest))
    return dest


def remove_source(pdf: Path) -> list[Path]:
    """删除 inbox 里的 PDF 和同名 sidecar，返回被删掉的文件。"""
    removed = []
    for path in (pdf, pdf.with_suffix(".json")):
        if path.is_file():
            _unlink(path)
            removed.append(path)
    return removed


def cleanup_source(pdf: Path | None, args):
    """成功后清理 inbox：默认删除；--archive 移动；--keep-pdf 保留。"""
    if pdf is None:
        return
    if args.keep_pdf:
        log(f"[keep] 保留 inbox PDF：{pdf.name}")
        return
    if args.archive:
        try:
            dest = archive_pdf(pdf, DEFAULT_ARCHIVE)
            log(f"[archive] {pdf.name} → {dest}")
        except OSError as e:
            log(f"[warn] 归档失败（成品已生成）：{e}")
        return
    try:
        removed = remove_source(pdf)
        names = "、".join(p.name for p in removed) or pdf.name
        log(f"[clean] 已从 inbox 删除：{names}")
    except OSError as e:
        log(f"[warn] 删除 inbox PDF 失败（成品已生成）：{e}")


def cleanup_intermediates(book: str, deliver_root: Path, args):
    """交付成功后清中间产物；清理失败不影响已交付的成品。"""
    try:
        cleanup_after_book(
            book,
            deliver_root=deliver_root,
            keep_output=args.keep_output,
            keep_sessions=args.keep_sessions,
            log=log,
        )
    except Exception as e:
        log(f"[warn] 清理中间产物失败（成品不受影响）：{e}")


def report_delivery(book: str, dest: str | Path):
    dest_dir = Path(dest)
    final = dest_dir / f"{book}.md"
    digest = dest_dir / f"{book}_浓缩版.md"
    parts = []
    if final.is_file():
        parts.append(f"完整版 {text_len(final)} 字符")
    if digest.is_file():
        parts.append(f"浓缩版 {text_len(digest)} 字符")
    else:
        parts.append("浓缩版缺失")
    log(f"[deliver] {book} → {dest_dir}（{'，'.join(parts)}）")


def deliver_existing(args) -> int:
    if not OUTPUT_ROOT.is_dir():
        log(f"[batch] 没有 output/ 目录：{OUTPUT_ROOT}")
        return 0

    candidates = sorted(p for p in OUTPUT_ROOT.iterdir() if p.is_dir())
    if args.book:
        wanted = book_filter(args.book)
        candidates = [p for p in candidates if p.name == wanted]

    books = [p for p in candidates if (p / f"{p.name}.md").is_file()]
    if not books:
        log(f"[batch] output/ 下没有可交付的成品"
            f"{f'（筛选：{args.book}）' if args.book else ''}")
        return 1 if args.book else 0

    deliver_root = resolve_path(args.deliver)
    ok = failed = 0
    for book_dir in books:
        book = book_dir.name
        meta = read_run_log(book_dir)
        title = str(meta.get("title") or book.replace("_", " "))
        if args.dry_run:
            log(f"[dry-run] {book} → {deliver_root / book}/")
            ok += 1
            continue
        success, message = deliver_book(book, title, None, deliver_root)
        if success:
            report_delivery(book, message)
            ok += 1
            cleanup_intermediates(book, deliver_root, args)
        else:
            log(f"[fail] {book}：{message}")
            failed += 1
    log("=" * 60)
    log(f"[batch] 交付成功 {ok}，失败 {failed}"
        f"{'（dry-run）' if args.dry_run else ''}")
    return 1 if failed else 0


def cleanup_only(args) -> int:
    """--cleanup-only：不跑 LLM，只清 output/ workspace/ 引擎会话。"""
    deliver_root = resolve_path(args.deliver)
    book_dirs: list[Path] = []
    if OUTPUT_ROOT.is_dir():
        if args.book:
            candidate = OUTPUT_ROOT / book_filter(args.book)
            if candidate.is_dir():
                book_dirs = [candidate]
        else:
            book_dirs = sorted(p for p in OUTPUT_ROOT.iterdir() if p.is_dir())

    totals = {"output": 0, "workspace": 0, "engine": 0}
    if not args.keep_output:
        for book_dir in book_dirs:
            totals["output"] += cleanup_output(
                book_dir, deliver_root, dry_run=args.dry_run, log=log
            )
    if not args.keep_sessions:
        totals["workspace"] = cleanup_workspace(dry_run=args.dry_run, log=log)
        totals["engine"] = cleanup_engine_sessions(dry_run=args.dry_run, log=log)

    total = sum(totals.values())
    verb = "预计释放" if args.dry_run else "释放"
    log("=" * 60)
    log(f"[clean] {verb} {human_size(total)}"
        f"（output {human_size(totals['output'])} · "
        f"workspace {human_size(totals['workspace'])} · "
        f"引擎会话 {human_size(totals['engine'])}）")
    return 0


def collect_jobs(inbox: Path, args) -> list[Path | None]:
    """排出这一轮要处理的书：inbox 里的 PDF，必要时补一个「续跑」空位。

    None 表示 inbox 里没有对应 PDF 但 output/{book}/ 还在——交付成功后
    inbox 那份就被清掉了，重跑报告、重新合并、重跑某一段都落在这条路上。
    """
    pdfs = find_pdfs(inbox)
    if not args.book:
        return list(pdfs)

    wanted = book_filter(args.book)
    hit = [p for p in pdfs
           if safe_book_name(p.stem) == wanted
           or p.stem == args.book
           or p.name == args.book]
    if hit:
        return hit
    if (OUTPUT_ROOT / wanted).is_dir():
        return [None]
    return []


def process(args) -> int:
    inbox = resolve_path(args.inbox)
    deliver_root = resolve_path(args.deliver)

    if not inbox.is_dir():
        if args.dry_run:
            log(f"[dry-run] inbox 不存在：{inbox}")
            return 0
        inbox.mkdir(parents=True, exist_ok=True)
        log(f"[batch] 已创建 inbox：{inbox}")
        log("[batch] 把 PDF 或 EPUB 放进去，再运行一次。")
        return 0

    # EPUB 先统一成 PDF，之后整条流水线只认 PDF。
    convert_failed = convert_inbox_epubs(inbox, args)

    jobs = collect_jobs(inbox, args)
    if not jobs:
        log(f"[batch] inbox 里没有待处理的书：{inbox}")
        return 1 if (args.book or convert_failed) else 0

    log("=" * 60)
    log(f"[batch] inbox：{inbox}")
    log(f"[batch] 成品目录：{deliver_root}")
    log(f"[batch] 待处理 {len(jobs)} 本（串行处理）")

    seen: dict[str, Path | None] = {}
    ok = skipped = 0
    failed = convert_failed       # 转换失败的 EPUB 已经是这一轮的失败，计进总账
    dry_run = args.dry_run

    for index, pdf in enumerate(jobs, 1):
        log("=" * 60)
        log(f"[{index}/{len(jobs)}] {pdf.name if pdf is not None else book_filter(args.book) + '（续跑）'}")
        try:
            if pdf is not None:
                meta = load_sidecar(pdf)
                book = safe_book_name(str_field(meta, "book") or pdf.stem)
            else:
                # 续跑：inbox 已无此书，上一轮的 run_log 就是它的元数据
                book = book_filter(args.book)
                meta = read_run_log(OUTPUT_ROOT / book)
            one = book_args(pdf, meta, book, args)
        except Exception as e:
            log(f"[fail] 元数据错误：{e}")
            failed += 1
            if args.stop_on_error:
                break
            continue

        if book in seen:
            other = seen[book]
            log(f"[fail] 书名 {book!r} 与 {other.name if other else book} 冲突；"
                "请在 sidecar 里用 book 字段区分")
            failed += 1
            if args.stop_on_error:
                break
            continue
        seen[book] = pdf

        existing = deliver_root / book / f"{book}.md"
        if existing.is_file() and not args.force:
            log(f"[skip] 成品已存在：{existing}（加 --force 重做）")
            skipped += 1
            if dry_run:
                if pdf is None:
                    pass
                elif args.keep_pdf:
                    log(f"[dry-run] 保留 inbox PDF：{pdf.name}")
                elif args.archive:
                    log(f"[dry-run] 归档 inbox PDF：{pdf.name}")
                else:
                    log(f"[dry-run] 删除 inbox PDF：{pdf.name}")
            else:
                cleanup_source(pdf, args)
                cleanup_intermediates(book, deliver_root, args)
            continue

        log(f"  book={book}  title={one.title}  page_offset={one.page_offset}")
        log(f"  中间产物：output/{book}/")
        log(f"  最终成品：{deliver_root / book}/")

        try:
            code = run_one_book(one)
        except PipelineError as e:
            log(f"[错误] {e}")
            code = 1
        except KeyboardInterrupt:
            log("\n[中断] 已完成的笔记保留。")
            return 130
        except Exception:
            traceback.print_exc()
            code = 1

        if code != 0:
            log("[fail] 这一本没跑完；已完成的笔记保留，可重跑或加 --force")
            failed += 1
            if args.stop_on_error:
                break
            continue

        if dry_run:
            if pdf is None:
                pass
            elif args.keep_pdf:
                log("[dry-run] 成功后保留 inbox PDF")
            elif args.archive:
                log("[dry-run] 成功后归档 inbox PDF")
            else:
                log("[dry-run] 成功后删除 inbox PDF")
            ok += 1
            continue

        success, message = deliver_book(book, one.title, pdf, deliver_root)
        if not success:
            log(f"[fail] 交付失败：{message}")
            failed += 1
            if args.stop_on_error:
                break
            continue

        report_delivery(book, message)
        ok += 1
        cleanup_source(pdf, args)
        cleanup_intermediates(book, deliver_root, args)

    log("=" * 60)
    if dry_run:
        log(f"[batch] 计划处理 {ok} 本，跳过 {skipped} 本，失败 {failed} 本（dry-run）")
    else:
        log(f"[batch] 成功 {ok} 本，跳过 {skipped} 本，失败 {failed} 本")
    return 1 if failed else 0


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description="扫 books/inbox/：EPUB 先转 PDF，整本读完写进 deliverables/；"
                    "成功后默认删除 inbox 里的源文件",
    )
    ap.add_argument("--inbox", default=str(DEFAULT_INBOX),
                    help="入料目录（默认 books/inbox/）")
    ap.add_argument("--deliver", default=str(DEFAULT_DELIVER),
                    help="成品目录（默认 deliverables/，可写绝对路径）")
    ap.add_argument("--book", default=None,
                    help="只处理指定书名或文件名；inbox 里没有就对 output/ 里那本续跑")
    ap.add_argument("--force", action="store_true",
                    help="重做已完成的书，并覆盖成品（会重跑全部 LLM 调用）")
    ap.add_argument("--dry-run", action="store_true",
                    help="只打印计划，不调 LLM、不写任何文件")
    ap.add_argument("--deliver-only", action="store_true",
                    help="不跑 LLM，只把 output/ 的成品复制到 deliverables/")
    ap.add_argument("--cleanup-only", action="store_true",
                    help="不跑 LLM，只清理 output/ workspace/ 引擎会话里的中间产物")
    ap.add_argument("--archive", action="store_true",
                    help="成功后把 PDF（和同名 sidecar）移到 books/processed/")
    ap.add_argument("--keep-pdf", action="store_true",
                    help="成功后保留 inbox 里的 PDF（默认删除；与 --archive 互斥）")
    ap.add_argument("--keep-epub", action="store_true",
                    help="转换成功后保留 inbox 里的 EPUB（默认删除）")
    ap.add_argument("--keep-output", action="store_true",
                    help="交付成功后保留 output/{书名}/（默认删除，只留 deliverables）")
    ap.add_argument("--keep-sessions", action="store_true",
                    help="保留 workspace 与引擎会话留痕（默认只留 workspace/current/STATUS.md）")
    ap.add_argument("--stop-on-error", action="store_true",
                    help="某本失败后停止，默认继续处理下一本")

    stage = ap.add_argument_group("阶段控制（多配 --book 用）")
    stage.add_argument("--skip-png", action="store_true", help="不重新渲染 PNG")
    stage.add_argument("--skip-report", action="store_true", help="跳过导读与浓缩版")
    stage.add_argument("--skip-digest", action="store_true", help="只生成导读，不生成浓缩版")
    stage.add_argument("--report-only", action="store_true", help="跳过 read_page，只跑报告")
    stage.add_argument("--merge-only", action="store_true", help="只合并，不调 LLM")
    stage.add_argument("--from", dest="from_chunk", type=int, default=1,
                       help="只跑第 N 段起（1 起）")
    stage.add_argument("--to", dest="to_chunk", type=int, default=None,
                       help="只跑第 N 段止（含）")
    stage.add_argument("--strict", action="store_true",
                       help="浓缩版失败也算这一本失败")

    tune = ap.add_argument_group("排版与分段（sidecar 同名字段优先）")
    tune.add_argument("--epub-fontsize", type=float, default=12.0,
                      help="EPUB 重排字号，pt（默认 12；字号决定每页装多少字）")
    tune.add_argument("--page-offset", type=int, default=0,
                      help="默认页码偏移；sidecar 的 page_offset 优先")
    tune.add_argument("--dpi", type=int, default=150,
                      help="PNG 分辨率（默认 150）")
    tune.add_argument("--window", type=int, default=20,
                      help="每段读多少页（默认 20）")
    tune.add_argument("--step", type=int, default=15,
                      help="每段前进多少页（默认 15）")
    tune.add_argument("--retries", type=int, default=2,
                      help="每阶段失败重试次数（默认 2）")
    tune.add_argument("--max-note-chars", type=int, default=12000,
                      help="单段笔记目标上限（默认 12000）")
    tune.add_argument("--min-note-chars", type=int, default=800,
                      help="单段笔记合格下限（默认 800）")
    tune.add_argument("--min-guide-chars", type=int, default=2000,
                      help="导读合格下限（默认 2000）")
    tune.add_argument("--min-digest-chars", type=int, default=8000,
                      help="浓缩版合格下限（默认 8000）")
    tune.add_argument("--report-max-chars", type=int, default=600000,
                      help="报告阶段输入笔记总字符上限（默认 600000）")
    return ap


def main(argv=None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = build_parser()
    args = ap.parse_args(argv)
    if args.archive and args.keep_pdf:
        ap.error("--archive 与 --keep-pdf 不能同时使用")
    if (args.report_only or args.merge_only) and not args.book:
        ap.error("--report-only / --merge-only 针对单本，必须同时给 --book")
    if args.cleanup_only:
        return cleanup_only(args)
    if args.deliver_only:
        if args.archive:
            log("[warn] --deliver-only 不会归档 PDF，忽略 --archive")
        return deliver_existing(args)
    return process(args)


if __name__ == "__main__":
    raise SystemExit(main())
