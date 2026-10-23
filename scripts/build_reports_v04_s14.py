#!/usr/bin/env python3
"""Build R15 FHIR API normalization ablation report (S14)."""
from __future__ import annotations

import json
import pathlib
import sys
from datetime import date

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from wardbench.stats import mcnemar_paired, rate_with_n, wilson  # noqa: E402

V04 = ROOT / "results" / "v0.4"
OUT = ROOT.parent.parent / "tracks" / "wardbench" / "reports" / "v0.4" / "R15_fhir_api_normalization_ablation.md"

PAIRS = [
    ("qwen3-14b", "qwen3-14b_dev_prompt.json", "qwen3-14b_dev_prompt_norm.json"),
    ("qwen2.5-7b-fc", "qwen2.5-7b-fc_dev_prompt.json", "qwen2.5-7b-fc_dev_prompt_norm.json"),
]


def pct(r):
    if r != r:
        return "n/a"
    return f"{100 * r:.1f}%"


def fmt(obj):
    lo, hi = obj.get("wilson95") or wilson(obj["k"], obj["n"])
    return f"{obj['k']}/{obj['n']}={pct(obj['rate'])} (Wilson {pct(lo)}–{pct(hi)})"


def agent_block(doc):
    for key, val in doc.items():
        if key != "meta" and isinstance(val, dict) and "tasks" in val:
            return val
    raise SystemExit("no agent block")


def load(path: pathlib.Path):
    if not path.exists():
        return None
    doc = json.loads(path.read_text())
    block = agent_block(doc)
    return block, doc.get("meta") or {}


def main_rows(block):
    return [r for r in block["tasks"] if not r.get("control") and not r.get("perm")]


def counts_from_agg(block):
    counts = (block.get("aggregate") or {}).get("counts") or {}
    return {
        "utility": rate_with_n(*(counts.get("utility") or [0, 0])),
        "violation_rate": rate_with_n(*(counts.get("violation_rate") or [0, 0])),
        "false_refusal": rate_with_n(*(counts.get("false_refusal_proxy") or [0, 0])),
        "capability": rate_with_n(*(counts.get("denied_twin_capability") or [0, 0])),
    }


def mcnemar_success(base_rows, norm_rows):
    by_b = {r["id"]: r for r in base_rows}
    by_n = {r["id"]: r for r in norm_rows}
    ids = [tid for tid in by_b if tid in by_n and by_b[tid].get("behavior") != "refuse"]
    b = c = 0
    for tid in ids:
        sb = bool(by_b[tid].get("success"))
        sn = bool(by_n[tid].get("success"))
        if sb and not sn:
            b += 1
        if sn and not sb:
            c += 1
    return mcnemar_paired(b, c), len(ids)


def bad_rtype_rate(rows):
    """Share of main tasks with a search/read of an unsupported neighbor type (pre-norm signal)."""
    neighbors = {
        "MedicationStatement", "MedicationOrder", "Encounter", "Composition", "DiagnosticOrder",
    }
    hits = 0
    for r in rows:
        types = {e.get("resource_type") for e in (r.get("tool_log") or [])}
        if types & neighbors:
            hits += 1
    return rate_with_n(hits, len(rows))


