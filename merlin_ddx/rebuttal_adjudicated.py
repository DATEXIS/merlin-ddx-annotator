"""Secondary comparison with one selected retrospective diagnosis per admission.

V2 matching here is deliberately literal. A broad or synonymous diagnosis is
not silently declared wrong merely because it differs from the selected name.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.dataset as ds

from merlin_ddx.rebuttal_analysis import _markdown_table, _name, _read_csv, _require, _string
from merlin_ddx.rebuttal_gt_concordance import normalize_icd

SUPPORT_TYPES = {"both", "both_icd_refines", "both_hedged", "ICD_only", "both_icd_broader"}


def load_adjudicated(path: Path, expected_ids: set[str], source_path: Path | None = None) -> pd.DataFrame:
    reference = _read_csv(path)
    required = {"hadm_id", "best_supported_diagnosis", "icd_code_raw", "icd_code_normalized",
                "support_type", "supporting_discharge_diagnosis", "original_mapped_disease",
                "adjudication_note"}
    _require(required <= set(reference), f"Adjudicated reference lacks {sorted(required - set(reference))}")
    _require(len(reference) == 42 and reference.hadm_id.nunique() == 42,
             "Adjudicated reference needs exactly 42 unique admissions")
    _require(set(reference.hadm_id) == expected_ids,
             "Adjudicated admission IDs differ from frozen audit batch")
    for field in ("best_supported_diagnosis", "icd_code_raw", "icd_code_normalized",
                  "original_mapped_disease", "adjudication_note"):
        _require(reference[field].map(lambda value: bool(_string(value))).all(),
                 f"Adjudicated reference has missing {field}")
    _require(reference.support_type.isin(SUPPORT_TYPES).all(), "Unknown adjudication support_type")
    _require(reference.loc[reference.support_type != "ICD_only", "supporting_discharge_diagnosis"]
             .map(lambda value: bool(_string(value))).all(),
             "Discharge-supported adjudications need supporting diagnosis text")
    reference["adjudicated_code"] = reference.icd_code_raw.map(normalize_icd)
    _require(reference.adjudicated_code.eq(reference.icd_code_normalized.map(normalize_icd)).all(),
             "Adjudicated raw and normalized ICD codes disagree")
    if source_path is not None:
        source = ds.dataset(source_path, format="parquet")
        _require({"hadm_id", "ICD_CODES", "disease"} <= set(source.schema.names),
                 "Raw source lacks fields needed to verify adjudication")
        ids = [int(value) for value in expected_ids]
        raw = source.to_table(columns=["hadm_id", "ICD_CODES", "disease"],
                              filter=pc.is_in(pc.field("hadm_id"), value_set=pa.array(ids, type=pa.int64()))).to_pylist()
        by_id: dict[str, list[dict]] = {}
        for row in raw:
            by_id.setdefault(str(row["hadm_id"]), []).append(row)
        _require(set(by_id) == expected_ids, "Raw source does not cover adjudicated admissions")
        for row in reference.itertuples():
            source_rows = by_id[row.hadm_id]
            _require(len(source_rows) == 3, f"Expected three source rows for {row.hadm_id}")
            _require(all(source_row["disease"] == row.original_mapped_disease for source_row in source_rows),
                     f"Adjudicated mapped disease differs from source for {row.hadm_id}")
            _require(all(row.adjudicated_code in {normalize_icd(code) for code in source_row["ICD_CODES"]}
                         for source_row in source_rows),
                     f"Adjudicated ICD code is absent from source for {row.hadm_id}")
    return reference


def prepare_adjudicated(joined: pd.DataFrame, reference: pd.DataFrame) -> pd.DataFrame:
    _require(len(joined) == 168 and joined.pair_id.nunique() == 84 and joined.hadm_id.nunique() == 42,
             "Two-rater analysis must contain 168 judgments for 84 pairs")
    frame = joined.merge(reference, on="hadm_id", validate="many_to_one")
    _require(len(frame) == len(joined), "Adjudicated join changed judgment count")
    for arm in ("loop", "zero_shot"):
        target = frame.target_A.where(frame.A_arm == arm, frame.target_B)
        frame[f"{arm}_target"] = target
        frame[f"{arm}_adjudicated_v2_exact"] = [
            _name(value) == _name(best) if stage == "V2" else None
            for value, best, stage in zip(target, frame.best_supported_diagnosis, frame.stage, strict=True)
        ]
        frame[f"{arm}_adjudicated_v4_full"] = [
            normalize_icd(value) == code if stage == "V4" else None
            for value, code, stage in zip(target, frame.adjudicated_code, frame.stage, strict=True)
        ]
        frame[f"{arm}_adjudicated_v4_icd3"] = [
            normalize_icd(value)[:3] == code[:3] if stage == "V4" else None
            for value, code, stage in zip(target, frame.adjudicated_code, frame.stage, strict=True)
        ]
    return frame


REFERENCES = (("V2", "selected_diagnosis_literal", "adjudicated_v2_exact"),
              ("V4", "selected_icd_full", "adjudicated_v4_full"),
              ("V4", "selected_icd3", "adjudicated_v4_icd3"))


def adjudicated_pair_summary(frame: pd.DataFrame) -> pd.DataFrame:
    """Count deterministic target matches once per pair, regardless of rater."""
    rows = []
    for stage, label, column in REFERENCES:
        data = frame[frame.stage == stage]
        for arm in ("loop", "zero_shot"):
            _require(data.groupby("pair_id")[f"{arm}_{column}"].nunique().eq(1).all(),
                     "Selected-reference match differs across raters")
        pairs = data.drop_duplicates("pair_id")
        loop = pairs[f"loop_{column}"].astype(bool)
        zero = pairs[f"zero_shot_{column}"].astype(bool)
        rows.append({"stage": stage, "reference": label, "n_pairs": len(pairs),
                     "loop_match_n": int(loop.sum()), "zero_shot_match_n": int(zero.sum()),
                     "both_match_n": int((loop & zero).sum()),
                     "one_match_n": int((loop ^ zero).sum()),
                     "neither_match_n": int((~loop & ~zero).sum())})
    return pd.DataFrame(rows)


def adjudicated_judgment_summary(frame: pd.DataFrame, rater_ids: list[str]) -> pd.DataFrame:
    """Keep Q2 and preference counts at clinician-judgment level."""
    rows = []
    for stage, label, column in REFERENCES:
        for rater, data in [("pooled", frame[frame.stage == stage])] + [
            (rater_id, frame[(frame.stage == stage) & (frame.rater_id == rater_id)])
            for rater_id in rater_ids
        ]:
            loop = data[f"loop_{column}"].astype(bool)
            zero = data[f"zero_shot_{column}"].astype(bool)
            matching = data[loop ^ zero]
            selected_arm = matching[f"loop_{column}"].map(lambda value: "loop" if value else "zero_shot")
            rows.append({
                "stage": stage, "reference": label, "rater": rater,
                "n_judgments": len(data), "one_match_judgments": len(matching),
                "loop_Q2_yes_when_match_n": int((loop & data.loop_Q2.eq("Yes")).sum()),
                "zero_shot_Q2_yes_when_match_n": int((zero & data.zero_shot_Q2.eq("Yes")).sum()),
                "target_prefers_selected_n": int((matching.target_preferred.to_numpy() == selected_arm.to_numpy()).sum()),
                "target_prefers_other_n": int(((matching.target_preferred != "equivalent") &
                                                 (matching.target_preferred.to_numpy() != selected_arm.to_numpy())).sum()),
                "target_equal_n": int(matching.target_preferred.eq("equivalent").sum()),
                "rationale_prefers_selected_n": int((matching.rationale_preferred.to_numpy() == selected_arm.to_numpy()).sum()),
                "rationale_prefers_other_n": int(((matching.rationale_preferred != "equivalent") &
                                                    (matching.rationale_preferred.to_numpy() != selected_arm.to_numpy())).sum()),
                "rationale_equivalent_n": int(matching.rationale_preferred.eq("equivalent").sum()),
            })
    return pd.DataFrame(rows)


def report_section(pair_summary: pd.DataFrame, judgment_summary: pd.DataFrame,
                   reference: pd.DataFrame) -> str:
    support = reference.support_type.value_counts().to_dict()
    icd3 = pair_summary[pair_summary.reference == "selected_icd3"].iloc[0]
    full = pair_summary[pair_summary.reference == "selected_icd_full"].iloc[0]
    selected_comparison = (
        f"Across the 42 V4 pairs, the selected ICD3 matched the loop target in "
        f"{icd3.loop_match_n}/42 and the zero-shot target in {icd3.zero_shot_match_n}/42; "
        f"the selected full code matched in {full.loop_match_n}/42 and "
        f"{full.zero_shot_match_n}/42, respectively. These are descriptive selected-reference "
        "counts, not clinician judgments or a test against the complete discharge ICD list."
    )
    return "\n".join([
        "## Secondary selected retrospective discharge reference", "",
        "The selected diagnosis and ICD code are retrospective, one per admission. An admission "
        "may legitimately have several diagnoses; non-match to the selected item does not imply an "
        "incorrect target. The full discharge ICD list is a more complete retrospective code reference. "
        "The selected item is separate from admission-time clinician judgments. "
        f"All 42 admissions are covered; support types: {support}. The chosen code was checked against "
        "each source model row. `selected_diagnosis_literal` is a strict normalized-name screen only: "
        "a synonymous or broader clinically plausible V2 target may fail it. V4 full-code and ICD3 "
        "checks compare each displayed target with the one selected code. A match or non-match "
        "is not interpreted as establishing admission-time correctness or rationale quality.", "",
        "Deterministic target matches are counted once per pair (42 per stage):", "",
        _markdown_table(pair_summary), "",
        "Clinician Q2 judgments and preferences are counted separately (84 pooled judgments per "
        "stage). Preference counts include only judgments where exactly one displayed target "
        "matches the selected reference; ties are retained:", "",
        _markdown_table(judgment_summary), "",
        "Pair and clinician-judgment tables and the private case-level join are in "
        "`adjudicated_reference_pair_summary.csv`, `adjudicated_reference_judgment_summary.csv`, "
        "and `adjudicated_reference_judgments.csv`.", "",
        selected_comparison, "",
    ])
