"""Streaming renderer: turns SDK session notifications into REPL output.

Consumes the notification vocabulary documented by the jsonrpc-agent example
snapshots: assistant/chunk (block-start / reasoning-delta / text-delta /
tool-call-delta / block-end / usage / finish), tool/call, tool/result,
turn/start, turn/end — and keeps the last tool results for ``/last``.
"""

from __future__ import annotations

import sys
import time
from dataclasses import dataclass, field

REASONING_PREVIEW_CHARS = 400
TOOL_LINE_WIDTH = 100


class Palette:
    """ANSI palette that degrades to plain text when unsupported."""

    def __init__(self, enabled: bool) -> None:
        self.enabled = enabled

    def _wrap(self, code: str, text: str) -> str:
        return f"\x1b[{code}m{text}\x1b[0m" if self.enabled else text

    def dim(self, text: str) -> str:
        return self._wrap("2", text)

    def bold(self, text: str) -> str:
        return self._wrap("1", text)

    def cyan(self, text: str) -> str:
        return self._wrap("36", text)

    def green(self, text: str) -> str:
        return self._wrap("32", text)

    def red(self, text: str) -> str:
        return self._wrap("31", text)

    def yellow(self, text: str) -> str:
        return self._wrap("33", text)


def make_palette(stream=None) -> Palette:
    stream = stream or sys.stdout
    if os_environ_flag("NO_COLOR"):
        return Palette(False)
    return Palette(bool(getattr(stream, "isatty", lambda: False)()))


def os_environ_flag(name: str) -> bool:
    import os

    return os.environ.get(name, "") not in ("", "0", "false")


def enable_windows_vt() -> None:
    """Enable VT processing on classic Windows consoles (no-op elsewhere)."""
    if sys.platform != "win32":
        return
    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        handle = kernel32.GetStdHandle(-11)
        mode = ctypes.c_uint32()
        if kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            kernel32.SetConsoleMode(handle, mode.value | 0x0004)
    except Exception:  # noqa: BLE001 — cosmetic only
        pass


def force_utf8_stdio() -> None:
    """Reconfigure stdio to UTF-8 so ✓/⚙/Chinese never crash on cp936 consoles.

    Covers piped stdin too: PowerShell pipes UTF-8 (with BOM) while Python
    decodes pipes with the GBK locale — the mismatch mangles the first line.
    """
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001 — cosmetic only
            pass


@dataclass(slots=True)
class ToolRecord:
    name: str
    arguments: str
    result_text: str = ""
    is_error: bool = False
    started: float = field(default_factory=time.monotonic)
    finished: float | None = None


@dataclass
class RendererState:
    in_reasoning: bool = False
    reasoning_shown: int = 0
    turn_steps: int = 0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    open_tool_lines: int = 0
    midline: bool = False  # cursor is mid-line (streamed text without newline)


