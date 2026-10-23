#!/usr/bin/env python3
"""Run record+prompt for one or more models into results/v0.4/.

Uses the same settings as run_v04_model.py (temp=0, seed=1, --include-perm).
Does not start LocalAI; smoke each model first with scripts/smoke_tools.py.
Unloads the previous LocalAI model via POST /backend/shutdown before each switch.
"""
import argparse
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from wardbench.agents import unload_localai_model  # noqa: E402


def unload(base_url: str, model: str) -> None:
    code, body = unload_localai_model(base_url, model)
    print(f"unload {model!r}: status={code} body={body[:200]!r}", flush=True)
    time.sleep(2)


def run(model: str, mode: str, *, base_url: str, tool_mode: str, resume: bool) -> int:
    safe = model.replace("/", "_").replace(":", "_")
    out = ROOT / "results" / "v0.4" / f"{safe}_dev_{mode}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    py = ROOT / ".venv" / "bin" / "python"
    if not py.exists():
        py = Path(sys.executable)
    cmd = [
        str(py), "-u", str(ROOT / "scripts" / "run.py"),
        "--agent", "openai_compat",
        "--base-url", base_url,
        "--model", model,
        "--policy-visibility", mode,
        "--temperature", "0",
        "--seed", "1",
        "--disable-thinking",
        "--cohort", "dev_pool",
        "--include-perm",
        "--tool-mode", tool_mode,
        "--tasks", str(ROOT / "tasks" / "dev.jsonl"),
        "--out", str(out),
    ]
    if resume:
        cmd.append("--resume")
    print(" ".join(cmd), flush=True)
    return subprocess.call(cmd)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--models", required=True, help="comma-separated LocalAI model ids")
    ap.add_argument("--modes", default="record,prompt")
    ap.add_argument("--base-url", default="http://127.0.0.1:8501/v1")
    ap.add_argument("--tool-mode", default="native", choices=["native", "react_json"])
    ap.add_argument("--resume", action="store_true")
    ap.add_argument(
        "--unload-between",
        action="store_true",
        default=True,
        help="POST /backend/shutdown before each model (default on)",
    )
    ap.add_argument("--no-unload-between", action="store_false", dest="unload_between")
    args = ap.parse_args()
    prev = None
    for model in args.models.split(","):
        model = model.strip()
        if not model:
            continue
        if args.unload_between:
            if prev:
                unload(args.base_url, prev)
            unload(args.base_url, model)
        for mode in args.modes.split(","):
            mode = mode.strip()
            if mode not in ("record", "prompt", "enforced", "prompt_enforced"):
                sys.exit(f"bad mode {mode!r}")
            code = run(
                model, mode, base_url=args.base_url,
                tool_mode=args.tool_mode, resume=args.resume,
            )
            if code != 0:
                sys.exit(code)
        prev = model
    if args.unload_between and prev:
        unload(args.base_url, prev)


if __name__ == "__main__":
    main()
