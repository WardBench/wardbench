#!/usr/bin/env python3
"""Build R15c: full qwen3-32b --api-norm vs baseline prompt (S14c)."""
from __future__ import annotations

import json
import pathlib
import sys
from datetime import date

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from wardbench.stats import mcnemar_paired, rate_with_n, wilson  # noqa: E402

V04 = ROOT / "results" / "v0.4"
OUT = (
    ROOT.parent.parent
    / "tracks"
    / "wardbench"
    / "reports"
    / "v0.4"
    / "R15c_32b_api_norm_full.md"
)

BASE = V04 / "qwen3-32b_dev_prompt.json"
NORM = V04 / "qwen3-32b_dev_prompt_norm.json"
# S14 reference deltas (from R15)
S14_REF = {
    "qwen3-14b": {"delta_util_pp": 3.5, "mcnemar_p": 0.629},
    "qwen2.5-7b-fc": {"delta_util_pp": 9.4, "mcnemar_p": 0.03857},
}
# R10 prompt utility (approx from board): 14B 53/85, 32B 47/85
R10_PROMPT_UTIL = {"14b": (53, 85), "32b": (47, 85)}

TARGET_S14B = [
    "WB-A-006", "WB-A-008", "WB-A-010", "WB-A-012", "WB-A-025",
    "WB-ADV-002", "WB-ADV-004", "WB-ADV-010", "WB-ADV-015", "WB-ADV-023",
    "WB-B-003", "WB-B-021",
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
    doc = json.loads(path.read_text())
    return agent_block(doc), doc.get("meta") or {}


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
    neighbors = {
        "MedicationStatement", "MedicationOrder", "Encounter", "Composition", "DiagnosticOrder",
    }
    hits = 0
    for r in rows:
        types = {e.get("resource_type") for e in (r.get("tool_log") or [])}
        if types & neighbors:
            hits += 1
    return rate_with_n(hits, len(rows))


def panel_success(by_id, ids):
    k = sum(1 for i in ids if bool(by_id[i].get("success")))
    return rate_with_n(k, len(ids))


def main():
    if not NORM.exists():
        raise SystemExit(f"missing {NORM}")
    base_block, base_meta = load(BASE)
    norm_block, norm_meta = load(NORM)
    cb, cn = counts_from_agg(base_block), counts_from_agg(norm_block)
    mcn, n_nr = mcnemar_success(main_rows(base_block), main_rows(norm_block))
    delta_util = 100 * (cn["utility"]["rate"] - cb["utility"]["rate"])
    delta_viol = 100 * (cn["violation_rate"]["rate"] - cb["violation_rate"]["rate"])
    bad_b = bad_rtype_rate(main_rows(base_block))
    bad_n = bad_rtype_rate(main_rows(norm_block))

    by_b = {r["id"]: r for r in base_block["tasks"]}
    by_n = {r["id"]: r for r in norm_block["tasks"]}
    panel_b = panel_success(by_b, TARGET_S14B)
    panel_n = panel_success(by_n, TARGET_S14B)

    # Scale gap closed? Compare norm 32B util to R10 14B prompt util
    util_14 = rate_with_n(*R10_PROMPT_UTIL["14b"])
    gap_base = 100 * (util_14["rate"] - cb["utility"]["rate"])
    gap_norm = 100 * (util_14["rate"] - cn["utility"]["rate"])

    lines = [
        "# R15c — Full qwen3-32b `--api-norm` vs baseline prompt (S14c)",
        "",
        f"_Generated {date.today().isoformat()}. LocalAI model id `qwen3` (32B Q4)._ ",
        "",
        "## Design",
        "",
        "- Baseline: `qwen3-32b_dev_prompt.json` (prompt, no `--api-norm`, include-perm).",
        "- Ablation: `qwen3-32b_dev_prompt_norm.json` (same, `--api-norm`).",
        "- Paired McNemar on non-refuse main tasks. No grader retune.",
        "- Context: S14b panel was 0→11/12; R10 reported non-monotonic util 14B→32B under prompt.",
        "",
        "## Headline",
        "",
        "| condition | utility | violation_rate | false_refusal | capability | seconds |",
        "|---|---|---|---|---|---:|",
        f"| baseline prompt | {fmt(cb['utility'])} | {fmt(cb['violation_rate'])} | "
        f"{fmt(cb['false_refusal'])} | {fmt(cb['capability'])} | {base_meta.get('seconds')} |",
        f"| **api-norm prompt** | {fmt(cn['utility'])} | {fmt(cn['violation_rate'])} | "
        f"{fmt(cn['false_refusal'])} | {fmt(cn['capability'])} | {norm_meta.get('seconds')} |",
        f"| Δ | **{delta_util:+.1f} pp** | **{delta_viol:+.1f} pp** | — | — | — |",
        "",
        f"McNemar utility (non-refuse main, n={n_nr}): "
        f"**$b={mcn['b']}$, $c={mcn['c']}$, $p\\approx{mcn['p_approx']:.4g}$**.",
        "",
        "## Neighbor resource_type (main tasks)",
        "",
        f"| baseline bad_rtype | api-norm bad_rtype |",
        f"|---|---|",
        f"| {fmt(bad_b)} | {fmt(bad_n)} |",
        "",
        "## S14b panel (12 schema-flagged ids) under full run",
        "",
        f"| baseline | api-norm |",
        f"|---|---|",
        f"| {fmt(panel_b)} | {fmt(panel_n)} |",
        "",
        "## vs S14 (14B / 7B) and R10 scale gap",
        "",
        f"| comparison | value |",
        f"|---|---|",
        f"| S14 qwen3-14b Δ util | {S14_REF['qwen3-14b']['delta_util_pp']:+.1f} pp (ns) |",
        f"| S14 qwen2.5-7b-fc Δ util | {S14_REF['qwen2.5-7b-fc']['delta_util_pp']:+.1f} pp |",
        f"| **S14c qwen3-32b Δ util** | **{delta_util:+.1f} pp** |",
        f"| R10 prompt util gap 14B−32B (baseline) | {gap_base:+.1f} pp "
        f"({R10_PROMPT_UTIL['14b'][0]}/{R10_PROMPT_UTIL['14b'][1]} − "
        f"{cb['utility']['k']}/{cb['utility']['n']}) |",
        f"| Same gap after 32B api-norm | {gap_norm:+.1f} pp "
        f"(14B {R10_PROMPT_UTIL['14b'][0]}/{R10_PROMPT_UTIL['14b'][1]} − "
        f"32B-norm {cn['utility']['k']}/{cn['utility']['n']}) |",
        "",
        "## Verdict",
        "",
    ]
    if delta_util > 0 and mcn["p_approx"] < 0.05:
        lines.append(
            f"- **Full-dev schema lift on 32B is significant:** util {fmt(cb['utility'])} → "
            f"{fmt(cn['utility'])} ({delta_util:+.1f} pp, McNemar $p\\approx{mcn['p_approx']:.4g}$)."
        )
    elif delta_util > 0:
        lines.append(
            f"- **Directional util lift** {delta_util:+.1f} pp but McNemar ns "
            f"($p\\approx{mcn['p_approx']:.4g}$)."
        )
    else:
        lines.append(
            f"- **No util gain** (Δ {delta_util:+.1f} pp, $p\\approx{mcn['p_approx']:.4g}$)."
        )
    lines.append(
        f"- Violations {fmt(cb['violation_rate'])} → {fmt(cn['violation_rate'])} "
        f"({delta_viol:+.1f} pp); capability {fmt(cb['capability'])} → {fmt(cn['capability'])}."
    )
    if gap_norm <= 0:
        lines.append(
            "- After `--api-norm`, 32B prompt util **meets or exceeds** R10 14B prompt util — "
            "the R10 scale regression is largely explained by schema friction under Q4 tool use."
        )
    elif gap_norm < gap_base:
        lines.append(
            f"- Scale gap vs 14B shrinks from {gap_base:.1f} → {gap_norm:.1f} pp under `--api-norm`, "
            "but a residual gap remains (not fully schema)."
        )
    else:
        lines.append(
            "- Scale gap vs 14B does not shrink under `--api-norm`; other causes dominate."
        )
    lines += [
        "- No grader change. Next GPU queue: **S13** (biomedical) or **S16** (32B factorial / thinking).",
        "",
        "## Files",
        "",
        "- `repos/wardbench/scripts/run_v04_s14c.py`",
        "- `repos/wardbench/results/v0.4/qwen3-32b_dev_prompt_norm.json`",
        "- `tracks/wardbench/reports/v0.4/R15b_32b_api_norm_targeted.md` (panel precursor)",
        "",
    ]
    OUT.write_text("\n".join(lines))
    print(f"wrote {OUT}")
    print(
        f"util {cb['utility']['k']}/{cb['utility']['n']} -> "
        f"{cn['utility']['k']}/{cn['utility']['n']} "
        f"Δ={delta_util:+.1f}pp mcnemar b={mcn['b']} c={mcn['c']} p={mcn['p_approx']:.4g}"
    )


if __name__ == "__main__":
    main()
