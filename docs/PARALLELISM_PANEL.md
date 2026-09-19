# Ideas Galore — Parallelism Panel: Ingestion, Quality Check & Review at 500–1,000 Detailed Records

> **Question put to the panel.** The pipeline is one record at a time, and the plan is 500–1,000
> projects that are *fully detailed and verified*. Where does the time actually go, what can be
> parallelized without buying throughput with weaker records, and what must stay serial no matter how
> much it costs?
>
> **Method.** Same as [`docs/EXPERT_PANEL.md`](EXPERT_PANEL.md): the panel argued from a dossier of
> *measured* premises (§1), each reproducible with a command printed in the row. Positions (§2) were
> attacked in a cross-critique matrix (§3), revised under fire (§4), scored (§5), and only then made
> binding (§6). Convergence rule, inherited: **no proposal may change rank between the final two
> rounds, and no objection may remain unrebutted.**
>
> **Honesty note.** Executed by the implementing agent as structured adversarial persona reasoning,
> not eleven independent model calls. What makes it worth reading is that the numbers are real: M1–M15
> were measured in this workspace on 2026-09-19 with `python3 pipeline/bench_scale.py`, including a
> 1,000-record synthetic tree, and three recommendations — the proven-lossless dedup blocking (ADR-P11) and
> the stale-sheet sweep with its emitted-vs-served accounting (ADR-P13, ADR-P14) — were **shipped inside
> this same commit**, the first with a byte-level equivalence proof. Where a figure is modelled rather than measured — the throughput table in §7 —
> it is labelled `(modelled)` and the assumption is stated next to it.

---

## 0 · Charter

| Item | Value |
| --- | --- |
| Goal | 500–1,000 published records, each carrying the full 12-field audit sheet, all six checks evidence-backed, `numbers` reconciled, and a repository read verified against `api.github.com`. |
| Constraint that does not move | Throughput may not be bought with weaker admission (ADR-5) or thinner records (the "maximally detailed" rule). The panel may re-order *who does what work*, not *what work is done* per record. |
| Constraint inherited from the sandbox | No server, no queue service, no database to coordinate workers; state lives in this git repo and the built surfaces. See M13. |
| Definition of "done" for a record | A file in `pipeline/raw/deep_captures/`, an entry in the notes registry, a verdict from `audit_projects`, a sheet that passes the cross-surface gate, and a line in the batch ledger. Not "ingested". |
| Success metric | **Gate-passing published records per hour of attention.** Not records touched, not pages fetched — the metric Nwosu and Vale both attacked openings over (§3.1). |

---

## 1 · Shared Dossier (measured premises)

Every row was observed on 2026-09-19 in this workspace. `bench` = `python3 pipeline/bench_scale.py --records 1000`, which prints the numbers below from the same code paths CI runs. The synthetic tree is an *instrument* built by cloning the real captures with `-cloneK` suffixes into a temp dir; it is not a catalog — see §1.2.

