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
  pipeline/raw/audit_notes/{id}.json  the panel's editorial judgement — worth, prior
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
    AUDIT_LITE_FIELDS, AUDIT_LITE_FORBIDDEN_WORTH, AUDIT_LITE_VERDICT,
    AUDIT_MANDATORY_FIELDS, AUDIT_MAX_LOAD_BEARING_UNKNOWNS, AUDIT_PUBLISH_VERDICTS,
    AUDIT_VERSION, BANNED_VERDICT_WORDS, DUP_MECHANISM_OVERLAP,
    DUP_TEXT_OVERLAP, HAZARD_CLAIM_RE, HAZARD_DISCLAIM_RE, HAZARD_DOMAINS, MOVES,
    detect_moves, jaccard_kin,
)

CORPUS = os.path.join(HERE, "corpus.jsonl")
CAPTURE_DIR = os.path.join(HERE, "raw", "deep_captures")
REPO_CHECKS = os.path.join(HERE, "raw", "repo_checks.json")
NOTES = os.path.join(HERE, "raw", "audit_notes.json")
# ADR-P4: one note file per record, so a parallel worker can own an id without touching a shared file.
# The legacy dict is merged first and this directory wins; the legacy file stays readable (emptied by
# migration, never deleted) so an older checkout still builds.
NOTES_DIR = os.path.join(HERE, "raw", "audit_notes")
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


def lint_refusals() -> Dict[str, List[str]]:
    """Ids `pipeline/capture_lint.py` refused (ADR-P1), read from its per-record ledger.

    The audit skips them for the same reason ingest does: a capture the gate called incomplete is not
    evidence, and scoring it anyway would publish a verdict about the *worker's* read while reading like
    a judgement about the project. The record stays in the pool, labelled `incomplete capture`.
    """
    out: Dict[str, List[str]] = {}
    dirpath = os.path.join(HERE, "raw", "lint_rejects")
    if os.path.isdir(dirpath):
        for fname in sorted(os.listdir(dirpath)):
            if fname.endswith(".json"):
                blob = _load(os.path.join(dirpath, fname), {}) or {}
                out[fname[:-5]] = list(blob.get("rules") or [])
    return out


def load_captures(dirpath: str = CAPTURE_DIR,
                  refusals: Optional[Dict[str, List[str]]] = None) -> Dict[str, Dict[str, Any]]:
    refused = refusals if refusals is not None else lint_refusals()
    out: Dict[str, Dict[str, Any]] = {}
    for path in sorted(glob.glob(os.path.join(dirpath, "*.json"))):
        cap = _load(path, {})
        pid = cap.get("id") or os.path.basename(path)[:-5]
        if pid in refused:
            continue
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


_NEG_CUE = re.compile(r"\b(no|not|never|none|nothing|without|absent|lacks?|missing|"
                      r"unpublished|undocumented|unsaid|omitted|does ?n.t|didn?t|zero|yet|"
                      # A comparative denial is still a denial: "a harness discipline is
                      # described rather than measured" contains the word "measured" only to
                      # say it does not apply, and a lookback that stops at the usual negations
                      # reads it as a benchmark.
                      r"rather than|instead of|allegedly|purportedly)\b", re.I)
# Deliberately excludes the bare word "baseline": in this corpus a "personal baseline" is
# an architecture choice, not an evaluation. A comparison needs comparator words.
_BENCH_RE = re.compile(r"(accuracy|f1\b|auc|precision|recall|latency|p95|benchmark|ab test|"
                       r"before/after|first-?pass|success rate|a/b|measured|sample size|"
                       r"seeded .*bias|calibrat|versus|vs\.\s|compared to|improvement over)", re.I)
# Two kinds of measurement a page can cite, and only one of them answers this rubric's
# question. A before/after load time says the team tuned the product; accuracy, precision,
# recall or a held-out set say the team checked what the product *produces*. Treating the
# first as evidence of an eval is how a fast-but-unverified system buys a soundness tier.
# The 0.75 tier asks for a *measured evaluation*, so the cue has to name a quality metric.
# `measured`, `before/after` and `latency` sit in `_BENCH_RE` because that is how honest pages
# talk about tuning, and a denial can be written entirely in those words. A page reporting a
# load-time improvement plus a third-party score it never names has told a reader something
# real - just nothing about whether its output was checked. So the top tier requires a cue from
# this list, and everything else falls through to the denominator tier, which is worded to
# describe exactly that: a figure with no method behind it.
# (A page naming a benchmark with no number at all still lands lower down, at 0.4.)
_QUALITY_BENCH_RE = re.compile(r"(accuracy|precision|recall|f1\b|auc|success rate|error rate|"
                               r"benchmark|held-?out|eval(?:uation)? set|test set|sample size|"
                               r"ground truth|inter-?rater|calibrat|improvement over|compared to|"
                               r"versus|vs\.\s)", re.I)
_HARNESS_RE = re.compile(r"(fixture|test suite|unit tests?|integration test|regression|"
                         r"simulation matrix|ci\b|workflow|github actions|cypress|jest|pytest)", re.I)