class StreamRenderer:
    """Callable ``on_notification`` handler printing a live transcript."""

    def __init__(self, palette: Palette | None = None, out=None,
                 on_tool_record=None) -> None:
        self.palette = palette or make_palette()
        self.out = out or sys.stdout
        self.state = RendererState()
        self.last_tool_results: list[ToolRecord] = []
        self._pending_calls: dict[str, ToolRecord] = {}
        # Optional sink invoked once per completed tool record (audit hooks).
        self.on_tool_record = on_tool_record

    # ── notification entry ────────────────────────────────────────────────

    def __call__(self, notification) -> None:  # noqa: ANN001 — SDK Notification
        if notification.method != "session.event":
            return
        event = notification.payload.get("event")
        if not isinstance(event, dict):
            return
        handler = getattr(self, f"_on_{event.get('type', '').replace('/', '_')}", None)
        if handler is not None:
            handler(event.get("data") or {})

    # ── lifecycle ─────────────────────────────────────────────────────────

    def begin_turn(self) -> None:
        self.state = RendererState()
        self._pending_calls.clear()
        print(self.palette.dim("─" * 8), file=self.out)

    def end_turn(self, finish_reason: str | None) -> None:
        s = self.state
        if s.midline:
            print(file=self.out)
            s.midline = False
        label = self.palette.yellow(finish_reason) if finish_reason not in (None, "completed") else "done"
        stats = f"steps {s.turn_steps} · in {s.total_input_tokens:,} tok · out {s.total_output_tokens:,} tok"
        print(self.palette.dim(f"⟨{label} · {stats}⟩"), file=self.out)
        if finish_reason == "max-tokens":
            print(self.palette.yellow("⚠ Output hit the max-tokens limit; ask me to continue if truncated."),
                  file=self.out)

    # ── event handlers ────────────────────────────────────────────────────

    def _on_turn_start(self, _data: dict) -> None:
        pass

    def _on_step_start(self, _data: dict) -> None:
        self.state.turn_steps += 1

    def _on_assistant_chunk(self, data: dict) -> None:
        chunk = data.get("chunk") or {}
        kind = chunk.get("type")
        if kind == "block-start":
            block_type = chunk.get("blockType")
            if block_type == "reasoning":
                self.state.in_reasoning = True
                self.state.reasoning_shown = 0
                print(self.palette.dim("· thinking "), end="", file=self.out, flush=True)
        elif kind == "reasoning-delta":
            self._feed_reasoning(str(chunk.get("text") or ""))
        elif kind == "text-delta":
            self._end_reasoning()
            print(str(chunk.get("text") or ""), end="", file=self.out, flush=True)
            self.state.midline = True
        elif kind == "block-end":
            block = chunk.get("block") or {}
            if block.get("type") == "reasoning":
                self._end_reasoning()
        elif kind == "usage":
            usage = chunk.get("usage") or {}
            self.state.total_input_tokens += int(usage.get("inputTokens") or 0)
            self.state.total_output_tokens += int(usage.get("outputTokens") or 0)

    def _feed_reasoning(self, text: str) -> None:
        shown = self.state.reasoning_shown
        room = REASONING_PREVIEW_CHARS - shown
        if room > 0:
            piece = text[:room]
            print(self.palette.dim(piece.replace("\n", " ")), end="", file=self.out, flush=True)
            self.state.reasoning_shown = shown + len(piece)
            self.state.midline = True
            if self.state.reasoning_shown >= REASONING_PREVIEW_CHARS:
                print(self.palette.dim(" …"), end="", file=self.out, flush=True)

    def _end_reasoning(self) -> None:
        if self.state.in_reasoning:
            self.state.in_reasoning = False
            print(file=self.out)
            self.state.midline = False

    def _on_tool_call(self, data: dict) -> None:
        call_id = str(data.get("callId") or "")
        name = str(data.get("name") or "?")
        args = str(data.get("arguments") or "")
        record = ToolRecord(name=name, arguments=args)
        self._pending_calls[call_id] = record
        self.last_tool_results.append(record)
        self.last_tool_results = self.last_tool_results[-20:]
        summary = self._summarize_call(name, args)
        print(f"  {self.palette.cyan('⚙ ' + name)}{summary}", file=self.out)

    def _on_tool_result(self, data: dict) -> None:
        message = (data.get("message") or {})
        source = message.get("source") or {}
        call_id = str(source.get("callId") or "")
        record = self._pending_calls.pop(call_id, None)
        if record is None:
            record = ToolRecord(name="?", arguments="")
            self.last_tool_results.append(record)
        record.finished = time.monotonic()
        text, is_error = self._extract_result_text(message)
        record.result_text = text
        record.is_error = is_error
        elapsed = (record.finished - record.started) * 1000
        if self.on_tool_record is not None:
            try:
                self.on_tool_record(record)
            except Exception:  # noqa: BLE001 — a sink must never break rendering
                pass
        if is_error:
            tag = self.palette.red(f"✗ {elapsed:.0f}ms error")
        else:
            tag = self.palette.green(f"✓ {elapsed:.0f}ms · {len(text):,} chars")
        print(f"    {tag}", file=self.out)

    # ── helpers ───────────────────────────────────────────────────────────

    @staticmethod
    def _summarize_call(name: str, args_json: str) -> str:
        import json

        try:
            args = json.loads(args_json) if args_json else {}
        except ValueError:
            return " " + (args_json or "")[:TOOL_LINE_WIDTH]
        if not isinstance(args, dict):
            return f" {args_json[:TOOL_LINE_WIDTH]}"
        for key in ("command", "path", "file_path", "pattern", "name", "prompt"):
            if key in args:
                value = str(args[key]).replace("\n", "⏎")
                shown = value[:TOOL_LINE_WIDTH] + ("…" if len(value) > TOOL_LINE_WIDTH else "")
                return f"({key}={shown})"
        keys = ", ".join(sorted(args)) or "no args"
        return f"({keys})"

    @staticmethod
    def _extract_result_text(message: dict) -> tuple[str, bool]:
        content = message.get("content")
        if not isinstance(content, list):
            return "", False
        parts: list[str] = []
        is_error = False
        for block in content:
            if not isinstance(block, dict) or block.get("type") != "tool-result":
                continue
            is_error = is_error or bool(block.get("isError"))
            for piece in block.get("content") or []:
                if isinstance(piece, dict) and piece.get("type") == "text":
                    parts.append(str(piece.get("text") or ""))
        return "\n".join(parts), is_error
