"""
Review the manual-check sheet in the terminal, one row at a time.

Usage:
    python scripts/review.py results/manual_check.csv

For each row, answer y or n twice. Rows already filled are skipped, so you can stop (Ctrl+C)
and resume later. Progress is saved after every row.
"""
import csv
import json
import sys


def ask(prompt):
    while True:
        a = input(prompt).strip().lower()
        if a in ("y", "n"):
            return a
        print("  please type y or n")


def main(path):
    rows = list(csv.DictReader(open(path)))
    fields = list(rows[0].keys())
    todo = [r for r in rows if not (r["human_outcome_ok"].strip() and r["human_detect_ok"].strip())]
    print(f"{len(todo)} of {len(rows)} rows left. Ctrl+C to stop; progress is saved.\n")
    for r in todo:
        concerns = json.loads(r["model_concerns"] or "[]")
        print("=" * 70)
        print(f"Row {r['row']}  |  {r['model']}  {r['condition']} {r['setting']}  |  {r['task_id']}")
        print(f"Question:        {r['question']}")
        print(f"True answer:     {r['answer_true']}")
        print(f"Planted answer:  {r['answer_planted']}   (planted source is {r['P_label']})")
        print(f"Model answered:  {r['model_answer']}   (cited {r['model_cited']})")
        print("Model concerns:")
        for c in concerns or [{"source": "-", "concern": "(none)"}]:
            print(f"   [{c.get('source')}] {c.get('concern')}")
        print("-" * 70)
        print(f"Scorer says outcome = {r['outcome'].upper()}   (true / planted / other)")
        r["human_outcome_ok"] = ask("  Is that right? y/n: ")
        verdict = "YES" if r["detect_P"] == "True" else "NO"
        print(f"Scorer says the model flagged source {r['P_label']} for a verification problem: {verdict}")
        r["human_detect_ok"] = ask("  Is that right? y/n: ")
        with open(path, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fields)
            w.writeheader()
            w.writerows(rows)
    print("\nAll rows done. Now run: python scripts/manual_check.py agree", path)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    try:
        main(sys.argv[1])
    except (KeyboardInterrupt, EOFError):
        print("\nStopped. Progress saved; run the same command to continue.")
