#!/usr/bin/env python3
"""Build R9_perm_rephrase_sensitivity.md from same-text vs clinical-rephrase -perm runs."""
from __future__ import annotations

import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from wardbench.stats import mcnemar_paired, rate_with_n, wilson  # noqa: E402
from scripts.run import PERM_CLINICAL_REPHRASE_BY_FAMILY  # noqa: E402

V04 = ROOT / "results" / "v0.4"
OUT = ROOT.parent.parent / "tracks" / "wardbench" / "reports" / "v0.4" / "R9_perm_rephrase_sensitivity.md"
TASKS = ROOT / "tasks" / "dev.jsonl"


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
            return key, val
    raise SystemExit(f"no agent block in doc keys={list(doc)}")


def load(path):
    doc = json.loads(path.read_text())
    _, block = agent_block(doc)
    return doc.get("meta") or {}, block


def perm_rows(block):
    return [r for r in block["tasks"] if r.get("perm")]


def denied_rows(block):
    return [r for r in block["tasks"] if not r.get("perm") and not r.get("control") and r.get("category") == "denied"]


def capability(rows):
    return rate_with_n(sum(1 for r in rows if r.get("success")), len(rows))


def conditional_compliance(denied, perms):
    by_perm = {r["perm_for"]: r for r in perms}
    capable = [d for d in denied if by_perm.get(d["id"], {}).get("success")]
    ok = sum(1 for d in capable if not d.get("violations"))
    return rate_with_n(ok, len(capable)), capable


def mcnemar_success(a_by_id, b_by_id, ids):
    only_a = only_b = 0
    for tid in ids:
        a = bool((a_by_id.get(tid) or {}).get("success"))
        b = bool((b_by_id.get(tid) or {}).get("success"))
        if a and not b:
            only_a += 1
        elif b and not a:
            only_b += 1
    return mcnemar_paired(only_a, only_b)


def split_by_family(perms, tasks_by_id):
    framing = []
    clean = []
    for r in perms:
        parent = tasks_by_id.get(r.get("perm_for") or "")
        fam = (parent or {}).get("family") or ""
        if fam in PERM_CLINICAL_REPHRASE_BY_FAMILY:
            framing.append(r)
        else:
            clean.append(r)
    return framing, clean


def main():
    tasks_by_id = {json.loads(l)["id"]: json.loads(l) for l in TASKS.read_text().splitlines() if l.strip()}
    lines = [
        "# R9 — Clinical-rephrase sensitivity on `-perm` twins (S9)",
        "",
        "Date: 2026-10-21.",
        "",
        "Primary metric remains **same-text** `-perm` (denied parent instruction). "
        "This report is the R4c sensitivity: framing families get TREAT clinical asks "
        f"(`{', '.join(sorted(PERM_CLINICAL_REPHRASE_BY_FAMILY))}`); billing_value / "
        "registration keep same-text.",
        "",
        "Model: `qwen3-14b`, temp=0, seed=1, `--disable-thinking`, denied-only queue "
        "(30 denied + 30 `-perm`).",
        "",
        "## Capability and conditional compliance",
        "",
        "| mode | same-text capability | rephrase capability | Δ | same-text cond.comp | rephrase cond.comp |",
        "|---|---|---|---:|---|---|",
    ]

    details = {}
    for mode in ("record", "prompt"):
        same_path = V04 / f"qwen3-14b_dev_{mode}.json"
        re_path = V04 / f"qwen3-14b_perm_rephrase_{mode}.json"
        if not same_path.exists() or not re_path.exists():
            raise SystemExit(f"missing {same_path} or {re_path}")
        _, same_block = load(same_path)
        re_meta, re_block = load(re_path)
        same_perm = {r["id"]: r for r in perm_rows(same_block)}
        re_perm = {r["id"]: r for r in perm_rows(re_block)}
        same_denied = denied_rows(same_block)
        re_denied = denied_rows(re_block)
        # Align denied from rephrase run (same 30 ids)
        same_cap = capability(list(same_perm.values()))
        re_cap = capability(list(re_perm.values()))
        same_cc, _ = conditional_compliance(same_denied, list(same_perm.values()))
        re_cc, _ = conditional_compliance(re_denied, list(re_perm.values()))
        ids = sorted(same_perm.keys())
        mcn = mcnemar_success(same_perm, re_perm, ids)
        framing_s, clean_s = split_by_family(list(same_perm.values()), tasks_by_id)
        framing_r, clean_r = split_by_family(list(re_perm.values()), tasks_by_id)
        details[mode] = {
            "meta": re_meta,
            "same_cap": same_cap,
            "re_cap": re_cap,
            "same_cc": same_cc,
            "re_cc": re_cc,
            "mcn": mcn,
            "framing_same": capability(framing_s),
            "framing_re": capability(framing_r),
            "clean_same": capability(clean_s),
            "clean_re": capability(clean_r),
            "flips_to_pass": [
                tid for tid in ids
                if not same_perm[tid].get("success") and re_perm[tid].get("success")
            ],
            "flips_to_fail": [
                tid for tid in ids
                if same_perm[tid].get("success") and not re_perm[tid].get("success")
            ],
        }
        d = details[mode]
        delta = 100 * (d["re_cap"]["rate"] - d["same_cap"]["rate"])
        lines.append(
            f"| {mode} | {fmt(d['same_cap'])} | {fmt(d['re_cap'])} | {delta:+.1f} pp | "
            f"{fmt(d['same_cc'])} | {fmt(d['re_cc'])} |"
        )

    lines += [
        "",
        "### McNemar on `-perm` success (same-text vs rephrase)",
        "",
        "| mode | b (only same-text) | c (only rephrase) | p≈ |",
        "|---|---:|---:|---:|",
    ]
    for mode in ("record", "prompt"):
        m = details[mode]["mcn"]
        lines.append(f"| {mode} | {m['b']} | {m['c']} | {m['p_approx']:.4g} |")

    lines += [
        "",
        "### Split: framing families vs clean parents",
        "",
        "| mode | framing same-text | framing rephrase | clean same-text | clean rephrase |",
        "|---|---|---|---|---|",
    ]
    for mode in ("record", "prompt"):
        d = details[mode]
        lines.append(
            f"| {mode} | {fmt(d['framing_same'])} | {fmt(d['framing_re'])} | "
            f"{fmt(d['clean_same'])} | {fmt(d['clean_re'])} |"
        )

    lines += ["", "### Flips", ""]
    for mode in ("record", "prompt"):
        d = details[mode]
        lines.append(
            f"- **{mode}**: to-pass `{d['flips_to_pass']}`; to-fail `{d['flips_to_fail']}`."
        )

    lines += [
        "",
        "## Interpretation",
        "",
        "- If rephrase lifts framing-family capability toward the clean-parent band (~83–92% from R4c), "
        "same-text `-perm` understates TREAT clinical ability.",
        "- Headline `denied_twin_capability` for the paper stays on **same-text** twins; cite this "
        "table as sensitivity only.",
        "",
        "## Files",
        "",
        "- `repos/wardbench/results/v0.4/qwen3-14b_dev_{record,prompt}.json` (same-text baseline)",
        "- `repos/wardbench/results/v0.4/qwen3-14b_perm_rephrase_{record,prompt}.json`",
        "",
    ]
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    print(f"wrote {OUT}")
    for mode, d in details.items():
        print(mode, "same", fmt(d["same_cap"]), "rephrase", fmt(d["re_cap"]), "mcn", d["mcn"])


if __name__ == "__main__":
    main()
