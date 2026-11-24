"""The synthetic DDx demonstration data: up to date, synthetic, and in the study's formats."""
from __future__ import annotations

import json
import re

from conftest import ROOT, SYNTHETIC, load_script
from merlin_ddx.annotation_store import read_annotation_record

APP = SYNTHETIC / "data_root" / "app"
DDX = SYNTHETIC / "ddx"


def _patients() -> list[dict]:
    return json.loads((APP / "patients.json").read_text()) + json.loads((APP / "patients_test350.json").read_text())


def test_generated_files_are_up_to_date():
    demo = load_script("build_synthetic_ddx_demo")
    stale = [p for p, data in demo.build().items() if not p.is_file() or p.read_bytes() != data]
    assert not stale, [str(p.relative_to(ROOT)) for p in stale]


def test_cohorts_have_the_study_layout():
    pilot = json.loads((APP / "patients.json").read_text())
    study = json.loads((APP / "patients_test350.json").read_text())
    assert {p["split"] for p in pilot} == {"train", "test"} and all("dataset" not in p for p in pilot)
    assert {(p["split"], p["dataset"]) for p in study} == {("test", "test350")}
    assert not {p["id"] for p in pilot} & {p["id"] for p in study}
    for patient in pilot + study:
        assert re.fullmatch(r"9\d{5}-[a-z_]+", patient["id"])
        assert patient["sections"][5]["title"] == "History of Present Illness"
        assert patient["sections"][5]["content"].startswith("SYNTHETIC CASE - not a real patient.")
        assert [d["id"] for d in patient["diagnoses"]] == [f"d{i}" for i in range(1, len(patient["diagnoses"]) + 1)]
        assert len(patient["diagnoses"]) > 10            # exercises the "show more" control


def test_rank_labels_follow_the_synthetic_predictions():
    demo = load_script("build_synthetic_ddx_demo")
    spec = demo.load_spec()
    cases = {c["id"]: c for c in spec["cases"]}
    for patient in _patients():
        case = cases[patient["id"]]
        labels = {d["id"]: d["label"] for d in patient["diagnoses"]}
        for entry in patient["existingAnnotations"]:
            v1, v2, v3, v4 = entry["rankLabel"].split(" / ")
            prediction = case["predictions"][entry["annotatorId"]]
            name = labels[entry["diagnosisId"]]
            assert v2 == (str(prediction["v2"].index(name) + 1) if name in prediction["v2"] else "_")
            assert v3 == (str(prediction["v3"].index(name) + 1) if name in prediction["v3"] else "_")
            ranking = demo.v1_ranking(spec, demo.chief(case), prediction["v1"])
            assert v1 == (str(ranking.index(name) + 1) if name in ranking else "_")


def test_annotation_records_are_valid_and_resolve():
    patients = {p["id"]: p for p in _patients()}
    records = sorted((DDX / "annotations").glob("*/*.json"))
    assert {p.parent.name for p in records} == {"synthetic_rater_1", "synthetic_rater_2", "synthetic_rater_3"}
    for path in records:
        record = read_annotation_record(path)
        assert record.annotator_id == path.parent.name and record.patient_id == path.stem
        custom_path = DDX / "custom_diagnoses" / f"{path.stem}.json"
        custom = {c["id"] for c in json.loads(custom_path.read_text())} if custom_path.is_file() else set()
        candidates = {d["id"] for d in patients[path.stem]["diagnoses"]}
        assert set(record.annotations) <= candidates | custom


def test_demonstrates_selection_added_diagnosis_multiple_raters_and_models():
    spec = load_script("build_synthetic_ddx_demo").load_spec()
    ratings = [labels for case in spec["cases"] for labels in case["ratings"].values()]
    assert any(len(labels) > 1 for labels in ratings)                                   # multi-label
    assert any(case.get("custom") for case in spec["cases"])                             # added diagnosis
    assert max(len(case["ratings"]) for case in spec["cases"]) == 3                     # three raters
    reasoning = json.loads((APP / "model_reasoning_test350.json").read_text())["patients"]
    assert set(reasoning["900201-back_pain"]["models"]) == {"llama", "qwen", "medgemma"}
    annotators = json.loads((APP / "annotators.json").read_text())
    assert {a["id"] for a in annotators if a["type"] == "llm"} == {"llama", "qwen", "medgemma"}
    assert [a["id"] for a in annotators if a["type"] == "human"] == [
        "synthetic_rater_1", "synthetic_rater_2", "synthetic_rater_3"]


def test_no_verification_data_is_shipped():
    assert not list((SYNTHETIC / "data_root").rglob("verification70*"))
