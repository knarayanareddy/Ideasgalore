# Data Ethics & Sourcing Policy

*Machine-readable twin of this file: `web/public/agents/ethics.json` (generated from
`pipeline/build_agent_api.py`, so the policy and the shipped contract cannot drift).*

Ideas Galore indexes other people's work. That is the whole product, so the rules
below are implemented in code, not just written here.

## 1 · What we read, and why it is defensible

| Surface | Status | Our posture |
| --- | --- | --- |
| `devpost.com/api/hackathons` | public JSON, no auth, no key | Primary source for event metadata. It is the same endpoint the site's own listing pages use. |
| `{slug}.devpost.com/project-gallery` | public HTML, server-rendered | Listing-level metadata only: name, slug, one-line summary, thumbnail reference. |
| `devpost.com/software/{slug}` | public HTML | Fetched for a *sample* of records (depth tier), never en masse on a loop. |
| `/software/{slug}.json`, judge/entry endpoints | not public / requires auth | **Not used.** We do not route around a login, a key, or a rate limit. |

`robots.txt` on 2026-09-18: `User-agent: *` + `Disallow:` (nothing disallowed for
general crawlers), while `Bytespider`, `Omgilibot`, `Omgili`, `ImagesiftBot` and
`BLEXBot` are explicitly blocked. We read that as: *indexing is welcome; bulk
corpus harvesting for model training is not.* Our design follows the distinction —
a small, purposeful, attributed index rather than a mirrored snapshot of the site.

Enforcement in code (`pipeline/harvest_devpost.py`):
`robots_allowed()` parses robots.txt, caches it, **fails closed** on network error,
and refuses a request rather than ignoring a disallow. `polite_wait()` enforces
≥1.25 s between requests with jitter. The `User-Agent` identifies the project and
points at a contact route. 429/503 back off exponentially and the run stops rather
than hammering.

## 2 · What we store, and what we refuse to

Stored: project identity, the team's own summary line, like counts where shown,
awards where shown, `built with` tags the authors declared, links the authors
published, and event metadata from the public API.

Deliberately not stored:

- **Verbatim page mirrors.** Authored sections are kept as a **condensed paraphrase**
  (`inspiration_intel`) plus a single **≤220-character attributed quote**. Bulk
  surfaces (`ideas.csv`, `ideas.ndjson`) carry `has_deep: 0|1` and **no prose at all** —
  pinned by `test_bulk_exports_do_not_mirror_authored_prose`.
- **People.** No team-member names, handles, avatars, follower counts, contact
  details, vote counts or profile pages. Project-level facts only, so a student's
  submission cannot become a row in a person-shaped dataset.
- **Media bytes.** Thumbnails are referenced by their Devpost CDN URL and never
  copied into this repository; images stay under their authors' control and any
  deletion upstream propagates naturally.
- **Anything gated.** No prize-wallet data, no judging ballots, no private
  submissions, no `secure.devpost.com` flows.

## 3 · Attribution is a schema requirement, not a courtesy

Every record carries `url`, and every agent-facing response carries
`devpost_url` + `hackathon`. `SKILL.md` and the MCP server both instruct: cite the
source page when surfacing a project. A copy of any idea brief (UI: *copy as
markdown*) includes the links and a provenance footer.

## 4 · Honesty about derived labels

Heuristic fields — `domain`, `subsystem`, `moves`, `stack` (partly), `specificity`,
`coolness`, `inspiration_intel` — are marked `provenance: derived`, and
`domain_margin` publishes the classifier's confidence. `likes: null` and
`award: "Unknown"` mean *not fetched*, never *zero* — that distinction is encoded
in the Tier-1 format (`-1`) and re-stated in every MCP result.

A reader who mistakes our classification for a team's self-description is the most
likely way this project misleads someone; the labelling is the mitigation.

## 5 · Copyright and reuse by *you*

- **Metadata** (titles, one-line summaries, counts, links, awards) is factual and is
  shared here with attribution. Query it, fork it, embed it.
- **The projects themselves** remain their authors' work. Source code, when a team
  published it, is under *their* licence — check before reuse; absence of a licence
  file is not permission.
- **Our derived labels** are offered as an index, with the same freedom and the same
  request to attribute.

## 6 · Removal requests

If you built a project that appears here and want it gone (or corrected): open an
issue naming the record `id`. Removal is one line in `pipeline/raw/overrides.json`
plus a rebuild, and we act on request before any dispute. Because the corpus is
rebuildable, a `takedown` list is applied at build time — it survives re-harvests,
so "removed" does not silently reappear next Monday.

## 7 · If you are an agent consuming this data

1. Keep `url` attribution in anything you render or store.
2. Do not bulk-fetch `data/details/*.json` in a loop; fetch the one sector you need.
3. Do not republish our quotes at length, and do not reconstruct the source pages
   from our paraphrase — link instead.
4. Cache (ETag revalidation); the corpus changes weekly.
5. Do not present `derived` fields as claims made by the project team.

*These five lines are also in `agents/ethics.json` under `for_downstream_agents`,
which is deliberate: policy that is only readable by humans is policy that agents
break by default.*
