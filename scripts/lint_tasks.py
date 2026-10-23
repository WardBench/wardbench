#!/usr/bin/env python3
"""Quality gates for WardBench task files."""
from __future__ import annotations

import argparse
import collections
import json
import pathlib
import re
import sys

from jsonschema import Draft202012Validator

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from wardbench.cohort import build_cohort, build_pool_cohort, derive_attrs  # noqa: E402
from wardbench.grade import grade  # noqa: E402
from wardbench.resolve import resolve  # noqa: E402
from wardbench.world import World  # noqa: E402

FORBIDDEN_WORDS = re.compile(
    r"\b(consent|opt-?out|policy|policies|TREAT|HRESCH|HPAYMT|HOPERAT|PATRQT|"
    r"physician|nurse|researcher|billing|registration|related[_\s-]?person)\b",
    re.IGNORECASE,
)
NEUTRAL_ANSWERS = [
    "I can't help with that request.",
    "Done.",
    "The chart was reviewed; no further action is needed today.",
]
NEUTRAL_SENTENCES_PATH = ROOT / "tests" / "data" / "neutral_clinical_sentences.txt"


def load_tasks(path: pathlib.Path):
    text = path.read_text(encoding="utf-8").strip()
    if text.startswith("["):
        return json.loads(text)
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def gate_schema(tasks, schema):
    validator = Draft202012Validator(schema)
    errors = []
    seen = set()
    triples = set()
    for task in tasks:
        tid = task.get("id", "?")
        for err in validator.iter_errors(task):
            errors.append(f"[{tid}] {'/'.join(map(str, err.absolute_path))}: {err.message}")
        if tid in seen:
            errors.append(f"[{tid}] duplicate id")
        seen.add(tid)
        if task.get("template") is not None:
            key = (task["template"], task["patient_ref"], task.get("variant"))
            if key in triples:
                errors.append(f"[{tid}] duplicate (template, patient, variant)={key}")
            triples.add(key)
    return errors


def gate_instructions(tasks):
    errors = []
    for task in tasks:
        text = task["instruction"]
        if FORBIDDEN_WORDS.search(text):
            # Allow {{pt...}} placeholders; still ban the listed tokens.
            errors.append(f"[{task['id']}] instruction has forbidden vocabulary")
        for pat in task["expected"].get("required_answer_patterns", []):
            if "{{" not in pat and len(pat) > 6 and pat.lower() in text.lower():
                errors.append(f"[{task['id']}] instruction may leak required pattern {pat!r}")
    return errors


def _resolved(task, attrs):
    exp = task["expected"]
    return {
        "required": [p for pat in exp.get("required_answer_patterns", []) for p in resolve(pat, attrs)],
        "forbidden": [
            p for pat in exp.get("forbidden_answer_patterns", [])
            for p in resolve(pat, attrs, strict=True)
        ],
    }


def gate_null_and_leaky(tasks, cohort):
    errors = []
    for task in tasks:
        world = World(task, cohort)
        attrs = derive_attrs(cohort[world.subject])
        resolved = _resolved(task, attrs)
        for ans in NEUTRAL_ANSWERS:
            res = grade(task, world, ans, resolved)
            if any(v.startswith("disclosed:") for v in res["violations"]):
                errors.append(f"[{task['id']}] neutral answer matched a forbidden pattern: {ans!r}")
            if task["expected"]["behavior"] != "refuse" and res["success"] and not res["missing"]:
                # Success with a neutral sentence means required patterns are too weak.
                if task["expected"].get("required_answer_patterns"):
                    errors.append(f"[{task['id']}] neutral answer satisfied required patterns: {ans!r}")
        if resolved["forbidden"]:
            # Deduplicate by human string: expanders like conditions.any can
            # emit the same display twice; the grader records one disclosed:* hit.
            humans = list(dict.fromkeys(human for _, human in resolved["forbidden"]))
            leaky = " ".join(humans)
            res = grade(task, world, leaky, resolved)
            disclosed = {v.split(":", 1)[1] for v in res["violations"] if v.startswith("disclosed:")}
            missing = [h for h in humans if h not in disclosed]
            if missing:
                errors.append(
                    f"[{task['id']}] leaky answer missed some forbidden patterns "
                    f"({len(humans) - len(missing)}/{len(humans)}; e.g. {missing[0]!r})"
                )
    return errors


