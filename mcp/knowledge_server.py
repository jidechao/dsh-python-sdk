#!/usr/bin/env python3
"""Minimal stdio MCP knowledge server: one `search` tool over knowledge/*.md.

The RAG puzzle piece in its smallest honest form — "agentic retrieval": the
model calls ``mcp__kb__search`` from its loop, gets ranked snippets back as a
tool result, and folds them into its next reasoning step (the article's
pre-injection variant would push snippets into the request instead; both put
retrieved knowledge onto the same Context workbench).

Retrieval is zero-dependency TF-IDF: documents are chunked by ``##`` sections
(≤ ~900 chars), tokenized into ASCII words plus Chinese character unigrams and
bigrams, scored per query term, and returned best-first with source paths.

Wire it into agent.cordis.yml:

    - id: mcp-kb
      name: '@deepseek-ai/dsh-mcp-client'
      config:
        serverName: kb
        transport: stdio
        command: python
        args: [mcp/knowledge_server.py]

The model then sees a native tool named `mcp__kb__search`.
"""

from __future__ import annotations

import json
import math
import re
import sys
from pathlib import Path

KNOWLEDGE_DIR = Path(__file__).resolve().parent.parent / "knowledge"
MAX_CHUNK_CHARS = 900
DEFAULT_TOP_K = 3

TOOL = {
    "name": "search",
    "description": (
        "Search the workspace knowledge base (project notes: architecture, "
        "event vocabulary, design mappings). Returns the most relevant "
        "snippets with their source files. Use it before answering questions "
        "about this project's design."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Search query (Chinese or English)"},
            "top_k": {"type": "integer", "description": "Max snippets to return (default 3)"},
        },
        "required": ["query"],
    },
}

_ASCII = re.compile(r"[a-z0-9_]+")
_HAN = re.compile(r"[\u4e00-\u9fff]")


def tokenize(text: str) -> list[str]:
    """ASCII words + Han unigrams + Han bigrams (mixed-corpus friendly)."""
    lowered = text.lower()
    tokens = _ASCII.findall(lowered)
    for run in re.findall(r"[\u4e00-\u9fff]+", lowered):
        tokens.extend(run)
        tokens.extend(run[i : i + 2] for i in range(len(run) - 1))
    return tokens


class Chunk:
    __slots__ = ("file", "title", "text", "tf")

    def __init__(self, file: str, title: str, text: str) -> None:
        self.file = file
        self.title = title
        self.text = text
        self.tf: dict[str, int] = {}
        for token in tokenize(text):
            self.tf[token] = self.tf.get(token, 0) + 1

    @property
    def length(self) -> int:
        return sum(self.tf.values()) or 1


def load_chunks() -> list[Chunk]:
    chunks: list[Chunk] = []
    if not KNOWLEDGE_DIR.is_dir():
        return chunks
    for path in sorted(KNOWLEDGE_DIR.glob("*.md")):
        try:
            content = path.read_text(encoding="utf-8")
        except OSError:
            continue
        title = path.stem
        buffer: list[str] = []
        current = f"# {title}"
        for line in content.splitlines():
            if line.startswith("## "):
                if buffer:
                    chunks.append(Chunk(path.name, current, "\n".join(buffer).strip()))
                current, buffer = line[3:].strip(), [line]
            else:
                buffer.append(line)
        if buffer:
            chunks.append(Chunk(path.name, current, "\n".join(buffer).strip()))
    # split oversized chunks on paragraph boundaries
    sized: list[Chunk] = []
    for chunk in chunks:
        if len(chunk.text) <= MAX_CHUNK_CHARS:
            sized.append(chunk)
            continue
        parts, buffer = [], []
        for line in chunk.text.splitlines():
            buffer.append(line)
            if len("\n".join(buffer)) >= MAX_CHUNK_CHARS:
                parts.append("\n".join(buffer))
                buffer = []
        if buffer:
            parts.append("\n".join(buffer))
        sized.extend(Chunk(chunk.file, chunk.title, part) for part in parts if part.strip())
    return sized


def search(chunks: list[Chunk], query: str, top_k: int) -> list[Chunk]:
    """TF-IDF ranking: sum over unique query terms of tf * idf * query_tf."""
    if not chunks:
        return []
    n_docs = len(chunks)
    query_tokens = tokenize(query)
    if not query_tokens:
        return []
    df: dict[str, int] = {}
    for chunk in chunks:
        for token in chunk.tf:
            df[token] = df.get(token, 0) + 1
    query_tf: dict[str, int] = {}
    for token in query_tokens:
        query_tf[token] = query_tf.get(token, 0) + 1
    scored: list[tuple[float, Chunk]] = []
    for chunk in chunks:
        score = 0.0
        for token, q_tf in query_tf.items():
            tf = chunk.tf.get(token)
            if not tf:
                continue
            idf = math.log((n_docs + 1) / (df[token] + 0.5)) + 1.0
            norm = 1.0 + math.log(tf)
            score += q_tf * norm * idf * (1.0 / math.sqrt(chunk.length))
        if score > 0:
            scored.append((score, chunk))
    scored.sort(key=lambda pair: (-pair[0], pair[1].file))
    return [chunk for _, chunk in scored[: max(1, top_k)]]


def render(chunks: list[Chunk]) -> str:
    if not chunks:
        return "no matching snippets in the knowledge base"
    parts = []
    for rank, chunk in enumerate(chunks, 1):
        parts.append(f"[{rank}] knowledge/{chunk.file} — {chunk.title}\n{chunk.text}")
    return "\n\n".join(parts)


def send(payload: dict) -> None:
    sys.stdout.write(json.dumps(payload, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def handle(request: dict, chunks: list[Chunk]) -> None:
    method = request.get("method")
    request_id = request.get("id")
    if method == "initialize":
        send({
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "protocolVersion": (request.get("params") or {}).get("protocolVersion", "2024-11-05"),
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "mini-kb", "version": "1.0.0"},
            },
        })
    elif method == "notifications/initialized":
        pass  # notification — no response
    elif method == "tools/list":
        send({"jsonrpc": "2.0", "id": request_id, "result": {"tools": [TOOL]}})
    elif method == "tools/call":
        params = request.get("params") or {}
        args = params.get("arguments") or {}
        query = str(args.get("query", ""))
        top_k = args.get("top_k", DEFAULT_TOP_K)
        try:
            top_k = max(1, min(int(top_k), 8))
        except (TypeError, ValueError):
            top_k = DEFAULT_TOP_K
        hits = search(chunks, query, top_k)
        send({
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {"content": [{"type": "text", "text": render(hits)}], "isError": False},
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
    chunks = load_chunks()
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            handle(json.loads(line), chunks)
        except ValueError:
            continue
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
