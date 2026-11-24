"""The original DDx analysis on the synthetic demonstration cases, checked against hand calculation.

Synthetic cases (examples/synthetic/ddx/demo_cases.json); cosine reference = first candidate,
ICD reference = candidate matching the earliest coder ICD code:

  pilot   900101 ACS/ACS            rater 1: ACS
          900102 bronchitis/flu     rater 1: influenza
          900103 appendicitis/chole rater 1: cholecystitis + choledocholithiasis
          900104 migraine/SAH       rater 1: SAH
  study   900201 disc/osteomyelitis rater 1: osteomyelitis + abscess; 2, 3: osteomyelitis
          900202 C. diff/med.-ind.  rater 1, 2: added diagnosis; 3: medication-induced
          900203 ADHF/ADHF          rater 1, 3: ADHF
          900204 ACS/PE             rater 1, 2: PE
          900205 COPD/pneumonia     rater 1: pneumonia; 2: COPD exacerbation
"""
from __future__ import annotations

import argparse
import contextlib
import io
import json
from fractions import Fraction
from pathlib import Path

import pytest

from conftest import load_script


@pytest.fixture(scope="module")
def runs(tmp_path_factory) -> dict[str, Path]:
    out = tmp_path_factory.mktemp("ddx")
    fixture = out / "fixture"
    load_script("make_synthetic_ddx_fixture").build(fixture)
    wrapper = load_script("run_ddx_analysis")
    results = {}
    for command in ("pilot", "study"):
        args = argparse.Namespace(command=command, fixture=fixture, data_root=None, pool=None, diagnoses=None,
                                  sample_csv=None, sample_meta=None, annotators_json=None, annotators=None,
                                  annotator="synthetic_rater_1", cohort=None, exclude_cc=[], out=out / command)
        with contextlib.redirect_stdout(io.StringIO()):
            results[command] = wrapper.run(wrapper.resolve(args))
    agreement = load_script("ddx_agreement")
    results["agreement"] = out / "agreement.json"
    with contextlib.redirect_stdout(io.StringIO()):
        data = agreement.compute(fixture / "data_root", fixture / "pool.pq", fixture / "diagnoses",
                                 fixture / "sample.csv", ["synthetic_rater_1", "synthetic_rater_2", "synthetic_rater_3"])
    results["agreement"].write_text(json.dumps(data))
    return results


def _summary(directory: Path, suffix: str) -> dict:
    return json.loads((directory / f"summary{suffix}.json").read_text())


@pytest.mark.parametrize("suffix, n, icd, cosine, disagree", [
    ("", 4, 1.0, 0.25, 3), ("_train", 2, 1.0, 0.5, 1), ("_test", 2, 1.0, 0.0, 2)])
def test_pilot_reference_agreement(runs, suffix, n, icd, cosine, disagree):
    s = _summary(runs["pilot"], suffix)
    assert s["n_cases"] == n                                   # only pilot records, no 350-case records
    assert s["clinician_vs_icd_agree"] == [icd, n]
    assert s["clinician_vs_cosine_agree"] == [cosine, n]
    assert s["tiebreak"] == {"n_disagree": disagree, "backs_cosine": 0, "backs_icd": disagree, "backs_neither": 0}
    assert s["ceiling_true_in_list"] == 1.0


@pytest.mark.parametrize("rater, n, icd, cosine, tiebreak, ceiling", [
    ("synthetic_rater_1", 5, 0.8, 0.2, (4, 3, 0, 1), 0.8),
    ("synthetic_rater_2", 4, 0.5, 0.25, (4, 2, 1, 1), 0.75),
    ("synthetic_rater_3", 3, 1.0, 1 / 3, (2, 2, 0, 0), 1.0)])
def test_study_reference_agreement(runs, rater, n, icd, cosine, tiebreak, ceiling):
    s = _summary(runs["study"], f"_{rater}")
    assert s["n_cases"] == n
    assert s["clinician_vs_icd_agree"][0] == pytest.approx(icd)
    assert s["clinician_vs_cosine_agree"][0] == pytest.approx(cosine)
    t = s["tiebreak"]
    assert (t["n_disagree"], t["backs_icd"], t["backs_cosine"], t["backs_neither"]) == tiebreak
    assert s["ceiling_true_in_list"] == pytest.approx(ceiling)


def test_pairwise_kappa_matches_hand_calculation_and_the_published_matrix_form(runs):
    reliability = json.loads((runs["study"] / "reliability_summary.json").read_text())
    pairs = {row["pair"]: row for row in reliability["pairwise"]}
    # raters 1 and 2: 4 shared cases, 45 candidates; both 3, only 1: 2, only 2: 1, neither 39
    p_o = Fraction(42, 45)
    p_e = Fraction(5, 45) * Fraction(4, 45) + Fraction(40, 45) * Fraction(41, 45)
    assert pairs["synthetic_rater_1 vs synthetic_rater_2"]["n"] == 4
    assert pairs["synthetic_rater_1 vs synthetic_rater_2"]["kappa"] == pytest.approx(float((p_o - p_e) / (1 - p_e)))
    agreement = json.loads(runs["agreement"].read_text())
    for pair in agreement["pairs"]:
        name = f"{pair['first']} vs {pair['second']}"
        assert pair["contingency"]["kappa"] == pytest.approx(pairs[name]["kappa"], abs=1e-12)
        assert pair["n_kappa_cases"] == pairs[name]["n"]
    first = agreement["pairs"][0]["contingency"]
    assert (first["both_selected"], first["only_first"], first["only_second"], first["neither"]) == (3, 2, 1, 39)
    assert reliability["fleiss_n"] == 2


def test_set_statistics_and_coverage(runs):
    a = json.loads(runs["agreement"].read_text())
    assert (a["cases_with_at_least_two_annotators"], a["cases_with_all_annotators"]) == (5, 2)
    r1 = a["per_annotator"]["synthetic_rater_1"]
    assert (r1["completed_records"], r1["positive_selections"], r1["added_diagnosis_selections"]) == (5, 6, 1)
    assert r1["multi_label_rate"] == pytest.approx(0.2)
    first = a["pairs"][0]                                   # raters 1 and 2
    assert first["identical_sets"] == 2 and first["exact_set_agreement"] == pytest.approx(0.5)
    assert first["mean_jaccard"] == pytest.approx((0.5 + 1 + 1 + 0) / 4)
    assert first["second_within_first"] == 3 and first["first_strictly_within_second"] == 0


def test_full_size_fixture_has_the_study_shape(tmp_path):
    fixture = load_script("make_synthetic_ddx_fixture").build(tmp_path / "full", full_size=True)
    agreement = load_script("ddx_agreement")
    with contextlib.redirect_stdout(io.StringIO()):
        data = agreement.compute(fixture["data_root"], fixture["pool"], fixture["diagnoses"], fixture["sample_csv"],
                                 ["synthetic_rater_1", "synthetic_rater_2", "synthetic_rater_3"])
    assert data["frame_size"] == 350
    assert data["per_annotator"]["synthetic_rater_1"]["completed_by_chief_complaint"] == {
        cc: 50 for cc in ("abdominal_pain", "back_pain", "chest_pain", "cough", "diarrhea", "dyspnea", "headache")}
    assert len(json.loads(fixture["pilot_cohort"].read_text())) == 70
