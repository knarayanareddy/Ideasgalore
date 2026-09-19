# Audit Panel — Deliberation Record
## How Ideas Galore decides whether a project is *good*, *sound*, and *not a duplicate* — before it is ever tabulated

> **Status:** binding spec. The ADRs in §6 are implemented in `pipeline/audit_projects.py`,
> `pipeline/repo_verify.py`, `pipeline/taxonomy_hacks.py`, `pipeline/shard_builder.py` and the
> front end. Rubric as data: `web/public/data/audit-rubric.json`; human read:
> [`AUDIT_PROTOCOL.md`](AUDIT_PROTOCOL.md). Prior art: [`EXPERT_PANEL.md`](EXPERT_PANEL.md)
> (architecture panel, 15 ADRs) — this panel *extends* it; nothing here relaxes an earlier
> decision except where a dissent below says so.
>
> **Trigger for this panel (user requirement):** the catalog must not contain weak projects or
> near-identical projects, and every published row must carry enough detail that neither a human
> nor an agent has to fill in blanks.

---

## 1 · Ground truth measured before anyone argued

| Measurement (2026-09-19, against the live build) | Value | Consequence |
| --- | --- | --- |
| Published rows in catalog | **165** | the thing being audited |
| rows with `depth: deep` (authored sections captured) | **2** | 98.8% of the catalog is a one-line gallery hook |
| rows with a project-repo link | **0** | nothing in the corpus has ever been verified against an artifact |
| rows with a like count | **1** | social signal is essentially absent; popularity-based quality control is impossible |
| rows whose summary ≥ 140 chars | 79 / 165 | half the corpus cannot even support a "what does it do" question |
| near-duplicate clusters found from listing text (Jaccard ≥ 0.34, same sector) | 1 (the two `Gemini-Box` records) | **hooks are too thin to detect similarity** — a hook-level dedup pass is theatre |
| `api.github.com/repos/…`, `/readme`, `/search/repositories` from this sandbox | 200 · 42 KB readme · search works · **8,200 req/hr** | mechanical verification of artifacts is available and cheap |
| `raw.githubusercontent.com` | blocked (`000`) | fetch file bodies via the API only; do not assume raw hosts |
| `fetch_page` cost per Devpost project page | 1–2 calls (~24 authored sections per page) | depth is the expensive axis: **~10–25 records per working session**, not 165 |

**The finding that reframed the whole debate (Osei, §2):** the request "audit every project
carefully and publish full detail" cannot be satisfied by *classifying harder*. Classification was
never the bottleneck — evidence was. With 2 of 165 rows carrying authored content, any verdict on
the other 163 would be a guess about a stranger's competence. Therefore the audit is a
**budgeted, evidence-gated promotion pipeline**, and the honest failure mode of "not enough
evidence" is *exclusion with a reason*, never a score.

---

## 2 · The panel

| # | Persona | Vantage / what they were hired to protect |
| --- | --- | --- |
| P1 | **Dr. Ines Varga** — forensic software auditor (SBOM / provenance background) | "Does the artifact exist, and does it match the claim?" Refuses any verdict with no observable behind it. |
| P2 | **Malik Osei** — ML systems engineer | Does the model claim survive arithmetic: latency, token cost, dataset size, eval design, "98% accuracy" on what denominator? |
| P3 | **Dr. Yuki Tanabe** — clinical/human-factors reviewer | Health, accessibility and safety claims: a hackathon demo is not a device. Wants explicit "not for clinical use" handling. |
| P4 | **Priya Raman** — venture/product analyst | "Is it a *good idea*": who has this problem on a Tuesday, what is the wedge, why now, what breaks first, could a weekend team clone it. |
| P5 | **Sofia Lindqvist** — information architect | Similarity, merge policy, catalog integrity: what is a duplicate vs parallel invention; single-source-of-truth for published vs pool. |
| P6 | **Owen Blake** — performance & cost engineer | Payload and rate budgets: audits make records ~40× bigger; where they may and may not go. |
| P7 | **Nadia Farouk** — data-ethics & sourcing counsel | We are publishing judgements about students' work. Tone policy, right of reply, "unverifiable" ≠ "dishonest". |
| P8 | **Theo Marsh** — agent-interop engineer | An agent must be able to *use* a verdict safely: refusal semantics, unknowns as data, confidence in every response. |
| P9 | **Camille Duarte** — technical editor | The "no blanks" standard: what a complete picture looks like as prose, and what an honest gap sentence looks like. |

