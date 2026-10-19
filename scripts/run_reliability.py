#!/usr/bin/env python3
"""Run a stratified 20-task subset three times with identical settings."""
import json
import pathlib
import random
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts.run import load_tasks, run_agent  # noqa: E402
from wardbench.agents import OpenAICompatAgent  # noqa: E402
from wardbench.cohort import build_pool_cohort  # noqa: E402

OUT = ROOT / "results" / "v0.3" / "reliability.json"
RAW = ROOT / "results" / "v0.3" / "reliability_raw"


def pick_tasks(tasks, n=20, seed=1):
    """Stratify by category first (5 each), then by family inside the category."""
    rng = random.Random(seed)
    by_cat = {}
    for t in tasks:
        by_cat.setdefault(t["category"], []).append(t)
    per = n // 4
    chosen = []
    for cat in ("allowed", "denied", "boundary", "adversarial"):
        pool = list(by_cat.get(cat, []))
        rng.shuffle(pool)
        # unique families preferred
        seen_fam, picks = set(), []
        for t in pool:
            if t["family"] in seen_fam:
                continue
            picks.append(t)
            seen_fam.add(t["family"])
            if len(picks) >= per:
                break
        while len(picks) < per and pool:
            t = pool[len(picks) % len(pool)]
            if t not in picks:
                picks.append(t)
            else:
                break
        chosen.extend(picks[:per])
    return chosen[:n]


def tool_seq(result):
    return [(e["tool"], e.get("resource_type"), json.dumps(e.get("args"), sort_keys=True))
            for e in result.get("tool_log") or []]


def main():
    tasks = load_tasks(ROOT / "tasks" / "dev.jsonl")
    subset = pick_tasks(tasks, 20, seed=1)
    RAW.mkdir(parents=True, exist_ok=True)
    cohort = build_pool_cohort(ROOT / "work" / "synthea" / "cohort_v03" / "dev")
    runs = []
    for r in range(1, 4):
        agent = OpenAICompatAgent(
            "qwen3-14b", "http://127.0.0.1:8501/v1", api_key="local",
            temperature=0, seed=1, disable_thinking=True,
        )
        t0 = time.perf_counter()
        results = run_agent(agent, subset, cohort, "record", include_controls=False)
        path = RAW / f"run{r}.json"
        path.write_text(json.dumps(results, indent=2), encoding="utf-8")
        runs.append({"run": r, "seconds": round(time.perf_counter() - t0, 1), "tasks": results})
        print(f"run {r} done in {runs[-1]['seconds']}s", flush=True)

    by_id = {t["id"]: [] for t in subset}
    for run in runs:
        for task in run["tasks"]:
            by_id[task["id"]].append(task)

    per_task = []
    flips = 0
    for tid, rows in by_id.items():
        successes = [bool(r["success"]) for r in rows]
        statuses = [r.get("response_status") for r in rows]
        seqs = [tool_seq(r) for r in rows]
        agree_success = len(set(successes)) == 1
        if not agree_success:
            flips += 1
        per_task.append({
            "id": tid,
            "family": next(t["family"] for t in subset if t["id"] == tid),
            "successes": successes,
            "success_agreement": agree_success,
            "response_status": statuses,
            "status_agreement": len(set(statuses)) == 1,
            "tool_seq_agreement": all(s == seqs[0] for s in seqs),
        })

    report = {
        "n_tasks": len(subset),
        "n_runs": 3,
        "settings": {
            "model": "qwen3-14b", "temperature": 0, "seed": 1,
            "disable_thinking": True, "n_ctx": 16384, "policy_visibility": "record",
            "parallel_slots": 1,
        },
        "noise_floor": flips / len(subset),
        "n_flips": flips,
        "per_task": per_task,
        "runs_seconds": [r["seconds"] for r in runs],
        "likely_nondeterminism": (
            "LocalAI/llama.cpp still fills a reasoning channel on tool turns; GPU kernels and "
            "prompt packing are not bit-stable even at temperature 0. Tool-argument JSON and "
            "search pagination can diverge enough to change graded success."
        ),
    }
    OUT.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({"noise_floor": report["noise_floor"], "n_flips": flips, "out": str(OUT)}, indent=2))


if __name__ == "__main__":
    main()
