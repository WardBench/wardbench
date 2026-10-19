#!/usr/bin/env python3
"""Run agents on WardBench tasks and print metrics.

    python scripts/run.py --agent baselines
    python scripts/run.py --agent oracle --strict
    ANTHROPIC_API_KEY=... python scripts/run.py --agent anthropic --model <model-id> --policy-visibility record
"""
import argparse
import copy
import json
import os
import pathlib
import sys
import time

N_CTX = 16384

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from wardbench.agents import (AnthropicAgent, Context, Naive, OpenAICompatAgent, OracleFromSpec,  # noqa: E402
                              RefuseAll, build_system_prompt)
from wardbench.cohort import build_cohort, build_pool_cohort, build_synthea_cohort, derive_attrs  # noqa: E402
from wardbench.grade import aggregate, grade  # noqa: E402
from wardbench.resolve import render_instruction, resolve  # noqa: E402
from wardbench.world import World  # noqa: E402


def load_tasks(path):
    text = pathlib.Path(path).read_text(encoding="utf-8").strip()
    if text.startswith("["):
        return json.loads(text)
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def with_controls(tasks):
    """Adversarial twins with the injection removed. Not part of the dataset."""
    out = []
    for task in tasks:
        out.append(task)
        if task.get("category") != "adversarial":
            continue
        twin = copy.deepcopy(task)
        twin.pop("environment_mods", None)
        twin["id"] = task["id"] + "-ctrl"
        twin["control_for"] = task["id"]
        out.append(twin)
    return out


def run_agent(agent, tasks, cohort, visibility, include_controls=True):
    results = []
    limit = 3500 if getattr(agent, "limit_tool_output", False) else None
    queue = with_controls(tasks) if include_controls else list(tasks)
    for task in queue:
        world = World(task, cohort)
        attrs = derive_attrs(cohort[world.subject])
        exp = task["expected"]
        resolved = {
            "required": [p for pat in exp.get("required_answer_patterns", []) for p in resolve(pat, attrs)],
            "forbidden": [p for pat in exp.get("forbidden_answer_patterns", []) for p in resolve(pat, attrs)],
        }
        ctx = Context(task=task, system=build_system_prompt(task, visibility),
                      instruction=render_instruction(task["instruction"], attrs),
                      subject=world.subject, tools=world.tools(output_limit=limit), required=resolved["required"])
        try:
            answer = agent.run(ctx)
        except Exception as exc:
            answer = ""
            agent.last_response_status = "empty"
            print(f"  {task['id']} agent error: {exc}", flush=True)
        status = getattr(agent, "last_response_status", "ok")
        res = grade(task, world, answer, resolved, response_status=status)
        res["answer_preview"] = (answer or "")[:200]
        res["tool_log"] = world.log
        reasoning = getattr(agent, "last_reasoning", "")
        if reasoning:
            res["reasoning"] = reasoning[:2000]
        prompt_tokens = getattr(agent, "last_prompt_tokens", None)
        res["prompt_tokens"] = prompt_tokens
        res["context_over_80pct"] = bool(prompt_tokens and prompt_tokens > 0.8 * N_CTX)
        res["finish_reason"] = getattr(agent, "last_finish_reason", None)
        results.append(res)
        mark = "ok" if res.get("success") else "fail"
        flag = " CONTEXT" if res["context_over_80pct"] else ""
        print(f"  {task['id']} {mark} tools={len(world.log)} status={status}{flag}", flush=True)
    return results


def fmt(x):
    return "  n/a" if x != x else f"{100 * x:4.0f}%"


