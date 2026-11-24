import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from merlin_ddx.annotation_store import (
    AnnotationStoreError,
    aggregate_annotations,
    list_annotation_records,
    validate_id,
    write_annotation_overlays,
    write_annotation_record,
)
from merlin_ddx.paths import data_paths
from merlin_ddx.sync_api import create_app


def test_write_list_and_aggregate_annotations(tmp_path: Path):
    paths = data_paths(tmp_path / "data")

    first = write_annotation_record(paths, "clinician1", "patient-1", {"d1": True, "d2": False})
    write_annotation_record(paths, "clinician2", "patient-1", {"d1": True})

    records = list_annotation_records(paths, "clinician1")
    assert records == [first]

    overlays = aggregate_annotations(paths)
    assert overlays["patients"]["patient-1"]["d1"]["positiveAnnotatorIds"] == [
        "clinician1",
        "clinician2",
    ]
    assert overlays["patients"]["patient-1"]["d2"]["negativeCount"] == 1


def test_write_annotation_overlays_file(tmp_path: Path):
    paths = data_paths(tmp_path / "data")
    write_annotation_record(paths, "clinician1", "patient-1", {"d1": True})

    overlays = write_annotation_overlays(paths)

    assert paths.annotation_overlays_json.exists()
    assert json.loads(paths.annotation_overlays_json.read_text()) == overlays


def test_rejects_unsafe_ids(tmp_path: Path):
    paths = data_paths(tmp_path / "data")
    with pytest.raises(AnnotationStoreError):
        write_annotation_record(paths, "../bad", "patient-1", {"d1": True})
    with pytest.raises(AnnotationStoreError):
        validate_id("patient_id", "patient/1")


def test_sync_api_saves_and_loads_annotations(tmp_path: Path):
    data_root = tmp_path / "data"
    app_dir = data_root / "app"
    app_dir.mkdir(parents=True)
    (app_dir / "patients.json").write_text('[{"id":"patient-1"}]\n')
    (app_dir / "annotators.json").write_text('[{"id":"clinician1","name":"Clinician 1","type":"human"}]\n')
    (app_dir / "metrics.json").write_text('{"stages":[]}\n')
    (app_dir / "verification70.json").write_text(
        '[{"patientId":"patient-1","chiefComplaint":"cough",'
        '"mainDiagnosis":{"diseaseName":"Pneumonia","v2Reasoning":"Example"},"items":'
        '[{"id":"a","icdCode":"J18.9","rationale":"Example"},'
        '{"id":"b","icdCode":"R05","rationale":"Example"}]}]\n'
    )
    (app_dir / "model_reasoning.json").write_text(
        '{"patients":{"patient-1":{"patientId":"patient-1","models":{}}}}\n'
    )

    app = create_app(data_root, sync_git=False)
    client = TestClient(app)

    response = client.get("/healthz")
    assert response.status_code == 200

    response = client.get("/api/patients")
    assert response.status_code == 200
    assert response.json()[0]["id"] == "patient-1"

    response = client.get("/api/annotators")
    assert response.status_code == 200
    assert response.json()[0]["id"] == "clinician1"

    response = client.get("/api/verification70")
    assert response.status_code == 200
    assert response.json()[0]["patientId"] == "patient-1"

    response = client.put(
        "/api/verification70/annotations/clinician1/patient-1",
        json={"answers": {
            "v2": {"grounding": "yes", "clinicalSupport": "yes"},
            "a": {"grounding": "yes", "clinicalSupport": "unclear"},
        }},
    )
    assert response.status_code == 200
    assert response.json()["answers"]["a"]["grounding"] == "yes"
    assert response.json()["answers"]["v2"]["clinicalSupport"] == "yes"
    assert client.get("/api/verification70/annotations/clinician1").json()[0]["patientId"] == "patient-1"
    assert client.get("/api/annotations/clinician1").json() == []
    assert client.put(
        "/api/verification70/annotations/clinician1/patient-1",
        json={"answers": {"a": {"grounding": "maybe"}}},
    ).status_code == 422

    response = client.get("/api/metrics")
    assert response.status_code == 200
    assert response.json()["stages"] == []

    response = client.get("/api/model-reasoning/patient-1")
    assert response.status_code == 200
    assert response.json() == {"patientId": "patient-1", "models": {}}

    response = client.get("/api/model-reasoning/missing")
    assert response.status_code == 404

    response = client.put(
        "/api/annotations/clinician1/patient-1",
        json={"annotations": {"d1": True}},
    )
    assert response.status_code == 200
    assert response.json()["record"]["annotations"] == {"d1": True}

    response = client.get("/api/annotations/clinician1")
    assert response.status_code == 200
    assert response.json()[0]["patientId"] == "patient-1"

    response = client.get("/api/annotations")
    assert response.status_code == 200
    assert response.json()[0]["annotatorId"] == "clinician1"

    response = client.get("/api/evaluation-overlays")
    assert response.status_code == 200
    assert response.json()["patients"]["patient-1"]["d1"]["positiveCount"] == 1
