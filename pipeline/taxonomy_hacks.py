"""
Ideas Galore — Inspiration Taxonomy, Move Detection & Coolness Ranking
=======================================================================
Implements ADR-4 (`moves` as the first-class axis), ADR-5 (quality gate), and
ADR-6 (explainable, versioned ranking) from docs/EXPERT_PANEL.md.

Unlike the reference repo (toolscour), whose axes answer "will this library run
on my hardware", the axes here answer "what can I steal from this project":

    domain      -> which shelf it sits on            (10 sectors)
    subsystem   -> finer shelf label                 (per domain)
    moves[]     -> transferable design tricks        (18-term vocabulary)
    stack[]     -> technologies claimed by authors   (observed when deep)
    specificity -> did they describe a mechanism or  (derived)
                  just a vibe
    coolness    -> additive, clamped, published-     (derived, versioned)
                  weights ranking

Provenance discipline (ADR-9): every field is tagged `observed` (came from
Devpost), `derived` (computed here), or `editorial` (hand-written blurb).

Zero third-party dependencies (Berg's reproducibility rule): stdlib only.
"""

from __future__ import annotations

import math
import re
from typing import Any, Dict, List, Optional, Tuple

SCORING_VERSION = 1
TAXONOMY_VERSION = 1

# ---------------------------------------------------------------------------
# 1 · THE 10 IDEA SECTORS  (navigation axis — "which shelf")
# ---------------------------------------------------------------------------
DOMAINS: Dict[str, Dict[str, Any]] = {
    "Agentic Autonomy & Orchestration": {
        "signature": ['agent', 'autonomous', 'orchestrat', 'crew of', 'unattended', 'watch over', 'guardrail'],
        "hue": "#0b7285",
        "blurb": "Projects where software acts on your behalf: crews, watchers, "
                 "gates, and the machinery that keeps autonomous behaviour governable.",
        "subsystems": {
            "Multi-Agent Crews": ["crew", "fleet", "swarm", "orchestrat", "multi-agent", "nine agents"],
            "Long-Horizon Autonomy": ["unattended", "weeks", "sleeps", "scheduled", "watch", "background"],
            "Agent Guardrails & Gating": ["guardrail", "policy", "approval", "boundary", "deterministic", "hitl"],
            "Tool & Integration Fabric": ["mcp", "tool call", "connector", "integration", "api layer", "webhook"],
        },
    },
    "Developer Tooling & Code Intelligence": {
        "signature": ['repo', 'codebase', 'pull request', 'git commit', 'merge conflict', 'ide', 'terminal', 'stack trace', 'incident', 'sentry', 'vulnerabilit', 'patch'],
        "hue": "#3b5bdb",
        "blurb": "Tools that change how software gets written, shipped, diagnosed, "
                 "or repaired — including agents that edit real repositories.",
        "subsystems": {
            "Code Repair & Patching": ["patch", "vulnerabilit", "fix", "refactor", "debug", "diagnos"],
            "Incident & Reliability Ops": ["incident", "outage", "slo", "p95", "observab", "grafana", "telemetry"],
            "IDE & Terminal Assistants": ["ide", "vscode", "cli", "terminal", "editor", "plugin"],
            "Build, CI & Release Plumbing": ["ci", "pipeline", "deploy", "build", "release", "docker", "runtime"],
        },
    },
    "Health, Care & Human Performance": {
        "signature": ['patient', 'clinician', 'clinical', 'therap', 'concussion', 'medication', 'diagnos', 'recovery', 'nurse', 'lesion', 'drug', 'rehab'],
        "hue": "#c2255c",
        "blurb": "Clinical, therapeutic, and bodily-self-tracking projects — where "
                 "the cost of a wrong answer is paid by a human, not a server.",
        "subsystems": {
            "Screening & Diagnostics": ["screen", "diagnos", "lesion", "concussion", "triage",
                                        "drug", "molecular", "protein", "biomarker", "clinical",
                                        "oncology", "symptom", "biological age", "longevity",
                                        "wearable", "hrv", "blood panel", "biometric"],
            "Recovery & Rehabilitation": ["recovery", "rehab", "physio", "acl", "exercise", "workout"],
            "Mental Health & Wellbeing": ["mental", "anxiet", "grief", "wellbeing", "mood", "therapy"],
            "Care Navigation & Records": ["records", "bill", "claim", "medication", "patient", "clinician"],
        },
    },
    "Climate, Energy & the Physical World": {
        "signature": ['energy', 'carbon', 'grid', 'charging', 'farm', 'harvest', 'soil', 'flood', 'wildfire', 'emission', 'sensor', 'drone'],
        "hue": "#2b8a3e",
        "blurb": "Sensing and acting on matter: grids, farms, fleets, sensors, "
                 "robots, and anything with a physical consequence.",
        "subsystems": {
            "Energy & Mobility": ["\\bev\\b", "charg", "grid", "energy", "battery", "fuel", "carbon"],
            "Agriculture & Environment": ["farm", "crop", "soil", "water", "tree", "weather", "flood"],
            "Sensing, Vision & Robotics": ["camera", "vision", "sensor", "drone", "robot", "lidar"],
            "Logistics & Field Operations": ["route", "dispatch", "fleet", "warehouse", "supply", "inventory"],
        },
    },
    "Public Trust, Safety & Compliance": {
        "signature": ['audit', 'provenance', 'forensic', 'deepfake', 'watermark', 'tamper', 'compliance', 'moderation', 'dispute', 'evidence', 'verdict', 'questionnaire'],
        "hue": "#495057",
        "blurb": "Verification, provenance, moderation, forensics, and the paperwork "
                 "of modern institutions rebuilt as machine-readable evidence.",
        "subsystems": {
            "Provenance & Anti-Deception": ["deepfake", "forensic", "verify", "authentic", "watermark", "tamper"],
            "Regulatory & Audit Machinery": ["compliance", "audit trail", "audit-ready",
                                       "audit finding", "auditor", "regulat",
                                       "questionnaire", "sign-off"],
            "Safety & Emergency Response": ["emergency", "responder", "accident", "safety", "alert"],
            "Civics & Discourse": ["civic", "vote", "public", "discourse", "policy", "government"],
        },
    },
    "Money, Commerce & Marketplaces": {
        "signature": ['payment', 'checkout', 'invoice', 'marketplace', 'seller', 'buyer', 'pricing', 'refund', 'transaction', 'revenue', 'smb'],
        "hue": "#b2710d",
        "blurb": "Transactions, matching, pricing, and the boring plumbing that "
                 "makes an exchange actually settle.",
        "subsystems": {
            "Payments & Claims": ["payment", "invoice", "billing", "payout", "refund", "dispute"],
            "Marketplace & Matching": ["marketplace", "matchmaking", "buyer", "seller", "listing", "p2p"],
            "Retail & Conversion": ["cart", "checkout", "shop", "product", "try-on", "conversion"],
            "Fintech & Personal Finance": ["budget", "saving", "invest", "credit", "finance", "wallet"],
        },
    },
    "Creative Media, Story & Play": {
        "signature": ['screenplay', 'storyboard', 'footage', 'film', 'video generation', 'music', 'game', 'narrative', 'voice cloning', 'text-to-speech', 'tts', 'avatar', 'render'],
        "hue": "#e64980",
        "blurb": "Film, games, music, writing and interactive narrative — including "
                 "the production machinery behind generated media.",
        "subsystems": {
            "Generative Video & Audio": ["video", "film", "footage", "music", "voice", "audio", "tts"],
            "Production & Direction": ["screenplay", "storyboard", "schedule", "cast", "crew", "shot"],
            "Games & Interactive Fiction": ["game", "play", "quest", "narrative", "player", "world"],
            "Design & Visual Tools": ["design", "canvas", "layout", "asset", "3d", "render"],
        },
    },
    "Learning & Knowledge Systems": {
        "signature": ['learn', 'study', 'tutor', 'course', 'quiz', 'wiki', 'document', 'ocr', 'transcri', 'retrieval', 'graphrag', 'notes'],
        "hue": "#087f5b",
        "blurb": "Teaching, studying, tutoring, and the organization of what a group "
                 "knows — from personal notes to institutional wikis.",
        "subsystems": {
            "Tutors & Adaptive Learning": ["tutor", "learn", "study", "quiz", "roadmap", "adaptive"],
            "Documents & Extraction": ["pdf", "document", "ocr", "extract", "table", "transcribe"],
            "Search & Retrieval": ["search", "retrieval", "rag", "index", "embed", "graphrag"],
            "Knowledge Curation": ["wiki", "note", "archive", "catalog", "memory", "curat"],
        },
    },
    "Accessibility & Assistive Tech": {
        "signature": ['blind', 'visually impaired', 'deaf', 'caption', 'sign language', 'dyslexia', 'screen reader', 'accessib', 'elderly', 'low-literacy', 'translate'],
        "hue": "#5c940d",
        "blurb": "Projects that widen who can use software: vision, hearing, speech, "
                 "literacy, motor access, and language barriers.",
        "subsystems": {
            "Vision & Hearing Aids": ["blind", "visually impaired", "deaf", "caption", "sign language", "audio cue"],
            "Speech & Literacy Support": ["speech", "dyslexia", "literacy", "read aloud", "simple language"],
            "Motor & Cognitive Access": ["switch access", "eye track", "motor", "cognitive", "aadld"],
            "Language & Translation": ["translat", "multilingual", "interpret", "locale", "dub"],
        },
    },
    "Data, Retrieval & Memory Infrastructure": {
        "signature": ['memory', 'vector', 'index', 'ledger', 'database', 'storage', 'state', 'sync', 'schema', 'cache', 'clickhouse', 'sqlite'],
        "hue": "#7f5539",
        "blurb": "The substrate layer: state that survives a session, storage with "
                 "opinions, and the ledgers everything else argues from.",
        "subsystems": {
            "Persistent Memory": ["memory", "state", "session", "context", "remember", "vector"],
            "Storage & Ledgers": ["ledger", "database", "store", "sql", "cache", "blob"],
            "Pipelines & Sync": ["sync", "etl", "ingest", "stream", "queue", "replicat"],
            "Edge & Local-First Runtime": ["local-first", "offline", "sqlite", "edge", "browser storage", "on-device"],
        },
    },
}

