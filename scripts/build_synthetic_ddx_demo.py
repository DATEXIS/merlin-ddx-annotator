#!/usr/bin/env python
"""Build the synthetic DDx-annotation inputs from ``examples/synthetic/ddx/demo_cases.json``.

Writes, in the formats the study's annotation server read and wrote:

* ``examples/synthetic/data_root/app/patients.json`` (pilot cohort) and
  ``patients_test350.json`` (350-case study cohort): cases with their note
  sections, labs, discharge diagnosis, coder ICD codes, the ranked candidate list
  (``d1`` = highest cosine score) and the model rank labels (V1 / V2 / V3 / V4);
* ``examples/synthetic/data_root/app/model_reasoning*.json``: the per-stage model
  rationales shown on hover;
* ``examples/synthetic/ddx/annotations/<rater>/<case>.json`` and
  ``examples/synthetic/ddx/custom_diagnoses/<case>.json``: synthetic annotation
  records and added ("Other Disease") diagnoses, exactly as the backend stores them;
* ``examples/synthetic/ddx/reference/diagnoses/<chief_complaint>.csv``: synthetic
  candidate schemes (disease, ICD-10 regex, symptom features) in the layout the
  original analysis reads.

The annotator list (``data_root/app/annotators.json``) is written by
``scripts/build_synthetic_demo.py`` and includes the DDx annotators listed here.
All content is synthetic. ``--check`` verifies the committed files are up to date.
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from merlin_ddx.annotation_store import normalize_annotations, validate_id  # noqa: E402

EXAMPLES = ROOT / "examples" / "synthetic"
DDX = EXAMPLES / "ddx"
SPEC = DDX / "demo_cases.json"
SAVED_AT = "2026-01-01T00:00:00Z"   # fixed so the build is deterministic
TOP_N_RANKS = 10                    # V1 shows the top 10 of the symptom dot-product ranking
STAGES = ("v1", "v2", "v3", "v4")
SECTION_TITLES = ["Service", "Allergies", "Attending", "Chief Complaint", "Major Surgical or Invasive Procedure",
                  "History of Present Illness", "Past Medical History", "Social History", "Family History",
                  "Physical Exam", "Pertinent Results", "Brief Hospital Course", "Medications on Admission",
                  "Discharge Medications", "Facility", "Discharge Disposition", "Discharge Diagnosis",
                  "Discharge Condition", "Discharge Instructions", "Followup Instructions"]
SERVICE = {"chest_pain": "MEDICINE", "cough": "MEDICINE", "abdominal_pain": "SURGERY", "headache": "NEUROLOGY",
           "back_pain": "MEDICINE", "diarrhea": "MEDICINE", "dyspnea": "MEDICINE"}


def load_spec() -> dict:
    return json.loads(SPEC.read_text(encoding="utf-8"))


def norm_icd(code: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(code).upper())


def chief(case: dict) -> str:
    return case["id"].split("-", 1)[1]


def scheme_rows(spec: dict, cc: str) -> dict[str, tuple[str, list[int]]]:
    return {name: (regex, features) for name, regex, features in spec["schemes"][cc]}


def v1_ranking(spec: dict, cc: str, preds: list[int]) -> list[str]:
    """Top-10 diseases by dot product of the model's symptom vector with each disease's
    feature vector, ties broken alphabetically (the rule of the original analysis)."""
    scored = [(name, sum(p * f for p, f in zip(preds, features)))
              for name, (_regex, features) in scheme_rows(spec, cc).items()]
    scored.sort(key=lambda item: (-item[1], item[0]))
    return [name for name, _ in scored[:TOP_N_RANKS]]


def icd_rank(regex: str, codes: list[str]) -> int | None:
    pattern = re.compile(regex)
    for rank, code in enumerate((norm_icd(c) for c in codes), start=1):
        if pattern.search(code):
            return rank
    return None


def stage_ranks(spec: dict, case: dict, model: str) -> dict[str, dict[str, int]]:
    """Rank of each candidate in each stage of one model (1-based; absent = not ranked)."""
    cc = chief(case)
    prediction = case["predictions"][model]
    regexes = scheme_rows(spec, cc)
    ranks: dict[str, dict[str, int]] = {}
    lists = {"v1": v1_ranking(spec, cc, prediction["v1"]), "v2": prediction["v2"], "v3": prediction["v3"]}
    for stage, ranking in lists.items():
        for position, name in enumerate(ranking, start=1):
            ranks.setdefault(name, {})[stage] = position
    for name in case["candidates"]:
        position = icd_rank(regexes[name][0], prediction["v4"])
        if position is not None:
            ranks.setdefault(name, {})["v4"] = position
    return ranks


def reason(case: dict, model: str, stage: str, name: str, rank: int, code: str | None = None) -> str:
    finding = case["findings"].get(name)
    model_label = {"llama": "Llama", "qwen": "Qwen", "medgemma": "MedGemma"}[model]
    if stage == "v2":
        lead = "From the admission note"
    elif stage == "v3":
        lead = "Taking the laboratory results into account"
    else:
        lead = f"ICD-10 {code} codes this diagnosis"
    support = f"the note documents {finding}" if finding else "it remains in the differential with fewer supporting findings"
    return f"[synthetic {model_label} rationale, rank {rank}] {lead}: {support}."


def build_case(spec: dict, case: dict) -> tuple[dict, dict]:
    cc = chief(case)
    validate_id("patient_id", case["id"])
    regexes = scheme_rows(spec, cc)
    unknown = [name for name in case["candidates"] if name not in regexes]
    if unknown or sorted(case["candidates"]) != sorted(regexes):
        raise SystemExit(f"{case['id']}: candidates must be exactly the {cc} scheme")
    ids = {name: f"d{i}" for i, name in enumerate(case["candidates"], start=1)}
    n = len(case["candidates"])
    diagnoses = []
    for i, name in enumerate(case["candidates"], start=1):
        entry = {"id": ids[name], "label": name, "rank": i, "score": round(0.82 - 0.035 * (i - 1), 3)}
        position = icd_rank(regexes[name][0], [c for c, _ in case["icd"]])
        if position is not None:
            entry["icd_rank"] = position
        diagnoses.append(entry)
    existing, reasoning = [], {}
    for model, model_name in spec["models"].items():
        ranks = stage_ranks(spec, case, model)
        model_diagnoses = {}
        for name in case["candidates"]:
            stage_rank = ranks.get(name, {})
            if not stage_rank:
                continue
            label = " / ".join(str(stage_rank.get(stage, "_")) for stage in STAGES)
            existing.append({"annotatorId": model, "diagnosisId": ids[name], "value": None, "rankLabel": label})
            entry = {}
            for stage in ("v2", "v3", "v4"):
                if stage in stage_rank:
                    code = None
                    if stage == "v4":
                        code = next(c for c in case["predictions"][model]["v4"]
                                    if re.search(regexes[name][0], norm_icd(c)))
                    entry[stage] = {"rank": stage_rank[stage], "reason": reason(case, model, stage, name,
                                                                                  stage_rank[stage], code)}
                    if code:
                        entry[stage]["icdCode"] = code
            if entry:
                model_diagnoses[ids[name]] = entry
        reasoning[model] = {"modelName": model_name, "diagnoses": model_diagnoses}
    note = case["note"]
    content = {
        "Service": SERVICE[cc], "Allergies": "No known drug allergies",
        "Chief Complaint": cc.replace("_", " "),
        "History of Present Illness": note["hpi"], "Past Medical History": note["pmh"],
        "Social History": "Synthetic case; social history not recorded.",
        "Physical Exam": note["exam"], "Pertinent Results": note["results"],
        "Brief Hospital Course": note["course"],
        "Medications on Admission": "See the synthetic history above.",
        "Discharge Medications": "Continued as described in the hospital course.",
        "Discharge Disposition": "Home", "Discharge Diagnosis": note["dd"],
        "Discharge Condition": "Synthetic case: stable at discharge.",
        "Discharge Instructions": "Synthetic case: return if symptoms recur.",
    }
    number = case["id"].split("-", 1)[0]
    patient = {
        "id": case["id"], "note_id": f"{number}-DS-1", "subject_id": f"S{number}", "hadm_id": number,
        "name": f"{number} ({cc})", "chief_complaint": cc, "split": case["split"],
        "labs": note["labs"], "dischargeDiagnosis": note["dd"],
        "groundTruthIcdCodes": [{"code": code, "longDescription": text} for code, text in case["icd"]],
        "sections": [{"title": title, "content": content.get(title, "")} for title in SECTION_TITLES],
        "diagnoses": diagnoses,
        "existingAnnotations": existing,
    }
    if case["dataset"] != "pilot":
        patient["dataset"] = case["dataset"]
    return patient, {"patientId": case["id"], "models": reasoning}


def build_records(spec: dict) -> tuple[dict[Path, bytes], list[str]]:
    files: dict[Path, bytes] = {}
    human = {a["id"] for a in spec["annotators"] if a["type"] == "human"} | {"synthetic_rater_1", "synthetic_rater_2"}
    for case in spec["cases"]:
        ids = {name: f"d{i}" for i, name in enumerate(case["candidates"], start=1)}
        custom = []
        for index, item in enumerate(case.get("custom", []), start=1):
            if item["label"] in ids:
                raise SystemExit(f"{case['id']}: added diagnosis {item['label']!r} is already a candidate")
            custom.append({"id": f"o{index}", "label": item["label"], "createdBy": item["createdBy"],
                           "createdAt": SAVED_AT})
        custom_ids = {item["label"]: item["id"] for item in custom}
        if custom:
            files[DDX / "custom_diagnoses" / f"{case['id']}.json"] = (json.dumps(custom, indent=2) + "\n").encode()
        for rater, labels in case["ratings"].items():
            if rater not in human:
                raise SystemExit(f"{case['id']}: unknown rater {rater}")
            marks = {(ids.get(label) or custom_ids[label]): True for label in labels}
            record = {"annotatorId": validate_id("annotator_id", rater), "patientId": case["id"],
                      "updatedAt": SAVED_AT, "annotations": normalize_annotations(marks)}
            files[DDX / "annotations" / rater / f"{case['id']}.json"] = (json.dumps(record, indent=2) + "\n").encode()
    return files, sorted(human)


def scheme_csv(spec: dict, cc: str) -> bytes:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(["Disease", "Synonyms", "icd10_regex", *spec["features"]])
    for name, regex, features in spec["schemes"][cc]:
        writer.writerow([name, "", regex, *features])
    return buffer.getvalue().encode("utf-8")


def build() -> dict[Path, bytes]:
    spec = load_spec()
    files: dict[Path, bytes] = {}
    app = EXAMPLES / "data_root" / "app"
    for dataset, suffix in (("pilot", ""), ("test350", "_test350")):
        patients, reasoning = [], {}
        for case in (c for c in spec["cases"] if c["dataset"] == dataset):
            patient, model_reasoning = build_case(spec, case)
            patients.append(patient)
            reasoning[case["id"]] = model_reasoning
        files[app / f"patients{suffix}.json"] = (json.dumps(patients, indent=2) + "\n").encode()
        files[app / f"model_reasoning{suffix}.json"] = (json.dumps({"patients": reasoning}, indent=2) + "\n").encode()
    records, _ = build_records(spec)
    files.update(records)
    for cc in sorted(spec["schemes"]):
        files[DDX / "reference" / "diagnoses" / f"{cc}.csv"] = scheme_csv(spec, cc)
    return files


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true", help="verify the committed files instead of writing them")
    args = parser.parse_args()
    files = build()
    stale = [path for path, data in files.items() if not path.is_file() or path.read_bytes() != data]
    owned = [DDX / "annotations", DDX / "custom_diagnoses", DDX / "reference" / "diagnoses"]
    extra = [p for d in owned if d.exists() for p in d.rglob("*") if p.is_file() and p not in files]
    if args.check:
        for path in stale + extra:
            print(f"out of date: {path.relative_to(ROOT)}")
        return 1 if stale or extra else 0
    for path in extra:
        path.unlink()
    for path, data in files.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    print(f"wrote {len(files)} files ({len(stale)} changed)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
