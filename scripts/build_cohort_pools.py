#!/usr/bin/env python3
"""Generate Synthea patients, apply eligibility, write disjoint dev/test pools."""
import argparse
import json
import pathlib
import random
import shutil
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from wardbench.cohort import (  # noqa: E402
    _annotate, _read_bundles, _rewrite_ids, augment, patient_eligible,
)

SYNTHEA_JAR = ROOT / "work" / "synthea" / "synthea-with-dependencies.jar"
SYNTHEA_VERSION = "d9d07a6"  # Build-Version from the jar MANIFEST
DEFAULT_SEED = 20261019


def run_synthea(out_dir: pathlib.Path, n: int, seed: int):
    out_dir.mkdir(parents=True, exist_ok=True)
    # clear previous fhir export in this out dir only
    fhir = out_dir / "fhir"
    if fhir.exists():
        shutil.rmtree(fhir)
    cmd = [
        "java", "-jar", str(SYNTHEA_JAR),
        "-s", str(seed),
        "-p", str(n),
        "--exporter.fhir.export=true",
        "--exporter.hospital.fhir.export=false",
        "--exporter.practitioner.fhir.export=false",
        f"--exporter.baseDirectory={out_dir}",
    ]
    print("running:", " ".join(cmd), flush=True)
    subprocess.check_call(cmd)


def eligible_rows(raw_dir: pathlib.Path, augment_seed: int):
    loaded = _read_bundles(raw_dir)
    rows = []
    for i, row in enumerate(loaded):
        tmp_id = f"tmp-{i:04d}"
        resources = _rewrite_ids(row["resources"], row["source_id"], tmp_id)
        for r in resources:
            _annotate(r)
        cohort = augment({tmp_id: resources}, seed=augment_seed + i)
        res = cohort[tmp_id]
        if patient_eligible(res):
            rows.append({
                "source_id": row["source_id"],
                "file": row["file"],
                "resources": row["resources"],
                "bounded": sum(1 for r in res if r.get("resourceType") == "Condition"
                               and (r.get("code") or {}).get("text", "").endswith("(disorder)")
                               and r.get("_class") != "PSY"),
            })
    return rows


def write_pool(rows, dest: pathlib.Path, src_fhir: pathlib.Path):
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    for i, row in enumerate(rows, 1):
        src = src_fhir / row["file"]
        shutil.copy2(src, dest / f"pt-{i:03d}_{row['file']}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=DEFAULT_SEED)
    ap.add_argument("--generate", type=int, default=120, help="Synthea population size")
    ap.add_argument("--pool-size", type=int, default=30)
    ap.add_argument("--out", default=str(ROOT / "work" / "synthea" / "cohort_v03"))
    args = ap.parse_args()
    out = pathlib.Path(args.out)
    raw = out / "raw"
    run_synthea(raw, args.generate, args.seed)
    rows = eligible_rows(raw / "fhir", augment_seed=args.seed)
    print(f"eligible after augment: {len(rows)} / generated under {raw / 'fhir'}")
    if len(rows) < 2 * args.pool_size:
        sys.exit(f"need {2 * args.pool_size} eligible patients, found {len(rows)}; raise --generate")
    rng = random.Random(args.seed)
    rng.shuffle(rows)
    dev, test = rows[:args.pool_size], rows[args.pool_size:2 * args.pool_size]
    write_pool(dev, out / "dev", raw / "fhir")
    write_pool(test, out / "test", raw / "fhir")
    meta = {
        "synthea_version": SYNTHEA_VERSION,
        "synthea_seed": args.seed,
        "generated": args.generate,
        "pool_size": args.pool_size,
        "eligible": len(rows),
        "dev_files": [r["file"] for r in dev],
        "test_files": [r["file"] for r in test],
    }
    (out / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    # Tracked manifest: only the dev pool (test stays git-ignored)
    cohort_dir = ROOT / "cohort"
    cohort_dir.mkdir(exist_ok=True)
    (cohort_dir / "dev_manifest.json").write_text(json.dumps({
        "synthea_version": SYNTHEA_VERSION,
        "synthea_seed": args.seed,
        "pool": "dev",
        "patients": [{"pid": f"pt-{i:03d}", "source_file": r["file"], "source_id": r["source_id"]}
                     for i, r in enumerate(dev, 1)],
    }, indent=2), encoding="utf-8")
    (cohort_dir / "test_manifest.json").write_text(json.dumps({
        "synthea_version": SYNTHEA_VERSION,
        "synthea_seed": args.seed,
        "pool": "test",
        "patients": [{"pid": f"pt-{i:03d}", "source_file": r["file"], "source_id": r["source_id"]}
                     for i, r in enumerate(test, 1)],
    }, indent=2), encoding="utf-8")
    print(f"wrote {out / 'dev'} and {out / 'test'}; meta={out / 'meta.json'}")


if __name__ == "__main__":
    main()