DOMAIN_ORDER = list(DOMAINS.keys())

# The 11th label is not a sector: it is an honest admission that the text was
# too thin to shelve. Shipped as data so no client hardcodes the fallback.
UNSHELVED = {"name": "Emerging & Cross-Domain", "hue": "#868e96",
             "blurb": "Submissions whose own description is too thin to place. "
                      "Browse them; do not trust the score."}

# ---------------------------------------------------------------------------
# AUDIT LAYER (docs/AUDIT_PANEL.md, ADR-A1..A15). These tables are the single
# source of truth for the verdict vocabulary: shard_builder encodes them into
# Tier 1, build_agent_api emits them as data/audit-rubric.json, and a test
# fails if the published vocabulary drifts from them.
# ---------------------------------------------------------------------------

AUDIT_VERSION = 1

# A2 — the only words this project uses about a stranger's work.
AUDIT_STATUSES = [
    "confirmed",        # we observed the artifact ourselves (repo/page/API response)
    "supported",        # consistent with what we observed, not directly observed
    "partial",          # true for part of the claim; the rest is unresolvable
    "unverifiable",     # no public evidence either way (a finding, not a blank)
    "contradicted",     # we observed something incompatible, with citation + date
    "duplicate",        # same submission re-entered under another id
]

# A1/A3 — verdict is derived from the evidence ledger, never typed.
AUDIT_VERDICTS = {
    "strong": "All load-bearing claims check out against artifacts; detail is sufficient to build from.",
    "sound-with-caveats": "Core mechanism verified; named gaps remain, listed as unknowns.",
    "thin": "Not enough public evidence to certify either way — stays in the pool, never in the catalog.",
    "unsound": "Load-bearing claim contradicted by evidence, or no artifact at all behind the pitch.",
    "duplicate": "Merged into an equivalent record (same submission or same-team resubmission).",
}
AUDIT_PUBLISH_VERDICTS = ["strong", "sound-with-caveats"]   # A1: the catalog's whole admission rule

# A4 — orthogonal to soundness and never averaged with it (dissent D3).
AUDIT_WORTH = {
    "breakthrough": "Reframes a category; the mechanism outlives the project.",
    "strong": "Genuine wedge, clearly better than the obvious alternative.",
    "niche": "Correct and useful for a specific, smaller audience.",
    "tired": "Competently built; the world already has five of these.",
}

