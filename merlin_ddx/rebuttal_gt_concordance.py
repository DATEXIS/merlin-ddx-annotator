"""Secondary discharge-reference concordance for a completed clinician audit.

Discharge labels are retrospective references, not admission-time truth. V2
free-text nonmatches remain unresolved until a human reviews the mapping file.
"""
from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from merlin_ddx.rebuttal_analysis import (
    ClusterBootstrap, _markdown_table, _name, _read_csv, _require, _string,
)

REVIEW_STATUSES = {"", "match", "no_match", "clinically_related_but_not_equivalent", "uncertain"}
AGENT_STATUSES = REVIEW_STATUSES - {""}
V2_REFS = ("original_mapping_candidate", "discharge_exact_text")
V4_REFS = ("icd3", "full_code")


def normalize_diagnosis(value: Any) -> str:
    """Normalize case and formatting, never clinical synonyms."""
    value = unicodedata.normalize("NFKC", _string(value)).casefold()
    return " ".join(re.sub(r"[^a-z0-9]+", " ", value).split())


def normalize_icd(value: Any) -> str:
    """Remove only whitespace and decimal punctuation from an ICD-10-CM code."""
    value = re.sub(r"[.\s]", "", _string(value).upper())
    _require(bool(re.fullmatch(r"[A-Z][A-Z0-9]{2,6}", value)),
             f"Invalid ICD formatting: {value!r}")
    return value


def _diagnosis_lines(raw: str) -> list[str]:
    # The source's diagnose_string uses newlines for separate discharge labels.
    # A single line is preserved whole; no comma/semicolon semantic splitting.
    return list(dict.fromkeys(line.strip() for line in raw.splitlines() if line.strip()))


def _bool(value: Any) -> bool:
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    if _string(value).lower() in {"true", "1"}:
        return True
    if _string(value).lower() in {"false", "0"}:
        return False
    raise ValueError(f"Invalid boolean value: {value!r}")


def _status(value: Any) -> str:
    if value is True or isinstance(value, np.bool_) and value:
        return "yes"
    if value is False or isinstance(value, np.bool_) and not value:
        return "no"
    return "unreviewed"


def _load_gt(path: Path, expected_ids: set[str]) -> pd.DataFrame:
    gt = pd.read_parquet(path)
    required = {"hadm_id", "discharge_diagnosis", "mapped_disease_candidate", "icd_codes"}
    _require(required <= set(gt), f"Ground-truth parquet lacks {sorted(required - set(gt))}")
    _require(len(gt) == 42 and gt.hadm_id.nunique() == 42,
             "Ground-truth extract must contain 42 unique admissions")
    gt = gt.copy()
    gt.hadm_id = gt.hadm_id.map(lambda value: str(int(value)))
    _require(set(gt.hadm_id) == expected_ids, "Ground-truth admission IDs differ from audit batch")
    _require(gt.discharge_diagnosis.map(lambda x: isinstance(x, str) and bool(x.strip())).all(),
             "Missing discharge diagnosis text")
    _require(gt.mapped_disease_candidate.map(lambda x: isinstance(x, str) and bool(x.strip())).all(),
             "Missing mapped disease candidate")
    gt["discharge_icd_codes_raw"] = gt.icd_codes.map(list)
    _require(gt.discharge_icd_codes_raw.map(lambda codes: bool(codes)).all(),
             "Missing discharge ICD list")
    gt["discharge_diagnosis_raw"] = gt.discharge_diagnosis
    gt["discharge_diagnoses_lines"] = gt.discharge_diagnosis_raw.map(_diagnosis_lines)
    gt["discharge_full_codes_normalized"] = gt.discharge_icd_codes_raw.map(
        lambda codes: list(dict.fromkeys(normalize_icd(code) for code in codes)))
    gt["discharge_icd3"] = gt.discharge_full_codes_normalized.map(
        lambda codes: list(dict.fromkeys(code[:3] for code in codes)))
    # Neither the audit extract nor combined_1_4.pq designates a primary item.
    # Retain these fields as null instead of inferring primacy from list order.
    gt["discharge_primary_diagnosis"] = gt.get("discharge_primary_diagnosis", None)
    gt["discharge_primary_icd"] = gt.get("discharge_primary_icd", None)
    return gt[["hadm_id", "discharge_diagnosis_raw", "mapped_disease_candidate", "discharge_icd_codes_raw",
               "discharge_diagnoses_lines", "discharge_full_codes_normalized",
               "discharge_icd3", "discharge_primary_diagnosis", "discharge_primary_icd"]]


