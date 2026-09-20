#!/usr/bin/env python3
"""ADR-P1 · the contract gate, as an admission boundary that also classifies the failure.

Every rule here is a subset of what the pipeline already enforces downstream, so a clean capture can
never be refused for a reason the engine does not actually care about. The point is *where* the check
happens: a violation used to be discovered by a reviewer reading the published sheet after the fact,
which is the slowest possible place to find a missing field (docs/PARALLELISM_PANEL.md §9, M5/M12).

Two classifications, deliberately kept apart:
  · `incomplete capture` — the worker's fault. The record is refused for this batch; the pool row says
    so, because "we did not read the page properly" must never be published as "this project is thin".
  · (not this tool) `thin` — the project's own verdict, produced by the audit, not by the lint.
A short section is legal: `what_next` being one line long says the page was quiet about the future, and
that is information, not a defect. An *absent* section is a defect, because we did not look.

  python3 pipeline/capture_lint.py                    # lint every capture, strict
  python3 pipeline/capture_lint.py --soft               # record rejects, exit 0 (used by `make build`)
  python3 pipeline/capture_lint.py --json               # machine-readable findings
  python3 pipeline/capture_lint.py --install-capture ID < capture.json    # write through the gate
  python3 pipeline/capture_lint.py --install-notes   ID < notes.json       # ditto, for the notes file
"""
import argparse
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import taxonomy_hacks as T  # noqa: E402  (AUDIT_WORTH, BANNED_VERDICT_WORDS, corpus paths)

CAPTURES = os.path.join(HERE, "raw", "deep_captures")
NOTES_DIR = os.path.join(HERE, "raw", "audit_notes")
NOTES_LEGACY = os.path.join(HERE, "raw", "audit_notes.json")
REJECTS = os.path.join(HERE, "raw", "lint_rejects")
PAGE_CACHE = os.path.join(HERE, "raw", "page_cache")
CORPUS = os.path.join(HERE, "corpus.jsonl")

# The keys a capture must carry to be readable as evidence. `limits_admitted` is the only optional one.
# The capture contract is versioned, because half of these rules describe a discipline the registry
# adopted after those records were written (a `gallery_images` key, per-number `verifiable`). Absent
# means v1: reported as legacy debt, never silently passed, and never allowed to grow. Everything
# admitted through --install-* from now on must be v2.
CAPTURE_SCHEMA = 2
REQUIRED_CAPTURE_KEYS = ("schema", "id", "name", "source_url", "software_id", "award", "likes", "built_with",
                        "links", "one_line", "numbers", "sections", "testing", "data_and_models",
                        "gallery_images", "captured_at")
OPTIONAL_CAPTURE_KEYS = ("limits_admitted", "page_words")
SEVEN_SECTIONS = ("inspiration", "what_it_does", "how_we_built_it", "challenges",
                  "accomplishments", "learned", "what_next")
REQUIRED_NOTES_KEYS = ("worth", "worth_note", "what_to_steal", "what_breaks_first",
                       "prior_art", "clone_cost")
OPTIONAL_NOTES_KEYS = ("hazard_note", "hazard_note_absent")
REPO_RE = re.compile(r"^(?:https?://(?:www\.)?github\.com/)?([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+?)(?:\.git)?/?$")
URL_RE = re.compile(r"^https?://\S+$")


class Findings:
    """One line per violation, with the fix in the same line (P1's requirement)."""

    def __init__(self, rid):
        self.id = rid
        self.rows = []
        self.skipped = []
        self.legacy = False

    def bad(self, rule, problem, fix):
        self.rows.append({"rule": rule, "problem": problem, "fix": fix})

    def skip(self, rule, why):
        self.skipped.append({"rule": rule, "why": why})

    @property
    def ok(self):
        return not self.rows


def _read_json(path, default=None):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return default


