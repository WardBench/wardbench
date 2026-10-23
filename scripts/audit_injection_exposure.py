#!/usr/bin/env python3
"""Indirect prompt-injection exposure decomposition over saved v0.4 runs (S12).

No LLM calls. Thin CLI over `wardbench.audit_metrics` (S12b library).
"""
from __future__ import annotations

import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from wardbench.audit_metrics import (  # noqa: E402
    channel_inventory,
    injection_exposure_metrics,
)
from wardbench.stats import wilson  # noqa: E402

V04 = ROOT / "results" / "v0.4"
TASKS = ROOT / "tasks" / "dev.jsonl"

RUNS = [
    ("qwen2.5-7b-fc", "record"),
    ("qwen2.5-7b-fc", "prompt"),
    ("qwen3-14b", "record"),
    ("qwen3-14b", "prompt"),
    ("qwen3-14b", "enforced"),
    ("qwen3-14b", "prompt_enforced"),
    ("qwen3-32b", "record"),
    ("qwen3-32b", "prompt"),
]


def pct(r: float) -> str:
    if r != r:
        return "n/a"
    return f"{100 * r:.1f}%"


def fmt(obj: dict) -> str:
    lo, hi = obj.get("wilson95") or wilson(obj["k"], obj["n"])
    return f"{obj['k']}/{obj['n']}={pct(obj['rate'])} (Wilson {pct(lo)}–{pct(hi)})"


def agent_block(doc: dict):
    for key, val in doc.items():
        if key != "meta" and isinstance(val, dict) and "tasks" in val:
            return key, val
    raise SystemExit("no agent block")


def load_tasks():
    return [json.loads(l) for l in TASKS.read_text().splitlines() if l.strip()]


def load_run(stem: str, mode: str):
    path = V04 / f"{stem}_dev_{mode}.json"
    if not path.exists():
        return None
    doc = json.loads(path.read_text())
    _, block = agent_block(doc)
    return path, block["tasks"]


def analyze_all(runs=None):
    runs = runs or RUNS
    tasks = load_tasks()
    adv = [t for t in tasks if t.get("category") == "adversarial"]
    inventory = channel_inventory(adv)
    results = {}
    for stem, mode in runs:
        loaded = load_run(stem, mode)
        if not loaded:
            results[(stem, mode)] = None
            continue
        _path, rows = loaded
        results[(stem, mode)] = injection_exposure_metrics(rows, adv)
    return inventory, results, adv


def main():
    inventory, results, _adv = analyze_all()
    print("## Injection channel inventory")
    print(json.dumps(inventory, indent=2))
    print()
    print(
        "| model | mode | exposure | DocRef touch | voluntary DocRef | "
        "attack_induced | cond_success|exposed&ctrl_clean |"
    )
    print("|---|---|---|---|---|---|---|")
    for stem, mode in RUNS:
        r = results.get((stem, mode))
        if not r:
            print(f"| {stem} | {mode} | missing | — | — | — | — |")
            continue
        print(
            f"| {stem} | {mode} | {fmt(r['injection_exposure_rate'])} | "
            f"{fmt(r['documentreference_touch_rate'])} | "
            f"{fmt(r['voluntary_docref_exposure_rate'])} | "
            f"{fmt(r['attack_induced_rate'])} | "
            f"{fmt(r['conditional_injection_success_given_exposed'])} |"
        )
        if r["induced_without_exposure"]:
            ids = [x["id"] for x in r["induced_without_exposure"]]
            print(f"  # induced w/o exposure: {ids}")
        if r["induced_with_exposure"]:
            ids = [x["id"] for x in r["induced_with_exposure"]]
            print(f"  # induced with exposure: {ids}")


if __name__ == "__main__":
    main()
