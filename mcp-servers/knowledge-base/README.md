# mcp-knowledge-base

MCP server exposing the AI Business OS knowledge base (§6, §10). Thin proxy
over `/v1/kb/*` — no business logic here.

## Tools

| Tool | Args | Returns |
|---|---|---|
| `search` | query, mode=hybrid\|keyword\|semantic, limit | ranked chunks with document citations; `degraded` flags keyword-only fallback |
| `ingest_document` | path (local file), title?, lang? (th\|en) | document row; ingestion is async — poll `get_document` |
| `get_document` | document_id | metadata + status + chunk_count |
| `list_documents` | status?, limit | recent documents |

## Run

```bash
AIBOS_API_URL=https://your-domain/api AIBOS_API_KEY=<scoped-key> \
  python -m mcp_knowledge_base.server        # stdio transport
```

Claude Code registration: `claude mcp add aibos-kb -- python -m mcp_knowledge_base.server`
(with the two env vars set). In dev (`ENV=dev`) the API key may be omitted.
