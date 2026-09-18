"""
Ideas Galore — Remix Engine (the reference repo's "stack architect", retargeted)
================================================================================
ADR-13: the collision of two unrelated implementations of the same *move* is
where inspiration actually comes from, so we generate it at build time and ship
it as data — zero runtime cost, cacheable, and readable by agents.

Two producers:
  curated : hand-written pairings by the panel (provenance: editorial) — the
            high-taste set, with real reasoning per pair.
  mined   : for each move, the top-ranked projects that share the move but sit
            in different domains; score = min(coolness) * domain_distance.

Output: web/public/data/remixes.json
Usage:  python3 pipeline/generate_remixes.py [--mined 18]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, Dict, List

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CORPUS = os.path.join(REPO, "pipeline", "corpus.jsonl")
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from taxonomy_hacks import DOMAINS, MOVES  # noqa: E402

# ---------------------------------------------------------------------------
# Curated collisions (editorial). Parents must exist in the corpus or they are
# dropped with a warning, so this file cannot silently rot when the corpus moves.
# ---------------------------------------------------------------------------
CURATED: List[Dict[str, Any]] = [
    {
        "id": "deadline-atc-meets-submission-ledger",
        "parents": ["tower-dq18x2", "proofflow-agent"],
        "title": "A control tower that prices your risk before it spends your deadline",
        "why_these_two": "Tower turned 'deadline anxiety' into an unattended watcher with a phone call. ProofFlow turned 'judging' into a source-cited ledger of build evidence. Put them together and the watcher stops nagging and starts filing proof of what it protected you from.",
        "the_wedge": "Nobody builds an agent that both waits for days and can defend its own decisions afterwards. Judges, reviewers and auditors all want the second half.",
        "starter_stack": ["sqlite-vec or LanceDB for the evidence graph", "a scheduler that sleeps until a condition flips",
                          "one LLM role that writes the ledger entry per state change", "a phone/notify escalation path"],
        "first_48_hours": ["Day 1 morning: define the two tables you refuse to fake — `evidence` and `decision`.",
                           "Day 1 afternoon: build the watcher as a cron that writes rows, no model in the loop yet.",
                           "Day 2 morning: add the cite-every-claim renderer (quote + source link, no prose).",
                           "Day 2 afternoon: demo the phone call, because that is the part people remember."],
        "kill_criteria": ["If the ledger can be updated after the decision without a new row, kill it — you rebuilt a notepad.",
                          "If the watcher needs a human to say 'continue', it is a timer, not an agent."],
        "effort": "hackathon",
    },
    {
        "id": "cost-ladder-meets-agent-memory",
        "parents": ["greenlight-nine-agent-production-crew", "dataaeternum-com"],
        "title": "Agent memory that quotes you a price before it remembers",
        "why_these_two": "Greenlight's real insight was the cost ladder: settle the two-cent decision (a character reference) before the one-dollar decision (a shot). LBrain's insight was that memory needs provenance and survives model swaps. A memory layer that prices its own writes — cheap candidate, expensive commit — is a product, not a feature.",
        "the_wedge": "Everyone persists agent context; nobody tells the user what a memory is going to cost to store, retrieve, or be wrong about.",
        "starter_stack": ["append-only memory log (SQLite + FTS5 is fine)", "vector index for candidates only",
                          "a two-tier write API: propose() then commit()", "per-entry provenance: source URL, model, token cost"],
        "first_48_hours": ["Ship propose/commit with a printed price delta before any embedding work.",
                           "Make the commit path refuse to write without provenance.",
                           "Add the 'this memory changed my answer' diff view.",
                           "Measure first-pass usefulness before and after commits — steal Greenlight's 29%→49% table shape."],
        "kill_criteria": ["If candidates and commits cost the same, the ladder is decoration.",
                          "If you cannot show which memory caused which answer, you built a cache."],
        "effort": "weekend",
    },
    {
        "id": "forensic-triage-meets-voice-first-access",
        "parents": ["ai-image-detector-9ayw71", "medvoice-y87kei"],
        "title": "A verification tool a nurse can use hands-free, with numbers attached",
        "why_these_two": "realityCheCk proved robustness on the axis everyone ignores (post-compression accuracy, reported as AUC across 15 transforms). Medvoice proved that real deployment in care means voice-first and low-literacy design. Detector demos die in the field; a robust detector with a voice UI and an explicit accuracy-under-duress figure is a triage instrument.",
        "the_wedge": "Every AI detector reports clean-input accuracy and every care tool assumes a free pair of hands. Neither assumption survives contact with WhatsApp compression or a busy ward.",
        "starter_stack": ["CLIP-class backbone + a frequency/FFT branch", "a transform battery (resize, crop, re-compress) as an eval harness, not an afterthought",
                          "STT→verdict→TTS loop that never requires typing", "an on-device path for privacy-sensitive capture"],
        "first_48_hours": ["Build the transform battery first; it is 30 lines and it is your entire credibility.",
                           "Report the delta (clean vs degraded) on the results screen, not in a paper.",
                           "Design the answer as one sentence a nurse can read aloud to a patient.",
                           "Then add the model. Only then."],
        "kill_criteria": ["If the accuracy claim drops out when you show the compressed-input number, you have marketing, not a tool.",
                          "If the happy path needs a keyboard, you have excluded your user."],
        "effort": "2 weeks",
    },
    {
        "id": "auto-patch-meets-deterministic-boundary",
        "parents": ["zeroday-ai-autonomous-vulnerability-patching-system", "tidemark-hgom3q"],
        "title": "An agent that fixes code inside a boundary it cannot cross",
        "why_these_two": "ZeroDay ships autonomous PRs; TIDEMARK's line — 'selection, not supply' — is a runtime boundary that stops an agent from ever putting a protected value into a side-effecting tool. Autonomy reviewers will not trust the first without the second, and the second is exactly the thing a patch agent needs.",
        "the_wedge": "Autonomous code changes are blocked by trust, not capability. Give the agent a hard boundary it physically cannot violate and the PR becomes mergeable.",
        "starter_stack": ["static allowlist of protected sinks enforced in the tool wrapper", "AST-level diff generation",
                          "sandbox runner per patch", "PR template that names the boundary and the checks run"],
        "first_48_hours": ["Implement the boundary as a wrapper you cannot import around — not a prompt instruction.",
                           "Patch one vuln class end to end (e.g. path traversal) rather than 12 classes shallowly.",
                           "Fail closed: no test-green patch means no PR.",
                           "Print the invariant in the PR body so a human reviews the guarantee, not the diff, first."],
        "kill_criteria": ["If the model can produce a value that reaches a sink, the boundary is advice.",
                          "If you cannot show a patch that was refused, the gate was never on."],
        "effort": "hackathon",
    },
    {
        "id": "offline-narrator-for-cheap-hardware",
        "parents": ["nua-offline-on-device-lecture-translator", "echovision-3d-0nk1l5"],
        "title": "Offline world-narration for phones nobody can upgrade",
        "why_these_two": "Nua keeps technical terms intact while dubbing lectures fully on-device; EchoVision turns a video stream into 3D binaural audio for navigation. Both are 'the network is not an option' designs. Together they are an assistive narrator for $80 Android phones — the population that accessibility demos usually skip.",
        "the_wedge": "Accessibility AI is prototyped on flagship hardware and shipped to people who do not own it. Constraints in both projects already solved that.",
        "starter_stack": ["quantized detection model (INT8) with a terms-preservation vocabulary",
                          "binaural panning from bounding-box geometry", "a no-cloud install path (APK, not store)",
                          "battery budget: 20-minute continuous use"],
        "first_48_hours": ["Test on the oldest phone in the room before writing a line of model code.",
                           "Fix the vocabulary problem first — mistranslated technical terms are a trust-killer in both domains.",
                           "Ship a walk-and-narrate demo in a stairwell: that is the acceptance test.",
                           "Measure latency, not mAP."],
        "kill_criteria": ["If it needs a server for >10s of operation, it is a demo.",
                          "If it narrates everything, it navigates nothing — one signal per second, maximum."],
        "effort": "2 weeks",
    },
    {
        "id": "self-auditing-knowledge-base",
        "parents": ["continuity-g7bty0", "browsegraph"],
        "title": "A personal graph that re-checks its own edges against the live web",
        "why_these_two": "Continuity's premise is that facts rot silently and a maintainer should approve the fix. BrowseGraph already put a graph index inside the browser. An in-browser knowledge base that audits its own staleness — and proposes edits instead of applying them — is the rare project where the maintenance loop is the feature.",
        "the_wedge": "Personal knowledge tools fail at month three because the notes drift from reality. Nobody re-checks them; everyone knows it.",
        "starter_stack": ["IndexedDB + a local graph (no server)", "a fetch-and-compare worker with per-edge confidence",
                          "an approval queue UI (accept / reject / snooze)", "signed edit history so the audit is yours"],
        "first_48_hours": ["Pick three edge types that genuinely rot (prices, versions, job titles) — do not audit everything.",
                           "Build the approval queue before the checker; the interaction is the product.",
                           "Show 'unchanged since' on every node, so silence is informative.",
                           "Cap the network budget per day and display it."],
        "kill_criteria": ["If it silently rewrites your notes, delete it — that is the failure mode it exists to prevent.",
                          "If more than 5% of edges need review per week, your scope is too wide."],
        "effort": "weekend",
    },
]

DOMAIN_INDEX = {d: i for i, d in enumerate(DOMAINS)}


def domain_distance(a: str, b: str) -> float:
    """Circular distance across the sector ring, normalized to [0,1]."""
    ia, ib = DOMAIN_INDEX.get(a, 0), DOMAIN_INDEX.get(b, 0)
    n = max(len(DOMAIN_INDEX), 1)
    d = abs(ia - ib)
    return round(min(d, n - d) / max(n // 2, 1), 3)


def mine(records: List[Dict[str, Any]], want: int, existing_ids: set) -> List[Dict[str, Any]]:
    by_move: Dict[str, List[Dict[str, Any]]] = {}
    for r in records:
        if not r.get("admitted", True):
            continue
        for m in r.get("moves") or []:
            by_move.setdefault(m, []).append(r)
    used = set()
    mined: List[Dict[str, Any]] = []
    ranked_moves = sorted(by_move.items(),
                          key=lambda kv: -max((r["coolness"] for r in kv[1]), default=0))
    for move, pool in ranked_moves:
        pool = sorted(pool, key=lambda r: -r["coolness"])
        for i, a in enumerate(pool):
            hit = False
            for b in pool[i + 1:]:
                if a["domain"] == b["domain"]:
                    continue
                key = tuple(sorted([a["id"], b["id"]]))
                if key in used or a["id"] in existing_ids or b["id"] in existing_ids:
                    continue
                used.add(key)
                rid = f"{move}::{a['id']}+{b['id']}"
                mined.append({
                    "id": rid, "kind": "mined", "move": move,
                    "parents": [a["id"], b["id"]],
                    "title": f"{move} — {a['domain'].split(',')[0]} × {b['domain'].split(',')[0]}",
                    "why_these_two": (f"Both independently converged on `{move}` in different "
                                      f"sectors. Transfer the mechanism, keep each project's "
                                      f"constraint."),
                    "the_wedge": MOVES[move]["definition"],
                    "reusable_moves": [
                        {"from": a["name"], "steal_this": MOVES[move]["steal_this"]},
                        {"from": b["name"], "steal_this": "port the constraint, not the feature list"},
                    ],
                    "starter_stack": sorted({*a.get("stack", [])[:4], *b.get("stack", [])[:4]})[:8],
                    "domain_distance": domain_distance(a["domain"], b["domain"]),
                    "score": round(min(a["coolness"], b["coolness"]) *
                                   domain_distance(a["domain"], b["domain"]), 4),
                    "effort": "hackathon",
                })
                hit = True
                break
            if hit:
                break
        if len(mined) >= want:
            break
    return sorted(mined, key=lambda m: -m["score"])[:want]


def build(mined_target: int, out_path: str) -> int:
    if not os.path.exists(CORPUS):
        raise SystemExit("corpus missing — run pipeline/ingest_seed.py first")
    records = [json.loads(l) for l in open(CORPUS, encoding="utf-8") if l.strip()]
    by_id = {str(r["id"]): r for r in records}

    recipes: List[Dict[str, Any]] = []
    for c in CURATED:
        missing = [p for p in c["parents"] if p not in by_id]
        if missing:
            print(f"  ! dropping curated remix {c['id']}: unknown parents {missing}")
            continue
        parents = [{
            "id": p, "name": by_id[p]["name"], "url": by_id[p]["url"],
            "domain": by_id[p]["domain"], "moves": by_id[p].get("moves") or [],
            "coolness": by_id[p]["coolness"],
        } for p in c["parents"]]
        shared = sorted(set.intersection(*[set(p["moves"]) for p in parents])) if parents else []
        recipes.append({**c, "kind": "curated", "parents_detail": parents,
                        "shared_moves": shared,
                        "provenance": {"fields": "editorial", "parents": "observed"}})

    curated_ids = {r["parents"][0] for r in recipes} | {r["parents"][1] for r in recipes}
    mined_list = mine(records, mined_target, set())
    mined_list = [m for m in mined_list if not set(m["parents"]) & curated_ids][:mined_target]
    for m in mined_list:
        m["parents_detail"] = [{
            "id": p, "name": by_id[p]["name"], "url": by_id[p]["url"],
            "domain": by_id[p]["domain"], "moves": by_id[p].get("moves") or [],
            "coolness": by_id[p]["coolness"],
        } for p in m["parents"]]

    data = {"recipes": recipes + mined_list,
            "counts": {"curated": len(recipes), "mined": len(mined_list)},
            "note": "Curated collisions are editorial judgement by the panel; mined pairs are "
                    "ranked by min(coolness) x domain distance. Both reference live corpus ids only."}
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(data, f, separators=(",", ":"))
    print(f"🧩 Remixes: {len(recipes)} curated + {len(mined_list)} mined -> {os.path.relpath(out_path, REPO)}")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--mined", type=int, default=18)
    ap.add_argument("--out", default=os.path.join(REPO, "web", "public", "data", "remixes.json"))
    args = ap.parse_args()
    raise SystemExit(build(args.mined, args.out))
