# Ideas Galore — MCP server

A zero-dependency Model Context Protocol server (stdio, JSON-RPC 2.0) over the same static
files the website reads. No network calls unless you point it at the live site, no keys, no
writes, no state.

```bash
python3 mcp/ideasgalore_mcp.py --dir web/public            # from a checkout (offline)
python3 mcp/ideasgalore_mcp.py --base https://knarayanareddy.github.io/Ideasgalore
python3 mcp/ideasgalore_mcp.py --dir web/public --selftest # smoke test, then exit
```

## Client config

```json
{
  "mcpServers": {
    "ideas-galore": {
      "command": "python3",
      "args": ["/ABS/PATH/TO/Ideasgalore/mcp/ideasgalore_mcp.py", "--dir", "/ABS/PATH/TO/Ideasgalore/web/public"]
    }
  }
}
```

Works as an entry in Claude Desktop's `claude_desktop_config.json`, Cursor's MCP settings, or
any stdio-MCP client. For a hosted-data variant, replace `--dir` with
`--base https://knarayanareddy.github.io/Ideasgalore`.

## Tools

| Tool | Input | What it answers |
| --- | --- | --- |
| `search_projects` | `query, moves[], domain, min_coolness, has_repo, depth, sort, limit, worth, include_pool` | "show me projects that do this mechanism" — cite-able rows, every one audited; `include_pool` adds held-out records marked `vetted: false` |
| `get_project` | `id, include_prose` | the deep sheet: event record, `inspiration_intel`, score decomposition, links, provenance, `audit` |
| `audit_report` | `id, full` | the evidence sheet: verdict, worth, soundness score + rubric coverage, the 12 mandatory fields with citations, per-check reasoning, named unknowns, clone cost with assumptions, hazard, duplicate merge |
| `promotion_queue` | `limit` | the highest-value unaudited records and what would settle each — a work list, not a merit list |
| `audit_rubric` | — | mandatory fields, check weights, verdict ladder, dedup + hazard rules — audit new candidates the same way |
| `ideas_for_goal` | `goal` (fuzzy prose) | maps a *goal* to the moves that fit it, then the projects that prove them |
| `similar_to` | `id` | parallel invention: same move, ideally a different sector |
| `list_moves` | `min_count` | the 18-term vocabulary with definitions, `steal_this`, postings |
| `remix_briefs` | `topic, limit` | collision briefs with `first_48_hours` + `kill_criteria` |
| `random_muse` | `seed, min_coolness` | one strong project + the question worth asking about it |
| `explain_scoring` | — | the published formula, so you can re-rank instead of deferring |

Every result embeds `devpost_url`, the hackathon name, and a `provenance_note`. `likes: null`
means *not fetched*, never zero. Every result also carries `verdict` / `worth` / `vetted`: the
catalog is audited-only, so `vetted: false` means "held out of the catalog" and a `null`
verdict means "never audited" — neither is a judgement of quality, and `unverifiable` is
not `false`.

## Hand-test without a client

```bash
printf '%s\n' \
 '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}' \
 '{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}' \
 '{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"ideas_for_goal","arguments":{"goal":"an agent that can audit its own claims"}}}' \
 | python3 mcp/ideasgalore_mcp.py --dir web/public
```

## Adding a tool

Add one function + one entry in `TOOLS` (schema + description). `Index` already decodes Tier 1
and lazy-loads the Tier-2 shard you need — do not eagerly fetch all shards, and do not put
mirrored project prose into any response (`docs/DATA_ETHICS.md`). `pipeline/tests/test_pipeline.py`
asserts every tool runs and cites.
