#!/usr/bin/env python
"""Reproduce the cohort-level clinician-audit results from the PhysioNet per-item aggregates.

    python scripts/reproduce_from_credentialed.py \
        --per-item /path/to/physionet/per_item_aggregate_ratings.csv \
        --case-mapping /path/to/physionet/case_mapping.csv \
        --compare results

Credentialed users receive per-item aggregate ratings (both clinicians' categories
per item, without saying which clinician gave which). From these alone this script
recomputes, with the study's definitions:

* Q1 = Yes, Q2 = Yes and composite-validity rates per stage and arm, with 95% CIs;
* loop minus zero-shot differences (percentage points) with 95% CIs;
* target- and rationale-preference margins with 95% CIs;
* raw inter-rater agreement for every criterion.

Intervals use the original admission-cluster percentile bootstrap (10,000 replicates,
seed 20260917, NumPy ``default_rng(seed).multinomial``). The original analysis ordered
admissions by MIMIC-IV ``hadm_id``; with ``--case-mapping`` that order is restored and
the intervals match the published ones exactly; without it, admissions are ordered by
``case_id`` and intervals agree up to Monte Carlo error.

Not reproducible from these data: Cohen's kappa for measures released in reduced form,
per-clinician analyses and the Unclear sensitivity analysis (they need individual
ratings, which are not released). With ``--compare`` the results are checked against
the public ``results/`` files; exits 1 on any difference.
"""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
SEED, REPLICATES = 20260917, 10_000


