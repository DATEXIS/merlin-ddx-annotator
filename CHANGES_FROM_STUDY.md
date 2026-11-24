# Differences from the study implementation

The code that served the clinicians and analysed their ratings is preserved in the research group's private archive (tag `clinician-audit-batch1-study`). That version was identified directly:

- **Frontend:** the archived `src/` rebuilds the bundle that was served during rating byte for byte (`index-pOh5B-mj.js`, SHA-256 `7cf162edc0c2c5e2a3f5485a702388ad65f51a8636cd821eec45c06893d5846a`). It was in place from 05:12 UTC on 17 September 2026, before the first rating was saved.
- **Backend:** the deployed Python files are identical to the archived ones. The deployment image (digest `sha256:5c9ba6e63382ff71bad8013c0217dfccbc1af6594288c357e4d474cd5f26f681`) ran unchanged throughout rating.
- **Analysis:** the analysis modules were finalized on 17 September 2026 after rating ended, minutes before the final run; their input digests were recorded, their code version was not.

## Unchanged in this repository

| Part | Files |
|---|---|
| Audit screen | `src/components/RebuttalAudit.tsx`, `src/components/PatientNav.tsx`, `src/types.ts`, `src/index.css` |
| Backend | `merlin_ddx/sync_api.py`, `merlin_ddx/rebuttal_audit.py`, `merlin_ddx/annotation_store.py`, `merlin_ddx/paths.py` |
| Analysis | `merlin_ddx/rebuttal_analysis.py`, `rebuttal_preliminary.py`, `rebuttal_final_detail.py`, `rebuttal_gt_concordance.py`, `rebuttal_adjudicated.py`; `scripts/analyze_rebuttal_audit.py`, `scripts/analyze_rebuttal_preliminary.py` |
| Build | `package.json`, `package-lock.json`, Vite, TypeScript, Tailwind and PostCSS configuration, `index.html`, `Dockerfile` |
| Tests | the study's synthetic tests for the audit screen, backend and analysis |

## Changed

- **Application shell.** In the study, clinicians opened the general annotator application (`src/App.tsx`), whose default view served a separate DDx-annotation study, and switched to its *reasoning audit* view. Here `src/main.tsx` renders `src/AuditApp.tsx`, a small shell that loads the annotator list and renders the unchanged audit screen. The screen's *train / test / test (350)* buttons now show a notice instead of switching views. Because Tailwind CSS includes only the classes used by the included components, the built stylesheet is smaller. The audit screen's own styling is unchanged.
- **Python packaging.** `pyproject.toml` declares only what the audit needs (FastAPI, Uvicorn; `analysis` and `dev` extras) and is locked in `uv.lock`.
- **Rater labels.** Synthetic annotators are named *Synthetic rater 1/2*; the study's annotator list is not included.

## Not included

- The general annotator application and its other views: the DDx annotation pilot (70 cases), the 350-case scale-up and the superseded 70-case verification view. Their backend endpoints remain in the unchanged `sync_api.py` but are not used by the audit screen.
- Data preparation and model runners, including frontier-LLM API runners, section-segmentation research code, notebooks and deployment configuration.
- The script that sampled the 42 admissions and built the blinded and keyed pair files: it was not recovered (see [docs/protocol.md](docs/protocol.md), section 2).

## Added

Synthetic demonstration cases and the tools to build, run and summarize them; a full-size synthetic dataset generator and a primary-analysis wrapper around the unchanged pipeline; reproduction tools for the contingency matrices and the credentialed per-item aggregates; rubric-consistency, backend, reproduction, hygiene and end-to-end tests; documentation and figures.