_CAPABILITY_RE = re.compile(r"(accuracy|latency|hallucinat|false (positive|negative)|"
                            r"unsupported|edge case|cannot|can not|only works|limitation|privacy|retention|"
                            r"offline|degrade|bias|drift|error rate|not measured|crash|fails?|"
                            # `block(s|ed)?` used to be in this list and matched every record
                            # whose challenges section mentioned a config block. Blocking is a
                            # feature and a JSON block is a noun; neither is a limitation.
                            r"abuse|hard-?cap|rate[- ]limit|escape hatch|not supported|"
                            r"unavailable|prone|vulnerable|silent(ly)? (fail|drop)|"
                            # A page can admit a limit without writing the word "limitation":
                            # naming the limits of its own data, or a coverage hole, is the
                            # same disclosure in a different tense, and the tier has to read
                            # it. `limits?\b` is whole-word so "rate limit" and "limitations"
                            # keep matching the way they always did.
                            r"limits?\b|(coverage|index|catalog) (gap|gaps|hole|holes)|"
                            r"does not cover|out of coverage)", re.I)
# A sentence about compiling, pushing or surviving a night of coding describes the *build*,
# not the product's limits. Only product-shaped sentences count toward limits_disclosed.
# No "dashboard": in this corpus that word names a UI surface, not a measurement loop.
# A sentence saying a *platform* supplies analytics is a stack line, not a measurement practice.
_MEASURE_CAPABILITY_RE = re.compile(r"(provided by|features? provided|out of the box|built[- ]in|"
                                    r"(?:firebase|google cloud|the platform)[^.]{0,26}provid)", re.I)
_MEASURE_RE = re.compile(r"(posthog|analytics|funnel|instrumented|telemetry|logged|"
                         r"a/b test|experiment|user study|usability test)", re.I)
_PROCESS_RE = re.compile(r"(compil|dependency|runner|push|commit|merge|deploy|phone|mobile|"
                         r"screen|hours|night|deadline|token|licence|disqualif)", re.I)