# A3 — six mechanical checks. Weights published; `pass` values are 0 / 0.5 / 1.
AUDIT_CHECKS = {
    "artifact_exists":       {"w": 0.22, "ask": "Is there an artifact at all — a repo, a deployed app, or a video of it running?", "settles_with": "a repository, deployment or store listing we can resolve"},
    "stack_consistency":     {"w": 0.18, "ask": "Does the repo's language/file mix match the stack they described?", "settles_with": "a repository to compare the declared stack against"},
    "build_is_real":         {"w": 0.18, "ask": "Is the code a real build (source tree, setup steps, non-trivial size) rather than a stub or zip?", "settles_with": "a readable source tree (a repo link, then `python3 pipeline/repo_verify.py`)"},
    "numbers_add_up":        {"w": 0.16, "ask": "Do their metrics have a denominator, and is the arithmetic internally consistent?", "settles_with": "a denominator and baseline for the headline figure, or the raw log behind it"},
    "limits_disclosed":      {"w": 0.12, "ask": "Did they state what does not work, or where it fails?", "settles_with": "a statement of what the system itself cannot do (accuracy, coverage, privacy, failure modes)"},
    "test_or_eval_evidence": {"w": 0.14, "ask": "Any test suite, eval harness, or measured benchmark we can see?", "settles_with": "a published eval table, harness or CI run link with a case count"},
}
AUDIT_HARD_FAIL = {"artifact_exists": "thin"}   # caps the verdict, per A3
AUDIT_CONTRADICTED_CAP = 2                      # >=2 contradicted load-bearing claims => unsound

# A6 — the "full picture" contract. A field we cannot fill produces an unknown, not a blank.
AUDIT_MANDATORY_FIELDS = [
    "what_it_is", "what_it_does", "how_it_works", "built_with_verified", "data_and_models",
    "how_they_tested", "limits_they_disclosed", "numbers_with_arithmetic", "what_to_steal",
    "what_breaks_first", "clone_cost", "prior_art",
]
AUDIT_LOAD_BEARING = ["what_it_does", "how_it_works", "numbers_with_arithmetic"]
AUDIT_MAX_LOAD_BEARING_UNKNOWNS = 2   # more than this => verdict thin (A6)

# A10 — tone policy, enforced by test on every published string.
BANNED_VERDICT_WORDS = [
    "fake", "vaporware", "scam", "slop", "lying", "lied", "misrepresent", "misrepresented",
    "dishonest", "fraud", "plagiar", "hallucinating team", "not real",
]

# A13 — regulated-outcome hazards, derived from domain + claim language, editable in notes.
HAZARD_DOMAINS = {
    "Health, Care & Human Performance": "clinical",
    "Accessibility & Assistive Tech": "assistive-safety",
    "Public Trust, Safety & Compliance": "compliance-signoff",
}
# What counts as the team disclaiming a regulated outcome, in their own words. The pattern is
# phrasal on purpose: a page writing "positioned as recovery support, not a diagnostic
# replacement" HAS disclaimed, and an auditor that misses it ships a false statement about
# somebody else's caution ("no team disclaimer found").
HAZARD_DISCLAIM_RE = (
    r"\b(not a medical[^.]{0,40}|not for (medical )?diagnos\w*|no diagnos\w*|does not diagnos\w*|"
    r"not.{0,25}diagnostic (replacement|tool|device|system)|not (a )?clinical[^.]{0,30}|"
    r"no clinical[^.]{0,30}|demo only|proof of concept|prototype only|still a prototype|"
    r"educational purposes|not a substitute for|informational only|wellness[^.]{0,20}(tool|support)|"
    r"not intended (for|to be) (medical|use in))"
)
HAZARD_CLAIM_RE = (
    r"\b(diagnos\w*|screen\w*|triage|medicat\w*|dosage|prescri\w*|clear\w* to (return|play)|"
    r"regulat\w*|approval|sign-?off|compliance|detect\w* (concussion|cancer|tumor|fraud)|"
    r"autis\w*|concussion|suicid\w*)\b"
)

# A5 — similarity thresholds, pinned by fixtures (A15).
DUP_TEXT_OVERLAP = 0.75      # same-team resubmission
DUP_MECHANISM_OVERLAP = 0.60 # cross-team parallel invention (kept + cross-linked)


def clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


def audit_rubric() -> dict:
    """Machine-readable rubric, generated from the same tables the code uses, so a
    downstream agent can recompute a verdict without reading prose (ADR-A2/A8)."""
    return {
        "audit_version": AUDIT_VERSION,
        "statuses": AUDIT_STATUSES,
        "verdicts": AUDIT_VERDICTS,
        "published_verdicts": AUDIT_PUBLISH_VERDICTS,
        "worth": AUDIT_WORTH,
        "checks": {k: {kk: vv for kk, vv in v.items()} for k, v in AUDIT_CHECKS.items()},
        "hard_fail_caps": AUDIT_HARD_FAIL,
        "contradicted_cap": AUDIT_CONTRADICTED_CAP,
        "mandatory_fields": AUDIT_MANDATORY_FIELDS,
        "load_bearing_fields": AUDIT_LOAD_BEARING,
        "max_load_bearing_unknowns": AUDIT_MAX_LOAD_BEARING_UNKNOWNS,
        "banned_words_in_verdict_text": BANNED_VERDICT_WORDS,
        "similarity": {
            "duplicate_text_overlap": DUP_TEXT_OVERLAP,
            "parallel_mechanism_overlap": DUP_MECHANISM_OVERLAP,
        },
        "policy": [
            "soundness and worth are never combined into one score",
            "a verdict is a function of the evidence ledger, never typed by hand",
            "unverifiable means no public evidence either way; it is not an accusation",
            "records that cannot be supported stay in the pool, they are not deleted",
        ],
    }

HUES_LOCKED = (
    "Field Museum spectrum v1: brand vermilion (#c9421a) owns CHROME only; the 10 "
    "sector hues + museum grey are DATA ONLY (dots, chips, atlas nodes). No hue in "
    "the 250-290 deg violet band, no hue within 12 deg of the brand, no gradient text."
)

