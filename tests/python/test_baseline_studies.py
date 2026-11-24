"""Baseline integration: config, standalone traces, isolated raters and DDx."""
import json
from pathlib import Path
import sys

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
from build_study import build, freeze
from independent_workspaces import prepare, collect
from export_annotations import export
from analyze_interrater_agreement import analyze, kappa
from analyze_annotation_study import analyze_single_reasoning, analyze_ddx
from merlin_ddx.sync_api import create_app


def rows(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


def test_standalone_isolated_roundtrip(tmp_path):
    path = tmp_path / "generated.jsonl"
    path.write_text(json.dumps({"hadm_id": "SYNCASE", "model": "synthetic", "stage": "V1",
        "split": "test", "chief_complaint": "synthetic", "admission_note": "Synthetic note.",
        "clinical_context": "", "target": '{"symptom A":1}', "reason": "Synthetic rationale.",
        "trace_id": "synthetic-1", "label_origin": "generated", "verifier_score": .5}) + "\n")
    study = tmp_path / "study"
    config = {"study_type": "single_reasoning", "path": str(path), "model": "synthetic",
              "stages": ["V1"], "split": "test", "rubric_version": "baseline-v1.2"}
    manifest = build(config, study)
    assert freeze(study) == manifest
    workspaces = tmp_path / "workspaces"
    assert prepare(study, workspaces) == 2
    raters = sorted(workspaces.iterdir())
    for i, workspace in enumerate(raters):
        client = TestClient(create_app(data_root=workspace, sync_git=False))
        rid = workspace.name
        other = raters[1-i].name
        assert [a["id"] for a in client.get("/api/annotators").json()] == [rid]
        assert client.get(f"/api/rebuttal-audit/annotations/{other}").status_code == 403
        assert client.get("/api/evaluation-overlays").status_code == 403
        assert not (workspace / "private_analysis").exists()
        case = client.get("/api/rebuttal-audit").json()[0]
        pair = case["pairs"][0]
        assert pair["target_format"] == "single_reasoning" and not pair["target_B"]
        url = f"/api/rebuttal-audit/annotations/{rid}/{case['hadm_id']}"
        assert client.put(url, json={"pairs": {pair["pair_id"]: {"B_Q1": "Yes"}}}).status_code == 400
        assert client.put(url, json={"pairs": {pair["pair_id"]: {"A_Q1": "Yes", "A_Q2": "No" if i else "Yes"}}}).status_code == 200
        assert client.put(f"/api/rebuttal-audit/annotations/{other}/{case['hadm_id']}",
                          json={"pairs": {}}).status_code == 403
    assert collect(study, workspaces) == 2
    with pytest.raises(ValueError, match="overwrite"):
        collect(study, workspaces)
    out = tmp_path / "export"
    assert export(study, out)["incomplete_rater_traces"] == 0
    data = rows(out / "single_reasoning_ratings.jsonl")
    assert data[0]["composite_votes"] == {"Yes": 1, "No": 1}
    assert analyze_single_reasoning(data, replicates=5)["single_reasoning_results"][0]["metrics"]["composite"]["rate"] == .5
    agreements = analyze(study)["pairwise_agreement"]
    assert len(agreements) == 2
    assert all(a["n"] == 1 for a in agreements)
    assert freeze(study) == manifest
    note = study / "annotation_inputs/source/merlin_rebuttal_audit/audit_batch1_notes.csv"
    note.write_text(note.read_text() + "\n")
    with pytest.raises(ValueError, match="changed"):
        freeze(study)


def test_ddx_import_isolation_and_custom_id_remapping(tmp_path):
    pd = pytest.importorskip("pandas")
    path = tmp_path / "combined.pq"
    row = {"hadm_id": "SYNCASE", "split": "test", "Chief Complaint": "synthetic complaint",
           "admission_note": "Synthetic admission.", "discharge_note": "Synthetic discharge.",
           "labs": "Synthetic labs."}
    pd.DataFrame([row, row]).to_parquet(path, index=False)
    schemes = tmp_path / "schemes"
    schemes.mkdir()
    (schemes / "synthetic_complaint.csv").write_text("Disease,Synonyms\nAlpha,A\nBeta,B\n")
    study = tmp_path / "study"
    assert build({"study_type": "ddx", "path": str(path), "schemes": str(schemes)}, study)["selected_admissions"] == 1
    workspaces = tmp_path / "workspaces"
    prepare(study, workspaces)
    for i, workspace in enumerate(sorted(workspaces.iterdir())):
        client = TestClient(create_app(data_root=workspace, sync_git=False))
        rid = workspace.name
        case = client.get("/api/patients").json()[0]
        assert case["dataset"] == "study" and case["existingAnnotations"] == []
        assert "groundTruthIcdCodes" not in case
        cid = case["id"]
        assert client.get(f"/api/model-reasoning/{cid}").status_code == 403
        assert client.get("/api/annotations").json() == []
        custom = client.post(f"/api/custom-diagnoses/{cid}", json={"label": "Gamma" if i else "Delta", "createdBy": rid})
        assert custom.status_code == 200
        extra = custom.json()["id"]
        assert extra == "o1"
        result = client.put(f"/api/annotations/{rid}/{cid}", json={"annotations": {case["diagnoses"][0]["id"]: True, extra: True}})
        assert result.status_code == 200
    assert collect(study, workspaces) == 3
    out = tmp_path / "export"
    assert export(study, out)["incomplete_rater_cases"] == 0
    data = rows(out / "ddx_ratings.jsonl")
    assert data[0]["other_selected_label_count"] == 2
    assert analyze_ddx(data)["ddx_results"][0]["mean_selections_per_completed_case"] == 2
    agreement = analyze(study)["pairwise_agreement"][0]
    assert agreement["exact_set_agreement"] == 0
    assert agreement["mean_jaccard"] == pytest.approx(1/3)
    assert agreement["fixed_candidate_agreement"]["kappa"] == 1


def test_kappa_degenerate_and_complete():
    assert kappa([])["kappa"] is None
    assert kappa([("Yes", "Yes")])["kappa"] is None
    assert kappa([("Yes", "Yes"), ("No", "No")])["kappa"] == 1
    assert kappa([("Yes", "No"), ("No", "Yes")])["kappa"] == -1
