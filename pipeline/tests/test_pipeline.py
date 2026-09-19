"""
Ideas Galore — pipeline tests
=============================
The reference repo shipped no tests; ADR-10 requires that a build can *fail* on
drift, and the cheapest way to keep a heuristic pipeline honest is to pin its
behaviour. Run:  python3 -m unittest discover -s pipeline/tests -v
       or:      python3 pipeline/tests/test_pipeline.py
"""

from __future__ import annotations

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


if __name__ == "__main__":
    unittest.main(verbosity=2)
