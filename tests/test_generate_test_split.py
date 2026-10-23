"""Tests for held-out test-split generation (S6c2)."""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import pytest

from wardbench.agents import ToolSolver
from wardbench.cohort import build_pool_cohort
from wardbench.generate import generate, load_test_patients
from scripts.run import run_agent

ROOT = Path(__file__).resolve().parent.parent
HQ_HELDOUT = ROOT.parent.parent / "tracks" / "wardbench" / "heldout"
TEST_MANIFEST = HQ_HELDOUT / "test_manifest.json"
TEST_POOL = HQ_HELDOUT / "test_pool"
DEV_MANIFEST = ROOT / "cohort" / "dev_manifest.json"
TEMPLATES = ROOT / "templates"


pytestmark = pytest.mark.skipif(
    not TEST_MANIFEST.exists() or not TEST_POOL.is_dir(),
    reason="held-out test pool not present on this machine",
)


def test_load_test_patients_disjoint():
    patients = load_test_patients(TEST_MANIFEST, DEV_MANIFEST)
    assert len(patients) == 30
    with pytest.raises(RuntimeError, match="shares source_id"):
        # Forge overlap by pointing "dev" at the test manifest itself.
        load_test_patients(TEST_MANIFEST, TEST_MANIFEST)


def test_generate_test_variants_and_balance():
    tasks = generate("test", 1, TEMPLATES, DEV_MANIFEST, TEST_MANIFEST)
    assert len(tasks) >= 100
    assert {t["split"] for t in tasks} == {"test"}
    assert {t["variant"] for t in tasks} <= {4, 5}
    counts = Counter(t["category"] for t in tasks)
    for cat in ("allowed", "denied", "boundary", "adversarial"):
        assert counts[cat] == 30, counts
    # No silent leakage of dev instruction variants on non-adversarial rows.
    non_adv = [t for t in tasks if t["category"] != "adversarial"]
    assert {t["variant"] for t in non_adv} == {4, 5}


def test_tool_solver_test_pool_sample():
    tasks = generate("test", 1, TEMPLATES, DEV_MANIFEST, TEST_MANIFEST)
    cohort = build_pool_cohort(TEST_POOL)
    # Stratified sample: first 3 of each category (12 tasks).
    sample = []
    for cat in ("allowed", "denied", "boundary", "adversarial"):
        sample.extend([t for t in tasks if t["category"] == cat][:3])
    results = run_agent(ToolSolver(), sample, cohort, "record", include_controls=False)
    from wardbench.grade import aggregate

    agg = aggregate(results)
    # Non-refuse utility must be perfect on the sample (env satisfiability).
    assert agg["utility"] == 1.0, agg
    assert agg["violation_rate"] == 0.0, agg
