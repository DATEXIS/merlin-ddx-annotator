# Third-party notices

The MIT licence in [LICENSE](LICENSE) covers the original software and documentation in this repository. It does not cover, and grants no rights to, MIMIC-IV or the MERLIN-DDx datasets on PhysioNet (see [docs/data_access.md](docs/data_access.md)).

## Material included in this repository

| Material | Location | Source | Terms |
|---|---|---|---|
| Nine ICD-10-CM FY2026 code descriptions (`I21.4`, `I50.23`, `I50.9`, `I60.2`, `I60.9`, `I63.542`, `K35.32`, `K35.80`, `R42`), in the order-file format | `examples/synthetic/icd10cm_order_2026_subset.txt` and the derived `examples/synthetic/data_root/source/icd10cm-Code-Descriptions-2026.zip` | ICD-10-CM FY2026 code descriptions in tabular order, National Center for Health Statistics (CDC/NCHS) | US government work, public domain in the United States |

All synthetic cases, rationales and ratings in `examples/synthetic/` were written for this repository.

## Dependencies (not included; installed from package registries)

Python and JavaScript dependencies are declared in `pyproject.toml` / `uv.lock` and `package.json` / `package-lock.json` and are distributed under their own licences (for example FastAPI and Uvicorn: BSD-3-Clause; React, Vite, Tailwind CSS: MIT; NumPy, pandas, SciPy: BSD-3-Clause; Matplotlib: PSF-based Matplotlib licence; PyArrow: Apache-2.0). The built interface (`dist/`, not committed) bundles React and Tailwind CSS output under their MIT licences. The workflow figure is rendered with Mermaid (MIT), which is not included.
