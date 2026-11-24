# Synthetic DDx annotation cases

**Everything here is synthetic.** The nine admissions, notes, candidate schemes, model predictions, rationales and annotations were written for this repository. None is derived from, paraphrased from or modelled on a MIMIC-IV record, a WikiDoc entry, a model output of the study or a clinician's annotation.

- **Notes:** every note's history starts with `SYNTHETIC CASE - not a real patient.`
- **Rationales:** model rationales start with `[synthetic … rationale …]`.
- **Identifiers:** case identifiers are six-digit numbers starting with 9.

## Files

| Path | Content |
|---|---|
| `demo_cases.json` | Single source: candidate schemes per chief complaint (disease, ICD-10 pattern, symptom features), cases, model predictions per stage, synthetic ratings |
| `annotations/<rater>/<case>.json` | Synthetic annotation records in the backend's storage format |
| `custom_diagnoses/<case>.json` | Added ("Other Disease") diagnoses, shared per case |
| `reference/diagnoses/<chief_complaint>.csv` | The synthetic candidate schemes in the layout the analysis reads |

`scripts/build_synthetic_ddx_demo.py` regenerates these files, plus the cohort and reasoning files in `../data_root/app/`, from `demo_cases.json`. Tests fail if they are out of date. `scripts/run_demo.py --with-ratings` loads the annotations into the demo server.

`scripts/make_synthetic_ddx_fixture.py` writes the analysis inputs: a case pool, the sampling frame, the schemes and the annotation store. It uses these cases by default; with `--full-size` it writes a random cohort of the study's size.

## What the cases demonstrate

| Case | View | Demonstrates |
|---|---|---|
| 900101 chest pain | pilot train | Cosine reference, ICD reference and rater agree |
| 900102 cough | pilot train | The references differ; the rater sides with the ICD reference |
| 900103 abdominal pain | pilot test | Two diagnoses marked (multi-label) |
| 900104 headache | pilot test | A dangerous diagnosis ranked low by cosine, chosen by rater and ICD reference |
| 900201 back pain | test (350) | Three raters; rater 1 adds a related second diagnosis; WikiDoc-style help card |
| 900202 diarrhea | test (350) | The correct diagnosis is missing from the list: added once, checked by two raters; the third rater picks the closest candidate |
| 900203 dyspnea | test (350) | Incomplete overlap: rater 2 did not annotate this case |
| 900204 chest pain | test (350) | References disagree; both raters side with the ICD reference |
| 900205 cough | test (350) | Raters disagree |

The model columns (Llama, Qwen, MedGemma) carry V1–V4 rank labels and V2–V4 rationales derived from the synthetic predictions. V1 is the dot product of a synthetic symptom vector with the scheme features, as in the original analysis.

`tests/python/test_ddx_analysis_synthetic.py` runs the original analysis on these cases and checks each result against a hand calculation, which is listed in the test's docstring. The synthetic results illustrate the procedure and say nothing about the study.
