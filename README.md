# Mini Agent — 简化版 REPL 编码 Agent

基于官方 [DeepSeek Harness Python SDK](https://deepseek-harness.github.io/deepseek-harness/guide/python-sdk)
构建的简化版编码智能体，以 REPL 交互终端呈现。能力设计对照
《万字长文拆解 Agent 架构设计》系列文章与《一张 Agent 全景图拆解落地的
"八块拼图"》：`Agent = LLM + Context + Skill + Memory + RAG + Tools + Loop + 工程化`
——八块全部落位，由 DSH 运行时的 Cordis 插件组合原生承担，Python 侧只做
REPL 编排与流式渲染。

```
──────────────────────────────────────────────────────────────
  你 › 用 pwsh 运行 Get-Date，告诉我今天是星期几
  ────────
  · thinking The user wants me to run Get-Date…
    ⚙ pwsh(command=Get-Date -Format "yyyy-MM-dd dddd")
      ✓ 1750ms · 16 chars
  今天是星期二（2026-08-18）。
  ⟨done · steps 2 · in 5,581 tok · out 200 tok⟩
  你 ›
──────────────────────────────────────────────────────────────
```

## 快速开始

> **测试约定：所有命令统一在项目 venv 中执行**（`.venv\Scripts\python.exe`）。

```powershell
# 1. 环境准备（安装 pydantic + 体检）
powershell -ExecutionPolicy Bypass -File setup.ps1

# 2. 无 key 冒烟（本地 mock 模型端点，验证 runtime/工具/持久化/审计全链路）
.venv\Scripts\python.exe smoke.py

# 3. 交互式 REPL（凭据来自 DEEPSEEK_API_KEY 环境变量，
#    未设置时自动回退读取 ~/.dsh/.credentials.yaml —— 与 GUI 同源）
.venv\Scripts\python.exe repl.py
```

常用参数：`--workspace DIR`（agent 工作区，默认当前目录）、`--session-id ID`、
`--model NAME`（默认 `DSH_MODEL` 或 `deepseek-v4-flash`）、`--max-tokens N`、
`--safe`（沙箱收窄为 workspace-write，见"信任边界"）、`--check`（仅体检）。

## 前置要求

| 依赖 | 说明 |
|---|---|
| deepseek-harness 检出 | 默认 `D:\project\Harness\deepseek-harness`，可用 `DSH_CHECKOUT` 覆盖。SDK 客户端从 `<检出>/python/sdk/src` 导入（官方 PyPI 尚未发布该包），运行时经 `node --import tsx` 从源码启动 |
| Node ≥ 22.19 + 检出内 tsx | `pnpm install` 后的 `node_modules/.bin/tsx`（本机已验证 Node 24） |
| PowerShell（Windows）/ bash（POSIX） | shell 工具的平台条件执行器 |
| pydantic ≥ 2.12 | SDK 客户端唯一第三方依赖，`setup.ps1` 自动安装 |

## 架构：八块拼图 → 落点

| 拼图 | 落点（组合行 / 模块） | 实测 |
|---|---|---|
| **① LLM** | `llm-deepseek`（流式 + `/model` 切换）+ `time-context`（每步注入带时区时间——补上"它甚至不知道现在几点"） | ✅ 模型零命令报出会话采样时间 `2026-08-18T17:10+08:00[Asia/Shanghai]` |
| **② Context** | `agent-spine-demo`：persona + `workspaceContext`（8 KiB 分层 AGENTS.md/CLAUDE.md）；`token-meter` + `compaction-basic` 长会话压缩（"该压缩的要压缩"） | ✅ 每轮 `⟨done · in/out tok⟩` 账单；压缩插件随组合启动 |
| **③ Skill** | `skills/` 目录：name+description 菜单常驻提示词，正文经 `skill` 工具按需加载（可插拔 SOP） | ✅ `skills/release-checklist/` |
| **④ Memory** | 短期=进程内会话（prompt cache 实证）；**长期=`memory/MEMORY.md`**（启动注入 persona，`/remember` 或模型直写更新） | ✅ `/remember 我的代号是青鸟-7号` → 重启进程 → 模型零工具答出代号 |
| **⑤ RAG** | `knowledge/*.md` + `mcp/knowledge_server.py`（零依赖 TF-IDF，中英混合分词）→ `mcp__kb__search` 工具，**agentic 检索**：Loop 中检索回灌 Context | ✅ 模型调用 `mcp__kb__search` 16ms 取回 1,138 字符并正确总结 |
| **⑥ Tools** | `pwsh`/`bash`（平台条件）、`str_replace_editor`、MCP 桥接工具；超时/输出上限由 runtime 兜底 | ✅ 见 MCP 与信任边界 |
| **⑦ Loop** | `dsh-agent-loop`（ReAct：工具结果回灌，模型不再调用工具即终止；`maxParallelToolCalls` 兜底） | ✅ 多步工具轮次实证 |
| **⑧ 工程化** | 审计：`audit.jsonl` + `/audit`；成本：`/cost`；SubAgent：`subagents` 注册表 + fork provider + `subagent` 工具；权限两档：默认 `danger-full-access` / `--safe` → `workspace-write` | ✅ 见下文实测记录 |

文章要点回顾：*Context 才是真正的战场*（每次请求重组装、体积与质量成反比）；
*八成功夫花在往 Context 放什么*；工具风险控制（权限收窄、二次确认、幂等）；
工程化四件事决定"敢不敢上线"。

### 长期记忆（Memory 的最小三层近似）

- 短期 = 会话内上下文（进程存活期间完整，实测 prompt cache 第二轮 input 仅 117 tok）。
- 长期+画像 = `memory/MEMORY.md`（`## 用户偏好` / `## 项目事实` 两节）：
  启动时截断 2 KiB 注入 persona；`/remember <text>` 追加带日期条目；
  persona 指示模型把稳定偏好/项目事实主动写入该文件（fs 工具可直接编辑）。
- 取舍（诚实说明）：persona 在 runtime 启动时定格，`/remember` 与模型直写都在
  **下一次启动**生效；记忆文件变更会改变 system prompt 前缀、使 KV cache 失效，
  属跨会话才发生的可接受代价。

### 知识库检索（agentic RAG）

文章的 RAG 是 pre-injection（检索结果组装进请求）；本项目用等价的现代形态
——模型在 Loop 中主动调 `mcp__kb__search`，结果作为工具产物回灌 Context。
知识库即 `knowledge/*.md`（本项目自指笔记：组合速查 / 事件词汇表 / 拼图映射）；
检索为零依赖 TF-IDF（`##` 标题分块 ≤900 字符，ASCII 词 + 汉字一元/二元）。
扩展即往目录加 Markdown，无需改代码。

### 审计与成本（工程化第 4 块）

- 每个完成的工具调用（含耗时/字符数/成败）追加一行 JSON 到
  `<session-root>/audit.jsonl`，`/audit [n]` 回看。
- `/cost` 汇总本次 REPL 运行的轮数、in/out tokens、工具调用数与逐工具统计
  （数据来自 `usage` 事件，无需额外插件）。

### SubAgent（工程化第 3 块，兼文章四）

`dsh-subagent`（`ctx.subagents` 注册表）→ `dsh-subagent-fork-in-process`
（fork provider：子代理继承父代理**已完成轮次**的前缀，规避未闭合轮次的
非法日志）→ `dsh-tool-subagent`（模型可见 `subagent` 工具，one-shot 前台
等待，`maxDepth: 1` 防递归委派）。实测：模型委派 `计算 37*43` → 子代理
1,015ms 回传 `1591`。

## MCP 支持

**支持。** 组合内置 `@deepseek-ai/dsh-mcp-client` 桥接：每个 MCP 服务器在
`agent.cordis.yml` 里一个插件实例，其工具以 `mcp__<serverName>__<原名>` 注册为
原生工具（与 Claude Code / Codex 同形的命名空间）。内置两个服务器：

- **demo**：`mcp/demo_server.py`（零依赖 stdio，echo 工具）——桥接验证用。
- **kb**：`mcp/knowledge_server.py`（零依赖 stdio，TF-IDF 检索）——RAG 拼图。

REPL 自动用当前解释器（`sys.executable`）拉起两个服务器，无需 PATH 上有
`python`；可用 `DSH_MCP_DEMO_PYTHON` / `DSH_MCP_KB_PYTHON` 覆盖。

- **接入真实服务器**：仿照组合中注释掉的 `mcp-github` 样例（stdio 传
  `command/args/env`，远程用 `transport: streamable-http` + `url/headers`）。
  断线自动重连（指数退避，预算耗尽后注销并停止）。
- **可见性时序**（实测行为）：工具目录在轮次/请求边界快照（KV cache 前缀稳定），
  MCP 握手完成前发起的请求暂不包含新工具，同轮后续 step 或下一轮起可见。
  REPL 启动即预热 runtime 把窗口藏在横幅后；**脚本管道喂首条消息**仍可能竞速
  输给握手（此时模型会退化为 pwsh 直接读知识库，功能等价）；交互输入无此问题。
- `failOnStartupError` 默认 false：某个 MCP 服务器起不来只影响它自己的工具。

## REPL 命令

| 命令 | 作用 |
|---|---|
| `/help` | 命令列表 |
| `/new` | 轮换新会话 id |
| `/sessions` | 列出会话根目录下的历史会话（标题/消息数/时间） |
| `/resume <id前缀>` | 切换会话：同一 REPL 进程内保留完整上下文；跨重启后 JSONL 日志在同一 id 下续写，但模型从全新上下文开始（当前组合为写侧检查点） |
| `/model [name]` | 查看/切换模型（切换后下一条消息重建运行时） |
| `/cwd` · `/system` | 工作区 / 组合摘要（含记忆、知识库、沙箱档位） |
| `/skills` | 列出发现的技能 |
| `/memory` · `/remember <text>` | 查看 / 追加长期记忆（下次启动注入） |
| `/last [n]` | 展开最近 n 条工具结果原文 |
| `/audit [n]` | 查看最近 n 条工具调用审计记录 |
| `/cost` | 本次运行的 token / 轮数 / 工具调用账单 |
| `/doctor` | 环境体检（SDK / 检出 / Node / tsx / shell / 凭据） |
| `/exit` | 退出 |

输入行尾 `\` 续行；运行中 Ctrl+C 中断并惰性重建运行时；Ctrl+D 或 `/exit` 退出。

## 测试（全部在 venv 中）

```powershell
.venv\Scripts\python.exe repl.py --check   # 环境体检
.venv\Scripts\python.exe smoke.py          # 无 key 全链路冒烟
.venv\Scripts\python.exe smoke.py --keep   # 保留会话目录以便检查 JSONL
```

`smoke.py` 四个阶段：⓪ 纯 Python——记忆组装（remember→compose_persona）与
知识库索引（分块/中英检索/来源渲染）；① 经 SDK 直连运行时跑一轮（mock 模型
发起 `pwsh` 工具调用 → 本机 PowerShell 真实执行 → 结果回传 → 最终文本），并
断言工具目录含 `mcp__demo__echo`、`mcp__kb__search`、`subagent`（跨轮并集，
容忍 MCP 握手竞速）；② JSONL 会话持久化；③ 完整 REPL 路径
（`AgentApp.send` + 流式渲染器 + 审计落盘 + `/cost` 计数）。

## 已验证行为（Windows 本机）

- ✅ runtime 经 tsx 源码路径启动，组合激活（含平台条件 shell 栈、time-context、
  token-meter、compaction-basic、subagents×3、mcp×2）
- ✅ 真实模型流式回复：思考（暗色预览，>400 字截断）、正文、工具调用行、token 汇总
- ✅ `pwsh` 工具真实执行；`str_replace_editor` 由同一组合注册
- ✅ MCP 桥接：`mcp__demo__echo` 与 `mcp__kb__search` 真实握手注册，模型均调用成功
- ✅ 长期记忆跨进程：`/remember` → 重启 → 模型凭 persona 注入答出，零工具调用
- ✅ SubAgent 委派：`subagent` 工具 → fork 子代理 → 1,015ms 回传计算结果
- ✅ 时间感知：模型引用 time-context 采样时间回答"现在几点"，零命令
- ✅ `--safe` 沙箱：工作区外硬路径写入被 ACL 受限令牌拒绝（`UnauthorizedAccessException`
  → `[sandbox: file access denied under workspace-write mode]`，文件确认未创建）；
  `%TEMP%` 自动重定向到会话专属私有临时目录（policy 允许范围）
- ✅ 同进程多轮记忆 + prompt cache；跨重启为日志续写、上下文重置（见 `/resume`）
- ✅ PowerShell 5.1 回退可用（无 pwsh 7 时 UTF-8 由执行器强制固定）
- ⚠️ POSIX 分支（`bash-sandbox` + `tool-bash`）镜像官方预设写法，未在本机验证

## 信任边界（两档）

| 档位 | 启用 | 行为 |
|---|---|---|
| `danger-full-access`（默认） | 直接启动 | 与官方 minimal 示例一致：shell 与编辑器可修改运行时进程可访问的任何路径，请在可丢弃的工作区运行 |
| `workspace-write` | `repl.py --safe` | shell 经沙箱孪生执行器真实受限：Windows ACL 受限令牌（写权限 = 工作区 + 会话私有临时目录），Linux bwrap/Landlock，macOS Seatbelt；文件工具同 policy；被拒命令返回标准拒绝标记，模型可请求 `sandbox_permissions` 升级（当前无审批应答器时升级失败关闭，见扩展点） |

## 扩展点

- **审批应答器**（工程化第 2 块的"二次确认"完整形态）：`dsh-user-approval` 的
  `ctx.approval` 应答通道接到 REPL 的 y/n 交互（当前 `--safe` 下升级请求无应答器
  时按失败关闭处理，默认档不受影响）
- **跨进程上下文恢复**：`dsh-session-checkpoint-policy`（当前 `/resume` 跨重启仅续写日志）
- **更多 SOP 技能**：`skills/` 加 SKILL.md 即可（机制已验证，数量是唯一差距）
- **`dsh-llm-retry`**：LLM 请求重试策略行
- **PyPI SDK 发布后**：`pip install deepseek-harness-sdk` 后删除
  `runtime.py` 中 sys.path 回退与 `launch_args_override`，改用内置运行时
