"""The unchanged study backend serves and stores the DDx annotation workflow on synthetic data."""
from __future__ import annotations

import json
import shutil

import pytest
from fastapi.testclient import TestClient

from conftest import SYNTHETIC
from merlin_ddx.sync_api import create_app


@pytest.fixture
def api(demo_data_root):
    return TestClient(create_app(data_root=demo_data_root, sync_git=False)), demo_data_root


def test_serves_both_cohorts_with_dataset_tags(api):
    client, _ = api
    patients = client.get("/api/patients").json()
    datasets = {p["id"]: p.get("dataset", "pilot") for p in patients}
    assert sorted(v for v in datasets.values()).count("pilot") == 4
    assert sorted(v for v in datasets.values()).count("test350") == 5
    reasoning = client.get("/api/model-reasoning/900201-back_pain").json()
    assert reasoning["models"]["qwen"]["modelName"] == "Qwen3-32B"
    assert client.get("/api/model-reasoning/unknown-case").status_code == 404


def test_saves_selections_and_shared_added_diagnoses(api):
    client, root = api
    response = client.put("/api/annotations/synthetic_rater_3/900204-chest_pain", json={"annotations": {"d2": True}})
    assert response.status_code == 200, response.text
    added = client.post("/api/custom-diagnoses/900205-cough",
                        json={"label": "Parapneumonic effusion", "createdBy": "synthetic_rater_3"}).json()
    assert added["id"] == "o1"
    again = client.post("/api/custom-diagnoses/900205-cough",
                        json={"label": "parapneumonic effusion ", "createdBy": "synthetic_rater_1"}).json()
    assert again["id"] == "o1"                              # case-insensitive reuse, shared across raters
    client.put("/api/annotations/synthetic_rater_3/900205-cough", json={"annotations": {"o1": True}})
    stored = json.loads((root / "annotations" / "synthetic_rater_3" / "900204-chest_pain.json").read_text())
    assert stored["annotations"] == {"d2": True}
    client.delete("/api/custom-diagnoses/900205-cough/o1")
    cleaned = json.loads((root / "annotations" / "synthetic_rater_3" / "900205-cough.json").read_text())
    assert cleaned["annotations"] == {}                     # deleting an added diagnosis strips the mark


def test_preloaded_synthetic_records_round_trip(api):
    client, root = api
    shutil.copytree(SYNTHETIC / "ddx" / "annotations", root / "annotations")
    records = client.get("/api/annotations").json()
    assert len(records) == len(list((SYNTHETIC / "ddx" / "annotations").glob("*/*.json")))
    assert all(set(r) == {"annotatorId", "patientId", "updatedAt", "annotations"} for r in records)


def test_verification_view_has_no_data(api):
    client, _ = api
    assert client.get("/api/verification70").status_code == 404