---

## 3 · Round 1 — proposals (each with its research note)

**Varga (P1) — "Verification ladder, not a score."**
Publish nothing that has not been checked against an artifact. Five rungs: *claimed → described →
demonstrated → reproducible-by-reading → corroborated-by-repo*. Every rung gets an evidence record
`{kind, url|metric, checked_at}`. Her data point: 0/165 rows carry a repo link, so today the
catalog would fail its own first rung on every record. Her ask: a verdict is a *function of the
evidence table*, never a field a human types.

**Osei (P2) — "Numbers must be re-derived, not repeated."**
Add a `numbers` block where the team's metrics are restated *with our arithmetic*: what denominator,
what baseline, cost per run at current API prices, and whether the claim is internally consistent
(e.g. "$0.02 per candidate, 40 candidates per film, so a 12-minute film ≈ $238" — checkable). A
project that only asserts "high accuracy" gets `numbers: unverifiable`, which is a *finding*, not a
blank.

**Tanabe (P3) — "Domain hazard is part of quality, not a footnote."**
Any record touching diagnosis, medication, clinical triage or safety-critical routing carries a
`hazard` field: regulated-claim risk, and whether the team disclaimed it. Without this, a catalog of
"cool ideas" becomes a list of things to ship dangerously.

**Raman (P4) — "'Good idea' and 'well built' are orthogonal. Score both, publish both, never average.**
Her counter-example set: `Greenlight` (a genuinely novel wedge — price-before-generate — on
sketchy engineering) and `Real Time Object Detection` (competent, boring, already exists 400
times). Averaging the axes would promote both-and-discard-neither. She wants `worth ∈
{breakthrough, strong, niche, tired}` justified in one sentence with the *competing prior art named*.

**Lindqvist (P5) — "Similarity is a merge, and only same-team re-submission is a true duplicate."**
Two teams at one event building the same thing is the *most interesting* fact in the corpus
(convergent need), not dirt. Proposed rule: `duplicate_of` only when the identity matches
(same submission re-posted / same team, same scope) or scope overlap ≥ 0.6 **and** mechanism overlap
is total; otherwise `parallel_invention_of` (kept, cross-linked). Also: dedup must run at *depth*
(authored sections), not on hooks — measured above as incapable.

**Blake (P6) — "Audited records are 2–6 KB each. They must not touch Tier 1."**
Proposed budget: Tier-1 grows by **3 ints per row** (`audit_id`, `verdict`, `worth`) ≈ +0.4 KB for
165 rows; full audit sheets live in `data/audits/<sector>.json`, lazy-loaded per sector like deep
records today. Hard ceilings: audited catalog ≤ 240 KB gz total; `data/audits.json` index ≤ 40 KB;
one GitHub call budget ≤ 60/run at 8,200/hr means a weekly cron can never be the reason the API
throttles anyone.

**Farouk (P7) — "Verdict vocabulary is a legal surface. Fix it in writing."**
Only these words in published verdicts: `confirmed`, `supported`, `partial`, `unverifiable`,
`contradicted`, `duplicate`. Never "dishonest", "fake", "AI slop", "vaporware" (even though engineers
will type it). Every `contradicted` must name what we looked at and when, and the record carries a
`right_of_reply` pointer to an issue template. Rejected Varga's draft wording "unsupported claims
suggest misrepresentation" outright — we audit artifacts, we do not impute intent to students.

