"""
Ideas Galore — Agent Contract Builder (ADR-14)
==============================================
Generates the machine-readable contract from the *same* vocabulary the UI uses,
so documentation can never drift from the schema:

  web/public/agents/llms.txt        what an agent reads first
  web/public/agents/schema.json     JSON Schema 2020-12 + x-provenance per field
  web/public/agents/openapi.json    OpenAPI 3.1 for the static read surfaces
  web/public/agents/ethics.json     machine-readable usage policy (ADR-12)
  web/public/agents/RECIPES.md      copy-pasteable curl/jq recipes
  web/public/agents/skill/ideas-galore/SKILL.md   agent-skill pack

Usage: python3 pipeline/build_agent_api.py
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, Dict, List

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(os.path.join(REPO, "pipeline"))
from taxonomy_hacks import (  # noqa: E402
    AUDIT_PUBLISH_VERDICTS, CSV_COLUMNS, DOMAINS, MOVES, POOL_CSV_COLUMNS, ROW_FORMAT,
    SCORING_VERSION,
    audit_rubric,
)

PAGES = "https://knarayanareddy.github.io/Ideasgalore"
OUT_DEFAULT = os.path.join(REPO, "web", "public", "agents")

# ROW_FORMAT / CSV_COLUMNS come from taxonomy_hacks — the same lists shard_builder emits.
# They used to be copies here, and they silently drifted when the audit columns landed.
audit_rub = audit_rubric()


def record_schema() -> Dict[str, Any]:
    """Tier-2 detail record shape, with provenance declared per field."""
    s: Dict[str, Any] = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": f"{PAGES}/agents/schema.json",
        "title": "Ideas Galore — Hackathon Project Record",
        "description": ("One hackathon project, mined from Devpost for inspiration. "
                        "Fields are labelled observed (from Devpost), derived (our "
                        "classifier/score) or editorial (hand-curated). Never treat a "
                        "derived field as a fact stated by the project team."),
        "type": "object",
        "required": ["id", "name", "url", "domain", "moves", "coolness", "provenance"],
        "additionalProperties": True,
        "properties": {
            "id": {"type": "string", "description": "Devpost software slug — canonical key. NOT the display name (two projects can share a name).", "x-provenance": "observed"},
            "name": {"type": "string", "x-provenance": "observed"},
            "url": {"type": "string", "format": "uri", "description": "Canonical Devpost page. Always link back to this.", "x-provenance": "observed"},
            "summary": {"type": "string", "maxLength": 600, "description": "The team's own one-liner, whitespace-normalized.", "x-provenance": "observed"},
            "likes": {"type": ["integer", "null"], "minimum": 0, "description": "Devpost likes (their engagement unit) when a deep fetch ran; null means NOT zero.", "x-provenance": "observed"},
            "award": {"type": "string",
                      "description": "Judge-validated signal where observed; 'Unknown' when not fetched — do not read it as 'no award'.", "x-provenance": "observed"},
            "event": {"type": "object", "properties": {
                "slug": {"type": ["string", "null"]}, "title": {"type": ["string", "null"]},
                "org": {"type": ["string", "null"]}, "url": {"type": ["string", "null"]},
                "date": {"type": ["string", "null"], "description": "Submission close date (ISO)."},
                "registrations": {"type": ["integer", "null"]}, "prize_usd": {"type": ["integer", "null"]},
                "themes": {"type": "array", "items": {"type": "string"}}}, "x-provenance": "observed"},
            "domain": {"type": "string", "enum": [*DOMAINS.keys(), "Emerging & Cross-Domain"],
                       "description": "Navigation shelf. Derived by lexicon vote; check domain_margin before trusting.", "x-provenance": "derived"},
            "subsystem": {"type": "string", "x-provenance": "derived"},
            "domain_margin": {"type": "number", "minimum": 0, "maximum": 1,
                              "description": "Winning-sector margin over runner-up. <0.2 means 'browse, don't trust'."},
            "moves": {"type": "array", "maxItems": 4, "items": {"type": "string", "enum": list(MOVES)},
                      "description": "The inspiration axis: transferable design tricks this project demonstrates. Definitions in /data/moves.json.",
                      "x-provenance": "derived"},
            "stack": {"type": "array", "items": {"type": "string"},
                      "description": "Technologies: authors' own built-with tags first (observed), lexicon matches appended (derived).",
                      "x-provenance": "mixed"},
            "coolness": {"type": "number", "minimum": 0, "maximum": 1,
                         "description": f"Admission + ranking score, scoring_version {SCORING_VERSION}. Decompose it with coolness_parts; re-rank freely.",
                         "x-provenance": "derived"},
            "coolness_parts": {"type": "object", "description": "Published weight components — the reason this record ranks where it does.",
                               "properties": {k: {"type": "number"} for k in
                                              ["engagement", "validation", "event_prestige", "recency",
                                               "specificity", "signal_richness", "redundancy", "total"]}},
            "specificity": {"type": "number", "description": "Did the team describe a mechanism (numbers, verbs, stack) or only a vibe?", "x-provenance": "derived"},
            "depth": {"type": "string", "enum": ["listing", "deep"],
                      "description": "Harvest tier. 'deep' means the project page itself was fetched."},
            "repo_url": {"type": ["string", "null"], "description": "Code link if the team published one.", "x-provenance": "observed"},
            "demo_url": {"type": ["string", "null"], "x-provenance": "observed"},
            "video_url": {"type": ["string", "null"], "x-provenance": "observed"},
            "thumbnail": {"type": ["string", "null"], "description": "Hotlinked Devpost CDN asset. Reference by URL; we never copy these into the repo (ADR-12).", "x-provenance": "observed"},
            "inspiration_intel": {"type": "object", "description": "Builder-facing synthesis: the wedge, what to steal, naive-vs-this, reuse surface, and (deep only) the team's own account.",
                                  "properties": {k: {"type": ["string", "null"]} for k in
                                                 ["the_wedge", "what_it_does", "naive_version_vs_this",
                                                  "reuse_surface", "how_they_built_it", "hard_won_lesson",
                                                  "proof_points", "next_moves"]},
                                  "additionalProperties": True, "x-provenance": "derived"},
            "quote": {"type": ["string", "null"], "maxLength": 220,
                      "description": "Short attributed quote from the team's own 'how we built it'. Bulk exports omit it by policy.",
                      "x-provenance": "observed"},
            "audit": {"type": ["object", "null"], "description":
                      ("Evidence-gated verdict for this project. Present on every PUBLISHED "
                       "record, because publication requires an audit. null means the record "
                       "came from a build without audit.jsonl — treat its claims as unaudited."),
                      "x-provenance": "audited", "additionalProperties": True,
                      "properties": {
                          "verdict": {"enum": list(audit_rub["verdicts"]),
                                      "description": "Publication decision. Only "
                                                     + "/".join(audit_rub["published_verdicts"])
                                                     + " are published. " + "; ".join(
                                                          f"{k} = {v}" for k, v in audit_rub["verdicts"].items())},
                          "worth": {"enum": list(audit_rub["worth"]) + ["unrated"],
                                    "description": "Is it a good idea for a builder to copy, independent of "
                                                   "soundness. " + "; ".join(f"{k} = {v}" for k, v in audit_rub["worth"].items())
                                                   + ". `unrated` = the auditor filed no judgement."},
                          "soundness": {"enum": ["verified", "partial", "weak", "unverified"],
                                        "description": "Band of the derived score — never hand-entered."},
                          "soundness_score": {"type": "number", "description": "Mean of scored checks, renormalized by evidence coverage."},
                          "rubric_coverage": {"type": "number", "description": "Fraction of rubric fields filed with an evidence status."},
                          "checks": {"type": "object", "description":
                                     ("check -> {status, score, why}. `confirmed` requires an "
                                      "independently reproducible artifact; `unverifiable` means "
                                      "the page made no checkable claim, which is not a failure."),
                                     "additionalProperties": {"type": "object"}},
                          "unknowns": {"type": "array", "items": {"type": "object"},
                                       "description": "Mandatory fields that could not be filled, with why and how to resolve. Never guess these."},
                          "clone_cost": {"type": ["object", "null"], "description":
                                         "{estimate, why, assumptions[]} — assumptions are the "
                                         "load-bearing part; read them before quoting the number."},
                          "what_to_steal": {"type": ["string", "null"], "description": "The transferable mechanism, not the product."},
                          "what_breaks_first": {"type": ["string", "null"], "description": "Where a rebuild dies first."},
                          "prior_art": {"type": "array", "description": "Named, linked existing systems — empty means 'searched, nothing found'."},
                          "hazard": {"type": ["object", "null"], "description":
                                     ("Regulated-outcome exposure: {class, team_disclaimed, note}. "
                                      "null = no regulated-claim language in the capture. A `class` "
                                      "with team_disclaimed=false is a warning to the reader, not a "
                                      "verdict on the team."),
                                     "additionalProperties": True},
                          "why_not_promoted": {"type": "array", "items": {"type": "string"},
                                               "description": "Only on held-back records: the derivation "
                                                              "trace (verdict reasons, named unknowns, hazard, "
                                                              "duplicate merge). Read this before re-auditing."},
                          "duplicate_of": {"type": ["string", "null"], "description": "id of the better-sourced sibling this row was merged into."},
                          "sheet": {"type": "string", "description": "Pointer into data/audits/<sector>.json#<id> for the full ledger."},
                      }},
            "provenance": {"type": "object", "description": "Field -> observed|derived|editorial|unavailable.", "additionalProperties": {"type": "string"}},
            "harvested_at": {"type": "string"},
            "scoring_version": {"type": "integer"},
            "taxonomy_version": {"type": "integer"},
        },
    }
    return s


def openapi() -> Dict[str, Any]:
    import re as _re
    return {
        "openapi": "3.1.0",
        "info": {
            "title": "Ideas Galore — Hackathon Inspiration Index",
            "version": "1.0.0",
            "description": ("Read-only static API. Every path is a committed JSON/CSV/NDJSON file "
                            "served by GitHub Pages with permissive CORS: no auth, no rate limit, "
                            "no write surface. ETag revalidation is supported by the CDN."),
            "contact": {"name": "Ideas Galore", "url": f"{PAGES}/"},
            "x-usage-policy": {"$ref": "./ethics.json", "note": "Honor attribution + no-mirror rules."},
        },
        "servers": [{"url": PAGES, "description": "GitHub Pages (static)"}],
        "paths": {
            "/catalog-packed.json": {"get": {"summary": "Tier-1 dictionary-encoded index (all admitted records)",
                "operationId": "getTier1",
                "responses": {"200": {"description": "rows[] + lookup dictionaries; row order fixed by row_format",
                    "content": {"application/json": {"schema": {"type": "object", "properties": {
                        "row_format": {"type": "array", "items": {"type": "string"}, "example": ROW_FORMAT},
                        "rows": {"type": "array", "items": {"type": "array"}}}}}}}}}},
            "/catalog-stats.json": {"get": {"summary": "Corpus totals + budget telemetry", "operationId": "getStats",
                "responses": {"200": {"description": "counts, shard sizes, gzip budget"}}}},
            "/manifest.json": {"get": {"summary": "Build provenance: corpus sha256, generated_at, surface list", "operationId": "getManifest",
                "responses": {"200": {"description": "verify what you loaded was built from what commit"}}}},
            "/data/pool.csv": {"get": {"summary": "Held-out records, same columns + why_not_promoted",
                    "operationId": "getPoolCSV", "tags": ["data"], "responses": {"200": {
                    "description": "CSV", "content": {"text/csv": {"schema": {
                        "type": "string",
                        "example": ",".join(POOL_CSV_COLUMNS)}}}}}}},
            "/data/ideas.csv": {"get": {"summary": "The tabular database (stable column order)", "operationId": "getCSV",
                "responses": {"200": {"description": "One row per admitted project; bulk exports omit authored prose by policy",
                    "content": {"text/csv": {"schema": {"type": "string", "example": ",".join(CSV_COLUMNS)}}}}}}},
            "/data/ideas.ndjson": {"get": {"summary": "Line-delimited full metadata for streaming", "operationId": "getNDJSON",
                "responses": {"200": {"description": "one JSON record per line", "content": {"application/x-ndjson": {}}}}}},
            "/data/hackathons.json": {"get": {"summary": "Event dimension table", "operationId": "getEvents",
                "responses": {"200": {"description": "prizes, registrations, themes, gallery urls, project counts"}}}},
            "/data/moves.json": {"get": {"summary": "Transferable-move vocabulary with postings and example ids", "operationId": "getMoves",
                "responses": {"200": {"description": "move -> definition, steal_this, count, examples[]"}}}},
            "/data/details/{domain}.json": {"get": {"summary": "Tier-2 deep shard for one domain (lazy-loaded by the UI)",
                "operationId": "getDomainShard",
                "parameters": [{"name": "domain", "in": "path", "required": True,
                                "schema": {"type": "string", "enum": [_re.sub(r"[^a-z0-9]+", "-", d.lower().replace("&", "and")).strip("-") for d in DOMAINS]}}],
                "responses": {"200": {"description": "map of id -> deep record (schema.json)"}}}},
            "/data/audits.json": {"get": {"summary": "Audit index: verdict + score for every audited record",
                "operationId": "getAuditIndex",
                "responses": {"200": {"description": "records{id: {verdict, worth, soundness, score, coverage, checks(status only), unknowns, sheet}}"}}}},
            "/data/audits/{sector}.json": {"get": {"summary": "Full audit sheets for one sector: evidence ledger, per-check reasons, all mandatory fields",
                "operationId": "getAuditSheets",
                "parameters": [{"name": "sector", "in": "path", "required": True,
                                "schema": {"type": "string", "enum": [_re.sub(r"[^a-z0-9]+", "-", d.lower().replace("&", "and")).strip("-") for d in DOMAINS]}}],
                "responses": {"200": {"description": "records{id: sheet} — sheet.fields[f] = {value, evidence, confidence, status, why?}"}}}},
            "/data/pool.json": {"get": {"summary": "Unaudited / rejected records — NOT inspiration-grade; why_not_promoted is per-record",
                "operationId": "getPool",
                "responses": {"200": {"description": "thin/duplicate/unsound/hazard-blocked + never-audited rows. Never present one as vetted."}}}},
            "/data/audit-rubric.json": {"get": {"summary": "The rubric itself: mandatory fields, checks, weights, verdict ladder, dedup + hazard rules",
                "operationId": "getAuditRubric",
                "responses": {"200": {"description": "what a sheet must contain to publish — machine-checkable",
                    "content": {"application/json": {"schema": {"type": "object", "example": audit_rub}}}}}}},
            "/data/remixes.json": {"get": {"summary": "Generated idea collisions with build briefs", "operationId": "getRemixes",
                "responses": {"200": {"description": "curated + mined pair recipes, each with first_48_hours and kill_criteria"}}}},
        },
    }


def llms_txt(stats: Dict[str, Any]) -> str:
    top = ", ".join(sorted(MOVES)[:6])
    cov = (stats.get("coverage") or {})
    sized = {k: v for k, v in (cov.get("events") or {}).items() if v.get("upstream_total")}
    cov_line = ""
    if sized:
        parts = ", ".join(f"{k} {v['published']}/{v['upstream_total']}" for k, v in sorted(sized.items()))
        cov_line = (
            "\n- **This index is a gated sample, not the platform.** The galleries we crawled report\n"
            f"  their own totals ({parts}); `catalog-stats.json` -> `coverage` repeats it in data.\n"
            "  Never write \"every hackathon project\" about this corpus — the defensible phrasing is\n"
            f"  \"{stats.get('total')} admitted projects from the pages captured\".\n")
    return f"""# Ideas Galore — the Hackathon Inspiration Index

