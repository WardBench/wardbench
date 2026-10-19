#!/usr/bin/env python3
"""qwen3-14b on tasks/dev.jsonl → results/v0.3/ (record, then prompt)."""
import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def run(mode: str):
    out = ROOT / "results" / "v0.3" / f"qwen3-14b_dev_{mode}.json"
    cmd = [
        str(ROOT / ".venv" / "bin" / "python"), "-u", str(ROOT / "scripts" / "run.py"),
        "--agent", "openai_compat",
        "--base-url", "http://127.0.0.1:8501/v1",
        "--model", "qwen3-14b",
        "--policy-visibility", mode,
        "--temperature", "0",
        "--seed", "1",
        "--disable-thinking",
        "--cohort", "dev_pool",
        "--tasks", str(ROOT / "tasks" / "dev.jsonl"),
        "--out", str(out),
    ]
    print(" ".join(cmd), flush=True)
    return subprocess.call(cmd)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--modes", default="record,prompt")
    args = ap.parse_args()
    for mode in args.modes.split(","):
        code = run(mode.strip())
        if code != 0:
            sys.exit(code)


if __name__ == "__main__":
    main()
