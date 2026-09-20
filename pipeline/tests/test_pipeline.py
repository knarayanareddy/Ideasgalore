"""
Ideas Galore — pipeline tests
=============================
The reference repo shipped no tests; ADR-10 requires that a build can *fail* on
drift, and the cheapest way to keep a heuristic pipeline honest is to pin its
behaviour. Run:  python3 -m unittest discover -s pipeline/tests -v
       or:      python3 pipeline/tests/test_pipeline.py
"""

from __future__ import annotations

import glob
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "pipeline"))
sys.path.insert(0, os.path.join(REPO, "mcp"))

import audit_projects as A  # noqa: E402
import ingest_seed as I  # noqa: E402
import shard_builder  # noqa: E402
import taxonomy_hacks as T  # noqa: E402

FIXTURE = [
    {
        "id": "alpha-agent", "slug": "alpha-agent", "name": "Alpha Agent",
        "summary": "Nine agents turn a screenplay into a film and quote you the cost before you spend a cent.",
        "url": "https://devpost.com/software/alpha-agent", "event_key": "xprize",
        "event_slug": "xprize", "event_title": "Build with Gemini XPRIZE",
        "event_org": "XPRIZE", "event_date": "2026-08-17", "event_registrations": 26445,
        "prize_usd": 2000000, "event_prize_usd": 2000000, "event_themes": ["Machine Learning/AI"],
        "event_featured": False, "event_winners_announced": False,
        "likes": 547, "award": "Grand Prize / Overall Winner", "depth": "deep",
        "thumbnail": "//cdn/thumb.png", "repo_url": "https://github.com/x/y",
        "built_with": ["python", "react"],
        "page": {"how_we_built_it": "One Cloud Run service and ClickHouse for the verdict log, UNIQUEPROSEMARKER",
                  "inspiration": "Video models levy an entry fee: you must already know how to talk to them."},
        "source": "deep", "harvested_at": "2026-09-18",
    },
    {
        "id": "beta-clinic", "slug": "beta-clinic", "name": "Beta Clinic",
        "summary": "AI-powered concussion screening and recovery tracking in the browser, offline, for clinics.",
        "url": "https://devpost.com/software/beta-clinic", "event_key": "xprize",
        "event_slug": "xprize", "event_title": "Build with Gemini XPRIZE",
        "event_org": "XPRIZE", "event_date": "2026-08-17", "event_registrations": 26445,
        "prize_usd": 2000000, "event_prize_usd": 2000000, "event_themes": ["Health"],
        "event_featured": False, "event_winners_announced": True,
        "likes": None, "award": None, "depth": "listing", "thumbnail": None,
        "built_with": [], "source": "seed:gallery", "harvested_at": "2026-09-18",
    },
    {
        "id": "noise-one", "slug": "noise-one", "name": "test",
        "summary": "demo only", "url": "https://devpost.com/software/noise-one",
        "event_key": "xprize", "likes": 0, "depth": "listing", "built_with": [],
        "harvested_at": "2026-09-18",
    },
]


def enrich_all(records, today="2026-09-18"):
    kin = T.jaccard_kin({r["id"]: f"{r.get('name')} {r.get('summary')}" for r in records})
    out = []
    for r in records:
        rr = dict(r)
        rr.setdefault("summary", "")
        e = T.enrich_project_record(rr, today, kin.get(r["id"], 0.0), {
            "title": r.get("event_title"), "organization_name": r.get("event_org"),
            "registrations_count": r.get("event_registrations"), "prize_usd": r.get("event_prize_usd"),
            "themes": r.get("event_themes"), "featured": r.get("event_featured"),
            "winners_announced": r.get("event_winners_announced"), "ended_at": r.get("event_date")})
        out.append(e)
    return out


class TestShelving(unittest.TestCase):
    """Sector assignment is read off the copy, and a verb in marketing prose is not a subsystem."""

    def test_a_health_app_saying_you_can_audit_its_score_is_not_compliance_infrastructure(self):
        recs = [json.loads(l) for l in open(os.path.join(REPO, "pipeline", "corpus.jsonl"),
                                           encoding="utf-8")]
        by = {str(r["id"]): r for r in recs}
        dom, sub, _ = T.classify_record(by["vitalis-bio"])
        self.assertEqual((dom, sub), ("Health, Care & Human Performance", "Screening & Diagnostics"),
                         "biological-age copy must not be shelved under Regulatory & Audit Machinery")
        dom, sub, _ = T.classify_record(by["complianceguardian-kcqs32"])
        self.assertEqual((dom, sub), ("Public Trust, Safety & Compliance", "Regulatory & Audit Machinery"),
                         "a ruleset-citation product belongs in the compliance sector")


class TestTaxonomy(unittest.TestCase):
    def test_domain_is_lexical_not_literal(self):
        got = T.classify_record({"name": "realityCheCk - AI Image Detector",
                                 "summary": "Detects AI-generated images using a hybrid CLIP + FFT-forensics "
                                            "model, 0.996 AUC after compression, blur, crop & rescale."})[0]
        self.assertEqual(got, "Public Trust, Safety & Compliance")

    def test_unshelvable_goes_to_explicit_bucket(self):
        dom, sub, margin = T.classify_record({"name": "Docagram", "summary": "Visualize everything with AI"})
        self.assertEqual((dom, sub, margin), ("Emerging & Cross-Domain", "Unclassified", 0.0))

    def test_move_detection_targets_mechanism_language(self):
        moves = T.detect_moves("Nine agents turn a screenplay into a film and quote you the cost before "
                               "you spend a cent. Every action that costs money is a state change; a human "
                               "approves. Stores every verdict to ClickHouse.")
        self.assertIn("price-before-generate", moves)
        self.assertIn("human-holds-the-last-button", moves)
        self.assertLessEqual(len(moves), 4)

    def test_specificity_rewards_mechanism_and_numbers(self):
        vague = T.specificity_score("a platform for people", "A better way to work", [])
        sharp = T.specificity_score("cuts p95 from 53ms to 19ms using CLIP", "Detects AI images; 0.996 AUC", ["python"])
        self.assertGreater(sharp, vague + 0.2)

    def test_coolness_monotonic_in_likes(self):
        base = dict(award=None, registrations=1000, prize_usd=1000, featured=False,
                    winners_announced=True, event_date="2026-09-01", today="2026-09-18",
                    specificity=0.5, depth="listing", has_thumbnail=True, has_links=False,
                    kin_redundancy=0.0)
        low = T.compute_coolness(likes=10, **base)["total"]
        high = T.compute_coolness(likes=900, **base)["total"]
        self.assertGreater(high, low)

    def test_unknown_likes_are_not_punished_like_zero(self):
        base = dict(registrations=1000, prize_usd=1000, featured=False, winners_announced=False,
                    event_date="2026-09-01", today="2026-09-18", specificity=0.5, depth="listing",
                    has_thumbnail=False, has_links=False, kin_redundancy=0.0, award=None)
        self.assertGreater(T.compute_coolness(likes=None, **base)["engagement"],
                           T.compute_coolness(likes=0, **base)["engagement"])

    def test_scores_are_bounded(self):
        for r in enrich_all(FIXTURE):
            self.assertGreaterEqual(r["coolness"], 0.0)
            self.assertLessEqual(r["coolness"], 1.0)
            parts = r["coolness_parts"]
            for k, v in parts.items():
                self.assertGreaterEqual(v, 0.0, f"{k} negative")
                self.assertLessEqual(v, 1.0, f"{k} over 1")
            positive = 0.30 * parts["engagement"] + 0.22 * parts["validation"] + 0.14 * parts["event_prestige"] \
                + 0.10 * parts["recency"] + 0.14 * parts["specificity"] + 0.10 * parts["signal_richness"]
            self.assertAlmostEqual(parts["total"], max(0.0, min(1.0, positive - 0.12 * parts["redundancy"])), places=3)

    def test_noise_gate_rejects_placeholder(self):
        recs = enrich_all(FIXTURE)
        noise = next(r for r in recs if r["id"] == "noise-one")
        self.assertFalse(noise["admitted"])

    def test_provenance_labels_every_field_class(self):
        for r in enrich_all(FIXTURE):
            for key in ("likes", "summary", "domain", "moves", "coolness", "specificity"):
                self.assertIn(r["provenance"][key], ("observed", "derived", "editorial", "unavailable"))
            self.assertEqual(r["provenance"]["domain"], "derived")

    def test_event_name_does_not_leak_into_domain(self):
        """An event called 'Build with Gemini' must not shelve every entrant under Developer Tooling."""
        rec = {"name": "Vidyut", "summary": "AI-powered P2P EV charging marketplace with intelligent routing",
               "event_title": "Build with Gemini XPRIZE", "themes": ["Productivity"]}
        self.assertEqual(T.classify_record(rec)[0], "Climate, Energy & the Physical World")


