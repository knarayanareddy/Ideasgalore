# Agent Access Contract

The corpus is designed to be **read by an agent without a human reading a README**
(ADR-14 in `EXPERT_PANEL.md`). One generator produces every surface from
`pipeline/corpus.jsonl`, so the browser, the CSV, the NDJSON, the SQLite file and
the MCP tools can never disagree.

## Surfaces & when to use each

| File | Shape | Use when |
| --- | --- | --- |
| `catalog-packed.json` | dictionary-encoded rows (**17 cols**: 14 + `verdict_id`, `worth_id`, `tier_id` — 0 full audit, 1 `audited-lite`) + lookup tables + `sectors` + an `audit` block | one request must give you the whole catalog for ranking/filtering, including what has been vetted |
| `data/ideas.csv` | **31 stable columns** — 8 audit columns first (`verdict, worth, soundness, soundness_score, rubric_coverage, audited_at, unknowns, repo_url`), then the original 23 | spreadsheets, DuckDB, quick `sort`/`awk`, "tabular database" |
| `data/audits.json` | id → verdict, worth, score, coverage, per-check `status`, unknown field names, sheet pointer | deciding *whether to trust* a record, cheaply, before fetching anything else |
| `data/audits/<sector>.json` | full audit sheets: `fields[f] = {value, evidence[], confidence, status, why?}`, per-check reasoning, evidence ledger | you are recommending a project and must state what is verified vs assumed |
| `data/pool.json` / `pool.csv` | records the audit held out, each with `why_not_promoted[]` + `would_settle_it[]`; `pool.csv` carries `ideas.csv`'s 31 columns in the same order plus `provenance`, `why_not_promoted`, `would_settle_it` | lead-mining; `provenance` says whether a row was scored-and-held or never checked — **never** present either as an example of good work |
| `data/promotion-queue.json` | unaudited candidates ranked by expected information gain | deciding what to fetch and audit next |
| `data/audit-rubric.json` | the rubric itself: mandatory fields, checks, weights, verdict ladder, dedup + hazard rules | auditing new candidates the same way, or checking our arithmetic |
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

## Four rules that keep you from lying

1. **`null` ≠ 0.** `likes: null` and `award: "Unknown"` mean *not fetched*
   (listing-depth records). Tier-1 encodes that as `-1`.
2. **Provenance is per field.** `observed` came from Devpost; `derived` is our
   classifier or score; `editorial` is hand-curated. Never attribute a `derived`
   value to the project team. Check `domain_margin` before trusting a sector label.
3. **Prose is Tier 2 only.** Bulk exports omit the authors' text by design
   (`has_deep` flag instead). Cite the `url`; do not reconstruct pages from us.
3b. **`why_not_promoted` distinguishes our reading from their project.** A row can say
   `incomplete capture (lint: …)` — our own read failed the contract gate at
   `pipeline/capture_lint.py`, so the record was never scored — which is a different claim from
   `verdict:thin`, the project's own verdict. Do not re-capture the first; re-audit the second.
4. **Unaudited ≠ approved.** The catalog is audited-only: every published record carries an
   `audit` verdict, and a `null` verdict (or a row in `data/pool.json`) means nobody
   verified it — not that it failed. Report `unverifiable` as *unverifiable*: it means the
   page made no checkable claim, which is not a debunking. Read `unknowns` aloud instead of
   filling them in; they are the honest part of the record.

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

# 4. Audited picks with the reasoning inline, then the sheet for the two survivors
curl -sL $BASE/data/audits.json | jq -r '.records | to_entries[]
  | select(.value.rubric_coverage > 0.6) | .key'
# 5. What the audit refused to publish, and exactly what would settle it
curl -sL $BASE/data/pool.json | jq -r '.records[]
  | "\(.id) · \(.why_not_promoted | join("; ")) · settle: \(.would_settle_it | join(", "))"'

# 6. Verify freshness + which build you are reading
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
remix_briefs · random_muse · explain_scoring · audit_report · promotion_queue ·
audit_rubric` — stdio JSON-RPC, stdlib only, no
network calls beyond reading these same files. `ideas_for_goal` is the interesting
one: it maps a fuzzy goal onto moves before it searches, because "an agent I can't
trust blindly" is a *move* query, not a keyword query. Client config in
`mcp/README.md`.

## Stability & versioning

`schema_version`, `scoring_version` and `audit_version` ride inside the data. Changes are additive;
a weight change bumps `scoring_version` and re-emits every surface in the same PR,
so a cached copy always self-identifies. Column order in `ideas.csv` is frozen by
`test_csv_header_is_stable_and_documented`; row order in `catalog-packed.json` is
frozen by `row_format`, and both are imported from the *same* constants the emitter uses
(`taxonomy_hacks.ROW_FORMAT` / `CSV_COLUMNS`) — a test asserts the emitted bytes match, so
the documentation cannot describe a shape we stopped building. `audit_version` bumps
whenever a rubric change re-derives verdicts; a missing `audit` block on a record is
itself a version signal ("built before the audit layer"), not a data error. Breakages are
announced by a version bump, not discovered by a `KeyError`.

## Known limits (do not over-trust)

<!-- census:begin -->
- **17 of 165** admitted records are published — this catalog is audited-only — **14** on the full twelve-field ladder and **3** as `audited-lite` (six fields established from the page, `build_is_real`/`stack_consistency` unexamined — see ADR-P15). **148** sit in `data/pool.json`: 8 captured, scored and held for cause · 140 never captured at all.
- **25** project pages have been deep-captured, 23 of them with a recorded figures table (claims written down with a denominator — whether they then proved checkable is each record's `numbers_add_up`), and 1 linking a repository we could verify against `api.github.com`. Hazard notes sit on 5 published and 3 held records.
- 127 pipeline tests, every surface regenerated by `make build`, and `make verify` fails the build if this block and `catalog-stats.json` ever disagree — including this block.
<!-- census:end -->

- The **catalog is audited-only**: a record publishes only if it was captured deeply enough to
  audit *and* cleared the verdict ladder; everything else sits in `data/pool.json` with reasons,
  which is why the census above separates scored-and-held from never-captured. Do not describe the
  pool as weak work — most of it is simply unchecked, and a `thin` record with `worth: strong` is a
  project the auditors liked but could not verify. See [`AUDIT_PROTOCOL.md`](AUDIT_PROTOCOL.md).
- `audit.verdict` (evidence strength) and `audit.worth` (copy-worthiness) are **two axes**; no
  composite exists, by design. `strong` is rare, not impossible: it needs rubric coverage ≥ 0.80
  *and* no open unknowns, which in practice requires a repository the team linked — see the
  captured-with-a-repo count in the census above, which is also why `strong` is rare here. For everything else
  `sound-with-caveats` is the ceiling of what a Devpost page can prove — treat it as
  "the claims hold up against the page and its artifact", not as a weak verdict.
- The committed corpus is **165 admitted records** (167 ingested, 2 held back as
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
