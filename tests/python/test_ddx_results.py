"""The published DDx-annotation results: consistent, cohort-level only, and matching the documentation."""
from __future__ import annotations

import csv
import hashlib
import json
import re

from conftest import ROOT, load_script

RESULTS = ROOT / "results" / "ddx_annotation"


def _rows(name: str) -> list[dict]:
    with (RESULTS / name).open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def test_kappa_reproduces_from_the_published_matrices():
    assert load_script("ddx_kappa_from_contingency").main() == 0


def test_manifest_checksums():
    manifest = json.loads((RESULTS / "manifest.json").read_text())
    for name, entry in manifest["files"].items():
        assert hashlib.sha256((RESULTS / name).read_bytes()).hexdigest() == entry["sha256"], name


def test_no_case_or_clinician_identifiers():
    for path in RESULTS.rglob("*"):
        if path.is_file():
            text = path.read_text(encoding="utf-8")
            assert not re.search(r"(?<![\d.])[12]\d{7}(?![\d.])", text), path
            assert not re.search(r"\b\d{5,}-[a-z_]+\b", text), path              # case ids
            assert not re.search(r"clinician[123]\b", text), path               # internal rater ids


def test_documented_values_match_the_tables():
    agreement = {r["pair"]: r for r in _rows("inter_rater_agreement.csv")}
    one_two = agreement["Clinician 1 vs Clinician 2"]
    assert (round(float(one_two["cohen_kappa"]), 3), one_two["n_cases_kappa"]) == (0.913, "236")
    assert round(float(one_two["exact_set_agreement"]) * 100, 1) == 89.0
    assert round(float(one_two["mean_jaccard"]), 3) == 0.912
    one_three = agreement["Clinician 1 vs Clinician 3"]
    assert (one_three["second_within_first"], one_three["identical_sets"], one_three["n_cases_both_completed"]) == (
        "97", "82", "121")
    assert round(float(agreement["Clinicians 1, 2 and 3"]["fleiss_kappa"]), 3) == 0.811
    reference = {(r["cohort"], r["clinician"], r["subset"]): r for r in _rows("reference_agreement.csv")}
    first = reference[("study_350", "Clinician 1", "all")]
    assert round(float(first["agree_icd_reference"]) * 100, 1) == 77.1
    assert round(float(first["agree_cosine_reference"]) * 100, 1) == 68.0
    assert (first["clinician_backs_icd"], first["clinician_backs_cosine"], first["references_disagree"]) == (
        "71", "39", "127")
    coverage = {(r["cohort"], r["clinician"]): r for r in _rows("coverage.csv")}
    assert [coverage[("study_350", f"Clinician {i}")]["completed_records"] for i in (1, 2, 3)] == ["350", "236", "121"]
    manifest = json.loads((RESULTS / "manifest.json").read_text())
    assert manifest["coverage"]["study_350"] == {"frame": 350, "at_least_two_clinicians": 316,
                                                 "all_three_clinicians": 41}
    for document in (RESULTS / "README.md", ROOT / "docs" / "ddx_annotation" / "README.md", ROOT / "README.md"):
        text = document.read_text(encoding="utf-8")
        for value in ("0.913", "89.0%", "0.912", "77.1%", "68.0%"):
            assert value in text, (document.name, value)
