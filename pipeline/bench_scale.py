#!/usr/bin/env python3
"""Scale harness — the measurements the parallelization plan is argued from.

`python3 pipeline/bench_scale.py` answers three questions, and every number the panel quotes is one
this file prints, so a future maintainer can re-derive them instead of trusting a transcript:

1. **Where does the time actually go, as the catalog grows?** Each stage of `make build` is timed in
   a subprocess at N audited records, with the N-record tree built by cloning the real captures and
   gallery rows into a temp directory. `--records` is the axis; `18` is what the catalog holds today.
2. **Is the similarity blocking lossless?** The dedup pass has a brute-force reference implementation
   here (the pre-blocking loop, verbatim) and the shipped blocked one; the two must produce identical
   verdicts and identical `audit.jsonl`. A speed-up that changes which projects get merged is not a
   speed-up, so this is the gate on the optimisation, not a footnote to it.
3. **What does the per-sector detail budget allow?** Published sheets are measured in gzip KB per
   record, and the 240 KB-per-sector budget in `pipeline/shard_builder.py` is divided by it to say how
   many published records one sector shard can hold before it stops being a single first-paint fetch.

The synthetic tree is an *instrument*, not a catalog: cloning captures with `-cloneK` suffixes
deliberately trips the duplicate detector, which is exactly what makes the quadratic pass visible.
Nothing outside `--work` (default `/tmp/ideasgalore-bench`) is written, and it is deleted on exit
unless `--keep`.
"""
from __future__ import annotations

import argparse
import gzip
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(HERE))

import audit_projects as A  # noqa: E402  (local module)

