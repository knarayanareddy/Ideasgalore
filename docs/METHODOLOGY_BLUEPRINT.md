# Ideas Galore — Blueprint & System Architecture Specification
## Multi-source ingestion, an inspiration taxonomy, an explainable ranking, and a static API that agents can read

> Status: **implemented** — every section below maps to files in this repo.
> Decisions and their arguments: [`EXPERT_PANEL.md`](EXPERT_PANEL.md). Visual system:
> [`DESIGN.md`](DESIGN.md). Usage policy: [`DATA_ETHICS.md`](DATA_ETHICS.md).
> Machine contract: [`AGENT_ACCESS.md`](AGENT_ACCESS.md) + `web/public/agents/`.

---

## 1 · Executive summary & feasibility

**Verdict: viable at $0/month, and small is a feature.**

| Constraint | Target | Measured (committed build) |
| --- | --- | --- |
| Hosting | $0/mo, no server, no key to read | GitHub Pages, static files |
| Corpus | quality-gated, expandable | 104 seed projects / 5 event sources, 18 moves |
| Tier-1 index | < 1.2 MB gzip hard gate | **9.8 KB** gzip → headroom for ~12k records |
| Search | sub-5ms at 10⁵ rows | inverted index over 104 rows in <1ms; linear-scan ceiling ≈ 40k rows/frame |
| JS payload | < 250 KB | 198 KB raw / **62.6 KB** gzip |
| Rebuild | offline, deterministic, no secrets | `pipeline/corpus.jsonl` → all surfaces, byte-stable (`--check`) |
| Agent access | readable without a human | 6 read surfaces + schema + OpenAPI + `llms.txt` + SKILL.md + MCP stdio server |

Feasibility rests on three verified facts (recon 2026-09-18, §1 of the panel): the
public hackathon API yields event metadata as *data*; gallery pages yield ~24
projects per request server-side; project pages yield likes, tags, awards and the
eight authored sections. Any one of those alone would not justify the design.

**Why not just scrape everything?** Devpost holds 10⁵–10⁶ projects. A firehose
indexed by popularity would reproduce the platform's own front page — the panel
graded that as negative value for an *inspiration* tool (see §3.2 objections
Nwosu→Voss, Tanabe→Voss). We optimize ideas-per-minute, not rows-per-night.

---

## 2 · Domain taxonomy: three orthogonal axes

toolscour classifies *libraries* by what they run on. Hackathon projects must be
classified by **what you can copy from them**, which is a different shape:

