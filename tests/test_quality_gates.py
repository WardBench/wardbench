"""pytest quality gates for v0.3."""
import json
import pathlib
import re
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from wardbench.cohort import COND, build_cohort, build_pool_cohort, derive_attrs  # noqa: E402
from wardbench.generate import generate  # noqa: E402
from wardbench.grade import grade  # noqa: E402
from wardbench.resolve import resolve  # noqa: E402
from wardbench.world import World  # noqa: E402
from scripts.lint_tasks import (  # noqa: E402
    FORBIDDEN_WORDS, NEUTRAL_ANSWERS, gate_false_positives, gate_instructions,
    gate_null_and_leaky, gate_schema, load_tasks,
)

SCHEMA = json.loads((ROOT / "schema" / "task.schema.json").read_text(encoding="utf-8"))
DEV = ROOT / "tasks" / "dev.jsonl"
SENTENCES = [ln.strip() for ln in (ROOT / "tests" / "data" / "neutral_clinical_sentences.txt").read_text().splitlines() if ln.strip()]


@pytest.fixture(scope="module")
def tasks():
    assert DEV.exists(), "run python -m wardbench.generate first"
    return load_tasks(DEV)


@pytest.fixture(scope="module")
def toy():
    return build_cohort(30)


def test_a_schema_unique(tasks):
    errors = gate_schema(tasks, SCHEMA)
    assert not errors, errors[:10]


def test_b_instructions(tasks):
    errors = gate_instructions(tasks)
    assert not errors, errors[:10]


def test_c_d_null_leaky(tasks, toy):
    # Sample 24 tasks for speed in CI; full scan is in lint_tasks.py
    sample = tasks[::5]
    errors = gate_null_and_leaky(sample, toy)
    assert not errors, errors[:10]


def test_e_false_positive_scan_size():
    assert len(SENTENCES) >= 30


def test_e_psy_pattern_safe():
    rx = COND["dep"]["match"]
    ordinary = [
        "No respiratory depression after opioid analgesia.",
        "Mood is euthymic. Sleep and appetite are normal.",
        "Pre-operative assessment: type 2 diabetes mellitus and essential hypertension.",
    ]
    for text in ordinary:
        assert re.search(rx, text, re.IGNORECASE) is None
    assert re.search(rx, "History of depressive disorder, stable.", re.IGNORECASE)


def test_f_coverage_has_families(tasks):
    families = {t["family"] for t in tasks}
    assert len(families) >= 20


def test_generator_refuses_test_overlap(tmp_path):
    man = json.loads((ROOT / "cohort" / "dev_manifest.json").read_text())
    # Forge a colliding test manifest
    bad = {"patients": [{"pid": "pt-001", "source_id": man["patients"][0]["source_id"], "source_file": "x"}]}
    path = tmp_path / "test.json"
    path.write_text(json.dumps(bad))
    with pytest.raises(RuntimeError):
        generate("dev", 1, ROOT / "templates", ROOT / "cohort" / "dev_manifest.json", path)


def test_g_oracle_toy_sample(tasks, toy):
    from wardbench.agents import OracleFromSpec, Context, build_system_prompt
    from wardbench.resolve import render_instruction
    oracle = OracleFromSpec()
    for task in tasks[:8]:
        world = World(task, toy)
        attrs = derive_attrs(toy[world.subject])
        resolved = {
            "required": [p for pat in task["expected"].get("required_answer_patterns", []) for p in resolve(pat, attrs)],
            "forbidden": [p for pat in task["expected"].get("forbidden_answer_patterns", []) for p in resolve(pat, attrs)],
        }
        ctx = Context(task=task, system=build_system_prompt(task, "record"),
                      instruction=render_instruction(task["instruction"], attrs),
                      subject=world.subject, tools=world.tools(), required=resolved["required"])
        answer = oracle.run(ctx)
        res = grade(task, world, answer, resolved)
        assert res["success"], (task["id"], res)
