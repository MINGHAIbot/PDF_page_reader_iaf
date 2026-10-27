"""
write_note_tools.py —— read_page 的笔记落盘工具。

硬规矩（沿用 IAF 固定目标 + 原子写范式）：
  1. 只收 `content`，不收 path —— 落点由 shell 层写入的
     workspace/read_page/task.json 决定，LLM 无法指定路径。
  2. 目标必须落在 output/{book}/notes/ 内，且文件名匹配
     NN_pages_XXX-YYY.md（防止路径穿越与误写）。
  3. 原子写：同目录临时文件 + os.replace；UTF-8；覆盖旧文件。
  4. 任何异常都返回 "Error: ..." 字符串，不向上冒泡。
"""

from __future__ import annotations

import json
import os
import re
import tempfile

_TOOLS_DIR = os.path.dirname(os.path.abspath(__file__))
_DISPATCH_DIR = os.path.dirname(_TOOLS_DIR)                       # IAF_AI/dispatch/read_page
_SHELL_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(_DISPATCH_DIR)))  # 框架根
_WORKSPACE_ROOT = os.path.join(_SHELL_ROOT, "workspace")
_TASK_FILE = os.path.join(_WORKSPACE_ROOT, "read_page", "task.json")

_BOOK_RE = re.compile(r"^[\w-]+$", re.UNICODE)
_NOTE_NAME_RE = re.compile(r"^\d{2}_pages_\d{3}-\d{3}\.md$")
_FENCE_RE = re.compile(r"^\s*```[A-Za-z]*\s*\n(.*?)\n```\s*$", re.DOTALL)


def _clean_content(content) -> str:
    """去掉模型偶尔包在全文外面的 Markdown 代码围栏。"""
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


def _resolve_target(raw_path: str, book: str):
    """校验 note_path 并返回绝对路径；失败返回 (None, 错误信息)。"""
    if not isinstance(raw_path, str) or not raw_path.strip():
        return None, "note_path 为空"
    if os.path.isabs(raw_path):
        return None, "note_path 不能是绝对路径"

    norm = os.path.normpath(raw_path)
    if norm == ".." or norm.startswith(".." + os.sep):
        return None, "note_path 不能包含 .."

    name = os.path.basename(norm)
    if not _NOTE_NAME_RE.match(name):
        return None, f"note_path 文件名不合法：{name}（应为 NN_pages_XXX-YYY.md）"

    notes_root = os.path.join(_SHELL_ROOT, "output", book, "notes")
    target = os.path.realpath(os.path.join(_SHELL_ROOT, norm))
    real_root = os.path.realpath(notes_root)
    if not (target == real_root or target.startswith(real_root + os.sep)):
        return None, f"note_path 越界（须在 output/{book}/notes/ 内）：{norm}"
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


def _write_note(args) -> str:
    try:
        content = _clean_content((args or {}).get("content", ""))
        if not content:
            return "Error: content 为空——必须提供完整笔记 Markdown。"

        task = _load_task()
        book = task.get("book", "")
        if not _BOOK_RE.match(book or ""):
            return f"Error: task.json 中的 book 不安全或缺失：{book!r}"

        target, err = _resolve_target(task.get("note_path", ""), book)
        if err:
            return f"Error: {err}"

        _atomic_write(target, content)
        return f"Written {len(content)} chars → {task.get('note_path')}"
    except Exception as e:
        return f"Error: {type(e).__name__}: {e}"


TOOLS = {
    "write_note": {
        "description": (
            "将本段读书笔记的完整 Markdown 覆盖写入固定落点。"
            "只接受 content 一个参数；没有 path。必须调用一次以完成本段产出。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "content": {
                    "type": "string",
                    "description": "完整的分段笔记 Markdown（不要代码围栏，不要元对话）",
                }
            },
            "required": ["content"],
        },
        "handler": _write_note,
    },
}
