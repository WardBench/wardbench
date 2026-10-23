#!/usr/bin/env python3
"""Build R14 biomedical models report (S13) and append rows to R6."""
from __future__ import annotations

import json
import pathlib
import sys
from datetime import date

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from wardbench.audit_metrics import consent_aware_perm_adjustment  # noqa: E402
from wardbench.stats import rate_with_n, wilson  # noqa: E402

V04 = ROOT / "results" / "v0.4"
OUT = (
    ROOT.parent.parent
    / "tracks"
    / "wardbench"
    / "reports"
    / "v0.4"
    / "R14_biomedical_models.md"
)
R6 = (
    ROOT.parent.parent
    / "tracks"
    / "wardbench"
    / "reports"
    / "v0.4"
    / "R6_multi_model.md"
)

BIO = [
    ("openbiollm-8b", "OpenBioLLM-8B (Llama-3)"),
    ("medgemma-4b-it", "MedGemma-4B-IT"),
]
REF = [
    ("qwen2.5-7b-fc", "prompt"),
    ("qwen3-14b", "prompt"),
    ("qwen3-32b", "prompt"),
]


def pct(r):
    if r != r:
        return "n/a"
    return f"{100 * r:.0f}%"


def fmt_pair(k, n):
    obj = rate_with_n(k, n)
    lo, hi = wilson(k, n)
    return f"{k}/{n}={pct(obj['rate'])} (Wilson {pct(lo)}–{pct(hi)})"


def agent_block(doc):
    for key, val in doc.items():
        if key != "meta" and isinstance(val, dict) and "tasks" in val:
            return val, doc.get("meta") or {}
    raise SystemExit("no agent block")


def load(stem, mode):
    path = V04 / f"{stem}_dev_{mode}.json"
    if not path.exists():
        return None
    block, meta = agent_block(json.loads(path.read_text()))
    counts = (block.get("aggregate") or {}).get("counts") or {}
    adj = consent_aware_perm_adjustment(block["tasks"])
    return {
        "stem": stem,
        "mode": mode,
        "path": path.name,
        "meta": meta,
        "utility": counts.get("utility") or [0, 0],
        "violation": counts.get("violation_rate") or [0, 0],
        "false_refusal": counts.get("false_refusal_proxy") or [0, 0],
        "capability": counts.get("denied_twin_capability") or [0, 0],
        "cond": counts.get("conditional_compliance") or [0, 0],
        "cap_ca": adj["denied_twin_capability_consent_aware"],
        "seconds": meta.get("seconds"),
        "tool_mode": meta.get("tool_mode"),
        "n_tasks": len(block["tasks"]),
    }