> A curated, scored, machine-readable index of hackathon projects mined from the
> Devpost public showcase, organized so a builder (human or agent) can answer
> "what should I steal next?" — not "what exists?".
> Static files only: no auth, no keys, no rate limit. CORS-open. Last build:
> {stats.get('generated_at')} · {stats.get('total')} audited, publishable projects ·
> {stats.get('events')} hackathons · {stats.get('moves')} transferable moves ·
> {stats.get('pool_records', '?')} more projects held out of the catalog pending audit.

## Read this before you use the data
{cov_line}
- `agents/schema.json` — record contract, with `x-provenance` on every field.
- `agents/ethics.json` — usage policy we are ourselves bound by; honour it downstream.
- `agents/RECIPES.md` — curl + jq patterns that actually work.
- Attribution: every record carries `url`. When you surface a project, link back to
  its Devpost page and name the hackathon. Do not republish the teams' authored text
  at bulk scale; summarize and link.
- `likes: null` means "not fetched", never "zero". Same for `award: "Unknown"`.

## Endpoints (relative to the site root)

- `catalog-packed.json` — Tier-1: every admitted row, dictionary-encoded. Best for
  whole-corpus ranking/filtering in one request (~{stats.get('tier1_gzip_kb')} KB gzip).
- `data/ideas.csv` — the tabular database; stable column order, spreadsheet-safe.
- `data/pool.csv` — the same columns in the same order, plus `provenance`,
  `why_not_promoted`, `would_settle_it`. `verdict` blank means never audited; `provenance`
  says whether a row was scored and held (`audited-hold`) or never captured (`unaudited`).
