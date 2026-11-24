# Synthetic demo: expected analysis output

**Synthetic ratings by two synthetic raters on five synthetic admissions.** These numbers show how the study aggregated ratings; they are not study results.

## V2 (5 pairs, 10 rater-pair judgments)

| Arm | Q1 Yes % | Q2 Yes % | Valid % | Q1 Yes/No/Unclear | Q2 Yes/No/Unclear |
|---|---|---|---|---|---|
| loop | 60.0 | 70.0 | 60.0 | 6/4/0 | 7/2/1 |
| zero_shot | 40.0 | 40.0 | 40.0 | 4/6/0 | 4/5/1 |

Loop minus zero-shot validity: 20.0 pp.

| Preference | Loop | Zero-shot | Tie | Not applicable |
|---|---|---|---|---|
| target_preference | 6 | 2 | 0 | 2 |
| rationale_preference | 6 | 4 | 0 | 0 |

| Agreement | Items | Raw agreement | Cohen's kappa |
|---|---|---|---|
| Q1 | 10 | 1.0 | 1.0 |
| Q2 | 10 | 0.8 | 0.6552 |
| valid | 10 | 1.0 | 1.0 |
| rationale_preference | 5 | 1.0 | 1.0 |
| target_preference | 4 | 1.0 | 1.0 |

## V4 (5 pairs, 10 rater-pair judgments)

| Arm | Q1 Yes % | Q2 Yes % | Valid % | Q1 Yes/No/Unclear | Q2 Yes/No/Unclear |
|---|---|---|---|---|---|
| loop | 60.0 | 50.0 | 50.0 | 6/4/0 | 5/3/2 |
| zero_shot | 80.0 | 80.0 | 60.0 | 8/1/1 | 8/2/0 |

Loop minus zero-shot validity: -10.0 pp.

| Preference | Loop | Zero-shot | Tie | Not applicable |
|---|---|---|---|---|
| target_preference | 4 | 2 | 2 | 2 |
| rationale_preference | 5 | 4 | 1 | 0 |

| Agreement | Items | Raw agreement | Cohen's kappa |
|---|---|---|---|
| Q1 | 10 | 0.9 | 0.7778 |
| Q2 | 10 | 0.8 | 0.6154 |
| valid | 10 | 0.9 | 0.8 |
| rationale_preference | 5 | 0.8 | 0.6667 |
| target_preference | 4 | 0.5 | 0.3333 |