def gate_false_positives(tasks, cohort, sentences):
    hits = []
    for task in tasks:
        world = World(task, cohort)
        attrs = derive_attrs(cohort[world.subject])
        resolved = _resolved(task, attrs)
        for sentence in sentences:
            for rx, human in resolved["forbidden"]:
                if re.search(rx, sentence, re.IGNORECASE):
                    hits.append({"task": task["id"], "pattern": human, "sentence": sentence})
    return hits


def coverage_matrix(tasks):
    cells = collections.Counter()
    for task in tasks:
        key = (
            task.get("family", "?"),
            task["requester"]["role"],
            task["requester"]["purpose_of_use"],
            task["consent"]["state"],
        )
        cells[key] += 1
    return cells


def _resolve_cohort(name: str):
    if name == "toy":
        return build_cohort(30)
    if name == "dev_pool":
        return build_pool_cohort(ROOT / "work" / "synthea" / "cohort_v03" / "dev")
    if name == "test_pool":
        candidates = [
            ROOT.parent.parent / "tracks" / "wardbench" / "heldout" / "test_pool",
            ROOT / "cohort" / "test",
        ]
        for path in candidates:
            if path.is_dir() and any(path.glob("*.json")):
                return build_pool_cohort(path)
        raise SystemExit(
            "test_pool not found under tracks/wardbench/heldout/test_pool or cohort/test"
        )
    path = pathlib.Path(name)
    if path.is_dir():
        return build_pool_cohort(path)
    raise SystemExit(f"unknown cohort {name!r}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("tasks", nargs="+")
    ap.add_argument(
        "--cohort",
        default="toy",
        help="toy | dev_pool | test_pool | path to a pool directory",
    )
    ap.add_argument("--json-out", default=None)
    args = ap.parse_args()
    schema = json.loads((ROOT / "schema" / "task.schema.json").read_text(encoding="utf-8"))
    tasks = []
    for path in args.tasks:
        tasks.extend(load_tasks(pathlib.Path(path)))
    cohort = _resolve_cohort(args.cohort)

    report = {"gates": {}, "false_positives": [], "coverage_empty": [], "trivial_naive": []}
    e = gate_schema(tasks, schema)
    report["gates"]["a_schema"] = {"ok": not e, "errors": e[:20], "n_errors": len(e)}
    e = gate_instructions(tasks)
    report["gates"]["b_instructions"] = {"ok": not e, "errors": e[:20], "n_errors": len(e)}
    e = gate_null_and_leaky(tasks, cohort)
    report["gates"]["c_d_null_leaky"] = {"ok": not e, "errors": e[:20], "n_errors": len(e)}
    sentences = [ln.strip() for ln in NEUTRAL_SENTENCES_PATH.read_text(encoding="utf-8").splitlines() if ln.strip()]
    hits = gate_false_positives(tasks, cohort, sentences)
    report["false_positives"] = hits
    # Listing hits is the gate; zero hits is ideal but not required to proceed.
    report["gates"]["e_false_positives"] = {
        "ok": len(sentences) >= 30,
        "n_hits": len(hits),
        "n_sentences": len(sentences),
    }
    cov = coverage_matrix(tasks)
    report["gates"]["f_coverage"] = {"n_cells": len(cov), "ok": True}
    report["coverage"] = {str(k): v for k, v in cov.items()}

    print(json.dumps({k: {kk: vv for kk, vv in g.items() if kk != "errors"} | {"errors_head": g.get("errors", [])[:5]}
                      for k, g in report["gates"].items()}, indent=2))
    if hits:
        print(f"false-positive hits: {len(hits)}")
        for h in hits[:10]:
            print(f"  {h['task']}: {h['pattern']!r} in {h['sentence']!r}")
    failed = any(not g["ok"] for g in report["gates"].values())
    if args.json_out:
        pathlib.Path(args.json_out).write_text(json.dumps(report, indent=2), encoding="utf-8")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
