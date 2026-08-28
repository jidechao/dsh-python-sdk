#!/usr/bin/env python3
"""Mini Agent REPL — a simplified coding agent on the DeepSeek Harness SDK.

Usage:
    python repl.py [--workspace DIR] [--session-root DIR] [--session-id ID]
                   [--model NAME] [--max-tokens N] [--check]

Requires a deepseek-harness checkout (DSH_CHECKOUT, default
D:\\project\\Harness\\deepseek-harness) with Node >= 22.19 and tsx installed.
Set DEEPSEEK_API_KEY (and optionally DEEPSEEK_BASE_URL) for real model calls;
run smoke.py for a keyless end-to-end verification.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_DIR))

from mini_agent.app import AgentApp  # noqa: E402
from mini_agent.commands import dispatch  # noqa: E402
from mini_agent.render import enable_windows_vt, force_utf8_stdio  # noqa: E402
from mini_agent.runtime import (  # noqa: E402
    CORDIS_CONFIG,
    DEFAULT_MODEL,
    check_environment,
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="mini-agent", description=__doc__.splitlines()[0])
    parser.add_argument("--workspace", type=Path, default=Path.cwd(), help="agent workspace (default: cwd)")
    parser.add_argument("--session-root", type=Path, default=PROJECT_DIR / ".mini-sessions")
    parser.add_argument("--session-id", help="continue an existing session")
    parser.add_argument("--model", default=None, help=f"default {DEFAULT_MODEL!r}; env DSH_MODEL also works")
    parser.add_argument("--max-tokens", type=int, default=None)
    parser.add_argument("--safe", action="store_true",
                        help="sandbox to workspace-write (default: danger-full-access)")
    parser.add_argument("--check", action="store_true", help="run environment diagnostics and exit")
    return parser.parse_args(argv)


def banner(app: AgentApp, sandbox_mode: str) -> None:
    p = app.palette
    tool = "pwsh" if sys.platform == "win32" else "bash"
    print(p.bold("Mini Agent") + p.dim(" — simplified REPL agent on DeepSeek Harness SDK"))
    print(p.dim(f"  model {app.model} · workspace {app.workspace}"))
    print(p.dim(f"  session {app.session_id} · shell tool {tool} · sandbox {sandbox_mode}"))
    print(p.dim(f"  composition {CORDIS_CONFIG}"))
    print(p.dim("  type /help for commands · /exit to quit · trailing \\\\ continues a line"))


def read_message() -> str | None:
    """Read one input, supporting backslash line continuation."""
    chunks: list[str] = []
    while True:
        try:
            line = input("› " if not chunks else "… ")
        except EOFError:
            print()
            return None
        if line.endswith("\\"):
            chunks.append(line[:-1])
            continue
        chunks.append(line)
        message = "\n".join(chunks)
        return message.lstrip("\ufeff").rstrip("\r")


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    force_utf8_stdio()
    enable_windows_vt()

    if args.check:
        failed = False
        for check in check_environment():
            mark = "✓" if check.ok else "✗"
            print(f" {mark} {check.label:<20} {check.detail}")
            failed = failed or not check.ok
        return 1 if failed else 0

    # --safe narrows the sandbox to workspace-write before any runtime boot.
    sandbox_mode = "danger-full-access"
    if args.safe:
        import os

        os.environ["DSH_SANDBOX_MODE"] = "workspace-write"
        sandbox_mode = "workspace-write"

    app = AgentApp(
        workspace=args.workspace,
        session_root=args.session_root,
        model=args.model,
        session_id=args.session_id,
        max_tokens=args.max_tokens,
    )
    banner(app, sandbox_mode)

    # Eager start: boot the runtime (and MCP handshakes) while the user reads
    # the banner, so late-registering tools are visible from the first turn.
    print(app.palette.dim("runtime starting…"), flush=True)
    try:
        app.ensure_harness()
        print(app.palette.dim("runtime ready"), flush=True)
    except Exception as exc:  # noqa: BLE001 — keep the REPL alive for /doctor
        print(app.palette.yellow(f"runtime failed to start ({exc}); /doctor may help — retrying on the next message"), flush=True)

    while True:
        try:
            message = read_message()
        except KeyboardInterrupt:
            print("\n(interrupted — /exit to quit)")
            continue
        if message is None:
            break
        stripped = message.strip()
        if not stripped:
            continue
        if dispatch(app, message):
            continue
        app.send(stripped)

    app.teardown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