- `data/ideas.ndjson` — full metadata, one record per line, no bulk prose.
- `data/hackathons.json` — event dimension: prize, registrations, themes, gallery URL.
- `data/moves.json` — the inspiration vocabulary: definition + `steal_this` per move,
  with posting counts and example project ids. Start here for "ideas for X".
- `data/details/<domain>.json` — Tier-2 deep shard per sector (the only place the
  condensed authored sections and quotes live). Lazy-load one, not all.
- `data/remixes.json` — pre-computed idea collisions with build briefs
  (`first_48_hours`, `kill_criteria`).
- `data/audits.json` — verdict + score + per-check status for every published record
  (~150 B each). The cheap answer to "is this vetted, and how?".
- `data/audits/<sector>.json` — full audit sheets for that sector: the evidence ledger,
  per-check reasoning, and all 12 mandatory fields (`what_to_steal`, `clone_cost` with
  assumptions, `unknowns`, `prior_art`, `hazard`). Detail shard, not default.
- `data/audit-rubric.json` — the rubric itself (mandatory fields, checks, weights, verdict
  ladder, dedup and hazard rules) so you can audit new candidates yourself the same way.
- `data/pool.json` — records held *out* of the catalog. `provenance` separates the two kinds:
  `audited-hold` (captured, scored, and held: `thin` / `duplicate` / hazard-capped) from
  `unaudited` (never captured). Both carry `why_not_promoted[]` and `would_settle_it[]`.
  Queryable for lead-mining; never present one as vetted.
