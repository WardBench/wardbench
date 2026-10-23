#!/usr/bin/env python3
"""Build R15b: targeted qwen3-32b --api-norm on 12 schema-flagged fails (S14b)."""
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
    / "R15b_32b_api_norm_targeted.md"
)

TARGET_IDS = [
    "WB-A-006",
    "WB-A-008",
    "WB-A-010",
    "WB-A-012",
    "WB-A-025",
    "WB-ADV-002",
    "WB-ADV-004",
    "WB-ADV-010",
    "WB-ADV-015",
    "WB-ADV-023",
    "WB-B-003",
    "WB-B-021",
]

BASE = V04 / "qwen3-32b_dev_prompt.json"
NORM = V04 / "qwen3-32b_dev_prompt_norm_targeted.json"


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


def by_id(path: pathlib.Path):
    doc = json.loads(path.read_text())
    block = agent_block(doc)
    return {r["id"]: r for r in block["tasks"]}, doc.get("meta") or {}


def success_of(row):
    return bool(row.get("success"))


def main():
    base, base_meta = by_id(BASE)
    norm, norm_meta = by_id(NORM)
    missing_b = [i for i in TARGET_IDS if i not in base]
    missing_n = [i for i in TARGET_IDS if i not in norm]
    if missing_b or missing_n:
        raise SystemExit(f"missing ids base={missing_b} norm={missing_n}")

    k_b = sum(1 for i in TARGET_IDS if success_of(base[i]))
    k_n = sum(1 for i in TARGET_IDS if success_of(norm[i]))
    util_b = rate_with_n(k_b, len(TARGET_IDS))
    util_n = rate_with_n(k_n, len(TARGET_IDS))

    b = c = 0
    flips = []
    for tid in TARGET_IDS:
        sb, sn = success_of(base[tid]), success_of(norm[tid])
        if sb and not sn:
            b += 1
            flips.append((tid, "win→lose"))
        elif sn and not sb:
            c += 1
            flips.append((tid, "lose→win"))
        elif sb == sn:
            flips.append((tid, "same_ok" if sb else "same_fail"))
    mc = mcnemar_paired(b, c)

    lines = [
        "# R15b — Targeted qwen3-32b `--api-norm` on 12 schema-flagged fails (S14b)",
        "",
        f"_Generated {date.today().isoformat()}. Offline recoverable set from R15; LocalAI model id `qwen3` (32B Q4)._ ",
        "",
        "## Design",
        "",
        "- Baseline: `results/v0.4/qwen3-32b_dev_prompt.json` (full `prompt`, no `--api-norm`).",
        "- Ablation: `results/v0.4/qwen3-32b_dev_prompt_norm_targeted.json` — same 12 ids, `--api-norm`, `temperature=0`, `--disable-thinking`.",
        "- No grader retune. McNemar on the fixed 12-id panel only (not extrapolated to full utility).",
        "",
        "## Headline",
        "",
        f"| Condition | Success on 12 ids |",
        f"|---|---|",
        f"| baseline prompt | {fmt(util_b)} |",
        f"| **api-norm prompt (targeted)** | {fmt(util_n)} |",
        f"| Δ | **{100 * (util_n['rate'] - util_b['rate']):+.1f} pp** |",
        "",
        f"McNemar (baseline success → norm fail = $b$, norm success → baseline fail = $c$): "
        f"**$b={b}$, $c={c}$, $p\\approx{mc['p_approx']:.4g}$**.",
        "",
        "## Per-id flips",
        "",
        "| task_id | baseline success | norm success | flip | baseline missing (head) | norm missing (head) |",
        "|---|---|---|---|---|---|",
    ]
    for tid, flip in flips:
        rb, rn = base[tid], norm[tid]
        mb = (rb.get("missing") or [])[:2]
        mn = (rn.get("missing") or [])[:2]
        lines.append(
            f"| `{tid}` | {success_of(rb)} | {success_of(rn)} | {flip} | "
            f"{mb!s} | {mn!s} |"
        )

    lines += [
        "",
        "## Meta",
        "",
        f"- Baseline seconds (full run): `{base_meta.get('seconds')}`",
        f"- Targeted norm seconds: `{norm_meta.get('seconds')}`",
        f"- `api_norm` flag on ablation meta: `{norm_meta.get('api_norm')}`",
        "",
        "## Verdict",
        "",
    ]
    p = mc["p_approx"]
    if k_n > k_b and p < 0.05:
        lines.append(
            f"- **Schema friction recoverable on 32B at this panel:** {k_b}→{k_n}/12 "
            f"(McNemar $p\\approx{p:.4g}$). Offline R15 preview was directionally correct."
        )
    elif k_n > k_b:
        lines.append(
            f"- **Directional recovery** {k_b}→{k_n}/12 but McNemar ns "
            f"($p\\approx{p:.4g}$); do not claim scale-regression explained."
        )
    elif k_n == k_b:
        lines.append(
            f"- **No net success change** on the 12-id panel ({k_b}/12). "
            "Neighbor-rtype / code-prefix friction is not the binding constraint for these fails under 32B `prompt`."
        )
    else:
        lines.append(
            f"- **Net regression** {k_b}→{k_n}/12 under `--api-norm` on this panel "
            f"($b={b},c={c},p\\approx{p:.4g}$)."
        )
    residual = [tid for tid, flip in flips if flip == "same_fail"]
    if residual:
        lines.append(
            f"- Residual fail(s) `{', '.join(residual)}`: inspect violations/missing — "
            "likely not pure schema (disclosure / omission)."
        )
    lines.append(
        "- Panel recovery ≠ full-dev utility lift: add **S14c** (full `qwen3-32b` / `prompt` / `--api-norm`) "
        "before attributing the 14B→32B scale regression to schema alone."
    )
    lines.append("- No grader change. Next GPU queue after S14c (or if deferred): **S13** / **S16**.")
    lines.append("")
    OUT.write_text("\n".join(lines))
    print(f"wrote {OUT}")
    print(
        f"success {k_b}/{len(TARGET_IDS)} -> {k_n}/{len(TARGET_IDS)} "
        f"mcnemar b={b} c={c} p={mc['p_approx']:.4g}"
    )


if __name__ == "__main__":
    main()
