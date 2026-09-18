"""
Ideas Galore — Seed Ingest (offline, no network)
=================================================
Builds `pipeline/corpus.jsonl`, the single source of truth every artifact is
derived from (ADR-10). This is the *seed* path: it reads the curated raw
captures in `pipeline/raw/` and needs no internet, which is what makes the
repo rebuildable inside sandboxes, CI, or on a plane.

Inputs
------
  raw/seed_gallery.tsv   event_key \t slug \t name \t summary          (listing depth)
  raw/events.json        hackathon dimension table (from the public API)
  raw/deep_records.json   condensed authored sections for the Muse Set (deep depth)

Output
------
  corpus.jsonl           one enriched record per line, sorted by coolness desc

The same enrichment path (`taxonomy_hacks.enrich_project_record`) is used by
`harvest_devpost.py`, so seed and live records are indistinguishable downstream.

Usage:  python3 pipeline/ingest_seed.py [--today YYYY-MM-DD]
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
from typing import Any, Dict, List

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from taxonomy_hacks import compute_coolness, enrich_project_record, jaccard_kin  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
RAW = os.path.join(HERE, "raw")


def load_events(path: str) -> Dict[str, Dict[str, Any]]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)["events"]


def load_deep(path: str) -> Dict[str, Dict[str, Any]]:
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)["records"]


def parse_tsv(path: str) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.rstrip("\n")
            if not line.strip() or line.startswith("#"):
                continue
            parts = line.split("\t")
            if len(parts) < 4:
                print(f"  ! skipping malformed line: {line[:60]}")
                continue
            event_key, slug, name, summary = parts[0], parts[1], parts[2], "\t".join(parts[3:])
            rows.append({
                "id": slug,                    # canonical key = slug (never name — see R12)
                "slug": slug,
                "name": name.strip(),
                "summary": " ".join(summary.split()),
                "event_key": event_key,
                "url": f"https://devpost.com/software/{slug}",
                "depth": "listing",
                "source": "seed:gallery" if event_key != "showcase" else "showcase",
                "built_with": [],
                "likes": None,
                "award": None,
            })
    return rows


def load_overrides(path: str) -> Dict[str, Dict[str, Any]]:
    """
    Editorial correction layer (ADR-9: `provenance: editorial`).
    A classifier that cannot be overruled is a classifier that gets ignored.
    Keys are slugs; supported ops: domain, subsystem, award, moves_add, moves_drop.
    """
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def apply_override(rec: Dict[str, Any], ov: Dict[str, Any]) -> Dict[str, Any]:
    applied = []
    if ov.get("domain"):
        rec["domain"], applied = ov["domain"], applied + ["domain"]
    if ov.get("subsystem"):
        rec["subsystem"], applied = ov["subsystem"], applied + ["subsystem"]
    if ov.get("award"):
        rec["award"], applied = ov["award"], applied + ["award"]
    if ov.get("moves_add") or ov.get("moves_drop"):
        moves = list(rec.get("moves") or [])
        for m in ov.get("moves_add") or []:
            if m not in moves:
                moves.append(m)
        for m in ov.get("moves_drop") or []:
            if m in moves:
                moves.remove(m)
        rec["moves"], applied = moves, applied + ["moves"]
    if applied:
        rec["provenance"] = {**rec.get("provenance", {}), **{k: "editorial" for k in applied}}
    return rec


def main() -> int:
    ap = argparse.ArgumentParser(description="Build corpus.jsonl from committed raw captures")
    ap.add_argument("--today", default=None,
                    help="as-of date; defaults to the capture date in raw/ so rebuilds are deterministic")
    ap.add_argument("--out", default=os.path.join(HERE, "corpus.jsonl"))
    args = ap.parse_args()
    if not args.today:
        # Determinism rule: the seed build is a function of raw/, not of the clock.
        stamps = []
        # Both capture files stamp their own pull date; the newest one is the truth
        # about how current this snapshot is, so it anchors every derived date.
        for fname in ("deep_records.json", "events.json"):
            fp = os.path.join(RAW, fname)
            if not os.path.exists(fp):
                continue
            with open(fp, encoding="utf-8") as fh:
                blob = json.load(fh)
            pool = blob.get("records") or blob.get("events") or []
            recs = list(pool.values()) if isinstance(pool, dict) else list(pool)
            cand_dates = [r.get("harvested_at") or r.get("end_date") for r in recs if isinstance(r, dict)]
            for cand in [blob.get("harvested_at")] + cand_dates:
                day = str(cand or "")[:10]
                if len(day) == 10:
                    stamps.append(day)
        stamps = [x for x in stamps if len(x) == 10]
        args.today = max(stamps) if stamps else dt.date.today().isoformat()
        print(f"🗓  as-of date derived from raw captures: {args.today}")

    events = load_events(os.path.join(RAW, "events.json"))
    deep = load_deep(os.path.join(RAW, "deep_records.json"))
    overrides = load_overrides(os.path.join(RAW, "overrides.json"))
    rows = parse_tsv(os.path.join(RAW, "seed_gallery.tsv"))
    print(f"🌱 Seed ingest: {len(rows)} listing rows, {len(deep)} deep overrides, "
          f"{len(events)} events, {len(overrides)} editorial corrections")

    merged: List[Dict[str, Any]] = []
    for r in rows:
        ev = events.get(r["event_key"], {})
        rec = dict(r)
        override = deep.get(rec["slug"])
        if override:
            rec = {**rec, **override, "depth": "deep"}
            rec["source"] = "seed:deep"
        # event join (denormalize what the browser needs — ADR-2)
        rec.update({
            "event_slug": ev.get("slug"),
            "event_title": ev.get("title"),
            "event_org": ev.get("organization_name"),
            "event_url": ev.get("url"),
            "event_date": ev.get("ended_at"),
            "event_registrations": ev.get("registrations_count"),
            "prize_usd": ev.get("prize_usd"),
            "themes": ev.get("themes") or [],
            "featured_event": ev.get("featured"),
            "winners_announced": ev.get("winners_announced"),
            "harvested_at": args.today,
        })
        merged.append(rec)

    # near-duplicate / parallel-invention signal (descriptive only)
    kin = jaccard_kin({r["id"]: f"{r['name']} {r['summary']}" for r in merged})

    enriched: List[Dict[str, Any]] = []
    for r in merged:
        ev_meta = {
            "title": r.get("event_title"), "organization_name": r.get("event_org"),
            "registrations_count": r.get("event_registrations"), "prize_usd": r.get("prize_usd"),
            "themes": r.get("themes"), "featured": r.get("featured_event"),
            "winners_announced": r.get("winners_announced"), "ended_at": r.get("event_date"),
        }
        e = enrich_project_record(r, args.today, kin.get(r["id"], 0.0), ev_meta)
        ov = overrides.get(r["id"])
        if ov:
            e = apply_override(e, ov)
            if ov.get("award"):
                # An editorial award changes judge-validated weight, so re-rank it.
                e["coolness_parts"] = compute_coolness(
                    likes=e.get("likes"), award=e.get("award"),
                    registrations=e.get("event_registrations"), prize_usd=e.get("event_prize_usd"),
                    featured=e.get("event_featured"), winners_announced=e.get("event_winners_announced"),
                    event_date=e.get("event_date"), today=args.today, specificity=e["specificity"],
                    depth=e.get("depth", "listing"), has_thumbnail=bool(e.get("thumbnail")),
                    has_links=bool(e.get("repo_url") or e.get("demo_url") or e.get("video_url")),
                    kin_redundancy=e["coolness_parts"]["redundancy"],
                    staff_pick=(e.get("source") == "showcase"),
                )
                e["coolness"] = e["coolness_parts"]["total"]
        enriched.append(e)

    enriched.sort(key=lambda x: (-x["coolness"], x["id"]))
    with open(args.out, "w", encoding="utf-8") as f:
        for rec in enriched:
            f.write(json.dumps(rec, ensure_ascii=False, separators=(",", ":")) + "\n")

    kept = sum(1 for r in enriched if r["admitted"])
    print(f"✅ Wrote {len(enriched)} records -> {os.path.relpath(args.out, os.path.dirname(HERE))}"
          f"  (quality gate admitted {kept}, held back {len(enriched) - kept})")
    doms: Dict[str, int] = {}
    for r in enriched:
        doms[r["domain"]] = doms.get(r["domain"], 0) + 1
    for d, n in sorted(doms.items(), key=lambda kv: -kv[1]):
        print(f"   {n:>4}  {d}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
