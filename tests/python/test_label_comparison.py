"""Blinded comparison of raw generated and reference labels; synthetic data only."""
import json
from pathlib import Path
import sys

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
from build_label_comparison_cases import build, canonical
from export_annotations import export
from analyze_annotation_study import analyze_label_comparison
from merlin_ddx.rebuttal_audit import load_cases
from merlin_ddx.sync_api import create_app


def test_label_projection():
    assert canonical("V2", '[{"name":"A","reason":"private"},{"name":"B"}]', "generated") == "A"
    assert canonical("V2", "A", "reference") == "A"
    assert canonical("V1", '{"a":{"value":1,"reasoning":"private"}}', "generated") == canonical("V1", '{"a":1}', "reference")
    assert canonical("V4", '[{"icd_code":"Z00.0","reason":"private"},{"icd_code":"Z000"}]', "generated") == canonical("V4", '["Z000"]', "reference")
    assert canonical("V4", "[]", "generated") == "[]"
    with pytest.raises(ValueError):
        canonical("V1", '{"a":true}', "reference")


def test_raw_label_comparison_roundtrip(tmp_path):
    pd = pytest.importorskip("pandas")
    path = tmp_path / "combined.pq"
    pd.DataFrame([{
        "hadm_id": "SYNCASE", "gen_model": "synthetic", "split": "test",
        "Chief Complaint": "synthetic complaint", "admission_note": "Synthetic note.",
        "labs": "Synthetic labs.", "disease_vector": [1, 0], "disease": "Reference diagnosis",
        "ICD_CODES": ["Z00.0"],
        "v1_json": '{"symptom A":{"value":0,"reasoning":"PRIVATE"},"symptom B":{"value":0}}',
        "v2_json": '[{"name":"Generated diagnosis","reason":"PRIVATE"},{"name":"Reference diagnosis"}]',
        "v3_json": '[{"name":"Generated diagnosis","reason":"PRIVATE"}]',
        "v4_json": '[{"icd_code":"Z00.0","reason":"PRIVATE"}]',
        "v2_score": 0.5,
    }]).to_parquet(path, index=False)
    schema = tmp_path / "schema.json"
    schema.write_text(json.dumps({"synthetic_complaint": ["symptom A", "symptom B"]}))
    study = tmp_path / "study"
    stages = ["V1", "V2", "V3", "V4"]
    assert build(path, path, "synthetic", stages, "test", study, schema_path=schema)["selected_pairs"] == 4
    root = study / "annotation_inputs"
    case = load_cases(root)[0]
    assert case["hadm_id"] != "SYNCASE"
    assert [p["stage"] for p in case["pairs"]] == stages
    assert all(p["target_format"] == "label_comparison" and p["reason_A"] == p["reason_B"] == "" for p in case["pairs"])
    assert "PRIVATE" not in json.dumps(case)
    assert all("label_source" not in p and "verifier_score" not in p for p in case["pairs"])
    assert case["pairs"][2]["clinical_context"] == "Synthetic labs."
    assert case["pairs"][3]["target_A"] == case["pairs"][3]["target_B"]
    key = json.loads((study / "private_analysis" / "label_comparison_key.json").read_text())
    client = TestClient(create_app(data_root=root, sync_git=False))
    raters = client.get("/api/annotators").json()
    for i, rater in enumerate(raters):
        url = f"/api/rebuttal-audit/annotations/{rater['id']}/{case['hadm_id']}"
        assert client.put(url, json={"pairs": {key[0]["pair_id"]: {"A_Q1": "Yes"}}}).status_code == 400
        answers = {}
        for row, pair in zip(key, case["pairs"]):
            same = pair["target_A"] == pair["target_B"]
            generated_arm = next(a for a, meta in row["arms"].items() if meta["label_origin"] == "generated")
            reference_arm = "B" if generated_arm == "A" else "A"
            answers[row["pair_id"]] = {
                f"{generated_arm}_label_validity": "Yes",
                f"{reference_arm}_label_validity": "Yes" if same else ("No" if i == 0 else "Unclear"),
                "target_preference_A_B_equal": None if same else generated_arm,
            }
        assert client.put(url, json={"pairs": answers}).status_code == 200
    out = tmp_path / "export"
    assert export(study, out)["incomplete_rater_pairs"] == 0
    rows = [json.loads(line) for line in (out / "label_comparison_ratings.jsonl").read_text().splitlines()]
    assert not (out / "trace_ratings.jsonl").exists()
    assert not (out / "label_ratings.jsonl").exists()
    assert rows[0]["joint_votes"] == [
        {"generated": "Yes", "reference": "No", "count": 1},
        {"generated": "Yes", "reference": "Unclear", "count": 1},
    ]
    assert rows[3]["preference_votes"] == {"Not applicable": 2}
    result = analyze_label_comparison(rows, replicates=10)["label_comparison_results"]
    assert result[0]["generated_only_supported"] == 1
    assert result[0]["at_least_one_unclear"] == 1
    assert result[0]["reference_only_supported"] == 0
    assert result[0]["paired_ci95"] is None
    assert result[3]["both_supported"] == 2


def test_mismatched_context(tmp_path):
    generated, reference = tmp_path / "g.jsonl", tmp_path / "r.jsonl"
    common = {"hadm_id": "SYNCASE", "stage": "V3", "split": "test",
              "chief_complaint": "synthetic", "admission_note": "Synthetic note."}
    generated.write_text(json.dumps({**common, "model": "synthetic", "trace_id": "g",
        "label_origin": "generated", "target": '[{"name":"A"}]', "clinical_context": "Synthetic labs."}) + "\n")
    reference.write_text(json.dumps({**common, "label_id": "r", "label_source": "Synthetic reference",
        "label_origin": "reference", "target": "A", "clinical_context": "Different labs."}) + "\n")
    with pytest.raises(ValueError, match="different stage-specific"):
        build(generated, reference, "synthetic", ["V3"], "test", tmp_path / "study")
