# Inter-rater agreement

Agreement between the two clinicians, recomputed from their original ratings with the original definitions: raw percentage agreement and unweighted Cohen's kappa, per stage, on the original response categories. No other agreement measure was used in the study and none is added here.

- Raw agreement p_o = share of items with identical categories from both clinicians.
- Cohen's kappa = (p_o - p_e) / (1 - p_e), where p_e is the sum over categories of the product of the two clinicians' marginal proportions; undefined when p_e = 1. Unweighted (nominal categories).
- Q1, Q2 and the composite: one item = one rationale, both arms of a pair pooled (84 items per stage). Preferences: one item = one pair; target preference only for pairs whose two targets differ.
- Missing data: none observed; an item with a missing rating would be excluded pairwise.
- Confidence intervals: not reported in the original analysis and no interval method was documented, so none is given.

| Stage | Criterion | Items | Categories | p_o | p_e | Cohen's kappa | Matrix |
|---|---|---|---|---|---|---|---|
| V2 | `Q1_evidence_grounded` | 84 | Yes, No, Unclear | 0.940 | 0.940 | 0.000 | full |
| V2 | `Q2_supports_target` | 84 | Yes, No, Unclear | 0.929 | 0.909 | 0.215 | full |
| V2 | `valid_composite` | 84 | valid, not_valid | 0.869 | 0.854 | 0.105 | full |
| V2 | `target_preference` | 13 | loop, zero_shot, equal | 0.385 | 0.314 | 0.103 | reduced |
| V2 | `rationale_preference` | 42 | loop, zero_shot, equivalent | 0.500 | 0.336 | 0.247 | full |
| V4 | `Q1_evidence_grounded` | 84 | Yes, No, Unclear | 0.929 | 0.929 | 0.000 | full |
| V4 | `Q2_supports_target` | 84 | Yes, No, Unclear | 0.726 | 0.541 | 0.404 | reduced |
| V4 | `valid_composite` | 84 | valid, not_valid | 0.726 | 0.552 | 0.389 | full |
| V4 | `target_preference` | 28 | loop, zero_shot, equal | 0.464 | 0.255 | 0.281 | full |
| V4 | `rationale_preference` | 42 | loop, zero_shot, equivalent | 0.524 | 0.292 | 0.327 | reduced |

## Contingency matrices and disclosure review

`agreement_contingency_matrices.csv` gives, per measure, either the **full** joint distribution of the two clinicians' categories with both marginals, or a **reduced** form: concordant counts per category and disagreement totals per unordered category pair. Kappa for every full matrix can be recomputed with `scripts/kappa_from_contingency.py`.

Rule. The PhysioNet per-item aggregates tell a credentialed user, for every item, which two categories the clinicians gave, but not who gave which. A full matrix is published when (a) the published kappa together with those aggregates already determines it up to swapping the two rater labels, or (b) it attributes no disagreement to one clinician. Otherwise only the reduced form is published. The labels `rater_A` and `rater_B` are assigned independently for every matrix with an unpublished seed; they do not denote the same clinician across matrices. Kappa is symmetric, so this does not change any value.

Publication decision. All kappa values are published at full precision. The investigators reviewed a reconstruction analysis showing that, for some measures (V2 Q1, V4 Q1, V4 target preference and, through Q1, some items of both composites), the published kappa together with the credentialed per-item aggregates assigns that measure's disagreements to one of the two anonymous clinicians. They accepted this residual risk for publication. Nothing released links an anonymous rater label to a named clinician or links labels across measures or stages.

| Measure | Disagreements | Kappa-consistent orientations | Decision | Reason |
|---|---|---|---|---|
| `V2.Q1_evidence_grounded` | 5 | 1 | full | matrix is determined (up to label swap) by the published kappa and the credentialed per-item aggregates |
| `V2.Q2_supports_target` | 6 | 1 | full | matrix is determined (up to label swap) by the published kappa and the credentialed per-item aggregates |
| `V2.valid_composite` | 11 | 1 | full | matrix is determined (up to label swap) by the published kappa and the credentialed per-item aggregates |
| `V2.target_preference` | 8 | 2 | reduced | full matrix would attribute disagreements to one rater beyond what kappa implies |
| `V2.rationale_preference` | 21 | 29 | full | no disagreement is attributable to a single rater |
| `V4.Q1_evidence_grounded` | 6 | 1 | full | matrix is determined (up to label swap) by the published kappa and the credentialed per-item aggregates |
| `V4.Q2_supports_target` | 23 | 6 | reduced | full matrix would attribute disagreements to one rater beyond what kappa implies |
| `V4.valid_composite` | 23 | 1 | full | matrix is determined (up to label swap) by the published kappa and the credentialed per-item aggregates |
| `V4.target_preference` | 15 | 1 | full | matrix is determined (up to label swap) by the published kappa and the credentialed per-item aggregates |
| `V4.rationale_preference` | 20 | 3 | reduced | full matrix would attribute disagreements to one rater beyond what kappa implies |

## Reproduction

- Recomputed from the clinician ratings and compared with the original analysis output: 30 of 30 values (items, raw agreement, kappa) identical.
- Every published kappa is reproduced from its full matrix, or from p_o and p_e for reduced measures, by an independent implementation (`scripts/kappa_from_contingency.py`).
- Manuscript ("Agreement on the coding-stage composite was 0.73 (κ = 0.39); diagnosis-stage κ is deflated by the ceiling."): PASS.
- The diagnosis-stage composite is near ceiling (about 92% valid), so kappa is low despite high raw agreement: the prevalence effect the manuscript refers to.
