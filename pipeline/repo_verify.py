#!/usr/bin/env python3
"""
repo_verify.py — mechanical artifact verification via the GitHub REST API
========================================================================
This is what turns "is it technically sound?" from a vibe into a check (ADR-A3):
we read the linked repository's language mix, size, README, file tree and push
date, and let the audit engine compare that against what the team claimed.

Design constraints the panel set:
  · stdlib only, no key required (unauthenticated = 5,000–8,000 req/hr; we budget
    `--budget` per run and cache ETags so a weekly cron can never exhaust it);
  · **we only verify repositories the project page itself links** (A14). A name match
    from search is recorded as `candidates` for a human to confirm, never promoted to
    "this is their code" — guessing a stranger's repo would put our error in their mouth;
  · captures are committed (`pipeline/raw/repo_checks.json`), so `make build` stays
    offline and byte-deterministic (ADR-10/A11). `checked_at` is data, not build time.

Usage:
  python3 pipeline/repo_verify.py --from-captures            # verify every linked repo
  python3 pipeline/repo_verify.py --repos owner/name other/name
  python3 pipeline/repo_verify.py --from-captures --search-missing   # + name-search candidates
  python3 pipeline/repo_verify.py --from-captures --dry-run  # show the call plan only
"""
from __future__ import annotations

import argparse
import base64
import glob
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

API = "https://api.github.com"
HERE = os.path.dirname(os.path.abspath(__file__))
RAW = os.path.join(HERE, "raw")
CAPTURE_DIR = os.path.join(RAW, "deep_captures")
CHECKS_OUT = os.path.join(RAW, "repo_checks.json")
CANDIDATES_OUT = os.path.join(RAW, "repo_candidates.json")
STATE = os.path.join(HERE, "state", "github_etag.json")
UA = "IdeasGalore-Audit/1.0 (+https://github.com/knarayanareddy/Ideasgalore; read-only artifact check)"

SETUP_RE = re.compile(r"(^\s*#{1,4}\s*(getting started|installation|setup|quick ?start|running|usage)"
                      r"|npm (ci|install)|pip install|docker(-compose)? (up|build)|make run|python -m venv|\.env)",
                      re.I | re.M)
TEST_RE = re.compile(r"(^|/)(tests?|__tests__|spec|e2e|cypress|playwright)(/|$)", re.I)
SRC_RE = re.compile(r"(^|/)(src|app|lib|backend|frontend|server|client|api|pkg|cmd|code|components)(/|$)", re.I)


class Budget(Exception):
    pass


class Client:
    def __init__(self, token: Optional[str], sleep: float, budget: int, dry: bool, cache: Dict[str, Any]):
        self.token, self.sleep, self.dry = token, sleep, dry
        self.budget, self.used, self.cache = budget, 0, cache

    def get(self, url: str) -> Tuple[int, Optional[Any]]:
        """Returns (status, json|None). 304 → (304, cached payload)."""
        if url in self.cache.get("etags", {}):
            pass
        if self.dry:
            print(f"  · plan GET {url}")
            return 0, None
        if self.used >= self.budget:
            raise Budget(f"run budget of {self.budget} requests reached")
        req = urllib.request.Request(url, headers={
            "User-Agent": UA, "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28"})
        if self.token:
            req.add_header("Authorization", f"Bearer {self.token}")
        etag = (self.cache.get("etags") or {}).get(url)
        if etag:
            req.add_header("If-None-Match", etag)
        for attempt in range(3):
            try:
                with urllib.request.urlopen(req, timeout=20) as r:
                    self.used += 1
                    body = r.read().decode("utf-8", "replace")
                    tag = r.headers.get("ETag")
                    if tag:
                        self.cache.setdefault("etags", {})[url] = tag
                    return r.status, (json.loads(body) if body.strip() else None)
            except urllib.error.HTTPError as e:
                self.used += 1
                if e.code == 304:
                    return 304, self.cache.get("bodies", {}).get(url)
                if e.code in (403, 429):
                    wait = min(30, 2 ** attempt * 3)
                    ra = e.headers.get("Retry-After")
                    if ra and ra.isdigit():
                        wait = max(wait, int(ra))
                    print(f"  ⏳ {e.code} from GitHub; backing off {wait}s (rate limit is a stop sign, not a hint)")
                    time.sleep(wait)
                    continue
                if e.code == 404:
                    return 404, None
                print(f"  ⚠ GET {url} → HTTP {e.code}")
                return e.code, None
            except Exception as ex:  # network/egress isolation: fail soft, never fake
                print(f"  ⚠ GET {url} → {type(ex).__name__}: {ex}")
                return 0, None
        return 0, None

    def remember(self, url: str, payload: Any) -> None:
        self.cache.setdefault("bodies", {})[url] = payload