# ---------------------------------------------------------------------------
# 2 · THE MOVE VOCABULARY  (the inspiration axis — "what can I steal")
# ---------------------------------------------------------------------------
# Each move: detectors (regex over name+summary+authored text), a definition
# written for a builder deciding what to build, and a `steal_this` imperative.
MOVES: Dict[str, Dict[str, Any]] = {
    "evidence-graph": {
        "definition": "Every claim the system makes points at the artifact that justifies it, and the graph is queryable after the fact.",
        "steal_this": "Store the citation as a first-class row, not a footnote. The moment evidence is structured, 'explain yourself' becomes a SELECT.",
        "pat": r"cites? (every|each|the)|source-cited|evidence graph|audit trail|traceab|provenance|tamper|attest|quote[d]? from",
    },
    "price-before-generate": {
        "definition": "The true cost and success odds of an expensive generation step are quoted before the user commits, so spend is a choice.",
        "steal_this": "Model your most expensive operation as a priced quote with an expected-retry figure. Users forgive slowness, not surprise bills.",
        "pat": r"quote you the cost|cost ladder|prices? your|what .{0,20}will cost|estimat\w* (the )?cost|before spending a cent|costs? \$",
    },
    "human-holds-the-last-button": {
        "definition": "Autonomy is bounded by an irreversible-action gate that only a named person can release.",
        "steal_this": "Decide which single action is expensive enough to require a human, and make that gate a schema state transition rather than a prompt request.",
        "pat": r"human (?:in the loop|approval|-approved|approves|signs|releases|judgment|review)|escalat|asks? a human|final authority|approve[sd]? by|requires? a human|sign-?off|hold[sd]? for a person",
    },
    "deterministic-guardrail": {
        "definition": "Hard requirements are enforced by the runtime, not by asking a model politely.",
        "steal_this": "Anything the architecture can enforce, the architecture enforces. Probabilistic components get proposals; deterministic components get verdicts.",
        "pat": r"deterministic|runtime boundary|cannot|never hands|enforces?|constraint|guard|prevent[sd]? .*from|whitelist|allowlist",
    },
    "make-the-invisible-measurable": {
        "definition": "A felt-but-unmeasured phenomenon (jank, grief, bias, fatigue) is converted into a number with a before/after delta.",
        "steal_this": "Find the metric practitioners already eyeball, instrument it, and ship the delta. A number turns a vibe into a product.",
        "pat": r"\d+(\.\d+)?\s?(%|ms|mb|kb|x )|p95|auc|reduc\w+ .{0,14}%|from \d+ .{0,6}(to|→)|speedup|score",
    },
    "offline-first-fallback": {
        "definition": "The feature works with no network; cloud is an upgrade, not a dependency.",
        "steal_this": "Put the model on the device and make connectivity a quality setting. It reads as a privacy feature and buys reliability for free.",
        "pat": r"offline|on-device|local[- ]first|without internet|no server|edge|browser-only|runs locally",
    },
    "long-horizon-watcher": {
        "definition": "The agent persists across days, sleeping until the world changes, instead of answering in one session.",
        "steal_this": "Replace chat turns with a scheduled process that wakes on a condition. Patience is a feature nobody else ships.",
        "pat": r"sleeps for|wakes (itself|when)|unattended|for weeks|over days|monitor|poll|scheduled run|keeps watch",
    },
    "verification-first": {
        "definition": "Nothing is emitted until it has been checked against an independent source; the check, not the generation, is the product.",
        "steal_this": "Invert the pipeline: generate last, verify first. Ship the checker as the artifact and the content as its output.",
        "pat": r"verification[- ]first|re-?checks?|cross-check|holds accuracy|detects? .{0,20}error|validat|compares? .{0,20}against|catch(?:es|ing) .{0,20}(bad|mistake|broken)",
    },
    "wrap-the-legacy-surface": {
        "definition": "Instead of migrating users, the new capability is embedded into the surface they already live in.",
        "steal_this": "Ship as a plugin/widget/block inside the incumbent UI. Adoption is one checkbox, not a migration project.",
        "pat": r"plugin|extension|widget|chrome (?:ext|feature)|vscode|wordpress|embedded in|no redirect|drop-in|add-on",
    },
    "crew-of-specialists": {
        "definition": "A job normally done by one generalist is decomposed into named specialist roles that check each other.",
        "steal_this": "Name the roles, give each a single responsibility and an output contract, and let the handoffs be where quality is enforced.",
        "pat": r"\b(?:two|three|four|five|six|seven|eight|nine|ten|twelve|\d+)[- ]agent|crew|fleet of agents|swarm|orchestrat|role[s]? (?:of|per)|specialist",
    },
    "artifacts-not-forms": {
        "definition": "Structured intake is replaced by capturing a raw artifact (photo, recording, log) and deriving the form from it.",
        "steal_this": "Ask for the thing the user already has, then do the parsing. Every field you don't ask for is a user who doesn't churn.",
        "pat": r"upload .{0,24}(evidence|photo|image|video|file), not|not forms|scan any|drop a file|capture|photo of|from a (?:photo|video|screenshot)",
    },
    "constraint-is-the-feature": {
        "definition": "A limitation (no budget, no GPU, no internet, no data rights) is designed into the value proposition rather than apologized for.",
        "steal_this": "Take the constraint you were going to write a workaround for, and make it the headline. Broken-and-proud beats blocked-and-polished.",
        "pat": r"we had \$\d+|broke|cheap(?:er)? than|without a |zero[- ]tax|no budget|100% offline|free, |no ai expertise|without needing",
    },
    "data-flywheel": {
        "definition": "Every user interaction writes a labeled row that measurably improves the next one, and the improvement is surfaced to the user.",
        "steal_this": "Log the verdict (keep/again, accept/reject) next to the input, and tell users their own history now drives the estimate.",
        "pat": r"learns from every|feedback loop|your own numbers|sample size|each take|improves? with use|history (drives|informs)|reward model",
    },
    "model-cost-routing": {
        "definition": "Work is assigned to models by shape and price of the task, with the expensive tier reserved for foundation decisions.",
        "steal_this": "Classify each step as judgement vs. format vs. volume, then route. Save the frontier model for the one call everything downstream depends on.",
        "pat": r"(pro|flash|lite|mini|small|large) (model|takes)|assign by|routing|cheaper model|distill|per-tier|vertex",
    },
    "single-input-ux": {
        "definition": "One affordance (a file drop, a button, a yes/no) replaces the prompt box; the system asks with candidates, not blank fields.",
        "steal_this": "Ban the text box. When you need information, render 2-4 options. The product stops demanding literacy in your tool's language.",
        "pat": r"no prompts required|press buttons|zero-decision|one[- ]click|pick from|candidate[s]? and lets you choose|no text box|automagically",
    },
    "privacy-as-architecture": {
        "definition": "Data ownership is enforced by where bytes live, and the user can verify the claim.",
        "steal_this": "Move the sensitive step to the user's machine, then prove it with an auditable claim (no egress, local model hash, exportable data).",
        "pat": r"patient-owned|consent|your data|privacy|nothing leaves|data ownership|gdpr|self-host|user-owned|encrypted",
    },
    "institutional-grade-reliability": {
        "definition": "A hackathon surface wearing enterprise armor: immutable logs, versioned rules, replayable state, or crypto verification.",
        "steal_this": "Adopt one boring enterprise discipline (append-only audit, signed config, replay on boot) and let it be the reason a buyer trusts you.",
        "pat": r"crypto-?verifiab|immutable|versioned|replayable|byte-identical|cryptographic|enterprise-grade|production-grade|soc ?2|iso ?27|can't be altered",
    },
    "narrow-domain-deep-model": {
        "definition": "A tiny model or rules engine tuned to one vertical beats a general model prompted at it.",
        "steal_this": "Pick the narrowest slice you can own, then fine-tune or rule-code it until it is unarguably better on that slice's eval.",
        "pat": r"fine-?tun|domain[- ]specific|vertical|specialized|7 diagnostic conditions|trained on|our own eval|grad-cam|kalman|yolo",
    },
}

