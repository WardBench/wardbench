#!/usr/bin/env python3
"""Build R17b: qwen3-32b prompt_enforced + --api-norm (S16b)."""
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
    / "R17b_32b_did_plus_api_norm.md"
)

PAIRS = [
    ("prompt (S10)", "qwen3-32b_dev_prompt.json"),
    ("prompt+api-norm (S14c)", "qwen3-32b_dev_prompt_norm.json"),
    ("prompt_enforced (S16)", "qwen3-32b_dev_prompt_enforced.json"),
    ("**prompt_enforced+api-norm (S16b)**", "qwen3-32b_dev_prompt_enforced_norm.json"),
]


def pct(r):
    if r != r:
        return "n/a"
    return f"{100 * r:.1f}%"


def fmt(k, n):
    obj = rate_with_n(k, n)
    lo, hi = wilson(k, n)
    return f"{k}/{n}={pct(obj['rate'])} (Wilson {pct(lo)}–{pct(hi)})"


def agent_block(doc):
    for key, val in doc.items():
        if key != "meta" and isinstance(val, dict) and "tasks" in val:
            return val, doc.get("meta") or {}
    raise SystemExit("no agent block")


def load(name):
    path = V04 / name
    if not path.exists():
        return None
    block, meta = agent_block(json.loads(path.read_text()))
    counts = (block.get("aggregate") or {}).get("counts") or {}
    return {
        "block": block,
        "meta": meta,
        "utility": counts.get("utility") or [0, 0],
        "violation": counts.get("violation_rate") or [0, 0],
        "false_refusal": counts.get("false_refusal_proxy") or [0, 0],
        "capability": counts.get("denied_twin_capability") or [0, 0],
        "consent_check": counts.get("consent_check_rate") or [0, 0],
        "seconds": meta.get("seconds"),
        "api_norm": meta.get("api_norm"),
    }


def main_rows(block):
    return [r for r in block["tasks"] if not r.get("control") and not r.get("perm")]


def mcnemar_success(a_rows, b_rows):
    by_a = {r["id"]: r for r in a_rows}
    by_b = {r["id"]: r for r in b_rows}
    ids = [i for i in by_a if i in by_b and by_a[i].get("behavior") != "refuse"]
    b = c = 0
    for i in ids:
        sa, sb = bool(by_a[i].get("success")), bool(by_b[i].get("success"))
        if sa and not sb:
            b += 1
        if sb and not sa:
            c += 1
    return mcnemar_paired(b, c), len(ids)


def mcnemar_viol(a_rows, b_rows):
    by_a = {r["id"]: r for r in a_rows}
    by_b = {r["id"]: r for r in b_rows}
    ids = [i for i in by_a if i in by_b]
    b = c = 0
    for i in ids:
        va, vb = bool(by_a[i].get("violations")), bool(by_b[i].get("violations"))
        if va and not vb:
            b += 1
        if vb and not va:
            c += 1
    return mcnemar_paired(b, c), len(ids)