- `catalog-stats.json` / `manifest.json` — corpus counts + build provenance (sha256).

## The audit (read this before you trust a record)

Every published project passed an evidence-gated audit: 12 mandatory fields, 6 technical
checks whose score is derived from an evidence ledger (`kind` + `locator` — a citation, not
an assertion), then a verdict. A dedicated auditor may only supply editorial judgement and
citations; every status is recomputed mechanically.

- Verdicts published: {", ".join(AUDIT_PUBLISH_VERDICTS)}. `thin` / `duplicate` / `unsound`
  / hazard-blocked live in `data/pool.json` instead.
- `confirmed` means we reproduced it from something we could reach (repo, deployment, video,
  benchmark table). `unverifiable` means the page made no checkable claim — it is NOT a
  failure and must not be reported as a false claim.
- `rubric_coverage` < 1 means the record is *silent* somewhere; `unknowns[]` says where and
  how to resolve it. Quote the unknown, do not fill it in.
- `duplicate_of` merges resubmissions of the same product (shared numeric fingerprints catch
  what prose similarity cannot).
- A missing `audit` block means the record predates the audit layer — treat it as unaudited.

## Sectors
{chr(10).join(f"- {d} — {v['blurb']}" for d, v in DOMAINS.items())}

## Moves (the axis that generates new projects)