**Marsh (P8) — "Refusal must be a first-class agent response."**
An agent asking about a pool record should get `{published: false, reason: "insufficient_evidence",
would_settle_it: ["project page capture", "repo link"]}` — not a row of nulls, and not a hallucinated
summary. Every MCP response gains `audit: {verdict, audited_at, unknowns: [...]}`; `search_projects`
defaults to `verdicts=[strong, sound-with-caveats]` so an agent cannot accidentally pull unaudited
material into a plan.

**Duarte (P9) — "No silent blanks. A gap is a sentence."**
Mandatory field set per published record (the "full picture" contract): what it is · what it does,
step by step · how it works (components, data flow, where the model sits) · built with (verified) ·
data & models · how they tested · limits they disclosed · numbers with our arithmetic · what to steal
· what breaks first when you clone it · cost to clone · `unknowns[]`. If a field cannot be filled,
`unknowns` gains a line naming the missing evidence. "The page does not say whether audio is on-device
or streamed" is a *useful* sentence; an empty string is not.

---

## 4 · Round 2 — critique matrix (attacked, defended, killed)

| # | Attack | From → On | Verdict after exchange |
| --- | --- | --- | --- |
| C1 | "A 6-check ladder on 165 records is 165 × (2 fetches + 3 API calls). You will audit 8 and call it a pipeline." | Blake → Varga | **Accepted as the design, not the objection.** Audit capacity is the product: **audited-only catalog**, everything else an explicitly-labelled pool (A1, A7). 12 candidates this session, 25/run ceiling thereafter. |
| C2 | "Verdicts computed from checks will be gamed by your own regexes; teams write 'we tested thoroughly' and pass." | Osei → Varga | **Partially accepted.** Checks look at *artifacts and structure* (repo languages vs claimed stack, README presence of setup steps, presence of an evaluation table with a denominator), never at adjectives. `tested` requires either a test dir in the repo or a numeric eval in the page. |
| C3 | "Marking 153 of 165 as 'pool' throws away the harvest you just sold me last week." | Lindqvist → Varga | **Rejected as stated, accepted in substance.** Nothing is deleted: pool rows keep full listing data + `why_not_promoted` + `would_settle_it`. Two read surfaces, one emitter (ADR-8) — pool is `data/pool.json(.csv)`, visible in the UI behind a toggle, excluded from agent defaults (A12). |
| C4 | "Publishing 'contradicted' about a student's project, with our name on it, is the most litigious sentence this repo can contain." | Farouk → Duarte | **Accepted with force.** `contradicted` is only emitted against a *specific* quotable claim, states what we observed and when, and is capped at factual register. Editorial adjectives are banned from the field set entirely. Right-of-reply link mandatory (A10). |
| C5 | "Prior art named by Raman is an LLM hallucination waiting to happen." | Varga → Raman | **Accepted under constraint.** `prior_art` entries must be URLs we resolved this session (search hit + title match) or a corpus id we publish; a bare "similar to X" phrase is not permitted. |
| C6 | "0.6 scope-overlap for duplicates is a magic number." | Duarte → Lindqvist | **Settled empirically and pinned in tests:** thresholds 0.60 total-mechanism-overlap + same event/sector for `parallel_invention_of`, and identity-level match (slug-derived id, or same name + same team text ≥ 0.75) for `duplicate_of`. The Gemini-Box pair and the two Greenlight captures are the fixtures that set them. |
| C7 | "Cost-to-clone is you guessing other people's effort." | Farouk → Raman | **Reframed, kept.** Published as `clone_cost: {estimate, why, assumptions[]}` — an *estimate with its assumptions visible*, explicitly `derived`, never a fact about the team. |
| C8 | "Hazard flags turn a museum catalogue into a compliance regime; nobody wants to read them." | Osei → Tanabe | **Accepted only for the inspector.** Hazard renders as one stamp + one line in the audit sheet, and is a *field agents must query*, not a wall of warnings. |
| C9 | "If Tier 1 carries `verdict`, you've made the audit's vocabulary a wire format; it must never drift from the rubric." | Marsh → Blake | **Accepted.** Emitter writes `verdicts` + `rubric_version` into Tier-1 dictionaries from `AUDIT_*` tables (single source), and a test fails if the published vocabulary ≠ the rubric JSON. |
| C10 | "audited_at as a timestamp breaks the determinism gate we fought for last week." | Lindqvist → Blake | **Accepted:** audit dates live in `raw/*` captures as *data* (`captured_at` in the capture, `checked_at` in repo checks) and are copied, never generated at build time. `manifest.json` remains the only clock-bearing surface (ADR-10 inherited). |
| C11 | "Reputation: we are scoring people, so the rubric needs a version and an appeals path or the whole file is a liability." | Farouk → all | **Accepted:** `audit_version` per record, rubric emitted as data, takedown/re-audit list applied at build time alongside `overrides.json`. |

