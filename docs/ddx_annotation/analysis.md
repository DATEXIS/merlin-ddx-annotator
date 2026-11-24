# DDx annotation analysis

## Code

| File | Role | Origin |
|---|---|---|
| [`scripts/analyse_annotations.py`](../../scripts/analyse_annotations.py) | Case construction, metrics, statistics and figures; the pilot analysis (one clinician, all / train / test) | Study code, sanitized (see [CHANGES_FROM_STUDY.md](../../CHANGES_FROM_STUDY.md)) |
| [`scripts/analyse_scaleup_annotations.py`](../../scripts/analyse_scaleup_annotations.py) | The 350-case analysis: the metrics above per clinician, pairwise Cohen's κ, Fleiss' κ, an HTML report | Study code, sanitized |
| [`scripts/generate_report.py`](../../scripts/generate_report.py) | HTML helpers used by the scale-up report | Study code, reduced to the helpers |
| [`scripts/sample_blind_annotation.py`](../../scripts/sample_blind_annotation.py) | The sampling of the 350 cases | Study code, sanitized |
| [`scripts/run_ddx_analysis.py`](../../scripts/run_ddx_analysis.py) | Runs the two analyses on a local copy of the annotation store | Added for this release |
| [`scripts/ddx_agreement.py`](../../scripts/ddx_agreement.py) | Coverage, selection counts, exact-set agreement, Jaccard, nesting, and the contingency matrices behind κ | Added for this release: these manuscript statistics were not computed by any archived script |
| [`scripts/ddx_kappa_from_contingency.py`](../../scripts/ddx_kappa_from_contingency.py) | Recomputes the published κ values from the published matrices | Added for this release |

## Scoring rules

These rules are the original code's. This release adds no scoring rule.

- **Unit.** A candidate diagnosis within a case.
  - The case's universe is its WikiDoc candidate list plus any marked added diagnosis.
  - Diagnoses are compared by normalized label, so the same added diagnosis checked by two clinicians counts as one candidate.
- **Positive.** A checked candidate `dN` (label = the *N*-th candidate) or a checked added diagnosis `oN` (label resolved per case).
  - Marks whose added diagnosis no longer exists are ignored: 2 marks in the study.
- **Unchecked.** An unchecked candidate counts as not selected.
  - The interface records no explicit negative, so this is how the original analysis builds its 2 × 2 tables.
- **Clinician vs a reference.** The reference counts as agreeing when it is among the clinician's positives.
  - Computed on cases with at least one positive.
  - ICD-reference agreement additionally needs an ICD reference to exist.
- **Tie-break.** In cases where the two references differ, the clinician backs ICD, cosine, or neither.
- **Recall ceiling.** The share of cases where at least one positive is a WikiDoc candidate.
- **Cohen's κ (inter-rater).** Candidate-level 2 × 2 table, pooled over the cases both clinicians have a record for.
  - For Clinicians 1 and 3 this includes one case where Clinician 3 marked nothing: 122 cases.
  - The original scale-up script computes it with `cohen_kappa_binary`. The published contingency matrices reproduce it exactly.
- **Fleiss' κ.** The same items, over the cases all three clinicians annotated.
- **Set statistics** ([`ddx_agreement.py`](../../scripts/ddx_agreement.py); as defined in the manuscript). Computed on cases both clinicians completed:
  - exact-set agreement: identical positive sets;
  - mean Jaccard: |A ∩ B| / |A ∪ B|;
  - nesting: the second clinician's set contained in the first's, and the reverse.
- **Uncertainty.** Case-level percentile bootstrap, 2,000 resamples, seed 12345.
- **Model evaluation (secondary, not in the manuscript).**
  - Hit@k (k = 1, 3, 5, 10) and MRR of each model's V1–V3 ranking against the clinician's positives.
  - V4 ICD predictions against the coder ICD categories.
  - Paired McNemar and Wilcoxon tests between models.
  - A paired model-vs-ICD-reference comparison, on the pilot test split only and for every clinician of the study.
- **Consensus.** None. Each clinician is analysed separately.

## Running it

On the synthetic data (no credentials):

```bash
uv run python scripts/make_synthetic_ddx_fixture.py --out .demo/ddx_fixture            # 9 demo cases
uv run python scripts/run_ddx_analysis.py pilot --fixture .demo/ddx_fixture --out .demo/ddx_pilot
uv run python scripts/run_ddx_analysis.py study --fixture .demo/ddx_fixture --out .demo/ddx_study
uv run python scripts/ddx_agreement.py --fixture .demo/ddx_fixture --out .demo/ddx_study/agreement.json
uv run python scripts/make_synthetic_ddx_fixture.py --out .demo/ddx_full --full-size    # 70 + 350 random cases
```

`tests/python/test_ddx_analysis_synthetic.py` runs these on the synthetic demo cases and checks every reported value against a hand calculation.

On the study data, the same commands take explicit inputs instead of `--fixture`:

- `--data-root`: a copy of the annotation store (`annotations/`, `custom_diagnoses/`);
- `--pool`: the case pool;
- `--diagnoses`: the WikiDoc candidate schemes;
- for `study` only: `--sample-csv`, `--sample-meta`, `--annotators-json`;
- for `pilot` only: `--cohort`, the pilot case list.

The individual annotation records are internal (see [data access](../data_access.md)), so the study-data run is reproducible by the study team. From the public files alone, κ can be recomputed from the matrices:

```bash
uv run python scripts/ddx_kappa_from_contingency.py
```

## Notes on the pilot run

- **No cohort filter in the original script.** The original pilot script has no cohort filter: it relied on a case pool that held only the pilot admissions. That pool was not recovered.
- **Shared pool.** The available pool also holds the 350-case study. `run_ddx_analysis.py pilot` therefore restricts the records to the pilot cohort (`--cohort`).
- **Coverage.** The available pool contains 62 of the 70 pilot cases, with candidate lists identical to those shown in the interface. Clinician 1 completed 61 of these 62, so the pilot reference-agreement and model-evaluation results cover 61 cases.
- **Counts.** The coverage and selection counts are taken from the records and cover all 69 completed pilot records.
