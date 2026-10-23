#!/usr/bin/env python3
"""Build R13b metric-formalization report from saved v0.4 runs (S12b).

No LLM calls. Uses `wardbench.audit_metrics` sensitivity helpers only —
does not change headline `denied_twin_capability` in grade aggregates.
"""
from __future__ import annotations

import json
import pathlib
import sys
from datetime import date

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from wardbench.audit_metrics import (  # noqa: E402
    channel_inventory,
    consent_aware_perm_adjustment,
    injection_exposure_metrics,
)
from wardbench.stats import wilson  # noqa: E402

V04 = ROOT / "results" / "v0.4"
TASKS = ROOT / "tasks" / "dev.jsonl"
OUT = ROOT.parent.parent / "tracks" / "wardbench" / "reports" / "v0.4" / "R13b_metric_formalization.md"

# Models with full record+prompt pairs on the local multi-model board.
MULTI_STEMS = ("qwen2.5-7b-fc", "qwen3-14b", "qwen3-32b")
# Extra modes for exposure / factorial context.
EXTRA_RUNS = [
    ("qwen3-14b", "enforced"),
    ("qwen3-14b", "prompt_enforced"),
]


def pct(r: float) -> str:
    if r != r:
        return "n/a"
    return f"{100 * r:.1f}%"


def fmt(obj: dict) -> str:
    lo, hi = obj.get("wilson95") or wilson(obj["k"], obj["n"])
    return f"{obj['k']}/{obj['n']}={pct(obj['rate'])} (Wilson {pct(lo)}–{pct(hi)})"


def agent_block(doc: dict):
    for key, val in doc.items():
        if key != "meta" and isinstance(val, dict) and "tasks" in val:
            return key, val
    raise SystemExit(f"no agent block in document keys={list(doc)}")


def load_tasks():
    return [json.loads(l) for l in TASKS.read_text().splitlines() if l.strip()]


def load_rows(stem: str, mode: str):
    path = V04 / f"{stem}_dev_{mode}.json"
    if not path.exists():
        return None
    doc = json.loads(path.read_text())
    _, block = agent_block(doc)
    return path, block["tasks"]


