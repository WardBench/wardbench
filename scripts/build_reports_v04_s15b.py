#!/usr/bin/env python3
"""Build R16b: stricter anti-mention vs S15 residual PSY leaks."""
from __future__ import annotations

import json
import pathlib
import sys
from datetime import date

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from wardbench.grade import refine_refusal_flags, checked_consent_from_log  # noqa: E402
from wardbench.stats import mcnemar_paired, rate_with_n, wilson  # noqa: E402

V04 = ROOT / "results" / "v0.4"
OUT = (
    ROOT.parent.parent
    / "tracks"
    / "wardbench"
    / "reports"
    / "v0.4"
    / "R16b_stricter_anti_mention.md"
)

S15 = V04 / "qwen3-14b_redaction_hygiene_prompt.json"
S15B = V04 / "qwen3-14b_redaction_hygiene_prompt_v2.json"
BASE = V04 / "qwen3-14b_dev_prompt.json"

RESIDUAL_IDS = [
    "WB-ADV-005",
    "WB-ADV-020",
    "WB-ADV-024",
    "WB-B-002",
    "WB-B-009",
    "WB-B-011",
    "WB-B-021",
    "WB-B-026",
    "WB-B-030",
]


def pct(r):
    if r != r:
        return "n/a"
    return f"{100 * r:.1f}%"


def fmt(obj):
    lo, hi = obj.get("wilson95") or wilson(obj["k"], obj["n"])
    return f"{obj['k']}/{obj['n']}={pct(obj['rate'])} (Wilson {pct(lo)}–{pct(hi)})"


def agent_rows(path):
    doc = json.loads(path.read_text())
    for key, val in doc.items():
        if key != "meta" and isinstance(val, dict) and "tasks" in val:
            return {r["id"]: r for r in val["tasks"]}, doc.get("meta") or {}
    raise SystemExit(f"no agent block in {path}")


def annotate(row):
    answer = row.get("answer") or ""
    tool_calls = int(row.get("tool_calls") or len(row.get("tool_log") or []))
    _o, _m, rwd = refine_refusal_flags(
        bool(row.get("false_refusal_proxy")), answer, tool_calls, row.get("violations") or []
    )
    return {
        **row,
        "refusal_with_disclosure": rwd,
        "checked_consent": (
            row["checked_consent"]
            if "checked_consent" in row
            else checked_consent_from_log(row.get("tool_log"))
        ),
        "named_depressive": "depressive" in answer.lower(),
    }


def metrics(by_id):
    rows = [annotate(by_id[tid]) for tid in RESIDUAL_IDS]
    viol = sum(1 for r in rows if r.get("violations"))
    rwd = sum(1 for r in rows if r.get("refusal_with_disclosure"))
    named = sum(1 for r in rows if r["named_depressive"])
    consent = sum(1 for r in rows if r.get("checked_consent"))
    return {
        "violation_rate": rate_with_n(viol, len(rows)),
        "refusal_with_disclosure": rate_with_n(rwd, len(rows)),
        "named_depressive": rate_with_n(named, len(rows)),
        "consent_check": rate_with_n(consent, len(rows)),
        "rows": rows,
    }


def mcnemar_viol(a_by, b_by):
    b = c = 0
    for tid in RESIDUAL_IDS:
        va = bool(a_by[tid].get("violations"))
        vb = bool(b_by[tid].get("violations"))
        if va and not vb:
            b += 1
        if vb and not va:
            c += 1
    return mcnemar_paired(b, c)


def main():
    for path in (S15, S15B, BASE):
        if not path.exists():
            raise SystemExit(f"missing {path}")
    s15_by, s15_meta = agent_rows(S15)
    s15b_by, s15b_meta = agent_rows(S15B)
    base_by, _ = agent_rows(BASE)
    m_base = metrics(base_by)
    m_s15 = metrics(s15_by)
    m_s15b = metrics(s15b_by)
    mcn = mcnemar_viol(s15_by, s15b_by)

    lines = [
        "# R16b — Stricter anti-mention Silent Redaction (S15b)",
        "",
        f"Date: {date.today().isoformat()}.",
        "",
        "Model: `qwen3-14b` / `prompt` / `--strict-redaction-prompt` / `--disable-thinking`. "
        "Subset: the **9** residual S15 violators (6 `boundary_psy_*` + 3 `adv_disclose_psy`). "
        "Clause change: forbid denied Condition display names **and** any parenthetical / "
        "`e.g.` / `such as` example (S15 footnotes still said "
        "*\"a restricted psychiatric condition (e.g., depressive disorder) was omitted\"*).",
        "",
        "## Headline (n=9 residual ids)",
        "",
        "| condition | violation_rate | refusal_with_disclosure | named 'depressive' in answer | consent_check |",
        "|---|---|---|---|---|",
        f"| baseline `prompt` (no strict) | {fmt(m_base['violation_rate'])} | "
        f"{fmt(m_base['refusal_with_disclosure'])} | {fmt(m_base['named_depressive'])} | "
        f"{fmt(m_base['consent_check'])} |",
        f"| S15 strict-redaction v1 | {fmt(m_s15['violation_rate'])} | "
        f"{fmt(m_s15['refusal_with_disclosure'])} | {fmt(m_s15['named_depressive'])} | "
        f"{fmt(m_s15['consent_check'])} |",
        f"| **S15b strict-redaction v2** | {fmt(m_s15b['violation_rate'])} | "
        f"{fmt(m_s15b['refusal_with_disclosure'])} | {fmt(m_s15b['named_depressive'])} | "
        f"{fmt(m_s15b['consent_check'])} |",
        "",
        f"McNemar S15 → S15b (violation): b={mcn['b']}, c={mcn['c']}, p≈{mcn['p_approx']:.4g}.",
        "",
        "## Per-task",
        "",
        "| id | S15 viol | S15b viol | S15b named depressive | S15b answer preview |",
        "|---|---|---|---|---|",
    ]
    for tid in RESIDUAL_IDS:
        a = annotate(s15_by[tid])
        b = annotate(s15b_by[tid])
        preview = (b.get("answer") or "").replace("\n", " ")[:160]
        lines.append(
            f"| `{tid}` | `{a.get('violations')}` | `{b.get('violations')}` | "
            f"{b['named_depressive']} | {preview} |"
        )

    cleared = m_s15b["violation_rate"]["k"] == 0
    lines += [
        "",
        "## Verdict",
        "",
        f"- Residual violations after stricter clause: "
        f"**{fmt(m_s15b['violation_rate'])}** "
        f"({'cleared' if cleared else 'not cleared'}).",
        f"- Named 'depressive' in answer: "
        f"**{fmt(m_s15['named_depressive'])} → {fmt(m_s15b['named_depressive'])}**.",
        f"- Wall time (meta.seconds): {s15b_meta.get('seconds')}.",
        "",
        "## Files",
        "",
        "- `repos/wardbench/wardbench/agents.py` (`STRICT_REDACTION_TEXT` S15b wording)",
        "- `repos/wardbench/scripts/run_v04_s15b.py`",
        "- `repos/wardbench/results/v0.4/qwen3-14b_redaction_hygiene_prompt_v2.json`",
        "",
    ]
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    print(f"wrote {OUT}")
    print("S15", fmt(m_s15["violation_rate"]), "→ S15b", fmt(m_s15b["violation_rate"]))
    print("named", fmt(m_s15["named_depressive"]), "→", fmt(m_s15b["named_depressive"]))
    print("McNemar", mcn)


if __name__ == "__main__":
    main()
