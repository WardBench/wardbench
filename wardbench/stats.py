"""Reporting helpers: Wilson intervals, cluster bootstrap, McNemar."""
from __future__ import annotations

import math
import random
from collections import defaultdict


def wilson(k, n, z=1.96):
    if not n:
        return (float("nan"), float("nan"))
    p = k / n
    den = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / den
    margin = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return max(0.0, centre - margin), min(1.0, centre + margin)


def rate_with_n(k, n):
    lo, hi = wilson(k, n)
    return {"k": k, "n": n, "rate": (k / n) if n else float("nan"), "wilson95": [lo, hi]}


def cluster_bootstrap(rows, value_fn, cluster_fn, n_resamples=10000, seed=1, alpha=0.05):
    """rows: list of task results. value_fn(row)->0/1. cluster_fn(row)->cluster id."""
    buckets = defaultdict(list)
    for row in rows:
        buckets[cluster_fn(row)].append(row)
    keys = list(buckets)
    if not keys:
        return {"mean": float("nan"), "ci95": [float("nan"), float("nan")], "n_clusters": 0}
    rng = random.Random(seed)
    stats = []
    for _ in range(n_resamples):
        sample = []
        for _k in keys:
            chosen = keys[rng.randrange(len(keys))]
            sample.extend(buckets[chosen])
        if not sample:
            continue
        stats.append(sum(value_fn(r) for r in sample) / len(sample))
    stats.sort()
    lo = stats[int(alpha / 2 * len(stats))]
    hi = stats[int((1 - alpha / 2) * len(stats)) - 1]
    point = sum(value_fn(r) for r in rows) / len(rows)
    return {"mean": point, "ci95": [lo, hi], "n_clusters": len(keys), "n_resamples": n_resamples}


def mcnemar_paired(a_true_b_false, a_false_b_true):
    """Exact McNemar mid-p style counts; returns discordant counts and two-sided p via binomial."""
    n = a_true_b_false + a_false_b_true
    if n == 0:
        return {"b": a_true_b_false, "c": a_false_b_true, "n_discordant": 0, "p_approx": 1.0}
    # Exact two-sided binomial test under p=0.5
    from math import comb
    k = min(a_true_b_false, a_false_b_true)
    tail = sum(comb(n, i) for i in range(0, k + 1)) / (2 ** n)
    p = min(1.0, 2 * tail)
    return {"b": a_true_b_false, "c": a_false_b_true, "n_discordant": n, "p_approx": p}


def paired_bootstrap_diff(pairs, n_resamples=10000, seed=1):
    """pairs: list of (success_a, success_b) as 0/1."""
    if not pairs:
        return {"diff": float("nan"), "ci95": [float("nan"), float("nan")]}
    rng = random.Random(seed)
    point = sum(a - b for a, b in pairs) / len(pairs)
    stats = []
    for _ in range(n_resamples):
        sample = [pairs[rng.randrange(len(pairs))] for _ in pairs]
        stats.append(sum(a - b for a, b in sample) / len(sample))
    stats.sort()
    return {
        "diff": point,
        "ci95": [stats[int(0.025 * len(stats))], stats[int(0.975 * len(stats)) - 1]],
        "n": len(pairs),
    }


def conditional_attack_induced(results):
    """Among adversarial tasks whose control twin passed (no violations), share with injected violations."""
    by_id = {r["id"]: r for r in results}
    pairs = []
    for r in results:
        if r.get("control") or r.get("category") != "adversarial":
            continue
        twin = by_id.get(r["id"] + "-ctrl") or next((x for x in results if x.get("control_for") == r["id"]), None)
        if not twin:
            continue
        if twin["violations"]:
            continue
        pairs.append(bool(r["violations"]))
    return rate_with_n(sum(pairs), len(pairs))


def group_rates(results, key_fn, success_fn=lambda r: r["success"]):
    groups = defaultdict(list)
    for r in results:
        if r.get("control"):
            continue
        groups[key_fn(r)].append(r)
    out = {}
    for key, rows in sorted(groups.items()):
        k = sum(1 for r in rows if success_fn(r))
        out[str(key)] = rate_with_n(k, len(rows))
    return out
