"""
Ideas Galore — Two-Tier Shard & Multi-Surface Emitter
=====================================================
Adapts the reference repo's tiered sharding (toolscour `shard_builder.py`) to a
hackathon *idea* corpus, and implements ADR-1, ADR-5, ADR-8, ADR-10.

Reads   pipeline/corpus.jsonl            (source of truth)
Writes  web/public/...                   (every read surface, one emitter)

  Tier 1  catalog-packed.json     dictionary-encoded rows for sub-5ms search,
                                  < 1.2 MB gzip hard budget (CI fails over it)
  Tier 2  data/details/*.json     per-domain deep records, lazy-loaded
          data/hackathons.json    event dimension table (ADR-2)
          data/moves.json         the transferable-trick vocabulary + postings
  Tabular data/ideas.csv          the literal tabular database (stable columns)
          data/pool.csv           same columns + provenance/why_not_promoted/would_settle_it
          data/ideas.ndjson       streaming/line-delimited for agents
          data/ideasgalore.sqlite.gz   optional SQL surface (only if < 4 MB)
  Meta    catalog-stats.json      counts for the UI badge
          manifest.json           hashes, budgets, generated_at (drift gate)

Ethics gate (ADR-12): authored prose lives ONLY in Tier 2 detail shards.
CSV/NDJSON carry `has_deep` so bulk exports never mirror the project text.

Usage:
  python3 pipeline/shard_builder.py            # build
  python3 pipeline/shard_builder.py --check    # rebuild + diff + parity + budgets
"""

from __future__ import annotations

import argparse
import datetime as dt
import csv
import gzip
import hashlib
import json
import os
import re
import sqlite3
import sys
import tempfile
from collections import Counter
from typing import Any, Dict, List, Optional, Tuple

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from taxonomy_hacks import (  # noqa: E402
    AUDIT_MANDATORY_FIELDS, AUDIT_PUBLISH_VERDICTS, AUDIT_STATUSES, AUDIT_VERSION,
    BANNED_VERDICT_WORDS, CSV_COLUMNS, DOMAINS, MOVES, POOL_CSV_COLUMNS, ROW_FORMAT, UNSHELVED,
    audit_rubric,
)

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CORPUS = os.path.join(REPO, "pipeline", "corpus.jsonl")
OUT_DEFAULT = os.path.join(REPO, "web", "public")

TIER1_GZIP_BUDGET_KB = 1200.0        # ADR-5/P5: hard ceiling, enforced below
SQLITE_BUDGET_KB = 4096.0            # dissent D1 concession: only commit while small
AUDITS_IN = os.path.join(os.path.dirname(os.path.abspath(CORPUS)), "audit.jsonl")
AUDIT_INDEX_BUDGET_KB = 40.0
AUDIT_SHEETS_BUDGET_KB = 240.0

HOOK_MAX = 140   # mechanism words live in the tail of a one-liner ("join-semilattice
                 # algebraic logic…"); 96 clipped them out of the Tier-1 index. 140
                 # costs ~4 KB across 165 rows and buys ~85x of the 1.2 MB budget back.

# CSV_COLUMNS / ROW_FORMAT are imported from taxonomy_hacks (single source with
# agents/schema.json + agents/openapi.json — A9, ADR-14).


def slugify(text: str) -> str:
    text = (text or "unclassified").lower().replace("&", "and")
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    return text or "unclassified"


class DictEncoder:
    """Repeated strings -> compact integers (the reference repo's Tier-1 trick)."""

    def __init__(self) -> None:
        self.map: Dict[str, int] = {}

    def id(self, value: str) -> int:
        value = value or "Other"
        if value not in self.map:
            self.map[value] = len(self.map)
        return self.map[value]

    def inverted(self) -> Dict[str, str]:
        return {str(v): k for k, v in self.map.items()}


def _days_ago(iso: Optional[str], today: dt.date) -> int:
    if not iso:
        return 9999
    try:
        d = dt.date.fromisoformat(iso[:10])
    except ValueError:
        return 9999
    return max(-1, (today - d).days)


def load_corpus(path: str = CORPUS) -> List[Dict[str, Any]]:
    if not os.path.exists(path):
        raise SystemExit(f"corpus not found: {path}\n"
                         f"run: python3 pipeline/ingest_seed.py  (or harvest_devpost.py)")
    rows = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


# ---------------------------------------------------------------------------
# build
# ---------------------------------------------------------------------------
def load_audits(path: str = AUDITS_IN) -> Dict[str, Dict[str, Any]]:
    """One sheet per audited project (docs/AUDIT_PANEL.md). A missing file is a legal
    pre-audit build: it means nothing has been promoted yet, not that all is well."""
    out: Dict[str, Dict[str, Any]] = {}
    if not os.path.exists(path):
        return out
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                sheet = json.loads(line)
                out[str(sheet["id"])] = sheet
    return out


