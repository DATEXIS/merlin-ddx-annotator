#!/usr/bin/env python3
"""Build a new blinded V1–V4 study from local raw MERLIN generation outputs.

This is not the historical audit pair builder. No network access or inference.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import random
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
STAGES = ("V1", "V2", "V3", "V4")
PAIR_COLUMNS = ("pair_id", "hadm_id", "chief_complaint", "stage", "target_A",
                "reason_A", "target_B", "reason_B", "target_format", "clinical_context")


def digest(path):
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def text(value):
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return ""
    if isinstance(value, str):
        return value
    if hasattr(value, "tolist"):
        value = value.tolist()
    return json.dumps(value, ensure_ascii=False, default=str, allow_nan=False)


def score(value):
    if value is None:
        return None
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (ValueError, TypeError):
        return None


def read_traces(path, model, stages, *, label_only=False):
    """Raw combined.pq or explicit normalized JSONL; never use corrected SFT Output."""
    if path.suffix.lower() in (".pq", ".parquet"):
        import pandas as pd
        frame = pd.read_parquet(path)
        required = {"hadm_id", "gen_model", "split", "Chief Complaint", "admission_note"}
        required |= {f"{s.lower()}_{field}" for s in stages
                     for field in (("json",) if label_only else ("json", "text", "score"))}
        if any(s in ("V3", "V4") for s in stages):
            required.add("labs")
        if not required.issubset(frame.columns):
            raise ValueError("Raw generation table is missing required columns")
        for row in frame.to_dict("records"):
            if row["gen_model"] != model:
                continue
            for stage in stages:
                prefix = stage.lower()
                target, rationale = text(row[f"{prefix}_json"]), text(row.get(f"{prefix}_text"))
                if not target.strip() or (not label_only and not rationale.strip()):
                    continue
                try:
                    parsed = json.loads(target)
                except (ValueError, TypeError):
                    continue
                if not isinstance(parsed, (dict, list)) or (not parsed and not (label_only and stage == "V4" and isinstance(parsed, list))):
                    continue
                # Construction prompts include labs in V3 and V4, unlike the
                # historical admission-only audit and downstream no-lab evaluation.
                labs = text(row.get("labs")) if stage in ("V3", "V4") else ""
                if stage in ("V3", "V4") and not labs.strip():
                    continue
                yield {
                    "hadm_id": str(row["hadm_id"]), "model": model, "stage": stage,
                    "split": str(row["split"]), "chief_complaint": str(row["Chief Complaint"]),
                    "admission_note": text(row["admission_note"]),
                    "clinical_context": ("Laboratory results (construction input):\n" + labs) if labs else "",
                    "target": target, "reason": rationale,
                    "trace_id": f"{model}:{row['hadm_id']}:{stage}", "label_origin": "generated",
                    "verifier_score": score(row.get(f"{prefix}_score")),
                }
    elif path.suffix.lower() == ".jsonl":
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                row = json.loads(line)
                if row.get("model") == model and row.get("stage") in stages:
                    yield row
    else:
        raise ValueError("Expected raw .pq/.parquet or normalized .jsonl")


def index(rows, split, complaints, *, label_only=False):
    result = {}
    fields = ("hadm_id", "stage", "model", "trace_id", "split", "chief_complaint",
              "admission_note", "clinical_context", "target") + (() if label_only else ("reason",))
    for row in rows:
        if row.get("label_origin") != "generated":
            raise ValueError("Generated trace input requires label_origin=generated; use the reference builder for labels")
        if any(not isinstance(row.get(k), str) for k in fields):
            raise ValueError("Trace fields must be explicit strings")
        if any(not row[k].strip() for k in fields if k != "clinical_context"):
            raise ValueError("Trace contains an empty required field")
        if row["stage"] not in STAGES:
            raise ValueError("Unknown stage")
        if row["split"] != split or (complaints and row["chief_complaint"] not in complaints):
            continue
        if row["stage"] == "V3" and not row["clinical_context"].strip():
            raise ValueError("V3 requires its laboratory context")
        key = (row["hadm_id"], row["stage"])
        if key in result:
            raise ValueError("Multiple traces for the same admission and stage; preselect one explicitly")
        result[key] = row
    return result


def write_csv(path, rows, fields):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def build(left_path, right_path, left_model, right_model, stages, split, out, *,
          seed=42, n=None, complaints=(), raters=2):
    from merlin_ddx.rebuttal_audit import load_cases
    if not stages or len(set(stages)) != len(stages) or not set(stages) <= set(STAGES):
        raise ValueError("Choose unique stages V1–V4")
    if raters < 1 or (n is not None and n < 1):
        raise ValueError("Positive sample size and rater count required")
    left_path, right_path, out = map(Path, (left_path, right_path, out))
    if out.exists():
        raise ValueError("Output must be a new directory; existing studies are never overwritten")
    if left_path.resolve() == right_path.resolve() and left_model == right_model:
        raise ValueError("Provide two distinct trace sources or models")
    hashes = [digest(left_path), digest(right_path)]
    settings = {"study_type": "paired_reasoning", "source_sha256": hashes, "models": [left_model, right_model],
                "stages": list(stages), "split": split, "seed": seed, "n": n,
                "complaints": list(complaints), "raters": raters}
    study_id = hashlib.sha256(json.dumps(settings, sort_keys=True).encode()).hexdigest()[:20]
    left = index(read_traces(left_path, left_model, stages), split, complaints)
    right = index(read_traces(right_path, right_model, stages), split, complaints)
    matched = set(left) & set(right)
    eligible = sorted({case for case, _ in matched
                       if all((case, s) in matched for s in stages)})
    if not eligible or (n is not None and n > len(eligible)):
        raise ValueError("Insufficient complete matched admissions")
    rng = random.Random(seed)
    selected = rng.sample(eligible, n) if n is not None else rng.sample(eligible, len(eligible))
    blinded, notes, key = [], [], []
    for i, case in enumerate(selected, 1):
        case_id = f"{study_id}-{i:06d}"
        first = left[(case, stages[0])]
        notes.append({"hadm_id": case_id, "chief_complaint": first["chief_complaint"],
                      "admission_note": first["admission_note"]})
        for stage in stages:
            a, b = left[(case, stage)], right[(case, stage)]
            for field in ("admission_note", "chief_complaint"):
                if a[field] != b[field] or a[field] != first[field]:
                    raise ValueError("Compared traces have different case evidence")
            if a["clinical_context"] != b["clinical_context"]:
                raise ValueError("Compared traces have different stage-specific evidence")
            arms = [(a, "left"), (b, "right")]
            if rng.randrange(2):
                arms.reverse()
            pair_id = f"{case_id}-{stage}"
            row = {"pair_id": pair_id, "hadm_id": case_id,
                   "chief_complaint": first["chief_complaint"], "stage": stage,
                   "target_format": "stage_output", "clinical_context": a["clinical_context"]}
            for letter, (trace, _) in zip("AB", arms):
                row[f"target_{letter}"] = trace["target"]
                row[f"reason_{letter}"] = trace["reason"]
            blinded.append(row)
            key.append({"pair_id": pair_id, "hadm_id": case_id, "source_hadm_id": case,
                        "stage": stage, "arms": {
                            letter: {"condition": condition, "trace_id": trace["trace_id"],
                                     "model": trace["model"], "label_origin": "generated",
                                     "source_sha256": hashes[0 if condition == "left" else 1],
                                     "verifier_score": score(trace.get("verifier_score")),
                                     "verifier_accepted": trace.get("verifier_accepted")}
                            for letter, (trace, condition) in zip("AB", arms)}})
    # The allocation directory is a sibling, not part of the served data root.
    root = out / "annotation_inputs"
    source = root / "source" / "merlin_rebuttal_audit"
    write_csv(source / "audit_batch1_blinded.csv", blinded, PAIR_COLUMNS)
    write_csv(source / "audit_batch1_notes.csv", notes, ("hadm_id", "chief_complaint", "admission_note"))
    app = root / "app"
    app.mkdir()
    (app / "annotators.json").write_text(json.dumps([
        {"id": f"{study_id}-r{i}", "name": f"Rater {i}", "type": "human", "active": True}
        for i in range(1, raters + 1)], indent=2) + "\n", encoding="utf-8")
    private = out / "private_analysis"
    private.mkdir(mode=0o700)
    (private / "allocation_key.json").write_text(json.dumps(key, indent=2) + "\n", encoding="utf-8")
    manifest = {**settings, "study_id": study_id, "matched_pairs": len(matched),
                "eligible_admissions": len(eligible), "selected_admissions": len(selected),
                "selected_pairs": len(blinded),
                "left_only_pairs": len(set(left) - set(right)), "right_only_pairs": len(set(right) - set(left))}
    (private / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    if len(load_cases(root)) != len(selected):
        raise ValueError("Generated inputs failed backend validation")
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--left", required=True, type=Path)
    parser.add_argument("--right", required=True, type=Path)
    parser.add_argument("--left-model", required=True)
    parser.add_argument("--right-model", required=True)
    parser.add_argument("--stages", nargs="+", choices=STAGES, default=list(STAGES))
    parser.add_argument("--split", choices=("train", "dev", "test"), default="test")
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--n", type=int)
    parser.add_argument("--complaints", nargs="+", default=[])
    parser.add_argument("--raters", type=int, default=2)
    args = parser.parse_args()
    result = build(args.left, args.right, args.left_model, args.right_model, args.stages,
                   args.split, args.out, seed=args.seed, n=args.n, complaints=args.complaints,
                   raters=args.raters)
    print(f"Prepared {result['selected_admissions']} admissions and {result['selected_pairs']} pairs.")


if __name__ == "__main__":
    main()
