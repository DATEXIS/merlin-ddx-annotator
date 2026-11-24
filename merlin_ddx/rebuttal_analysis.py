"""Offline, post-annotation analysis of the blinded MERLIN rebuttal audit.

No source CSV or clinician export is modified. The keyed allocation is read only
after the blinded 42-admission/two-rater completion check succeeds.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import shutil
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy.stats import binomtest


QUESTIONS = ("A_Q1", "A_Q2", "B_Q1", "B_Q2")
LEGACY_QUESTIONS = {
    "A_Q1": "A_Q1_evidence_grounded", "A_Q2": "A_Q2_supports_target",
    "B_Q1": "B_Q1_evidence_grounded", "B_Q2": "B_Q2_supports_target",
}
VALID_JUDGMENTS = {"Yes", "No", "Unclear"}
TARGET_CHOICES = {"A", "B", "Equal"}
RATIONALE_CHOICES = {"A", "B", "Equivalent"}
EXPECTED_PAIRS = 84
EXPECTED_ADMISSIONS = 42
MIN_CONTROLLED_PAIRS_FOR_CI = 5


class AuditValidationError(ValueError):
    """The frozen frame, blinded ratings, or key failed preflight checks."""


def _string(value: Any) -> str:
    if value is None or (not isinstance(value, (str, list, dict)) and pd.isna(value)):
        return ""
    return str(value).strip()


def _name(value: Any) -> str:
    return " ".join(_string(value).casefold().split())


def _icd(value: Any) -> str:
    return re.sub(r"[^A-Z0-9]", "", _string(value).upper())


def _flag(value: Any) -> bool | None:
    value = _string(value).lower()
    if value in {"1", "true", "yes", "y"}:
        return True
    if value in {"0", "false", "no", "n"}:
        return False
    if not value:
        return None
    raise AuditValidationError(f"Unrecognized boolean flag: {value!r}")


def _read_csv(path: Path) -> pd.DataFrame:
    if not path.is_file():
        raise AuditValidationError(f"Missing input: {path}")
    return pd.read_csv(path, dtype=str, keep_default_na=False)


def _records_from_json(path: Path) -> list[dict]:
    obj = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(obj, list):
        return obj
    if isinstance(obj, dict) and "records" in obj:
        return obj["records"]
    if isinstance(obj, dict):
        return [obj]
    raise AuditValidationError(f"Unrecognized annotation JSON structure: {path}")


def _flatten_export_record(record: dict, rater_id: str) -> list[dict]:
    found_rater = record.get("annotatorId") or record.get("annotator_id") or record.get("rater_id")
    if found_rater and _string(found_rater) != rater_id:
        raise AuditValidationError(f"Export annotator ID disagrees with --rater {rater_id}")
    if "pairs" not in record:
        return [record]
    hadm_id = _string(record.get("hadm_id"))
    pairs = record["pairs"]
    if not isinstance(pairs, dict):
        raise AuditValidationError("Annotation record 'pairs' must be an object")
    result = []
    for pair_id, answer in pairs.items():
        if not isinstance(answer, dict):
            raise AuditValidationError("Each pair answer must be an object")
        if answer.get("pair_id") is not None and _string(answer["pair_id"]) != _string(pair_id):
            raise AuditValidationError("pair_id inside answer disagrees with its mapping key")
        if answer.get("hadm_id") is not None and _string(answer["hadm_id"]) != hadm_id:
            raise AuditValidationError("hadm_id inside answer disagrees with its admission record")
        result.append({**answer, "pair_id": _string(pair_id), "hadm_id": hadm_id})
    return result


def load_annotation_export(path: Path, rater_id: str) -> pd.DataFrame:
    """Accept app JSON directories, one JSON file/list, or a long-form CSV."""
    if path.is_dir():
        files = sorted(path.glob("*.json"))
        if not files:
            raise AuditValidationError(f"No JSON annotation records in {path}")
        records = [record for file in files for record in _records_from_json(file)]
    elif path.suffix.lower() == ".json":
        records = _records_from_json(path)
    elif path.suffix.lower() == ".csv":
        records = _read_csv(path).to_dict("records")
    else:
        raise AuditValidationError(f"Expected a JSON directory, JSON file, or CSV: {path}")
    rows = [row for record in records for row in _flatten_export_record(record, rater_id)]
    if not rows:
        raise AuditValidationError(f"No pair responses in {path}")
    normalized = []
    for row in rows:
        answer_fields = {
            "pair_id", "hadm_id", *QUESTIONS, *LEGACY_QUESTIONS.values(),
            "target_preference_A_B_equal", "rationale_preference_A_B_equal",
            "preference_A_B_equivalent", "rater_comment",
        }
        item = {key: row[key] for key in answer_fields if key in row}
        for short, legacy in LEGACY_QUESTIONS.items():
            item[short] = _string(item.get(short)) or _string(item.get(legacy))
        item["pair_id"] = _string(item.get("pair_id"))
        item["hadm_id"] = _string(item.get("hadm_id"))
        item["target_preference_A_B_equal"] = _string(item.get("target_preference_A_B_equal"))
        item["rationale_preference_A_B_equal"] = _string(item.get("rationale_preference_A_B_equal"))
        item["rater_comment"] = _string(item.get("rater_comment"))
        item["rater_id"] = rater_id
        normalized.append(item)
    return pd.DataFrame(normalized)


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise AuditValidationError(message)


def validate_blinded_and_annotations(blinded: pd.DataFrame, ratings: pd.DataFrame,
                                     rater_ids: list[str]) -> tuple[pd.DataFrame, dict]:
    """Run this before even opening the keyed allocation file."""
    required = {"pair_id", "hadm_id", "chief_complaint", "stage", "target_A", "reason_A", "target_B", "reason_B"}
    _require(required.issubset(blinded), f"Blinded CSV lacks: {sorted(required - set(blinded))}")
    blinded = blinded.copy()
    for column in ("pair_id", "hadm_id"):
        blinded[column] = blinded[column].map(_string)
    _require(len(blinded) == EXPECTED_PAIRS, f"Expected {EXPECTED_PAIRS} blinded pairs; found {len(blinded)}")
    _require(blinded.pair_id.nunique() == EXPECTED_PAIRS, "Duplicate or missing pair_id in blinded CSV")
    _require(blinded.hadm_id.nunique() == EXPECTED_ADMISSIONS, "Expected 42 unique admissions")
    _require(blinded.stage.value_counts().to_dict() == {"V2": 42, "V4": 42}, "Expected 42 V2 and 42 V4 pairs")
    for field in ("target_A", "target_B", "reason_A", "reason_B"):
        _require((blinded[field].map(_string) != "").all(), f"Blinded CSV has missing {field}")
    _require((blinded.groupby("hadm_id").stage.nunique() == 2).all(), "Each admission must have V2 and V4")
    complaints = blinded.groupby("chief_complaint").hadm_id.nunique()
    _require(len(complaints) == 7 and (complaints == 6).all(), "Expected seven complaints with six admissions each")
    _require(len(rater_ids) == 2 and len(set(rater_ids)) == 2, "Supply exactly two distinct raters")
    _require({"pair_id", "hadm_id", "rater_id", *QUESTIONS,
              "target_preference_A_B_equal", "rationale_preference_A_B_equal"}.issubset(ratings),
             "Annotation export lacks required response fields")
    _require(not ratings.duplicated(["pair_id", "rater_id"]).any(), "Duplicate pair/rater rows")
    expected_ids = set(blinded.pair_id)
    for rater_id in rater_ids:
        rater = ratings[ratings.rater_id == rater_id]
        _require(len(rater) == EXPECTED_PAIRS and set(rater.pair_id) == expected_ids,
                 f"{rater_id} has not completed the exact 84-pair batch")
    _require(set(ratings.rater_id) == set(rater_ids), "Unexpected rater in exports")
    annotation_template_fields = {
        "preference_A_B_equivalent", *LEGACY_QUESTIONS.values(), "rater_comment",
    }
    blind_metadata = blinded.drop(columns=list(annotation_template_fields & set(blinded)))
    frame = ratings.merge(blind_metadata, on="pair_id", how="left", validate="many_to_one", suffixes=("", "_blind"))
    _require(frame["hadm_id_blind"].notna().all(), "Annotation references an unknown pair_id")
    _require((frame.hadm_id == frame.hadm_id_blind).all(), "Pair/hadm_id mismatch")
    frame = frame.drop(columns="hadm_id_blind")
    missing_q1 = sum((frame[field].map(_string) == "").sum() for field in ("A_Q1", "B_Q1"))
    missing_q2 = sum((frame[field].map(_string) == "").sum() for field in ("A_Q2", "B_Q2"))
    _require(missing_q1 == 0 and missing_q2 == 0, f"Incomplete Q1/Q2: {missing_q1}/{missing_q2} missing")
    for field in QUESTIONS:
        _require(set(frame[field].map(_string)) <= VALID_JUDGMENTS, f"Invalid {field} response")
    missing_rationale = int((frame.rationale_preference_A_B_equal.map(_string) == "").sum())
    _require(missing_rationale == 0, f"Missing {missing_rationale} rationale preferences")
    _require(set(frame.rationale_preference_A_B_equal) <= RATIONALE_CHOICES,
             "Invalid rationale-preference response")
    same = frame.target_A == frame.target_B
    target = frame.target_preference_A_B_equal.map(_string)
    _require((target[same] == "").all(), "Identical targets must have null/not-applicable target preference")
    _require((target[~same] != "").all(), "Differing targets require target preference")
    _require(set(target[~same]) <= TARGET_CHOICES, "Invalid target-preference response")
    accounting = {
        "n_pairs": EXPECTED_PAIRS,
        "n_admissions": EXPECTED_ADMISSIONS,
        "n_raters": 2,
        "n_rater_judgments": len(frame),
        "missing_Q1": missing_q1,
        "missing_Q2": missing_q2,
        "missing_rationale_preference": missing_rationale,
        "n_target_preference_responses": int((target != "").sum()),
        "n_target_not_applicable": int(same.sum()),
        "chief_complaint_admissions": complaints.to_dict(),
    }
    return frame, accounting


def _arm(value: Any) -> str:
    normalized = re.sub(r"[^a-z0-9]", "", _string(value).lower())
    if normalized in {"loop", "verifierloop", "vl"}:
        return "loop"
    if normalized in {"zeroshot", "zs", "baseline"}:
        return "zero_shot"
    raise AuditValidationError(f"Unknown keyed arm identity: {value!r}")


def _decode(choice: str, a_arm: str, b_arm: str) -> str:
    return a_arm if choice == "A" else b_arm if choice == "B" else "equivalent"


def join_key_after_completion(frame: pd.DataFrame, keyed_path: Path) -> tuple[pd.DataFrame, dict]:
    keyed = _read_csv(keyed_path)
    required = {"pair_id", "_A_arm", "_B_arm", "_v4_code_matched_cell",
                "_confirmed_diagnosis", "_words_A", "_words_B"}
    _require(required.issubset(keyed), f"Keyed CSV lacks: {sorted(required - set(keyed))}")
    _require("_loop_accepted" in keyed or "loop_accept" in keyed,
             "Keyed CSV lacks loop-acceptance flag")
    keyed.pair_id = keyed.pair_id.map(_string)
    _require(len(keyed) == EXPECTED_PAIRS and keyed.pair_id.nunique() == EXPECTED_PAIRS,
             "Keyed CSV must have 84 unique pair_ids")
    _require(set(keyed.pair_id) == set(frame.pair_id), "Keyed and blinded pair IDs differ")
    common = [field for field in ("hadm_id", "chief_complaint", "stage", "target_A", "target_B", "reason_A", "reason_B")
              if field in keyed]
    for field in common:
        reference = frame.drop_duplicates("pair_id").set_index("pair_id")[field]
        proposed = keyed.set_index("pair_id")[field]
        _require(reference.map(_string).sort_index().equals(proposed.map(_string).sort_index()),
                 f"Keyed/blinded mismatch in {field}")
    hidden = keyed[["pair_id", *(field for field in keyed if field.startswith("_"))]]
    joined = frame.merge(hidden, on="pair_id", how="left", validate="many_to_one")
    _require({"_A_arm", "_B_arm"}.issubset(joined), "Keyed arm columns missing")
    joined["A_arm"] = joined._A_arm.map(_arm)
    joined["B_arm"] = joined._B_arm.map(_arm)
    _require(((joined.A_arm == "loop") != (joined.B_arm == "loop")).all(),
             "Each pair must contain one loop and one zero-shot arm")
    for side in ("loop", "zero_shot"):
        is_a = joined.A_arm == side
        for q in ("Q1", "Q2"):
            joined[f"{side}_{q}"] = np.where(is_a, joined[f"A_{q}"], joined[f"B_{q}"])
        joined[f"{side}_valid"] = (joined[f"{side}_Q1"] == "Yes") & (joined[f"{side}_Q2"] == "Yes")
        word_a = pd.to_numeric(joined.get("_words_A", pd.Series(index=joined.index)), errors="coerce")
        word_b = pd.to_numeric(joined.get("_words_B", pd.Series(index=joined.index)), errors="coerce")
        joined[f"{side}_words"] = np.where(is_a, word_a, word_b)
    joined["rationale_preferred"] = [
        _decode(p, a, b) for p, a, b in zip(joined.rationale_preference_A_B_equal,
                                            joined.A_arm, joined.B_arm, strict=True)
    ]
    joined["target_preferred"] = [
        _decode(p, a, b) if _string(p) else "not_applicable"
        for p, a, b in zip(joined.target_preference_A_B_equal,
                           joined.A_arm, joined.B_arm, strict=True)
    ]
    joined["same_target"] = joined.target_A == joined.target_B
    joined["same_target_normalized"] = np.where(
        joined.stage == "V2",
        joined.target_A.map(_name) == joined.target_B.map(_name),
        joined.target_A.map(_icd) == joined.target_B.map(_icd),
    )
    joined["same_icd3"] = (joined.stage == "V4") & (
        joined.target_A.map(_icd).str[:3] == joined.target_B.map(_icd).str[:3]
    )
    joined["v4_code_matched_cell"] = joined.get("_v4_code_matched_cell", pd.Series(index=joined.index)).map(_flag)
    accepted_column = "_loop_accepted" if "_loop_accepted" in joined else "loop_accept"
    joined["loop_accepted"] = joined.get(accepted_column, pd.Series(index=joined.index)).map(_flag)
    _require(joined.loop_accepted.notna().all(), "Missing loop-acceptance flag")
    _require(joined.loc[joined.stage == "V4", "v4_code_matched_cell"].notna().all(),
             "Missing V4 protected-cell flag")
    _require((joined.loc[joined.stage == "V2", "_confirmed_diagnosis"].map(_string) != "").all(),
             "Missing V2 original mapping reference")
    for field in ("_words_A", "_words_B"):
        counts = pd.to_numeric(joined[field], errors="coerce")
        _require(counts.notna().all() and (counts >= 0).all(), f"Invalid or missing {field}")
    joined["v2_original_reference_cell"] = joined.apply(_v2_original_reference_cell, axis=1)
    balance = (joined.drop_duplicates("pair_id").groupby(["stage", "A_arm"])
               .size().unstack(fill_value=0).to_dict("index"))
    _require(all(set(counts) == {"loop", "zero_shot"} and min(counts.values()) > 0
                 for counts in balance.values()),
             "A/B randomization is degenerate in a stage")
    return joined, balance


def _v2_original_reference_cell(row: pd.Series) -> str:
    if row.stage != "V2":
        return "not_applicable"
    original_reference = _name(row.get("_confirmed_diagnosis"))
    if not original_reference:
        return "unknown"
    loop_target = row.target_A if row.A_arm == "loop" else row.target_B
    zero_target = row.target_A if row.A_arm == "zero_shot" else row.target_B
    loop_match = _name(loop_target) == original_reference
    zero_match = _name(zero_target) == original_reference
    return ("both_match_original_reference" if loop_match and zero_match else
            "loop_only_matches_original_reference" if loop_match else
            "zero_shot_only_matches_original_reference" if zero_match else
            "neither_matches_original_reference")


class ClusterBootstrap:
    def __init__(self, admissions: list[str], replicates: int, seed: int):
        _require(replicates >= 10_000, "At least 10,000 bootstrap replicates are required")
        self.admissions = admissions
        self.replicates = replicates
        self.seed = seed
        self.counts = np.random.default_rng(seed).multinomial(
            len(admissions), [1 / len(admissions)] * len(admissions), size=replicates,
        )

    def _sums(self, data: pd.DataFrame, values: np.ndarray) -> np.ndarray:
        indexed = pd.DataFrame({"hadm_id": data.hadm_id.to_numpy(), "value": values})
        vector = indexed.groupby("hadm_id").value.sum().reindex(self.admissions, fill_value=0).to_numpy(float)
        return self.counts @ vector

    def rate_ci(self, data: pd.DataFrame, values: np.ndarray) -> tuple[float | None, float | None]:
        if data.hadm_id.nunique() < 2:
            return None, None
        valid = np.isfinite(values)
        numerators = self._sums(data, np.where(valid, values, 0))
        denominators = self._sums(data, valid.astype(float))
        estimates = np.divide(numerators, denominators, out=np.full(self.replicates, np.nan),
                              where=denominators > 0)
        return _percentile_interval(estimates)

    def difference_ci(self, data: pd.DataFrame, loop_values: np.ndarray,
                      zero_values: np.ndarray) -> tuple[float | None, float | None]:
        if data.hadm_id.nunique() < 2:
            return None, None
        loop_valid = np.isfinite(loop_values)
        zero_valid = np.isfinite(zero_values)
        loop_n = self._sums(data, np.where(loop_valid, loop_values, 0))
        zero_n = self._sums(data, np.where(zero_valid, zero_values, 0))
        loop_d = self._sums(data, loop_valid.astype(float))
        zero_d = self._sums(data, zero_valid.astype(float))
        loop_rate = np.divide(loop_n, loop_d, out=np.full(self.replicates, np.nan), where=loop_d > 0)
        zero_rate = np.divide(zero_n, zero_d, out=np.full(self.replicates, np.nan), where=zero_d > 0)
        return _percentile_interval(loop_rate - zero_rate)


def _percentile_interval(values: np.ndarray) -> tuple[float | None, float | None]:
    requested = len(values)
    values = values[np.isfinite(values)]
    if len(values) < 0.95 * requested:
        return None, None
    if not len(values):
        return None, None
    return tuple(float(x) for x in np.percentile(values, [2.5, 97.5]))


def _rate(values: np.ndarray) -> float | None:
    valid = values[np.isfinite(values)]
    return float(valid.mean()) if len(valid) else None


def _quality(data: pd.DataFrame, bootstrap: ClusterBootstrap, stage: str,
             group: str, min_ci_pairs: int = 0) -> tuple[list[dict], dict]:
    rows = []
    results: dict[str, Any] = {"stage": stage, "group": group, "n_pairs": data.pair_id.nunique(),
                               "n_judgments": len(data)}
    can_ci = data.pair_id.nunique() >= min_ci_pairs
    for arm in ("zero_shot", "loop"):
        row: dict[str, Any] = {"stage": stage, "arm": arm, "group": group, "n": len(data)}
        for label, column in (("Q1", f"{arm}_Q1"), ("Q2", f"{arm}_Q2"),
                              ("valid", f"{arm}_valid")):
            values = (data[column] == "Yes").to_numpy(float) if label != "valid" else data[column].to_numpy(float)
            ci = bootstrap.rate_ci(data, values) if can_ci else (None, None)
            row[f"{label}_yes_n" if label != "valid" else "valid_n"] = int(values.sum())
            row[f"{label}_yes_pct" if label != "valid" else "valid_pct"] = 100 * _rate(values) if len(values) else None
            row[f"{label}_denominator" if label != "valid" else "valid_denominator"] = len(values)
            row[f"{label}_95CI" if label != "valid" else "valid_95CI"] = _ci_text(ci)
            row[f"{label}_ci_low" if label != "valid" else "valid_ci_low"] = ci[0]
            row[f"{label}_ci_high" if label != "valid" else "valid_ci_high"] = ci[1]
        rows.append(row)
    for label in ("Q1", "Q2", "valid"):
        loop_values = ((data[f"loop_{label}"] == "Yes").to_numpy(float) if label != "valid"
                       else data.loop_valid.to_numpy(float))
        zero_values = ((data[f"zero_shot_{label}"] == "Yes").to_numpy(float) if label != "valid"
                       else data.zero_shot_valid.to_numpy(float))
        interval = bootstrap.difference_ci(data, loop_values, zero_values) if can_ci else (None, None)
        results[f"delta_{label}_pp"] = 100 * (_rate(loop_values) - _rate(zero_values)) if len(data) else None
        results[f"delta_{label}_ci_low"] = None if interval[0] is None else 100 * interval[0]
        results[f"delta_{label}_ci_high"] = None if interval[1] is None else 100 * interval[1]
        results[f"delta_{label}_95CI"] = _ci_text(interval, scale=100)
    return rows, results


def _ci_text(ci: tuple[float | None, float | None], scale: float = 100) -> str:
    return "NA" if ci[0] is None else f"[{ci[0] * scale:.1f}, {ci[1] * scale:.1f}]"


def _preference(data: pd.DataFrame, bootstrap: ClusterBootstrap,
                stage: str, preference_type: str, group: str = "all",
                min_ci_pairs: int = 0) -> dict:
    column = "rationale_preferred" if preference_type == "rationale" else "target_preferred"
    if preference_type == "target":
        data = data[data[column] != "not_applicable"]
    n = len(data)
    row: dict[str, Any] = {"stage": stage, "group": group, "preference_type": preference_type,
                           "n_pairs": data.pair_id.nunique(), "n_judgments": n}
    for choice, label in (("loop", "loop"), ("zero_shot", "zero_shot"), ("equivalent", "equivalent")):
        count = int((data[column] == choice).sum())
        row[f"{label}_n"] = count
        row[f"{label}_pct"] = 100 * count / n if n else None
    if n:
        loop = (data[column] == "loop").to_numpy(float)
        zero = (data[column] == "zero_shot").to_numpy(float)
        ci = bootstrap.difference_ci(data, loop, zero) if data.pair_id.nunique() >= min_ci_pairs else (None, None)
        row.update({"margin_pp": 100 * (loop.mean() - zero.mean()),
                    "margin_95CI": _ci_text(ci, scale=100),
                    "margin_ci_low": None if ci[0] is None else 100 * ci[0],
                    "margin_ci_high": None if ci[1] is None else 100 * ci[1]})
        if preference_type == "rationale":
            non_equal = row["loop_n"] + row["zero_shot_n"]
            row["sign_test_p"] = float(binomtest(row["loop_n"], non_equal, 0.5).pvalue) if non_equal else None
    else:
        row.update({"margin_pp": None, "margin_95CI": "NA", "margin_ci_low": None,
                    "margin_ci_high": None})
    return row


def _agreement(left: list[str], right: list[str], categories: list[str]) -> tuple[float | None, float | None]:
    if not left:
        return None, None
    n = len(left)
    observed = sum(a == b for a, b in zip(left, right, strict=True)) / n
    left_counts, right_counts = Counter(left), Counter(right)
    expected = sum(left_counts[c] * right_counts[c] for c in categories) / (n * n)
    return observed, (observed - expected) / (1 - expected) if expected < 1 else None


def reliability(data: pd.DataFrame, rater_ids: list[str]) -> pd.DataFrame:
    rows = []
    for stage in ("V2", "V4"):
        stage_data = data[data.stage == stage]
        by_rater = {r: stage_data[stage_data.rater_id == r].set_index("pair_id") for r in rater_ids}
        first, second = (by_rater[r] for r in rater_ids)
        _require(set(first.index) == set(second.index), "Raters do not cover identical pairs")
        first, second = first.sort_index(), second.sort_index()
        outcomes: list[tuple[str, list[str], list[str], list[str]]] = []
        for outcome in ("Q1", "Q2", "valid"):
            columns = [f"{arm}_{outcome}" for arm in ("loop", "zero_shot")]
            left = [str(x) for column in columns for x in first[column]]
            right = [str(x) for column in columns for x in second[column]]
            outcomes.append((outcome, left, right,
                             ["True", "False"] if outcome == "valid" else ["Yes", "No", "Unclear"]))
        outcomes.append(("rationale_preference", first.rationale_preferred.tolist(),
                         second.rationale_preferred.tolist(), ["loop", "zero_shot", "equivalent"]))
        applicable = first.target_preferred != "not_applicable"
        outcomes.append(("target_preference", first.loc[applicable, "target_preferred"].tolist(),
                         second.loc[applicable, "target_preferred"].tolist(),
                         ["loop", "zero_shot", "equivalent"]))
        for outcome, left, right, categories in outcomes:
            agreement, kappa = _agreement(left, right, categories)
            rows.append({"stage": stage, "outcome": outcome, "n_items": len(left),
                         "raw_agreement": agreement, "cohen_kappa": kappa})
    return pd.DataFrame(rows)


def _accounting_table(data: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for stage in ("V2", "V4"):
        subset = data[data.stage == stage]
        rows.append({"stage": stage, "n_pairs": subset.pair_id.nunique(),
                     "n_admissions": subset.hadm_id.nunique(), "n_rater_judgments": len(subset),
                     "missing_Q1": int(sum((subset[f"{arm}_Q1"] == "").sum() for arm in ("loop", "zero_shot"))),
                     "missing_Q2": int(sum((subset[f"{arm}_Q2"] == "").sum() for arm in ("loop", "zero_shot"))),
                     "same_target_pairs": subset[subset.same_target].pair_id.nunique(),
                     "differing_target_pairs": subset[~subset.same_target].pair_id.nunique()})
    return pd.DataFrame(rows)


def _subsets(data: pd.DataFrame) -> list[tuple[str, str, pd.DataFrame]]:
    v2 = data[data.stage == "V2"]
    v4 = data[data.stage == "V4"]
    result = [
        ("all_pairs", "V2", v2), ("all_pairs", "V4", v4),
        ("exact_target", "V2", v2[v2.same_target_normalized]),
        ("exact_full_code", "V4", v4[v4.same_target_normalized]),
        ("same_icd3_category", "V4", v4[v4.same_icd3]),
        ("protected_both_match_original_icd3", "V4", v4[v4.v4_code_matched_cell == True]),
    ]
    for cell in ("both_match_original_reference", "loop_only_matches_original_reference",
                 "zero_shot_only_matches_original_reference", "neither_matches_original_reference"):
        result.append((f"v2_{cell}", "V2", v2[v2.v2_original_reference_cell == cell]))
    return result


def analyze(data: pd.DataFrame, accounting: dict, balance: dict,
            rater_ids: list[str], *, bootstrap_replicates: int = 10_000,
            seed: int = 20260917) -> dict[str, Any]:
    bootstrap = ClusterBootstrap(sorted(data.hadm_id.unique()), bootstrap_replicates, seed)
    quality_rows: list[dict] = []
    primary_rows: list[dict] = []
    preference_rows: list[dict] = []
    for stage in ("V2", "V4"):
        stage_data = data[data.stage == stage]
        for group, subset in [("pooled", stage_data)] + [
            (rater, stage_data[stage_data.rater_id == rater]) for rater in rater_ids
        ]:
            quality, result = _quality(subset, bootstrap, stage, group)
            quality_rows.extend(quality)
            primary_rows.append(result)
            for preference_type in ("rationale", "target"):
                preference_rows.append(_preference(subset, bootstrap, stage, preference_type, group))
    quality_df = pd.DataFrame(quality_rows)
    primary_df = pd.DataFrame(primary_rows)
    preference_df = pd.DataFrame(preference_rows)
    sensitivity = []
    for stage in ("V2", "V4"):
        subset = data[(data.stage == stage) &
                      ~data[[f"{arm}_{q}" for arm in ("loop", "zero_shot")
                             for q in ("Q1", "Q2")]].eq("Unclear").any(axis=1)]
        _, result = _quality(subset, bootstrap, stage, "exclude_unclear_paired")
        sensitivity.append(result)
    controlled = []
    for name, stage, subset in _subsets(data):
        quality, delta = _quality(subset, bootstrap, stage, name, MIN_CONTROLLED_PAIRS_FOR_CI)
        rationale = _preference(subset, bootstrap, stage, "rationale", name, MIN_CONTROLLED_PAIRS_FOR_CI)
        target = _preference(subset, bootstrap, stage, "target", name, MIN_CONTROLLED_PAIRS_FOR_CI)
        controlled.append({"subset": name, "stage": stage, "n_pairs": subset.pair_id.nunique(),
                           "n_rater_judgments": len(subset),
                           "loop_Q1_yes_pct": quality[1]["Q1_yes_pct"],
                           "zero_shot_Q1_yes_pct": quality[0]["Q1_yes_pct"],
                           "delta_Q1_pp": delta["delta_Q1_pp"],
                           "delta_Q1_95CI": delta["delta_Q1_95CI"],
                           "loop_Q2_yes_pct": quality[1]["Q2_yes_pct"],
                           "zero_shot_Q2_yes_pct": quality[0]["Q2_yes_pct"],
                           "delta_Q2_pp": delta["delta_Q2_pp"],
                           "delta_Q2_95CI": delta["delta_Q2_95CI"],
                           "loop_valid_pct": quality[1]["valid_pct"],
                           "zero_shot_valid_pct": quality[0]["valid_pct"],
                           "loop_valid_ci_low": quality[1]["valid_ci_low"],
                           "loop_valid_ci_high": quality[1]["valid_ci_high"],
                           "zero_shot_valid_ci_low": quality[0]["valid_ci_low"],
                           "zero_shot_valid_ci_high": quality[0]["valid_ci_high"],
                           "delta_pp": delta["delta_valid_pp"], "delta_95CI": delta["delta_valid_95CI"],
                           "loop_preferred_pct": rationale["loop_pct"],
                           "zero_shot_preferred_pct": rationale["zero_shot_pct"],
                           "equivalent_pct": rationale["equivalent_pct"],
                           "target_loop_preferred_pct": target["loop_pct"],
                           "target_zero_shot_preferred_pct": target["zero_shot_pct"],
                           "target_equal_pct": target["equivalent_pct"],
                           "small_cell": subset.pair_id.nunique() < MIN_CONTROLLED_PAIRS_FOR_CI})
    accepted = []
    for stage in ("V2", "V4"):
        subset = data[(data.stage == stage) & (data.loop_accepted == True)]
        for outcome, values in (("Q1_yes", (subset.loop_Q1 == "Yes").to_numpy(float)),
                                ("Q2_yes", (subset.loop_Q2 == "Yes").to_numpy(float)),
                                ("valid", subset.loop_valid.to_numpy(float))):
            ci = bootstrap.rate_ci(subset, values) if subset.pair_id.nunique() >= MIN_CONTROLLED_PAIRS_FOR_CI else (None, None)
            accepted.append({"stage": stage, "outcome": outcome, "n_pairs": subset.pair_id.nunique(),
                             "n_judgments": len(subset), "yes_n": int(values.sum()),
                             "yes_pct": 100 * _rate(values) if len(values) else None,
                             "ci_95": _ci_text(ci)})
    complaint = []
    for (stage, chief), subset in data.groupby(["stage", "chief_complaint"], sort=True):
        pref = _preference(subset, bootstrap, stage, "rationale", chief)
        complaint.append({"stage": stage, "chief_complaint": chief,
                          "n_pairs": subset.pair_id.nunique(), "n_judgments": len(subset),
                          "loop_valid_pct": 100 * subset.loop_valid.mean(),
                          "zero_shot_valid_pct": 100 * subset.zero_shot_valid.mean(),
                          "loop_preferred_pct": pref["loop_pct"],
                          "zero_shot_preferred_pct": pref["zero_shot_pct"],
                          "equivalent_pct": pref["equivalent_pct"]})
    lengths = []
    length_check = []
    for stage in ("V2", "V4"):
        subset = data[data.stage == stage].drop_duplicates("pair_id")
        for arm in ("loop", "zero_shot"):
            values = pd.to_numeric(subset[f"{arm}_words"], errors="coerce").dropna()
            lengths.append({"stage": stage, "arm": arm, "n": len(values),
                            "median_words": values.median() if len(values) else None,
                            "q1_words": values.quantile(.25) if len(values) else None,
                            "q3_words": values.quantile(.75) if len(values) else None})
        for preference, group in data[data.stage == stage].groupby("rationale_preferred"):
            word_delta = (pd.to_numeric(group.loop_words, errors="coerce") -
                          pd.to_numeric(group.zero_shot_words, errors="coerce")).dropna()
            length_check.append({"stage": stage, "rationale_preferred": preference,
                                 "n_judgments": len(group),
                                 "median_loop_minus_zero_words": word_delta.median() if len(word_delta) else None,
                                 "loop_valid_pct": 100 * group.loop_valid.mean(),
                                 "zero_shot_valid_pct": 100 * group.zero_shot_valid.mean()})
    return {
        "accounting": accounting, "balance": balance, "seed": seed,
        "bootstrap_replicates": bootstrap_replicates,
        "randomization_balance": pd.DataFrame([
            {"stage": stage, "A_loop": counts["loop"], "A_zero_shot": counts["zero_shot"],
             "B_loop": counts["zero_shot"], "B_zero_shot": counts["loop"]}
            for stage, counts in balance.items()
        ]),
        "table1_accounting": _accounting_table(data),
        "table2_quality": quality_df,
        "table3_preferences": preference_df,
        "table4_controlled": pd.DataFrame(controlled),
        "table5_reliability": reliability(data, rater_ids),
        "primary_differences": primary_df,
        "sensitivity": pd.DataFrame(sensitivity),
        "loop_accepted": pd.DataFrame(accepted),
        "chief_complaint": pd.DataFrame(complaint),
        "rationale_length": pd.DataFrame(lengths),
        "length_check": pd.DataFrame(length_check),
    }


def _markdown_table(frame: pd.DataFrame, columns: list[str] | None = None) -> str:
    if columns:
        frame = frame[columns]
    if frame.empty:
        return "No observations."
    def fmt(value: Any) -> str:
        if value is None or (isinstance(value, (float, np.floating)) and not math.isfinite(value)):
            return "NA"
        if isinstance(value, (float, np.floating)):
            return f"{value:.2f}"
        return str(value).replace("|", "\\|").replace("\n", " ")
    headers = list(frame.columns)
    lines = ["| " + " | ".join(headers) + " |", "|" + "|".join("---" for _ in headers) + "|"]
    lines += ["| " + " | ".join(fmt(value) for value in row) + " |"
              for row in frame.itertuples(index=False, name=None)]
    return "\n".join(lines)


def _interpret(results: dict[str, Any]) -> tuple[str, str]:
    primary = results["primary_differences"]
    pooled = primary[primary.group == "pooled"].set_index("stage")
    v2 = pooled.loc["V2"]
    v4 = pooled.loc["V4"]
    values = [v2.delta_valid_pp, v4.delta_valid_pp]
    quality = results["table2_quality"]
    stage_rates = quality[quality.group == "pooled"].valid_pct.tolist()
    if all(rate >= 80 for rate in stage_rates) and all(abs(value) < 10 for value in values):
        conclusion = ("Clinicians rated both strategies' sampled rationales as frequently valid; "
                      "this audit does not show a large additional validity gain from the loop.")
    elif any(rate < 50 for rate in quality[(quality.group == "pooled") & (quality.arm == "loop")].valid_pct):
        conclusion = ("Some verifier-loop outputs lacked clinically adequate rationales; "
                      "claims about retained reasoning-trace quality should be narrowed.")
    elif all(value > 0 for value in values) and all(pooled.loc[s].delta_valid_ci_low > 0 for s in ("V2", "V4")):
        conclusion = "In this enriched blinded sample, verifier-loop rationales had higher clinician-rated validity in both stages."
    elif all(value > 0 for value in values):
        conclusion = "Point estimates favored verifier-loop rationales in both stages, but the intervals do not establish a consistent difference."
    elif all(value < 0 for value in values):
        conclusion = "Point estimates did not favor verifier-loop rationale validity in either stage."
    else:
        conclusion = "The stage-specific rationale-validity differences were mixed or small."
    controlled = results["table4_controlled"]
    exact = controlled[(controlled.subset.isin(["exact_target", "exact_full_code"])) &
                       (controlled.n_pairs >= MIN_CONTROLLED_PAIRS_FOR_CI)]
    controlled_sentence = (
        "Exact-target comparisons (" + "; ".join(
            f"{row.stage} n={row.n_pairs}, loop-minus-zero-shot validity {row.delta_pp:+.1f} pp "
            f"{row.delta_95CI}" for row in exact.itertuples()
        ) + ") hold diagnostic target selection constant."
        if not exact.empty else "Exact-target cells were too small for a stable controlled inference."
    )
    preference = results["table3_preferences"]
    target = preference[(preference.group == "pooled") & (preference.preference_type == "target")]
    rationale = preference[(preference.group == "pooled") & (preference.preference_type == "rationale")]
    if (target.margin_pp.fillna(0) > 0).all() and (rationale.margin_pp.fillna(0) <= 0).all():
        conclusion += (" Target comparisons favored the loop, while rationale preference did not; "
                       "target selection and explanation quality should be described separately.")
    return conclusion, controlled_sentence


def _report(results: dict[str, Any], rater_ids: list[str],
            details: dict[str, dict[str, Any]] | None = None) -> str:
    interpretation, controlled_sentence = _interpret(results)
    q = results["table2_quality"]
    pref = results["table3_preferences"]
    controlled = results["table4_controlled"]
    reliability_table = results["table5_reliability"]
    pooled = results["primary_differences"]
    pooled = pooled[pooled.group == "pooled"].set_index("stage")
    v2, v4 = pooled.loc["V2"], pooled.loc["V4"]
    valid = q[(q.group == "pooled") & (q.arm == "loop")].set_index("stage")
    pooled_quality = q[q.group == "pooled"].set_index(["stage", "arm"])
    grounding = "; ".join(
        f"{stage} {arm.replace('_', ' ')} {pooled_quality.loc[(stage, arm)].Q1_yes_pct:.1f}%"
        for stage in ("V2", "V4") for arm in ("zero_shot", "loop"))
    support = "; ".join(
        f"{stage} {arm.replace('_', ' ')} {pooled_quality.loc[(stage, arm)].Q2_yes_pct:.1f}%"
        for stage in ("V2", "V4") for arm in ("zero_shot", "loop"))
    interpretation += (" Patient-fact grounding (Q1) was high across both stages and arms "
                       f"({grounding}), whereas clinical support (Q2) fell at the code-specific V4 stage "
                       f"({support}). This pattern points to whether cited facts justify the stated target "
                       "more than to unsupported patient facts.")
    verifier_note = ""
    if details is not None:
        scores = []
        accepted = []
        sanity = []
        for rater, tables in details.items():
            score = tables["deepdive"]["score_association"]
            for row in score[score.outcome == "Q2_yes"].itertuples():
                scores.append(f"{rater} {row.stage} ρ={row.spearman_rho_binary:+.2f}")
            comparison = tables["deepdive"]["accepted_vs_rejected"]
            for row in comparison[comparison.outcome == "valid"].itertuples():
                accepted.append(f"{rater} {row.stage} {row.accepted_minus_rejected_pp:+.1f} pp "
                                f"[95% CI {row.ci_low_pp:+.1f}, {row.ci_high_pp:+.1f}]")
            conditional = tables["deepdive"]["conditional_preference"]
            for row in conditional[(conditional.stage == "V4") & (conditional.basis == "Q2") &
                                   (conditional.condition.isin(["loop_only_yes", "zero_shot_only_yes"]))].itertuples():
                preferred = row.loop_preferred if row.condition == "loop_only_yes" else row.zero_shot_preferred
                sanity.append(f"{rater} {row.condition}: {preferred}/{row.n_pairs}")
        verifier_note = (" Loop acceptance showed no stable validity advantage over rejection "
                         f"({'; '.join(accepted)}). Continuous verifier-score associations with clinician Q2 "
                         f"were weak ({'; '.join(scores)}). These descriptive results suggest limited alignment "
                         "between the automated verification signal and clinician-assessed clinical support; "
                         "the sample is small and enriched. As a response-consistency check, when only one V4 "
                         f"rationale passed Q2, clinicians usually preferred it ({'; '.join(sanity)}).")
        interpretation += verifier_note
    agreement = reliability_table[reliability_table.outcome == "valid"].set_index("stage")
    def kappa(stage: str) -> str:
        value = agreement.loc[stage].cohen_kappa
        return "NA" if value is None or not math.isfinite(value) else f"{value:.2f}"
    length_notes = []
    lengths = results["rationale_length"]
    for stage_name in ("V2", "V4"):
        stage_lengths = lengths[lengths.stage == stage_name].set_index("arm")
        loop_median = stage_lengths.loc["loop"].median_words
        zero_median = stage_lengths.loc["zero_shot"].median_words
        if pd.notna(loop_median) and pd.notna(zero_median):
            imbalance = abs(loop_median - zero_median) / max(zero_median, 1)
            label = "large descriptive imbalance" if imbalance >= .5 else "no large median-length imbalance"
            length_notes.append(f"{stage_name}: loop {loop_median:.1f} vs zero-shot {zero_median:.1f} words ({label})")
    rebuttal = (
        "We agree that our verifier does not establish step-level logical validity; this is not the claim we intend to make. "
        f"In a blinded, within-admission audit of 42 selected cases, two clinicians compared zero-shot and verifier-loop V2/V4 rationales. "
        f"Loop rationale-valid rates were {valid.loc['V2'].valid_pct:.1f}% (V2) and {valid.loc['V4'].valid_pct:.1f}% (V4); "
        f"paired loop-minus-zero-shot differences were {v2.delta_valid_pp:+.1f} pp {v2.delta_valid_95CI} and "
        f"{v4.delta_valid_pp:+.1f} pp {v4.delta_valid_95CI}, respectively. "
        f"{controlled_sentence} Inter-rater composite-validity raw agreement was "
        f"{agreement.loc['V2'].raw_agreement:.2f} (V2; κ={kappa('V2')}) and "
        f"{agreement.loc['V4'].raw_agreement:.2f} (V4; κ={kappa('V4')}). "
        "Grounding of patient facts remained high, while support for the specific diagnosis/code fell at V4; "
        "the loop did not reliably improve clinical support for the target. "
        "Verifier acceptance and score showed little alignment with clinician clinical-support ratings."
    )
    lines = [
        "# Blinded clinician audit: batch 1", "",
        "## Study design", "",
        "Two clinicians rated the same selected 42-admission batch: 42 V2 and 42 V4 A/B pairs, "
        "with zero-shot/verifier-loop identities hidden until annotation completion. "
        "The 42 cases are enriched and do not estimate prevalence over all model outputs. "
        "V2 precedes V4; A and B were shown together. Raters: " + ", ".join(rater_ids) + ".", "",
        "## Annotation completion and sanity checks", "",
        _markdown_table(results["table1_accounting"]), "",
        f"All required Q1/Q2, rationale-preference, and applicable target-preference responses were present. "
        f"Target preferences recorded: {results['accounting']['n_target_preference_responses']}; "
        f"not applicable because targets were identical: {results['accounting']['n_target_not_applicable']}. "
        f"Each complaint contributed six admissions. A/B stage allocation: {results['balance']}. "
        f"Admission-cluster percentile bootstrap: {results['bootstrap_replicates']:,} replicates, seed {results['seed']}. "
        "The independent resampling unit is admission, not clinician judgment.", "",
        _markdown_table(results["randomization_balance"]), "",
        "## Primary V2 results", "",
        _markdown_table(q[(q.stage == "V2") & (q.group == "pooled")],
                        ["arm", "n", "Q1_yes_n", "Q1_yes_pct", "Q2_yes_n", "Q2_yes_pct", "valid_n", "valid_pct", "valid_95CI"]), "",
        f"Loop minus zero-shot validity: {v2.delta_valid_pp:+.1f} percentage points, 95% CI {v2.delta_valid_95CI}.", "",
        "## Primary V4 results", "",
        _markdown_table(q[(q.stage == "V4") & (q.group == "pooled")],
                        ["arm", "n", "Q1_yes_n", "Q1_yes_pct", "Q2_yes_n", "Q2_yes_pct", "valid_n", "valid_pct", "valid_95CI"]), "",
        f"Loop minus zero-shot validity: {v4.delta_valid_pp:+.1f} percentage points, 95% CI {v4.delta_valid_95CI}. "
        "Unclear counts as not valid in the primary composite.", "",
        "### Per-clinician and Unclear-exclusion checks", "",
        _markdown_table(q[q.group != "pooled"], ["stage", "group", "arm", "n", "Q1_yes_pct", "Q2_yes_pct", "valid_pct", "valid_95CI"]), "",
        _markdown_table(results["primary_differences"], ["stage", "group", "n_pairs", "delta_valid_pp", "delta_valid_95CI"]), "",
        "Sensitivity excludes an entire paired rater judgment when either arm has an Unclear Q1 or Q2 response.", "",
        _markdown_table(results["sensitivity"], ["stage", "n_pairs", "n_judgments", "delta_valid_pp", "delta_valid_95CI"]), "",
        "## Same-target / original-reference-stratified analyses", "",
        "The exact-target subsets are the cleanest rationale-only comparison: "
        "V2 exact targets use case/whitespace-normalized names; V4 exact targets use normalized full ICD codes. "
        "The V4 ICD3 subset holds category constant but may differ in full-code specificity. "
        "The protected V4 cell was selected using the original three-character ICD mapping criterion; "
        "it is not a prevalence estimate. Cells with fewer than five pairs have no bootstrap CI.", "",
        _markdown_table(controlled, ["subset", "stage", "n_pairs", "loop_Q1_yes_pct", "zero_shot_Q1_yes_pct",
                                     "delta_Q1_pp", "delta_Q1_95CI", "loop_Q2_yes_pct", "zero_shot_Q2_yes_pct",
                                     "delta_Q2_pp", "delta_Q2_95CI", "loop_valid_pct", "zero_shot_valid_pct",
                                     "delta_pp", "delta_95CI", "loop_preferred_pct", "zero_shot_preferred_pct", "equivalent_pct"]), "",
        "V2 original-reference strata compare normalized target names with the keyed SentenceTransformer `disease` candidate. "
        "That candidate is derived from discharge text, not an independent clinician-adjudicated diagnosis; "
        "no fuzzy semantic matching was used.", "",
        "## Target-appropriateness results", "",
        "Only differing-target pairs were asked. Equal means two different targets judged equally appropriate; "
        "null means the comparison was not asked. V4 preferences include evidence-supported full-code specificity.", "",
        _markdown_table(pref[(pref.preference_type == "target") & (pref.group == "pooled")],
                        ["stage", "n_pairs", "n_judgments", "loop_n", "loop_pct", "zero_shot_n",
                         "zero_shot_pct", "equivalent_n", "equivalent_pct", "margin_pp", "margin_95CI"]), "",
        "## Rationale-preference results", "",
        "Preferences concern the explanation, separate from target selection. Exact two-sided sign tests use non-equivalent judgments only. "
        "The pooled sign-test p-value treats two ratings of the same admission as independent and is descriptive only; "
        "per-clinician tests are in table3_preferences.csv. Effect sizes and admission-cluster CIs remain primary.", "",
        _markdown_table(pref[(pref.preference_type == "rationale") & (pref.group == "pooled")],
                        ["stage", "n_judgments", "loop_n", "loop_pct", "zero_shot_n", "zero_shot_pct",
                         "equivalent_n", "equivalent_pct", "margin_pp", "margin_95CI", "sign_test_p"]), "",
        "## Loop-accepted trace quality", "",
        "Absolute clinician-assessed quality of traces accepted by the construction loop. This is not a causal comparison.", "",
        _markdown_table(results["loop_accepted"]), "",
        "## Inter-rater agreement", "",
        "Q1/Q2 retain Yes/No/Unclear categories; preferences retain loop/zero-shot/equivalent. "
        "Kappa is undefined when expected agreement is 1.", "",
        _markdown_table(reliability_table), "",
        "## Chief-complaint robustness", "",
        "Descriptive only; no complaint-specific hypothesis tests.", "",
        _markdown_table(results["chief_complaint"]), "",
        "## Rationale length check", "",
        "Word counts come from the keyed construction metadata; Q1/Q3 are the interquartile limits. "
        "The second table checks whether the arm-length difference tracks clinician preference or validity. "
        "These are descriptive associations, not an adjustment for length.", "",
        _markdown_table(results["rationale_length"]), "",
        _markdown_table(results["length_check"]), "",
        "; ".join(length_notes) + ". A length imbalance alone cannot establish that length explains clinical ratings.", "",
        "## Interpretation", "", interpretation + " " + controlled_sentence, "",
        "## Limitations", "",
        "This audit cannot establish step-level logical validity, faithfulness to internal model reasoning, "
        "quality of every MERLIN-DDx trace, or prevalence in the full model-output distribution. "
        "Both raters evaluated the same admissions, and controlled subsets may be small.", "",
        "## Candidate rebuttal wording", "", rebuttal, "",
    ]
    return "\n".join(lines)


def _figures(results: dict[str, Any], directory: Path) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    directory.mkdir(parents=True, exist_ok=True)
    colors = {"zero_shot": "#59799B", "loop": "#B66B48"}
    quality = results["table2_quality"]
    quality = quality[quality.group == "pooled"]
    fig, axes = plt.subplots(1, 2, figsize=(9.2, 3.8), sharey=True)
    for axis, stage in zip(axes, ("V2", "V4"), strict=True):
        for offset, arm in ((-.1, "zero_shot"), (.1, "loop")):
            row = quality[(quality.stage == stage) & (quality.arm == arm)].iloc[0]
            for i, key in enumerate(("Q1", "Q2", "valid")):
                rate = row[f"{key}_yes_pct" if key != "valid" else "valid_pct"]
                low = row[f"{key}_ci_low" if key != "valid" else "valid_ci_low"]
                high = row[f"{key}_ci_high" if key != "valid" else "valid_ci_high"]
                xerr = None if low is None else [[rate - 100 * low], [100 * high - rate]]
                axis.errorbar(rate, i + offset, xerr=xerr, fmt="o", color=colors[arm],
                              capsize=3, label=arm.replace("_", " ") if i == 0 else None)
        axis.set(title=stage, xlim=(0, 100), yticks=range(3), yticklabels=["Q1 grounded", "Q2 supportive", "Valid rationale"])
        axis.invert_yaxis(); axis.grid(axis="x", alpha=.2); axis.set_xlabel("Yes / valid (%)")
    axes[1].legend(loc="lower right", frameon=False)
    fig.tight_layout()
    for suffix in ("png", "pdf"):
        fig.savefig(directory / f"figure1_absolute_quality.{suffix}", dpi=250)
    plt.close(fig)

    prefs = results["table3_preferences"]
    prefs = prefs[(prefs.preference_type == "rationale") & (prefs.group == "pooled")]
    fig, ax = plt.subplots(figsize=(7, 3.2))
    left = np.zeros(2)
    for field, label, color in (("loop_pct", "Loop", colors["loop"]),
                                 ("equivalent_pct", "Equivalent", "#AEB4B9"),
                                 ("zero_shot_pct", "Zero-shot", colors["zero_shot"])):
        values = np.array([prefs[prefs.stage == stage][field].iloc[0] for stage in ("V2", "V4")])
        ax.barh(["V2", "V4"], values, left=left, color=color, label=label)
        left += values
    ax.set(xlim=(0, 100), xlabel="Clinician judgments (%)", title="Pairwise rationale preference")
    ax.legend(ncol=3, loc="upper center", bbox_to_anchor=(.5, -.22), frameon=False)
    fig.tight_layout()
    for suffix in ("png", "pdf"):
        fig.savefig(directory / f"figure2_rationale_preference.{suffix}", dpi=250, bbox_inches="tight")
    plt.close(fig)

    controlled = results["table4_controlled"]
    controlled = controlled[(controlled.n_pairs >= MIN_CONTROLLED_PAIRS_FOR_CI) &
                            controlled.subset.isin(["all_pairs", "exact_target", "exact_full_code", "protected_both_match_original_icd3"])]
    if not controlled.empty:
        fig, ax = plt.subplots(figsize=(8.5, max(3.1, .55 * len(controlled) + 1.3)))
        y = np.arange(len(controlled))
        for offset, arm, label in ((-.16, "zero_shot", "Zero-shot"), (.16, "loop", "Loop")):
            rates = controlled[f"{arm}_valid_pct"].to_numpy(float)
            lows = 100 * controlled[f"{arm}_valid_ci_low"].to_numpy(float)
            highs = 100 * controlled[f"{arm}_valid_ci_high"].to_numpy(float)
            errors = np.vstack((np.maximum(0, rates - lows), np.maximum(0, highs - rates)))
            errors = None if not np.isfinite(errors).all() else errors
            ax.barh(y + offset, rates, height=.29, color=colors[arm], label=label,
                    xerr=errors, error_kw={"ecolor": "#333333", "capsize": 2, "elinewidth": .8})
        ax.set(yticks=y, yticklabels=[f"{row.stage}: {row.subset.replace('_', ' ')} (n={row.n_pairs})"
                                    for row in controlled.itertuples()], xlim=(0, 100), xlabel="Valid rationales (%)")
        ax.invert_yaxis(); ax.legend(frameon=False); ax.grid(axis="x", alpha=.2)
        fig.tight_layout()
        for suffix in ("png", "pdf"):
            fig.savefig(directory / f"figure3_controlled_subsets.{suffix}", dpi=250)
        plt.close(fig)


def run_pipeline(*, blinded_path: Path, keyed_path: Path, raters: dict[str, Path],
                 output_dir: Path, bootstrap_replicates: int = 10_000,
                 seed: int = 20260917, adjudicated_path: Path | None = None,
                 raw_source_path: Path | None = None, ground_truth_path: Path | None = None,
                 mapping_review_path: Path | None = None) -> Path:
    """Validate blind completion first, then join key, analyze, and write outputs atomically."""
    _require(len(raters) == 2, "Exactly two --rater exports are required")
    output_dir = output_dir.resolve()
    source_paths = [blinded_path.resolve(), keyed_path.resolve(), *(p.resolve() for p in raters.values()),
                    *(p.resolve() for p in (adjudicated_path, raw_source_path, ground_truth_path,
                                             mapping_review_path) if p is not None)]
    _require(not any(output_dir == path or output_dir in path.parents or path in output_dir.parents
                     for path in source_paths),
             "Output directory must be separate from raw inputs")
    project_data = Path(__file__).resolve().parents[1] / "data"
    raw_roots = [project_data / name for name in ("source", "annotations", "rebuttal_audit_annotations")]
    _require(not any(root.resolve() == output_dir or root.resolve() in output_dir.parents
                     for root in raw_roots), "Output directory cannot be inside a raw-data directory")
    _require(not output_dir.exists(), f"Output directory already exists: {output_dir}")
    blinded = _read_csv(blinded_path)
    ratings = pd.concat([load_annotation_export(path, rater) for rater, path in raters.items()], ignore_index=True)
    frame, accounting = validate_blinded_and_annotations(blinded, ratings, list(raters))
    # Nothing above opens keyed_path. An incomplete annotation export stops here.
    joined, balance = join_key_after_completion(frame, keyed_path)
    results = analyze(joined, accounting, balance, list(raters),
                      bootstrap_replicates=bootstrap_replicates, seed=seed)
    adjudicated_frame = None
    adjudicated_pair_summary = None
    adjudicated_judgment_summary = None
    adjudicated_reference = None
    if adjudicated_path is not None:
        from merlin_ddx.rebuttal_adjudicated import (
            adjudicated_pair_summary as summarize_adjudicated_pairs,
            adjudicated_judgment_summary as summarize_adjudicated_judgments,
            load_adjudicated, prepare_adjudicated,
        )
        adjudicated_reference = load_adjudicated(adjudicated_path, set(joined.hadm_id), raw_source_path)
        adjudicated_frame = prepare_adjudicated(joined, adjudicated_reference)
        adjudicated_pair_summary = summarize_adjudicated_pairs(adjudicated_frame)
        adjudicated_judgment_summary = summarize_adjudicated_judgments(adjudicated_frame, list(raters))
    detailed = None
    if ground_truth_path is not None:
        from merlin_ddx.rebuttal_final_detail import analyze_detail
        detailed = analyze_detail(joined, list(raters), gt_path=ground_truth_path,
                                  keyed_path=keyed_path, mapping_review_path=mapping_review_path,
                                  bootstrap_replicates=bootstrap_replicates, seed=seed)
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="audit-batch1-", dir=output_dir.parent) as scratch:
        stage = Path(scratch) / output_dir.name
        stage.mkdir()
        (adjudicated_frame if adjudicated_frame is not None else joined).to_csv(
            stage / "audit_batch1_analysis.csv", index=False)
        if adjudicated_frame is not None:
            adjudicated_frame.to_csv(stage / "adjudicated_reference_judgments.csv", index=False)
            adjudicated_pair_summary.to_csv(stage / "adjudicated_reference_pair_summary.csv", index=False)
            adjudicated_judgment_summary.to_csv(stage / "adjudicated_reference_judgment_summary.csv", index=False)
        if detailed is not None:
            from merlin_ddx.rebuttal_final_detail import write_detail
            write_detail(detailed, stage)
        summary = []
        for row in results["table2_quality"].itertuples():
            for outcome in ("Q1", "Q2", "valid"):
                prefix = outcome if outcome != "valid" else "valid"
                rate = getattr(row, f"{outcome}_yes_pct" if outcome != "valid" else "valid_pct")
                low = getattr(row, f"{prefix}_ci_low")
                high = getattr(row, f"{prefix}_ci_high")
                summary.append({"analysis": f"{outcome}_yes_rate" if outcome != "valid" else "rationale_valid_rate",
                                "stage": row.stage, "group": row.group, "arm": row.arm,
                                "n_judgments": row.n, "estimate_pp": rate,
                                "ci_low_pp": None if low is None else 100 * low,
                                "ci_high_pp": None if high is None else 100 * high})
        for row in results["primary_differences"].itertuples():
            summary.append({"analysis": "validity_difference", "stage": row.stage, "group": row.group,
                            "n_pairs": row.n_pairs, "estimate_pp": row.delta_valid_pp,
                            "ci_low_pp": row.delta_valid_ci_low, "ci_high_pp": row.delta_valid_ci_high})
        for row in results["table3_preferences"].itertuples():
            summary.append({"analysis": f"{row.preference_type}_preference_margin", "stage": row.stage,
                            "group": row.group, "n_pairs": row.n_pairs, "estimate_pp": row.margin_pp,
                            "ci_low_pp": row.margin_ci_low, "ci_high_pp": row.margin_ci_high})
        pd.DataFrame(summary).to_csv(stage / "audit_batch1_summary.csv", index=False)
        for name in ("randomization_balance", "table1_accounting", "table2_quality", "table3_preferences", "table4_controlled",
                     "table5_reliability", "primary_differences", "sensitivity", "loop_accepted",
                     "chief_complaint", "rationale_length", "length_check"):
            results[name].to_csv(stage / f"{name}.csv", index=False)
        report = _report(results, list(raters), detailed)
        if adjudicated_pair_summary is not None:
            from merlin_ddx.rebuttal_adjudicated import report_section as adjudicated_report_section
            report += "\n" + adjudicated_report_section(
                adjudicated_pair_summary, adjudicated_judgment_summary, adjudicated_reference)
        if detailed is not None:
            from merlin_ddx.rebuttal_final_detail import detail_report
            report += "\n" + detail_report(detailed)
        (stage / "audit_batch1_report.md").write_text(report, encoding="utf-8")
        _figures(results, stage / "figures")
        (stage / "run_metadata.json").write_text(json.dumps({
            "seed": seed, "bootstrap_replicates": bootstrap_replicates,
            "rater_ids": list(raters), "input_files": {"blinded": str(blinded_path),
                "keyed": str(keyed_path), **{r: str(p) for r, p in raters.items()},
                **({"adjudicated": str(adjudicated_path)} if adjudicated_path else {}),
                **({"raw_source": str(raw_source_path)} if raw_source_path else {}),
                **({"ground_truth": str(ground_truth_path)} if ground_truth_path else {}),
                **({"mapping_review": str(mapping_review_path)} if mapping_review_path else {})},
            "input_sha256": {"blinded": _input_digest(blinded_path),
                "keyed": _input_digest(keyed_path), **{r: _input_digest(p) for r, p in raters.items()},
                **({"adjudicated": _input_digest(adjudicated_path)} if adjudicated_path else {}),
                **({"raw_source": _input_digest(raw_source_path)} if raw_source_path else {}),
                **({"ground_truth": _input_digest(ground_truth_path)} if ground_truth_path else {}),
                **({"mapping_review": _input_digest(mapping_review_path)} if mapping_review_path else {})},
            "analysis_rules": {"unclear_primary": "not valid", "unclear_sensitivity": "exclude paired judgment",
                               "cluster_unit": "hadm_id", "controlled_ci_min_pairs": MIN_CONTROLLED_PAIRS_FOR_CI,
                               "adjudicated_v2": "literal normalized diagnosis only",
                               "adjudicated_v4": "selected full ICD and ICD3"},
        }, indent=2) + "\n", encoding="utf-8")
        for directory, _, files in os.walk(stage):
            os.chmod(directory, 0o700)
            for file in files:
                os.chmod(Path(directory) / file, 0o600)
        shutil.move(str(stage), str(output_dir))
    return output_dir


def _input_digest(path: Path) -> str:
    digest = hashlib.sha256()
    files = sorted(path.glob("*.json")) if path.is_dir() else [path]
    for file in files:
        digest.update(file.name.encode("utf-8"))
        with file.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    return digest.hexdigest()