def _build_mapping(frame: pd.DataFrame, existing_path: Path | None) -> pd.DataFrame:
    v2 = frame[frame.stage == "V2"]
    rows = {}
    for row in v2.itertuples():
        labels = {normalize_diagnosis(x) for x in row.discharge_diagnoses_lines}
        for arm in ("loop", "zero_shot"):
            target = getattr(row, f"{arm}_target")
            key = (row.hadm_id, target)
            rows[key] = {"hadm_id": row.hadm_id, "model_target": target,
                         "discharge_diagnosis_raw": row.discharge_diagnosis_raw,
                         "mapped_disease_candidate": row.mapped_disease_candidate,
                         "candidate_exact_target": normalize_diagnosis(target) == normalize_diagnosis(row.mapped_disease_candidate),
                         "proposed_status": "match" if normalize_diagnosis(target) in labels else "uncertain",
                         "agent_status": "", "agent_confidence": "", "agent_comment": "",
                         "agent_candidate_note": "",
                         "reviewer_status": "", "reviewer_comment": ""}
    mapping = pd.DataFrame(sorted(rows.values(), key=lambda row: (int(row["hadm_id"]), row["model_target"])))
    if existing_path is not None and existing_path.exists():
        existing = pd.read_csv(existing_path, dtype=str, keep_default_na=False)
        needed = {"hadm_id", "model_target", "discharge_diagnosis_raw", "reviewer_status", "reviewer_comment"}
        _require(needed <= set(existing), "Existing V2 mapping review lacks required fields")
        _require(not existing.duplicated(["hadm_id", "model_target"]).any(),
                 "Existing V2 mapping review has duplicate targets")
        proposed_keys = set(zip(mapping.hadm_id, mapping.model_target))
        existing_keys = set(zip(existing.hadm_id, existing.model_target))
        _require(proposed_keys == existing_keys, "Existing V2 mapping review targets differ from audit")
        _require(existing.reviewer_status.isin(REVIEW_STATUSES).all(),
                 "Existing V2 mapping review has an invalid reviewer status")
        if "agent_status" in existing:
            _require(existing.agent_status.isin(AGENT_STATUSES | {""}).all(),
                     "Existing V2 mapping has an invalid agent status")
        if "agent_confidence" in existing:
            confidence = pd.to_numeric(existing.agent_confidence.replace("", np.nan), errors="coerce")
            _require(confidence.dropna().between(0, 1).all(),
                     "Existing V2 mapping agent confidence must be between 0 and 1")
            _require((existing.agent_confidence.eq("") | confidence.notna()).all(),
                     "Existing V2 mapping has invalid agent confidence")
            if "agent_status" in existing:
                _require(existing.agent_status.eq("").eq(existing.agent_confidence.eq("")).all(),
                         "Agent status and confidence must both be present or both blank")
        existing = existing.set_index(["hadm_id", "model_target"])
        for index, row in mapping.iterrows():
            previous = existing.loc[(row.hadm_id, row.model_target)]
            _require(previous.discharge_diagnosis_raw == row.discharge_diagnosis_raw,
                     "Existing V2 mapping review discharge text changed")
            if "mapped_disease_candidate" in existing.columns:
                _require(previous.mapped_disease_candidate == row.mapped_disease_candidate,
                         "Existing V2 mapping review disease candidate changed")
            mapping.at[index, "reviewer_status"] = previous.reviewer_status
            mapping.at[index, "reviewer_comment"] = previous.reviewer_comment
            for field in ("agent_status", "agent_confidence", "agent_comment", "agent_candidate_note"):
                if field in existing.columns:
                    mapping.at[index, field] = previous[field]
    return mapping


