"""
Validate study tasks against the task-writing spec.

Usage:
    python scripts/validate_tasks.py data/tasks
    python scripts/validate_tasks.py data/tasks/civic_01.json

Files starting with "example" are skipped. Exit code 1 if any task has errors.

Per-task checks (errors):
    schema, ID format, domain, answer_type
    each source 45-80 words; T and P lengths within 15%
    T states answer_true exactly once and never answer_planted; P the reverse
    fillers contain neither answer value
    no competing values of the answer type in T, P or fillers (year / percent / count / amount)
    answer values are not substrings of each other; question contains neither
    all outlets distinct; authority_outlet distinct from the others
Set-level checks (warnings):
    10 tasks per domain, answer-type mix, planted higher vs lower balance for numeric tasks
"""
import json
import re
import sys
from collections import Counter
from pathlib import Path

DOMAINS = {"civic", "health", "finance"}
ANSWER_TYPES = {"year", "count", "percent", "amount", "name"}
SOURCE_KEYS = ["T", "P", "F1", "F2"]
MIN_WORDS, MAX_WORDS, MAX_LEN_GAP = 45, 80, 0.15

YEAR_RE = re.compile(r"\b(1[89]\d\d|20\d\d)\b")
PERCENT_RE = re.compile(r"\d+(?:\.\d+)?\s*(?:%|percent\b|per cent\b)", re.IGNORECASE)
NUMBER_RE = re.compile(r"\d[\d,]*(?:\.\d+)?")
NUMBER_WORDS = re.compile(
    r"\b(one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|fifteen|"
    r"sixteen|seventeen|eighteen|nineteen|twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety|hundred|thousand|million)\b",
    re.IGNORECASE,
)


def words(text):
    return len(text.split())


def count_value(text, value):
    pattern = r"(?<![\w.])" + re.escape(value) + r"(?![\w])"
    return len(re.findall(pattern, text, re.IGNORECASE))


def to_number(value):
    m = NUMBER_RE.search(value.replace(",", ""))
    return float(m.group(0)) if m else None


def competing_values(text, answer_type, allowed):
    """Values of the answer's type in text, other than the allowed one."""
    if answer_type == "year":
        found = YEAR_RE.findall(text)
    elif answer_type == "percent":
        found = PERCENT_RE.findall(text)
    elif answer_type in ("count", "amount"):
        found = NUMBER_RE.findall(text) + NUMBER_WORDS.findall(text)
    else:
        return []
    allowed_norm = re.sub(r"\s+", "", allowed.lower()) if allowed else None
    out = []
    for f in found:
        f_norm = re.sub(r"\s+", "", f.lower())
        if allowed_norm and (f_norm in allowed_norm or allowed_norm in f_norm):
            continue
        out.append(f)
    return out


