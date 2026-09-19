#!/usr/bin/env python3
"""ADR-P2 + ADR-P9 · dispatch and governor for one audit batch.

Every session that audits this catalog is the same agent with the same instructions; what keeps them from
colliding is that the assignment is a pure function of the id (`partition_of`), and what keeps the batch
from outrunning the quality signal is that the size comes from `raw/batch_policy.json`, which the lint's
reject rate edits — not from anyone's confidence.

  python3 pipeline/next_batch.py --plan                     # who gets what, as JSON
  python3 pipeline/next_batch.py --shard 2 --quiet           # just the ids, for worker 2 of 4
  python3 pipeline/next_batch.py --report --in-batch 4 --rejected 1
                                                            # after a batch: apply the governor
"""
import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from taxonomy_hacks import partition_of  # noqa: E402

POLICY = os.path.join(HERE, "raw", "batch_policy.json")
QUEUE = os.path.join(HERE, "..", "web", "public", "data", "promotion-queue.json")
AUDITED = os.path.join(HERE, "audit.jsonl")
REJECTS = os.path.join(HERE, "raw", "lint_rejects")


def load(path, default):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return default


def audited_ids():
    out = set()
    if os.path.exists(AUDITED):
        with open(AUDITED, encoding="utf-8") as fh:
            for line in fh:
                if line.strip():
                    out.add(json.loads(line).get("id"))
    return out


def batch_reject_rate(size):
    """Share of this batch's ids that the contract gate refused. Read off the ledger, not off a
    transcript: the only reject rate that means anything is one the gate produced."""
    if not size or not os.path.isdir(REJECTS):
        return 0.0
    return min(1.0, len([f for f in os.listdir(REJECTS) if f.endswith(".json")]) / float(size))


def main() -> int:
    ap = argparse.ArgumentParser(description="dispatch a batch and enforce the governor")
    ap.add_argument("--plan", action="store_true", help="print the whole assignment as JSON")
    ap.add_argument("--shard", type=int, default=None, help="print only this worker's ids")
    ap.add_argument("--workers", type=int, default=None, help="override policy.workers")
    ap.add_argument("--report", action="store_true", help="record a finished batch and re-govern")
    ap.add_argument("--in-batch", type=int, default=None)
    ap.add_argument("--rejected", type=int, default=None)
    ap.add_argument("--quiet", action="store_true")
    ap.add_argument("--policy", default=POLICY)
    ap.add_argument("--queue", default=os.path.normpath(QUEUE))
    args = ap.parse_args()

    pol = load(args.policy, {})
    workers = args.workers or int(pol.get("workers") or 1)
    size = int(pol.get("next_batch_size") or pol.get("batch_size") or 2)
    queue = load(args.queue, {})
    done = audited_ids()
    # The queue is rank order; the partition is by id. Taking the first `workers * size` unassigned
    # candidates and then splitting them keeps each worker's slice contiguous in rank (so nobody is
    # handed only the leftovers) while keeping the slices disjoint.
    candidates = [c.get("id") for c in (queue.get("candidates") or [])
                  if c.get("id") and c["id"] not in done]
    pool = candidates[:workers * size] or candidates[:size]
    assignment = {str(i): [] for i in range(workers)}
    for rid in pool:
        assignment[str(partition_of(rid, workers))].append(rid)

    if args.report is not None and args.report:
        size_rep = args.in_batch or len(pool) or size
        rate = (args.rejected or 0) / float(size_rep) if size_rep else 0.0
        if args.rejected is None:
            rate = batch_reject_rate(size_rep)
        ceil, floor = int(pol.get("ceiling") or 6), int(pol.get("floor") or 2)
        base = int(pol.get("batch_size") or size_rep)
        if rate > 0.20:
            nxt = max(floor, base // 2)
            why = f"reject rate {rate:.2f} > 0.20 → halve"
        else:
            nxt = min(ceil, base)
            why = f"reject rate {rate:.2f} ≤ 0.20 → restore toward the ceiling"
        pol["reject_rate"] = round(rate, 4)
        pol["next_batch_size"] = nxt
        hist = pol.setdefault("history", [])
        hist.append({"batch_size": size_rep, "rejected": args.rejected, "reject_rate": round(rate, 4),
                     "next_batch_size": nxt, "reason": why})
        del hist[:-12]
        with open(args.policy, "w", encoding="utf-8") as fh:
            json.dump(pol, fh, indent=2, sort_keys=True)
            fh.write("\n")
        print(f"📏 governor: {why} → next_batch_size {nxt}")
        return 0

    if args.shard is not None:
        for rid in assignment.get(str(args.shard), []):
            print(rid)
        return 0

    print(json.dumps({"workers": workers, "batch_size": size, "unassigned_candidates": len(candidates),
                      "assigned": sum(len(v) for v in assignment.values()),
                      "assignment": assignment,
                      "recipe": ["fetch_page each id's source_url",
                                 "write raw/deep_captures/{id}.json via capture_lint --install-capture",
                                 "write raw/audit_notes/{id}.json via capture_lint --install-notes",
                                 "commit and push to the session branch",
                                 "the reducer alone runs make build / --check / --report"]},
                     indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
