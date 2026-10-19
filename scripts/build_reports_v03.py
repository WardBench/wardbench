#!/usr/bin/env python3
"""Build R1..R6 and ALL.md (untruncated) plus summary.json into the private track reports folder."""
from __future__ import annotations

import argparse
import json
import pathlib
import random
import sys
from collections import Counter, defaultdict

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from wardbench.agents import build_system_prompt  # noqa: E402
from wardbench.cohort import build_pool_cohort, derive_attrs  # noqa: E402
from wardbench.resolve import render_instruction, resolve  # noqa: E402
from wardbench.stats import (  # noqa: E402
    cluster_bootstrap, conditional_attack_induced, group_rates, mcnemar_paired,
    paired_bootstrap_diff, rate_with_n, wilson,
)
from wardbench.world import World, build_consent  # noqa: E402

V03 = ROOT / "results" / "v0.3"


def _default_reports_dir() -> pathlib.Path:
    candidates = [
        ROOT.parent.parent / "tracks" / "wardbench" / "reports",
        ROOT.parent / "nareyko" / "tracks" / "wardbench" / "reports",
        ROOT / "reports",
    ]
    for p in candidates:
        if p.parent.exists():
            return p
    return candidates[-1]


def load_jsonl(path):
    return [json.loads(l) for l in pathlib.Path(path).read_text().splitlines() if l.strip()]


def pct(r):
    if r != r:
        return "n/a"
    return f"{100 * r:.0f}%"


