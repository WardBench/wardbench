#!/usr/bin/env python3
"""S9: qwen3-14b on denied + clinically rephrased -perm twins (record + prompt)."""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PY = ROOT / ".venv" / "bin" / "python"
RUN = ROOT / "scripts" / "run.py"
OUT_DIR = ROOT / "results" / "v0.4"


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--base-url", default="http://127.0.0.1:8501/v1")
    ap.add_argument("--model", default="qwen3-14b")
    ap.add_argument("--modes", default="record,prompt")
    args = ap.parse_args()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for mode in [m.strip() for m in args.modes.split(",") if m.strip()]:
        out = OUT_DIR / f"qwen3-14b_perm_rephrase_{mode}.json"
        cmd = [
            str(PY), "-u", str(RUN),
            "--agent", "openai_compat",
            "--base-url", args.base_url,
            "--model", args.model,
            "--policy-visibility", mode,
            "--temperature", "0",
            "--seed", "1",
            "--disable-thinking",
            "--cohort", "dev_pool",
            "--tasks", str(ROOT / "tasks" / "dev.jsonl"),
            "--denied-only",
            "--include-perm",
            "--perm-clinical-rephrase",
            "--out", str(out),
        ]
        print(" ".join(cmd), flush=True)
        code = subprocess.call(cmd)
        if code != 0:
            sys.exit(code)


if __name__ == "__main__":
    main()