def prepare_concordance(decoded: pd.DataFrame, gt_path: Path, keyed_path: Path,
                        existing_review_path: Path | None = None) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Join full discharge references and the original model-derived mapping candidate."""
    required = {"pair_id", "hadm_id", "stage", "chief_complaint", "loop_target",
                "zero_shot_target", "loop_Q1", "zero_shot_Q1", "loop_Q2", "zero_shot_Q2",
                "loop_valid", "zero_shot_valid", "target_preference", "rationale_preference",
                "rater_comment"}
    _require(required <= set(decoded), f"Decoded audit lacks {sorted(required - set(decoded))}")
    _require(len(decoded) == 84 and decoded.pair_id.nunique() == 84 and decoded.hadm_id.nunique() == 42,
             "Decoded audit must have 84 unique pairs and 42 admissions")
    frame = decoded.copy()
    frame.pair_id = frame.pair_id.map(_string)
    frame.hadm_id = frame.hadm_id.map(_string)
    frame["target_preference"] = frame.target_preference.replace({"equivalent": "equal"})
    for arm in ("loop", "zero_shot"):
        frame[f"{arm}_valid"] = frame[f"{arm}_valid"].map(_bool)
    gt = _load_gt(gt_path, set(frame.hadm_id))
    frame = frame.merge(gt, on="hadm_id", how="left", validate="many_to_one")
    keyed = _read_csv(keyed_path)
    _require({"pair_id", "hadm_id", "stage", "_confirmed_diagnosis"} <= set(keyed),
             "Keyed audit lacks original mapping candidate")
    _require(len(keyed) == 84 and keyed.pair_id.nunique() == 84,
             "Keyed audit must contain 84 unique pairs")
    keyed = keyed[["pair_id", "hadm_id", "stage", "_confirmed_diagnosis"]]
    frame = frame.merge(keyed, on="pair_id", how="left", validate="one_to_one", suffixes=("", "_keyed"))
    _require(frame.hadm_id.eq(frame.hadm_id_keyed).all() and frame.stage.eq(frame.stage_keyed).all(),
             "Decoded and keyed audit pair metadata disagree")
    frame = frame.drop(columns=["hadm_id_keyed", "stage_keyed"])
    frame["original_mapping_candidate"] = frame._confirmed_diagnosis
    _require(frame.original_mapping_candidate.eq(frame.mapped_disease_candidate).all(),
             "Keyed original reference differs from the source SentenceTransformer disease candidate")
    frame = frame.drop(columns="_confirmed_diagnosis")
    mapping = _build_mapping(frame, existing_review_path)
    lookup = mapping.set_index(["hadm_id", "model_target"])
    for arm in ("loop", "zero_shot"):
        target = f"{arm}_target"
        frame[f"{arm}_original_mapping_candidate"] = [
            _name(t) == _name(c) if s == "V2" else None
            for s, t, c in zip(frame.stage, frame[target], frame.original_mapping_candidate, strict=True)]
        frame[f"{arm}_discharge_exact_text"] = [
            normalize_diagnosis(t) in {normalize_diagnosis(x) for x in labels} if s == "V2" else None
            for s, t, labels in zip(frame.stage, frame[target], frame.discharge_diagnoses_lines, strict=True)]
        frame[f"{arm}_primary_discharge"] = [
            normalize_diagnosis(t) == normalize_diagnosis(primary) if s == "V2" and _string(primary) else None
            for s, t, primary in zip(frame.stage, frame[target], frame.discharge_primary_diagnosis, strict=True)]
        reviewed = []
        for row in frame.itertuples():
            if row.stage != "V2":
                reviewed.append(None)
                continue
            status = lookup.loc[(row.hadm_id, getattr(row, target))].reviewer_status
            reviewed.append(True if status == "match" else False if status in
                            {"no_match", "clinically_related_but_not_equivalent"} else None)
        frame[f"{arm}_discharge_reviewed"] = reviewed
        full = []
        icd3 = []
        code = []
        for row in frame.itertuples():
            if row.stage != "V4":
                full.append(None)
                icd3.append(None)
                code.append(None)
                continue
            normalized = normalize_icd(getattr(row, target))
            code.append(normalized)
            full.append(normalized in row.discharge_full_codes_normalized)
            icd3.append(normalized[:3] in row.discharge_icd3)
        frame[f"{arm}_full_code_normalized"] = code
        frame[f"{arm}_full_code"] = full
        frame[f"{arm}_icd3"] = icd3
    if "v4_code_matched_cell" in frame:
        v4 = frame[frame.stage == "V4"]
        protected = v4.v4_code_matched_cell.map(_bool)
        recomputed = v4.loop_icd3.map(_bool) & v4.zero_shot_icd3.map(_bool)
        _require(protected.eq(recomputed).all(),
                 "Computed ICD3 reference-match status disagrees with frozen protected cell")
    if "v2_original_reference_stratum" in frame:
        v2 = frame[frame.stage == "V2"]
        recomputed = [_pair_stratum(_status(loop), _status(zero), "V2") for loop, zero in
                      zip(v2.loop_original_mapping_candidate, v2.zero_shot_original_mapping_candidate, strict=True)]
        expected = {"both_match": "both_match_original_reference",
                    "loop_only_match": "loop_only_matches_original_reference",
                    "zero_shot_only_match": "zero_shot_only_matches_original_reference",
                    "neither_match": "neither_matches_original_reference"}
        _require(v2.v2_original_reference_stratum.tolist() == [expected[label] for label in recomputed],
                 "Computed original-mapping status disagrees with existing V2 stratum")
    return frame, mapping


def _definitions(frame: pd.DataFrame) -> list[tuple[str, str]]:
    definitions = [("V2", name) for name in V2_REFS] + [("V4", name) for name in V4_REFS]
    if (frame.loop_discharge_reviewed.notna() | frame.zero_shot_discharge_reviewed.notna()).any():
        definitions.insert(2, ("V2", "discharge_reviewed"))
    if frame.discharge_primary_diagnosis.map(lambda value: bool(_string(value))).any():
        definitions.insert(2, ("V2", "primary_discharge"))
    return definitions


def _pair_stratum(loop: str, zero: str, stage: str) -> str:
    if "unreviewed" in (loop, zero):
        return "unreviewed"
    positive = "match"
    if loop == "yes" and zero == "yes":
        return f"both_{positive}"
    if loop == "yes":
        return f"loop_only_{positive}"
    if zero == "yes":
        return f"zero_shot_only_{positive}"
    return f"neither_{positive}"


def _reference_rows(frame: pd.DataFrame, stage: str, reference: str) -> pd.DataFrame:
    subset = frame[frame.stage == stage].copy()
    subset["loop_gt_status"] = subset[f"loop_{reference}"].map(_status)
    subset["zero_shot_gt_status"] = subset[f"zero_shot_{reference}"].map(_status)
    subset["reference_match_stratum"] = [
        _pair_stratum(loop, zero, stage)
        for loop, zero in zip(subset.loop_gt_status, subset.zero_shot_gt_status, strict=True)]
    subset["gt_definition"] = reference
    return subset


def _n(data: pd.DataFrame, column: str, value: str) -> int:
    return int(data[column].eq(value).sum())


def _arm_quality(data: pd.DataFrame, arm: str) -> dict[str, Any]:
    n = len(data)
    result = {}
    for label, values in (("Q1", data[f"{arm}_Q1"].eq("Yes")),
                          ("Q2", data[f"{arm}_Q2"].eq("Yes")),
                          ("valid", data[f"{arm}_valid"].astype(bool))):
        result[f"{arm}_{label}_yes_n" if label != "valid" else f"{arm}_valid_n"] = int(values.sum())
        result[f"{arm}_{label}_pct"] = 100 * values.mean() if n else np.nan
    return result


def _strata_table(data: pd.DataFrame, stage: str, reference: str) -> pd.DataFrame:
    suffix = "match"
    labels = [f"both_{suffix}", f"loop_only_{suffix}", f"zero_shot_only_{suffix}",
              f"neither_{suffix}", "unreviewed"]
    rows = []
    for label in labels:
        subset = data[data.reference_match_stratum == label]
        rows.append({"stage": stage, "gt_definition": reference, "reference_match_stratum": label,
                     "n_pairs": len(subset),
                     "target_asked_n": int(subset.target_preference.notna().sum()),
                     "target_loop_preferred": _n(subset, "target_preference", "loop"),
                     "target_zero_shot_preferred": _n(subset, "target_preference", "zero_shot"),
                     "target_equal": _n(subset, "target_preference", "equal"),
                     "rationale_loop_preferred": _n(subset, "rationale_preference", "loop"),
                     "rationale_zero_shot_preferred": _n(subset, "rationale_preference", "zero_shot"),
                     "rationale_equivalent": _n(subset, "rationale_preference", "equivalent"),
                     **_arm_quality(subset, "loop"), **_arm_quality(subset, "zero_shot")})
    return pd.DataFrame(rows)


def _support_table(data: pd.DataFrame, stage: str, reference: str) -> pd.DataFrame:
    rows = []
    for arm in ("loop", "zero_shot"):
        for status in ("yes", "no", "unreviewed"):
            subset = data[data[f"{arm}_gt_status"] == status]
            n = len(subset)
            q2 = subset[f"{arm}_Q2"].eq("Yes")
            valid = subset[f"{arm}_valid"].astype(bool)
            q1 = subset[f"{arm}_Q1"].eq("Yes")
            rows.append({"stage": stage, "gt_definition": reference, "arm": arm,
                         "gt_status": status, "n": n,
                         "Q1_yes_n": int(q1.sum()), "Q1_yes_pct": 100 * q1.mean() if n else np.nan,
                         "Q2_yes_n": int(q2.sum()), "Q2_yes_pct": 100 * q2.mean() if n else np.nan,
                         "Q2_not_yes_n": int((~q2).sum()),
                         "Q2_not_yes_pct": 100 * (~q2).mean() if n else np.nan,
                         "valid_n": int(valid.sum()), "valid_pct": 100 * valid.mean() if n else np.nan})
    return pd.DataFrame(rows)


def _discordance_summary(data: pd.DataFrame, stage: str, reference: str) -> dict[str, Any]:
    positive_unsupported = 0
    negative_supported = 0
    for arm in ("loop", "zero_shot"):
        status = data[f"{arm}_gt_status"]
        q2 = data[f"{arm}_Q2"].eq("Yes")
        positive_unsupported += int(((status == "yes") & ~q2).sum())
        negative_supported += int(((status == "no") & q2).sum())
    only_one = data.reference_match_stratum.isin(["loop_only_match", "zero_shot_only_match"])
    non_gt = ((data.loop_gt_status.eq("yes") & data.zero_shot_gt_status.eq("no") &
               data.target_preference.eq("zero_shot")) |
              (data.loop_gt_status.eq("no") & data.zero_shot_gt_status.eq("yes") &
               data.target_preference.eq("loop")))
    return {"stage": stage, "gt_definition": reference,
            "gt_yes_Q2_no": positive_unsupported, "gt_no_Q2_yes": negative_supported,
            "only_one_gt_match_n": int(only_one.sum()),
            "clinician_prefers_non_gt_n": int(non_gt.sum())}


def _preference_concordance(data: pd.DataFrame, stage: str, reference: str,
                            preference: str) -> pd.DataFrame:
    rows = []
    for gt_arm in ("loop", "zero_shot"):
        subset = data[(data[f"{gt_arm}_gt_status"] == "yes") &
                      (data[f"{'zero_shot' if gt_arm == 'loop' else 'loop'}_gt_status"] == "no")]
        if preference == "target":
            subset = subset[subset.target_preference.notna()]
        column = f"{preference}_preference"
        n = len(subset)
        rows.append({"stage": stage, "gt_definition": reference, "preference_type": preference,
                     "only_gt_arm": gt_arm, "n_pairs": n,
                     "prefers_gt_n": _n(subset, column, gt_arm),
                     "prefers_gt_pct": 100 * _n(subset, column, gt_arm) / n if n else np.nan,
                     "prefers_non_gt_n": _n(subset, column, "zero_shot" if gt_arm == "loop" else "loop"),
                     "equal_or_equivalent_n": _n(subset, column, "equal" if preference == "target" else "equivalent")})
    return pd.DataFrame(rows)


def _support_association(data: pd.DataFrame, bootstrap: ClusterBootstrap,
                         stage: str, reference: str) -> dict[str, Any]:
    long_rows = []
    for arm in ("loop", "zero_shot"):
        long_rows.append(pd.DataFrame({"hadm_id": data.hadm_id,
                                       "status": data[f"{arm}_gt_status"],
                                       "q2_yes": data[f"{arm}_Q2"].eq("Yes").astype(float)}))
    long = pd.concat(long_rows, ignore_index=True)
    yes_mask = long.status.eq("yes").to_numpy()
    no_mask = long.status.eq("no").to_numpy()
    q2 = long.q2_yes.to_numpy(float)
    yes_n, no_n = int(yes_mask.sum()), int(no_mask.sum())
    yes_count = int(q2[yes_mask].sum())
    no_count = int(q2[no_mask].sum())
    yes_pct = 100 * yes_count / yes_n if yes_n else np.nan
    no_pct = 100 * no_count / no_n if no_n else np.nan
    ci_low = ci_high = np.nan
    if yes_n and no_n:
        yes_numer = bootstrap._sums(long, np.where(yes_mask, q2, 0))
        no_numer = bootstrap._sums(long, np.where(no_mask, q2, 0))
        yes_denom = bootstrap._sums(long, yes_mask.astype(float))
        no_denom = bootstrap._sums(long, no_mask.astype(float))
        draws = np.divide(yes_numer, yes_denom, out=np.full(len(yes_numer), np.nan), where=yes_denom > 0) - np.divide(
            no_numer, no_denom, out=np.full(len(no_numer), np.nan), where=no_denom > 0)
        finite = draws[np.isfinite(draws)]
        if len(finite) >= .95 * len(draws):
            ci_low, ci_high = np.percentile(finite, [2.5, 97.5]) * 100
    return {"stage": stage, "gt_definition": reference, "gt_yes_n": yes_n,
            "gt_yes_Q2_yes_n": yes_count, "P_Q2_yes_given_gt_yes_pct": yes_pct,
            "gt_no_n": no_n, "gt_no_Q2_yes_n": no_count,
            "P_Q2_yes_given_gt_no_pct": no_pct,
            "difference_pp": yes_pct - no_pct if yes_n and no_n else np.nan,
            "ci_low_pp": ci_low, "ci_high_pp": ci_high}


def _triple_category(row: Any) -> str:
    loop = row.loop_gt_status
    zero = row.zero_shot_gt_status
    if {loop, zero} != {"yes", "no"}:
        return "not_single_gt_match"
    gt_arm = "loop" if loop == "yes" else "zero_shot"
    other = "zero_shot" if gt_arm == "loop" else "loop"
    if row.target_preference == other:
        return "clinician_vs_GT_discordance"
    if row.target_preference != gt_arm:
        return "target_equal_or_unasked"
    if row.rationale_preference == other:
        return "rationale_only_discordance"
    if row.rationale_preference == gt_arm and getattr(row, f"{gt_arm}_Q2") == "Yes":
        return "full_concordance"
    return "target_only_concordance"


def _discordant_cases(data: pd.DataFrame, stage: str, reference: str) -> pd.DataFrame:
    # The unreviewed V2 discharge mapping and its exact-string screen are kept
    # separate: they are not a clinically adjudicated discharge-reference test.
    if reference == "discharge_exact_text":
        return pd.DataFrame()
    rows = []
    for row in data.itertuples():
        reasons = []
        for arm in ("loop", "zero_shot"):
            status = getattr(row, f"{arm}_gt_status")
            supported = getattr(row, f"{arm}_Q2") == "Yes"
            if status == "yes" and not supported:
                reasons.append(f"{arm}_GT_yes_Q2_not_yes")
            elif status == "no" and supported:
                reasons.append(f"{arm}_GT_no_Q2_yes")
        if row.loop_gt_status == "yes" and row.zero_shot_gt_status == "no" and row.target_preference == "zero_shot":
            reasons.append("clinician_prefers_non_GT_target")
        if row.loop_gt_status == "no" and row.zero_shot_gt_status == "yes" and row.target_preference == "loop":
            reasons.append("clinician_prefers_non_GT_target")
        if not reasons:
            continue
        rows.append({"pair_id": row.pair_id, "hadm_id": row.hadm_id, "stage": stage,
                     "gt_definition": reference, "chief_complaint": row.chief_complaint,
                     "loop_target": row.loop_target, "zero_shot_target": row.zero_shot_target,
                     "loop_reason": row.loop_reason, "zero_shot_reason": row.zero_shot_reason,
                     "discharge_diagnosis": row.discharge_diagnosis_raw,
                     "discharge_icd_codes": json.dumps(row.discharge_icd_codes_raw, ensure_ascii=False),
                     "loop_gt_status": row.loop_gt_status, "zero_shot_gt_status": row.zero_shot_gt_status,
                     "loop_Q2": row.loop_Q2, "zero_shot_Q2": row.zero_shot_Q2,
                     "target_preference": row.target_preference,
                     "rationale_preference": row.rationale_preference,
                     "rater_comment": row.rater_comment,
                     "loop_full_in_gt": row.loop_full_code if stage == "V4" else None,
                     "zero_shot_full_in_gt": row.zero_shot_full_code if stage == "V4" else None,
                     "loop_icd3_in_gt": row.loop_icd3 if stage == "V4" else None,
                     "zero_shot_icd3_in_gt": row.zero_shot_icd3 if stage == "V4" else None,
                     "review_reasons": ";".join(reasons)})
    return pd.DataFrame(rows)


def _specificity(frame: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    v4 = frame[frame.stage == "V4"].copy()
    matched = v4[(v4.loop_full_code_normalized.str[:3] == v4.zero_shot_full_code_normalized.str[:3]) &
                 (v4.loop_full_code_normalized != v4.zero_shot_full_code_normalized)].copy()
    detail = matched[["pair_id", "hadm_id", "chief_complaint", "discharge_diagnosis_raw",
                      "discharge_icd_codes_raw", "loop_target", "zero_shot_target",
                      "loop_full_code_normalized", "zero_shot_full_code_normalized",
                      "loop_full_code", "zero_shot_full_code", "loop_icd3", "zero_shot_icd3",
                      "loop_Q2", "zero_shot_Q2", "target_preference", "rationale_preference",
                      "rater_comment"]].rename(columns={"loop_full_code": "loop_full_in_gt",
                                                  "zero_shot_full_code": "zero_shot_full_in_gt",
                                                  "loop_icd3": "loop_icd3_in_gt",
                                                  "zero_shot_icd3": "zero_shot_icd3_in_gt"})
    rows = []
    for label, subset in (("same_icd3_different_full_code", matched),
                          ("only_loop_full_in_gt", matched[(matched.loop_full_code == True) &
                                                              (matched.zero_shot_full_code == False)]),
                          ("only_zero_shot_full_in_gt", matched[(matched.loop_full_code == False) &
                                                                   (matched.zero_shot_full_code == True)]),
                          ("both_full_in_gt", matched[(matched.loop_full_code == True) &
                                                       (matched.zero_shot_full_code == True)]),
                          ("neither_full_in_gt", matched[(matched.loop_full_code == False) &
                                                          (matched.zero_shot_full_code == False)])):
        rows.append({"subset": label, "n": len(subset),
                     "loop_full_in_gt": int(subset.loop_full_code.eq(True).sum()),
                     "zero_shot_full_in_gt": int(subset.zero_shot_full_code.eq(True).sum()),
                     "loop_Q2_yes": int(subset.loop_Q2.eq("Yes").sum()),
                     "zero_shot_Q2_yes": int(subset.zero_shot_Q2.eq("Yes").sum()),
                     "target_loop_preferred": _n(subset, "target_preference", "loop"),
                     "target_zero_shot_preferred": _n(subset, "target_preference", "zero_shot"),
                     "target_equal": _n(subset, "target_preference", "equal"),
                     "rationale_loop_preferred": _n(subset, "rationale_preference", "loop"),
                     "rationale_zero_shot_preferred": _n(subset, "rationale_preference", "zero_shot"),
                     "rationale_equivalent": _n(subset, "rationale_preference", "equivalent")})
    return pd.DataFrame(rows), detail


def analyze_concordance(frame: pd.DataFrame, *, bootstrap_replicates: int = 10_000,
                        seed: int = 20260917) -> dict[str, pd.DataFrame]:
    """Keep GT membership, target preference, and rationale ratings distinct."""
    bootstrap = ClusterBootstrap(sorted(frame.hadm_id.unique()), bootstrap_replicates, seed)
    table_a, table_b, table_c, target_pref, rationale_pref, support, triple, discordant = [], [], [], [], [], [], [], []
    for stage, reference in _definitions(frame):
        data = _reference_rows(frame, stage, reference)
        table_a.append(_support_table(data, stage, reference))
        table_b.append(_strata_table(data, stage, reference))
        table_c.append(_discordance_summary(data, stage, reference))
        target_pref.append(_preference_concordance(data, stage, reference, "target"))
        rationale_pref.append(_preference_concordance(data, stage, reference, "rationale"))
        support.append(_support_association(data, bootstrap, stage, reference))
        triple.extend({"stage": stage, "gt_definition": reference,
                       "triple_category": category, "n_pairs": int(count)}
                      for category, count in data.apply(_triple_category, axis=1).value_counts().items())
        discordant.append(_discordant_cases(data, stage, reference))
    specificity, specificity_cases = _specificity(frame)
    cases = pd.concat(discordant, ignore_index=True) if any(not x.empty for x in discordant) else pd.DataFrame()
    return {"joined": frame,
            "table_A_support": pd.concat(table_a, ignore_index=True),
            "table_B_strata": pd.concat(table_b, ignore_index=True),
            "table_C_discordance": pd.DataFrame(table_c),
            "table_D_specificity": specificity,
            "target_preference_concordance": pd.concat(target_pref, ignore_index=True),
            "rationale_preference_concordance": pd.concat(rationale_pref, ignore_index=True),
            "support_association": pd.DataFrame(support),
            "triple_concordance": pd.DataFrame(triple),
            "discordant_cases": cases,
            "specificity_cases": specificity_cases}


def _interpret(results: dict[str, pd.DataFrame]) -> str:
    support = results["support_association"].set_index(["stage", "gt_definition"])
    discordance = results["table_C_discordance"].set_index(["stage", "gt_definition"])
    pieces = ["Discharge diagnoses and ICD codes are retrospective reference labels and may use information acquired after admission. "
              "A reference mismatch does not by itself make an admission-time diagnosis clinically implausible. "
              "The clinician's target preference and Q1/Q2 rationale judgments remain separate evaluation axes."]
    for reference, label in (("icd3", "ICD3"), ("full_code", "full code")):
        row = support.loc[("V4", reference)]
        if pd.notna(row.difference_pp):
            pieces.append(f"For V4 {label} agreement, Q2 support was {row.P_Q2_yes_given_gt_yes_pct:.1f}% "
                          f"among reference-matching arm targets and {row.P_Q2_yes_given_gt_no_pct:.1f}% "
                          f"among nonmatching targets (difference {row.difference_pp:+.1f} pp, "
                          f"95% admission-bootstrap CI [{row.ci_low_pp:.1f}, {row.ci_high_pp:.1f}]); "
                          "this is an association, not a causal effect.")
        discord = discordance.loc[("V4", reference)]
        if discord.gt_no_Q2_yes:
            pieces.append(f"For {label}, {int(discord.gt_no_Q2_yes)} arm judgments were reference-negative "
                          "but clinician-supported from the available case information.")
        if discord.gt_yes_Q2_no:
            pieces.append(f"For {label}, {int(discord.gt_yes_Q2_no)} arm judgments matched the reference "
                          "but were not judged clinically supported; category membership does not guarantee "
                          "support for the generated full diagnosis or its rationale.")
        if discord.clinician_prefers_non_gt_n:
            pieces.append(f"Among {int(discord.only_one_gt_match_n)} V4 pairs with only one {label} "
                          f"reference-matching target, the clinician preferred the nonmatching target in "
                          f"{int(discord.clinician_prefers_non_gt_n)}; these need case review rather than an "
                          "automatic clinician-versus-reference error label.")
    specificity = results["table_D_specificity"].set_index("subset")
    held_category = specificity.loc["same_icd3_different_full_code"]
    pieces.append(f"In the {int(held_category.n)} pairs sharing an ICD3 category but differing in full code, "
                  f"the clinician chose equal target appropriateness in {int(held_category.target_equal)}; "
                  "full-code specificity cannot be ranked automatically from code length or category agreement.")
    pieces.append("The V2 literal discharge-text screen is not a clinical synonym map. "
                  "The original keyed diagnosis is the SentenceTransformer-derived `disease` candidate, "
                  "not an independently adjudicated clinical reference.")
    pieces.append("Discordant cases are exported for qualitative review. No cause of a discrepancy is assigned automatically: "
                  "later information, excluded differentials, incomplete coding, coexistence, code specificity, "
                  "or unsupported reasoning are possibilities to inspect rather than assumptions.")
    return " ".join(pieces)


def report_section(results: dict[str, pd.DataFrame], mapping: pd.DataFrame,
                   *, bootstrap_replicates: int, seed: int) -> str:
    a = results["table_A_support"]
    b = results["table_B_strata"]
    c = results["table_C_discordance"]
    support = results["support_association"]
    target = results["target_preference_concordance"]
    rationale = results["rationale_preference_concordance"]
    v2_reviewed = int(mapping.reviewer_status.eq("match").sum())
    v2_exact = int(mapping.proposed_status.eq("match").sum())
    v2_unreviewed = int(mapping.reviewer_status.eq("").sum())
    agent_done = int(mapping.agent_status.isin(AGENT_STATUSES).sum())
    agent_counts = mapping.agent_status[mapping.agent_status.isin(AGENT_STATUSES)].value_counts().to_dict()
    candidate_exact = int(mapping.candidate_exact_target.sum())
    candidate_exact_related = int((mapping.candidate_exact_target &
                                   mapping.agent_status.eq("clinically_related_but_not_equivalent")).sum())
    agent_note = (f"An AI first pass assigned status and 0–1 confidence to {agent_done}/{len(mapping)} mappings "
                  f"({agent_counts}). These are judgments against discharge diagnosis text, with ICD-code "
                  "corroboration noted separately in comments. `match` means the text names or directly entails "
                  "the target; `clinically_related_but_not_equivalent` means overlap without the same diagnosis; "
                  "`no_match` means a distinct or absent text diagnosis; and `uncertain` records unresolved wording. "
                  "Confidence is in the assigned status, not admission-time plausibility. AI statuses are not treated as clinician-confirmed "
                  "discharge agreement in the main tables. " if agent_done else
                  "No AI first-pass mapping statuses have been entered. ")
    primary_note = ("An explicit primary discharge diagnosis is available and retained separately."
                    if results["joined"].discharge_primary_diagnosis.map(lambda value: bool(_string(value))).any()
                    else "No explicit primary/main diagnosis or primary ICD designation is present; those fields are null.")
    lines = [
        "## Ground-truth concordance and clinician assessment", "",
        "**Preliminary: one clinician completed.** This secondary analysis compares three separate axes: "
        "retrospective discharge-reference agreement, admission-time clinician target appropriateness, "
        "and clinician-assessed rationale grounding/support/preference. Discharge labels can incorporate "
        "information unavailable at admission; reference disagreement is not automatically a clinical error.", "",
        f"Admission-cluster percentile bootstrap: {bootstrap_replicates:,} replicates, seed {seed}. "
        "Both V2 and V4 ratings for a resampled admission remain together. No inter-rater agreement or "
        "per-stratum significance testing is computed.", "",
        "### V2 diagnosis-reference agreement", "",
        "The keyed original mapping candidate is the SentenceTransformer-derived `disease` value, "
        "not an independent clinician adjudication. The discharge source has newline-separated "
        "diagnosis text. " + primary_note + " "
        "The `discharge_exact_text` screen matches only normalized punctuation/case/whitespace, with no synonym inference. "
        f"It proposed {v2_exact} exact normalized target mappings; {v2_unreviewed} unique mappings await review "
        f"and {v2_reviewed} were manually marked `match`. The all-empty human-review reference "
        "is omitted from analysis tables; AI mapping statuses remain private and separate. "
        + agent_note + f"The source `disease` field is a SentenceTransformer top WikiDoc differential "
        f"candidate derived from `diagnose_string`, not an independent reference. It exactly matches "
        f"{candidate_exact}/{len(mapping)} model targets after formatting normalization; "
        f"{candidate_exact_related} of those still have an AI first-pass status of "
        "`clinically_related_but_not_equivalent`. Candidate agreement never overrides the "
        "discharge text or ICD evidence. The editable private file is `audit_v2_gt_mapping_review.csv`.", "",
        _markdown_table(b[b.stage == "V2"][["gt_definition", "reference_match_stratum", "n_pairs",
                                            "loop_Q2_pct", "zero_shot_Q2_pct", "loop_valid_pct",
                                            "zero_shot_valid_pct", "target_loop_preferred",
                                            "target_zero_shot_preferred", "target_equal",
                                            "rationale_loop_preferred", "rationale_zero_shot_preferred",
                                            "rationale_equivalent"]]), "",
        "### V4 ICD3 agreement", "",
        "ICD3 membership is the paper's automatic comparison: each generated category is compared with "
        "all discharge ICD3 categories, not a selected first code.", "",
        _markdown_table(b[(b.stage == "V4") & (b.gt_definition == "icd3")]), "",
        "### V4 full-code agreement", "",
        "Full-code matching removes only decimal punctuation and whitespace; it is a stricter secondary reference comparison. "
        "A full-code nonmatch may still match the discharge ICD3 category.", "",
        _markdown_table(b[(b.stage == "V4") & (b.gt_definition == "full_code")]), "",
        "### GT agreement versus Q2 clinical support", "",
        "Table A includes Q1, Q2, and composite-validity counts/rates for each arm and reference status. "
        "Q2!=Yes combines No and Unclear. `unreviewed` is shown separately for V2 discharge equivalence.", "",
        _markdown_table(a[["stage", "gt_definition", "arm", "gt_status", "n", "Q1_yes_n", "Q2_yes_n",
                           "Q2_yes_pct", "Q2_not_yes_n", "Q2_not_yes_pct", "valid_n", "valid_pct"]]), "",
        "Absolute Q2 association: P(Q2=Yes | reference yes) minus P(Q2=Yes | reference no). "
        "The V2 discharge exact-text row is a literal-screen association only; a clinical-equivalence association "
        "cannot be estimated until mapping review is complete.", "",
        _markdown_table(support), "",
        "### GT agreement versus target preference", "",
        "Only differing-target pairs with one matching and one nonmatching arm enter this table. "
        "The percentage is reference/clinician concordance, not clinician accuracy.", "",
        _markdown_table(target), "",
        "### GT agreement versus rationale preference", "",
        "These counts are independent of the target-preference question. `prefers_gt` means the rationale "
        "attached to the reference-matching target was chosen.", "",
        _markdown_table(rationale), "",
        "### Full-code specificity", "",
        "The same-ICD3/different-full-code cases hold the broad category fixed. The table and "
        "`audit_v4_specificity_cases.csv` show full-code membership, Q2 support, and both preferences; "
        "more specific is not assumed better.", "",
        _markdown_table(results["table_D_specificity"]), "",
        "### Discordant cases", "",
        "Table C counts arm-level reference/Q2 discordances and pair-level target-preference discordances. "
        "The exact-text V2 screen is not used to label clinically discordant cases. "
        "`audit_gt_clinician_discordant_cases.csv` contains the identifiable cases and both rationales "
        "for manual inspection.", "",
        _markdown_table(c), "",
        "Triple-concordance categories are descriptive and mutually exclusive among pairs with one reference-matching arm. "
        "`rationale_only_discordance` means target preference follows the reference while rationale preference "
        "favors the other arm. `target_only_concordance` includes ties or unsupported Q2; no composite score is formed.", "",
        _markdown_table(results["triple_concordance"]), "",
        "### Interpretation", "", _interpret(results), "",
        "The joined private pair-level file preserves raw discharge diagnosis text and the full ordered ICD list "
        "alongside the original mapping candidate and clinician assessments. It does not infer a primary diagnosis or code.", "",
    ]
    return "\n".join(lines)


def write_tables(results: dict[str, pd.DataFrame], mapping: pd.DataFrame, directory: Path) -> None:
    """Write patient-derived outputs into the caller's private staging directory."""
    names = ("table_A_support", "table_B_strata", "table_C_discordance", "table_D_specificity",
             "target_preference_concordance", "rationale_preference_concordance",
             "support_association", "triple_concordance", "specificity_cases")
    for name in names:
        table = results[name].copy()
        if name == "specificity_cases":
            table["discharge_icd_codes_raw"] = table.discharge_icd_codes_raw.map(
                lambda value: json.dumps(value, ensure_ascii=False))
        table.to_csv(directory / f"audit_batch1_gt_{name}.csv", index=False)
    joined = results["joined"].copy()
    for column in ("discharge_icd_codes_raw", "discharge_diagnoses_lines",
                   "discharge_full_codes_normalized", "discharge_icd3"):
        joined[column] = joined[column].map(lambda value: json.dumps(value, ensure_ascii=False))
    joined.to_csv(directory / "audit_batch1_gt_concordance_pairs.csv", index=False)
    mapping.to_csv(directory / "audit_v2_gt_mapping_review.csv", index=False)
    results["discordant_cases"].to_csv(directory / "audit_gt_clinician_discordant_cases.csv", index=False)
    detail = results["specificity_cases"].copy()
    detail["discharge_icd_codes_raw"] = detail.discharge_icd_codes_raw.map(
        lambda value: json.dumps(value, ensure_ascii=False))
    detail.to_csv(directory / "audit_v4_specificity_cases.csv", index=False)
