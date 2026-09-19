# Audit Protocol — how a project earns a row

Status: **implemented and gated**. Engine `pipeline/audit_projects.py`, publication
`pipeline/shard_builder.py`, rubric source `pipeline/taxonomy_hacks.py`
(`audit_rubric()`), deliberation record [`AUDIT_PANEL.md`](AUDIT_PANEL.md).

This document is the executable version of the panel's decision: what is checked, in what
order, with what evidence, and what a build does when a record fails.

---

## 1 · Why the catalog is small

A reader asked "what should I build next?" gets no value from a list of 165 one-liners.
They get value from a smaller number of records they can trust: what the thing is, what it
does, whether it works the way it claims, whether it is worth copying, and where it will
break in *their* hands.

So the published catalog is **audited-only**. A record appears in
`web/public/catalog-packed.json`, `data/ideas.csv`, `data/ideas.ndjson`, the SQLite file
and the Tier-2 detail shards **only if** its audit sheet says `publishable`. Everything
else — thin evidence, resubmissions, hazard-blocked, never-audited — moves to
`data/pool.json` with machine-readable reasons and stays reachable, because nothing here
is deleted.

The catalog currently holds **5** records out of 165 admitted ones. Ten projects have been
captured and scored; five cleared the ladder and five are held for cause (two resubmissions,
three thin-evidence). The other 155 were never captured deeply enough to audit. Both gaps are
the point of the promotion queue (§6), not defects to hide: `agents/llms.txt` and
`catalog-stats.json` publish `audited_published` next to `pool_records`, and `pool.json`
carries a per-record reason for every one of the 160.

The published five span the range a reader should expect from this method: a cost-model
pipeline at 0.77, a live production consumer product at 0.68, a concussion-recovery triage
tool at 0.55, a Rust supply-chain verifier at 0.52, an on-device transcription stack at 0.51.
All five are `sound-with-caveats` — no project in this corpus can currently reach `strong`,
and §4 explains why that is a finding about hackathon pages rather than about teams.

---

## 2 · Inputs (and what each one is allowed to say)

| Input | Path | Provides | May it decide a status? |
| --- | --- | --- | --- |
| capture | `pipeline/raw/deep_captures/<id>.json` | the page's own structure: `sections`, `built_with`, `links`, `numbers[{claim, denominator, arithmetic, verifiable}]`, `testing`, `data_and_models`, `captured_at` | it *supplies evidence*; the status is recomputed |
| repo check | `pipeline/raw/repo_checks.json` | `api.github.com` facts: language, size, last push, README size, test paths | yes — it is the only independent signal we have |
| editorial notes | `pipeline/raw/audit_notes.json` | `worth`, `worth_note`, `what_to_steal`, `what_breaks_first`, `prior_art`, `clone_cost`, `hazard_note` | **no** — judgement fields only, never a check status |

The split is load-bearing. An auditor cannot mark its own `arithmetic: "not falsifiable
as presented"` as confirmation, and cannot claim a benchmark by writing the word
"benchmark". `run_checks()` derives every status from the shape of the data.

Two rules came out of mistakes the panel actually made:

- **A page's framing is not evidence.** A capture that labels its own number
  `verifiable: false`, or whose arithmetic note starts with *not / unfalsifiable / cannot /
  no*, yields `unverifiable`, not `confirmed`. (MCOP read as `1.0 confirmed` before this.)
- **A measured table is evidence even without the word "test".** `numbers_add_up` and
  `test_or_eval_evidence` scan `testing` for first-pass rates, A/B denominators, seeds,
  sample sizes and calibration runs. (Greenlight's 29% → 49% before/after read as
  "no tests visible" before this.)

---

## 3 · The rubric: 12 mandatory fields, 6 checks

Fields (all must be *filed* — a value plus an evidence status — for publication; an honest
`unknown` with a reason is a filed answer, a silent blank is not):

`what_it_is` · `what_it_does` · `how_it_works` · `numbers_with_arithmetic` ·
`data_and_models` · `how_they_tested` · `limits_they_disclosed` · `built_with_verified` ·
`what_to_steal` · `what_breaks_first` · `clone_cost` · `prior_art`

Checks, each `status` + `pass ∈ [0,1]` + `why` + evidence ids:

| check | answered question | status rule of thumb |
| --- | --- | --- |
| `artifact_exists` | is there a thing (repo, deployment, video)? | `contradicted`/missing ⇒ hard cap `thin` (A3) |
| `build_is_real` | does the described architecture match the repo/stack? | repo files + `built_with` overlap |
| `test_or_eval_evidence` | did anyone measure anything? | harness in repo, or an eval table on the page |
| `numbers_add_up` | do the quoted numbers survive arithmetic? | recomputed from `denominator` + `arithmetic` |
| `stack_consistency` | does the claimed stack do the job claimed? | tag/section cross-check |
| `limits_disclosed` | did they say what it cannot do? | presence of real constraints, costs, refusals |

`soundness_score` is the mean of scored checks; `rubric_coverage` is the fraction of the 12
fields filed with an evidence status. Both are emitted, never a composite of them.

### Reading prose without being fooled by it

Every one of these rules exists because a real page broke the simpler version. They are
mechanical, not judgement calls, and each is pinned by a test.

- **Polarity, not vocabulary.** `test_or_eval_evidence` reads the capture's `testing` field,
  then the page, and discards any keyword sitting inside a negation (`no`, `not`, `without`,
  `absent`, `no public`… within 80 characters before it). "No test suite, evaluation set, or
  validation is described" must lower the score; an earlier version scored that sentence as
  *supported 0.75* because it contained the word "evaluation".
- **A comparator word is not a comparison.** `accuracy`, `precision`, `latency` count as
  evaluation language only inside a sentence that carries a digit. "Coding the sync layer on a
  phone demanded precision" is an adjective. Prose-only mentions of a measurement earn
  `partial 0.4` with both halves of the contradiction quoted, never `supported`.
- **Structural figures cannot vouch for outcome figures.** "Ten art styles" and "twelve attack
  scenarios" are checkable by opening the product; they are recorded in a `checkable` tier and
  lift a page to `partial 0.5`/`supported 0.6`, never to `confirmed 1.0`. `confirmed` requires
  arithmetic *we* re-derived (`_testable` rejects `arithmetic` beginning `structural`, `n/a`,
  `not`, `cannot`).
- **A hard weekend is not a disclosed limitation.** `limits_disclosed` reaches `confirmed` only
  on a capability-shaped statement (accuracy, privacy, offline, unsupported, fails, abuse,
  rate-limit…) sitting in a sentence that is not about compiling, pushing, devices or hours.
  Build-process honesty scores `supported 0.6`, with a `why` that says which half is missing.
- **A described harness and a measured loop are different from absence.** A harness named
  without a linked result scores `partial 0.5`; a product measurement loop (analytics, funnels,
  logged A/B) also scores `partial 0.5` — above `unverifiable 0.0`, which is reserved for pages
  that state nothing or deny testing. "Dashboard" is deliberately *not* a measurement word: in
  this corpus it names a screen.
- **`artifact_exists` ranks the artifact.** A live address any reader can open scores
  `supported 0.75`; a video of a working thing `supported 0.5`; nothing linkable
  `unverifiable 0.0` and the record is hard-capped to `thin`.
- **`built_with_verified` says whether it was verified.** Its value is the declared tag list plus
  what corroborates it — repo languages, or "no repository published, so these are the team's
  own claim and nothing corroborates them". A mandatory field's value has to carry its own
  epistemic status; a length floor that dropped a four-tag list into `unknowns` once failed the
  build gate, which is the wrong place to discover a formatting rule.

---

## 4 · Verdict ladder

```
contradicted on a load-bearing claim  →  unsound      (pool)
no artifact                            →  thin          (pool, hard cap)
coverage < 0.34 or >2 load-bearing unknowns → thin    (pool)
score ≥ 0.70 and coverage ≥ 0.80       →  strong       (publish)
score ≥ 0.45                           →  sound-with-caveats (publish, unknowns listed)
otherwise                              →  thin          (pool)
same product under another name/slug   →  duplicate → best-sourced sibling (pool)
```

Two deviations from the panel's first draft, both of which the code enforced on its own:

1. **Coverage-aware renormalisation.** A record cannot be `strong` at 64% coverage however
   high its score: `strong` requires `rubric_coverage ≥ 0.80`. Greenlight sits at
   `sound-with-caveats` for exactly this reason — its scores are high and its gaps are many.
2. **Listing-title equality merges what prose cannot.** Two records whose *published display
   names are identical* inside one event are one product submitted twice — on Devpost each page
   carries the platform's title, and the teams' own prose diverges on purpose. `gemini-box` and
   `adversarial-compliance-matrix` both list as "Gemini-Box" at XPRIZE, so the thinner-evidenced
   one is a `duplicate`. The route reads the corpus listing title, not the slug or the capture
   name, and needs no text overlap (their Jaccard was 0.07). The pair it must *not* touch —
   "NeuroGuard AI" vs "NeuroGuard AI (v2)", two teams, same event, same idea — differs by a
   suffix, so it fails exact equality and is instead kept and cross-linked as parallel
   invention. That is the whole distinction: a name a team chose twice is a collision, a name
   that is byte-identical is a listing.
