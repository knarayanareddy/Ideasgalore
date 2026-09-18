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
import subprocess
import sys
import tempfile
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "pipeline"))
sys.path.insert(0, os.path.join(REPO, "mcp"))

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
        cls.stats = shard_builder.build(enrich_all(FIXTURE), cls.tmp, "2026-09-18")

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
            stats = shard_builder.build(broken, td, "2026-09-18")
            problems = shard_builder.gate_checks(broken, stats, td)
        self.assertTrue(any("required field" in p for p in problems))

    def test_deterministic_rebuild(self):
        with tempfile.TemporaryDirectory() as td:
            shard_builder.build(enrich_all(FIXTURE), td, "2026-09-18")
            for name in ("catalog-packed.json", "data/ideas.csv", "data/moves.json"):
                a = open(f"{self.tmp}/{name}", "rb").read()
                b = open(f"{td}/{name}", "rb").read()
                self.assertEqual(a, b, f"{name} must be byte-stable across builds")


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
        self.assertGreater(len(i.rows), 50)
        for r in i.rows[:20]:
            self.assertTrue(r["url"].startswith("https://devpost.com/software/"))
            self.assertIsInstance(r["coolness"], float)
            self.assertIsInstance(r["moves"], list)
            self.assertIsNotNone(r["event"], "event title must resolve for every row")

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


if __name__ == "__main__":
    unittest.main(verbosity=2)
