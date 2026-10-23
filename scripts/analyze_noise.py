#!/usr/bin/env python3
"""Turn-by-turn (tool-step) noise divergence across reliability_raw runs (no LLM).

Compares results/v0.3/reliability_raw/run{1,2,3}.json with reliability.json.
Writes tracks/wardbench/reports/v0.4/R5_noise_analysis.md.

Note: raw run1.json on disk is a *different* 20-task subset than run2/run3 and
than reliability.json. Analysis uses run2+run3 for the official cohort and flags
the integrity gap. "Turn" = tool_log step index (LLM turns were not persisted).
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys
from collections import Counter

ROOT = pathlib.Path(__file__).resolve().parent.parent
RAW = ROOT / "results" / "v0.3" / "reliability_raw"
RELI = ROOT / "results" / "v0.3" / "reliability.json"


def _default_out() -> pathlib.Path:
    return ROOT.parent.parent / "tracks" / "wardbench" / "reports" / "v0.4" / "R5_noise_analysis.md"


def load_run(path: pathlib.Path):
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, list):
        return data
    for key, val in data.items():
        if key != "meta" and isinstance(val, dict) and "tasks" in val:
            return val["tasks"]
        if key != "meta" and isinstance(val, list):
            return val
    raise SystemExit(f"unrecognized run format: {path}")


def tool_seq(row):
    out = []
    for e in row.get("tool_log") or []:
        args = e.get("args") or {}
        out.append({
            "tool": e.get("tool"),
            "resource_type": e.get("resource_type"),
            "args": args,
            "args_json": json.dumps(args, sort_keys=True, ensure_ascii=False),
        })
    return out


def first_tool_divergence(seqs):
    """seqs: list of tool_seq lists. Return (step, kind, detail) or None if all equal."""
    n = max((len(s) for s in seqs), default=0)
    for i in range(n):
        steps = []
        for s in seqs:
            steps.append(s[i] if i < len(s) else None)
        # length mismatch at this index
        if any(st is None for st in steps) and any(st is not None for st in steps):
            return {
                "step": i,
                "kind": "tool_seq_length",
                "detail": f"lengths={[len(s) for s in seqs]}",
                "quotes": [
                    _quote_step(st) if st else "(no tool at this step)"
                    for st in steps
                ],
            }
        names = [st["tool"] for st in steps]
        if len(set(names)) > 1:
            return {
                "step": i,
                "kind": "tool_name",
                "detail": f"names={names}",
                "quotes": [_quote_step(st) for st in steps],
            }
        rtypes = [st["resource_type"] for st in steps]
        if len(set(rtypes)) > 1:
            return {
                "step": i,
                "kind": "tool_resource_type",
                "detail": f"resource_types={rtypes}",
                "quotes": [_quote_step(st) for st in steps],
            }
        # argument key diffs
        arg_kinds = _arg_diff_kind(steps)
        if arg_kinds:
            return {
                "step": i,
                "kind": f"tool_args:{arg_kinds}",
                "detail": arg_kinds,
                "quotes": [_quote_step(st) for st in steps],
            }
        aj = [st["args_json"] for st in steps]
        if len(set(aj)) > 1:
            return {
                "step": i,
                "kind": "tool_args:other",
                "detail": "args JSON differ",
                "quotes": [_quote_step(st) for st in steps],
            }
    return None


def _arg_diff_kind(steps) -> str:
    keys_of_interest = ("_sort", "_count", "code", "patient", "subject", "status", "_id", "date")
    hit = []
    for key in keys_of_interest:
        vals = [json.dumps((st["args"] or {}).get(key), sort_keys=True) for st in steps]
        if len(set(vals)) > 1:
            hit.append(f"{key}={vals}")
    return "; ".join(hit)


def _quote_step(st) -> str:
    if not st:
        return "(none)"
    return f"{st['tool']} {st.get('resource_type') or ''} {st['args_json']}"[:180]


def answer_div(rows):
    texts = [(r.get("answer") or r.get("answer_preview") or "") for r in rows]
    if len(set(texts)) <= 1:
        return None
    return {
        "kind": "final_answer_text",
        "quotes": [t[:160].replace("\n", " ") for t in texts],
    }


def reasoning_div(rows):
    texts = [(r.get("reasoning") or "") for r in rows]
    # Ignore empty-all
    if not any(texts):
        return None
    if len(set(texts)) <= 1:
        return None
    return {
        "kind": "reasoning",
        "quotes": [t[:160].replace("\n", " ") for t in texts],
    }


def classify_task(tid, rows_by_run, reli_row):
    """rows_by_run: dict run_label -> row or None."""
    available = {k: v for k, v in rows_by_run.items() if v is not None}
    labels = sorted(available)
    rows = [available[k] for k in labels]
    seqs = [tool_seq(r) for r in rows]
    tool_equal = all(s == seqs[0] for s in seqs)
    div = None if tool_equal else first_tool_divergence(seqs)
    ans = answer_div(rows)
    rea = reasoning_div(rows)

    # Prefer first divergence: tool step, else reasoning, else answer
    if div:
        primary = div
        primary_source = "tool_log"
    elif rea:
        primary = {"step": None, **rea}
        primary_source = "reasoning"
    elif ans:
        primary = {"step": None, **ans}
        primary_source = "final_answer"
    else:
        primary = {"step": None, "kind": "none_in_available_runs", "quotes": [], "detail": ""}
        primary_source = "none"

    successes = [bool(r["success"]) for r in rows]
    return {
        "id": tid,
        "family": (reli_row or {}).get("family") or rows[0].get("category"),
        "runs_available": labels,
        "reli_successes": (reli_row or {}).get("successes"),
        "reli_tool_seq_agreement": (reli_row or {}).get("tool_seq_agreement"),
        "reli_success_agreement": (reli_row or {}).get("success_agreement"),
        "available_successes": successes,
        "available_tool_seq_agreement": tool_equal,
        "primary_source": primary_source,
        "primary_kind": primary.get("kind"),
        "first_step": primary.get("step"),
        "detail": primary.get("detail") or "",
        "quotes": primary.get("quotes") or [],
        "answer_also_differs": bool(ans) if div else False,
        "reasoning_also_differs": bool(rea),
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default=str(_default_out()))
    args = ap.parse_args(argv)
    out = pathlib.Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)

    for i in (1, 2, 3):
        if not (RAW / f"run{i}.json").exists():
            raise SystemExit(f"missing {RAW / f'run{i}.json'}")
    if not RELI.exists():
        raise SystemExit(f"missing {RELI}")

    run_lists = {f"run{i}": load_run(RAW / f"run{i}.json") for i in (1, 2, 3)}
    by = {label: {r["id"]: r for r in rows} for label, rows in run_lists.items()}
    id_sets = {label: set(m) for label, m in by.items()}
    reli = json.loads(RELI.read_text(encoding="utf-8"))
    reli_by = {t["id"]: t for t in reli["per_task"]}
    reli_ids = set(reli_by)

    # Integrity
    r1_vs_reli = id_sets["run1"] == reli_ids
    r2_vs_reli = id_sets["run2"] == reli_ids
    r3_vs_reli = id_sets["run3"] == reli_ids
    aligned = r1_vs_reli and r2_vs_reli and r3_vs_reli
    shared_all = id_sets["run1"] & id_sets["run2"] & id_sets["run3"]
    subset_lock_path = RAW / "subset_ids.json"
    subset_lock = (
        json.loads(subset_lock_path.read_text(encoding="utf-8"))
        if subset_lock_path.exists() else None
    )

    disagree = [t for t in reli["per_task"] if not t["tool_seq_agreement"]]
    flips = [t for t in reli["per_task"] if not t["success_agreement"]]

    # Official cohort analysis on run2+run3 (+ run1 when present)
    analyses = []
    for t in reli["per_task"]:
        tid = t["id"]
        rows = {
            "run1": by["run1"].get(tid),
            "run2": by["run2"].get(tid),
            "run3": by["run3"].get(tid),
        }
        analyses.append(classify_task(tid, rows, t))

    focus_ids = {t["id"] for t in disagree} | {t["id"] for t in flips}
    focus = [a for a in analyses if a["id"] in focus_ids]
    kind_counts = Counter(a["primary_kind"] for a in focus)

    lines = [
        "# R5 — Turn-by-turn noise divergence audit (v0.4 / S5)",
        "",
        "Date: 2026-10-21.",
        "",
        "Source: `results/v0.3/reliability_raw/run{1,2,3}.json` + `reliability.json`.",
        "Settings (from reliability.json): "
        f"`{reli.get('settings')}`; noise floor **{reli.get('n_flips')}/{reli.get('n_tasks')} = "
        f"{100 * reli.get('noise_floor', float('nan')):.0f}%**; "
        f"tool-seq agreement was reported as "
        f"{sum(1 for t in reli['per_task'] if t['tool_seq_agreement'])}/20.",
        "",
        "## Data integrity finding",
        "",
        f"| file | n tasks | IDs match `reliability.json`? |",
        f"|---|---:|---|",
        f"| run1.json | {len(id_sets['run1'])} | **{'yes' if r1_vs_reli else 'NO'}** |",
        f"| run2.json | {len(id_sets['run2'])} | {'yes' if r2_vs_reli else 'NO'} |",
        f"| run3.json | {len(id_sets['run3'])} | {'yes' if r3_vs_reli else 'NO'} |",
        "",
        f"- run1 category mix: `{Counter(r['category'] for r in run_lists['run1'])}`",
        f"- run2 category mix: `{Counter(r['category'] for r in run_lists['run2'])}`",
        f"- Intersection of all three ID sets: **{len(shared_all)}** tasks "
        f"(`{sorted(shared_all)}`).",
        f"- `subset_ids.json` present: **{'yes' if subset_lock else 'no'}**"
        + (f" (n={len(subset_lock.get('ids', []))})" if subset_lock else "") + ".",
        "",
    ]

    if aligned:
        lines.extend([
            "All three raw runs match `reliability.json` IDs. "
            "Three-way tool-sequence comparison is valid for every task.",
            "",
        ])
    else:
        lines.extend([
            "`reliability.json` successes slot `[1]` / `[2]` match run2 / run3 when "
            "those files share the cohort. If run1 IDs differ, slot `[0]` tool logs "
            "are not on disk for the reliability cohort (historical overwrite).",
            "",
            "**Implication:** side-by-side quotes use whichever runs share the "
            "reliability ID set; tasks that only disagreed vs a missing run1 cannot "
            "be fully reconstructed.",
            "",
        ])

    lines.extend([
        "## Focus set (from reliability.json)",
        "",
        f"- tool_seq_agreement=False: **{len(disagree)}** — "
        f"`{[t['id'] for t in disagree]}`",
        f"- success flip: **{len(flips)}** — `{[t['id'] for t in flips]}`",
        "",
    ])

    if not focus:
        lines.extend([
            "No diverging tasks in the current reliability summary "
            "(tool sequences and successes agree across all three runs).",
            "",
        ])
    else:
        lines.extend([
            "### First divergence summary (available runs)",
            "",
            "| id | flip? | runs | first step | kind | detail |",
            "|---|---|---|---:|---|---|",
        ])
        flip_ids = {t["id"] for t in flips}
        for a in focus:
            lines.append(
                f"| {a['id']} | {'Y' if a['id'] in flip_ids else ''} | "
                f"{'+'.join(a['runs_available'])} | "
                f"{a['first_step'] if a['first_step'] is not None else '—'} | "
                f"{a['primary_kind']} | {a['detail'][:80]} |"
            )
        lines.extend([
            "",
            f"Kind counts on focus set: `{dict(kind_counts)}`.",
            "",
            "### Side-by-side quotes",
            "",
        ])
        for a in focus:
            lines.append(
                f"#### {a['id']} ({a['family']}) — `{a['primary_kind']}` "
                f"at step {a['first_step']}"
            )
            lines.append("")
            lines.append(
                f"reliability successes={a['reli_successes']}; "
                f"available successes={a['available_successes']}; "
                f"reli tool_seq_agree={a['reli_tool_seq_agreement']}; "
                f"available tool_seq_agree={a['available_tool_seq_agreement']}."
            )
            if a["primary_kind"] == "none_in_available_runs":
                lines.append(
                    "Available runs' tool sequences match; divergence (if any) was "
                    "against a missing/misaligned run file."
                )
            else:
                for label, quote in zip(a["runs_available"], a["quotes"]):
                    lines.append(f"- **{label}:** `{quote}`")
            if a["id"] in flip_ids or a["answer_also_differs"]:
                lines.append("Answer previews:")
                for label in a["runs_available"]:
                    row = by[label][a["id"]]
                    prev = (row.get("answer") or row.get("answer_preview") or "")[:160].replace("\n", " ")
                    lines.append(f"- **{label}** success={row['success']}: `{prev}`")
            lines.append("")

    # Full 20: where do run2/run3 already diverge?
    r2r3_disagree = []
    for tid in sorted(reli_ids):
        if tid not in by["run2"] or tid not in by["run3"]:
            continue
        s2 = tool_seq(by["run2"][tid])
        s3 = tool_seq(by["run3"][tid])
        if s2 != s3:
            d = first_tool_divergence([s2, s3])
            r2r3_disagree.append((tid, d))

    lines.extend([
        "## run2 vs run3 (same cohort, n=20)",
        "",
        f"Tool-sequence disagreements between run2 and run3 alone: "
        f"**{len(r2r3_disagree)}/20**.",
        "",
    ])
    if r2r3_disagree:
        lines.append("| id | first step | kind |")
        lines.append("|---|---:|---|")
        for tid, d in r2r3_disagree:
            lines.append(f"| {tid} | {d['step']} | {d['kind']} |")
        lines.append("")
    else:
        lines.append("None.")
        lines.append("")

    # Shared-all three-way
    three_way_disagree = []
    lines.extend([
        f"## Tasks present in all three raw files (n={len(shared_all)})",
        "",
    ])
    if shared_all:
        lines.append("| id | 3-way tool agree | first kind |")
        lines.append("|---|---|---|")
        for tid in sorted(shared_all):
            rows = {f"run{i}": by[f"run{i}"][tid] for i in (1, 2, 3)}
            a = classify_task(tid, rows, reli_by.get(tid))
            lines.append(
                f"| {tid} | {a['available_tool_seq_agreement']} | {a['primary_kind']} |"
            )
            if not a["available_tool_seq_agreement"]:
                three_way_disagree.append(a)
        lines.append("")
    else:
        lines.append("None.")
        lines.append("")

    n_flip = reli.get("n_flips", len(flips))
    n_tasks = reli.get("n_tasks", 20)
    floor_pct = 100 * (n_flip / n_tasks) if n_tasks else float("nan")
    lines.extend([
        "## Mechanisms",
        "",
    ])
    if aligned and not disagree and not flips:
        lines.extend([
            "With an aligned locked subset (`subset_ids.json`) and three fresh passes, "
            "**no tool-sequence or success disagreements** were observed at "
            "`temperature=0, seed=1`. Residual reasoning-channel text may still differ "
            "across runs but is not graded.",
            "",
            "Earlier (pre-S5b) disagreements were measured on a **misaligned raw cohort** "
            "(run1 stratified 5×4 vs run2/run3 adversarial-heavy) and must not be cited "
            "as the noise floor for the locked subset.",
            "",
        ])
    else:
        lines.extend([
            "1. **Tool-argument nondeterminism at temperature=0** — same tool name, "
            "different `_sort` / `_count` / `code` / empty vs populated params.",
            "2. **Tool-sequence length** — one run stops earlier than another.",
            "3. **Misaligned raw files** — if run1 IDs differ, three-way quotes are incomplete.",
            "",
            "LLM `reasoning` channels may differ even when tools match; they are not "
            "the graded answer.",
            "",
        ])

    lines.extend([
        "## Verdict",
        "",
        f"Noise floor: **{n_flip}/{n_tasks} = {floor_pct:.0f}%** success flips. "
        f"Tool-seq disagreement: **{len(disagree)}/{n_tasks}** in reliability.json; "
        f"**{len(r2r3_disagree)}/20** between run2 and run3; "
        f"**{len(three_way_disagree)}/{len(shared_all)}** three-way among shared IDs.",
        "",
    ])
    if aligned and not disagree and not flips:
        lines.append(
            "Aligned re-run (S5b): bit-stable tool sequences on this stratified "
            "20-task lock under the stated LocalAI settings. Cite **0/20** as the "
            "current reliability floor for this subset; keep the pre-S5b 5%/7-disagree "
            "episode only as a data-integrity cautionary tale."
        )
    elif not aligned:
        lines.append(
            "**Blocker for a complete 3-way quote audit:** restore or re-run "
            "reliability with three aligned raw files (S5b)."
        )
    else:
        lines.append(
            "First divergences (when present) are typically tool args / resource type "
            "/ sequence length, not final-answer-only drift."
        )
    lines.extend([
        "",
        "## Files",
        "",
        "- `repos/wardbench/scripts/analyze_noise.py`",
        "- `repos/wardbench/results/v0.3/reliability.json`",
        "- `repos/wardbench/results/v0.3/reliability_raw/run{1,2,3}.json`",
        "- `repos/wardbench/results/v0.3/reliability_raw/subset_ids.json`",
        "",
    ])

    out.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    print(f"wrote {out}")
    print("integrity run1_match", r1_vs_reli, "run2_match", r2_vs_reli, "run3_match", r3_vs_reli)
    print("focus kinds", dict(kind_counts))
    print("r2r3_disagree", len(r2r3_disagree))
    for a in focus:
        print(a["id"], a["primary_kind"], "step", a["first_step"], "runs", a["runs_available"])


if __name__ == "__main__":
    main()