def load_notes_map():
    """Per-record notes merged over the legacy dict — the same rule the audit uses (ADR-P4)."""
    out = {}
    legacy = _read_json(NOTES_LEGACY, {})
    if isinstance(legacy, dict):
        out.update(legacy)
    if os.path.isdir(NOTES_DIR):
        for fn in sorted(os.listdir(NOTES_DIR)):
            if fn.endswith(".json"):
                blob = _read_json(os.path.join(NOTES_DIR, fn))
                if isinstance(blob, dict):
                    out[fn[:-5]] = blob
    return out


def lint_capture(cap, notes, corpus_row=None):
    """Every rule against one record. `notes=None` means no notes file was found.

    A v1 capture (no `schema` key — everything written before this gate existed) is checked only for
    the things that were always true of a capture: unknown keys, links, and the notes file. Its missing
    fields are the registry's history, not this batch's failure, so they are reported as legacy debt in
    the summary instead of refusing a record that is already published.
    """
    f = Findings(str(cap.get("id") or "?"))
    rid = f.id
    legacy = int(cap.get("schema") or 1) < CAPTURE_SCHEMA
    if legacy:
        f.legacy = True
    else:
        f.legacy = False

    # 1 · schema keys, both directions: an absent key is unread data, an unrecognised one is a rename
    keys = set(cap)
    missing = [k for k in REQUIRED_CAPTURE_KEYS if k not in keys]
    if missing and not legacy:
        f.bad("capture.keys", "missing key(s): " + ", ".join(missing),
              "add them (null is allowed and means 'the page does not say'; an absent key means "
              "nobody looked)")
    unknown = sorted(keys - set(REQUIRED_CAPTURE_KEYS) - set(OPTIONAL_CAPTURE_KEYS))
    if unknown:
        f.bad("capture.keys.unknown", "unexpected key(s): " + ", ".join(unknown),
              "a key nobody reads is a key that will silently stop being written — fold it into a "
              "section or add it to REQUIRED_CAPTURE_KEYS with a consumer")

    # `page_words` counts the words the team authored across the seven sections. It is optional because
    # most of the registry predates it, and it exists for one reason: the audited-lite ladder has to tell
    # "we could not examine the build" apart from "there was barely a page". Only the page's own length
    # answers that, since the length of a capture measures the auditor and not the record. The rule keeps
    # the number from becoming a vibe — it must be a real count — and nothing more.
    if "page_words" in cap:
        pw = cap.get("page_words")
        if isinstance(pw, bool) or not isinstance(pw, int) or pw < 0:
            f.bad("capture.page_words.shape",
                  "`page_words` must be a non-negative integer count of the words the page itself authors",
                  f"got {pw!r} — count the seven sections as submitted, not as summarised")

    # 2 · the seven authored sections exist; thin prose is a property of the page, not of the capture
    secs = cap.get("sections") or {}
    if not isinstance(secs, dict):
        f.bad("capture.sections.shape", "`sections` is not an object", "use the seven-key object")
        secs = {}
    for name in SEVEN_SECTIONS:
        val = str(secs.get(name) or "").strip()
        if name not in secs and not legacy:
            f.bad("capture.sections.seven", f"`{name}` key absent",
                  f"write `sections.{name}` (empty string if the page truly has nothing, key absent "
                  "means the read was incomplete)")
        elif not val:
            pass   # present-but-empty is the documented "the page says nothing here"
        elif len(val) < 20:
            f.bad("capture.sections.fragment", f"`{name}` is {len(val)} chars of fragment",
                  "either quote the page's sentence or write the empty string; a fragment reads as "
                  "a transcription slip")

    # 3 · links: a repo must be resolvable by repo_verify, or it should not be in this field
    links = cap.get("links") or {}
    if not isinstance(links, dict):
        f.bad("capture.links.shape", "`links` is not an object", 'use {"demo":…,"repo":…,"video":…}')
        links = {}
    repo = links.get("repo")
    if repo not in (None, "") and not REPO_RE.match(str(repo).strip()):
        f.bad("capture.links.repo-parseable", f"repo is not owner/repo: {repo!r}",
              "put the `owner/repo` (or a github URL) in this field, and put prose about the repo in a "
              "section — repo_verify can only resolve the first")
    for key in ("demo", "video"):
        val = links.get(key)
        if val not in (None, "") and not URL_RE.match(str(val).strip()):
            f.bad("capture.links.url-shaped", f"links.{key} is not an absolute URL: {val!r}",
                  "use the full URL the page links, or null")

    # 4 · numbers: a claim without a denominator is a marketing sentence we would be re-publishing
    nums = cap.get("numbers")
    if not isinstance(nums, list):
        f.bad("capture.numbers.shape", "`numbers` is not a list",
              "use a list of {claim,denominator,arithmetic,verifiable} objects; [] means the page has "
              "no figures")
        nums = []
    for i, item in enumerate(nums):
        if not isinstance(item, dict) or "claim" not in item:
            f.bad("capture.numbers.entry", f"numbers[{i}] is not an object with a `claim`",
                  "quote the page's figure verbatim in `claim`")
            continue
        arith = str(item.get("arithmetic") or "")
        has_denom = bool(str(item.get("denominator") or "").strip())
        untestable = arith[:3] in ("not", "str") or arith.lower().startswith("structural")
        if not has_denom and not untestable:
            f.bad("capture.numbers.denominators",
                  f"numbers[{i}] ({item['claim']!r}) has no denominator and no `not…`/`structural` "
                  "prefix in `arithmetic`",
                  "add the population the figure is a share of, or write why it cannot be checked; the "
                  "audit will otherwise read a bare number as an unexamined claim")
        if "verifiable" not in item and not legacy:
            f.bad("capture.numbers.verifiable", f"numbers[{i}] has no `verifiable` boolean",
                  "say whether a reader could re-derive it from what the page publishes")

    # 5 · one_line is our derivation, not the page's pitch
    one = " ".join(str(cap.get("one_line") or "").split())
    summary = " ".join(str((corpus_row or {}).get("summary") or "").split())
    if len(one.split()) < 8 and not legacy:
        f.bad("capture.one_line.substance", f"one_line is {len(one.split())} words",
              "write the sentence that says what the thing does and for whom; the listing already did")
    if summary and one and one.lower() in summary.lower():
        f.bad("capture.one_line.derived", "one_line is the page's own summary sentence",
              "rewrite it from the sections: the marketing line is already in `summary`, and copying it "
              "puts the pitch where the finding belongs")

    # 6 · register: verdict-shaped words must not leak into prose that reads like a judgement
    hay = " ".join([one] + [str(v) for v in secs.values()] + [str(cap.get("testing") or "")]).lower()
    hit = sorted({w for w in T.BANNED_VERDICT_WORDS if re.search(r"\b" + re.escape(w) + r"\b", hay)})
    if hit:
        f.bad("capture.register.banned-words", "banned verdict words in captured prose: " + ", ".join(hit),
              "describe the evidence instead; those words belong in the verdict the engine derives")

    # 7 · the notes file, shape then judgement-then-evidence
    if notes is None:
        f.bad("notes.present", "no `pipeline/raw/audit_notes/%s.json`" % rid,
              "write the editorial notes; without them the sheet publishes placeholders")
    else:
        nkeys = set(notes)
        nmis = [k for k in REQUIRED_NOTES_KEYS if k not in nkeys]
        if nmis:
            f.bad("notes.keys", "missing note key(s): " + ", ".join(nmis),
                  "every one of these is a field the sheet renders; add them or the record publishes "
                  "a placeholder")
        nun = sorted(nkeys - set(REQUIRED_NOTES_KEYS) - set(OPTIONAL_NOTES_KEYS))
        if nun:
            f.bad("notes.keys.unknown", "unexpected note key(s): " + ", ".join(nun),
                  "a note nobody reads is a note that will rot")
        if notes.get("worth") not in T.AUDIT_WORTH:
            f.bad("notes.worth-enum", f"worth={notes.get('worth')!r} is not one of "
                  + "/".join(T.AUDIT_WORTH), "pick a rung from AUDIT_WORTH and justify it in worth_note")
        pa = notes.get("prior_art")
        if not isinstance(pa, list) or not pa:
            f.bad("notes.prior-art", "`prior_art` must be a non-empty list",
                  "name at least one corpus record it resembles; an entry may instead carry a `url` the "
                  "session opened (A5/C5 resolves an assertion to something checkable). A bare "
                  "{corpus_id: null, relation: 'nothing in this corpus…'} is allowed and honest, but the "
                  "audit will carry it as a load-bearing unknown, so do not use it to avoid a comparison")
        else:
            for i, x in enumerate(pa):
                if not isinstance(x, dict) or "relation" not in x or "corpus_id" not in x:
                    f.bad("notes.prior-art", f"prior_art[{i}] needs both `corpus_id` and `relation`",
                          "relation is the sentence a reader acts on; corpus_id is what makes it checkable")
        cc = notes.get("clone_cost")
        if not isinstance(cc, dict) or not {"estimate", "why"} <= set(cc):
            f.bad("notes.clone-cost", "clone_cost needs `estimate` and `why`",
                  "an effort claim without its reasoning is a guess with a number on it")

    f._page_cache_rule = True
    return f


