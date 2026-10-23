#!/usr/bin/env python3
"""Build R8_factorial_and_consent_ablation.md and patch ALL_v04.md / summary_v04.json."""
from __future__ import annotations

import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from wardbench.stats import mcnemar_paired, rate_with_n, wilson  # noqa: E402
from scripts.run import CONSENT_DEPENDENT_PREFIXES, is_consent_dependent  # noqa: E402

V04 = ROOT / "results" / "v0.4"
REPORTS = ROOT.parent.parent / "tracks" / "wardbench" / "reports" / "v0.4"
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
    raise SystemExit("no agent block")


def load(path: pathlib.Path):
    doc = json.loads(path.read_text())
    name, block = agent_block(doc)
    return doc.get("meta") or {}, name, block


def main_rows(rows):
    return [r for r in rows if not r.get("control") and not r.get("perm")]


def headline(block):
    agg = block["aggregate"]
    counts = agg.get("counts") or {}
    return {
        "utility": rate_with_n(*(counts.get("utility") or [0, 0])),
        "violation_rate": rate_with_n(*(counts.get("violation_rate") or [0, 0])),
        "access": rate_with_n(*(counts.get("access_violation_rate") or [0, 0])),
        "action": rate_with_n(*(counts.get("action_violation_rate") or [0, 0])),
        "disclosure": rate_with_n(*(counts.get("disclosure_violation_rate") or [0, 0])),
        "capability": rate_with_n(*(counts.get("denied_twin_capability") or [0, 0])),
        "conditional_compliance": rate_with_n(*(counts.get("conditional_compliance") or [0, 0])),
        "consent_check": rate_with_n(*(counts.get("consent_check_rate") or [0, 0])),
    }


def by_id(rows):
    return {r["id"]: r for r in rows}


def paired_viol(a_rows, b_rows, ids):
    """McNemar on violation presence: a=True b=False vs a=False b=True."""
    only_a = only_b = 0
    pairs = []
    for tid in ids:
        a = bool((a_rows.get(tid) or {}).get("violations"))
        b = bool((b_rows.get(tid) or {}).get("violations"))
        pairs.append((int(a), int(b)))
        if a and not b:
            only_a += 1
        elif b and not a:
            only_b += 1
    return mcnemar_paired(only_a, only_b), pairs


def paired_success(a_rows, b_rows, ids):
    only_a = only_b = 0
    for tid in ids:
        a = bool((a_rows.get(tid) or {}).get("success"))
        b = bool((b_rows.get(tid) or {}).get("success"))
        if a and not b:
            only_a += 1
        elif b and not a:
            only_b += 1
    return mcnemar_paired(only_a, only_b)


def subset_metrics(rows, task_ids):
    sel = [r for r in main_rows(rows) if r["id"] in task_ids]
    viol = sum(1 for r in sel if r.get("violations"))
    util_rows = [r for r in sel if r.get("behavior") != "refuse"]
    util = sum(1 for r in util_rows if r.get("success"))
    return {
        "violation_rate": rate_with_n(viol, len(sel)),
        "utility": rate_with_n(util, len(util_rows)),
        "n": len(sel),
    }