def print_table(rows):
    print(f"{'agent':<28}{'utility':>9}{'violation':>11}{'false-ref*':>12}{'inj.succ':>10}")
    for name, agg in rows:
        print(f"{name:<28}{fmt(agg['utility']):>9}{fmt(agg['violation_rate']):>11}"
              f"{fmt(agg['false_refusal_proxy']):>12}{fmt(agg['injection_success']):>10}")
    print(f"{'':<28}{'access':>9}{'action':>11}{'disclosed':>12}{'invalid':>10}")
    for name, agg in rows:
        print(f"{name:<28}{fmt(agg['access_violation_rate']):>9}{fmt(agg['action_violation_rate']):>11}"
              f"{fmt(agg['disclosure_violation_rate']):>12}{fmt(agg['invalid_response_rate']):>10}")
    print(f"{'':<28}{'adv-viol':>9}{'control':>11}{'induced':>12}")
    for name, agg in rows:
        print(f"{name:<28}{fmt(agg['adversarial_violation_rate']):>9}{fmt(agg['control_violation_rate']):>11}"
              f"{fmt(agg['attack_induced_rate']):>12}")
    print("* false-ref ignores empty, truncated, and reasoning-only responses")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tasks", default=str(ROOT / "tasks" / "examples_dev.json"))
    ap.add_argument("--agent", default="baselines",
                    choices=["baselines", "refuse_all", "naive", "oracle", "anthropic", "openai_compat"])
    ap.add_argument("--model", default=None)
    ap.add_argument("--base-url", default=None)
    ap.add_argument("--api-key-env", default="OPENAI_API_KEY",
                    help="env var holding the key; local backends may leave it unset (a dummy key is used)")
    ap.add_argument("--temperature", type=float, default=0)
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--disable-thinking", action="store_true",
                    help="ask chat templates to skip a reasoning channel (Qwen3)")
    ap.add_argument("--policy-visibility", default="record", choices=["prompt", "record"])
    ap.add_argument("--cohort", default="toy", choices=["toy", "synthea", "dev_pool", "test_pool"])
    ap.add_argument("--synthea-dir", default=str(ROOT / "work" / "synthea" / "out" / "fhir"))
    ap.add_argument("--pool-dir", default=str(ROOT / "work" / "synthea" / "cohort_v03"))
    ap.add_argument("--cohort-size", type=int, default=30)
    ap.add_argument("--out", default=None)
    ap.add_argument("--strict", action="store_true", help="exit 1 if the oracle does not score 100%% utility / 0 violations")
    args = ap.parse_args()

    tasks = load_tasks(args.tasks)
    if args.cohort == "synthea":
        cohort = build_synthea_cohort(args.synthea_dir, args.cohort_size)
        print("task patients (2-8 active disorders):")
        for row in build_synthea_cohort.task_patients:
            print(f"  {row['pid']}  n={row['bounded_conditions']}  {row['file']}")
    elif args.cohort in ("dev_pool", "test_pool"):
        pool = "dev" if args.cohort == "dev_pool" else "test"
        if args.cohort == "test_pool":
            # Generator must never place these patients into a published dev task file.
            print("loading git-ignored test pool", flush=True)
        cohort = build_pool_cohort(pathlib.Path(args.pool_dir) / pool)
        print(f"pool={pool} patients={len(build_synthea_cohort.task_patients)}")
    else:
        cohort = build_cohort(args.cohort_size)

    if args.agent == "baselines":
        agents = [RefuseAll(), Naive(), OracleFromSpec()]
    elif args.agent == "anthropic":
        if not args.model:
            sys.exit("--model is required for --agent anthropic")
        agents = [AnthropicAgent(args.model)]
    elif args.agent == "openai_compat":
        if not args.model or not args.base_url:
            sys.exit("--model and --base-url are required for --agent openai_compat")
        agents = [OpenAICompatAgent(
            args.model, args.base_url, api_key=os.environ.get(args.api_key_env, "local"),
            temperature=args.temperature, seed=args.seed, disable_thinking=args.disable_thinking,
        )]
    else:
        agents = [{"refuse_all": RefuseAll, "naive": Naive, "oracle": OracleFromSpec}[args.agent]()]

    meta = {
        "version": "0.3",
        "n_ctx": N_CTX,
        "cohort": args.cohort,
        "policy_visibility": args.policy_visibility,
        "temperature": args.temperature,
        "seed": args.seed,
        "disable_thinking": args.disable_thinking,
    }
    if args.agent == "openai_compat":
        meta.update({"model": args.model, "base_url": args.base_url, "backend": "localai",
                     "quantization": "Q4_K_M" if "Q4" in args.model or args.model in ("qwen3", "qwen3-14b") else None})

    rows, dump = [], {}
    started = time.perf_counter()
    for agent in agents:
        results = run_agent(agent, tasks, cohort, args.policy_visibility)
        agg = aggregate(results)
        rows.append((agent.name, agg))
        dump[agent.name] = {"aggregate": agg, "tasks": results}
        for r in results:
            if r["violations"] or r["missing"]:
                print(f"  [{agent.name}] {r['id']:<11} violations={r['violations']} missing={r['missing']}")
    print()
    print_table(rows)
    meta["seconds"] = round(time.perf_counter() - started, 1)
    if args.out:
        payload = {"meta": meta, **dump}
        pathlib.Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        pathlib.Path(args.out).write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(f"\nwrote {args.out}")
    if args.strict:
        for name, agg in rows:
            if name == "oracle" and (agg["utility"] != 1.0 or agg["violation_rate"] != 0.0):
                sys.exit("oracle check FAILED: some task is not satisfiable as specified")


if __name__ == "__main__":
    main()
