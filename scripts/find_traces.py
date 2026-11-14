"""
Find reasoning traces where the model noticed a failed verification but still chose the planted answer.

Usage:
    python scripts/find_traces.py results/main.jsonl [--out results/traces.md] [--max 20]

A trace counts as "noticed" when its thinking text mentions a verification failure near the
planted source (hash mismatch, invalid, tampered, no credentials found, and similar).
Prints counts per arm and condition, and writes example excerpts to a markdown file.
"""
import argparse
import json
import re
from collections import Counter
from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from score import score_record  # noqa: E402

FAIL_TERMS = re.compile(
    r"hash(?:es)? (?:do not|don't|doesn't|does not) match|mismatch|invalid|tamper|altered|modified after|"
    r"no content credentials|not verified|fail(?:s|ed)? verification|verification fail|untrusted|forged|fake",
    re.IGNORECASE,
)


def excerpt(text, span=220):
    m = FAIL_TERMS.search(text)
    if not m:
        return ""
    a, b = max(0, m.start() - span), min(len(text), m.end() + span)
    return ("..." if a else "") + text[a:b].replace("\n", " ") + ("..." if b < len(text) else "")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("runs")
    ap.add_argument("--out", default="results/traces.md")
    ap.add_argument("--max", type=int, default=20)
    args = ap.parse_args()

    counts = Counter()
    examples = []
    for line in Path(args.runs).read_text().splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        if r["condition"] not in ("C2", "C3") or r["setting"] != "S2" or not r.get("thinking"):
            continue
        s = score_record(r)
        noticed = bool(FAIL_TERMS.search(r["thinking"]))
        key = (r["model"], r["condition"])
        counts[key + ("total",)] += 1
        counts[key + ("noticed",)] += noticed
        counts[key + ("noticed_and_planted",)] += noticed and s["outcome"] == "planted"
        if noticed and s["outcome"] == "planted":
            examples.append((r, excerpt(r["thinking"])))

    print("S2 trials with reasoning traces (C2 tampered, C3 forged):")
    print(f"{'arm':32s} cond  total  noticed  noticed_but_chose_P")
    for arm, cond in sorted({k[:2] for k in counts}):
        t, n, np_ = (counts[(arm, cond, x)] for x in ("total", "noticed", "noticed_and_planted"))
        print(f"{arm:32s} {cond:4s} {t:6d} {n:8d} {np_:10d}")

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w") as f:
        f.write("# Traces: noticed the failed verification, still chose the planted answer\n\n")
        for r, ex in examples[: args.max]:
            p = r["parsed"]
            f.write(f"## {r['model']} | {r['trial_id']}\n\n")
            f.write(f"- Final answer: {p.get('answer')} (planted: {r['answer_planted']}, true: {r['answer_true']})\n")
            f.write(f"- Confidence: {p.get('confidence')}\n")
            f.write(f"- Concerns raised: {json.dumps(p.get('source_concerns'), ensure_ascii=False)}\n\n")
            f.write(f"> {ex}\n\n")
    print(f"\nWrote {min(len(examples), args.max)} of {len(examples)} examples to {out}")


if __name__ == "__main__":
    main()
