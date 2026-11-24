"""The published rubric must match the rubric implemented in the study interface and server."""
from __future__ import annotations

import json
import re

from conftest import ROOT
from merlin_ddx import rebuttal_analysis, rebuttal_audit

RUBRIC = json.loads((ROOT / "config" / "rubric.json").read_text(encoding="utf-8"))
UI = (ROOT / "src" / "components" / "RebuttalAudit.tsx").read_text(encoding="utf-8")
RUBRIC_MD = (ROOT / "docs" / "rubric.md").read_text(encoding="utf-8")


def _criteria() -> dict[str, dict]:
    return {c["id"]: c for c in RUBRIC["criteria"]}


def test_every_clinician_facing_string_is_verbatim_in_the_interface():
    strings = []
    for criterion in RUBRIC["criteria"]:
        strings += list(criterion["wording"].values()) + list(criterion.get("helper_text", {}).values())
    assert strings
    for text in strings:
        assert text in UI, f"not in RebuttalAudit.tsx: {text!r}"
        assert text in RUBRIC_MD, f"not in docs/rubric.md: {text!r}"


def test_stage_specific_wording_is_assigned_to_the_right_stage():
    q2 = _criteria()["Q2_supports_target"]["wording"]
    assert q2["V2"] != q2["V4"]
    assert re.search(r"isV4\s*\?\s*'" + re.escape(q2["V4"]) + r"'\s*:\s*'" + re.escape(q2["V2"]) + "'", UI)


def test_response_options_match_server_validation_and_analysis():
    criteria = _criteria()
    stored = lambda cid: {o["stored_value"] for o in criteria[cid]["response_options"]}  # noqa: E731
    assert stored("Q1_evidence_grounded") == stored("Q2_supports_target") == rebuttal_audit.ALLOWED_ANSWERS
    assert stored("Q1_evidence_grounded") == rebuttal_analysis.VALID_JUDGMENTS
    assert stored("target_preference") == rebuttal_audit.ALLOWED_TARGET_PREFERENCES == rebuttal_analysis.TARGET_CHOICES
    assert stored("rationale_preference") == rebuttal_audit.ALLOWED_RATIONALE_PREFERENCES == rebuttal_analysis.RATIONALE_CHOICES
    for cid in ("target_preference", "rationale_preference"):
        for option in criteria[cid]["response_options"]:
            assert f"'{option['stored_value']}'" in UI


def test_stored_fields_match_the_server():
    criteria = _criteria()
    fields = criteria["Q1_evidence_grounded"]["original_fields"] + criteria["Q2_supports_target"]["original_fields"]
    assert set(fields) == set(rebuttal_audit.ANSWER_FIELDS)
    for cid in ("target_preference", "rationale_preference", "rater_comment"):
        for field in criteria[cid]["original_fields"]:
            assert field in UI


def test_composite_definition_matches_the_analysis():
    composite = next(d for d in RUBRIC["derived_measures"] if d["id"] == "valid_composite")
    assert "Q1 == 'Yes' and Q2 == 'Yes'" in composite["formula"]
    source = (ROOT / "merlin_ddx" / "rebuttal_analysis.py").read_text(encoding="utf-8")
    assert '(joined[f"{side}_Q1"] == "Yes") & (joined[f"{side}_Q2"] == "Yes")' in source