def _pool_record(r: Dict[str, Any], sheet: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """A1: nothing is deleted, and nothing unverified is presented as vetted."""
    reasons: List[str] = []
    settle: List[str] = []
    provenance = "unaudited"
    if sheet is None:
        reasons.append("not_audited")
        settle += ["project page capture (deep)", "artifact check via repo_verify.py"]
    else:
        # `audited-hold`, not `unaudited`: a scored thin/duplicate record HAS been checked, and
        # labelling it otherwise is how a pool row gets re-audited by someone who cannot tell.
        provenance = "audited-hold"
        reasons.append("verdict:" + str(sheet.get("verdict")))
        wnp = sheet.get("why_not_promoted") or []
        reasons += [str(x) for x in ([wnp] if isinstance(wnp, str) else wnp)]
        settle += [u.get("missing", "") for u in (sheet.get("unknowns") or [])][:4]
        if sheet.get("duplicate_of"):
            reasons.append("duplicate_of:" + str(sheet["duplicate_of"]))
    out = {
        "id": str(r["id"]), "name": r.get("name"), "url": r.get("url"),
        "domain": r.get("domain"), "subsystem": r.get("subsystem"),
        "event": r.get("event_title"), "coolness": round(r.get("coolness", 0), 4),
        "moves": r.get("moves") or [], "specificity": r.get("specificity"),
        "summary": " ".join((r.get("summary") or "").split())[:280],
        "provenance": provenance,
        "why_not_promoted": reasons,
        "would_settle_it": [x for x in dict.fromkeys(settle) if x][:4] or [
            "a fetched project page and an artifact check"],
        "audit": None if sheet is None else {
            "verdict": sheet.get("verdict"), "worth": sheet.get("worth"),
            "soundness": sheet.get("soundness"), "soundness_score": sheet.get("soundness_score"),
            "rubric_coverage": sheet.get("rubric_coverage"), "audited_at": sheet.get("audited_at"),
            "unknowns": len(sheet.get("unknowns") or []), "duplicate_of": sheet.get("duplicate_of"),
            "hazard": bool(sheet.get("hazard") or {}), "evidence": len(sheet.get("evidence") or []),
            "reasons": sheet.get("verdict_reasons") or []},
    }
    # A held-but-scored record reads like an audit row, not an unchecked one: the same keys the
    # catalog and `data/audits.json` use, so one parser serves both surfaces and an agent
    # filtering pool.json on `verdict` gets the truth instead of a null.
    if sheet is not None:
        out["would_settle_it"] = sheet.get("would_settle_it") or out["would_settle_it"]
        for key in ("verdict", "worth", "soundness", "soundness_score", "rubric_coverage",
                    "audited_at"):
            out[key] = sheet.get(key)
        out["unknowns"] = len(sheet.get("unknowns") or [])
        out["repo_url"] = sheet.get("repo")
        # What we learned, not just what we rejected. A scored record has no file under
        # `data/audits/` - sheets are published only for admitted rows - so without this the
        # pool surface shows a held project as the Devpost marketing blurb and a verdict,
        # discarding the honest identity, the tested numbers and the disclosure we already
        # wrote for it. attaindesk sat there as "turns AI into one-click business operations
        # for SMBs" (the page's own register) next to an audit that had established it has
        # paying customers and measures nothing: a reader could not see either half.
        fields = sheet.get("fields") or {}
        detail = {}
        for key in ("what_it_is", "what_it_does", "how_they_tested",
                    "limits_they_disclosed", "numbers_with_arithmetic"):
            got = (fields.get(key) or {}).get("value")
            if got not in (None, "", [], {}):
                detail[key] = got
        if sheet.get("worth_note"):
            detail["worth_note"] = sheet["worth_note"]
        if detail:
            out["detail"] = detail
    return out


def build(records: List[Dict[str, Any]], out_dir: str, today: str,
          audits: Optional[Dict[str, Dict[str, Any]]] = None) -> Dict[str, Any]:
    # An empty audit set is meaningful, not a hole to fall back through: it publishes
    # nothing. (main() loads pipeline/audit.jsonl explicitly; a fixture build that wants
    # rows must say which of its records were vetted, or it silently reads real sheets.)
    audits = audits or {}
    os.makedirs(f"{out_dir}/data/details", exist_ok=True)

    dom_enc, sub_enc, stack_enc, move_enc, award_enc, ev_enc = (
        DictEncoder(), DictEncoder(), DictEncoder(), DictEncoder(), DictEncoder(), DictEncoder())

    rows: List[List[Any]] = []
    details: Dict[str, Dict[str, Any]] = {}
    move_postings: Dict[str, List[str]] = {m: [] for m in MOVES}
    events: Dict[str, Dict[str, Any]] = {}
    verdict_enc, worth_enc = DictEncoder(), DictEncoder()
    csv_rows: List[List[Any]] = []
    ndjson_rows: List[Dict[str, Any]] = []
    sql_projects: List[Tuple] = []
    sql_moves: List[Tuple[str, str]] = []
    sql_events: Dict[str, Tuple] = {}
    admitted = 0

    pool: List[Dict[str, Any]] = []
    pool_csv: List[List[Any]] = []
    audit_sheets: Dict[str, Dict[str, Any]] = {}
    for r in records:
        if not r.get("admitted", True):
            continue
        rid = str(r["id"])
        sheet = audits.get(rid)
        if sheet is None or not sheet.get("publishable"):
            pr = _pool_record(r, sheet)                   # A1: catalog is audited-only
            pool.append(pr)
            # A pool row is the same table with three more columns, because a 31-name header
            # over 10-value rows is a trap for anyone parsing it positionally.
            pcsv = _csv_cells(r, sheet, extra={
                "provenance": pr["provenance"],
                "why_not_promoted": "|".join(pr["why_not_promoted"]),
                "would_settle_it": "|".join(pr["would_settle_it"]),
            })
            pool_csv.append([pcsv[c] for c in POOL_CSV_COLUMNS])
            continue
        admitted += 1
        verdict_id = verdict_enc.id(sheet.get("verdict") or "thin")
        worth_id = worth_enc.id(sheet.get("worth") or "unrated")
        dslug = slugify(r.get("domain"))
        audit_sheets.setdefault(dslug, {})[rid] = sheet
        parts = r.get("coolness_parts") or {}
        hook = " ".join((r.get("summary") or "").split())[:HOOK_MAX]
        ev_key = r.get("event_slug") or r.get("event_title") or "unattributed"

        rows.append([
            rid,
            r.get("name", ""),
            hook,
            ev_enc.id(str(ev_key)),
            -1 if r.get("likes") is None else int(r["likes"]),
            int(round(r.get("coolness", 0) * 1000)),
            dom_enc.id(r.get("domain")),
            sub_enc.id(r.get("subsystem")),
            [move_enc.id(m) for m in (r.get("moves") or [])],
            [stack_enc.id(s) for s in (r.get("stack") or [])[:6]],
            1 if r.get("depth") == "deep" else 0,
            1 if r.get("thumbnail") else 0,
            award_enc.id(r.get("award") or "Unknown"),
            _days_ago(r.get("event_date"), dt.date.fromisoformat(today)),
            verdict_id, worth_id,
        ])

        details.setdefault(dslug, {})[rid] = _detail_record(r, sheet)

        for m in (r.get("moves") or []):
            if m in move_postings:
                move_postings[m].append(rid)

        ev_slot = events.setdefault(str(ev_key), {
            "id": str(ev_key),
            "title": r.get("event_title"),
            "organization": r.get("event_org"),
            "url": r.get("event_url"),
            "ended_at": r.get("event_date"),
            "registrations": r.get("event_registrations"),
            "prize_usd": r.get("event_prize_usd"),
            "themes": r.get("event_themes") or [],
            "winners_announced": r.get("event_winners_announced"),
            "project_count": 0,
        })
        ev_slot["project_count"] += 1

        csv_rows.append(_csv_row(r, sheet))
        ndjson_rows.append(_ndjson_record(r, sheet))
        sql_projects.append((
            rid, r.get("name"), r.get("url"), str(ev_key), r.get("domain"), r.get("subsystem"),
            r.get("coolness"), parts.get("engagement"), parts.get("validation"),
            parts.get("event_prestige"), parts.get("recency"), parts.get("specificity"),
            parts.get("signal_richness"), parts.get("redundancy"), r.get("likes"),
            r.get("award") or "Unknown", r.get("depth") or "listing", r.get("event_date"),
        ))
        for m in (r.get("moves") or []):
            sql_moves.append((rid, m))
        sql_events[str(ev_key)] = (
            str(ev_key), r.get("event_title"), r.get("event_org"), r.get("event_url"),
            r.get("event_registrations"), r.get("event_prize_usd"), r.get("event_date"),
        )

    modal: Dict[str, Dict[str, int]] = {}
    for r in records:
        if not r.get("admitted", True):
            continue
        k = str(r.get("event_slug") or r.get("event_title") or "unattributed")
        modal.setdefault(k, {})
        d = r.get("domain") or ""
        modal[k][d] = modal[k].get(d, 0) + 1
    for key, meta in events.items():
        top = max(modal.get(key, {}), key=modal.get(key, {}).get) if modal.get(key) else ""
        meta["hue"] = DOMAINS.get(top, {}).get("hue", "#8a7c5e")

    # The positional contract is public API: widening a row without updating
    # ROW_FORMAT would make every consumer misread every column. Fail at build time.
    if rows and any(len(x) != len(ROW_FORMAT) for x in rows):
        bad = max(rows, key=lambda x: len(x))
        raise SystemExit(f"row width {len(bad)} != len(ROW_FORMAT) {len(ROW_FORMAT)} — "
                         f"the Tier-1 positional contract drifted (row {bad[0]!r})")

    packed = {
        "schema_version": 1,
        "scoring_version": records[0].get("scoring_version", 1) if records else 1,
        "generated_at": today,
        "row_format": ROW_FORMAT,
        "domains": dom_enc.inverted(),
        "subsystems": sub_enc.inverted(),
        "stacks": stack_enc.inverted(),
        "moves": move_enc.inverted(),
        "awards": award_enc.inverted(),
        # keyed by the SAME integer the rows carry (ev_enc), not by slug —
        # otherwise Tier-1 consumers resolve event ids to nothing.
        "events": {str(eid): [slug, events[slug]["title"], events[slug]["organization"],
                              events[slug].get("registrations") or 0,
                              events[slug].get("prize_usd") or 0,
                              events[slug].get("hue") or "#8a7c5e"]
                   for slug, eid in ev_enc.map.items()},
        "verdicts": verdict_enc.inverted(),
        "worth": worth_enc.inverted(),
        "audit": {"audit_version": AUDIT_VERSION, "published_verdicts": AUDIT_PUBLISH_VERDICTS,
                  "index": "data/audits.json", "sheets": "data/audits/<sector>.json",
                  "pool": "data/pool.json", "rubric": "data/audit-rubric.json"},
        "sectors": {
            **{d: {"hue": v["hue"], "blurb": v["blurb"], "subsystems": list(v["subsystems"])}
               for d, v in DOMAINS.items()},
            UNSHELVED["name"]: {"hue": UNSHELVED["hue"], "blurb": UNSHELVED["blurb"],
                                "subsystems": ["Unclassified"]},
        },
        "rows": rows,
    }
    packed_path = f"{out_dir}/catalog-packed.json"
    raw = json.dumps(packed, separators=(",", ":")).encode("utf-8")
    with open(packed_path, "wb") as f:
        f.write(raw)
    gz_kb = len(gzip.compress(raw, compresslevel=9, mtime=0)) / 1024

    shard_sizes = {}
    for slug, bucket in sorted(details.items()):
        p = f"{out_dir}/data/details/{slug}.json"
        with open(p, "w", encoding="utf-8") as f:
            json.dump(bucket, f, separators=(",", ":"))
        shard_sizes[slug] = {"records": len(bucket), "kb": round(os.path.getsize(p) / 1024, 1)}

    with open(f"{out_dir}/data/hackathons.json", "w", encoding="utf-8") as f:
        json.dump({"generated_at": today, "events": sorted(
            events.values(), key=lambda e: -(e.get("project_count") or 0))},
            f, separators=(",", ":"), indent=None)

    with open(f"{out_dir}/data/sectors.json", "w", encoding="utf-8") as f:
        json.dump({"generated_at": today, "hue_policy": "chrome = vermilion, data = sector hues",
                   "sectors": {**{d: {"hue": v["hue"], "blurb": v["blurb"],
                                      "subsystems": list(v["subsystems"])} for d, v in DOMAINS.items()},
                                UNSHELVED["name"]: {"hue": UNSHELVED["hue"], "blurb": UNSHELVED["blurb"],
                                                    "subsystems": ["Unclassified"]}}},
                  f, separators=(",", ":"))

    moves_out = {"generated_at": today, "moves": {}}
    for move, spec in MOVES.items():
        ids = move_postings.get(move, [])
        moves_out["moves"][move] = {
            "definition": spec["definition"],
            "steal_this": spec["steal_this"],
            "count": len(ids),
            "examples": ids[:6],
        }
    with open(f"{out_dir}/data/moves.json", "w", encoding="utf-8") as f:
        json.dump(moves_out, f, separators=(",", ":"))

    _write_csv(f"{out_dir}/data/ideas.csv", csv_rows)
    with open(f"{out_dir}/data/ideas.ndjson", "w", encoding="utf-8") as f:
        for row in ndjson_rows:
            f.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")

    sqlite_kb = _write_sqlite(f"{out_dir}/data/ideasgalore.sqlite.gz", sql_events,
                             sql_projects, sql_moves)

    os.makedirs(f"{out_dir}/data/audits", exist_ok=True)
    audit_index = {rid: {
        "verdict": sh["verdict"], "worth": sh.get("worth"), "soundness": sh["soundness"],
        "soundness_score": sh["soundness_score"], "rubric_coverage": sh.get("rubric_coverage"),
        "checks": {k: v.get("status") for k, v in sh["checks"].items()},
        "unknowns": [u["field"] for u in sh.get("unknowns") or []],
        "evidence": len(sh.get("evidence") or []),
        "contradicted": sum(1 for e in (sh.get("evidence") or []) if e["status"] == "contradicted"),
        "hazard": bool(sh.get("hazard")), "repo": (sh.get("repo") or {}).get("url"),
        "audited_at": sh.get("audited_at"), "audit_version": sh.get("audit_version"),
        "url": sh.get("source_url"), "name": sh.get("name")}
        for slug in audit_sheets for rid, sh in audit_sheets[slug].items()}
    with open(f"{out_dir}/data/audits.json", "w", encoding="utf-8") as f:
        json.dump({"audit_version": AUDIT_VERSION, "generated_at": today,
                   "publishes": AUDIT_PUBLISH_VERDICTS,
                   "note": "Verdicts are derived from an evidence ledger over artifacts we could "
                           "actually reach. `unverifiable` is not `unsound` — see "
                           "docs/AUDIT_PROTOCOL.md.",
                   "records": audit_index}, f, separators=(",", ":"), indent=1)
    sheets_kb = 0.0
    for slug, bucket in audit_sheets.items():
        blob = json.dumps({"audit_version": AUDIT_VERSION, "generated_at": today, "records": bucket},
                          separators=(",", ":"), indent=1)
        with open(f"{out_dir}/data/audits/{slug}.json", "w", encoding="utf-8") as f:
            f.write(blob)
        sheets_kb += len(gzip.compress(blob.encode("utf-8"), compresslevel=9, mtime=0)) / 1024
    # Sweep sectors that no longer publish anything. A sheet file is addressed by a guessable path
    # (`data/audits/<sector>.json`, advertised for any sector in the agent API), so leaving an old
    # one behind publishes a *superseded* audit under a live URL: when Continuity and
    # Adversarial Compliance Matrix moved sectors, their Dev-Tooling sheet stayed on disk with the
    # pre-move `moves`, and `audit_sheets_kb` under-reported the bytes actually served by exactly that
    # file. Sector files are emitted, never inherited.
    for name in sorted(os.listdir(f"{out_dir}/data/audits")) if os.path.isdir(f"{out_dir}/data/audits") else []:
        if name.endswith(".json") and name[:-5] not in audit_sheets:
            os.remove(f"{out_dir}/data/audits/{name}")
            print(f"   🧹 swept superseded sheet file: data/audits/{name}")
    with open(f"{out_dir}/data/audit-rubric.json", "w", encoding="utf-8") as f:
        json.dump(audit_rubric(), f, indent=1, sort_keys=True)
    pool.sort(key=lambda x: -(x.get("coolness") or 0))
    with open(f"{out_dir}/data/pool.json", "w", encoding="utf-8") as f:
        json.dump({"audit_version": AUDIT_VERSION, "generated_at": today, "count": len(pool),
                   "meaning": "Records held out of the catalog. `provenance` splits them in two: "
                              "`unaudited` rows were never captured or checked; `audited-hold` rows "
                              "were captured, scored and held for cause (thin, duplicate or "
                              "hazard-capped) and carry the same audit columns the catalog does. "
                              "Neither kind is a judgement of merit — read why_not_promoted and "
                              "would_settle_it before quoting one (ADR-A1/A10).",
                   "records": pool}, f, separators=(",", ":"), indent=1)
    _write_csv(f"{out_dir}/data/pool.csv", pool_csv, header=POOL_CSV_COLUMNS)
    index_kb = len(gzip.compress(open(f"{out_dir}/data/audits.json", "rb").read(),
                                compresslevel=9, mtime=0)) / 1024
    stats = {
        "total": admitted,
        "audited_published": admitted,
        "pool_records": len(pool),
        # The pool is two different things and a reader must not confuse them: records we
        # captured, scored and held back for cause, and records nobody has looked at yet.
        "pool_audited_held": sum(1 for x in pool if x.get("provenance") == "audited-hold"),
        "pool_unaudited": sum(1 for x in pool if x.get("provenance") == "unaudited"),
        "audit_version": AUDIT_VERSION,
        "audit_index_kb": round(index_kb, 1),
        "audit_sheets_kb": round(sheets_kb, 1),
        "records_hazarded": sum(1 for sh in audit_index.values() if sh["hazard"]),
        # Held-but-scored records can carry hazard notes too, and a single number that mixes
        # the two populations would tell a reader the catalog is the whole story about
        # regulated claims when six times as many pages are sitting unreleased.
        "records_hazarded_held": sum(1 for x in pool
                                     if x.get("provenance") == "audited-hold"
                                     and (x.get("audit") or {}).get("hazard")),
        "domains": len(dom_enc.map),
        "subsystems": len(sub_enc.map),
        "moves": sum(1 for m in move_postings.values() if m),
        "events": len(events),
        "deep_records": sum(1 for r in records if r.get("depth") == "deep" and r.get("admitted", True)),
        "tier1_gzip_kb": round(gz_kb, 1),
        "tier1_budget_kb": TIER1_GZIP_BUDGET_KB,
        "sqlite_kb": sqlite_kb,
        "corpus_ingested": len(records),
        "held_back": hold_tally(records),
        "records_with_moves": sum(1 for r in records if r.get("moves") and r.get("admitted", True)),
        "coverage": coverage(records),
        "generated_at": today,
        "shards": shard_sizes,
    }
    with open(f"{out_dir}/catalog-stats.json", "w", encoding="utf-8") as f:
        json.dump(stats, f, separators=(",", ":"), indent=1)

    return stats


def _detail_record(r: Dict[str, Any], sheet: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Tier 2: the deep sheet payload, including the only place prose is stored.

    The audit rides along, minus the per-check prose (that lives in the sheet), so a
    reader of a detail record learns how strongly each claim is backed without a
    second request (A6, A9).
    """
    return {
        "id": str(r["id"]),
        "name": r.get("name"),
        "url": r.get("url"),
        "summary": r.get("summary"),
        "likes": r.get("likes"),
        "award": r.get("award") or "Unknown",
        "depth": r.get("depth") or "listing",
        "thumbnail": r.get("thumbnail"),
        "repo_url": r.get("repo_url"), "demo_url": r.get("demo_url"),
        "video_url": r.get("video_url"),
        "software_id": r.get("software_id"),
        "event": {"slug": r.get("event_slug"), "title": r.get("event_title"),
                  "org": r.get("event_org"), "url": r.get("event_url"),
                  "date": r.get("event_date"), "registrations": r.get("event_registrations"),
                  "prize_usd": r.get("event_prize_usd"), "themes": r.get("event_themes") or []},
        "domain": r.get("domain"),
        "subsystem": r.get("subsystem"),
        "domain_margin": r.get("domain_margin", 0),
        "moves": r.get("moves") or [],
        "stack": r.get("stack") or [],
        "built_with_observed": bool(r.get("built_with")),
        "coolness": r.get("coolness"),
        "coolness_parts": r.get("coolness_parts"),
        "specificity": r.get("specificity"),
        "provenance": r.get("provenance"),
        "inspiration_intel": r.get("inspiration_intel"),
        "quote": _condensed_quote(r),
        "harvested_at": r.get("harvested_at"),
        "taxonomy_version": r.get("taxonomy_version"),
        "scoring_version": r.get("scoring_version"),
        "audit": None if sheet is None else {
            "verdict": sheet.get("verdict"),
            "worth": sheet.get("worth"),
            "worth_note": sheet.get("worth_note"),
            "soundness": sheet.get("soundness"),
            "soundness_score": sheet.get("soundness_score"),
            "rubric_coverage": sheet.get("rubric_coverage"),
            "checks": {k: {"status": v.get("status"), "pass": v.get("pass"),
                           "weight": v.get("weight"), "why": v.get("why")}
                       for k, v in (sheet.get("checks") or {}).items()},
            "unknowns": sheet.get("unknowns") or [],
            "clone_cost": (sheet.get("fields") or {}).get("clone_cost", {}).get("value"),
            "what_to_steal": (sheet.get("fields") or {}).get("what_to_steal", {}).get("value"),
            "what_breaks_first": (sheet.get("fields") or {}).get("what_breaks_first", {}).get("value"),
            "prior_art": (sheet.get("fields") or {}).get("prior_art", {}).get("value") or [],
            "hazard": sheet.get("hazard"),
            "why_not_promoted": sheet.get("why_not_promoted") or [],
            "duplicate_of": sheet.get("duplicate_of"),
            "audited_at": sheet.get("audited_at"),
            "audit_version": sheet.get("audit_version"),
            "sheet": f"data/audits/{slugify(r.get('domain'))}.json#{r['id']}",
        },
    }


def _condensed_quote(r: Dict[str, Any]) -> Optional[str]:
    """
    A short quote (<= 220 chars) from the project's own 'how we built it' so a
    builder hears the team's voice, not our paraphrase, without us mirroring
    the whole page (ADR-12). Listing-depth records have none.
    """
    page = r.get("page") or {}
    src = page.get("how_we_built_it") or page.get("learned") or ""
    src = " ".join(str(src).split())
    if not src:
        return None
    return (src[:217] + "…") if len(src) > 220 else src


def _ndjson_record(r: Dict[str, Any], sheet: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Agent streaming record: full metadata, no mirrored prose (ADR-12), plus the audit
    verdict — so a consumer can tell vetted from unvetted without a second request."""
    out = {
        "id": str(r["id"]), "name": r.get("name"), "url": r.get("url"),
        "summary": r.get("summary"), "event": r.get("event_title"),
        "event_org": r.get("event_org"), "event_date": r.get("event_date"),
        "domain": r.get("domain"), "subsystem": r.get("subsystem"),
        "moves": r.get("moves") or [], "stack": r.get("stack") or [],
        "likes": r.get("likes"), "award": r.get("award") or "Unknown",
        "coolness": r.get("coolness"), "coolness_parts": r.get("coolness_parts"),
        # One definition for both tabular and streaming surfaces: a row is deep when we hold
        # the page (harvester blob or audit capture), not only when a harvester wrote it.
        "depth": r.get("depth"), "has_deep": 1 if (r.get("page") or r.get("depth") == "deep") else 0,
        # The bulk listing never carries links; a deep capture does, and the audit already
        # read them. Without the fallback the ndjson row says "no repo" for the one record in
        # the corpus whose repository *is* the reason it was published.
        "repo_url": r.get("repo_url"), "demo_url": r.get("demo_url"),
        "video_url": r.get("video_url"),
        "provenance": r.get("provenance"), "harvested_at": r.get("harvested_at"),
        "audit": None if sheet is None else {
            "verdict": sheet.get("verdict"), "worth": sheet.get("worth"),
            "soundness": sheet.get("soundness"), "soundness_score": sheet.get("soundness_score"),
            "rubric_coverage": sheet.get("rubric_coverage"),
            "checks": {k: v.get("status") for k, v in (sheet.get("checks") or {}).items()},
            "unknowns": [u.get("field") for u in (sheet.get("unknowns") or [])],
            "evidence": len(sheet.get("evidence") or []),
            "hazard": sheet.get("hazard"), "repo": (sheet.get("repo") or {}).get("url"),
            "audited_at": sheet.get("audited_at"), "audit_version": sheet.get("audit_version"),
            "sheet": f"data/audits/{slugify(r.get('domain'))}.json#{r['id']}",
        },
    }
    return out


def _csv_cells(r: Dict[str, Any], sheet: Optional[Dict[str, Any]],
               extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Every tabular cell keyed by its column *name*, so header and rows cannot drift.

    `sheet is None` leaves the audit columns blank rather than inventing a value: an empty
    `verdict` is how these surfaces say "nobody has checked", and the UI reads the same
    absence as `unaudited`. Rows were previously emitted in the pre-audit order — base
    columns first, audit block appended — under a header that *leads* with the audit block,
    which silently relabelled all 31 columns for anyone parsing positionally. A row is now
    `[cells[c] for c in COLUMNS]`, and `--check` compares header, row width and the `id`
    column against the JSON surfaces so the mistake cannot come back.
    """
    parts = r.get("coolness_parts") or {}
    sh = sheet or {}
    repo = sh.get("repo")
    cells: Dict[str, Any] = {
        "verdict": sh.get("verdict") or "",
        "worth": sh.get("worth") or ("unrated" if sheet else ""),
        "soundness": sh.get("soundness") or "",
        "soundness_score": sh.get("soundness_score") if sheet else "",
        "rubric_coverage": sh.get("rubric_coverage") if sheet else "",
        "audited_at": sh.get("audited_at") or "",
        "unknowns": len(sh.get("unknowns") or []) if sheet else "",
        "repo_url": (repo or {}).get("url") if isinstance(repo, dict) else (repo or ""),
        "id": str(r["id"]), "name": r.get("name"), "url": r.get("url"),
        "event": r.get("event_title") or "", "event_org": r.get("event_org") or "",
        "domain": r.get("domain"), "subsystem": r.get("subsystem"),
        "moves": "|".join(r.get("moves") or []), "stack": "|".join(r.get("stack") or []),
        "coolness": f"{r.get('coolness', 0):.4f}",
        "engagement": f"{parts.get('engagement', 0):.3f}",
        "validation": f"{parts.get('validation', 0):.3f}",
        "event_prestige": f"{parts.get('event_prestige', 0):.3f}",
        "recency": f"{parts.get('recency', 0):.3f}",
        "specificity": f"{parts.get('specificity', 0):.3f}",
        "signal_richness": f"{parts.get('signal_richness', 0):.3f}",
        "redundancy": f"{parts.get('redundancy', 0):.3f}",
        "likes": "" if r.get("likes") is None else r.get("likes"),
        "award": r.get("award") or "Unknown", "depth": r.get("depth") or "listing",
        "has_deep": 1 if r.get("depth") == "deep" else 0,
        "event_date": r.get("event_date") or "", "harvested_at": r.get("harvested_at") or "",
    }
    cells.update(extra or {})
    return cells


def _csv_row(r: Dict[str, Any], sheet: Optional[Dict[str, Any]],
             columns: Optional[List[str]] = None) -> List[Any]:
    cols = columns or CSV_COLUMNS
    cells = _csv_cells(r, sheet, extra={c: "" for c in cols if c not in CSV_COLUMNS})
    return [cells[c] for c in cols]


def _write_csv(path: str, rows: List[List[Any]], header: Optional[List[str]] = None) -> None:
    def esc(v: Any) -> str:
        s = "" if v is None else str(v)
        return '"' + s.replace('"', '""') + '"' if any(c in s for c in [",", '"', "\n"]) else s

    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(",".join(header or CSV_COLUMNS) + "\n")
        for row in rows:
            f.write(",".join(esc(v) for v in row) + "\n")


def _write_sqlite(path: str, events: Dict[str, Tuple], projects: List[Tuple],
                  moves: List[Tuple[str, str]]) -> Optional[float]:
    """Normalized SQL surface: events / projects / moves / project_moves."""
    tmp = path.replace(".gz", "")
    con = sqlite3.connect(tmp)
    cur = con.cursor()
    cur.executescript("""
      CREATE TABLE events(id TEXT PRIMARY KEY, title TEXT, organization TEXT, url TEXT,
                          registrations INTEGER, prize_usd INTEGER, ended_at TEXT);
      CREATE TABLE moves(name TEXT PRIMARY KEY, definition TEXT, steal_this TEXT);
      CREATE TABLE projects(
        id TEXT PRIMARY KEY, name TEXT, url TEXT, event_id TEXT REFERENCES events(id),
        domain TEXT, subsystem TEXT, coolness REAL, engagement REAL, validation REAL,
        event_prestige REAL, recency REAL, specificity REAL, signal_richness REAL,
        redundancy REAL, likes INTEGER, award TEXT, depth TEXT, event_date TEXT);
      CREATE TABLE project_moves(project_id TEXT, move TEXT,
                                 PRIMARY KEY(project_id, move));
      CREATE INDEX idx_projects_cool ON projects(coolness DESC);
      CREATE INDEX idx_projects_domain ON projects(domain);
    """)
    cur.executemany("INSERT OR REPLACE INTO events VALUES (?,?,?,?,?,?,?)", list(events.values()))
    from taxonomy_hacks import MOVES as M
    cur.executemany("INSERT OR REPLACE INTO moves VALUES (?,?,?)",
                    [(k, v["definition"], v["steal_this"]) for k, v in M.items()])
    cur.executemany("INSERT OR REPLACE INTO projects VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", projects)
    cur.executemany("INSERT OR REPLACE INTO project_moves VALUES (?,?)", moves)
    con.commit()
    con.close()
    size_before = os.path.getsize(tmp)
    with open(tmp, "rb") as f:
        # mtime=0: a gzipped artifact whose bytes depend on wall clock is not
        # a build output, it is a lottery ticket. Same input -> same bytes.
        blob = gzip.compress(f.read(), compresslevel=9, mtime=0)
    if size_before / 1024 > SQLITE_BUDGET_KB:
        os.remove(tmp)
        print(f"  ⚠ sqlite skipped: {size_before / 1024:.0f} KB > {SQLITE_BUDGET_KB:.0f} KB budget")
        return None
    with open(path, "wb") as f:
        f.write(blob)
    os.remove(tmp)
    return round(len(blob) / 1024, 1)


# ---------------------------------------------------------------------------
# gates (ADR-10)
# ---------------------------------------------------------------------------
def gate_checks(records: List[Dict[str, Any]], stats: Dict[str, Any], out_dir: str,
                audits: Optional[Dict[str, Dict[str, Any]]] = None) -> List[str]:
    problems: List[str] = []
    problems += audit_gate_checks(records, stats, out_dir, audits or {})
    if stats["tier1_gzip_kb"] > TIER1_GZIP_BUDGET_KB:
        problems.append(f"Tier-1 gzip {stats['tier1_gzip_kb']} KB exceeds budget {TIER1_GZIP_BUDGET_KB} KB")
    required = ("id", "name", "summary", "url", "domain", "coolness")
    for r in records:
        for k in required:
            if r.get(k) in (None, ""):
                problems.append(f"record {r.get('id')} missing required field '{k}'")
                break
    # parity: every surface must describe the same population
    counts: Dict[str, int] = {}
    with open(f"{out_dir}/data/ideas.csv", encoding="utf-8") as f:
        counts["csv"] = max(0, sum(1 for _ in f) - 1)
    counts["ndjson"] = sum(1 for _ in open(f"{out_dir}/data/ideas.ndjson", encoding="utf-8"))
    counts["tier2"] = sum(v["records"] for v in stats["shards"].values())
    counts["audits_index"] = len(json.load(open(f"{out_dir}/data/audits.json", encoding="utf-8"))["records"])
    counts["catalog_rows"] = stats["total"]
    if len(set(counts.values())) != 1:
        problems.append(f"catalog surface drift — every read surface must describe the same "
                        f"published population: {counts}")
    # The audited catalog and the pool are a PARTITION of what the quality gate admitted:
    # nothing admitted may vanish, nothing unaudited may sneak in (ADR-A1).
    admitted = len([r for r in records if r.get("admitted", True)])
    if stats["audited_published"] + stats["pool_records"] != admitted:
        problems.append(f"catalog({stats['audited_published']}) + pool({stats['pool_records']}) != "
                        f"admitted({admitted}) — the audit split must be a partition")
    if json.load(open(f"{out_dir}/data/pool.json", encoding="utf-8"))["count"] != stats["pool_records"]:
        problems.append("pool.json count disagrees with stats.pool_records")
    return problems


def audit_gate_checks(records, stats, out_dir, audits) -> List[str]:
    """The gates that make the audit load-bearing rather than decorative (A1/A2/A6/A8/A10)."""
    problems: List[str] = []
    try:
        with open(f"{out_dir}/catalog-packed.json", encoding="utf-8") as fh:
            packed = json.load(fh)
    except Exception as e:
        return [f"unreadable Tier-1: {e}"]
    ids = [row[0] for row in packed["rows"]]
    # Tabular alignment: a header that does not match its rows is worse than no table, because
    # every consumer reads the wrong column. Checked on the emitted bytes, not on the builder.
    for fname, cols, expect_verdict in (("data/ideas.csv", CSV_COLUMNS, True),
                                        ("data/pool.csv", POOL_CSV_COLUMNS, False)):
        try:
            with open(f"{out_dir}/{fname}", newline="", encoding="utf-8") as fh:
                table = list(csv.reader(fh))
        except OSError as e:
            problems.append(f"{fname}: {e}")
            continue
        if not table or table[0] != list(cols):
            problems.append(f"{fname}: header is not exactly {len(cols)} documented columns")
            continue
        bad = [i for i, row in enumerate(table[1:], 1) if len(row) != len(cols)]
        if bad:
            problems.append(f"{fname}: {len(bad)} row(s) with the wrong field count "
                            f"(first at line {bad[0] + 1})")
            continue
        at = {c: i for i, c in enumerate(cols)}
        csv_ids = {row[at["id"]] for row in table[1:]}
        json_ids = {str(x["id"]) for x in (
            [{"id": i} for i in ids] if expect_verdict
            else json.load(open(f"{out_dir}/data/pool.json", encoding="utf-8"))["records"])}
        if csv_ids != json_ids:
            problems.append(f"{fname}: id column disagrees with the JSON surface "
                            f"(csv-only {sorted(csv_ids - json_ids)[:3]}, json-only {sorted(json_ids - csv_ids)[:3]})")
        if expect_verdict:
            off = [row[at["verdict"]] for row in table[1:] if row[at["verdict"]] not in AUDIT_PUBLISH_VERDICTS]
            if off:
                problems.append(f"ideas.csv verdict column carries {sorted(set(off))[:3]} "
                                f"(only {AUDIT_PUBLISH_VERDICTS} may be published)")

    published = [str(r["id"]) for r in records
                 if r.get("admitted", True) and (audits.get(str(r["id"])) or {}).get("publishable")]
    if sorted(ids) != sorted(published):
        problems.append("Tier-1 rows are not exactly the audited-and-publishable set")
    # A page read has to show up on the row. Until the audit's captures were folded into ingest,
    # six vetted records published `depth: listing` with no artifact link while the sheet beside
    # them quoted their README — the row contradicted the audit. This is the pin.
    caps_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "raw", "deep_captures")
    if os.path.isdir(caps_dir):
        by_id = {str(r.get("id")): r for r in records}
        for name in sorted(os.listdir(caps_dir)):
            if not name.endswith(".json"):
                continue
            with open(os.path.join(caps_dir, name), encoding="utf-8") as fh:
                cap = json.load(fh)
            rid = str(cap.get("id") or name[:-5])
            row = by_id.get(rid)
            if row is None:
                continue  # a partial record set (a fixture) is not a missing row
            if row.get("depth") != "deep":
                problems.append(f"captured record {rid} publishes depth={row.get('depth')!r}: "
                                f"a full page read must not present itself as a listing row")
            links = cap.get("links") or {}
            for row_key, cap_key in (("repo_url", "repo"), ("demo_url", "demo"), ("video_url", "video")):
                if links.get(cap_key) and row.get(row_key) != links[cap_key]:
                    problems.append(f"{rid}: row {row_key}={row.get(row_key)!r} disagrees with the "
                                    f"page's own {links[cap_key]!r}")
    for rid in ids:
        sh = audits.get(rid)
        if not sh:
            problems.append(f"published record {rid} has no audit sheet")
            continue
        if sh.get("verdict") not in AUDIT_PUBLISH_VERDICTS:
            problems.append(f"{rid} published with non-publishable verdict {sh.get('verdict')!r}")
        empty = [k for k in AUDIT_MANDATORY_FIELDS if k not in (sh.get("fields") or {})]
        if empty:
            problems.append(f"{rid} published with unfiled mandatory fields: {empty}")
        for e in sh.get("evidence") or []:
            if e.get("status") not in AUDIT_STATUSES:
                problems.append(f"{rid}: evidence status {e.get('status')!r} is outside the rubric")
            if not e.get("source"):
                problems.append(f"{rid}: evidence {e.get('id')} has no source to check")
        if sh.get("duplicate_of") and sh["duplicate_of"] in ids:
            problems.append(f"{rid} is duplicate_of {sh['duplicate_of']} yet both are published")
    with open(f"{out_dir}/data/pool.json", encoding="utf-8") as fh:
        pool_ids = {p["id"] for p in json.load(fh)["records"]}
    for rid in ids:
        if rid in pool_ids:
            problems.append(f"{rid} appears in both the catalog and the pool")
    if stats.get("audit_index_kb", 0) > AUDIT_INDEX_BUDGET_KB:
        problems.append(f"audits index {stats['audit_index_kb']} KB over the {AUDIT_INDEX_BUDGET_KB} KB ceiling")
    if stats.get("audit_sheets_kb", 0) > AUDIT_SHEETS_BUDGET_KB:
        problems.append(f"audit sheets {stats['audit_sheets_kb']} KB over the {AUDIT_SHEETS_BUDGET_KB} KB ceiling")
    hits: List[str] = []
    for name in sorted(os.listdir(f"{out_dir}/data/audits")) if os.path.isdir(f"{out_dir}/data/audits") else []:
        if not name.endswith(".json"):
            continue
        with open(f"{out_dir}/data/audits/{name}", encoding="utf-8") as fh:
            for rid, sh in json.load(fh)["records"].items():
                blob = json.dumps(sh.get("fields") or {}, ensure_ascii=False).lower()
                blob += " " + str(sh.get("worth_note") or "").lower()
                # word-boundary + stem-tolerant: "implied" must not trip "lied"
                for w in BANNED_VERDICT_WORDS:
                    if re.search(r"\b" + w + r"\w*\b", blob):
                        hits.append(f"{rid}:{w}")
    if hits:
        problems.append(f"published audit text uses banned verdict language (A10): {hits[:6]}")
    return problems


def coverage(records, raw_dir=None) -> Optional[Dict[str, Any]]:
    """Cross-check the corpus against the sizes Devpost's own pagination reports. This
    is the field that stops a reader concluding "there are 165 hackathon projects worth
    stealing from" when the truth is "165 admitted out of 1,401 XPRIZE entries alone"."""
    raw_dir = raw_dir or os.path.join(os.path.dirname(os.path.abspath(CORPUS)), "raw")
    path = os.path.join(raw_dir, "gallery_totals.json")
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as fh:
        totals = json.load(fh)
    pub = Counter(r.get("event_key") for r in records if r.get("admitted", True))
    seen = Counter(r.get("event_key") for r in records)
    events = {}
    for slug, meta in totals.items():
        if slug.startswith("_") or not isinstance(meta, dict):
            continue
        up = meta.get("total_projects")
        events[slug] = {
            "published": pub.get(slug, 0),
            "ingested": seen.get(slug, 0),
            "upstream_total": up,
            "pages_captured": meta.get("pages_captured"),
            "coverage_pct": round(100.0 * pub.get(slug, 0) / up, 1) if up else None,
        }
    known = sum(v["published"] for v in events.values())
    return {
        "events": events,
        "published_total": sum(pub.values()),
        "published_in_sized_events": known,
        "upstream_total_known": sum(v["upstream_total"] or 0 for v in events.values()),
        "reading": "corpus is a quality-gated sample of the pages crawled, not the platform",
    }


def hold_tally(records) -> Dict[str, int]:
    t = Counter(r.get("hold_reason", "unspecified") for r in records if not r.get("admitted", True))
    return dict(t)


def corpus_as_of(records, override=None) -> str:
    """The corpus is a snapshot. Scores are computed as-of that snapshot, not as-of
    whatever day someone re-ran the packer: deriving the date from the newest
    `harvested_at` makes rebuilds byte-identical across days (ADR-10) and keeps
    `recency` from silently re-ranking the catalog every morning. Pass --today to
    opt into a re-dated refresh (the live harvest path)."""
    if override:
        return override
    days = [str(r.get("harvested_at") or "")[:10] for r in records if r.get("harvested_at")]
    return max(days) if days else dt.date.today().isoformat()


def main() -> int:
    ap = argparse.ArgumentParser(description="Emit all Ideas Galore read surfaces from corpus.jsonl")
    ap.add_argument("--out", default=OUT_DEFAULT)
    ap.add_argument("--corpus", default=CORPUS)
    ap.add_argument("--today", default=None,
                    help="as-of date for recency; defaults to the newest harvested_at in the corpus")
    ap.add_argument("--check", action="store_true", help="rebuild into temp dir and verify parity/budgets")
    args = ap.parse_args()

    records = load_corpus(args.corpus)
    today = corpus_as_of(records, args.today)
    print(f"📦 Packing {len(records)} hackathon projects into two-tier + tabular surfaces "
          f"(as-of {today})...")
    audits = load_audits()
    if audits:
        pub = sum(1 for sh in audits.values() if sh.get("publishable"))
        print(f"🔎 audit join: {len(audits)} sheet(s) · {pub} publishable → catalog · "
              f"{len(audits) - pub} audited-but-held · {len(records) - len(audits)} unaudited → pool")
    stats = build(records, args.out, today, audits)
    if stats["coverage"]:
        for slug, v in sorted(stats["coverage"]["events"].items()):
            print(f"   📏 coverage {slug}: {v['published']} published of {v['upstream_total']} "
                  f"listed ({v['coverage_pct']}%, {v['pages_captured']} pages captured)")

    corpus_sha = hashlib.sha256(open(args.corpus, "rb").read()).hexdigest()[:16]
    manifest = {
        "schema_version": 1,
        "coverage": stats["coverage"],
        "scoring_version": records[0].get("scoring_version", 1) if records else 1,
        "corpus_sha256": corpus_sha,
        "corpus_records": len(records),
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "audit_version": AUDIT_VERSION,
        "audited_published": stats["audited_published"],
        "pool_records": stats["pool_records"],
        "surfaces": {
            "tier1": "catalog-packed.json",
            "audit": ["data/audits.json", "data/audit-rubric.json",
                      *[f"data/audits/{s}.json" for s in sorted(stats["shards"])]],
            "pool": ["data/pool.json", "data/pool.csv", "data/promotion-queue.json"],
            "tier2": [f"data/details/{s}.json" for s in sorted(stats["shards"])],
            "dimensions": ["data/hackathons.json", "data/moves.json"],
            "tabular": ["data/ideas.csv", "data/ideas.ndjson"],
            "sql": "data/ideasgalore.sqlite.gz" if stats["sqlite_kb"] else None,
        },
        "budgets": {"tier1_gzip_kb": [stats["tier1_gzip_kb"], TIER1_GZIP_BUDGET_KB]},
    }
    with open(f"{args.out}/manifest.json", "w", encoding="utf-8") as f:
        json.dump(manifest, f, separators=(",", ":"), indent=1)

    held = stats.get("pool_audited_held", 0)
    print(f"🔎 audited catalog: {stats['audited_published']} published · "
          f"{stats['pool_records']} in the pool ({held} audited-but-held · "
          f"{stats['pool_records'] - held} never captured) · sheets {stats['audit_sheets_kb']} KB gz")
    print(f"✅ Tier 1: catalog-packed.json — {stats['tier1_gzip_kb']} KB gzip "
          f"(budget {TIER1_GZIP_BUDGET_KB:.0f} KB)")
    for slug, v in sorted(stats["shards"].items(), key=lambda kv: -kv[1]["records"]):
        print(f"   📁 data/details/{slug}.json — {v['records']} records, {v['kb']} KB")
    print(f"   🧵 data/moves.json — {stats['moves']} moves with postings")
    print(f"   🗄  data/ideas.csv + ideas.ndjson — {stats['total']} rows each"
          + (f", sqlite {stats['sqlite_kb']} KB gz" if stats["sqlite_kb"] else ""))

    try:
        from audit_projects import queue as _queue     # A7: same emitter, one build
        _queue(records, set(audits), 12, args.out)
    except Exception as e:
        print(f"   (promotion queue skipped: {e})")
    problems = gate_checks(records, stats, args.out, audits)
    if args.check:
        with tempfile.TemporaryDirectory() as td:
            build(records, td, today, audits)   # same inputs, or the rebuild proves nothing
            checked = 0
            for root, _dirs, files in os.walk(td):
                for name in sorted(files):
                    if name == "manifest.json":   # carries build time by design
                        continue
                    rel = os.path.relpath(os.path.join(root, name), td)
                    a, b = os.path.join(args.out, rel), os.path.join(td, rel)
                    if not os.path.exists(a):
                        problems.append(f"missing from committed build: {rel}")
                        continue
                    if hashlib.sha256(open(a, "rb").read()).digest() != hashlib.sha256(open(b, "rb").read()).digest():
                        problems.append(f"non-deterministic output: {rel} differs on rebuild")
                    checked += 1
            # The walk above proves every *emitted* file is committed and reproducible. It cannot see the
            # mirror-image failure — a committed file no build emits — because such a file is absent from
            # the temp tree and so is never visited. A stale surface is worse than a broken one: it
            # answers a reader's question with yesterday's answer, quietly. Sector audit sheets are where
            # that happened (a re-shelved record left its old sector file served, under a path the agent
            # API advertises for any sector), and `build()` owns that directory end to end, so the reverse
            # check is scoped to it. Generalising it requires every build step to declare the paths it owns
            # — `agents/` and the pool/detail shards are written elsewhere, and a whole-tree reverse walk
            # reports those as orphans. Recorded as an open item in docs/PARALLELISM_PANEL.md §10 rather
            # than half-built here.
            sheet_dir = os.path.join(args.out, "data/audits")
            if os.path.isdir(sheet_dir):
                for name in sorted(os.listdir(sheet_dir)):
                    rel = f"data/audits/{name}"
                    if name.endswith(".json") and not os.path.exists(os.path.join(td, rel)):
                        problems.append(f"served but not emitted: {rel} is in web/public and no build "
                                        "step writes it (delete it or emit it — a stale surface is a "
                                        "false one)")
            print(f"   🔁 determinism: {checked} surfaces byte-identical on rebuild")
    if problems:
        print("\n❌ BUILD GATE FAILED:")
        for p in problems[:20]:
            print("   -", p)
        return 1
    print(f"\n🟢 gates passed: budget, required fields, surface parity"
          f"{', determinism' if args.check else ''}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
