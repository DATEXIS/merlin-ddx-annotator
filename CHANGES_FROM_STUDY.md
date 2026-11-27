# Differences from the study implementation

> This document records the historical reproduction release through v1.1.0. The v1.2.0 baseline extends the frontend and backend for new studies; claims of unchanged files or byte-identical builds below refer to v1.1.0. The historical rubric and original analysis are retained. See [new-study baseline](docs/new_studies.md).

The code that served the clinicians and analysed their annotations is preserved in the research group's private archive (tag `clinician-audit-batch1-study`, the state of 17 September 2026).

## How the released code was identified

- **Frontend:**
  - The archived `src/` rebuilds byte for byte the bundle that was served during the reasoning audit (`index-pOh5B-mj.js`, SHA-256 `7cf162edc0c2c5e2a3f5485a702388ad65f51a8636cd821eec45c06893d5846a`). That bundle was in place from 05:12 UTC on 17 September 2026, before the first audit rating was saved.
  - In this repository every frontend source except `src/main.tsx` is the archived file. `src/main.tsx` adds the fallback described below, so the bundle built here is not byte-identical to the served one.
  - The DDx annotation (July–August 2026) ran on earlier builds, which were not recorded. From 16 July 2026, when the repository history starts, the DDx view's code differs from the released one only by the position field for jumping to a case and the code paths of the later views. Display defaults and storage are unchanged ([docs/ddx_annotation/protocol.md](docs/ddx_annotation/protocol.md), section 4.5).
- **Backend:** the deployed Python files are identical to the archived ones. The deployment image (digest `sha256:5c9ba6e63382ff71bad8013c0217dfccbc1af6594288c357e4d474cd5f26f681`) ran unchanged throughout the audit.
- **Audit analysis:** the audit analysis modules were finalized on 17 September 2026, after rating ended and minutes before the final run. Their input digests were recorded; their code version was not.

## Unchanged in this repository

| Part | Files |
|---|---|
| Application | `src/App.tsx`, `src/components/*` (DDx panel, discharge note, audit screen, navigation, hover cards, switches, the hidden verification panel), `src/hooks/*`, `src/config/*`, `src/types.ts`, `src/index.css` |
| Backend | `merlin_ddx/sync_api.py`, `merlin_ddx/annotation_store.py`, `merlin_ddx/rebuttal_audit.py`, `merlin_ddx/paths.py` |
| Audit analysis | `merlin_ddx/rebuttal_analysis.py`, `rebuttal_preliminary.py`, `rebuttal_final_detail.py`, `rebuttal_gt_concordance.py`, `rebuttal_adjudicated.py`; `scripts/analyze_rebuttal_audit.py`, `scripts/analyze_rebuttal_preliminary.py` |
| Build | `package.json`, `package-lock.json`, Vite, TypeScript, Tailwind and PostCSS configuration, `index.html`, `Dockerfile` |
| Tests | the study's synthetic tests for the audit screen, backend and audit analysis |

## Changed

**DDx analysis scripts (sanitized).** Changed files: `scripts/analyse_annotations.py`, `scripts/analyse_scaleup_annotations.py`, `scripts/sample_blind_annotation.py` and `scripts/generate_report.py`. The public files are derived from the archived ones by fixed, counted text replacements, applied and checked by the private release tooling. No computation, scoring rule, parameter or output file name changed. The replacements are:

- **Name.** A clinician's first name in docstrings and in result keys (`<name>_true`, `<name>_vs_icd_agree`, …) becomes "the clinician" / `clinician_*`.
- **Credentials.** The default URL, user name and password of the retired annotation server become empty defaults.
- **Identifier.** A real admission identifier in a comment becomes a placeholder.
- **Blinding wording.** The code called the clinician, or a pilot split, "blinded". These labels in comments, plot titles and console output now read neutrally. Both DDx cohorts (both pilot splits and the 350-case study) used procedural blinding to model predictions and peer marks, according to the investigators' account. The recorded discharge diagnoses and ICD codes were visible only in the pilot training split for calibration and hidden in the pilot test split and the 350-case study. The original pilot report incorrectly described model predictions as visible during calibration, according to the investigators. The interface did not enforce or log DDx masking ([protocol](docs/ddx_annotation/protocol.md), section 4).
- **Deployment wording.** Mentions of the cluster volume and namespace become generic.
- **`generate_report.py`.** Only the helpers and page template that the 350-case report imports are kept; they are unchanged. The study version also assembled the pilot report, whose text hard-codes interpretive statements and recommended paper wording about the pilot results. That report body is not released.

**Application shell.**

- v1.0 rendered the audit screen through a separate shell (`src/AuditApp.tsx`), because the DDx views were not part of that release.
- v1.1.0 renders the study's own `src/App.tsx` again. The application opens on the DDx pilot view, and the audit is the *reasoning audit* view, as in the study.
- The study's `App` cannot reach that view when the data root holds no DDx cases. This is the case for the credentialed reasoning-audit inputs. For that situation, `src/main.tsx` (otherwise the study's ten-line entry point) checks `/api/patients` and falls back to the v1.0 audit-only shell (`src/AuditApp.tsx`).
- The audit screen itself is unchanged, and so are its screenshots, which regenerate byte-identical.

**Python packaging.** `pyproject.toml` declares FastAPI and Uvicorn, with `analysis` and `dev` extras, and is locked in `uv.lock`.

**Annotators.** Synthetic annotators are named *Synthetic rater 1/2/3*; the study's annotator list is not included.

## Not included

- **Verification view.** The data of the superseded 70-case verification view, which collected no judgments ([docs/verification/](docs/verification/README.md)). Its frontend code ships hidden, as in the study, because the unchanged application imports it.
- **Data preparation and model runners.** This covers the candidate lists, the WikiDoc schemes and model predictions, the frontier-LLM API runners, the section-segmentation research code, notebooks and deployment configuration.
- **Audit sampling script.** The script that sampled the 42 audit admissions and built the blinded and keyed pair files was not recovered ([docs/protocol.md](docs/protocol.md), section 2).
- **Pilot sampling and analysis inputs.** The selection procedure of the 70 pilot cases and the case pool of the original pilot analysis were not recovered ([docs/ddx_annotation/protocol.md](docs/ddx_annotation/protocol.md), section 7).
- **Study frontend test.** The study's frontend test of `App.tsx` reads the study's patient files. It is replaced by a test on the synthetic cohorts.

## Added

- **DDx synthetic data and tools:**
  - synthetic DDx cohorts (pilot and 350-case views), annotations, added diagnoses and candidate schemes, with their builder;
  - a synthetic analysis fixture (demo cases or full-size);
  - a wrapper that runs the original DDx analyses on a local annotation store, restricting the pilot run to the pilot cohort (the original pilot script relied on a pilot-only case pool);
  - the coverage and set-agreement statistics the manuscript reports, which no archived script computed;
  - κ reproduction from the published DDx matrices.
- **DDx results and documentation:** cohort-level DDx results, the DDx and verification documentation, the DDx workflow figure and screenshots.
- **Audit tools (v1.0):** synthetic demonstration cases and the tools to build, run and summarize them; a full-size synthetic dataset generator and a primary-analysis wrapper around the unchanged pipeline; reproduction tools for the contingency matrices and the credentialed per-item aggregates.
- **Tests:** rubric-consistency, backend, reproduction, hygiene, DDx and end-to-end tests.
