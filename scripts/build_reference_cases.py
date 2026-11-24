#!/usr/bin/env python3
"""Prepare standalone reference-label reviews, without generated rationales."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import random
import sys

from build_annotation_cases import STAGES, PAIR_COLUMNS, digest, text, write_csv

LABEL_COLUMNS = (*PAIR_COLUMNS, "label_source")


def raw_labels(path, model, stages, schema, retrospective, *, include_v4_labs=False):
    import pandas as pd
    if not model:
        raise ValueError("Raw Parquet requires --source-model to select one storage row per admission")
    fields = {"hadm_id", "gen_model", "split", "Chief Complaint", "admission_note"}
    if "V1" in stages:
        fields.add("disease_vector")
        if not schema:
            raise ValueError("V1 prototype review requires the ordered symptom schema")
    if {"V2", "V3"} & set(stages):
        fields.add("disease")
    if "V4" in stages:
        fields.add("ICD_CODES")
    if "V3" in stages or (include_v4_labs and "V4" in stages):
        fields.add("labs")
    if retrospective and set(stages) - {"V1"}:
        fields.add("discharge_note")
    frame = pd.read_parquet(path)
    if not fields.issubset(frame.columns):
        raise ValueError("Raw table is missing required reference columns")
    for row in frame.to_dict("records"):
        if row["gen_model"] != model:
            continue
        complaint = str(row["Chief Complaint"])
        for stage in stages:
            if stage == "V1":
                vector_text = text(row["disease_vector"])
                if not vector_text:
                    continue
                vector = json.loads(vector_text)
                names = schema.get(complaint.lower().replace(" ", "_"))
                if (not isinstance(names, list) or not names
                        or not all(isinstance(n, str) and n.strip() for n in names)
                        or len(set(names)) != len(names) or not isinstance(vector, list)
                        or len(vector) != len(names)
                        or any(type(v) not in (int, float) or v not in (-1, 0, 1) for v in vector)):
                    raise ValueError("Disease vector does not match the ordered manifestation schema")
                target = json.dumps(dict(zip(names, (int(v) for v in vector))), ensure_ascii=False, indent=2)
                source = "WikiDoc disease prototype (not patient-specific symptom ground truth)"
            elif stage in ("V2", "V3"):
                target = text(row["disease"])
                source = "Mapped WikiDoc diagnosis reference"
            else:
                codes = text(row["ICD_CODES"])
                if not codes:
                    continue
                parsed = json.loads(codes)
                if not isinstance(parsed, list) or not parsed or not all(isinstance(c, str) and c.strip() for c in parsed):
                    raise ValueError("Expected a nonempty list of recorded ICD codes")
                target = json.dumps(parsed, ensure_ascii=False, indent=2)
                source = "Recorded MIMIC-IV discharge ICD codes"
            if not target.strip():
                continue
            context = []
            if stage == "V3" or (include_v4_labs and stage == "V4"):
                labs = text(row.get("labs"))
                if not labs.strip():
                    continue
                context.append("Laboratory evidence:\n" + labs)
            if retrospective and stage != "V1":
                discharge = text(row.get("discharge_note"))
                if not discharge.strip():
                    continue
                context.append("Retrospective discharge documentation:\n" + discharge)
            yield {"hadm_id": str(row["hadm_id"]), "stage": stage, "split": str(row["split"]),
                   "chief_complaint": complaint, "admission_note": text(row["admission_note"]),
                   "clinical_context": "\n\n".join(context), "target": target,
                   "label_source": source, "label_id": f"{row['hadm_id']}:{stage}", "label_origin": "reference"}


def read_labels(path, model, stages, schema, retrospective, *, include_v4_labs=False):
    if path.suffix.lower() in (".pq", ".parquet"):
        yield from raw_labels(path, model, stages, schema, retrospective, include_v4_labs=include_v4_labs)
    elif path.suffix.lower() == ".jsonl":
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                if line.strip():
                    yield json.loads(line)
    else:
        raise ValueError("Expected raw .pq/.parquet or explicit label .jsonl")


def build(path, out, stages, split, *, model=None, schema_path=None, retrospective=True,
          seed=42, n=None, raters=2):
    from merlin_ddx.rebuttal_audit import load_cases
    path, out = Path(path), Path(out)
    if out.exists():
        raise ValueError("Output must be a new directory")
    if not stages or len(set(stages)) != len(stages) or not set(stages) <= set(STAGES):
        raise ValueError("Choose unique stages V1–V4")
    if raters < 1 or (n is not None and n < 1):
        raise ValueError("Positive sample and rater counts required")
    schema = None if schema_path is None else json.loads(Path(schema_path).read_text(encoding="utf-8"))
    settings = {"study_type": "reference_label", "source_sha256": digest(path), "storage_model": model,
                "schema_sha256": digest(Path(schema_path)) if schema_path else None,
                "stages": list(stages), "split": split, "retrospective_raw_context": retrospective,
                "seed": seed, "n": n, "raters": raters}
    study_id = hashlib.sha256(json.dumps(settings, sort_keys=True).encode()).hexdigest()[:20]
    fields = ("hadm_id", "stage", "split", "chief_complaint", "admission_note",
              "clinical_context", "target", "label_source", "label_id")
    records = {}
    for row in read_labels(path, model, stages, schema, retrospective):
        if any(not isinstance(row.get(f), str) for f in fields):
            raise ValueError("Reference rows require explicit string fields")
        if row["split"] != split or row["stage"] not in stages:
            continue
        if row.get("label_origin") != "reference":
            raise ValueError("Reference input requires label_origin=reference")
        if any(not row[f].strip() for f in fields if f != "clinical_context"):
            raise ValueError("Reference row has an empty required field")
        if row["stage"] == "V3" and not row["clinical_context"].strip():
            raise ValueError("V3 reference review requires laboratory evidence")
        key = (row["hadm_id"], row["stage"])
        if key in records:
            raise ValueError("Duplicate admission/stage reference")
        records[key] = row
    eligible = sorted({case for case, _ in records if all((case, stage) in records for stage in stages)})
    if not eligible or (n is not None and n > len(eligible)):
        raise ValueError("Insufficient complete reference cases")
    selected = random.Random(seed).sample(eligible, n if n is not None else len(eligible))
    notes, rows, labels = [], [], []
    for i, case in enumerate(selected, 1):
        case_id = f"{study_id}-{i:06d}"
        first = records[case, stages[0]]
        notes.append({"hadm_id": case_id, "chief_complaint": first["chief_complaint"],
                      "admission_note": first["admission_note"]})
        for stage in stages:
            record = records[case, stage]
            if any(record[f] != first[f] for f in ("admission_note", "chief_complaint")):
                raise ValueError("Reference stages have inconsistent admission evidence")
            pair_id = f"{case_id}-{stage}"
            rows.append({"pair_id": pair_id, "hadm_id": case_id, "chief_complaint": first["chief_complaint"],
                         "stage": stage, "target_A": record["target"], "reason_A": "", "target_B": "",
                         "reason_B": "", "target_format": "reference_label",
                         "clinical_context": record["clinical_context"], "label_source": record["label_source"]})
            labels.append({"pair_id": pair_id, "case_id": case_id, "source_hadm_id": case,
                           "stage": stage, "label_id": record["label_id"], "label_origin": "reference",
                           "label_source": record["label_source"], "source_sha256": settings["source_sha256"],
                           "label_sha256": hashlib.sha256(record["target"].encode("utf-8")).hexdigest()})
    root = out / "annotation_inputs"
    source = root / "source" / "merlin_rebuttal_audit"
    write_csv(source / "audit_batch1_blinded.csv", rows, LABEL_COLUMNS)
    write_csv(source / "audit_batch1_notes.csv", notes, ("hadm_id", "chief_complaint", "admission_note"))
    app = root / "app"
    app.mkdir()
    (app / "annotators.json").write_text(json.dumps([
        {"id": f"{study_id}-r{i}", "name": f"Rater {i}", "type": "human", "active": True}
        for i in range(1, raters + 1)], indent=2) + "\n", encoding="utf-8")
    private = out / "private_analysis"
    private.mkdir(mode=0o700)
    (private / "reference_key.json").write_text(json.dumps(labels, indent=2) + "\n", encoding="utf-8")
    manifest = {**settings, "study_id": study_id, "eligible_admissions": len(eligible),
                "selected_admissions": len(selected), "selected_labels": len(labels)}
    (private / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    cases = load_cases(root)
    if len(cases) != len(selected) or sum(len(c["pairs"]) for c in cases) != len(labels):
        raise ValueError("Reference inputs failed backend validation")
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--source-model")
    parser.add_argument("--symptom-schema-json", type=Path,
                        help="Complaint key to ordered manifestation names, matching upstream schema order")
    parser.add_argument("--stages", nargs="+", choices=STAGES, default=["V2", "V3", "V4"])
    parser.add_argument("--split", choices=("train", "dev", "test"), default="test")
    parser.add_argument("--admission-only", action="store_true",
                        help="Omit discharge documentation for raw sources (V3 still includes labs)")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--n", type=int)
    parser.add_argument("--raters", type=int, default=2)
    args = parser.parse_args()
    result = build(args.input, args.out, args.stages, args.split, model=args.source_model,
                   schema_path=args.symptom_schema_json, retrospective=not args.admission_only,
                   seed=args.seed, n=args.n, raters=args.raters)
    print(f"Prepared {result['selected_admissions']} admissions and {result['selected_labels']} reference labels.")


if __name__ == "__main__":
    main()