MOVE_ORDER = list(MOVES.keys())

# ---------------------------------------------------------------------------
# 3 · TECHNOLOGY LEXICON (detected from authored text + listing tags)
# ---------------------------------------------------------------------------
STACK_LEXICON: Dict[str, str] = {
    "react": "react", "next.js": "next-?js|nextjs", "vue": "\\bvue\\b", "svelte": "\\bsvelte\\b",
    "typescript": "typescript|\\bts\\b", "python": "python", "fastapi": "fastapi", "flask": "flask",
    "node.js": "node\\.?js|express", "go": "\\bgolang\\b|\\bgo\\b", "rust": "\\brust\\b",
    "swift": "\\bswift\\b|swiftui", "kotlin": "kotlin|android", "flutter": "flutter|dart\\b",
    "react native": "react[- ]native", "tailwind": "tailwind", "shadcn": "shadcn",
    "postgres": "postgres|\\bpg\\b|supabase", "sqlite": "sqlite", "mongodb": "mongo",
    "redis": "redis", "clickhouse": "clickhouse", "firebase": "firebase|firestore",
    "docker": "docker|container", "kubernetes": "kubernetes|\\bk8s\\b", "cloud run": "cloud run",
    "vercel": "vercel", "aws": "\\baws\\b|lambda|s3", "gcp": "\\bgcp\\b|google cloud|vertex",
    "azure": "\\bazure\\b", "grpc": "grpc", "graphql": "graphql", "websocket": "websocket|socket\\.io",
    "openai api": "openai|gpt-4|gpt-5|chatgpt", "gemini": "gemini|vertex ai|model armor",
    "claude": "claude|anthropic", "llama": "llama|llama.cpp", "whisper": "whisper",
    "langchain": "langchain|langgraph", "crewai": "crewai", "mcp": "\\bmcp\\b|model context protocol",
    "ollama": "ollama", "pytorch": "pytorch|torch", "tensorflow": "tensorflow|\\btf\\b",
    "transformers": "hugging ?face|transformers", "opencv": "opencv|\\bcv2\\b",
    "yolo": "yolo", "clip": "\\bclip\\b", "stable diffusion": "stable diffusion|\\bsdxl\\b|comfyui",
    "rag": "\\brag\\b|retrieval augmented", "vector db": "vector (?:db|database|store)|pinecone|qdrant|chroma|faiss",
    "redis-streams": "kafka|pubsub|pub/sub|queue", "grpc": "grpc",
    "playwright": "playwright|puppeteer|selenium", "electron": "electron", "tauri": "tauri",
    "figma": "figma", "three.js": "three\\.?js|webgl|\\bglsl\\b", "unity": "unity|unreal",
    "wasm": "\\bwasm\\b|webassembly", "ios": "\\bios\\b|iphone", "android": "android",
    "wearable": "watch|wearable|smartwatch|garmin", "raspberry-pi": "raspberry|\\bpi\\b|esp32|arduino",
    "bluetooth": "bluetooth|ble\\b", "camera": "camera|\\bcamera stream\\b|webcam",
    "stripe": "stripe", "twilio": "twilio", "sendgrid": "sendgrid",
}

# ---------------------------------------------------------------------------
# 4 · EVENT PRESTIGE  (observed signals folded into one [0,1] term)
# ---------------------------------------------------------------------------
# Prestige is derived from public hackathon API fields — see pipeline/corpus
# provenance. We deliberately do NOT hand-weight organizers beyond scale.
def event_prestige_score(registrations: Optional[int], prize_usd: Optional[int],
                         featured: Optional[bool], winners_announced: Optional[bool]) -> float:
    reg = 0.0 if not registrations else min(1.0, math.log10(max(registrations, 1)) / 4.6)  # ~40k -> 1.0
    prize = 0.0 if not prize_usd else min(1.0, math.log10(max(prize_usd, 1)) / 6.5)         # ~3M -> 1.0
    # Editorial curation (Devpost staff rails) carries scale-free prestige: the
    # showcase has no registrations or prize pool, so it must not score ~0.
    prestige = 0.55 * reg + 0.30 * prize
    if featured:
        prestige += 0.08
    if not registrations and not prize_usd and featured:
        prestige = max(prestige, 0.38)
    if winners_announced:
        prestige += 0.07
    return round(min(1.0, prestige), 4)


AWARD_WEIGHT = {
    "Grand Prize / Overall Winner": 1.0,
    "Best in Track / Category Winner": 0.82,
    "Sponsored Prize Winner": 0.7,
    "Finalist / Semi-Finalist": 0.5,
    "Honorable Mention": 0.4,
    "Featured by Devpost Staff": 0.55,
    "Submitted / No Award": 0.12,
    "Unknown": 0.1,
}

# Words that mean "this project is 37 lines and a dream" — ADR-5 noise gate.
NOISE_PATTERNS = [
    r"^.{0,18}$",
    r"^(just|simply|we made|we built an? app|app to|for fun|test)\b",
    r"\bunder construction\b|\bin progress\b|\bdemo only\b",
]

