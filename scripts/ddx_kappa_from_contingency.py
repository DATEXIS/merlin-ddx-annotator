#!/usr/bin/env python
"""Recompute the published DDx inter-rater kappa values from the published matrices.

    python scripts/ddx_kappa_from_contingency.py

Reads results/ddx_annotation/agreement_contingency_matrices.csv (candidate-level
2 x 2 tables) and checks Cohen's kappa, p_o and p_e against
results/ddx_annotation/inter_rater_agreement.csv. Exits non-zero on a mismatch.
"""
from __future__ import annotations

import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "results" / "ddx_annotation"


def kappa(both: int, first: int, second: int, neither: int) -> tuple[float, float, float]:
    total = both + first + second + neither
    p_o = (both + neither) / total
    p_a, p_b = (both + first) / total, (both + second) / total
    p_e = p_a * p_b + (1 - p_a) * (1 - p_b)
    return p_o, p_e, (p_o - p_e) / (1 - p_e)


def main() -> int:
    with (RESULTS / "inter_rater_agreement.csv").open(newline="", encoding="utf-8") as handle:
        published = {row["pair"]: row for row in csv.DictReader(handle) if row["statistic"] == "pairwise"}
    failures = 0
    with (RESULTS / "agreement_contingency_matrices.csv").open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            p_o, p_e, k = kappa(*(int(row[c]) for c in ("both_selected", "first_only", "second_only", "neither")))
            target = published[row["pair"]]
            ok = all(abs(value - float(target[name])) < 5e-6 for value, name in
                     ((p_o, "p_o"), (p_e, "p_e"), (k, "cohen_kappa")))
            ok = ok and int(row["n_cases"]) == int(target["n_cases_kappa"])
            failures += not ok
            print(f"{row['pair']}: kappa {k:.4f} (published {float(target['cohen_kappa']):.4f}, "
                  f"n = {row['n_cases']}) {'ok' if ok else 'MISMATCH'}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
