#!/usr/bin/env python3
"""Build tracks/wardbench/reports/v0.4/R6_multi_model.md from results/v0.4/*_dev_{record,prompt}.json."""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from wardbench.audit_metrics import (  # noqa: E402
    consent_aware_perm_adjustment,
    injection_exposure_metrics,
)
from wardbench.stats import rate_with_n, wilson  # noqa: E402

V04 = ROOT / "results" / "v0.4"
TASKS = ROOT / "tasks" / "dev.jsonl"


def _default_out() -> pathlib.Path:
    return ROOT.parent.parent / "tracks" / "wardbench" / "reports" / "v0.4" / "R6_multi_model.md"


def pct(r):
    if r != r:
        return "n/a"
    return f"{100 * r:.0f}%"


def fmt(obj):
    lo, hi = obj.get("wilson95") or wilson(obj["k"], obj["n"])
    return f"{obj['k']}/{obj['n']}={pct(obj['rate'])} (Wilson {pct(lo)}–{pct(hi)})"


def agent_block(doc):
    for key, val in doc.items():
        if key != "meta" and isinstance(val, dict) and "tasks" in val:
            return key, val
    raise SystemExit("no agent block")


def load_adv_tasks():
    if not TASKS.exists():
        return []
    return [
        json.loads(l)
        for l in TASKS.read_text().splitlines()
        if l.strip() and json.loads(l).get("category") == "adversarial"
    ]


def load_pair(stem: str, adv_tasks=None):
    adv_tasks = adv_tasks if adv_tasks is not None else load_adv_tasks()
    out = {}
    for mode in ("record", "prompt"):
        path = V04 / f"{stem}_dev_{mode}.json"
        if not path.exists():
            return None
        doc = json.loads(path.read_text())
        _, block = agent_block(doc)
        agg = block["aggregate"]
        counts = agg.get("counts") or {}
        rows = block["tasks"]
        perm_adj = consent_aware_perm_adjustment(rows)
        exposure = injection_exposure_metrics(rows, adv_tasks) if adv_tasks else None
        out[mode] = {
            "path": str(path.relative_to(ROOT)),
            "meta": doc.get("meta"),
            "utility": rate_with_n(*(counts.get("utility") or [0, 0])),
            "violation_rate": rate_with_n(*(counts.get("violation_rate") or [0, 0])),
            "access": rate_with_n(*(counts.get("access_violation_rate") or [0, 0])),
            "action": rate_with_n(*(counts.get("action_violation_rate") or [0, 0])),
            "disclosure": rate_with_n(*(counts.get("disclosure_violation_rate") or [0, 0])),
            "capability": rate_with_n(*(counts.get("denied_twin_capability") or [0, 0])),
            "capability_consent_aware": perm_adj["denied_twin_capability_consent_aware"],
            "consent_aware_refusals": perm_adj["consent_aware_perm_refusals"],
            "conditional_compliance": rate_with_n(*(counts.get("conditional_compliance") or [0, 0])),
            "voluntary_docref_exposure": (
                exposure["voluntary_docref_exposure_rate"] if exposure else rate_with_n(0, 0)
            ),
            "injection_exposure": (
                exposure["injection_exposure_rate"] if exposure else rate_with_n(0, 0)
            ),
            "seconds": (doc.get("meta") or {}).get("seconds"),
        }
    return out


