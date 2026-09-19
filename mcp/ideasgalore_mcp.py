#!/usr/bin/env python3
"""
Ideas Galore — MCP server (ADR-14)
=================================
A zero-dependency Model Context Protocol server over stdio that exposes the
static catalog as *tools*. It reads exactly the files the website reads, so an
agent and a browser can never disagree about what the corpus says — including the
audit: the catalog is audited-only, `audit_report` returns the same evidence sheet
the inspector panel renders, and pool records are only reachable when you ask for
them and always come back marked `vetted: false`.

    python3 mcp/ideasgalore_mcp.py --dir web/public          # local checkout
    python3 mcp/ideasgalore_mcp.py --base https://knarayanareddy.github.io/Ideasgalore

Test it by hand:

    printf '%s\n' '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}' \\
      '{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}' \\
      '{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"audit_report","arguments":{"id":"audionova","full":false}}}' \\
      | python3 mcp/ideasgalore_mcp.py --dir web/public

Protocol: JSON-RPC 2.0, `initialize` / `tools/list` / `tools/call`, no streaming,
no sampling, no writes. Ethics (docs/DATA_ETHICS.md): every result embeds the
project `url` and the event title, and derived fields are labelled — do not
present `provenance: derived` values as claims made by the project team.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

PROTOCOL = "2024-11-05"
SERVER = {"name": "ideas-galore", "version": "1.0.0",
          "description": "Hackathon-project inspiration index: scored projects, "
                         "transferable design moves, and generated idea collisions."}

BASE: Optional[str] = None
DIR: Optional[str] = None
_CACHE: Dict[str, Any] = {}


def load(path: str, refresh: bool = False) -> Any:
    """Load a catalog file from disk or HTTP, memoized per process."""
    key = path
    if key in _CACHE and not refresh:
        return _CACHE[key]
    if DIR:
        full = os.path.join(DIR, path)
        if not os.path.exists(full):
            raise FileNotFoundError(f"{full} not found — build it: python3 pipeline/shard_builder.py")
        with open(full, encoding="utf-8") as f:
            body = f.read()
    else:
        req = urllib.request.Request(f"{BASE}/{path}", headers={"User-Agent": "ideas-galore-mcp/1.0"})
        with urllib.request.urlopen(req, timeout=25) as resp:  # noqa: S310 (https base, no key)
            body = resp.read().decode("utf-8", "replace")
    data = None
    if path.endswith(".ndjson"):
        data = [json.loads(line) for line in body.splitlines() if line.strip()]
    elif path.endswith(".json"):
        data = json.loads(body)
    else:
        data = body
    _CACHE[key] = data
    return data


# ---------------------------------------------------------------------------
# index
# ---------------------------------------------------------------------------
class Index:
    """Decodes Tier-1 packed rows once; Tier-2 shards are loaded on demand."""

    def __init__(self) -> None:
        packed = load("catalog-packed.json")
        self.packed = packed
        self.domains = packed.get("domains", {})
        self.subsystems = packed.get("subsystems", {})
        self.moves = packed.get("moves", {})
        self.stacks = packed.get("stacks", {})
        self.awards = packed.get("awards", {})
        self.events = packed.get("events", {})
        self.rows: List[Dict[str, Any]] = []
        for r in packed.get("rows", []):
            row = {
                "id": r[0], "name": r[1], "hook": r[2],
                "event": (self.events.get(str(r[3])) or [None, None])[1],
                "event_org": (self.events.get(str(r[3])) or [None, None, None])[2],
                "event_hue": (self.events.get(str(r[3])) or [None] * 5)[5] if len(self.events.get(str(r[3])) or []) > 5 else None,
                "likes": None if r[4] == -1 else r[4],
                "coolness": r[5] / 1000.0,
                "domain": self.domains.get(str(r[6]), "Unclassified"),
                "subsystem": self.subsystems.get(str(r[7]), "General"),
                "moves": [self.moves.get(str(i), "") for i in r[8]],
                "stack": [self.stacks.get(str(i), "") for i in r[9]],
                "depth": "deep" if r[10] else "listing",
                "has_thumbnail": bool(r[11]),
                "award": self.awards.get(str(r[12]), "Unknown"),
                "event_age_days": r[13],
                "url": f"https://devpost.com/software/{r[0]}",
            }
            # audit layer (A9): the columns exist only in audits-built catalogs, so a
            # pre-audit build must still decode — absent means "unaudited", never "fine".
            vf, wf = packed.get("verdicts", {}), packed.get("worth", {})
            if len(r) > 15:
                row["verdict"] = vf.get(str(r[14]))
                row["worth"] = wf.get(str(r[15]))
                row["vetted"] = row["verdict"] in ("strong", "sound-with-caveats")
            else:
                row["verdict"] = row["worth"] = None
                row["vetted"] = False
            self.rows.append(row)
        self.by_id = {r["id"]: r for r in self.rows}
        self._shards: Dict[str, Dict[str, Any]] = {}
        self._audit_idx: Optional[Dict[str, Any]] = None
        self._pool: Optional[List[Dict[str, Any]]] = None
        self._moves_meta = load("data/moves.json").get("moves", {})

    def domain_slug(self, domain: str) -> str:
        d = (domain or "unclassified").lower().replace("&", "and")
        return re.sub(r"[^a-z0-9]+", "-", d).strip("-") or "unclassified"

    def shard(self, domain: str) -> Dict[str, Any]:
        slug = self.domain_slug(domain)
        if slug not in self._shards:
            try:
                self._shards[slug] = load(f"data/details/{slug}.json")
            except (FileNotFoundError, json.JSONDecodeError):
                self._shards[slug] = {}
        return self._shards[slug]

    def audit_index(self) -> Dict[str, Any]:
        """id -> {verdict, worth, score, coverage, checks(status), unknowns, sheet}.

        Missing file = a pre-audit build: return {} and let callers say "unaudited"."""
        if self._audit_idx is None:
            try:
                self._audit_idx = load("data/audits.json").get("records", {})
            except (FileNotFoundError, json.JSONDecodeError):
                self._audit_idx = {}
        return self._audit_idx

    def audit_sheet(self, rid: str) -> Optional[Dict[str, Any]]:
        """Full sheet for one id: every mandatory field with its value, evidence,
        confidence and the reason a status was assigned. Index entry as fallback."""
        row = self.by_id.get(rid)
        slug = self.domain_slug((row or {}).get("domain") or "unclassified")
        try:
            sheet = load(f"data/audits/{slug}.json").get("records", {}).get(rid)
        except (FileNotFoundError, json.JSONDecodeError):
            sheet = None
        return sheet or self.audit_index().get(rid)

    def pool(self) -> List[Dict[str, Any]]:
        """Records held out of the catalog (unaudited, thin, duplicate, hazard-blocked).
        These are leads, not inspiration: never present one as vetted."""
        if self._pool is None:
            try:
                self._pool = load("data/pool.json").get("records", [])
            except (FileNotFoundError, json.JSONDecodeError):
                self._pool = []
        return self._pool

    def detail(self, rid: str) -> Optional[Dict[str, Any]]:
        row = self.by_id.get(rid)
        if not row:
            return None
        return self.shard(row["domain"]).get(rid)


_idx: Optional[Index] = None


def idx() -> Index:
    global _idx
    if _idx is None:
        _idx = Index()
    return _idx


def _tokens(text: str) -> List[str]:
    return re.findall(r"[a-z]{3,}", (text or "").lower())


def _score_row(row: Dict[str, Any], terms: List[str]) -> float:
    hay = " ".join(_tokens(f"{row['name']} {row['hook']} {' '.join(row['moves'])} "
                           f"{row['domain']} {row['subsystem']} {' '.join(row['stack'])}"))
    if not terms:
        return row["coolness"]
    hits = sum(hay.count(t) for t in terms)
    return round(0.72 * row["coolness"] + 0.28 * min(1.0, hits / 3.0), 4)


def _cite(row: Dict[str, Any]) -> Dict[str, Any]:
    """Every payload carries attribution + honest absence markers (ethics.json)."""
    return {
        "id": row["id"], "name": row["name"], "devpost_url": row["url"],
        "hackathon": row["event"], "summary": row["hook"],
        "domain": row["domain"], "subsystem": row["subsystem"], "moves": row["moves"],
        "stack": row["stack"], "coolness": round(row["coolness"], 3),
        "likes": row["likes"], "likes_note": "null = not fetched, not zero" if row["likes"] is None else None,
        "award": row["award"], "depth": row["depth"],
        "verdict": row.get("verdict"), "worth": row.get("worth"),
        "vetted": bool(row.get("vetted")),
        "provenance_note": "domain/moves/coolness are derived by the index, not claims by the team",
        "audit_note": (None if row.get("verdict") else
                       "no audit verdict on this record — treat its claims as unaudited"),
    }


def _cite_pool(row: Dict[str, Any]) -> Dict[str, Any]:
    """Pool rows are the same shape plus an honest reason, so an agent can decide
    whether a lead is worth auditing before it cites anything."""
    return {
        "id": row["id"], "name": row.get("name"), "devpost_url": row.get("url"),
        "hackathon": row.get("event"), "summary": row.get("summary"),
        "domain": row.get("domain"), "subsystem": row.get("subsystem"),
        "moves": row.get("moves") or [], "coolness": row.get("coolness"),
        "vetted": False, "verdict": (row.get("audit") or {}).get("verdict"),
        "why_not_promoted": row.get("why_not_promoted") or [],
        "would_settle_it": row.get("would_settle_it") or [],
        "note": "held out of the catalog by the audit — a lead, not a vetted example",
    }


# ---------------------------------------------------------------------------
# tools
# ---------------------------------------------------------------------------
def search_projects(query: str = "", moves: Optional[List[str]] = None, domain: Optional[str] = None,
                    min_coolness: float = 0.0, has_repo: bool = False, depth: Optional[str] = None,
                    limit: int = 12, sort: str = "coolness", worth: Optional[str] = None,
                    include_pool: bool = False) -> Dict[str, Any]:
    """Catalog search. Only audited, publishable records are in the catalog, so every
    hit is a project a human checked against artifacts. `include_pool` adds the held-out
    records, clearly marked, for lead-mining."""
    idxs = idx()
    terms = _tokens(query)
    out = []
    if include_pool:
        pool_terms = terms
        for prow in idxs.pool():
            hay = " ".join(_tokens(f"{prow.get('name')} {prow.get('summary')} "
                                   f"{' '.join(prow.get('moves') or [])} {prow.get('domain')}"))
            if pool_terms and not any(t in hay for t in pool_terms):
                continue
            if domain and domain.lower() not in str(prow.get("domain") or "").lower():
                continue
            item = _cite_pool(prow)
            item["_score"] = round(0.4 * float(prow.get("coolness") or 0), 4)
            out.append(item)
    for row in idxs.rows:
        if row["coolness"] < min_coolness:
            continue
        if domain and domain.lower() not in row["domain"].lower():
            continue
        if depth and row["depth"] != depth:
            continue
        if moves and not set(moves) & set(row["moves"]):
            continue
        s = _score_row(row, terms)
        if terms and s <= 0.001:
            continue
        if worth and row.get("worth") != worth:
            continue
        item = _cite(row)
        item["_score"] = s
        if has_repo:
            det = idxs.detail(row["id"]) or {}
            if not det.get("repo_url"):
                continue
        out.append(item)
    if sort == "recency":
        out.sort(key=lambda r: (r["event_age_days"], -r["_score"]))
    else:
        out.sort(key=lambda r: (-r["_score"], r["name"]))
    pool_hits = sum(1 for r in out if not r.get("vetted"))
    return {"query": query, "matched": len(out), "returned": min(limit, len(out)),
            "results": out[:limit],
            "catalog_size": len(idxs.rows), "pool_returned": pool_hits,
            "attribution": "Cite devpost_url and hackathon when displaying these.",
            "vetting_note": ("results mix held-out pool records (vetted=false) with the "
                             "audited catalog" if pool_hits else
                             "every result passed the evidence audit") if out else
                            "no audited match — retry with include_pool=true to see leads"}


def get_project(id: str, include_prose: bool = True) -> Dict[str, Any]:  # noqa: A002
    idxs = idx()
    row = idxs.by_id.get(id)
    if not row:
        held = next((x for x in idxs.pool() if x.get("id") == id), None)
        if held:
            out = _cite_pool(held)
            out["found"] = "pool"
            out["audit"] = idxs.audit_sheet(id) or None
            out["hint"] = ("held out of the catalog by the audit; `audit_report` gives the "
                           "full sheet, `promotion_queue` gives the next steps")
            return out
        near = [r for r in idxs.rows if id.lower() in r["name"].lower() or id.lower() in r["id"]]
        return {"error": f"no record '{id}'", "did_you_mean": [_cite(r) for r in near[:5]],
                "hint": "ids are devpost slugs; try search_projects or include_pool=true"}
    det = idxs.detail(id) or {}
    payload = _cite(row)
    if det:
        payload["event_detail"] = det.get("event")
        payload["inspiration_intel"] = det.get("inspiration_intel")
        payload["coolness_parts"] = det.get("coolness_parts")
        payload["links"] = {"repo": det.get("repo_url"), "demo": det.get("demo_url"),
                            "video": det.get("video_url")}
        payload["team_quote"] = det.get("quote") if include_prose else None
        payload["provenance"] = det.get("provenance")
        payload["specificity"] = det.get("specificity")
        payload["domain_margin"] = det.get("domain_margin")
        payload["audit"] = det.get("audit") or idxs.audit_index().get(id)
        payload["kin_note"] = ("near-duplicate ids share a move+subsystem; see similar_to"
                                if det.get("coolness_parts", {}).get("redundancy", 0) > 0.5 else None)
    if payload.get("audit") is None:
        held = next((x for x in idxs.pool() if x.get("id") == id), None)
        if held:
            payload.update(_cite_pool(held))
            payload["hint"] = "in the pool, not the catalog — see audit_report(id) for the full sheet"
    return payload


def audit_report(id: str, full: bool = True) -> Dict[str, Any]:  # noqa: A002
    """The per-project audit sheet: what it is, what it does, whether it is
    technically sound, whether it is worth building — with citations per claim."""
    idxs = idx()
    sheet = idxs.audit_sheet(id)
    row = idxs.by_id.get(id)
    if sheet is None:
        held = next((x for x in idxs.pool() if x.get("id") == id), None)
        return {"id": id, "found": False,
                "why": "no audit sheet — never audited" if held is None else
                       "audited and held out of the catalog",
                "pool_row": held}
    out = {
        "id": id, "found": True, "name": sheet.get("name"),
        "audited_at": sheet.get("audited_at"), "audit_version": sheet.get("audit_version"),
        "source_url": sheet.get("source_url"),
        "verdict": sheet.get("verdict"), "publishable": sheet.get("publishable"),
        "worth": sheet.get("worth"), "worth_note": sheet.get("worth_note"),
        "soundness": sheet.get("soundness"), "soundness_score": sheet.get("soundness_score"),
        "rubric_coverage": sheet.get("rubric_coverage"),
        "verdict_reasons": sheet.get("verdict_reasons") or [],
        "why_not_promoted": sheet.get("why_not_promoted") or [],
        "hazard": sheet.get("hazard"), "duplicate_of": sheet.get("duplicate_of"),
        "unknowns": sheet.get("unknowns") or [],
        "evidence_count": len(sheet.get("evidence") or []),
        "repo": sheet.get("repo"), "right_of_reply": sheet.get("right_of_reply"),
        "in_catalog": row is not None,
        "how_to_read": "status=confirmed means we reproduced it from a reachable artifact; "
                       "unverifiable means the page made no checkable claim — it is not a debunking. "
                       "Quote unknowns verbatim instead of filling them in.",
    }
    if full:
        out["checks"] = sheet.get("checks") or {}
        out["fields"] = sheet.get("fields") or {}
        out["evidence"] = sheet.get("evidence") or []
    return out


def promotion_queue(limit: int = 10) -> Dict[str, Any]:
    """The highest-value unaudited records, with what would settle each one. This is the
    work list: fetch the page, check the artifact, re-run the audit."""
    try:
        q = load("data/promotion-queue.json")
    except (FileNotFoundError, json.JSONDecodeError):
        q = {}
    items = (q.get("candidates") or [])[:limit]
    return {"count": len(items), "queued": q.get("queued", len(items)),
            "pool_size": q.get("pool_size"), "total_pool": len(idx().pool()),
            "audit_version": q.get("audit_version"), "note": q.get("note"),
            "queue": items,
            "how_to_work_it": "for each: fetch the Devpost page, run repo_verify.py on any "
                              "linked repo, add a capture under pipeline/raw/deep_captures/, "
                              "then `make build` re-runs the audit and the gates"}


def audit_rubric() -> Dict[str, Any]:
    """The rubric itself, so an agent can audit new candidates the same way we did."""
    try:
        rub = load("data/audit-rubric.json")
    except (FileNotFoundError, json.JSONDecodeError):
        rub = {}
    return dict(rub, how_to_use=(
        "file all 12 mandatory fields with evidence {kind, source, locator, status}; "
        "statuses are recomputed mechanically, so hand-written verdicts are ignored; "
        "publish only if verdict is in " + "/".join(rub.get("published_verdicts", []))))


def list_moves(min_count: int = 1) -> Dict[str, Any]:
    meta = idx()._moves_meta
    out = {m: v for m, v in meta.items() if v.get("count", 0) >= min_count}
    return {"count": len(out), "moves": out,
            "how_to_use": "Pick the move that matches the *mechanism* you want, then "
                          "search_projects(moves=[...]) or read `examples` ids."}


def ideas_for_goal(goal: str, limit: int = 6) -> Dict[str, Any]:
    """
    Free text in, stealable patterns out: match the goal against move definitions
    and steal_this prose, then return the projects that demonstrate the winners.
    """
    terms = set(_tokens(goal))
    meta = idx()._moves_meta
    scored: List[Tuple[float, str]] = []
    for move, spec in meta.items():
        hay = " ".join(_tokens(f"{move} {spec.get('definition','')} {spec.get('steal_this','')}"))
        hits = len(terms & set(hay.split()))
        if hits:
            scored.append((hits / max(len(terms), 1), move))
    scored.sort(reverse=True)
    chosen = [m for _, m in scored[:3]] or list(meta)[:3]
    recs = search_projects(moves=chosen, limit=limit, sort="coolness")
    return {"goal": goal, "matched_moves": chosen,
            "move_guidance": [{"move": m, "steal_this": meta.get(m, {}).get("steal_this")} for m in chosen],
            "candidate_projects": recs["results"],
            "suggested_next_step": "Open two candidates from different domains and ask which "
                                   "mechanism transfers to your context unchanged."}


def similar_to(id: str, limit: int = 6) -> Dict[str, Any]:  # noqa: A002
    idxs = idx()
    row = idxs.by_id.get(id)
    if not row:
        return {"error": f"no record '{id}'"}
    scored = []
    for other in idxs.rows:
        if other["id"] == id:
            continue
        j = set(row["moves"]) & set(other["moves"])
        same_dom = row["domain"] == other["domain"]
        same_sub = row["subsystem"] == other["subsystem"]
        s = 2.2 * len(j) + (0.6 if same_sub else 0.0) + (0.25 if same_dom else 0.0) + 0.4 * other["coolness"]
        if s > 0:
            item = _cite(other)
            item["_why"] = {"shared_moves": sorted(j), "same_subsystem": same_sub, "same_domain": same_dom}
            scored.append((s, item))
    scored.sort(key=lambda t: -t[0])
    return {"source": _cite(row), "near": [i for _, i in scored[:limit]],
            "note": "ranked by shared moves first — parallel invention beats topical adjacency"}


def random_muse(seed: Optional[int] = None, min_coolness: float = 0.25) -> Dict[str, Any]:
    import random
    rows = [r for r in idx().rows if r["coolness"] >= min_coolness]
    pick = random.Random(seed).choice(rows) if rows else None
    return {"muse": _cite(pick) if pick else None,
            "prompt": "What constraint forced this design — and what is your equivalent constraint?"}


def remix_briefs(topic: Optional[str] = None, limit: int = 4) -> Dict[str, Any]:
    data = load("data/remixes.json")
    recipes = data.get("recipes", [])
    if topic:
        terms = set(_tokens(topic))
        recipes = [r for r in recipes
                   if terms & set(_tokens(f"{r.get('title','')} {r.get('why_these_two','')} "
                                          f"{r.get('the_wedge','')} {' '.join(r.get('starter_stack', []))}"))]
        recipes.sort(key=lambda r: -len(terms & set(_tokens(json.dumps(r, default=str).lower()))))
    return {"count": len(recipes), "briefs": recipes[:limit],
            "usage": "Treat first_48_hours as scaffolding and kill_criteria as a scope guard, "
                     "not as gospel. Parents are real corpus ids with urls."}


def explain_scoring() -> Dict[str, Any]:
    return {"formula": "coolness = 0.30·engagement + 0.22·validation + 0.14·event_prestige "
                       "+ 0.10·recency + 0.14·specificity + 0.10·signal_richness − 0.12·redundancy",
            "scoring_version": 1, "weights_public": True,
            "components": {
                "engagement": "log-scaled Devpost likes (null likes -> 0.22 prior, never 0)",
                "validation": "judge/editorial award tier",
                "event_prestige": "log registrations + log prize + featured/winners flags",
                "recency": "0.5 ** (age_days / 426)  (14-month half-life)",
                "specificity": "does the text state a mechanism (numbers, verbs, stack) or a vibe",
                "signal_richness": "depth + thumbnail + published links",
                "redundancy": "nearest-neighbour Jaccard of tokens; browse-time only"},
            "re_rank_hint": "subtract the terms you disagree with and re-sort; every component is per-record"}


TOOLS: Dict[str, Tuple[Any, Dict[str, Any], str]] = {
    "search_projects": (search_projects, {
        "type": "object", "properties": {
            "query": {"type": "string", "description": "free text over name+summary+moves+stack"},
            "moves": {"type": "array", "items": {"type": "string"}, "description": "filter by transferable trick, e.g. evidence-graph"},
            "domain": {"type": "string", "description": "sector name, substring match"},
            "min_coolness": {"type": "number", "minimum": 0, "maximum": 1},
            "has_repo": {"type": "boolean", "description": "only projects that published code"},
            "depth": {"type": "string", "enum": ["listing", "deep"]},
            "worth": {"type": "string", "enum": ["breakthrough", "strong", "niche", "tired"],
                      "description": "auditor's judgement of whether it is worth copying"},
            "include_pool": {"type": "boolean", "default": False,
                             "description": "also search records the audit held out (marked vetted=false)"},
            "limit": {"type": "integer", "minimum": 1, "maximum": 50, "default": 12},
            "sort": {"type": "string", "enum": ["coolness", "recency"]}}, "required": []},
        "Search the audited catalog by text, sector, or the design move it demonstrates. Every "
        "hit passed an evidence audit; include_pool adds held-out leads for mining. Returns "
        "cite-able rows with devpost_url + hackathon + verdict."),
    "get_project": (get_project, {
        "type": "object", "properties": {
            "id": {"type": "string", "description": "devpost slug, e.g. greenlight-nine-agent-production-crew"},
            "include_prose": {"type": "boolean", "default": True,
                              "description": "include the <=220-char team quote (honor ethics.json)"}},
        "required": ["id"]},
        "Full record: event detail, inspiration intel, score decomposition, links, provenance."),
    "ideas_for_goal": (ideas_for_goal, {
        "type": "object", "properties": {"goal": {"type": "string",
            "description": "describe the problem or feeling, not keywords"},
            "limit": {"type": "integer", "default": 6}}, "required": ["goal"]},
        "Turn a fuzzy goal into the moves that fit it, then the projects that prove them."),
    "similar_to": (similar_to, {
        "type": "object", "properties": {"id": {"type": "string"}, "limit": {"type": "integer", "default": 6}},
        "required": ["id"]},
        "Parallel invention: other projects demonstrating the same moves, ideally in another sector."),
    "list_moves": (list_moves, {
        "type": "object", "properties": {"min_count": {"type": "integer", "default": 1}}},
        "The 18-term transferable-trick vocabulary with definitions, steal_this, and postings."),
    "remix_briefs": (remix_briefs, {
        "type": "object", "properties": {"topic": {"type": "string"}, "limit": {"type": "integer", "default": 4}}},
        "Pre-generated idea collisions: pitch, wedge, starter stack, first 48 hours, kill criteria."),
    "random_muse": (random_muse, {
        "type": "object", "properties": {"seed": {"type": "integer"}, "min_coolness": {"type": "number", "default": 0.25}}},
        "One strong project at random, with the question worth asking about it."),
    "explain_scoring": (explain_scoring, {"type": "object", "properties": {}},
                         "The published ranking formula and how to re-rank the corpus yourself."),
    "audit_report": (audit_report, {
        "type": "object", "properties": {
            "id": {"type": "string", "description": "devpost slug"},
            "full": {"type": "boolean", "default": True,
                     "description": "include per-check reasoning, all 12 fields and the evidence ledger"}},
        "required": ["id"]},
        "The per-project audit: what it is/does, technical soundness with evidence, whether it "
        "is worth building, clone cost, what breaks first, and every named unknown."),
    "promotion_queue": (promotion_queue, {
        "type": "object", "properties": {"limit": {"type": "integer", "default": 10,
                                                    "minimum": 1, "maximum": 50}}},
        "Unaudited records worth promoting, with what would settle each one — the work list."),
    "audit_rubric": (audit_rubric, {"type": "object", "properties": {}},
                     "Mandatory fields, checks, weights, verdict ladder, dedup and hazard rules — "
                     "audit new candidates with it."),
}


# ---------------------------------------------------------------------------
# JSON-RPC plumbing
# ---------------------------------------------------------------------------
def tools_list() -> Dict[str, Any]:
    return {"tools": [{"name": n, "description": d, "inputSchema": s} for n, (_, s, d) in TOOLS.items()]}


def call(name: str, args: Dict[str, Any]) -> Dict[str, Any]:
    if name not in TOOLS:
        return {"isError": True, "content": [{"type": "text", "text": f"unknown tool {name}"}]}
    try:
        out = TOOLS[name][0](**{k: v for k, v in (args or {}).items()})
        return {"content": [{"type": "text", "text": json.dumps(out, ensure_ascii=False, indent=1)}]}
    except Exception as exc:  # noqa: BLE001
        return {"isError": True, "content": [{"type": "text", "text": f"{type(exc).__name__}: {exc}"}]}


def handle(msg: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    method = msg.get("method", "")
    if method.startswith("notifications/"):
        return None
    mid = msg.get("id")
    if method == "initialize":
        return {"jsonrpc": "2.0", "id": mid, "result": {
            "protocolVersion": PROTOCOL, "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": SERVER,
            "instructions": "Read-only hackathon inspiration index. Cite devpost_url; likes "
                            "null means not fetched; derived fields are labelled."}}
    if method in ("ping",):
        return {"jsonrpc": "2.0", "id": mid, "result": {}}
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": mid, "result": tools_list()}
    if method == "tools/call":
        params = msg.get("params") or {}
        return {"jsonrpc": "2.0", "id": mid, "result": call(params.get("name", ""), params.get("arguments") or {})}
    return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"method not found: {method}"}}


def main() -> int:
    global BASE, DIR
    ap = argparse.ArgumentParser(description="Ideas Galore MCP server (stdio)")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--dir", help="local web/public directory to read")
    g.add_argument("--base", default="https://knarayanareddy.github.io/Ideasgalore",
                   help="site root to fetch when --dir is not given")
    ap.add_argument("--selftest", action="store_true", help="run the tools and exit")
    args = ap.parse_args()
    DIR = os.path.abspath(args.dir) if args.dir else None
    BASE = None if DIR else args.base.rstrip("/")

    if args.selftest:
        checks = [search_projects(limit=2), get_project(id="tower-dq18x2"),
                  list_moves(), ideas_for_goal(goal="an agent I can't trust blindly"),
                  similar_to(id="greenlight-nine-agent-production-crew"),
                  random_muse(seed=7), remix_briefs(limit=1), explain_scoring()]
        for c in checks:
            assert c is not None
        print(f"🟢 selftest ok — {len(TOOLS)} tools, {len(idx().rows)} records in memory")
        return 0

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            print(json.dumps({"jsonrpc": "2.0", "id": None,
                              "error": {"code": -32700, "message": "parse error"}}), flush=True)
            continue
        resp = handle(msg)
        if resp is not None:
            try:
                sys.stdout.write(json.dumps(resp, ensure_ascii=False) + "\n")
                sys.stdout.flush()
            except BrokenPipeError:      # client hung up mid-response: not an error
                return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