| Axis | Answers | Cardinality | Where |
| --- | --- | --- | --- |
| `domain` + `subsystem` | "which shelf do I browse?" | 10 (+1 explicit unshelved bucket), ~40 subsystems | `DOMAINS` |
| `moves[]` | "which transferable trick does this demonstrate?" | 18 | `MOVES` |
| `stack[]` | "what did they actually build with?" | open (authors' tags first, lexicon second) | `STACK_LEXICON` |

```
   shelf (domain)      : navigation, low cognitive load, colour-coded
   move                : the stealable mechanism — first-class, own postings index,
                         own /data/moves.json, own MCP tool (`list_moves`)
   stack               : feasibility — what a weekend build needs
   domain_margin       : confidence, exposed so nobody over-trusts a heuristic
```

The move vocabulary is the deliberate deviation from the reference architecture.
Each move ships three things: a `definition` (what it is), `steal_this` (the
imperative for a builder), and a regex detector so it can be *derived at build
time* rather than hand-tagged — and each is capped at 4 per record to keep
precision over recall.

**Classification contract.** `classify_record()` scores a weighted lexicon vote
(name/summary ×2.0 weight, authored prose ×1.0, sector `signature` terms ×3.0/1.5)
over the project's *own* text. Two rules learned during the build, both tested:
1. Event title and event themes are **excluded** — "Build with Gemini XPRIZE"
   would otherwise shelve a thousand projects under Developer Tooling because of
   the word "build".
2. Short keywords match as whole words, long ones as stems — otherwise `cli`
   matches "CLIP" and `crop` matches an image transform.

Zero-score records land in `Emerging & Cross-Domain` with `domain_margin 0.0`
instead of being silently misfiled.

---

## 3 · Data acquisition architecture

```
┌──────────────────────── INGESTION TIERS (priced per request) ────────────────────────┐
│ L1 discover                    L2 gallery                        L3 deep            │
│ GET /api/hackathons            {slug}.devpost.com/project-gallery  /software/{slug}   │
│ 10 events/req · JSON · no auth ~24 projects/req · HTML parse      1 project/req · HTML │
│ → event dimension table        → listing rows (name, slug, hook, → likes, built-with, │
│   prizes · registrations ·       thumbnail, event)                  awards, links,    │
│   themes · gallery URL                                             8 authored sects  │
└──────────────┬──────────────────────────┬───────────────────────────┬────────────────┘
               ▼                          ▼                           ▼
     ┌─────────────────────────────────────────────────────────────────────────┐
     │  NORMALIZE & DEDUPE  canonical key = slug (never name: two "NeuroGuard   │
     │  AI" records exist in one event); append-only JSONL; idempotent merge;   │
     │  quality gate min_coolness ≥ 0.18 + placeholder-summary rejection         │
     └───────────────────────────────┬─────────────────────────────────────────┘
                                     ▼
     ┌─────────────────────────────────────────────────────────────────────────┐
     │  ENRICH (taxonomy_hacks.enrich_project_record)                            │
     │  domain+subsystem vote · move detection · stack union (observed first) ·  │
     │  specificity · event prestige · recency · kin-redundancy (Jaccard) ·      │
     │  coolness (6 terms, published weights) · inspiration_intel synthesis ·    │
     │  provenance map per field                                                  │
     └───────────────────────────────┬─────────────────────────────────────────┘
                                     ▼
     ┌─────────────────────────────────────────────────────────────────────────┐
     │  PUBLISH (one emitter, six surfaces + contract)  — see §5                │
     └─────────────────────────────────────────────────────────────────────────┘
```

**Two ingestion paths, one enrichment path.** `pipeline/ingest_seed.py` (offline,
reads committed captures in `pipeline/raw/`) and `pipeline/harvest_devpost.py`
(live, network) both end in `enrich_project_record()`, so seed and live records are
indistinguishable downstream. That is what lets the repo build inside a network-
isolated sandbox and still be a real crawler.

**Politeness is implemented, not promised:** ≥1.25 s between requests with jitter,
declared `User-Agent` with contact, robots.txt cached in `pipeline/state/` and
**fail-closed**, exponential backoff on 429/503, resume state so an interrupted
cron loses nothing, `--dry-run` everywhere, and a 60%-floor assertion that refuses
to publish a collapsed corpus.

**Cadence: weekly (Mondays 03:00 UTC), not daily.** Hackathon records are
write-once; a daily crawl buys nothing and looks like an attack.

---

## 4 · Record schema (v1)

Tier-2 detail record — the full shape is generated into
`web/public/agents/schema.json` with `x-provenance` on every field:

```json
{
  "id": "greenlight-nine-agent-production-crew",
  "name": "Greenlight — Nine-Agent Production Crew",
  "url": "https://devpost.com/software/greenlight-nine-agent-production-crew",
  "summary": "Nine agents turn a screenplay into a film — and quote you the cost…",
  "likes": null,
  "award": "Submitted / No Award",
  "depth": "deep",
  "event": { "title": "All Things Agentic Hackathon", "org": "Google",
             "registrations": 12308, "prize_usd": 180000, "date": "2026-08-31",
             "themes": ["Enterprise", "Machine Learning/AI", "Productivity"] },
  "domain": "Creative Media, Story & Play",
  "subsystem": "Production & Direction",
  "domain_margin": 0.67,
  "moves": ["price-before-generate", "crew-of-specialists", "model-cost-routing", "data-flywheel"],
  "stack": ["cloud run", "vertex ai", "clickhouse", "firestore", "mcp", "react"],
  "coolness": 0.429,
  "coolness_parts": { "engagement": 0.22, "validation": 0.12, "event_prestige": 0.79,
                      "recency": 0.97, "specificity": 0.72, "signal_richness": 0.83,
                      "redundancy": 0.31, "total": 0.429 },
  "specificity": 0.72,
  "provenance": { "likes": "unavailable", "summary": "observed", "built_with": "observed",
                  "domain": "derived", "moves": "derived", "coolness": "derived",
                  "event": "observed", "award": "observed" },
  "inspiration_intel": {
    "the_wedge": "Video models are good enough, but they levy an entry fee…",
    "what_it_does": "Drop a screenplay; nine agents read it, split it into shots…",
    "naive_version_vs_this": "A prompt box that asks a human to describe what they want…",
    "reuse_surface": "portable to any product with an expensive generation step",
    "how_they_built_it": "One Cloud Run service; model assigned by shape of work…",
    "hard_won_lesson": "$150 of credits against $1 per 10s of footage…",
    "proof_points": "Locking a character reference lifts first-pass success 29%→49%…",
    "steal_this": ["Model your most expensive operation as a priced quote…"]
  },
  "quote": "Gates are real state transitions, not polite requests in a prompt…",
  "harvested_at": "2026-09-18", "scoring_version": 1, "taxonomy_version": 1
}
```

Tier-1 row (14 columns, dictionary-encoded):

```
[id, name, hook≤96, event_id, likes|-1, coolness_x1000, domain_id, subsystem_id,
 move_ids[], stack_ids[], is_deep, has_thumbnail, award_id, event_age_days]
```

`likes: -1` ⇄ `null` — a missing signal is encoded as *missing*, never as zero.
That single convention is what keeps the ranking honest at listing depth.

---

## 5 · Ranking: `coolness` (explainable, versioned, re-rankable)

```
coolness = 0.30·engagement      log-scaled Devpost likes (null → 0.22 prior, never 0)
         + 0.22·validation      judge/editorial award tier (Unknown → 0.10)
         + 0.14·event_prestige  0.55·log₁₀(registrations)/4.6 + 0.30·log₁₀(prize)/6.5
                                + 0.08·featured + 0.07·winners_announced (0.38 floor for
                                editorial rails that have no scale numbers)
         + 0.10·recency         0.5 ** (age_days / 426)      (14-month half-life)
         + 0.14·specificity     mechanism verbs, numbers, stack tags, length tiers
         + 0.10·signal_richness depth + thumbnail + published links
         − 0.12·redundancy      nearest-neighbour Jaccard; browse-time only, never deletes
```

Properties under test (`pipeline/tests/test_pipeline.py`): monotonic in likes;
`unknown likes > zero likes`; every component in [0,1]; total equals the published
linear combination (so a re-ranking in SQL matches ours exactly). Admission gate:
`coolness ≥ 0.18` and not a placeholder summary.

Why public weights beat a hidden model: an agent must be able to *disagree*. Drop
`engagement` in SQL and you get "underrated mechanisms"; that query is the reason
the formula is documented in three places.

---

## 6 · Multi-agent implementation model

The reference blueprint names five implementation personas. Here they are, mapped
to files, plus the review panel that argued them out (full record in
`EXPERT_PANEL.md`):

| Persona | Responsibility | Realized in |
| --- | --- | --- |
| **Harvester** | polite multi-tier acquisition, dedupe, resume | `pipeline/harvest_devpost.py` |
| **Taxonomy Engine** | sectors, moves, stack, specificity, inspiration synthesis | `pipeline/taxonomy_hacks.py` |
| **Shard Engineer** | dictionary encoding, tier split, budget gates, parity | `pipeline/shard_builder.py` |
| **Remix Architect** | idea collisions → build briefs at build time | `pipeline/generate_remixes.py` |
| **Agent-Interop Engineer** | schema/OpenAPI/llms.txt/SKILL.md/MCP, generated not hand-written | `pipeline/build_agent_api.py`, `mcp/ideasgalore_mcp.py` |
| *(panel)* 8 reviewers | acquisition, IA, interop, performance, product, ranking, ethics, ops | `docs/EXPERT_PANEL.md` |

Persona contract that matters most: **provenance**. Any field the project team did
not state is labelled `derived` or `editorial`, in the data and in every MCP tool
response, so an agent cannot accidentally present our heuristic as someone's claim.

---

## 7 · Technology stack & layout

React 18 + Vite 5 + Tailwind 3 + lucide-react; no chart/3D/UX library (the Atlas is
hand-projected canvas). Python 3.11 **stdlib-only** pipeline (`urllib`, `re`,
`sqlite3`, `gzip`, `json`, `unittest`) — no lockfile to rot, nothing to install to
rebuild. Static hosting on GitHub Pages.

```
Ideasgalore/
├── .github/workflows/deploy.yml        Pages build · weekly harvest · gate-checked
├── docs/{EXPERT_PANEL,METHODOLOGY_BLUEPRINT→this,DESIGN,DATA_ETHICS,AGENT_ACCESS}.md
├── mcp/ideasgalore_mcp.py              stdio MCP server, 8 tools, stdlib only
├── pipeline/
│   ├── raw/{seed_gallery.tsv,events.json,deep_records.json,overrides.json}
│   ├── taxonomy_hacks.py  harvest_devpost.py  ingest_seed.py
│   ├── shard_builder.py   generate_remixes.py  build_agent_api.py
│   ├── corpus.jsonl        ← single source of truth
│   └── tests/test_pipeline.py  (34 tests)
└── web/
    ├── public/
    │   ├── catalog-packed.json  catalog-stats.json  manifest.json
    │   ├── data/{details/*.json, hackathons.json, moves.json, sectors.json,
    │   │         ideas.csv, ideas.ndjson, ideasgalore.sqlite.gz, remixes.json}
    │   └── agents/{llms.txt, RECIPES.md, schema.json, openapi.json, ethics.json,
    │               skill/ideas-galore/SKILL.md}
    └── src/{App.jsx, IdeaAtlas.jsx, IdeaInspector.jsx, IdeaForge.jsx, lib.js, index.css}
```

`make verify` = ingest → build → regenerate in a temp dir → byte-diff → parity +
budget + schema gates → 34-test suite. CI runs exactly that, so the repo can never
contain data the code cannot reproduce.

Two rules make that claim survive contact with reality, both found by the gate itself:
- **The as-of date is a property of the corpus, not of the clock.** `recency` feeds
  `coolness`, so a packer that read `date.today()` would silently re-rank the catalog
  every morning and make the byte-diff gate useless. `shard_builder.corpus_as_of()`
  therefore defaults to the newest `harvested_at` in `corpus.jsonl` (and
  `ingest_seed.py` derives its date from the stamp inside `raw/`); `--today` remains
  the explicit override for a live refresh.
- **Gzip gets `mtime=0`.** A gzipped artifact that embeds build time in its header
  differs on every run, which is how `data/ideasgalore.sqlite.gz` once passed a
  three-file determinism check and failed a full-tree one. The test now walks *every*
  emitted file except `manifest.json` (the one surface that is build metadata on
  purpose, and the one path CI's drift check excludes).
