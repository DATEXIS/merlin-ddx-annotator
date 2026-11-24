# Reproducibility guide

Two workflows: a public one that needs nothing but this repository, and a credentialed one that uses the MERLIN-DDx data on PhysioNet. Neither reruns models or creates new study ratings.

## Coverage: which result can be reproduced from which data

Four levels of data exist:

- **Public results:** the cohort-level counts and estimates in `results/`.
- **Public matrices:** the rater contingency matrices in `results/agreement_contingency_matrices.csv`.
- **Credentialed aggregates:** the per-item aggregate ratings in the PhysioNet release, with its case mapping. They give both clinicians' categories for each item, but not which clinician gave which.
- **Individual ratings:** each clinician's own ratings, kept in the research group's internal archive and not released.

For each analysis, the table gives the least data that reproduces the point estimate and its uncertainty independently, that is, from released observations rather than by reading off a published number.

| Analysis (where reported) | Point estimate | Uncertainty (95% interval) |
|---|---|---|
| Validity, Q1 = Yes and Q2 = Yes rates by stage and arm (App. B, §6.5) | Public results (counts) | Credentialed aggregates, exactly |
| Loop minus zero-shot validity difference (App. B, Limitations) | Public results | Credentialed aggregates, exactly |
| Loop minus zero-shot Q1 and Q2 differences (results only) | Public results | Credentialed aggregates, exactly |
| Target and rationale preference shares and margins (results only) | Public results | Credentialed aggregates, exactly |
| Exact sign test on rationale preferences (results only) | Public results | not applicable |
| Loop accepted / rejected pairs (App. B) | Public results | not applicable |
| Raw agreement p_o, all 10 measures (App. B: coding-stage composite 0.73) | Public matrices: full matrices, or concordant counts for reduced ones. Also credentialed aggregates. | None was reported |
| Cohen's κ, the 7 measures released with full matrices (App. B: coding-stage composite 0.39) | Public matrices | None was reported |
| Cohen's κ, the 3 measures released in reduced form (V2 target preference, V4 Q2, V4 rationale preference) | Individual ratings only. Public: the published κ is arithmetically consistent with the published p_o and p_e, but p_e cannot be re-derived | None was reported |
| Accepted minus rejected validity, per clinician and stage (App. B: range −10.9 to +5.9) | Individual ratings only (the published range is the reported result) | Individual ratings only (published: all intervals include 0) |
| Verifier score vs Q2 = Yes, Spearman ρ per clinician and stage (App. B, Limitations: range −0.12 to +0.07) | Individual ratings only (published range) | None was reported |
| Sensitivity analysis excluding Unclear judgments per clinician (not in the paper) | Individual ratings only | Individual ratings only |

What this means:

- **Credentialed aggregates:** they reproduce every pooled rate, difference and preference statistic of the audit, with its interval, and raw agreement. They do **not** reproduce Cohen's κ. κ needs each clinician's own category distribution, which aggregates do not contain; the public contingency matrices supply it for 7 of the 10 measures.
- **Per-clinician analyses:** these need the individual ratings. The paper reports them only as ranges, and the ranges are published here. They can be checked only by the study team.
- **Ordering for exact intervals:** all intervals are admission-cluster percentile bootstrap intervals: 10,000 replicates, seed 20260917, `numpy.random.default_rng(seed).multinomial(n, [1/n]*n, size=10000)` over admissions sorted by their MIMIC-IV `hadm_id`. Both arms and both clinicians of an admission are resampled together. The credentialed case mapping restores that order. Without it, intervals agree only up to Monte Carlo error.

## Public workflow (no credentials)

