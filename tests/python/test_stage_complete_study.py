"""New-study importer/exporter round trip; synthetic inputs only."""
import json
from pathlib import Path
import sys

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
from build_annotation_cases import STAGES, build
from export_annotations import export
from analyze_annotation_study import analyze
from merlin_ddx.rebuttal_audit import load_cases
from merlin_ddx.sync_api import create_app


def make_input(path, model):
    rows = []
    for stage in STAGES:
        rows.append({"hadm_id": "SYNCASE", "model": model, "stage": stage, "label_origin": "generated",
                     "split": "test", "chief_complaint": "synthetic complaint",
                     "admission_note": "Synthetic admission note.",
                     "clinical_context": "Synthetic laboratory results." if stage in ("V3", "V4") else "",
                     "target": json.dumps({"synthetic": model, "stage": stage}),
                     "reason": "Synthetic rationale.", "trace_id": f"{model}-{stage}",
                     "verifier_score": 0.5})
    path.write_text("".join(json.dumps(r) + "\n" for r in rows))


def test_four_stage_roundtrip(tmp_path):
    left, right = tmp_path / "left.jsonl", tmp_path / "right.jsonl"
    make_input(left, "synthetic-left")
    make_input(right, "synthetic-right")
    study = tmp_path / "study"
    manifest = build(left, right, "synthetic-left", "synthetic-right", STAGES, "test", study)
    assert manifest["selected_pairs"] == 4
    root = study / "annotation_inputs"
    cases = load_cases(root)
    assert [pair["stage"] for pair in cases[0]["pairs"]] == list(STAGES)
    assert cases[0]["hadm_id"] != "SYNCASE"
    assert cases[0]["pairs"][0]["clinical_context"] == ""
    assert cases[0]["pairs"][2]["clinical_context"] == "Synthetic laboratory results."
    assert all("verifier_score" not in p for p in cases[0]["pairs"])
    assert not (root / "private_analysis").exists()
    client = TestClient(create_app(data_root=root, sync_git=False))
    case = client.get("/api/rebuttal-audit").json()[0]
    raters = client.get("/api/annotators").json()
    answers = {}
    for pair in case["pairs"]:
        answers[pair["pair_id"]] = {"A_Q1": "Yes", "A_Q2": "Yes", "B_Q1": "Yes",
                                   "B_Q2": "Unclear", "target_preference_A_B_equal": "A",
                                   "rationale_preference_A_B_equal": "A"}
    with pytest.raises(ValueError, match="incomplete"):
        export(study, tmp_path / "empty")
    for rater in raters:
        response = client.put(f"/api/rebuttal-audit/annotations/{rater['id']}/{case['hadm_id']}",
                              json={"pairs": answers})
        assert response.status_code == 200
    out = tmp_path / "export"
    assert export(study, out)["incomplete_rater_pairs"] == 0
    rows = [json.loads(line) for line in (out / "trace_ratings.jsonl").read_text().splitlines()]
    assert len(rows) == 8
    assert all(row["source_hadm_id"] == "SYNCASE" for row in rows)
    assert all(sum(row["composite_votes"].values()) == 2 for row in rows)
    assert all(row["source_sha256"] for row in rows)
    result = analyze(rows, replicates=10)
    assert set(result["stage_results"]) == set(STAGES)
    assert all(v["paired_differences"]["composite"]["ci95"] is None for v in result["stage_results"].values())
    with pytest.raises(ValueError, match="outside"):
        export(study, root / "export")
    again = tmp_path / "again"
    build(left, right, "synthetic-left", "synthetic-right", STAGES, "test", again)
    for path in (root / "source").rglob("*.csv"):
        assert path.read_bytes() == (again / "annotation_inputs" / path.relative_to(root)).read_bytes()


def test_mismatched_context_rejected(tmp_path):
    left, right = tmp_path / "left.jsonl", tmp_path / "right.jsonl"
    make_input(left, "left")
    make_input(right, "right")
    right.write_text(right.read_text().replace("Synthetic laboratory results.", "Different synthetic labs."))
    with pytest.raises(ValueError, match="different stage-specific"):
        build(left, right, "left", "right", STAGES, "test", tmp_path / "study")


def test_raw_parquet(tmp_path):
    pd = pytest.importorskip("pandas")
    rows = []
    for model in ("left", "right"):
        row = {"hadm_id": "SYNCASE", "gen_model": model, "split": "test",
               "Chief Complaint": "synthetic complaint", "admission_note": "Synthetic note.",
               "labs": "Synthetic labs."}
        for stage in STAGES:
            row[f"{stage.lower()}_json"] = json.dumps({"synthetic": model})
            row[f"{stage.lower()}_text"] = "Synthetic raw response."
            row[f"{stage.lower()}_score"] = 0.5
        rows.append(row)
    path = tmp_path / "combined.pq"
    pd.DataFrame(rows).to_parquet(path, index=False)
    study = tmp_path / "study"
    assert build(path, path, "left", "right", STAGES, "test", study)["selected_pairs"] == 4
    cases = load_cases(study / "annotation_inputs")
    assert "Synthetic labs." in cases[0]["pairs"][3]["clinical_context"]
    assert cases[0]["pairs"][1]["clinical_context"] == ""