3. **Resubmission detection by numeric fingerprint.** Prose Jaccard cannot catch the same
   product rewritten for a different hackathon (each event gets its own write-up; overlap
   stayed under the 0.60 threshold). `numeric_fingerprint()` extracts the distinctive
   `$`/`%`/unit figures from numbers, sections and one-liners; two records that share ≥3
   fingerprints *and* a leading name token merge. Greenlight's two slugs share
   `$0.02 · $20 · $238 · $4.50 · 29% · 49%`.

One consequence is worth stating plainly, because it looks like a scoring bug until you read
the corpus: `rubric_coverage` tops out near **0.64** for any record without a repository, since
`built_with_verified`, `build_is_real` and `stack_consistency` can never be *filed with
evidence* without one. `strong` needs coverage ≥ 0.80. So **`strong` is unreachable for
projects that publish no code** — and 0 of the 165 admitted records link a repository. The top
rung of the ladder is currently aspirational by construction, which is a finding about
hackathon submission pages, not a defect: from a page alone, nobody can certify a build.

`worth` (`breakthrough | strong | niche | tired`) is decided *only* after soundness, and
never combined into a single number. An impressive-but-unverifiable project is
`thin` + `breakthrough`, and `why_not_promoted` says so.

---

## 5 · What the build refuses to publish

`shard_builder.audit_gate_checks()` runs inside `--check` (and `make verify`), so these are
build failures, not style opinions:

- the Tier-1 row set must equal *exactly* the admitted ∧ `publishable` set;
- no published record may carry a non-publishable verdict, or an unfiled mandatory field;
- every evidence row needs a `source` and an in-vocabulary `status`;
- a `duplicate_of` pair may not both be published;
- catalog + pool must be a **partition** of admitted records (nothing vanishes, nothing
  bypasses the audit), and `pool.json` must agree with `catalog-stats.json`;
- `data/audits.json` ≤ 40 KB gz, `data/audits/*.json` ≤ 240 KB gz;
- auditor prose is scanned for verdict adjectives (`fake`, `vaporware`, `scam`, `lied`…),
  **word-bounded** — `implied` must not trip `lied`;
- every emitted surface is byte-identical on rebuild (determinism includes the audit).

`Tier-1 column order` and the `CSV header` come from one place
(`taxonomy_hacks.ROW_FORMAT` / `CSV_COLUMNS`), imported by both the emitter and the agent
contract, and asserted against each other — the drift that hid 16 vs 14 columns was the
reason.

---

## 6 · Working the queue

```bash
make audit                      # re-derive sheets + print the top held-back candidates
python3 pipeline/audit_projects.py --report --queue 12
```

For each candidate: fetch its Devpost page (`pipeline/harvest_devpost.py deep`), run
`pipeline/repo_verify.py` on any linked repo, write `pipeline/raw/deep_captures/<id>.json`,
add editorial notes for anything you can cite, then `make build`. The gates decide whether
it ships; no manual promotion path exists.

Two operational facts, learned the hard way in batch 1:

- **The pipeline cannot fetch Devpost.** `harvest_devpost.py` only paginates galleries it was
  given as saved HTML, and the search endpoints answer 500. A capture is written by hand from
  a fetched page — `https://devpost.com/software/<slug>`, chunk 0 carries all eight authored
  sections, the `Built With` list and the `software_id`. `harvest_devpost.py deep` has no
  per-id selector, so targeted refetches mean authoring the capture file yourself.
- **`repo_verify.py --search-missing` records leads, never findings.** For every captured page
  that links no repository it name-searches GitHub and writes
  `pipeline/raw/repo_candidates.json`, explicitly labelled CANDIDATES. It exists so the next
  auditor knows what to ask a team for — a search hit is never evidence of authorship. The
  corpus makes the difference concrete: `Adversarial Compliance Matrix` returns one exact-name
  repo, while `ComplianceGuardian` returns three same-named repos from unrelated accounts, and
  `NeuroGuard AI` returns four teams that have nothing to do with either submission. The engine
  reads `links.repo` from the capture and nothing else, so a candidate cannot reach a verdict
  even by accident (A14).