class TestSurfaces(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.records = enrich_all(FIXTURE)
        # The catalog is audited-only (A1), so a fixture that expects rows has to say
        # which records the audit passed.
        cls.audits = audit_sheets_for(cls.records)
        cls.stats = shard_builder.build(cls.records, cls.tmp, "2026-09-18", cls.audits)

    def test_counts_match_across_every_surface(self):
        n = self.stats["total"]
        self.assertEqual(n, sum(v["records"] for v in self.stats["shards"].values()))
        with open(f"{self.tmp}/data/ideas.csv", encoding="utf-8") as f:
            self.assertEqual(n, sum(1 for _ in f) - 1)
        self.assertEqual(n, sum(1 for _ in open(f"{self.tmp}/data/ideas.ndjson", encoding="utf-8")))

    def test_tier1_row_shape_matches_declared_format(self):
        packed = json.load(open(f"{self.tmp}/catalog-packed.json", encoding="utf-8"))
        width = len(packed["row_format"])
        for row in packed["rows"]:
            self.assertEqual(len(row), width)
            self.assertIn(str(row[6]), packed["domains"])
            for mid in row[8]:
                self.assertIn(str(mid), packed["moves"])

    def test_event_ids_resolve(self):
        packed = json.load(open(f"{self.tmp}/catalog-packed.json", encoding="utf-8"))
        for row in packed["rows"]:
            self.assertIn(str(row[3]), packed["events"], "row event id must resolve in the packed table")

    def test_bulk_exports_do_not_mirror_authored_prose(self):
        """ADR-12 ethics gate: the only prose allowed in Tier 2, never CSV/NDJSON."""
        csv = open(f"{self.tmp}/data/ideas.csv", encoding="utf-8").read()
        nd = open(f"{self.tmp}/data/ideas.ndjson", encoding="utf-8").read()
        self.assertNotIn("UNIQUEPROSEMARKER", csv)
        self.assertNotIn("UNIQUEPROSEMARKER", nd)
        for line in nd.splitlines():
            self.assertEqual(json.loads(line)["has_deep"] in (0, 1), True)
        detail = json.load(open(f"{self.tmp}/data/details/creative-media-story-and-play.json", encoding="utf-8"))
        self.assertIn("UNIQUEPROSEMARKER", json.dumps(detail))

    def test_csv_header_is_stable_and_documented(self):
        header = open(f"{self.tmp}/data/ideas.csv", encoding="utf-8").readline().strip().split(",")
        self.assertEqual(header, shard_builder.CSV_COLUMNS)

    def test_sqlite_roundtrip(self):
        gz = f"{self.tmp}/data/ideasgalore.sqlite.gz"
        if not os.path.exists(gz):
            self.skipTest("sqlite surface skipped by size budget")
        import gzip
        import sqlite3
        with tempfile.TemporaryDirectory() as td:
            db = os.path.join(td, "x.sqlite")
            open(db, "wb").write(gzip.decompress(open(gz, "rb").read()))
            con = sqlite3.connect(db)
            n = con.execute("SELECT COUNT(*) FROM projects").fetchone()[0]
            self.assertEqual(n, self.stats["total"])
            self.assertEqual(n, con.execute("SELECT COUNT(DISTINCT project_id) FROM project_moves").fetchone()[0])
            csv_n = sum(1 for _ in open(f"{self.tmp}/data/ideas.csv", encoding="utf-8")) - 1
            self.assertEqual(n, csv_n, "SQL and CSV must describe the same population")

    def test_gate_rejects_missing_required_field(self):
        broken = enrich_all(FIXTURE)
        broken[0]["name"] = ""
        with tempfile.TemporaryDirectory() as td:
            audits = audit_sheets_for(broken)
            stats = shard_builder.build(broken, td, "2026-09-18", audits)
            problems = shard_builder.gate_checks(broken, stats, td, audits)
        self.assertTrue(any("required field" in p for p in problems))

    def test_every_surface_is_byte_stable_across_rebuilds(self):
        """Not just the packed index: the *gzipped* SQLite is the file that taught us
        this lesson, because gzip writes the current time into its header. A build
        artifact whose bytes depend on wall clock makes every drift gate a coin flip,
        so the comparison walks every emitted file (ADR-10)."""
        with tempfile.TemporaryDirectory() as td:
            shard_builder.build(self.records, td, "2026-09-18", self.audits)
            seen = []
            for root, _dirs, files in os.walk(td):
                for name in sorted(files):
                    if name == "manifest.json":   # build-time metadata, exempt by design
                        continue
                    rel = os.path.relpath(os.path.join(root, name), td)
                    with open(os.path.join(self.tmp, rel), "rb") as fa, open(os.path.join(root, name), "rb") as fb:
                        self.assertEqual(fa.read(), fb.read(), f"{rel} must be byte-stable across builds")
                    seen.append(rel)
            self.assertIn("data/ideasgalore.sqlite.gz", seen, "the gzipped surface must be covered")
            self.assertGreaterEqual(len(seen), 8, "the walk should cover Tier 1, Tier 2 and tabular surfaces")

    def test_as_of_date_is_derived_from_the_corpus(self):
        self.assertEqual(shard_builder.corpus_as_of([{"harvested_at": "2026-01-05"},
                                                    {"harvested_at": "2026-03-01"}]), "2026-03-01")
        self.assertEqual(shard_builder.corpus_as_of([{"harvested_at": "2026-03-01"}], "2026-09-18"),
                         "2026-09-18", "--today must still override for live refreshes")
        stamped = json.loads(open(shard_builder.CORPUS, encoding="utf-8").readline())["harvested_at"] \
            if os.path.exists(shard_builder.CORPUS) else None
        if stamped:
            recs = [json.loads(l) for l in open(shard_builder.CORPUS, encoding="utf-8")]
            self.assertEqual(shard_builder.corpus_as_of(recs), max(r["harvested_at"] for r in recs),
                             "committed corpus must repack without re-dating its scores")


class TestCoverageAndHolds(unittest.TestCase):
    """The corpus's honesty about its own size. Two failures we specifically guard
    against: a rejected record that does not say why (so a reader assumes the data is
    wrong rather than thin), and a sample that reads like a complete index."""

    def test_held_back_records_state_a_reason(self):
        for line in open(os.path.join(REPO, "pipeline", "corpus.jsonl"), encoding="utf-8"):
            rec = json.loads(line)
            if not rec.get("admitted", True):
                self.assertIn(rec.get("hold_reason"),
                              {"placeholder_summary", "below_min_coolness"},
                              f"{rec['id']} is unpublished but unexplained")

    def test_placeholder_summary_is_held_and_reasoned(self):
        rec = dict(FIXTURE[0]); rec["summary"] = "test"; rec["id"] = rec["slug"] = "junk"
        out = T.enrich_project_record(rec, "2026-09-18", 0.0, {})
        self.assertFalse(out["admitted"])
        self.assertEqual(out["hold_reason"], "placeholder_summary")

    def test_gallery_total_is_read_from_the_pagination_label(self):
        import harvest_devpost as H
        for frag, want in (("<strong>1</strong> – <strong>24</strong> of <strong>1,401</strong>", 1401),
                           ("1 - 24 of 1401", 1401),
                           ("Showing 25 – 48 of 1,401 projects", 1401),
                           ("no numbers on this page", None)):
            self.assertEqual(H.parse_gallery_total(frag), want, frag)

    def test_coverage_is_published_when_totals_are_recorded(self):
        with tempfile.TemporaryDirectory() as td:
            json.dump({"_note": "x", "demo": {"total_projects": 400, "pages_captured": 2}},
                      open(f"{td}/gallery_totals.json", "w"))
            recs = enrich_all(FIXTURE)
            for r in recs:
                r["event_key"] = "demo"
            admitted = sum(1 for r in recs if r.get("admitted", True))
            cov = shard_builder.coverage(recs, raw_dir=td)
            self.assertLess(admitted, len(recs), "fixture must contain a held-back record for this to mean anything")
            self.assertEqual(cov["events"]["demo"]["upstream_total"], 400)
            self.assertEqual(cov["events"]["demo"]["published"], admitted)
            self.assertEqual(cov["events"]["demo"]["ingested"], len(recs),
                             "ingested counts rejects; published counts what ships")
            self.assertEqual(cov["events"]["demo"]["coverage_pct"], round(100.0 * admitted / 400, 1))

    def test_shipped_stats_report_coverage(self):
        stats = json.load(open(os.path.join(REPO, "web", "public", "catalog-stats.json"), encoding="utf-8"))
        cov = stats.get("coverage")
        self.assertTrue(cov, "committed build must report coverage from raw/gallery_totals.json")
        for v in cov["events"].values():
            self.assertLessEqual(v["published"], v["upstream_total"])
            self.assertGreater(v["published"], 0)
        # Audited-only catalog: published + pool is the partition of what the quality
        # gate admitted (pre-audit this was simply total == admitted).
        self.assertEqual(stats["audited_published"] + stats["pool_records"],
                         stats["corpus_ingested"] - sum(stats["held_back"].values()))


class TestHarvestParsers(unittest.TestCase):
    """Parsers are the part that rots when the site changes; pin their contracts."""

    def setUp(self):
        sys.path.insert(0, os.path.join(REPO, "pipeline"))
        self.h = __import__("harvest_devpost")

    def test_prize_html_is_parsed_to_int(self):
        self.assertEqual(self.h.parse_prize('$<span data-currency-value>2,000,000</span>'), 2000000)
        self.assertEqual(self.h.parse_prize(None), None)

    def test_gallery_cards_parse(self):
        html = """
        <div class="thumbnail">
          <a href="https://devpost.com/software/tower-dq18x2">
            <img src="//cdn/x.png" alt="Tower">
            <h3>Tower</h3>
            <p>An air traffic controller for your deadlines that watches your work for weeks.</p>
          </a>
        </div>
        <div class="thumbnail">
          <a href="/software/antislop-vkjag3"><h3>Antislop</h3>
          <p>Turns any learning goal into an adaptive study experience with AI roadmaps.</p></a>
        </div>
        """
        rows = self.h.parse_gallery(html)
        self.assertEqual({r["id"] for r in rows}, {"tower-dq18x2", "antislop-vkjag3"})
        tower = next(r for r in rows if r["id"] == "tower-dq18x2")
        self.assertEqual(tower["name"], "Tower")
        self.assertIn("air traffic controller", tower["summary"])
        self.assertTrue(all(r["url"].startswith("https://devpost.com/software/") for r in rows))

    def test_project_page_extracts_likes_tags_sections_links(self):
        html = """
        <html><head><title>Foo | Devpost</title></head><body>
        <h2>Inspiration</h2><p>We were broke and the model cost a dollar a shot.</p>
        <h2>How we built it</h2><p>Cloud Run with ClickHouse for verdict logs and Gemini Pro for parsing.</p>
        <h2>Challenges we ran into</h2><p>Budget.</p>
        <p>Grand Prize winner</p>
        <a href="/software/built-with/python">python</a><a href="/software/built-with/react">react</a>
        <a href="https://github.com/foo/bar">code</a>
        <a href="https://www.youtube.com/watch?v=abc123">demo</a>
        <span>Like 547</span><p>547 people like this</p>
        <a href="/users/register?flow%5Bdata%5D%5Bsoftware_id%5D=880846">like</a>
        </body></html>"""
        rec = self.h.parse_project_page(html, "foo")
        self.assertEqual(rec["likes"], 547)
        self.assertEqual(rec["software_id"], 880846)
        self.assertEqual(rec["built_with"], ["python", "react"])
        self.assertIn("ClickHouse", rec["page"]["how_we_built_it"])
        self.assertEqual(rec["award"], "Grand Prize / Overall Winner")
        self.assertEqual(rec["repo_url"], "https://github.com/foo/bar")
        self.assertTrue(rec["open_source"])

    def test_strip_tags_decodes_entities(self):
        self.assertEqual(self.h.strip_tags("<p>a &amp; b &quot;c&quot;</p>"), 'a & b "c"')


class TestAgentContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not os.path.exists(os.path.join(REPO, "web/public/catalog-packed.json")):
            raise unittest.SkipTest("catalog not built yet")
        sys.path.insert(0, os.path.join(REPO, "mcp"))

    def test_mcp_index_decodes_tier1(self):
        import ideasgalore_mcp as m
        m.DIR, m.BASE = os.path.join(REPO, "web/public"), None
        i = m.Index()
        # The audited catalog is deliberately small — it is a vetted subset, not the
        # corpus. What must hold is that everything decoded is audited and publishable.
        self.assertGreater(len(i.rows), 0)
        self.assertTrue(set(i.packed.get("verdicts", {}).values()) <= set(T.AUDIT_PUBLISH_VERDICTS))
        for r in i.rows[:20]:
            self.assertTrue(r["url"].startswith("https://devpost.com/software/"))
            self.assertIsInstance(r["coolness"], float)
            self.assertIsInstance(r["moves"], list)
            self.assertIsNotNone(r["event"], "event title must resolve for every row")

    def test_mcp_audit_tools(self):
        import ideasgalore_mcp as m
        m.DIR, m.BASE = os.path.join(REPO, "web/public"), None
        names = {t["name"] for t in m.tools_list()["tools"]}
        self.assertTrue({"audit_report", "promotion_queue", "audit_rubric"} <= names, names)
        sheet = m.call("audit_report", {"id": "audionova"})
        body = json.loads(sheet["content"][0]["text"])
        self.assertTrue(body["found"] and body["verdict"] in T.AUDIT_PUBLISH_VERDICTS)
        self.assertEqual(set(body["fields"]), set(T.AUDIT_MANDATORY_FIELDS))
        held = json.loads(m.call("get_project", {"id": "mcop"})["content"][0]["text"])
        self.assertEqual(held.get("found"), "pool", "an audited-but-held record must not 404")
        self.assertFalse(held["vetted"])
        self.assertTrue(held["why_not_promoted"])
        q = json.loads(m.call("promotion_queue", {"limit": 3})["content"][0]["text"])
        self.assertGreater(q["count"], 0, "the pool must be workable, not just visible")
        rub = json.loads(m.call("audit_rubric", {})["content"][0]["text"])
        self.assertEqual(rub["published_verdicts"], list(T.AUDIT_PUBLISH_VERDICTS))
        mixed = json.loads(m.call("search_projects", {"query": "screenplay", "include_pool": True,
                                                       "limit": 5})["content"][0]["text"])
        self.assertTrue(any(r["vetted"] for r in mixed["results"]))
        self.assertTrue(all(r.get("why_not_promoted") for r in mixed["results"] if not r["vetted"]))

    def test_mcp_tools_run_and_cite(self):
        import ideasgalore_mcp as m
        m.DIR, m.BASE = os.path.join(REPO, "web/public"), None
        m._idx = None
        for name, args in [("search_projects", {"limit": 3}), ("list_moves", {}),
                           ("ideas_for_goal", {"goal": "make an agent auditable"}),
                           ("explain_scoring", {}), ("random_muse", {"seed": 1}),
                           ("remix_briefs", {"limit": 2})]:
            out = m.call(name, args)
            self.assertNotIn("isError", out, f"{name} failed: {out}")
        res = json.loads(m.call("search_projects", {"limit": 3})["content"][0]["text"])
        self.assertTrue(all("devpost_url" in r and "hackathon" in r for r in res["results"]))

    def test_unknown_tool_and_bad_id_are_graceful(self):
        import ideasgalore_mcp as m
        m.DIR, m.BASE = os.path.join(REPO, "web/public"), None
        m._idx = None
        self.assertTrue(m.call("nope", {})["isError"])
        self.assertIn("error", json.loads(m.call("get_project", {"id": "does-not-exist"})["content"][0]["text"]))

    def test_contract_files_exist_and_are_parseable(self):
        for name in ("llms.txt", "RECIPES.md"):
            self.assertTrue(os.path.getsize(f"{REPO}/web/public/agents/{name}") > 500)
        for name in ("schema.json", "openapi.json", "ethics.json"):
            json.load(open(f"{REPO}/web/public/agents/{name}", encoding="utf-8"))

    def test_schema_declares_provenance_for_every_property(self):
        schema = json.load(open(f"{REPO}/web/public/agents/schema.json", encoding="utf-8"))
        for key, prop in schema["properties"].items():
            if key in ("inspiration_intel", "coolness_parts", "provenance", "event", "domain_margin",
                       "specificity", "depth", "harvested_at", "scoring_version", "taxonomy_version"):
                continue
            self.assertIn("x-provenance", prop, f"{key} lacks provenance")

    def test_moves_surface_documents_all_moves(self):
        data = json.load(open(f"{REPO}/web/public/data/moves.json", encoding="utf-8"))
        self.assertEqual(set(data["moves"]), set(T.MOVES))
        for m, spec in data["moves"].items():
            self.assertTrue(spec["definition"], m)
            self.assertTrue(spec["steal_this"], m)


class TestMoveVocabularyIntegrity(unittest.TestCase):
    def test_regexes_compile(self):
        for m, spec in T.MOVES.items():
            try:
                re.compile(spec["pat"], re.IGNORECASE)
            except re.error as exc:
                self.fail(f"move {m} has invalid pattern: {exc}")

    def test_definitions_are_actionable_not_descriptive(self):
        for m, spec in T.MOVES.items():
            self.assertGreater(len(spec["steal_this"]), 40, f"{m} steal_this too thin")
            self.assertTrue(re.search(r"[.!?]$", spec["definition"].strip()), f"{m} definition not a sentence")

    def test_lexicon_keywords_compile(self):
        for dom, spec in T.DOMAINS.items():
            for kw in [*spec.get("signature", []), *[k for ks in spec["subsystems"].values() for k in ks]]:
                if not kw:
                    continue
                try:
                    re.compile(T._kw_pattern(kw))
                except re.error as exc:
                    self.fail(f"{dom} keyword {kw!r} invalid: {exc}")


class TestCliEntrypoints(unittest.TestCase):
    def test_full_offline_rebuild_is_reproducible(self):
        env = dict(os.environ)
        r = subprocess.run([sys.executable, "pipeline/ingest_seed.py", "--out",
                            os.path.join(tempfile.mkdtemp(), "corpus.jsonl")],
                           cwd=REPO, capture_output=True, text=True, env=env)
        self.assertEqual(r.returncode, 0, r.stderr[-800:])
        self.assertIn("Seed ingest", r.stdout)

    def test_shard_check_passes_on_committed_catalog(self):
        r = subprocess.run([sys.executable, "pipeline/shard_builder.py", "--check"],
                           cwd=REPO, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout[-800:] + r.stderr[-400:])


class TestUiContract(unittest.TestCase):
    """The browser decodes the same bytes the gates validated; a UI that reads a stale
    column order shows readers the wrong verdict. Checked with node, no DOM needed
    (`pipeline/tests/ui_audit_smoke.mjs` also asserts the UI field list == the rubric)."""

    @unittest.skipIf(shutil.which("node") is None, "node not available")
    def test_ui_audit_smoke_passes_on_the_built_catalog(self):
        run = subprocess.run(["node", os.path.join(REPO, "pipeline", "tests", "ui_audit_smoke.mjs")],
                             cwd=REPO, capture_output=True, text=True)
        self.assertEqual(run.returncode, 0, run.stdout[-1200:] + run.stderr[-600:])
        self.assertIn("consistent with the built catalog", run.stdout)

    def test_ui_field_labels_cover_the_rubric(self):
        """Parse the UI's field list and check it against the rubric — a JS-side drift
        the node harness proves at run time, and this proves even where node is absent."""
        js = open(os.path.join(REPO, "web", "src", "lib.js"), encoding="utf-8").read()
        block = js.split("AUDIT_FIELD_ORDER = [", 1)[1].split("]", 1)[0]
        listed = re.findall(r"'([a-z_]+)'", block)
        # The inspector re-orders the fields for reading (identity → mechanism → honesty),
        # so compare membership, not position; position is a design choice, not drift.
        self.assertEqual(sorted(listed), sorted(T.AUDIT_MANDATORY_FIELDS),
                         "the inspector must show every mandatory field — no blanks, no extras")
        labels = js.split("AUDIT_FIELD_LABELS = {", 1)[1].split("}", 1)[0]
        for f in T.AUDIT_MANDATORY_FIELDS:
            self.assertIn(f"{f}:", labels, f"no display label for {f}")


class TestAuditGate(unittest.TestCase):
    """The audit must be load-bearing: publication requires a publishable sheet, and
    nothing unverified or duplicated reaches a published surface (docs/AUDIT_PANEL.md
    A1/A2/A6/A10)."""

    @classmethod
    def setUpClass(cls):
        cls.records = enrich_all(FIXTURE)

    def _build(self, audits):
        td = tempfile.mkdtemp()
        stats = shard_builder.build(self.records, td, "2026-09-18", audits)
        packed = json.load(open(f"{td}/catalog-packed.json", encoding="utf-8"))
        pool = json.load(open(f"{td}/data/pool.json", encoding="utf-8"))
        problems = shard_builder.gate_checks(self.records, stats, td, audits)
        return td, stats, packed, pool, problems

    def test_a_csv_header_must_match_its_rows(self):
        """A table whose rows sit under the wrong header is worse than no table at all.

        `ideas.csv` once led with 23 base columns under a header that led with the 8 audit
        ones: every consumer reading `verdict` got an id, and no gate noticed. Rows are now
        built by column name and the alignment is gated.
        """
        # one sheet, not two: the fixture needs a non-empty pool to test both tables
        audits = audit_sheets_for(self.records[:1])
        td, stats, packed, pool, problems = self._build(audits)
        self.assertEqual(problems, [])
        self.assertTrue(pool["records"], "fixture must leave held-out rows")
        import csv as _csv
        with open(f"{td}/data/ideas.csv", newline="", encoding="utf-8") as fh:
            ideas = list(_csv.reader(fh))
        with open(f"{td}/data/pool.csv", newline="", encoding="utf-8") as fh:
            pools = list(_csv.reader(fh))
        self.assertEqual(ideas[0], T.CSV_COLUMNS)
        self.assertEqual(pools[0], T.POOL_CSV_COLUMNS)
        for table, cols, path in ((ideas, T.CSV_COLUMNS, "ideas.csv"), (pools, T.POOL_CSV_COLUMNS, "pool.csv")):
            widths = {len(r) for r in table[1:]}
            self.assertEqual(widths, {len(cols)}, f"{path}: field counts {widths} vs header {len(cols)}")
            at = {c: i for i, c in enumerate(table[0])}
            ids = {r[at["id"]] for r in table[1:]}
            want = {r[0] for r in packed["rows"]} if path == "ideas.csv" else {
                str(r["id"]) for r in pool["records"]}
            self.assertEqual(ids, want, f"{path}: id column does not identify the ids")
        at = {c: i for i, c in enumerate(ideas[0])}
        verdicts = {r[at["verdict"]] for r in ideas[1:]}
        self.assertTrue(verdicts and verdicts <= set(T.AUDIT_PUBLISH_VERDICTS),
                        f"the verdict column must hold verdicts, not ids — got {sorted(verdicts)[:3]}. "
                        "An id landing in `verdict` is exactly what a base-first row under an "
                        "audit-first header does")
        self.assertEqual({r[at["worth"]] for r in ideas[1:]} - set(T.AUDIT_WORTH), set(),
                         "the worth column must hold worth labels")
        # and the gate has to notice the old bug
        rows = ideas[1:]
        order = T.BASE_CSV_COLUMNS + T.AUDIT_CSV_COLUMNS
        with open(f"{td}/data/ideas.csv", "w", newline="", encoding="utf-8") as fh:
            fh.write(",".join(ideas[0]) + "\n")
            for r in rows:
                fh.write(",".join(r[order.index(c)] for c in ideas[0]) + "\n")
        caught = [g for g in shard_builder.audit_gate_checks(self.records, stats, td, audits)
                  if "ideas.csv" in g]
        self.assertTrue(caught, "a header/row misalignment must fail the build, not ship")

    def test_unaudited_build_publishes_nothing(self):
        _td, stats, packed, pool, problems = self._build({})
        self.assertEqual(packed["rows"], [], "no audit sheet means nothing may be published")
        self.assertEqual(stats["audited_published"], 0)
        self.assertEqual(stats["pool_records"], stats["corpus_ingested"] - sum(stats["held_back"].values()))
        self.assertEqual(problems, [], "an empty-but-consistent build must pass the gates")

    def test_catalog_and_pool_are_a_partition_of_admitted(self):
        audits = audit_sheets_for(self.records[:2])
        _td, stats, packed, pool, problems = self._build(audits)
        published = {r[0] for r in packed["rows"]}
        self.assertEqual(published, {"alpha-agent", "beta-clinic"})
        self.assertEqual(stats["audited_published"] + stats["pool_records"],
                         stats["corpus_ingested"] - sum(stats["held_back"].values()))
        self.assertFalse(published & {p["id"] for p in pool["records"]}, "no id in both surfaces")
        self.assertEqual(problems, [])

    def test_thin_verdict_is_pooled_not_deleted(self):
        audits = audit_sheets_for(self.records, over={
            "alpha-agent": {"verdict": "thin", "publishable": False,
                            "why_not_promoted": ["no checkable claim about performance"]}})
        _td, _stats, packed, pool, problems = self._build(audits)
        self.assertNotIn("alpha-agent", {r[0] for r in packed["rows"]})
        row = [p for p in pool["records"] if p["id"] == "alpha-agent"][0]
        self.assertEqual(row["audit"]["verdict"], "thin")
        self.assertIn("verdict:thin", row["why_not_promoted"])
        self.assertIn("checkable claim", row["why_not_promoted"][1])
        self.assertTrue(row["would_settle_it"])
        self.assertEqual(problems, [])

    def test_gate_rejects_nonpublishable_verdict_and_unfiled_fields(self):
        audits = audit_sheets_for(self.records)
        rid = "alpha-agent"
        audits[rid]["verdict"] = "thin"          # publishable flag left stale on purpose
        del audits[rid]["fields"]["prior_art"]
        _td, _stats, _packed, _pool, problems = self._build(audits)
        joined = " | ".join(problems)
        self.assertIn("non-publishable verdict", joined)
        self.assertIn("unfiled mandatory fields", joined)

    def test_gate_rejects_a_published_duplicate_pair(self):
        audits = audit_sheets_for(self.records)
        audits["alpha-agent"]["duplicate_of"] = "beta-clinic"
        _td, _stats, _packed, _pool, problems = self._build(audits)
        self.assertTrue(any("both are published" in p for p in problems), problems)

    def test_gate_requires_evidence_to_be_checkable(self):
        audits = audit_sheets_for(self.records)
        audits["alpha-agent"]["evidence"][0]["source"] = None
        audits["beta-clinic"]["evidence"][0]["status"] = "probably"
        _td, _stats, _packed, _pool, problems = self._build(audits)
        self.assertTrue(any("no source to check" in p for p in problems), problems)
        self.assertTrue(any("outside the rubric" in p for p in problems), problems)

    def test_banned_language_scan_is_word_bounded(self):
        """A10 bans verdict adjectives in the auditor's prose — but 'implied' is not 'lied'."""
        audits = audit_sheets_for(self.records)
        audits["alpha-agent"]["fields"]["what_to_steal"]["value"] = (
            "the cost ladder is implied by the pricing table")
        audits["beta-clinic"]["worth_note"] = "the team lied about the benchmark"
        _td, _stats, _packed, _pool, problems = self._build(audits)
        banned = [p for p in problems if "banned verdict language" in p]
        self.assertEqual(len(banned), 1, problems)
        self.assertIn("beta-clinic:lied", banned[0])
        self.assertNotIn("alpha-agent:lied", banned[0])

    def test_public_row_shape_is_shared_with_the_agent_contract(self):
        """The packed row_format and the CSV header are the same objects the docs publish
        — the drift that used to be invisible is a build failure now (A9, ADR-14)."""
        audits = audit_sheets_for(self.records)
        _td, _stats, packed, _pool, _problems = self._build(audits)
        self.assertEqual(packed["row_format"], T.ROW_FORMAT)
        self.assertEqual(shard_builder.CSV_COLUMNS, T.CSV_COLUMNS)
        self.assertEqual(shard_builder.ROW_FORMAT, T.ROW_FORMAT)
        for row in packed["rows"]:
            self.assertEqual(len(row), len(T.ROW_FORMAT))
            self.assertIn(str(row[14]), packed["verdicts"])
            self.assertIn(str(row[15]), packed["worth"])
            self.assertIn(packed["verdicts"][str(row[14])], T.AUDIT_PUBLISH_VERDICTS)

    def test_detail_and_ndjson_records_carry_the_verdict(self):
        audits = audit_sheets_for(self.records)
        _td, _stats, _packed, _pool, _problems = self._build(audits)
        nd = [json.loads(l) for l in open(f"{_td}/data/ideas.ndjson", encoding="utf-8")]
        self.assertTrue(all(r["audit"] and r["audit"]["verdict"] in T.AUDIT_PUBLISH_VERDICTS for r in nd))
        self.assertTrue(all(r["audit"]["sheet"].startswith("data/audits/") for r in nd))
        detail = {}
        for name in os.listdir(f"{_td}/data/details"):
            detail.update(json.load(open(f"{_td}/data/details/{name}", encoding="utf-8")))
        rec = detail["alpha-agent"]
        self.assertEqual(rec["audit"]["clone_cost"]["estimate"], "one weekend")
        self.assertEqual(rec["audit"]["what_to_steal"], "the cost ladder")
        self.assertIn("what_to_steal", json.dumps(rec["audit"]))

    def test_audit_surfaces_are_self_consistent(self):
        audits = audit_sheets_for(self.records)
        td, stats, packed, pool, _problems = self._build(audits)
        index = json.load(open(f"{td}/data/audits.json", encoding="utf-8"))
        self.assertEqual(set(index["records"]), {r[0] for r in packed["rows"]})
        self.assertEqual(index["audit_version"], T.AUDIT_VERSION)
        sheets = {}
        for name in os.listdir(f"{td}/data/audits"):
            if name.endswith(".json"):
                sheets.update(json.load(open(f"{td}/data/audits/{name}", encoding="utf-8"))["records"])
        self.assertEqual(set(sheets), set(index["records"]), "index and sheets must agree")
        for rid, sh in sheets.items():
            self.assertEqual(set(sh["fields"]), set(T.AUDIT_MANDATORY_FIELDS))
        rub = json.load(open(f"{td}/data/audit-rubric.json", encoding="utf-8"))
        self.assertEqual(rub["audit_version"], T.AUDIT_VERSION)
        self.assertEqual(rub["published_verdicts"], list(T.AUDIT_PUBLISH_VERDICTS))


class TestAuditEngine(unittest.TestCase):
    """The engine, run on the real captures. These four pin the mistakes the panel
    argued about: trusting a page's own framing, ignoring a measured A/B table, and
    letting a resubmission through as a second project."""

    @classmethod
    def setUpClass(cls):
        with tempfile.TemporaryDirectory() as td:
            out = os.path.join(td, "audit.jsonl")
            sheets, actions = A.audit(A.CORPUS, out)
            cls.sheets = {s["id"]: s for s in sheets}
            cls.actions = actions
        committed = [json.loads(l) for l in open(os.path.join(REPO, "pipeline", "audit.jsonl"), encoding="utf-8")]
        cls.committed = {s["id"]: s for s in committed}

    def test_audit_is_deterministic_and_matches_the_committed_sheets(self):
        self.assertEqual(list(self.sheets), list(self.committed))
        for rid, sh in self.sheets.items():
            self.assertEqual(json.dumps(sh, sort_keys=True), json.dumps(self.committed[rid], sort_keys=True),
                             f"{rid}: audit output must be reproducible from committed inputs")

    def test_a_pages_own_disclaimer_cannot_count_as_confirmation(self):
        sh = self.sheets["mcop"]
        chk = sh["checks"]["numbers_add_up"]
        self.assertEqual(chk["status"], "unverifiable", "an unfalsifiable claim has nothing to check")
        self.assertLess(chk["pass"], 0.5)
        self.assertIn("harness", chk["why"].lower())
        self.assertFalse(sh["publishable"], "unverifiable numbers + no artifact must not publish")

    def test_a_measured_ab_table_counts_as_confirmation(self):
        sh = self.sheets["greenlight-nine-agent-production-crew"]
        chk = sh["checks"]["numbers_add_up"]
        self.assertEqual(chk["status"], "confirmed")
        self.assertGreaterEqual(chk["pass"], 0.9)
        self.assertIn("49", chk["why"] + json.dumps(chk.get("evidence", [])))
        self.assertEqual(sh["verdict"], "sound-with-caveats")

    def test_our_own_summary_is_never_marked_as_the_teams(self):
        """`what_it_is` is `derived` when it comes from the capture's `one_line`.

        A reader who believes a sentence is transcribed will attribute it to the authors.
        Only text taken from an authored section earns `observed`.
        """
        cap = {"id": "fixture", "name": "Fixture", "source_url": "https://devpost.com/software/fixture",
               "one_line": "A restatement of the page in the auditor's own words, filed as derived.",
               "sections": {"what_it_does": "The page's own description of its behaviour, verbatim."},
               "built_with": [], "links": {}, "numbers": [], "data_and_models": None, "testing": None}
        notes = {"worth": "niche"}
        fields, _ = A.build_fields(cap, notes, None, None, {})
        self.assertEqual(fields["what_it_is"]["provenance"], "derived", fields["what_it_is"])
        cap2 = {**cap, "one_line": None}
        fields2, _ = A.build_fields(cap2, notes, None, None, {})
        self.assertEqual(fields2["what_it_is"]["provenance"], "observed", fields2["what_it_is"])

    def test_a_page_read_shows_up_on_the_row_it_came_from(self):
        """Depth and artifact links are row facts, not sheet-only facts.

        Every id in `raw/deep_captures` was read in full, so its corpus row must say
        `depth: deep` and carry the links the page published. The bug this pins: the
        projection existed for harvester records only, and the UI's "project page fetched"
        badge, its depth filter and every bulk export described the six audited records as
        un-fetched listing rows.
        """
        caps = {}
        for name in sorted(os.listdir(os.path.join(REPO, "pipeline", "raw", "deep_captures"))):
            if name.endswith(".json"):
                with open(os.path.join(REPO, "pipeline", "raw", "deep_captures", name), encoding="utf-8") as fh:
                    cap = json.load(fh)
                caps[str(cap["id"])] = cap
        self.assertGreaterEqual(len(caps), 12)
        with open(os.path.join(REPO, "pipeline", "corpus.jsonl"), encoding="utf-8") as fh:
            rows = {json.loads(l)["id"]: json.loads(l) for l in fh}
        for rid, cap in caps.items():
            r = rows.get(rid)
            self.assertIsNotNone(r, f"{rid} captured but absent from the corpus")
            self.assertEqual(r.get("depth"), "deep", f"{rid}: a full page read must not publish as a listing row")
            self.assertEqual(r.get("has_deep", 1), 1, rid)
            for row_key, cap_key in (("repo_url", "repo"), ("demo_url", "demo"), ("video_url", "video")):
                if (cap.get("links") or {}).get(cap_key):
                    self.assertEqual(r.get(row_key), cap["links"][cap_key],
                                     f"{rid}: {row_key} must be the link the page actually printed")

    def test_enriching_a_row_cannot_change_its_staff_pick_credit(self):
        """`staff_pick` reads the feed the row came from, not which stage wrote to it last.

        Deriving it from `source` meant a harvester or audit capture that stamps its own
        provenance silently moved a row's `validation` term — enrichment lowering a score is
        an invitation to stop enriching.
        """
        base = dict(likes=None, award=None, registrations=100, prize_usd=1000, featured=True,
                    winners_announced=True, event_date="2026-09-12", today="2026-09-19",
                    specificity=0.6, depth="listing", has_thumbnail=True, has_links=False,
                    kin_redundancy=0.0)
        showcase = T.compute_coolness(**base, staff_pick=True)
        gallery = T.compute_coolness(**base, staff_pick=False)
        self.assertGreater(showcase["validation"], gallery["validation"])
        for depth, links in (("deep", True), ("listing", False)):
            same = T.compute_coolness(**{**base, "depth": depth, "has_links": links}, staff_pick=True)
            self.assertEqual(round(same["validation"], 6), round(showcase["validation"], 6),
                             "validation must not depend on capture stage")

    def test_an_empty_capture_field_cannot_erase_what_the_listing_knew(self):
        """A page read that saw no tag sidebar is an absence of evidence, not evidence of absence."""
        with tempfile.TemporaryDirectory() as td:
            cap = {"id": "x", "likes": 0, "award": None, "software_id": None, "built_with": [],
                   "gallery_images": 0, "links": {"repo": "https://github.com/o/x", "demo": None,
                                                   "video": None}}
            with open(os.path.join(td, "x.json"), "w", encoding="utf-8") as fh:
                json.dump(cap, fh)
            proj = I.load_capture_projection(td)["x"]
        self.assertEqual(proj["depth"], "deep")
        self.assertEqual(proj["likes"], 0, "zero likes is an observation")
        self.assertEqual(proj["repo_url"], "https://github.com/o/x")
        self.assertNotIn("built_with", proj, "an unread tag list must not clear the row's stack")
        self.assertNotIn("demo_url", proj)
        self.assertNotIn("award", proj)

    def test_a_cost_disclosure_is_credited_as_what_it_is(self):
        """A challenges section about money is honest, but it is not a capability limit.

        Continuity discloses that every run costs a search plus several model calls and that
        fixtures are what made iteration affordable. That belongs in the ledger at 0.5; what did
        not belong there was the reason string, which said the page had no limitations section at
        all while quoting material from one.
        """
        cap = {"id": "fixture", "name": "Fixture", "source_url": "https://devpost.com/software/fixture",
               "built_with": [], "links": {}, "numbers": [], "testing": "",
               "sections": {"challenges": ("Every run costs money: one pass is a web search per claim "
                                           "plus several model calls, so we recorded fixtures on the "
                                           "first live run and replayed everything else from disk."),
                            "what_next": "A queue that ranks unresolved disagreements by page traffic."},
               "one_line": None}
        chk = A.run_checks(cap, None, None, {})[0]["limits_disclosed"]
        self.assertEqual((chk["status"], chk["pass"]), ("supported", 0.5), chk["why"])
        self.assertIn("operating constraints", chk["why"])
        self.assertNotIn("no limitations section", chk["why"])

    def test_a_recomputation_that_disagrees_is_not_reported_as_confirmation(self):
        """`reconciles: false` must cost the record, not buy it a `confirmed`.

        Continuity's page says "run all six stages" and then enumerates seven steps. We caught
        that by actually counting — which is exactly why it must not land in the tier reserved
        for figures that *add up*: a check that reports "recomputed, see above" on a mismatch
        tells the next reader the page is arithmetically sound when it is not.
        """
        cap = {"id": "fixture", "name": "Fixture", "source_url": "https://devpost.com/software/fixture",
               "sections": {}, "testing": "", "built_with": [], "links": {},
               "numbers": [{"claim": "'six stages' versus the seven listed steps",
                            "denominator": "the pipeline's own stage list",
                            "arithmetic": "internally inconsistent as written: seven enumerated, six claimed",
                            "verifiable": True, "reconciles": False, "load_bearing": False}]}
        chk = A.run_checks(cap, None, None, {})[0]["numbers_add_up"]
        self.assertEqual(chk["status"], "partial", chk["why"])
        self.assertEqual(chk["pass"], 0.5)
        self.assertIn("do not match", chk["why"])

    def test_a_disagreement_on_the_figure_the_case_rests_on_is_a_contradiction(self):
        """The load-bearing variant routes to `contradicted`, which the ladder then treats as unsound."""
        cap = {"id": "fixture", "name": "Fixture", "source_url": "https://devpost.com/software/fixture",
               "sections": {}, "testing": "", "built_with": [], "links": {},
               "numbers": [{"claim": "Latency 12 ms p95", "denominator": "400 logged sessions",
                            "arithmetic": "recomputed from the published log: 41 ms p95, not 12 ms",
                            "verifiable": True, "reconciles": False, "load_bearing": True}]}
        chk = A.run_checks(cap, None, None, {})[0]["numbers_add_up"]
        self.assertEqual((chk["status"], chk["pass"]), ("contradicted", 0.0), chk["why"])
        self.assertIn("does not reconcile", chk["why"])

    def test_rather_than_is_a_denial_of_the_thing_it_names(self):
        """"described rather than measured" must not read as a benchmark.

        The word carries the tier, so a comparative denial of it has to be filtered like the
        plain negations already are — otherwise a page earns credit for evaluation language by
        writing that it lacks the evaluation.
        """
        cap = {"id": "fixture", "name": "Fixture", "source_url": "https://devpost.com/software/fixture",
               "sections": {}, "built_with": [], "links": {}, "numbers": [],
               "testing": ("A real harness discipline is described rather than measured: the first live "
                           "run recorded fixtures so later runs replay free, and a test suite exists for "
                           "the core. No case count or pass rate is published.")}
        chk = A.run_checks(cap, None, None, {})[0]["test_or_eval_evidence"]
        self.assertLess(chk["pass"], 0.75, chk["why"])
        self.assertEqual(chk["status"], "partial", chk["why"])
        self.assertIn("harness", chk["why"].lower(), chk["why"])

    def test_a_recomputed_figure_outranks_a_structural_one(self):
        """`ok` must sit above `checkable` in the numbers ladder.

        SATU's headline is recomputable from the formula printed on the page and it also
        publishes latency figures a reader could re-measure. Crediting only the weaker tier
        because a branch was ordered badly is the quietest possible way to fail a good
        submission, and it did exactly that once.
        """
        cap = {"id": "fixture", "name": "Fixture", "source_url": "https://devpost.com/software/fixture",
               "sections": {}, "testing": "", "built_with": [], "links": {},
               "numbers": [
                   {"claim": "Composite 0.9672", "denominator": "per-session ranks and turns",
                    "arithmetic": "recomputed: 0.50*1.000 + 0.30*0.975 + 0.20*0.873 = 0.9671",
                    "verifiable": True},
                   {"claim": "Latency about 1 ms", "denominator": "harness runs",
                    "arithmetic": "structural: rerun the shipped harness to check", "verifiable": True}]}
        chk = A.run_checks(cap, None, None, {})[0]["numbers_add_up"]
        self.assertEqual((chk["status"], chk["pass"]), ("confirmed", 1.0), chk["why"])

    def test_a_figure_the_team_called_unfalsifiable_is_not_credit_as_checkable(self):
        """A disclaimer in the right tense is still a disclaimer.

        Fisheries-guard described its risk score as structural and explicitly not
        falsifiable; matching the word "structural" handed it the same tier as a figure a
        reader can actually open.
        """
        cap = {"id": "fixture", "name": "Fixture", "source_url": "https://devpost.com/software/fixture",
               "sections": {}, "testing": "", "built_with": [], "links": {},
               "numbers": [
                   {"claim": "Risk classification", "denominator": "no ground truth, per the page",
                    "arithmetic": "not falsifiable from the page: no evaluation set", "verifiable": False},
                   {"claim": "Real-time detection", "denominator": "no latency figure given",
                    "arithmetic": "structural: claimed capability, nothing to recompute", "verifiable": False}]}
        chk = A.run_checks(cap, None, None, {})[0]["numbers_add_up"]
        self.assertEqual((chk["status"], chk["pass"]), ("unverifiable", 0.25), chk["why"])

    def test_a_verified_repo_files_the_stack_even_when_the_tag_sidebar_is_empty(self):
        """The field asks what the project is built with, *verified*.

        A repository census answers that. A Devpost widget nobody filled in is a formatting
        gap on the page, and treating it as an unfiled mandatory field would leave the single
        most checkable record in the corpus looking less documented than one that published
        nothing — an unknown has to name something that would settle it, and here it already
        is settled.
        """
        cap = {"id": "fixture", "name": "Fixture", "source_url": "https://devpost.com/software/fixture",
               "one_line": "A shopping agent that answers with a slate and a question." * 2,
               "sections": {k: "It normalises the feed, folds state, then ranks candidates. " * 2
                              for k in ("inspiration", "what_it_does", "how_we_built_it", "challenges",
                                         "accomplishments", "learned", "what_next")},
               "data_and_models": "BM25 over the supplied catalog, no model in the scored path. " * 2,
               "testing": "Harness tests ship in the repository under harness/tests/. " * 2,
               "numbers": [], "built_with": [], "links": {"repo": "https://github.com/o/r"}}
        repo = {"exists": True, "size_kb": 900, "language": "Python",
                "languages": {"Python": 99.4, "Makefile": 0.6}, "test_paths": ["harness/tests/t.py"],
                "readme_bytes": 4000, "readme_has_setup": True, "source_dirs": ["src"],
                "pushed_at": "2026-09-01", "open_issues": 0, "default_branch": "main", "license": None}
        notes = {"worth": "breakthrough", "worth_note": "w" * 60, "what_to_steal": "s" * 60,
                 "what_breaks_first": "b" * 60, "prior_art": [], "hazard_note": "h" * 60,
                 "clone_cost": {"estimate": "2 days", "why": "c" * 60, "assumptions": ["a"]}}
        checks, _ = A.run_checks(cap, "o/r", repo, notes)
        fields, unknowns = A.build_fields(cap, notes, "o/r", repo, checks)
        self.assertIn("built_with_verified", fields, [x["field"] for x in unknowns])
        self.assertIn("python", json.dumps(fields["built_with_verified"]).lower())
        self.assertNotIn("built_with_verified", [x["field"] for x in unknowns])
        # a record with neither tags nor a repo keeps its unknown
        checks2, _ = A.run_checks({**cap, "links": {}}, None, None, notes)
        fields2, unknowns2 = A.build_fields({**cap, "links": {}}, notes, None, None, checks2)
        self.assertNotIn("built_with_verified", fields2)
        self.assertIn("built_with_verified", [x["field"] for x in unknowns2])

    def test_resubmission_merges_on_shared_numeric_fingerprints(self):
        sh = self.sheets["greenlight-screenplay-to-film"]
        self.assertEqual(sh["verdict"], "duplicate")
        self.assertEqual(sh["duplicate_of"], "greenlight-nine-agent-production-crew")
        self.assertFalse(sh["publishable"])
        self.assertTrue(any("duplicate" in a for a in self.actions), self.actions)

    def test_verdict_is_capped_when_rubric_coverage_is_thin(self):
        for sh in self.sheets.values():
            self.assertLessEqual(sh["rubric_coverage"], 1.0)
            if sh["verdict"] == "strong":
                self.assertGreaterEqual(sh["rubric_coverage"], 0.80,
                                        "A15: 'strong' needs rubric coverage, not just high scores")

    def test_a_denial_of_testing_is_not_read_as_evidence_of_testing(self):
        """The page saying "no test suite is described" must lower the score, not raise it.

        Both sentences contain the nouns "test" and "evaluation"; only the polarity makes
        them different claims, so the check is a polarity test and this is its pin.
        """
        def check_for(testing: str, sections: str):
            cap = {"id": "fixture", "name": "Fixture", "source_url": "https://devpost.com/software/fixture",
                   "sections": {"how_we_built_it": sections}, "testing": testing, "numbers": [],
                   "built_with": ["python"], "links": {"video": "https://youtu.be/x"}}
            return A.run_checks(cap, None, None, {})[0]["test_or_eval_evidence"]

        denial = check_for("No test suite, evaluation set or validation is described.",
                           "The model compares each reading against a personal baseline.")
        self.assertEqual(denial["status"], "unverifiable", denial["why"])
        self.assertEqual(denial["pass"], 0.0)
        # the same nouns, affirmed: still no repo, so supported at best — never confirmed
        affirmed = check_for("We ran a seeded regression set against the unoptimised path and logged 2x.",
                             "Nothing else on the page.")
        self.assertIn(affirmed["status"], ("supported", "partial"), affirmed["why"])
        self.assertLess(affirmed["pass"], 1.0)
        # an adjective is not an evaluation: "demanded precision" has no figure in it
        prose_only = check_for("No tests of any kind were run.",
                               "Coding the sync layer on a phone demanded precision and patience.")
        self.assertEqual(prose_only["status"], "unverifiable", prose_only["why"])

    def test_structural_figures_cannot_vouch_for_an_unmeasured_headline(self):
        """Ten styles is checkable by opening the app; a self-graded 100% is not a result."""
        cap = {"id": "fixture", "name": "Fixture", "source_url": "https://devpost.com/software/fixture",
               "sections": {"what_it_does": "Renders a photo in ten styles."},
               "testing": "", "built_with": ["react"], "links": {},
               "numbers": [{"claim": "ten art styles", "denominator": None,
                            "arithmetic": "structural, checkable in the live product", "verifiable": True},
                           {"claim": "97% accurate transcription", "denominator": None,
                            "arithmetic": "not falsifiable from the page", "verifiable": False}]}
        chk = A.run_checks(cap, None, None, {})[0]["numbers_add_up"]
        self.assertEqual(chk["status"], "partial", chk["why"])
        self.assertEqual(chk["pass"], 0.5)
        self.assertIn("headline", chk["why"].lower())
        # without the structural figure the same page is worse-evidenced, not equally so
        cap["numbers"] = cap["numbers"][1:]
        worse = A.run_checks(cap, None, None, {})[0]["numbers_add_up"]
        self.assertLess(worse["pass"], chk["pass"], (worse["why"], chk["why"]))

    def test_a_live_product_url_outranks_a_video_of_one(self):
        """A deployment any reader can open is a different kind of artifact than a recording."""
        def artifact(links):
            cap = {"id": "fixture", "name": "Fixture", "source_url": "https://devpost.com/software/fixture",
                   "sections": {}, "testing": "", "built_with": [], "links": links, "numbers": []}
            return A.run_checks(cap, None, None, {})[0]["artifact_exists"]

        live, video = artifact({"demo": "https://sketchwish.com"}), artifact({"video": "https://youtu.be/x"})
        self.assertGreater(live["pass"], video["pass"], (live["why"], video["why"]))
        self.assertEqual(live["status"], "supported", "unreachable from the build box, so never confirmed")
        zero = artifact({})
        self.assertEqual((zero["pass"], zero["status"]), (0.0, "unverifiable"))
        # and in the real ledger: SketchWish ships to a URL, AudioNova ships a video
        self.assertEqual(self.sheets["sketchwish"]["checks"]["artifact_exists"]["pass"], 0.75)
        self.assertEqual(self.sheets["audionova"]["checks"]["artifact_exists"]["pass"], 0.5)

    def test_one_product_under_two_listings_merges_while_two_teams_do_not(self):
        """A14/A5: identical published listing titles in one event = one product submitted twice.

        A name that differs by a suffix ("NeuroGuard AI" vs "NeuroGuard AI (v2)") is two teams
        converging on an idea, which is the most interesting thing in the corpus; it must be
        kept and cross-linked, never merged.
        """
        kept, dropped = self.sheets["adversarial-compliance-matrix"], self.sheets["gemini-box"]
        self.assertTrue(dropped["publishable"] is False and kept["publishable"] is True,
                        (kept["verdict"], dropped["verdict"]))
        self.assertEqual(dropped["verdict"], "duplicate")
        self.assertEqual(dropped["duplicate_of"], "adversarial-compliance-matrix")
        self.assertIn("listing-title equality True", dropped["verdict_reasons"][-1])
        pair = ("neuroguard-ai-0qb34c",
                "neuroguard-ai-adaptiveconcussionrecoveryintelligencesystem")
        for rid in pair:
            self.assertIsNone(self.sheets[rid].get("duplicate_of"), f"{rid}: parallel invention is not a duplicate")
        self.assertEqual(self.sheets[pair[0]].get("parallel_invention_of"), pair[1])
        self.assertEqual(self.sheets[pair[1]].get("parallel_invention_of"), pair[0])
        self.assertTrue(any("parallel invention" in a for a in self.actions), self.actions)

    def test_a_short_tag_list_is_still_a_filed_mandatory_field(self):
        """A 40-character floor for prose must not turn a real enumeration into a hole."""
        published = [sh for sh in self.sheets.values() if sh["publishable"]]
        self.assertTrue(published)
        for sh in published:
            self.assertIn("built_with_verified", sh["fields"], f"{sh['id']}: mandatory field unfiled")
            self.assertNotIn("built_with_verified", [u["field"] for u in sh["unknowns"]])
        # and the field has to say whether anything corroborates the tags it lists
        stated = [sh for sh in published
                  if "no repository published" in sh["fields"]["built_with_verified"]["value"]]
        self.assertTrue(stated, "an uncorroborated stack claim must be labelled as one")

    def test_a_ui_name_is_not_a_measurement_loop(self):
        """"dashboard" names a screen here; a measurement loop has to measure something."""
        cap = {"id": "fixture", "name": "Fixture", "source_url": "https://devpost.com/software/fixture",
               "sections": {"how_we_built_it": "The platform adds a dashboard for the operator."},
               "testing": "No test suite, eval set or benchmark is described.", "numbers": [],
               "built_with": [], "links": {}}
        chk = A.run_checks(cap, None, None, {})[0]["test_or_eval_evidence"]
        self.assertEqual(chk["status"], "unverifiable", chk["why"])
        cap["testing"] = ("We watch a PostHog funnel on the live app and logged a 2x conversion "
                          "difference after fixing the sign-in button.")
        loop = A.run_checks(cap, None, None, {})[0]["test_or_eval_evidence"]
        self.assertEqual(loop["status"], "partial", loop["why"])
        self.assertGreater(loop["pass"], chk["pass"])

    def test_an_audited_hold_is_labelled_as_scored_not_unchecked(self):
        """`provenance: unaudited` on a record this pipeline *did* score is a false statement,
        and "go fetch a project page" on a page we already fetched wastes the next auditor's
        time. The two kinds of pool row have to be tellable apart without opening the sheets."""
        pub = os.path.join(REPO, "web", "public")
        pool_path, audit_path = f"{pub}/data/pool.json", os.path.join(REPO, "pipeline", "audit.jsonl")
        if not (os.path.exists(pool_path) and os.path.exists(audit_path)):
            self.skipTest("built surfaces not present; run `make build`")
        sheets = {sh["id"]: sh for sh in (json.loads(l) for l in open(audit_path, encoding="utf-8"))}
        rows = {r["id"]: r for r in json.load(open(pool_path, encoding="utf-8"))["records"]}
        held = [rid for rid, sh in sheets.items()
                if not sh["publishable"] and rid in rows]
        self.assertTrue(held, "expected at least one audited-but-held record")
        for rid in held:
            row = rows[rid]
            self.assertEqual(row["provenance"], "audited-hold", rid)
            self.assertEqual(row["verdict"], sheets[rid]["verdict"], rid)
            self.assertEqual(row["worth"], sheets[rid].get("worth"), rid)
            self.assertEqual(row["soundness_score"], sheets[rid]["soundness_score"], rid)
            self.assertTrue(row["would_settle_it"], f"{rid}: a hold without a next step is a dead end")
            self.assertNotIn("a fetched project page and an artifact check", row["would_settle_it"],
                            f"{rid}: already captured, so must not be told to go fetch the page")
        unchecked = [r for r in rows.values() if r["provenance"] == "unaudited"]
        self.assertTrue(unchecked)
        for row in unchecked:
            self.assertFalse(row.get("verdict"), f"{row['id']}: unaudited rows must not carry a verdict")

    def test_a_team_that_disclaimed_is_not_recorded_as_silent(self):
        """The hazard stamp may say a claim is regulated; it may not invent a missing disclaimer."""
        disclaimed = self.sheets["neuroguard-ai-0qb34c"]
        self.assertEqual(disclaimed["hazard"]["class"], "clinical")
        self.assertTrue(disclaimed["hazard"]["team_disclaimed"],
                        "the page reads 'positioned as recovery support, not a diagnostic replacement'")
        self.assertNotIn("hazard: clinical (no team disclaimer found)",
                         disclaimed.get("why_not_promoted") or [])
        silent = self.sheets["medvoice-y87kei"]
        self.assertFalse(silent["hazard"]["team_disclaimed"],
                         "medvoice's capture contains no disclaimer of its own, so the stamp must say so")
        self.assertIn("hazard: clinical (no team disclaimer found)", silent["why_not_promoted"])

    def test_a_denominator_that_denies_itself_is_not_a_measurement(self):
        """"over 95% accuracy", denominator: "unstated" is a claim plus a confession.

        The confession has to win: an audit that scores the number and shrugs at the gap is
        how a page's marketing percentage becomes a certified result.
        """
        cap = {"id": "fixture", "name": "Fixture", "source_url": "https://devpost.com/software/fixture",
               "sections": {"accomplishments": "We achieved over 95% accuracy parsing lab PDFs."},
               "testing": ("The one quantified result - over 95% accuracy - has no denominator: "
                           "no document count, no held-out set, no definition of correct."),
               "numbers": [{"claim": "over 95% accuracy parsing lab PDFs",
                            "denominator": "unstated - no document count or provider breakdown",
                            "arithmetic": "not falsifiable from the page", "verifiable": False},
                           {"claim": "nine biomarkers in the clock", "denominator": "the model's parameter set",
                            "arithmetic": "structural: checkable against the published table", "verifiable": True}],
               "built_with": [], "links": {"video": "https://youtu.be/x"}}
        chk = A.run_checks(cap, None, None, {})[0]["test_or_eval_evidence"]
        self.assertEqual(chk["status"], "partial", chk["why"])
        self.assertLessEqual(chk["pass"], 0.5)
        # a real denominator still earns the higher tier
        cap["numbers"][0]["denominator"] = "412 lab PDFs from 3 providers, held-out 84"
        cap["numbers"][0]["verifiable"] = True
        cap["numbers"][0]["arithmetic"] = "recomputed: 392/412 = 95.1%"
        better = A.run_checks(cap, None, None, {})[0]["test_or_eval_evidence"]
        self.assertIn(better["status"], ("supported", "confirmed"), better["why"])

    def test_an_advice_loop_in_a_regulated_domain_is_flagged_without_the_word_diagnosis(self):
        """The exposure is telling a person what to take; "we do not diagnose" was never the risk."""
        cap = {"id": "fixture", "name": "Fixture", "source_url": "https://devpost.com/software/fixture",
               "sections": {"what_it_does": "A weekly engine returns the top three supplement "
                            "and protocol interventions to move your score."},
               "one_line": "A dashboard that recommends lifestyle protocols.", "testing": "",
               "numbers": [], "built_with": [], "links": {}}
        rec = {"domain": "Health, Care & Human Performance", "summary": "biological age dashboard"}
        hz = A.hazard_for(rec, cap, {})
        self.assertIsNotNone(hz, "advice inside a clinical domain is a hazard whether or not it says diagnose")
        self.assertEqual(hz["class"], "clinical")
        self.assertFalse(hz["team_disclaimed"])
        chart = {"id": "fixture", "name": "Fixture", "source_url": "https://devpost.com/software/x",
                 "sections": {"what_it_does": "Charts the resting heart rate you already track."},
                 "one_line": "A chart of wearable data.", "testing": "", "numbers": [],
                 "built_with": [], "links": {}}
        self.assertIsNone(A.hazard_for(rec, chart, {}), "visualisation alone is not a regulated claim")

    def test_nothing_publishable_is_banned_language_free(self):
        for sh in self.sheets.values():
            if not sh["publishable"]:
                continue
            blob = json.dumps(sh.get("fields"), ensure_ascii=False).lower()
            for w in T.BANNED_VERDICT_WORDS:
                self.assertIsNone(re.search(r"\b" + w + r"\w*\b", blob), f"{sh['id']} uses {w}")


def audit_sheets_for(records, over=None):
    """Publishable audit sheets for fixture records. The catalog is audited-only, so a
    fixture build that expects rows has to declare the vetting (A1)."""
    rub = T.audit_rubric()
    sheets = {}
    for r in records:
        rid = str(r["id"])
        ev = [{"id": "ev1", "kind": "video", "source": "devpost",
               "locator": f"https://devpost.com/software/{rid}", "status": "supported",
               "quote": "how we built it"}]
        sheet = {
            "id": rid, "audit_version": T.AUDIT_VERSION, "audited_at": "2026-09-18",
            "name": r.get("name"), "sector": r.get("domain"), "url": r.get("url"),
            "verdict": "sound-with-caveats", "worth": "strong",
            "worth_note": "the cost-ladder gate is the transferable idea",
            "soundness": "supported", "soundness_score": 0.9, "rubric_coverage": 1.0,
            "publishable": True, "duplicate_of": None, "hazard": "ok",
            "why_not_promoted": None, "evidence": ev,
            "checks": {c: {"status": "supported", "pass": 1.0, "why": "fixture evidence",
                           "evidence": ["ev1"]} for c in rub["checks"]},
            "fields": {f: {"value": "fixture", "status": "filed", "confidence": "medium",
                           "evidence": ["ev1"]} for f in rub["mandatory_fields"]},
            "unknowns": [], "repo": {"url": r.get("repo_url")},
        }
        sheet["fields"]["what_to_steal"]["value"] = "the cost ladder"
        sheet["fields"]["clone_cost"]["value"] = {"estimate": "one weekend",
                                                 "why": "no training, one table",
                                                 "assumptions": ["one reviewer", "no billing"]}
        sheet["fields"]["prior_art"]["value"] = [{"title": "Runway", "url": "https://runway.com"}]
        for k, v in (over or {}).get(rid, {}).items():
            sheet[k] = v
        sheets[rid] = sheet
    return sheets


class TestShelvingAcademy(unittest.TestCase):
    """A name that says "Academy" has to beat a tag list that says "postgres".

    Two bugs in one: the Learning lexicon had no institution words at all, and `core` includes
    the Built With tags — so the moment a capture put honest tags on a row, an education product
    started shelving under Data Infrastructure on the strength of `sqlite, node.js, fastapi`.
    """

    def test_an_academy_shelves_with_education_not_with_its_tags(self):
        rec = {"name": "AX4U Academy",
               "summary": "AI Skills. Real Results. Build with AI. Learn AI by Doing. Practical AI Academy.",
               "built_with": ["fastapi", "firebase", "gcp", "geminiapi", "github", "html/css",
                              "javascript", "node.js", "python", "sqlite", "streamlit"]}
        domain, sub, margin = T.classify_record(rec)
        self.assertEqual(domain, "Learning & Knowledge Systems", (domain, sub, margin))
        self.assertEqual(sub, "Tutors & Adaptive Learning", (domain, sub, margin))

    def test_the_same_tags_under_a_non_education_name_stay_out_of_learning(self):
        """The fix must not become a rule that any stack list is an education signal."""
        rec = {"name": "Syncboard", "summary": "Postgres-backed sync console for ops teams.",
               "built_with": ["fastapi", "firebase", "gcp", "github", "javascript", "node.js",
                              "python", "sqlite", "streamlit"]}
        domain, sub, margin = T.classify_record(rec)
        self.assertNotEqual(domain, "Learning & Knowledge Systems", (domain, sub, margin))


class TestShelvingSubjectVocabulary(unittest.TestCase):
    """A shelf is a claim about what a product is *for*, so only subject text may decide it.

    Batch 5 found two opposite leaks at once. A news-comparison engine shelved under "Games &
    Interactive Fiction" and a salvage-estimation tool under Climate, both at margin 0.00,
    because Public Trust had no news vocabulary and Money had no pricing vocabulary: the win
    came from a single subsystem word ("game" in one, "vision" and "emission" in the other).
    Folding captured prose in then created the mirror-image leak — our own `learned` section,
    which began "The lesson the page argues hardest is…", moved a car tool into Learning. Both
    halves are pinned here: the sectors must recognise their subjects, and the classifier must
    read only text that describes the subject.
    """

    def test_a_news_product_reaches_the_sector_that_owns_verification(self):
        rec = {"name": "Newspectives - new perspective on news",
               "summary": "One news event. Every regional lens. Side-by-side. Compares how USA, "
                          "China, Russia and the Arab World frame each story - daily.",
               "built_with": ["react", "typescript", "vite"]}
        domain, sub, margin = T.classify_record(rec)
        self.assertEqual(domain, "Public Trust, Safety & Compliance", (domain, sub, margin))
        self.assertEqual(sub, "Civics & Discourse", (domain, sub, margin))
        self.assertGreater(margin, 0.0, "a tie means the shelf is arbitrary, which is what broke")

    def test_an_editorial_tool_does_not_fall_to_the_entertainment_sectors(self):
        rec = {"name": "Headline Lens",
               "summary": "An editorial desk that checks a claim against each country's press "
                          "before the story is published.", "built_with": []}
        domain, sub, margin = T.classify_record(rec)
        self.assertNotIn(domain, ("Creative Media, Story & Play", "Emerging & Cross-Domain"),
                         (domain, sub, margin))

    def test_pricing_an_asset_is_commerce_even_when_the_tool_uses_vision(self):
        rec = {"name": "Carbender",
               "summary": "Identifies damaged car parts, estimates repair costs and turns photos "
                          "into OEM part lists with real-market price reports and a resale-value "
                          "verdict.",
               "built_with": ["next.js", "typescript", "prisma", "postgresql", "stripe"]}
        domain, sub, margin = T.classify_record(rec)
        self.assertEqual(domain, "Money, Commerce & Marketplaces", (domain, sub, margin))
        self.assertNotEqual(domain, "Climate, Energy & the Physical World")

    def test_the_stack_a_product_runs_on_is_not_its_subject(self):
        """`what_it_does` is the captured text the classifier may read, so the projection is the
        seam. `how_we_built_it` and `data_and_models` describe storage, and storage vocabulary
        (`state`, `index`, `ledger`) outvoted the product: a compliance harness moved to Data
        Infrastructure and an orchestration platform's margin fell from 0.71 to 0.14."""
        import ingest_seed as I
        self.assertEqual(tuple(I.CAPTURE_CLASSIFY_SECTIONS), ("what_it_does",))


class TestEvidenceTiersAreNamedByTheirEvidence(unittest.TestCase):
    """What a page measured has to match what the check claims it measured."""

    @staticmethod
    def _cap(testing, nums, challenges="We tuned the splash screen."):
        return {"id": "fixture", "name": "Fixture",
                "source_url": "https://devpost.com/software/fixture",
                "sections": {"what_it_does": "It reads a corpus and answers questions.",
                             "challenges": challenges},
                "testing": testing, "numbers": nums, "built_with": ["python"],
                "links": {"video": "https://youtu.be/x"}}

    def test_a_performance_figure_is_not_an_evaluation_of_the_output(self):
        """'TTI 40s to 0.9s' is a real measurement of the build, not a check of what the system
        produces; crediting it at the top tier told readers a news engine's journalism was
        evaluated when only its load time was."""
        cap = self._cap(
            "Time to interactive was measured before/after: 40s to 0.9s on mobile Safari.",
            [{"claim": "TTI 40s to 0.9s", "denominator": "first interactive on mobile Safari",
              "verifiable": False,
              "arithmetic": "not falsifiable from the page: no device list, network condition or sample size"}])
        chk = A.run_checks(cap, None, None, {})[0]["test_or_eval_evidence"]
        self.assertEqual(chk["pass"], 0.5, chk["why"])
        self.assertIn("no harness, held-out set or method behind it", chk["why"])
        self.assertIn("measurement words", chk["why"], "the why must name the figure it found")

    def test_a_quality_metric_with_a_recomputed_figure_reaches_the_supported_tier(self):
        cap = self._cap(
            "Held-out accuracy was 95.1% against a 412-clip labelled set, versus 71% for the baseline.",
            [{"claim": "95.1% held-out accuracy", "denominator": "412 labelled clips",
              "verifiable": True, "arithmetic": "recomputed: 392/412 = 95.1%"}])
        chk = A.run_checks(cap, None, None, {})[0]["test_or_eval_evidence"]
        self.assertIn(chk["pass"], (0.75, 1.0), chk["why"])

    def test_a_config_block_is_not_a_limitation_of_the_system(self):
        """`block` used to be a capability cue, so 'the hosting block in firebase.json' read as
        a disclosure of what the product cannot do."""
        cap = self._cap("", [], challenges="The hosting block in firebase.json was silently "
                        "ignored, so the sitemap and RSS were proxied by hand in server.ts.")
        chk = A.run_checks(cap, None, None, {})[0]["limits_disclosed"]
        self.assertLess(chk["pass"] or 0.0, 1.0, chk["why"])

    def test_naming_the_limits_of_its_own_data_is_a_disclosure(self):
        """A page can admit a limit without writing 'we cannot': the noun phrase counts."""
        cap = self._cap("", [], challenges="Coverage is thin outside the EU, so the interface "
                        "carries advisory banners whose job is to communicate the limits of the "
                        "parts catalog instead of returning an empty result.")
        chk = A.run_checks(cap, None, None, {})[0]["limits_disclosed"]
        self.assertEqual((chk["pass"], chk["status"]), (1.0, "confirmed"), chk["why"])
        self.assertIn("what the system itself cannot do", chk["why"])

    def test_a_failure_post_mortem_says_fail_not_cannot(self):
        """Same tier, different evidence, and the sentence has to tell them apart."""
        cap = self._cap("", [], challenges="The music API failed quietly: a null payload produced "
                        "an undefined task id and the client polled it fifty times, so the server "
                        "now returns a real 502 and bails after five nulls.")
        chk = A.run_checks(cap, None, None, {})[0]["limits_disclosed"]
        self.assertEqual(chk["pass"], 1.0, chk["why"])
        self.assertIn("where the system fails", chk["why"], chk["why"])


class TestHazardFollowsTheClaimNotTheShelf(unittest.TestCase):
    """A13 says the hazard is stamped from what a page asserts; a shelf change must not lose it."""

    REC = {"domain": "Money, Commerce & Marketplaces", "summary": "salvage repair estimate tool"}

    def test_invoking_a_regulator_is_a_claim_in_any_sector(self):
        cap = {"sections": {"what_it_does": "Each estimate is graded against DOT and SAE standards, "
                            "with the loss bands described as matching EU salvage threshold standards."},
               "one_line": "A repair estimate with a total-loss verdict.", "testing": "", "numbers": []}
        hz = A.hazard_for(self.REC, cap, {})
        self.assertIsNotNone(hz, "the exposure is the borrowed authority, not the sector")
        self.assertEqual(hz["class"], "regulated-claim")
        self.assertFalse(hz["team_disclaimed"])

    def test_the_word_standard_alone_is_not_a_hazard(self):
        cap = {"sections": {"what_it_does": "The layout follows a standard grid of cards."},
               "one_line": "A design surface.", "testing": "", "numbers": []}
        self.assertIsNone(A.hazard_for(self.REC, cap, {}))


class TestSignalsAreNotWordCollisions(unittest.TestCase):
    """Three published records carried a hazard because of a substring, and one nearly carried a testing
    rung because of a hosting plan. `HAZARD_CLAIM_RE`'s clinical words are also ordinary English - a
    "diagnosis" of why teams lose hackathons (tower-dq18x2), the "screen" inside "screenplay" (both
    Greenlight records) and inside "splash screen" (newspectives) each stamped `regulated-claim` with a
    note about missing clinical validation - and a stack bullet that Firebase supplies analytics was
    read as a product measurement loop (attaindesk). Each fix is a rule about what the *sentence*
    claims, so these tests pin the sentence, not the record."""

    REC = {"domain": "Agentic Autonomy & Orchestration",
           "summary": "a watcher that re-checks a rulebook against live artifacts"}

    @staticmethod
    def _cap(text, testing=""):
        return {"id": "fixture", "name": "Fixture",
                "source_url": "https://devpost.com/software/fixture",
                "sections": {"what_it_does": text},
                "testing": testing, "numbers": [], "built_with": ["python"],
                "links": {"video": "https://youtu.be/x"}}

    def test_a_metaphor_about_a_failure_mode_is_not_a_clinical_claim(self):
        self.assertIsNone(A.hazard_for(self.REC, self._cap(
            "Our diagnosis is that nobody loses a competition because the idea was bad; teams lose on"
            " unmet requirements."), {}),
            "diagnosing a failure mode is English, not an assertion about a regulated outcome")

    def test_a_screenplay_is_not_clinical_screening(self):
        self.assertIsNone(A.hazard_for(self.REC, self._cap(
            "One model holds the whole screenplay in mind at once; the others read scenes."), {}))

    def test_a_bare_word_still_stamps_when_it_has_a_clinical_object(self):
        hz = A.hazard_for(self.REC, self._cap(
            "The tool screens patients between plays and flags missed doses to a clinician."), {})
        self.assertIsNotNone(hz, "the guard is about the missing object, not the missing word")
        self.assertEqual(hz["class"], "regulated-claim")

    def test_a_platform_capability_is_not_a_measurement_loop(self):
        cap = self._cap("It runs on Google Cloud, with authentication, logging and analytics features "
                        "provided by Firebase.",
                        testing="No test suite, eval or measured result is described on the page.")
        cap["sections"]["how_we_built_it"] = cap["sections"]["what_it_does"]
        chk = A.run_checks(cap, None, None, {})[0]["test_or_eval_evidence"]
        self.assertEqual(chk["pass"], 0.0, "a stack line must not buy a rung on the testing ladder: " + chk["why"])

    def test_one_reconciling_figure_does_not_certify_the_headline(self):
        """`numbers_add_up: confirmed` has to mean the record's numbers hold up, not that one of them
        does. zeroday-ai reconciled its Like count against two named likers and was credited at 1.0 while
        the sentence it sells itself on — "webhook to tested pull request in under 30 seconds" — has no
        run count, no repository size and no defined endpoints, so there is nothing to time. A
        reconciliation and an untestable claim are both findings; both get said."""
        cap = {"id": "fixture", "name": "Fixture",
               "source_url": "https://devpost.com/software/fixture",
               "sections": {"what_it_does": "It reads a finding, writes a patch, opens a pull request."},
               "testing": "No eval set or result is published.", "built_with": ["python"],
               "links": {"video": "https://youtu.be/x"},
               "numbers": [
                   {"claim": "2 likes", "denominator": "the likers listed on the page",
                    "arithmetic": "reproduces: two named likers are listed under the Like button",
                    "verifiable": True},
                   {"claim": "under 30 seconds end to end", "denominator": "one pipeline run",
                    "arithmetic": "not falsifiable from the page: no run count, no repository size, no "
                                  "breakdown of the interval, no repository to check the pipeline against",
                    "verifiable": False}]}
        chk = A.run_checks(cap, None, None, {})[0]["numbers_add_up"]
        self.assertEqual(chk["pass"], 0.5, chk["why"])
        self.assertEqual(chk["status"], "partial")
        self.assertIn("reconcile", chk["why"], "the half that checks out must stay in the sentence")
        self.assertIn("no testable denominator", chk["why"])

    def test_a_measurement_claim_in_the_testing_field_is_credited(self):
        cap = self._cap("The digest ships weekly.",
                        testing="We instrumented the send path and watch delivery funnels on the live "
                                "product.")
        chk = A.run_checks(cap, None, None, {})[0]["test_or_eval_evidence"]
        self.assertEqual(chk["pass"], 0.5, chk["why"])


class TestHeldRecordsKeepWhatWeLearned(unittest.TestCase):
    """A held record has no file under `data/audits/` - sheets are emitted only for admitted rows - so
    the pool surface used to show it as the marketing blurb plus a verdict. attaindesk sat there as
    "turns AI into one-click business operations for SMBs" beside an audit that had established it has
    paying customers and measures nothing, and a reader could see neither half. The audit row is the
    same shape whether or not it publishes, so the pool row carries the parts that decide whether to
    re-capture."""

    def test_pool_rows_for_scored_records_carry_the_captured_detail(self):
        with open(os.path.join(REPO, "web/public/data/pool.json"), encoding="utf-8") as fh:
            pool = json.load(fh)
        scored = [r for r in pool["records"] if r.get("provenance") == "audited-hold"]
        self.assertTrue(scored)
        for r in scored:
            self.assertIn("detail", r, r["id"] + " was captured and audited; the pool must not "
                          "publish it as a bare verdict")
            self.assertIn("what_it_is", r["detail"])
        for r in pool["records"]:
            if r.get("provenance") == "unaudited":
                self.assertNotIn("detail", r, "nothing was captured, so nothing may be asserted")


class TestServedSurfacesAreSwept(unittest.TestCase):
    """A file under `web/public/` is an answer to someone's question, so it must be emitted by the
    build that serves it. Sector audit sheets are addressed by a guessable, API-advertised path
    (`data/audits/<sector>.json`), which means a sector that stops publishing must stop *having* a
    file: the build once left a superseded sheet for Developer Tooling whose `moves` disagreed with the
    record's current sheet elsewhere, and the size budget under-counted it because the budget sums what
    is emitted."""

    def test_no_sector_sheet_without_published_records(self):
        import shard_builder as S
        want = set()
        with open(os.path.join(REPO, "web/public/data/ideas.ndjson"), encoding="utf-8") as fh:
            for line in fh:
                if line.strip():
                    want.add(S.slugify(json.loads(line).get("domain") or ""))
        served = {os.path.basename(p)[:-5] for p in
                  glob.glob(os.path.join(REPO, "web/public/data/audits/*.json"))}
        self.assertEqual(served, want, "the sector sheets served are not exactly the sectors with "
                        "published records — a stale sheet is a superseded answer at a live URL")

    def test_build_sweeps_a_superseded_sheet_file(self):
        import shard_builder as S
        with tempfile.TemporaryDirectory() as td:
            S.build(S.load_corpus(os.path.join(REPO, "pipeline/corpus.jsonl")), td,
                    S.corpus_as_of(S.load_corpus(os.path.join(REPO, "pipeline/corpus.jsonl"))),
                    S.load_audits())
            ghost = os.path.join(td, "data/audits/sector-that-nobody-publishes.json")
            with open(ghost, "w", encoding="utf-8") as fh:
                fh.write('{"records": {"x": {"verdict": "strong"}}}')
            S.build(S.load_corpus(os.path.join(REPO, "pipeline/corpus.jsonl")), td,
                    S.corpus_as_of(S.load_corpus(os.path.join(REPO, "pipeline/corpus.jsonl"))),
                    S.load_audits())
            self.assertFalse(os.path.exists(ghost), "re-emitting left a sector sheet behind")


class TestScaleHarness(unittest.TestCase):
    """The parallelism plan (docs/PARALLELISM_PANEL.md) is argued from measurements, so the
    measurements have to be code. These two tests are what stop ADR-P11 from rotting: the blocked
    similarity pass must stay lossless against a brute-force reference, and the per-record sheet cost
    the budget argument rests on must stay in the range the dossier quotes."""

    def test_blocked_similarity_pass_is_lossless_against_the_reference(self):
        import bench_scale
        same, ref_actions, blocked_actions = bench_scale.blocking_is_lossless()
        self.assertTrue(same, "blocking changed a verdict, a reason, a cross-link or a sheet byte")
        self.assertEqual(ref_actions, blocked_actions, "the blocked pass raised a different set of "
                        "duplicate actions — admission changed, which is a catalog change")

    def test_budget_math_keeps_the_sector_ceiling_measurable(self):
        import bench_scale
        import pathlib
        bud = bench_scale.budget_math(pathlib.Path(REPO))
        per_record = bud["gzip_kb_per_published_record"]
        self.assertGreater(per_record, 0.5, "a published sheet under half a KB gz is not a detailed record")
        self.assertLess(per_record, 10.0, f"{per_record} KB gz per published record means the prose "
                        "budget in docs/PARALLELISM_PANEL.md M8 has to be restated")
        self.assertGreaterEqual(bud["published_records_per_sector_at_budget"], 1)
        self.assertLess(bud["published_records_per_sector_at_budget"], 1000,
                        "if a sector could hold 1,000 records the re-shard (ADR-P5) is unnecessary "
                        "and the dossier's blocking objection was wrong")


class TestThroughputRails(unittest.TestCase):
    """ADR-P1/P2/P4/P9. A batch can only get bigger if four things are true at once: a record's mutable
    facts are one file each, a half-read capture is refused at the boundary instead of repaired by a
    reviewer, two sessions can never be handed the same id, and the batch size is edited by the lint's
    reject rate rather than by anyone's confidence. Each test names the failure it prevents."""

    def test_notes_cannot_be_installed_before_the_capture(self):
        """The two files are one unit of work; installing the argument before the evidence is how a
        refused capture leaves a judgement file with nothing to be about."""
        import capture_lint as L
        rows = L.validate_blob("notes", {"id": "no-such-record-zzz", "worth": "niche",
                                         "worth_note": "x", "what_to_steal": "y",
                                         "what_breaks_first": "z", "prior_art": [{"corpus_id": None,
                                                                                 "relation": "r"}],
                                         "clone_cost": {"estimate": "days", "why": "w"}})
        self.assertIn("notes.order", [r["rule"] for r in rows])

    def test_notes_are_one_file_per_record_and_the_legacy_dict_is_empty(self):
        """P4, or the throughput is spent resolving write collisions: three writers on one notes file
        was M10, and a merge conflict in the judgement fields is worse than a slow build."""
        notes = A.load_notes()
        self.assertTrue(os.path.isdir(os.path.join(REPO, "pipeline/raw/audit_notes")))
        self.assertEqual(len(notes), len(A.load_captures()),
                         "every captured record needs a note file, or its sheet publishes placeholders")
        with open(os.path.join(REPO, "pipeline/raw/audit_notes.json"), encoding="utf-8") as fh:
            self.assertEqual(json.load(fh), {},
                             "the legacy dict must be emptied, not kept as a second source of truth")
        for rid, ent in notes.items():
            for key in ("worth", "worth_note", "what_to_steal", "what_breaks_first",
                        "prior_art", "clone_cost"):
                self.assertIn(key, ent, f"{rid} is missing the {key} the sheet renders")

    def test_every_committed_capture_satisfies_the_contract(self):
        import capture_lint as L
        bad = [f.id for f in (L.lint_one(rid) for rid in L.all_ids()) if not f.ok]
        self.assertEqual(bad, [], "a committed capture that fails the gate bricks `make verify`: "
                         + ", ".join(bad))
        legacy = sorted(f.id for f in (L.lint_one(r) for r in L.all_ids()) if f.legacy)
        self.assertLessEqual(len(legacy), 4,
                             "grandfathered v1 captures may only shrink (retire them by re-capturing): "
                             + ", ".join(legacy))

    def test_a_half_read_capture_is_refused_by_rule_name(self):
        """P1's acceptance criterion: the *named* rule, and the install path refuses rather than
        accepting-and-repairing, which is the difference between a gate and a suggestion."""
        import capture_lint as L
        path = os.path.join(REPO, "pipeline/raw/deep_captures/tower-dq18x2.json")
        with open(path, encoding="utf-8") as fh:
            cap = json.load(fh)
        cap = dict(cap)
        cap["sections"] = {k: v for k, v in cap["sections"].items() if k != "learned"}
        f = L.lint_capture(cap, {}, {})
        self.assertIn("capture.sections.seven", [r["rule"] for r in f.rows])
        self.assertTrue(f.rows[0]["fix"], "a violation without a fix line just moves the work later")
        rows = L.validate_blob("capture", cap)
        self.assertTrue(any(r["rule"] == "capture.sections.seven" for r in rows),
                        "--install-capture must refuse the same payload")
        # and refusing must mean *nothing written*, so a worker cannot half-install a record
        import subprocess
        bad = subprocess.run([sys.executable, os.path.join(REPO, "pipeline/capture_lint.py"),
                              "--install-capture", "lint-selftest"],
                             input=json.dumps({"id": "lint-selftest"}), capture_output=True,
                             text=True, cwd=REPO)
        self.assertNotEqual(bad.returncode, 0)
        self.assertIn("capture.schema", bad.stdout, "the version key is what makes the contract explicit")
        self.assertFalse(os.path.exists(os.path.join(REPO, "pipeline/raw/deep_captures/lint-selftest.json")),
                         "a refused payload must not reach the tree")

    def test_the_installer_refuses_exactly_what_the_gate_refuses(self):
        """`--install-*` is a preview of the gate, so the two must agree on every payload: a stricter
        installer tells a worker to invent prose for a page that has none, and a looser one ships a
        capture that `make verify` will refuse three stages later. This disagreement is what fired on the
        first real payload through the installer — a Showcase entry with no challenges section."""
        import capture_lint as L
        path = os.path.join(REPO, "pipeline/raw/deep_captures/tower-dq18x2.json")
        with open(path, encoding="utf-8") as fh:
            base = json.load(fh)
        for mutate in (lambda c: c["sections"].pop("challenges"),
                       lambda c: c["sections"].__setitem__("challenges", ""),
                       lambda c: c["sections"].__setitem__("challenges", "Short"),
                       lambda c: c.pop("gallery_images"),
                       lambda c: c["links"].__setitem__("repo", "see their github"),
                       lambda c: c["numbers"].__setitem__(0, {"claim": "96%"})):
            cap = json.loads(json.dumps(base))
            mutate(cap)
            # one payload kind at a time: `--install-capture` previews the capture rules, and the
            # notes rules belong to `--install-notes`, which refuses its own kinds separately
            gate = {r["rule"] for r in L.lint_capture(cap, None, {}).rows
                    if r["rule"].startswith("capture.")}
            gate.discard("capture.keys")          # v1 grandfathering applies only to on-disk records
            gate.discard("capture.numbers.verifiable")
            inst = {r["rule"] for r in L.validate_blob("capture", cap) if r["rule"].startswith("capture.")}
            self.assertTrue(gate <= inst or inst <= gate,
                            f"installer and gate disagree on {sorted(gate ^ inst)}: one of them is wrong")

    def test_a_default_hazard_note_is_a_refusal_not_a_fallback(self):
        """The shape of the Tower defect: a stamp attached to the engine's generic sentence because the
        notes file had nothing in it. Either the stamp is wrong or the note is missing; the lint refuses
        until someone decides which, because the fallback reads exactly like a finding."""
        import capture_lint as L
        cap = {"id": "fixture", "schema": 2, "one_line": "A sideline tool for teams.",
               "sections": {"what_it_does": "It screens patients between plays and flags missed doses "
                                             "to a clinician."},
               "testing": "", "numbers": []}
        f = L.Findings("fixture")
        L.lint_notes_for_hazard("fixture", cap, {}, f)
        self.assertIn("notes.hazard-note-when-stamped", [r["rule"] for r in f.rows])
        f2 = L.Findings("fixture")
        L.lint_notes_for_hazard("fixture", cap,
                                {"hazard_note": "The page offers a dosing flag to a clinician and "
                                                "disclaims nothing."}, f2)
        self.assertEqual(f2.rows, [], "with a note of our own, the record is admissible")

    def test_partitions_are_disjoint_stable_and_complete(self):
        """P2's only interesting property: a worker set of four must cover every candidate exactly once,
        and re-ranking the queue must not move an id mid-batch."""
        from taxonomy_hacks import partition_of
        ids = []
        with open(os.path.join(REPO, "pipeline/corpus.jsonl"), encoding="utf-8") as fh:
            for line in fh:
                if line.strip():
                    ids.append(json.loads(line)["id"])
        self.assertTrue(ids)
        for width in (1, 3, 4, 7):
            buckets = {i: [] for i in range(width)}
            for rid in ids:
                buckets[partition_of(rid, width)].append(rid)
            self.assertEqual(sorted(x for b in buckets.values() for x in b), sorted(ids),
                             f"width {width} must cover every id exactly once")
            self.assertTrue(all(b for b in buckets.values()),
                            f"width {width} left an idle worker while records waited: {buckets}")
        self.assertEqual([partition_of(r, 4) for r in ids],
                         [partition_of(r, 4) for r in list(reversed(ids))[::-1]],
                         "the shard of an id may not depend on queue order")

    def test_the_governor_throttles_the_batch_on_the_reject_rate(self):
        """P9, and the reviewer is bound by it too: a batch that produced a 25% reject rate is followed
        by a smaller one, mechanically. Intent is not a control."""
        import subprocess
        with tempfile.TemporaryDirectory() as td:
            pol, q = os.path.join(td, "p.json"), os.path.join(td, "q.json")
            with open(pol, "w", encoding="utf-8") as fh:
                json.dump({"workers": 4, "batch_size": 4, "ceiling": 6, "floor": 2,
                           "next_batch_size": 4, "history": []}, fh)
            with open(q, "w", encoding="utf-8") as fh:
                json.dump({"candidates": [{"id": f"c{i}"} for i in range(8)]}, fh)
            tool = os.path.join(REPO, "pipeline/next_batch.py")

            def report(*extra):
                subprocess.run([sys.executable, tool, "--policy", pol, "--queue", q,
                                "--report", *extra], check=True, capture_output=True, text=True)

            report("--in-batch", "4", "--rejected", "1")
            got = json.load(open(pol, encoding="utf-8"))
            self.assertEqual(got["next_batch_size"], 2, "one reject in four is the 20% line")
            self.assertEqual(got["history"][-1]["rejected"], 1)
            report("--in-batch", "2", "--rejected", "0")
            self.assertEqual(json.load(open(pol, encoding="utf-8"))["next_batch_size"], 4,
                             "a clean batch restores to batch_size, not to the ceiling by default")

    def test_a_refused_capture_is_published_as_incomplete_not_thin(self):
        """M12 on the surface: the pool row must blame the read, not the project."""
        records = enrich_all(FIXTURE)
        refused = records[1]["id"]
        with tempfile.TemporaryDirectory() as td:
            shard_builder.build(records, td, "2026-09-18", {},
                               lint_rejects={refused: ["capture.sections.seven"]})
            with open(f"{td}/data/pool.json", encoding="utf-8") as fh:
                pool = json.load(fh)
        rows = {r["id"]: r for r in pool["records"]}
        self.assertIn("incomplete capture (lint: capture.sections.seven)",
                      rows[refused]["why_not_promoted"])
        self.assertNotIn("not_audited", rows[refused]["why_not_promoted"],
                         "the record was read; saying otherwise hides the reason")
        others = [r for i, r in rows.items() if i != refused]
        self.assertTrue(all("incomplete capture" not in " ".join(r["why_not_promoted"]) for r in others))


class TestAuditedLiteTier(unittest.TestCase):
    """ADR-P15: a record can be thin because it is contradicted or because there is less to check, and a
    tier that publishes the second kind must make readers *see* the difference. These pin the four guards,
    the caps, and the fact that the tier is on every surface that shows a verdict — a lite row that reads
    like a full one is the M15 failure in a new costume."""

    @staticmethod
    def _audit_rows():
        rows = {}
        with open(os.path.join(REPO, "pipeline/audit.jsonl"), encoding="utf-8") as fh:
            for line in fh:
                if line.strip():
                    r = json.loads(line)
                    rows[r["id"]] = r
        return rows

    def test_a_small_but_honest_record_publishes_as_lite(self):
        rows = self._audit_rows()
        lite = [r for r in rows.values() if r.get("tier") == "lite"]
        self.assertTrue(lite, "the second ladder must actually be used, or it is decoration")
        for r in lite:
            self.assertTrue(r["publishable"], r["id"] + " carries a tier but is not published")
            self.assertEqual(r["verdict"], T.AUDIT_LITE_VERDICT,
                             "a six-field row may not certify `strong` soundness")
            self.assertEqual(sorted(r["fields_absent"]),
                             sorted(set(T.AUDIT_MANDATORY_FIELDS) - set(T.AUDIT_LITE_FIELDS)),
                             "the row must name exactly what nobody wrote")
            self.assertNotIn("breakthrough", [r.get("worth")],
                             "breakthrough is refused at this tier, not softened")
            self.assertIn("build_is_real", str(r.get("tier_note")),
                          "the note must say which checks were never run")

    def test_a_refuted_record_cannot_be_lite_washed(self):
        cap = {"id": "fixture", "sections": {"what_it_does": "x"}}
        checks = {k: {"pass": 0.9, "status": "supported"} for k in T.AUDIT_CHECKS}
        ok, refuse, _absent = A.lite_admission(cap, checks, {f: {"value": "v"} for f in T.AUDIT_LITE_FIELDS},
                                               1, 0.64)
        self.assertFalse(ok, "a contradicted claim is the one thing lite must never publish")
        self.assertTrue(any("never washes a refutation" in x for x in refuse), refuse)

    def test_a_bare_feature_list_cannot_be_lite(self):
        checks = {k: {"pass": 0.9, "status": "supported"} for k in T.AUDIT_CHECKS}
        checks["limits_disclosed"] = {"pass": 0.0, "status": "unverifiable"}
        checks["test_or_eval_evidence"] = {"pass": 0.0, "status": "unverifiable"}
        ok, refuse, _ = A.lite_admission({"id": "f"}, checks,
                                        {f: {"value": "v"} for f in T.AUDIT_LITE_FIELDS}, 0, 0.64)
        self.assertFalse(ok, "a page that says nothing about behaviour or measurement is a brochure")
        self.assertTrue(any("how the thing behaves" in x for x in refuse), refuse)

    def test_no_artifact_resolves_means_no_lite_row(self):
        checks = {k: {"pass": 0.9, "status": "supported"} for k in T.AUDIT_CHECKS}
        checks["artifact_exists"] = {"pass": 0.0, "status": "unverifiable"}
        ok, refuse, _ = A.lite_admission({"id": "f"}, checks,
                                        {f: {"value": "v"} for f in T.AUDIT_LITE_FIELDS}, 0, 0.64)
        self.assertFalse(ok)
        self.assertTrue(any("something to look at" in x for x in refuse), refuse)

    def test_the_tier_is_visible_on_every_published_surface(self):
        import shard_builder as S
        with open(os.path.join(REPO, "web/public/catalog-packed.json"), encoding="utf-8") as fh:
            packed = json.load(fh)
        self.assertEqual(packed["row_format"], T.ROW_FORMAT)
        self.assertIn("tier_id", packed["row_format"], "a card that never loads a sheet must still know")
        idx = packed["row_format"].index("tier_id")
        tiers = {1: "lite", 0: "full"}
        rows_by_id = packed["row_format"].index("id")
        names = {str(r[rows_by_id]): tiers[int(r[idx])] for r in packed["rows"]}
        with open(os.path.join(REPO, "web/public/data/audits.json"), encoding="utf-8") as fh:
            index = json.load(fh)["records"]
        for rid, sheet in index.items():
            self.assertEqual(names[rid], sheet["tier"], rid + ": packed tier and index tier disagree")
        with open(os.path.join(REPO, "web/public/data/ideas.ndjson"), encoding="utf-8") as fh:
            for line in fh:
                r = json.loads(line)
                if r.get("audit"):
                    self.assertEqual(r["audit"]["tier"], index[r["id"]]["tier"],
                                     r["id"] + ": ndjson and index disagree on the tier")
        import csv as _csv
        with open(os.path.join(REPO, "web/public/data/ideas.csv"), newline="", encoding="utf-8") as fh:
            for row in _csv.DictReader(fh):
                want = index.get(row["id"], {}).get("tier", "") or ""
                self.assertEqual(row["audit_tier"], want, row["id"] + ": csv tier drifted")

    def test_the_rubric_publishes_both_ladders(self):
        with open(os.path.join(REPO, "web/public/data/audit-rubric.json"), encoding="utf-8") as fh:
            rub = json.load(fh)
        self.assertEqual(rub["tiers"]["full"]["fields"], list(T.AUDIT_MANDATORY_FIELDS))
        self.assertEqual(rub["tiers"]["lite"]["fields"], list(T.AUDIT_LITE_FIELDS))
        self.assertEqual(rub["tiers"]["lite"]["verdicts"], [T.AUDIT_LITE_VERDICT])
        self.assertEqual(len(rub["tiers"]["lite"]["requires"]), 4,
                         "an agent must be able to see what promotes a lite row")

    def test_the_census_counts_the_two_ladders_apart(self):
        with open(os.path.join(REPO, "web/public/catalog-stats.json"), encoding="utf-8") as fh:
            stats = json.load(fh)
        self.assertEqual(stats["published_full"] + stats["published_lite"], stats["total"],
                         "the tier split must account for every published row")
        for doc in ("README.md", "docs/AGENT_ACCESS.md"):
            with open(os.path.join(REPO, doc), encoding="utf-8") as fh:
                text = fh.read()
            self.assertIn("audited-lite", text, doc + " says `published` without naming the two ladders")
        self.assertGreater(stats["published_lite"], 0,
                           "if lite rows vanish the split is untested prose, not a real surface")


class TestGeneratedCensus(unittest.TestCase):
    """The docs quote counts, and the counting is done by a program.

    Hand-copied stats were wrong inside a batch of being written — three documents at once — so every
    count in that prose lives between sentinels and is emitted from the built surfaces. Batch 5 widened
    the rule, because one census block was not enough: a document that regenerates its headline while a
    paragraph further down still quotes "157 held-out records" and "8 of 165 audited" has only moved the
    lie. `docsync` now renders *named* regions, and a region name with no renderer — or a renderer whose
    output the file disagrees with — fails the build. These tests are that gate in unittest form;
    `pipeline/docsync.py --check` is the same claim on the committed tree.
    """

    @staticmethod
    def _src(rel):
        with open(os.path.join(REPO, rel), encoding="utf-8") as fh:
            return fh.read()

    def test_every_doc_carries_the_generated_census(self):
        import docsync
        b, e = docsync.begin("census"), docsync.end("census")
        for rel in docsync.TARGETS:
            src = self._src(rel)
            self.assertIn(b, src, f"{rel} lost its census sentinel")
            self.assertIn(e, src, f"{rel} lost its census end sentinel")
            self.assertLess(src.index(b), src.index(e), rel)
            self.assertNotIn("placeholder", src[src.index(b):src.index(e)],
                             f"{rel}: census block was never generated")

    def test_every_region_in_a_doc_is_generated_by_something(self):
        """The failure mode this pins is prose that starts quoting a number nobody regenerates."""
        import docsync
        known = set(docsync.REGIONS) | {"census"}
        for rel in docsync.TARGETS:
            src = self._src(rel)
            for name in re.findall(r"<!-- ([a-z-]+):begin -->", src):
                self.assertIn(name, known, f"{rel}: region `{name}` has no renderer")
                self.assertIn(docsync.end(name), src, f"{rel}: region `{name}` never closes")

    def test_the_regions_say_what_the_built_surfaces_say(self):
        import docsync
        with open(os.path.join(REPO, "web", "public", "catalog-stats.json"), encoding="utf-8") as fh:
            stats = json.load(fh)
        caps = docsync._captures()
        rendered = {"census": docsync.render_census(stats, caps)}
        for name, fn in docsync.REGIONS.items():
            rendered[name] = fn(stats, caps)
        for rel in docsync.TARGETS:
            src = self._src(rel)
            for name, body in rendered.items():
                beg, fin = docsync.begin(name), docsync.end(name)
                if beg not in src:
                    continue
                region = src[src.index(beg) + len(beg):src.index(fin)]
                self.assertEqual(" ".join(region.split()), " ".join(("\n".join(body)).split()),
                                 f"{rel}: region `{name}` disagrees with the surfaces it claims to quote")

    def test_the_census_says_what_the_stats_say(self):
        import docsync
        with open(os.path.join(REPO, "web", "public", "catalog-stats.json"), encoding="utf-8") as fh:
            stats = json.load(fh)
        with open(os.path.join(REPO, "pipeline", "corpus.jsonl"), encoding="utf-8") as fh:
            corpus = [json.loads(l) for l in fh]
        block = "\n".join(docsync.render_census(stats, docsync._captures()))
        self.assertIn(f"**{stats['audited_published']} of {stats['coverage']['published_total']}**", block)
        self.assertIn(f"**{stats['pool_records']}** sit in", block)
        self.assertIn(f"{stats['pool_audited_held']} captured, scored and held for cause", block)
        self.assertIn(f"{stats['pool_unaudited']} never captured at all", block)
        self.assertEqual(stats["audited_published"] + stats["pool_records"],
                        stats["coverage"]["published_total"],
                        "catalog + pool must still be the whole admitted corpus, or the census is a lie")
        caps = docsync._captures()
        self.assertEqual(len(caps), stats["deep_records"], "capture count in stats must match the files")
        self.assertTrue(all(c["id"] in {r["id"] for r in corpus} for c in caps),
                        "every capture must have a corpus row — see the capture-parity gate")
        self.assertEqual("placeholder" in block, False)


if __name__ == "__main__":
    unittest.main(verbosity=2)