def main():
    tasks = [json.loads(l) for l in TASKS.read_text().splitlines() if l.strip()]
    consent_ids = {t["id"] for t in tasks if is_consent_dependent(t)}
    assert len(consent_ids) == 30, len(consent_ids)

    modes = {}
    for mode in ("record", "prompt", "enforced", "prompt_enforced"):
        path = V04 / f"qwen3-14b_dev_{mode}.json"
        if not path.exists():
            if mode == "prompt_enforced":
                raise SystemExit(f"missing {path} — run scripts/run_v04_s8.py first")
            continue
        meta, name, block = load(path)
        modes[mode] = {"meta": meta, "agent": name, "block": block, "h": headline(block), "path": path}

    pref_path = V04 / "qwen3-14b_dev_prompt_consent_prefetch.json"
    if not pref_path.exists():
        raise SystemExit(f"missing {pref_path}")
    pref_meta, pref_agent, pref_block = load(pref_path)

    prompt_rows = by_id(modes["prompt"]["block"]["tasks"])
    pref_rows = by_id(pref_block["tasks"])
    pe_rows = by_id(modes["prompt_enforced"]["block"]["tasks"])

    prompt_sub = subset_metrics(modes["prompt"]["block"]["tasks"], consent_ids)
    pref_sub = subset_metrics(pref_block["tasks"], consent_ids)
    mcn_viol, _ = paired_viol(prompt_rows, pref_rows, sorted(consent_ids))
    mcn_util = paired_success(prompt_rows, pref_rows, sorted(consent_ids))

    # Factorial McNemar prompt vs prompt_enforced on all main 120
    main_ids = [r["id"] for r in main_rows(modes["prompt"]["block"]["tasks"])]
    mcn_pe_viol, _ = paired_viol(prompt_rows, pe_rows, main_ids)

    lines = [
        "# R8 — $2\\times 2$ policy factorial + Consent prefetch ablation (S8)",
        "",
        "Date: 2026-10-21.",
        "",
        "Model: `qwen3-14b`, `temperature=0`, `seed=1`, `--disable-thinking`, cohort `dev_pool`.",
        "",
        "## Factorial table (Prompt Policy × Server Gate)",
        "",
        "| cell | policy in prompt | server gate | utility | violation_rate | access | action | disclosure | capability | cond. compliance | consent_check |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    labels = {
        "record": ("no", "no"),
        "prompt": ("yes", "no"),
        "enforced": ("no", "yes"),
        "prompt_enforced": ("yes", "yes"),
    }
    for mode in ("record", "prompt", "enforced", "prompt_enforced"):
        h = modes[mode]["h"]
        pin, gate = labels[mode]
        lines.append(
            f"| `{mode}` | {pin} | {gate} | {fmt(h['utility'])} | {fmt(h['violation_rate'])} | "
            f"{fmt(h['access'])} | {fmt(h['action'])} | {fmt(h['disclosure'])} | "
            f"{fmt(h['capability'])} | {fmt(h['conditional_compliance'])} | {fmt(h['consent_check'])} |"
        )

    pe = modes["prompt_enforced"]["h"]
    pr = modes["prompt"]["h"]
    lines += [
        "",
        "### Defense-in-Depth vs prompt alone",
        "",
        f"- Violations: prompt {fmt(pr['violation_rate'])} → prompt_enforced {fmt(pe['violation_rate'])}.",
        f"- Disclosure: prompt {fmt(pr['disclosure'])} → prompt_enforced {fmt(pe['disclosure'])}.",
        f"- Utility: prompt {fmt(pr['utility'])} → prompt_enforced {fmt(pe['utility'])}.",
        f"- McNemar (violation, prompt vs prompt_enforced, n={len(main_ids)}): "
        f"b={mcn_pe_viol['b']} (only prompt), c={mcn_pe_viol['c']} (only prompt_enforced), "
        f"p≈{mcn_pe_viol['p_approx']:.4g}.",
        "",
        "## Epistemic Consent prefetch ablation",
        "",
        f"Subset: {len(consent_ids)} Consent-dependent tasks "
        f"(`{'`, `'.join(CONSENT_DEPENDENT_PREFIXES)}*`). Prefetch appends slim Consent JSON "
        "(or `No Consent resource on file`) to the user message under `prompt` visibility; "
        "it is **not** logged as a tool call.",
        "",
        "| condition | n | violation_rate | utility (non-refuse) |",
        "|---|---:|---|---|",
        f"| prompt (baseline, same ids) | {prompt_sub['n']} | {fmt(prompt_sub['violation_rate'])} | {fmt(prompt_sub['utility'])} |",
        f"| prompt + `--prefetch-consent` | {pref_sub['n']} | {fmt(pref_sub['violation_rate'])} | {fmt(pref_sub['utility'])} |",
        "",
        f"- McNemar violations (prompt vs prefetch): b={mcn_viol['b']} (only prompt), "
        f"c={mcn_viol['c']} (only prefetch), p≈{mcn_viol['p_approx']:.4g}.",
        f"- McNemar success (prompt vs prefetch): b={mcn_util['b']} (only prompt), "
        f"c={mcn_util['c']} (only prefetch), p≈{mcn_util['p_approx']:.4g}.",
        "",
        "### Interpretation",
        "",
        "- If prefetch **cuts** violations without needing `fhir_search(Consent)`, the prompt-mode "
        "gap on dynamic tasks was largely **procedural omission**.",
        "- If violations stay high with Consent in context, the model also fails to **reason** "
        "over Consent JSON under the role/purpose policy text.",
        "",
        "## Files",
        "",
    ]
    for mode in ("record", "prompt", "enforced", "prompt_enforced"):
        lines.append(f"- `repos/wardbench/{modes[mode]['path'].relative_to(ROOT)}`")
    lines.append(f"- `repos/wardbench/{pref_path.relative_to(ROOT)}`")
    lines.append("")

    out = REPORTS / "R8_factorial_and_consent_ablation.md"
    out.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    print(f"wrote {out}")

    # Patch summary_v04.json with prompt_enforced + ablation block
    summary_path = REPORTS / "summary_v04.json"
    summary = json.loads(summary_path.read_text()) if summary_path.exists() else {"version": "0.4", "modes": {}}
    summary.setdefault("modes", {})
    summary["modes"]["prompt_enforced"] = {
        "agent": modes["prompt_enforced"]["agent"],
        "meta": modes["prompt_enforced"]["meta"],
        **{k: modes["prompt_enforced"]["h"][k] for k in modes["prompt_enforced"]["h"]},
    }
    summary["s8_consent_prefetch"] = {
        "n_tasks": len(consent_ids),
        "prompt": prompt_sub,
        "prefetch": pref_sub,
        "mcnemar_violation": mcn_viol,
        "mcnemar_success": mcn_util,
        "meta": pref_meta,
    }
    summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(f"updated {summary_path}")

    all_path = REPORTS / "ALL_v04.md"
    section = [
        "",
        "## S8 addendum — factorial + Consent prefetch",
        "",
        f"See [`R8_factorial_and_consent_ablation.md`](R8_factorial_and_consent_ablation.md).",
        "",
        f"- `prompt_enforced` utility {fmt(pe['utility'])}, violations {fmt(pe['violation_rate'])} "
        f"(disclosure {fmt(pe['disclosure'])}).",
        f"- Consent-dependent subset: prompt viol {fmt(prompt_sub['violation_rate'])} → "
        f"prefetch {fmt(pref_sub['violation_rate'])} "
        f"(McNemar p≈{mcn_viol['p_approx']:.4g}).",
        "",
    ]
    text = all_path.read_text() if all_path.exists() else "# ALL v0.4\n"
    marker = "## S8 addendum"
    if marker in text:
        pre = text.split(marker)[0].rstrip()
        text = pre + "\n" + "\n".join(section)
    else:
        text = text.rstrip() + "\n" + "\n".join(section)
    all_path.write_text(text + "\n", encoding="utf-8")
    print(f"updated {all_path}")


if __name__ == "__main__":
    main()