**Killed in this round:** per-record embedding-similarity dedup (Varga: no model, no corpus of
labels, and it hides *why* two rows matched); LLM-generated verdicts (Farouk: an unverifiable
judgement about a person's work generated by an unverifiable system); "audit everything nightly"
(Blake: 165 × depth fetches would be the third-party load this project exists to avoid); collapsing
soundness and worth into one `quality` number (Raman, unanimously seconded).

---

## 5 · Round 3 — scored vote

Scale 1–5: 1 = block, 3 = accept with edits, 5 = champion.

| Decision | V1 | O2 | T3 | R4 | L5 | B6 | F7 | M8 | D9 | mean |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Audited-only catalog + labelled pool (A1, A12) | 5 | 5 | 4 | 4 | 5 | 5 | 5 | 5 | 4 | **4.7** |
| Evidence ledger, verdict computed from checks (A2, A3) | 5 | 5 | 5 | 4 | 4 | 4 | 5 | 5 | 4 | **4.5** |
| soundness ⟂ worth, never averaged (A4) | 4 | 5 | 5 | 5 | 4 | 5 | 5 | 5 | 5 | **4.7** |
| merge-not-delete similarity policy (A5) | 4 | 4 | 4 | 5 | 5 | 5 | 5 | 4 | 4 | **4.4** |
| mandatory-field "no silent blanks" + unknowns[] (A6) | 4 | 4 | 4 | 4 | 5 | 3 | 5 | 5 | 5 | **4.2** |
| audit capacity ceiling + priority queue (A7) | 4 | 4 | 3 | 3 | 4 | 5 | 4 | 4 | 3 | **3.7** |
| payload split, Tier-1 +3 ints (A8) | 3 | 3 | – | – | 5 | 5 | – | 5 | – | **4.2** |
| agent refusal semantics (A9) | 5 | 4 | – | – | 4 | 4 | 5 | 5 | 3 | **4.2** |
| verdict vocabulary + tone + right of reply (A10) | 5 | 4 | 5 | 4 | 4 | 3 | 5 | 4 | 5 | **4.2** |
| determinism-safe audit dates (A11) | 5 | – | – | – | 5 | 5 | – | 4 | – | **4.8** |
| hazard stamp for regulated-claim domains (A13) | 3 | 3 | 5 | 3 | – | – | 5 | 4 | 4 | **3.9** |
| clone-cost estimate with visible assumptions (A14) | 3 | 4 | 3 | 5 | – | 4 | 3 | 4 | 5 | **3.8** |
| audit the audit: fixtures pin the thresholds (A15) | 5 | 5 | – | – | 5 | 5 | 4 | 5 | – | **4.8** |

**Consensus reached** after one revision pass (edits: C2's `tested` tightening, C4's tone cap,
C10's date rule, Duarte's unknowns→verdict interaction in A6). Two items needed a third round of
argument: A6's "unknowns count demotes the verdict" (Blake called it a perverse incentive to fill
fields with filler — resolved by requiring unknowns to name the *missing evidence*, which filler
cannot do) and A1's hard exclusion of pool rows from `search_projects` (Marsh wanted a flag, Blake
wanted the default; resolved as default-off + explicit `include_pool=true`).