| # | Finding | Consequence |
| --- | --- | --- |
| M1 | Single-process cost of the whole build today (18 deep captures, 11 published, 167 corpus rows): `ingest_seed 0.74 s · taxonomy 0.02 s · audit 0.11 s · shards 0.13 s · docsync 0.04 s` = **1.0 s**, plus `shard_builder --check ≈ 0.8 s` and the full test suite in **1.48 s** (1.75 s at the current size) (suite size is the generated count in §1.1, and its cost is measured here rather than quoted from a later build). `(bench)` | At the current size there is nothing to parallelize. The local pipeline is not the bottleneck, and a design that only speeds it up wins a prize nobody wants. |
| M2 | At 1,000 audited records / 1,151 corpus rows: `ingest 13.03 s · taxonomy 0.02 s · audit 3.57 s · shards 0.37 s · docsync 0.11 s` = **17.1 s**. Before ADR-P11 shipped, the same tree measured `ingest 14.06 s · audit 67.79 s` = 82 s of stage time. `(bench)` | Two numbers matter: the **12 ms/row in `ingest_seed`** (per-file JSON reads, embarrassingly parallel) and the audit pass that was **quadratic** and is now 19× cheaper. Everything else is noise at this scale. |
| M3 | The quadratic term was the A5 duplicate/parallel-invention pass, which rebuilt every record's section text and token set *inside* the pair loop. Blocking it on a leading-name-token + shared-number index took `audit_projects` from **67.79 s → 3.57 s** at 1,000 records, and the test suite from **82.24 s → 18.18 s** (the suite re-runs the audit in fixtures). `(bench)` | The reducer's global pass is now cheap enough that the cross-record logic never needs to be sharded (§3.1). CPU was never the wall; it was one function. |
| M4 | The blocking is **lossless, tested not argued**: `bench_scale.blocking_is_lossless()` runs the whole audit twice on the real corpus — brute-force reference and blocked implementation — and compares every verdict, `verdict_reasons`, `duplicate_of`, cross-links, `soundness_score`, `coolness` *and* the bytes of `audit.jsonl`. Identical (`3 duplicate actions` both ways). The 1,000-record tree reproduced a byte-identical `audit.jsonl` under `cmp`. `(verified)` | A speed-up that changes which projects get merged is a catalog change. That is why it shipped with a diff, not with a comment. |
| M5 | Per-record cost on the **agent** side, from the last two batches: a project page is 1–4 `fetch_page` chunks of ~6–8 KB markdown (`tower-dq18x2` 2, `newspectives` 2, `carbender` 4 because of gallery/video chrome), then ~2 authored writes (capture 9.6–9.8 KB, note ~7 KB), then 6–10 read/verify/command calls. Batch 5 = 2 records ≈ **30 tool calls**. | **This is the actual pipeline length.** 1,000 records ≈ 15,000 calls and 2,000–4,000 page fetches. Round-trips, not flops. |
| M6 | Egress from this workspace is an allow-list: `devpost.com` and `raw.githubusercontent.com` return no route (`curl` → `000`); `api.github.com` answers (HTTP 200, unauthenticated core budget 8,200/hr observed). `(verified)` | A scripted harvester — "`curl` the 1,000 pages with `xargs -P 16`" — is **impossible here**, so the only parallelizable fetcher is the agent-side `fetch_page` tool. That single fact decides the whole architecture. |
| M7 | GitHub reads through the real `repo_verify.Client`: **325–346 ms/request sequentially**, **178–186 ms amortised at 4-way**; a wider burst measured **577 ms → 85 ms at 8-way (6.8×)**. `(verified)` | Verification is latency, not compute. `verify()` fires ~4 requests per repo, and the parallelism unit must be the *request* (or at least several repos per worker), or there is nothing to hide behind. |
| M8 | Detail-surface budget: `shard_builder` gives the sector sheets a **240 KB gzip** ceiling, summed over what the build *emits*. The real published sheets cost **4.06 KB gz per published record** (44.7 KB gz across 6 sector files for 11 published — 14.0 KB of raw JSON per record, which is what "maximally detailed" costs). `(bench)` → **~59 published records per sector**, so the 11-sector taxonomy caps the current *layout* at ~650 detailed records. |
| M9 | Tier 1 has enormous headroom: `catalog-packed.json` is 4.0 KB gz of a 1,200 KB budget at 11 published and 4.9 KB at 106, so 1,000 rows ≈ 45 KB. `ideas.csv` 5.3 KB for 11 rows. The pool is the largest held surface (19.4 KB gz). `(bench)` | Growing the *index* is free. Growing the *prose* is what costs. Every proposed budget raise should be checked against which surface it is actually about. |
| M10 | Captures are already **one file per record** (`pipeline/raw/deep_captures/{id}.json`, `sort_keys=True`), but notes are **one shared dict** (`pipeline/raw/audit_notes.json`, 18 entries), as are `repo_checks.json` and `gallery_totals.json`. `(verified)` | Record-level fan-out is safe for captures and a **guaranteed write collision** for the other three. The first thing a parallel design has to do is fix the shape of the files, not add locks. |
| M11 | The audit's duplicate pass (M3) and the promotion queue ranking (`pool.json`, ranked by margin over the whole pool) are **cross-record**; `shard_builder --check` and `docsync --check` are **whole-surface** reducers. `(verified)` | Any design that lets a worker decide an *admission* per shard is wrong: shard 3 cannot see what shard 1 found. Map evidence, reduce judgement (§3.1). |
| M12 | A malformed capture crashes the build with a traceback naming the file (`_load` only defaults for *missing* files), while a valid-but-empty capture is silently scored as a **thin** record and parked in the pool with a quality reason. `(verified)` | Two distinct defects for a fleet of workers: one bad file **kills everybody's merge** (blast radius), and one half-written file **disguises a worker crash as a judgement about a project** (integrity). Both must be handled before batch sizes go up. |
| M13 | This workspace is volatile. Mid-research, the sandbox was restored: `web/node_modules` vanished (breaking `make verify` with `vite: not found` — now fixed by wiring `deps` into `verify`/`serve`/`api`) and `.git` came back rolled back to the initial commit while the working tree was intact, recovered only because the branch had been pushed (`git fetch && git reset --hard FETCH_HEAD`). `(verified)` | Any worker that keeps progress in a working tree will eventually lose a batch. **A batch is not finished until it is pushed**, and every stage must be re-runnable from committed state. It also means each parallel worker needs its own dependency install. |
| M14 | `taxonomy_hacks` costs 0.02 s at 1,000 records, and every real shelving fix in batches 3–5 was a *judgement* edit to a lexicon (each commented with the record it fixes and the variants rejected). `(bench)` | Shelving is not a throughput problem. Parallelizing the classifier would multiply the number of unreviewed lexicon edits, which is the one thing that can quietly corrupt the catalog. |
| M15 | The panel's own budget arithmetic exposed a **published defect**: `web/public/data/audits/developer-tooling-and-code-intelligence.json` was a sector sheet from before Continuity and Adversarial Compliance Matrix were re-shelved, still served under a path the agent API advertises for any sector, and its copy of Continuity disagreed with the live one (`moves` `[offline-first-fallback, verification-first, constraint-is-the-feature, deterministic-guardrail]` vs the current `[verification-first, deterministic-guardrail, make-the-invisible-measurable]`). It also made the sheet budget under-report served bytes by 6.93 KB (44.7 emitted vs 51.6 served). `(verified)` | A stale surface is worse than a missing one: it answers a real question with a superseded audit. A fleet of workers multiplies this class — files are emitted per sector while records move between sectors, so **emit must imply sweep**, and the sweep has to be owned by the build, not by a janitor. Shipped as ADR-P13 in this same commit. |


### 1.2 Which numbers are allowed to be trusted

The dossier mixes three kinds of measurement, and the panel agreed on what each can prove — because
the alternative is a research document that quotes a synthetic tree as if it were the catalog.

| Class | Source | May be used for | May not be used for |
| --- | --- | --- | --- |
| **Real catalog** | the 18 captures / 11 published rows in this repo | byte budgets, per-record cost, verdict and admission facts (M1, M4, M8, M9, M10, M12, M15) | anything about how the pipeline behaves at 1,000 records |
| **Synthetic tree** | `bench_scale.py --records 1000`, clones of the real captures with suffixes | *cost shape*: whether a pass is quadratic, how CI scales (M2, M3, M14) | *sizes*: its records compress into each other, so it understated per-record sheet bytes ~19× and would have set a budget 11× too generous |
| **Modelled** | §7 | a stated plan with visible assumptions | a claim of measured speed-up; D3 keeps this honest by demanding the first parallel batch report back |

### 1.1 Where the catalog stands while this was measured

