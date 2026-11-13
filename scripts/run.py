# PRE-SPRINT: harness scaffolding (model calls). Sprint change (Nov 13): records p_first.
"""
Run trials against Cohere models and append raw responses to a JSONL file.

Usage:
    python scripts/run.py --tasks data/tasks/civic_01.json --models command-a-03-2025 \
        --conditions C0 C2 --settings S2 --repeats 1 --out results/plumbing.jsonl

Model arms: append @nothink or @think to a model name to force thinking off or on,
e.g. command-a-plus-05-2026@think. The arm name (with suffix) is recorded as "model".

Resumable: trials already present in --out (same model + trial_id) are skipped.
Use --mock to test the pipeline without calling the API.
"""
import argparse
import json
import os
import random
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import prompts  # noqa: E402

RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "answer": {"type": "string"},
        "cited_source": {"type": "string"},
        "confidence": {"type": "integer"},
        "source_concerns": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"source": {"type": "string"}, "concern": {"type": "string"}},
                "required": ["source", "concern"],
            },
        },
    },
    "required": ["answer", "cited_source", "confidence", "source_concerns"],
}

LOCK = threading.Lock()


def parse_json(text):
    """Parse the model's JSON, tolerating code fences or surrounding prose."""
    if text is None:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(0))
            except json.JSONDecodeError:
                return None
    return None


def extract_text(response):
    """Return (final text, thinking text) from a Cohere v2 response."""
    parts, thoughts = [], []
    for item in response.message.content or []:
        kind = getattr(item, "type", None)
        if kind == "text":
            parts.append(item.text)
        elif kind == "thinking":
            thoughts.append(getattr(item, "thinking", "") or "")
    return ("".join(parts) if parts else None), ("\n".join(thoughts) if thoughts else None)


def parse_arm(arm):
    """'model@nothink' -> ('model', 'disabled'); 'model@think' -> ('model', 'enabled'); 'model' -> ('model', None)."""
    name, _, mode = arm.partition("@")
    return name, {"nothink": "disabled", "think": "enabled", "": None}[mode]


def usage_of(response):
    u = getattr(response, "usage", None)
    tokens = getattr(u, "tokens", None) if u else None
    return {
        "input_tokens": getattr(tokens, "input_tokens", None),
        "output_tokens": getattr(tokens, "output_tokens", None),
    }


def call_cohere(client, arm, messages, temperature, use_schema):
    model, thinking = parse_arm(arm)
    kwargs = dict(model=model, messages=messages, temperature=temperature)
    if thinking:
        kwargs["thinking"] = {"type": thinking}
    if use_schema:
        kwargs["response_format"] = {"type": "json_object", "json_schema": RESPONSE_SCHEMA}
    return client.chat(**kwargs)


def call_mock(trial):
    """Fake response for pipeline tests: picks T or P at random, sometimes flags P."""
    rng = random.Random(trial["trial_id"])
    inv = {v: k for k, v in trial["label_map"].items()}
    pick = rng.choice(["T", "P"])
    answer = trial["answer_true"] if pick == "T" else trial["answer_planted"]
    concerns = []
    if rng.random() < 0.5:
        concerns.append({"source": inv["P"], "concern": "Verification result shows the content hash does not match."})
    return json.dumps(
        {"answer": answer, "cited_source": inv[pick], "confidence": rng.randint(40, 95), "source_concerns": concerns}
    )


def run_one(client, model, trial, args):
    record = {
        "model": model,
        "trial_id": trial["trial_id"],
        "task_id": trial["task_id"],
        "condition": trial["condition"],
        "setting": trial["setting"],
        "repeat": trial["repeat"],
        "label_map": trial["label_map"],
        "p_first": trial["p_first"],
        "answer_true": trial["answer_true"],
        "answer_planted": trial["answer_planted"],
        "temperature": args.temperature,
    }
    thinking_text = None
    if args.mock:
        text, usage, err, latency = call_mock(trial), {}, None, 0.0
    else:
        text, usage, err = None, {}, None
        use_schema = True
        start = time.time()
        for attempt in range(6):
            try:
                resp = call_cohere(client, model, trial["messages"], args.temperature, use_schema)
                (text, thinking_text), usage, err = extract_text(resp), usage_of(resp), None
                break
            except Exception as e:  # rate limits, transient errors, unsupported schema
                err = f"{type(e).__name__}: {e}"
                if "response_format" in str(e) or "json_schema" in str(e):
                    use_schema = False  # model does not support structured output; fall back to prompt-only JSON
                    continue
                time.sleep(min(60, 2 ** attempt + random.random()))
        latency = round(time.time() - start, 2)
        record["structured_output"] = use_schema
    record.update(
        {
            "raw_text": text,
            "parsed": parse_json(text),
            "thinking": thinking_text,
            "error": err,
            "usage": usage,
            "latency_s": latency,
        }
    )
    return record


def load_done(path):
    done = set()
    if path.exists():
        for line in path.read_text().splitlines():
            if line.strip():
                r = json.loads(line)
                if r.get("parsed") is not None:
                    done.add((r["model"], r["trial_id"]))
    return done


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tasks", nargs="+", required=True)
    ap.add_argument("--models", nargs="+", required=True)
    ap.add_argument("--conditions", nargs="+", default=prompts.CONDITIONS)
    ap.add_argument("--settings", nargs="+", default=prompts.SETTINGS)
    ap.add_argument("--repeats", type=int, default=5)
    ap.add_argument("--temperature", type=float, default=0.7)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--out", required=True)
    ap.add_argument("--mock", action="store_true")
    args = ap.parse_args()

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    done = load_done(out)

    jobs = []
    for tpath in args.tasks:
        task = json.loads(Path(tpath).read_text())
        creds = prompts.load_credentials(task["task_id"])
        for c in args.conditions:
            for s in args.settings:
                for r in range(args.repeats):
                    trial = prompts.build_trial(task, creds, c, s, r)
                    for m in args.models:
                        if (m, trial["trial_id"]) not in done:
                            jobs.append((m, trial))

    print(f"{len(jobs)} calls to run ({len(done)} already done).")
    if not jobs:
        return

    client = None
    if not args.mock:
        import cohere
        from dotenv import load_dotenv

        load_dotenv()
        client = cohere.ClientV2(api_key=os.environ["COHERE_API_KEY"])

    n_ok = n_err = 0
    with ThreadPoolExecutor(max_workers=args.workers) as pool, open(out, "a") as f:
        futures = [pool.submit(run_one, client, m, t, args) for m, t in jobs]
        for i, fut in enumerate(as_completed(futures), 1):
            rec = fut.result()
            with LOCK:
                f.write(json.dumps(rec) + "\n")
                f.flush()
            if rec["parsed"] is None:
                n_err += 1
            else:
                n_ok += 1
            if i % 25 == 0 or i == len(futures):
                print(f"  {i}/{len(futures)}  ok={n_ok}  failed={n_err}")
    print(f"Done. Wrote {out}")


if __name__ == "__main__":
    main()