{chr(10).join(f"- `{m}` — {MOVES[m]['steal_this']}" for m in list(MOVES)[:10])}

…full list in `data/moves.json` (first six alphabetically: {top}).

## Scoring (explainable by design)

`coolness = 0.30·engagement + 0.22·validation + 0.14·event_prestige + 0.10·recency +
0.14·specificity + 0.10·signal_richness − 0.12·redundancy` (scoring_version {SCORING_VERSION}).
Each component ships per record in `coolness_parts`, so re-ranking is a division, not
a guess. `engagement` is log-scaled Devpost likes; `validation` is judge/editorial
awards; `redundancy` only ever de-duplicates browse views, it never deletes records.

## Doing this in SQL instead

Unzip the SQLite surface and use stdlib `sqlite3` (or DuckDB / Datasette if you have them):

```bash
curl -sL {PAGES}/data/ideasgalore.sqlite.gz | gunzip > idea_galore.sqlite
python3 -c "import sqlite3; print(sqlite3.connect('idea_galore.sqlite').execute(
  'SELECT name, domain, round(coolness,3) FROM projects ORDER BY coolness DESC LIMIT 5'
).fetchall())"
```

Tables: `events`, `projects`, `moves`, `project_moves` (many-to-many). The CSV surface
is equally queryable without a database step:

```bash
duckdb -c "SELECT name, domain, moves FROM '{PAGES}/data/ideas.csv'
           WHERE list_contains(string_split(moves, '|'), 'evidence-graph')
           ORDER BY coolness DESC LIMIT 10"
```

## Give an agent tools, not a dump

```bash
git clone https://github.com/knarayanareddy/Ideasgalore
python3 Ideasgalore/mcp/ideasgalore_mcp.py --base {PAGES}   # stdio MCP, stdlib only
```

Tools: `search_projects`, `get_project`, `list_moves`, `ideas_for_goal`, `similar_to`,
`random_muse`, `remix_briefs`.

## Source & freshness

Devpost public pages (`api/hackathons`, `project-gallery`, `/software/*`). Refreshed
weekly (Mondays) — hackathon records are effectively immutable, so staleness here
means "a new project exists", not "the data is wrong". See `docs/DATA_ETHICS.md`.
"""


def recipes() -> str:
    return f"""# Agent recipes — Ideas Galore

All reads are plain static files. `{PAGES}` is the site root (also works from a local
checkout: `python3 -m http.server -d web/dist`).

## Top 20 by coolness, one line each

```bash
curl -sL {PAGES}/data/ideas.csv | head -1
# columns are quoted and the audit block leads, so parse by name, not by position:
curl -sL {PAGES}/data/ideas.csv | python3 -c "
import csv, sys
rows = sorted(csv.DictReader(sys.stdin), key=lambda r: -float(r['coolness']))
for r in rows[:20]:
    print(f\"{{r['coolness']}}  {{r['verdict']:18}}  {{r['name']}}\")"
```

## Every project that demonstrates a given move

```bash
curl -sL {PAGES}/data/ideas.ndjson | \\
  jq -c 'select(.moves | index("price-before-generate")) |
          {{name, url, domain, coolness}}'
```

## Ideas for a goal, ranked by specificity (not popularity)

```bash
curl -sL {PAGES}/data/ideas.ndjson | \\
  jq -r 'select(.specificity? // .coolness_parts.specificity > 0.5)
         | [.coolness_parts.specificity, .name, .url] | @tsv' | sort -gr | head -10
```

## Sector shard, then pull one record's deep intel (two hops, never the whole corpus)

```bash
curl -sL {PAGES}/data/details/public-trust-safety-and-compliance.json | jq 'keys[:5]'
curl -sL {PAGES}/data/details/public-trust-safety-and-compliance.json | jq '.["realityCheCk"] // .[] | select(.id=="complianceguardian-kcqs32")'
```

## Which events is this corpus biased toward?

```bash
curl -sL {PAGES}/data/hackathons.json | jq -r '.events[] | [.project_count, .title, .prize_usd] | @tsv'
```

## Build brief for the next hackathon (curated collisions)

```bash
curl -sL {PAGES}/data/remixes.json | jq '.recipes[0] | {{title, the_wedge, first_48_hours, kill_criteria}}'
```

## Audited picks only, with the reasoning inline