MECHANISM_VERBS = r"\b(converts?|detects?|reads?|watches?|turns?|splits?|routes?|scores?|checks?|matches?|generates?|orchestrat\w*|indexes?|compares?|classifies?|transcribes?|verifies?|triages?|replaces?)\b"


# ---------------------------------------------------------------------------
# 5 · CLASSIFICATION
# ---------------------------------------------------------------------------
def _corpus(rec: Dict[str, Any]) -> str:
    """
    Classification text for `moves` / `stack` / `specificity`: title, summary,
    the authors' own sections and their tags.

    Event title and event themes are deliberately EXCLUDED: an event called
    "Build with Gemini" would otherwise inject 'build' into every one of its
    ~1,000 projects and flatten the taxonomy into the sponsor's name.
    """
    parts = [str(rec.get("name") or ""), str(rec.get("summary") or "")]
    parts += [str(x) for x in (rec.get("built_with") or [])]
    page = rec.get("page") or {}
    parts += [str(v) for v in page.values()]
    return " \n ".join(p for p in parts if p)


def _core_corpus(rec: Dict[str, Any]) -> str:
    """The short, high-trust text: name + one-line summary + claimed tags."""
    parts = [str(rec.get("name") or ""), str(rec.get("summary") or "")]
    parts += [str(x) for x in (rec.get("built_with") or [])]
    return " ".join(p for p in parts if p)


_META = re.compile(r"[\\\[\](){}|+*?.^$]")


def _kw_pattern(kw: str) -> str:
    """
    Keyword lists mix plain stems (`charg`) with real regex (`\\brag\\b`).
    A pattern-looking entry is compiled as written; a plain entry gets a leading
    word boundary + suffix wildcard, which fixes the `crop` inside "crop &
    rescale" class of false positives without breaking either style.
    """
    kw = kw.strip()
    if _META.search(kw):
        return kw
    # Short entries are whole words (`clip`, `ide`, `pi`); longer ones are stems
    # (`charg`, `schedul`) and may match a suffix. Without this rule `cli`
    # matches "clip" and a detector project becomes "Developer Tooling".
    if len(kw) <= 4:
        return r"(?<!\w)" + re.escape(kw) + r"\b"
    return r"(?<!\w)" + re.escape(kw) + r"\w*"


def _kw_hits(low: str, kws: List[str]) -> int:
    """Word-boundary-aware lexicon match over a lowercase haystack."""
    hits = 0
    for kw in kws:
        if not kw:
            continue
        try:
            if re.search(_kw_pattern(kw), low):
                hits += 1
        except re.error:
            continue
    return hits


def classify_record(rec: Dict[str, Any]) -> Tuple[str, str, float]:
    """
    Weighted lexicon vote across the 10 sectors. Name/summary matches count
    double vs. authored prose (long text produces incidental hits), so a
    project that merely *mentions* a farm in its challenges section does not
    get shelved under Climate.
    Returns (domain, subsystem, margin). `margin` is the confidence the UI and
    the agent contract expose; a low margin means "browse, don't trust".
    """
    core = _core_corpus(rec).lower()
    full = _corpus(rec).lower()
    scores: Dict[str, float] = {}
    for domain, spec in DOMAINS.items():
        s = 0.0
        # `signature` terms are high-precision, heavily weighted; subsystem stems
        # are high-recall and cheap. "crop" alone must not outvote "forensics".
        s += 3.0 * _kw_hits(core, spec.get("signature", [])) + 1.5 * _kw_hits(full, spec.get("signature", []))
        for kws in spec["subsystems"].values():
            s += 2.0 * _kw_hits(core, kws) + 1.0 * _kw_hits(full, kws)
        scores[domain] = s
    ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    top_domain, top_score = ranked[0]
    runner = ranked[1][1] if len(ranked) > 1 else 0.0
    if top_score == 0:
        # Honest "unshelved": the submission's own text was too thin to place.
        # Surfaced in the UI as a real bucket instead of being filed anywhere.
        return "Emerging & Cross-Domain", "Unclassified", 0.0
    subs = {
        sub: 2.0 * _kw_hits(core, kws) + _kw_hits(full, kws)
        for sub, kws in DOMAINS[top_domain]["subsystems"].items()
    }
    top_sub = max(subs.items(), key=lambda kv: kv[1])[0] if subs else "General"
    if subs and max(subs.values()) == 0:
        top_sub = "General"
    margin = 0.0 if runner == 0 else min(1.0, (top_score - runner) / max(top_score, 1))
    return top_domain, top_sub, round(margin, 3)


def classify_domain(corpus: str) -> Tuple[str, str, float]:
    """Back-compat helper (text in, labels out) used by tests and ad-hoc probes."""
    return classify_record({"name": "", "summary": corpus})


def detect_moves(corpus: str, cap: int = 4) -> List[str]:
    low = corpus.lower()
    hits: List[Tuple[int, str]] = []
    for move, spec in MOVES.items():
        n = len(re.findall(spec["pat"], low, re.IGNORECASE))
        if n:
            hits.append((n, move))
    hits.sort(key=lambda t: (-t[0], MOVE_ORDER.index(t[1])))
    return [m for _, m in hits[:cap]]


def detect_stack(rec: Dict[str, Any], corpus: str) -> List[str]:
    """Observed `built_with` tags win; lexicon matching fills in (provenance differs)."""
    observed = [str(t).strip().lower() for t in (rec.get("built_with") or []) if str(t).strip()]
    low = corpus.lower()
    derived = [name for name, pat in STACK_LEXICON.items() if re.search(pat, low, re.IGNORECASE)]
    out: List[str] = []
    for t in observed + derived:
        if t and t not in out:
            out.append(t)
    return out[:10]


def looks_noisy(summary: str) -> bool:
    s = (summary or "").strip()
    return any(re.search(p, s, re.IGNORECASE) for p in NOISE_PATTERNS)


def specificity_score(corpus: str, summary: str, built_with: List[str]) -> float:
    """Does the record describe a *mechanism* (stealable) or a *vibe* (not)?"""
    s = 0.0
    words = len(re.findall(r"[A-Za-z']+", summary or ""))
    if words >= 12:
        s += 0.18
    if words >= 26:
        s += 0.12
    if re.search(MECHANISM_VERBS, summary or "", re.IGNORECASE):
        s += 0.22
    if re.search(r"\d", summary or ""):
        s += 0.14                     # numbers = falsifiable claim
    if re.search(r"\b(via|using|through|powered by|built with)\b", corpus, re.IGNORECASE):
        s += 0.12
    if built_with:
        s += min(0.14, 0.05 * len(built_with))
    if re.search(r"[.!?]\s*[A-Z].{40,}", summary or ""):
        s += 0.08
    return round(min(1.0, s), 4)


