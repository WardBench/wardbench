#!/usr/bin/env python3
"""Re-grade saved v0.3 qwen3-14b runs under the calibrated v0.4 grader (no LLM).

Uses answer_preview (v0.3 did not store full answers) and the saved tool_log.
Writes tracks/wardbench/reports/v0.4/regrade_v03_summary.json and prints a table.
"""
from __future__ import annotations

import copy
import json
import pathlib
import sys
from collections import defaultdict

ROOT = pathlib.Path(__file__).resolve().parent.parent
HQ = ROOT.parent.parent / "tracks" / "wardbench" / "reports" / "v0.4"
sys.path.insert(0, str(ROOT))

from wardbench.cohort import build_pool_cohort, derive_attrs  # noqa: E402
from wardbench.grade import aggregate, grade  # noqa: E402
from wardbench.resolve import resolve  # noqa: E402
from wardbench.stats import mcnemar_paired, paired_bootstrap_diff, wilson  # noqa: E402
from wardbench.world import World  # noqa: E402


def load_jsonl(path):
    return [json.loads(line) for line in pathlib.Path(path).read_text().splitlines() if line.strip()]


def rebuild_world(task, cohort, tool_log):
    world = World(task, cohort)
    world.log = list(tool_log or [])
    world.created = []
    for entry in world.log:
        if entry.get("tool") != "fhir_create":
            continue
        rtype = entry.get("resource_type") or "ServiceRequest"
        world.created.append({
            "resourceType": rtype,
            "status": "active",
            "intent": "order",
            "subject": {"reference": f"Patient/{world.subject}"},
        })
    return world


def grading_task(row, tasks_by_id):
    if row.get("control"):
        parent = copy.deepcopy(tasks_by_id[row["control_for"]])
        parent.pop("environment_mods", None)
        parent["id"] = row["id"]
        parent["control_for"] = row["control_for"]
        return parent
    return tasks_by_id[row["id"]]


def regrade_mode(mode, tasks_by_id, cohort):
    payload = json.loads((ROOT / "results" / "v0.3" / f"qwen3-14b_dev_{mode}.json").read_text())
    key = next(k for k in payload if k != "meta")
    original_rows = payload[key]["tasks"]
    original_agg = payload[key]["aggregate"]
    regraded = []
    flips = []
    for row in original_rows:
        task = grading_task(row, tasks_by_id)
        world = rebuild_world(task, cohort, row.get("tool_log"))
        attrs = derive_attrs(cohort[world.subject])
        exp = task["expected"]
        resolved = {
            "required": [p for pat in exp.get("required_answer_patterns", []) for p in resolve(pat, attrs)],
            "forbidden": [
                p for pat in exp.get("forbidden_answer_patterns", [])
                for p in resolve(pat, attrs, strict=True)
            ],
        }
        answer = row.get("answer") or row.get("answer_preview") or ""
        status = row.get("response_status") or "ok"
        res = grade(task, world, answer, resolved, response_status=status)
        res["family"] = task.get("family")
        res["template"] = task.get("template")
        res["original_success"] = bool(row.get("success"))
        res["original_violations"] = list(row.get("violations") or [])
        regraded.append(res)
        if (not row.get("control")) and bool(row.get("success")) != bool(res["success"]):
            flips.append({
                "id": row["id"],
                "category": row["category"],
                "family": res["family"],
                "was_success": bool(row.get("success")),
                "now_success": bool(res["success"]),
                "was_missing": row.get("missing"),
                "now_missing": res["missing"],
                "was_violations": row.get("violations"),
                "now_violations": res["violations"],
                "answer_preview": (answer or "")[:200],
            })
    return {
        "mode": mode,
        "original_rows": original_rows,
        "original_aggregate": original_agg,
        "regraded_aggregate": aggregate(regraded),
        "flips": flips,
        "rows": regraded,
    }


def family_table(rows):
    groups = defaultdict(list)
    for r in rows:
        if r.get("control"):
            continue
        groups[r.get("family") or "?"].append(r)
    out = {}
    for fam, items in sorted(groups.items()):
        non_refuse = [r for r in items if r["behavior"] != "refuse"]
        out[fam] = {
            "n": len(items),
            "utility_k": sum(r["success"] for r in non_refuse),
            "utility_n": len(non_refuse),
            "viol_k": sum(bool(r["violations"]) for r in items),
            "viol_n": len(items),
            "orig_utility_k": sum(r["original_success"] for r in non_refuse),
            "orig_viol_k": sum(bool(r["original_violations"]) for r in items),
        }
    return out


def fmt_rate(counts):
    if not counts:
        return "n/a"
    k, n = counts[0], counts[1]
    lo, hi = wilson(k, n)
    return f"{100 * k / n:4.1f}% ({k}/{n}); Wilson 95% [{100 * lo:.1f}, {100 * hi:.1f}]"


