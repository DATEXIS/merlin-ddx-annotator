"""Standalone reference-label review; all data are synthetic."""
import json
from pathlib import Path
import sys

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
from build_reference_cases import build
from export_annotations import export
from analyze_annotation_study import analyze_reference
from merlin_ddx.rebuttal_audit import load_cases
from merlin_ddx.sync_api import create_app


def test_raw_reference_roundtrip(tmp_path):
    pd = pytest.importorskip("pandas")
    path = tmp_path / "combined.pq"
    pd.DataFrame([{
        "hadm_id": "SYNCASE", "gen_model": "synthetic", "split": "test",
        "Chief Complaint": "synthetic complaint", "admission_note": "Synthetic admission evidence.",
        "discharge_note": "Synthetic discharge evidence.", "labs": "Synthetic laboratory evidence.",
        "disease_vector": [1, 0, -1], "disease": "Synthetic diagnosis",
        "ICD_CODES": ["Z00.0"], "v2_json": "THIS GENERATED OUTPUT MUST NOT BE USED",
    }]).to_parquet(path, index=False)
    schema = tmp_path / "schema.json"
    schema.write_text(json.dumps({"synthetic_complaint": ["symptom A", "symptom B", "symptom C"]}))
    study = tmp_path / "study"
    assert build(path, study, ["V1", "V2", "V3", "V4"], "test",
                 model="synthetic", schema_path=schema)["selected_labels"] == 4
    root = study / "annotation_inputs"
    case = load_cases(root)[0]
    pairs = case["pairs"]
    assert all(p["target_format"] == "reference_label" for p in pairs)
    assert all(not p["reason_A"] and not p["target_B"] for p in pairs)
    assert json.loads(pairs[0]["target_A"]) == {"symptom A": 1, "symptom B": 0, "symptom C": -1}
    assert "not patient-specific" in pairs[0]["label_source"]
    assert not pairs[0]["clinical_context"]
    assert pairs[1]["target_A"] == "Synthetic diagnosis"
    assert "Synthetic laboratory evidence." in pairs[2]["clinical_context"]
    assert json.loads(pairs[3]["target_A"]) == ["Z00.0"]
    assert "THIS GENERATED OUTPUT" not in json.dumps(case)
    client = TestClient(create_app(data_root=root, sync_git=False))
    raters = client.get("/api/annotators").json()
    url = f"/api/rebuttal-audit/annotations/{raters[0]['id']}/{case['hadm_id']}"
    assert client.put(url, json={"pairs": {pairs[0]["pair_id"]: {"A_Q1": "Yes"}}}).status_code == 400
    assert client.put(url, json={"pairs": {pairs[0]["pair_id"]: {"label_validity": "Invalid"}}}).status_code == 400
    for rater in raters:
        url = f"/api/rebuttal-audit/annotations/{rater['id']}/{case['hadm_id']}"
        answers = {p["pair_id"]: {"label_validity": "Yes" if p["stage"] != "V1" else "No",
                                  "suggested_label": "Synthetic correction" if p["stage"] == "V1" else ""}
                   for p in pairs}
        assert client.put(url, json={"pairs": answers}).status_code == 200
    out = tmp_path / "export"
    assert export(study, out)["incomplete_rater_labels"] == 0
    assert not (out / "trace_ratings.jsonl").exists()
    assert not (out / "private_suggested_corrections.jsonl").exists()
    labels = [json.loads(line) for line in (out / "label_ratings.jsonl").read_text().splitlines()]
    assert all(r["label_origin"] == "reference" and "verifier_score" not in r for r in labels)
    assert labels[0]["label_validity_votes"] == {"No": 2}
    assert labels[0]["n_suggestions"] == 2
    result = analyze_reference(labels, replicates=10)
    assert len(result["reference_results"]) == 4
    assert result["reference_results"][0]["reference_supported_rate"] == 0
    private = tmp_path / "private_export"
    export(study, private, include_corrections=True)
    corrections = [json.loads(line) for line in (private / "private_suggested_corrections.jsonl").read_text().splitlines()]
    assert corrections[0]["suggestions"] == [{"suggested_label": "Synthetic correction", "count": 2}]


def test_patient_specific_reference_jsonl(tmp_path):
    path = tmp_path / "reference.jsonl"
    path.write_text(json.dumps({
        "hadm_id": "SYNCASE", "stage": "V1", "split": "test", "chief_complaint": "synthetic",
        "admission_note": "Synthetic note.", "clinical_context": "",
        "target": '{"symptom A": 1}', "label_source": "Patient-specific synthetic human annotation",
        "label_id": "synthetic-label-1",
    }) + "\n")
    study = tmp_path / "study"
    build(path, study, ["V1"], "test")
    assert load_cases(study / "annotation_inputs")[0]["pairs"][0]["label_source"].startswith("Patient-specific")
    with pytest.raises(ValueError, match="incomplete"):
        export(study, tmp_path / "export")
