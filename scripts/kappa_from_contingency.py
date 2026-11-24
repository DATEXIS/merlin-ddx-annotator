#!/usr/bin/env python
"""Recompute Cohen's kappa from the published rater contingency matrices.

    python scripts/kappa_from_contingency.py            # uses results/
    python scripts/kappa_from_contingency.py --results path/to/results

An independent, dependency-free implementation: for every measure published at the
``full`` disclosure level it rebuilds the joint table from
``agreement_contingency_matrices.csv`` and computes

    p_o = sum_c n_cc / n,   p_e = sum_c (n_c. / n)(n_.c / n),   kappa = (p_o - p_e) / (1 - p_e)

(unweighted; undefined when p_e = 1). For ``reduced`` measures only p_o can be
rebuilt (from the concordant counts); kappa is then checked against the published
p_o and p_e. Every value is compared with ``agreement_statistics.json``, and the two
agreement values stated in the paper are checked at their reported precision.
Exits 1 on any mismatch.
"""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PAPER = {"V4.valid_composite": {"raw_agreement": 0.73, "kappa": 0.39}}   # Appendix B, two decimals


def kappa_table(rows: list[dict[str, str]]) -> dict[str, dict]:
    measures: dict[str, list[dict[str, str]]] = {}
    for row in rows:
        measures.setdefault(row["measure_id"], []).append(row)
    result = {}
    for measure_id, cells in measures.items():
        n = int(cells[0]["n_items"])
        level = cells[0]["disclosure_level"]
        if level == "full":
            joint = [c for c in cells if c["cell_type"] == "joint"]
            categories = list(dict.fromkeys(c["rater_A_category"] for c in joint))
            table = {(c["rater_A_category"], c["rater_B_category"]): int(c["count"]) for c in joint}
            total = sum(table.values())
            rows_m = {a: sum(table[(a, b)] for b in categories) for a in categories}
            cols_m = {b: sum(table[(a, b)] for a in categories) for b in categories}
            for kind, marginal in (("marginal_rater_A", rows_m), ("marginal_rater_B", cols_m)):
                published = {c["rater_A_category"] or c["rater_B_category"]: int(c["count"])
                             for c in cells if c["cell_type"] == kind}
                if published != marginal:
                    raise SystemExit(f"{measure_id}: published {kind} disagrees with the joint counts")
            p_o = sum(table[(c, c)] for c in categories) / total
            p_e = sum(rows_m[c] * cols_m[c] for c in categories) / (total * total)
            kappa = (p_o - p_e) / (1 - p_e) if p_e < 1 else None
            result[measure_id] = {"level": level, "n": total, "p_o": p_o, "p_e": p_e, "kappa": kappa}
        else:
            p_o = sum(int(c["count"]) for c in cells if c["cell_type"] == "concordant") / n
            result[measure_id] = {"level": level, "n": n, "p_o": p_o, "p_e": None, "kappa": None}
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--results", type=Path, default=ROOT / "results")
    args = parser.parse_args()
    with (args.results / "agreement_contingency_matrices.csv").open(newline="", encoding="utf-8") as handle:
        recomputed = kappa_table(list(csv.DictReader(handle)))
    published = {m["id"]: m for m in json.loads((args.results / "agreement_statistics.json").read_text())["measures"]}
    failures = 0
    print(f"{'measure':34} {'level':8} {'n':>4} {'p_o':>7} {'p_e':>7} {'kappa':>8}  check")
    for measure_id, mine in recomputed.items():
        ref = published[measure_id]
        close = lambda a, b: (a is None and b is None) or (a is not None and b is not None and abs(a - b) < 1e-12)  # noqa: E731
        if mine["level"] == "full":
            ok = mine["n"] == ref["n_items"] and close(mine["p_o"], ref["raw_agreement"]) and \
                close(mine["p_e"], ref["expected_agreement"]) and close(mine["kappa"], ref["kappa"])
            kappa = mine["kappa"]
        else:
            kappa = (None if ref["expected_agreement"] is None or ref["expected_agreement"] >= 1 else
                     (ref["raw_agreement"] - ref["expected_agreement"]) / (1 - ref["expected_agreement"]))
            ok = mine["n"] == ref["n_items"] and close(mine["p_o"], ref["raw_agreement"]) and close(kappa, ref["kappa"])
        paper = PAPER.get(measure_id)
        if paper:
            ok = ok and round(mine["p_o"], 2) == paper["raw_agreement"] and round(kappa, 2) == paper["kappa"]
        failures += not ok
        p_e = mine["p_e"] if mine["p_e"] is not None else ref["expected_agreement"]
        print(f"{measure_id:34} {mine['level']:8} {mine['n']:>4} {mine['p_o']:7.3f} {p_e:7.3f} "
              f"{'undef.' if kappa is None else f'{kappa:8.3f}':>8}  {'ok' if ok else 'MISMATCH'}"
              + ("  (paper: p_o 0.73, kappa 0.39)" if paper else ""))
    missing = sorted(set(published) - set(recomputed))
    if missing:
        print(f"no contingency rows for: {missing}")
        failures += len(missing)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
