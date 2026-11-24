#!/usr/bin/env python3
"""Build the local one-clinician preliminary rebuttal-audit deep dive."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from merlin_ddx.rebuttal_analysis import AuditValidationError  # noqa: E402
from merlin_ddx.rebuttal_preliminary import run_preliminary  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    source = ROOT / "data/source/merlin_rebuttal_audit"
    parser.add_argument("--blinded", type=Path, default=source / "audit_batch1_blinded.csv")
    parser.add_argument("--keyed", type=Path, default=source / "audit_batch1_keyed.csv")
    parser.add_argument("--ground-truth", type=Path, default=source / "audit_batch1_ground_truth.pq",
                        help="Private discharge-reference extract; adds secondary GT concordance")
    parser.add_argument("--rater", required=True, help="Clinician ID in the export, e.g. clinician1")
    parser.add_argument("--annotations", required=True, type=Path,
                        help="One clinician's app JSON export, JSON directory, or long CSV")
    parser.add_argument("--out", type=Path,
                        default=ROOT / "reports/merlin_rebuttal_audit/batch1_preliminary")
    parser.add_argument("--bootstrap", type=int, default=10_000)
    parser.add_argument("--seed", type=int, default=20260917)
    args = parser.parse_args()
    try:
        path = run_preliminary(blinded_path=args.blinded, keyed_path=args.keyed,
                               rater_id=args.rater, annotation_path=args.annotations,
                               output_dir=args.out, ground_truth_path=args.ground_truth,
                               bootstrap_replicates=args.bootstrap,
                               seed=args.seed)
    except (AuditValidationError, OSError, ValueError) as exc:
        parser.exit(2, f"Preliminary audit stopped: {exc}\n")
    print(f"Preliminary one-clinician analysis written to {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