def lint_notes_for_hazard(rid, cap, notes, findings):
    """The Tower defect, made mechanical: when a hazard class attaches, the note must be ours.

    `hazard_for` falls back to a generic sentence when the notes entry omits `hazard_note`, and that
    fallback once published a claim about "no evidence of clinical validation" on a record where the
    trigger was the word *diagnosis* used as a metaphor. Either the stamp is wrong (fix the signal) or
    the note is missing (write it) — the lint cannot tell which, so it refuses the record until someone
    does.
    """
    try:
        import audit_projects as A
    except Exception:                                   # pragma: no cover - lint still useful standalone
        findings.skip("notes.hazard-note-when-stamped", "audit_projects not importable")
        return
    corpus = {}
    if os.path.exists(CORPUS):
        with open(CORPUS, encoding="utf-8") as fh:
            for line in fh:
                if line.strip():
                    row = json.loads(line)
                    corpus[row.get("id")] = row
    hz = A.hazard_for(corpus.get(rid) or {"id": rid, "domain": None, "summary": ""}, cap, notes or {})
    if hz and not str((notes or {}).get("hazard_note") or "").strip():
        findings.bad("notes.hazard-note-when-stamped",
                     f"a {hz['class']} hazard is stamped but the notes carry no `hazard_note`, so the "
                     "generic fallback would publish",
                     "either write the note that names the claim on the page, or show the stamp is a "
                     "false fire and fix the regex/capture — never let the default sentence through")
    elif not hz and str((notes or {}).get("hazard_note") or "").strip():
        findings.bad("notes.hazard-note-orphan", "notes carry `hazard_note` but no class attaches",
                     "delete it, or the record reads as if a stamp was removed by hand")


