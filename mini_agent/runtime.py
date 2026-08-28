"""Harness wiring: locate the DSH checkout, boot the SDK client against the
tsx source runtime, and diagnose the environment.

The published ``deepseek-harness-sdk`` wheel is not on public PyPI and its
runtime wheel targets linux/macos only. The documented contributor path
(``python/development.md``) runs the runtime from a repo checkout on system
Node via tsx; this module automates exactly that, importing the *official*
SDK client package from the checkout when it is not pip-installed.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
DEFAULT_CHECKOUT = Path(r"D:\project\Harness\deepseek-harness")
CORDIS_CONFIG = PROJECT_DIR / "agent.cordis.yml"
SKILLS_DIR = PROJECT_DIR / "skills"

DEFAULT_MODEL = "deepseek-v4-flash"
DEFAULT_PROVIDER = "deepseek-official"

# Mirrors the fallback persona in agent.cordis.yml; the memory instruction is
# appended only when this default (not a custom DSH_SYSTEM_PROMPT) is in use.
DEFAULT_PERSONA = (
    "You are Mini, a concise coding agent. Prefer reading before editing, "
    "verify changes by running commands, and keep replies short and structured."
)
MEMORY_INSTRUCTION = (
    " Long-term memory lives in memory/MEMORY.md at the workspace root: when the "
    "user states a durable preference or project fact, record it there; it is "
    "reloaded into your context on the next start."
)


def compose_persona(workspace: Path) -> str:
    """Base persona + the persisted long-term memory block (when present)."""
    from mini_agent.memory import load_memory

    base = os.environ.get("DSH_SYSTEM_PROMPT")
    persona = base if base else DEFAULT_PERSONA + MEMORY_INSTRUCTION
    memory = load_memory(workspace)
    if memory:
        persona += "\n\n## Long-term memory (persists across sessions)\n" + memory
    return persona


def resolve_checkout() -> Path:
    """Return the deepseek-harness checkout path (DSH_CHECKOUT overrides)."""
    return Path(os.environ.get("DSH_CHECKOUT") or DEFAULT_CHECKOUT).resolve()


def import_sdk():
    """Import the official ``deepseek_harness`` package.

    Tries a normal import first (covers a future PyPI install or an existing
    PYTHONPATH); falls back to inserting ``<checkout>/python/sdk/src`` — the
    same pure-Python sources that get published — into ``sys.path``.
    """
    try:
        import deepseek_harness  # noqa: F401
        return deepseek_harness
    except ImportError:
        pass
    sdk_src = resolve_checkout() / "python" / "sdk" / "src"
    if not sdk_src.is_dir():
        raise ImportError(
            f"deepseek_harness is not installed and {sdk_src} does not exist; "
            "install the SDK or point DSH_CHECKOUT at a deepseek-harness checkout"
        )
    sys.path.insert(0, str(sdk_src))
    import deepseek_harness  # noqa: F811
    return deepseek_harness


def load_credentials_env() -> dict[str, str]:
    """Return DEEPSEEK_API_KEY from env, falling back to the local DSH store.

    Reads only the env-var-named entries from ``~/.dsh/.credentials.yaml``
    (the same store the GUI uses). Values never appear in logs or output.
    """
    if os.environ.get("DEEPSEEK_API_KEY"):
        return {}
    path = Path.home() / ".dsh" / ".credentials.yaml"
    try:
        content = path.read_text(encoding="utf-8")
    except OSError:
        return {}
    match = re.search(r"^\s*(DEEPSEEK_API_KEY)\s*:\s*(\S+)\s*$", content, re.M)
    return {match.group(1): match.group(2)} if match else {}


def runtime_entry(checkout: Path) -> Path:
    return checkout / "packages" / "examples" / "jsonrpc-demo" / "src" / "bin.ts"


def build_harness(
    *,
    model: str,
    workspace: Path,
    session_root: Path,
    max_tokens: int | None = None,
    env: dict[str, str] | None = None,
):
    """Create a lazily-starting DeepSeekHarness bound to the source runtime."""
    sdk = import_sdk()
    checkout = resolve_checkout()
    merged_env = load_credentials_env()
    # Deterministic interpreters for the bundled MCP servers (caller may override).
    merged_env.setdefault("DSH_MCP_DEMO_PYTHON", sys.executable)
    merged_env.setdefault("DSH_MCP_KB_PYTHON", sys.executable)
    # Long-term memory rides the persona into every session (memory puzzle piece).
    merged_env.setdefault("DSH_SYSTEM_PROMPT", compose_persona(workspace))
    merged_env.update(env or {})
    return sdk.DeepSeekHarness(
        provider=DEFAULT_PROVIDER,
        model=model,
        max_tokens=max_tokens,
        cwd=str(workspace),
        session_root=str(session_root),
        cordis=str(CORDIS_CONFIG),
        runtime_cwd=str(checkout),
        launch_args_override=("node", "--import", "tsx", str(runtime_entry(checkout))),
        env=merged_env,
        request_timeout_seconds=None,
        shutdown_timeout_seconds=3.0,
    )


@dataclass(slots=True)
class CheckResult:
    ok: bool
    label: str
    detail: str


def check_environment() -> list[CheckResult]:
    """Diagnostics for every prerequisite of the source-runtime path."""
    results: list[CheckResult] = []

    def add(ok: bool, label: str, detail: str) -> None:
        results.append(CheckResult(ok, label, detail))

    # 1. official SDK client importable (pip install or checkout source)
    try:
        sdk = import_sdk()
        add(True, "SDK client", f"deepseek_harness ({getattr(sdk, '__file__', '?')})")
    except ImportError as exc:
        add(False, "SDK client", str(exc))

    checkout = resolve_checkout()
    entry = runtime_entry(checkout)
    add(checkout.is_dir(), "DSH checkout", str(checkout))
    add(entry.is_file(), "runtime entry", str(entry))
    add(CORDIS_CONFIG.is_file(), "composition", str(CORDIS_CONFIG))

    # 2. Node >= 22.19 (dev carrier requirement)
    node = shutil.which("node")
    if node is None:
        add(False, "Node.js", "node not found on PATH (need >= 22.19)")
    else:
        try:
            version = subprocess.run(
                ["node", "--version"], capture_output=True, text=True, timeout=15
            ).stdout.strip()
            major = int(version.lstrip("v").split(".")[0]) if version else 0
            add(major >= 23, "Node.js", f"{version} at {node} (need >= 22.19)")
        except Exception as exc:  # noqa: BLE001
            add(False, "Node.js", f"failed to probe: {exc}")

    # 3. tsx available inside the checkout
    tsx = checkout / "node_modules" / ".bin" / ("tsx.cmd" if os.name == "nt" else "tsx")
    add(tsx.is_file() or (checkout / "node_modules" / ".bin" / "tsx").exists(),
        "tsx (checkout)", str(checkout / "node_modules" / ".bin" / "tsx"))

    # 4. shell executor for this platform
    if os.name == "nt":
        pwsh = shutil.which("pwsh") or shutil.which("powershell")
        add(pwsh is not None, "pwsh", pwsh or "neither pwsh nor powershell on PATH")
    else:
        bash = shutil.which("bash")
        add(bash is not None, "bash", bash or "bash not found on PATH")

    # 5. credentials: env var, falling back to the local DSH credential store
    key = os.environ.get("DEEPSEEK_API_KEY") or load_credentials_env().get("DEEPSEEK_API_KEY")
    if key:
        add(True, "DEEPSEEK_API_KEY", "set" if os.environ.get("DEEPSEEK_API_KEY") else "via ~/.dsh/.credentials.yaml")
    else:
        add(False, "DEEPSEEK_API_KEY", "not set (real model calls will fail; smoke.py still works)")
    base = os.environ.get("DEEPSEEK_BASE_URL")
    if base:
        add(True, "DEEPSEEK_BASE_URL", base)

    return results