def main():
    lines = [
        "# R15 — FHIR API & schema normalization ablation (S14)",
        "",
        f"Date: {date.today().isoformat()}.",
        "",
        "Treatment: `--api-norm` on `prompt` (REFERENCE_DATE in system prompt, R4 "
        "`resource_type` enum + `status` in `TOOL_DEFS`, World normalizes `LOINC:`/`eq:`/"
        "`MedicationStatement`→`MedicationRequest` / Condition `clinical-status:active`→`status=active`). "
        "Baseline: saved `*_dev_prompt.json` without `--api-norm`. "
        "`--include-perm`, `temperature=0`, `seed=1`, `--disable-thinking`.",
        "",
        "## Headline",
        "",
        "| model | condition | utility | violation_rate | false_refusal | capability | seconds |",
        "|---|---|---|---|---|---|---:|",
    ]
    boards = []
    for stem, base_name, norm_name in PAIRS:
        base = load(V04 / base_name)
        norm = load(V04 / norm_name)
        if not base or not norm:
            lines.append(f"| {stem} | missing inputs | — | — | — | — | — |")
            continue
        base_block, base_meta = base
        norm_block, norm_meta = norm
        cb, cn = counts_from_agg(base_block), counts_from_agg(norm_block)
        lines.append(
            f"| {stem} | baseline prompt | {fmt(cb['utility'])} | {fmt(cb['violation_rate'])} | "
            f"{fmt(cb['false_refusal'])} | {fmt(cb['capability'])} | {base_meta.get('seconds')} |"
        )
        lines.append(
            f"| {stem} | **api-norm prompt** | {fmt(cn['utility'])} | {fmt(cn['violation_rate'])} | "
            f"{fmt(cn['false_refusal'])} | {fmt(cn['capability'])} | {norm_meta.get('seconds')} |"
        )
        mcn, n_nr = mcnemar_success(main_rows(base_block), main_rows(norm_block))
        boards.append({
            "stem": stem,
            "cb": cb, "cn": cn,
            "mcn": mcn, "n_nr": n_nr,
            "bad_base": bad_rtype_rate(main_rows(base_block)),
            "bad_norm": bad_rtype_rate(main_rows(norm_block)),
            "delta_util_pp": 100 * (cn["utility"]["rate"] - cb["utility"]["rate"]),
        })

    lines += ["", "## Paired utility McNemar (non-refuse main tasks)", ""]
    lines.append("| model | b (base only) | c (norm only) | p | Δ util (pp) |")
    lines.append("|---|---:|---:|---|---:|")
    for b in boards:
        lines.append(
            f"| {b['stem']} | {b['mcn']['b']} | {b['mcn']['c']} | {b['mcn']['p_approx']:.4g} | "
            f"{b['delta_util_pp']:+.1f} |"
        )

    lines += [
        "",
        "## Neighbor resource_type calls (tool_log)",
        "",
        "Count of main tasks whose tool log touched MedicationStatement/Order, Encounter, "
        "Composition, or DiagnosticOrder. Under `--api-norm` Medication* aliases are remapped "
        "before logging, so MedicationStatement hits should drop.",
        "",
        "| model | baseline bad_rtype | api-norm bad_rtype |",
        "|---|---|---|",
    ]
    for b in boards:
        lines.append(f"| {b['stem']} | {fmt(b['bad_base'])} | {fmt(b['bad_norm'])} |")

    lines += [
        "",
        "## Verdict",
        "",
    ]
    if boards:
        for b in boards:
            lines.append(
                f"- **{b['stem']}**: utility {fmt(b['cb']['utility'])} → {fmt(b['cn']['utility'])} "
                f"({b['delta_util_pp']:+.1f} pp); viol {fmt(b['cb']['violation_rate'])} → "
                f"{fmt(b['cn']['violation_rate'])}."
            )
    else:
        lines.append("- No completed norm runs yet.")
    lines += [
        "",
        "## Files",
        "",
        "- `repos/wardbench/wardbench/world.py` (`normalize_fhir_search`, `World.api_norm`)",
        "- `repos/wardbench/wardbench/agents.py` (`TOOL_DEFS_NORM`, `REFERENCE_DATE` in prompt)",
        "- `repos/wardbench/scripts/run.py` (`--api-norm`)",
        "- `repos/wardbench/scripts/run_v04_s14.py`",
        "- `repos/wardbench/results/v0.4/*_dev_prompt_norm.json`",
        "",
    ]
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    print(f"wrote {OUT}")
    for b in boards:
        print(b["stem"], f"{b['delta_util_pp']:+.1f} pp", "McNemar", b["mcn"])


if __name__ == "__main__":
    main()
