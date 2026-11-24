#!/usr/bin/env python3
"""Offline evaluator for the completed blinded two-clinician audit.

No analysis runs without two explicit annotation-export paths. The keyed CSV
is not opened until the blinded completion checks pass.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from merlin_ddx.rebuttal_analysis import (  # noqa: E402
    AuditValidationError,
    load_annotation_export,
    run_pipeline,
    validate_blinded_and_annotations,
    _read_csv,
)
import pandas as pd  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    source = ROOT / "data/source/merlin_rebuttal_audit"
    parser.add_argument("--blinded", type=Path, default=source / "audit_batch1_blinded.csv")
    parser.add_argument("--keyed", type=Path, default=source / "audit_batch1_keyed.csv")
    parser.add_argument("--adjudicated", type=Path,
                        default=ROOT / "reports/merlin_rebuttal_audit/batch1_preliminary/audit_batch1_adjudicated_ground_truth.csv",
                        help="One selected retrospective diagnosis and ICD code per admission")
    parser.add_argument("--raw-source", type=Path, default=ROOT / "data/source/combined_1_4.pq",
                        help="Source Parquet used to verify every selected ICD code")
    parser.add_argument("--ground-truth", type=Path, default=source / "audit_batch1_ground_truth.pq",
                        help="Full discharge text and ordered ICD lists for detailed two-rater analyses")
    parser.add_argument("--mapping-review", type=Path,
                        default=ROOT / "reports/merlin_rebuttal_audit/batch1_preliminary/audit_v2_gt_mapping_review.csv",
                        help="Private V2 mapping review; AI statuses remain separate from human review")
    parser.add_argument("--rater", action="append", required=True, metavar="ID=PATH",
                        help="Repeat exactly twice; PATH is an app JSON export directory, JSON file, or long CSV")
    parser.add_argument("--out", type=Path, default=ROOT / "reports/merlin_rebuttal_audit/batch1")
    parser.add_argument("--bootstrap", type=int, default=10_000)
    parser.add_argument("--seed", type=int, default=20260917)
    parser.add_argument("--validate-only", action="store_true",
                        help="Check blinded completion only; do not open the key or write outputs")
    args = parser.parse_args()
    raters: dict[str, Path] = {}
    for specification in args.rater:
        if "=" not in specification:
            parser.error("--rater must be ID=PATH")
        rater_id, path = specification.split("=", 1)
        if not rater_id or not path or rater_id in raters:
            parser.error("--rater IDs and paths must be nonempty and IDs distinct")
        raters[rater_id] = Path(path)
    if len(raters) != 2:
        parser.error("Supply exactly two --rater ID=PATH arguments")
    try:
        if args.validate_only:
            blinded = _read_csv(args.blinded)
            ratings = pd.concat([load_annotation_export(path, rater) for rater, path in raters.items()],
                                ignore_index=True)
            _, counts = validate_blinded_and_annotations(blinded, ratings, list(raters))
            print(f"Blinded completion passed: {counts['n_pairs']} pairs, "
                  f"{counts['n_admissions']} admissions, {counts['n_rater_judgments']} judgments. "
                  "Key was not opened; no report was written.")
        else:
            output = run_pipeline(blinded_path=args.blinded, keyed_path=args.keyed, raters=raters,
                                  output_dir=args.out, bootstrap_replicates=args.bootstrap, seed=args.seed,
                                  adjudicated_path=args.adjudicated, raw_source_path=args.raw_source,
                                  ground_truth_path=args.ground_truth, mapping_review_path=args.mapping_review)
            print(f"Audit analysis written to {output}")
    except (AuditValidationError, OSError, ValueError) as exc:
        parser.exit(2, f"Audit evaluation stopped: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
