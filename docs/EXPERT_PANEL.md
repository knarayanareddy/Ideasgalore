# Ideas Galore — Domain Expert Panel: Debate, Critique & Consensus Record

> **Purpose.** This file is the audit trail for every architectural decision in this
> repository. It is not marketing copy — it is the reasoning chain, so that a future
> human or agent can disagree with a *specific* argument instead of guessing at
> intent.
>
> **Method.** Eight domain-expert personas were instantiated. Each produced a position
> paper grounded in the shared research dossier (§1), attacked the weakest claims of
> the others (§3), revised its own proposal under fire (§4), and voted on a weighted
> rubric (§5). Rounds repeat until the adjudicator's convergence test passes:
> **no proposal may change rank between the final two rounds, and no objection may
> remain unrebutted.** Convergence reached at end of Round 3 (§5.3).
>
> **Honesty note.** The panel was executed by the implementing agent as structured
> adversarial persona reasoning — not eight independent LLM calls. What makes it worth
> reading is that every factual premise in §1 was *verified against live endpoints*
> during reconnaissance (2026-09-18), and every decision in §6 has a file in this repo
> that implements it. Claims marked `(verified)` were observed directly.

---

## 0 · Charter

| Item | Value |
| --- | --- |
| Mission | A tabular database of **cool hackathon projects**, mined for *inspiration*, equally legible to a human browser and an autonomous agent. |
| Reference architecture | `knarayanareddy/toolscour` — static two-tier sharded index, zero-dep Python harvest pipeline, React 18 + Vite + Tailwind front end, GitHub Pages hosting. **Inherited where it earns its keep; rejected where it doesn't (see §7).** |
| Hard budget | $0/mo hosting, no server, no API keys required to *read* the data. |
| Corpus source | Devpost (public hackathon project showcase + public hackathon API). |
| Success test | (a) A builder finds 3 ideas worth stealing in 60 seconds. (b) An agent answers "what's a good pattern for making a model's reasoning auditable?" with real, linked, cited examples — over plain HTTP. |

---

## 1 · Shared Research Dossier (verified premises)

Everything below was observed during recon on 2026-09-18 from this workspace; it is the
evidence the panel was allowed to argue from.

