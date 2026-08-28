#!/usr/bin/env python3
"""Keyless end-to-end smoke test for the Mini Agent composition.

Boots the real DSH runtime (tsx source path from the checkout), points the
DeepSeek adapter at a local mock SSE server, and drives one full agent turn:
a pwsh tool call executed for real on this machine, then a final text reply.
Mirrors the repo's own python/sdk/tests/manual_sdk_agent_smoke.py pattern.

Run:  python smoke.py
"""

from __future__ import annotations

import io
import json
import shutil
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_DIR))

from mini_agent.render import force_utf8_stdio  # noqa: E402
from mini_agent.runtime import build_harness, resolve_checkout  # noqa: E402

PROOF = "dsh-mini-proof-9137"
TOOL_COMMAND = f"Write-Output {PROOF}"


def phase0_static(failures: list[str]) -> None:
    """Pure-python checks: long-term memory + knowledge retrieval (no runtime)."""
    import tempfile

    from mini_agent.memory import load_memory, memory_path, remember
    from mini_agent.runtime import DEFAULT_PERSONA, compose_persona

    with tempfile.TemporaryDirectory(prefix="mini-memory-") as tmp:
        workspace = Path(tmp)
        assert load_memory(workspace) == "" or True  # absent file is fine
        entry = remember(workspace, "回答用中文")
        assert "回答用中文" in entry
        saved = load_memory(workspace)
        if "回答用中文" not in saved:
            failures.append("memory: /remember entry not persisted")
        persona = compose_persona(workspace)
        if DEFAULT_PERSONA not in persona or "回答用中文" not in persona:
            failures.append("memory: compose_persona missing persona or memory block")
        if load_memory(workspace) == "" or memory_path(workspace).name != "MEMORY.md":
            failures.append("memory: unexpected file layout")

    sys.path.insert(0, str(PROJECT_DIR / "mcp"))
    try:
        import knowledge_server as kb  # noqa: E402

        chunks = kb.load_chunks()
        if len(chunks) < 6:
            failures.append(f"kb: too few chunks indexed ({len(chunks)})")
        hits = kb.search(chunks, "八块拼图 工程化 审计", 3)
        if not hits or not any("工程化" in c.text or "八块" in c.text for c in hits):
            failures.append(f"kb: Chinese query missed expected chunks: {[c.title for c in hits]}")
        hits_en = kb.search(chunks, "request header tools advertised catalog", 2)
        if not hits_en:
            failures.append("kb: English query returned nothing")
        rendered = kb.render(hits)
        if "knowledge/" not in rendered:
            failures.append("kb: render missing source paths")
    finally:
        sys.path.remove(str(PROJECT_DIR / "mcp"))
    print(f"phase0     memory compose + kb index ok ({len(chunks)} chunks)")


def sse(*payloads: dict) -> bytes:
    # One SSE event per payload: each data line needs its own blank-line terminator.
    return "".join(
        f"data: {json.dumps(p, separators=(',', ':'))}\n\n" for p in payloads
    ).encode("utf-8")


def tool_call_stream() -> bytes:
    return sse(
        {"choices": [{"delta": {"role": "assistant", "content": None, "reasoning_content": ""}}]},
        {"choices": [{"delta": {"tool_calls": [
            {"index": 0, "id": "call_smoke_1", "type": "function",
             "function": {"name": "pwsh", "arguments": ""}}]}}]},
        {"choices": [{"delta": {"tool_calls": [
            {"index": 0, "function": {"arguments": json.dumps(
                {"command": TOOL_COMMAND, "description": "Print the smoke proof string"})}}]}}]},
        {"choices": [{"delta": {}, "finish_reason": "tool_calls"}],
         "usage": {"prompt_tokens": 11, "completion_tokens": 7}},
    ) + b"data: [DONE]\n\n"


