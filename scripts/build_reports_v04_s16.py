#!/usr/bin/env python3
"""Build R17: qwen3-32b 2x2 factorial + 14B thinking ablation (S16)."""
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
    / "R17_32b_factorial_and_thinking.md"
)

# 14B factorial reference (R8)
R8_14B = {
    "record": {"utility": (56, 85), "violation": (52, 120)},
    "prompt": {"utility": (53, 85), "violation": (26, 120)},
    "enforced": {"utility": (64, 85), "violation": (5, 120)},  # verify from R8
    "prompt_enforced": {"utility": (66, 85), "violation": (2, 120)},
}


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


def load(path: pathlib.Path):
    if not path.exists():
        return None
    block, meta = agent_block(json.loads(path.read_text()))
    counts = (block.get("aggregate") or {}).get("counts") or {}
    return {
        "block": block,
        "meta": meta,
        "utility": counts.get("utility") or [0, 0],
        "violation": counts.get("violation_rate") or [0, 0],
        "access": counts.get("access_violation_rate") or [0, 0],
        "action": counts.get("action_violation_rate") or [0, 0],
        "disclosure": counts.get("disclosure_violation_rate") or [0, 0],
        "capability": counts.get("denied_twin_capability") or [0, 0],
        "cond": counts.get("conditional_compliance") or [0, 0],
        "consent_check": counts.get("consent_check_rate") or [0, 0],
        "false_refusal": counts.get("false_refusal_proxy") or [0, 0],
        "seconds": meta.get("seconds"),
    }


def subset_by_ids(block, ids):
    by = {r["id"]: r for r in block["tasks"]}
    return [by[i] for i in ids if i in by]


def rates_from_rows(rows, *, utility_nonrefuse=True):
    main = [r for r in rows if not r.get("control") and not r.get("perm")]
    viol_k = sum(1 for r in main if r.get("violations"))
    if utility_nonrefuse:
        util_rows = [r for r in main if r.get("behavior") != "refuse"]
    else:
        util_rows = main
    util_k = sum(1 for r in util_rows if r.get("success"))
    consent_k = sum(1 for r in main if r.get("checked_consent"))
    rwd = sum(1 for r in main if r.get("refusal_with_disclosure"))
    return {
        "utility": (util_k, len(util_rows)),
        "violation": (viol_k, len(main)),
        "consent_check": (consent_k, len(main)),
        "refusal_with_disclosure": (rwd, len(main)),
        "n_main": len(main),
    }


def mcnemar_flag(rows_a, rows_b, pred):
    by_a = {r["id"]: r for r in rows_a}
    by_b = {r["id"]: r for r in rows_b}
    ids = [i for i in by_a if i in by_b]
    b = c = 0
    for i in ids:
        pa, pb = bool(pred(by_a[i])), bool(pred(by_b[i]))
        if pa and not pb:
            b += 1
        if pb and not pa:
            c += 1
    return mcnemar_paired(b, c), len(ids)


