#!/usr/bin/env python3
"""S10: run LocalAI model id `qwen3` (32B Q4) into results/v0.4/qwen3-32b_dev_*.json.

Resumes unfinished mode files and restarts LocalAI once per mode if the backend dies.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PY = ROOT / ".venv" / "bin" / "python"
RUN = ROOT / "scripts" / "run.py"
OUT_DIR = ROOT / "results" / "v0.4"
COMPOSE_DIR = Path("/home/vadim/projects/common-services")


def localai_ok(base_url: str) -> bool:
    import urllib.request

    url = base_url.rstrip("/") + "/models"
    try:
        with urllib.request.urlopen(url, timeout=5) as resp:
            return resp.status == 200
    except Exception:
        return False


def restart_localai() -> None:
    print("restarting LocalAI…", flush=True)
    subprocess.call(
        ["docker", "compose", "--profile", "localai", "up", "-d", "localai"],
        cwd=str(COMPOSE_DIR),
    )
    for _ in range(60):
        if localai_ok("http://127.0.0.1:8501/v1"):
            print("LocalAI ready", flush=True)
            return
        time.sleep(2)
    raise SystemExit("LocalAI did not become ready after restart")


def run_mode(mode: str, base_url: str, model: str) -> int:
    out = OUT_DIR / f"qwen3-32b_dev_{mode}.json"
    cmd = [
        str(PY), "-u", str(RUN),
        "--agent", "openai_compat",
        "--base-url", base_url,
        "--model", model,
        "--policy-visibility", mode,
        "--temperature", "0",
        "--seed", "1",
        "--disable-thinking",
        "--cohort", "dev_pool",
        "--include-perm",
        "--resume",
        "--tasks", str(ROOT / "tasks" / "dev.jsonl"),
        "--out", str(out),
    ]
    print(" ".join(cmd), flush=True)
    return subprocess.call(cmd)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--base-url", default="http://127.0.0.1:8501/v1")
    ap.add_argument("--model", default="qwen3", help="LocalAI model id")
    ap.add_argument("--modes", default="record,prompt")
    args = ap.parse_args()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    if not localai_ok(args.base_url):
        restart_localai()
    for mode in [m.strip() for m in args.modes.split(",") if m.strip()]:
        code = run_mode(mode, args.base_url, args.model)
        if code != 0:
            print(f"mode={mode} exited {code}; restart LocalAI and resume once", flush=True)
            restart_localai()
            code = run_mode(mode, args.base_url, args.model)
            if code != 0:
                sys.exit(code)
    print("S10 qwen3-32b modes complete", flush=True)


if __name__ == "__main__":
    main()