def check_page_cache(rid, cap, findings):
    """P6 groundwork: when a raw page cache exists, every section must be traceable into it."""
    for ext in (".md", ".txt"):
        path = os.path.join(PAGE_CACHE, rid + ext)
        if os.path.exists(path):
            with open(path, encoding="utf-8", errors="replace") as fh:
                page = fh.read().lower()
            for name, val in (cap.get("sections") or {}).items():
                words = [w for w in re.findall(r"[a-z]{7,}", str(val).lower())]
                absent = [w for w in words if w not in page]
                if len(absent) > max(3, 0.12 * max(1, len(words))):
                    findings.bad("page.traceable",
                                 f"sections.{name} uses {len(absent)} word(s) absent from the cached page",
                                 "quote the page or mark the sentence as inference in the section prose")
            return
    findings.skip("page.traceable", "no raw/page_cache/%s.md yet (ADR-P6)" % rid)


def lint_one(rid, findings_by_rid=None):
    cap = _read_json(os.path.join(CAPTURES, rid + ".json"))
    if cap is None:
        f = Findings(rid)
        f.bad("capture.exists", "no `pipeline/raw/deep_captures/%s.json`" % rid,
              "capture the page first; the queue lists ids, not evidence")
        return f
    notes = load_notes_map().get(rid)
    corpus_row = None
    if os.path.exists(CORPUS):
        with open(CORPUS, encoding="utf-8") as fh:
            for line in fh:
                if line.strip():
                    row = json.loads(line)
                    if row.get("id") == rid:
                        corpus_row = row
                        break
    f = lint_capture(cap, notes, corpus_row)
    lint_notes_for_hazard(rid, cap, notes, f)
    check_page_cache(rid, cap, f)
    return f


