from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.staticfiles import StaticFiles

from merlin_ddx.annotation_store import (
    AnnotationStoreError,
    add_custom_diagnosis,
    list_annotation_records,
    list_custom_diagnoses,
    pull_annotation_changes,
    remove_custom_diagnosis,
    sync_annotation_changes,
    write_annotation_overlays,
    write_annotation_record,
    write_json_atomic,
    validate_id,
)
from merlin_ddx.paths import data_paths
from merlin_ddx.rebuttal_audit import load_cases as load_rebuttal_cases, validate_answers as validate_rebuttal_answers


class AnnotationSaveRequest(BaseModel):
    annotations: dict[str, bool]
    expectedUpdatedAt: str | None = None


class CustomDiagnosisCreateRequest(BaseModel):
    label: str
    createdBy: str


class VerificationAnswer(BaseModel):
    grounding: Literal["yes", "no", "unclear"] | None = None
    clinicalSupport: Literal["yes", "no", "unclear"] | None = None


class VerificationSaveRequest(BaseModel):
    answers: dict[Literal["v2", "a", "b"], VerificationAnswer]


class RebuttalAuditSaveRequest(BaseModel):
    pairs: dict[str, dict[str, str | None]]


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text())
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"Missing data file: {path.name}") from exc
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=500, detail=f"Invalid JSON data file: {path.name}") from exc


def dataset_files(app_dir: Path, base: str) -> list[tuple[str, Path]]:
    """Discover cohort files named ``{base}*.json`` and derive a dataset id from
    each filename: ``patients.json`` -> ``"pilot"`` (the original 70 cases),
    ``patients_test350.json`` -> ``"test350"``. Kept data-driven so a new cohort
    is added by dropping in a file, not by editing code. Sorted so the bare
    ``{base}.json`` ("pilot") is served first."""
    files: list[tuple[str, Path]] = []
    for path in sorted(app_dir.glob(f"{base}*.json")):
        suffix = path.stem[len(base):].lstrip("_")
        files.append((suffix or "pilot", path))
    return files


