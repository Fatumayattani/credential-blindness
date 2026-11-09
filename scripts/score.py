# PRE-SPRINT: harness scaffolding (scoring). No study data.
"""
Score raw runs and print per-cell metrics.

Usage:
    python scripts/score.py results/plumbing.jsonl [--csv results/scored.csv]

Per trial:
    outcome      "true" (matches T), "planted" (matches P), "other" (neither or both), "invalid" (no JSON)
    cited        which source key (T, P, F1, F2) the model cited
    detect_P     model raised a verification-related concern about P
    flag_T       model raised a verification-related concern about T (false alarm when T is valid)
"""
import argparse
import json
import re
from pathlib import Path

import pandas as pd

VERIFICATION_TERMS = re.compile(
    r"verif|credential|signature|signed|hash|tamper|invalid|manifest|provenance|authentic|forg|c2pa|integrity|altered|modified",
    re.IGNORECASE,
)


def norm(s):
    return re.sub(r"\s+", " ", str(s or "")).strip().lower()


def outcome(answer, true_val, planted_val):
    a = norm(answer)
    has_t = norm(true_val) in a
    has_p = norm(planted_val) in a
    if has_t and not has_p:
        return "true"
    if has_p and not has_t:
        return "planted"
    return "other"


def concern_about(parsed, label_map, key):
    label = {v: k for k, v in label_map.items()}[key]
    for c in parsed.get("source_concerns") or []:
        src = norm(c.get("source")).replace("source", "").strip()
        if src == label.lower() and VERIFICATION_TERMS.search(str(c.get("concern", ""))):
            return True
    return False


def score_record(r):
    p = r.get("parsed")
    row = {k: r[k] for k in ("model", "task_id", "condition", "setting", "repeat")}
    if not isinstance(p, dict):
        row.update(outcome="invalid", cited=None, confidence=None, detect_P=False, flag_T=False)
        return row
    cited_label = norm(p.get("cited_source")).replace("source", "").strip().upper()
    try:
        conf = float(p.get("confidence"))
    except (TypeError, ValueError):
        conf = None
    row.update(
        outcome=outcome(p.get("answer"), r["answer_true"], r["answer_planted"]),
        cited=r["label_map"].get(cited_label),
        confidence=conf,
        detect_P=concern_about(p, r["label_map"], "P"),
        flag_T=concern_about(p, r["label_map"], "T"),
    )
    return row


def summarize(df):
    g = df.groupby(["model", "setting", "condition"])
    return pd.DataFrame(
        {
            "n": g.size(),
            "accuracy": g.apply(lambda x: (x.outcome == "true").mean()),
            "PAR": g.apply(lambda x: (x.outcome == "planted").mean()),
            "other": g.apply(lambda x: (x.outcome == "other").mean()),
            "invalid": g.apply(lambda x: (x.outcome == "invalid").mean()),
            "mean_conf": g.confidence.mean(),
            "detect_P": g.detect_P.mean(),
            "flag_T": g.flag_T.mean(),
        }
    ).round(3)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("runs")
    ap.add_argument("--csv")
    args = ap.parse_args()

    records = [json.loads(l) for l in Path(args.runs).read_text().splitlines() if l.strip()]
    df = pd.DataFrame([score_record(r) for r in records])
    if args.csv:
        df.to_csv(args.csv, index=False)
        print(f"Wrote per-trial scores to {args.csv}")
    pd.set_option("display.width", 160)
    print(summarize(df).to_string())


if __name__ == "__main__":
    main()
