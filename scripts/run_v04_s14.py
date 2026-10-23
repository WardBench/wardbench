#!/usr/bin/env python3
"""S14: --api-norm prompt ablation on qwen3-14b and qwen2.5-7b-fc.

Does not start LocalAI. Writes results/v0.4/<stem>_dev_prompt_norm.json.
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

DEFAULT_MODELS = (
    ("qwen3-14b", "qwen3-14b"),
    ("qwen2.5-7b-fc", "qwen2.5-7b-fc"),
)


def call(cmd: list[str]) -> int:
    print(" ".join(cmd), flush=True)
    return subprocess.call(cmd)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--base-url", default="http://127.0.0.1:8501/v1")
    ap.add_argument(
        "--models",
        default="qwen3-14b,qwen2.5-7b-fc",
        help="comma-separated LocalAI model ids",
    )
    ap.add_argument("--resume", action="store_true")
    args = ap.parse_args()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for model in [m.strip() for m in args.models.split(",") if m.strip()]:
        stem = model
        out = OUT_DIR / f"{stem}_dev_prompt_norm.json"
        cmd = [
            str(PY), "-u", str(RUN),
            "--agent", "openai_compat",
            "--base-url", args.base_url,
            "--model", model,
            "--temperature", "0",
            "--seed", "1",
            "--disable-thinking",
            "--cohort", "dev_pool",
            "--tasks", str(TASKS),
            "--policy-visibility", "prompt",
            "--include-perm",
            "--api-norm",
            "--out", str(out),
        ]
        if args.resume:
            cmd.append("--resume")
        code = call(cmd)
        if code != 0:
            sys.exit(code)


if __name__ == "__main__":
    main()