def discover_stems():
    stems = set()
    for path in V04.glob("*_dev_record.json"):
        stems.add(path.name[: -len("_dev_record.json")])
    return sorted(stems)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default=str(_default_out()))
    ap.add_argument("--stems", default="", help="comma-separated result stems (default: auto-discover)")
    args = ap.parse_args(argv)
    stems = [s.strip() for s in args.stems.split(",") if s.strip()] or discover_stems()
    if not stems:
        raise SystemExit(f"no *_dev_record.json under {V04}")

    adv_tasks = load_adv_tasks()
    rows = []
    missing = []
    for stem in stems:
        pair = load_pair(stem, adv_tasks=adv_tasks)
        if not pair:
            missing.append(stem)
            continue
        rows.append((stem, pair))

    lines = [
        "# R6 — Multi-model matrix on `dev.jsonl` (v0.4 / S6a)",
        "",
        "Date: 2026-10-21 (sensitivity columns added 2026-10-22 / S12b).",
        "",
        "Settings: `temperature=0`, `seed=1`, `--disable-thinking`, cohort `dev_pool`, "
        "`--include-perm` (180 runs/mode). Headline utility/violations exclude `-ctrl`/`-perm`.",
        "",
        "`capability` is the primary same-text `-perm` rate. "
        "`capability_consent_aware` is a **sensitivity** column "
        "(successes + Consent-aware policy refusals; see R13b). "
        "`vol_DocRef_exp` is voluntary off-path DocumentReference exposure.",
        "",
        "## Utility vs violation (Pareto)",
        "",
        "| model | mode | utility | violation_rate | access | action | disclosure | "
        "capability | capability_consent_aware | cond. compliance | vol_DocRef_exp | seconds |",
        "|---|---|---|---|---|---|---|---|---|---|---|---:|",
    ]
    for stem, pair in rows:
        for mode in ("record", "prompt"):
            m = pair[mode]
            lines.append(
                f"| {stem} | {mode} | {fmt(m['utility'])} | {fmt(m['violation_rate'])} | "
                f"{fmt(m['access'])} | {fmt(m['action'])} | {fmt(m['disclosure'])} | "
                f"{fmt(m['capability'])} | {fmt(m['capability_consent_aware'])} | "
                f"{fmt(m['conditional_compliance'])} | {fmt(m['voluntary_docref_exposure'])} | "
                f"{m['seconds']} |"
            )
    lines.append("")

    # Compact Pareto points
    lines.append("### Compact points (utility %, violation %)")
    lines.append("")
    lines.append("| model | record (util, viol) | prompt (util, viol) | Δ viol (record−prompt) |")
    lines.append("|---|---|---|---:|")
    for stem, pair in rows:
        ur, vr = pair["record"]["utility"]["rate"], pair["record"]["violation_rate"]["rate"]
        up, vp = pair["prompt"]["utility"]["rate"], pair["prompt"]["violation_rate"]["rate"]
        lines.append(
            f"| {stem} | {100*ur:.0f}%, {100*vr:.0f}% | {100*up:.0f}%, {100*vp:.0f}% | "
            f"{100*(vr-vp):+.1f} pp |"
        )
    lines.append("")

    # Extra aggregates for interpretation
    def _extra(stem, mode):
        path = V04 / f"{stem}_dev_{mode}.json"
        doc = json.loads(path.read_text())
        _, block = agent_block(doc)
        agg = block["aggregate"]
        counts = agg.get("counts") or {}
        return {
            "false_refusal": rate_with_n(*(counts.get("false_refusal_proxy") or [0, 0])),
            "invalid": rate_with_n(*(counts.get("invalid_response_rate") or [0, 0])),
        }

    lines.append("## Refusal / invalid (context)")
    lines.append("")
    lines.append("| model | mode | false_refusal_proxy | invalid_response |")
    lines.append("|---|---|---|---|")
    for stem, pair in rows:
        for mode in ("record", "prompt"):
            ex = _extra(stem, mode)
            lines.append(f"| {stem} | {mode} | {fmt(ex['false_refusal'])} | {fmt(ex['invalid'])} |")
    lines.append("")

    lines.append("## Findings")
    lines.append("")
    stems_present = {s for s, _ in rows}
    if "qwen2.5-7b-fc" in stems_present and "qwen3-14b" in stems_present:
        lines.append(
            "- Local scale curve targets `qwen2.5-7b-fc` → `qwen3-14b` → `qwen3-32b` "
            "(when the 32B pair is present)."
        )
    if "qwen3-14b" in stems_present:
        lines.append(
            "- **qwen3-14b** shows a clear policy-in-prompt effect on the 2-model baseline: "
            "violations 43%→22% at nearly flat utility (66%→62%); "
            "conditional compliance 6%→60%."
        )
    if "qwen2.5-7b-fc" in stems_present:
        lines.append(
            "- **qwen2.5-7b-fc** sits low on the Pareto chart (utility ≈20–21%, "
            "violations ≈16–17%) with almost no prompt effect. False-refusal proxy "
            "≈66–69% — under-retrieval floor, not better alignment."
        )
    if "qwen3-32b" in stems_present:
        r = dict(rows)["qwen3-32b"]
        ur, vr = r["record"]["utility"]["rate"], r["record"]["violation_rate"]["rate"]
        up, vp = r["prompt"]["utility"]["rate"], r["prompt"]["violation_rate"]["rate"]
        cr = r["record"]["capability"]["rate"]
        cp = r["prompt"]["capability"]["rate"]
        lines.append(
            f"- **qwen3-32b** (LocalAI id `qwen3`, `gpu_layers:55`, `cache-ram:512`): "
            f"record {100*ur:.0f}%/{100*vr:.0f}% → prompt {100*up:.0f}%/{100*vp:.0f}% "
            f"(Δ viol {100*(vr-vp):+.1f} pp). Strongest local policy-in-prompt Δ-viol, "
            f"but utility sits below 14B; capability {100*cr:.0f}%→{100*cp:.0f}% under prompt "
            f"(see `R10_scale_regression.md`)."
        )
        if "qwen3-14b" in stems_present:
            lines.append(
                "- **Pareto pick on this local curve:** `qwen3-14b` still dominates utility; "
                "`qwen3-32b` is the best local Δ-viol / conditional-compliance point under `prompt`, "
                "not a free util upgrade."
            )
    lines.append(
        "- Skipped biomedical GGUFs (no native OpenAI tool-call path for WardBench): "
        "`OpenBioLLM-Llama3-8B` has `function.grammar.disable: true` in its LocalAI YAML; "
        "`medgemma-4b-it` is a vision/chat import (`mmproj`, no `use_jinja` tool template). "
        "Frontier APIs remain **S6a2**."
    )
    lines.append(
        "- Prefer models that keep utility while cutting violations under `prompt` "
        "(policy-in-prompt effect)."
    )
    lines.append(
        "- `denied_twin_capability` on framing-heavy `-perm` twins underestimates "
        "clinical ability (see R4c / R13b); compare capability cautiously across models. "
        "Use `capability_consent_aware` only as sensitivity when a model checks Consent "
        "and refuses inherited research/email framing."
    )
    lines.append(
        "- Voluntary off-path DocRef exposure stays near zero on capable models "
        "(S12 / R13): cite `attack_induced` only with the exposure decomposition."
    )
    if missing:
        lines.append(f"- Missing pairs (need both record+prompt JSON): `{missing}`")
    lines.append("")
    lines.append("## Files")
    lines.append("")
    for stem, pair in rows:
        for mode in ("record", "prompt"):
            lines.append(f"- `repos/wardbench/{pair[mode]['path']}`")
    lines.append("")

    out = pathlib.Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    print(f"wrote {out}")
    for stem, pair in rows:
        print(
            stem,
            "record",
            fmt(pair["record"]["utility"]),
            fmt(pair["record"]["violation_rate"]),
            "prompt",
            fmt(pair["prompt"]["utility"]),
            fmt(pair["prompt"]["violation_rate"]),
        )


if __name__ == "__main__":
    main()
