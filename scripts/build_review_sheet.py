#!/usr/bin/env python3
"""Build review/review_sheet.csv — 2 tasks per template, plain language."""
import csv
import json
import pathlib
import random
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from wardbench.cohort import build_pool_cohort, derive_attrs  # noqa: E402
from wardbench.resolve import render_instruction  # noqa: E402

TASKS = ROOT / "tasks" / "dev.jsonl"
OUT = ROOT / "review" / "review_sheet.csv"


def load():
    return [json.loads(l) for l in TASKS.read_text().splitlines() if l.strip()]


def consent_words(c):
    if c["state"] == "none":
        return "No Consent resource on file"
    if c["state"] == "inactive":
        return "Consent present but inactive (treated as no grant)"
    bits = [f"Active Consent with {len(c.get('provisions') or [])} provision(s)"]
    for p in c.get("provisions") or []:
        bits.append(f"{p['type']} purpose={p.get('purpose')} classes={p.get('data_classes')} constraints={p.get('constraints')}")
    return "; ".join(bits)


def patient_summary(attrs):
    dx = [c["display"] for c in attrs["conditions"] if c.get("bounded")][:3]
    return (f"Age {attrs['age_years']}; latest HbA1c {attrs['hba1c']['value']} on {attrs['hba1c']['date']}; "
            f"example disorders: {', '.join(dx) or 'n/a'}")


def violation_words(task):
    exp = task["expected"]
    parts = []
    if exp.get("forbidden_reads"):
        parts.append("forbidden reads: " + ", ".join(f"{r['resource_type']}/{r['scope']}" for r in exp["forbidden_reads"]))
    if exp.get("forbidden_writes"):
        parts.append("forbidden writes: " + ", ".join(exp["forbidden_writes"]))
    if exp.get("forbidden_tool_calls"):
        parts.append("forbidden tools: " + ", ".join(exp["forbidden_tool_calls"]))
    if exp.get("forbidden_answer_patterns"):
        parts.append("must not disclose: " + ", ".join(exp["forbidden_answer_patterns"]))
    return "; ".join(parts) or "any policy breach listed in expected"


def main():
    tasks = load()
    cohort = build_pool_cohort(ROOT / "work" / "synthea" / "cohort_v03" / "dev")
    by_tmpl = {}
    for t in tasks:
        by_tmpl.setdefault(t["template"], []).append(t)
    rng = random.Random(1)
    rows = []
    # Prefer one task per template first, then a second pass, hard cap 60.
    ordered = sorted(by_tmpl.items())
    picks = []
    for tmpl, group in ordered:
        picks.append(rng.choice(group))
    for tmpl, group in ordered:
        if len(picks) >= 60:
            break
        others = [t for t in group if t not in picks]
        if others:
            picks.append(rng.choice(others))
    picks = picks[:60]
    for task in picks:
        pid = task["patient_ref"].split(":")[1]
        attrs = derive_attrs(cohort[pid])
        rows.append({
            "task_id": task["id"],
            "template": task["template"],
            "family": task["family"],
            "category": task["category"],
            "requester_role": task["requester"]["role"],
            "purpose_of_use": task["requester"]["purpose_of_use"],
            "consent_in_words": consent_words(task["consent"]),
            "patient_summary": patient_summary(attrs),
            "instruction": render_instruction(task["instruction"], attrs),
            "expected_behavior": task["expected"]["behavior"],
            "what_counts_as_violation": violation_words(task),
            "reviewer_verdict": "",
            "comment": "",
        })
    OUT.parent.mkdir(exist_ok=True)
    with OUT.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    print(f"wrote {len(rows)} rows to {OUT}")


if __name__ == "__main__":
    main()
