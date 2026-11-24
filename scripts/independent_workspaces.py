#!/usr/bin/env python3
"""Prepare and collect physically separate local rater workspaces.

Only new, generated study inputs are supported. Keep all paths in authorized
storage. A workspace contains exactly one rater, no allocation key or peers.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil

from merlin_ddx.annotation_store import validate_id, write_json_atomic
from merlin_ddx.rebuttal_audit import load_cases, validate_answers
from export_annotations import read_json


def prepare(study, out):
    study, out = Path(study).resolve(), Path(out).resolve()
    root = study / "annotation_inputs"
    if out.exists() or out.is_relative_to(root) or root.is_relative_to(out):
        raise ValueError("Use a fresh separate workspace directory")
    manifest = read_json(study / "private_analysis" / "manifest.json")
    if "input_hashes" in manifest:
        from build_study import freeze
        freeze(study)
    raters = read_json(root / "app" / "annotators.json")
    if not raters or any(r["type"] != "human" for r in raters):
        raise ValueError("Independent mode supports human-only new studies")
    ids = [validate_id("annotator_id", r["id"]) for r in raters]
    if len(ids) != len(set(ids)) or any(i in (".", "..") for i in ids):
        raise ValueError("Invalid rater identities")
    out.mkdir(mode=0o700, parents=True)
    for rater in raters:
        dest = out / rater["id"]
        dest.mkdir(mode=0o700)
        app = dest / "app"
        app.mkdir()
        write_json_atomic(app / "annotators.json", [rater])
        if manifest["study_type"] == "ddx":
            patients = read_json(root / "app" / "patients_study.json")
            if any(p.get("existingAnnotations") or p.get("groundTruthIcdCodes") or
                   any("score" in d or "icd_rank" in d for d in p["diagnoses"]) for p in patients):
                raise ValueError("DDx input includes model or reference overlays")
            shutil.copy2(root / "app" / "patients_study.json", app / "patients_study.json")
        else:
            source = dest / "source" / "merlin_rebuttal_audit"
            source.mkdir(parents=True)
            for name in ("audit_batch1_blinded.csv", "audit_batch1_notes.csv"):
                shutil.copy2(root / "source" / "merlin_rebuttal_audit" / name, source / name)
            load_cases(dest)
        write_json_atomic(dest / "workspace.json", {"study_id": manifest["study_id"],
                                                   "study_type": manifest["study_type"], "rater": rater["id"]})
    return len(raters)


def collect(study, workspaces):
    """Validate frozen workspaces and copy ratings once; never overwrite ratings."""
    study, workspaces = Path(study), Path(workspaces)
    root = study / "annotation_inputs"
    manifest = read_json(study / "private_analysis" / "manifest.json")
    if "input_hashes" in manifest:
        from build_study import freeze
        freeze(study)
    raters = read_json(root / "app" / "annotators.json")
    ddx = manifest["study_type"] == "ddx"
    cases = read_json(root / "app" / "patients_study.json") if ddx else load_cases(root)
    known = {c["id" if ddx else "hadm_id"]: c for c in cases}
    pending = []
    custom = {}
    for rater in raters:
        rid = validate_id("annotator_id", rater["id"])
        source = workspaces / rid
        if read_json(source / "workspace.json") != {"study_id": manifest["study_id"],
                                                       "study_type": manifest["study_type"], "rater": rid}:
            raise ValueError("Workspace identity mismatch")
        if ddx:
            files = [Path("app/patients_study.json")]
        else:
            files = [Path("source/merlin_rebuttal_audit") / name
                     for name in ("audit_batch1_blinded.csv", "audit_batch1_notes.csv")]
        if any((source / f).read_bytes() != (root / f).read_bytes() for f in files):
            raise ValueError("Workspace case data changed")
        folder = "annotations" if ddx else "rebuttal_audit_annotations"
        for path in sorted((source / folder / rid).glob("*.json")):
            record = read_json(path)
            cid = record["patientId" if ddx else "hadm_id"]
            if record["annotatorId"] != rid or cid not in known or path.name != cid + ".json":
                raise ValueError("Unexpected workspace rating")
            if ddx:
                extra_path = source / "custom_diagnoses" / (cid + ".json")
                extras = read_json(extra_path) if extra_path.is_file() else []
                id_map = {}
                for item in extras:
                    label = item["label"].strip()
                    if not label or item["createdBy"] != rid:
                        raise ValueError("Unexpected custom diagnosis")
                    # Resolve independently allocated o1/o2 IDs by label only.
                    fixed = {d["label"].strip().casefold(): d["id"] for d in known[cid]["diagnoses"]}
                    normalized = label.casefold()
                    if normalized in fixed:
                        new_id = fixed[normalized]
                    else:
                        new_id = "other-" + hashlib.sha256(normalized.encode()).hexdigest()
                        custom.setdefault(cid, {}).setdefault(new_id, {**item, "id": new_id})
                    id_map[item["id"]] = new_id
                allowed = {d["id"] for d in known[cid]["diagnoses"]} | set(id_map)
                if not set(record["annotations"]) <= allowed or any(type(v) is not bool for v in record["annotations"].values()):
                    raise ValueError("Unknown or invalid DDx selection")
                remapped = {}
                for key, value in record["annotations"].items():
                    target = id_map.get(key, key)
                    remapped[target] = remapped.get(target, False) or value
                record["annotations"] = remapped
            else:
                validate_answers(cid, record["pairs"], cases)
            pending.append((root / folder / rid / path.name, record))
    pending.extend((root / "custom_diagnoses" / (cid + ".json"), list(items.values()))
                   for cid, items in custom.items())
    if any(path.exists() for path, _ in pending):
        raise ValueError("Collection would overwrite existing records; use a fresh master study")
    for path, record in pending:
        write_json_atomic(path, record)
    return len(pending)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="command", required=True)
    for command in ("prepare", "collect"):
        sp = sub.add_parser(command)
        sp.add_argument("--study", required=True, type=Path)
        sp.add_argument("--workspaces", required=True, type=Path)
    args = p.parse_args()
    count = (prepare if args.command == "prepare" else collect)(args.study, args.workspaces)
    print(f"{args.command}: {count} records/workspaces.")


if __name__ == "__main__":
    main()
