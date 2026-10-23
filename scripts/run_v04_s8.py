#!/usr/bin/env python3
"""S8 runs: prompt_enforced (full factorial cell) + prompt+prefetch-consent ablation.

Does not start LocalAI. Default model qwen3-14b at http://127.0.0.1:8501/v1.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PY = ROOT / ".venv" / "bin" / "python"
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
        default="prompt_enforced,consent_prefetch",
        help="comma-separated: prompt_enforced and/or consent_prefetch",
    )
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
    ]
    for step in [s.strip() for s in args.steps.split(",") if s.strip()]:
        if step == "prompt_enforced":
            out = OUT_DIR / "qwen3-14b_dev_prompt_enforced.json"
            code = call(common + [
                "--policy-visibility", "prompt_enforced",
                "--include-perm",
                "--out", str(out),
            ])
        elif step == "consent_prefetch":
            out = OUT_DIR / "qwen3-14b_dev_prompt_consent_prefetch.json"
            code = call(common + [
                "--policy-visibility", "prompt",
                "--prefetch-consent",
                "--consent-dependent-only",
                "--out", str(out),
            ])
        else:
            sys.exit(f"unknown step {step!r}")
        if code != 0:
            sys.exit(code)


if __name__ == "__main__":
    main()
