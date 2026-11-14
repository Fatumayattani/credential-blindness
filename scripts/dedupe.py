"""
Collapse retried calls: keep one record per (model, trial_id).

A rate-limited call is written as a failed record; rerunning run.py retries it and appends the
successful record. This keeps the successful record when one exists, otherwise the last attempt.

Usage:
    python scripts/dedupe.py results/main.jsonl results/main_clean.jsonl
"""
import json
import sys
from collections import Counter
from pathlib import Path


def main(src, dst):
    best, order = {}, []
    for line in Path(src).read_text().splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        key = (r["model"], r["trial_id"])
        if key not in best:
            order.append(key)
            best[key] = r
        elif r.get("parsed") is not None or best[key].get("parsed") is None:
            best[key] = r
    with open(dst, "w") as f:
        for key in order:
            f.write(json.dumps(best[key]) + "\n")
    per_model = Counter(k[0] for k in order)
    failed = Counter(k[0] for k in order if best[k].get("parsed") is None)
    print(f"{len(order)} unique trials written to {dst}")
    for m in sorted(per_model):
        print(f"  {m:35s} {per_model[m]:5d} trials, {failed[m]} still failed")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    main(sys.argv[1], sys.argv[2])
