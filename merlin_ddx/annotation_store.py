from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from merlin_ddx.paths import DataPaths, data_paths


SAFE_ID = re.compile(r"^[A-Za-z0-9_.-]+$")


class AnnotationStoreError(ValueError):
    pass


def write_json_atomic(path: Path, data: Any) -> None:
    """Serialise `data` to `path` atomically: write a temp file in the same
    directory, fsync it, then os.replace() into place. A crash or pod kill
    mid-write can then only leave the (discarded) temp file -- never a truncated
    0-byte target -- so readers of the store never see a half-written file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


@dataclass(frozen=True)
class AnnotationRecord:
    annotator_id: str
    patient_id: str
    updated_at: str
    annotations: dict[str, bool]

    def to_json(self) -> dict[str, Any]:
        return {
            "annotatorId": self.annotator_id,
            "patientId": self.patient_id,
            "updatedAt": self.updated_at,
            "annotations": self.annotations,
        }


@dataclass(frozen=True)
class CustomDiagnosis:
    id: str
    label: str
    created_by: str
    created_at: str

    def to_json(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "createdBy": self.created_by,
            "createdAt": self.created_at,
        }


def validate_id(kind: str, value: str) -> str:
    if not value or not SAFE_ID.match(value):
        raise AnnotationStoreError(f"Invalid {kind}: {value!r}")
    return value


def annotation_path(paths: DataPaths, annotator_id: str, patient_id: str) -> Path:
    annotator = validate_id("annotator_id", annotator_id)
    patient = validate_id("patient_id", patient_id)
    return paths.annotations_dir / annotator / f"{patient}.json"


def normalize_annotations(value: dict[str, Any]) -> dict[str, bool]:
    return {
        validate_id("diagnosis_id", str(diagnosis_id)): bool(checked)
        for diagnosis_id, checked in value.items()
    }


def read_annotation_record(path: Path) -> AnnotationRecord:
    raw = json.loads(path.read_text())
    return AnnotationRecord(
        annotator_id=str(raw["annotatorId"]),
        patient_id=str(raw["patientId"]),
        updated_at=str(raw["updatedAt"]),
        annotations=normalize_annotations(raw.get("annotations", {})),
    )


def read_annotation_record_or_none(path: Path) -> AnnotationRecord | None:
    """Read a record, returning None (and logging) for an empty/corrupt file
    instead of raising. A single bad file must not take down the whole
    /api/annotations listing."""
    try:
        return read_annotation_record(path)
    except (json.JSONDecodeError, KeyError, ValueError, OSError) as exc:
        print(f"[annotation_store] skipping unreadable record {path}: {exc}", file=sys.stderr)
        return None


def list_annotation_records(paths: DataPaths, annotator_id: str | None = None) -> list[AnnotationRecord]:
    if annotator_id:
        validate_id("annotator_id", annotator_id)
        candidates = sorted((paths.annotations_dir / annotator_id).glob("*.json"))
    else:
        candidates = sorted(paths.annotations_dir.glob("*/*.json"))
    records = (read_annotation_record_or_none(path) for path in candidates if path.is_file())
    return [record for record in records if record is not None]


def write_annotation_record(
    paths: DataPaths,
    annotator_id: str,
    patient_id: str,
    annotations: dict[str, Any],
    expected_updated_at: str | None = None,
) -> AnnotationRecord:
    path = annotation_path(paths, annotator_id, patient_id)
    if expected_updated_at and path.exists():
        # A corrupt/empty existing file has no valid timestamp to conflict with,
        # so treat it as overwritable rather than blocking the save.
        current = read_annotation_record_or_none(path)
        if current is not None and current.updated_at != expected_updated_at:
            raise AnnotationStoreError("Annotation changed on disk; refresh before overwriting.")

    record = AnnotationRecord(
        annotator_id=annotator_id,
        patient_id=patient_id,
        updated_at=datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
        annotations=normalize_annotations(annotations),
    )
    write_json_atomic(path, record.to_json())
    return record


def custom_diagnoses_path(paths: DataPaths, patient_id: str) -> Path:
    patient = validate_id("patient_id", patient_id)
    return paths.custom_diagnoses_dir / f"{patient}.json"


def list_custom_diagnoses(paths: DataPaths, patient_id: str) -> list[CustomDiagnosis]:
    path = custom_diagnoses_path(paths, patient_id)
    if not path.exists():
        return []
    raw = json.loads(path.read_text())
    return [
        CustomDiagnosis(
            id=str(item["id"]),
            label=str(item["label"]),
            created_by=str(item["createdBy"]),
            created_at=str(item["createdAt"]),
        )
        for item in raw
    ]


def add_custom_diagnosis(
    paths: DataPaths,
    patient_id: str,
    label: str,
    created_by: str,
) -> CustomDiagnosis:
    label = label.strip()
    if not label:
        raise AnnotationStoreError("Diagnosis label must not be empty.")

    existing = list_custom_diagnoses(paths, patient_id)

    # Reuse an existing entry with the same (case-insensitive) label instead
    # of creating a near-duplicate row every time someone retypes it.
    for item in existing:
        if item.label.strip().lower() == label.lower():
            return item

    next_index = 1
    existing_ids = {item.id for item in existing}
    while f"o{next_index}" in existing_ids:
        next_index += 1

    entry = CustomDiagnosis(
        id=f"o{next_index}",
        label=label,
        created_by=created_by,
        created_at=datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
    )
    updated = [*existing, entry]
    path = custom_diagnoses_path(paths, patient_id)
    write_json_atomic(path, [item.to_json() for item in updated])
    return entry


def remove_custom_diagnosis(paths: DataPaths, patient_id: str, diagnosis_id: str) -> None:
    validate_id("diagnosis_id", diagnosis_id)
    existing = list_custom_diagnoses(paths, patient_id)
    remaining = [item for item in existing if item.id != diagnosis_id]
    if len(remaining) == len(existing):
        raise AnnotationStoreError(f"Unknown custom diagnosis: {diagnosis_id!r}")

    path = custom_diagnoses_path(paths, patient_id)
    write_json_atomic(path, [item.to_json() for item in remaining])

    # Strip the now-deleted id from every annotator's saved annotations for
    # this patient so a stale "checked" boolean doesn't linger unseen.
    patient = validate_id("patient_id", patient_id)
    for record_path in sorted(paths.annotations_dir.glob(f"*/{patient}.json")):
        record = read_annotation_record_or_none(record_path)
        if record is None or diagnosis_id not in record.annotations:
            continue
        remaining_annotations = {
            key: value for key, value in record.annotations.items() if key != diagnosis_id
        }
        write_annotation_record(paths, record.annotator_id, patient_id, remaining_annotations)


def aggregate_annotations(paths: DataPaths) -> dict[str, Any]:
    patients: dict[str, dict[str, dict[str, Any]]] = {}
    for record in list_annotation_records(paths):
        patient = patients.setdefault(record.patient_id, {})
        for diagnosis_id, checked in record.annotations.items():
            diagnosis = patient.setdefault(
                diagnosis_id,
                {
                    "positiveAnnotatorIds": [],
                    "negativeAnnotatorIds": [],
                    "positiveCount": 0,
                    "negativeCount": 0,
                },
            )
            key = "positiveAnnotatorIds" if checked else "negativeAnnotatorIds"
            if record.annotator_id not in diagnosis[key]:
                diagnosis[key].append(record.annotator_id)

    for diagnoses in patients.values():
        for diagnosis in diagnoses.values():
            diagnosis["positiveAnnotatorIds"].sort()
            diagnosis["negativeAnnotatorIds"].sort()
            diagnosis["positiveCount"] = len(diagnosis["positiveAnnotatorIds"])
            diagnosis["negativeCount"] = len(diagnosis["negativeAnnotatorIds"])

    return {
        "updatedAt": datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "patients": patients,
    }


def write_annotation_overlays(paths: DataPaths) -> dict[str, Any]:
    overlays = aggregate_annotations(paths)
    write_json_atomic(paths.annotation_overlays_json, overlays)
    return overlays


def git_has_remote(repo_root: Path) -> bool:
    result = subprocess.run(
        ["git", "remote"],
        cwd=repo_root,
        check=False,
        capture_output=True,
        text=True,
    )
    return bool(result.stdout.strip())


def git_has_head(repo_root: Path) -> bool:
    result = subprocess.run(
        ["git", "rev-parse", "--verify", "HEAD"],
        cwd=repo_root,
        check=False,
        capture_output=True,
        text=True,
    )
    return result.returncode == 0


def run_git(repo_root: Path, args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
    )


def pull_annotation_changes(paths: DataPaths) -> dict[str, Any]:
    repo_root = paths.root.parent
    if not git_has_head(repo_root):
        return {"pulled": False, "reason": "no_head"}
    if not git_has_remote(repo_root):
        return {"pulled": False, "reason": "no_remote"}
    run_git(repo_root, ["pull", "--rebase", "--autostash"])
    return {"pulled": True}


def sync_annotation_changes(paths: DataPaths, message: str) -> dict[str, Any]:
    repo_root = paths.root.parent
    if not git_has_head(repo_root):
        return {"committed": False, "pushed": False, "reason": "no_head"}

    changed_paths = [
        str(paths.annotations_dir.relative_to(repo_root)),
        str(paths.annotation_overlays_json.relative_to(repo_root)),
    ]
    run_git(repo_root, ["add", *changed_paths])

    status = subprocess.run(
        ["git", "diff", "--cached", "--quiet", "--", *changed_paths],
        cwd=repo_root,
        check=False,
    )
    if status.returncode == 0:
        return {"committed": False, "pushed": False, "reason": "no_changes"}

    run_git(repo_root, ["commit", "-m", message, "--", *changed_paths])
    if not git_has_remote(repo_root):
        return {"committed": True, "pushed": False, "reason": "no_remote"}

    run_git(repo_root, ["pull", "--rebase", "--autostash"])
    run_git(repo_root, ["push"])
    return {"committed": True, "pushed": True}


def load_records_for_api(data_root: Path | str | None, annotator_id: str) -> list[dict[str, Any]]:
    paths = data_paths(data_root)
    return [record.to_json() for record in list_annotation_records(paths, annotator_id)]
