"""The synthetic demonstration set is up to date, clearly synthetic, blinded and covers the rubric."""
from __future__ import annotations

import csv
import json
import subprocess
import sys

from conftest import ROOT, SYNTHETIC

SPEC = json.loads((SYNTHETIC / "demo_cases.json").read_text(encoding="utf-8"))


def test_generated_files_are_up_to_date():
    for script in ("build_synthetic_demo.py", "demo_summary.py"):
        result = subprocess.run([sys.executable, str(ROOT / "scripts" / script), "--check"], capture_output=True, text=True)
        assert result.returncode == 0, result.stderr


def test_every_case_and_comment_is_labelled_synthetic():
    assert SPEC["_about"].startswith("SYNTHETIC")
    for case in SPEC["cases"]:
        assert case["hadm_id"].startswith("SYN")
        assert case["admission_note"].startswith("SYNTHETIC CASE")
    comments = [a["comment"] for r in SPEC["ratings"].values() for a in r.values() if a.get("comment")]
    assert comments and all(c.startswith("SYNTHETIC") for c in comments)
    assert all(r["name"].startswith("Synthetic") for r in SPEC["raters"])


def test_allocation_key_is_kept_out_of_the_served_data():
    served = SYNTHETIC / "data_root"
    assert not list(served.rglob("*key*"))
    with (served / "source/merlin_rebuttal_audit/audit_batch1_blinded.csv").open(newline="", encoding="utf-8") as handle:
        header = next(csv.reader(handle))
    assert not [c for c in header if c.startswith("_") or "arm" in c or "score" in c or "accept" in c]


def test_demo_covers_the_original_rubric():
    answers = [a for rater in SPEC["ratings"].values() for a in rater.values()]
    judgments = {a[q] for a in answers for q in ("A_Q1", "A_Q2", "B_Q1", "B_Q2")}
    assert judgments == {"Yes", "No", "Unclear"}
    assert {a["target"] for a in answers} == {"A", "B", "Equal", None}
    assert {a["rationale"] for a in answers} == {"A", "B", "Equivalent"}
    pairs = [p for c in SPEC["cases"] for p in c["pairs"]]
    assert {p["stage"] for p in pairs} == {"V2", "V4"}
    assert any(p["A"]["target"] == p["B"]["target"] for p in pairs)          # target question not applicable
    assert any(p["A"]["target"] != p["B"]["target"] for p in pairs)
    assert {p["A"]["arm"] for p in pairs} == {"loop", "zero_shot"}            # both arms appear in position A
    assert {p["loop_accepted"] for p in pairs} == {True, False}
    first, second = (SPEC["ratings"][r["id"]] for r in SPEC["raters"])
    assert any(first[k] == second[k] for k in first) and any(first[k] != second[k] for k in first)
    summary = json.loads((SYNTHETIC / "expected" / "demo_summary.json").read_text(encoding="utf-8"))
    assert summary["n_comments"] >= 2