```bash
# cheap filter (Tier-1 ids), then the sheet for the two survivors
curl -sL {PAGES}/catalog-packed.json | jq -r \
  '[.rows[] | select(.verdict_id != null)] | length'
curl -sL {PAGES}/data/audits.json | jq -r \
  '.records | to_entries[] | select(.value.rubric_coverage > 0.6) | .key'
curl -sL {PAGES}/data/audits/creative-media-story-and-play.json | jq -r \
  '.records | to_entries[0].value | {{id, verdict, worth, what_to_steal: .fields.what_to_steal.value, unknowns: [.unknowns[].field]}}'
```

## "What can I clone this weekend?" — filter on clone_cost assumptions, not the headline

```bash
curl -sL {PAGES}/data/audits/creative-media-story-and-play.json | jq -r \
  '.records | to_entries[] | .value.fields.clone_cost.value
   | select(.estimate != null) | "\(.estimate) — assumes: \(.assumptions | join("; "))"'
```

## Find leads the audit refused to publish (and why)

```bash
curl -sL {PAGES}/data/pool.json | jq -r '.records[] | "\(.id) · \(.verdict) · \(.why_not_promoted // "never audited")"'
```

## Verify what you loaded

```bash
curl -sIL {PAGES}/catalog-packed.json | grep -i etag        # revalidate, don't refetch
curl -sL {PAGES}/manifest.json | jq '.corpus_sha256, .scoring_version'
```

## Politeness expected of you

- Cache the response (ETag/`If-None-Match`); these files change weekly, not per minute.
- Never bulk-fetch `data/details/*.json` in a loop; fetch the one shard you need.
- Keep `url` attribution in anything you render, and respect `agents/ethics.json`.
"""


def ethics() -> Dict[str, Any]:
    return {
        "policy": "Ideas Galore data-usage policy (ADR-12)",
        "generated_for": "both this project and downstream consumers of it",
        "source": {
            "site": "https://devpost.com",
            "endpoints": ["https://devpost.com/api/hackathons", "{slug}.devpost.com/project-gallery",
                          "https://devpost.com/software/{slug}"],
            "robots_txt": "User-agent: * / Disallow: (open) — verified 2026-09-18; the operator "
                          "explicitly blocks named AI-training crawlers, which is respected by design.",
        },
        "we_collect": ["project identity + summary", "public engagement count (likes)", "awards where shown",
                        "author-declared technology tags", "links the team published",
                        "event metadata from the public JSON API"],
        "we_refuse": ["verbatim full-page mirroring or bulk prose in exports (Tier-2 stores a <=220-char quote)",
                       "team-member names, avatars, emails, votes, or profile pages",
                       "copying image/video assets into this repo (CDN URLs only)",
                       "authenticated or judge-only endpoints, scraper-token workarounds",
                       "sponsor prize claims not present in the public payload"],
        "crawling": {"min_interval_seconds": 1.25, "jitter": True, "user_agent": "IdeasGaloreBot/1.0 (+repo URL; contact in UA)",
                      "robots": "honored, cached in pipeline/state/robots.txt, fail-closed",
                      "backoff": "exponential on 429/503, hard stop on repeated failure",
                      "cadence": "weekly; records are write-once upstream"},
        "takedown": "Open an issue in the repository naming the record id; removal is a one-line change to "
                    "pipeline/raw/overrides.json plus a rebuild, and is honoured before any dispute.",
        "licensing": "Metadata is factual and shared with attribution. Project source code remains under each "
                     "team's own terms — check the repo before reuse; absence of a licence is not permission.",
        "for_downstream_agents": ["keep the `url` attribution on anything you render",
                                   "do not treat `likes: null` as zero",
                                   "do not present `derived` fields as the team's own claims",
                                   "summarize prose; link for the original",
                                   "cache; the corpus changes weekly, not hourly"],
    }


def skill_md() -> str:
    return f"""---
name: ideas-galore
description: Find transferable design tricks in real hackathon projects to inspire a new build. Use when asked for project ideas, prior art, "has anyone built X", patterns for a problem, or a starter brief for a hackathon. Reads a static, scored index of Devpost projects.
version: 1.0.0
---

# Ideas Galore — inspiration lookup

The index answers "what can I steal?" It stores hackathon projects with an
explainable `coolness` score and, more importantly, a `moves[]` vocabulary of
transferable design tricks (e.g. `price-before-generate`, `evidence-graph`,
`human-holds-the-last-button`, `offline-first-fallback`).

