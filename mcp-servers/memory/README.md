# mcp-memory

MCP server exposing AI Business OS long-term memory (§6, §10). Thin proxy over
`/v1/memory`.

## Tools

| Tool | Args | Returns |
|---|---|---|
| `remember` | kind (business\|person\|competitor\|campaign\|decision\|task), subject, body, importance 1–5, expires_at? | stored memory row |
| `recall` | query, kind?, limit | relevant memories (semantic + keyword RRF; excludes expired/consolidated) |
| `consolidate` | — | {merged, expired} — also runs Sun 03:00 via beat |

## Run

```bash
AIBOS_API_URL=https://your-domain/api AIBOS_API_KEY=<scoped-key> \
  python -m mcp_memory.server
```