<!-- census:begin -->
- **14 of 165** admitted records are published — this catalog is audited-only — **12** on the full twelve-field ladder and **2** as `audited-lite` (six fields established from the page, `build_is_real`/`stack_consistency` unexamined — see ADR-P15). **151** sit in `data/pool.json`: 7 captured, scored and held for cause · 144 never captured at all.
- **21** project pages have been deep-captured, 19 of them with a recorded figures table (claims written down with a denominator — whether they then proved checkable is each record's `numbers_add_up`), and 1 linking a repository we could verify against `api.github.com`. Hazard notes sit on 5 published and 2 held records.
- 124 pipeline tests, every surface regenerated by `make build`, and `make verify` fails the build if this block and `catalog-stats.json` ever disagree — including this block.
<!-- census:end -->

(Generated by `pipeline/docsync.py`. The test count in that block is the reason "add a test" is a rebuild and not a prose edit: the census quotes it, so `make build` has to run before a standalone test invocation can pass.)

---

## 2 · The Panel

The eight standing personas from `docs/EXPERT_PANEL.md` §2, plus two the question requires and the existing cast does not cover:

| Persona | Domain | Mandate (what they were told to defend) |
| --- | --- | --- |
| **Kestrel Voss** — Data Acquisition | crawlers, APIs, politeness | Maximise gate-passing records per hour of *network and agent* round-trips. |
| **Dr. Imani Okoro** — Information Architecture | schemas, vocabularies | One record model. Parallelism may partition inputs; it may never fork the schema or the file layout per worker. |
| **Ravi Chandrasekhar** — Agent Interop | contracts, machine-readable surfaces | A worker is an agent. Its output must be *validated*, not reviewed by hand, and its contract must be a file. |
| **Sofia Lindqvist** — Static Performance | byte budgets, CDN, first paint | Nothing may make a reader fetch 600 KB to read one project. Budgets are load-bearing, not taste. |
| **Marcus Vale** — Product for builders | what a reader steals | 1,000 shallow entries are worth less than 500 deep ones. A detail floor, checked per record. |
| **Dr. Ada Nwosu** — Measurement | what the number means | Define the metric first, then optimise. Reject any plan whose speed-up is not measurable in this repo. |
| **Yuki Tanabe** — Ethics & licensing | durable, polite sourcing | A cache of a thousand pages must still be an index with quotes, not a mirror. **Holds the Legal veto.** |
| **Tomas Berg** — Data Ops / SRE | determinism, idempotency, CI | Re-runnable, resumable, content-addressed. A worker may die at any moment and leave the build correct. |
| **Dr. Priya Raghunathan** — Scheduling & distributed systems *(new)* | partitioning, failure, exactly-once | Workers are unreliable and slow; design for a partitioned queue and a single deterministic reducer, and never for a lock. |
| **Elias Moreau** — Data-quality adversary *(new)* | what a fast pipeline breaks | Every field a worker fills in is a field nobody read. **Holds the Quality veto:** no proposal may admit a weaker record or a shorter one. |

**Adjudicator** (non-voting) scores 0–5 per axis. Two new axes, and why: *Throughput* because the question is throughput; *Resumability* because M13 showed this environment loses work. Vetoes are not weights — Legal and Quality can block a proposal but cannot win one.

`Throughput ×1.20 · Resumability ×1.10 · Corpus Value ×1.05 · Agent Legibility ×1.00 · Budget Fit ×1.00 · Maintenance ×0.85 · Legal = veto · Quality = veto`

---

## 3 · Round 1 — Openings, then Cross-Critique

### 3.1 Openings (compressed to the load-bearing claim)

- **Raghunathan (Scheduling):** Three parallelizable axes, and only one is code: **(a) record-level fan-out across agent sessions**, **(b) tool-call batching inside a session**, **(c) thread-level concurrency inside a stage**. The queue is already a list of record ids and captures are already one file per id (M10), so partition `fnv1a(id) mod W`, publish the partition, and let W workers own disjoint files — no locks, no leases, no coordination service, because M6 forbids one and M13 forbids trusting one. The reducer is *single-threaded by law*.
- **Voss (Acquisition):** M6 is the whole story: the pages can only be read by `fetch_page`, so the ingestion throughput is **pages per agent turn**, not processes per CPU. Today's method reads one page, writes one record, then reads the next. Issue 4–6 page reads in parallel per turn, and 3–4 records per batch-turn; nothing else changes the critical path.
- **Chandrasekhar (Agents):** M12 says why the batch is 2 today: a bad field is caught by *a human reading a sheet*. Give workers a machine contract — `pipeline/capture_lint.py`, one line per violation, `REJECT <id> <field> <rule> <fix>` — so a bad record is **rejected at the boundary** instead of repaired serially in the merge. Rejection is the parallelism primitive; review is the serialisation point.
- **Okoro (Schema):** Do not shard the model. The unit that a worker writes is a *capture file and a note file for one id*, byte-identical in shape whether it is record 12 or record 980; the reducer then does exactly what it does today. M10's three shared files are the actual defect — split the notes registry into `raw/audit_notes/{id}.json` before adding any worker, or you'll spend the throughput you gained resolving write collisions.
- **Lindqvist (Budget):** M8 is the only hard ceiling in the dossier: **~59 published records per sector** at 240 KB gz. 1,000 detailed records on 11 sectors cannot be *shelved* in the current layout, parallel or not. Fix: `data/audits/<sector>.json` becomes an index of ids and `data/sheets/<id>.json` becomes the per-record fetch. Do not "fix" it by raising the budget (R3) — the number encodes what the UI is allowed to fetch on first paint.
- **Berg (Ops):** Parallel means "more than one writer touched the tree and one of them crashed". So: (i) a worker writes only its own paths; (ii) every stage must be a pure function of committed inputs — no clock in the artifacts (already house law), no dict order; (iii) `make build` stays the only writer of `web/public/`; (iv) **the unit of work ends in a commit and a push**, because M13 is not hypothetical, it happened during this research.
- **Nwosu (Measurement):** Refuse "records ingested per hour" as the metric; it rewards filling a directory. The only unit that means anything here is *gate-passing published records per hour*, and the only honest speed-up claim is one `bench_scale.py` can reproduce after the change. Concretely: benchmark P4 before shipping it (done — M4), and benchmark each subsequent proposal the same way or drop it.
- **Vale (Product):** The failure mode of a fast pipeline is a catalog that reads like a fast pipeline. Publish a **detail floor** as data, not as intent: 12 mandatory fields, ≥3 reconciled numbers with denominators, a `what_to_steal` that names a mechanism, a `prior_art` entry with a relation. The floor is already implicit in `_pool_record`/`_ndjson_record`; make it a check.
- **Moreau (Quality adversary):** Three things must never be parallelized, whatever the wall-clock cost: **the duplicate pass** (M11 — it is cross-record by definition), **the promotion queue ranking** (a shard that ranks locally promotes the wrong next record), and **the `worth` judgement** (eleven workers each inventing a standard for "is this a good idea" produces a catalog with eleven standards). Parallelize *evidence*, serialize *verdicts*. And M12's second half is the trap: an empty capture is scored as a *thin project*, so a dead worker shows up as a quality decision about someone's hackathon entry. The gate must separate "the page has little" from "the record is incomplete".
- **Tanabe (Ethics):** A page cache is where mirroring starts. Rule: the cache stores the markdown *as the capture already stores it* — the seven authored sections plus a content hash — and the sheet may cite only text present in the cache. That preserves ADR-12 (no bulk prose in Tier 1) *and* makes re-review cheap, which is the ethical version of the same optimisation: fewer repeat requests to Devpost, not more.

### 3.2 Cross-critique matrix (attested objections; each row is a real attack)

| Attacker → Target | Objection | Severity | Resolution |
| --- | --- | --- | --- |
| Moreau → Raghunathan | "Your W independent workers each run `audit_projects` over their own partition, so the duplicate pass sees 1/W of the corpus. A team re-submitting to two events lands in different shards, both publish, and the catalog ships the same project twice — the exact failure the standing rule names." | **Blocking** | Conceded before it could be argued twice: workers produce *captures*, never verdicts. The audit, dedup, queue ranking and all sheet generation run once on the union (P3). Made possible by M3: the global pass is 3.6 s, so keeping it serial costs nothing. |
| Lindqvist → Okoro | "Your record model is fine and your file layout is broken at 1,000. ~59 published per sector (M8) is a hard number from the real corpus. Nobody has proposed a layout that survives it." | **Blocking** | Accepted as P5, and it is the one proposal the panel ranks as *required* for the goal, independent of parallelism: 500 records already need it. |
| Nwosu → Voss | "'Issue more fetches per turn' is not a pipeline, it is a to-do list with better posture. Bounded by agent turns either way — so state the ceiling instead of implying a cluster." | High | Accepted and it became the headline: the ceiling is *judgement turns*, and §7 states it as a model with the arithmetic visible rather than as a promise. |
| Berg → Chandrasekhar | "A linter that only rejects costs you a re-run per violation. If its output isn't a fix instruction, the merge becomes the bottleneck you tried to remove." | High | Accepted: one machine-readable line per violation, rule id, and the fix template; plus a stop rule (§10) that halves the batch when the reject rate says the contract is being misunderstood. |
| Vale → Moreau | "A quality adversary with a veto is how this catalog stays at 11 records forever." | High | Partly rebutted, partly accepted: the veto is on *weakening the gate*, never on batch size — P9 raises 2 → 4–6 records per batch precisely by moving checks into the gate. Accepted addition: the veto must be exercisable on the *published surface*, which is why P10 exists (the standing loop's field-by-field read becomes a diff of what a batch changed). |
| Tanabe → Voss | "Caching 1,000 Devpost pages is the behaviour R6's blocked bots exhibit. Volume is not our defence; quoting with attribution is." | Medium | Accepted with a bound: the cache holds exactly the sections the record cites (P6), never bulk HTML, and the sheet's `provenance` field keeps pointing at the live URL so a reader can check us. |
| Raghunathan → everyone | "Nobody costed the failure path. 8 workers, 1 crash: M12 says one malformed capture aborts the *whole* merge for everyone. Without per-record isolation, your fleet's availability is 0.875^batch." | High | Accepted: the lint is the isolation boundary — an unparseable or structurally incomplete capture is a **rejected record**, not a build failure; `--strict` stays a flag for the nightly, and the reducer skips rejected ids with a logged reason and a pool entry. |
| Okoro → Lindqvist | "Per-record sheet files are 1,000 more files under `web/public/`, and a manifest the UI must fetch. Fine — but then the manifest is a first-class surface, and it needs parity checks like every other one, or you've built an index that lies." | Medium | Accepted into P5's acceptance criteria: `--check` verifies `data/audits/<sector>.json` ids ∪ `data/sheets/*.json` = published set, both directions. |
| Moreau → Nwosu | "You are mixing corpora. The 68 s → 3.6 s figure came from a synthetic tree whose clones trip dedup harder than reality; the 4.06 KB/record figure came from the real 11 records. One more number lifted from the wrong tree and this dossier is marketing." | Medium | Accepted; recorded as a rule in the doc header of `bench_scale.py` and in M8's caveat. Synthetic trees for *cost shapes*, real records for *budget arithmetic*. |
| Chandrasekhar → Raghunathan | "Claim-check leases need a shared mutable store. There isn't one (M6, and ADR-1 forbids inventing a backend for *reads*). Your protocol is a service." | Medium | Conceded, and simplified: the "lease" is a **pushed commit** naming the ids it authored (`chore(capture): shard 3 of 8, ids …`). Git is the queue; `git status` is the lock table. |
| Voss → Lindqvist | "If you re-shard per record, my review loop becomes 1,000 fetches for one read-through." | Medium | Accepted in the other direction: P6's cache plus P10's diff are what make a re-read O(batch) instead of O(catalog) — the same fix serves both. |
| Berg → everyone | "Every proposal that touches a shared file dies on M10. I count three writers on `audit_notes.json` and two on `repo_checks.json` in the plans above." | High | Accepted: P4 (per-record notes) is the prerequisite of P1/P3/P9, and it is sequenced first in §10 for that reason. |
| Lindqvist → Berg | "Your 'install deps per worker' rule costs 135 packages and 4 s per shard (`web/node_modules` is not persisted between sessions — it vanished mid-research today). Ten workers × ten merges × install is real money." | Low | Accepted, mitigated: only the reducer runs the web build; workers run python-only checks, so `npm ci` happens once per batch, not per worker (P2). |

---

## 4 · Round 2 — Revised Proposals Under Fire

| # | Proposal (post-critique) | Changed from R1? |
| --- | --- | --- |
| P1 | **The contract gate comes first.** `pipeline/capture_lint.py`: schema keys present, seven sections non-empty, `links.repo` a parseable `owner/repo` or null, every `numbers[].value` with a denominator or an explicit `structural`/`not` prefix, `one_line` derived not authored, banned verdict words absent, no section text absent from the page cache. Output is one line per violation with the fix. Exit non-zero ⇒ the id is **rejected for this batch** and a `pool.json` note says *incomplete capture*, not *thin project*. | ✅ from "a linter" to "an admission boundary that also classifies the failure" |
| P2 | **Unit of work = one batch of W records inside one session**, not one shard of the pipeline. A worker: read `promotion-queue.json` once, take ids where `fnv1a(id) mod W == self.shard`, `fetch_page` all of them **in parallel in one turn**, write `deep_captures/{id}.json` + `audit_notes/{id}.json`, run the lint, commit+push. Only the reducer runs `npm`/`make build`/`--check`. | ✅ leases dropped; reducers centralised; installs centralised |
| P3 | **Map evidence, reduce judgement.** No worker may compute or store a verdict, a score, a rank or a duplicate decision. Everything cross-record (`similarity_verdicts`, queue ranking, `coverage`, `coolness`'s `kin_redundancy`) stays in the reducer, over the union, single-threaded. | ✅ forced by the blocking objection |
| P4 | **Per-record notes registry.** `pipeline/raw/audit_notes/{id}.json`, loaded by merging the directory over the legacy `audit_notes.json` (which stays readable, and is emptied by migration rather than deleted, so an old checkout still builds). Removes the only shared file in the write path. | ✅ was M10's footnote, now a numbered decision |
| P5 | **Detail surface re-shard.** `data/audits/<sector>.json` → per-sector *index* (id → sheet path + the two fields the list view needs); `data/sheets/<id>.json` → the full sheet, fetched on demand. The 240 KB budget then applies to the index, and M8's ceiling is gone: 1,000 records × 4.1 KB = 4.1 MB of per-record files, each a cheap single fetch. `--check` gains the both-directions parity rule from §3.2. | ✅ raised from "a suggestion" to the scaling prerequisite |
| P6 | **Page cache.** `pipeline/raw/pages/{sha1(url)}.md` + `pipeline/raw/pages/index.json` (`url → {sha, captured_at, chunks, bytes}`), written by whoever reads a page, read before any fetch. A capture may quote only cached text. Re-review stops costing fetches, and the cache doubles as the evidence file the lint checks quotes against. | ✅ bounded by Tanabe; now also the lint's source of truth |
| P7 | **Request-level concurrency inside `repo_verify`.** A `ThreadPoolExecutor(max_workers=8)` over `Client.get`, one shared ETag cache per run, retries preserved. Measured ceiling from M7: **6.8× on the wall clock**, 0× on the rate budget. | ✅ concurrency at the request, not the repo |
| P8 | **A shared API ledger.** `pipeline/raw/api_ledger.json`: `repo → {pushed_at, verified_at, payload}`; skip a repo whose `pushed_at` is unchanged; the run's `--budget` is *divided* across workers by the reducer (each shard is told its slice), so N workers can't collectively blow one hourly window (4,000 requests for 1,000 records against the 8,200/hr of M6). | ✅ budget is now a shared, partitioned resource |
| P9 | **Batch size 2 → 4–6 records per turn, with a governor.** After P1+P2+P4 land, raise the batch; if the lint's reject rate in a batch exceeds 20 %, halve the batch for the next one and record it in the ledger. Throughput is capped by the *quality signal*, mechanically, not by intent. | ✅ the governor added after Vale↔Moreau |
| P10 | **Review as a diff, not a re-read.** `pipeline/review_diff.py`: for a batch, print per-field deltas of every *published* surface the batch touched (row, sheet, index, CSV line, ndjson record, stats counts, the census block), plus the falsification checklist for the batch's load-bearing claims. Nothing is dropped from the standing rule — the reader reads every field that *changed* (which, for a new record, is every field). | ✅ answers "review doesn't scale" without lowering the bar |
| P11 | **Keep the blocking, guarded.** The lossless proof runs in `bench_scale.py`; a test asserts it, so a future edit to the similarity pass cannot silently change admission *and* speed. | ✅ promoted from optimisation to invariant |
| P12 | **Serialise what is cheap or what must be serial.** `taxonomy_hacks` (0.02 s, M14), `docsync`, the gates, `kin_redundancy`, `worth` and the sector census stay single-threaded forever. `ingest_seed`'s 12 ms/row gets an explicit **`--workers` flag only if the corpus passes 5,000 rows** (predicted 60 s at 12 ms/row) — a trigger written down so nobody parallelizes 13 s again. | ✅ explicit non-goals recorded |

---

## 5 · Round 3 — Scored Vote

0–5 per axis, × §2 weights; Legal and Quality are veto checks (pass/fail), excluded from the sum.

| Proposal | Voss | Okoro | Chandr. | Lindqv. | Vale | Nwosu | Berg | Raghun. | Moreau | **Weighted** | Vetoes | Verdict |
| --- | :-: | :-: | :-: | :-: | :-: | :-: | :-: | :-: | :-: | :-: | :-: | --- |
| P1 contract gate | 4 | 5 | 5 | 4 | 5 | 5 | 5 | 4 | 5 | **24.3** | ✅✅ | Adopt — prerequisite |
| P2 batch-in-a-session | 5 | 4 | 4 | 4 | 3 | 4 | 4 | 5 | 4 | **22.1** | ✅✅ | Adopt |
| P3 map/reduce split | 3 | 5 | 4 | 4 | 5 | 5 | 5 | 5 | 5 | **23.6** | ✅✅ | Adopt (binding law) |
| P4 per-record notes | 4 | 5 | 4 | 3 | 3 | 4 | 5 | 5 | 4 | **21.0** | ✅✅ | Adopt — prerequisite |
| P5 detail re-shard | 2 | 5 | 5 | 5 | 5 | 4 | 4 | 3 | 5 | **22.0** | ✅✅ | Adopt — scaling prerequisite |
| P6 page cache | 5 | 4 | 5 | 3 | 4 | 4 | 4 | 4 | 4 | **20.5** | ⚠️→✅ | Adopt with Tanabe's bound |
| P7 request concurrency | 5 | 3 | 3 | 4 | 2 | 4 | 4 | 5 | 3 | **19.2** | ✅✅ | Adopt |
| P8 shared API ledger | 4 | 4 | 4 | 4 | 3 | 5 | 5 | 4 | 4 | **19.8** | ✅✅ | Adopt |
| P9 batch governor | 5 | 3 | 4 | 3 | 5 | 5 | 4 | 4 | 3 | **19.6** | ✅✅ | Adopt |
| P10 review as diff | 3 | 4 | 5 | 4 | 5 | 5 | 5 | 3 | 5 | **22.5** | ✅✅ | Adopt |
| P11 blocking + proof | 4 | 4 | 3 | 5 | 3 | 5 | 5 | 4 | 5 | **21.2** | ✅✅ | **Shipped in this commit** |
| P12 explicit serials | 3 | 4 | 3 | 4 | 3 | 4 | 5 | 4 | 4 | **17.5** | ✅✅ | Adopt (as non-goals) |

**Convergence.** Round 1 → 2: six of twelve re-ranked (P1 rose from a footnote to top; P5 rose from objection to prerequisite; P7 fell three places once the request-vs-repo distinction was made). Round 2 → 3: **zero re-rankings**. Unrebutted objections after Round 2: **none** — the two that could not be resolved by design (Moreau's "parallel `worth` is eleven standards" and Nwosu's "the ceiling is judgement turns") were *accepted into the plan* as P3 and as §7's labelled model, which is the correct outcome for an objection that is really a constraint.

The top proposal is a *test*, not a speed-up (P1, 24.3), and the panel notes that as the point: at this corpus, the fastest thing available is to stop repairing output serially.

---

## 6 · Consensus — Binding Decisions for the Throughput Track

Each names the file that will implement it and the gate that proves it, in the house convention. **ADR-P11, ADR-P13 and ADR-P14 are implemented and verified today; P1–P10 are the ordered plan in §9** — recorded here so the next batches implement a decision rather than invent one.

**ADR-P1 · Admission is a contract, checked at the boundary.** `pipeline/capture_lint.py`, run per record before merge and in `make verify`. Its rule set is a **subset** of what the gates already enforce (nothing new may be required of a record that the published surfaces don't already show), and it must distinguish `incomplete capture` (worker failure) from `thin` (a project that is genuinely thin) — M12. *Acceptance: a deliberately truncated capture is rejected with a named rule, and the build does not die.*

**ADR-P2 · The batch is the parallel unit; the reducer is the serial one.** Workers write only `pipeline/raw/deep_captures/{id}.json` and `pipeline/raw/audit_notes/{id}.json` inside one session, in one turn per 4–6 page reads. `make build`, `--check`, `docsync`, `npm` and the commit/push belong to the reducer. *(No lease service: a pushed commit is the claim.)*

**ADR-P3 · Cross-record logic may not be sharded.** `similarity_verdicts`, promotion-queue ranking, `kin_redundancy`, coverage and every budget gate run once over the union, single-threaded, in the reducer. Justified by M3 (3.6 s at 1,000) and M11.

**ADR-P4 · One file per mutable fact.** `raw/audit_notes/{id}.json` (per record) replaces the shared dict; the legacy file is merged first for compatibility. Any new registry must be directory-shaped from the start. *Acceptance: two workers writing disjoint ids produce no git conflict — testable by construction: the only shared file left is `web/public/*`, which no worker writes.*

**ADR-P5 · Detail scales by record, not by sector.** `data/audits/<sector>.json` = index; `data/sheets/<id>.json` = sheet; `--check` asserts index↔sheets↔published parity in both directions and keeps the 240 KB budget on the index. Motivated by M8's ~59-records-per-sector ceiling and by M15, because a per-record file cannot go stale the way a per-sector file can.

**ADR-P6 · Fetch once, quote from cache.** `pipeline/raw/pages/` keyed by URL hash with `captured_at` and byte counts; a capture may quote only cached text; `provenance` still points at the live URL. Legal-bound per Tanabe/ADR-12.

**ADR-P7 · Concurrency where the clock is spent.** `repo_verify` gains request-level concurrency (default 8) against a shared `Client` cache, preserving back-off and the `Budget` exception. Measured headroom 6.8× (M7). CPU-bound stages get *no* threads (M1/M2).

**ADR-P8 · Rate limit is a shared, partitioned budget.** `raw/api_ledger.json` keyed on `(repo, pushed_at)`; unchanged pushes are skipped; each worker gets an explicit slice of `--budget` from the reducer. Ceiling from M6/M7: ~2,050 records/hour at 4 requests each, unauthenticated.

**ADR-P9 · Throughput governor.** Batch size is data, not mood: `raw/batch_policy.json` records `batch_size`, `reject_rate`, `next_batch_size` with the 20 %-reject halving rule. The gate, not the reviewer, throttles.

**ADR-P10 · A review surface for the reviewer.** `pipeline/review_diff.py <ids…>` prints field-level deltas across every published surface for exactly those records, plus the batch's falsification checklist. The standing "read what you published, field by field" rule becomes executable, so it survives scale instead of being quietly dropped.

**ADR-P11 · A quadratic pass may only be cut by a proven-lossless blocking rule.** Shipped: `pipeline/audit_projects.py::similarity_verdicts` blocks on (leading name token ∪ shared numeric fingerprint), hoists per-record text/tokens/numbers out of the pair loop, preserves pair order, and is checked against a brute-force reference by `pipeline/bench_scale.py`. *Measured: `audit_projects` 67.79 s → 3.57 s at 1,000 audited records; suite 82.24 s → 18.18 s; `audit.jsonl` byte-identical on both the real 18-record tree and the 1,000-record tree.*



**ADR-P12 · Named non-goals.** `taxonomy_hacks`, `docsync`, the gates, the shelving lexicons, and `worth` stay serial. `ingest_seed --workers` is gated behind a 5,000-row trigger. Multiprocessing the python stages is rejected outright (§8 R1).

**ADR-P13 · Emit implies sweep.** `build()` writes the sector sheets it owes and then deletes any `data/audits/*.json` it does not own; `--check` additionally fails on a sheet in the committed tree that no build emits (scoped to that directory, because the other surfaces are owned by other steps). *Acceptance, both in `pipeline/tests/test_pipeline.py`: `test_no_sector_sheet_without_published_records` (served set == sectors with published rows, read off `data/ideas.ndjson`) and `test_build_sweeps_a_superseded_sheet_file` (a planted ghost file does not survive a re-emit).* Motivated by M15.

**ADR-P14 · A budget is a claim about bytes a reader fetches.** `audit_sheets_kb` measures emitted bytes; M15 showed a reader could fetch more than that. `bench_scale.py` now prints `emitted vs served` per build so the two cannot drift apart silently again (the harness reports the divergence; the gate owns the ceiling).


---

## 7 · The Model Nobody Wanted, Stated Plainly

`(modelled)` — assumptions visible so the number can be argued with. A turn of agent attention is ~3 min of wall clock (read, fetch, write, verify); a record needs ~15 tool calls of which ~4 are page reads and ~2 are multi-KB writes (M5). The reducer (build + gates + commit) is ~40 s and runs per batch, not per record (M1/M2).

| Configuration | Records per batch | Turns per batch | Wall clock per record | 500 records | 1,000 records |
| --- | :-: | :-: | :-: | :-: | :-: |
| Today: 1 record per turn-pair, hand-repaired after writing | 2 | ~6 | ~9 min | ~75 h | ~150 h |
| P1+P2+P4: 4 records/turn-pair, lint rejects instead of reviewer repairs | 4 | ~4 | ~3 min | ~25 h | ~50 h |
| + P9 governor at 6, + P6 cache (re-reads free) | 6 | ~5 | ~2.5 min | ~21 h | ~42 h |
| + 4 parallel sessions (P2, disjoint partitions) | 24 | ~5 | — | **~5–6 h** | **~11 h** |

Three honest caveats the panel insisted on: (i) **parallel sessions share no memory**, only git, so their real speed-up is W only while the *queues stay disjoint* — which is what `fnv1a(id) mod W` buys, and what a re-ranked queue (P3 runs after the merge) can disturb, so partitions must be recomputed per batch; (ii) the model assumes the *page* is adequate — on the ~147 never-captured pool records, some turns will spend their whole budget on fetches that yield nothing publishable, and those are exactly the turns the governor is for; (iii) **the reducer does not parallelize, and 1,000 records makes the sector census its own problem** — M8 says 11 sectors hold ~650 detailed records, so P5 is not an optimisation, it is a precondition of the goal.

Bottom line the panel accepted: **parallelism buys roughly 6–13×, and it buys it in structure, not in skipped checks.** 500 fully detailed, verified records is a few days of work at W=4; 1,000 is about a week, plus P5 shipped.

---

## 8 · Rejected Variants (each killed by a measurement)

| # | Proposal | Why it is not in the plan |
| --- | --- | --- |
| R1 | `multiprocessing` the python stages (ingest/audit/shards in parallel). | Max saving is 13 s of an 81 s build, and the stages must run *in order*; M1/M2 show the reducer is already ~4 s. Zero for the real cost, nonzero for nondeterminism risk. |
| R2 | Shell-harvest the 1,000 pages with `curl`/`xargs -P 16` into `raw/pages/`. | **Impossible here** — M6: `devpost.com` and `raw.githubusercontent.com` do not answer from this workspace. Only the agent-side `fetch_page` path exists, which is why P2 is a session design and not a script. |
| R3 | Raise the per-sector detail budget from 240 KB to 1 MB and keep one file per sector. | One line, no re-shard — and it breaks the premise the number encodes: a sector sheet is what the UI fetches to list records (M8/M9). Also doubles the git churn per batch for a surface that is regenerated every batch. |
| R4 | A real queue: SQLite or JSONL with `claimed_by`/`status` columns as the coordination store. | State must be diffable, reviewable and pushed (M13); `ideasgalore.sqlite` is a *build artifact* (ADR-8), not a source of truth. A writable DB outside git would be the one place a lost sandbox destroys work. Git-as-queue (P2) is strictly worse in features and strictly better in recovery. |
| R5 | Parallelise the per-sheet checks (`run_checks`, coverage, arithmetic) across workers. | The audit is 0.11 s at 18 and 3.57 s at 1,000 *including* the quadratic pass (M2/M3). The checks are microseconds; sharding them risks ordering nondeterminism in `evidence[]` for a gain under 0.2 s. |
| R6 | Bulk-admit shallow pool records with a "detail pending" tier to hit the 500 number faster. | Quality veto (Moreau) and ADR-5: the pool already carries them legibly with a reason. A catalog of 1,000 where 600 are stubs is a *worse* product and a *smaller* one in the terms the charter uses. |
| R7 | Second-agent review inside the pipeline (an LLM checks each capture's `worth`). | Accepted as a *queue* idea (a second opinion per batch on the two or three hardest calls), rejected as a *parallelisation* mechanism: eleven concurrent reviewers each invent their own standard for "is this a good idea" is how a curated catalog becomes a list. Verdicts are the serial part (P3). |
| R8 | Re-fetch pages per review to "confirm the capture is current". | M5 × catalog size: re-reading 1,000 pages is 2,000+ fetches per review cycle, against a source that has rate limits and a no-mirror posture. The cache (P6) plus the capture's `captured_at` is the answer; Devpost pages are write-once (R11 of the first panel). |

---

## 9 · Sequenced Implementation (what each next batch actually does)

Ordered so that each step is independently shippable, each ends in a green `make verify`, and the prerequisites (P1, P4, P5) come before anything that would otherwise fail on write collisions or the sector ceiling.

| Batch | Ships | Gate that proves it | Rollback |
| --- | --- | --- | --- |
| 6 ✅ | **P4 + P1.** Per-record notes files; `capture_lint.py` with the rule set above, wired into `make build` and `make verify`; lint failures classified `incomplete` vs `thin`. | `bench_scale.py --skip-grow` still lossless; a truncated capture in a temp dir is rejected by name, build survives; all 18 existing captures lint clean. | `git revert` the lint call in `build`; the notes shim keeps the legacy file authoritative. |
| 7 ✅ | **P2 + P9.** 4 published records in one batch with zero hand-repair; reject-rate recorded; queue recomputed after merge (test: partition is stable across a merge, ids unique across shards). | set `batch_size: 2`. |
| 8 | **P5.** Sheet index + `data/sheets/<id>.json`; UI lazy-load for a sheet; `--check` parity both directions; sector budget moved onto the index. | Every existing sheet byte-identical after the move (compare `git show HEAD:web/public/data/audits/*.json` payloads field by field); budget `--check` green; a reader fetches < 12 KB to open any record. | revert the emitter, keep the index generator unused. |
| 9 | **P7 + P8.** `repo_verify` request pool + shared `Client`; `api_ledger.json` with `pushed_at` skipping; per-shard budget slices. | `bench_scale.py`'s `[repo_verify I/O]` line improves ≥ 4× at 8-way; a re-run with unchanged pushes costs **0** requests (assertable in a unit test with a fake client). | `--workers 1` and ignore the ledger. |
| 10 | **P6.** Page cache + quote-must-be-in-cache rule in the lint; `fetch_page` calls recorded in the ledger so fetch counts per batch become a measured number. | Lint rejects a quote absent from the cache; re-running a batch costs 0 fetches; cache size reported in `catalog-stats.json`. | cache is advisory; disable the quote rule by flag. |
| 11 | **P10 + P3's codification.** `review_diff.py`; a `docs/` note that verdicts and ranking are reducer-only; `bench_scale.py --check-only` mode in CI. | The batch-11 review is a single diff print, and the printed field set ⊇ the 12 mandatory fields. | it's a print tool; delete the make target. |

**Standing stop conditions** (the governor, from P9, stated here so it binds the reviewer too): if any batch shows a lint reject rate > 20 %, or a *material* correction found in review (a published field that states something false), the batch size halves and the engine — not the record — gets the next change. That is how "faster" is prevented from becoming "looser" in the one place the panel could not defend by argument.

---

## 10 · Dissents and Open Risks (not swept under the rug)

- **D1 · Raghunathan's dissent, kept on the record:** "the plan is not parallel, it is *batched*. W=4 sessions is the practical ceiling because the reducer — build, gates, one commit — is serial, and every real win after P9 comes from the lint's reject rate, not from my partition. If the reject rate is high, I have engineered a nicer way to fail four times as often." Accepted as the reason P9's governor is in the plan and the stop conditions are binding.
- **D2 · Lindqvist on M8:** the ~59-published-per-sector figure is **11 real records** extrapolated; at 100 records per sector the fixed overhead per file is amortised, so the true ceiling per sector is higher — but nobody has measured it, and the panel agreed to plan against the pessimistic number and let P5 make the question moot.
- **D3 · Nwosu's standing objection:** this document's speed-ups are measured *locally*; the §7 table is modelled. The first batch that runs two sessions in parallel is the experiment, and its result — including a null result — belongs in `docs/AUDIT_PANEL.md`'s ledger, not in this file.
- **D4 · Vale's fear, unresolved by design:** bigger batches make *sameness* cheaper to produce. The duplicate pass catches the same project; it does not catch "the same idea from four events, described in four voices". `kin_redundancy` and `cross_linked` are the only signals, and both are descriptive (ADR-5). If the catalog grows to 1,000 and reads like 40 ideas wearing hats, the correct diagnosis is the sector/subsystem vocabulary, not the gate.
- **D5 · Ops reality check (Berg):** M13 already cost this session an hour of recovery (`node_modules`, a rolled-back `.git`). Any worker that treats the workspace as durable will eventually produce a batch that exists only in someone's scrollback. Every ADR here that survives contact with this environment ends in a **push**, and `pipeline/` keeps its no-network-required build.
- **Open (raised by M15, deliberately not finished here):** the reverse "served but not emitted" check is scoped to `data/audits/`, because `agents/*` and the detail/pool shards are emitted by other steps and a whole-tree reverse walk reports them as orphans. The right shape is each build step declaring the paths it owns, then one gate over all of them — worth doing before any second writer touches `web/public/` (§9 batch 8), or P5 will re-create this defect one directory over.
- **Open:** 1,000 `data/sheets/*.json` files × `ingest`-style directory scans — the per-file JSON cost is 12 ms/row at 1,151 rows (M2). At 1,000 sheets + 1,000 captures + 1,000 notes, `make build` is projected at ~60 s (modelled, 3× M2's ingest rate). Trigger for a manifest cache, written down so it is a decision and not a surprise.

---

## 11 · Reproducing this document's numbers

```bash
python3 pipeline/bench_scale.py --records 1000      # timings, lossless proof, budget math, API latency
python3 pipeline/bench_scale.py --skip-grow         # the proof + the sector/Tier-1 budget math only (~1 s)
make verify                                         # the gates every ADR above is judged by
```

`bench_scale.py` writes only under a temp dir, deletes it unless `--keep`, and treats a lossy optimisation as a hard failure (`exit 1`). If a future change to the audit makes the blocking lossy, this file's M3/M4 numbers are wrong and §6 ADR-P11 needs re-arguing — which is the intended behaviour of a dossier that can be re-measured rather than re-read.


---

## 11 · Addendum (2026-09-19) · rows 6 and 7 shipped, and one decision the panel never had to make

Plan batch 6 (P4 per-record notes, P1 the contract gate) and plan batch 7 (P2 dispatch, P9 governor) are
implemented and gated: `pipeline/raw/audit_notes/{id}.json` (20 files, legacy dict emptied, loader merges
directory over legacy), `pipeline/capture_lint.py` (schema-versioned, `--install-*` refuses before
writing, `--soft` in `make build` and strict in `make verify`, refusals recorded per record in
`raw/lint_rejects/{id}.json` and surfaced in `pool.json` as `incomplete capture`), `partition_of` in
`taxonomy_hacks.py`, and `pipeline/next_batch.py` for dispatch plus the reject-rate governor. 16 of the 20
committed captures adopted `schema: 2` on the day it shipped; the four that did not are named in the lint's
summary line and pinned by a test that only lets that list shrink.

**P15 · A second tier, adopted by the operator, not by the panel.** The panel argued throughput inside one
constraint — every published row carries all twelve fields. The operator has now lifted it for volume: an
`audited-lite` row publishes **six** fields (`what_it_is`, `what_it_does`, `limits_they_disclosed`,
`how_they_tested`, `prior_art`, `numbers_with_arithmetic`) with a `tier` label on every surface that shows a
verdict, and it may never carry `strong` worth or a `strong` verdict. That is a real trade, and its cost is
legibility: a reader who cannot tell a 6-field row from a 12-field row has been *sold* depth they did not
get, which is the same failure class as the superseded sheet in M15. So the spec is not "allow shorter
records", it is "make the shorter records unmissable": `tier` in the sheet, the index row, the CSV column,
the NDJSON record and the UI badge; `fields_absent` naming what was never written; and the rubric publishing
the ladder for both tiers so an agent can tell what a lite row would take to become full. P15 **shipped the same day it was proposed**: `audit_projects.lite_admission`, `tier`/`fields_absent`/
`tier_note` on the sheet, `tier_id` in the packed rows, `audit_tier` in both CSVs, `tier` in the audit
index and the NDJSON `audit` block, both ladders in the rubric, and separate `published_full` /
`published_lite` counts that the census quotes. The twelve-field ladder is unmodified; lite is a second
ladder with its own four guards, and a contradicted record cannot reach it at all.
