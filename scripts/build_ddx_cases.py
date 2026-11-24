#!/usr/bin/env python3
"""Prepare a new DDx candidate-selection cohort from raw MERLIN Parquet."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
import random
import re
import sys

from build_annotation_cases import digest, text


def build(path, schemes, out, *, split="test", seed=42, n=None, raters=2, retrospective=True):
    import pandas as pd
    path, schemes, out = map(Path, (path, schemes, out))
    if out.exists() or raters < 1 or (n is not None and n < 1):
        raise ValueError("Require new output directory and positive sample/rater counts")
    fields = ["hadm_id", "split", "Chief Complaint", "admission_note"]
    if retrospective:
        fields += ["discharge_note", "labs"]
    frame = pd.read_parquet(path, columns=fields)
    candidates = {}
    by_case = {}
    for row in frame.to_dict("records"):
        if row["split"] != split:
            continue
        complaint = str(row["Chief Complaint"]).strip().lower().replace(" ", "_")
        if not re.fullmatch(r"[a-z_]+", complaint):
            raise ValueError("Invalid complaint key")
        evidence = {k: text(row[k]) for k in fields if k not in ("hadm_id", "split")}
        if not evidence["admission_note"].strip() or (retrospective and not evidence["discharge_note"].strip()):
            continue
        case = str(row["hadm_id"])
        if case in by_case and by_case[case] != evidence:
            raise ValueError("Inconsistent duplicated admission evidence across generators")
        by_case[case] = evidence
        if complaint not in candidates:
            file = schemes / (complaint + ".csv")
            with file.open(encoding="utf-8-sig", newline="") as handle:
                labels = [r["Disease"].strip() for r in csv.DictReader(handle)]
            if not labels or any(not label for label in labels) or len(set(labels)) != len(labels):
                raise ValueError("Invalid candidate scheme")
            candidates[complaint] = (sorted(labels), digest(file))
    if not by_case or (n is not None and n > len(by_case)):
        raise ValueError("Insufficient eligible admissions")
    settings = {"study_type": "ddx", "source_sha256": digest(path), "split": split, "seed": seed,
                "n": n, "raters": raters, "retrospective": retrospective,
                "scheme_sha256": {k: v[1] for k, v in sorted(candidates.items())}}
    study_id = hashlib.sha256(json.dumps(settings, sort_keys=True).encode()).hexdigest()[:20]
    rng = random.Random(seed)
    selected = rng.sample(sorted(by_case), n if n is not None else len(by_case))
    patients, mapping = [], []
    for i, case in enumerate(selected, 1):
        evidence = by_case[case]
        complaint = evidence["Chief Complaint"].strip().lower().replace(" ", "_")
        labels = list(candidates[complaint][0])
        rng.shuffle(labels)
        case_id = f"{study_id}-{i:06d}"
        diagnoses = [{"id": f"d{j}", "label": label, "rank": j}
                     for j, label in enumerate(labels, 1)]
        sections = [{"title": "History of Present Illness", "content": evidence["admission_note"]}]
        if retrospective:
            sections.append({"title": "Brief Hospital Course", "content": evidence["discharge_note"]})
        patients.append({"id": case_id, "note_id": case_id, "subject_id": case_id, "hadm_id": case_id,
                         "name": f"Case {i}", "chief_complaint": complaint, "dataset": "study",
                         "sections": sections, "labs": evidence.get("labs", ""), "diagnoses": diagnoses,
                         "existingAnnotations": []})
        mapping.append({"case_id": case_id, "source_hadm_id": case, "chief_complaint": complaint,
                        "candidates": diagnoses})
    root = out / "annotation_inputs"
    app = root / "app"
    app.mkdir(parents=True)
    (app / "patients_study.json").write_text(json.dumps(patients, ensure_ascii=False, indent=2) + "\n")
    (app / "annotators.json").write_text(json.dumps([
        {"id": f"{study_id}-r{i}", "name": f"Rater {i}", "type": "human", "active": True}
        for i in range(1, raters + 1)], indent=2) + "\n")
    private = out / "private_analysis"
    private.mkdir(mode=0o700)
    (private / "ddx_key.json").write_text(json.dumps(mapping, ensure_ascii=False, indent=2) + "\n")
    manifest = {**settings, "study_id": study_id, "eligible_admissions": len(by_case),
                "selected_admissions": len(selected)}
    (private / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--schemes", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--split", choices=("train", "dev", "test"), default="test")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--n", type=int)
    parser.add_argument("--raters", type=int, default=2)
    parser.add_argument("--admission-only", action="store_true")
    args = parser.parse_args()
    result = build(args.input, args.schemes, args.out, split=args.split, seed=args.seed,
                   n=args.n, raters=args.raters, retrospective=not args.admission_only)
    print(f"Prepared {result['selected_admissions']} DDx cases.")


if __name__ == "__main__":
    main()