def create_app(
    data_root: Path | str | None = None,
    sync_git: bool = True,
    static_dir: Path | str | None = None,
) -> FastAPI:
    paths = data_paths(data_root)
    app = FastAPI(title="MERLIN DDx annotation sync")
    workspace = paths.root / "workspace.json"
    independent_rater = None
    if workspace.is_file():
        independent_rater = validate_id("annotator_id", load_json(workspace)["rater"])
        configured = load_json(paths.annotators_json)
        if [r["id"] for r in configured] != [independent_rater] or sync_git:
            raise ValueError("Independent workspace requires exactly one rater and disabled Git sync")

        @app.middleware("http")
        async def restrict_workspace(request: Request, call_next):
            path = request.url.path
            if path.startswith("/api/"):
                parts = path.strip("/").split("/")
                allowed = path in {"/api/patients", "/api/annotators", "/api/annotations", "/api/rebuttal-audit"}
                if len(parts) >= 3 and parts[1] == "annotations":
                    allowed = parts[2] == independent_rater and len(parts) in (3, 4)
                if len(parts) >= 4 and parts[1:3] == ["rebuttal-audit", "annotations"]:
                    allowed = parts[3] == independent_rater and len(parts) in (4, 5)
                if len(parts) in (3, 4) and parts[1] == "custom-diagnoses":
                    allowed = load_json(workspace)["study_type"] == "ddx"
                if not allowed:
                    return JSONResponse({"detail": "Unavailable in independent workspace"}, status_code=403)
            response = await call_next(request)
            response.headers["Cache-Control"] = "no-store"
            return response

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/patients")
    def get_patients() -> list[dict[str, Any]]:
        # Merge every patients*.json cohort into one list; tag each record with
        # its dataset id (defaulting to the id derived from the filename) so the
        # UI can filter cohorts without the files being mixed on disk.
        patients: list[dict[str, Any]] = []
        for dataset_id, path in dataset_files(paths.app_dir, "patients"):
            for record in load_json(path):
                record.setdefault("dataset", dataset_id)
                patients.append(record)
        return patients

    @app.get("/api/annotators")
    def get_annotators() -> list[dict[str, Any]]:
        return load_json(paths.annotators_json)

    @app.get("/api/verification70")
    def get_verification_cases() -> list[dict[str, Any]]:
        return load_json(paths.app_dir / "verification70.json")

    @app.get("/api/rebuttal-audit")
    def get_rebuttal_audit() -> list[dict[str, Any]]:
        return load_rebuttal_cases(paths.root)

    @app.get("/api/rebuttal-audit/annotations/{annotator_id}")
    def get_rebuttal_annotations(annotator_id: str) -> list[dict[str, Any]]:
        try:
            annotator = validate_id("annotator_id", annotator_id)
        except AnnotationStoreError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        directory = paths.root / "rebuttal_audit_annotations" / annotator
        return [load_json(path) for path in sorted(directory.glob("*.json"))]

    @app.put("/api/rebuttal-audit/annotations/{annotator_id}/{hadm_id}")
    def save_rebuttal_annotation(
        annotator_id: str, hadm_id: str, request: RebuttalAuditSaveRequest,
    ) -> dict[str, Any]:
        try:
            annotator = validate_id("annotator_id", annotator_id)
            admission = validate_id("hadm_id", hadm_id)
        except AnnotationStoreError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        validate_rebuttal_answers(admission, request.pairs, load_rebuttal_cases(paths.root))
        destination = paths.root / "rebuttal_audit_annotations" / annotator / f"{admission}.json"
        previous_pairs = load_json(destination).get("pairs", {}) if destination.exists() else {}
        case_pairs = {pair["pair_id"]: pair for case in load_rebuttal_cases(paths.root)
                      if case["hadm_id"] == admission for pair in case["pairs"]}
        record = {
            "annotatorId": annotator,
            "hadm_id": admission,
            "updatedAt": datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
            "pairs": {**previous_pairs, **{pair_id: {
                **previous_pairs.get(pair_id, {}), **answers,
                "pair_id": pair_id, "hadm_id": admission,
                **({"target_preference_A_B_equal": None}
                   if case_pairs[pair_id]["target_A"] == case_pairs[pair_id]["target_B"] else {}),
            }
                      for pair_id, answers in request.pairs.items()}},
        }
        write_json_atomic(destination, record)
        return record

    @app.get("/api/verification70/annotations/{annotator_id}")
    def get_verification_annotations(annotator_id: str) -> list[dict[str, Any]]:
        try:
            annotator = validate_id("annotator_id", annotator_id)
        except AnnotationStoreError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        directory = paths.root / "verification70" / annotator
        records = []
        for path in sorted(directory.glob("*.json")):
            try:
                records.append(load_json(path))
            except HTTPException:
                continue
        return records

    @app.put("/api/verification70/annotations/{annotator_id}/{patient_id}")
    def save_verification_annotation(
        annotator_id: str, patient_id: str, request: VerificationSaveRequest,
    ) -> dict[str, Any]:
        try:
            annotator = validate_id("annotator_id", annotator_id)
            patient = validate_id("patient_id", patient_id)
        except AnnotationStoreError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        cases = load_json(paths.app_dir / "verification70.json")
        if patient not in {case["patientId"] for case in cases}:
            raise HTTPException(status_code=404, detail="Verification case not found")
        record = {
            "annotatorId": annotator,
            "patientId": patient,
            "updatedAt": datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
            "answers": {key: value.model_dump() for key, value in request.answers.items()},
        }
        write_json_atomic(paths.root / "verification70" / annotator / f"{patient}.json", record)
        return record

    @app.get("/api/metrics")
    def get_metrics() -> dict[str, Any]:
        return load_json(paths.metrics_json)

    @app.get("/api/model-reasoning/{patient_id}")
    def get_model_reasoning(patient_id: str) -> dict[str, Any]:
        # Patient ids are unique across cohorts, so scan each model_reasoning*.json
        # and return the first match.
        for _dataset_id, path in dataset_files(paths.app_dir, "model_reasoning"):
            reasoning = load_json(path)
            patient_reasoning = reasoning.get("patients", {}).get(patient_id)
            if patient_reasoning is not None:
                return patient_reasoning
        raise HTTPException(
            status_code=404,
            detail=f"No model reasoning found for patient: {patient_id}",
        )

    @app.get("/api/annotations")
    def get_all_annotations() -> list[dict[str, Any]]:
        return [record.to_json() for record in list_annotation_records(paths, independent_rater)]

    @app.get("/api/annotations/{annotator_id}")
    def get_annotations(annotator_id: str) -> list[dict[str, Any]]:
        try:
            return [record.to_json() for record in list_annotation_records(paths, annotator_id)]
        except AnnotationStoreError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.put("/api/annotations/{annotator_id}/{patient_id}")
    def save_annotation(
        annotator_id: str,
        patient_id: str,
        request: AnnotationSaveRequest,
    ) -> dict[str, Any]:
        try:
            record = write_annotation_record(
                paths,
                annotator_id,
                patient_id,
                request.annotations,
                request.expectedUpdatedAt,
            )
            overlays = write_annotation_overlays(paths)
            git_status = (
                sync_annotation_changes(
                    paths,
                    f"annotations: save {annotator_id} {patient_id}",
                )
                if sync_git
                else {"committed": False, "pushed": False, "reason": "disabled"}
            )
        except AnnotationStoreError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

        return {
            "record": record.to_json(),
            "overlaysUpdatedAt": overlays["updatedAt"],
            "git": git_status,
        }

    @app.get("/api/custom-diagnoses/{patient_id}")
    def get_custom_diagnoses(patient_id: str) -> list[dict[str, Any]]:
        try:
            return [item.to_json() for item in list_custom_diagnoses(paths, patient_id)]
        except AnnotationStoreError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/custom-diagnoses/{patient_id}")
    def create_custom_diagnosis(
        patient_id: str,
        request: CustomDiagnosisCreateRequest,
    ) -> dict[str, Any]:
        try:
            if independent_rater and request.createdBy != independent_rater:
                raise HTTPException(status_code=403, detail="Rater identity mismatch")
            entry = add_custom_diagnosis(paths, patient_id, request.label, request.createdBy)
        except AnnotationStoreError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return entry.to_json()

    @app.delete("/api/custom-diagnoses/{patient_id}/{diagnosis_id}")
    def delete_custom_diagnosis(patient_id: str, diagnosis_id: str) -> dict[str, Any]:
        try:
            remove_custom_diagnosis(paths, patient_id, diagnosis_id)
        except AnnotationStoreError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        overlays = write_annotation_overlays(paths)
        return {"deleted": True, "overlaysUpdatedAt": overlays["updatedAt"]}

    @app.post("/api/sync/pull")
    def pull_and_aggregate() -> dict[str, Any]:
        try:
            git_status = pull_annotation_changes(paths) if sync_git else {
                "pulled": False,
                "reason": "disabled",
            }
            overlays = write_annotation_overlays(paths)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        return {"overlaysUpdatedAt": overlays["updatedAt"], "git": git_status}

    @app.get("/api/evaluation-overlays")
    def get_evaluation_overlays() -> dict[str, Any]:
        if paths.annotation_overlays_json.exists():
            return json.loads(paths.annotation_overlays_json.read_text())
        return write_annotation_overlays(paths)

    if static_dir:
        static_path = Path(static_dir)
        if static_path.exists():
            app.mount("/", StaticFiles(directory=static_path, html=True), name="static")

    return app


def env_flag(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.lower() in {"1", "true", "yes", "on"}


app = create_app(
    data_root=os.getenv("MERLIN_DDX_DATA_ROOT"),
    sync_git=env_flag("MERLIN_DDX_SYNC_GIT", default=False),
    static_dir=os.getenv("MERLIN_DDX_STATIC_DIR"),
)