```bash
uv sync --extra analysis --extra dev && npm ci && npm run build

# Recompute Cohen's kappa from the published contingency matrices
uv run python scripts/kappa_from_contingency.py

# Run the interface on the synthetic cases and aggregate your own ratings
uv run python scripts/run_demo.py
uv run python scripts/demo_summary.py --ratings .demo/data_root/rebuttal_audit_annotations

# Run the ORIGINAL analysis pipeline on a full-size synthetic study
uv run python scripts/make_synthetic_analysis_fixture.py --out .demo/fixture
uv run python scripts/run_original_analysis.py --blinded .demo/fixture/audit_batch1_blinded.csv \
  --keyed .demo/fixture/audit_batch1_keyed.csv \
  --rater r1=.demo/fixture/exports/synthetic_rater_1 --rater r2=.demo/fixture/exports/synthetic_rater_2 \
  --out .demo/run
```

The original analysis (`merlin_ddx/rebuttal_analysis.py`) refuses any dataset that is not shaped like the study: 42 admissions, 7 complaints × 6, 84 pairs, two complete raters. So the five hand-written demo cases are summarized by `scripts/demo_summary.py`, using the study's agreement function, and `make_synthetic_analysis_fixture.py` creates a placeholder dataset of the full shape for the original pipeline. On that synthetic dataset, `tests/python/test_credentialed_reproduction.py` shows that per-item aggregates reproduce the pipeline's rates, differences, preference margins, intervals and raw agreement exactly, and nothing about κ.

`scripts/run_original_analysis.py` calls the study's `run_pipeline` unchanged. The study's own entry point, `scripts/analyze_rebuttal_audit.py`, is included as it was used. It additionally requires private discharge-reference inputs for secondary concordance tables that are not part of the paper.

## Credentialed workflow (PhysioNet)

1. Obtain credentialed access to the MERLIN-DDx datasets on PhysioNet and sign the data use agreement ([data access](data_access.md)).
2. Keep the files outside this repository, or in the git-ignored `physionet/` folder.

**Reproduce the cohort-level results** and compare them with `results/`:

```bash
uv run python scripts/reproduce_from_credentialed.py \
  --per-item physionet/per_item_aggregate_ratings.csv \
  --case-mapping physionet/case_mapping.csv \
  --compare results
```

**Review or re-rate the study cases in the interface.** The PhysioNet release includes the exact files the rating server read (`annotation_inputs/`): the blinded pairs and the admission notes as shown, byte-identical, and the public ICD-10-CM catalog. Copy that folder to a writable location covered by your data use agreement, then:

```bash
uv run python scripts/run_demo.py --data-root /path/to/your/copy/of/annotation_inputs
```

This shows the 42 admissions exactly as the clinicians saw them, under generic reassessment annotator names. New answers are stored inside that copy; keep them under the data use agreement. Which response is loop or zero-shot is not in these files, as in the study. It is given per item in `rationale_records.csv`, so keep that file out of view while re-rating. The admission notes are also byte-identical to the `admission_note` of the same admission in the MERLIN-DDx source table.

## What was verified for this release

- **Original run:** all 222 values recomputed from the original clinician ratings are identical to the study's final analysis run (rates, intervals, differences, preferences, agreement, per-clinician details).
- **κ:** every κ published with a full matrix is reproduced from it, including the paper's coding-stage 0.73 / κ 0.39. The 3 reduced measures are consistent with their published p_o and p_e.
- **Credentialed aggregates:** every pooled rate, difference, preference margin, interval and raw agreement is reproduced exactly.
- **Rubric:** `config/rubric.json` and `docs/rubric.md` are tested against the interface and the server (`tests/python/test_rubric_consistency.py`).
- **Study code:** the audit interface and backend are the code that served the clinicians. The frontend sources rebuild the deployed bundle byte for byte, and the backend files equal those in the deployment. The release differs only as listed in [CHANGES_FROM_STUDY.md](../CHANGES_FROM_STUDY.md).

## Regenerating figures

```bash
npm run build && CAPTURE_SCREENSHOTS=1 PYTHON=.venv/bin/python npx playwright test tests/e2e/screenshots.spec.ts
npx -p @mermaid-js/mermaid-cli mmdc -i docs/assets/evaluation_workflow.mmd -o docs/assets/evaluation_workflow.svg -b white
```
