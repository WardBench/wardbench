#!/usr/bin/env python3
"""S16: qwen3-32b enforced/prompt_enforced factorial + 14B thinking ablation.

Order (VRAM): (1) qwen3-14b Consent-subset --enable-thinking,
(2) unload, (3) qwen3 enforced + prompt_enforced full include-perm --disable-thinking.

Does not start LocalAI. Result stems use qwen3-32b_* for LocalAI id `qwen3`.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from wardbench.agents import unload_localai_model  # noqa: E402

PY = ROOT / ".venv" / "bin" / "python"
if not PY.exists():
    PY = Path(sys.executable)
RUN = ROOT / "scripts" / "run.py"
TASKS = ROOT / "tasks" / "dev.jsonl"
OUT_DIR = ROOT / "results" / "v0.4"


def unload(base_url: str, model: str) -> None:
    code, body = unload_localai_model(base_url, model)
    print(f"unload {model!r}: status={code} body={body[:200]!r}", flush=True)
    time.sleep(2)


def call(cmd: list[str]) -> int:
    print(" ".join(cmd), flush=True)
    return subprocess.call(cmd)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--base-url", default="http://127.0.0.1:8501/v1")
    ap.add_argument(
        "--steps",
        default="thinking,enforced,prompt_enforced",
        help="comma-separated: thinking, enforced, prompt_enforced",
    )
    ap.add_argument("--resume", action="store_true")
    ap.add_argument("--model-14b", default="qwen3-14b")
    ap.add_argument("--model-32b", default="qwen3", help="LocalAI id for 32B")
    args = ap.parse_args()
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    for step in [s.strip() for s in args.steps.split(",") if s.strip()]:
        if step == "thinking":
            # Free whatever is resident, then load 14B.
            for mid in ("qwen3", "qwen3-14b", "qwen2.5-7b-fc", "medgemma-4b-it",
                        "OpenBioLLM-Llama3-8B-Q5_K_M.gguf"):
                unload(args.base_url, mid)
            out = OUT_DIR / "qwen3-14b_consent_thinking_prompt.json"
            cmd = [
                str(PY), "-u", str(RUN),
                "--agent", "openai_compat",
                "--base-url", args.base_url,
                "--model", args.model_14b,
                "--temperature", "0",
                "--seed", "1",
                "--enable-thinking",
                "--cohort", "dev_pool",
                "--tasks", str(TASKS),
                "--policy-visibility", "prompt",
                "--consent-dependent-only",
                "--out", str(out),
            ]
            if args.resume:
                cmd.append("--resume")
            code = call(cmd)
            if code != 0:
                sys.exit(code)
            unload(args.base_url, args.model_14b)

        elif step in ("enforced", "prompt_enforced"):
            # Ensure 32B has VRAM (unload smaller models).
            for mid in ("qwen3-14b", "qwen2.5-7b-fc", "medgemma-4b-it",
                        "OpenBioLLM-Llama3-8B-Q5_K_M.gguf"):
                unload(args.base_url, mid)
            out = OUT_DIR / f"qwen3-32b_dev_{step}.json"
            cmd = [
                str(PY), "-u", str(RUN),
                "--agent", "openai_compat",
                "--base-url", args.base_url,
                "--model", args.model_32b,
                "--temperature", "0",
                "--seed", "1",
                "--disable-thinking",
                "--cohort", "dev_pool",
                "--tasks", str(TASKS),
                "--policy-visibility", step,
                "--include-perm",
                "--out", str(out),
            ]
            if args.resume:
                cmd.append("--resume")
            code = call(cmd)
            if code != 0:
                sys.exit(code)

        else:
            sys.exit(f"unknown step {step!r}")

    print("S16 runs complete", flush=True)


if __name__ == "__main__":
    main()