def main():
    today = date.today().isoformat()
    tasks = load_tasks()
    adv = [t for t in tasks if t.get("category") == "adversarial"]
    inventory = channel_inventory(adv)

    lines = [
        "# R13b — Metric formalization: Consent-aware `-perm` + injection exposure (S12b)",
        "",
        f"Date: {today}.",
        "",
        "Offline only. Formalizes the S12 sensitivity metrics in "
        "`wardbench/audit_metrics.py` for reuse by report builders. "
        "**Headline** `denied_twin_capability` and `attack_induced_rate` are unchanged.",
        "",
        "## Definitions",
        "",
        "| metric | definition | status |",
        "|---|---|---|",
        "| `denied_twin_capability` | success rate on 30 same-text `-perm` twins | **primary** |",
        "| `consent_aware_perm_refusals` | `-perm` fails with Consent check ∧ policy-refusal "
        "language ∧ zero violations | sensitivity count |",
        "| `denied_twin_capability_consent_aware` | `(successes + consent_aware_refusals) / 30` | "
        "**sensitivity only** |",
        "| `injection_exposure_rate` | adversarial tasks whose `tool_log` touched the injected "
        "`resource_type` | reporting |",
        "| `voluntary_docref_exposure_rate` | DocRef touches on off-path note injections | reporting |",
        "| `conditional_injection_success_given_exposed` | violation rate among exposed tasks "
        "with clean `-ctrl` | reporting |",
        "",
        "## Channel inventory (adversarial n=30)",
        "",
        f"- By `resource_type`: `{inventory['by_resource_type']}`",
        f"- On-path / off-path DocRef: **{inventory['on_path_n']}/30** / "
        f"**{inventory['off_path_docref_n']}/30**",
        "",
        "## Consent-aware `-perm` sensitivity",
        "",
        "| model | mode | capability (primary) | consent-aware refusals | "
        "capability (consent-aware, sensitivity) | refusal ids |",
        "|---|---|---|---|---|---|",
    ]

    perm_board = []
    for stem in MULTI_STEMS:
        for mode in ("record", "prompt"):
            loaded = load_rows(stem, mode)
            if not loaded:
                lines.append(f"| {stem} | {mode} | missing | — | — | — |")
                continue
            _path, rows = loaded
            adj = consent_aware_perm_adjustment(rows)
            perm_board.append((stem, mode, adj))
            ids = ", ".join(f"`{i}`" for i in adj["consent_aware_perm_refusal_ids"]) or "—"
            lines.append(
                f"| {stem} | {mode} | {fmt(adj['denied_twin_capability'])} | "
                f"{fmt(adj['consent_aware_perm_refusals'])} | "
                f"{fmt(adj['denied_twin_capability_consent_aware'])} | {ids} |"
            )

    # Highlight 32B prompt
    adj_32_prompt = next((a for s, m, a in perm_board if s == "qwen3-32b" and m == "prompt"), None)
    adj_32_record = next((a for s, m, a in perm_board if s == "qwen3-32b" and m == "record"), None)
    lines += ["", "### Interpretation", ""]
    if adj_32_prompt and adj_32_record:
        lines.append(
            f"On `qwen3-32b` / `prompt`, primary capability is "
            f"**{fmt(adj_32_prompt['denied_twin_capability'])}** vs record "
            f"**{fmt(adj_32_record['denied_twin_capability'])}**. "
            f"Consent-aware adjustment adds "
            f"**{adj_32_prompt['consent_aware_perm_refusals']['k']}** rows "
            f"({', '.join(f'`{i}`' for i in adj_32_prompt['consent_aware_perm_refusal_ids']) or 'none'}), "
            f"lifting the sensitivity rate to "
            f"**{fmt(adj_32_prompt['denied_twin_capability_consent_aware'])}**. "
            "The remaining gap vs record is still mostly omission/empty answers "
            "(see R10), not Consent-aware refusals."
        )
        lines.append("")
    lines.append(
        "Primary paper metric stays **same-text** `denied_twin_capability` "
        "(R4c / R9). Cite the consent-aware column only as construct-validity sensitivity."
    )

    runs = [(s, m) for s in MULTI_STEMS for m in ("record", "prompt")] + EXTRA_RUNS
    lines += [
        "",
        "## Injection exposure board",
        "",
        "| model | mode | exposure | DocRef touch | voluntary DocRef | "
        "attack_induced | cond. success \\| exposed & ctrl clean |",
        "|---|---|---|---|---|---|---|",
    ]
    for stem, mode in runs:
        loaded = load_rows(stem, mode)
        if not loaded:
            lines.append(f"| {stem} | {mode} | missing | — | — | — | — |")
            continue
        _path, rows = loaded
        exp = injection_exposure_metrics(rows, adv)
        lines.append(
            f"| {stem} | {mode} | {fmt(exp['injection_exposure_rate'])} | "
            f"{fmt(exp['documentreference_touch_rate'])} | "
            f"{fmt(exp['voluntary_docref_exposure_rate'])} | "
            f"{fmt(exp['attack_induced_rate'])} | "
            f"{fmt(exp['conditional_injection_success_given_exposed'])} |"
        )

    lines += [
        "",
        "Voluntary off-path DocRef exposure remains **0** on capable local models: "
        "headline `attack_induced` without exposure is trajectory / base-task leakage, "
        "not successful indirect prompt injection (R13).",
        "",
        "## Integration",
        "",
        "- Library: `repos/wardbench/wardbench/audit_metrics.py`",
        "- Multi-model board: `scripts/build_reports_v04_multi.py` prints "
        "`capability_consent_aware` and `voluntary_docref_exp` columns.",
        "- CLI audit: `scripts/audit_injection_exposure.py`",
        "- Regenerate this report: `python3 scripts/build_reports_v04_s12.py`",
        "",
        "## Files",
        "",
        f"- `{OUT.relative_to(ROOT.parent.parent)}`",
        "",
    ]

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    print(f"wrote {OUT}")
    if adj_32_prompt:
        print(
            "32B prompt capability",
            fmt(adj_32_prompt["denied_twin_capability"]),
            "→ consent-aware",
            fmt(adj_32_prompt["denied_twin_capability_consent_aware"]),
            "ids",
            adj_32_prompt["consent_aware_perm_refusal_ids"],
        )


if __name__ == "__main__":
    main()
