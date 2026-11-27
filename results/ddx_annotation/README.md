# DDx annotation results (pilot and 350-case study)

These are cohort-level results of the clinician DDx annotation. They contain no case, candidate or item-level values. They come from the final state of the annotation records, analysed with the code in this repository ([docs/ddx_annotation/analysis.md](../../docs/ddx_annotation/analysis.md)). Clinicians are numbered as in the manuscript. The numbering is unrelated to the rater labels of the reasoning audit.

## Files

| File | Content |
|---|---|
| `coverage.csv` | Completed records per cohort and clinician, in total and per chief complaint |
| `selections.csv` | Positive selections: total, from the candidate list, added diagnoses, mean per case, multi-label records |
| `reference_agreement.csv` | Agreement with the ICD-derived and cosine references with 95% bootstrap intervals, the tie-break where the references differ, recall ceiling |
| `recall_ceiling_by_chief_complaint.csv` | Recall ceiling per chief complaint |
| `inter_rater_agreement.csv` | 350-case study: pairwise Cohen's κ with p_o and p_e, exact-set agreement, mean Jaccard, nesting; Fleiss' κ |
| `agreement_contingency_matrices.csv` | Candidate-level 2 × 2 tables behind each pairwise κ (`python scripts/ddx_kappa_from_contingency.py` recomputes κ) |
| `model_evaluation/*.csv` | Secondary outputs of the original analysis: Hit@k and MRR of the model rankings and of the two reference rankings against each clinician, κ of the models and references against the clinician, paired model tests, model vs ICD reference. Not reported in the manuscript |
| `manifest.json` | Provenance, coverage, notes and file checksums |

## 350-case study

| | Clinician 1 | Clinician 2 | Clinician 3 |
|---|---|---|---|
| Completed records | 350 | 236 | 121 |
| Chief complaints | all seven, 50 each | abdominal pain 49, back pain 49, chest pain 49, cough 50, diarrhea 39 | dyspnea 50, diarrhea 49, headache 20, abdominal pain 1, cough 1 |
| Positive selections (candidate list + added) | 387 (338 + 49) | 250 (224 + 26) | 123 (92 + 31) |
| Mean selections per case; multi-label records | 1.11; 34 (9.7%) | 1.06; 13 (5.5%) | 1.02; 2 (1.7%) |
| Agrees with the ICD-derived reference | 77.1% [72.6, 81.4] | 75.8% [70.8, 80.9] | 71.9% [63.6, 80.2] |
| Agrees with the cosine reference | 68.0% [63.1, 72.6] | 66.1% [60.2, 72.0] | 57.9% [48.8, 66.9] |
| References disagree: backs ICD / cosine / neither | 71 / 39 / 17 of 127 | 50 / 27 / 15 of 92 | 18 / 1 / 13 of 32 |
| Recall ceiling of the candidate list | 0.886 | 0.907 | 0.754 |

- **Coverage.** 316 of the 350 cases have completed records from at least two clinicians, and 41 from all three.
- **Clinician 3's cases.** Clinician 3 has one further record (122 in total) without a positive mark. The analysis counts it in the case totals of the reference comparison and the κ pairs. Agreement rates use the 121 cases with a positive mark.
- **Intervals.** Brackets are 95% case-bootstrap intervals (2,000 resamples, seed 12345).

| Pair | Cohen's κ (cases) | Exact-set agreement | Mean Jaccard | Second ⊆ first (identical) | First ⊊ second |
|---|---|---|---|---|---|
| Clinicians 1 and 2 | 0.913 (236) | 89.0% (210 of 236) | 0.912 | 216 (210) | 4 |
| Clinicians 1 and 3 | 0.740 (122) | 67.8% (82 of 121) | 0.748 | 97 (82) | 2 |
| Clinicians 2 and 3 | 0.855 (41) | 82.9% (34 of 41) | 0.854 | 36 (34) | 0 |

**Fleiss' κ.** Over the 41 cases annotated by all three clinicians, Fleiss' κ is 0.811.

**Unit.** κ is computed on candidate diagnoses, pooled over cases. An unchecked candidate counts as not selected.

**Contingency matrices.** The matrices are published in full. They hold aggregate counts over thousands of candidates. No item-level DDx data is released anywhere, and every off-diagonal cell is non-zero, so the matrices cannot attribute a disagreement to a clinician.

## Pilot (Clinician 1)

- **Completed records.** 69 of 70 cases: 69 selections, 66 from the candidate list and 3 added; no multi-label record.
- **Analysable cases.** The analysis covers the 61 completed cases present in the available case pool. The pool used by the original pilot analysis was not recovered.

| Subset | Cases | Agrees with ICD reference | Agrees with cosine reference | References disagree: backs ICD / cosine / neither | Recall ceiling |
|---|---|---|---|---|---|
| All | 61 | 86.9% [78.7, 95.1] | 80.3% [68.9, 90.2] | 8 / 4 / 3 of 15 | 1.000 |
| Train | 30 | 90.0% [80.0, 100.0] | 86.7% [73.3, 96.7] | 3 / 2 / 0 of 5 | 1.000 |
| Test | 31 | 83.9% [71.0, 96.8] | 74.2% [58.1, 87.2] | 5 / 2 / 3 of 10 | 1.000 |

**Reporting by split.** The pilot splits are reported separately, as in the original analysis. The historical analysis code describes the two splits as annotated under different information regimes; the investigators report that both pilot splits were conducted blinded to model predictions and other clinicians' annotations. The conflicting historical account is retained for provenance. See [the protocol](../../docs/ddx_annotation/protocol.md), section 4.

**Not in the manuscript.** The pilot results are not reported in the manuscript.

## Interpretation limits

- **Purpose.** The clinician labels confirm the reference diagnoses retrospectively, with the discharge summary available by design. They are not admission-time diagnoses.
- **Blinding (both DDx cohorts).** Clinicians conducted both pilot splits and the 350-case study blinded to model predictions and other clinicians' marks. This is investigator-confirmed procedural blinding, not technically enforced masking: the interface showed both by default, did not enforce hiding and kept no interaction log, so actual display states cannot be independently verified from the records. The conflicting historical pilot report is separately documented.
- **Order of annotation.** Clinician 1's records preceded the other clinicians' in nearly all shared cases.
- **Model evaluation.** The model-evaluation tables measure agreement with these labels. They are secondary and not reported in the manuscript.