def repo_from_url(url: str) -> Optional[str]:
    m = re.search(r"github\.com/([^/]+/[^/#?\s]+)", url or "")
    if not m:
        return None
    return re.sub(r"\.git$", "", m.group(1).strip("/"))


def linked_repos() -> List[Tuple[str, str]]:
    """(project_id, owner/repo) for every project page link we captured."""
    out = []
    for path in sorted(glob.glob(os.path.join(CAPTURE_DIR, "*.json"))):
        cap = json.load(open(path, encoding="utf-8"))
        pid = cap.get("id") or os.path.basename(path)[:-5]
        for key in ("repo", "source_code", "code", "github"):
            url = (cap.get("links") or {}).get(key)
            if url:
                full = repo_from_url(url)
                if full:
                    out.append((pid, full))
    seen, uniq = set(), []
    for pid, full in out:
        if (pid, full) not in seen:
            seen.add((pid, full))
            uniq.append((pid, full))
    return uniq


def verify(client: Client, full: str) -> Dict[str, Any]:
    rec: Dict[str, Any] = {"checked_at": time.strftime("%Y-%m-%d", time.gmtime()),
                           "url": f"https://github.com/{full}"}
    st, meta = client.get(f"{API}/repos/{full}")
    if st in (0, None) or meta is None:
        return {**rec, "exists": None, "error": "unresolved",
                "note": "GitHub did not answer (network isolation, rate limit, or the repo is gone). "
                        "Treated as unverifiable, never as a failed build."}
    client.remember(f"{API}/repos/{full}", meta)
    rec.update({
        "exists": True, "description": (meta.get("description") or "")[:280],
        "language": meta.get("language"), "size_kb": meta.get("size", 0),
        "pushed_at": (meta.get("pushed_at") or "")[:10], "created_at": (meta.get("created_at") or "")[:10],
        "stars": meta.get("stargazers_count", 0), "forks": meta.get("forks_count", 0),
        "open_issues": meta.get("open_issues_count", 0), "archived": bool(meta.get("archived")),
        "default_branch": meta.get("default_branch") or "main",
        "license": (meta.get("license") or {}).get("spdx_id") if meta.get("license") else None,
        "topics": (meta.get("topics") or [])[:8], "owner_type": meta.get("owner", {}).get("type"),
        "homepage": meta.get("homepage"),
    })
    st, langs = client.get(f"{API}/repos/{full}/languages")
    if st == 200 and isinstance(langs, dict):
        client.remember(f"{API}/repos/{full}/languages", langs)
        total = sum(langs.values()) or 1
        rec["languages"] = {k: round(100.0 * v / total, 1) for k, v in
                           sorted(langs.items(), key=lambda kv: -kv[1])[:8]}
    st, readme = client.get(f"{API}/repos/{full}/readme")
    if st == 200 and isinstance(readme, dict) and readme.get("content"):
        try:
            text = base64.b64decode(readme["content"]).decode("utf-8", "replace")
            rec["readme_bytes"] = len(text)
            rec["readme_has_setup"] = bool(SETUP_RE.search(text))
            rec["readme_headings"] = [h.strip("# ").strip()[:40] for h in
                                      re.findall(r"^\s*#{1,4}\s*([^\n]{3,60})$", text, re.M)][:8]
        except Exception:
            rec["readme_bytes"] = 0
    st, tree = client.get(f"{API}/repos/{full}/git/trees/{rec['default_branch']}?recursive=1")
    if st == 200 and isinstance(tree, dict):
        paths = [t.get("path", "") for t in tree.get("tree", []) if t.get("type") == "blob"]
        tops = sorted({p.split("/")[0] for p in paths if "/" in p})
        rec["file_count"] = len(paths)
        rec["source_dirs"] = [d for d in tops if SRC_RE.search(d + "/")][:6] or \
                             [d for d in tops if not d.startswith(".")][:4]
        rec["test_paths"] = sorted({p for p in paths if TEST_RE.search(p)})[:4]
        rec["has_tests"] = bool(rec["test_paths"])
        rec["tree_truncated"] = bool(tree.get("truncated"))
        rec["entry_files"] = [p for p in ("README.md", "package.json", "requirements.txt",
                                         "pyproject.toml", "Dockerfile", "docker-compose.yml",
                                         "index.html") if p in paths]
    return rec


