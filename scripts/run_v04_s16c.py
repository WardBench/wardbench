#!/usr/bin/env python3
"""S16c: Targeted qwen3-32b / prompt_enforced / --api-norm / --strict-redaction-prompt.

Runs LocalAI `qwen3` (32B Q4) on the 6 de-identified research / exfil tasks
(including the 2 residual birthDate violators from S16b: WB-ADV-030 and WB-B-022,
plus WB-B-008, WB-B-020, WB-B-025, WB-ADV-001, WB-ADV-007) to test whether
stacking `--strict-redaction-prompt` v2 on top of `32B + prompt_enforced + --api-norm`
drives the residual 2/120 violations to 0/120.
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
OUT = ROOT / "results" / "v0.4" / "qwen3-32b_did_norm_strict_redaction.json"

# All 6 de-identified research + adv_exfil_deid tasks (includes the 2 S16b residual
# violators WB-ADV-030 and WB-B-022, plus the other 4 deid age/birthDate tasks).
TARGET_IDS = (
    "WB-ADV-001",
    "WB-ADV-007",
    "WB-ADV-030",
    "WB-B-008",
    "WB-B-020",
    "WB-B-022",
    "WB-B-025",
)


def unload(base_url: str, model: str) -> None:
    code, body = unload_localai_model(base_url, model)
    print(f"unload {model!r}: status={code} body={body[:200]!r}", flush=True)
    time.sleep(1)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--base-url", default="http://127.0.0.1:8501/v1")
    ap.add_argument("--model", default="qwen3", help="LocalAI model id for 32B")
    ap.add_argument("--resume", action="store_true")
    args = ap.parse_args()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    for mid in ("qwen3-14b", "qwen2.5-7b-fc", "medgemma-4b-it", "OpenBioLLM-Llama3-8B-Q5_K_M.gguf"):
        unload(args.base_url, mid)
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
        "--policy-visibility", "prompt_enforced",
        "--api-norm",
        "--strict-redaction-prompt",
        "--task-ids", ",".join(TARGET_IDS),
        "--out", str(OUT),
    ]
    if args.resume:
        cmd.append("--resume")
    print(" ".join(cmd), flush=True)
    raise SystemExit(subprocess.call(cmd))


if __name__ == "__main__":
    main()
