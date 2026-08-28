# 八块拼图映射

《一张 Agent 全景图拆解落地的"八块拼图》给出公式：
Agent = LLM + Context + Skill + Memory + RAG + Tools + Loop + 工程化。
mini-agent 的落点：

## 逐块落点

- LLM：`llm-deepseek` 行 + `time-context` 行（时间感知）。
- Context：`agent-spine-demo` 的 workspaceContext（8 KiB 分层 AGENTS.md）与
  persona；长会话压缩由 `token-meter` + `compaction-basic` 承担。
- Skill：`skills/` 目录的 SKILL.md 菜单（name+description 进提示词，正文经
  skill 工具按需加载）。
- Memory：短期=进程内会话；长期=`memory/MEMORY.md`（启动注入 persona，
  `/remember` 或模型直写更新）。
- RAG：`knowledge/` 目录 + `mcp__kb__search` 工具（agentic 检索：模型在
  Loop 中主动检索回灌，等价于文章的 pre-injection RAG）。
- Tools：pwsh/bash、str_replace_editor、MCP 桥接工具。
- Loop：`dsh-agent-loop`（ReAct；工具结果回灌，模型不再调用工具即终止）。
- 工程化：审计（`audit.jsonl` + `/audit`）、成本（`/cost`）、SubAgent
  （fork provider + `subagent` 工具）、权限两档（默认 danger-full-access，
  `--safe` 切 workspace-write）。

## 文章要点回顾

Context 是真正的战场：每次请求重新组装，体积与质量成反比；八成功夫花在
"放什么、不放什么、怎么排优先级"。Memory 三层（短期/长期/画像），该忘的
要忘、该压缩的要压缩。RAG 不是加个搜索框：改写、检索、融合排序缺一不可。
工具风险控制：权限收窄、二次确认、幂等。工程化四件事：Hook、权限、
SubAgent、审计重试日志——决定"敢不敢上线"。
