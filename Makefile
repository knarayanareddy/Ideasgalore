# Ideas Galore — offline-reproducible build: nothing here needs network or secrets.
# `make build` regenerates every committed artifact from pipeline/raw/ + corpus.jsonl.
PY := python3

.PHONY: all seed harvest gallery deep remix api build verify test serve clean gates

all: build

## 1. corpus: rebuild the source of truth from committed raw captures (no network)
seed:
	$(PY) pipeline/ingest_seed.py

## 2. surfaces: Tier-1 packed index + Tier-2 shards + CSV + NDJSON + SQLite + stats
build: seed
	$(PY) pipeline/shard_builder.py
	$(PY) pipeline/generate_remixes.py
	$(PY) pipeline/build_agent_api.py

## 3. gates: budget, required fields, cross-surface parity, determinism, then tests
verify: build
	$(PY) pipeline/shard_builder.py --check
	$(PY) pipeline/tests/test_pipeline.py
	cd web && npm run build

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

## frontend
serve:
	cd web && npm run dev -- --host 0.0.0.0

web/node_modules:
	cd web && npm install

deps: web/node_modules

api:
	cd web && npm run build
	@echo "static bundle in web/dist — serve with: python3 -m http.server -d web/dist 8080"

clean:
	rm -rf web/dist web/.vite pipeline/state /**/__pycache__
