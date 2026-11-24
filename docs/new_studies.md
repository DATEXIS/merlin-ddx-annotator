# New-study baseline (v1.2.0)

This release separates the historical reproducibility artifact from new-study
infrastructure. The existing study rubrics are retained. The new V1–V4 rubric
questions are proposals, not clinically validated instruments. Configurable
criterion profiles are intentionally out of scope.

## Build a study

Install dependencies and build the UI as in the main README. All builders
operate locally on authorized data. Use a private, fresh output directory
outside this repository. The recommended entry point accepts JSON
configuration and freezes the served inputs and private allocation key.

| study_type | builder | Required configuration keys (in addition to study_type) |
|---|---|---|
| paired_reasoning | build_annotation_cases.py | left_path, right_path, left_model, right_model, stages, split |
| single_reasoning | build_single_reasoning_cases.py | path, model, stages, split |
| reference_label | build_reference_cases.py | path, stages, split (model for raw Parquet) |
| label_comparison | build_label_comparison_cases.py | generated_path, reference_path, model, stages, split |
| ddx | build_ddx_cases.py | path, schemes |

Common optional fields: seed, n, raters. Other builder-specific options are
documented in the individual guides or CLI help. The rubric_version is
baseline-v1.2; experimental criteria are not accepted.

Example local config for standalone reasoning (replace placeholders):

```json
{
  "study_type": "single_reasoning",
  "path": "/authorized/data/combined.pq",
  "model": "Qwen3-32B",
  "stages": ["V1", "V2", "V3", "V4"],
  "split": "test",
  "seed": 42,
  "n": 20,
  "raters": 2,
  "rubric_version": "baseline-v1.2"
}
```

```bash
uv run python scripts/build_study.py --config /authorized/config.json \
  --out /authorized/studies/study01
uv run python scripts/build_study.py --verify --out /authorized/studies/study01
```

Standalone reasoning reviews one raw generated output and its rationale using
the same Q1/Q2 as the paired generated-reasoning mode, without a comparator or
preference. Both generated and reference inputs retain their provenance.
The manifest captures selection settings, source digests, fixed rubric version,
served input hashes and the private allocation-key hash. Verification detects
changes relative to that local manifest; it is not a cryptographic signature
against a malicious administrator. The builders can also be called directly.

### DDx case import

The new DDx importer reads the raw MERLIN Parquet admission pool and the
upstream diagnosis-scheme CSV directory (one file per chief complaint, with
a Disease column). It deduplicates admissions only when evidence agrees,
randomizes candidate order, and deliberately omits model rankings, similarity
scores, reference labels and ICD-derived candidate ranks. The default is
retrospective review with admission, laboratory and discharge documentation;
set retrospective=false for admission-only review. The historical candidate
selection UI and custom diagnosis functionality are reused. No positive
selection is treated as incomplete, consistent with the historical UI;
an intentional empty set cannot yet be distinguished.

## Independent local annotation

A new study can be separated into per-rater workspaces before annotation:

```bash
uv run python scripts/independent_workspaces.py prepare \
  --study /authorized/studies/study01 \
  --workspaces /authorized/workspaces/study01
```

Each workspace contains only the assigned rater, the same case input, and
no allocation key or peer ratings. Give each rater access only to their own
workspace (separate authorized OS account or controlled machine). Do not
share the master directory. Launch the interface for that workspace on
loopback, using its actual generated rater directory name:

```bash
uv run python scripts/run_demo.py \
  --data-root /authorized/workspaces/study01/RATER_DIRECTORY
```

The backend restricts annotation endpoints to that workspace's rater,
disables model/peer overlay and sync endpoints, and requires Git sync to
remain off. Custom diagnoses are local to that rater. This is physical
data isolation with server-side route restrictions, NOT authentication
for a shared remote deployment. Separate OS/browser accounts and filesystem
permissions remain necessary. Do not expose these local servers publicly.
The trusted legacy demo mode is unchanged.

After all raters save their answers and the servers are stopped, collect once:

```bash
uv run python scripts/independent_workspaces.py collect \
  --study /authorized/studies/study01 \
  --workspaces /authorized/workspaces/study01
```

Collection checks workspace identity, exact case inputs, rating schemas, and
refuses to overwrite existing master ratings. DDx custom labels are merged
by normalized text, not the independently allocated o1/o2 identifiers.
This is an offline collection step; stop annotation before running it.

## Export and analyze

```bash
uv run python scripts/export_annotations.py \
  --study /authorized/studies/study01 \
  --out /authorized/studies/study01/private_export
uv run python scripts/analyze_annotation_study.py \
  --export /authorized/studies/study01/private_export \
  --out /authorized/studies/study01/private_analysis/summary.json
uv run python scripts/analyze_interrater_agreement.py \
  --study /authorized/studies/study01 \
  --out /authorized/studies/study01/private_analysis/agreement.json
```

The general exporter distinguishes paired reasoning, standalone reasoning,
reference review, blinded label comparison and DDx selections. Individual
ratings remain local. DDx export includes fixed-candidate vote counts,
completion and the number of selected custom labels, not their free text.
DDx summary describes coverage and selection cardinality, not diagnostic
accuracy against an external reference. The original DDx analysis remains
available for reproduction of the historical study.

Agreement analysis uses pairwise Cohen's kappa with the observed and expected
agreement, contingency counts, and complete shared item denominators, grouped
by stage and rubric field. Undefined kappas are null. For DDx, fixed candidate
decisions form the kappa universe, while exact-set agreement and Jaccard include
normalized custom selections. Do not compare these kappas directly with the
historical study's distinct definitions. The `multi_rater_agreement` section adds Fleiss' kappa and nominal Krippendorff's alpha for each stage/rubric field (or the fixed DDx candidate universe). Fleiss' kappa uses only items rated by every configured active rater (at least two); nominal alpha uses all items with at least two judgments and accounts for varying rater counts through the coincidence weighting and finite-population expected disagreement. `Unclear` remains an observed nominal category, not a missing value. Empty/missing answers are omitted; structurally inapplicable preferences are excluded from the expected item denominator. Each report includes eligible/excluded item counts, the rating-count histogram, observed/expected agreement or disagreement, and pooled category counts. Undefined coefficients (including zero expected disagreement) are null, not 0 or 1. DDx candidate decisions from uncompleted admissions remain missing. The complete-case and pairable-item populations may differ, so report their denominators alongside the coefficients. These are descriptive point estimates; cluster-adjusted inference and missingness correction are not included. All summaries remain
local until disclosure review; even aggregate contingency cells can reveal
individual ratings when combined with other releases.

The analysis/export scripts do not enforce remote authentication or clinical
validity. No new rubric methodology, automated adjudication, model inference,
or GPU workloads are introduced.