def recency_score(event_date: Optional[str], today: str) -> float:
    """Half-life 14 months: hackathon ideas age like tooling, like papers slowly."""
    if not event_date:
        return 0.35
    try:
        y, m, d = (int(x) for x in event_date[:10].split("-"))
        ty, tm, td = (int(x) for x in today[:10].split("-"))
        days = (ty - y) * 365 + (tm - m) * 30 + (td - d)
    except Exception:
        return 0.35
    if days < 0:
        days = 0
    return round(0.5 ** (days / 426.0), 4)


def like_score(likes: Optional[int]) -> Optional[float]:
    if likes is None:
        return None
    return round(min(1.0, math.log1p(max(likes, 0)) / math.log1p(2500)), 4)


def compute_coolness(
    likes: Optional[int],
    award: Optional[str],
    registrations: Optional[int],
    prize_usd: Optional[int],
    featured: Optional[bool],
    winners_announced: Optional[bool],
    event_date: Optional[str],
    today: str,
    specificity: float,
    depth: str,
    has_thumbnail: bool,
    has_links: bool,
    kin_redundancy: float,
    staff_pick: bool = False,
) -> Dict[str, float]:
    """
    ADR-6: additive, clamped, published weights. Components ship with the record
    so a human can disagree and an agent can re-rank without our source code.
    """
    ls = like_score(likes)
    like_term = ls if ls is not None else 0.22        # unknown likes ~= mid-low prior, never punished to 0
    award_term = AWARD_WEIGHT.get(award or "Unknown", AWARD_WEIGHT["Unknown"])
    if staff_pick:
        award_term = max(award_term, AWARD_WEIGHT["Featured by Devpost Staff"])
    prestige_term = event_prestige_score(registrations, prize_usd, featured, winners_announced)
    rec_term = recency_score(event_date, today)
    rich_term = (0.55 if depth == "deep" else 0.28) + (0.25 if has_thumbnail else 0.0) + (0.20 if has_links else 0.0)
    rich_term = min(1.0, rich_term)

    parts = {
        "engagement": round(like_term, 4),
        "validation": round(award_term, 4),
        "event_prestige": round(prestige_term, 4),
        "recency": rec_term,
        "specificity": specificity,
        "signal_richness": round(rich_term, 4),
        "redundancy": round(max(0.0, min(1.0, kin_redundancy)), 4),
    }
    total = (
        0.30 * parts["engagement"]
        + 0.22 * parts["validation"]
        + 0.14 * parts["event_prestige"]
        + 0.10 * parts["recency"]
        + 0.14 * parts["specificity"]
        + 0.10 * parts["signal_richness"]
        - 0.12 * parts["redundancy"]
    )
    parts["total"] = round(max(0.0, min(1.0, total)), 4)
    return parts


def _seed(*parts: Any) -> int:
    h = 2166136261
    for b in "|".join(str(p) for p in parts).encode("utf-8"):
        h = ((h ^ b) * 16777619) & 0xFFFFFFFF
    return h


def _pick(pool: List[str], seed: int, salt: int = 0) -> str:
    return pool[(seed + salt * 7919) % len(pool)] if pool else ""


def build_inspiration_intel(rec: Dict[str, Any], moves: List[str], domain: str,
                            subsystem: str, stack: List[str]) -> Dict[str, Any]:
    """
    The `beginner_intel` analogue from the reference repo, retargeted: instead of
    explaining what a tool is, it tells a builder what to DO with the idea.
    Deterministic (seeded) so rebuilds are byte-stable (ADR-10).
    """
    name = rec.get("name") or "This project"
    seed = _seed(rec.get("slug") or name, domain)
    move_objs = [MOVES[m] for m in moves if m in MOVES]
    steal = [m["steal_this"] for m in move_objs]
    page = rec.get("page") or {}
    summary = (rec.get("summary") or "").strip()

    what = (page.get("what_it_does") or summary).strip()
    what = re.sub(r"\s+", " ", what)[:340]

    wedge = (page.get("inspiration") or "").strip()
    if wedge:
        wedge = "Their starting insight: " + re.sub(r"\s+", " ", wedge)[:260]
    else:
        wedge = _pick([
            f"The team treated the annoying part of the workflow as the product, not the demo.",
            f"They assumed the expensive step (generation, review, data entry) should be priced before it runs.",
            f"They built the thing that survives the no-budget, no-internet, no-permission case.",
        ], seed)

    naive = _pick([
        f"A prompt box that asks a human to describe what they want.",
        f"A dashboard of raw numbers with no verdict attached.",
        f"A form with 14 fields nobody fills in.",
        f"A chatbot answering questions nobody asked mid-task.",
    ], seed, 1) if not page else "A demo that needs the user to already know what to type."

    return {
        "the_wedge": wedge,
        "what_it_does": what,
        "steal_this": steal or [f"Steal the framing: {subsystem} work inside {domain}, done as a bounded loop."],
        "naive_version_vs_this": f"{naive} — then {name[:60]} made the step measurable, gated, or priced instead.",
        "reuse_surface": _pick([
            "portable to any workflow with an audit obligation",
            "portable to any tool with an expensive generation step",
            "portable to any product whose users hate forms",
            "portable to any agent that touches production data",
        ], seed, 2),
        "stack": stack,
        "how_they_built_it": (re.sub(r"\s+", " ", (page.get("how_we_built_it") or "").strip())[:320]
                              if page.get("how_we_built_it") else None),
        "hard_won_lesson": (re.sub(r"\s+", " ", (page.get("challenges") or page.get("learned") or "").strip())[:300]
                            if page.get("challenges") or page.get("learned") else None),
        "proof_points": (re.sub(r"\s+", " ", (page.get("accomplishments") or "").strip())[:300]
                         if page.get("accomplishments") else None),
        "next_moves": (re.sub(r"\s+", " ", (page.get("next") or "").strip())[:240]
                       if page.get("next") else None),
    }


