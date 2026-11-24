#!/usr/bin/env python3
"""Build blinded label-only comparisons between generated and reference outputs."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import random
import re

from build_annotation_cases import STAGES, PAIR_COLUMNS, digest, index, read_traces, score, write_csv
from build_reference_cases import read_labels


def canonical(stage, target, origin):
    """Project both arms onto the same label unit, stripping rationale fields."""
    if origin not in ("generated", "reference"):
        raise ValueError("Explicit label origin required")
    if stage == "V1":
        obj = json.loads(target)
        if not isinstance(obj, dict) or not obj:
            raise ValueError("V1 requires a nonempty manifestation mapping")
        values = {}
        for name, item in obj.items():
            value = item.get("value") if isinstance(item, dict) else item
            if not isinstance(name, str) or not name.strip() or type(value) is not int or value not in (-1, 0, 1):
                raise ValueError("Invalid manifestation label")
            values[name] = value
        return json.dumps(values, sort_keys=True, ensure_ascii=False, indent=2)
    if stage in ("V2", "V3"):
        if origin == "generated":
            obj = json.loads(target)
            if not isinstance(obj, list) or not obj or not isinstance(obj[0], dict):
                raise ValueError("Generated diagnosis ranking must be a nonempty list")
            target = obj[0].get("name")
        if not isinstance(target, str) or not target.strip():
            raise ValueError("Missing top diagnosis label")
        return target.strip()
    if stage == "V4":
        obj = json.loads(target)
        if not isinstance(obj, list):
            raise ValueError("Expected ICD label list")
        codes = []
        for item in obj:
            code = item.get("icd_code") if isinstance(item, dict) else item
            if not isinstance(code, str):
                raise ValueError("Invalid ICD label")
            code = code.strip().upper()
            if not re.fullmatch(r"[A-Z0-9]+(?:\.[A-Z0-9]+)?", code):
                raise ValueError("Invalid ICD label format")
            codes.append(code.replace(".", ""))
        # Compare unordered code sets at full available specificity.
        return json.dumps(sorted(set(codes)), ensure_ascii=False, indent=2)
    raise ValueError("Unknown stage")


def reference_index(rows, split, stages):
    fields = ("hadm_id", "stage", "split", "chief_complaint", "admission_note",
              "clinical_context", "target", "label_source", "label_id")
    result = {}
    for row in rows:
        if row.get("split") != split or row.get("stage") not in stages:
            continue
        if row.get("label_origin") != "reference" or any(
                not isinstance(row.get(f), str) or (f != "clinical_context" and not row[f].strip())
                for f in fields):
            raise ValueError("Invalid reference record")
        key = (row["hadm_id"], row["stage"])
        if key in result:
            raise ValueError("Duplicate reference admission/stage")
        result[key] = row
    return result


def normalized_context(value):
    # Raw adapters use different headings for the same laboratory evidence.
    for heading in ("Laboratory results (construction input):\n", "Laboratory evidence:\n"):
        if value.startswith(heading):
            return value[len(heading):].strip()
    return value.strip()


def build(generated_path, reference_path, model, stages, split, out, *,
          reference_model=None, schema_path=None, seed=42, n=None, raters=2):
    from merlin_ddx.rebuttal_audit import load_cases
    generated_path, reference_path, out = map(Path, (generated_path, reference_path, out))
    if out.exists():
        raise ValueError("Output must be a new directory")
    if not stages or len(set(stages)) != len(stages) or not set(stages) <= set(STAGES):
        raise ValueError("Choose unique stages V1–V4")
    if raters < 1 or (n is not None and n < 1):
        raise ValueError("Positive sample and rater counts required")
    schema = json.loads(Path(schema_path).read_text(encoding="utf-8")) if schema_path else None
    generated = index(read_traces(generated_path, model, stages, label_only=True), split, (), label_only=True)
    references = reference_index(read_labels(reference_path, reference_model or model, stages, schema, False, include_v4_labs=True),
                                 split, stages)
    matched = set(generated) & set(references)
    eligible = sorted({case for case, _ in matched if all((case, s) in matched for s in stages)})
    if not eligible or (n is not None and n > len(eligible)):
        raise ValueError("Insufficient complete matched admissions")
    settings = {"study_type": "label_comparison", "generated_sha256": digest(generated_path),
                "reference_sha256": digest(reference_path), "model": model,
                "reference_storage_model": reference_model or model,
                "schema_sha256": digest(Path(schema_path)) if schema_path else None,
                "stages": list(stages), "split": split, "seed": seed, "n": n, "raters": raters,
                "comparison_units": {"V1": "manifestation_mapping", "V2": "top1_diagnosis",
                                     "V3": "top1_diagnosis", "V4": "full_code_set"}}
    study_id = hashlib.sha256(json.dumps(settings, sort_keys=True).encode()).hexdigest()[:20]
    rng = random.Random(seed)
    selected = rng.sample(eligible, n if n is not None else len(eligible))
    notes, rows, allocation = [], [], []
    for i, case in enumerate(selected, 1):
        case_id = f"{study_id}-{i:06d}"
        first = generated[case, stages[0]]
        notes.append({"hadm_id": case_id, "chief_complaint": first["chief_complaint"],
                      "admission_note": first["admission_note"]})
        for stage in stages:
            g, r = generated[case, stage], references[case, stage]
            for field in ("admission_note", "chief_complaint"):
                if g[field] != r[field] or g[field] != first[field]:
                    raise ValueError("Compared labels have different admission evidence")
            context = normalized_context(g["clinical_context"])
            ref_context = normalized_context(r["clinical_context"])
            if context != ref_context:
                raise ValueError("Compared labels have different stage-specific evidence")
            if stage == "V3" and not context:
                raise ValueError("V3 requires laboratory evidence")
            ga, ra = canonical(stage, g["target"], "generated"), canonical(stage, r["target"], "reference")
            if stage == "V1" and set(json.loads(ga)) != set(json.loads(ra)):
                raise ValueError("V1 arms must use the same manifestation schema")
            arms = [(ga, {"label_origin": "generated", "trace_id": g["trace_id"],
                          "model": model, "source_sha256": settings["generated_sha256"],
                          "verifier_score": score(g.get("verifier_score")),
                          "verifier_accepted": g.get("verifier_accepted")}),
                    (ra, {"label_origin": "reference", "label_id": r["label_id"],
                          "label_source": r["label_source"], "source_sha256": settings["reference_sha256"]})]
            if rng.randrange(2):
                arms.reverse()
            pair_id = f"{case_id}-{stage}"
            row = {"pair_id": pair_id, "hadm_id": case_id, "chief_complaint": first["chief_complaint"],
                   "stage": stage, "target_format": "label_comparison", "clinical_context": context,
                   "reason_A": "", "reason_B": ""}
            key = {"pair_id": pair_id, "case_id": case_id, "source_hadm_id": case,
                   "stage": stage, "comparison_unit": settings["comparison_units"][stage], "arms": {}}
            for letter, (label, meta) in zip("AB", arms):
                row[f"target_{letter}"] = label
                key["arms"][letter] = {**meta, "label_sha256": hashlib.sha256(label.encode("utf-8")).hexdigest()}
            rows.append(row)
            allocation.append(key)
    root = out / "annotation_inputs"
    source = root / "source" / "merlin_rebuttal_audit"
    write_csv(source / "audit_batch1_blinded.csv", rows, PAIR_COLUMNS)
    write_csv(source / "audit_batch1_notes.csv", notes, ("hadm_id", "chief_complaint", "admission_note"))
    app = root / "app"
    app.mkdir()
    (app / "annotators.json").write_text(json.dumps([
        {"id": f"{study_id}-r{i}", "name": f"Rater {i}", "type": "human", "active": True}
        for i in range(1, raters + 1)], indent=2) + "\n", encoding="utf-8")
    private = out / "private_analysis"
    private.mkdir(mode=0o700)
    (private / "label_comparison_key.json").write_text(json.dumps(allocation, indent=2) + "\n", encoding="utf-8")
    manifest = {**settings, "study_id": study_id, "eligible_admissions": len(eligible),
                "selected_admissions": len(selected), "selected_pairs": len(rows),
                "generated_only_pairs": len(set(generated) - set(references)),
                "reference_only_pairs": len(set(references) - set(generated))}
    (private / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    cases = load_cases(root)
    if len(cases) != len(selected) or sum(len(c["pairs"]) for c in cases) != len(rows):
        raise ValueError("Comparison inputs failed backend validation")
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--generated", required=True, type=Path)
    parser.add_argument("--reference", required=True, type=Path)
    parser.add_argument("--model", required=True)
    parser.add_argument("--reference-model")
    parser.add_argument("--symptom-schema-json", type=Path)
    parser.add_argument("--stages", nargs="+", choices=STAGES, default=["V2", "V3", "V4"])
    parser.add_argument("--split", choices=("train", "dev", "test"), default="test")
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--n", type=int)
    parser.add_argument("--raters", type=int, default=2)
    args = parser.parse_args()
    result = build(args.generated, args.reference, args.model, args.stages, args.split, args.out,
                   reference_model=args.reference_model, schema_path=args.symptom_schema_json,
                   seed=args.seed, n=args.n, raters=args.raters)
    print(f"Prepared {result['selected_admissions']} admissions and {result['selected_pairs']} label pairs.")


if __name__ == "__main__":
    main()
