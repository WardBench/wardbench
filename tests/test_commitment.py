"""Unit tests for salted Merkle task commitment."""
import hashlib

from wardbench.commitment import canonical_task, commit_tasks, leaf_hash, merkle_root


def _task(i: int) -> dict:
    return {
        "id": f"WB-T-{i:03d}",
        "split": "dev",
        "category": "allowed",
        "family": "demo",
        "template": "demo",
        "variant": 1,
        "patient_id": f"pt-{i:03d}",
        "instruction": f"List facts for patient {i}.",
        "requester": {"role": "physician", "purpose_of_use": "TREAT"},
        "consent": {"state": "active"},
        "expected": {"behavior": "complete", "required_answer_patterns": ["x"]},
    }


def test_canonical_ignores_extra_keys():
    a = _task(1)
    b = {**a, "answer_preview": "noise", "tool_log": []}
    assert canonical_task(a) == canonical_task(b)


def test_leaf_depends_on_salt_and_id():
    t = _task(1)
    h1 = leaf_hash(t, b"salt-a")
    h2 = leaf_hash(t, b"salt-b")
    h3 = leaf_hash({**t, "id": "WB-T-002"}, b"salt-a")
    assert h1 != h2
    assert h1 != h3
    assert len(h1) == 64


def test_merkle_root_stable_and_order_invariant_via_commit():
    tasks = [_task(i) for i in (3, 1, 2)]
    salt = hashlib.sha256(b"unit-test-salt").digest()
    a = commit_tasks(tasks, salt)
    b = commit_tasks(list(reversed(tasks)), salt)
    assert a["root"] == b["root"]
    assert a["n_tasks"] == 3
    assert [x["id"] for x in a["leaves"]] == ["WB-T-001", "WB-T-002", "WB-T-003"]
    # Odd padding: single leaf root equals the leaf itself.
    assert merkle_root([a["leaves"][0]["leaf"]]) == a["leaves"][0]["leaf"]
