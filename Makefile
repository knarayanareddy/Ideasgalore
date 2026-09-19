# Ideas Galore — offline-reproducible build: nothing here needs network or secrets.
# `make build` regenerates every committed artifact from pipeline/raw/ + corpus.jsonl.
PY := python3

.PHONY: all lint seed audit harvest gallery deep remix api build verify test serve clean gates

all: build

## 0. contract gate: refuse a half-read capture here, at the boundary, rather than letting a reviewer
## find it in a published sheet three stages later. `--soft` because one unfinished record must not brick
## the surfaces for the other nineteen: it records the refusal in raw/lint_rejects/ and moves on, and
## `verify` is where a refusal actually fails the build.
lint:
	$(PY) pipeline/capture_lint.py --soft

## 1. corpus: rebuild the source of truth from committed raw captures (no network)
seed: lint
	$(PY) pipeline/ingest_seed.py

## 2. audit: evidence-gated per-project audit; only publishable verdicts reach the catalog
audit: seed
	$(PY) pipeline/audit_projects.py
	$(PY) pipeline/audit_projects.py --report --queue 12

## 3. surfaces: Tier-1 packed index + Tier-2 shards + CSV + NDJSON + SQLite + stats + pool
build: seed audit
	$(PY) pipeline/shard_builder.py
	$(PY) pipeline/generate_remixes.py
	$(PY) pipeline/build_agent_api.py
	$(PY) pipeline/docsync.py

## 4. gates: budget, required fields, cross-surface parity, determinism, then tests
## `verify` depends on the node install because two of its steps shell into the frontend:
## a fresh clone (or a CI shard, or this sandbox — `node_modules` is not persisted between
## sessions) otherwise fails the gate with `vite: not found`, which reads like a broken build.
verify: build deps
	$(PY) pipeline/capture_lint.py --quiet
	$(PY) pipeline/shard_builder.py --check
	$(PY) pipeline/docsync.py --check
	$(PY) pipeline/tests/test_pipeline.py
	cd web && npm run build
	node pipeline/tests/ui_audit_smoke.mjs

test:
	$(PY) pipeline/tests/test_pipeline.py

gates:
	$(PY) pipeline/shard_builder.py --check

## live refresh (network + politeness enforced in code; see docs/DATA_ETHICS.md)
harvest:
	$(PY) pipeline/harvest_devpost.py discover --pages 4

gallery:
	$(PY) pipeline/harvest_devpost.py gallery --from-state --max-events 25 --pages 2

deep:
	$(PY) pipeline/harvest_devpost.py deep --limit 150

remix:
	$(PY) pipeline/harvest_devpost.py ingest && $(PY) pipeline/shard_builder.py

## frontend — `make serve` is the preview entry point; it installs first so a fresh
## checkout is a working preview instead of a stack of module errors.
serve: deps
	cd web && npm run dev -- --host 0.0.0.0

## `npm ci` when the lockfile is committed (reproducible), `npm install` otherwise.
web/node_modules: web/package-lock.json
	cd web && (test -f package-lock.json && npm ci --no-audit --no-fund || npm install)

deps: web/node_modules

api: deps
	cd web && npm run build
	@echo "static bundle in web/dist — serve with: python3 -m http.server -d web/dist 8080"

clean:
	rm -rf web/dist web/.vite pipeline/state /**/__pycache__