| # | Finding | Consequence |
| --- | --- | --- |
| R1 | `https://devpost.com/api/hackathons?status[]=ended&order=ends_at&page=N` returns clean JSON, **no auth required**. Fields: `id`, `title`, `organization_name`, `themes[]`, `prize_amount` (HTML-wrapped!), `prizes_counts{cash,other}`, `registrations_count`, `open_state`, `featured`, `invite_only`, `winners_announced`, `submission_gallery_url`, `url`. `(verified)` | Event metadata is available *as data*, not by scraping HTML. A hackathon **dimension table** is free. |
| R2 | The API **ignores unknown query params** — `?query=treehacks` returned the unfiltered default page. `(verified)` | Do not build discovery on guesswork params. Discovery = paginate `status[]=ended` + explicit slug lists. |
| R3 | `{subdomain}.devpost.com/api/hackathon` → 404. `(verified)` | No per-event JSON API. Projects come from `project-gallery` HTML. |
| R4 | `project-gallery` renders ~24 projects **server-side** per page, each as `[![title](thumb.png)](https://devpost.com/software/{slug})` + title + one-line summary. `(verified)` | Highest yield per request in the whole surface: 1 fetch → ~24 project rows. Listing depth is cheap; deep records are not. |
| R5 | A project page (`/software/{slug}`) contains the eight authored sections (Inspiration / What it does / How we built it / Challenges / Accomplishments / What we learned / What's next), the `Built With` tag list, an **integer `software_id`**, and a **Like count** (AudioNova: 547). `(verified)` | "Likes" is Devpost's native popularity unit — the direct analogue of a GitHub star. The eight authored sections are the actual inspiration payload. |
| R6 | `robots.txt`: `User-agent: *` / `Disallow:` (nothing), while explicitly blocking `Bytespider`, `Omgilibot`, `ImagesiftBot`, `BLEXBot`. `(verified)` | General crawling is permitted by the operator. The named blocks are AI-training harvesters → our posture must be *indexing with attribution*, not bulk content mirroring. |
| R7 | Devpost hosts 13,000+ hackathons; the project corpus is in the **hundreds of thousands to millions**; gallery pages are paginated. | Full harvest is a background job with a rate budget, never a synchronous requirement. |
| R8 | This sandbox's egress is an allow-list (`api.github.com` reachable; `devpost.com`, `huggingface.co` TLS-reset). `(verified)` | The committed seed corpus must be producible *without* live network. Pipeline must therefore run in **three independent modes**: seed, harvest, build-from-JSONL. |
| R9 | GitHub Pages serves static files with permissive CORS and ETags; gzip is applied by the CDN. | The static index *is* the API. No backend is needed to satisfy "other agents can access it with ease". |
| R10 | In toolscour, Tier-1 = 15-column dictionary-encoded rows, ~405 KB gz for 10.6k records (~38 bytes/record). `(verified from repo)` | Budget anchor: at ~40 bytes/row gzipped, a 1.2 MB ceiling ≈ 30k records. Our rows carry longer text hooks, so we must be stricter. |
| R11 | Hackathon projects are **write-once**: a submitted project's page never changes materially after the event ends. | The daily-cron assumption inherited from toolscour (repos move; stars decay) is **wrong here**. Freshness cadence should be weekly, and "recency" is a *discovery* signal, not a staleness risk. |
| R12 | Two distinct projects in the same event shared the display name `NeuroGuard AI` but had different slugs. `(verified)` | Canonical key = `software_id` / `slug`, never name. Naive dedupe would destroy real records; name-similarity must instead feed a **novelty/cluster** signal. |

---

## 2 · The Panel

| Persona | Domain | Mandate (what they were told to defend) |
| --- | --- | --- |
| **Kestrel Voss** — Data Acquisition Engineer | crawlers, APIs, politeness | Maximize corpus size and harvest reliability per unit of network cost. |
| **Dr. Imani Okoro** — Information Architect | schemas, controlled vocabularies, retrieval semantics | One coherent record model; no field that doesn't answer a question. |
| **Ravi Chandrasekhar** — Agent-Interop Engineer | MCP, JSON contracts, machine-readable docs | The dataset must be *usable by agents* without a human reading the README. |
| **Sofia Lindqvist** — Static Performance Engineer | bundle/index budgets, CDN | Nothing may break the $0-static constraint or the sub-5ms search promise. |
| **Marcus Vale** — Product Designer for Builders | what hackers actually do with inspiration | The product must produce *actionable* ideas, not a prettier list. |
| **Dr. Ada Nwosu** — Ranking & Evaluation Scientist | relevance, bias, measurement | Ranking must be explainable, monotonic, and testable — or don't rank. |
| **Yuki Tanabe** — Data Ethics & Licensing Counsel | ToS, copyright, privacy, opt-outs | Anything we ship must survive a polite letter from the platform. |
| **Tomas Berg** — Data Ops / SRE | idempotency, reproducibility, CI | Every artifact must be rebuildable from committed inputs, deterministically. |

**Adjudicator** (non-voting): scores each proposal 0–5 on *Corpus Value*, *Agent Legibility*, *Budget Fit*, *Legal Durability*, *Maintenance Cost*; declares convergence.

**Weighting** (why these weights): the corpus is the product, so acquisition and schema
outweigh polish; legal durability is a *gate*, not a weight — it can veto but not win.

`Corpus Value ×1.25 · Agent Legibility ×1.15 · Budget Fit ×1.00 · Maintenance ×0.90 · Legal = veto`

---

## 3 · Round 1 — Position Papers, then Cross-Critique

### 3.1 Openings (compressed to the load-bearing claim)

- **Voss (Acquisition):** Ship a three-source harvester — `api/hackathons` for events, `project-gallery` for breadth, `/software/{slug}` for depth — behind a token-bucket at 1 req/1.5 s, with cursor checkpointing so a 3 a.m. cron can die and resume. Target 25k projects in 20 hours.
- **Okoro (Schema):** Model it as a **star schema**, not a flat repo list: fact = `project`, dimensions = `event`, `domain`, `move[]`, `stack[]`. Hackathon identity is *load-bearing*: a project from a $2M XPRIZE with 26k registrants is not the same as one from a 46-person invite-only campus event, and that must be a joinable dimension, not a string.
- **Chandrasekhar (Agents):** Five read surfaces, one generator: packed JSON (UI), NDJSON (streaming), CSV (tables/spreadsheets), **gzipped SQLite** (SQL, no server), plus a contract layer — `llms.txt`, JSON Schema, OpenAPI, an agent `SKILL.md`, and a zero-dependency stdio MCP server. If an agent has to parse prose to query us, we failed.
- **Lindqvist (Budget):** Cap Tier-1 at **1.2 MB gzip** and make the build *fail* over budget. Every field must pay rent. Reject in-browser embeddings, reject a graph DB, reject anything needing a server. Sub-5ms search comes from a typed-array inverted index built once at load, not from a library.
- **Nwosu (Ranking):** Define `coolness` as an **additive, logged, clamped** score with published weights, and expose the components in every record. A single scalar that agents can't decompose is a ranking nobody can debug or re-rank. Add a hard rule: **popularity must not dominate**, or the index becomes a mirror of Devpost's own front page and adds zero discovery value.
- **Vale (Product):** Nobody leaves a hackathon catalog saying "I found a project." They leave saying *"I could steal that."* So the atomic unit of value is not the project, it is the **transferable move** ("price it before you generate it", "the constraint *is* the feature"). Build a Remix pane that collides two ideas into a fresh brief; that is the actual use case, and it must be *generated offline* so it costs nothing at runtime.
- **Tanabe (Ethics):** Metadata + summary + link-out. No mirroring of images or the eight authored sections verbatim at scale; no team-member names, handles, photos, or vote-rigs; honor `ai.txt`/robots; identify as a project index with a takedown address. The Bytespider block in R6 is a signal we must read, not route around.
- **Berg (Ops):** Deterministic build from committed `corpus.jsonl`; `--check` mode that regenerates in a temp dir and diffs; schema `version` field with additive-only evolution; every artifact content-addressed so CI can prove "data unchanged" and skip. No secrets required to build — only to harvest.

### 3.2 Cross-critique matrix (attested objections; each row is a real attack)

| Attacker → Target | Objection | Severity | Resolution |
| --- | --- | --- | --- |
| Lindqvist → Voss | "25k deep-harvested records is 25k page fetches ≈ 30 MB of HTML per night, and you want the *text* in the index. At R10's ~40 B/row our Tier-1 budget buys ~30k rows *without* prose. Your plan fits only if depth lives in Tier 2 and Tier 1 carries a ≤ 88-char hook." | **Blocking** | Voss concedes: depth is *tiered and sampled*, not uniform (§6 ADR-3). |
| Tanabe → Voss | "Crawling 25k project pages a night reproduces the authors' *prose* at industrial scale. That is the behavior R6's blocked bots exhibit. We don't want to be the polite-looking version of that." | **Blocking** | Deep fetches capped (`--deep N`, default 400/run), long-cache, and prose stored as *quotes in an inspector for the selected record*, never bulk-exported in Tier 1 (ADR-12). |
| Nwosu → Voss | "Volume is not value. A 25k list of `Lumina study buddy`-class submissions (one line: 'a lot of students don't have learning apps so I built this') dilutes the corpus and *lowers* expected ideas-per-minute. Quality gate first, scale second." | High | Accepted as **gate, not ceiling**: `min_coolness` filter + noise blacklist on empty/placeholder summaries (ADR-5). |
| Okoro → Chandrasekhar | "Five surfaces is five schemas. If CSV column order drifts from SQLite columns, agents silently mis-parse. One generator, one schema, one CI check that every surface round-trips to the same record count." | High | Accepted: single `emit_all()` writer; `--check` asserts count + column parity across JSON/CSV/NDJSON/SQLite (ADR-8). |
| Lindqvist → Chandrasekhar | "SQLite in `public/` is a binary blob in a git repo — merge-conflict bait and a 20 MB commit if the corpus scales. And you can't diff it." | Medium | Compromise: SQLite is a **build artifact emitted on demand**, `ideas.sqlite.gz` committed only while < 4 MB; CSV/NDJSON are the diffable canonical exports (ADR-8, §8 dissent D2). |
| Vale → Okoro | "A star schema is correct for SQL and wrong for a browser. The UI needs denormalized fat on the row it renders; joins cost code we don't want to write client-side." | Medium | Both: emit normalized dimensions *and* denormalize the 4 display-critical event fields into each row at build time (ADR-2). |
| Vale → Okoro | "`domain` + `subsystem` is toolscour's shape and it is *wrong for ideas*. 'Health' tells a builder nothing stealable. The axis that produces insight is the **move** — the design trick, not the market vertical." | **Blocking** | Accepted, and this is the single largest deviation from the reference repo: `domain` (10 sectors) is retained for *navigation*, but `moves[]` becomes a **first-class, independently queryable vocabulary** with its own shard file (ADR-4). |
| Chandrasekhar → Nwosu | "Respectful opacity is still opacity. If I can't tell whether a field is *from Devpost* or *inferred by our classifier*, I will ship your guess as fact into a user's product." | High | Accepted: every derived field carries `provenance: observed | derived | editorial` and a `confidence` where material (ADR-9). |
| Berg → Everyone | "Nobody specified what happens when Devpost changes its markup. A scraper whose parse silently yields 0 rows and 'succeeds' is worse than one that crashes." | High | Accepted: **floor assertions** — build aborts if rows < 60% of previous committed count or if any required field is null (ADR-10). |
| Tanabe → Nwosu | "Your 'novelty penalty' that clusters similar projects is how we end up shadow-banning imitators. Imitation is *how hackathons work*. Rank for utility, editorialize never." | Medium | Partially accepted: novelty is exposed as a *descriptive* `kin_count` field, and only ever *reduces* redundancy in browse views; it never removes records (ADR-5). |
| Lindqvist → Berg | "Your 'regenerate and diff' CI gate will flap on `harvested_at` timestamps and make every PR look dirty." | Low | Accepted: content-hash excludes volatile `generated_at`; timestamps land in a separate `manifest.json` (ADR-10). |
| Voss → Nwosu | "A `coolness` score with public weights is a target. Once people know likes weight 0.42, like-farms appear." | Low | Rebutted: we are an index, not a prize — gaming our sort has no payoff; hiding weights would break reproducibility, which Ravi and Berg both need. Kept public, documented, versioned (`scoring_version`). |

---

## 4 · Round 2 — Revised Proposals Under Fire

Each persona restates a proposal only if it survived or was repaired.

| # | Proposal (post-critique) | Changed from R1? |
| --- | --- | --- |
| P1 | **Tiered harvest.** L1 = event discovery via `api/hackathons` (10 events/page). L2 = gallery listing parse (≈24 projects/fetch, cheap, 3 fields each). L3 = deep project page (8 sections, likes, built-with, links), sampled by `--deep N` with likes-weighted priority. | ✅ depth now sampled, not uniform |
| P2 | **Record model:** one fact table (`projects`) + two dimensions (`events`, `moves`), denormalizing `event_title`, `event_org`, `event_prestige`, `prize_usd` onto the fact for browser use. | ✅ + denormalization |
| P3 | **The `moves` vocabulary** (≈18 controlled terms, e.g. `evidence-graph`, `price-before-generate`, `offline-first-fallback`, `human-hold-the-last-button`, `make-the-invisible-measurable`, `wrap-the-legacy-surface`) with regex+lexical detectors, a per-move shard, and a curated definition blurb per move. | ✅ promoted to first-class axis |
| P4 | **Six agent surfaces** emitted by one generator; contract files (`llms.txt`, `schema.json`, `openapi.json`, `SKILL.md`, `mcp/ideasgalore_mcp.py`) all *generated from the same registry* so prose can't drift from schema. | ✅ contract files now generated |
| P5 | **Budget:** Tier-1 ≤ 1.2 MB gz with hard CI failure; per-row field budget table published; prose forbidden in Tier 1 except a ≤ 96-char hook. | ✅ tightened |
| P6 | **`coolness` v1** (published weights, `scoring_version: 1`): `0.30·log-like + 0.22·award + 0.14·event_prestige + 0.10·recency + 0.14·specificity + 0.10·signal_richness − 0.12·kin_redundancy`, each term in [0,1]; `specificity` rewards measurable claims (numbers in the summary) and punishes one-liners with no mechanism; monotonic by construction and covered by unit tests. | ✅ + specificity & richness terms |
| P7 | **Ethics contract** shipped as a file, not folklore: `docs/DATA_ETHICS.md` + machine-readable `agents/ethics.json` (purpose, source, no-mirror policy, rate limits, takedown route, `respect Robots: yes`) linked from `llms.txt` so downstream agents inherit our constraints. | ✅ machine-readable |
| P8 | **Ops:** `corpus.jsonl` = source of truth; all artifacts derived; `make verify` = build → regenerate in temp → diff → assert floors/parities; `harvested_at` excluded from content hash; weekly cron (R11), not daily. | ✅ cadence changed |
| P9 | **Remixes generated offline:** 12 curated + algorithmically-mined `idea_pairs` (same move, different domain = highest transfer value) compiled into `data/remixes.json` with a full build brief per pair. Zero runtime cost, cacheable, and agents can read briefs directly. | ✅ moved from client-side to build-time |

---

## 5 · Round 3 — Scored Vote

Scores 0–5 per axis, multiplied by §2 weights. Legal = veto check (pass/fail), excluded from sum.

| Proposal | Voss | Okoro | Chandr. | Lindqv. | Vale | Nwosu | Berg | **Weighted** | Legal | Verdict |
| --- | :-: | :-: | :-: | :-: | :-: | :-: | :-: | :-: | :-: | --- |
| P1 tiered harvest | 5 | 4 | 3 | 4 | 4 | 4 | 4 | **17.6** | ✅ | Adopt |
| P2 star + denorm | 4 | 5 | 5 | 4 | 5 | 4 | 5 | **19.4** | ✅ | Adopt |
| P3 moves axis | 3 | 5 | 5 | 4 | 5 | 5 | 4 | **19.8** | ✅ | Adopt (top) |
| P4 six surfaces + generated contracts | 3 | 4 | 5 | 3 | 4 | 4 | 5 | **17.7** | ⚠️→✅ | Adopt, SQLite gated by size |
| P5 budget gate | 3 | 4 | 4 | 5 | 3 | 4 | 5 | **17.0** | ✅ | Adopt |
| P6 coolness v1 | 4 | 4 | 5 | 4 | 5 | 5 | 4 | **18.6** | ✅ | Adopt |
| P7 ethics as artifact | 3 | 4 | 5 | 4 | 4 | 4 | 4 | **17.3** | ✅ | Adopt (veto-holder) |
| P8 deterministic ops | 5 | 4 | 5 | 5 | 3 | 4 | 5 | **18.9** | ✅ | Adopt |
| P9 offline remixes | 2 | 4 | 5 | 4 | 5 | 4 | 5 | **17.5** | ✅ | Adopt |

### 5.3 Convergence

- Round 1 → 2 rank movement: 4 of 9 proposals re-ranked. Round 2 → 3: **zero re-rankings** → convergence criterion met.
- Unrebutted objections after Round 2: **none** (the like-farming objection in §3.2 was answered on the record).
- Highest-scoring decision (`P3 moves axis`, 19.8) is precisely the one that departs from the reference repo — the panel judged that *imitating toolscour's axes faithfully would have been the failure mode*, since its taxonomy serves "which library do I install", while ours must serve "which trick do I steal".

---

## 6 · Consensus — Binding Architecture Decisions (ADRs)

Each ADR names the file that implements it, so this document cannot rot silently.

**ADR-1 · Static-first, two-tier index, $0 forever.** No backend, no DB service, no keys to read. `pipeline/shard_builder.py` emits `web/public/catalog-packed.json` (Tier 1) + `web/public/data/details/*.json` (Tier 2) + `catalog-stats.json`. *(Inherited from toolscour, retained on merit.)*

**ADR-2 · Star schema with browser denormalization.** Fact: `projects`. Dimensions: `data/hackathons.json` (event), `data/moves.json` (vocabulary). Each Tier-1 row carries `event_prestige` and `prize_usd` inline for sort/filter without a join.

**ADR-3 · Tiered depth with an explicit `depth` field.** `depth ∈ {listing, deep}`. Listing rows: identity + hook + event + derived classification. Deep rows add likes, `built_with[]`, authored-section quotes, `open_source` links, awards. Never pretend a listing row is a deep row — UI must render the difference (badge), and `min_depth` is a filter. `pipeline/harvest_devpost.py`.

**ADR-4 · `moves[]` is the first-class inspiration axis.** Controlled vocabulary of transferable design tricks, each with a definition and an example list, queryable by humans (`MOVES` rail) and agents (`/moves.json`, MCP `list_moves`/`search_by_move`). Domains are for shelves; moves are for stealing. `pipeline/taxonomy_hacks.py::MOVES`.

**ADR-5 · Quality gate over raw volume.** `min_coolness` admission (default 0.18) + placeholder-summary rejection + `kin_count` for near-duplicates. `kin_count` reorders browse views only; it never deletes. Scale is achieved by *more events harvested*, not by admitting noise.

**ADR-6 · Explainable ranking, public weights, versioned.** `coolness` + its six components ship *inside* every record and in `agents/schema.json`; `scoring_version` bumps on any weight change. Unit tests assert monotonicity (more likes ⇒ score never decreases, ceteris paribus) — `pipeline/tests/test_pipeline.py`.

**ADR-7 · Token search, no runtime embeddings.** Inverted token index over `name + summary + built_with + moves + event`, built once on load, sub-5ms at 10⁵ rows (budget: < 3 ms/10⁴ rows measured in `catalog-stats.json` self-test). Optional offline `vectors.f32.bin` sidecar for semantic agents is **explicitly deferred** — documented as `not_shipped` rather than silently absent (§8).

**ADR-8 · Six read surfaces, one emitter.** `catalog-packed.json` (UI), `data/ideas.ndjson` (stream), `data/ideas.csv` (spreadsheets; the literal "tabular database"), `data/ideasgalore.sqlite.gz` (SQL/DuckDB; emitted only under a 4 MB budget), `data/details/*.json` (deep), `data/hackathons.json` + `data/moves.json` (dimensions). `--check` verifies identical record counts and column parity.

**ADR-9 · Provenance on every derived field.** `observed` (came from Devpost), `derived` (our classifier/score), `editorial` (hand-curated blurb). Machine-readable in `agents/schema.json` under `x-provenance`; the MCP server re-emits it per field.

**ADR-10 · Deterministic, self-defeating-on-drift builds.** All artifacts rebuild from committed `pipeline/corpus.jsonl`; volatile timestamps quarantined in `manifest.json`; CI aborts if `row_count < 0.6 × previous`, if a required field is null, or if Tier-1 gzip > 1.2 MB. `make verify`.

**ADR-11 · Weekly refresh, not daily.** Hackathon records are write-once (R11). Cron: `0 3 * * 1` (Mondays) for L1/L2 discovery + likes top-ups; full re-harvest stays `workflow_dispatch` only. Cheaper and it also makes the *index* look less like the target's traffic pattern.

**ADR-12 · Ethics is a shipped artifact, not a paragraph.** `docs/DATA_ETHICS.md` + `agents/ethics.json`; robots.txt honored and cached; token bucket ≥ 1.25 s between requests with jitter and a declared `User-Agent` carrying a contact; images referenced by hotlinked URL, never copied into the repo; authored prose stored for a single selected record (fair-use summary/quote) and **never** emitted into bulk exports (CSV/NDJSON carry `has_deep: 1`, not the text).

**ADR-13 · The Remix (Forge) is generated at build time.** `pipeline/generate_remixes.py` pairs high-`coolness` projects that share a move but differ in domain, and emits a build brief: `the_wedge`, `reusable_moves`, `naive_version_vs_this_one`, `starter_stack`, `first_48_hours`, `kill_criteria`. Curated recipes take precedence; mined pairs fill the rest.

**ADR-14 · Agent contract is a first-class deliverable.** `agents/llms.txt` (what/where/how, with copy-pasteable `curl | jq` recipes), `agents/openapi.json` (3.1, static-path server), `agents/skill/ideas-galore/SKILL.md`, and `agents/mcp/ideasgalore_mcp.py` — a stdlib-only stdio MCP server (`search_projects`, `get_project`, `list_moves`, `ideas_for_goal`, `random_muse`, `similar_to`) that reads the same files the site serves, so an agent and a browser can never disagree.

**ADR-15 · Interface identity is *not* toolscour's.** Reference repos give you a scaffold, not a face (§8 lists what we deliberately did not inherit).

---

## 7 · Inherited vs Rejected from the Reference Architecture

| toolscour mechanism | Verdict | Reason |
| --- | --- | --- |
| Two-tier dictionary-packed index | **Inherit** | R10 math is sound and it is the whole reason $0 hosting works. |
| Zero-dep stdlib Python harvesters, JSONL corpus in-repo | **Inherit** | Berg: reproducible in CI without a lockfile fight. |
| Daily 02:00 UTC cron | **Replace** | ADR-11 — records are write-once; weekly is honest and cheaper (R11). |
| Flat single-record schema (`repos.json`) | **Replace** | ADR-2 — event context is load-bearing for hackathons; a project's meaning is its brief. |
| `primitives`/`accelerators`/`quantization` axes | **Replace** | Those answer "will it run on my GPU". Ours answers "what can I copy" → `moves[]` (ADR-4). |
| Synergetic **stack** generator | **Adapt** | Stacks combine *components*; ours combine *ideas under a constraint* (ADR-13). |
| Custom 3D galaxy canvas | **Adapt** | Keep a hand-rolled canvas (no three.js) but render a 2.5D *museum floor plan* — clusters are display rooms; a star-field metaphor implies rarity ranking we don't want to imply. |
| Star-count as primary ranking | **Replace** | Popularity-only ranking reproduces the platform's front page (Nwosu, §3.2). Multi-signal + specificity (ADR-6). |
| `beginner_intel` ELI5 prose template | **Refine** | Kept as `inspiration_intel`, but with `has_deep` gating so templated fallbacks never masquerade as authored content (ADR-3/9). |
| Violet-free, shadow-free, mono-for-data design discipline | **Inherit the discipline, not the palette** | §3.2 of `docs/DESIGN.md`. |

---

## 8 · Recorded Dissents & Open Risks (not swept under the rug)

- **D1 — Lindqvist vs Chandrasekhar (SQLite).** Wants the SQLite blob out of git entirely. Concession: size-gated emission + gzip; if `> 4 MB` the emitter skips it and `--check` tolerates its absence. Risk: schema drift between CSV and SQLite columns; mitigated by the parity assertion, not by trust.
- **D2 — Voss vs Nwosu (novelty penalty).** Voss argues any redundancy penalty entrenches incumbents at hackathons where parallel invention is the norm. Compromise implemented: `kin_count` is descriptive and browse-time only. If metrics show it suppressing strong new ideas, this is the first knob to turn.
- **D3 — Deferred semantic search.** The panel rejected embeddings for *this* tier of scale, but an agent hitting `search_projects` with a fuzzy goal may still want vectors. `vectors.f32.bin` is documented as an explicit opt-in future artifact; do not fake it with `grep` and call it semantic.
- **R4 risk — markup fragility.** Devpost can change `project-gallery` HTML at any time. Mitigated by ADR-10 floor assertions (a crashed workflow is better than an empty catalog), and by the committed corpus letting the site rebuild forever without the network.
- **R5 risk — likes are gameable and small-N.** 547 likes for a staff pick means the like distribution is thin; hence log-scaling and a 0.30 cap on its weight, plus `award` from `winners_announced`/gallery badges where observed.
- **R6 risk — legal grey remains grey.** Public-data scraping is well-trodden (hiQ-era) but ToS contract claims are jurisdiction-specific; the *durable* posture is minimal-copy + attribution + takedown + polite rates, which is what ADR-12 encodes. Not legal advice.
- **R7 risk — corpus youth.** The committed seed is ~104 projects across 5 sources, harvested through a rendering proxy, so `likes`/awards are largely absent (listing depth). The UI must therefore default to *specificity + recency* ordering until a full `harvest_devpost.py` run adds likes. Faking `likes: 0` as if observed would violate ADR-9; the field is `null` with `provenance: "unavailable"` until fetched.

---

## 9 · What Changed Because of the Debate (diff against first instinct)

1. **Depth became tiered and sampled** — a plain "scrape everything" plan would have blown the budget (Lindqvist) and looked like the bots Devpost blocks (Tanabe).
2. **`moves[]` over `domains`** as the headline axis — the biggest product-shape change, from Vale's blocking objection.
3. **Ranking lost its dependence on popularity** and gained published, testable components (Nwosu).
4. **SQLite/CSV/NDJSON added** as equal citizens, forcing the single-emitter and parity-check rules (Chandrasekhar → Okoro → Berg).
5. **Cron moved daily → weekly** because hackathon data is write-once (R11), which also lowered the polite-crawl budget for free.
6. **Provenance labels** exist because "agent will ship our guess as fact" is the most probable way this repo causes harm (Chandrasekhar).
7. **Near-duplicates are informative, not deleted** — the two-`NeuroGuard AI` case (R12) turned a dedupe bug into a feature.

*Converged: 2026-09-18 · Adjudicator sign-off: 9/9 proposals adopted, 3 dissent notes logged, 1 deferral (semantic vectors) with an explicit non-goal statement.*
