"""Tool-call audit log: append-only JSONL under the session root.

The engineering puzzle piece's "audit" requirement in its smallest form:
every completed tool call (from the SDK notification stream) becomes one
JSON line — who (session), what (tool + argument digest), how long, how
big, and whether it errored. Failures to write never break the REPL.
"""

from __future__ import annotations

import datetime as _dt
import json
from pathlib import Path

from mini_agent.render import ToolRecord

ARGS_DIGEST_CHARS = 200


class AuditLog:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    def record(self, session_id: str, record: ToolRecord) -> None:
        entry = {
            "ts": _dt.datetime.now().isoformat(timespec="seconds"),
            "session": session_id,
            "tool": record.name,
            "args": record.arguments[:ARGS_DIGEST_CHARS],
            "is_error": record.is_error,
            "ms": round(((record.finished or record.started) - record.started) * 1000),
            "chars": len(record.result_text),
        }
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except OSError:
            pass  # auditing must never break the conversation

    def read_tail(self, count: int) -> list[dict]:
        try:
            lines = self.path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return []
        entries: list[dict] = []
        for line in lines[-count:]:
            try:
                entries.append(json.loads(line))
            except ValueError:
                continue
        return entries
