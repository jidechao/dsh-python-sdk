"""AgentApp: REPL state and the harness lifecycle around Session.run()."""

from __future__ import annotations

import os
import uuid
from pathlib import Path

from mini_agent.audit import AuditLog
from mini_agent.render import Palette, StreamRenderer, ToolRecord, make_palette
from mini_agent.runtime import (
    CORDIS_CONFIG,
    DEFAULT_MODEL,
    DEFAULT_PROVIDER,
    SKILLS_DIR,
    build_harness,
)


class AgentApp:
    def __init__(
        self,
        *,
        workspace: Path,
        session_root: Path,
        model: str | None = None,
        session_id: str | None = None,
        max_tokens: int | None = None,
    ) -> None:
        self.workspace = workspace.resolve()
        self.session_root = session_root.resolve()
        self.model = model or os.environ.get("DSH_MODEL") or DEFAULT_MODEL
        self.provider = DEFAULT_PROVIDER
        self.max_tokens = max_tokens
        self.session_id = session_id or self._fresh_session_id()
        self.cordis = CORDIS_CONFIG
        self.skills_dir = SKILLS_DIR
        self.palette: Palette = make_palette()
        self.renderer: StreamRenderer | None = None
        self._harness = None  # lazily created; recreated after /model or interrupt
        self.audit = AuditLog(self.session_root / "audit.jsonl")
        self.usage_totals = {
            "turns": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            "tool_calls": 0,
            "tool_errors": 0,
            "per_tool": {},
        }

    # ── lifecycle ─────────────────────────────────────────────────────────

    @staticmethod
    def _fresh_session_id() -> str:
        stamp = uuid.uuid4().hex[:6]
        return f"mini-{stamp}"

    def ensure_harness(self):
        if self._harness is None:
            self._harness = build_harness(
                model=self.model,
                workspace=self.workspace,
                session_root=self.session_root,
                max_tokens=self.max_tokens,
            )
            self._harness.start()
        return self._harness

    def teardown(self) -> None:
        """Close the runtime subprocess; the next prompt rebuilds it lazily."""
        if self._harness is not None:
            try:
                self._harness.close()
            except Exception:  # noqa: BLE001 — teardown must never raise
                pass
            self._harness = None

    # ── commands support ──────────────────────────────────────────────────

    def rotate_session(self) -> None:
        self.session_id = self._fresh_session_id()
        self.print(f"→ new session {self.session_id}")

    def resume_session(self, session_id: str) -> None:
        self.teardown()
        self.session_id = session_id
        self.print(
            f"→ switched to session {session_id}\n"
            "  (same REPL run keeps full context; after a restart the JSONL log "
            "continues under this id but the model starts a fresh context)"
        )

    def set_model(self, model: str) -> None:
        self.teardown()
        self.model = model
        self.print(f"→ model switched to {model}; runtime restarts on the next message")

    # ── one conversation turn ─────────────────────────────────────────────

    def _on_tool_record(self, record: ToolRecord) -> None:
        """Audit + usage sink: one call per completed tool record."""
        self.audit.record(self.session_id, record)
        totals = self.usage_totals
        totals["tool_calls"] += 1
        totals["tool_errors"] += 1 if record.is_error else 0
        per_tool = totals["per_tool"]
        per_tool[record.name] = per_tool.get(record.name, 0) + 1

    def _collect_usage(self, renderer: StreamRenderer) -> None:
        totals = self.usage_totals
        totals["input_tokens"] += renderer.state.total_input_tokens
        totals["output_tokens"] += renderer.state.total_output_tokens

    def send(self, text: str) -> None:
        harness = self.ensure_harness()
        renderer = StreamRenderer(self.palette, on_tool_record=self._on_tool_record)
        self.renderer = renderer
        renderer.begin_turn()
        try:
            result = harness.run(text, session_id=self.session_id, on_notification=renderer)
        except KeyboardInterrupt:
            self.teardown()
            self._collect_usage(renderer)
            self.print(self.palette.yellow("\n⚠ interrupted — runtime stopped; next message restarts it"))
            return
        except Exception as exc:  # noqa: BLE001 — surface, keep REPL alive
            self.teardown()
            self.print(self.palette.red(f"\nerror: {exc}"))
            self.print(self.palette.dim("the runtime was stopped; next message restarts it"))
            return
        self._collect_usage(renderer)
        self.usage_totals["turns"] += 1
        renderer.end_turn(result.finish_reason)
        if not result.final_response.strip():
            self.print(self.palette.dim("(no assistant text in this interval)"))

    # ── output helper ─────────────────────────────────────────────────────

    def print(self, *parts: str) -> None:
        print(*parts)
