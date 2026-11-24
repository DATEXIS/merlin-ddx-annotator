# Data access and restrictions

## What is where

| Material | Where | Access |
|---|---|---|
| Interface, backend, analysis code, protocol, rubric, cohort-level results, aggregate agreement statistics and contingency matrices, synthetic examples | This repository | Public, MIT licence (software) |
| Evaluated rationale texts and targets, per-item aggregate ratings, case grouping identifiers (including MIMIC-IV `hadm_id`/`subject_id`), condition, stage, verifier scores, loop outcomes, provenance metadata, and the exact annotation inputs (blinded pairs and the admission notes as shown to clinicians) | MERLIN-DDx credentialed release on PhysioNet (not yet published) | Credentialed PhysioNet users under the data use agreement, once published |
| Individual clinician ratings, clinician comments, clinician identities, allocation key, source files | Internal research archive | Not distributed |

**Status:** the credentialed PhysioNet release is not yet published. Its location will be linked here when it is.

## Why the split

- **Admission notes and annotation inputs** are MIMIC-IV-derived text; they are to be released on PhysioNet so that credentialed users can review or re-rate the study cases in this interface exactly as clinicians saw them.
- **Rationale texts** were generated from MIMIC-IV notes and can repeat patient-specific content. MIMIC-IV is distributed under the PhysioNet Credentialed Health Data Use Agreement, so anything derived from it is shared only through PhysioNet.
- **Per-item ratings**, even aggregated and pseudonymized, attach clinicians' judgments to individual patient-derived items. They are therefore released with the texts, under the same agreement, and not here.
- **Individual ratings and comments** are internal research records of named clinicians and are not released. The public contingency matrices passed a disclosure review: a matrix is published in full only when it reveals no more about individual clinicians' item-level answers than the published κ already does. All κ values are published at full precision: for some measures, κ together with the credentialed per-item aggregates assigns that measure's disagreements to one of the two anonymous clinicians, and the investigators accepted this residual risk. Nothing released links an anonymous rater label to a named clinician (see [results/agreement_statistics.md](../results/agreement_statistics.md)).

## Licence versus data use agreement

The MIT licence covers the software and documentation in this repository. It grants no rights to MIMIC-IV, to the MERLIN-DDx PhysioNet datasets or to anything derived from them. Use of those data is governed solely by the PhysioNet credentialing process and the data use agreement you sign there; PhysioNet credentialing by itself does not permit redistributing the data.

## Using credentialed data with this code

- Keep credentialed files outside this repository or in the git-ignored `physionet/` or `data/` folders. Do not commit them, attach them to issues or pull requests, or paste their content into external services.
- `scripts/reproduce_from_credentialed.py` reads the PhysioNet files locally and prints only cohort-level numbers.
- Nothing in this repository downloads, uploads or transmits data automatically. Continuous integration uses only the synthetic examples.
