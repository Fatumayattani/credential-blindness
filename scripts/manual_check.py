"""
Manual validation of the automatic scorer.

Step 1, draw a stratified sample (default 50) and write a review sheet:
    python scripts/manual_check.py sample results/main.jsonl results/manual_check.csv

Step 2, fill in the two human columns in the CSV (y or n for each row):
    human_outcome_ok   is the scorer's "outcome" right? (true / planted / other)
    human_detect_ok    is the scorer's "detect_P" right? (did the model flag P for a verification reason?)

Step 3, compute agreement:
    python scripts/manual_check.py agree results/manual_check.csv
"""
import csv
import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from score import score_record  # noqa: E402

SEED = 13


def sample(runs, out, n=50):
    records = [json.loads(l) for l in Path(runs).read_text().splitlines() if l.strip()]
    records = [r for r in records if r.get("parsed")]
    rng = random.Random(SEED)
    # Stratify by arm x condition so every cell is represented, then top up at random.
    strata = {}
    for r in records:
        strata.setdefault((r["model"], r["condition"]), []).append(r)
    picked = []
    keys = sorted(strata)
    per = max(1, n // len(keys))
    for k in keys:
        picked += rng.sample(strata[k], min(per, len(strata[k])))
    rest = [r for r in records if r not in picked]
    picked += rng.sample(rest, max(0, n - len(picked)))
    picked = picked[:n]
    rng.shuffle(picked)

    task_q = {}
    for p in Path("data/tasks").glob("*_[0-9][0-9].json"):
        t = json.loads(p.read_text())
        task_q[t["task_id"]] = t["question"]

    fields = ["row", "model", "condition", "setting", "task_id", "question", "answer_true", "answer_planted",
              "P_label", "model_answer", "model_cited", "model_concerns", "outcome", "detect_P",
              "human_outcome_ok", "human_detect_ok"]
    with open(out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for i, r in enumerate(picked, 1):
            s = score_record(r)
            p = r["parsed"]
            inv = {v: k for k, v in r["label_map"].items()}
            w.writerow({
                "row": i, "model": r["model"], "condition": r["condition"], "setting": r["setting"],
                "task_id": r["task_id"], "question": task_q.get(r["task_id"], ""),
                "answer_true": r["answer_true"], "answer_planted": r["answer_planted"], "P_label": inv["P"],
                "model_answer": p.get("answer"), "model_cited": p.get("cited_source"),
                "model_concerns": json.dumps(p.get("source_concerns") or [], ensure_ascii=False),
                "outcome": s["outcome"], "detect_P": s["detect_P"],
                "human_outcome_ok": "", "human_detect_ok": "",
            })
    print(f"Wrote {len(picked)} rows to {out}. Fill human_outcome_ok and human_detect_ok with y or n.")


def agree(path):
    rows = list(csv.DictReader(open(path)))
    for col in ("human_outcome_ok", "human_detect_ok"):
        vals = [r[col].strip().lower() for r in rows if r[col].strip()]
        if not vals:
            print(f"{col}: not filled in yet")
            continue
        yes = sum(v == "y" for v in vals)
        print(f"{col}: {yes}/{len(vals)} agree ({yes / len(vals):.0%})")
        bad = [r["row"] for r in rows if r[col].strip().lower() == "n"]
        if bad:
            print(f"  disagreements in rows: {', '.join(bad)}")


if __name__ == "__main__":
    if len(sys.argv) >= 2 and sys.argv[1] == "sample" and len(sys.argv) == 4:
        sample(sys.argv[2], sys.argv[3])
    elif len(sys.argv) == 3 and sys.argv[1] == "agree":
        agree(sys.argv[2])
    else:
        sys.exit(__doc__)