def main():
    rows = []
    for stem, _label in BIO:
        for mode in ("record", "prompt"):
            row = load(stem, mode)
            if row:
                rows.append(row)
    if len(rows) < 4:
        missing = [f"{s}_{m}" for s, _ in BIO for m in ("record", "prompt")
                   if not (V04 / f"{s}_dev_{m}.json").exists()]
        raise SystemExit(f"missing result files: {missing}")

    ref_rows = []
    for stem, mode in REF:
        r = load(stem, mode)
        if r:
            ref_rows.append(r)

    lines = [
        "# R14 — Biomedical GGUFs on LocalAI via `--tool-mode react_json` (S13)",
        "",
        f"_Generated {date.today().isoformat()}. Models: OpenBioLLM-Llama3-8B-Q5_K_M + medgemma-4b-it._ ",
        "",
        "## Design",
        "",
        "- Native OpenAI `tools=` fails on these GGUFs (grammar disabled / no tool template).",
        "- Ablation: `--tool-mode react_json` (schema in system prompt; parse JSON tool turns).",
        "- VRAM: `POST /backend/shutdown` before each model switch.",
        "- Modes: `record` + `prompt`, `--include-perm`, `temperature=0`, `seed=1`.",
        "- Compare vs Qwen local curve (7B-fc / 14B / 32B) from R6.",
        "",
        "## Headline (biomedical)",
        "",
        "| model | mode | utility | violation_rate | false_refusal | capability | cond. compliance | seconds |",
        "|---|---|---|---|---|---|---|---:|",
    ]
    for row in rows:
        lines.append(
            f"| {row['stem']} | {row['mode']} | {fmt_pair(*row['utility'])} | "
            f"{fmt_pair(*row['violation'])} | {fmt_pair(*row['false_refusal'])} | "
            f"{fmt_pair(*row['capability'])} | {fmt_pair(*row['cond'])} | {row['seconds']} |"
        )

    lines += [
        "",
        "## vs Qwen prompt baselines",
        "",
        "| model | utility | violation_rate |",
        "|---|---|---|",
    ]
    for r in ref_rows:
        lines.append(f"| {r['stem']} prompt | {fmt_pair(*r['utility'])} | {fmt_pair(*r['violation'])} |")
    for row in rows:
        if row["mode"] == "prompt":
            lines.append(
                f"| **{row['stem']} prompt (react_json)** | {fmt_pair(*row['utility'])} | "
                f"{fmt_pair(*row['violation'])} |"
            )

    # Verdict heuristics
    lines += ["", "## Verdict", ""]
    for stem, label in BIO:
        rec = next(r for r in rows if r["stem"] == stem and r["mode"] == "record")
        pr = next(r for r in rows if r["stem"] == stem and r["mode"] == "prompt")
        util_r = rate_with_n(*rec["utility"])["rate"]
        util_p = rate_with_n(*pr["utility"])["rate"]
        viol_r = rate_with_n(*rec["violation"])["rate"]
        viol_p = rate_with_n(*pr["violation"])["rate"]
        lines.append(
            f"- **{label}**: record util {fmt_pair(*rec['utility'])}, viol {fmt_pair(*rec['violation'])}; "
            f"prompt util {fmt_pair(*pr['utility'])}, viol {fmt_pair(*pr['violation'])} "
            f"(Δ util {100*(util_p-util_r):+.1f} pp, Δ viol {100*(viol_r-viol_p):+.1f} pp record−prompt)."
        )
        if util_p < 0.25:
            lines.append(
                f"  - Under-retrieval / tool-format floor likely (utility <25% under prompt); "
                f"domain pretraining alone does not unlock WardBench tool use."
            )
        elif util_p >= rate_with_n(*(next(r for r in ref_rows if r['stem']=='qwen3-14b')['utility']))["rate"]:
            lines.append("  - Matches or exceeds qwen3-14b prompt utility on this board.")
    lines += [
        "- `--tool-mode react_json` is sufficient to *run* both GGUFs end-to-end; "
        "whether domain models improve the Pareto frontier is read from the table above.",
        "- No grader retune. Next GPU queue: **S16** (32B factorial / thinking).",
        "",
        "## Files",
        "",
        "- `repos/wardbench/wardbench/agents.py` (`react_json`, `unload_localai_model`)",
        "- `repos/wardbench/scripts/run_v04_s13.py`",
        "- `repos/wardbench/results/v0.4/openbiollm-8b_dev_{record,prompt}.json`",
        "- `repos/wardbench/results/v0.4/medgemma-4b-it_dev_{record,prompt}.json`",
        "",
    ]
    OUT.write_text("\n".join(lines))
    print(f"wrote {OUT}")

    # Append R6 note if marker absent
    if R6.exists():
        text = R6.read_text()
        marker = "<!-- S13_biomedical -->"
        block = (
            "\n\n---\n\n"
            f"{marker}\n"
            "## Addendum — Biomedical GGUFs (S13 / `react_json`)\n\n"
            "See **`R14_biomedical_models.md`**. Local matrix expands Qwen → + OpenBioLLM-8B + MedGemma-4B-IT.\n\n"
            "| model | mode | utility | violation_rate | seconds |\n"
            "|---|---|---|---|---:|\n"
        )
        for row in rows:
            block += (
                f"| {row['stem']} | {row['mode']} (react_json) | "
                f"{fmt_pair(*row['utility'])} | {fmt_pair(*row['violation'])} | {row['seconds']} |\n"
            )
        if marker in text:
            # replace from marker to EOF-ish: keep prior, replace addendum
            text = text.split(marker)[0].rstrip() + "\n" + block.lstrip()
        else:
            text = text.rstrip() + "\n" + block
        R6.write_text(text if text.endswith("\n") else text + "\n")
        print(f"updated {R6}")


if __name__ == "__main__":
    main()
