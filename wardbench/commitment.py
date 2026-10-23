"""Salted Merkle commitment over a task JSONL (held-out freeze).

Leaves are SHA-256(salt || task_id || canonical_task_json). The Merkle tree is
binary, padded with the last leaf when the level size is odd. Only the root is
meant for public release; salt and leaf hashes stay private until reveal.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Iterable


# Fields that identify the task content for commitment. Volatile / run-only
# keys are omitted so regenerating with the same generator seed matches.
_COMMIT_KEYS = (
    "id",
    "split",
    "category",
    "family",
    "template",
    "variant",
    "patient_id",
    "subject",
    "instruction",
    "requester",
    "consent",
    "expected",
    "injection",
    "control_of",
    "perm_for",
)


def canonical_task(task: dict[str, Any]) -> bytes:
    payload = {k: task.get(k) for k in _COMMIT_KEYS if k in task}
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def leaf_hash(task: dict[str, Any], salt: bytes) -> str:
    tid = str(task.get("id") or "")
    digest = hashlib.sha256()
    digest.update(salt)
    digest.update(b"\0")
    digest.update(tid.encode("utf-8"))
    digest.update(b"\0")
    digest.update(canonical_task(task))
    return digest.hexdigest()


def merkle_root(leaf_hex: Iterable[str]) -> str:
    level = [bytes.fromhex(h) for h in leaf_hex]
    if not level:
        raise ValueError("empty leaf set")
    while len(level) > 1:
        if len(level) % 2 == 1:
            level.append(level[-1])
        nxt = []
        for i in range(0, len(level), 2):
            nxt.append(hashlib.sha256(level[i] + level[i + 1]).digest())
        level = nxt
    return level[0].hex()


def commit_tasks(tasks: list[dict[str, Any]], salt: bytes) -> dict[str, Any]:
    ordered = sorted(tasks, key=lambda t: str(t.get("id") or ""))
    leaves = [{"id": t["id"], "leaf": leaf_hash(t, salt)} for t in ordered]
    root = merkle_root(leaf["leaf"] for leaf in leaves)
    return {
        "algorithm": "sha256-merkle-v1",
        "n_tasks": len(leaves),
        "root": root,
        "leaves": leaves,
        "canonical_keys": list(_COMMIT_KEYS),
    }
