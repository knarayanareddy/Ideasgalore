---
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

`https://knarayanareddy.github.io/Ideasgalore` — static, no auth, CORS-open, weekly refresh.

## Procedure

1. **Translate the request into a move or a sector, not a keyword.** "I want an
   agent that can't be trusted blindly" → `human-holds-the-last-button` or
   `deterministic-guardrail`. `curl -sL {base}/data/moves.json | jq '.moves|keys'`
   lists the 18 terms with definitions.
2. **Select candidates** from the tabular surface (cheap, one request):
   `curl -sL {base}/data/ideas.ndjson | jq -c 'select(.moves|index("MOVE"))|{name,url,domain,coolness,summary}'`
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

- `random_muse`: `jq -s '.[ (now*1000|floor) % length ]' {base}/data/ideas.ndjson`
- By sector: `{base}/data/details/agentic-autonomy-and-orchestration.json`
- Event bias check before you generalize: `{base}/data/hackathons.json`

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