def search_candidates(client: Client, names: List[str]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for name in names:
        q = re.sub(r"[^a-z0-9 ]+", " ", name.lower()).strip()
        if len(q) < 3:
            continue
        st, data = client.get(f"{API}/search/repositories?q={urllib.parse.quote(q)}&per_page=5")
        if st != 200 or not isinstance(data, dict):
            out[name] = {"error": "search unresolved"}
            continue
        out[name] = [{"full_name": i.get("full_name"), "language": i.get("language"),
                      "stars": i.get("stargazers_count"), "pushed_at": (i.get("pushed_at") or "")[:10],
                      "description": (i.get("description") or "")[:140]}
                     for i in (data.get("items") or [])[:5]]
    return out


def record_candidates(client: "Client") -> bool:
    """Name-search every captured page that links no repository. Candidates only (§ A14):
    a search hit is never treated as the project's code, and the audit engine reads only
    `links.repo` from the capture itself."""
    caps = []
    for path in sorted(glob.glob(os.path.join(CAPTURE_DIR, "*.json"))):
        cap = json.load(open(path, encoding="utf-8"))
        if not (cap.get("links") or {}).get("repo"):
            caps.append(cap.get("name") or cap.get("id"))
    if not caps:
        print("no captured page lacks a repo link")
        return False
    print(f"🔎 name-searching {len(caps)} project(s) with no linked repo (candidates only)")
    found = search_candidates(client, caps[:12])
    with open(CANDIDATES_OUT, "w", encoding="utf-8") as fh:
        json.dump({"_note": "Search hits are CANDIDATES. Ownership is not asserted: the audit "
                           "engine only verifies repos the project page itself links (A14).",
                   "results": found}, fh, indent=1, sort_keys=True)
        fh.write("\n")
    print(f"✅ wrote {os.path.relpath(CANDIDATES_OUT, os.path.dirname(HERE))}")
    return True


def main() -> int:
    ap = argparse.ArgumentParser(description="Verify project artifacts via the GitHub API")
    ap.add_argument("--repos", nargs="*", default=[], help="explicit owner/name list")
    ap.add_argument("--from-captures", action="store_true", help="verify every repo linked by a captured page")
    ap.add_argument("--search-missing", action="store_true",
                    help="for projects with no linked repo, record name-search candidates (NOT verified ownership)")
    ap.add_argument("--budget", type=int, default=60, help="max API requests this run (A7)")
    ap.add_argument("--sleep", type=float, default=0.25)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--token-env", default="GITHUB_TOKEN")
    args = ap.parse_args()

    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    cache = {}
    if os.path.exists(STATE):
        try:
            cache = json.load(open(STATE, encoding="utf-8"))
        except Exception:
            cache = {}
    client = Client(os.environ.get(args.token_env), args.sleep, args.budget, args.dry_run, cache)

    pairs: List[Tuple[str, Optional[str]]] = [(None, r.strip()) for r in args.repos if r.strip()]
    if args.from_captures:
        pairs += linked_repos()
    searched = record_candidates(client) if (args.search_missing and not args.dry_run) else False
    if not pairs:
        # The candidate search above is the *only* thing an auditor with no linked repos can
        # run, so it must not hide behind this guard — and it must not exit non-zero either,
        # because "the pages link nothing" is a finding, not a failure of the tool.
        print("nothing to verify — pass --repos owner/name or capture pages with --from-captures"
              + (" · candidate search ran" if searched else ""))
        return 0 if searched else 1

    checks = {}
    if os.path.exists(CHECKS_OUT):
        checks = json.load(open(CHECKS_OUT, encoding="utf-8"))
    todo: List[str] = []
    for _pid, full in pairs:
        if full and (full not in checks or not checks[full].get("exists")):
            if full not in todo:
                todo.append(full)
    print(f"🔍 verifying {len(todo)} repository/repositories (budget {args.budget} requests)")
    try:
        for i, full in enumerate(todo):
            checks[full] = verify(client, full)
            c = checks[full]
            print(f"   {'✓' if c.get('exists') else '·'} {full:38} "
                  f"{(c.get('language') or '?'):10} {str(c.get('size_kb','?')):>7} KB "
                  f"push={c.get('pushed_at','?')} tests={'y' if c.get('has_tests') else 'n'} "
                  f"readme={c.get('readme_bytes', 0)}B setup={'y' if c.get('readme_has_setup') else 'n'}")
            time.sleep(args.sleep)
    except Budget as b:
        print(f"   ⏸ {b} — resuming later is free: results already fetched are kept")

    if not args.dry_run:
        checks.setdefault("_meta", {})["last_run"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        checks["_meta"]["requests_used"] = client.used
        with open(CHECKS_OUT, "w", encoding="utf-8") as fh:
            json.dump(checks, fh, indent=1, sort_keys=True)
            fh.write("\n")
        with open(STATE, "w", encoding="utf-8") as fh:
            json.dump(cache, fh)
        print(f"✅ wrote {os.path.relpath(CHECKS_OUT, os.path.dirname(HERE))} ({client.used} requests used)")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