def all_ids():
    return sorted(x[:-5] for x in os.listdir(CAPTURES) if x.endswith(".json"))


def write_rejects(findings):
    os.makedirs(REJECTS, exist_ok=True)
    for f in findings:
        path = os.path.join(REJECTS, f.id + ".json")
        if f.ok:
            if os.path.exists(path):
                os.remove(path)
            continue
        with open(path, "w", encoding="utf-8") as fh:
            json.dump({"id": f.id, "rules": sorted({r["rule"] for r in f.rows}), "rows": f.rows},
                      fh, indent=2, sort_keys=True)
            fh.write("\n")


def validate_blob(kind, blob, target_id=None):
    """The install path: refuse a payload that would not survive the gate, before it hits the tree.

    Returns findings in the same shape as `Findings.rows` (rule/problem/fix dicts) — the first version
    returned a mixture of dicts and lists, which is exactly the kind of inconsistency a gate should have
    caught in itself.
    """
    probe = Findings(str((blob or {}).get("id") or "?"))
    if not isinstance(blob, dict):
        probe.bad(f"{kind}.shape", "stdin is not a JSON object", "pipe one object for one id")
        return probe.rows
    # The id a worker is installing *for* comes from the command line; the payload's own `id` is
    # optional for notes (the filename is the key, per ADR-P4) and must match for a capture. Reading the
    # id out of the blob instead refused the very first notes install, because notes never carried one.
    rid = str(target_id or blob.get("id") or "")
    if blob.get("id") and str(blob["id"]) != rid:
        probe.bad("capture.id", "payload id %r does not match the target %r" % (blob["id"], rid),
                  "one file per record means the filename is the truth")
    if kind == "capture":
        if int(blob.get("schema") or 1) < CAPTURE_SCHEMA:
            probe.bad("capture.schema", f"schema={blob.get('schema')!r}; new captures must be "
                      f"{CAPTURE_SCHEMA}", 'add "schema": %d — the version is what tells the gate you '
                      "agreed to the current contract rather than inherited an old one" % CAPTURE_SCHEMA)
        if rid and rid != blob.get("id"):
            probe.bad("capture.id", "`id` does not match", "the filename is derived from it")
        for k in REQUIRED_CAPTURE_KEYS:
            if k not in blob:
                probe.bad("capture.keys", "missing key: " + k, "add it (null allowed, absence not)")
        secs = blob.get("sections") if isinstance(blob.get("sections"), dict) else {}
        for name in SEVEN_SECTIONS:
            # Same rule `lint_capture` applies, deliberately: a key that is *absent* means the read was
            # incomplete, while a key present as the empty string is the documented answer to that
            # question ("the page says nothing about this"). The first version of this install check
            # refused both, which told a worker to go invent prose for a page that has none — and an
            # admission gate stricter than the gate it previews is worse than no gate, because the
            # repair it forces is a fabrication. This fired on the first real payload through the
            # installer (finova-j9av5f, a Showcase entry with no challenges or what's-next section).
            if name not in secs:
                probe.bad("capture.sections.seven", f"`{name}` absent",
                          "write the section, or the empty string if the page has nothing")
            elif 0 < len(str(secs[name]).strip()) < 20:
                probe.bad("capture.sections.fragment", f"`{name}` is a {len(str(secs[name]).strip())}-char "
                          "fragment", "quote the page's sentence or write the empty string")
        if not isinstance(blob.get("numbers"), list):
            probe.bad("capture.numbers.shape", "`numbers` is not a list",
                      "[] is the honest answer when the page carries no figures")
    elif kind == "notes" and not os.path.exists(os.path.join(CAPTURES, rid + ".json")):
        # The unit of work is a capture *and* its notes for one id (Okoro, §4). Installing them in the
        # other order is how a refused capture leaves an orphan judgement file behind, which then reads
        # as a record that was audited and held. Capture first; the notes are judgement *about* it.
        probe.bad("notes.order", f"no capture on disk for {rid!r} — notes are installed after the read",
                  "write the capture first (it is the evidence; the notes are the argument about it)")
    else:
        for k in REQUIRED_NOTES_KEYS:
            if k not in blob:
                probe.bad("notes.keys", "missing key: " + k, "the sheet renders it")
        if blob.get("worth") not in T.AUDIT_WORTH:
            probe.bad("notes.worth-enum", f"worth={blob.get('worth')!r}", "pick an AUDIT_WORTH rung")
        pa = blob.get("prior_art")
        if not isinstance(pa, list) or not pa:
            probe.bad("notes.prior-art", "`prior_art` must be a non-empty list",
                      "name the corpus record it resembles, or say there is none")
        cc = blob.get("clone_cost")
        if not isinstance(cc, dict) or not {"estimate", "why"} <= set(cc):
            probe.bad("notes.clone-cost", "clone_cost needs `estimate` and `why`",
                      "an effort claim without its reasoning is a guess with a number on it")
    return probe.rows


