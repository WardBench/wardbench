#!/usr/bin/env python3
"""Validate WardBench task files against the schema.

Usage: python scripts/validate.py tasks/examples_dev.json
Accepts a JSON array or JSONL.
"""
import collections
import json
import pathlib
import re
import sys

from jsonschema import Draft202012Validator

ROOT = pathlib.Path(__file__).resolve().parent.parent
PLACEHOLDER = re.compile(r"\{\{(.+?)\}\}")
KNOWN_PREFIXES = ("pt.",)


def load(path: pathlib.Path):
    text = path.read_text(encoding="utf-8").strip()
    if text.startswith("["):
        return json.loads(text)
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def main(paths):
    schema = json.loads((ROOT / "schema" / "task.schema.json").read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema)
    errors = 0
    seen_ids = set()
    counts = collections.Counter()
    placeholders = set()

    for p in paths:
        for task in load(pathlib.Path(p)):
            tid = task.get("id", "<no id>")
            for err in validator.iter_errors(task):
                errors += 1
                loc = "/".join(map(str, err.absolute_path)) or "(root)"
                print(f"[{tid}] {loc}: {err.message}")
            if tid in seen_ids:
                errors += 1
                print(f"[{tid}] duplicate id")
            seen_ids.add(tid)
            counts[task.get("category")] += 1
            expected = task.get("expected", {})
            for key in ("required_answer_patterns", "forbidden_answer_patterns"):
                for pat in expected.get(key, []):
                    for ph in PLACEHOLDER.findall(pat):
                        placeholders.add(ph)
                        if not ph.startswith(KNOWN_PREFIXES):
                            errors += 1
                            print(f"[{tid}] unknown placeholder namespace: {ph}")
            # a refusal task must not require answer facts
            if expected.get("behavior") == "refuse" and expected.get("required_answer_patterns"):
                errors += 1
                print(f"[{tid}] refuse task has required_answer_patterns")

    print(f"\n{len(seen_ids)} tasks, categories: {dict(counts)}")
    print(f"{len(placeholders)} distinct placeholders the cohort builder must resolve:")
    for ph in sorted(placeholders):
        print(f"  {{{{{ph}}}}}")
    print("OK" if errors == 0 else f"{errors} problem(s)")
    return 1 if errors else 0


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    sys.exit(main(sys.argv[1:]))
