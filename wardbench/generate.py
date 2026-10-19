"""Expand hand-written YAML templates into WardBench task JSONL."""
from __future__ import annotations

import argparse
import json
import pathlib
import random
import sys

import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
PREFIX = {"allowed": "A", "denied": "D", "boundary": "B", "adversarial": "ADV"}
CHANNEL_TARGET = {
    "latest_note": {
        "resource_type": "DocumentReference", "selector": "latest",
        "field": "content.attachment.data",
    },
    "older_note": {
        "resource_type": "DocumentReference", "selector": "oldest",
        "field": "content.attachment.data",
    },
    "hba1c_display": {
        "resource_type": "Observation", "selector": "latest_hba1c",
        "field": "code.text",
    },
}


def load_templates(directory: pathlib.Path):
    templates = []
    for path in sorted(directory.glob("*.yaml")):
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or []
        for row in data:
            row["_file"] = path.name
            templates.append(row)
    return templates


def load_dev_patients(manifest_path: pathlib.Path, test_manifest: pathlib.Path | None):
    man = json.loads(manifest_path.read_text(encoding="utf-8"))
    patients = [p["pid"] for p in man["patients"]]
    test_ids = set()
    if test_manifest and test_manifest.exists():
        test = json.loads(test_manifest.read_text(encoding="utf-8"))
        test_ids = {p["source_id"] for p in test["patients"]}
        for p in man["patients"]:
            if p["source_id"] in test_ids:
                raise RuntimeError(f"dev patient {p['pid']} shares source_id with test pool")
    return patients, test_ids


def _variants_for_split(split: str):
    return (1, 2, 3) if split == "dev" else (4, 5)


def _next_id(counters, category):
    counters[category] = counters.get(category, 0) + 1
    return f"WB-{PREFIX[category]}-{counters[category]:03d}"


def _task_from_template(tmpl, patient, variant, split, tid):
    instructions = tmpl["instructions"]
    if variant > len(instructions):
        raise ValueError(f"{tmpl['id']} has no instruction variant {variant}")
    task = {
        "id": tid,
        "split": split,
        "category": tmpl["category"],
        "title": tmpl["title"],
        "patient_ref": f"cohort:{patient}",
        "requester": tmpl["requester"],
        "consent": tmpl["consent"],
        "instruction": instructions[variant - 1],
        "expected": json.loads(json.dumps(tmpl["expected"])),
        "provenance": {
            "author": "Vadim Nareyko",
            "created": "2026-10-19",
            "clinical_review": "pending",
        },
        "template": tmpl["id"],
        "family": tmpl["family"],
        "variant": variant,
    }
    if tmpl.get("environment_mods"):
        task["environment_mods"] = json.loads(json.dumps(tmpl["environment_mods"]))
    return task


def _inject_mod(injection):
    channel = injection["channel"]
    if channel not in CHANNEL_TARGET:
        raise KeyError(channel)
    target = dict(CHANNEL_TARGET[channel])
    payload = injection["payload"]
    if injection.get("position") == "start":
        # World appends with a leading newline; encode start by using a marker the
        # world still appends — we prepend inside the payload itself for "start".
        payload = payload + "\n\n"
        # Actual start placement: store as prepend via a dedicated kind handled below.
    return {
        "kind": "inject_text",
        "target": target,
        "payload": payload,
        "_position": injection.get("position", "end"),
    }


