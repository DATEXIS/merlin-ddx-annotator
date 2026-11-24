# Published clinician-audit results

Cohort-level results of the MERLIN-DDx blinded clinician audit (42 admissions, 84 pairs, 168 rationales, 2 clinicians, 922 rating observations, 0 missing). Every value was recomputed from the original clinician ratings and checked against the original analysis run. No item-level or per-clinician observation is included.

| File | Content |
|---|---|
| `cohort_aggregate_ratings.csv` | Category counts and favourable rates (95% CI) by stage, arm and criterion; preference distributions |
| `comparative_results.csv` | Loop minus zero-shot differences and preference margins (95% CI), sign tests, loop outcome counts, per-clinician ranges as reported |
| `agreement_contingency_matrices.csv` | Rater contingency matrices: 7 full, 3 reduced after disclosure review |
| `agreement_statistics.json`, `.md` | p_o, p_e and Cohen's kappa for each measure, with definitions |
| `manifest.json` | Checksums, provenance, reproduction and disclosure-review results |

## Headline results

| Stage | Valid, loop | Valid, zero-shot | Loop minus zero-shot (pp, 95% CI) |
|---|---|---|---|
| V2 | 91.7% | 92.9% | -1.2 [-8.3, 7.1] |
| V4 | 65.5% | 66.7% | -1.2 [-16.7, 14.3] |

Valid = Q1 (facts supported) = Yes and Q2 (facts support the target) = Yes; Unclear counts as not valid. Rates pool both clinicians (84 judgments per stage and arm). Intervals: admission-cluster percentile bootstrap, 10,000 replicates, seed 20260917.

## What can be reproduced from what

| Data | Reproducible statistics |
|---|---|
| Public cohort-level results alone | Point estimates of every rate, loop minus zero-shot difference, preference share and margin, sign test and loop outcome count, recomputed from the published counts. Their 95% intervals are published but cannot be re-derived without item-level data. |
| Public contingency matrices | Raw agreement and Cohen's kappa for the measures published at the `full` level, from the joint counts. For `reduced` measures only raw agreement can be rebuilt; their kappa can be checked arithmetically against the published p_e, which itself cannot be re-derived. No interval was reported for any agreement statistic. |
| Credentialed per-item aggregates (PhysioNet), alone or with the public files | Every point estimate above and its admission-cluster bootstrap interval, exactly (with the case mapping), and raw agreement for every measure. Per-item aggregates do not say which clinician gave which rating, so they add nothing to Cohen's kappa: kappa comes only from the public matrices (full measures). |
| Individual clinician ratings (internal archive only; not released) | Independent reproduction of kappa for `reduced` measures; per-clinician accepted-minus-rejected differences with intervals and per-clinician verifier-score correlations (the paper reports both only as ranges, which are published); per-clinician differences; the sensitivity analysis excluding a clinician's paired judgment when either arm was Unclear. |

## Manuscript consistency

13 of 16 audit claims in the paper reproduce; 1 is discrepant, 1 cannot be verified from the surviving artifacts and 1 needs manual review. See [`docs/protocol.md`](../docs/protocol.md), section 9.

| Claim | Location | Status |
|---|---|---|
| n_admissions | Appendix B | PASS |
| generator | Appendix B | UNVERIFIED |
| dev_split | Appendix B | FAIL |
| blinding | Appendix B | PASS |
| within_admission_pairing | Appendix B | PASS |
| sampling_counts | Appendix B | PASS |
| criteria_and_preregistration | Appendix B | MANUAL_REVIEW |
| primary_contrast | Appendix B | PASS |
| accepted_vs_rejected_and_score | Appendix B | PASS |
| absolute_levels | Appendix B | PASS |
| agreement | Appendix B | PASS |
| stage_scope | Appendix B | PASS |
| section6_levels | Section 6 | PASS |
| limitations_contrast | Limitations | PASS |
| limitations_icd_support | Limitations | PASS |
| release_statement | Appendix B | PASS |