# ---------------------------------------------------------------------------
# 6 · ENRICH (single entry point used by ingest + harvest)
# ---------------------------------------------------------------------------
def enrich_project_record(raw: Dict[str, Any], today: str,
                          kin_redundancy: float = 0.0,
                          event_meta: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    ev = event_meta or {}
    corpus = _corpus(raw)
    domain, subsystem, margin = classify_record(raw)
    moves = detect_moves(corpus)
    stack = detect_stack(raw, corpus)
    spec = specificity_score(corpus, raw.get("summary") or "", stack)

    rec = dict(raw)
    rec.update({
        "domain": domain,
        "domain_margin": margin,
        "subsystem": subsystem,
        "moves": moves,
        "stack": stack,
        "specificity": spec,
        "event_title": raw.get("event_title") or ev.get("title"),
        "event_org": raw.get("event_org") or ev.get("organization_name"),
        "event_url": raw.get("event_url") or (f"https://{raw['event_slug']}.devpost.com/" if raw.get("event_slug") else None),
        "event_registrations": ev.get("registrations_count"),
        "event_prize_usd": ev.get("prize_usd"),
        "event_themes": ev.get("themes") or [],
        "event_featured": ev.get("featured"),
        "event_winners_announced": ev.get("winners_announced"),
        "event_date": raw.get("event_date") or ev.get("ended_at"),
    })
    rec["coolness_parts"] = compute_coolness(
        likes=rec.get("likes"),
        award=rec.get("award"),
        registrations=rec.get("event_registrations"),
        prize_usd=rec.get("event_prize_usd"),
        featured=rec.get("event_featured"),
        winners_announced=rec.get("event_winners_announced"),
        event_date=rec.get("event_date"),
        today=today,
        specificity=spec,
        depth=rec.get("depth") or "listing",
        has_thumbnail=bool(rec.get("thumbnail")),
        has_links=bool(rec.get("repo_url") or rec.get("demo_url") or rec.get("video_url")),
        kin_redundancy=kin_redundancy,
        # `source` records which stage last wrote the row and changes when a page is fetched
        # or a capture is folded in; `event_key` is what actually says "this came from the
        # staff-picked showcase feed". Deriving a score from the former meant a record could
        # lose its staff-pick credit purely by being deepened.
        staff_pick=bool(rec.get("event_key") == "showcase"),
    )
    rec["coolness"] = rec["coolness_parts"]["total"]
    noisy = looks_noisy(rec.get("summary") or "")
    rec["admitted"] = rec["coolness"] >= 0.18 and not noisy
    if not rec["admitted"]:
        # corpus.jsonl keeps rejected records for the audit trail, so a reader (human
        # or agent) must be able to tell *why* a row exists but is unpublished: a low
        # score is a ranking opinion, a placeholder summary is a data-quality refusal.
        rec["hold_reason"] = "placeholder_summary" if noisy else "below_min_coolness"
    rec["taxonomy_version"] = TAXONOMY_VERSION
    rec["scoring_version"] = SCORING_VERSION
    rec["provenance"] = {
        "likes": "observed" if rec.get("likes") is not None else "unavailable",
        "summary": "observed",
        "built_with": "observed" if rec.get("built_with") else "unavailable",
        "domain": "derived",
        "moves": "derived",
        "stack": "derived",
        "specificity": "derived",
        "coolness": "derived",
        "event": "observed" if ev else "unknown",
        "award": "observed" if rec.get("award") else "unavailable",
    }
    rec["inspiration_intel"] = build_inspiration_intel(rec, moves, domain, subsystem, stack)
    return rec


def jaccard_kin(texts: Dict[str, str]) -> Dict[str, float]:
    """
    Near-duplicate redundancy: token-set Jaccard vs. the nearest other record.
    Descriptive only (ADR-5 / dissent D2) — never used to delete records.
    """
    toks = {k: set(re.findall(r"[a-z]{4,}", v.lower())) for k, v in texts.items()}
    keys = list(toks)
    out: Dict[str, float] = {k: 0.0 for k in keys}
    for i, a in enumerate(keys):
        ta = toks[a]
        if not ta:
            continue
        best = 0.0
        for b in keys[i + 1:]:
            tb = toks[b]
            if not tb:
                continue
            inter = len(ta & tb)
            if not inter:
                continue
            j = inter / len(ta | tb)
            if j > best:
                best = j
                if tb and j > out[b]:
                    out[b] = j
        if best > out[a]:
            out[a] = best
    return out


# ---------------------------------------------------------------------------
# AGENT CONTRACT — public row shapes (ADR-14 + audit A9). One definition, imported by
# shard_builder (which emits the bytes) and build_agent_api (which documents them), so
# the published contract can never describe a shape we stopped building. test_pipeline
# asserts the emitted CSV header and packed row_format equal these lists — the drift
# that used to be invisible is now a build failure.
# ---------------------------------------------------------------------------

# Tier-1 positional contract. Append-only: integers in `rows` are decoded by index, so
# reordering these names would silently mislabel every column for every consumer.
ROW_FORMAT = ["id", "name", "hook", "event_id", "likes", "coolness_x1000", "domain_id",
              "subsystem_id", "move_ids[]", "stack_ids[]", "is_deep", "has_thumbnail",
              "award_id", "event_age_days",
              # audit layer: ids into packed["verdicts"] / packed["worth"], so a client can
              # drop unvetted or low-worth rows without fetching a single audit sheet
              "verdict_id", "worth_id"]

# Audit columns lead the CSV, because they change how every column after them should be
# read; the remaining order is the pre-audit shape, byte-for-byte, for existing consumers.
AUDIT_CSV_COLUMNS = ["verdict", "worth", "soundness", "soundness_score", "rubric_coverage",
                     "audited_at", "unknowns", "repo_url"]
BASE_CSV_COLUMNS = [
    "id", "name", "url", "event", "event_org", "domain", "subsystem", "moves",
    "stack", "coolness", "engagement", "validation", "event_prestige", "recency",
    "specificity", "signal_richness", "redundancy", "likes", "award", "depth",
    "has_deep", "event_date", "harvested_at",
]
CSV_COLUMNS = AUDIT_CSV_COLUMNS + BASE_CSV_COLUMNS
# The pool is the same table plus three columns, so one `csv.DictReader` configuration serves
# both files and a consumer never has to guess which column holds the id.
POOL_CSV_EXTRA = ["provenance", "why_not_promoted", "would_settle_it"]
POOL_CSV_COLUMNS = CSV_COLUMNS + POOL_CSV_EXTRA