---

## 6 · Binding decisions (ADR-A1 … A15)

- **A1 · Two tiers of *trust*, not just payload.** The catalog carries **audited records only**
  (`verdict ∈ {strong, sound-with-caveats}`). Everything else is the **pool**: same identity and
  listing facts, loudly marked `unaudited`, with `why_not_promoted` and `would_settle_it`. Nothing is
  deleted; nothing unverified is presented as inspiration.
- **A2 · Evidence ledger per record.** `audit.evidence[] = {id, claim, status, kind, source, detail,
  checked_at}` with status ∈ {`confirmed`,`supported`,`partial`,`unverifiable`,`contradicted`,
  `duplicate`}. Any published assertion must point at an `evidence` id. `verdict` is *derived* from
  the ledger (A3), never authored directly.
- **A3 · Six mechanical soundness checks** (weights fixed in `AUDIT_CHECKS`): `artifact_exists` (.22),
  `stack_consistency` (.18), `build_is_real` (.18), `numbers_add_up` (.16), `limits_disclosed` (.12),
  `test_or_eval_evidence` (.14). `soundness_score = Σ wᵢ·passᵢ` ∈ [0,1]; `artifact_exists` failing
  caps the verdict at `thin`; two or more `contradicted` ⇒ `unsound`.
- **A4 · Orthogonal axes.** `soundness` (did they build what they say) ⟂ `worth`
  (`breakthrough|strong|niche|tired`, is it a good idea). A record may be `sound: verified,
  worth: tired` (a clean clone) or `sound: partial, worth: breakthrough` (Greenlight) — both are
  publishable, both are honest, and the UI shows both.
- **A5 · Similarity policy.** `duplicate_of` (merge; only same-submission identity or same-team +
  ≥0.75 text overlap) → loser is unpublished with reason. `parallel_invention_of` (keep + cross-link;
  same-scope, different team) → *promoted*, not penalised, and the pair is surfaced in the inspector.
  Thresholds are pinned by fixtures (A15).
