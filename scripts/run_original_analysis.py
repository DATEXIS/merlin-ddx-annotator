#!/usr/bin/env python
"""Run the original primary analysis of the clinician audit.

    python scripts/run_original_analysis.py \
        --blinded audit_batch1_blinded.csv --keyed audit_batch1_keyed.csv \
        --rater rater_1=exports/rater_1 --rater rater_2=exports/rater_2 --out results_run

This calls the study's own pipeline (``merlin_ddx.rebuttal_analysis.run_pipeline``)
unchanged: blinded completion checks first, the allocation key only afterwards,
10,000 admission-cluster bootstrap replicates with seed 20260917, and atomic output.

It differs from the study's command-line entry point ``scripts/analyze_rebuttal_audit.py``
only in leaving out the secondary inputs that entry point always passes (a selected
discharge reference per admission, the raw source table and the discharge text):
those feed retrospective discharge-concordance tables that are not part of the paper
and require credentialed source data. All tables behind the reported clinician-audit
results are produced.

Running it on the study data requires the individual clinician ratings and the
allocation key, which are not distributed. Use
``scripts/make_synthetic_analysis_fixture.py`` to try it on synthetic data.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from merlin_ddx.rebuttal_analysis import AuditValidationError, run_pipeline  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--blinded", type=Path, required=True)
    parser.add_argument("--keyed", type=Path, required=True)
    parser.add_argument("--rater", action="append", required=True, metavar="ID=PATH")
    parser.add_argument("--out", type=Path, required=True, help="must not exist yet")
    parser.add_argument("--bootstrap", type=int, default=10_000)
    parser.add_argument("--seed", type=int, default=20260917)
    args = parser.parse_args()
    raters = {}
    for specification in args.rater:
        rater_id, _, path = specification.partition("=")
        if not rater_id or not path or rater_id in raters:
            parser.error("--rater must be ID=PATH with distinct IDs")
        raters[rater_id] = Path(path)
    try:
        output = run_pipeline(blinded_path=args.blinded, keyed_path=args.keyed, raters=raters, output_dir=args.out,
                              bootstrap_replicates=args.bootstrap, seed=args.seed)
    except (AuditValidationError, OSError, ValueError) as exc:
        parser.exit(2, f"Audit analysis stopped: {exc}\n")
    print(f"Audit analysis written to {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
