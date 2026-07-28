#!/usr/bin/env python3
"""Measure how well a Claude Code skill triggers, against the REAL installed skill.

For each query in the eval set, runs `claude -p` once and checks whether the model
fired the skill (a `Skill` tool_use whose `skill` input contains the skill name).
Prints a confusion matrix (precision / recall / accuracy) and the misclassifications.

Why not a harness that registers a temp copy of the skill? If the skill is already
installed under its base name, the model fires the REAL one — a harness that keys on a
hashed temp name will silently report "not triggered" for everything (recall 0%). So
test against ground truth: the installed skill itself.

Usage:
    python validate.py --skill verified-delivery --eval trigger-eval.example.json
    python validate.py --skill my-skill --eval evals.json --model claude-opus-5 --runs 3
"""

import argparse
import json
import os
import subprocess


def fired(query: str, skill: str, model: str | None) -> bool:
    """True if `claude -p query` fires Skill(skill=...<skill>...)."""
    env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}
    cmd = [
        "claude",
        "-p",
        query,
        "--output-format",
        "stream-json",
        "--verbose",
        "--max-turns",
        "1",
    ]
    if model:
        cmd += ["--model", model]
    p = subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=120)
    for line in p.stdout.splitlines():
        try:
            e = json.loads(line)
        except Exception:
            continue
        if e.get("type") == "assistant":
            for c in e["message"].get("content", []):
                if c.get("type") == "tool_use" and c.get("name") == "Skill":
                    if skill in (c.get("input") or {}).get("skill", ""):
                        return True
    return False


def majority(query, skill, model, runs):
    hits = sum(fired(query, skill, model) for _ in range(runs))
    return hits * 2 > runs  # strict majority


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--skill", required=True, help="Skill name (as in Skill(skill=...))"
    )
    ap.add_argument("--eval", required=True, help="Path to eval set JSON")
    ap.add_argument(
        "--model",
        default=None,
        help="Model for claude -p (default: your configured model)",
    )
    ap.add_argument(
        "--runs", type=int, default=1, help="Runs per query; majority vote (default 1)"
    )
    args = ap.parse_args()

    queries = json.load(open(args.eval))
    fp, fn, tp, tn = [], [], 0, 0
    for q in queries:
        exp = q["should_trigger"]
        got = majority(q["query"], args.skill, args.model, args.runs)
        ok = got == exp
        if got and exp:
            tp += 1
        elif got and not exp:
            fp.append(q["query"])
        elif not got and exp:
            fn.append(q["query"])
        else:
            tn += 1
        print(
            f"{'OK ' if ok else 'XX '} got={str(got):5} exp={str(exp):5} | {q['query'][:60]}"
        )

    n = len(queries)
    prec = tp / (tp + len(fp)) if (tp + len(fp)) else 1.0
    rec = tp / (tp + len(fn)) if (tp + len(fn)) else 1.0
    print(f"\n==== CONFUSION ====\nTP={tp} FN={len(fn)} | FP={len(fp)} TN={tn}")
    print(f"precision={prec:.0%}  recall={rec:.0%}  accuracy={(tp + tn) / n:.0%}")
    if fn:
        print("\nFALSE NEGATIVES (should fire, didn't):")
        for x in fn:
            print("  -", x)
    if fp:
        print("\nFALSE POSITIVES (shouldn't fire, did):")
        for x in fp:
            print("  -", x)


if __name__ == "__main__":
    main()
