# Ideas Galore 🗄️✨

**A tabular database of cool hackathon projects — mined from Devpost, ranked by what you
can steal from them, and readable by an agent over plain HTTP.**

Ideas Galore ingests hackathon submissions (public showcase rails, project galleries, the
public hackathon JSON API), classifies each one by sector **and by transferable design
"moves"**, scores it with an *explainable* ranking, and publishes the result as static
JSON + CSV + NDJSON + SQLite on GitHub Pages: **$0/month, no backend, no API key, forever.**

> **Why it exists:** hackathon projects are the densest source of "what would this look like
> if someone actually tried it?" on the internet — and none of it is organized for reuse.
> This index is built for the two audiences who need it: a **builder** looking for their next
> idea, and **other agents** looking for grounded prior art.
>
> Architecture, data model, ranking: [`docs/METHODOLOGY_BLUEPRINT.md`](docs/METHODOLOGY_BLUEPRINT.md)
> · Every decision argued by an 8-expert panel: [`docs/EXPERT_PANEL.md`](docs/EXPERT_PANEL.md)
> · Visual system: [`docs/DESIGN.md`](docs/DESIGN.md) · Sourcing/ethics: [`docs/DATA_ETHICS.md`](docs/DATA_ETHICS.md)
> · Scaling the workflow to 500–1,000 records (measured, parallelised): [`docs/PARALLELISM_PANEL.md`](docs/PARALLELISM_PANEL.md)
> · Built on the [`toolscour`](https://github.com/knarayanareddy/toolscour) two-tier static methodology, retargeted for ideas.

---

## ✨ What you get

| Capability | Detail |
| --- | --- |
| **Quality-gated catalog** | nothing ships without an audit sheet: 12 mandatory fields, 6 evidence-backed checks, a verdict ladder and a duplicate-merge pass. The catalog is deliberately small: only records with a publishable audit sheet ship, and the rest stay reachable in `data/pool.json` with a per-record reason. Counts are generated below, so this row cannot quote a stale one — see [`docs/AUDIT_PROTOCOL.md`](docs/AUDIT_PROTOCOL.md) |
| **Tabular database** | `data/ideas.csv` (31 stable columns — 8 audit + 23 catalog), `data/ideas.ndjson`, and a gzipped **SQLite** file with `events` / `projects` / `moves` / `project_moves` — query it in DuckDB, pandas, Excel or SQL without a server |
| **Two-tier sharded index** | Tier 1 `catalog-packed.json` (dictionary-encoded, 16 columns including `verdict_id`/`worth_id`, budget 1.2 MB) + Tier 2 per-sector deep shards + per-sector **audit sheets**, lazy-loaded |
| **Honest coverage** | the corpus publishes its own sampling rate: `catalog-stats.json → coverage` says 83 of the 1,401 projects listed in the XPRIZE gallery are in here, from 4 captured pages — a *gated sample*, never a claim of completeness |
| **18 transferable "moves"** | `price-before-generate`, `evidence-graph`, `human-holds-the-last-button`, `offline-first-fallback`, `data-flywheel`… each with a definition, a `steal_this` imperative, and its own postings index — **the axis that produces new projects, not just lists** |
| **10 sectors + subsystems** | Agentic Autonomy · Dev Tooling · Health & Care · Climate & Physical World · Public Trust · Money & Commerce · Creative Media · Learning · Accessibility · Data & Memory — plus an honest `Emerging & Cross-Domain` bucket for submissions too thin to place |
| **Explainable ranking** | `coolness` = six logged components with **published weights**; every record ships its decomposition, so you can re-rank in SQL instead of trusting us |
| **Specificity over popularity** | a record earns rank by describing a *mechanism* (numbers, verbs, stack), not by being liked — otherwise we'd just be Devpost's front page |
| **The Atlas** | hand-projected canvas vault (no three.js): height = coolness, gold ring = deep record, arcs = shared move, click any node for the deep sheet |
| **The Remix Bench** | build-time idea collisions: curated + mined pairs, each with `the_wedge`, `starter_stack`, `first_48_hours` and **`kill_criteria`** |
| **Idea shelf** | star plates → export a markdown brief with links, provenance footer and all — paste it into your next project plan or hand it to an agent |
| **Agent-native** | `llms.txt`, JSON Schema with **per-field provenance** (the `audit` block included), OpenAPI 3.1 with the audit surfaces, an agent `SKILL.md`, and a stdlib **MCP server** with 11 tools (`audit_report`, `promotion_queue`, `audit_rubric` included) |
| **Reproducible & gated** | `make verify`: offline rebuild → byte-diff of **every** emitted surface → catalog/pool partition parity → budget ceiling → header/row alignment on both CSV surfaces → 77 tests → a node check that the browser decodes the same verdicts the gates validated. Scores are stamped as-of the corpus, not the clock, so a rebuild in January matches a build in September. CI fails on drift and refuses to publish a collapsed corpus |

## 📊 Where the catalog stands

<!-- census:begin -->
- **18 of 165** admitted records are published — this catalog is audited-only — **14** on the full twelve-field ladder and **4** as `audited-lite` (six fields established from the page, `build_is_real`/`stack_consistency` unexamined — see ADR-P15). **147** sit in `data/pool.json`: 9 captured, scored and held for cause · 138 never captured at all.
- **27** project pages have been deep-captured, 25 of them with a recorded figures table (claims written down with a denominator — whether they then proved checkable is each record's `numbers_add_up`), and 1 linking a repository we could verify against `api.github.com`. Hazard notes sit on 5 published and 3 held records.
- 128 pipeline tests, every surface regenerated by `make build`, and `make verify` fails the build if this block and `catalog-stats.json` ever disagree — including this block.
<!-- census:end -->

---

## 🔌 Data as an API (one emitter, audited gate)

| Endpoint (relative to the site root) | What it is |
| --- | --- |
| `catalog-packed.json` | Tier-1 index: 16-column dictionary-encoded rows + `domains/subsystems/moves/stacks/awards/events/sectors` lookup tables |
| `data/ideas.csv` | the tabular database — stable header, no mirrored prose |
| `data/ideas.ndjson` | full metadata per line, streaming-friendly |
| `data/ideasgalore.sqlite.gz` | normalized SQL surface (4 tables + indexes) |
| `data/details/<sector>.json` | Tier-2 deep records: `inspiration_intel`, links, score parts, provenance, ≤220-char quote |
| `data/moves.json` · `data/hackathons.json` · `data/sectors.json` | the three dimensions: trick vocabulary, event table, sector definitions |
| `data/remixes.json` | generated idea collisions with build briefs |
| `catalog-stats.json` · `manifest.json` | corpus counts + build provenance (`corpus_sha256`) |
| `data/audits.json` · `data/audits/<sector>.json` | audit index (verdict + coverage per record) and full evidence sheets: fields, per-check reasoning, evidence ledger |
| `data/pool.json` · `data/pool.csv` · `data/promotion-queue.json` | what the audit held out, why, and what would settle it — `provenance` marks each pool row as scored-and-held or never captured — plus the work list, ranked by information gain |
| `data/audit-rubric.json` | the rubric itself, so anyone can re-derive (or argue with) a verdict |
| `agents/{llms.txt,schema.json,openapi.json,ethics.json,RECIPES.md,skill/…}` | the machine contract |

```bash
BASE=https://knarayanareddy.github.io/Ideasgalore

# what mechanisms does this corpus hold for making an agent auditable?
curl -sL $BASE/data/ideas.ndjson | jq -c 'select(.moves|index("evidence-graph"))|{name,url,domain}'

# re-rank without our weights: high-specificity ideas only
curl -sL $BASE/data/ideas.csv | awk -F, 'NR>1 && $15>0.55 {print $10,$1,$6}' | sort -gr | head
```

Full query cookbook: [`docs/AGENT_ACCESS.md`](docs/AGENT_ACCESS.md) and `agents/RECIPES.md`.

### Give an agent tools, not a dump

```bash
python3 mcp/ideasgalore_mcp.py --dir web/public          # or --base $BASE
```
`search_projects · get_project · ideas_for_goal · similar_to · list_moves · remix_briefs ·
random_muse · explain_scoring` — stdio MCP, zero dependencies. Config snippet in `mcp/README.md`.

---

## 🚀 Local development

```bash
# 1. Build the data (offline — reads committed captures in pipeline/raw/)
python3 pipeline/ingest_seed.py
python3 pipeline/shard_builder.py --check      # + gates
python3 pipeline/generate_remixes.py
python3 pipeline/build_agent_api.py

# 2. Run the explorer
cd web && npm install && npm run dev           # :5173, host 0.0.0.0

# or just:  make build && make serve
```

```bash
# 3. Optional: refresh the corpus from Devpost (network; polite by construction)
python3 pipeline/harvest_devpost.py discover --pages 4
python3 pipeline/harvest_devpost.py gallery --from-state --max-events 25
python3 pipeline/harvest_devpost.py deep --limit 150
python3 pipeline/harvest_devpost.py ingest
```

No key is needed to read or build; none is needed to harvest either (the public API is
unauthenticated). `pipeline/corpus.jsonl` is committed, so the site builds with no network
at all — including inside network-isolated sandboxes and CI.

---

## 🧠 How a record is described

Each project carries: identity + `url` + `event{org, prize, registrations, themes, date}` ·
`likes` (or `null`, never 0) · `award` · `depth: listing|deep` · `domain`/`subsystem` +
`domain_margin` · `moves[]` · `stack[]` · `specificity` · `coolness` + `coolness_parts` ·
`inspiration_intel{the_wedge, naive_version_vs_this, how_they_built_it, hard_won_lesson,
proof_points, next_moves, steal_this[], reuse_surface}` · `links{repo,demo,video}` ·
**`provenance{}` per field** (`observed` / `derived` / `editorial` / `unavailable`) ·
`harvested_at`, `taxonomy_version`, `scoring_version` ·
**`audit{verdict, worth, soundness, soundness_score, rubric_coverage, checks{}, unknowns[],
clone_cost, what_to_steal, what_breaks_first, prior_art[], hazard, sheet}`** — the record's
own evidence ledger is one pointer away, and `unknowns[]` states what nobody could verify
instead of leaving the reader to guess it ([`docs/AUDIT_PROTOCOL.md`](docs/AUDIT_PROTOCOL.md)).

```
coolness = 0.30·engagement + 0.22·validation + 0.14·event_prestige + 0.10·recency
         + 0.14·specificity + 0.10·signal_richness − 0.12·redundancy
```
Admission gate `coolness ≥ 0.18` + placeholder-summary rejection. The `redundancy` term only
reorders browse views; it never deletes a record — parallel invention is a *feature* of
hackathons (two teams in one event both shipped "NeuroGuard AI"; we keep both and say so).
What *is* merged is the same product resubmitted to a different hackathon: shared numeric
fingerprints ($0.02 · $20 · $238 · 29% → 49%) set `duplicate_of` on the thinner record, which
then sits in the pool pointing at its better-sourced twin.

---

## 📁 Repository layout

```
Ideasgalore/
├── .github/workflows/deploy.yml        verify gate · weekly refresh · Pages deploy
├── docs/
│   ├── EXPERT_PANEL.md                 8 personas · 3 rounds · critiques · 15 ADRs · dissents
│   ├── METHODOLOGY_BLUEPRINT.md        system spec: taxonomy, acquisition, ranking, schema
│   ├── DESIGN.md                       "Field Museum of Ideas" — locked tokens
│   ├── AGENT_ACCESS.md                 surfaces, contract, query cookbook, known limits
│   ├── AUDIT_PANEL.md                  9 personas · evidence rules · 15 audit ADRs · dissents
│   ├── AUDIT_PROTOCOL.md               the executable rubric: fields, checks, verdicts, gates
│   └── DATA_ETHICS.md                  sourcing policy, what we refuse to store, takedowns
├── mcp/ideasgalore_mcp.py              stdio MCP server (11 tools, stdlib only)
├── pipeline/
│   ├── raw/{seed_gallery.tsv, events.json, deep_records.json, overrides.json,
│   │        audit_notes.json, deep_captures/*.json}
│   ├── taxonomy_hacks.py               sectors · 18 moves · stack · specificity · coolness · intel
│   ├── harvest_devpost.py              L1 discover · L2 gallery · L3 deep · ingest
│   ├── ingest_seed.py                  offline corpus build from committed captures
│   ├── audit_projects.py               evidence → checks → verdict → promotion gate
│   ├── repo_verify.py                  api.github.com facts for stack/build/test claims
│   ├── shard_builder.py                every surface + gates (budget, parity, audit, determinism)
│   ├── generate_remixes.py             curated + mined idea collisions → build briefs
│   ├── build_agent_api.py              llms.txt · schema · OpenAPI · SKILL.md · ethics
│   ├── corpus.jsonl                    ← single source of truth
│   ├── raw/gallery_totals.json         upstream gallery sizes → published coverage
│   └── tests/test_pipeline.py          77 tests (incl. the audit engine, both CSV contracts and the "no prose in bulk exports" gate)
└── web/
    ├── public/                         everything an agent can fetch
    └── src/{App, IdeaAtlas, IdeaInspector, IdeaForge}.jsx · lib.js · index.css
```

---

## ⚖️ Sourcing, honesty, and take-downs

Public pages and the public JSON API only — no login, no judge-only endpoints, no
circumvention. ≥1.25 s between requests, robots.txt honored and **fail-closed**, identifying
User-Agent, exponential backoff. We store facts and a short attributed quote, never mirrored
pages, never team-member identities, never copied media. Derived labels are labelled as
derived. If your project is in here and you want it corrected or removed, open an issue with
the record `id` — removal is applied at build time, so it survives future harvests.
Details: [`docs/DATA_ETHICS.md`](docs/DATA_ETHICS.md).

*Not affiliated with or endorsed by Devpost. Project data © its submitters; this index and its
derived labels are offered for research and inspiration.*