def main():
    tasks = load_jsonl(ROOT / "tasks" / "dev.jsonl")
    tasks_by_id = {t["id"]: t for t in tasks}
    cohort = build_pool_cohort(ROOT / "work" / "synthea" / "cohort_v03" / "dev")
    HQ.mkdir(parents=True, exist_ok=True)

    report = {
        "note": "v0.3 answers are answer_preview (<=200 chars); suffix ablation is a lower bound",
        "modes": {},
    }
    lines = [
        "# Re-grade v0.3 under calibrated grader",
        "",
        "Answers are `answer_preview` (≤200 chars). Suffix-only recoveries inside the truncated preview are counted; recoveries only in the unseen tail are not.",
        "",
    ]
    for mode in ("record", "prompt"):
        block = regrade_mode(mode, tasks_by_id, cohort)
        orig = block["original_aggregate"]
        new = block["regraded_aggregate"]
        fam = family_table(block["rows"])
        by_id = {r["id"]: r for r in block["rows"] if not r.get("control")}
        b = c = 0
        pairs = []
        for r in block["original_rows"]:
            if r.get("control"):
                continue
            o = bool(r["success"])
            n = bool(by_id[r["id"]]["success"])
            pairs.append((int(n), int(o)))
            if o and not n:
                b += 1
            if (not o) and n:
                c += 1
        mc = mcnemar_paired(b, c)
        boot = paired_bootstrap_diff(pairs)

        report["modes"][mode] = {
            "original": {
                "utility": orig.get("utility"),
                "utility_counts": orig.get("counts", {}).get("utility"),
                "violation_rate": orig.get("violation_rate"),
                "violation_counts": orig.get("counts", {}).get("violation_rate"),
            },
            "regraded": {
                "utility": new.get("utility"),
                "utility_counts": new.get("counts", {}).get("utility"),
                "violation_rate": new.get("violation_rate"),
                "violation_counts": new.get("counts", {}).get("violation_rate"),
                "success_by_category": new.get("success_by_category"),
            },
            "flips": block["flips"],
            "n_flips_to_success": sum(1 for f in block["flips"] if f["now_success"] and not f["was_success"]),
            "n_flips_to_fail": sum(1 for f in block["flips"] if f["was_success"] and not f["now_success"]),
            "mcnemar_success_orig_vs_regrade": mc,
            "paired_bootstrap_regrade_minus_orig": boot,
            "by_family": fam,
        }

        lines += [
            f"## Mode `{mode}`",
            "",
            "| Metric | v0.3 original | Re-graded (v0.4 grader) |",
            "|---|---|---|",
            f"| utility | {fmt_rate(orig.get('counts', {}).get('utility'))} | {fmt_rate(new.get('counts', {}).get('utility'))} |",
            f"| violation_rate | {fmt_rate(orig.get('counts', {}).get('violation_rate'))} | {fmt_rate(new.get('counts', {}).get('violation_rate'))} |",
            "",
            f"- Success flips to pass: **{report['modes'][mode]['n_flips_to_success']}**",
            f"- Success flips to fail: **{report['modes'][mode]['n_flips_to_fail']}**",
            f"- McNemar (orig-only success b / regrade-only success c): b={mc['b']}, c={mc['c']}, p≈{mc['p_approx']:.4g}",
            f"- Paired bootstrap (regrade − orig success rate): {100 * boot['diff']:+.1f} pp, "
            f"95% CI [{100 * boot['ci95'][0]:+.1f}, {100 * boot['ci95'][1]:+.1f}]",
            "",
        ]
        if block["flips"]:
            lines.append("Flipped tasks:")
            for f in block["flips"][:25]:
                lines.append(
                    f"- `{f['id']}` ({f['family']}): {f['was_success']} → {f['now_success']}; "
                    f"missing {f['was_missing']} → {f['now_missing']}"
                )
            if len(block["flips"]) > 25:
                lines.append(f"- … ({len(block['flips']) - 25} more)")
            lines.append("")

        # Families with utility change
        changed = [
            (fam_name, row) for fam_name, row in fam.items()
            if row["utility_k"] != row["orig_utility_k"] or row["viol_k"] != row["orig_viol_k"]
        ]
        if changed:
            lines.append("Families with metric change:")
            for fam_name, row in changed:
                lines.append(
                    f"- `{fam_name}`: utility {row['orig_utility_k']}/{row['utility_n']} → "
                    f"{row['utility_k']}/{row['utility_n']}; "
                    f"viol {row['orig_viol_k']}/{row['viol_n']} → {row['viol_k']}/{row['viol_n']}"
                )
            lines.append("")

    out_json = HQ / "regrade_v03_summary.json"
    out_json.write_text(json.dumps(report, indent=2), encoding="utf-8")
    text = "\n".join(lines)
    print(text)
    print(f"wrote {out_json}")
    return report, text


if __name__ == "__main__":
    main()
