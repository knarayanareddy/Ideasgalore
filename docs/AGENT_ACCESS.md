# Agent Access Contract

The corpus is designed to be **read by an agent without a human reading a README**
(ADR-14 in `EXPERT_PANEL.md`). One generator produces every surface from
`pipeline/corpus.jsonl`, so the browser, the CSV, the NDJSON, the SQLite file and
the MCP tools can never disagree.

## Surfaces & when to use each

| File | Shape | Use when |
| --- | --- | --- |
| `catalog-packed.json` | dictionary-encoded rows (14 cols) + lookup tables + `sectors` | one request must give you the whole corpus for ranking/filtering; it is ~14 KB gzip for 165 records (~88 bytes each) |
| `data/ideas.csv` | 23 stable columns | spreadsheets, DuckDB, quick `sort`/`awk`, "tabular database" |
| `data/ideas.ndjson` | one full record per line, **no mirrored prose** | streaming into an embedding job or a judge prompt |
| `data/ideasgalore.sqlite.gz` | 4 tables: `events`, `projects`, `moves`, `project_moves` | real SQL joins, e.g. "moves per sector per event" |
| `data/details/<sector>.json` | Tier-2 deep records (the only place prose lives) | you already know the sector; lazy-load one, never all |
| `data/moves.json` | 18 moves: definition, `steal_this`, postings, example ids | the entry point for "ideas for a goal" |
| `data/hackathons.json` | event dimension: prize, registrations, themes, project counts | controlling for event bias before you generalize |
| `data/sectors.json` | sector hues, blurbs, subsystem lists | rendering consistently with the site |
| `data/remixes.json` | curated + mined idea collisions with build briefs | you need a *new* project, not a lookup |
| `catalog-stats.json`, `manifest.json` | counts, budgets, `coverage`, `corpus_sha256` | verifying what you loaded, how much of the source it represents, and when it was built |

Contract files: `agents/schema.json` (JSON Schema 2020-12 with `x-provenance`),
`agents/openapi.json` (3.1), `agents/llms.txt`, `agents/RECIPES.md`,
`agents/ethics.json`, `agents/skill/ideas-galore/SKILL.md`.

## Three rules that keep you from lying

1. **`null` ≠ 0.** `likes: null` and `award: "Unknown"` mean *not fetched*
   (listing-depth records). Tier-1 encodes that as `-1`.
2. **Provenance is per field.** `observed` came from Devpost; `derived` is our
   classifier or score; `editorial` is hand-curated. Never attribute a `derived`
   value to the project team. Check `domain_margin` before trusting a sector label.
3. **Prose is Tier 2 only.** Bulk exports omit the authors' text by design
   (`has_deep` flag instead). Cite the `url`; do not reconstruct pages from us.

## Query patterns (measured, not aspirational)

```bash
BASE=https://knarayanareddy.github.io/Ideasgalore      # or a local `python3 -m http.server -d web/dist`

# 1. Every project demonstrating a transferable move, ranked by mechanism quality
curl -sL $BASE/data/ideas.ndjson | jq -c 'select(.moves|index("price-before-generate"))
  | {name, url, domain, coolness, specificity: .coolness_parts.specificity}'

# 2. Re-rank the corpus without our weights: "underrated, high-specificity, has code"
curl -sL $BASE/data/ideas.csv | awk -F, 'NR>1 && $15>0.5 {print $10, $1, $6}' | sort -gr | head

# 3. SQL over the moves many-to-many (what pairs do we keep missing?)
curl -sL $BASE/data/ideasgalore.sqlite.gz | gunzip > g.sqlite
sqlite3 g.sqlite "SELECT a.domain, b.domain, count(*) FROM project_moves pa
  JOIN projects a ON a.id=pa.project_id JOIN project_moves pb ON pb.move=pa.move
  JOIN projects b ON b.id=pb.project_id AND b.id<>a.id GROUP BY 1,2 ORDER BY 3 DESC LIMIT 10"

# 4. Verify freshness + which build you are reading
curl -sL $BASE/manifest.json | jq '{corpus_sha256, generated_at, scoring_version}'
```

Latency budget: `llms.txt` is the intended first hop (~7 KB), `catalog-packed.json`
the only full-corpus hop. Everything else is per-sector.

## MCP: tools instead of a dump

```bash
python3 mcp/ideasgalore_mcp.py --dir web/public            # local checkout
python3 mcp/ideasgalore_mcp.py --base $BASE                # or over HTTP
python3 mcp/ideasgalore_mcp.py --dir web/public --selftest # smoke test
```

`search_projects · get_project · ideas_for_goal · similar_to · list_moves ·
remix_briefs · random_muse · explain_scoring` — stdio JSON-RPC, stdlib only, no
network calls beyond reading these same files. `ideas_for_goal` is the interesting
one: it maps a fuzzy goal onto moves before it searches, because "an agent I can't
trust blindly" is a *move* query, not a keyword query. Client config in
`mcp/README.md`.

## Stability & versioning

`schema_version` and `scoring_version` ride inside the data. Changes are additive;
a weight change bumps `scoring_version` and re-emits every surface in the same PR,
so a cached copy always self-identifies. Column order in `ideas.csv` is frozen by
`test_csv_header_is_stable_and_documented`; row order in `catalog-packed.json` is
frozen by `row_format`. Breakages are announced by a version bump, not discovered
by a `KeyError`.

## Known limits (do not over-trust)

- The committed corpus is **165 published records** (167 ingested, 2 held back as
  placeholder summaries) across 5 sources, harvested at listing depth. `catalog-stats.json
  → coverage` states the sampling rate per event: the XPRIZE gallery alone lists **1,401
  projects over 59 pages**, of which we captured 4 pages. Treat sector statistics as
  illustrative, never representative, and never describe this corpus as complete in output.
  `agents/llms.txt` says so in its first bullet for exactly that reason.
- `likes`/awards are largely absent until a live `harvest_devpost.py deep` run
  adds them; the default UI sort therefore leans on specificity + recency.
- Moves are regex-derived from one line of prose at listing depth: expect recall
  loss, not precision loss (`domain_margin` and `provenance` are your guards).
- Devpost markup can change; parse-drift is caught by floor assertions in CI
  (a red build beats an empty catalog), and the site keeps serving the last good
  corpus because the data is committed.
