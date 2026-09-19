#!/usr/bin/env python3
"""
audit_projects.py — the promotion gate (docs/AUDIT_PANEL.md ADR-A1..A15)
=======================================================================
Ideas Galore publishes only what it can support. This module turns three kinds of
input into an audit sheet per project, and derives a verdict from the evidence
rather than from anyone's opinion:

  pipeline/raw/deep_captures/*.json   what the project's own Devpost page says
                                      (condensed paraphrase + observed numbers + links;
                                      captured by a human-run fetch, committed so the
                                      build stays offline — ADR-10/A7)
  pipeline/raw/repo_checks.json       what the GitHub API says about the artifact
                                      (produced by repo_verify.py; language mix, size,
                                      test paths, README setup, push date)
  pipeline/raw/audit_notes.json       the panel's editorial judgement — worth, prior
                                      art, what breaks first, clone cost. Labelled
                                      `editorial` everywhere, never implied to be fact.

Outputs `pipeline/audit.jsonl`: one audit sheet per *audited* record. `shard_builder`
then publishes only verdicts in AUDIT_PUBLISH_VERDICTS into the catalog; everything
else stays in the pool with `why_not_promoted` (A1).

Usage:
  python3 pipeline/audit_projects.py                 # audit everything captured
  python3 pipeline/audit_projects.py --report        # + explain each verdict
  python3 pipeline/audit_projects.py --queue 12      # what to audit next, and why
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
import sys
from typing import Any, Dict, List, Optional, Tuple

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from taxonomy_hacks import (  # noqa: E402
    AUDIT_CHECKS, AUDIT_CONTRADICTED_CAP, AUDIT_HARD_FAIL, AUDIT_LOAD_BEARING,
    AUDIT_MANDATORY_FIELDS, AUDIT_MAX_LOAD_BEARING_UNKNOWNS, AUDIT_PUBLISH_VERDICTS,
    AUDIT_VERSION, BANNED_VERDICT_WORDS, DUP_MECHANISM_OVERLAP, DUP_TEXT_OVERLAP,
    HAZARD_CLAIM_RE, HAZARD_DOMAINS, MOVES, detect_moves, jaccard_kin,
)

CORPUS = os.path.join(HERE, "corpus.jsonl")
CAPTURE_DIR = os.path.join(HERE, "raw", "deep_captures")
REPO_CHECKS = os.path.join(HERE, "raw", "repo_checks.json")
NOTES = os.path.join(HERE, "raw", "audit_notes.json")
AUDIT_OUT = os.path.join(HERE, "audit.jsonl")

_LANG_HINTS = {
    "python": ["python", ".py", "fastapi", "flask", "django", "streamlit", "pytorch", "langchain"],
    "typescript": ["typescript", "tsx", "react", "next", "node", "vite"],
    "javascript": ["javascript", "react", "node", "express", "vue"],
    "swift": ["swift", "ios", "xcode"],
    "kotlin": ["kotlin", "android"],
    "dart": ["flutter", "dart"],
    "rust": ["rust", "cargo"],
    "go": ["go", "golang"],
    "java": ["java", "spring", "android"],
    "csharp": [".net", "c#", "wpf", "unity"],
    "cpp": ["c++", "opencv", "onnxruntime"],
    "html": ["html", "css", "tailwind"],
    "shell": ["bash", "shell", "docker", "scripts"],
}


def _load(path: str, default):
    if not os.path.exists(path):
        return default
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def load_captures(dirpath: str = CAPTURE_DIR) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    for path in sorted(glob.glob(os.path.join(dirpath, "*.json"))):
        cap = _load(path, {})
        pid = cap.get("id") or os.path.basename(path)[:-5]
        cap.setdefault("id", pid)
        cap["_file"] = os.path.basename(path)
        out[pid] = cap
    return out


def _repo_for(cap: Dict[str, Any], checks: Dict[str, Any]) -> Tuple[Optional[str], Optional[Dict[str, Any]]]:
    """Only accept a repo the project page itself linked (A14/C5: no inferred ownership)."""
    url = ((cap.get("links") or {}).get("repo") or "").rstrip("/")
    if not url:
        return None, None
    m = re.search(r"github\.com/([^/]+/[^/#?]+)", url)
    if not m:
        return None, None
    full = m.group(1)
    return full, checks.get(full)


def _sections_text(cap: Dict[str, Any]) -> str:
    sec = cap.get("sections") or {}
    return "\n".join(str(sec.get(k) or "") for k in sec).lower()


def run_checks(cap: Dict[str, Any], repo_name: Optional[str], repo: Optional[Dict[str, Any]],
               notes: Dict[str, Any]) -> Tuple[Dict[str, Dict[str, Any]], List[Dict[str, Any]]]:
    """A3: six mechanical checks. Each returns {pass, status, why}; `unverifiable` is an
    honest outcome, not a failure of the project."""
    ev: List[Dict[str, Any]] = []
    checks: Dict[str, Any] = {}
    text = _sections_text(cap)
    claimed = [str(t).lower() for t in (cap.get("built_with") or [])]
    numbers = cap.get("numbers") or []

    def _testable(n: Dict[str, Any]) -> bool:
        """A number counts as checked only when *we* could re-derive it. A capture that
        writes an `arithmetic` line saying 'not falsifiable' must not read as confirmation
        — that is exactly how an audit launders a claim it never verified."""
        if n.get("verifiable") is False:
            return False
        arith = str(n.get("arithmetic") or "").strip()
        return bool(arith) and not re.match(r"(not|unfalsifiable|cannot|no |n/?a)", arith, re.I)

    ok = [n for n in numbers if _testable(n)]
    unfalsifiable = [n for n in numbers
                     if n.get("arithmetic") or n.get("denominator") or n.get("verifiable") is False]
    unfalsifiable = [n for n in unfalsifiable if n not in ok]
    sec = cap.get("sections") or {}

    def emit(name: str, passed: Optional[float], status: str, why: str,
             kind: str, source: str, checked_at: str) -> None:
        checks[name] = {"pass": passed, "status": status, "why": why}
        ev.append({"id": f"{cap['id']}:{name}", "claim": AUDIT_CHECKS[name]["ask"], "status": status,
                   "kind": kind, "source": source, "detail": why, "checked_at": checked_at})

    when = str(cap.get("captured_at") or "")
    rwhen = str((repo or {}).get("checked_at") or when)

    # 1 · artifact_exists
    if repo and repo.get("exists") and (repo.get("size_kb") or 0) > 5:
        emit("artifact_exists", 1.0, "confirmed",
             f"repo {repo_name} exists ({repo.get('size_kb')} KB, {repo.get('language')}), "
             f"last push {repo.get('pushed_at')}", "api", f"https://github.com/{repo_name}", rwhen)
    elif (cap.get("links") or {}).get("demo") or (cap.get("links") or {}).get("video") or (cap.get("links") or {}).get("app_store"):
        links = [v for k, v in (cap.get("links") or {}).items() if v and k != "repo"]
        emit("artifact_exists", 0.5, "supported",
             "no source repo linked, but the page publishes a working artifact: " + ", ".join(links[:3]),
             "page", cap.get("source_url", ""), when)
    else:
        emit("artifact_exists", 0.0, "unverifiable",
             "page links no repository, deployment or video we can resolve", "page",
             cap.get("source_url", ""), when)

    # 2 · stack_consistency
    langs = {str(k).lower() for k in (repo or {}).get("languages") or {}}
    if repo and langs and claimed:
        hits = 0
        matched: List[str] = []
        for c in claimed:
            for lang, hints in _LANG_HINTS.items():
                if any(h in c for h in hints) and (lang in langs or any(h in " ".join(langs) for h in hints)):
                    hits += 1
                    matched.append(c)
                    break
        ratio = hits / max(len(claimed), 1)
        if ratio >= 0.5:
            emit("stack_consistency", 1.0 if ratio >= 0.75 else 0.5,
                 "confirmed" if ratio >= 0.75 else "partial",
                 f"{hits}/{len(claimed)} claimed technologies appear in the repo language mix "
                 f"({', '.join(sorted(langs)[:5])}); matched: {', '.join(matched[:4]) or '—'}",
                 "api", f"https://api.github.com/repos/{repo_name}/languages", rwhen)
        else:
            # not a contradiction of competence — a mismatch worth showing
            emit("stack_consistency", 0.25, "contradicted",
                 f"repo is {', '.join(sorted(langs)[:4])} but the page claims "
                 f"{', '.join(claimed[:6])}; the linked repo may not be the whole build",
                 "api", f"https://api.github.com/repos/{repo_name}/languages", rwhen)
    elif repo and langs:
        emit("stack_consistency", 0.5, "partial",
             f"repo languages {', '.join(sorted(langs)[:5])}; page lists no `Built With` tags to compare",
             "api", f"https://api.github.com/repos/{repo_name}/languages", rwhen)
    else:
        emit("stack_consistency", None, "unverifiable",
             "no repo to cross-check the declared stack against", "page",
             cap.get("source_url", ""), when)

    # 3 · build_is_real
    if repo and repo.get("exists"):
        src = repo.get("source_dirs") or []
        readme = int(repo.get("readme_bytes") or 0)
        setup = bool(repo.get("readme_has_setup"))
        size = int(repo.get("size_kb") or 0)
        substantive = size >= 60 and len(src) >= 1
        if substantive and (setup or readme >= 1500):
            emit("build_is_real", 1.0, "confirmed",
                 f"{size} KB, source dirs {', '.join(src[:4]) or '—'}, README {readme} B"
                 + (" incl. setup steps" if setup else ""), "api",
                 f"https://github.com/{repo_name}", rwhen)
        elif size >= 20 or src:
            emit("build_is_real", 0.5, "partial",
                 f"{size} KB with {len(src)} source director{'y' if len(src) != 1 else 'ies'} — a real "
                 f"start, not a shipped codebase", "api", f"https://github.com/{repo_name}", rwhen)
        else:
            emit("build_is_real", 0.0, "contradicted",
                 f"repo is {size} KB with no source tree; nothing to read", "api",
                 f"https://github.com/{repo_name}", rwhen)
    else:
        emit("build_is_real", None, "unverifiable",
             "no repository published, so the build cannot be read", "page",
             cap.get("source_url", ""), when)

    # 4 · numbers_add_up
    with_denom = [n for n in numbers if (n.get("denominator") or n.get("baseline"))]
    if unfalsifiable and not ok:
        # A headline number nobody can check is a finding about the claim, not about the
        # team's competence, so the wording stays descriptive (A10).
        emit("numbers_add_up", 0.25, "unverifiable",
             f"{len(unfalsifiable)} figure(s) we could not test: "
             + "; ".join(n["claim"] for n in unfalsifiable[:2])
             + " — no published harness, baseline or reproduction command to check against",
             "page", cap.get("source_url", ""), when)
    elif ok:
        emit("numbers_add_up", 1.0, "confirmed",
             "; ".join(f"{n['claim']} (recomputed: {n['arithmetic']})" for n in ok[:2]),
             "page", cap.get("source_url", ""), when)
    elif with_denom:
        emit("numbers_add_up", 0.75, "supported",
             f"{len(with_denom)} metric(s) with a stated denominator: "
             + "; ".join(n["claim"] for n in with_denom[:3]), "page", cap.get("source_url", ""), when)
    elif numbers:
        emit("numbers_add_up", 0.4, "partial",
             f"{len(numbers)} number(s) asserted without a baseline (e.g. {numbers[0].get('claim')!r})",
             "page", cap.get("source_url", ""), when)
    else:
        emit("numbers_add_up", 0.0, "unverifiable",
             "the page states no measurable outcome at all", "page", cap.get("source_url", ""), when)

    # 5 · limits_disclosed
    limits = str(sec.get("challenges") or sec.get("limitations") or "")
    if len(limits) >= 60 and re.search(r"(fail|couldn|could not|limit|bug|crash|struggl|not yet|"
                                       r"only supports|had to|required|balanc|trade-?off|hard|difficult|"
                                       r"never got to|no public|unresolved)", limits.lower()):
        emit("limits_disclosed", 1.0, "confirmed", "the team wrote down what broke while building",
             "page", cap.get("source_url", ""), when)
    elif str(sec.get("what_next") or "").strip():
        emit("limits_disclosed", 0.5, "supported",
             "no limitations section, but 'what's next' implies the open edges", "page",
             cap.get("source_url", ""), when)
    elif len(limits) >= 20:
        emit("limits_disclosed", 0.5, "partial", "a short challenges note exists; too thin to quote",
             "page", cap.get("source_url", ""), when)
    else:
        emit("limits_disclosed", 0.0, "unverifiable",
             "everything is presented as working; nothing to audit", "page",
             cap.get("source_url", ""), when)

    # 6 · test_or_eval_evidence
    tests = repo.get("test_paths") if repo else None
    testing_text = text + " " + str(cap.get("testing") or "").lower()
    benchmark = bool(re.search(r"(accuracy|f1\b|auc|precision|recall|latency|p95|benchmark|ab test|"
                               r"before/after|baseline|first-?pass|success rate|a/b|measured|sample size|"
                               r"seeded .*bias|calibrat)", testing_text, re.I))
    if tests:
        emit("test_or_eval_evidence", 1.0, "confirmed",
             f"test paths in repo: {', '.join(tests[:3])}", "api",
             f"https://api.github.com/repos/{repo_name}/git/trees", rwhen)
    elif benchmark and (with_denom or ok):
        emit("test_or_eval_evidence", 0.75, "supported",
             "a measured evaluation with a stated denominator is described on the page "
             "(an A/B comparison or a logged-outcome harness counts; a bare 'we tested it' does not)",
             "page",
             cap.get("source_url", ""), when)
    elif benchmark:
        emit("test_or_eval_evidence", 0.4, "partial",
             "evaluation language present but no numbers attached", "page",
             cap.get("source_url", ""), when)
    else:
        emit("test_or_eval_evidence", 0.0, "unverifiable",
             "no tests visible and no evaluation described", "api" if repo else "page",
             f"https://github.com/{repo_name}" if repo_name else cap.get("source_url", ""),
             rwhen if repo else when)
    return checks, ev


def build_fields(cap: Dict[str, Any], notes: Dict[str, Any], repo_name: Optional[str],
                 repo: Optional[Dict[str, Any]], checks: Dict[str, Any]) -> Tuple[Dict[str, Any], List[Dict[str, str]]]:
    """A6: fill the 12 mandatory fields from evidence; anything we cannot fill becomes a
    named unknown. Padding is impossible because an unknown must say what would settle it."""
    sec = cap.get("sections") or {}
    fields: Dict[str, Any] = {}
    unknowns: List[Dict[str, str]] = []

    def put(name: str, value: Optional[Any], from_: str, settle: str) -> None:
        text = value.strip() if isinstance(value, str) else value
        if isinstance(text, str) and (len(text) < 40 or re.fullmatch(
                r"(n/?a|none|not stated|tbd|todo|unknown|see the page)", text, re.I)):
            text = None
        if text:
            fields[name] = {"value": text, "provenance": from_}
        else:
            unknowns.append({"field": name, "missing": settle})

    put("what_it_is", cap.get("one_line") or sec.get("what_it_does"), "observed",
        "the page's own summary section is missing or generic; a demo link would settle it")
    put("what_it_does", sec.get("what_it_does") or sec.get("inspiration"), "observed",
        "no step-by-step description of user-visible behaviour on the page")
    put("how_it_works", sec.get("how_we_built_it"), "observed",
        "the 'how we built it' section describes no architecture/data flow; a repo README would settle it")
    put("built_with_verified",
        (", ".join(cap.get("built_with") or [])) or None, "observed",
        "authors published no 'Built With' tags")
    put("data_and_models", cap.get("data_and_models") or sec.get("how_we_built_it"), "observed",
        "which model(s), on what data, and at what cost are not stated anywhere public")
    put("how_they_tested",
        (", ".join(repo.get("test_paths") or []) if repo and repo.get("test_paths") else None) or
        (cap.get("testing") or None) or
        (sec.get("accomplishments") if re.search(r"(test|eval|bench|accuracy|measured)", sec.get("accomplishments", "").lower()) else None),
        "observed", "no test suite in the repo and no evaluation described on the page")
    put("limits_they_disclosed", sec.get("challenges") or sec.get("limitations"), "observed",
        "the team disclosed no limitations; ask on the submission thread")
    nums = cap.get("numbers") or []
    put("numbers_with_arithmetic",
        nums or (cap.get("numbers_note") if isinstance(cap.get("numbers_note"), str) else None) or None,
        "observed", "no measurable outcome is asserted; a benchmark table would settle it")
    put("what_to_steal", notes.get("what_to_steal"), "editorial",
        "panel has not yet written the transferable-move note (audit_notes.json)")
    put("what_breaks_first", notes.get("what_breaks_first"), "editorial",
        "panel has not yet written the first-failure note (audit_notes.json)")
    cc = notes.get("clone_cost")
    if isinstance(cc, dict) and cc.get("estimate"):
        fields["clone_cost"] = {"value": cc, "provenance": "derived",
                                "note": "our estimate with assumptions visible; not a claim about the team"}
    else:
        unknowns.append({"field": "clone_cost",
                         "missing": "no clone-cost estimate recorded; needs a stack + scope read of the repo"})
    pa = notes.get("prior_art")
    if isinstance(pa, list) and pa:
        bad = [p for p in pa if not (p.get("url") or p.get("corpus_id"))]
        if pa and not bad:
            fields["prior_art"] = {"value": pa, "provenance": "editorial",
                                   "note": "each entry resolves to a URL we opened this session or a corpus id"}
        else:
            unknowns.append({"field": "prior_art",
                             "missing": "prior-art entries must carry a URL or corpus id (A5/C5); "
                                         f"{len(bad)} bare assertion(s)"})
    else:
        unknowns.append({"field": "prior_art", "missing": "no named competitor; a search pass would settle it"})
    return fields, unknowns


def derive_verdict(checks: Dict[str, Any], unknowns: List[Dict[str, Any]], fields: Dict[str, Any],
                   contradicted: int) -> Tuple[str, float, float, List[str]]:
    """A3 + A6: the verdict is a function of the ledger, never typed by hand.

    `unverifiable` is not failure: we score over the checks we could actually run and
    publish `rubric_coverage` alongside it, so a record judged on 64% of the rubric can
    never be mistaken for one judged on 100% — and a missing repo costs reach, not
    reputation."""
    w_all = sum(AUDIT_CHECKS[k]["w"] for k in AUDIT_CHECKS)
    resolvable = {k: v for k, v in checks.items() if v.get("pass") is not None}
    w_res = sum(AUDIT_CHECKS[k]["w"] for k in resolvable)
    num = sum(AUDIT_CHECKS[k]["w"] * (v.get("pass") or 0.0) for k, v in resolvable.items())
    coverage = round(w_res / max(w_all, 1e-9), 3)
    score = round(num / max(w_res, 1e-9), 4) if w_res else 0.0
    reasons: List[str] = []
    lb_unknowns = [u for u in unknowns if u["field"] in AUDIT_LOAD_BEARING]
    missing_worth = "what_to_steal" not in fields or "what_breaks_first" not in fields

    af = checks.get("artifact_exists") or {}
    hard_cap = AUDIT_HARD_FAIL.get("artifact_exists")
    if af.get("pass") == 0.0 and hard_cap:
        reasons.append(f"artifact_exists failed → capped at '{hard_cap}' (A3)")
        return hard_cap, score, coverage, reasons
    if contradicted >= AUDIT_CONTRADICTED_CAP:
        reasons.append(f"{contradicted} load-bearing claims contradicted by evidence → unsound")
        return "unsound", score, coverage, reasons
    if len(lb_unknowns) > AUDIT_MAX_LOAD_BEARING_UNKNOWNS:
        reasons.append(f"{len(lb_unknowns)} load-bearing fields unresolvable (> "
                       f"{AUDIT_MAX_LOAD_BEARING_UNKNOWNS}) → thin (A6)")
        return "thin", score, coverage, reasons
    if missing_worth:
        reasons.append("panel judgement fields (what_to_steal / what_breaks_first) not yet written → thin")
        return "thin", score, coverage, reasons
    if score >= 0.70 and not unknowns and coverage >= 0.80:
        reasons.append(f"soundness {score:.2f}, zero unknowns, {int(coverage*100)}% of the rubric was "
                       f"checkable → strong")
        return "strong", score, coverage, reasons
    if score >= 0.70 and not unknowns:
        reasons.append(f"reads strong, but only {int(coverage*100)}% of the rubric was checkable (no "
                       f"public artifact to read) → caveats, not strong")
        return "sound-with-caveats", score, coverage, reasons
    if score >= 0.45:
        reasons.append(f"soundness {score:.2f} over {int(coverage*100)}% of the rubric; "
                       f"{len(unknowns)} named unknown(s) remain → publishable with caveats")
        return "sound-with-caveats", score, coverage, reasons
    if score >= 0.25:
        reasons.append(f"soundness {score:.2f} is too low to certify; stays in the pool")
        return "thin", score, coverage, reasons
    reasons.append(f"soundness {score:.2f}: pitch with nothing behind it")
    return "unsound", score, coverage, reasons


def hazard_for(rec: Dict[str, Any], cap: Dict[str, Any], notes: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """A13: one stamp, one line, mandatory for agents."""
    dom = rec.get("domain")
    cls = HAZARD_DOMAINS.get(dom)
    text = _sections_text(cap) + " " + (rec.get("summary") or "").lower()
    if not cls and not re.search(HAZARD_CLAIM_RE, text, re.I):
        return None
    if not re.search(HAZARD_CLAIM_RE, text, re.I):
        return None
    disclaimed = bool(re.search(r"(not a medical device|not for (medical )?diagnos|demo only|"
                                r"proof of concept|educational purposes|no clinical|"
                                r"not a substitute for)", text))
    return {
        "class": cls or "regulated-claim",
        "team_disclaimed": disclaimed,
        "note": str((notes.get("hazard_note") or
                     "Regulated-outcome language (screening/diagnosis/compliance) with no evidence of "
                     "clinical validation or disclaimers in the captured page.")),
    }


def numeric_fingerprint(cap: Dict[str, Any]) -> List[str]:
    """Distinctive percentages and money figures from the authored text. Teams re-submit a
    product to a second hackathon and rewrite the prose, but they do not independently
    invent the same '29% → 49%' A/B result or the same '$0.02 / $1 / $20' ladder — so the
    numbers are the identity, and a name collision between two unrelated teams is not."""
    blob = " ".join([str(cap.get("one_line") or "")]
                    + [str(v) for v in (cap.get("sections") or {}).values()]
                    + [str(n.get("claim")) for n in (cap.get("numbers") or [])])
    found = re.findall(r"\$\s?\d[\d,]*(?:\.\d+)?(?:[km]?)?|\d+(?:\.\d+)?\s?%|\d+(?:\.\d{1,2})\s?(?:ms|mb|s)\b", blob, re.I)
    norm = {re.sub(r"\s+", "", f).lower().replace(",", "") for f in found}
    return sorted(x for x in norm if len(x) >= 3)


def similarity_verdicts(sheets: List[Dict[str, Any]], recs: Dict[str, Dict[str, Any]]) -> List[str]:
    """A5: merge true duplicates; cross-link parallel invention (it is signal, not dirt)."""
    actions: List[str] = []
    for i in range(len(sheets)):
        for j in range(i + 1, len(sheets)):
            a, b = sheets[i], sheets[j]
            ra, rb = recs.get(a["id"], {}), recs.get(b["id"], {})
            ta = _sections_text({"sections": a.get("_sections")}) or (ra.get("summary") or "").lower()
            tb = _sections_text({"sections": b.get("_sections")}) or (rb.get("summary") or "").lower()
            na, nb = a.get("name", "").strip().lower(), b.get("name", "").strip().lower()
            same_name = na == nb
            # "Greenlight — Nine-Agent Production Crew" vs "Greenlight — Screenplay to Film":
            # same leading product token, same event → a resubmission, not two teams converging.
            fa = set(a.get("_numbers") or []); fb = set(b.get("_numbers") or [])
            num_shared = len(fa & fb)
            numjac = num_shared / max(1, len(fa | fb))
            first = na.split(" ")[0].strip("—-:")
            same_word = first == nb.split(" ")[0].strip("—-:") and len(first) > 4
            same_event = (recs.get(a["id"], {}).get("event_key") == recs.get(b["id"], {}).get("event_key"))
            # Prose overlap alone cannot prove a resubmission (each event wants its own
            # write-up), so the strong route is shared *numbers*: a 45-page script does not
            # independently produce "29% → 49%" and "$0.02 / $1 / $20" twice. A team re-
            # submitting across two hackathons is a duplicate for our purposes even though
            # the events differ; two teams colliding on a generic name is not.
            fingerprint = (same_word and num_shared >= 3)
            same_product = same_word and (same_event or fingerprint)
            tok_a = set(re.findall(r"[a-z]{4,}", ta)) | set(a.get("moves") or [])
            tok_b = set(re.findall(r"[a-z]{4,}", tb)) | set(b.get("moves") or [])
            overlap = len(tok_a & tok_b) / max(1, len(tok_a | tok_b))
            if (same_name and overlap >= DUP_TEXT_OVERLAP) or (same_product and overlap >= DUP_MECHANISM_OVERLAP) \
                    or fingerprint:
                keep, drop = ((a, b) if a["soundness_score"] >= b["soundness_score"] else (b, a))
                drop["duplicate_of"] = keep["id"]
                drop["verdict"] = "duplicate"
                drop["verdict_reasons"].append(
                    f"resubmission of the same product — name match {same_name}, shared mechanism/text "
                    f"overlap {overlap:.2f}, shared numeric fingerprints {sorted(fa & fb)[:4]} "
                    f"({numjac:.2f} jaccard); merged into the better-evidenced copy (A5)")
                actions.append(f"duplicate: {drop['id']} → {keep['id']}")
            elif overlap >= DUP_MECHANISM_OVERLAP and (ra.get("domain") == rb.get("domain")):
                a["parallel_invention_of"] = b["id"]
                b["parallel_invention_of"] = a["id"]
                actions.append(f"parallel invention kept + cross-linked: {a['id']} ↔ {b['id']}")
    return actions


def audit(corpus_path: str = CORPUS, out_path: str = AUDIT_OUT, report: bool = False
          ) -> Tuple[List[Dict[str, Any]], List[str]]:
    recs = {}
    for line in open(corpus_path, encoding="utf-8"):
        r = json.loads(line)
        recs[r["id"]] = r
    caps = load_captures()
    repos = _load(REPO_CHECKS, {})
    notes_all = _load(NOTES, {})

    sheets: List[Dict[str, Any]] = []
    for pid, cap in caps.items():
        rec = recs.get(pid)
        if rec is None:
            print(f"  ⚠ capture {cap.get('_file')} has no corpus record {pid!r} — skipped")
            continue
        notes = notes_all.get(pid) or {}
        if isinstance(notes, str):
            notes = {"note": notes}
        repo_name, repo = _repo_for(cap, repos)
        checks, evidence = run_checks(cap, repo_name, repo, notes)
        fields, unknowns = build_fields(cap, notes, repo_name, repo, checks)
        contradicted = sum(1 for e in evidence if e["status"] == "contradicted")
        verdict, score, coverage, reasons = derive_verdict(checks, unknowns, fields, contradicted)
        moves = rec.get("moves") or list(detect_moves(" ".join(
            str(v) for v in (cap.get("sections") or {}).values())))[:4]
        sheet = {
            "id": pid,
            "name": rec.get("name"),
            "audit_version": AUDIT_VERSION,
            "audited_at": str(cap.get("captured_at") or ""),
            "source_url": cap.get("source_url") or rec.get("url"),
            "verdict": verdict,
            "publishable": verdict in AUDIT_PUBLISH_VERDICTS,
            "soundness_score": score,
            "rubric_coverage": coverage,
            "soundness": ("verified" if score >= 0.7 else "partial" if score >= 0.45
                          else "weak" if score >= 0.25 else "unverified"),
            "checks": checks,
            "evidence": evidence,
            "worth": notes.get("worth") if notes.get("worth") in ("breakthrough", "strong", "niche", "tired") else None,
            "worth_note": notes.get("worth_note"),
            "fields": fields,
            "unknowns": unknowns,
            "moves": moves,
            "repo": ({"full_name": repo_name, "url": f"https://github.com/{repo_name}",
                      "language": (repo or {}).get("language"), "size_kb": (repo or {}).get("size_kb"),
                      "pushed_at": (repo or {}).get("pushed_at"), "stars": (repo or {}).get("stars"),
                      "readme_bytes": (repo or {}).get("readme_bytes"),
                      "test_paths": (repo or {}).get("test_paths"),
                      "checked_at": (repo or {}).get("checked_at")} if repo_name else None),
            "hazard": hazard_for(rec, cap, notes),
            "likes": cap.get("likes", rec.get("likes")),
            "award": cap.get("award") or rec.get("award"),
            "built_with": cap.get("built_with") or [],
            "verdict_reasons": reasons,
            "right_of_reply": "https://github.com/knarayanareddy/Ideasgalore/issues/new?labels=audit-recheck",
            "provenance": {"fields": "observed", "worth": "editorial", "clone_cost": "derived",
                           "checks": "derived", "evidence": "observed",
                           "verdict": "derived"},
        }
        if repo_name and not repo:
            sheet["unknowns"].append({"field": "repo_verification",
                                      "missing": f"{repo_name} is linked but not yet verified via "
                                                 f"`repo_verify.py`; run it to settle stack/build checks"})
        sheet["_sections"] = cap.get("sections") or {}   # internal, stripped before write
        sheet["_numbers"] = numeric_fingerprint(cap)
        sheets.append(sheet)

    actions = similarity_verdicts(sheets, recs)
    # `publishable` was decided before the similarity pass ran. A record merged into a
    # duplicate must stop being publishable — otherwise the shard_builder gate (rightly)
    # fails for shipping a duplicate.
    for s in sheets:
        s["publishable"] = s["verdict"] in AUDIT_PUBLISH_VERDICTS
        # A reader of the pool needs the *reason*, not the label: verdict_reasons are the
        # derivation trace, unknowns say what to go and find, hazard says why it is capped.
        if not s["publishable"]:
            why = list(s.get("verdict_reasons") or [])
            why += [f"unknown: {u.get('field')} — {u.get('missing') or 'not filed'}"
                    for u in (s.get("unknowns") or [])[:3]]
            hz = s.get("hazard") or {}
            if hz.get("class"):
                why.append(f"hazard: {hz['class']}"
                           + ("" if hz.get("team_disclaimed") else " (no team disclaimer found)"))
            if s.get("duplicate_of"):
                why.append(f"merged into {s['duplicate_of']} — same submission, richer twin published")
            s["why_not_promoted"] = [w for w in dict.fromkeys(why) if w]
        s.pop("_sections", None)
        s.pop("_numbers", None)
    with open(out_path, "w", encoding="utf-8") as fh:
        for s in sorted(sheets, key=lambda x: x["id"]):
            fh.write(json.dumps(s, ensure_ascii=False, sort_keys=True) + "\n")

    pub = [s for s in sheets if s["publishable"]]
    print(f"🔎 audited {len(sheets)} record(s) -> {os.path.relpath(out_path, HERE)}")
    print(f"   published (verdict in {AUDIT_PUBLISH_VERDICTS}): {len(pub)}   "
          f"held to pool: {len(sheets) - len(pub)}")
    for s in sorted(sheets, key=lambda x: (-x["soundness_score"], x["id"])):
        flag = "✅" if s["publishable"] else "⏸ "
        mark = f"{s['verdict']:>17}"
        print(f"   {flag} {s['name'][:30]:30} {mark} sound={s['soundness_score']:.2f} "
              f"worth={s['worth'] or '—':12} unk={len(s['unknowns'])}"
              + (f" dup→{s['duplicate_of'][:18]}" if s.get("duplicate_of") else ""))
        if report:
            for k, v in s["checks"].items():
                print(f"        {k:22} {str(v['pass']):>5} {v['status']:13} {v['why'][:78]}")
            for u in s["unknowns"]:
                print(f"        unknown · {u['field']:20} {u['missing'][:76]}")
            for r_ in s["verdict_reasons"]:
                print(f"        why      · {r_[:96]}")
    for a in actions:
        print(f"   similarity · {a}")
    def _banned_in(text: str) -> List[str]:
        low = str(text or "").lower()
        # word-boundary, stem-tolerant: "implied" must not trip "lied" (the first pass
        # flagged AudioNova for exactly that).
        return [w for w in BANNED_VERDICT_WORDS if re.search(r"\b" + w + r"\w*\b", low)]

    banned = [w for s in sheets for k in ("worth_note",) for w in _banned_in(s.get(k))]
    if banned:
        print(f"   ⚠ banned words in editorial text: {sorted(set(banned))}")
    return sheets, actions


def queue(pool: List[Dict[str, Any]], audited_ids: set, n: int, out_dir: str) -> List[Dict[str, Any]]:
    """A7/D1: the gap is legible — rank what *should* be audited next, with the reason."""
    from collections import Counter
    need = Counter(r.get("domain") for r in pool if r.get("admitted", True))
    out = []
    for r in pool:
        if not r.get("admitted", True) or r["id"] in audited_ids:
            continue
        sec_need = 1.0 / (1.0 + need.get(r.get("domain"), 0) / max(need.values(), default=1))
        marketing = len(r.get("summary") or "") > 120 and not re.search(r"\d", r.get("summary") or "")
        ambig = 0.5 if any((r.get("name", "").lower().startswith(p) for p in ("gemini-box", "neuroguard",
                              "greenlight", "medvoice", "aura", "nova"))) else 0.0
        gain = (0.35 * r.get("coolness", 0) + 0.25 * r.get("specificity", 0)
                + 0.20 * sec_need + 0.20 * (0.6 if marketing else 0.0) + ambig)
        out.append({"id": r["id"], "name": r.get("name"), "domain": r.get("domain"),
                    "coolness": round(r.get("coolness", 0), 3), "expected_gain": round(gain, 4),
                    "why": (f"sector {r.get('domain','?').split(',')[0]} has {need.get(r.get('domain'),0)} rows and no audit"
                            if sec_need > 0.5 else "mechanism-rich hook; depth likely to convert"),
                    "would_settle_it": ["project page capture", "repo link check"]})
    out.sort(key=lambda x: -x["expected_gain"])
    sel = out[:n]
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, "data", "promotion-queue.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump({"audit_version": AUDIT_VERSION, "pool_size": len(out), "queued": len(sel),
                   "note": "Ranking of unaudited candidates by expected information gain (ADR-A7). "
                           "Nothing here has been verified; the order is only 'what would teach us most'.",
                   "candidates": sel}, fh, indent=1)
    print(f"📋 promotion queue: top {len(sel)} of {len(out)} candidates -> {os.path.relpath(path, os.path.dirname(HERE))}")
    for c in sel:
        print(f"   {c['expected_gain']:.3f}  {c['name'][:30]:30} {c['domain'][:22]:22} {c['why'][:44]}")
    return sel


def main() -> int:
    ap = argparse.ArgumentParser(description="Evidence-gated audit + promotion gate")
    ap.add_argument("--corpus", default=CORPUS)
    ap.add_argument("--out", default=AUDIT_OUT)
    ap.add_argument("--report", action="store_true", help="print per-check and per-unknown detail")
    ap.add_argument("--queue", type=int, default=0, help="also emit the top-N next audit targets")
    ap.add_argument("--web-out", default=os.path.join(os.path.dirname(HERE), "web", "public"))
    args = ap.parse_args()
    sheets, _ = audit(args.corpus, args.out, args.report)
    if args.queue:
        pool = [json.loads(l) for l in open(args.corpus, encoding="utf-8")]
        queue(pool, {s["id"] for s in sheets}, args.queue, args.web_out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
