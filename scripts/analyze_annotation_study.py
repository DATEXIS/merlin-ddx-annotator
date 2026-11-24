#!/usr/bin/env python3
"""Analyze a new-study trace export without historical sample-size constraints.

Default analysis requires complete paired observations. Missing votes are not
silently treated as negative. Results are local research artifacts.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
import json
from pathlib import Path
import random


def read_jsonl(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def rate(yes, total):
    return yes / total if total else None


def quantile(values, p):
    data = sorted(values)
    i = p * (len(data) - 1)
    lo = int(i)
    hi = min(lo + 1, len(data) - 1)
    return data[lo] + (i - lo) * (data[hi] - data[lo])


def analyze(rows, *, seed=42, replicates=2000):
    if replicates < 1:
        raise ValueError("Positive bootstrap replicate count required")
    grouped = defaultdict(list)
    for row in rows:
        grouped[row["stage"]].append(row)
    if not grouped:
        raise ValueError("No trace ratings supplied")
    result = {}
    for stage, records in sorted(grouped.items()):
        pairs = defaultdict(dict)
        for r in records:
            if r["condition"] not in ("left", "right") or r["condition"] in pairs[r["pair_id"]]:
                raise ValueError("Duplicate or invalid condition")
            pairs[r["pair_id"]][r["condition"]] = r
        for sides in pairs.values():
            if set(sides) != {"left", "right"} or sides["left"]["case_id"] != sides["right"]["case_id"]:
                raise ValueError("Unmatched pair")
        summary = {"pairs": len(pairs), "admissions": len({r["case_id"] for r in records}),
                   "conditions": {}, "paired_differences": {}}
        for metric in ("q1", "q2", "composite"):
            clusters = defaultdict(lambda: [0, 0, 0, 0])
            for sides in pairs.values():
                cluster = clusters[sides["left"]["case_id"]]
                for i, condition in enumerate(("left", "right")):
                    row = sides[condition]
                    votes = row[f"{metric}_votes"]
                    n = row["n_expected_raters"]
                    if votes.get("Missing", 0) or sum(votes.values()) != n or n < 1:
                        raise ValueError("Analysis requires complete rating exports")
                    cluster[2*i] += votes.get("Yes", 0)
                    cluster[2*i+1] += n
                if sides["left"]["n_expected_raters"] != sides["right"]["n_expected_raters"]:
                    raise ValueError("Unbalanced expected rater count within pair")
            counts = [sum(v[i] for v in clusters.values()) for i in range(4)]
            left, right = rate(*counts[:2]), rate(*counts[2:])
            for condition, i in (("left", 0), ("right", 2)):
                summary["conditions"].setdefault(condition, {})[metric] = {
                    "yes": counts[i], "n": counts[i+1], "rate": rate(*counts[i:i+2])}
            values = [clusters[k] for k in sorted(clusters)]
            rng = random.Random(seed)
            draws = []
            for _ in range(replicates):
                sampled = rng.choices(values, k=len(values))
                totals = [sum(v[i] for v in sampled) for i in range(4)]
                draws.append(rate(*totals[:2]) - rate(*totals[2:]))
            summary["paired_differences"][metric] = {
                "left_minus_right": left - right,
                "ci95": [quantile(draws, .025), quantile(draws, .975)] if len(values) > 1 else None}
        # Correlation is descriptive, at trace level, separately by condition.
        # Human outcome is the fraction of raters marking both Q1 and Q2 Yes.
        from scipy.stats import spearmanr
        for condition in ("left", "right"):
            points = [(r["verifier_score"], r["composite_votes"].get("Yes", 0)/r["n_expected_raters"])
                      for r in records if r["condition"] == condition and r.get("verifier_score") is not None]
            x, y = zip(*points) if points else ((), ())
            rho = (float(spearmanr(x, y).statistic)
                   if len(points) >= 3 and len(set(x)) > 1 and len(set(y)) > 1 else None)
            summary["conditions"][condition]["verifier_association"] = {"n_traces": len(points), "spearman_rho": rho}
        result[stage] = summary
    return {"bootstrap_seed": seed, "bootstrap_replicates": replicates,
            "stage_results": result}



def analyze_reference(rows, *, seed=42, replicates=2000):
    """Report reference agreement by stage and provenance, separately from model validity."""
    if replicates < 1 or not rows:
        raise ValueError("Nonempty reference ratings and positive replicate count required")
    groups = defaultdict(lambda: defaultdict(lambda: [0, 0, 0, 0]))
    seen = set()
    for row in rows:
        if row["label_origin"] != "reference" or row["pair_id"] in seen:
            raise ValueError("Invalid or duplicate reference item")
        seen.add(row["pair_id"])
        votes = row["label_validity_votes"]
        n = row["n_expected_raters"]
        if n < 1 or votes.get("Missing", 0) or sum(votes.values()) != n:
            raise ValueError("Analysis requires complete reference ratings")
        group = groups[row["stage"], row["label_source"]][row["case_id"]]
        for i, value in enumerate(("Yes", "No", "Unclear")):
            group[i] += votes.get(value, 0)
        group[3] += n
    results = []
    for (stage, source), clusters in sorted(groups.items()):
        values = [clusters[k] for k in sorted(clusters)]
        totals = [sum(v[i] for v in values) for i in range(4)]
        rng = random.Random(seed)
        draws = []
        for _ in range(replicates):
            sampled = rng.choices(values, k=len(values))
            draws.append(rate(sum(v[0] for v in sampled), sum(v[3] for v in sampled)))
        results.append({"stage": stage, "label_source": source, "admissions": len(values),
                        "votes": dict(zip(("Yes", "No", "Unclear"), totals[:3])),
                        "n": totals[3], "reference_supported_rate": rate(totals[0], totals[3]),
                        "ci95": [quantile(draws, .025), quantile(draws, .975)] if len(values) > 1 else None})
    return {"study_type": "reference_label", "bootstrap_seed": seed,
            "bootstrap_replicates": replicates, "reference_results": results}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--export", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--seed", default=42, type=int)
    parser.add_argument("--replicates", default=2000, type=int)
    args = parser.parse_args()
    if args.out.exists():
        parser.error("Output already exists")
    if (args.export / "label_ratings.jsonl").is_file():
        result = analyze_reference(read_jsonl(args.export / "label_ratings.jsonl"),
                                   seed=args.seed, replicates=args.replicates)
    else:
        result = analyze(read_jsonl(args.export / "trace_ratings.jsonl"),
                         seed=args.seed, replicates=args.replicates)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("x", encoding="utf-8") as handle:
        json.dump(result, handle, indent=2, allow_nan=False)
        handle.write("\n")
    print("Analysis complete.")


if __name__ == "__main__":
    main()
