#!/usr/bin/env python3
"""qwen3-14b on tasks/dev.jsonl → results/v0.4/ (record, prompt, enforced).

Always includes adversarial -ctrl twins (default in run.py) and denied -perm twins.
Does not start LocalAI; the server must already listen at --base-url.
"""
import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def run(mode: str, *, base_url: str, model: str) -> int:
    out = ROOT / "results" / "v0.4" / f"qwen3-14b_dev_{mode}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        str(ROOT / ".venv" / "bin" / "python"), "-u", str(ROOT / "scripts" / "run.py"),
        "--agent", "openai_compat",
        "--base-url", base_url,
        "--model", model,
        "--policy-visibility", mode,
        "--temperature", "0",
        "--seed", "1",
        "--disable-thinking",
        "--cohort", "dev_pool",
        "--include-perm",
        "--tasks", str(ROOT / "tasks" / "dev.jsonl"),
        "--out", str(out),
    ]
    print(" ".join(cmd), flush=True)
    return subprocess.call(cmd)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--modes", default="record,prompt,enforced",
                    help="comma-separated policy modes (default: record,prompt,enforced)")
    ap.add_argument("--base-url", default="http://127.0.0.1:8501/v1")
    ap.add_argument("--model", default="qwen3-14b")
    args = ap.parse_args()
    for mode in args.modes.split(","):
        mode = mode.strip()
        if mode not in ("record", "prompt", "enforced"):
            sys.exit(f"unknown mode: {mode!r} (expected record|prompt|enforced)")
        code = run(mode, base_url=args.base_url, model=args.model)
        if code != 0:
            sys.exit(code)


if __name__ == "__main__":
    main()
