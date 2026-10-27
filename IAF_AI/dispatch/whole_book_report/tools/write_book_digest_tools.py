"""
write_book_digest_tools.py —— whole_book_report / agent digest 的浓缩版落盘工具。

落点由 workspace/whole_book_report/task.json 的 digest_path 决定。
校验：
  - stage 必须是 "digest"；
  - 目标必须落在 output/{book}/ 内，文件名为 {book}_浓缩版.md；
  - input_notes/ 至少有一份 NN_pages_*.md。
任何异常返回 "Error: ..."，不向上冒泡。
"""

from __future__ import annotations

import json
import os
import re
import tempfile

_TOOLS_DIR = os.path.dirname(os.path.abspath(__file__))
_DISPATCH_DIR = os.path.dirname(_TOOLS_DIR)                       # IAF_AI/dispatch/whole_book_report
_SHELL_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(_DISPATCH_DIR)))  # 框架根
_WORKSPACE_ROOT = os.path.join(_SHELL_ROOT, "workspace")
_TASK_FILE = os.path.join(_WORKSPACE_ROOT, "whole_book_report", "task.json")
_INPUT_NOTES = os.path.join(_WORKSPACE_ROOT, "whole_book_report", "input_notes")

_BOOK_RE = re.compile(r"^[\w-]+$", re.UNICODE)
_INPUT_NOTE_RE = re.compile(r"^\d{2}_pages_\d{3}-\d{3}\.md$")
_FENCE_RE = re.compile(r"^\s*```[A-Za-z]*\s*\n(.*?)\n```\s*$", re.DOTALL)


def _clean_content(content) -> str:
    if not isinstance(content, str):
        return ""
    text = content.strip()
    match = _FENCE_RE.match(text)
    if match:
        text = match.group(1).strip()
    return text


def _load_task() -> dict:
    with open(_TASK_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def _count_input_notes() -> int:
    if not os.path.isdir(_INPUT_NOTES):
        return 0
    return sum(
        1 for name in os.listdir(_INPUT_NOTES)
        if _INPUT_NOTE_RE.match(name) and os.path.isfile(os.path.join(_INPUT_NOTES, name))
    )


def _resolve_target(raw_path: str, book: str):
    if not isinstance(raw_path, str) or not raw_path.strip():
        return None, "digest_path 为空"
    if os.path.isabs(raw_path):
        return None, "digest_path 不能是绝对路径"

    norm = os.path.normpath(raw_path)
    if norm == ".." or norm.startswith(".." + os.sep):
        return None, "digest_path 不能包含 .."

    expected_name = f"{book}_浓缩版.md"
    name = os.path.basename(norm)
    if name != expected_name:
        return None, f"digest_path 文件名必须是 {expected_name}，实际为 {name}"

    book_root = os.path.join(_SHELL_ROOT, "output", book)
    target = os.path.realpath(os.path.join(_SHELL_ROOT, norm))
    real_root = os.path.realpath(book_root)
    if not (target == real_root or target.startswith(real_root + os.sep)):
        return None, f"digest_path 越界（须在 output/{book}/ 内）：{norm}"
    return target, None


def _atomic_write(target: str, content: str):
    out_dir = os.path.dirname(target)
    os.makedirs(out_dir, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=out_dir, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
            if not content.endswith("\n"):
                f.write("\n")
        os.replace(tmp, target)
    except Exception:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def _write_book_digest(args) -> str:
    try:
        content = _clean_content((args or {}).get("content", ""))
        if not content:
            return "Error: content 为空——必须提供完整浓缩版 Markdown。"

        task = _load_task()
        if task.get("stage") != "digest":
            return f"Error: 当前 stage={task.get('stage')!r}，不能写浓缩版。"

        book = task.get("book", "")
        if not _BOOK_RE.match(book or ""):
            return f"Error: task.json 中的 book 不安全或缺失：{book!r}"

        target, err = _resolve_target(task.get("digest_path", ""), book)
        if err:
            return f"Error: {err}"

        note_count = _count_input_notes()
        if note_count < 1:
            return "Error: input_notes 中没有可用的分段笔记，拒绝生成浓缩版。"

        _atomic_write(target, content)
        return f"Written {len(content)} chars → {task.get('digest_path')}"
    except Exception as e:
        return f"Error: {type(e).__name__}: {e}"


TOOLS = {
    "write_book_digest": {
        "description": (
            "将《全书浓缩版》的完整 Markdown 覆盖写入固定落点。"
            "只接受 content 一个参数；没有 path。必须调用一次以完成浓缩版。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "content": {
                    "type": "string",
                    "description": "完整浓缩版 Markdown（不要代码围栏，不要元对话）",
                }
            },
            "required": ["content"],
        },
        "handler": _write_book_digest,
    },
}
