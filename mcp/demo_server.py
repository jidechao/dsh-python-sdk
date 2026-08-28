#!/usr/bin/env python3
"""Minimal stdio MCP server for the Mini Agent demo: one `echo` tool.

Implements just enough of the Model Context Protocol (JSON-RPC 2.0 over
newline-delimited stdio) to demonstrate the dsh-mcp-client bridge:
initialize → notifications/initialized → tools/list → tools/call.

Wire it into agent.cordis.yml:

    - id: mcp-demo
      name: '@deepseek-ai/dsh-mcp-client'
      config:
        serverName: demo
        transport: stdio
        command: python   # or the venv interpreter path
        args: [mcp/demo_server.py]

The model then sees a native tool named `mcp__demo__echo`.
"""

from __future__ import annotations

import json
import sys
import time

TOOL = {
    "name": "echo",
    "description": "Echo the given text back with a server-side timestamp.",
    "inputSchema": {
        "type": "object",
        "properties": {"text": {"type": "string", "description": "Text to echo"}},
        "required": ["text"],
    },
}


def send(payload: dict) -> None:
    sys.stdout.write(json.dumps(payload, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def handle(request: dict) -> None:
    method = request.get("method")
    request_id = request.get("id")
    if method == "initialize":
        send({
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                # Echo the client's requested version to negotiate cleanly.
                "protocolVersion": (request.get("params") or {}).get("protocolVersion", "2024-11-05"),
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "mini-demo", "version": "1.0.0"},
            },
        })
    elif method == "notifications/initialized":
        pass  # notification — no response
    elif method == "tools/list":
        send({"jsonrpc": "2.0", "id": request_id, "result": {"tools": [TOOL]}})
    elif method == "tools/call":
        params = request.get("params") or {}
        text = str((params.get("arguments") or {}).get("text", ""))
        send({
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "content": [{"type": "text", "text": f"echo @ {time.strftime('%H:%M:%S')}: {text}"}],
                "isError": False,
            },
        })
    elif request_id is not None:
        send({"jsonrpc": "2.0", "id": request_id,
              "error": {"code": -32601, "message": f"unknown method {method}"}})


def main() -> int:
    for stream in (sys.stdin, sys.stdout):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001 — cosmetic only
            pass
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            handle(json.loads(line))
        except ValueError:
            continue
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
