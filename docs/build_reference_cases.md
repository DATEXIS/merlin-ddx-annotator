# Review MERLIN reference labels

Reference labels and raw generated model outputs are different evidence types.
The reference workflow reviews candidate labels without requiring a generated
rationale or a second response. It does not assume that a reference label is
clinically correct merely because it is used by the verifier or training pipeline.

| Stage | Raw source field | Meaning |
|---|---|---|
| V1 | disease_vector | WikiDoc disease-level manifestation prototype; NOT patient-specific symptom ground truth |
| V2 | disease | Mapped WikiDoc diagnosis reference |
| V3 | disease | Same mapped diagnosis reference, with laboratory evidence |
| V4 | ICD_CODES | Recorded MIMIC-IV discharge ICD labels |

For V1, supply an explicit ordered symptom schema JSON whose keys are normalized
chief complaints (lowercase, spaces replaced by underscores) and whose values
are lists of manifestation names in the exact upstream YAML key order.
For example, a synthetic schema might be {"synthetic_complaint": ["Symptom A", "Symptom B"]}.
The importer checks vector length and values. Do not infer key order from model
predictions. A disease prototype is not a patient-level extraction annotation.
To review actual patient-specific symptom references, supply explicit JSONL
records instead.

The raw Parquet workflow selects one storage row per admission via
--source-model because combined.pq contains duplicate admissions across
generators. That choice does not make the reference model-generated. The
reference importer never reads v*_json, v*_text, or verifier scores.
By default V2–V4 reference review includes retrospective discharge documentation
and V3 also includes labs; --admission-only omits discharge documentation.
V1 uses admission evidence. For controlled evidence exposure, build separate
single-stage studies: all stages included for an admission can be visible to
the same reviewer. Review the proposed questions with clinicians before use.

## Example

```bash
uv run python scripts/build_reference_cases.py \
  --input /authorized/data/combined.pq \
  --source-model Qwen3-32B \
  --stages V2 V3 V4 --split test --n 20 \
  --out /authorized/studies/reference01

uv run python scripts/run_demo.py \
  --data-root /authorized/studies/reference01/annotation_inputs
```

To include raw V1 prototypes, add V1 to --stages and pass
--symptom-schema-json /authorized/data/symptom_schema.json.

Explicit JSONL source: one record per admission and stage. Required string
fields: hadm_id, stage, split, chief_complaint, admission_note, clinical_context,
target, label_source, label_id, label_origin (exactly "reference").
clinical_context must be nonempty for V3. For JSONL, evidence scope is supplied
by the caller; --admission-only does not rewrite that evidence. Only include
authorized patient data and document the actual source. A separate generated
study requires label_origin="generated"; these source types must not be
substituted for each other.

## Annotation and export

The reviewer answers a stage-specific label question (Yes/No/Unclear) and can
optionally suggest a correction or enter a comment. A reference item has no
generated rationale, no Q1 rationale grounding judgment, and no pairwise
preference. A proposed correction does not replace the original label.
The reference-label hash and source artifact hash remain in the private key.

```bash
uv run python scripts/export_annotations.py \
  --study /authorized/studies/reference01 \
  --out /authorized/studies/reference01/private_export

uv run python scripts/analyze_annotation_study.py \
  --export /authorized/studies/reference01/private_export \
  --out /authorized/studies/reference01/private_analysis/summary.json
```

The export writes label_ratings.jsonl, not trace_ratings.jsonl.
It contains explicit reference provenance, vote counts, missing votes, and the
number of suggested corrections. For local authorized adjudication only,
--include-corrections adds a separate file of suggested-label text and counts.
It does not export comments or overwrite source labels. Corrections are not
automatically validated clinical labels; they require adjudication. The
analysis reports reference-label support by stage and provenance, including
admission-cluster bootstrap intervals when there is more than one admission.
These metrics must not be pooled with generated-rationale validity rates.

All patient-linked material, including corrections, stays in authorized
storage outside Git. The new mode is a local research instrument, not a
clinically validated rubric or authenticated multi-rater service. The existing
DDx reference-annotation workflow and historical reasoning audit remain
unchanged.