def main():
    ap = argparse.ArgumentParser(description="ADR-P1 capture contract gate")
    ap.add_argument("ids", nargs="*", help="ids to lint (default: every capture on disk)")
    ap.add_argument("--soft", action="store_true",
                    help="record rejects but exit 0 — `make build` uses this so one unfinished record "
                         "cannot brick the catalog for the other eleven")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--quiet", action="store_true")
    ap.add_argument("--install-capture", metavar="ID",
                    help="read a capture on stdin, validate it, write raw/deep_captures/ID.json")
    ap.add_argument("--install-notes", metavar="ID",
                    help="read notes on stdin, validate them, write raw/audit_notes/ID.json")
    args = ap.parse_args()

    for flag, kind, dest in ((args.install_capture, "capture", CAPTURES),
                             (args.install_notes, "notes", NOTES_DIR)):
        if flag:
            blob = json.load(sys.stdin)
            problems = validate_blob(kind, blob, flag)
            if problems:
                for row in problems:
                    print(f"{flag}\t{row['rule']}\t{row['problem']}\t→ {row['fix']}")
                print(f"❌ {kind} for {flag} refused: it would not survive the gate; nothing written")
                return 1
            os.makedirs(dest, exist_ok=True)
            out = os.path.join(dest, flag + ".json")
            with open(out, "w", encoding="utf-8") as fh:
                json.dump(blob, fh, indent=2, sort_keys=True)
                fh.write("\n")
            print(f"✅ wrote {os.path.relpath(out, os.path.join(HERE, '..'))}")
            if kind == "capture":
                post = lint_one(flag)
                if not post.ok:
                    print(f"⚠  written, but the full lint still flags {len(post.rows)} rule(s): "
                          + ", ".join(sorted({r['rule'] for r in post.rows})))
            return 0

    ids = args.ids or all_ids()
    findings = [lint_one(rid) for rid in ids]
    write_rejects(findings)
    bad = [f for f in findings if not f.ok]
    if args.json:
        print(json.dumps({"checked": len(findings), "rejected": len(bad),
                          "records": [{"id": f.id, "rows": f.rows, "skipped": f.skipped}
                                      for f in findings]}, indent=2, sort_keys=True))
    else:
        for f in bad:
            for r in f.rows:
                print(f"✗ {f.id}\t{r['rule']}\t{r['problem']}\t→ {r['fix']}")
        if not args.quiet:
            legacy = [f for f in findings if f.legacy and f.ok]
            print(f"🧹 capture_lint: {len(ids) - len(bad)}/{len(ids)} captures pass; "
                  f"{len(bad)} rejected as incomplete (recorded in raw/lint_rejects/); "
                  f"{len(legacy)} grandfathered at schema v1 "
                  f"({', '.join(sorted(f.id for f in legacy)) or 'none'}) — retire them by re-capturing, "
                  "and the count must never grow")
    return 1 if (bad and not args.soft) else 0


if __name__ == "__main__":
    sys.exit(main())
