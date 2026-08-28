"""Slash commands for the mini-agent REPL."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover — import cycle guard
    from mini_agent.app import AgentApp


def cmd_help(app: "AgentApp", args: str) -> None:
    palette = app.palette
    print(palette.bold("commands"))
    for name, (_, help_text) in sorted(COMMANDS.items()):
        print(f"  {palette.cyan(name):<18} {help_text}")


def cmd_new(app: "AgentApp", args: str) -> None:
    app.rotate_session()


def cmd_sessions(app: "AgentApp", args: str) -> None:
    from mini_agent.sessions import list_sessions

    sessions = list_sessions(app.session_root)
    if not sessions:
        print(app.palette.dim(f"no sessions under {app.session_root}"))
        return
    print(app.palette.bold(f"{'session':<28} {'msgs':>9}  {'updated':<16} title"))
    for s in sessions:
        stamp = time.strftime("%Y-%m-%d %H:%M", time.localtime(s.mtime))
        msgs = f"{s.user_messages}/{s.assistant_messages}"
        marker = "*" if s.session_id == app.session_id else " "
        print(f"{marker}{s.session_id:<27} {msgs:>9}  {stamp:<16} {s.title}")


def cmd_resume(app: "AgentApp", args: str) -> None:
    from mini_agent.sessions import find_session

    target = args.strip()
    if not target:
        print("usage: /resume <session-id-prefix>")
        return
    found = find_session(app.session_root, target)
    if found is None:
        print(app.palette.red(f"no unique session matches {target!r} — see /sessions"))
        return
    app.resume_session(found.session_id)


def cmd_model(app: "AgentApp", args: str) -> None:
    name = args.strip()
    if not name:
        print(f"model: {app.model} (provider {app.provider})")
        return
    app.set_model(name)


def cmd_cwd(app: "AgentApp", args: str) -> None:
    print(f"workspace: {app.workspace}")
    print(f"session root: {app.session_root}")


def cmd_system(app: "AgentApp", args: str) -> None:
    import os

    persona = os.environ.get(
        "DSH_SYSTEM_PROMPT",
        "You are Mini, a concise coding agent. Prefer reading before editing, "
        "verify changes by running commands, and keep replies short and structured.",
    )
    from mini_agent.memory import load_memory

    sandbox = os.environ.get("DSH_SANDBOX_MODE", "danger-full-access")
    memory = load_memory(app.workspace)
    print(app.palette.bold("composition"))
    print(f"  cordis:     {app.cordis}")
    print(f"  provider:   {app.provider}")
    print(f"  model:      {app.model}")
    print(f"  persona:    {persona[:120]}{'…' if len(persona) > 120 else ''}")
    print(f"  workspace:  {app.workspace} (AGENTS.md/CLAUDE.md layered, 8 KiB budget)")
    print(f"  skills:     {app.skills_dir}")
    print(f"  memory:     {len(memory)} chars from memory/MEMORY.md (persona-injected)")
    print(f"  knowledge:  knowledge/*.md via mcp__kb__search (agentic RAG)")
    print(f"  sandbox:    {sandbox}"
          + ("  (narrowed: writes limited to the workspace)" if sandbox == "workspace-write" else ""))


def cmd_skills(app: "AgentApp", args: str) -> None:
    found = 0
    for skill_dir in sorted(app.skills_dir.glob("*/SKILL.md")):
        found += 1
        name, desc = skill_dir.parent.name, ""
        try:
            text = skill_dir.read_text(encoding="utf-8")
            for line in text.splitlines():
                if line.startswith("description:"):
                    desc = line.split(":", 1)[1].strip()
                    break
        except OSError:
            pass
        print(f"  {app.palette.cyan(name):<24} {desc}")
    if not found:
        print(app.palette.dim(f"no SKILL.md under {app.skills_dir}"))
    else:
        print(app.palette.dim("(name+description enter the prompt; the model loads bodies via the skill tool)"))


def cmd_last(app: "AgentApp", args: str) -> None:
    count = 1
    if args.strip().isdigit():
        count = max(1, int(args.strip()))
    records = app.renderer.last_tool_results[-count:] if app.renderer else []
    if not records:
        print(app.palette.dim("no tool results yet"))
        return
    for record in records:
        header = f"{record.name} {record.arguments}"
        print(app.palette.bold(f"── {header[:160]}"))
        print(record.result_text or "(empty)")


def cmd_memory(app: "AgentApp", args: str) -> None:
    from mini_agent.memory import load_memory, memory_path

    text = load_memory(app.workspace)
    if not text:
        print(app.palette.dim(f"no long-term memory yet — create entries with /remember "
                              f"(file: {memory_path(app.workspace)})"))
        return
    print(app.palette.bold(f"long-term memory ({memory_path(app.workspace)}):"))
    print(text)


def cmd_remember(app: "AgentApp", args: str) -> None:
    from mini_agent.memory import remember

    text = args.strip()
    if not text:
        print("usage: /remember <durable fact or preference>")
        return
    entry = remember(app.workspace, text)
    print(f"recorded: {entry}")
    print(app.palette.dim("the live runtime keeps its current persona; "
                          "the entry loads on the next runtime start (/new keeps context, restart reloads)"))


def cmd_audit(app: "AgentApp", args: str) -> None:
    from mini_agent.audit import AuditLog

    count = 10
    if args.strip().isdigit():
        count = max(1, int(args.strip()))
    entries = AuditLog(app.session_root / "audit.jsonl").read_tail(count)
    if not entries:
        print(app.palette.dim(f"no audit records yet (file: {app.session_root / 'audit.jsonl'})"))
        return
    print(app.palette.bold(f"last {len(entries)} tool calls (audit.jsonl):"))
    for e in entries:
        mark = "✗" if e.get("is_error") else "✓"
        print(f"  {e.get('ts', '')} {mark} {e.get('session', '')} {e.get('tool', '?')} "
              f"({e.get('ms', 0):.0f}ms · {e.get('chars', 0)} chars)")


def cmd_cost(app: "AgentApp", args: str) -> None:
    totals = app.usage_totals
    if not totals["turns"]:
        print(app.palette.dim("no turns yet in this REPL run"))
        return
    print(app.palette.bold("session cost (this REPL run):"))
    print(f"  turns        {totals['turns']}")
    print(f"  tokens in    {totals['input_tokens']:,}")
    print(f"  tokens out   {totals['output_tokens']:,}")
    print(f"  tool calls   {totals['tool_calls']} ({totals['tool_errors']} errors)")
    per_tool = sorted(totals["per_tool"].items(), key=lambda kv: -kv[1])
    if per_tool:
        print("  by tool      " + " · ".join(f"{name} {count}" for name, count in per_tool))


def cmd_doctor(app: "AgentApp", args: str) -> None:
    from mini_agent.runtime import check_environment

    for check in check_environment():
        mark = app.palette.green("✓") if check.ok else app.palette.red("✗")
        print(f" {mark} {check.label:<20} {check.detail}")


def cmd_exit(app: "AgentApp", args: str) -> None:
    raise SystemExit(0)


def _build_registry() -> dict:
    return {
        "/help": (cmd_help, "list commands"),
        "/new": (cmd_new, "start a fresh session (rotates the session id)"),
        "/sessions": (cmd_sessions, "list saved sessions under the session root"),
        "/resume": (cmd_resume, "switch to a saved session: /resume <id-prefix> "
                                 "(full context within one REPL run; across restarts the log continues under the same id)"),
        "/model": (cmd_model, "show or switch model: /model <name>"),
        "/cwd": (cmd_cwd, "show workspace and session root"),
        "/system": (cmd_system, "show the active composition summary"),
        "/skills": (cmd_skills, "list skills discovered for this agent"),
        "/last": (cmd_last, "show the full text of recent tool results: /last [n]"),
        "/memory": (cmd_memory, "show the long-term memory file (MEMORY.md)"),
        "/remember": (cmd_remember, "append a durable fact/preference: /remember <text>"),
        "/audit": (cmd_audit, "show recent tool-call audit records: /audit [n]"),
        "/cost": (cmd_cost, "show cumulative token/tool usage for this REPL run"),
        "/doctor": (cmd_doctor, "run environment diagnostics"),
        "/exit": (cmd_exit, "quit the REPL"),
    }


COMMANDS = _build_registry()


def dispatch(app: "AgentApp", line: str) -> bool:
    """Handle a slash command. Returns True when the line was a command."""
    stripped = line.strip()
    if not stripped.startswith("/"):
        return False
    name, _, args = stripped.partition(" ")
    entry = COMMANDS.get(name)
    if entry is None:
        app.print(f"unknown command {name} — try /help")
        return True
    handler = entry[0]
    handler(app, args.strip())
    return True
