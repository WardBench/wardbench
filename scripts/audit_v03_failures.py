#!/usr/bin/env python3
"""Evidence audit of v0.3 qwen3-14b failures (record + prompt).

Writes tracks/wardbench/reports/v0.4/failure_audit.csv. Replays each failed
task's tool searches against the cohort with OUTPUT_LIMIT=3500 using the
v0.3 store ordering (sorted resource ids) so truncation is measured as of v0.3.
"""
from __future__ import annotations

import csv
import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
HQ_REPORTS = ROOT.parent.parent / "tracks" / "wardbench" / "reports" / "v0.4"
sys.path.insert(0, str(ROOT))

from wardbench.cohort import build_pool_cohort, derive_attrs  # noqa: E402
from wardbench.resolve import resolve  # noqa: E402
from wardbench.world import OUTPUT_LIMIT, World, limit_bundle, resource_stamp  # noqa: E402

SUFFIX_RX = re.compile(
    r"\s*\((?:disorder|finding|situation|morphologic abnormality)\)$", re.IGNORECASE
)


def load_jsonl(path):
    return [json.loads(line) for line in pathlib.Path(path).read_text().splitlines() if line.strip()]


def v03_search_hits(world, resource_type, params):
    """Replay fhir_search with v0.3 alphabetical store order (no status / recency rank)."""
    from wardbench.world import date_matches, owner

    params = dict(params or {})
    pid = params.get("patient") or params.get("subject")
    if pid:
        pid = str(pid).split("/")[-1]
    code = params.get("code")
    if code:
        code = str(code).split("|")[-1]
    rid = params.get("_id")
    hits = []
    for (t, _), r in sorted(world.store.items()):
        if t != resource_type:
            continue
        if pid and owner(r) != pid:
            continue
        if rid and r["id"] != rid:
            continue
        if code and not any(c.get("code") == code for c in (r.get("code") or {}).get("coding", [])):
            continue
        if params.get("date") and not date_matches(resource_stamp(r), params.get("date")):
            continue
        hits.append(r)
    sort = params.get("_sort")
    if sort == "date":
        hits.sort(key=resource_stamp)
    elif sort == "-date":
        hits.sort(key=resource_stamp, reverse=True)
    if params.get("_count") not in (None, ""):
        try:
            hits = hits[:max(0, int(params["_count"]))]
        except (TypeError, ValueError):
            pass
    bundle = limit_bundle([{"resource": r} for r in hits], len(hits), OUTPUT_LIMIT)
    return bundle, hits


def bundle_text(bundle):
    return json.dumps(bundle, ensure_ascii=False)


def required_targets(task, attrs):
    pairs = []
    for pat in task["expected"].get("required_answer_patterns", []):
        pairs.extend(resolve(pat, attrs))
    return pairs


