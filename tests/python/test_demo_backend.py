"""The unchanged study backend serves, validates, stores and exports synthetic ratings."""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from conftest import SYNTHETIC, load_script
from merlin_ddx.sync_api import create_app


@pytest.fixture
def client(demo_data_root):
    return TestClient(create_app(data_root=demo_data_root, sync_git=False)), demo_data_root


def _record(rater: str, case: str) -> dict:
    return json.loads((SYNTHETIC / "ratings" / rater / f"{case}.json").read_text(encoding="utf-8"))


def test_serves_blinded_cases_with_icd_descriptions(client):
    api, _ = client
    cases = api.get("/api/rebuttal-audit").json()
    assert [c["hadm_id"] for c in cases] == ["SYN001", "SYN002", "SYN003", "SYN004", "SYN005"]
    assert all([p["stage"] for p in c["pairs"]] == ["V2", "V4"] for c in cases)
    pair = cases[0]["pairs"][0]
    assert not any(k.startswith("_") or "arm" in k or "score" in k for k in pair)       # no allocation fields
    v4 = {p["pair_id"]: p for c in cases for p in c["pairs"] if p["stage"] == "V4"}
    assert v4["4"]["description_B"] == "Acute on chronic systolic (congestive) heart failure"
    assert v4["10"]["description_category_A"] == "R42"          # invalid code -> closest catalog category


def test_saves_and_exports_every_synthetic_rating(client, tmp_path):
    api, data_root = client
    for rater in ("synthetic_rater_1", "synthetic_rater_2"):
        for case in ("SYN001", "SYN002", "SYN003", "SYN004", "SYN005"):
            response = api.put(f"/api/rebuttal-audit/annotations/{rater}/{case}",
                               json={"pairs": _record(rater, case)["pairs"]})
            assert response.status_code == 200, response.text
        exported = api.get(f"/api/rebuttal-audit/annotations/{rater}").json()
        assert len(exported) == 5 and all(r["annotatorId"] == rater for r in exported)
    summary = load_script("demo_summary").summarize(data_root / "rebuttal_audit_annotations")
    expected = json.loads((SYNTHETIC / "expected" / "demo_summary.json").read_text(encoding="utf-8"))
    assert summary == expected


@pytest.mark.parametrize("change, detail", [
    ({"A_Q1": "Maybe"}, "Invalid validity judgment"),
    ({"pair_id": "2"}, "Pair identifiers do not match"),
    ({"A_Q2": None, "rationale_preference_A_B_equal": "A"}, "Comparisons require four validity judgments"),
    ({"unexpected": "x"}, "Unexpected answer field"),
])
def test_rejects_invalid_answers(client, change, detail):
    api, _ = client
    answer = {**_record("synthetic_rater_1", "SYN001")["pairs"]["1"], **change}
    response = api.put("/api/rebuttal-audit/annotations/synthetic_rater_1/SYN001", json={"pairs": {"1": answer}})
    assert response.status_code == 400 and detail in response.text


def test_identical_targets_cannot_take_a_target_preference(client):
    api, _ = client
    answer = {**_record("synthetic_rater_1", "SYN001")["pairs"]["2"], "target_preference_A_B_equal": "A"}
    response = api.put("/api/rebuttal-audit/annotations/synthetic_rater_1/SYN001", json={"pairs": {"2": answer}})
    assert response.status_code == 400 and "Identical targets" in response.text


def test_unknown_pair_and_unsafe_ids_are_rejected(client):
    api, _ = client
    answer = _record("synthetic_rater_1", "SYN001")["pairs"]["1"]
    assert api.put("/api/rebuttal-audit/annotations/synthetic_rater_1/SYN001",
                   json={"pairs": {"99": {**answer, "pair_id": "99"}}}).status_code == 400
    assert api.put("/api/rebuttal-audit/annotations/..%2Fescape/SYN001", json={"pairs": {}}).status_code in (400, 404)
