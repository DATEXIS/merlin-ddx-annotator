"""Synthetic checks for the selected retrospective diagnosis integration."""
import csv
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from merlin_ddx.rebuttal_adjudicated import load_adjudicated
from merlin_ddx.rebuttal_analysis import AuditValidationError, run_pipeline
from test_rebuttal_analysis import make_synthetic_batch


def _reference(path: Path) -> None:
    rows = [{"hadm_id": 20_000_000 + index,
             "best_supported_diagnosis": "Pneumonia",
             "icd_code_raw": "J189", "icd_code_normalized": "J18.9",
             "support_type": "both", "supporting_discharge_diagnosis": "Pneumonia",
             "original_mapped_disease": "Pneumonia", "adjudication_note": "Synthetic reference"}
            for index in range(42)]
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def test_selected_reference_is_integrated_after_blinded_completion(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("MPLCONFIGDIR", str(tmp_path / "mplcache"))
    blinded, keyed, raters = make_synthetic_batch(tmp_path / "inputs")
    reference = tmp_path / "adjudicated.csv"
    _reference(reference)
    ground_truth = tmp_path / "ground_truth.pq"
    pq.write_table(pa.Table.from_pylist([
        {"hadm_id": 20_000_000 + index, "discharge_diagnosis": "Pneumonia\nCough",
         "mapped_disease_candidate": "Pneumonia",
         "icd_codes": ["J18.9", "E11.9"] if index % 3 == 0 else ["E11.9", "Z99.9"]}
        for index in range(42)
    ]), ground_truth)
    output = run_pipeline(blinded_path=blinded, keyed_path=keyed, raters=raters,
                          output_dir=tmp_path / "out", adjudicated_path=reference,
                          ground_truth_path=ground_truth)
    summary = pd.read_csv(output / "adjudicated_reference_pair_summary.csv").set_index("reference")
    judgments = pd.read_csv(output / "adjudicated_reference_judgment_summary.csv")
    assert summary.loc["selected_icd3", "both_match_n"] == 42
    assert summary.loc["selected_icd_full", "both_match_n"] == 14
    assert summary.loc["selected_icd_full", "one_match_n"] == 28
    assert judgments[judgments.rater == "pooled"].n_judgments.eq(84).all()
    report = (output / "audit_batch1_report.md").read_text()
    assert "Secondary selected retrospective discharge reference" in report
    assert "Detailed final-dataset analyses" in report
    assert not any(line.startswith("| ") and "| unreviewed |" in line
                   for line in report.splitlines())
    for rater in raters:
        assert len(pd.read_csv(output / "details" / rater / "decoded.csv")) == 84
        assert len(pd.read_csv(output / "details" / rater / "audit_batch1_gt_table_B_strata.csv")) > 0
    assert (output / "adjudicated_reference_judgments.csv").stat().st_mode & 0o077 == 0


def test_adjudicated_code_mismatch_is_rejected(tmp_path: Path):
    reference = tmp_path / "adjudicated.csv"
    _reference(reference)
    frame = pd.read_csv(reference, dtype=str, keep_default_na=False)
    frame.at[0, "icd_code_normalized"] = "J18.1"
    frame.to_csv(reference, index=False)
    with pytest.raises(AuditValidationError, match="raw and normalized ICD codes disagree"):
        load_adjudicated(reference, set(frame.hadm_id))