def read(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def percentile(draws: np.ndarray) -> tuple[float | None, float | None]:
    finite = draws[np.isfinite(draws)]
    if not len(finite) or len(finite) < 0.95 * len(draws):
        return None, None
    low, high = np.percentile(finite, [2.5, 97.5])
    return float(low), float(high)


class Bootstrap:
    def __init__(self, cases: list[str], seed: int = SEED, replicates: int = REPLICATES):
        self.index = {c: i for i, c in enumerate(cases)}
        self.counts = np.random.default_rng(seed).multinomial(len(cases), [1 / len(cases)] * len(cases), size=replicates)

    def sums(self, cases: list[str], values: list[float]) -> np.ndarray:
        vector = np.zeros(len(self.index))
        for case, value in zip(cases, values):
            vector[self.index[case]] += value
        return self.counts @ vector

    def ratio(self, cases, numerator, denominator) -> np.ndarray:
        num, den = self.sums(cases, numerator), self.sums(cases, denominator)
        with np.errstate(divide="ignore", invalid="ignore"):
            return np.where(den > 0, num / np.where(den > 0, den, 1), np.nan)


def reproduce(per_item: list[dict[str, str]], order_key: dict[str, str] | None = None) -> dict:
    cases = sorted({r["case_id"] for r in per_item}, key=lambda c: (order_key or {}).get(c, c))
    boot = Bootstrap(cases)
    out: dict = {"rates": {}, "differences": {}, "preferences": {}, "raw_agreement": {}}
    stages = sorted({r["stage"] for r in per_item})
    for stage in stages:
        for criterion, favourable in (("Q1_evidence_grounded", "Yes"), ("Q2_supports_target", "Yes"),
                                      ("valid_composite", "valid")):
            per_arm = {}
            for arm in ("loop", "zero_shot"):
                rows = [r for r in per_item if r["stage"] == stage and r["condition"] == arm and r["criterion"] == criterion]
                yes = [json.loads(r["rating_distribution"])[favourable] for r in rows]
                n = [int(r["n_raters"]) for r in rows]
                c = [r["case_id"] for r in rows]
                low, high = percentile(boot.ratio(c, yes, n))
                out["rates"][(stage, arm, criterion)] = {"n_judgments": sum(n), "favourable_n": sum(yes),
                                                         "pct": 100 * sum(yes) / sum(n),
                                                         "ci_low": 100 * low, "ci_high": 100 * high}
                per_arm[arm] = (c, yes, n)
            loop, zero = per_arm["loop"], per_arm["zero_shot"]
            draws = boot.ratio(*loop) - boot.ratio(*zero)
            low, high = percentile(draws)
            out["differences"][(stage, criterion)] = {
                "estimate": 100 * (sum(loop[1]) / sum(loop[2]) - sum(zero[1]) / sum(zero[2])),
                "ci_low": 100 * low, "ci_high": 100 * high}
        for preference in ("rationale_preference", "target_preference"):
            rows = [r for r in per_item if r["stage"] == stage and r["criterion"] == preference and int(r["n_raters"]) > 0]
            dist = [json.loads(r["rating_distribution"]) for r in rows]
            c = [r["case_id"] for r in rows]
            n = [int(r["n_raters"]) for r in rows]
            loop_n, zero_n = [d["loop"] for d in dist], [d["zero_shot"] for d in dist]
            low, high = percentile(boot.ratio(c, loop_n, n) - boot.ratio(c, zero_n, n))
            out["preferences"][(stage, preference)] = {
                "loop_n": sum(loop_n), "zero_shot_n": sum(zero_n), "n_judgments": sum(n),
                "margin": 100 * (sum(loop_n) - sum(zero_n)) / sum(n), "ci_low": 100 * low, "ci_high": 100 * high}
        for criterion in ("Q1_evidence_grounded", "Q2_supports_target", "valid_composite",
                          "rationale_preference", "target_preference"):
            rows = [r for r in per_item if r["stage"] == stage and r["criterion"] == criterion and int(r["n_raters"]) == 2]
            if rows:
                out["raw_agreement"][f"{stage}.{criterion}"] = sum(float(r["agreement_fraction"]) for r in rows) / len(rows)
    return out


def compare(result: dict, results_dir: Path) -> list[str]:
    problems = []
    close = lambda a, b, tol=1e-3: abs(float(a) - float(b)) <= tol  # noqa: E731  (public files keep 4 decimals)
    for row in read(results_dir / "cohort_aggregate_ratings.csv"):
        if row["level"] != "rationale":
            continue
        mine = result["rates"][(row["stage"], row["condition"], row["criterion"])]
        for field, theirs in (("pct", row["favourable_pct"]), ("ci_low", row["ci95_low_pct"]), ("ci_high", row["ci95_high_pct"])):
            if not close(mine[field], theirs):
                problems.append(f"rate {row['stage']}/{row['condition']}/{row['criterion']} {field}: {mine[field]:.4f} vs {theirs}")
    for row in read(results_dir / "comparative_results.csv"):
        if row["comparison"] != "loop_minus_zero_shot":
            continue
        if row["measure"].endswith("_favourable_rate_difference"):
            mine = result["differences"][(row["stage"], row["measure"].replace("_favourable_rate_difference", ""))]
            pairs = (("estimate", row["estimate"]), ("ci_low", row["ci95_low"]), ("ci_high", row["ci95_high"]))
        else:
            mine = result["preferences"][(row["stage"], row["measure"].replace("_margin", ""))]
            pairs = (("margin", row["estimate"]), ("ci_low", row["ci95_low"]), ("ci_high", row["ci95_high"]))
        for field, theirs in pairs:
            if not close(mine[field], theirs):
                problems.append(f"{row['stage']} {row['measure']} {field}: {mine[field]:.4f} vs {theirs}")
    statistics = json.loads((results_dir / "agreement_statistics.json").read_text())
    for measure in statistics["measures"]:
        mine = result["raw_agreement"].get(measure["id"])
        if mine is None or abs(mine - measure["raw_agreement"]) > 1e-9:
            problems.append(f"raw agreement {measure['id']}: {mine} vs {measure['raw_agreement']}")
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--per-item", type=Path, required=True)
    parser.add_argument("--case-mapping", type=Path, help="restores the original bootstrap order (credentialed)")
    parser.add_argument("--compare", type=Path, help="public results/ directory to check against")
    args = parser.parse_args()
    order = {r["case_id"]: r["hadm_id"] for r in read(args.case_mapping)} if args.case_mapping else None
    result = reproduce(read(args.per_item), order)
    for (stage, criterion), d in sorted(result["differences"].items()):
        print(f"{stage} {criterion:22} loop - zero-shot {d['estimate']:7.2f} pp  [{d['ci_low']:.2f}, {d['ci_high']:.2f}]")
    for measure, value in sorted(result["raw_agreement"].items()):
        print(f"raw agreement {measure:34} {value:.4f}")
    if args.compare:
        problems = compare(result, args.compare)
        for problem in problems:
            print("MISMATCH", problem)
        print("all published cohort statistics reproduced" if not problems else f"{len(problems)} differences")
        return 1 if problems else 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
