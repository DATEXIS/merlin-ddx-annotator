#!/usr/bin/env python3
"""Create a standalone generated-reasoning study with no comparator."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import random

from build_annotation_cases import STAGES, PAIR_COLUMNS, digest, index, read_traces, score, write_csv


def build(path, model, stages, split, out, *, seed=42, n=None, raters=2):
    from merlin_ddx.rebuttal_audit import load_cases
    path, out = Path(path), Path(out)
    if out.exists() or raters < 1 or (n is not None and n < 1):
        raise ValueError("Require new output directory and positive sample/rater counts")
    if not stages or len(set(stages)) != len(stages) or not set(stages) <= set(STAGES):
        raise ValueError("Choose unique stages V1–V4")
    records = index(read_traces(path, model, stages), split, ())
    eligible = sorted({case for case, _ in records if all((case, s) in records for s in stages)})
    if not eligible or (n is not None and n > len(eligible)):
        raise ValueError("Insufficient eligible complete admissions")
    settings = {"study_type": "single_reasoning", "source_sha256": digest(path), "model": model,
                "stages": list(stages), "split": split, "seed": seed, "n": n, "raters": raters}
    study_id = hashlib.sha256(json.dumps(settings, sort_keys=True).encode()).hexdigest()[:20]
    selected = random.Random(seed).sample(eligible, n if n is not None else len(eligible))
    notes, rows, key = [], [], []
    for i, case in enumerate(selected, 1):
        case_id = f"{study_id}-{i:06d}"
        first = records[case, stages[0]]
        notes.append({"hadm_id": case_id, "chief_complaint": first["chief_complaint"],
                      "admission_note": first["admission_note"]})
        for stage in stages:
            trace = records[case, stage]
            if any(trace[f] != first[f] for f in ("admission_note", "chief_complaint")):
                raise ValueError("Inconsistent admission evidence")
            pair_id = f"{case_id}-{stage}"
            rows.append({"pair_id": pair_id, "hadm_id": case_id, "chief_complaint": first["chief_complaint"],
                         "stage": stage, "target_A": trace["target"], "reason_A": trace["reason"],
                         "target_B": "", "reason_B": "", "target_format": "single_reasoning",
                         "clinical_context": trace["clinical_context"]})
            key.append({"pair_id": pair_id, "case_id": case_id, "source_hadm_id": case,
                        "stage": stage, "label_origin": "generated", "trace_id": trace["trace_id"],
                        "model": model, "source_sha256": settings["source_sha256"],
                        "verifier_score": score(trace.get("verifier_score")),
                        "verifier_accepted": trace.get("verifier_accepted"),
                        "target_sha256": hashlib.sha256(trace["target"].encode()).hexdigest(),
                        "reason_sha256": hashlib.sha256(trace["reason"].encode()).hexdigest()})
    root = out / "annotation_inputs"
    source = root / "source" / "merlin_rebuttal_audit"
    write_csv(source / "audit_batch1_blinded.csv", rows, PAIR_COLUMNS)
    write_csv(source / "audit_batch1_notes.csv", notes, ("hadm_id", "chief_complaint", "admission_note"))
    app = root / "app"
    app.mkdir()
    (app / "annotators.json").write_text(json.dumps([
        {"id": f"{study_id}-r{i}", "name": f"Rater {i}", "type": "human", "active": True}
        for i in range(1, raters + 1)], indent=2) + "\n")
    private = out / "private_analysis"
    private.mkdir(mode=0o700)
    (private / "single_reasoning_key.json").write_text(json.dumps(key, indent=2) + "\n")
    manifest = {**settings, "study_id": study_id, "eligible_admissions": len(eligible),
                "selected_admissions": len(selected), "selected_traces": len(rows)}
    (private / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    if len(load_cases(root)) != len(selected):
        raise ValueError("Backend validation failed")
    return manifest


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--input", type=Path, required=True)
    p.add_argument("--model", required=True)
    p.add_argument("--stages", nargs="+", choices=STAGES, default=list(STAGES))
    p.add_argument("--split", choices=("train", "dev", "test"), default="test")
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--n", type=int)
    p.add_argument("--raters", type=int, default=2)
    a = p.parse_args()
    result = build(a.input, a.model, a.stages, a.split, a.out, seed=a.seed, n=a.n, raters=a.raters)
    print(f"Prepared {result['selected_traces']} standalone traces.")


if __name__ == "__main__":
    main()