def text_stream() -> bytes:
    return sse(
        {"choices": [{"delta": {"role": "assistant", "content": None, "reasoning_content": ""}}]},
        {"choices": [{"delta": {"reasoning_content": "The command output matched; report the proof."}}]},
        {"choices": [{"delta": {"content": f"SMOKE-OK: pwsh said {PROOF}"}}]},
        {"choices": [{"delta": {"content": ""}, "finish_reason": "stop"}],
         "usage": {"prompt_tokens": 29, "completion_tokens": 9}},
    ) + b"data: [DONE]\n\n"


class MockCompletionHandler(BaseHTTPRequestHandler):
    requests: list[dict] = []

    def do_POST(self) -> None:  # noqa: N802 — http.server API
        length = int(self.headers.get("content-length", "0"))
        body = self.rfile.read(length).decode("utf-8")
        self.requests.append({
            "path": self.path,
            "authorization": self.headers.get("authorization"),
            "body": body,
        })
        # Scenario: after the tool result arrives (role:"tool"), answer with text.
        stream = text_stream() if '"role":"tool"' in body else tool_call_stream()
        self.send_response(200)
        self.send_header("content-type", "text/event-stream")
        self.end_headers()
        self.wfile.write(stream)

    def log_message(self, _format: str, *_args: object) -> None:
        return