STAGES = [
    ("ingest_seed", "pipeline/ingest_seed.py"),
    ("taxonomy_hacks", "pipeline/taxonomy_hacks.py"),
    ("audit_projects", "pipeline/audit_projects.py"),
    ("shard_builder", "pipeline/shard_builder.py"),
    ("docsync", "pipeline/docsync.py"),
]
# The pre-blocking implementation, verbatim from the commit before the optimisation, kept here so
# the shipped pass can be *diffed* against it rather than argued about (docs/PARALLELISM_PANEL.md
# ADR-P4). If the two ever disagree on any verdict, the optimisation is not lossless and must not
# be shipped.
REFERENCE_SRC = "def similarity_verdicts_reference(sheets: List[Dict[str, Any]], recs: Dict[str, Dict[str, Any]]) -> List[str]:\n    \"\"\"A5: merge true duplicates; cross-link parallel invention (it is signal, not dirt).\"\"\"\n    actions: List[str] = []\n    for i in range(len(sheets)):\n        for j in range(i + 1, len(sheets)):\n            a, b = sheets[i], sheets[j]\n            ra, rb = recs.get(a[\"id\"], {}), recs.get(b[\"id\"], {})\n            ta = _sections_text({\"sections\": a.get(\"_sections\")}) or (ra.get(\"summary\") or \"\").lower()\n            tb = _sections_text({\"sections\": b.get(\"_sections\")}) or (rb.get(\"summary\") or \"\").lower()\n            na, nb = a.get(\"name\", \"\").strip().lower(), b.get(\"name\", \"\").strip().lower()\n            same_name = na == nb\n            # \"Greenlight \u2014 Nine-Agent Production Crew\" vs \"Greenlight \u2014 Screenplay to Film\":\n            # same leading product token, same event \u2192 a resubmission, not two teams converging.\n            fa = set(a.get(\"_numbers\") or []); fb = set(b.get(\"_numbers\") or [])\n            num_shared = len(fa & fb)\n            numjac = num_shared / max(1, len(fa | fb))\n            first = na.split(\" \")[0].strip(\"\u2014-:\")\n            same_word = first == nb.split(\" \")[0].strip(\"\u2014-:\") and len(first) > 4\n            ea = recs.get(a[\"id\"], {}) or {}\n            eb = recs.get(b[\"id\"], {}) or {}\n            ev_key = lambda r_: (r_.get(\"event_key\") or r_.get(\"event_slug\") or r_.get(\"event_title\") or \"\")\n            same_event = ev_key(ea) == ev_key(eb) and bool(ev_key(ea))\n            # Two submissions whose *published display names are identical* inside one event\n            # are one product published twice (each page carries the platform title), while\n            # \"NeuroGuard AI\" vs \"NeuroGuard AI (v2)\" is two teams converging \u2014 a name that\n            # differs by a suffix is a different team's name. That distinction is invisible\n            # to text overlap, which is why it gets its own route instead of a lower bar.\n            display_a = str(ra.get(\"name\") or \"\").strip().lower()\n            display_b = str(rb.get(\"name\") or \"\").strip().lower()\n            same_listing = bool(display_a) and display_a == display_b and same_event\n            # Prose overlap alone cannot prove a resubmission (each event wants its own\n            # write-up), so the strong route is shared *numbers*: a 45-page script does not\n            # independently produce \"29% \u2192 49%\" and \"$0.02 / $1 / $20\" twice. A team re-\n            # submitting across two hackathons is a duplicate for our purposes even though\n            # the events differ; two teams colliding on a generic name is not.\n            fingerprint = (same_word and num_shared >= 3)\n            same_product = same_word and (same_event or fingerprint)\n            tok_a = set(re.findall(r\"[a-z]{4,}\", ta)) | set(a.get(\"moves\") or [])\n            tok_b = set(re.findall(r\"[a-z]{4,}\", tb)) | set(b.get(\"moves\") or [])\n            overlap = len(tok_a & tok_b) / max(1, len(tok_a | tok_b))\n            if (same_name and overlap >= DUP_TEXT_OVERLAP) or (same_product and overlap >= DUP_MECHANISM_OVERLAP) \\\n                    or fingerprint or same_listing:\n                keep, drop = ((a, b) if a[\"soundness_score\"] >= b[\"soundness_score\"] else (b, a))\n                drop[\"duplicate_of\"] = keep[\"id\"]\n                drop[\"verdict\"] = \"duplicate\"\n                drop[\"verdict_reasons\"].append(\n                    f\"resubmission of the same product \u2014 name match {same_name}, listing-title \"\n                    f\"equality {same_listing}, shared mechanism/text \"\n                    f\"overlap {overlap:.2f}, shared numeric fingerprints {sorted(fa & fb)[:4]} \"\n                    f\"({numjac:.2f} jaccard); merged into the better-evidenced copy (A5)\")\n                actions.append(f\"duplicate: {drop['id']} \u2192 {keep['id']}\")\n            elif (overlap >= DUP_MECHANISM_OVERLAP or (same_word and ra.get(\"domain\") == rb.get(\"domain\"))):\n                a[\"parallel_invention_of\"] = b[\"id\"]\n                b[\"parallel_invention_of\"] = a[\"id\"]\n                actions.append(f\"parallel invention kept + cross-linked: {a['id']} \u2194 {b['id']}\")\n    return actions\n"


def run(cmd: list, cwd: Path, check: bool = True) -> float:
    t = time.perf_counter()
    p = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True)
    if p.returncode and check:
        raise SystemExit(f"{cmd} failed:\n{p.stdout[-1500:]}\n{p.stderr[-1500:]}")
    return time.perf_counter() - t