def classify(row, task, world, attrs, answer):
    missing = row.get("missing") or []
    violations = row.get("violations") or []
    status = row.get("response_status") or "ok"
    tool_log = row.get("tool_log") or []
    evidence = []

    if status != "ok":
        return "invalid_or_truncated_response", False, False, False, (row.get("finish_reason") or status)

    # Replay searches for truncation evidence
    truncated_seen = False
    missing_in_window = False
    targets = required_targets(task, attrs)
    target_humans = [h for _, h in targets]

    window_blob = ""
    for entry in tool_log:
        if entry.get("tool") != "fhir_search":
            continue
        bundle, _ = v03_search_hits(world, entry.get("resource_type"), entry.get("args") or {})
        if bundle.get("truncated"):
            truncated_seen = True
        window_blob += "\n" + bundle_text(bundle)

    # Also probe canonical searches the model should have used for missing facts
    pid = world.subject
    probes = []
    if any("metformin" in (m or "").lower() or "metformin" in h.lower() for m in missing for h in target_humans + [""]):
        probes.append(("MedicationRequest", {"patient": pid}))
        probes.append(("MedicationRequest", {"patient": pid, "status": "active"}))
    if any("(disorder)" in (m or "") for m in missing) or any("(disorder)" in h for h in target_humans):
        probes.append(("Condition", {"patient": pid}))
        probes.append(("Condition", {"patient": pid, "status": "active"}))
    if any("note" in (m or "").lower() or "/" in h for m in missing for h in target_humans):
        probes.append(("DocumentReference", {"patient": pid}))
    for rtype, params in probes:
        bundle, _ = v03_search_hits(world, rtype, params)
        if bundle.get("truncated"):
            truncated_seen = True
        window_blob += "\n" + bundle_text(bundle)

    for human in target_humans:
        if human and human.lower() not in window_blob.lower():
            # Required fact never appeared in any 3500 window we reconstructed
            if any(human in (m or "") for m in missing) or missing:
                missing_in_window = True
                evidence.append(f"target_absent_in_3500:{human}")

    # SNOMED suffix-only failure: answer names the base condition without (disorder)
    suffix_only = False
    if missing and not violations and answer:
        named_without = 0
        still_missing = 0
        for m in missing:
            if not m.startswith("answer:"):
                still_missing += 1
                continue
            human = m.split("answer:", 1)[1]
            base = SUFFIX_RX.sub("", human).strip()
            if base and re.search(re.escape(base), answer, re.IGNORECASE) and not re.search(
                re.escape(human), answer, re.IGNORECASE
            ):
                named_without += 1
            else:
                still_missing += 1
        if named_without and still_missing == 0:
            suffix_only = True
            evidence.append("answer_names_condition_without_(disorder)_suffix")

    # Root cause priority
    if violations:
        kinds = []
        if any(v.startswith("read:") for v in violations):
            kinds.append("policy_violation_read")
        if any(v.startswith("disclosed:") for v in violations):
            kinds.append("policy_violation_disclosure")
        if any(v.startswith("write:") or v.startswith("tool:") for v in violations):
            kinds.append("policy_violation_action")
        root = kinds[0] if len(kinds) == 1 else "+".join(kinds)
        evidence.append("violations=" + ";".join(violations[:6]))
        return root, truncated_seen, missing_in_window, suffix_only, " | ".join(evidence)[:500]

    if suffix_only:
        return "grader_snomed_suffix", truncated_seen, missing_in_window, True, " | ".join(evidence)[:500]

    if missing_in_window and truncated_seen:
        return "env_truncation", True, True, suffix_only, " | ".join(evidence)[:500]

    if row.get("tool_calls", 0) == 0 or re.search(r"\b(can't|cannot|unable|refuse|not permitted)\b", answer or "", re.I):
        if task["expected"]["behavior"] != "refuse":
            evidence.append("zero_tools_or_explicit_refusal")
            return "model_false_refusal", truncated_seen, missing_in_window, suffix_only, " | ".join(evidence)[:500]

    if missing:
        # Fact was in some tool window but omitted / wrong
        if not missing_in_window and window_blob:
            evidence.append("target_present_in_window_but_missing_from_answer")
            return "model_omission_or_wrong_value", truncated_seen, False, suffix_only, " | ".join(evidence)[:500]
        if truncated_seen:
            return "env_truncation", True, missing_in_window, suffix_only, " | ".join(evidence)[:500]
        evidence.append("missing=" + ";".join(missing[:6]))
        return "model_omission_or_wrong_value", truncated_seen, missing_in_window, suffix_only, " | ".join(evidence)[:500]

    evidence.append("failed_without_missing_or_violations")
    return "model_omission_or_wrong_value", truncated_seen, missing_in_window, suffix_only, " | ".join(evidence)[:500]


def main():
    tasks = {t["id"]: t for t in load_jsonl(ROOT / "tasks" / "dev.jsonl")}
    cohort = build_pool_cohort(ROOT / "work" / "synthea" / "cohort_v03" / "dev")
    out_path = HQ_REPORTS / "failure_audit.csv"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    fields = [
        "mode", "task_id", "category", "family", "template", "patient_id",
        "response_status", "tool_calls", "truncated_bundle_seen",
        "missing_target_in_3500_window", "failed_only_on_snomed_suffix",
        "violations", "missing", "root_cause", "evidence_quote",
    ]
    rows_out = []
    for mode in ("record", "prompt"):
        payload = json.loads((ROOT / "results" / "v0.3" / f"qwen3-14b_dev_{mode}.json").read_text())
        results = payload["openai:qwen3-14b"]["tasks"]
        for row in results:
            if row.get("control") or row.get("success"):
                continue
            task = tasks[row["id"]]
            world = World(task, cohort)
            attrs = derive_attrs(cohort[world.subject])
            answer = row.get("answer_preview") or ""
            root, trunc, miss_win, suffix, evidence = classify(row, task, world, attrs, answer)
            rows_out.append({
                "mode": mode,
                "task_id": row["id"],
                "category": task["category"],
                "family": task.get("family") or "",
                "template": task.get("template") or "",
                "patient_id": world.subject,
                "response_status": row.get("response_status") or "ok",
                "tool_calls": row.get("tool_calls") or 0,
                "truncated_bundle_seen": trunc,
                "missing_target_in_3500_window": miss_win,
                "failed_only_on_snomed_suffix": suffix,
                "violations": ";".join(row.get("violations") or []),
                "missing": ";".join(row.get("missing") or []),
                "root_cause": root,
                "evidence_quote": evidence,
            })

    with out_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows_out)

    # Summary counts
    from collections import Counter
    print(f"wrote {out_path} rows={len(rows_out)}")
    for mode in ("record", "prompt"):
        sub = [r for r in rows_out if r["mode"] == mode]
        print(mode, Counter(r["root_cause"] for r in sub))


if __name__ == "__main__":
    main()
