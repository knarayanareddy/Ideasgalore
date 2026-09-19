"""
Ideas Galore — Devpost Harvester (agents 1 + 2 of the reference blueprint)
==========================================================================
Three tiers, priced by what recon measured (docs/EXPERT_PANEL.md R1–R7):

  L1 discover : GET https://devpost.com/api/hackathons?status[]=ended&...
                → event dimension records. 10 events per request, JSON, no auth.
  L2 gallery  : GET https://{slug}.devpost.com/project-gallery?page=N
                → ~24 listing rows per request. Cheapest breadth in the surface.
  L3 deep     : GET https://devpost.com/software/{slug}
                → likes, built-with tags, awards, links, condensed authored
                sections. Expensive: sampled, never uniform (ADR-3).

Politeness (ADR-12, enforced in code, not in a comment):
  * robots.txt fetched once, cached in pipeline/state/, honored (403 abort on deny)
  * minimum 1.25 s between requests, jittered
  * identifying User-Agent with a contact address
  * exponential backoff on 429/5xx, hard stop after --max-retries
  * resume state + append-only JSONL so a killed cron run loses nothing

Nothing here runs in CI by default: the site is built from committed
`pipeline/corpus.jsonl` (ADR-10). Requires network; stdlib only.

Usage
-----
  python3 pipeline/harvest_devpost.py discover --pages 4
  python3 pipeline/harvest_devpost.py gallery  --event xprize --pages 3
  python3 pipeline/harvest_devpost.py gallery  --from-state --max-events 25
  python3 pipeline/harvest_devpost.py deep     --limit 150
  python3 pipeline/harvest_devpost.py ingest                       # JSONL -> corpus.jsonl
  python3 pipeline/harvest_devpost.py all --events 25 --deep 150
  python3 pipeline/harvest_devpost.py discover --dry-run           # no writes
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import random
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, Iterable, List, Optional, Tuple

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from taxonomy_hacks import enrich_project_record, jaccard_kin  # noqa: E402

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATE_DIR = os.path.join(REPO, "pipeline", "state")
RAW_DIR = os.path.join(REPO, "pipeline", "raw")
GALLERY_OUT = os.path.join(RAW_DIR, "live_gallery.jsonl")
DEEP_OUT = os.path.join(RAW_DIR, "live_deep.jsonl")
EVENTS_OUT = os.path.join(RAW_DIR, "live_events.json")
STATE = os.path.join(STATE_DIR, "harvest_state.json")

# A crawler that hides is a crawler that gets blocked. Identify yourself.
USER_AGENT = ("IdeasGaloreBot/1.0 (+https://github.com/knarayanareddy/Ideasgalore; "
              "inspiration index; contact: repo issues)")
MIN_INTERVAL = 1.25          # ADR-12
ROBOTS_CACHE = os.path.join(STATE_DIR, "robots.txt")
API_HACKATHONS = "https://devpost.com/api/hackathons"

_last_request = [0.0]


# ---------------------------------------------------------------------------
# network
# ---------------------------------------------------------------------------
def _ensure_dirs() -> None:
    for d in (STATE_DIR, RAW_DIR):
        os.makedirs(d, exist_ok=True)


def polite_wait() -> None:
    elapsed = time.time() - _last_request[0]
    need = MIN_INTERVAL + random.uniform(0, 0.6)
    if elapsed < need:
        time.sleep(need - elapsed)
    _last_request[0] = time.time()


def robots_allowed(url: str, force: bool = False) -> bool:
    """
    Honor the operator's stated crawl policy (R6: `/` is open for `*`, a named
    set of AI harvesters is disallowed). Cached to disk; fails closed on error.
    """
    if os.environ.get("IDEAS_GALORE_IGNORE_ROBOTS") == "1" and force:
        return True
    polite_wait()
    try:
        with urllib.request.urlopen("https://devpost.com/robots.txt",
                                    timeout=20) as resp:
            text = resp.read().decode("utf-8", "replace")
        os.makedirs(STATE_DIR, exist_ok=True)
        with open(ROBOTS_CACHE, "w", encoding="utf-8") as f:
            f.write(text)
    except Exception as exc:  # noqa: BLE001
        if os.path.exists(ROBOTS_CACHE):
            text = open(ROBOTS_CACHE, encoding="utf-8").read()
        else:
            print(f"⚠ robots.txt unreachable ({exc}); failing closed")
            return False

    path = urllib.parse.urlparse(url).path or "/"
    disallow: List[str] = []
    agent = None
    for line in text.splitlines():
        line = line.split("#")[0].strip()
        m = re.match(r"[Uu]ser-agent:\s*(.+)", line)
        if m:
            agent = m.group(1).strip().lower()
            continue
        m = re.match(r"[Dd]isallow:\s*(.*)", line)
        if m and agent in ("*", "ideasgalorebot", "ideasgalorebot/1.0"):
            val = m.group(1).strip()
            if val:
                disallow.append(val)
    return not any(path.startswith(d) for d in disallow)


def fetch(url: str, max_retries: int = 3, dry: bool = False) -> Optional[str]:
    if dry:
        print(f"  [dry-run] GET {url}")
        return None
    if not robots_allowed(url):
        print(f"⛔ robots.txt disallows {url} — aborting this request (ADR-12)")
        return None
    for attempt in range(max_retries):
        polite_wait()
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT,
                                                       "Accept": "text/html,application/json"})
            with urllib.request.urlopen(req, timeout=30) as resp:
                return resp.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as exc:
            if exc.code in (429, 503):
                wait = 20 * (attempt + 1)
                print(f"  {exc.code} on {url} — backing off {wait}s")
                time.sleep(wait)
                continue
            if exc.code == 404:
                return None
            print(f"  HTTP {exc.code} on {url}")
        except Exception as exc:  # noqa: BLE001 network blips
            print(f"  error {exc} on {url}")
        time.sleep(1.5 * (attempt + 1))
    return None


def read_state() -> Dict[str, Any]:
    if os.path.exists(STATE):
        try:
            return json.load(open(STATE, encoding="utf-8"))
        except Exception:  # noqa: BLE001
            pass
    return {"events_done": [], "gallery_pages": {}, "deep_done": [], "last_run": None}


def write_state(state: Dict[str, Any]) -> None:
    _ensure_dirs()
    state["last_run"] = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    json.dump(state, open(STATE, "w", encoding="utf-8"), indent=1)


def append_jsonl(path: str, records: Iterable[Dict[str, Any]]) -> int:
    seen = set()
    if os.path.exists(path):
        for line in open(path, encoding="utf-8"):
            try:
                seen.add(str(json.loads(line).get("id")))
            except Exception:  # noqa: BLE001
                continue
    n = 0
    with open(path, "a", encoding="utf-8") as f:
        for r in records:
            if str(r.get("id")) in seen:
                continue
            f.write(json.dumps(r, ensure_ascii=False, separators=(",", ":")) + "\n")
            n += 1
    return n


def strip_tags(html: str) -> str:
    html = re.sub(r"(?is)<(script|style).*?</\1>", " ", html)
    html = re.sub(r"(?i)<br\s*/?>|</p>|</li>|</h[1-6]>", "\n", html)
    text = re.sub(r"(?s)<[^>]+>", " ", html)
    text = (text.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
                .replace("&quot;", '"').replace("&#39;", "'").replace("&nbsp;", " "))
    return re.sub(r"[ \t]+", " ", re.sub(r"\n\s*\n+", "\n", text)).strip()


# ---------------------------------------------------------------------------
# L1 · discover events (public JSON API — verified field names)
# ---------------------------------------------------------------------------
def parse_prize(html: Optional[str]) -> Optional[int]:
    """`prize_amount` ships as HTML ("$<span data-currency-value>2,000,000</span>")."""
    if not html:
        return None
    text = strip_tags(str(html))
    m = re.search(r"([\d,]+(?:\.\d+)?)\s*(k|m)?", text, re.IGNORECASE)
    if not m:
        return None
    val = float(m.group(1).replace(",", ""))
    if m.group(2):
        val *= 1000 if m.group(2).lower() == "k" else 1_000_000
    return int(val)


def discover(pages: int, order: str, status: str, dry: bool) -> Dict[str, Any]:
    events: Dict[str, Any] = {}
    if os.path.exists(EVENTS_OUT):
        try:
            events = json.load(open(EVENTS_OUT, encoding="utf-8")).get("events", {})
        except Exception:  # noqa: BLE001
            events = {}
    for page in range(1, pages + 1):
        url = (f"{API_HACKATHONS}?status[]={status}&order={order}"
               f"&challenge[]=featured&page={page}")
        body = fetch(url, dry=dry)
        if not body:
            url = f"{API_HACKATHONS}?status[]={status}&order={order}&page={page}"
            body = fetch(url, dry=dry)
        if not body:
            continue
        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            print(f"  ! page {page}: response was not JSON (markup/API drift?)")
            break
        got = 0
        for h in payload.get("hackathons", []):
            slug = None
            u = h.get("url") or ""
            m = re.match(r"https?://([a-z0-9\-]+)\.devpost\.com", u, re.IGNORECASE)
            if m:
                slug = m.group(1)
            if not slug:
                continue
            got += 1
            events[slug] = {
                "id": h.get("id"), "slug": slug, "title": h.get("title"),
                "organization_name": h.get("organization_name"), "url": u,
                "submission_gallery_url": h.get("submission_gallery_url"),
                "registrations_count": h.get("registrations_count"),
                "prize_usd": parse_prize(h.get("prize_amount")),
                "cash_prizes": (h.get("prizes_counts") or {}).get("cash"),
                "submission_period_dates": h.get("submission_period_dates"),
                "ended_at": None,  # date parse: pull the trailing year from the human string
                "themes": [t.get("name") for t in (h.get("themes") or [])],
                "featured": h.get("featured"), "winners_announced": h.get("winners_announced"),
                "invite_only": h.get("invite_only"), "open_state": h.get("open_state"),
            }
            ym = re.findall(r"(\w{3})\s+\d{1,2}\s*-\s*\w{3}\s+\d{1,2},?\s*(\d{4})",
                            h.get("submission_period_dates") or "")
            if ym:
                mon, year = ym[-1][0], ym[-1][1]
                days = {"Jan":1,"Feb":2,"Mar":3,"Apr":4,"May":5,"Jun":6,"Jul":7,"Aug":8,
                        "Sep":9,"Oct":10,"Nov":11,"Dec":12}
                events[slug]["ended_at"] = f"{year}-{days.get(mon, 12):02d}-28"
        print(f"  page {page}: +{got} events (corpus {len(events)})")
        if got == 0:
            break
    if not dry:
        _ensure_dirs()
        json.dump({"source": API_HACKATHONS, "harvested_at": dt.date.today().isoformat(),
                   "events": events}, open(EVENTS_OUT, "w", encoding="utf-8"),
                  separators=(",", ":"))
    return events


# ---------------------------------------------------------------------------
# L2 · project galleries (~24 listing rows per request — R4)
# ---------------------------------------------------------------------------
CARD_RE = re.compile(
    r'<a[^>]+href="(?:https://devpost\.com)?/software/(?P<slug>[a-z0-9][a-z0-9\-_]{2,80})"'
    r'(?:"[^>]*>|[^>]*>)', re.IGNORECASE)


def parse_gallery(html: str) -> List[Dict[str, Any]]:
    """
    Strategy: gallery cards are `<div class="thumbnail">` wrappers containing an
    anchor to /software/{slug}, an <h3>-ish name and a short description. We parse
    generously and let `ingest`'s floor assertions catch markup drift (ADR-10) —
    a crashed harvest beats a silently empty one.
    """
    out: Dict[str, Dict[str, Any]] = {}
    blocks = re.split(r"(?i)<div[^>]+class=\"[^\"]*(?:thumbnail|entry-box|software-box)[^\"]*\"", html)
    candidates: List[str] = blocks if len(blocks) > 2 else [html]
    for block in candidates:
        m = CARD_RE.search(block)
        if not m:
            continue
        slug = m.group("slug")
        if slug in ("search", "popular", "built-with"):
            continue
        name = None
        nm = re.search(r"(?is)<h[34][^>]*>(.*?)</h[34]>", block)
        if nm:
            name = strip_tags(nm.group(1))
        alt = re.search(r'(?i)alt="([^"]{4,90})"', block)
        if not name and alt:
            name = alt.group(1).split(" – ")[0].split(" - screenshot")[0]
        desc = None
        for dm in re.finditer(r"(?is)<p[^>]*>(.*?)</p>", block):
            txt = strip_tags(dm.group(1))
            if txt and len(txt) > 20:
                desc = txt
                break
        thumb = re.search(r'(?i)src="(//[^"]+|https://[^"]+)"\s+alt', block)
        if not name:
            continue
        out[slug] = {
            "id": slug, "slug": slug, "name": name.strip(),
            "summary": (desc or "").strip()[:600],
            "url": f"https://devpost.com/software/{slug}",
            "thumbnail": thumb.group(1) if thumb else None,
            "depth": "listing", "source": "gallery",
            "built_with": [], "likes": None, "award": None,
        }
    return list(out.values())


_TOTAL_RE = re.compile(r"(\d[\d,]*)\s*(?:\u2013|\u2014|-|\bto\b)\s*(\d[\d,]*)\s*of\s*(\d[\d,]*)", re.I)


def parse_gallery_total(html: str) -> Optional[int]:
    """Galleries print their own size ("1 - 24 of 1401"). Keep that number: without it,
    a four-page capture of 165 rows is indistinguishable from a complete index, which is
    the difference between a sample and a claim."""
    text = re.sub(r"<[^>]+>", " ", html or "")
    m = _TOTAL_RE.search(text)
    return int(m.group(3).replace(",", "")) if m else None


def record_gallery_total(slug: str, meta: Dict[str, Any]) -> None:
    """Observations about upstream size belong in raw/ (committed), not in the polite
    scratch state, so the published catalog can always state its own coverage."""
    path = os.path.join(RAW_DIR, "gallery_totals.json")
    data = {}
    if os.path.exists(path):
        try:
            data = json.load(open(path, encoding="utf-8"))
        except Exception:
            data = {}
    entry = dict(meta)
    entry["observed_at"] = dt.date.today().isoformat()
    entry["url"] = f"https://{slug}.devpost.com/project-gallery"
    data[slug] = {**data.get(slug, {}), **entry}
    data.setdefault("_note", "Sizes reported by Devpost gallery pagination. Coverage in "
                             "catalog-stats.json is computed from these: the corpus is a "
                             "gated sample of what was crawled, never the whole platform.")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=1, sort_keys=True)


def gallery_for_event(slug: str, pages: int, dry: bool):
    """Returns (rows, meta) where meta carries the gallery's reported total, so the
    caller can log coverage and stop early when the crawl is actually complete."""
    base = f"https://{slug}.devpost.com/project-gallery"
    collected: List[Dict[str, Any]] = []
    meta: Dict[str, Any] = {"pages_captured": 0, "total_projects": None, "per_page": None}
    for page in range(1, pages + 1):
        url = base if page == 1 else f"{base}?page={page}"
        html = fetch(url, dry=dry)
        if not html:
            break
        if meta["total_projects"] is None:
            meta["total_projects"] = parse_gallery_total(html)
        rows = parse_gallery(html)
        if not rows:
            print(f"  ⚠ {slug} page {page}: parsed 0 cards — markup may have changed. "
                  f"Add a parse strategy (see parse_gallery docstring).")
            break
        meta["per_page"] = meta["per_page"] or len(rows)
        for r in rows:
            r["event_key"] = slug
        collected.extend(rows)
        meta["pages_captured"] += 1
        if meta["total_projects"] and len(collected) >= meta["total_projects"]:
            print(f"  ✓ {slug}: captured all {meta['total_projects']} listed projects")
            break
        if len(rows) < 8:
            break
    return collected, meta


def cmd_gallery(args: argparse.Namespace) -> int:
    _ensure_dirs()
    state = read_state()
    events = json.load(open(EVENTS_OUT, encoding="utf-8"))["events"] if os.path.exists(EVENTS_OUT) else {}
    targets: List[str] = []
    if args.event:
        targets = [args.event]
    elif args.from_state:
        done = set(state.get("events_done", []))
        ranked = sorted(events.values(), key=lambda e: -(e.get("registrations_count") or 0))
        targets = [e["slug"] for e in ranked if e["slug"] not in done][: args.max_events]
    if not targets:
        print("no target events — run `discover` first, or pass --event SLUG")
        return 1

    total = 0
    for slug in targets:
        rows, meta = gallery_for_event(slug, args.pages, args.dry_run)
        added = append_jsonl(GALLERY_OUT, rows) if rows else 0
        total += added
        cov = (f" · {100.0 * len(rows) / meta['total_projects']:.1f}% of "
               f"{meta['total_projects']} listed") if meta.get("total_projects") else ""
        print(f"🖼  {slug}: {len(rows)} cards parsed, {added} new{cov}")
        if not args.dry_run and meta.get("total_projects"):
            record_gallery_total(slug, meta)
        if not args.dry_run:
            state.setdefault("events_done", []).append(slug)
            state["gallery_pages"] = state.get("gallery_pages", {})
            state["gallery_pages"][slug] = args.pages
    if not args.dry_run:
        write_state(state)
    print(f"\n✅ gallery tier: {total} new listing rows -> {os.path.relpath(GALLERY_OUT, REPO)}")
    return 0


# ---------------------------------------------------------------------------
# L3 · deep project pages (likes, tags, awards, authored sections)
# ---------------------------------------------------------------------------
SECTION_TITLES = {
    "inspiration": r"inspiration", "what_it_does": r"what (it does|this project does)",
    "how_we_built_it": r"how (we|i|they) (built|made|created)",
    "challenges": r"challenges", "accomplishments": r"accomplishments",
    "learned": r"what we learned|what i learned", "next": r"what.?s next",
}


def parse_project_page(html: str, slug: str) -> Dict[str, Any]:
    rec: Dict[str, Any] = {"id": slug, "slug": slug, "depth": "deep", "source": "deep",
                           "built_with": [], "likes": None, "award": None}
    m = re.search(r'href="https://devpost\.com/software/([a-z0-9\-_]+)"', html)
    rec["url"] = m.group(0).replace('href="', "").rstrip('"') if m else f"https://devpost.com/software/{slug}"

    t = re.search(r"(?is)<title>(.*?)</title>", html)
    if t:
        rec["name"] = re.sub(r"\s*[|–-]\s*Devpost\s*$", "", strip_tags(t.group(1))).strip()

    lm = re.search(r"([\d,]+)\s+people like this", strip_tags(html))
    if lm:
        rec["likes"] = int(lm.group(1).replace(",", ""))
    sid = re.search(r"software_id(?:%5D|\])=(\d+)", html)
    if sid:
        rec["software_id"] = int(sid.group(1))

    tags = re.findall(r"/software/built-with/([a-z0-9\-_.]+)", html)
    seen: List[str] = []
    for tag in tags:
        if tag not in seen:
            seen.append(tag)
    rec["built_with"] = seen[:10]

    # H2 sections, in document order, with the heading set as the boundary
    body = strip_tags(html)
    heads = [(m.start(), m.group(1)) for m in re.finditer(
        r"(?im)^\s*(Inspiration|What (?:it|this project) does|How (?:we|i|they) "
        r"(?:built|made|created)[^\n]*|Challenges (?:we|i) (?:ran|came) [^\n]*|"
        r"Accomplishments[^\n]*|What (?:we|i) learned|What.?s next[^\n]*)\s*$", body)]
    for i, (pos, title) in enumerate(heads):
        key = next((k for k, pat in SECTION_TITLES.items() if re.search(pat, title, re.IGNORECASE)), None)
        if not key:
            continue
        chunk = body[pos + len(title):heads[i + 1][0] if i + 1 < len(heads) else len(body)]
        chunk = " ".join(chunk.split())
        if chunk and key not in rec.setdefault("page", {}):
            rec["page"][key] = chunk[:900]

    aw = re.search(r"(?i)(grand prize|best (?:of|overall)[^<]{0,40}|1st place|winner[^<]{0,40}|"
                   r"honorable mention|finalist)", body[:40000])
    if aw:
        txt = aw.group(1).strip()
        low = txt.lower()
        rec["award"] = ("Grand Prize / Overall Winner" if "grand" in low or "best overall" in low
                        else "Finalist / Semi-Finalist" if "finalist" in low
                        else "Honorable Mention" if "honorable" in low
                        else "Best in Track / Category Winner")

    gh = re.search(r'href="(https?://(?:www\.)?github\.com/[^"\s]+)"', html)
    if gh:
        rec["repo_url"] = gh.group(1)
        rec["open_source"] = True
    demo = re.search(r'href="(https?://[^"]+)"[^>]*>\s*(?:Try it out|View Live|Demo|Website)', html)
    if demo:
        rec["demo_url"] = demo.group(1)
    yt = re.search(r'href="(https://(?:www\.)?youtube\.com/watch\?v=[\w\-]+)"', html)
    if yt:
        rec["video_url"] = yt.group(1)
    if not rec.get("name"):
        rec["name"] = slug.replace("-", " ").title()
    if not rec.get("page"):
        rec.pop("page", None)
    return rec


def cmd_deep(args: argparse.Namespace) -> int:
    _ensure_dirs()
    listings: Dict[str, Dict[str, Any]] = {}
    if os.path.exists(GALLERY_OUT):
        for line in open(GALLERY_OUT, encoding="utf-8"):
            try:
                r = json.loads(line)
                listings.setdefault(str(r["id"]), r)
            except Exception:  # noqa: BLE001
                continue
    done = set(read_state().get("deep_done", []))
    # Priority: mechanism-rich summaries first — depth is expensive (P1/ADR-3).
    order = sorted(listings.values(),
                   key=lambda r: -(len(r.get("summary") or "") + 3 * len(r.get("name") or "")))
    todo = [r for r in order if r["slug"] not in done][: args.limit]
    print(f"🔎 deep tier: {len(todo)} of {len(listings)} listings queued "
          f"(~{len(todo) * MIN_INTERVAL / 60:.1f} min of polite waiting)")
    written = append_jsonl(DEEP_OUT, [])  # seed dedupe index
    out_handle = open(DEEP_OUT, "a", encoding="utf-8")
    got = 0
    for i, r in enumerate(todo, 1):
        html = fetch(r["url"], dry=args.dry_run)
        if not html:
            continue
        deep = parse_project_page(html, r["slug"])
        merged = {**r, **{k: v for k, v in deep.items() if v not in (None, [], {})}}
        merged["depth"] = "deep"
        merged["source"] = "deep"
        if args.dry_run:
            print(f"  [dry-run] would store {merged['slug']}")
            continue
        out_handle.write(json.dumps(merged, ensure_ascii=False, separators=(",", ":")) + "\n")
        out_handle.flush()
        got += 1
        state = read_state()
        state.setdefault("deep_done", []).append(r["slug"])
        write_state(state)
        if i % 25 == 0:
            print(f"  …{i}/{len(todo)} (written {got + written})")
    if not args.dry_run:
        out_handle.close()
    print(f"✅ deep tier: {got + written} records -> {os.path.relpath(DEEP_OUT, REPO)}")
    return 0


# ---------------------------------------------------------------------------
# ingest: live JSONL -> corpus.jsonl (same enrichment as the seed path)
# ---------------------------------------------------------------------------
def cmd_ingest(args: argparse.Namespace) -> int:
    today = dt.date.today().isoformat()
    events = {}
    if os.path.exists(EVENTS_OUT):
        events = json.load(open(EVENTS_OUT, encoding="utf-8")).get("events", {})
    elif os.path.exists(os.path.join(RAW_DIR, "events.json")):
        events = json.load(open(os.path.join(RAW_DIR, "events.json"), encoding="utf-8"))["events"]

    merged: Dict[str, Dict[str, Any]] = {}
    for path in (GALLERY_OUT, DEEP_OUT):
        if not os.path.exists(path):
            continue
        for line in open(path, encoding="utf-8"):
            try:
                r = json.loads(line)
            except Exception:  # noqa: BLE001
                continue
            key = str(r["id"])
            merged[key] = {**merged.get(key, {}), **r}
    if not merged:
        print("no live captures found — run `discover`, `gallery`, `deep` first")
        return 1

    kin = jaccard_kin({k: f"{v.get('name')} {v.get('summary')}" for k, v in merged.items()})
    out: List[Dict[str, Any]] = []
    for key, r in merged.items():
        ev = events.get(r.get("event_key") or "", {})
        r.setdefault("url", f"https://devpost.com/software/{key}")
        r.setdefault("harvested_at", today)
        r["event_slug"] = ev.get("slug") or r.get("event_key")
        r["event_title"] = r.get("event_title") or ev.get("title")
        r["event_date"] = r.get("event_date") or ev.get("ended_at")
        rec = enrich_project_record(r, today, kin.get(key, 0.0), {
            "title": ev.get("title"), "organization_name": ev.get("organization_name"),
            "registrations_count": ev.get("registrations_count"), "prize_usd": ev.get("prize_usd"),
            "themes": ev.get("themes"), "featured": ev.get("featured"),
            "winners_announced": ev.get("winners_announced"), "ended_at": ev.get("ended_at"),
        })
        out.append(rec)

    # floor assertion (ADR-10): never publish a collapse
    prev = 0
    if os.path.exists(args.out):
        prev = sum(1 for _ in open(args.out, encoding="utf-8"))
    if prev and len(out) < 0.6 * prev and not args.allow_shrink:
        print(f"❌ refusing to write {len(out)} records — previous corpus had {prev} "
              f"(<60% floor). If this is intended, pass --allow-shrink.")
        return 2

    out.sort(key=lambda x: (-x["coolness"], x["id"]))
    with open(args.out, "w", encoding="utf-8") as f:
        for rec in out:
            f.write(json.dumps(rec, ensure_ascii=False, separators=(",", ":")) + "\n")
    kept = sum(1 for r in out if r["admitted"])
    print(f"✅ live corpus: {len(out)} records ({kept} above quality gate) -> {os.path.relpath(args.out, REPO)}")
    print("   next: python3 pipeline/shard_builder.py")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Ideas Galore Devpost harvester (polite, resumable)")
    ap.add_argument("--dry-run", action="store_true")
    sub = ap.add_subparsers(dest="cmd", required=True)

    d = sub.add_parser("discover", help="L1: event dimension table from the public JSON API")
    d.add_argument("--pages", type=int, default=3)
    d.add_argument("--order", default="prize_amount", choices=["prize_amount", "newest", "popularity", "complexity"])
    d.add_argument("--status", default="ended", choices=["ended", "open", "upcoming", "all"])

    g = sub.add_parser("gallery", help="L2: listing cards from project galleries")
    g.add_argument("--event")
    g.add_argument("--from-state", action="store_true")
    g.add_argument("--max-events", type=int, default=20)
    g.add_argument("--pages", type=int, default=2)

    p = sub.add_parser("deep", help="L3: per-project pages (likes, tags, authored sections)")
    p.add_argument("--limit", type=int, default=150)

    i = sub.add_parser("ingest", help="merge live captures into corpus.jsonl + enrich")
    i.add_argument("--out", default=os.path.join(REPO, "pipeline", "corpus.jsonl"))
    i.add_argument("--allow-shrink", action="store_true")

    a = sub.add_parser("all", help="discover -> gallery -> deep -> ingest")
    a.add_argument("--events", type=int, default=25)
    a.add_argument("--deep", type=int, default=150)

    args = ap.parse_args()
    t0 = time.time()
    if args.cmd == "discover":
        rc = 0 if discover(args.pages, args.order, args.status, args.dry_run) else 1
    elif args.cmd == "gallery":
        rc = cmd_gallery(args)
    elif args.cmd == "deep":
        rc = cmd_deep(args)
    elif args.cmd == "ingest":
        rc = cmd_ingest(args)
    else:
        discover(3, "prize_amount", "ended", args.dry_run)
        state = read_state()
        args.from_state, args.max_events, args.pages = True, args.events, 2
        args.event = None
        rc = cmd_gallery(args)
        args.limit = args.deep
        rc = cmd_deep(args) or rc
        args.out, args.allow_shrink = os.path.join(REPO, "pipeline", "corpus.jsonl"), False
        rc = cmd_ingest(args) or rc
    print(f"\n⏱  {time.time() - t0:.1f}s wall clock (rate-limited by design: {MIN_INTERVAL}s/req)")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
