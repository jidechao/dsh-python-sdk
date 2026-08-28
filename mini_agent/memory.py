"""Long-term memory: one Markdown file reloaded into every session's persona.

Implements the Memory puzzle piece from the "eight blocks" article as its
smallest honest form: a single ``memory/MEMORY.md`` inside the workspace,
injected into the system prompt at runtime start. The file is the source of
truth — ``/remember`` appends to it, and the model itself may edit it with
its file tools. Changes take effect the next time the runtime boots.
"""

from __future__ import annotations

import datetime as _dt
from pathlib import Path

MEMORY_DIR = "memory"
MEMORY_FILE = "MEMORY.md"
MAX_INJECTED_CHARS = 2048
FACTS_HEADER = "## 项目事实"

DEFAULT_TEMPLATE = """\
# Mini Agent 长期记忆

跨会话持久的事实与偏好（《八块拼图》Memory 块的最小实现）。
启动时整体注入系统提示词（截断 {limit} 字符）；`/remember <text>` 追加条目，
或让模型在对话中直接编辑本文件（重启后生效）。

## 用户偏好

## 项目事实
""".format(limit=MAX_INJECTED_CHARS)


def memory_path(workspace: Path) -> Path:
    return workspace / MEMORY_DIR / MEMORY_FILE


def load_memory(workspace: Path) -> str:
    """Return the trimmed memory body ('' when absent or empty)."""
    try:
        text = memory_path(workspace).read_text(encoding="utf-8")
    except OSError:
        return ""
    return text.strip()[:MAX_INJECTED_CHARS]


def ensure_memory_file(workspace: Path) -> Path:
    """Create the memory file with a template on first use; return its path."""
    path = memory_path(workspace)
    if not path.is_file():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(DEFAULT_TEMPLATE, encoding="utf-8")
    return path


def remember(workspace: Path, text: str) -> str:
    """Append one dated entry under the facts header; return the entry line."""
    text = text.strip()
    if not text:
        return ""
    path = ensure_memory_file(workspace)
    content = path.read_text(encoding="utf-8")
    stamp = _dt.date.today().isoformat()
    entry = f"- [{stamp}] {text}"
    lines = content.splitlines()
    insert_at = None
    for index, line in enumerate(lines):
        if line.strip() == FACTS_HEADER:
            insert_at = index + 1
            break
    if insert_at is None:
        if lines and lines[-1].strip():
            lines.append("")
        lines.extend([FACTS_HEADER, entry])
    else:
        lines.insert(insert_at, entry)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return entry