def _affirmative(rx: re.Pattern, text: str, lookback: int = 80) -> List[str]:
    """Keyword hits that are not inside a negation.

    A capture writes both kinds of sentence — 'we ran a regression suite' and 'no test
    suite is described' — and they contain the same nouns. Reading the noun without the
    polarity is how an audit lauds a project for admitting it has no evidence, so every
    keyword here is checked against the clause in front of it.
    """
    hits: List[str] = []
    for m in rx.finditer(text):
        if _NEG_CUE.search(text[max(0, m.start() - lookback):m.start()]):
            continue
        hits.append(m.group(0))
    return hits


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
        # "structural" marks a feature a reader can count in the product (ten styles,
        # twelve scenarios). Treating that as a recomputed figure would let a feature list
        # vouch for an accuracy claim, so it goes to the `checkable` tier instead.
        return bool(arith) and not re.match(
            r"(not|unfalsifiable|cannot|no |n/?a|structural)", arith, re.I)

    ok = [n for n in numbers if _testable(n)]
    # A structural figure ("10 styles", "three free renders") is checkable by opening the
    # product, which is not the same as a performance figure we re-derived. Counting the
    # first as the second would let a feature list vouch for an accuracy claim.
    # "structural:" means *a reader can look*; it does not survive the team's own
    # verdict that the figure is not falsifiable, and counting a disclaimed number as
    # checkable would let a page buy credit by describing its gap in the right tense.
    checkable = [n for n in numbers if n not in ok and n.get("verifiable") is not False
                 and re.match(r"structural", str(n.get("arithmetic") or ""), re.I)]
    unfalsifiable = [n for n in numbers
                     if n.get("arithmetic") or n.get("denominator") or n.get("verifiable") is False]
    # A recomputation that *disagrees* with the page is a finding, not a confirmation, and
    # the capture has to say so out loud (`reconciles: false`): reading polarity back out of
    # "the walkthrough enumerates seven, the cost narrative says six" is precisely the
    # judgement a keyword check cannot be trusted with. Continuity's stage count landed in the
    # top tier before this, because we had in fact done the arithmetic — on the wrong side of it.
    mismatch = [n for n in ok if n.get("reconciles") is False]
    ok = [n for n in ok if n.get("reconciles") is not False]
    load_bearing = [n for n in mismatch if n.get("load_bearing")]
    unfalsifiable = [n for n in unfalsifiable
                     if n not in ok and n not in checkable and n not in mismatch]
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
    elif (cap.get("links") or {}).get("demo") or (cap.get("links") or {}).get("app_store"):
        # A deployment anyone can open is the strongest artifact a hackathon page offers:
        # the reader can check it without us. We could not reach it from the build
        # environment, so it is `supported`, not `confirmed`.
        links = [v for k, v in (cap.get("links") or {}).items() if v and k != "repo"]
        emit("artifact_exists", 0.75, "supported",
             "no source repo linked, but the product is published at a live address a reader "
             "can open: " + ", ".join(links[:3]),
             "page", cap.get("source_url", ""), when)
    elif (cap.get("links") or {}).get("video"):
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
    # A denominator that says "unstated" is a denial wearing the field's clothes. Only a
    # figure with a real, non-negated denominator (or one we recomputed) can stand for
    # "this was measured".
    def _stated(n: Dict[str, Any]) -> bool:
        for key in ("denominator", "baseline"):
            v = str(n.get(key) or "").strip()
            if v and not re.match(r"(un(stated|known|available)?|no[t]?|n/?a|unknown|missing|absent)",
                                  v, re.I):
                return True
        return False

    measured = [n for n in with_denom if n not in checkable and _stated(n)]
    if load_bearing:
        emit("numbers_add_up", 0.0, "contradicted",
             "the figure this record's case rests on does not reconcile: "
             + "; ".join(f"{n['claim']} — {n['arithmetic']}" for n in load_bearing[:2]),
             "page", cap.get("source_url", ""), when)
    elif mismatch:
        emit("numbers_add_up", 0.5, "partial",
             f"{len(mismatch)} figure(s) we re-derived do not match the page"
             + (f" ({len(ok)} did reconcile)" if ok else "") + ": "
             + "; ".join(f"{n['claim']} — {n['arithmetic']}" for n in mismatch[:2]),
             "page", cap.get("source_url", ""), when)
    elif ok and unfalsifiable:
        # `confirmed` has to mean the record's numbers hold up, not that one of them does while the one
        # the pitch rests on cannot be tested at all. The first version of this ladder let a listing
        # figure reconcile its way past an unfalsifiable headline: zeroday-ai's "webhook to tested pull
        # request in under 30 seconds" has no run count, no repository size and no defined endpoints, and
        # its "2 likes" (which does reproduce, against two named likers) was lifting the check to 1.0
        # `confirmed`. A reconciling figure and an untestable claim are both findings, so both are said.
        emit("numbers_add_up", 0.5, "partial",
             f"{len(ok)} figure(s) re-derived and reconcile ({'; '.join(n['claim'] for n in ok[:2])}), "
             f"but {len(unfalsifiable)} headline figure(s) carry no testable denominator: "
             + "; ".join(n["claim"] for n in unfalsifiable[:2]),
             "page", cap.get("source_url", ""), when)
    elif ok:
        emit("numbers_add_up", 1.0, "confirmed",
             "; ".join(f"{n['claim']} (recomputed: {n['arithmetic']})" for n in ok[:2]),
             "page", cap.get("source_url", ""), when)
    elif checkable and unfalsifiable:
        # Some of the arithmetic is checkable and the headline is not; that is a different
        # finding from "nothing here is testable", and merging the two would let a feature
        # list launder an unmeasured claim (or hide a measured one).
        emit("numbers_add_up", 0.5, "partial",
             f"{len(checkable)} figure(s) a reader can check against the product "
             f"({'; '.join(n_['claim'] for n_ in checkable[:2])}), but "
             f"{len(unfalsifiable)} headline figure(s) carry no testable denominator: "
             + "; ".join(n_["claim"] for n_ in unfalsifiable[:2]),
             "page", cap.get("source_url", ""), when)
    elif checkable:
        emit("numbers_add_up", 0.6, "supported",
             f"{len(checkable)} figure(s) stated as structural facts checkable in the "
             f"product ({'; '.join(n_['claim'] for n_ in checkable[:3])}); no outcome metric "
             f"was published, so nothing was re-derived",
             "page", cap.get("source_url", ""), when)
    elif unfalsifiable and not ok:
        # A headline number nobody can check is a finding about the claim, not about the
        # team's competence, so the wording stays descriptive (A10).
        emit("numbers_add_up", 0.25, "unverifiable",
             f"{len(unfalsifiable)} figure(s) we could not test: "
             + "; ".join(n["claim"] for n in unfalsifiable[:2])
             + " — no published harness, baseline or reproduction command to check against",
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
    effort = re.search(r"(couldn|could not|had to|required|balanc|trade-?off|hard|difficult|"
                       r"never got to|struggl)", limits.lower())
    capability = [c for c in _affirmative(_CAPABILITY_RE, limits.lower())
                  if not _PROCESS_RE.search(
                      re.split(r"(?<=[.;!?])", limits.lower() or " ")[0:0] or "")]
    # sentence-scoped: a capability word sitting in a build-process sentence is not a
    # disclosure about the system
    _sentences = re.split(r"(?<=[.!?])\s+", limits or "")
    capability = [c for sent in _sentences
                  for c in _affirmative(_CAPABILITY_RE, sent.lower())
                  if not _PROCESS_RE.search(sent)]
    capability = list(dict.fromkeys(capability))
    if len(limits) >= 60 and capability:
        # Two different disclosures land on this tier and the `why` has to tell them apart:
        # a capability admission ("it cannot price a car we do not cover") and a failure-mode
        # admission ("the music API answers 200 with a null body"). Naming a failure the team
        # watched in production is evidence they stated where it fails, not that they wrote a
        # capability list, and the check's sentence should not overclaim which one it found.
        _cannot = [c for c in capability if re.search(
            r"cannot|can not|only works|limitation|limits?\b|not supported|unsupported|"
            r"unavailable|coverage gap|does not cover|out of coverage|rate[- ]limit|hard-?cap|"
            r"prone|vulnerable|escape hatch|privacy|retention|offline|not measured", c, re.I)]
        lead = ("the team named what the system itself cannot do" if _cannot else
                "the team stated where the system fails, in production terms")
        emit("limits_disclosed", 1.0, "confirmed",
             lead + " (" + ", ".join(sorted(set(capability))[:3]) + ")",
             "page", cap.get("source_url", ""), when)
    elif len(limits) >= 60 and effort:
        # Honest about the build, silent about the product: worth credit, not a
        # disclosure. "We coded this on a phone all night" tells a builder nothing that
        # will save them when the thing is live.
        emit("limits_disclosed", 0.6, "supported",
             "the team described how hard the build was, but not a limitation of the "
             "system itself — no accuracy, coverage, privacy or failure-mode statement",
             "page", cap.get("source_url", ""), when)
    elif len(limits) >= 60:
        # An operating-constraint disclosure is honest in a different register: what costs
        # money, what does not scale, what had to be recorded as a fixture to be affordable at
        # all. Credit it, name its kind, and stop calling the section missing when the check is
        # quoting from it - Continuity's why string did exactly that.
        costly = bool(re.search(r"(cost|money|price|expensive|afford|budget|billing)", limits.lower()))
        tail = ("; the future-work section implies the remaining open edges"
                if str(sec.get("what_next") or "").strip() else "")
        emit("limits_disclosed", 0.5, "supported",
             "the challenges section discloses operating constraints"
             + (" (what the pipeline costs to run and to iterate on)" if costly else "")
             + ", but no accuracy, coverage or failure-mode limit" + tail, "page",
             cap.get("source_url", ""), when)
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
    # `testing` is the audited field for this question. Scanning the whole page instead
    # let a section that says "compares against a personal baseline" outvote the capture's
    # own sentence "no test suite, evaluation set, or validation is described" — the
    # denial was scored as evidence. Fall back to page text only when no field was filed.
    testing_field = str(cap.get("testing") or "").strip()
    testing_text = (testing_field or text).lower()
    # A comparator word in *prose* is not a measured comparison: "the work demanded
    # precision" says nothing was measured. Only a hit sitting in a sentence that carries a
    # figure counts, which is the difference between an evaluation claim and an adjective.
    def _bench_with_figures(blob: str) -> List[str]:
        out: List[str] = []
        for sent in re.split(r"(?<=[.!?])\s+", blob or ""):
            if re.search(r"\d", sent):
                out += _affirmative(_BENCH_RE, sent.lower())
        return out

    page_bench = _bench_with_figures(text)
    denied = bool(testing_field) and not _affirmative(_BENCH_RE, testing_field.lower())
    benchmark = _affirmative(_BENCH_RE, testing_text)
    harness = _affirmative(_HARNESS_RE, testing_text)
    if tests:
        emit("test_or_eval_evidence", 1.0, "confirmed",
             f"test paths in repo: {', '.join(tests[:3])}", "api",
             f"https://api.github.com/repos/{repo_name}/git/trees", rwhen)
    elif benchmark and (measured or ok) and [w for w in benchmark if _QUALITY_BENCH_RE.search(w)]:
        emit("test_or_eval_evidence", 0.75, "supported",
             "a measured evaluation with a stated denominator is described on the page "
             "(an A/B comparison or a logged-outcome harness counts; a bare 'we tested it' does not)",
             "page",
             cap.get("source_url", ""), when)
    elif benchmark and with_denom:
        # The figure exists and the method does not: a quoted percentage with a denominator
        # but a stated absence of anything to reproduce it from. Crediting it as supported
        # would reward the number while ignoring the confession next to it.
        emit("test_or_eval_evidence", 0.5, "partial",
             "a figure with a stated denominator is quoted, but the capture records no "
             "harness, held-out set or method behind it (the page's measurement words: "
             + ", ".join(sorted(set(benchmark))[:3]) + ")", "page", cap.get("source_url", ""), when)
    elif benchmark:
        emit("test_or_eval_evidence", 0.4, "partial",
             "evaluation language present but no numbers attached", "page",
             cap.get("source_url", ""), when)
    elif denied and page_bench:
        # A measured comparison described in prose with no harness behind it is neither
        # evidence nor its absence; the audit records both halves of that sentence.
        emit("test_or_eval_evidence", 0.4, "partial",
             "the page reports a measured comparison (" + ", ".join(sorted(set(page_bench))[:3]) +
             ") but the capture records no harness, method or eval set to reproduce it from",
             "page", cap.get("source_url", ""), when)
    elif harness:
        emit("test_or_eval_evidence", 0.5, "partial",
             "a harness is described (" + ", ".join(sorted(set(harness))[:3]) +
             ") but no result, run link or case count is published, so it cannot be checked",
             "page", cap.get("source_url", ""), when)
    elif measurement_practice := _measurement_claim(testing_text):
        # A loop that watches the product in use is not an accuracy eval, but it is real
        # evidence practice and far above "no tests visible" — the difference matters to a
        # builder deciding whether the team measured anything at all.
        emit("test_or_eval_evidence", 0.5, "partial",
             "a product measurement loop is described (" + ", ".join(sorted(set(measurement_practice))[:3]) +
             ") — analytics, funnels or logs rather than an accuracy or quality eval",
             "page", cap.get("source_url", ""), when)
    else:
        emit("test_or_eval_evidence", 0.0, "unverifiable",
             "the page states no tests and describes no evaluation"
             if not _NEG_CUE.search(testing_text) else
             "the only testing sentence on the page is a denial (no suite, set or run is linked)",
             "api" if repo else "page",
             f"https://github.com/{repo_name}" if repo_name else cap.get("source_url", ""),
             rwhen if repo else when)
    return checks, ev


def load_notes(path: str = NOTES, notes_dir: str = NOTES_DIR) -> Dict[str, Any]:
    """The notes registry, in whichever shape it is stored: per-record files merged over the legacy dict."""
    out: Dict[str, Any] = {}
    legacy = _load(path, {})
    if isinstance(legacy, dict):
        out.update({k: v for k, v in legacy.items() if isinstance(v, dict)})
    if os.path.isdir(notes_dir):
        for fname in sorted(os.listdir(notes_dir)):
            if fname.endswith(".json"):
                blob = _load(os.path.join(notes_dir, fname), None)
                if isinstance(blob, dict):
                    out[fname[:-5]] = blob
    return out


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

    _one_line = str(cap.get("one_line") or "").strip()
    put("what_it_is", _one_line or sec.get("what_it_does"),
        # A capture's `one_line` is the auditor's condensation of the page, not a transcription
        # — the authors' own sentence rides on the catalog row as `summary`. Marking ours
        # `observed` would tell a reader the page said it in those words.
        "derived" if _one_line else "observed",
        "the page's own summary section is missing or generic; a demo link would settle it")
    put("what_it_does", sec.get("what_it_does") or sec.get("inspiration"), "observed",
        "no step-by-step description of user-visible behaviour on the page")
    put("how_it_works", sec.get("how_we_built_it"), "observed",
        "the 'how we built it' section describes no architecture/data flow; a repo README would settle it")
    # The field is called *verified*, so its value has to say whether verification
    # happened — a bare tag list was being dropped as "too short to be a finding", which
    # turned a format floor into an unfiled mandatory field and failed the build gate.
    tags = [str(t).strip() for t in (cap.get("built_with") or []) if str(t).strip()]
    langs = ", ".join(sorted({str(k) for k in ((repo or {}).get("languages") or {})}))
    if tags:
        declared = f"declared by the authors ({len(tags)}): {', '.join(tags[:8])}"
        if langs:
            declared += f" · repo languages say: {langs[:70]}"
        else:
            declared += " · no repository published, so these are the team's own claim and nothing corroborates them"
        put("built_with_verified", declared, "observed",
            "authors published no 'Built With' tags, and no repo exists to read the stack from")
    elif langs:
        # The field answers "what is this actually built with, verified" — a repository census
        # answers that whether or not the team filled in the tag sidebar. Leaving it unfiled
        # because a UI widget was empty would punish the one record type that can be checked.
        put("built_with_verified",
            f"page published no 'Built With' tags; the linked repository reports {langs[:80]} "
            f"(verified via the GitHub API), which is the only evidence of the real stack — "
            f"library choices asserted in prose remain unverified",
            "derived",
            "neither tags nor a repository describe the stack")
    else:
        put("built_with_verified", None, "observed",
            "authors published no 'Built With' tags, and no repo exists to read the stack from")
    put("data_and_models", cap.get("data_and_models") or sec.get("how_we_built_it"), "observed",
        "which model(s), on what data, and at what cost are not stated anywhere public")
    repo_tests = (", ".join(repo.get("test_paths") or []) if repo and repo.get("test_paths") else None)
    put("how_they_tested",
        (f"test modules present in the linked repository — {repo_tests} — which is what the "
         f"page's harness figures were produced with; the page itself describes no further "
         f"evaluation protocol" if repo_tests else None) or
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
        "panel has not yet written the transferable-move note (raw/audit_notes/{id}.json)")
    put("what_breaks_first", notes.get("what_breaks_first"), "editorial",
        "panel has not yet written the first-failure note (raw/audit_notes/{id}.json)")
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


# HAZARD_CLAIM_RE's first alternative is a list of words that are also ordinary English. These are the
# bare ones, plus the object that has to share their sentence for them to state a regulated claim rather
# than a metaphor. Records this reclassifies are named in the guard at `hazard_for`.
_BARE_CLINICAL_RE = re.compile(r"\b(?:diagnos\w*|screen\w*|triage|medicat\w*|dosage|prescri\w*)\b", re.I)
# Only words that can *only* be read as a clinical or regulated subject. "symptom", "condition" and
# "diagnosis" are ordinary engineering metaphor — greenlight's own page says "users report symptoms, not
# causes, and every user diagnosis was wrong" about debugging a pipeline, and tower's says "the diagnosis
# is that nobody loses a competition because their idea was bad" — so an object that vague would let the
# metaphor through and publish a clinical-validation warning about a non-clinical product.
_CLINICAL_OBJECT_RE = re.compile(
    r"\b(?:patients?|clinicians?|physicians?|doctors?|hospitals?|clinic\w*|medical|clinical|"
    r"health(?:-| )?(?:care|records?|professional|provider)|prescription|medication|dosage|"
    r"cancer|tumor|concussion|autis\w*|depress\w*|anxiet\w*|suicid\w*|adhd|diabet\w*|epilep\w*)\b", re.I)

# The routes that carry their own object, so they never need the sentence-level guard.
_STRONG_CLAIM_RE = re.compile(
    r"\b(?:clear\w* to (?:return|play)|regulat\w*|approval|sign-?off|compliance)\b"
    r"|\bdetect\w* (?:concussion|cancer|tumor|fraud)\b|\b(?:autis\w*|concussion|suicid\w*)\b"
    r"|\b(?:DOT|SAE|ECE|ISO\s?\d+|GDPR|HIPAA|FDA|EPA|FCC|CE marking|EN\s?\d{4}|WCAG|SOC\s?2)\b"
    r"|\b(?:threshold|standards?|directive|regulation|guideline)s?\b[^.]{0,30}"
    r"\b(?:match\w*|comply|compliant|certif\w*|conform\w*|require\w*)\b"
    r"|\b(?:match\w*|compliant with|conforms? to|certified by|accredited by)\b[^.]{0,30}"
    r"\b(?:standard|threshold|directive|regulation|authority)\b", re.I)


def _measurement_claim(testing_text: str):
    """Sentences in which the team claims it watched the product in use, minus sentences that merely
    list an analytics feature the platform provides.

    attaindesk runs on Firebase analytics and says so in its architecture prose; it measured nothing.
    Reading a stack bullet as a measurement loop would put a rung on the testing ladder for that page, and
    a builder copying the signal would be copying a hosting plan. A sentence in the testing or limits
    field that claims usage was watched ("funnels showed X", an A/B result, an instrumented rollout) still
    counts.
    """
    keep = []
    # Deliberately only the testing/limits prose. `testing_text` already falls back to the page when no
    # testing field was filed, so widening it again would mean a stack bullet anywhere on the page can
    # buy a testing rung - which is exactly what happened to attaindesk, whose `data_and_models` summary
    # faithfully names the analytics it runs on.
    for sent in re.split(r"(?<=[.;!?])\s+", testing_text or ""):
            if _MEASURE_RE.search(sent) and not _MEASURE_CAPABILITY_RE.search(sent):
                keep.append(sent)
    if not keep:
        return None
    return _affirmative(_MEASURE_RE, " ".join(keep))


def lite_admission(cap: Dict[str, Any], checks: Dict[str, Any], fields: Dict[str, Any],
                   contradicted: int, coverage: float) -> Tuple[bool, List[str], List[str]]:
    """ADR-P15: the second ladder, and its refusals are recorded rather than swallowed.

    A record reaches `thin` for two quite different reasons: the evidence contradicts it, or there is
    simply less to check (no repo, no published eval) than the twelve-field rubric assumes. Lite exists for
    the second case only, so the guards are the ones that matter: something real to look at, no refuted
    claim, every lite field actually written, and at least one sentence from the team about how the thing
    behaves or was measured. That last one is what stops a feature list from being laundered into a
    published row — which is the obvious way a "shorter audit" tier would degrade a catalog.
    """
    refuse: List[str] = []
    absent = [f for f in AUDIT_MANDATORY_FIELDS if f not in AUDIT_LITE_FIELDS]
    lite_present = [f for f in AUDIT_LITE_FIELDS if f in fields]
    if len(lite_present) < len(AUDIT_LITE_FIELDS):
        refuse.append("lite fields unwritten: " + ", ".join(sorted(set(AUDIT_LITE_FIELDS) - set(lite_present))))
    af = checks.get("artifact_exists") or {}
    if not af or af.get("pass") in (None, 0.0) or af.get("status") not in ("supported", "confirmed"):
        refuse.append("no artifact we could resolve (lite still requires something to look at)")
    if contradicted:
        refuse.append(f"{contradicted} claim(s) contradicted by evidence — lite never washes a refutation")
    disclosed = (checks.get("limits_disclosed") or {}).get("pass") or 0.0
    measured = (checks.get("test_or_eval_evidence") or {}).get("pass") or 0.0
    if disclosed <= 0.0 and measured <= 0.0:
        refuse.append("the page says nothing about limits or measurement: a lite row still has to "
                      "contain a sentence about how the thing behaves")
    numbers = checks.get("numbers_add_up") or {}
    if numbers.get("status") == "contradicted":
        refuse.append("numbers contradicted on their own terms")
    return (not refuse), refuse, absent


def hazard_for(rec: Dict[str, Any], cap: Dict[str, Any], notes: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """A13: one stamp, one line, mandatory for agents."""
    dom = rec.get("domain")
    cls = HAZARD_DOMAINS.get(dom)
    # The one-liner is where a regulated claim is most likely to be made, so it is part of
    # what we scan, alongside everything the team wrote about what the tool is *not*.
    text = (_sections_text(cap) + " " + str(cap.get("one_line") or "")
            + " " + (rec.get("summary") or "")).lower()
    claim = bool(re.search(HAZARD_CLAIM_RE, text, re.I))
    # A bare clinical word in ordinary English is not a regulated-outcome claim. This fired three
    # false hazards before the guard: tower-dq18x2 because its author wrote "the diagnosis is that
    # nobody loses a competition because their idea was bad", and both Greenlight records because a
    # screenplay contains the substring "screen" - and each then published the generic note claiming
    # no clinical validation, about a product with nothing clinical to validate. So the bare words
    # only count when the same sentence carries a clinical or regulatory object. Every route that
    # already names its object (a regulator, a threshold the product claims to meet, "clear to return
    # to play", autism, concussion) is untouched, and so is the sector-plus-advice path below.
    if claim and not _STRONG_CLAIM_RE.search(text):   # compiled already; `text` is lower-cased
        claim = any(_BARE_CLINICAL_RE.search(sent) and _CLINICAL_OBJECT_RE.search(sent)
                    for sent in re.split(r"(?<=[.;!?])\s+", text))
    # Telling a user what to take, do or follow inside a regulated domain is the exposure,
    # even when the page never uses the word diagnosis or approval. A mood chart that only
    # visualises stays unflagged; an advice loop does not.
    advises = bool(re.search(r"(recommend\w*|advise\w*|supplement\w*|dosage|protocol|"
                             r"intervention|action plan|coach\w*|guidance)", text, re.I))
    if not claim and not (cls and advises):
        return None
    disclaimed = bool(re.search(HAZARD_DISCLAIM_RE, text))
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
    """A5: merge true duplicates; cross-link parallel invention (it is signal, not dirt).

    Blocking (docs/PARALLELISM_PANEL.md ADR-P4): the pass is quadratic in the audited set, and every
    condition that can *act* on a pair needs a shared leading name token or shared
    numeric-fingerprint text. So the candidate set is the union of those two indexes, visited in the
    same (i, j) order the unblocked loop used, and skipping a non-candidate pair changes nothing
    because that branch has no side effect. Proven, not argued: `pipeline/bench_scale.py` runs both
    implementations over a 1,000-record tree and diffs `audit.jsonl` byte-for-byte. The per-record
    text, token and number sets are hoisted out of the loop too — they were being rebuilt n times per
    record, which is what made the pass quadratic in string work rather than in comparisons.
    """
    actions: List[str] = []
    n = len(sheets)
    _text: Dict[int, str] = {}
    _tok: Dict[int, set] = {}
    _nums: Dict[int, set] = {}
    _key: Dict[int, str] = {}
    by_key: Dict[str, List[int]] = {}
    by_num: Dict[str, List[int]] = {}
    for idx, a in enumerate(sheets):
        ra = recs.get(a["id"], {})
        text = _sections_text({"sections": a.get("_sections")}) or (ra.get("summary") or "").lower()
        _text[idx] = text
        _tok[idx] = set(re.findall(r"[a-z]{4,}", text)) | set(a.get("moves") or [])
        _nums[idx] = set(a.get("_numbers") or [])
        first = str(a.get("name", "")).strip().lower().split(" ")[0].strip("—-:")
        _key[idx] = first
        by_key.setdefault(first, []).append(idx)
        for num in _nums[idx]:
            by_num.setdefault(str(num), []).append(idx)
    cand: List[List[int]] = []
    for i0 in range(n):
        ahead = set(x for x in by_key.get(_key[i0], ()) if x > i0)
        ahead.update(x for num in _nums[i0] for x in by_num.get(str(num), ()) if x > i0)
        cand.append(sorted(ahead))
    for i in range(n):
        for j in cand[i]:
            a, b = sheets[i], sheets[j]
            ra, rb = recs.get(a["id"], {}), recs.get(b["id"], {})
            ta, tb = _text[i], _text[j]
            na, nb = a.get("name", "").strip().lower(), b.get("name", "").strip().lower()
            same_name = na == nb
            # "Greenlight — Nine-Agent Production Crew" vs "Greenlight — Screenplay to Film":
            # same leading product token, same event → a resubmission, not two teams converging.
            fa, fb = _nums[i], _nums[j]
            num_shared = len(fa & fb)
            numjac = num_shared / max(1, len(fa | fb))
            first = na.split(" ")[0].strip("—-:")
            same_word = first == nb.split(" ")[0].strip("—-:") and len(first) > 4
            ea = recs.get(a["id"], {}) or {}
            eb = recs.get(b["id"], {}) or {}
            ev_key = lambda r_: (r_.get("event_key") or r_.get("event_slug") or r_.get("event_title") or "")
            same_event = ev_key(ea) == ev_key(eb) and bool(ev_key(ea))
            # Two submissions whose *published display names are identical* inside one event
            # are one product published twice (each page carries the platform title), while
            # "NeuroGuard AI" vs "NeuroGuard AI (v2)" is two teams converging — a name that
            # differs by a suffix is a different team's name. That distinction is invisible
            # to text overlap, which is why it gets its own route instead of a lower bar.
            display_a = str(ra.get("name") or "").strip().lower()
            display_b = str(rb.get("name") or "").strip().lower()
            same_listing = bool(display_a) and display_a == display_b and same_event
            # Prose overlap alone cannot prove a resubmission (each event wants its own
            # write-up), so the strong route is shared *numbers*: a 45-page script does not
            # independently produce "29% → 49%" and "$0.02 / $1 / $20" twice. A team re-
            # submitting across two hackathons is a duplicate for our purposes even though
            # the events differ; two teams colliding on a generic name is not.
            fingerprint = (same_word and num_shared >= 3)
            same_product = same_word and (same_event or fingerprint)
            tok_a, tok_b = _tok[i], _tok[j]
            overlap = len(tok_a & tok_b) / max(1, len(tok_a | tok_b))
            if (same_name and overlap >= DUP_TEXT_OVERLAP) or (same_product and overlap >= DUP_MECHANISM_OVERLAP) \
                    or fingerprint or same_listing:
                keep, drop = ((a, b) if a["soundness_score"] >= b["soundness_score"] else (b, a))
                drop["duplicate_of"] = keep["id"]
                drop["verdict"] = "duplicate"
                drop["verdict_reasons"].append(
                    f"resubmission of the same product — name match {same_name}, listing-title "
                    f"equality {same_listing}, shared mechanism/text "
                    f"overlap {overlap:.2f}, shared numeric fingerprints {sorted(fa & fb)[:4]} "
                    f"({numjac:.2f} jaccard); merged into the better-evidenced copy (A5)")
                actions.append(f"duplicate: {drop['id']} → {keep['id']}")
            elif (overlap >= DUP_MECHANISM_OVERLAP or (same_word and ra.get("domain") == rb.get("domain"))):
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
    notes_all = load_notes()

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
            "tier": "full" if verdict in AUDIT_PUBLISH_VERDICTS else None,
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
            # The page's own artifact links, copied verbatim, so every surface that publishes a
            # row can point at the same demo the audit opened. Absent stays null — a missing
            # demo link is a fact about the submission, not a hole to fill in (A10).
            "links": {k: (cap.get("links") or {}).get(k) or None for k in ("repo", "demo", "video")},
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
        # ADR-P15 · the second ladder, applied where the first one said `thin` and nowhere else.
        if not sheet["publishable"] and verdict == "thin":
            admitted, refused, absent = lite_admission(cap, checks, fields, contradicted, coverage)
            if admitted:
                sheet["verdict"] = AUDIT_LITE_VERDICT          # never `strong`: coverage cannot reach it
                sheet["publishable"] = True
                sheet["tier"] = "lite"
                sheet["fields_absent"] = absent
                if sheet.get("worth") in AUDIT_LITE_FORBIDDEN_WORTH:
                    sheet["worth_note"] = (f"worth demoted from {sheet['worth']} to strong: a six-field "
                                           "row cannot certify a breakthrough (ADR-P15). ") + str(
                                               sheet.get("worth_note") or "")
                    sheet["worth"] = "strong"
                sheet["verdict_reasons"] = list(sheet.get("verdict_reasons") or []) + [
                    f"published as audited-lite on {len(AUDIT_LITE_FIELDS)} of {len(AUDIT_MANDATORY_FIELDS)} "
                    f"fields ({int(coverage * 100)}% of the rubric checkable); the other "
                    f"{len(absent)} need a repository or a longer read and are named in `fields_absent`"]
                sheet["tier_note"] = ("Lite audit: six fields were established from the page and nothing "
                                      "was read from a repository. Treat `build_is_real` and "
                                      "`stack_consistency` as unexamined, not as passing.")
            else:
                sheet["tier"] = None
                # Recorded in the derivation trace, because `why_not_promoted` is rebuilt from it below:
                # a refusal that only lived in the final list would be silently dropped, and the refusal
                # is the *instruction* — it says which lite field is unwritten or which guard failed.
                sheet["verdict_reasons"] = list(sheet.get("verdict_reasons") or []) + [
                    "audited-lite refused: " + "; ".join(refused)]
        elif sheet["publishable"]:
            sheet["tier"] = "full"

        sheet["_sections"] = cap.get("sections") or {}   # internal, stripped before write
        sheet["_numbers"] = numeric_fingerprint(cap)
        sheets.append(sheet)

    actions = similarity_verdicts(sheets, recs)
    # `publishable` was decided before the similarity pass ran. A record merged into a
    # duplicate must stop being publishable — otherwise the shard_builder gate (rightly)
    # fails for shipping a duplicate.
    for s in sheets:
        s["publishable"] = s["verdict"] in AUDIT_PUBLISH_VERDICTS
        if not s["publishable"] and s.get("tier") == "lite":
            # Lite admission was decided before the similarity pass. A record that pass demotes (merged
            # into a duplicate, say) is no longer a published six-field row, and leaving `tier: lite` on
            # it would publish "this row was certified with six fields" about a record we are holding —
            # and its reason list would still say "published as audited-lite".
            s["tier"] = None
            s["fields_absent"] = []
            s["tier_note"] = None
            s["verdict_reasons"] = [r for r in (s.get("verdict_reasons") or [])
                                    if not str(r).startswith("published as audited-lite")]
            s.setdefault("why_not_promoted", []).append(
                "audited-lite withdrawn: the similarity pass demoted this record after lite admission")
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
            # The actionable half of a hold: named unknowns first, then each check that did not
            # clear, with the artifact that would answer it. A record already captured must
            # never be told to "go fetch a project page".
            if s.get("duplicate_of"):
                s["would_settle_it"] = [
                    f"nothing — {s['duplicate_of']} is the same submission with more evidence; "
                    f"read its audit sheet instead"]
            else:
                settle = [str(u.get("missing")) for u in (s.get("unknowns") or [])
                          if u.get("missing")][:2]
                for ck in AUDIT_CHECKS:          # declaration order, so the list is stable
                    st = s["checks"].get(ck) or {}
                    if st.get("status") in ("unverifiable", "contradicted") \
                            or (st.get("pass") or 0) < 0.75:
                        got = AUDIT_CHECKS[ck].get("settles_with")
                        if got:
                            settle.append(f"{ck}: {got}")
                s["would_settle_it"] = [x for x in dict.fromkeys(settle) if x][:5]
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
                   "note": "Ranking of never-audited candidates by expected information gain (ADR-A7). "
                           "Nothing here has been verified; the order is only 'what would teach us most'. "
                           f"`pool_size` counts records with no sheet at all — the full holding area, "
                           "including audited-but-held records (thin, duplicate, hazard), is "
                           "data/pool.json.",
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
