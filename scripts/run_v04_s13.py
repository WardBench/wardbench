#!/usr/bin/env python3
"""S13: OpenBioLLM-8B + MedGemma-4B-IT via --tool-mode react_json (record+prompt).

Unloads the previous LocalAI model before each new GGUF. Does not start LocalAI.
Result stems: openbiollm-8b_dev_{mode}.json, medgemma-4b-it_dev_{mode}.json.
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

# LocalAI model id → result stem
MODELS = (
    ("OpenBioLLM-Llama3-8B-Q5_K_M.gguf", "openbiollm-8b"),
    ("medgemma-4b-it", "medgemma-4b-it"),
)


def unload(base_url: str, model: str) -> None:
    code, body = unload_localai_model(base_url, model)
    print(f"unload {model!r}: status={code} body={body[:200]!r}", flush=True)
    time.sleep(2)


def smoke_react(base_url: str, model: str) -> int:
    """One-shot chat without tools=; expect JSON tool call in content."""
    from openai import OpenAI
    from wardbench.agents import react_json_tool_prompt

    client = OpenAI(base_url=base_url, api_key="local")
    system = (
        "You are a FHIR tool agent.\n\n" + react_json_tool_prompt()
    )
    resp = client.chat.completions.create(
        model=model,
        temperature=0,
        max_tokens=300,
        messages=[
            {"role": "system", "content": system},
            {
                "role": "user",
                "content": "Call fhir_search for Patient pt-001. Do not answer in prose.",
            },
        ],
    )
    text = (resp.choices[0].message.content or "").strip()
    print(f"smoke {model}: {text[:240]!r}", flush=True)
    if "fhir_search" not in text and "Patient" not in text:
        print(f"smoke WARN: unexpected content from {model}", flush=True)
        return 1
    return 0


def run_one(model: str, stem: str, mode: str, *, base_url: str, resume: bool) -> int:
    out = OUT_DIR / f"{stem}_dev_{mode}.json"
    cmd = [
        str(PY), "-u", str(RUN),
        "--agent", "openai_compat",
        "--base-url", base_url,
        "--model", model,
        "--temperature", "0",
        "--seed", "1",
        "--disable-thinking",
        "--cohort", "dev_pool",
        "--tasks", str(TASKS),
        "--policy-visibility", mode,
        "--include-perm",
        "--tool-mode", "react_json",
        "--out", str(out),
    ]
    if resume:
        cmd.append("--resume")
    print(" ".join(cmd), flush=True)
    return subprocess.call(cmd)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--base-url", default="http://127.0.0.1:8501/v1")
    ap.add_argument("--modes", default="record,prompt")
    ap.add_argument(
        "--models",
        default="OpenBioLLM-Llama3-8B-Q5_K_M.gguf,medgemma-4b-it",
        help="comma-separated LocalAI ids (order preserved)",
    )
    ap.add_argument("--resume", action="store_true")
    ap.add_argument("--skip-smoke", action="store_true")
    ap.add_argument(
        "--unload-first",
        default="qwen3,qwen3-14b,qwen2.5-7b-fc",
        help="comma-separated models to shutdown before the first biomedical load",
    )
    args = ap.parse_args()
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    want = [m.strip() for m in args.models.split(",") if m.strip()]
    id_to_stem = dict(MODELS)
    for mid in want:
        if mid not in id_to_stem:
            # allow stem=id when already a stem-like id
            id_to_stem[mid] = mid.replace("/", "_").replace(":", "_")

    for mid in [m.strip() for m in args.unload_first.split(",") if m.strip()]:
        unload(args.base_url, mid)

    for model in want:
        stem = id_to_stem[model]
        unload(args.base_url, model)  # clear any partial load
        if not args.skip_smoke:
            code = smoke_react(args.base_url, model)
            if code != 0:
                print(f"smoke failed for {model}; continuing with full run", flush=True)
        for mode in [m.strip() for m in args.modes.split(",") if m.strip()]:
            if mode not in ("record", "prompt", "enforced", "prompt_enforced"):
                sys.exit(f"bad mode {mode!r}")
            code = run_one(model, stem, mode, base_url=args.base_url, resume=args.resume)
            if code != 0:
                sys.exit(code)
        # free VRAM before next biomedical model
        unload(args.base_url, model)
    print("S13 biomedical runs complete", flush=True)


if __name__ == "__main__":
    main()
