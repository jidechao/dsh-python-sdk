"""Session index: scan the JSONL session root for resumable conversations."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class SessionSummary:
    session_id: str
    title: str
    user_messages: int
    assistant_messages: int
    path: Path
    mtime: float
    size: int


def _iter_events(path: Path):
    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    yield json.loads(line)
                except ValueError:
                    continue
    except OSError:
        return


def _unwrap(record: dict) -> dict:
    """Accept both a bare event and a JSON-RPC notification envelope."""
    if record.get("method") == "session.event":
        event = record.get("params", {}).get("event")
        return event if isinstance(event, dict) else {}
    return record


def summarize(path: Path) -> SessionSummary:
    # Persistence layout: <root>/<cwd-slug>/<session-id>/session.jsonl — the
    # session id is the parent directory name, not the file stem.
    summary = SessionSummary(
        session_id=path.parent.name if path.stem == "session" else path.stem,
        title="",
        user_messages=0,
        assistant_messages=0,
        path=path,
        mtime=path.stat().st_mtime,
        size=path.stat().st_size,
    )
    for raw in _iter_events(path):
        event = _unwrap(raw) if isinstance(raw, dict) else {}
        event_type = event.get("type")
        if event_type == "session/title":
            data = event.get("data") or {}
            title = str(data.get("title") or "")
            if title:
                summary.title = title
        elif event_type == "user/message":
            summary.user_messages += 1
        elif event_type == "assistant/message":
            summary.assistant_messages += 1
    return summary


def list_sessions(root: Path, limit: int = 20) -> list[SessionSummary]:
    if not root.is_dir():
        return []
    summaries = [summarize(path) for path in sorted(root.rglob("*.jsonl")) if path.is_file()]
    summaries.sort(key=lambda s: s.mtime, reverse=True)
    return summaries[:limit]


def find_session(root: Path, prefix: str) -> SessionSummary | None:
    """Match a session id by exact name or unambiguous prefix."""
    sessions = list_sessions(root, limit=500)
    exact = [s for s in sessions if s.session_id == prefix]
    if exact:
        return exact[0]
    partial = [s for s in sessions if s.session_id.startswith(prefix)]
    return partial[0] if len(partial) == 1 else None
