"""Mini Agent — a simplified REPL agent on the DeepSeek Harness Python SDK.

Architecture mapping (《万字长文拆解 Agent 架构设计》):
  * Agent Loop / tool dispatch / system-prompt assembly → runtime composition
    (``agent.cordis.yml`` mounts dsh-agent-spine-demo + shell/editor tools).
  * Layered AGENTS.md/CLAUDE.md memory → workspaceContext in the composition.
  * SKILL.md skill menu + on-demand loading → skills.filesystem composition.
  * REPL streaming render + session management → this package (Python).
"""

from mini_agent.app import AgentApp

__all__ = ["AgentApp"]
