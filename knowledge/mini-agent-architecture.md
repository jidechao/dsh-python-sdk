# mini-agent 组合速查

## 组合文件

`agent.cordis.yml` 是独立 Cordis 组合，模板来自
`deepseek-harness/examples/jsonrpc-agent/minimal.cordis.yml`。每行一个插件实例：
`id`（本组合内唯一）+ `name`（npm 包名，从 `~/.dsh/profiles/node_modules` 解析）
+ `config`。`!!js` 表达式在加载时求值；`disabled: !!js` 用于平台条件行；
相对路径条目经 `new URL('...', baseUrl)` 从组合文件所在目录解析。

## 核心行与作用

- `sdk-jsonrpc-server`：SDK 的 JSON-RPC 传输层，`maxTokensAsSuccess: false` 让
  max-tokens 以 error 收尾而不是成功。
- `llm-deepseek`：DeepSeek 适配器，模型与上下文窗口经 `DSH_MODEL` /
  `DSH_CONTEXT_WINDOW` 环境变量注入。
- `sandbox-policy`：信任边界；mode 可为 `danger-full-access`（默认，官方示例
  同款）或 `workspace-write`（`--safe` 启动）。
- `agent-spine-demo`：系统提示词装配（persona、workspaceContext 分层
  AGENTS.md/CLAUDE.md、skills 菜单）。
- `dsh-mcp-client`：每个 MCP 服务器一个实例，工具注册为
  `mcp__<serverName>__<原名>`。

## 已知时序陷阱

工具目录在请求/轮次装配时快照（KV cache 前缀稳定性），因此 MCP 握手完成前
发起的首轮请求看不到 MCP 工具，后续 step/turn 起可见。REPL 在启动时预热
runtime 来缩小这个窗口。`request/header` 事件的 `data.header.tools` 就是
当轮通告给模型的工具清单。
