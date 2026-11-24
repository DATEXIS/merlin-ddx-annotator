"""Descriptive, one-clinician deep dive for the frozen rebuttal audit.

The keyed allocation is opened only after the single export passes the full
blinded completion check. Outputs contain patient-derived text and belong in
the ignored local reports directory, never in version control.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

from merlin_ddx.rebuttal_analysis import (
    AuditValidationError, ClusterBootstrap, EXPECTED_ADMISSIONS, EXPECTED_PAIRS,
    QUESTIONS, RATIONALE_CHOICES, TARGET_CHOICES, VALID_JUDGMENTS,
    _markdown_table, _quality, _read_csv, _require, _string,
    join_key_after_completion, load_annotation_export,
)


def validate_one_rater(blinded: pd.DataFrame, ratings: pd.DataFrame) -> pd.DataFrame:
    """Check all 84 blinded responses before opening any keyed information."""
    required = {"pair_id", "hadm_id", "chief_complaint", "stage", "target_A", "reason_A",
                "target_B", "reason_B"}
    _require(required <= set(blinded), f"Blinded CSV lacks {sorted(required - set(blinded))}")
    _require(len(blinded) == EXPECTED_PAIRS and blinded.pair_id.nunique() == EXPECTED_PAIRS,
             "Blinded batch must contain 84 unique pairs")
    _require(blinded.hadm_id.nunique() == EXPECTED_ADMISSIONS,
             "Blinded batch must contain 42 admissions")
    _require(blinded.stage.value_counts().to_dict() == {"V2": 42, "V4": 42},
             "Blinded batch must contain 42 V2 and 42 V4 pairs")
    _require((blinded.groupby("hadm_id").stage.nunique() == 2).all(),
             "Every admission must have both stages")
    complaints = blinded.groupby("chief_complaint").hadm_id.nunique()
    _require(len(complaints) == 7 and (complaints == 6).all(),
             "Expected seven complaints with six admissions each")
    for field in ("target_A", "target_B", "reason_A", "reason_B"):
        _require((blinded[field].map(_string) != "").all(), f"Missing blinded {field}")
    needed = {"pair_id", "hadm_id", "rater_id", *QUESTIONS,
              "target_preference_A_B_equal", "rationale_preference_A_B_equal"}
    _require(needed <= set(ratings), f"Annotation export lacks {sorted(needed - set(ratings))}")
    _require(len(ratings) == EXPECTED_PAIRS and ratings.pair_id.nunique() == EXPECTED_PAIRS,
             "One clinician must complete all 84 unique pairs")
    _require(set(ratings.pair_id) == set(blinded.pair_id),
             "Annotation pair IDs do not match the blinded batch")
    _require(ratings.rater_id.nunique() == 1, "Expected exactly one clinician")
    template = {"preference_A_B_equivalent", "A_Q1_evidence_grounded",
                "A_Q2_supports_target", "B_Q1_evidence_grounded", "B_Q2_supports_target",
                "rater_comment"}
    frame = ratings.merge(blinded.drop(columns=list(template & set(blinded))),
                          on="pair_id", how="left", validate="one_to_one", suffixes=("", "_blind"))
    _require(frame.hadm_id.eq(frame.hadm_id_blind).all(), "Pair/admission mismatch")
    frame = frame.drop(columns="hadm_id_blind")
    for field in QUESTIONS:
        _require(frame[field].map(_string).isin(VALID_JUDGMENTS).all(),
                 f"Missing or invalid {field} response")
    _require(frame.rationale_preference_A_B_equal.map(_string).isin(RATIONALE_CHOICES).all(),
             "Missing or invalid rationale preference")
    same = frame.target_A == frame.target_B
    choice = frame.target_preference_A_B_equal.map(_string)
    _require((choice[same] == "").all(),
             "Same-target pairs must have null target preference")
    _require(choice[~same].isin(TARGET_CHOICES).all(),
             "Different-target pairs need a valid target preference")
    return frame


def decoded_pairs(data: pd.DataFrame) -> pd.DataFrame:
    """One row per pair, with only the requested decoded analysis fields."""
    _require(len(data) == EXPECTED_PAIRS and data.pair_id.nunique() == EXPECTED_PAIRS,
             "Decoded output requires 84 unique pairs")
    score = pd.to_numeric(data.get("_loop_score"), errors="coerce")
    _require(score.notna().all(), "Continuous loop verifier score missing or invalid")
    loop_a = data.A_arm == "loop"
    loop_target = np.where(loop_a, data.target_A, data.target_B)
    zero_target = np.where(loop_a, data.target_B, data.target_A)
    loop_reason = np.where(loop_a, data.reason_A, data.reason_B)
    zero_reason = np.where(loop_a, data.reason_B, data.reason_A)
    return pd.DataFrame({
        "pair_id": data.pair_id, "hadm_id": data.hadm_id, "stage": data.stage,
        "chief_complaint": data.chief_complaint,
        "loop_target": loop_target, "loop_reason": loop_reason,
        "zero_shot_target": zero_target, "zero_shot_reason": zero_reason,
        "loop_Q1": data.loop_Q1, "loop_Q2": data.loop_Q2,
        "loop_valid": data.loop_valid, "zero_shot_Q1": data.zero_shot_Q1,
        "zero_shot_Q2": data.zero_shot_Q2, "zero_shot_valid": data.zero_shot_valid,
        "target_same_exact": data.same_target,
        "target_same_3digit": np.where(data.stage == "V4", data.same_icd3, None),
        "target_preference": data.target_preferred.replace({"not_applicable": None}),
        "rationale_preference": data.rationale_preferred,
        "loop_accept": data.loop_accepted, "loop_verifier_score": score,
        "v4_code_matched_cell": np.where(data.stage == "V4", data.v4_code_matched_cell, None),
        "v2_original_reference_stratum": np.where(data.stage == "V2", data.v2_original_reference_cell, None),
        "loop_reason_words": data.loop_words,
        "zero_shot_reason_words": data.zero_shot_words,
        "rater_comment": data.rater_comment,
    }).reset_index(drop=True)


def _pref_counts(data: pd.DataFrame, column: str = "rationale_preference") -> dict[str, Any]:
    values = data[column].dropna()
    n = len(values)
    loop = int((values == "loop").sum())
    zero = int((values == "zero_shot").sum())
    equal = int((values == "equivalent").sum())
    return {"loop_preferred": loop, "zero_shot_preferred": zero,
            "equal_or_equivalent": equal,
            "loop_margin_pp": 100 * (loop - zero) / n if n else None}


def _quality_counts(data: pd.DataFrame) -> dict[str, Any]:
    n = len(data)
    result: dict[str, Any] = {"n_pairs": n}
    for arm in ("loop", "zero_shot"):
        for label, value in (("Q1", data[f"{arm}_Q1"] == "Yes"),
                             ("Q2", data[f"{arm}_Q2"] == "Yes"),
                             ("valid", data[f"{arm}_valid"].astype(bool))):
            result[f"{arm}_{label}_yes_n" if label != "valid" else f"{arm}_valid_n"] = int(value.sum())
            result[f"{arm}_{label}_pct"] = 100 * value.mean() if n else None
    return result


def _summary_row(data: pd.DataFrame, label: str, *, target: bool = False) -> dict[str, Any]:
    row = {"subset": label, **_quality_counts(data), **_pref_counts(data)}
    if target:
        choices = data.target_preference.dropna()
        row.update({"target_asked_n": len(choices),
                    "target_loop_n": int((choices == "loop").sum()),
                    "target_zero_shot_n": int((choices == "zero_shot").sum()),
                    "target_equal_n": int((choices == "equivalent").sum())})
    return row


def _target_group(row: pd.Series) -> str:
    if row.stage == "V2":
        return "exact_same_diagnosis" if row.target_same_exact else "different_diagnosis"
    if row.target_same_exact:
        return "exact_same_full_icd"
    if row.target_same_3digit:
        return "same_icd3_different_full_code"
    return "different_icd3_categories"


def _conditional_group(row: pd.Series, suffix: str) -> str:
    loop = row[f"loop_{suffix}"] == "Yes" if suffix == "Q2" else bool(row.loop_valid)
    zero = row[f"zero_shot_{suffix}"] == "Yes" if suffix == "Q2" else bool(row.zero_shot_valid)
    if loop and zero:
        return "both_yes"
    if loop:
        return "loop_only_yes"
    if zero:
        return "zero_shot_only_yes"
    return "neither_yes"


def _accepted_difference(data: pd.DataFrame, bootstrap: ClusterBootstrap) -> pd.DataFrame:
    rows = []
    for stage in ("V2", "V4"):
        stage_data = data[data.stage == stage]
        accepted = stage_data[stage_data.loop_accept == True]
        rejected = stage_data[stage_data.loop_accept == False]
        _require(len(accepted) and len(rejected), f"{stage} needs accepted and rejected cases")
        for label, column in (("Q1", "loop_Q1"), ("Q2", "loop_Q2"), ("valid", "loop_valid")):
            if label == "valid":
                yes = stage_data[column].astype(float).to_numpy()
            else:
                yes = stage_data[column].eq("Yes").astype(float).to_numpy()
            accept_mask = stage_data.loop_accept.to_numpy(bool)
            accepted_values = np.where(accept_mask, yes, 0)
            rejected_values = np.where(~accept_mask, yes, 0)
            a_n = bootstrap._sums(stage_data, accepted_values)
            r_n = bootstrap._sums(stage_data, rejected_values)
            a_d = bootstrap._sums(stage_data, accept_mask.astype(float))
            r_d = bootstrap._sums(stage_data, (~accept_mask).astype(float))
            draws = np.divide(a_n, a_d, out=np.full(len(a_n), np.nan), where=a_d > 0) - np.divide(
                r_n, r_d, out=np.full(len(r_n), np.nan), where=r_d > 0)
            finite = draws[np.isfinite(draws)]
            ci = np.percentile(finite, [2.5, 97.5]) * 100 if len(finite) >= .95 * len(draws) else (np.nan, np.nan)
            a_yes = int(yes[accept_mask].sum())
            r_yes = int(yes[~accept_mask].sum())
            rows.append({"stage": stage, "outcome": label,
                         "accepted_n": len(accepted), "accepted_yes_n": a_yes,
                         "accepted_pct": 100 * a_yes / len(accepted),
                         "rejected_n": len(rejected), "rejected_yes_n": r_yes,
                         "rejected_pct": 100 * r_yes / len(rejected),
                         "accepted_minus_rejected_pp": 100 * (a_yes / len(accepted) - r_yes / len(rejected)),
                         "ci_low_pp": ci[0], "ci_high_pp": ci[1]})
    return pd.DataFrame(rows)


def _score_association(data: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for stage in ("V2", "V4"):
        stage_data = data[data.stage == stage]
        score = stage_data.loop_verifier_score.astype(float)
        for outcome, yes in (("Q2_yes", stage_data.loop_Q2.eq("Yes")),
                             ("composite_valid", stage_data.loop_valid.astype(bool))):
            yes_score = score[yes]
            no_score = score[~yes]
            rho = float(spearmanr(score, yes.astype(int)).statistic) if yes.nunique() > 1 and score.nunique() > 1 else np.nan
            rows.append({"stage": stage, "outcome": outcome,
                         "yes_n": len(yes_score), "not_yes_n": len(no_score),
                         "yes_mean": yes_score.mean() if len(yes_score) else np.nan,
                         "not_yes_mean": no_score.mean() if len(no_score) else np.nan,
                         "mean_difference": yes_score.mean() - no_score.mean() if len(no_score) else np.nan,
                         "yes_median": yes_score.median() if len(yes_score) else np.nan,
                         "not_yes_median": no_score.median() if len(no_score) else np.nan,
                         "yes_q1": yes_score.quantile(.25) if len(yes_score) else np.nan,
                         "yes_q3": yes_score.quantile(.75) if len(yes_score) else np.nan,
                         "not_yes_q1": no_score.quantile(.25) if len(no_score) else np.nan,
                         "not_yes_q3": no_score.quantile(.75) if len(no_score) else np.nan,
                         "median_difference": yes_score.median() - no_score.median() if len(no_score) else np.nan,
                         "spearman_rho_binary": rho})
    return pd.DataFrame(rows)


def _length_tables(data: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    overview, by_preference = [], []
    for stage in ("V2", "V4"):
        subset = data[data.stage == stage]
        for arm in ("loop", "zero_shot"):
            words = subset[f"{arm}_reason_words"].astype(float)
            overview.append({"stage": stage, "arm": arm, "n": len(words),
                             "median_words": words.median(), "q1_words": words.quantile(.25),
                             "q3_words": words.quantile(.75)})
            for status, selection in (("preferred", subset.rationale_preference == arm),
                                      ("not_preferred", subset.rationale_preference.isin(
                                          ["loop", "zero_shot"]) & (subset.rationale_preference != arm)),
                                      ("equivalent_pair", subset.rationale_preference == "equivalent")):
                selected = words[selection]
                by_preference.append({"stage": stage, "arm": arm, "preference_status": status,
                                      "n": len(selected), "median_words": selected.median() if len(selected) else np.nan,
                                      "q1_words": selected.quantile(.25) if len(selected) else np.nan,
                                      "q3_words": selected.quantile(.75) if len(selected) else np.nan})
    return pd.DataFrame(overview), pd.DataFrame(by_preference)


def analyze_preliminary(data: pd.DataFrame, *, bootstrap_replicates: int = 10_000,
                        seed: int = 20260917) -> dict[str, pd.DataFrame]:
    """Produce only descriptive one-rater tables; no inter-rater statistics."""
    decoded = decoded_pairs(data)
    bootstrap = ClusterBootstrap(sorted(decoded.hadm_id.unique()), bootstrap_replicates, seed)
    decoded["target_group"] = decoded.apply(_target_group, axis=1)
    decoded["q2_group"] = decoded.apply(lambda row: _conditional_group(row, "Q2"), axis=1)
    decoded["valid_group"] = decoded.apply(lambda row: _conditional_group(row, "valid"), axis=1)
    aggregate, target_subsets, correctness, conditions, complaints = [], [], [], [], []
    cross_tabs = []
    for stage in ("V2", "V4"):
        subset = decoded[decoded.stage == stage]
        _, validity_delta = _quality(subset, bootstrap, stage, "one_clinician")
        preference_ci = bootstrap.difference_ci(
            subset, subset.rationale_preference.eq("loop").to_numpy(float),
            subset.rationale_preference.eq("zero_shot").to_numpy(float))
        aggregate.append({"stage": stage, **_summary_row(subset, "all_pairs", target=True),
                          "loop_minus_zero_valid_pp": validity_delta["delta_valid_pp"],
                          "valid_ci_low_pp": validity_delta["delta_valid_ci_low"],
                          "valid_ci_high_pp": validity_delta["delta_valid_ci_high"],
                          "rationale_margin_ci_low_pp": None if preference_ci[0] is None else 100 * preference_ci[0],
                          "rationale_margin_ci_high_pp": None if preference_ci[1] is None else 100 * preference_ci[1]})
        for label, group in subset.groupby("target_group", sort=True):
            target_subsets.append({"stage": stage, **_summary_row(group, label, target=True)})
        applicable = subset[subset.target_preference.notna()]
        for target in ("loop", "zero_shot", "equivalent"):
            for rationale in ("loop", "zero_shot", "equivalent"):
                cross_tabs.append({"stage": stage, "target_preference": target,
                                   "rationale_preference": rationale,
                                   "n_pairs": int(((applicable.target_preference == target) &
                                                   (applicable.rationale_preference == rationale)).sum())})
        for basis, group_column in (("Q2", "q2_group"), ("composite_valid", "valid_group")):
            for label in ("both_yes", "loop_only_yes", "zero_shot_only_yes", "neither_yes"):
                group = subset[subset[group_column] == label]
                conditions.append({"stage": stage, "basis": basis, "condition": label,
                                   "n_pairs": len(group), **_pref_counts(group)})
        for complaint, group in subset.groupby("chief_complaint", sort=True):
            complaints.append({"stage": stage, "chief_complaint": complaint,
                               **_summary_row(group, "all_pairs")})
    protected = decoded[(decoded.stage == "V4") & (decoded.v4_code_matched_cell == True)]
    correctness.append({"stage": "V4", **_summary_row(protected, "protected_all", target=True)})
    for label, group in protected.groupby("target_group", sort=True):
        correctness.append({"stage": "V4", **_summary_row(group, f"protected_{label}", target=True)})
    v2 = decoded[decoded.stage == "V2"]
    for label in ("both_match_original_reference", "loop_only_matches_original_reference",
                  "zero_shot_only_matches_original_reference", "neither_matches_original_reference"):
        group = v2[v2.v2_original_reference_stratum == label]
        correctness.append({"stage": "V2", **_summary_row(group, label, target=True)})
    both_valid = decoded[decoded.loop_valid & decoded.zero_shot_valid]
    mutually_valid = []
    review = both_valid[both_valid.rationale_preference != "equivalent"].copy()
    for stage in ("V2", "V4"):
        group = both_valid[both_valid.stage == stage]
        mutually_valid.append({"stage": stage, "n_pairs": len(group), **_pref_counts(group),
                               "nonempty_comments": int(group.rater_comment.map(_string).ne("").sum())})
    comment_rows = decoded[decoded.rater_comment.map(_string).ne("")][
        ["stage", "pair_id", "rationale_preference", "rater_comment"]].copy()
    both_valid_comments = both_valid[both_valid.rater_comment.map(_string).ne("")][
        ["stage", "pair_id", "rationale_preference", "rater_comment"]].copy()
    overview, length_preference = _length_tables(decoded)
    return {
        "decoded": decoded.drop(columns=["target_group", "q2_group", "valid_group"]),
        "aggregate": pd.DataFrame(aggregate),
        "target_subsets": pd.DataFrame(target_subsets),
        "target_rationale_crosstab": pd.DataFrame(cross_tabs),
        "conditional_preference": pd.DataFrame(conditions),
        "original_reference_strata": pd.DataFrame(correctness),
        "accepted_vs_rejected": _accepted_difference(decoded, bootstrap),
        "score_association": _score_association(decoded),
        "mutually_valid": pd.DataFrame(mutually_valid),
        "both_valid_review": review[["stage", "pair_id", "loop_target", "loop_reason",
                                      "zero_shot_target", "zero_shot_reason", "rationale_preference"]],
        "comments": comment_rows,
        "both_valid_comments": both_valid_comments,
        "chief_complaint": pd.DataFrame(complaints),
        "rationale_length": overview,
        "length_by_preference": length_preference,
    }


def _interpret(results: dict[str, pd.DataFrame]) -> str:
    aggregate = results["aggregate"].set_index("stage")
    accepted = results["accepted_vs_rejected"]
    v2 = aggregate.loc["V2"]
    v4 = aggregate.loc["V4"]
    pieces = ["In this selected 42-admission, one-clinician sample, the loop did not show an overall composite-validity advantage "
              f"(V2 {v2.loop_valid_n}/42 versus {v2.zero_shot_valid_n}/42; "
              f"V4 {v4.loop_valid_n}/42 versus {v4.zero_shot_valid_n}/42)."]
    accepted_valid = accepted[accepted.outcome == "valid"].set_index("stage")
    if all(abs(accepted_valid.loc[stage].accepted_minus_rejected_pp) < 10 for stage in ("V2", "V4")):
        pieces.append("Accepted and rejected loop outputs had similar point estimates for clinician-rated validity. The wide intervals do not establish enrichment for rationale quality.")
    else:
        pieces.append("Accepted-minus-rejected differences are descriptive selection/enrichment associations, not causal effects; their intervals and small cells limit inference.")
    same_v2 = results["target_subsets"]
    same_v2 = same_v2[(same_v2.stage == "V2") & (same_v2.subset == "exact_same_diagnosis")].iloc[0]
    if same_v2.zero_shot_preferred > same_v2.loop_preferred:
        pieces.append("The V2 zero-shot rationale preference persists when both arms have the same diagnosis target, so target selection alone does not explain it. Q1/Q2 may miss comparative explanation differences.")
    both_valid = results["mutually_valid"].set_index("stage")
    if both_valid.loc["V2"].zero_shot_preferred > both_valid.loc["V2"].loop_preferred:
        row = both_valid.loc["V2"]
        pieces.append(f"Among {int(row.n_pairs)} V2 pairs where both rationales passed Q1/Q2, preferences were "
                      f"{int(row.loop_preferred)} loop, {int(row.zero_shot_preferred)} zero-shot, and "
                      f"{int(row.equal_or_equivalent)} equivalent.")
    both_correct = results["original_reference_strata"]
    both_correct = both_correct[(both_correct.stage == "V2") &
                                (both_correct.subset == "both_match_original_reference")].iloc[0]
    pieces.append(f"In the {both_correct.n_pairs} V2 pairs where both displayed targets match the original mapping candidate, "
                  f"rationale preferences were {both_correct.loop_preferred} loop, "
                  f"{both_correct.zero_shot_preferred} zero-shot, and "
                  f"{both_correct.equal_or_equivalent} equivalent; this small stratum differs from the overall pattern.")
    if v4.equal_or_equivalent >= max(v4.loop_preferred, v4.zero_shot_preferred):
        pieces.append("V4 rationales were often judged equivalent despite variation in clinical-support validity.")
    score = results["score_association"]
    support_score = score[score.outcome == "Q2_yes"].set_index("stage")
    if all(pd.notna(support_score.loc[stage].spearman_rho_binary) and
           abs(support_score.loc[stage].spearman_rho_binary) < .1 for stage in ("V2", "V4")):
        pieces.append("The continuous loop score showed little rank association with this clinician's Q2 judgment "
                      "in either stage; V2 had only two loop Q2!=Yes cases.")
    lengths = results["rationale_length"].set_index(["stage", "arm"])
    v2_loop_words = lengths.loc[("V2", "loop")].median_words
    v2_zero_words = lengths.loc[("V2", "zero_shot")].median_words
    pieces.append(f"Median V2 rationale lengths were {v2_loop_words:g} loop and "
                  f"{v2_zero_words:g} zero-shot words, so a large arm-level length imbalance is not apparent.")
    pieces.append("These ratings do not establish step-level logical validity or faithfulness to model reasoning.")
    return " ".join(pieces)


def preliminary_report(results: dict[str, pd.DataFrame], *, rater_id: str,
                       bootstrap_replicates: int, seed: int) -> str:
    aggregate = results["aggregate"]
    conditions = results["conditional_preference"]
    q2 = conditions[conditions.basis == "Q2"]
    valid = conditions[conditions.basis == "composite_valid"]
    composite_note = ("Composite-validity groups match Q2 groups exactly because every Q1 rating was Yes."
                      if q2[["stage", "condition", "n_pairs", "loop_preferred", "zero_shot_preferred", "equal_or_equivalent"]].reset_index(drop=True).equals(
                          valid[["stage", "condition", "n_pairs", "loop_preferred", "zero_shot_preferred", "equal_or_equivalent"]].reset_index(drop=True))
                      else "Composite-validity groups differ from Q2 groups; both are shown below.")
    comments = results["comments"]
    both_valid_comments = results["both_valid_comments"]
    if comments.empty:
        comments_text = "No non-empty clinician comments were recorded; no qualitative themes can be inferred."
    else:
        explicit_specificity = int(comments.rater_comment.str.contains(
            r"specif|categor|with/without", case=False, regex=True, na=False).sum())
        theme = (f"{explicit_specificity} of {len(comments)} comments explicitly discuss diagnostic or code "
                 "specificity; this is a small, post-hoc qualitative observation, "
                 "not a prevalence estimate. " if explicit_specificity >= 3 else "")
        comments_text = ("All non-empty comments are listed below by decoded preference. "
                         + theme + "Other themes are not coded automatically from free text.\n\n" +
                         _markdown_table(comments.sort_values(["rationale_preference", "stage", "pair_id"])))
    review = results["both_valid_review"]
    examples = (_markdown_table(review.head(5)) if not review.empty else "No preferred pair had both rationales valid.")
    cross = results["target_rationale_crosstab"]
    discordance = []
    for stage in ("V2", "V4"):
        stage_cross = cross[cross.stage == stage]
        def cell(target: str, rationale: str) -> int:
            return int(stage_cross[(stage_cross.target_preference == target) &
                                   (stage_cross.rationale_preference == rationale)].n_pairs.iloc[0])
        discordance.append(f"{stage}: loop target/zero-shot rationale {cell('loop', 'zero_shot')}; "
                           f"zero-shot target/loop rationale {cell('zero_shot', 'loop')}")
    same = results["target_subsets"]
    same_v2 = same[(same.stage == "V2") & (same.subset == "exact_same_diagnosis")].iloc[0]
    same_v4 = same[(same.stage == "V4") & (same.subset == "exact_same_full_icd")].iloc[0]
    same_note = (f"When targets were identical, V2 rationales were preferred loop/zero-shot/equivalent "
                 f"{same_v2.loop_preferred}/{same_v2.zero_shot_preferred}/{same_v2.equal_or_equivalent}; "
                 f"V4 {same_v4.loop_preferred}/{same_v4.zero_shot_preferred}/{same_v4.equal_or_equivalent}.")
    lines = [
        "# Blinded clinician audit: batch 1", "",
        "## Preliminary one-clinician deep-dive", "",
        f"**Preliminary: one clinician completed** ({rater_id}). Exactly 84 pairs across 42 admissions: "
        "42 V2 and 42 V4. The batch is selected/enriched, so results are not prevalence estimates. "
        f"Admission-cluster percentile bootstrap: {bootstrap_replicates:,} replicates; seed {seed}. "
        "Both stages travel together when an admission is resampled. No inter-rater agreement is computed.", "",
        "### Aggregate result", "",
        _markdown_table(aggregate[["stage", "n_pairs", "loop_Q1_yes_n", "zero_shot_Q1_yes_n",
                                   "loop_Q2_yes_n", "zero_shot_Q2_yes_n", "loop_valid_n", "zero_shot_valid_n",
                                   "loop_minus_zero_valid_pp", "valid_ci_low_pp", "valid_ci_high_pp",
                                   "loop_preferred", "zero_shot_preferred", "equal_or_equivalent", "loop_margin_pp",
                                   "rationale_margin_ci_low_pp", "rationale_margin_ci_high_pp"]]), "",
        "Composite validity means Q1=Yes and Q2=Yes. Both differences are loop minus zero-shot in percentage points; "
        "CI columns are 95% admission-bootstrap limits.", "",
        "### Same-target and different-target rationale preference", "",
        "V2 uses exact diagnosis targets. V4 separates identical full ICD codes, different full codes within one ICD3 category, and different ICD3 categories. "
        "Exact same-target comparisons hold the displayed target fixed; they do not control every other difference.", "",
        _markdown_table(results["target_subsets"][["stage", "subset", "n_pairs", "loop_preferred",
                                                   "zero_shot_preferred", "equal_or_equivalent", "loop_margin_pp",
                                                   "loop_Q2_pct", "zero_shot_Q2_pct", "loop_valid_pct", "zero_shot_valid_pct"]]), "",
        same_note, "",
        "### Target preference versus rationale preference", "",
        "Only differing-target pairs were asked for target preference. “Equivalent” is the rationale choice; “equal” is the target choice. "
        "The two off-diagonal cells (loop target/zero-shot rationale and vice versa) separate target appropriateness from explanation preference.", "",
        _markdown_table(results["target_rationale_crosstab"]), "",
        "Cross-arm discordance: " + "; ".join(discordance) + ".", "",
        "### Rationale preference conditional on clinical support", "",
        "Within each stage and Q2 group, counts are loop/zero-shot/equivalent rationale preferences. " + composite_note, "",
        _markdown_table(conditions), "",
        "### Original-reference-stratified subsets", "",
        "The V4 protected cell uses `_v4_code_matched_cell`: both arms match the original 3-character ICD mapping criterion. "
        "Its ICD-specificity strata are descriptive, including small cells. V2 original-reference strata compare normalized displayed diagnoses "
        "with the keyed SentenceTransformer `disease` candidate; semantic near matches are not assumed.", "",
        _markdown_table(results["original_reference_strata"][["stage", "subset", "n_pairs",
                                                         "loop_Q1_pct", "zero_shot_Q1_pct", "loop_Q2_pct",
                                                         "zero_shot_Q2_pct", "loop_valid_pct", "zero_shot_valid_pct",
                                                         "target_asked_n", "target_loop_n", "target_zero_shot_n",
                                                         "target_equal_n", "loop_preferred", "zero_shot_preferred",
                                                         "equal_or_equivalent"]]), "",
        "### Loop-accepted versus loop-rejected", "",
        "Loop-arm judgments only. Difference = accepted minus rejected. 95% percentile intervals resample admissions, "
        "retaining both stages. This measures selection/enrichment, not a causal effect of acceptance.", "",
        _markdown_table(results["accepted_vs_rejected"]), "",
        "### Continuous verifier score versus clinical support", "",
        "Loop-arm score only. Means, medians, and Spearman correlations with a binary human outcome are exploratory; "
        "Q2!=Yes includes No and Unclear. An undefined correlation appears as NA.", "",
        _markdown_table(results["score_association"]), "",
        "### Preference among mutually valid rationales", "",
        "Both arms have Q1=Yes and Q2=Yes. Preference may reflect qualities not captured by this binary validity threshold.", "",
        _markdown_table(results["mutually_valid"]), "",
        "Comments attached to mutually valid pairs:", "",
        _markdown_table(both_valid_comments), "",
        "The full table of preferred, mutually valid pairs is in `audit_batch1_both_valid_preference_review.csv`. "
        "Five rows for manual inspection follow; no reason for preference is inferred from them.", "",
        examples, "",
        "### Comments and examples", "",
        comments_text, "",
        "### Chief-complaint descriptive check", "",
        "Six admissions per complaint; no complaint-specific significance tests.", "",
        _markdown_table(results["chief_complaint"][["stage", "chief_complaint", "n_pairs",
                                                 "loop_valid_pct", "zero_shot_valid_pct", "loop_preferred",
                                                 "zero_shot_preferred", "equal_or_equivalent"]]), "",
        "### Rationale-length check", "",
        "Word counts come from keyed construction metadata. Preferred versus non-preferred rows exclude ties; "
        "equivalent pairs are shown separately. Length differences are descriptive associations.", "",
        _markdown_table(results["rationale_length"]), "",
        _markdown_table(results["length_by_preference"]), "",
        "### Interpretation", "", _interpret(results), "",
        "The decoded one-row-per-pair analysis is in `audit_batch1_preliminary_deepdive.csv`. "
        "These local outputs include patient-derived targets and rationales and must remain private.", "",
    ]
    return "\n".join(lines)


def run_preliminary(*, blinded_path: Path, keyed_path: Path, rater_id: str,
                    annotation_path: Path, output_dir: Path,
                    ground_truth_path: Path | None = None,
                    bootstrap_replicates: int = 10_000, seed: int = 20260917) -> Path:
    """Validate, analyze, then atomically replace only preliminary report files."""
    output_dir = output_dir.resolve()
    sources = [blinded_path.resolve(), keyed_path.resolve(), annotation_path.resolve()]
    if ground_truth_path is not None:
        sources.append(ground_truth_path.resolve())
    _require(not any(output_dir == source or output_dir in source.parents or source in output_dir.parents
                     for source in sources), "Output directory must be separate from raw inputs")
    raw_roots = [Path(__file__).resolve().parents[1] / "data" / name
                 for name in ("source", "annotations", "rebuttal_audit_annotations")]
    _require(not any(root.resolve() == output_dir or root.resolve() in output_dir.parents
                     for root in raw_roots), "Output directory cannot be inside raw data")
    blinded = _read_csv(blinded_path)
    ratings = load_annotation_export(annotation_path, rater_id)
    frame = validate_one_rater(blinded, ratings)
    # The key is intentionally opened only after every blinded rating is complete.
    joined, _ = join_key_after_completion(frame, keyed_path)
    results = analyze_preliminary(joined, bootstrap_replicates=bootstrap_replicates, seed=seed)
    gt_results = gt_mapping = None
    if ground_truth_path is not None:
        from merlin_ddx.rebuttal_gt_concordance import analyze_concordance, prepare_concordance
        gt_frame, gt_mapping = prepare_concordance(
            results["decoded"], ground_truth_path, keyed_path,
            output_dir / "audit_v2_gt_mapping_review.csv")
        gt_results = analyze_concordance(gt_frame, bootstrap_replicates=bootstrap_replicates, seed=seed)
    output_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(output_dir, 0o700)
    with tempfile.TemporaryDirectory(prefix="preliminary-audit-", dir=output_dir) as scratch:
        temp = Path(scratch)
        results["decoded"].to_csv(temp / "audit_batch1_preliminary_deepdive.csv", index=False)
        for name in ("aggregate", "target_subsets", "target_rationale_crosstab", "conditional_preference",
                     "original_reference_strata", "accepted_vs_rejected", "score_association",
                     "mutually_valid", "comments", "both_valid_comments", "chief_complaint",
                     "rationale_length", "length_by_preference"):
            results[name].to_csv(temp / f"audit_batch1_{name}.csv", index=False)
        results["both_valid_review"].to_csv(temp / "audit_batch1_both_valid_preference_review.csv", index=False)
        report = preliminary_report(results, rater_id=rater_id,
                                    bootstrap_replicates=bootstrap_replicates, seed=seed)
        if gt_results is not None:
            from merlin_ddx.rebuttal_gt_concordance import report_section, write_tables
            write_tables(gt_results, gt_mapping, temp)
            report += "\n" + report_section(gt_results, gt_mapping,
                                             bootstrap_replicates=bootstrap_replicates, seed=seed)
        (temp / "audit_batch1_report.md").write_text(report, encoding="utf-8")
        for file in temp.iterdir():
            os.chmod(file, 0o600)
            os.replace(file, output_dir / file.name)
    return output_dir