def main():
    rows = []
    for label, name in PAIRS:
        r = load(name)
        if r is None:
            raise SystemExit(f"missing {name}")
        rows.append((label, r))

    pe = rows[2][1]
    pe_norm = rows[3][1]
    p_norm = rows[1][1]

    mc_u_pe, n_u = mcnemar_success(main_rows(pe["block"]), main_rows(pe_norm["block"]))
    mc_v_pe, n_v = mcnemar_viol(main_rows(pe["block"]), main_rows(pe_norm["block"]))
    mc_u_pn, _ = mcnemar_success(main_rows(p_norm["block"]), main_rows(pe_norm["block"]))
    mc_v_pn, _ = mcnemar_viol(main_rows(p_norm["block"]), main_rows(pe_norm["block"]))

    du_pe = 100 * (rate_with_n(*pe_norm["utility"])["rate"] - rate_with_n(*pe["utility"])["rate"])
    dv_pe = 100 * (rate_with_n(*pe_norm["violation"])["rate"] - rate_with_n(*pe["violation"])["rate"])
    du_pn = 100 * (rate_with_n(*pe_norm["utility"])["rate"] - rate_with_n(*p_norm["utility"])["rate"])
    dv_pn = 100 * (rate_with_n(*pe_norm["violation"])["rate"] - rate_with_n(*p_norm["violation"])["rate"])

    lines = [
        "# R17b — qwen3-32b `prompt_enforced` + `--api-norm` (S16b)",
        "",
        f"_Generated {date.today().isoformat()}. LocalAI id `qwen3` (32B Q4)._ ",
        "",
        "## Design",
        "",
        "- Stack schema normalization (`--api-norm`) on Defense-in-Depth (`prompt_enforced`).",
        "- Compare to S16 raw DiD and S14c `prompt`+`api-norm` (no gate).",
        "- `--include-perm`, `temperature=0`, `--disable-thinking`. No grader retune.",
        "",
        "## Headline",
        "",
        "| condition | utility | violation_rate | false_refusal | capability | consent_check | seconds |",
        "|---|---|---|---|---|---|---:|",
    ]
    for label, r in rows:
        lines.append(
            f"| {label} | {fmt(*r['utility'])} | {fmt(*r['violation'])} | "
            f"{fmt(*r['false_refusal'])} | {fmt(*r['capability'])} | "
            f"{fmt(*r['consent_check'])} | {r['seconds']} |"
        )

    lines += [
        "",
        "## Paired McNemar",
        "",
        f"| contrast | util $b$/$c$/$p$ | viol $b$/$c$/$p$ | Δ util (pp) | Δ viol (pp) |",
        f"|---|---|---|---:|---:|",
        f"| DiD → DiD+norm | {mc_u_pe['b']}/{mc_u_pe['c']}/{mc_u_pe['p_approx']:.4g} | "
        f"{mc_v_pe['b']}/{mc_v_pe['c']}/{mc_v_pe['p_approx']:.4g} | {du_pe:+.1f} | {dv_pe:+.1f} |",
        f"| prompt+norm → DiD+norm | {mc_u_pn['b']}/{mc_u_pn['c']}/{mc_u_pn['p_approx']:.4g} | "
        f"{mc_v_pn['b']}/{mc_v_pn['c']}/{mc_v_pn['p_approx']:.4g} | {du_pn:+.1f} | {dv_pn:+.1f} |",
        "",
        "## Verdict",
        "",
    ]
    if du_pe > 0 and mc_u_pe["p_approx"] < 0.05:
        lines.append(
            f"- **Schema adds util on top of DiD:** {fmt(*pe['utility'])} → {fmt(*pe_norm['utility'])} "
            f"({du_pe:+.1f} pp, $p\\approx{mc_u_pe['p_approx']:.4g}$)."
        )
    elif du_pe > 0:
        lines.append(
            f"- Directional util lift on DiD+norm ({du_pe:+.1f} pp) but McNemar ns "
            f"($p\\approx{mc_u_pe['p_approx']:.4g}$)."
        )
    else:
        lines.append(
            f"- No util gain from stacking api-norm on DiD (Δ {du_pe:+.1f} pp)."
        )
    lines.append(
        f"- Viol vs raw DiD: {fmt(*pe['violation'])} → {fmt(*pe_norm['violation'])} "
        f"({dv_pe:+.1f} pp)."
    )
    lines.append(
        f"- Vs S14c prompt+norm: util {fmt(*p_norm['utility'])} → {fmt(*pe_norm['utility'])} "
        f"({du_pn:+.1f} pp); viol {fmt(*p_norm['violation'])} → {fmt(*pe_norm['violation'])} "
        f"({dv_pn:+.1f} pp) — gate still the privacy lever when schema is fixed."
    )
    # Pareto note vs 14B DiD
    lines.append(
        "- Reference 14B `prompt_enforced` (R8): util 66/85, viol 2/120. "
        "Judge whether 32B DiD+norm closes that gap."
    )
    lines += [
        "- No grader retune. Local GPU queue → **S6b** (blocked on clinician review) unless residuals warrant another ablation.",
        "",
        "## Files",
        "",
        "- `repos/wardbench/scripts/run_v04_s16b.py`",
        "- `repos/wardbench/results/v0.4/qwen3-32b_dev_prompt_enforced_norm.json`",
        "",
    ]
    OUT.write_text("\n".join(lines))
    print(f"wrote {OUT}")
    print(
        f"DiD {pe['utility']} / {pe['violation']} -> "
        f"DiD+norm {pe_norm['utility']} / {pe_norm['violation']} "
        f"Δu={du_pe:+.1f} Δv={dv_pe:+.1f}"
    )


if __name__ == "__main__":
    main()