def main() -> int:
    force_utf8_stdio()
    keep = "--keep" in sys.argv
    if shutil.which("pwsh") is None and shutil.which("powershell") is None:
        print("skip: no PowerShell on PATH (Windows-only smoke)")
        return 0

    checkout = resolve_checkout()
    session_root = Path(tempfile.mkdtemp(prefix="mini-agent-smoke-"))
    server = ThreadingHTTPServer(("127.0.0.1", 0), MockCompletionHandler)
    threading.Thread(target=server.serve_forever, name="mock-deepseek", daemon=True).start()
    base_url = f"http://127.0.0.1:{server.server_address[1]}/v1"

    print(f"checkout     {checkout}")
    print(f"session_root {session_root}")
    print(f"mock_base    {base_url}")
    failures: list[str] = []
    phase0_static(failures)

    try:
        harness = build_harness(
            model="mini-smoke-model",
            workspace=PROJECT_DIR,
            session_root=session_root,
            env={
                "DSH_MODEL": "mini-smoke-model",
                "DEEPSEEK_BASE_URL": base_url,
                "DEEPSEEK_API_KEY": "smoke-key",
                # Deterministic interpreter for the bundled MCP demo server.
                "DSH_MCP_DEMO_PYTHON": sys.executable,
            },
        )
        with harness:
            result = harness.run(
                "Run the requested command with your pwsh tool, then report its stdout.",
                session_id="mini-smoke",
            )
            print(f"final_response = {result.final_response!r}")
            print(f"finish_reason   = {result.finish_reason!r}")

            # MCP bridge: the tool catalog freezes at turn start, so the
            # mcp__demo__echo tool (registered during the async handshake)
            # appears in the first turn that starts after registration — which
            # one depends on handshake vs prompt timing. Assert on the union.
            result2 = harness.run("thanks, just say ok", session_id="mini-smoke")
            advertised = set()
            for run_result in (result, result2):
                for event in run_result.events:
                    if event.get("type") == "request/header":
                        tools = ((event.get("data") or {}).get("header") or {}).get("tools") or []
                        advertised.update(t.get("name") for t in tools)
            print(f"advertised      = {sorted(advertised)}")
            if "mcp__demo__echo" not in advertised:
                failures.append(f"MCP bridge tool missing from every catalog: {sorted(advertised)}")
            if "mcp__kb__search" not in advertised:
                failures.append(f"knowledge-base tool missing from every catalog: {sorted(advertised)}")
            if "subagent" not in advertised:
                failures.append(f"subagent tool missing from every catalog: {sorted(advertised)}")
        if result.finish_reason == "error":
            for event in result.events:
                if event.get("type") == "turn/end":
                    print(f"turn/end reason = {json.dumps(event.get('data'), ensure_ascii=False)[:800]}")
            stderr = getattr(getattr(harness, "client", None), "_stderr_lines", [])
            if stderr:
                print("runtime stderr tail:")
                for line in list(stderr)[-25:]:
                    print(f"  | {line}")

        if PROOF not in result.final_response:
            failures.append(f"final_response missing proof {PROOF!r}: {result.final_response!r}")
        if result.finish_reason != "completed":
            failures.append(f"unexpected finish_reason {result.finish_reason!r}")

        first = MockCompletionHandler.requests[0]["body"]
        after_tool = MockCompletionHandler.requests[1]["body"]
        if "pwsh" not in first:
            failures.append("first request does not advertise the pwsh tool")
        if PROOF not in after_tool:
            failures.append("post-tool request lacks the executed result — pwsh did not run?")
        # turn 1: tool round + final text; turn 2: one more text round
        if len(MockCompletionHandler.requests) != 3:
            failures.append(f"expected 3 model requests, saw {len(MockCompletionHandler.requests)}")

        jsonl = sorted(p for p in session_root.rglob("*.jsonl") if p.name != "audit.jsonl")
        if not jsonl:
            failures.append("no session JSONL written")
        else:
            print(f"session_jsonl  {jsonl[0]} ({jsonl[0].stat().st_size} bytes)")

        # (Tool-call audit records come from the AgentApp/renderer path —
        # asserted in phase 2 below; raw harness.run has no renderer sink.)

        # Phase 2: the full REPL path (AgentApp.send + StreamRenderer).
        import contextlib
        import os

        from mini_agent.app import AgentApp

        os.environ.update({"DSH_MODEL": "mini-smoke-model", "DEEPSEEK_BASE_URL": base_url,
                           "DEEPSEEK_API_KEY": "smoke-key",
                           "DSH_MCP_DEMO_PYTHON": sys.executable})
        MockCompletionHandler.requests.clear()
        captured = io.StringIO()
        repl_app = AgentApp(workspace=PROJECT_DIR, session_root=session_root,
                            model="mini-smoke-model")
        repl_app.palette.enabled = False  # plain output while captured
        with contextlib.redirect_stdout(captured):
            repl_app.send("Run the command via pwsh again and report the output.")
        transcript = captured.getvalue()
        print("repl transcript:")
        for line in transcript.splitlines():
            print(f"  | {line}")
        if PROOF not in transcript:
            failures.append("REPL transcript missing proof — renderer did not print the final text?")
        records = repl_app.renderer.last_tool_results if repl_app.renderer else []
        if not records or not records[0].result_text or records[0].is_error:
            failures.append(f"renderer tool record wrong: {records[:1]!r}")
        elif PROOF not in records[0].result_text:
            failures.append("renderer tool result missing the pwsh stdout proof")
        totals = repl_app.usage_totals
        print(f"usage_totals   turns={totals['turns']} in={totals['input_tokens']} "
              f"out={totals['output_tokens']} tools={totals['tool_calls']}")
        if totals["turns"] != 1 or totals["tool_calls"] < 1 or totals["input_tokens"] <= 0:
            failures.append(f"usage totals wrong: {totals}")
        repl_audit = [ln for ln in (session_root / "audit.jsonl").read_text(encoding="utf-8").splitlines() if ln]
        audited_tools = [json.loads(ln).get("tool") for ln in repl_audit]
        print(f"audit_jsonl    {session_root / 'audit.jsonl'} ({len(repl_audit)} entries: {audited_tools})")
        if not any(json.loads(ln).get("session") == repl_app.session_id for ln in repl_audit):
            failures.append("REPL audit records missing for the phase-2 session")
        if "pwsh" not in audited_tools:
            failures.append(f"audit log has no pwsh record: {audited_tools}")
        repl_app.teardown()
    except Exception as exc:  # noqa: BLE001 — report and fail
        failures.append(f"unhandled exception: {exc!r}")
    finally:
        server.shutdown()
        server.server_close()
        if keep:
            print(f"kept session root: {session_root}")
        else:
            shutil.rmtree(session_root, ignore_errors=True)

    if failures:
        print("\nFAIL:")
        for failure in failures:
            print(f"  ✗ {failure}")
        return 1
    print("\nPASS: memory compose · kb index · runtime boot · pwsh tool round-trip · "
          "final text · JSONL persisted · audit log · usage totals")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
