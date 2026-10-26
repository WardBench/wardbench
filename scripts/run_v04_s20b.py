#!/usr/bin/env python3
"""S20b: DiD (± api-norm) on top-2 non-Qwen vendors from S20 ranking.

Default models: gemma4-31b, gpt-oss-20b (override with --models).
Per model, in order:
  1) prompt_enforced
  2) prompt_enforced + --api-norm

Uses S19 tool modes (react_json for gemma/phi/devstral; native for gpt-oss/glm/granite).
Does not start LocalAI. Unloads between models. Supports --resume.
Writes:
  results/v0.4/<id>_dev_prompt_enforced.json
  results/v0.4/<id>_dev_prompt_enforced_norm.json
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import time
from datetime import datetime, timezone
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
HQ_REP = ROOT.parent.parent / "tracks" / "wardbench" / "reports" / "v0.4"
DISK_LOG = HQ_REP / "vendor_disk_log.md"

DEFAULT_TOOL_MODE = {
    "gemma4-31b": "react_json",
    "gpt-oss-20b": "native",
    "phi4-14b": "react_json",
    "devstral-24b": "react_json",
    "glm47-flash": "native",
    "granite42-30b": "native",
}


def unload(base_url: str, model: str) -> None:
    code, body = unload_localai_model(base_url, model)
    print(f"unload {model!r}: status={code} body={body[:200]!r}", flush=True)
    time.sleep(2)


def avail_gb() -> str:
    try:
        out = subprocess.check_output(["df", "-BG", "/"], text=True).splitlines()[1]
        return out.split()[3].rstrip("G")
    except Exception:
        return "?"


def disk_line(action: str, model: str, note: str) -> None:
    DISK_LOG.parent.mkdir(parents=True, exist_ok=True)
    if not DISK_LOG.exists():
        DISK_LOG.write_text(
            "| ts | action | model | note | Avail_GB |\n|---|---|---|---|---:|\n",
            encoding="utf-8",
        )
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    with DISK_LOG.open("a", encoding="utf-8") as f:
        f.write(f"| {ts} | {action} | {model} | {note} | {avail_gb()} |\n")


def run_one(
    *,
    model: str,
    out: Path,
    base_url: str,
    tool_mode: str,
    api_norm: bool,
    resume: bool,
) -> int:
    out.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        str(PY), "-u", str(RUN),
        "--agent", "openai_compat",
        "--base-url", base_url,
        "--model", model,
        "--policy-visibility", "prompt_enforced",
        "--temperature", "0",
        "--seed", "1",
        "--disable-thinking",
        "--cohort", "dev_pool",
        "--include-perm",
        "--tool-mode", tool_mode,
        "--tasks", str(TASKS),
        "--out", str(out),
    ]
    if api_norm:
        cmd.append("--api-norm")
    if resume:
        cmd.append("--resume")
    print(" ".join(cmd), flush=True)
    return subprocess.call(cmd)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--models",
        default="gemma4-31b,gpt-oss-20b",
        help="comma-separated LocalAI ids (S20 top-2 non-Qwen default)",
    )
    ap.add_argument("--base-url", default="http://127.0.0.1:8501/v1")
    ap.add_argument("--resume", action="store_true")
    ap.add_argument(
        "--steps",
        default="did,did_norm",
        help="comma-separated: did (=prompt_enforced), did_norm (=+api-norm)",
    )
    args = ap.parse_args()
    steps = [s.strip() for s in args.steps.split(",") if s.strip()]
    for s in steps:
        if s not in ("did", "did_norm"):
            sys.exit(f"bad step {s!r}")

    models = [m.strip() for m in args.models.split(",") if m.strip()]
    disk_line("s20b_start", "—", f"models={','.join(models)} steps={','.join(steps)}")

    prev = None
    for model in models:
        tool_mode = DEFAULT_TOOL_MODE.get(model, "native")
        # Prefer status file from S19 if present
        tm_path = HQ_REP / f".s19_tool_mode_{model}"
        if tm_path.exists():
            raw = tm_path.read_text().strip()
            if raw.startswith("native"):
                tool_mode = "native"
            elif raw == "react_json":
                tool_mode = "react_json"

        if prev:
            unload(args.base_url, prev)
        unload(args.base_url, model)

        for step in steps:
            api_norm = step == "did_norm"
            suffix = "prompt_enforced_norm" if api_norm else "prompt_enforced"
            out = OUT_DIR / f"{model}_dev_{suffix}.json"
            label = f"{step}/{tool_mode}"
            disk_line("s20b_run_start", model, label)
            code = run_one(
                model=model,
                out=out,
                base_url=args.base_url,
                tool_mode=tool_mode,
                api_norm=api_norm,
                resume=args.resume,
            )
            if code != 0:
                disk_line("s20b_run_fail", model, f"{label} exit={code}")
                sys.exit(code)
            disk_line("s20b_run_done", model, f"{label} -> {out.name}")
            status = HQ_REP / f".s20b_status_{model}_{step}"
            status.write_text("ok\n", encoding="utf-8")

        prev = model

    if prev:
        unload(args.base_url, prev)
    disk_line("s20b_queue_complete", "—", "all requested steps done")
    print("S20B_DONE", flush=True)


if __name__ == "__main__":
    main()