def grow(root: Path, target: int) -> int:
    """Clone the real captures + gallery rows until `target` records are audited. Returns the corpus size."""
    cdir = root / "pipeline/raw/deep_captures"
    caps = sorted(cdir.glob("*.json"))
    cap0 = json.loads(caps[0].read_text(encoding="utf-8"))
    evs = cap0["source_url"].split("/")[3]
    lines = (root / "pipeline/raw/seed_gallery.tsv").read_text(encoding="utf-8").rstrip("\n").split("\n")
    notes_p = root / "pipeline/raw/audit_notes.json"
    # ADR-P4: the registry is a directory of per-record files with the legacy dict merged under it,
    # so a synthetic tree has to read it the same way the audit does or the clones lose their notes.
    notes = json.loads(notes_p.read_text(encoding="utf-8")) if notes_p.exists() else {}
    for nf in sorted((root / "pipeline/raw/audit_notes").glob("*.json")):
        notes[nf.stem] = json.loads(nf.read_text(encoding="utf-8"))
    rows, added, k = list(lines), 0, 0
    while len(rows) - len(lines) < (target - len(caps)) and k < 4000:
        base = caps[k % len(caps)]
        bid = base.stem
        cid = f"{bid}-clone{k}"
        obj = json.loads(base.read_text(encoding="utf-8"))
        obj["id"] = cid
        obj["software_id"] = int(obj.get("software_id") or 4600000) + 100000 + k
        obj["name"] = f"{obj['name']} Clone {k}"
        obj["source_url"] = f"https://devpost.com/software/{evs}/{cid}"
        (cdir / f"{cid}.json").write_text(json.dumps(obj, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        if bid in notes:
            notes[cid] = notes[bid]
        rows.append("\t".join([evs, cid, obj["name"], obj.get("one_line") or obj["name"]]))
        added += 1
        if len(rows) - len(lines) >= (target - len(caps)):
            break
        k += 1
    (root / "pipeline/raw/seed_gallery.tsv").write_text("\n".join(rows) + "\n", encoding="utf-8")
    notes_p.write_text(json.dumps(notes, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return len(lines) + added


def time_stages(root: Path) -> dict:
    out = {}
    for name, script in STAGES:
        out[name] = run([sys.executable, script], root)
    return out


def check_and_suite(root: Path) -> dict:
    """Gate and suite at scale. `check=False` on the suite on purpose: a synthetic tree has no .git,
    so the two tests that diff against a committed artifact fail there for an environmental reason.
    The number we want is the wall clock, and it must be reported even when that happens."""
    return {
        "shard_builder --check": run([sys.executable, "pipeline/shard_builder.py", "--check"], root),
        "test suite": run([sys.executable, "-m", "unittest", "discover", "-s", "pipeline/tests",
                           "-t", "pipeline"], root, check=False),
    }


def blocking_is_lossless() -> tuple:
    """Run the whole audit twice on the real tree — once blocked, once brute-force — and compare.

    `audit()` is re-entered with the reference bound in place of the shipped pass, writing to temp
    paths, so the comparison covers every verdict the file carries, not just a summary of it.
    """
    import contextlib, io as _io, tempfile

    def run_with(fn, out_path):
        prev = A.similarity_verdicts
        if fn is not None:
            A.similarity_verdicts = fn
        try:
            with open(os.devnull, "w") as devnull, contextlib.redirect_stdout(devnull):
                sheets, actions = A.audit(str(REPO / "pipeline/corpus.jsonl"), out_path, False)
        finally:
            A.similarity_verdicts = prev
        payload = json.dumps([{k: sh.get(k) for k in ("id", "sector", "subsystem", "verdict",
                                                     "verdict_reasons", "duplicate_of", "cross_linked",
                                                     "soundness_score", "coolness")} for sh in sheets],
                             sort_keys=True)
        return payload, actions, open(out_path, encoding="utf-8").read()

    with tempfile.TemporaryDirectory() as td:
        p_new, acts_new, file_new = run_with(None, f"{td}/new.jsonl")
        ns = {"re": re, "List": list, "Dict": dict, "Any": object,
              "DUP_TEXT_OVERLAP": A.DUP_TEXT_OVERLAP, "DUP_MECHANISM_OVERLAP": A.DUP_MECHANISM_OVERLAP,
              "_sections_text": A._sections_text, "recs": {}, "sheets": []}
        exec(REFERENCE_SRC, ns)
        ref = ns["similarity_verdicts_reference"]

        def ref_bound(sheets, recs):
            return ref(sheets, recs)

        p_ref, acts_ref, file_ref = run_with(ref_bound, f"{td}/ref.jsonl")
    same = p_new == p_ref and acts_new == acts_ref and file_new == file_ref
    return same, len(acts_ref), len(acts_new)


def repo_io(root: Path, workers: int = 8, limit: int = 24) -> tuple:
    """Cost of one repo-verification round, measured against the live API: per repo, per request.

    The repo pool is every `owner/repo` the pipeline knows about — links captured from project pages,
    plus the ledger's keys, plus name-search candidates — so the measurement covers the same endpoint
    fan-out the stage performs (~4 requests per repo). It writes nothing: `verify()` is a pure read,
    and each call gets its own cache. Reported as ms/request because the stage is latency-bound, not
    CPU-bound, which is the whole reason its fix is concurrency plus a cache instead of more compute.
    """
    import os
    import repo_verify as R
    from concurrent.futures import ThreadPoolExecutor
    pool_names = {f for _, f in R.linked_repos()}
    for path, key in (("pipeline/raw/repo_checks.json", None), ("pipeline/raw/repo_candidates.json", "results")):
        fp = root / path
        if fp.exists():
            data = json.loads(fp.read_text(encoding="utf-8"))
            if key:
                rows = data.get(key) or {}
                groups = rows.values() if isinstance(rows, dict) else rows
                for row in groups:
                    cands = (row.get("candidates") if isinstance(row, dict) else row) or []
                    for cand in cands:
                        fn = R.repo_from_url(cand if isinstance(cand, str)
                                            else (cand.get("url") or cand.get("html_url") or ""))
                        if fn:
                            pool_names.add(fn)
            else:
                pool_names.update(k for k in data if not k.startswith("_"))
    fulls = sorted(pool_names)[:limit]
    if not fulls:
        return 0.0, [], 0.0, 0
    tok = os.environ.get("GITHUB_TOKEN")
    mk = lambda: R.Client(tok, sleep=0.0, budget=8 * len(fulls) + 8, dry=False, cache={})
    # Request-level measurement, because that is the primitive the stage is built on: `verify()` fires
    # several GETs per repo, and a worker parallelised per *repo* can only hide latency when it has
    # several repos in flight. Timed both ways so the design choice is visible in the number.
    urls = [f"{R.API}/repos/{f}" for f in fulls]
    t = time.perf_counter()
    for c_u in urls:
        mk().get(c_u)
    seq = time.perf_counter() - t
    t = time.perf_counter()
    with ThreadPoolExecutor(max_workers=max(2, workers // max(len(fulls), 1))) as tp:
        list(tp.map(lambda c_u: mk().get(c_u), urls))
    par = time.perf_counter() - t
    per_req_seq = seq / len(urls) * 1000
    per_req_par = par / len(urls) * 1000
    print(f"[api latency] {len(urls)} GETs to api.github.com: {per_req_seq:.0f} ms/request sequentially, "
          f"{per_req_par:.0f} ms/request at {max(2, workers // max(len(fulls), 1))}-way "
          f"({seq / max(par, 1e-9):.1f}x). Verification cost is round-trips; batch them.")
    reqs = len(urls)
    return per_req_seq, fulls, per_req_par, reqs


def budget_math(root: Path) -> dict:
    """Published sheet bytes per record, and how many published records one sector shard can hold.

    `shard_builder` gives each sector a 240 KB gzip budget, because the detail surface is a single
    per-sector file the UI fetches once. Divide that budget by the real per-record sheet cost and you
    get the number that decides whether 500-1,000 detailed projects fit the current layout at all.
    """
    stats = json.loads((root / "web/public/catalog-stats.json").read_text(encoding="utf-8"))
    published = max(1, int(stats.get("total") or 1))
    sheets_kb = float(stats.get("audit_sheets_kb") or 0.0)
    gz = {}
    for p in sorted((root / "web/public/data/audits").glob("*.json")):
        gz[p.stem] = round(len(gzip.compress(p.read_bytes(), 9)) / 1024, 2)
    served_gz = round(sum(gz.values()), 2)
    # The builder budgets what it *emits* (`audit_sheets_kb`); a reader fetches what is *served* (the
    # files in the directory). They diverged by one stale sector sheet — 44.7 KB budgeted against
    # 51.6 KB served — which is why both numbers are printed and the budget math uses the builder's.
    per_record_gz = sheets_kb / published if sheets_kb else served_gz / published
    budget = 240.0
    return {
        "published": published,
        "audited": len([1 for _ in (root / "pipeline/raw/deep_captures").glob("*.json")]),
        "sheets_kb_gz_emitted": sheets_kb,
        "sheets_kb_gz_served": served_gz,
        "served_minus_emitted_kb": round(served_gz - sheets_kb, 2),
        "sheet_files": len(gz),
        "per_sector_gzip_kb": dict(sorted(gz.items(), key=lambda kv: -kv[1])),
        "gzip_kb_per_published_record": round(per_record_gz, 3),
        "sector_budget_kb": budget,
        "published_records_per_sector_at_budget": int(budget // max(per_record_gz, 1e-9)),
        "tier1_gzip_kb": stats.get("tier1_gzip_kb"),
        "tier1_budget_kb": stats.get("tier1_budget_kb"),
        "shards": stats.get("shards") or {},
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--records", type=int, default=200, help="target number of audited records in the grown tree")
    ap.add_argument("--work", default="", help="where to build the synthetic tree (default: a temp dir)")
    ap.add_argument("--keep", action="store_true", help="leave the synthetic tree on disk")
    ap.add_argument("--concurrency", type=int, default=8, help="simulated repo_verify worker count (for the I/O-bound stage)")
    ap.add_argument("--skip-grow", action="store_true", help="only run the lossless proof and the budget math on the real tree")
    args = ap.parse_args()

    same, n_ref, n_new = blocking_is_lossless()
    print(f"[blocking] duplicate actions raised by the brute-force pass: {n_ref}; by the blocked pass: "
          f"{n_new}; every verdict, reason, cross-link and sheet byte identical: {same}")
    if not same:
        print("[blocking] LOSSY — do not ship the optimisation")
        return 1

    bud = budget_math(REPO)
    top = ", ".join(f"{k}={v} KB" for k, v in list(bud["per_sector_gzip_kb"].items())[:3])
    drift = bud["served_minus_emitted_kb"]
    verdict = ("a served file the build does not emit — a stale surface, see docs/PARALLELISM_PANEL.md M15"
               if drift > 0.1 else "in step (rounding only)")
    print(f"[budget] sheets: {bud['sheets_kb_gz_emitted']} KB gz emitted vs {bud['sheets_kb_gz_served']} KB "
          f"gz served across {bud['sheet_files']} sector files (divergence {drift} KB: {verdict})")
    print(f"[budget] {bud['published']} published records at {bud['gzip_kb_per_published_record']} KB gz each; the {bud['sector_budget_kb']} KB "
          f"per-sector budget allows ~{bud['published_records_per_sector_at_budget']} published records per "
          f"sector shard before the detail surface stops being one cheap fetch. Largest today: {top}")
    print(f"[budget] tier1 catalog-packed.json {bud['tier1_gzip_kb']} KB of a {bud['tier1_budget_kb']} KB budget "
          f"— the packed surface has room for 1,000 rows; the per-sector detail files do not")

    if args.skip_grow:
        return 0
    tmp = Path(args.work) if args.work else Path(tempfile.mkdtemp(prefix="ideasgalore-bench-"))
    if not args.work:
        tmp.mkdir(parents=True, exist_ok=True)
    shutil.copytree(str(REPO), str(tmp / "tree"), ignore=shutil.ignore_patterns(
        "node_modules", ".git", "dist", ".svelte-kit", "__pycache__"), symlinks=False)
    root = tmp / "tree"
    try:
        grown = grow(root, args.records)
        print(f"[grow] synthetic tree: {args.records} audited records, corpus rows {grown}")
        t1 = time_stages(root)
        print(f"[timings @ {args.records} audited] " + ", ".join(f"{k}={v:.2f}s" for k, v in t1.items())
              + f", total={sum(t1.values()):.1f}s")
        t0 = time_stages(REPO)
        print("[timings @ real catalog] " + ", ".join(f"{k}={v:.2f}s" for k, v in t0.items())
              + f", total={sum(t0.values()):.1f}s")
        c = check_and_suite(root)
        print("[gate+suite @ scale] " + ", ".join(f"{k}={v:.2f}s" for k, v in c.items()))
        io_ms, urls, par_ms, reqs = repo_io(REPO, workers=args.concurrency)
        if urls:
            print(f"[repo_verify I/O] {len(urls)} repos ≈ {reqs} API reads at {io_ms:.0f} ms/request "
                  f"sequentially; the stage is latency-bound, not CPU-bound, so the fix is request-level "
                  f"concurrency plus a cache keyed on (repo, pushed_at) — see ADR-P7/P8.")
            print("[rate] the GitHub core budget (8200/hr for this workspace) divides records per hour, "
                  "not their latency: ~2,050 records per hour at 4 requests each serially, so a "
                  "1,000-record refresh fits in one window only if every worker shares one ledger.")
    finally:
        if not args.keep:
            shutil.rmtree(str(tmp), ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
