# Clinician DDx annotation: pilot and 350-case study

MERLIN-DDx maps each admission to a reference diagnosis from the WikiDoc differential list of its chief complaint. The verifier signals of stages V1–V3 depend on that mapping. To check the references, clinician co-authors confirmed the clinically correct diagnosis for sampled admissions in the annotation interface of this repository. This happened in two rounds:

| | 70-case pilot | 350-case study |
|---|---|---|
| Purpose | First check of the WikiDoc-mapped references against a clinician; first evaluation of model rankings against clinician labels | The same at scale, stratified, with a second and third clinician for agreement |
| Cases | 70 admissions, 10 per chief complaint; 35 train, 35 test | 350 test admissions, 50 per chief complaint, disease-balanced draw (seed 20260711); no pilot case |
| Clinicians with completed records | Clinician 1: 69 of 70 | Clinician 1: 350 · Clinician 2: 236 · Clinician 3: 121 |
| Overlap | — | 316 cases by at least two clinicians, 41 by all three |
| Annotation period | July 2026 | July–August 2026 |
| In the MERLIN-DDx paper | Not reported | §6.5, Appendix A.2, abstract, Limitations |
| Interface view | `train`, `test` | `test (350)` |

A "completed record" is a clinician's record for a case with at least one diagnosis marked. Counts come from the records, not from the cohort size or the number of stored files.

Both the 70-case pilot (train and test splits) and the 350-case study were conducted blinded to MERLIN model predictions and other clinicians' annotations. Discharge information remained available by design. Blinding was procedural rather than technically enforced; the [protocol](protocol.md) distinguishes investigator confirmation from the absence of interaction logs and the historical pilot report's conflicting account.

The third activity in the paper, the blinded audit of generated rationales on 42 further admissions, is documented in [docs/reasoning_audit/](../reasoning_audit/README.md). A 70-case verification view also exists in the code, but it never collected a judgment; see [docs/verification/](../verification/README.md).

![Workflow of the DDx annotation: cohorts, candidate lists and automated references; the annotation interface with the information shown and the instruction to hide model predictions and peer marks; offline analysis of clinician-vs-reference agreement, inter-rater agreement and model evaluation.](../assets/ddx_annotation_workflow.svg)

## Documents

| Document | Content |
|---|---|
| [Protocol](protocol.md) | Task, cohorts, what clinicians saw and were instructed to hide, what was recorded, and which artifacts were not recovered |
| [Walkthrough](annotation_walkthrough.md) | The interface step by step, with screenshots on synthetic cases |
| [Analysis](analysis.md) | Scoring rules, statistics, the analysis code and how to run it |
| [Results](../../results/ddx_annotation/README.md) | Cohort-level results: coverage, selections, agreement with the automated references, inter-rater agreement, model evaluation |

## Headline results (350-case study, final records)

| Measure | Value |
|---|---|
| Clinician 1 agrees with the ICD-derived reference | 77.1% [72.6, 81.4] of 350 cases |
| Clinician 1 agrees with the cosine-similarity reference | 68.0% [63.1, 72.6] |
| Confirmed diagnosis missing from the WikiDoc candidate list (Clinician 1) | 11.4% of cases (recall ceiling 0.886) |
| References disagree; Clinician 1 sides with ICD / cosine / neither | 71 / 39 / 17 of 127 cases |
| Cohen's κ, Clinicians 1 and 2 (candidate level) | 0.913 on 236 cases |
| Exact-set agreement / mean Jaccard, Clinicians 1 and 2 | 89.0% / 0.912 |
| Cohen's κ, Clinicians 1 and 3 / 2 and 3 | 0.740 (122 cases) / 0.855 (41 cases) |
| Fleiss' κ, all three clinicians | 0.811 on 41 cases |
| Clinician 3's selection contained in Clinician 1's | 97 of 121 cases (80.2%); identical in 82 (67.8%); reverse containment in 2 |
| Mean selections per case / multi-label rate | 1.11 / 9.7% · 1.06 / 5.5% · 1.02 / 1.7% (Clinicians 1, 2, 3) |

Brackets are 95% case-bootstrap intervals (2,000 resamples, seed 12345). All values come from the final state of the annotation records and the analysis code in this repository; see [results/ddx_annotation/](../../results/ddx_annotation/README.md) for every number, including the pilot.
