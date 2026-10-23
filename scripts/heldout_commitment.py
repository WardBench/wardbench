#!/usr/bin/env python3
"""Build a salted Merkle commitment over a task JSONL.

Dry-run default: commit `tasks/dev.jsonl` into a private report artifact.
Official held-out commitment (after clinician review + `tasks/test.jsonl`)
writes `tracks/wardbench/reports/v0.4/heldout_commitment.json` with salt kept
under the private heldout directory (git-ignored).

Never sends tasks to an API.
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import secrets
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from wardbench.commitment import commit_tasks  # noqa: E402

DEFAULT_TASKS = ROOT / "tasks" / "dev.jsonl"
DEFAULT_DRY_OUT = (
    ROOT.parent.parent / "tracks" / "wardbench" / "reports" / "v0.4" / "commitment_dev_dryrun.json"
)
DEFAULT_OFFICIAL_OUT = (
    ROOT.parent.parent / "tracks" / "wardbench" / "reports" / "v0.4" / "heldout_commitment.json"
)
DEFAULT_OFFICIAL_SALT = (
    ROOT.parent.parent / "tracks" / "wardbench" / "heldout" / "commitment_salt.txt"
)
DEFAULT_DRYRUN_SALT = (
    ROOT.parent.parent / "tracks" / "wardbench" / "reports" / "v0.4" / ".commitment_dev_dryrun_salt"
)


def load_jsonl(path: pathlib.Path) -> list[dict]:
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        rows.append(json.loads(line))
    return rows


def load_or_create_salt(path: pathlib.Path, *, create: bool) -> bytes:
    if path.exists():
        text = path.read_text(encoding="utf-8").strip()
        if not text:
            raise SystemExit(f"empty salt file: {path}")
        return bytes.fromhex(text) if all(c in "0123456789abcdef" for c in text.lower()) else text.encode("utf-8")
    if not create:
        raise SystemExit(f"salt file missing: {path} (pass --create-salt)")
    path.parent.mkdir(parents=True, exist_ok=True)
    salt = secrets.token_bytes(32)
    path.write_text(salt.hex() + "\n", encoding="utf-8")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return salt


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--tasks", default=str(DEFAULT_TASKS))
    ap.add_argument("--salt-file", default="", help="default: dryrun salt under reports/; official under heldout/")
    ap.add_argument("--create-salt", action="store_true")
    ap.add_argument(
        "--mode",
        choices=("dryrun", "official"),
        default="dryrun",
        help="dryrun → commitment_dev_dryrun.json; official → heldout_commitment.json",
    )
    ap.add_argument("--out", default="")
    args = ap.parse_args(argv)

    tasks_path = pathlib.Path(args.tasks)
    if not tasks_path.exists():
        raise SystemExit(f"missing tasks: {tasks_path}")
    if args.mode == "official" and tasks_path.name == "dev.jsonl":
        raise SystemExit(
            "refusing official commitment over dev.jsonl; "
            "generate held-out tasks/test.jsonl after clinician review first"
        )

    salt_path = pathlib.Path(args.salt_file) if args.salt_file else (
        DEFAULT_OFFICIAL_SALT if args.mode == "official" else DEFAULT_DRYRUN_SALT
    )
    # Always allow creating dry-run salt; official requires explicit --create-salt.
    create = args.create_salt or args.mode == "dryrun"
    salt = load_or_create_salt(salt_path, create=create)
    tasks = load_jsonl(tasks_path)
    if not tasks:
        raise SystemExit("no tasks")

    doc = commit_tasks(tasks, salt)
    doc["meta"] = {
        "mode": args.mode,
        "tasks_path": str(tasks_path),
        "salt_file": str(salt_path),
        "salt_sha256": __import__("hashlib").sha256(salt).hexdigest(),
        "note": (
            "Public reveal publishes only meta.root (+ algorithm). "
            "Salt and leaf list stay private until the held-out reveal."
            if args.mode == "official"
            else "Dry-run on a non-held-out file; not the official commitment."
        ),
    }
    # Never embed the raw salt in the JSON artifact.
    out = pathlib.Path(args.out) if args.out else (
        DEFAULT_OFFICIAL_OUT if args.mode == "official" else DEFAULT_DRY_OUT
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {out}")
    print(f"root={doc['root']}")
    print(f"n_tasks={doc['n_tasks']}")


if __name__ == "__main__":
    main()
