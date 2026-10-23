#!/usr/bin/env python3
"""S15b: stricter anti-mention clause on the 9 S15 residual PSY/adv_disclose violators.

Runs qwen3-14b / prompt / --strict-redaction-prompt on a fixed task-id list.
Does not start LocalAI.
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
OUT = ROOT / "results" / "v0.4" / "qwen3-14b_redaction_hygiene_prompt_v2.json"

# Residual violators under S15 strict-redaction / prompt (R16).
RESIDUAL_IDS = (
    "WB-ADV-005",
    "WB-ADV-020",
    "WB-ADV-024",
    "WB-B-002",
    "WB-B-009",
    "WB-B-011",
    "WB-B-021",
    "WB-B-026",
    "WB-B-030",
)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--base-url", default="http://127.0.0.1:8501/v1")
    ap.add_argument("--model", default="qwen3-14b")
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
        "--strict-redaction-prompt",
        "--task-ids", ",".join(RESIDUAL_IDS),
        "--out", str(OUT),
    ]
    if args.resume:
        cmd.append("--resume")
    print(" ".join(cmd), flush=True)
    raise SystemExit(subprocess.call(cmd))


if __name__ == "__main__":
    main()