- **A6 · "No silent blanks."** 12 mandatory audit fields (Duarte's list). A field that cannot be
  filled yields a named `unknowns[]` entry (what is missing + what would settle it). More than 2
  unknowns on load-bearing fields (`what_it_does`, `how_it_works`, `numbers`) ⇒ `verdict: thin` ⇒
  not published in the catalog.
- **A7 · Depth budget & prioritisation.** Per run: ≤25 project-page captures, ≤60 GitHub requests
  (`--budget`), 1.25 s politeness floor retained from ADR-12. `select_candidates()` ranks the pool by
  expected information gain = `0.35·coolness + 0.25·specificity + 0.20·sector_need + 0.20·
  ambiguity` (ambiguity = duplicate-suspicion or high-marketing-to-mechanism ratio). Captures are
  committed under `pipeline/raw/deep_captures/` so rebuilds stay offline (ADR-10 inherited).
- **A8 · Where the bytes go.** Tier-1 rows gain exactly three integer columns
  (`audit_id`, `verdict_id`, `worth_id`) plus a `verdicts` dictionary; audit sheets ship as
  `data/audits.json` (index) and `data/audits/<sector>.json` (lazy). Ceilings: Tier-1 ≤ 1.2 MB (as
  before), audits index ≤ 40 KB gz, audited sheets ≤ 240 KB gz total; `--check` enforces them.
- **A9 · Agent contract.** `agents/schema.json` gains the audit object with per-field
  `x-provenance: audit`; `llms.txt` and `SKILL.md` state the promotion rule and forbid presenting a
  pool row as vetted. MCP: `search_projects` defaults to published verdicts (`include_pool` opt-in),
  new tools `audit_report` (full sheet) and `promotion_queue` (what to audit next + why), and
  `get_project` on a pool record returns `{published: false, why_not_promoted, would_settle_it}`.
- **A10 · Verdict language is a legal surface.** Banned-word list enforced by test
  (`fake`, `vaporware`, `scam`, `slop`, `lying`, `misrepresented`, `dishonest`). `contradicted`
  requires the specific quoted claim, the observation, and the date. Every audited record carries
  `right_of_reply`. Editorial voice lives in `worth_note`/`what_breaks_first`, never in statuses.
- **A11 · Audit determinism.** All audit timestamps are *input data* (`captured_at`, `checked_at`)
  copied through, never `now()`. `audit_version` bumps when the rubric changes, exactly like
  `scoring_version`. `--check` byte-diffs the new surfaces.
- **A12 · Migration of the existing 165.** One-time, recorded: the 2 previously-deep records
  (AudioNova, Greenlight) enter the audit as `soundness: partial` (no repo corroboration yet); the
  remaining 163 are pool rows. Their `coolness` stays computed — pool rows are still ranked, so the
  promotion queue has an order — but they are absent from the default human view.
- **A13 · Hazard stamp.** For Health/Care, Accessibility and Public-Trust records whose text asserts
  a regulated outcome (diagnosis, screening, medication, triage, compliance sign-off): `hazard:
  {class, team_disclaimed, note}`. Rendered as one stamp + one line; mandatory in agent responses.
- **A14 · Clone economics.** `clone_cost: {estimate: weekend|week|month|multi-week, why,
  assumptions[]}`, marked `derived`. This is the field that turns "cool" into "could I".
- **A15 · Audit the audit.** Three fixtures pin the thresholds: the `Gemini-Box` pair (cross-team
  same-name → `parallel_invention_of`, both kept), the two `Greenlight` captures (same-team
  re-submission → `duplicate_of`, one kept), and `test`/`test` (no evidence → pool, `why_not_promoted:
  placeholder_summary`). A test asserts each outcome; a rubric change must move the fixtures
  deliberately, not accidentally.

---

## 7 · Dissents & open risks (not smoothed over)

- **D1 — Varga, on A7.** "A 25-record ceiling means the catalog stays small for months, and a small
  catalog that claims rigour is worth less than a large one that claims nothing." Held as a live
  risk: mitigation is the promotion queue's visibility (`promotion_queue` MCP tool + UI badge) so the
  gap is legible, not hidden.
- **D2 — Blake, on A6.** "Mandatory fields will get padded." Mitigated by requiring `unknowns` to
  name evidence, and by a test that rejects a mandatory field whose text is ≤40 chars or matches a
  filler pattern — but a motivated parser could still satisfy form over substance. Accepted residual.
- **D3 — Raman, on A4.** "Separating worth from soundness will get averaged by consumers anyway —
  the UI shows two scores and people sum them." Mitigation: no composite is ever emitted; the
  inspector prints `no overall quality score by design` where a user expects one.
- **D4 — Tanabe, on A13.** "One line for a clinical hazard is thin." Overruled for payload reasons,
  retained as the most likely source of downstream harm; revisit if the corpus grows clinical depth.
- **D5 — Farouk, standing.** The pool exposes *ranking* of unaudited rows (`coolness`), which is a
  legibility risk: someone will screenshot a pool row's score as if it were a judgement of merit.
  Pool surfaces carry `provenance: unaudited` on every row and the CSV column `promoted=0`; not
  further solvable in data.
- **Open:** soundness of *frontend-only* projects with no repo (very common) — `artifact_exists`
  falls back to a reachable demo/working app, which flatters throwaway UIs. Next iteration should add
  `demo_responds` as an equal rung rather than a fallback (needs a fetch budget decision).

## 8 · What changed against the first instinct

First instinct was: add a `quality_flag` column, hand-label the 165 rows, keep publishing them all.
The panel's net effect: the flag became a **derived verdict over an evidence ledger**; hand-labelling
became a **promotion queue**; the score stayed **two orthogonal axes with no composite**; the dedup
pass became **merge/annotate with fixtures that pin the thresholds**; and the biggest structural
change — **the catalog now refuses to publish what it cannot support**, which the first draft would
have called a bug because the row count would drop.