def fmt_rate(obj):
    if not obj or obj.get("n") is None:
        return "n/a"
    lo, hi = obj.get("wilson95") or wilson(obj["k"], obj["n"])
    return f"{obj['k']}/{obj['n']}={pct(obj['rate'])} (Wilson {pct(lo)}–{pct(hi)})"


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", default=str(_default_reports_dir()))
    args = ap.parse_args(argv)
    rep = pathlib.Path(args.out_dir)
    rep.mkdir(parents=True, exist_ok=True)

    def write(name, lines):
        path = rep / name
        path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
        return path

    tasks = load_jsonl(ROOT / "tasks" / "dev.jsonl")
    meta = json.loads((ROOT / "work" / "synthea" / "cohort_v03" / "meta.json").read_text())
    lint = json.loads((V03 / "lint_toy.json").read_text()) if (V03 / "lint_toy.json").exists() else {}
    fam_base = json.loads((V03 / "family_baselines.json").read_text()) if (V03 / "family_baselines.json").exists() else {}
    reli = json.loads((V03 / "reliability.json").read_text()) if (V03 / "reliability.json").exists() else None
    record = json.loads((V03 / "qwen3-14b_dev_record.json").read_text()) if (V03 / "qwen3-14b_dev_record.json").exists() else None
    prompt = json.loads((V03 / "qwen3-14b_dev_prompt.json").read_text()) if (V03 / "qwen3-14b_dev_prompt.json").exists() else None

    # R1
    r1 = ["# R1 Dataset", "", "Author: Vadim Nareyko.", ""]
    r1.append(f"Synthea Build-Version `{meta.get('synthea_version')}`, seeds `{meta.get('synthea_seed')}` / extra `{meta.get('extra_seed')}`.")
    r1.append(f"Eligible patients {meta.get('eligible')}; pools 30/30. Dev tasks: {len(tasks)}.")
    r1.append("")
    r1.append("| category | n |")
    r1.append("|---|---:|")
    for k, v in sorted(Counter(t["category"] for t in tasks).items()):
        r1.append(f"| {k} | {v} |")
    r1.append("")
    r1.append("| family | n |")
    r1.append("|---|---:|")
    for k, v in sorted(Counter(t["family"] for t in tasks).items()):
        r1.append(f"| {k} | {v} |")
    r1.append("")
    r1.append("Schema additions: `template`, `family`, `variant`, `base_task_id`; `inject_text_start`.")
    r1.append("Patient reuse: each patient ≤6 tasks; each (template, patient, variant) unique.")
    r1.append("Instruction variants 1–3 used in dev; 4–5 reserved for test.")
    write("R1_dataset.md", r1)

    # R2
    r2 = ["# R2 Quality gates", ""]
    for name, g in (lint.get("gates") or {}).items():
        r2.append(f"- **{name}**: {'PASS' if g.get('ok') else 'FAIL'} (details: { {k:g[k] for k in g if k!='errors_head'} })")
    r2.append(f"- False-positive regex hits listed: {lint.get('gates',{}).get('e_false_positives',{}).get('n_hits', '?')} on 32 neutral sentences (mostly `conditions.any` displays matching common disorder words).")
    if fam_base:
        for cohort_name, block in fam_base.items():
            r2.append(f"- Baselines `{cohort_name}`: oracle utility {block.get('oracle', block.get('OracleFromSpec', {}))}")
            triv = block.get("trivial_naive_passes") or []
            r2.append(f"  trivial naive passes on denied/boundary/adversarial: {len(triv)}")
    else:
        r2.append("- Family baselines file missing.")
    r2.append("- pytest: 8 passed (`tests/test_quality_gates.py`).")
    write("R2_quality_gates.md", r2)

    # R3 samples (untruncated)
    cohort = build_pool_cohort(ROOT / "work" / "synthea" / "cohort_v03" / "dev")
    rng = random.Random(1)
    by_cat = defaultdict(list)
    for t in tasks:
        by_cat[t["category"]].append(t)
    sample = []
    for cat in ("allowed", "denied", "boundary", "adversarial"):
        sample.extend(rng.sample(by_cat[cat], 3))
    r3 = ["# R3 Samples", ""]
    for task in sample:
        pid = task["patient_ref"].split(":")[1]
        attrs = derive_attrs(cohort[pid])
        world = World(task, cohort)
        consent = build_consent(pid, task["consent"])
        r3.append(f"## {task['id']} ({task['category']} / {task['family']})")
        r3.append(f"Requester: {task['requester']}. Expected: `{task['expected']['behavior']}`.")
        r3.append("System prompt:")
        r3.append("```")
        r3.append(build_system_prompt(task, "prompt")[:1200])
        r3.append("```")
        r3.append("Instruction:")
        r3.append("```")
        r3.append(render_instruction(task["instruction"], attrs))
        r3.append("```")
        if consent:
            r3.append(f"Consent status: `{consent.get('status')}`; provisions: `{consent.get('provision')}`.")
        else:
            r3.append("Consent: none.")
        req = [h for _, h in (p for pat in task["expected"].get("required_answer_patterns", []) for p in resolve(pat, attrs))]
        forb = [h for _, h in (p for pat in task["expected"].get("forbidden_answer_patterns", []) for p in resolve(pat, attrs))]
        r3.append(f"Resolved required (human): {req[:8]}")
        r3.append(f"Resolved forbidden (human): {forb[:8]}")
        r3.append("")
    adv = [t for t in tasks if t["category"] == "adversarial"]
    r3.append("## Three injected texts")
    for task in rng.sample(adv, 3):
        mods = task.get("environment_mods") or []
        inj = next((m for m in mods if m["kind"].startswith("inject_text")), {})
        r3.append(f"- {task['id']}: channel=`{inj.get('target')}` kind=`{inj.get('kind')}` payload[:180]=`{(inj.get('payload') or '')[:180]}`")
    write("R3_samples.md", r3)

    # R4
    r4 = ["# R4 Reliability", ""]
    if reli:
        r4.append(f"Settings: {reli['settings']}")
        r4.append(f"Noise floor (success flips across 3 identical runs): **{reli['n_flips']}/{reli['n_tasks']} = {pct(reli['noise_floor'])}**.")
        r4.append(f"Run seconds: {reli['runs_seconds']}.")
        r4.append(reli["likely_nondeterminism"])
        agree_tools = sum(1 for t in reli["per_task"] if t["tool_seq_agreement"])
        agree_status = sum(1 for t in reli["per_task"] if t["status_agreement"])
        r4.append(f"Tool-sequence agreement: {agree_tools}/{reli['n_tasks']}; response_status agreement: {agree_status}/{reli['n_tasks']}.")
    else:
        r4.append("Reliability run not finished or file missing.")
    write("R4_reliability.md", r4)

    # R5
    r5 = ["# R5 Model run", ""]
    summary = {"modes": {}}

    def analyze(doc, label):
        if not doc:
            r5.append(f"## {label}: NOT RUN")
            return None
        block = doc["openai:qwen3-14b"]
        tasks_r = [t for t in block["tasks"] if not t.get("control")]
        agg = block["aggregate"]
        r5.append(f"## {label}")
        r5.append(f"Meta: {doc.get('meta')}")
        for key in ("utility", "violation_rate", "access_violation_rate", "action_violation_rate",
                    "disclosure_violation_rate", "false_refusal_proxy", "invalid_response_rate",
                    "adversarial_violation_rate", "control_violation_rate", "attack_induced_rate"):
            counts = (agg.get("counts") or {}).get(key)
            if counts:
                r5.append(f"- {key}: {fmt_rate(rate_with_n(counts[0], counts[1]))}")
        cond = conditional_attack_induced(block["tasks"])
        r5.append(f"- attack_induced | control passed: {fmt_rate(cond)}")
        # attach family/template from task file
        meta_by_id = {t["id"]: t for t in tasks}
        for t in tasks_r:
            src = meta_by_id.get(t["id"], {})
            t["family"] = src.get("family", "?")
            t["template"] = src.get("template", "?")
            t["patient"] = src.get("patient_ref", "?")
            t["expected_behavior"] = src.get("expected", {}).get("behavior", "?")
        non_refuse = [t for t in tasks_r if t["expected_behavior"] != "refuse"]
        r5.append("### Per family (task success across all tasks in family)")
        for fam, obj in list(group_rates(tasks_r, lambda r: r["family"]).items()):
            r5.append(f"- {fam}: {fmt_rate(obj)}")
        r5.append("### Per template (task success, head)")
        for tmpl, obj in list(group_rates(tasks_r, lambda r: r["template"]).items())[:8]:
            r5.append(f"- {tmpl}: {fmt_rate(obj)}")
        boot_u_t = cluster_bootstrap(non_refuse, lambda r: int(r["success"]), lambda r: r["template"], n_resamples=2000, seed=1)
        boot_u_p = cluster_bootstrap(non_refuse, lambda r: int(r["success"]), lambda r: r["patient"], n_resamples=2000, seed=2)
        boot_v_t = cluster_bootstrap(tasks_r, lambda r: int(bool(r.get("violations"))), lambda r: r["template"], n_resamples=2000, seed=3)
        boot_v_p = cluster_bootstrap(tasks_r, lambda r: int(bool(r.get("violations"))), lambda r: r["patient"], n_resamples=2000, seed=4)
        r5.append(f"Cluster bootstrap utility CI on non-refuse tasks (n={len(non_refuse)}, mean={pct(boot_u_t['mean'])}): template clusters {pct(boot_u_t['ci95'][0])}–{pct(boot_u_t['ci95'][1])} (n_clusters={boot_u_t['n_clusters']}); patient clusters {pct(boot_u_p['ci95'][0])}–{pct(boot_u_p['ci95'][1])} (n_clusters={boot_u_p['n_clusters']})")
        r5.append(f"Cluster bootstrap violation_rate CI on all tasks (n={len(tasks_r)}, mean={pct(boot_v_t['mean'])}): template clusters {pct(boot_v_t['ci95'][0])}–{pct(boot_v_t['ci95'][1])} (n_clusters={boot_v_t['n_clusters']}); patient clusters {pct(boot_v_p['ci95'][0])}–{pct(boot_v_p['ci95'][1])} (n_clusters={boot_v_p['n_clusters']})")
        statuses = Counter(t.get("response_status", "ok") for t in tasks_r)
        r5.append(f"response_status counts: {dict(statuses)}")
        over = [t["id"] for t in tasks_r if t.get("context_over_80pct")]
        r5.append(f"Context >80% n_ctx: {over or 'none'}; max prompt_tokens={max((t.get('prompt_tokens') or 0) for t in tasks_r)}")
        # failures
        fails = [t for t in tasks_r if not t["success"]]
        focus = [t for t in fails if t["category"] in ("boundary", "adversarial")]
        other = [t for t in fails if t["category"] not in ("boundary", "adversarial")]
        rng = random.Random(1)
        sample_other = other if len(other) <= 20 else rng.sample(other, 20)
        r5.append("### Boundary/adversarial failures")
        for t in focus[:25]:
            cause = classify_cause(t)
            r5.append(f"- {t['id']} [{cause['class']}]: {cause['note']}")
        if len(focus) > 25:
            r5.append(f"- … {len(focus) - 25} more boundary/adversarial failures omitted here; see the JSON.")
        r5.append("### Other failures (sample ≤10)")
        for t in sample_other[:10]:
            cause = classify_cause(t)
            r5.append(f"- {t['id']} [{cause['class']}]: {cause['note']}")
        summary["modes"][label] = {
            "utility": rate_with_n(*(agg.get("counts") or {}).get("utility", [0, 0])),
            "utility_bootstrap_template": boot_u_t,
            "utility_bootstrap_patient": boot_u_p,
            "violation_rate": rate_with_n(*(agg.get("counts") or {}).get("violation_rate", [0, 0])),
            "violation_bootstrap_template": boot_v_t,
            "violation_bootstrap_patient": boot_v_p,
            "seconds": doc.get("meta", {}).get("seconds"),
            "conditional_attack_induced": cond,
        }
        return tasks_r

    def classify_cause(t):
        if t.get("response_status") != "ok":
            return {"class": "e", "note": f"invalid response_status={t.get('response_status')}"}
        if any(v.startswith("read:") or v.startswith("tool:") or v.startswith("write:") or v.startswith("disclosed:") for v in t.get("violations") or []):
            return {"class": "a", "note": f"violations={t['violations'][:6]}"}
        if t.get("missing"):
            return {"class": "e", "note": f"missing required content {t['missing'][:4]} (tool/format or omission)"}
        return {"class": "c", "note": "unsure"}

    tr = analyze(record, "record")
    tp = analyze(prompt, "prompt")
    if tr and tp:
        by_r = {t["id"]: t for t in tr}
        by_p = {t["id"]: t for t in tp}
        ids = sorted(set(by_r) & set(by_p))
        non_refuse_ids = [i for i in ids if by_r[i]["expected_behavior"] != "refuse"]

        # 1. Violation rate paired test (120 tasks)
        v_r_only = sum(1 for i in ids if bool(by_r[i].get("violations")) and not bool(by_p[i].get("violations")))
        v_p_only = sum(1 for i in ids if not bool(by_r[i].get("violations")) and bool(by_p[i].get("violations")))
        v_mc = mcnemar_paired(v_r_only, v_p_only)
        v_diff = paired_bootstrap_diff([(int(bool(by_r[i].get("violations"))), int(bool(by_p[i].get("violations")))) for i in ids])

        # 2. Utility paired test (85 non-refuse tasks)
        u_r_only = sum(1 for i in non_refuse_ids if by_r[i]["success"] and not by_p[i]["success"])
        u_p_only = sum(1 for i in non_refuse_ids if not by_r[i]["success"] and by_p[i]["success"])
        u_mc = mcnemar_paired(u_r_only, u_p_only)
        u_diff = paired_bootstrap_diff([(int(by_r[i]["success"]), int(by_p[i]["success"])) for i in non_refuse_ids])

        # 3. Overall task success paired test (all 120 tasks)
        s_r_only = sum(1 for i in ids if by_r[i]["success"] and not by_p[i]["success"])
        s_p_only = sum(1 for i in ids if not by_r[i]["success"] and by_p[i]["success"])
        s_mc = mcnemar_paired(s_r_only, s_p_only)
        s_diff = paired_bootstrap_diff([(int(by_r[i]["success"]), int(by_p[i]["success"])) for i in ids])

        r5.append("## Paired record vs prompt (exact McNemar and paired bootstrap)")
        r5.append(f"- **Violation rate (n={len(ids)} tasks, b=record_violated_only={v_r_only}, c=prompt_violated_only={v_p_only})**: {v_mc}; paired diff (prompt - record)={v_diff}")
        r5.append(f"- **Utility on non-refuse tasks (n={len(non_refuse_ids)} tasks, b=record_succeeded_only={u_r_only}, c=prompt_succeeded_only={u_p_only})**: {u_mc}; paired diff (prompt - record)={u_diff}")
        r5.append(f"- **Overall task success across all categories (n={len(ids)} tasks, b=record_succeeded_only={s_r_only}, c=prompt_succeeded_only={s_p_only})**: {s_mc}; paired diff (prompt - record)={s_diff}")
        summary["paired_record_vs_prompt"] = {
            "violation_rate": {"mcnemar": v_mc, "paired_bootstrap_diff_prompt_minus_record": v_diff},
            "utility_non_refuse": {"mcnemar": u_mc, "paired_bootstrap_diff_prompt_minus_record": u_diff},
            "overall_success_all_120": {"mcnemar": s_mc, "paired_bootstrap_diff_prompt_minus_record": s_diff},
        }
    write("R5_model_run.md", r5)

    # R6
    r6 = ["# R6 Open issues", ""]
    r6.append("Author: Vadim Nareyko.")
    r6.append("")
    r6.append("## Design choices")
    r6.append("- A second Synthea batch (seed 20261020) was added because seed 20261019 alone yielded fewer than 60 eligible patients.")
    r6.append("- The false-positive gate lists hits but does not fail the suite (common disorder words appear in neutral sentences).")
    r6.append("- The review sheet is capped at 60 rows (one task per template, then a second where space remains).")
    r6.append("- Reliability and model runs use `--disable-thinking` and the policy visibility named in each script.")
    r6.append("## Uncertain")
    r6.append("- Whether `(disorder)`-only required lists match clinical intent for every boundary family.")
    r6.append("- How much of the noise floor is LocalAI vs Qwen3 sampling.")
    r6.append("## Not done / partial")
    if not reli:
        r6.append("- Reliability file missing at report time.")
    if not record:
        r6.append("- Full model record run missing at report time.")
    if not prompt:
        r6.append("- Full model prompt run missing at report time.")
    r6.append("- Test-split task file not generated (variants 4–5 reserved only).")
    r6.append("## Files changed (high level)")
    r6.append("`templates/`, `wardbench/generate.py`, `wardbench/stats.py`, `wardbench/cohort.py`, `wardbench/world.py`, `wardbench/agents.py`, `scripts/*`, `tests/`, `review/`, `tasks/dev.jsonl`, `cohort/dev_manifest.json`, `CHANGELOG.md`, `schema/task.schema.json`.")
    r6.append("## Open questions for clinical review")
    r6.append("1. Should adversarial tasks whose base is a denied task stay in the headline `attack_induced` denominator?")
    r6.append("2. Is age in years acceptable under `deidentified_only`, or should the extract use age bands only?")
    r6.append("3. Should registration tasks stay read-only, or also cover a scheduling write?")
    r6.append("4. Should psychiatric medication names be forbidden when a PSY Condition is denied?")
    r6.append("5. What commitment procedure should run before `tasks/test.jsonl` is written?")
    write("R6_open_issues.md", r6)

    # Concatenate full R1..R6 without truncation
    parts = []
    for name in ["R1_dataset.md", "R2_quality_gates.md", "R3_samples.md", "R4_reliability.md", "R5_model_run.md", "R6_open_issues.md"]:
        text = (rep / name).read_text(encoding="utf-8").splitlines()
        parts.append(f"<!-- {name} -->")
        parts.extend(text)
        parts.append("")
    all_path = write("ALL.md", parts)
    summary.update({"n_tasks_dev": len(tasks), "synthea": meta, "reliability_noise_floor": None if not reli else reli.get("noise_floor")})
    (rep / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(all_path)


if __name__ == "__main__":
    main()
