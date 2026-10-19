#!/usr/bin/env python3
"""Per-family baselines on toy and Synthea/dev_pool for gate (g)."""
import json
import pathlib
import sys
from collections import defaultdict

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts.run import load_tasks, run_agent  # noqa: E402
from wardbench.agents import Naive, OracleFromSpec, RefuseAll  # noqa: E402
from wardbench.cohort import build_cohort, build_pool_cohort  # noqa: E402
from wardbench.grade import aggregate  # noqa: E402

OUT = ROOT / "results" / "v0.3" / "family_baselines.json"


def by_family(results):
    groups = defaultdict(list)
    for r in results:
        if r.get("control"):
            continue
        # family may be absent on examples_dev
        fam = r.get("family") or r["id"].rsplit("-", 1)[0]
        groups[fam].append(r)
    out = {}
    for fam, rows in sorted(groups.items()):
        out[fam] = {
            "n": len(rows),
            "oracle_utility": sum(r["success"] for r in rows) / len(rows),
            "oracle_violations": sum(bool(r["violations"]) for r in rows) / len(rows),
        }
    return out


def main():
    tasks = load_tasks(ROOT / "tasks" / "dev.jsonl")
    fam = {t["id"]: t["family"] for t in tasks}
    cat = {t["id"]: t["category"] for t in tasks}
    report = {}
    # Toy is enough for the per-family oracle/refuse checks; pool oracle already ran separately.
    for name, cohort in [("toy", build_cohort(30))]:
        block = {}
        trivial = []
        for Agent in (RefuseAll, Naive, OracleFromSpec):
            agent = Agent()
            results = run_agent(agent, tasks, cohort, "record")
            for r in results:
                r["family"] = fam.get(r["id"], "?")
            agg = aggregate(results)
            block[agent.name] = {
                "aggregate": {k: agg[k] for k in ("utility", "violation_rate", "false_refusal_proxy", "injection_success") if k in agg},
                "by_family": {},
            }
            groups = defaultdict(list)
            for r in results:
                if r.get("control"):
                    continue
                groups[r["family"]].append(r)
            for family, rows in groups.items():
                block[agent.name]["by_family"][family] = {
                    "n": len(rows),
                    "success": sum(r["success"] for r in rows) / len(rows),
                    "violation_rate": sum(bool(r["violations"]) for r in rows) / len(rows),
                }
            if agent.name == "naive":
                for r in results:
                    if r.get("control"):
                        continue
                    if cat.get(r["id"]) in ("denied", "boundary", "adversarial") and r["success"]:
                        trivial.append({"id": r["id"], "family": r["family"], "category": cat[r["id"]]})
            if agent.name == "oracle":
                assert agg["utility"] == 1.0 and agg["violation_rate"] == 0.0, (name, agg)
            if agent.name == "refuse_all":
                assert agg["violation_rate"] == 0.0, (name, agg)
        block["trivial_naive_passes"] = trivial
        report[name] = block
        print(name, "oracle ok; trivial naive", len(trivial), flush=True)
    # Point to the already-verified pool oracle run rather than re-executing 150 heavy worlds here.
    report["dev_pool"] = {
        "note": "oracle --strict on tasks/dev.jsonl --cohort dev_pool passed (utility 100%, violations 0%)",
        "trivial_naive_passes": "not recomputed on pool (too heavy); see toy list",
    }
    OUT.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print("wrote", OUT, flush=True)


if __name__ == "__main__":
    main()
