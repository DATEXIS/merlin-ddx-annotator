"""Synthetic tests for the separate, one-clinician preliminary path."""
import csv
import json
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from merlin_ddx.rebuttal_analysis import AuditValidationError
from merlin_ddx.rebuttal_preliminary import run_preliminary
from test_rebuttal_analysis import make_synthetic_batch


def test_preliminary_requires_complete_one_rater_before_key(tmp_path: Path):
    blinded, keyed, raters = make_synthetic_batch(tmp_path / "inputs")
    records = json.loads(raters["rater_one"].read_text())
    records[0]["pairs"]["1"]["B_Q2"] = None
    raters["rater_one"].write_text(json.dumps(records))
    keyed.unlink()
    output = tmp_path / "report"
    with pytest.raises(AuditValidationError, match="Missing or invalid B_Q2"):
        run_preliminary(blinded_path=blinded, keyed_path=keyed, rater_id="rater_one",
                        annotation_path=raters["rater_one"], output_dir=output)
    assert not output.exists()


def test_preliminary_decodes_arms_and_conditions_without_interrater_analysis(tmp_path: Path):
    blinded, keyed, raters = make_synthetic_batch(tmp_path / "inputs")
    key_rows = list(csv.DictReader(keyed.open()))
    key_rows[0]["_loop_score"] = "0.2"
    with keyed.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(key_rows[0]))
        writer.writeheader()
        writer.writerows(key_rows)
    records = json.loads(raters["rater_one"].read_text())
    records[0]["pairs"]["1"]["A_Q2"] = "No"
    raters["rater_one"].write_text(json.dumps(records))
    output = run_preliminary(blinded_path=blinded, keyed_path=keyed, rater_id="rater_one",
                             annotation_path=raters["rater_one"], output_dir=tmp_path / "report",
                             bootstrap_replicates=10_000, seed=42)
    decoded = pd.read_csv(output / "audit_batch1_preliminary_deepdive.csv", dtype={"pair_id": str})
    assert len(decoded) == 84
    assert decoded.pair_id.nunique() == 84
    assert decoded.loc[decoded.pair_id == "1", "loop_Q2"].item() == "No"
    assert decoded.loc[decoded.pair_id == "1", "loop_verifier_score"].item() == .2
    assert decoded.loc[decoded.pair_id == "1", "loop_target"].item() == "Pneumonia"
    assert decoded.loc[decoded.pair_id == "1", "target_preference"].isna().all()
    conditions = pd.read_csv(output / "audit_batch1_conditional_preference.csv")
    assert conditions.loc[(conditions.stage == "V2") & (conditions.basis == "Q2") &
                          (conditions.condition == "zero_shot_only_yes"), "n_pairs"].item() == 1
    assert (output / "audit_batch1_both_valid_preference_review.csv").exists()
    report = (output / "audit_batch1_report.md").read_text()
    assert "Preliminary: one clinician completed" in report
    assert "Loop-accepted versus loop-rejected" in report
    assert "inter-rater agreement is computed" in report
    assert "Inter-rater agreement" not in report


def test_gt_secondary_keeps_raw_references_and_preserves_mapping_review(tmp_path: Path):
    blinded, keyed, raters = make_synthetic_batch(tmp_path / "inputs")
    ground_truth = tmp_path / "ground_truth.pq"
    pq.write_table(pa.Table.from_pylist([
        {"hadm_id": 20_000_000 + index, "discharge_diagnosis": "Pneumonia\nCough",
         "mapped_disease_candidate": "Pneumonia",
         "icd_codes": ["J18.9", "E11.9"] if index % 3 == 0 else ["E11.9", "Z99.9"]}
        for index in range(42)
    ]), ground_truth)
    options = dict(blinded_path=blinded, keyed_path=keyed, rater_id="rater_one",
                   annotation_path=raters["rater_one"], output_dir=tmp_path / "report",
                   ground_truth_path=ground_truth)
    output = run_preliminary(**options)
    pairs = pd.read_csv(output / "audit_batch1_gt_concordance_pairs.csv", dtype=str)
    assert len(pairs) == 84
    assert pairs.discharge_diagnosis_raw.iloc[0] == "Pneumonia\nCough"
    assert pairs.mapped_disease_candidate.iloc[0] == "Pneumonia"
    assert json.loads(pairs.discharge_icd_codes_raw.iloc[0]) == ["J18.9", "E11.9"]
    assert pairs.discharge_primary_diagnosis.isna().all()
    table_b = pd.read_csv(output / "audit_batch1_gt_table_B_strata.csv")
    full = table_b[(table_b.stage == "V4") & (table_b.gt_definition == "full_code")]
    assert full.loc[full.reference_match_stratum == "both_match", "n_pairs"].item() == 14
    assert full.n_pairs.sum() == 42
    assert "discharge_reviewed" not in table_b.gt_definition.to_numpy()
    mapping_path = output / "audit_v2_gt_mapping_review.csv"
    mapping = pd.read_csv(mapping_path, dtype=str, keep_default_na=False)
    assert mapping.mapped_disease_candidate.eq("Pneumonia").all()
    assert mapping.loc[mapping.model_target == "Pneumonia", "candidate_exact_target"].eq("True").all()
    index = mapping.index[mapping.model_target == "Cough"][0]
    mapping.at[index, "reviewer_status"] = "match"
    mapping.at[index, "reviewer_comment"] = "Synthetic reviewer confirmation"
    mapping.at[index, "agent_status"] = "clinically_related_but_not_equivalent"
    mapping.at[index, "agent_confidence"] = "0.77"
    mapping.at[index, "agent_comment"] = "Synthetic AI first-pass comment"
    mapping.at[index, "agent_candidate_note"] = "Candidate differs from this target"
    mapping.to_csv(mapping_path, index=False)
    run_preliminary(**options)
    updated = pd.read_csv(mapping_path, dtype=str, keep_default_na=False)
    assert updated.loc[index, "reviewer_status"] == "match"
    assert updated.loc[index, "reviewer_comment"] == "Synthetic reviewer confirmation"
    assert updated.loc[index, "agent_status"] == "clinically_related_but_not_equivalent"
    assert updated.loc[index, "agent_confidence"] == "0.77"
    assert updated.loc[index, "agent_comment"] == "Synthetic AI first-pass comment"
    assert updated.loc[index, "agent_candidate_note"] == "Candidate differs from this target"
    updated_pairs = pd.read_csv(output / "audit_batch1_gt_concordance_pairs.csv", dtype=str)
    updated_table = pd.read_csv(output / "audit_batch1_gt_table_B_strata.csv")
    assert "discharge_reviewed" in updated_table.gt_definition.to_numpy()
    reviewed_pair = updated_pairs[updated_pairs.hadm_id == updated.loc[index, "hadm_id"]]
    reviewed_v2 = reviewed_pair[reviewed_pair.stage == "V2"].iloc[0]
    reviewed_arm = "loop" if reviewed_v2.loop_target == "Cough" else "zero_shot"
    assert reviewed_v2[f"{reviewed_arm}_discharge_reviewed"] == "True"
    updated.at[index, "agent_confidence"] = "1.2"
    updated.to_csv(mapping_path, index=False)
    with pytest.raises(AuditValidationError, match="agent confidence must be between 0 and 1"):
        run_preliminary(**options)
