# Clinician audit rubric

Recovered verbatim from the clinician interface (`RebuttalAudit` view) and the server-side answer validation that were deployed before the first rating was saved. Nothing here was reworded; the machine-readable version is [`config/rubric.json`](../config/rubric.json).

## Unit of rating

- **rationale**: One generated rationale (target diagnosis or ICD code plus its justification text).
- **pair**: Two rationales for the same admission and stage, shown side by side as Response A and Response B.

## What clinicians saw

- Admission note on the left; V2 pair panel above V4 pair panel on the right.
- Target (V4: ICD code followed by its ICD-10-CM description), then the rationale text, then Q1 and Q2.
- Stages: V2 = diagnosis (differential-diagnosis) stage; V4 = coding (ICD prediction) stage.
- Responses were labelled only "Response A" and "Response B"; arm identity, verifier score and loop outcome were not shown.

## `Q1_evidence_grounded`

- Level: rationale; asked for: every rationale; required: True.
- Stored field(s): `A_Q1`, `B_Q1`.
- V2 wording: "Are the clinical facts stated in this rationale supported by the patient information?"
- V4 wording: "Are the clinical facts stated in this rationale supported by the patient information?"

| Option shown | Stored value | Release value / analysis code |
|---|---|---|
| Yes | `Yes` | 1 |
| No | `No` | 0 |
| Unclear | `Unclear` | 0 |

- Direction: Yes = favourable

## `Q2_supports_target`

- Level: rationale; asked for: every rationale; required: True.
- Stored field(s): `A_Q2`, `B_Q2`.
- V2 wording: "Do the stated facts clinically support this diagnosis as a plausible diagnosis for this patient?"
- V4 wording: "Do the stated facts clinically support this specific ICD diagnosis?"

| Option shown | Stored value | Release value / analysis code |
|---|---|---|
| Yes | `Yes` | 1 |
| No | `No` | 0 |
| Unclear | `Unclear` | 0 |

- Direction: Yes = favourable

## `target_preference`

- Level: pair; asked for: only pairs whose two displayed targets differ (exact string comparison); required: when asked.
- Stored field(s): `target_preference_A_B_equal`.
- V2 wording: "Which diagnosis is more clinically appropriate for this patient at this point in the case?"
- V4 wording: "Which ICD diagnosis is more clinically appropriate for this patient, including whether the level of specificity is justified by the available evidence?"
- V4 helper text: "Prefer a more specific code when the evidence supports it; penalize unsupported over-specificity."

| Option shown | Stored value | Release value / analysis code |
|---|---|---|
| A | `A` | loop or zero_shot (decoded via the allocation key) |
| B | `B` | loop or zero_shot (decoded via the allocation key) |
| Equally appropriate | `Equal` | equal |

- Direction: No ordering; analysis contrasts loop-preferred with zero-shot-preferred shares.
- Not applicable: Identical targets: no question shown; stored as null; released as not_applicable.
- Enabled after: all four Q1/Q2 judgments of the pair

## `rationale_preference`

- Level: pair; asked for: every pair; required: True.
- Stored field(s): `rationale_preference_A_B_equal`.
- V2 wording: "Which rationale is clinically better?"
- V4 wording: "Which rationale is clinically better?"
- V2 helper text: "Consider grounding in the patient record, clinical relevance, whether the reasoning supports its target, and clarity of the justification."
- V4 helper text: "Consider grounding in the patient record, clinical relevance, whether the reasoning supports its target, and clarity of the justification."

| Option shown | Stored value | Release value / analysis code |
|---|---|---|
| A | `A` | loop or zero_shot (decoded via the allocation key) |
| B | `B` | loop or zero_shot (decoded via the allocation key) |
| Equivalent | `Equivalent` | equivalent |

- Direction: No ordering; analysis contrasts loop-preferred with zero-shot-preferred shares.
- Enabled after: all four Q1/Q2 judgments of the pair

## `rater_comment`

- Level: pair; asked for: every pair; required: False.
- Stored field(s): `rater_comment`.
- V2 wording: "Optional comment"
- V4 wording: "Optional comment"
- Release: Not released (unreviewed free text); retained in the internal research archive only.

## Derived: `valid_composite`

- Formula: valid if Q1 == 'Yes' and Q2 == 'Yes'; otherwise not_valid (No and Unclear both count as not valid).
- Missing: missing if Q1 or Q2 is missing.
- Origin: Primary outcome of the original analysis (merlin_ddx/rebuttal_analysis.py).

## Missing, uncertain and not-applicable answers

- **missing**: No answer saved; the original analysis refuses to run with any missing required response.
- **uncertain**: Unclear is a valid response category, never imputed.
- **not applicable**: Target preference for pairs with identical targets.
- **legacy overall preference**: An earlier interface field (preference_A_B_equivalent) is accepted for loading only and never substituted for rationale_preference.

## Aggregation rules

- Ratings are never averaged across categories; per-item distributions keep every original category.
- Q1/Q2 Yes-rates and composite validity rates pool both raters' judgments (denominator = raters x rationales).
- Loop minus zero-shot differences use the same admissions in both arms (paired within admission).
- Preference shares: loop-preferred, zero-shot-preferred and equal/equivalent counts over all judgments.
- In the credentialed per-item aggregates, mean_rating is reported only for valid_composite (share of raters judging the rationale valid).
