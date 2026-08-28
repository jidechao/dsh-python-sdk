# 事件词汇表

## session.event 类型

SDK `run()` 的 `on_notification` 回调收到 `session.event` 通知，`payload.event`
含 `type` 与 `data`：

- `turn/start` / `turn/end`：一轮边界；`turn/end` 的 `data.reason` 是
  `completed` / `error` / `max-tokens` / `aborted` 等。
- `step/start` / `step/end`：轮内每个推理步。
- `assistant/chunk`：流式块。`chunk.type` 取 `block-start`（`blockType` 为
  `reasoning` 或 `text`）、`reasoning-delta`、`text-delta`、`tool-call-delta`、
  `block-end`、`usage`（`inputTokens`/`outputTokens`）、`finish`。
- `tool/call`：`data.callId/name/arguments`。
- `tool/result`：`data.message.content[]` 中 `tool-result` 块携带文本与
  `isError`；`message.source.callId` 对应 `tool/call`。
- `request/header`：`data.header.tools` 为当轮通告的工具清单；
  仅在首次或装配变化时发出。
- `session/title`、`user/message`：标题与用户消息回显。

## 会话持久化布局

`<session-root>/<cwd-slug>/<session-id>/session.jsonl`；首行是会话头
（含 `id/cwd/createdAt`），后续每行一个存储记录，`seq` 连续。会话 id 是
目录名（文件 stem 恒为 `session`）。跨进程 resume 只续写日志，不恢复模型
上下文——完整上下文恢复仅限同一进程内。