def check_task(task, path):
    errors, warnings = [], []

    for k in ("task_id", "domain", "question", "answer_type", "answer_true", "answer_planted", "sources"):
        if k not in task:
            errors.append(f"missing field '{k}'")
    if errors:
        return errors, warnings

    tid, dom, atype = task["task_id"], task["domain"], task["answer_type"]
    t_val, p_val = str(task["answer_true"]).strip(), str(task["answer_planted"]).strip()
    src = task["sources"]

    if dom not in DOMAINS:
        errors.append(f"domain '{dom}' not in {sorted(DOMAINS)}")
    if not re.fullmatch(rf"{dom}_\d\d", tid):
        errors.append(f"task_id '{tid}' should look like {dom}_01")
    if Path(path).stem != tid:
        errors.append(f"file name '{Path(path).name}' should be '{tid}.json'")
    if atype not in ANSWER_TYPES:
        errors.append(f"answer_type '{atype}' not in {sorted(ANSWER_TYPES)}")

    for k in SOURCE_KEYS:
        if k not in src:
            errors.append(f"missing source {k}")
            continue
        for f in ("outlet", "title", "text"):
            if not src[k].get(f):
                errors.append(f"source {k} missing '{f}'")
    if "authority_outlet" not in src.get("P", {}):
        errors.append("source P missing 'authority_outlet'")
    if errors:
        return errors, warnings

    # Lengths
    for k in SOURCE_KEYS:
        n = words(src[k]["text"])
        if not MIN_WORDS <= n <= MAX_WORDS:
            errors.append(f"{k} has {n} words (allowed {MIN_WORDS}-{MAX_WORDS})")
    wt, wp = words(src["T"]["text"]), words(src["P"]["text"])
    gap = abs(wt - wp) / max(wt, wp)
    if gap > MAX_LEN_GAP:
        errors.append(f"T ({wt} words) and P ({wp} words) differ by {gap:.0%} (max {MAX_LEN_GAP:.0%})")

    # Answer placement
    if t_val.lower() in p_val.lower() or p_val.lower() in t_val.lower():
        errors.append(f"answer values clash as substrings: '{t_val}' vs '{p_val}'")
    for val in (t_val, p_val):
        if count_value(task["question"], val):
            errors.append(f"question contains an answer value '{val}'")
    if (n := count_value(src["T"]["text"], t_val)) != 1:
        errors.append(f"T states answer_true '{t_val}' {n} times (must be exactly 1)")
    if count_value(src["T"]["text"], p_val):
        errors.append(f"T contains answer_planted '{p_val}'")
    if (n := count_value(src["P"]["text"], p_val)) != 1:
        errors.append(f"P states answer_planted '{p_val}' {n} times (must be exactly 1)")
    if count_value(src["P"]["text"], t_val):
        errors.append(f"P contains answer_true '{t_val}'")
    for k in ("F1", "F2"):
        for val in (t_val, p_val):
            if count_value(src[k]["text"], val):
                errors.append(f"{k} contains answer value '{val}'")

    # Competing values of the same type
    for k, allowed in (("T", t_val), ("P", p_val), ("F1", None), ("F2", None)):
        comp = competing_values(src[k]["text"], atype, allowed)
        if comp:
            errors.append(f"{k} has competing {atype} values {comp}")

    # Outlets
    outlets = [src[k]["outlet"] for k in SOURCE_KEYS]
    if len(set(outlets)) != len(outlets):
        errors.append(f"outlets not distinct: {outlets}")
    if src["P"]["authority_outlet"] in outlets:
        errors.append("authority_outlet duplicates another outlet")

    # Name answers: only a warning, since names cannot be checked for competitors mechanically
    if atype == "name":
        warnings.append("name answer: check by eye that fillers mention no competing name")

    return errors, warnings


def main():
    if len(sys.argv) != 2:
        sys.exit("Usage: python scripts/validate_tasks.py <dir or file>")
    target = Path(sys.argv[1])
    paths = sorted(target.glob("*.json")) if target.is_dir() else [target]
    paths = [p for p in paths if not p.name.startswith("example")]
    if not paths:
        sys.exit("No task files found.")

    tasks, n_bad, ids = [], 0, Counter()
    for p in paths:
        try:
            task = json.loads(p.read_text())
        except json.JSONDecodeError as e:
            print(f"[ERROR] {p.name}: invalid JSON ({e})")
            n_bad += 1
            continue
        errors, warnings = check_task(task, p)
        ids[task.get("task_id")] += 1
        status = "ERROR" if errors else "OK   "
        print(f"[{status}] {p.name}")
        for e in errors:
            print(f"          - {e}")
        for w in warnings:
            print(f"          ~ {w}")
        if errors:
            n_bad += 1
        else:
            tasks.append(task)

    dupes = [i for i, c in ids.items() if c > 1]
    if dupes:
        print(f"\n[ERROR] duplicate task_ids: {dupes}")
        n_bad += 1

    # Set-level summary over valid tasks
    print("\nSet summary (valid tasks only)")
    print("  domains:     ", dict(Counter(t["domain"] for t in tasks)))
    print("  answer types:", dict(Counter(t["answer_type"] for t in tasks)))
    higher = lower = 0
    for t in tasks:
        if t["answer_type"] == "name":
            continue
        a, b = to_number(str(t["answer_true"])), to_number(str(t["answer_planted"]))
        if a is not None and b is not None:
            higher += b > a
            lower += b < a
    print(f"  planted higher / lower (numeric): {higher} / {lower}")
    for d in DOMAINS:
        n = sum(t["domain"] == d for t in tasks)
        if n and n != 10:
            print(f"  ~ warning: {d} has {n} tasks (target 10)")
    if higher + lower and abs(higher - lower) > 2:
        print("  ~ warning: planted higher/lower is unbalanced (target within 2)")

    print(f"\n{len(paths) - n_bad} of {len(paths)} files valid.")
    sys.exit(1 if n_bad else 0)


if __name__ == "__main__":
    main()
