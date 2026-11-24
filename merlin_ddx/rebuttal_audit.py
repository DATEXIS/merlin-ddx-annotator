"""Serve only the prepared, blinded audit material and store clinician judgments."""
from __future__ import annotations

import csv
import re
from collections import OrderedDict
from pathlib import Path
from zipfile import ZipFile

from fastapi import HTTPException


ANSWER_FIELDS = (
    "A_Q1", "A_Q2", "B_Q1", "B_Q2",
)
LEGACY_ANSWER_FIELDS = {
    "A_Q1": "A_Q1_evidence_grounded", "A_Q2": "A_Q2_supports_target",
    "B_Q1": "B_Q1_evidence_grounded", "B_Q2": "B_Q2_supports_target",
}
ALLOWED_ANSWERS = {"Yes", "No", "Unclear"}
ALLOWED_TARGET_PREFERENCES = {"A", "B", "Equal"}
ALLOWED_RATIONALE_PREFERENCES = {"A", "B", "Equivalent"}


def normalize_code(code: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", code.upper())


def display_code(code: str) -> str:
    return code[:3] + "." + code[3:] if len(code) > 3 else code


def descriptions(data_root: Path) -> dict[str, str]:
    # The complete, public FY2026 ICD-10-CM catalog; never use patient GT codes.
    archive_path = data_root / "source" / "icd10cm-Code-Descriptions-2026.zip"
    try:
        with ZipFile(archive_path) as archive:
            lines = archive.read("icd10cm-order-2026.txt").decode("cp1252").splitlines()
    except (FileNotFoundError, KeyError) as exc:
        raise HTTPException(status_code=503, detail="ICD-10-CM description catalog unavailable") from exc
    return {normalize_code(line[6:13]): line[77:].strip() for line in lines}


def describe(code: str, catalog: dict[str, str]) -> tuple[str, str | None]:
    normalized = normalize_code(code)
    if normalized in catalog:
        return catalog[normalized], None
    for length in range(len(normalized) - 1, 2, -1):
        parent = normalized[:length]
        if parent in catalog:
            return catalog[parent], display_code(parent)
    return "No catalog description available", None


def load_cases(data_root: Path) -> list[dict]:
    source = data_root / "source" / "merlin_rebuttal_audit"
    try:
        with (source / "audit_batch1_notes.csv").open(newline="", encoding="utf-8-sig") as handle:
            notes = {row["hadm_id"]: row["admission_note"] for row in csv.DictReader(handle)}
        with (source / "audit_batch1_blinded.csv").open(newline="", encoding="utf-8-sig") as handle:
            rows = list(csv.DictReader(handle))
    except FileNotFoundError as exc:
        raise HTTPException(status_code=503, detail="Blinded audit dataset unavailable") from exc
    catalog = None
    cases: OrderedDict[str, dict] = OrderedDict()
    for row in rows:
        hadm_id = row["hadm_id"]
        if hadm_id not in notes:
            raise HTTPException(status_code=500, detail="Audit note missing")
        case = cases.setdefault(hadm_id, {
            "hadm_id": hadm_id,
            "chief_complaint": row["chief_complaint"],
            "admission_note": notes[hadm_id],
            "pairs": [],
        })
        pair = {key: row[key] for key in (
            "pair_id", "hadm_id", "stage", "target_A", "reason_A", "target_B", "reason_B",
        )}
        if pair["stage"] not in {"V1", "V2", "V3", "V4"}:
            raise HTTPException(status_code=500, detail="Unsupported reasoning stage")
        if row.get("target_format") in {"stage_output", "reference_label", "label_comparison"}:
            pair["target_format"] = row["target_format"]
            pair["clinical_context"] = row.get("clinical_context", "")
        if pair.get("target_format") == "reference_label":
            if not row.get("label_source") or not pair["target_A"] or any(
                    pair[field] for field in ("reason_A", "target_B", "reason_B")):
                raise HTTPException(status_code=500, detail="Malformed reference label case")
            pair["label_source"] = row["label_source"]
        if pair.get("target_format") == "label_comparison":
            if not pair["target_A"] or not pair["target_B"] or pair["reason_A"] or pair["reason_B"]:
                raise HTTPException(status_code=500, detail="Malformed label comparison")
        if pair["stage"] == "V4" and pair.get("target_format") not in {"stage_output", "reference_label", "label_comparison"}:
            if catalog is None:
                catalog = descriptions(data_root)
            for arm in "AB":
                description, category = describe(pair[f"target_{arm}"], catalog)
                pair[f"description_{arm}"] = description
                pair[f"description_category_{arm}"] = category
        case["pairs"].append(pair)
    for case in cases.values():
        case["pairs"].sort(key=lambda pair: {"V1": 0, "V2": 1, "V3": 2, "V4": 3}[pair["stage"]])
    return list(cases.values())


def validate_answers(hadm_id: str, pairs: dict[str, dict], cases: list[dict]) -> None:
    case = next((case for case in cases if case["hadm_id"] == hadm_id), None)
    if case is None:
        raise HTTPException(status_code=404, detail="Audit admission not found")
    expected = {pair["pair_id"]: pair for pair in case["pairs"]}
    if not set(pairs).issubset(expected):
        raise HTTPException(status_code=400, detail="Unknown pair_id for admission")
    allowed = {
        *ANSWER_FIELDS, *LEGACY_ANSWER_FIELDS.values(),
        "target_preference_A_B_equal", "rationale_preference_A_B_equal",
        "preference_A_B_equivalent", "rater_comment", "pair_id", "hadm_id",
    }
    for pair_id, answer in pairs.items():
        if expected[pair_id].get("target_format") == "label_comparison":
            fields = ("A_label_validity", "B_label_validity")
            if not set(answer).issubset({*fields, "target_preference_A_B_equal", "rater_comment", "pair_id", "hadm_id"}):
                raise HTTPException(status_code=400, detail="Unexpected label comparison field")
            if answer.get("pair_id", pair_id) != pair_id or answer.get("hadm_id", hadm_id) != hadm_id:
                raise HTTPException(status_code=400, detail="Label identifiers do not match")
            if any(answer.get(field) not in (None, "", *ALLOWED_ANSWERS) for field in fields):
                raise HTTPException(status_code=400, detail="Invalid label judgment")
            preference = answer.get("target_preference_A_B_equal")
            if preference not in (None, *ALLOWED_TARGET_PREFERENCES):
                raise HTTPException(status_code=400, detail="Invalid label preference")
            if expected[pair_id]["target_A"] == expected[pair_id]["target_B"] and preference is not None:
                raise HTTPException(status_code=400, detail="Identical labels cannot have a preference")
            if preference and not all(answer.get(field) in ALLOWED_ANSWERS for field in fields):
                raise HTTPException(status_code=400, detail="Comparison requires both label judgments")
            if not isinstance(answer.get("rater_comment", ""), str):
                raise HTTPException(status_code=400, detail="Invalid comment")
            continue
        if expected[pair_id].get("target_format") == "reference_label":
            if not set(answer).issubset({"label_validity", "suggested_label", "rater_comment",
                                         "pair_id", "hadm_id"}):
                raise HTTPException(status_code=400, detail="Unexpected reference answer field")
            if answer.get("pair_id", pair_id) != pair_id or answer.get("hadm_id", hadm_id) != hadm_id:
                raise HTTPException(status_code=400, detail="Reference identifiers do not match")
            if answer.get("label_validity") not in (None, "", *ALLOWED_ANSWERS):
                raise HTTPException(status_code=400, detail="Invalid reference judgment")
            if any(not isinstance(answer.get(field, ""), str)
                   for field in ("suggested_label", "rater_comment")):
                raise HTTPException(status_code=400, detail="Invalid reference review text")
            continue
        if not set(answer).issubset(allowed):
            raise HTTPException(status_code=400, detail="Unexpected answer field")
        if answer.get("pair_id", pair_id) != pair_id or answer.get("hadm_id", hadm_id) != hadm_id:
            raise HTTPException(status_code=400, detail="Pair identifiers do not match")
        if any(answer.get(field) not in (None, "", *ALLOWED_ANSWERS)
               for field in (*ANSWER_FIELDS, *LEGACY_ANSWER_FIELDS.values())):
            raise HTTPException(status_code=400, detail="Invalid validity judgment")
        target_preference = answer.get("target_preference_A_B_equal")
        rationale_preference = answer.get("rationale_preference_A_B_equal")
        legacy_preference = answer.get("preference_A_B_equivalent")
        if target_preference not in (None, *ALLOWED_TARGET_PREFERENCES):
            raise HTTPException(status_code=400, detail="Invalid target preference")
        if rationale_preference not in (None, *ALLOWED_RATIONALE_PREFERENCES):
            raise HTTPException(status_code=400, detail="Invalid rationale preference")
        if legacy_preference not in (None, "", *ALLOWED_RATIONALE_PREFERENCES):
            raise HTTPException(status_code=400, detail="Invalid legacy preference")
        if expected[pair_id]["target_A"] == expected[pair_id]["target_B"] and target_preference is not None:
            raise HTTPException(status_code=400, detail="Identical targets cannot have a target preference")
        judged = all(
            (answer.get(field) or answer.get(LEGACY_ANSWER_FIELDS[field])) in ALLOWED_ANSWERS
            for field in ANSWER_FIELDS
        )
        if (target_preference or rationale_preference or legacy_preference) and not judged:
            raise HTTPException(status_code=400, detail="Comparisons require four validity judgments")
        if not isinstance(answer.get("rater_comment", ""), str):
            raise HTTPException(status_code=400, detail="Invalid comment")
