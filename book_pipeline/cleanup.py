#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""一本文书跑完后的中间产物清理。

成品交付到 deliverables/{书名}/ 之后，output/ 与 workspace/ 里的东西
都是可再生的中间态；真正值得留的只有一份 STATUS 轨迹。本模块把
「任务结束 → 清中间产物」固化成一条可复用的清理路径：

    cleanup_after_book(book, deliver_root)   # run_books.py 交付成功后调用

清理范围：
    output/{书名}/                  PNG、分段笔记、chunks、run_log
    workspace/*                     只留 current → {最新 session}/STATUS.md
    IAF_AI/dispatch/*/sessions/     引擎会话历史（每条都内嵌 base64 PNG）
    IAF_AI/dispatch/*/staging/      引擎暂存

安全护栏：output/{书名}/ 只有在 deliverables/{书名}/{书名}.md 存在时才删，
避免交付失败时把唯一成品清掉。
"""

from __future__ import annotations

import os
import shutil
import stat
from pathlib import Path

SHELL_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_ROOT = SHELL_ROOT / "output"
WORKSPACE = SHELL_ROOT / "workspace"
CURRENT_LINK = WORKSPACE / "current"
DEFAULT_DELIVER_ROOT = SHELL_ROOT / "deliverables"
ENGINE_DISPATCH = SHELL_ROOT / "IAF_AI" / "dispatch"

KEEP_NAMES = {"STATUS.md"}


def human_size(num: int) -> str:
    size = float(num)
    for unit in ("B", "KiB", "MiB", "GiB"):
        if size < 1024 or unit == "GiB":
            return f"{size:.1f} {unit}" if unit != "B" else f"{int(size)} B"
        size /= 1024
    return f"{size:.1f} GiB"


def _dir_size(path: Path) -> int:
    """目录内文件总字节；符号链接按 0 计，不跟进去。"""
    if path.is_symlink() or path.is_file():
        try:
            return path.stat().st_size
        except OSError:
            return 0
    total = 0
    for root, dirs, files in os.walk(path):
        dirs[:] = [d for d in dirs if not os.path.islink(os.path.join(root, d))]
        for name in files:
            try:
                total += os.path.getsize(os.path.join(root, name))
            except OSError:
                pass
    return total


def _force_rmtree(path: Path):
    """删除目录/文件；Windows 上遇到只读属性先去掉再删。"""
    if path.is_symlink():
        path.unlink()
        return
    if not path.exists():
        return

    def onerror(func, target, exc_info):
        try:
            os.chmod(target, stat.S_IWRITE)
            func(target)
        except OSError:
            raise exc_info[1]

    if path.is_dir():
        shutil.rmtree(path, onerror=onerror)
    else:
        try:
            path.unlink()
        except PermissionError:
            os.chmod(path, stat.S_IWRITE)
            path.unlink()


def _current_target() -> Path | None:
    """workspace/current 指向的 session 目录（相对软链或 Windows junction）。"""
    if not os.path.lexists(CURRENT_LINK):
        return None
    try:
        raw = os.readlink(CURRENT_LINK)
    except OSError:
        return None
    target = Path(raw)
    if not target.is_absolute():
        target = WORKSPACE / target
    try:
        return target.resolve()
    except OSError:
        return None


def cleanup_workspace(dry_run: bool = False, log=print) -> int:
    """只留 current → 最新 session/STATUS.md，其余目录与文件全部删掉。

    Returns: 释放的字节数（dry-run 时为预计值）。
    """
    if not WORKSPACE.is_dir():
        return 0

    entries = sorted(WORKSPACE.iterdir(), key=lambda p: p.name)
    keep = _current_target()
    if keep is None or not keep.is_dir():
        sessions = [
            p for p in entries
            if p.is_dir() and not p.is_symlink() and p.name.startswith("session_")
        ]
        keep = sessions[-1] if sessions else None
    keep_name = keep.name if keep else ""

    freed = 0
    for entry in entries:
        if entry.name == "current" and os.path.lexists(entry):
            continue
        if entry.is_dir() and not entry.is_symlink() and entry.name == keep_name:
            for child in sorted(entry.iterdir(), key=lambda p: p.name):
                if child.name in KEEP_NAMES:
                    continue
                freed += _dir_size(child)
                if not dry_run:
                    try:
                        _force_rmtree(child)
                    except OSError as e:
                        log(f"[warn] 删除失败 {child}：{e}")
            continue
        freed += _dir_size(entry)
        if not dry_run:
            try:
                _force_rmtree(entry)
            except OSError as e:
                log(f"[warn] 删除失败 {entry}：{e}")
    return freed


def cleanup_engine_sessions(dry_run: bool = False, log=print) -> int:
    """清空 IAF_AI/dispatch/*/sessions 与 staging。

    每个 read_page 会话的 history.jsonl 都存着一整段 20 张 base64 PNG，
    单本 400 页的书能堆到几个 GiB；续跑靠 notes/ 的文件长度判断，
    不依赖这些会话档，所以可以整目录清空。
    """
    if not ENGINE_DISPATCH.is_dir():
        return 0
    freed = 0
    for dispatch_dir in sorted(ENGINE_DISPATCH.iterdir()):
        if not dispatch_dir.is_dir():
            continue
        for name in ("sessions", "staging"):
            root = dispatch_dir / name
            if not root.is_dir():
                continue
            for child in sorted(root.iterdir(), key=lambda p: p.name):
                freed += _dir_size(child)
                if not dry_run:
                    try:
                        _force_rmtree(child)
                    except OSError as e:
                        log(f"[warn] 删除失败 {child}：{e}")
    return freed


def cleanup_output(book_dir: Path, deliver_root: Path | None = None,
                   dry_run: bool = False, log=print) -> int:
    """删掉 output/{书名}/；deliverables 里没有完整版时跳过。"""
    book_dir = Path(book_dir)
    if not book_dir.is_dir():
        return 0
    book = book_dir.name
    delivered = (Path(deliver_root) if deliver_root else DEFAULT_DELIVER_ROOT) / book / f"{book}.md"
    if not delivered.is_file():
        log(f"[clean] 跳过 output/{book}/：deliverables 里没有 {book}.md，保留以便交付/续跑")
        return 0
    freed = _dir_size(book_dir)
    if dry_run:
        log(f"[clean] 将删除 output/{book}/（{human_size(freed)}）")
        return freed
    try:
        _force_rmtree(book_dir)
    except OSError as e:
        log(f"[warn] 删除 output/{book}/ 失败：{e}")
        return 0
    log(f"[clean] 已删除 output/{book}/（{human_size(freed)}）")
    return freed


def cleanup_after_book(book: str | None,
                       deliver_root: Path | None = None,
                       keep_output: bool = False,
                       keep_sessions: bool = False,
                       dry_run: bool = False,
                       log=print) -> dict:
    """一本书交付成功后的总清理。返回各项释放字节数。"""
    result = {"output": 0, "workspace": 0, "engine": 0}
    if not keep_output and book:
        result["output"] = cleanup_output(
            OUTPUT_ROOT / book, deliver_root, dry_run=dry_run, log=log
        )
    if not keep_sessions:
        result["workspace"] = cleanup_workspace(dry_run=dry_run, log=log)
        result["engine"] = cleanup_engine_sessions(dry_run=dry_run, log=log)
    total = sum(result.values())
    if total:
        verb = "预计释放" if dry_run else "释放"
        log(f"[clean] {verb} {human_size(total)}（output {human_size(result['output'])} · "
            f"workspace {human_size(result['workspace'])} · "
            f"引擎会话 {human_size(result['engine'])}）")
    return result