- **Only `api.github.com` is reachable from the build box.** Live deployments were probed once:
  the TCP connect succeeded and the TLS handshake was closed. So `repo_verify.py` is the sole
  independent verification channel, `artifact_exists` for a page with a live URL but no repo
  stops at `supported`, and `confirmed` needs a GitHub repository. Write `provenance:
  "unavailable"` and a `why` rather than guessing at an org name: `repo_checks.json` records
  which repos were actually queried, and a capture with `links.repo = null` produces no
  `build_is_real` check at all (A14/C5) — absence of a link is not treated as absence of code.

**Batch 1 (2026-09-19)** captured six pages: NeuroGuard AI (both teams), Gemini-Box,
Adversarial Compliance Matrix, Medvoice, SketchWish. Two shipped (`SketchWish` 0.68,
`NeuroGuard AI` 0.55), one shipped under its sibling's slug after the listing-title merge
(`adversarial-compliance-matrix` 0.52), three are held: `gemini-box` as a duplicate,
`neuroguard-ai-0qb34c` and `medvoice-y87kei` as `thin` — no measurements, no repo, video only.
Working that batch is what produced the six prose-reading rules in §3; five of the six pages
initially scored too well, in ways that flattered the teams' vocabulary rather than their evidence.

`data/promotion-queue.json` ranks unaudited rows by expected information gain — a sector
with many rows and no audit is worth more than a 12th agentic-crew project. It is a
*learning* order, explicitly not a merit order.

---

## 7 · Reading the surfaces

| Surface | What to expect |
| --- | --- |
| `data/audits.json` | id → verdict, worth, score, coverage, per-check `status`, unknown field names, sheet pointer (~150 B/record) |
| `data/audits/<sector>.json` | full sheets: `fields[f] = {value, evidence[], confidence, status, why?}`, per-check `why`, the evidence ledger, `right_of_reply` |
| `data/audit-rubric.json` | the rubric itself: mandatory fields, check weights, verdict ladder, hard caps, dedup thresholds, banned words, policy |
| `data/pool.json` / `pool.csv` | held-out records with `why_not_promoted[]` and `would_settle_it[]`; `provenance` splits `audited-hold` (scored, capped) from `unaudited` (never captured), and the CSV repeats `ideas.csv`'s column order so one parser reads both |
| `data/promotion-queue.json` | the work list |
| `agents/schema.json → audit` | the same vocabulary, generated from the rubric rather than retyped |
| MCP `audit_report` / `promotion_queue` / `audit_rubric` | the same three answers over the protocol |

A `null` audit block in a record, or a `verdict_id` outside the enum, means *unaudited* —
never "passed".

---

## 8 · What this audit still cannot do

- It cannot verify a demo that exists only as a video, nor run a claim's code:
  `build_is_real` stays `unverifiable` when a page has no repo, which caps many otherwise
  good UI-only projects. `demo_responds` (actually probing a live deployment) is the next
  rung and is deliberately not faked.
- It cannot audit a record it cannot capture: Devpost's search endpoints return 500 here,
  so candidate discovery is gallery-pagination-bound.
- It will call a claim `unverifiable`, not false. Reporting `unverifiable` as a debunking
  is the most likely misuse of this layer, and the reason the word "harness" appears in the
  `why` strings rather than a verdict adjective.
- It cannot reach the artifacts it would most like to check. From the build environment only
  `api.github.com` responds, so a live deployment is credited as `supported`, never
  `confirmed`, and a page with neither repo nor URL cannot be helped at all. A reader or agent
  with a browser *can* do the remaining step; `would_settle_it[]` on the pool row names it.
- It cannot see a repository that a page does not link. Since 0 of 165 admitted records link
  one, `build_is_real` and `stack_consistency` are `unverifiable` for the whole corpus, and
  `strong` is out of reach for every record (§4).
- It scores an authored fixture suite generously unless someone reads it as what it is: an
  agent that wrote its own attack matrix and its own tests, then ran them in CI it configured,
  has produced *agreement with itself*. That reads as `partial 0.5` here with the reason
  spelled out, which is a smaller claim than the page's own "flawless / bulletproof" framing.
- A `thin` verdict is a statement about this audit's evidence, not about the team. Three of the
  five held records here are projects a builder may well want to copy — `Medvoice` carries
  `worth: strong` while sitting in the pool at 0.27, and `why_not_promoted` says the only thing
  that would change that.
- It inherits the corpus's biases. 85 of the 165 admitted rows come from one XPRIZE gallery
  that is 1,401 pages deep, of which 4 pages were crawled (5.9%); 10 records in total have been
  captured for audit. `catalog-stats.json → coverage` publishes the same figures so a consumer
  cannot quietly forget them.
