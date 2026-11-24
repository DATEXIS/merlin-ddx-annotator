# Blinded generated-versus-reference label comparisons

The third annotation workflow compares generated and reference labels using the
same questions and patient evidence for both arms. It is distinct from paired
rationale evaluation and standalone reference review. It does not assume either
source is correct and does not show generated rationales, model identities,
verifier scores, reference source names, or the allocation key.

## Comparison units

| Stage | Generated label | Reference label | Common unit |
|---|---|---|---|
| V1 | Raw manifestation values | Disease prototype or explicit patient-level annotation | Named manifestation mapping |
| V2 | First entry of raw diagnosis ranking | Mapped or independently supplied diagnosis | One diagnosis |
| V3 | First entry of raw reranked diagnosis list | Mapped or independently supplied diagnosis | One diagnosis with lab evidence |
| V4 | Raw predicted ICD codes | Recorded or independently supplied ICD codes | Unordered full-code set |

V1 requires the same manifestation keys in both arms; rationale fields are
removed. The disease-level prototype is not patient-specific extraction ground
truth. V2/V3 compare top-1 labels only, not ranking quality. V4 removes dots,
uppercases and deduplicates codes in both sources without truncating specificity.
An empty predicted ICD set remains empty, rather than being replaced by a
reference. Full code strings are displayed without source-specific descriptions.
These projections are deliberate; they do not modify the underlying dataset.

## Build a study

Use local raw MERLIN generation Parquet or explicit JSONL sources as documented
in the [trace guide](build_annotation_cases.md) and [reference guide](build_reference_cases.md).
Generated JSONL requires label_origin="generated", but not reason. Reference
JSONL requires label_origin="reference". For V1 from a raw table, provide the
ordered symptom schema. Explicit JSONL evidence must match across both arms.
Raw V3 and V4 construction comparisons include the same laboratory evidence
for both arms; V1 and V2 use admission evidence. No retrospective discharge note
is appended by the raw label comparison importer.

```bash
uv run python scripts/build_label_comparison_cases.py \
  --generated /authorized/data/combined.pq \
  --reference /authorized/data/combined.pq \
  --model Qwen3-32B \
  --stages V1 V2 V3 V4 \
  --symptom-schema-json /authorized/data/symptom_schema.json \
  --split test --seed 42 --n 20 \
  --out /authorized/studies/label01

uv run python scripts/run_demo.py \
  --data-root /authorized/studies/label01/annotation_inputs
```

The importer selects complete matched admissions, randomizes order and A/B
assignment reproducibly, and records source hashes and the canonical-label
hashes in a private key outside the served data root. Explicit labels may still
reveal their origin through content or distribution: blinding hides metadata,
not all inferable cues. Stage panels for a case can be viewed together; use
separate single-stage studies if cross-stage evidence exposure matters.

## Rubric and analysis

For each arm, independently answer Yes / No / Unclear to the same stage-specific
label question. If canonical labels differ, additionally choose A / B / Equally
appropriate. Identical labels do not require a preference. No rationale
grounding question is asked. These are new proposed rubrics, not clinically
validated instruments.

```bash
uv run python scripts/export_annotations.py \
  --study /authorized/studies/label01 \
  --out /authorized/studies/label01/private_export

uv run python scripts/analyze_annotation_study.py \
  --export /authorized/studies/label01/private_export \
  --out /authorized/studies/label01/private_analysis/summary.json
```

The exporter writes label_comparison_ratings.jsonl, with per-pair aggregate
joint human judgments (generated x reference), preferences and private
provenance. It does not export clinical text or clinician identities. The
analysis groups by stage, reference provenance and comparison unit. It reports
the full 3x3 Yes/No/Unclear table, marginal support rates and paired
admission-cluster bootstrap intervals, and preferences. Four decisive
categories distinguish both supported, generated only supported, reference
only supported, and neither supported. Any pair with an Unclear judgment stays
separate. Counts are rater-pair judgments, not distinct patient diagnoses.
A Yes/No contrast is evidence of differential clinical support, not definitive
proof that either source is erroneous.

The primary support rate counts Unclear as non-Yes, while the joint table
preserves uncertainty. Incomplete exports are rejected by the statistical
analysis. These results must not be pooled with rationale validity or
standalone reference-review results. The allocation key and all patient-linked
exports remain in authorized local storage; no external inference is used.
The interface is a trusted local research tool, not an authenticated remote
multi-rater service. Do not expose it publicly.