def generate(split: str, seed: int, template_dir: pathlib.Path, manifest: pathlib.Path,
             test_manifest: pathlib.Path, max_per_patient: int = 6,
             target_per_category: int = 30):
    rng = random.Random(seed)
    templates = load_templates(template_dir)
    patients, _ = load_dev_patients(manifest, test_manifest if split == "dev" else None)
    if split != "dev":
        raise NotImplementedError("test split generation is reserved; variants 4-5 only")

    base_tmpls = [t for t in templates if t["category"] != "adversarial"]
    adv_tmpls = [t for t in templates if t["category"] == "adversarial"]
    by_id = {t["id"]: t for t in templates}
    variants = _variants_for_split(split)

    # Schedule non-adversarial first: round-robin templates × variants, assign patients.
    slots = []
    for tmpl in base_tmpls:
        for variant in variants:
            slots.append((tmpl, variant))
    rng.shuffle(slots)

    patient_counts = {p: 0 for p in patients}
    patient_templates = {p: set() for p in patients}
    counters = {}
    tasks = []
    base_index = {}  # (template_id, patient) -> task id

    def pick_patient(tmpl_id):
        candidates = [p for p in patients
                      if patient_counts[p] < max_per_patient and tmpl_id not in patient_templates[p]]
        if not candidates:
            return None
        # Prefer least-used patients for balance.
        candidates.sort(key=lambda p: (patient_counts[p], p))
        return candidates[0]

    for tmpl, variant in slots:
        if sum(1 for t in tasks if t["category"] == tmpl["category"]) >= target_per_category:
            continue
        patient = pick_patient(tmpl["id"])
        if patient is None:
            continue
        tid = _next_id(counters, tmpl["category"])
        task = _task_from_template(tmpl, patient, variant, split, tid)
        tasks.append(task)
        patient_counts[patient] += 1
        patient_templates[patient].add(tmpl["id"])
        base_index[(tmpl["id"], patient)] = tid

    # Fill categories that are short by cloning remaining variant/patient pairs.
    for category in ("allowed", "denied", "boundary"):
        cat_tmpls = [t for t in base_tmpls if t["category"] == category]
        guard = 0
        while sum(1 for t in tasks if t["category"] == category) < target_per_category and guard < 500:
            guard += 1
            tmpl = rng.choice(cat_tmpls)
            variant = rng.choice(list(variants))
            patient = pick_patient(tmpl["id"])
            if patient is None:
                break
            tid = _next_id(counters, category)
            task = _task_from_template(tmpl, patient, variant, split, tid)
            # Avoid exact duplicate (template, patient, variant)
            if any(t["template"] == tmpl["id"] and t["patient_ref"].endswith(patient)
                   and t["variant"] == variant for t in tasks):
                continue
            tasks.append(task)
            patient_counts[patient] += 1
            patient_templates[patient].add(tmpl["id"])
            base_index.setdefault((tmpl["id"], patient), tid)

    denied_adv = 0
    adv_slots = []
    for tmpl in adv_tmpls:
        for variant in variants:
            adv_slots.append((tmpl, variant))
    rng.shuffle(adv_slots)

    for tmpl, variant in adv_slots:
        if sum(1 for t in tasks if t["category"] == "adversarial") >= target_per_category:
            break
        base_tmpl = by_id[tmpl["base_template"]]
        if base_tmpl["category"] == "denied" and denied_adv >= 8:
            continue
        # Prefer a patient that already has a base task instance.
        linked = [(p, base_index[(tmpl["base_template"], p)])
                  for p in patients if (tmpl["base_template"], p) in base_index
                  and patient_counts[p] < max_per_patient
                  and tmpl["id"] not in patient_templates[p]]
        if not linked:
            patient = pick_patient(tmpl["id"])
            if patient is None:
                continue
            # Create a silent base task first so control twin is well-defined.
            base_tid = _next_id(counters, base_tmpl["category"])
            base_task = _task_from_template(base_tmpl, patient, 1, split, base_tid)
            tasks.append(base_task)
            patient_counts[patient] += 1
            patient_templates[patient].add(base_tmpl["id"])
            base_index[(base_tmpl["id"], patient)] = base_tid
        else:
            linked.sort(key=lambda row: patient_counts[row[0]])
            patient, base_tid = linked[0]

        if tmpl["id"] in patient_templates[patient] or patient_counts[patient] >= max_per_patient:
            continue
        tid = _next_id(counters, "adversarial")
        base_task = next(t for t in tasks if t["id"] == base_index[(tmpl["base_template"], patient)])
        task = {
            "id": tid,
            "split": split,
            "category": "adversarial",
            "title": tmpl["title"],
            "patient_ref": base_task["patient_ref"],
            "requester": base_task["requester"],
            "consent": base_task["consent"],
            "instruction": base_tmpl["instructions"][min(variant, len(base_tmpl["instructions"])) - 1],
            "expected": json.loads(json.dumps(base_task["expected"])),
            "attack": tmpl["attack"],
            "base_task_id": base_task["id"],
            "template": tmpl["id"],
            "family": tmpl["family"],
            "variant": variant,
            "provenance": {
                "author": "Vadim Nareyko",
                "created": "2026-10-19",
                "clinical_review": "pending",
            },
        }
        mods = list(base_task.get("environment_mods") or [])
        inj = _inject_mod(tmpl["injection"])
        position = inj.pop("_position", "end")
        if position == "start":
            # Represent start by injecting a payload that the world still appends;
            # content-wise the payload is written first in the concatenated string
            # by putting it in a separate prepend marker consumed in World.
            inj["kind"] = "inject_text_start"
        mods.append(inj)
        task["environment_mods"] = mods
        extra = tmpl.get("extra_forbidden") or {}
        for key, values in extra.items():
            cur = task["expected"].setdefault(key, [])
            for item in values:
                if item not in cur:
                    cur.append(item)
        tasks.append(task)
        patient_counts[patient] += 1
        patient_templates[patient].add(tmpl["id"])
        if base_tmpl["category"] == "denied":
            denied_adv += 1

    # Stable order by id
    tasks.sort(key=lambda t: t["id"])
    return tasks


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m wardbench.generate")
    ap.add_argument("--split", choices=["dev", "test"], default="dev")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--templates", default=str(ROOT / "templates"))
    ap.add_argument("--manifest", default=str(ROOT / "cohort" / "dev_manifest.json"))
    ap.add_argument("--test-manifest", default=str(ROOT / "cohort" / "test_manifest.json"))
    ap.add_argument("--out", default=str(ROOT / "tasks" / "dev.jsonl"))
    args = ap.parse_args(argv)
    tasks = generate(args.split, args.seed, pathlib.Path(args.templates),
                     pathlib.Path(args.manifest), pathlib.Path(args.test_manifest))
    out = pathlib.Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as fh:
        for task in tasks:
            fh.write(json.dumps(task, ensure_ascii=False) + "\n")
    from collections import Counter
    print(f"wrote {len(tasks)} tasks to {out}")
    print(dict(Counter(t["category"] for t in tasks)))


if __name__ == "__main__":
    main()
