"""Detailed secondary tables for both completed rebuttal-audit clinicians."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from merlin_ddx.rebuttal_analysis import _markdown_table, _require, _string
from merlin_ddx.rebuttal_gt_concordance import (
    analyze_concordance, prepare_concordance, write_tables as write_gt_tables,
)
from merlin_ddx.rebuttal_preliminary import analyze_preliminary


def analyze_detail(joined: pd.DataFrame, rater_ids: list[str], *, gt_path: Path,
                   keyed_path: Path, mapping_review_path: Path | None,
                   bootstrap_replicates: int, seed: int) -> dict[str, dict[str, Any]]:
    """Reuse the validated single-clinician deep dive for each final rater."""
    _require(len(rater_ids) == 2 and len(set(rater_ids)) == 2,
             "Detailed final analysis needs two distinct raters")
    result = {}
    for rater in rater_ids:
        subset = joined[joined.rater_id == rater].copy()
        _require(len(subset) == 84 and subset.pair_id.nunique() == 84,
                 f"{rater} does not cover all 84 audit pairs")
        preliminary = analyze_preliminary(subset, bootstrap_replicates=bootstrap_replicates, seed=seed)
        concordance_frame, mapping = prepare_concordance(
            preliminary["decoded"], gt_path, keyed_path, mapping_review_path)
        concordance = analyze_concordance(
            concordance_frame, bootstrap_replicates=bootstrap_replicates, seed=seed)
        result[rater] = {"deepdive": preliminary, "concordance": concordance, "mapping": mapping}
    return result


def write_detail(details: dict[str, dict[str, Any]], directory: Path) -> None:
    for rater, tables in details.items():
        destination = directory / "details" / rater
        destination.mkdir(parents=True, exist_ok=True)
        for name, frame in tables["deepdive"].items():
            frame.to_csv(destination / f"{name}.csv", index=False)
        write_gt_tables(tables["concordance"], tables["mapping"], destination)


def _combined(details: dict[str, dict[str, Any]], group: str, name: str) -> pd.DataFrame:
    frames = []
    for rater, tables in details.items():
        frame = tables[group][name].copy()
        frame.insert(0, "rater", rater)
        frames.append(frame)
    return pd.concat(frames, ignore_index=True)


def detail_report(details: dict[str, dict[str, Any]]) -> str:
    """Append the preliminary report's analytical depth without calling it preliminary."""
    names = ", ".join(details)
    deep = lambda name: _combined(details, "deepdive", name)
    gt = lambda name: _combined(details, "concordance", name)
    comments = deep("comments")
    review = deep("both_valid_review")
    examples = pd.concat([group.head(5) for _, group in review.groupby("rater", sort=False)],
                         ignore_index=True) if not review.empty else review
    gt_mapping = next(iter(details.values()))["mapping"]
    _require(all(tables["mapping"][["hadm_id", "model_target"]].equals(
        gt_mapping[["hadm_id", "model_target"]]) for tables in details.values()),
        "Per-rater GT mapping keys disagree")
    lines = [
        "## Detailed final-dataset analyses", "",
        f"The following tables use both completed clinician exports ({names}). Each rater has 42 V2 "
        "and 42 V4 pairs; rows labeled by rater are separate descriptive analyses of the same "
        "admissions, not independent cohorts. The pooled primary estimates and inter-rater agreement "
        "are above. All case-level exports are private under `details/<rater>/`.", "",

        "### Same-target and different-target rationale preference", "",
        "Identical V2 names or V4 full ICD codes hold the displayed target fixed; the V4 "
        "same-ICD3 subset allows different full-code specificity.", "",
        _markdown_table(deep("target_subsets")[["rater", "stage", "subset", "n_pairs",
            "loop_preferred", "zero_shot_preferred", "equal_or_equivalent", "loop_margin_pp",
            "loop_Q2_pct", "zero_shot_Q2_pct", "loop_valid_pct", "zero_shot_valid_pct"]]), "",

        "### Target preference versus rationale preference", "",
        "Target comparison was asked only when A and B differed. Off-diagonal cells separate "
        "the preferred diagnosis from the preferred explanation.", "",
        _markdown_table(deep("target_rationale_crosstab")), "",

        "### Rationale preference conditional on clinical support", "",
        "Q2 and composite-validity groups are both shown. Composite validity requires Q1=Yes "
        "and Q2=Yes; No and Unclear do not count as valid.", "",
        _markdown_table(deep("conditional_preference")), "",

        "### Original-reference-stratified subsets", "",
        "V2 uses exact normalized target matches to the keyed SentenceTransformer `disease` candidate. "
        "The protected V4 cell uses the construction-time ICD3 mapping criterion; its "
        "full-code subgroups may be small.", "",
        _markdown_table(deep("original_reference_strata")[["rater", "stage", "subset", "n_pairs",
            "loop_Q1_pct", "zero_shot_Q1_pct", "loop_Q2_pct", "zero_shot_Q2_pct",
            "loop_valid_pct", "zero_shot_valid_pct", "target_asked_n", "target_loop_n",
            "target_zero_shot_n", "target_equal_n", "loop_preferred", "zero_shot_preferred",
            "equal_or_equivalent"]]), "",

        "### Loop-accepted versus loop-rejected", "",
        "Loop-arm judgments only. These are selection associations, not causal effects. "
        "Intervals resample admissions and retain V2/V4 together.", "",
        _markdown_table(deep("accepted_vs_rejected")), "",

        "### Continuous verifier score versus clinical support", "",
        "Exploratory means, medians and Spearman correlations. Q2!=Yes includes No and Unclear; "
        "a correlation can be undefined if an outcome is constant.", "",
        _markdown_table(deep("score_association")), "",

        "### Preference among mutually valid rationales", "",
        "Both arms passed Q1 and Q2. Preference may still reflect differences that the absolute "
        "questions do not capture.", "",
        _markdown_table(deep("mutually_valid")), "",
        "All comments on mutually valid pairs:", "",
        _markdown_table(deep("both_valid_comments")), "",
        "Five preferred, mutually valid examples per clinician (all cases in "
        "`details/<rater>/both_valid_review.csv`):", "",
        _markdown_table(examples), "",

        "### Clinician comments", "",
        "All nonempty comments follow without automated theme coding; the text and examples are "
        "patient-derived and should remain private.", "",
        _markdown_table(comments), "",

        "### Chief-complaint descriptive check", "",
        "Six admissions per complaint. No complaint-specific significance tests were performed.", "",
        _markdown_table(deep("chief_complaint")[["rater", "stage", "chief_complaint", "n_pairs",
            "loop_valid_pct", "zero_shot_valid_pct", "loop_preferred", "zero_shot_preferred",
            "equal_or_equivalent"]]), "",

        "### Rationale-length check", "",
        "Word counts come from keyed construction metadata. Preference groups are descriptive.", "",
        _markdown_table(deep("rationale_length")), "",
        _markdown_table(deep("length_by_preference")), "",

        "### Full discharge-reference concordance", "",
        "This is separate from the single selected retrospective discharge reference above. "
        "V2 includes the original SentenceTransformer-derived mapping candidate and a literal "
        "discharge-text screen. The mapping candidate is not an independent clinician adjudication. "
        "Human discharge-text equivalence was not reviewed, so no all-empty `discharge_reviewed` "
        "table is shown. AI first-pass mapping notes remain in private CSVs only. "
        "V4 checks every discharge ICD code at full-code "
        "and three-character levels. Retrospective discharge agreement does not determine "
        "admission-time appropriateness.", "",
        _markdown_table(gt("table_B_strata").query("n_pairs > 0")[["rater", "stage", "gt_definition",
            "reference_match_stratum", "n_pairs", "loop_Q2_pct", "zero_shot_Q2_pct",
            "loop_valid_pct", "zero_shot_valid_pct", "target_loop_preferred",
            "target_zero_shot_preferred", "target_equal", "rationale_loop_preferred",
            "rationale_zero_shot_preferred", "rationale_equivalent"]]), "",

        "### Discharge-reference agreement versus Q2 support", "",
        "The table gives Q1/Q2 and composite-validity counts for each arm and reference status. "
        "The literal V2 screen is not a synonym map or an admission-time correctness label.", "",
        _markdown_table(gt("table_A_support").query("n > 0")[["rater", "stage", "gt_definition", "arm",
            "gt_status", "n", "Q1_yes_n", "Q2_yes_n", "Q2_yes_pct", "valid_n", "valid_pct"]]), "",
        "Admission-cluster bootstrap comparison of Q2=Yes rates for reference-matching and "
        "nonmatching targets:", "",
        _markdown_table(gt("support_association")), "",

        "### Discharge-reference agreement versus target and rationale preference", "",
        "These tables include pairs where only one target matches the reference. Target "
        "appropriateness and explanation preference remain distinct judgments; ties are retained.", "",
        _markdown_table(gt("target_preference_concordance")), "",
        _markdown_table(gt("rationale_preference_concordance")), "",
        _markdown_table(gt("triple_concordance")), "",

        "### V4 full-code specificity", "",
        "These cases share ICD3 but differ in full code. A more specific code is not assumed "
        "better without adequate evidence; case-level rows are in "
        "`details/<rater>/audit_v4_specificity_cases.csv`.", "",
        _markdown_table(gt("table_D_specificity")), "",

        "### Discharge-reference/clinician discordances", "",
        "The counts identify cases for inspection, not adjudicated clinical errors. The "
        "private `details/<rater>/audit_gt_clinician_discordant_cases.csv` files contain "
        "targets, rationales and clinician comments.", "",
        _markdown_table(gt("table_C_discordance")), "",
        "The private V2 mapping-review file is retained for future adjudication; its AI notes "
        "are not substituted for a clinician review.", "",
    ]
    return "\n".join(lines)
