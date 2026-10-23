#!/usr/bin/env python3
"""S15: strict-redaction-prompt ablation on the 36-task Consent/PSY/deid subset.

Runs qwen3-14b under prompt and prompt_enforced with --strict-redaction-prompt.
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
OUT_DIR = ROOT / "results" / "v0.4"


def call(cmd: list[str]) -> int:
    print(" ".join(cmd), flush=True)
    return subprocess.call(cmd)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--base-url", default="http://127.0.0.1:8501/v1")
    ap.add_argument("--model", default="qwen3-14b")
    ap.add_argument(
        "--steps",
        default="prompt,prompt_enforced",
        help="comma-separated: prompt and/or prompt_enforced",
    )
    ap.add_argument("--resume", action="store_true")
    args = ap.parse_args()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    common = [
        str(PY), "-u", str(RUN),
        "--agent", "openai_compat",
        "--base-url", args.base_url,
        "--model", args.model,
        "--temperature", "0",
        "--seed", "1",
        "--disable-thinking",
        "--cohort", "dev_pool",
        "--tasks", str(TASKS),
        "--redaction-ablation-only",
        "--strict-redaction-prompt",
    ]
    if args.resume:
        common.append("--resume")
    for step in [s.strip() for s in args.steps.split(",") if s.strip()]:
        if step not in ("prompt", "prompt_enforced"):
            sys.exit(f"unknown step {step!r}")
        out = OUT_DIR / f"qwen3-14b_redaction_hygiene_{step}.json"
        code = call(common + [
            "--policy-visibility", step,
            "--out", str(out),
        ])
        if code != 0:
            sys.exit(code)


if __name__ == "__main__":
    main()
