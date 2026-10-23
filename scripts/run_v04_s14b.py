#!/usr/bin/env python3
"""S14b: targeted qwen3-32b / prompt / --api-norm on 12 schema-flagged fails.

Does not start LocalAI. Writes results/v0.4/qwen3-32b_dev_prompt_norm_targeted.json.
LocalAI model id is `qwen3` (32B Q4); result stem stays qwen3-32b_*.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PY = ROOT / ".venv" / "bin" / "python"
if not PY.exists():
    PY = Path(sys.executable)
RUN = ROOT / "scripts" / "run.py"
TASKS = ROOT / "tasks" / "dev.jsonl"
OUT = ROOT / "results" / "v0.4" / "qwen3-32b_dev_prompt_norm_targeted.json"

# S14 offline recoverable ids (bad_rtype / cond_clinical_code) on qwen3-32b prompt.
TARGET_IDS = (
    "WB-A-006",
    "WB-A-008",
    "WB-A-010",
    "WB-A-012",
    "WB-A-025",
    "WB-ADV-002",
    "WB-ADV-004",
    "WB-ADV-010",
    "WB-ADV-015",
    "WB-ADV-023",
    "WB-B-003",
    "WB-B-021",
)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--base-url", default="http://127.0.0.1:8501/v1")
    ap.add_argument("--model", default="qwen3", help="LocalAI model id for 32B")
    ap.add_argument("--resume", action="store_true")
    args = ap.parse_args()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        str(PY), "-u", str(RUN),
        "--agent", "openai_compat",
        "--base-url", args.base_url,
        "--model", args.model,
        "--temperature", "0",
        "--seed", "1",
        "--disable-thinking",
        "--cohort", "dev_pool",
        "--tasks", str(TASKS),
        "--policy-visibility", "prompt",
        "--api-norm",
        "--task-ids", ",".join(TARGET_IDS),
        "--out", str(OUT),
    ]
    if args.resume:
        cmd.append("--resume")
    print(" ".join(cmd), flush=True)
    raise SystemExit(subprocess.call(cmd))


if __name__ == "__main__":
    main()
