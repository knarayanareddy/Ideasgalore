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

The catalog currently holds 2 records out of 165 admitted ones, because only 4 projects
have been captured deeply enough to audit. That gap is the point of the promotion queue
(§6), not a defect to hide: `agents/llms.txt` and `catalog-stats.json` both publish
`audited_published` next to `pool_records`.

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
2. **Resubmission detection by numeric fingerprint.** Prose Jaccard cannot catch the same
   product rewritten for a different hackathon (each event gets its own write-up; overlap
   stayed under the 0.60 threshold). `numeric_fingerprint()` extracts the distinctive
   `$`/`%`/unit figures from numbers, sections and one-liners; two records that share ≥3
   fingerprints *and* a leading name token merge. Greenlight's two slugs share
   `$0.02 · $20 · $238 · $4.50 · 29% · 49%`.

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
| `data/pool.json` / `pool.csv` | held-out records with `why_not_promoted[]` and `would_settle_it[]` |
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
- It inherits the corpus's biases (one dominant hackathon, 4 of 1,401 XPRIZE pages).
  Coverage is stated in the same files so a consumer cannot quietly forget it.