def main():
    # Patch R8 enforced from file if present
    e14 = load(V04 / "qwen3-14b_dev_enforced.json")
    if e14:
        R8_14B["enforced"] = {
            "utility": tuple(e14["utility"]),
            "violation": tuple(e14["violation"]),
        }
    pe14 = load(V04 / "qwen3-14b_dev_prompt_enforced.json")
    if pe14:
        R8_14B["prompt_enforced"] = {
            "utility": tuple(pe14["utility"]),
            "violation": tuple(pe14["violation"]),
        }

    cells_32 = {}
    for mode in ("record", "prompt", "enforced", "prompt_enforced"):
        row = load(V04 / f"qwen3-32b_dev_{mode}.json")
        if row:
            cells_32[mode] = row

    missing = [m for m in ("enforced", "prompt_enforced") if m not in cells_32]
    if missing:
        raise SystemExit(f"missing 32B factorial cells: {missing}")

    # Thinking ablation
    think = load(V04 / "qwen3-14b_consent_thinking_prompt.json")
    base14 = load(V04 / "qwen3-14b_dev_prompt.json")
    if not think or not base14:
        raise SystemExit("missing thinking ablation inputs")

    think_ids = [r["id"] for r in think["block"]["tasks"]]
    base_rows = subset_by_ids(base14["block"], think_ids)
    think_rows = think["block"]["tasks"]
    base_r = rates_from_rows(base_rows)
    think_r = rates_from_rows(think_rows)
    mc_viol, _ = mcnemar_flag(
        base_rows, think_rows, lambda r: bool(r.get("violations")),
    )
    mc_consent, _ = mcnemar_flag(
        base_rows, think_rows, lambda r: bool(r.get("checked_consent")),
    )
    mc_util, _ = mcnemar_flag(
        [r for r in base_rows if r.get("behavior") != "refuse"],
        [r for r in think_rows if r.get("behavior") != "refuse"],
        lambda r: bool(r.get("success")),
    )

    lines = [
        "# R17 — qwen3-32b $2\\times2$ factorial + 14B thinking ablation (S16)",
        "",
        f"_Generated {date.today().isoformat()}. LocalAI 32B id `qwen3` (Q4); thinking on `qwen3-14b`._ ",
        "",
        "## A. Policy factorial on qwen3-32b",
        "",
        "Cells `record`/`prompt` from S10; `enforced`/`prompt_enforced` from S16 "
        "(`--disable-thinking`, `--include-perm`, no `--api-norm` — parity with S10).",
        "",
        "| cell | policy in prompt | server gate | utility | violation_rate | access | disclosure | capability | consent_check | seconds |",
        "|---|---|---|---|---|---|---|---|---|---:|",
    ]
    labels = {
        "record": (False, False),
        "prompt": (True, False),
        "enforced": (False, True),
        "prompt_enforced": (True, True),
    }
    for mode, (pol, gate) in labels.items():
        if mode not in cells_32:
            continue
        r = cells_32[mode]
        lines.append(
            f"| `{mode}` | {'yes' if pol else 'no'} | {'yes' if gate else 'no'} | "
            f"{fmt(*r['utility'])} | {fmt(*r['violation'])} | {fmt(*r['access'])} | "
            f"{fmt(*r['disclosure'])} | {fmt(*r['capability'])} | {fmt(*r['consent_check'])} | "
            f"{r['seconds']} |"
        )

    # McNemar prompt vs prompt_enforced on 32B
    if "prompt" in cells_32 and "prompt_enforced" in cells_32:
        p_rows = [r for r in cells_32["prompt"]["block"]["tasks"]
                  if not r.get("control") and not r.get("perm")]
        pe_rows = [r for r in cells_32["prompt_enforced"]["block"]["tasks"]
                   if not r.get("control") and not r.get("perm")]
        mc_v, n = mcnemar_flag(p_rows, pe_rows, lambda r: bool(r.get("violations")))
        lines += [
            "",
            f"McNemar violations (`prompt` vs `prompt_enforced`, n={n}): "
            f"$b={mc_v['b']}$ (only prompt), $c={mc_v['c']}$ (only prompt_enforced), "
            f"$p\\approx{mc_v['p_approx']:.4g}$.",
        ]

    lines += [
        "",
        "### vs qwen3-14b factorial (R8)",
        "",
        "| cell | 14B util | 14B viol | 32B util | 32B viol |",
        "|---|---|---|---|---|",
    ]
    for mode in ("record", "prompt", "enforced", "prompt_enforced"):
        u14, v14 = R8_14B[mode]["utility"], R8_14B[mode]["violation"]
        if mode in cells_32:
            u32, v32 = cells_32[mode]["utility"], cells_32[mode]["violation"]
            lines.append(
                f"| `{mode}` | {fmt(*u14)} | {fmt(*v14)} | {fmt(*u32)} | {fmt(*v32)} |"
            )

    lines += [
        "",
        "## B. Thinking-mode ablation (`qwen3-14b` / `prompt` / 30 Consent-dependent)",
        "",
        "Baseline: same 30 ids sliced from `qwen3-14b_dev_prompt.json` (`--disable-thinking`). "
        "Ablation: `qwen3-14b_consent_thinking_prompt.json` (`--enable-thinking`, `max_tokens=8000`).",
        "",
        "| condition | utility (non-refuse) | violation_rate | consent_check | refusal_with_disclosure |",
        "|---|---|---|---|---|",
        f"| disable-thinking | {fmt(*base_r['utility'])} | {fmt(*base_r['violation'])} | "
        f"{fmt(*base_r['consent_check'])} | {fmt(*base_r['refusal_with_disclosure'])} |",
        f"| **enable-thinking** | {fmt(*think_r['utility'])} | {fmt(*think_r['violation'])} | "
        f"{fmt(*think_r['consent_check'])} | {fmt(*think_r['refusal_with_disclosure'])} |",
        "",
        f"McNemar violations: $b={mc_viol['b']}$, $c={mc_viol['c']}$, $p\\approx{mc_viol['p_approx']:.4g}$.",
        f"McNemar consent_check: $b={mc_consent['b']}$, $c={mc_consent['c']}$, "
        f"$p\\approx{mc_consent['p_approx']:.4g}$.",
        f"McNemar utility: $b={mc_util['b']}$, $c={mc_util['c']}$, $p\\approx{mc_util['p_approx']:.4g}$.",
        "",
        "## Verdict",
        "",
    ]

    pe = cells_32.get("prompt_enforced")
    pr = cells_32.get("prompt")
    if pe and pr:
        dv = 100 * (rate_with_n(*pr["violation"])["rate"] - rate_with_n(*pe["violation"])["rate"])
        du = 100 * (rate_with_n(*pe["utility"])["rate"] - rate_with_n(*pr["utility"])["rate"])
        lines.append(
            f"- **32B Defense-in-Depth:** prompt_enforced vs prompt — viol Δ {dv:+.1f} pp, "
            f"util Δ {du:+.1f} pp. Compare to 14B R8 (viol 21.7%→1.7%, util 62.4%→77.6%)."
        )
        if rate_with_n(*pe["violation"])["rate"] <= 0.05:
            lines.append(
                "- Low absolute viol under `prompt_enforced` on 32B supports **scale-invariant DiD**, "
                "not a 14B quirk."
            )
        else:
            lines.append(
                "- Residual viol under 32B `prompt_enforced` is higher than 14B’s 1.7% — "
                "DiD helps but is not identically tight at Q4 32B."
            )

    d_consent = think_r["consent_check"][0] - base_r["consent_check"][0]
    d_viol = think_r["violation"][0] - base_r["violation"][0]
    if d_consent > 0 and mc_consent["p_approx"] < 0.05:
        lines.append(
            f"- **Thinking helps Consent prefetch:** consent_check "
            f"{fmt(*base_r['consent_check'])} → {fmt(*think_r['consent_check'])} "
            f"(McNemar $p\\approx{mc_consent['p_approx']:.4g}$)."
        )
    elif d_consent > 0:
        lines.append(
            f"- Thinking raises consent_check directionally ({base_r['consent_check'][0]}→"
            f"{think_r['consent_check'][0]}/30) but McNemar ns."
        )
    else:
        lines.append(
            "- **Thinking does not unlock Consent lookup** on this 30-task panel "
            f"(consent_check {base_r['consent_check'][0]}→{think_r['consent_check'][0]}/30)."
        )
    lines.append(
        f"- Thinking viol {base_r['violation'][0]}→{think_r['violation'][0]}/30 "
        f"(Δ {d_viol:+d}); util {base_r['utility'][0]}→{think_r['utility'][0]}."
    )
    lines += [
        "- No grader retune. Active local GPU queue cleared aside from **S6b** (blocked on review).",
        "",
        "## Files",
        "",
        "- `repos/wardbench/results/v0.4/qwen3-32b_dev_{enforced,prompt_enforced}.json`",
        "- `repos/wardbench/results/v0.4/qwen3-14b_consent_thinking_prompt.json`",
        "- `repos/wardbench/scripts/run_v04_s16.py`",
        "",
    ]
    OUT.write_text("\n".join(lines))
    print(f"wrote {OUT}")
    for mode, r in cells_32.items():
        print(mode, "util", r["utility"], "viol", r["violation"])
    print(
        "thinking consent", base_r["consent_check"], "->", think_r["consent_check"],
        "viol", base_r["violation"], "->", think_r["violation"],
    )


if __name__ == "__main__":
    main()