## Base URL

`{PAGES}` — static, no auth, CORS-open, weekly refresh.

## Procedure

1. **Translate the request into a move or a sector, not a keyword.** "I want an
   agent that can't be trusted blindly" → `human-holds-the-last-button` or
   `deterministic-guardrail`. `curl -sL {{base}}/data/moves.json | jq '.moves|keys'`
   lists the 18 terms with definitions.
2. **Select candidates** from the tabular surface (cheap, one request):
   `curl -sL {{base}}/data/ideas.ndjson | jq -c 'select(.moves|index("MOVE"))|{{name,url,domain,coolness,summary}}'`
   Sort by `.coolness` for proven strength, or `.coolness_parts.specificity` for
   stealable *mechanisms* (preferred for ideation).
3. **Read the detail for what you shortlist** — `data/details/<domain-slug>.json`
   holds `inspiration_intel` (`the_wedge`, `naive_version_vs_this`,
   `reuse_surface`, `hard_won_lesson`) and a short attributed `quote`.
4. **For a fresh idea, collide two projects**: `data/remixes.json` → pick a recipe
   whose `shared_moves` or domains are adjacent to the request and reuse its
   `first_48_hours` + `kill_criteria` verbatim as scaffolding.
5. **Cite.** Every answer must include the project `url` and its event title.
   Note when a signal is missing: `likes: null` / `award: "Unknown"` mean "not
   fetched", never "zero". Do not present `provenance: derived` fields as the
   team's own claims, and do not quote beyond the stored `quote` field
   (`agents/ethics.json`).

## Useful one-liners

- `random_muse`: `jq -s '.[ (now*1000|floor) % length ]' {{base}}/data/ideas.ndjson`
- By sector: `{{base}}/data/details/agentic-autonomy-and-orchestration.json`
- Event bias check before you generalize: `{{base}}/data/hackathons.json`

## Audit rules (these are the ones agents break)

1. Publication requires an audit: if `audit` is null, say "unaudited" in the same breath.
2. Report `unknowns` verbatim when you recommend a project — the gap is the useful part.
3. Never convert `unverifiable` into "false". Absence of evidence is not a debunking.
4. Quote `clone_cost.assumptions` next to the estimate; the number alone is misleading.
5. Dedup before you recommend: two entries sharing cost/percentage fingerprints are one product.
6. If you audit candidates yourself, follow `data/audit-rubric.json` and store citations,
   not opinions.

## Failure modes

404 on a domain shard → the sector slug is wrong; read keys from `catalog-stats.json`.
Empty result → your move term is too narrow: retry with `jq` on `.stack` or `.summary`.
Site unreachable → fall back to `data/ideas.csv` from a local checkout of the repo.
`verdict_id` null → the row predates the audit layer; treat its claims as unaudited.
"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=OUT_DEFAULT)
    args = ap.parse_args()
    stats_path = os.path.join(REPO, "web", "public", "catalog-stats.json")
    stats = json.load(open(stats_path, encoding="utf-8")) if os.path.exists(stats_path) else {}

    os.makedirs(f"{args.out}/skill/ideas-galore", exist_ok=True)
    writes = {
        f"{args.out}/llms.txt": llms_txt(stats or {"total": "?", "events": "?", "moves": len(MOVES),
                                                    "generated_at": "see manifest.json",
                                                    "tier1_gzip_kb": "?"}),
        f"{args.out}/RECIPES.md": recipes(),
        f"{args.out}/ethics.json": json.dumps(ethics(), indent=1),
        f"{args.out}/schema.json": json.dumps(record_schema(), separators=(",", ":")),
        f"{args.out}/openapi.json": json.dumps(openapi(), separators=(",", ":")),
        f"{args.out}/skill/ideas-galore/SKILL.md": skill_md(),
    }
    for path, body in writes.items():
        with open(path, "w", encoding="utf-8") as f:
            f.write(body if body.endswith("\n") else body + "\n")
        print(f"  📄 {os.path.relpath(path, REPO):48} {len(body) / 1024:5.1f} KB")
    print(f"✅ agent contract: {len(writes)} files -> {os.path.relpath(args.out, REPO)}/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
