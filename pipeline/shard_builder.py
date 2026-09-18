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
import gzip
import hashlib
import json
import os
import re
import sqlite3
import sys
import tempfile
from typing import Any, Dict, List, Optional, Tuple

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from taxonomy_hacks import DOMAINS, MOVES, UNSHELVED  # noqa: E402

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CORPUS = os.path.join(REPO, "pipeline", "corpus.jsonl")
OUT_DEFAULT = os.path.join(REPO, "web", "public")

TIER1_GZIP_BUDGET_KB = 1200.0        # ADR-5/P5: hard ceiling, enforced below
SQLITE_BUDGET_KB = 4096.0            # dissent D1 concession: only commit while small
HOOK_MAX = 96

CSV_COLUMNS = [
    "id", "name", "url", "event", "event_org", "domain", "subsystem", "moves",
    "stack", "coolness", "engagement", "validation", "event_prestige", "recency",
    "specificity", "signal_richness", "redundancy", "likes", "award", "depth",
    "has_deep", "event_date", "harvested_at",
]


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
def build(records: List[Dict[str, Any]], out_dir: str, today: str) -> Dict[str, Any]:
    os.makedirs(f"{out_dir}/data/details", exist_ok=True)

    dom_enc, sub_enc, stack_enc, move_enc, award_enc, ev_enc = (
        DictEncoder(), DictEncoder(), DictEncoder(), DictEncoder(), DictEncoder(), DictEncoder())

    rows: List[List[Any]] = []
    details: Dict[str, Dict[str, Any]] = {}
    move_postings: Dict[str, List[str]] = {m: [] for m in MOVES}
    events: Dict[str, Dict[str, Any]] = {}
    csv_rows: List[List[Any]] = []
    ndjson_rows: List[Dict[str, Any]] = []
    sql_projects: List[Tuple] = []
    sql_moves: List[Tuple[str, str]] = []
    sql_events: Dict[str, Tuple] = {}
    admitted = 0

    for r in records:
        if not r.get("admitted", True):
            continue
        admitted += 1
        rid = str(r["id"])
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
        ])

        details.setdefault(slugify(r.get("domain")), {})[rid] = _detail_record(r)

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

        csv_rows.append([
            rid, r.get("name"), r.get("url"), r.get("event_title") or "", r.get("event_org") or "",
            r.get("domain"), r.get("subsystem"), "|".join(r.get("moves") or []),
            "|".join(r.get("stack") or []), f"{r.get('coolness', 0):.4f}",
            f"{parts.get('engagement', 0):.3f}", f"{parts.get('validation', 0):.3f}",
            f"{parts.get('event_prestige', 0):.3f}", f"{parts.get('recency', 0):.3f}",
            f"{parts.get('specificity', 0):.3f}", f"{parts.get('signal_richness', 0):.3f}",
            f"{parts.get('redundancy', 0):.3f}",
            "" if r.get("likes") is None else r.get("likes"),
            r.get("award") or "Unknown", r.get("depth") or "listing",
            1 if r.get("depth") == "deep" else 0,
            r.get("event_date") or "", r.get("harvested_at") or "",
        ])
        ndjson_rows.append(_ndjson_record(r))
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

    packed = {
        "schema_version": 1,
        "scoring_version": records[0].get("scoring_version", 1) if records else 1,
        "generated_at": today,
        "row_format": ["id", "name", "hook", "event_id", "likes", "coolness_x1000",
                       "domain_id", "subsystem_id", "move_ids[]", "stack_ids[]",
                       "is_deep", "has_thumbnail", "award_id", "event_age_days"],
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

    stats = {
        "total": admitted,
        "domains": len(dom_enc.map),
        "subsystems": len(sub_enc.map),
        "moves": sum(1 for m in move_postings.values() if m),
        "events": len(events),
        "deep_records": sum(1 for r in records if r.get("depth") == "deep" and r.get("admitted", True)),
        "tier1_gzip_kb": round(gz_kb, 1),
        "tier1_budget_kb": TIER1_GZIP_BUDGET_KB,
        "sqlite_kb": sqlite_kb,
        "generated_at": today,
        "shards": shard_sizes,
    }
    with open(f"{out_dir}/catalog-stats.json", "w", encoding="utf-8") as f:
        json.dump(stats, f, separators=(",", ":"), indent=1)

    return stats


def _detail_record(r: Dict[str, Any]) -> Dict[str, Any]:
    """Tier 2: the deep sheet payload, including the only place prose is stored."""
    return {
        "id": str(r["id"]),
        "name": r.get("name"),
        "url": r.get("url"),
        "summary": r.get("summary"),
        "likes": r.get("likes"),
        "award": r.get("award") or "Unknown",
        "depth": r.get("depth") or "listing",
        "thumbnail": r.get("thumbnail"),
        "repo_url": r.get("repo_url"),
        "demo_url": r.get("demo_url"),
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


def _ndjson_record(r: Dict[str, Any]) -> Dict[str, Any]:
    """Agent streaming record: full metadata, no mirrored prose (ADR-12)."""
    return {
        "id": str(r["id"]), "name": r.get("name"), "url": r.get("url"),
        "summary": r.get("summary"), "event": r.get("event_title"),
        "event_org": r.get("event_org"), "event_date": r.get("event_date"),
        "domain": r.get("domain"), "subsystem": r.get("subsystem"),
        "moves": r.get("moves") or [], "stack": r.get("stack") or [],
        "likes": r.get("likes"), "award": r.get("award") or "Unknown",
        "coolness": r.get("coolness"), "coolness_parts": r.get("coolness_parts"),
        "depth": r.get("depth"), "has_deep": 1 if r.get("page") else 0,
        "repo_url": r.get("repo_url"), "demo_url": r.get("demo_url"),
        "provenance": r.get("provenance"), "harvested_at": r.get("harvested_at"),
    }


def _write_csv(path: str, rows: List[List[Any]]) -> None:
    def esc(v: Any) -> str:
        s = "" if v is None else str(v)
        return '"' + s.replace('"', '""') + '"' if any(c in s for c in [",", '"', "\n"]) else s

    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(",".join(CSV_COLUMNS) + "\n")
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
def gate_checks(records: List[Dict[str, Any]], stats: Dict[str, Any], out_dir: str) -> List[str]:
    problems: List[str] = []
    if stats["tier1_gzip_kb"] > TIER1_GZIP_BUDGET_KB:
        problems.append(f"Tier-1 gzip {stats['tier1_gzip_kb']} KB exceeds budget {TIER1_GZIP_BUDGET_KB} KB")
    required = ("id", "name", "summary", "url", "domain", "coolness")
    for r in records:
        for k in required:
            if r.get(k) in (None, ""):
                problems.append(f"record {r.get('id')} missing required field '{k}'")
                break
    # parity: every surface must describe the same population
    counts = {"jsonl": len([r for r in records if r.get("admitted", True)])}
    with open(f"{out_dir}/data/ideas.csv", encoding="utf-8") as f:
        counts["csv"] = max(0, sum(1 for _ in f) - 1)
    counts["ndjson"] = sum(1 for _ in open(f"{out_dir}/data/ideas.ndjson", encoding="utf-8"))
    counts["tier2"] = sum(v["records"] for v in stats["shards"].values())
    if len(set(counts.values())) != 1:
        problems.append(f"surface count drift: {counts}")
    return problems


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
    stats = build(records, args.out, today)

    corpus_sha = hashlib.sha256(open(args.corpus, "rb").read()).hexdigest()[:16]
    manifest = {
        "schema_version": 1,
        "scoring_version": records[0].get("scoring_version", 1) if records else 1,
        "corpus_sha256": corpus_sha,
        "corpus_records": len(records),
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "surfaces": {
            "tier1": "catalog-packed.json",
            "tier2": [f"data/details/{s}.json" for s in sorted(stats["shards"])],
            "dimensions": ["data/hackathons.json", "data/moves.json"],
            "tabular": ["data/ideas.csv", "data/ideas.ndjson"],
            "sql": "data/ideasgalore.sqlite.gz" if stats["sqlite_kb"] else None,
        },
        "budgets": {"tier1_gzip_kb": [stats["tier1_gzip_kb"], TIER1_GZIP_BUDGET_KB]},
    }
    with open(f"{args.out}/manifest.json", "w", encoding="utf-8") as f:
        json.dump(manifest, f, separators=(",", ":"), indent=1)

    print(f"✅ Tier 1: catalog-packed.json — {stats['tier1_gzip_kb']} KB gzip "
          f"(budget {TIER1_GZIP_BUDGET_KB:.0f} KB)")
    for slug, v in sorted(stats["shards"].items(), key=lambda kv: -kv[1]["records"]):
        print(f"   📁 data/details/{slug}.json — {v['records']} records, {v['kb']} KB")
    print(f"   🧵 data/moves.json — {stats['moves']} moves with postings")
    print(f"   🗄  data/ideas.csv + ideas.ndjson — {stats['total']} rows each"
          + (f", sqlite {stats['sqlite_kb']} KB gz" if stats["sqlite_kb"] else ""))

    problems = gate_checks(records, stats, args.out)
    if args.check:
        with tempfile.TemporaryDirectory() as td:
            build(records, td, today)
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
