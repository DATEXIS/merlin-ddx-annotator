#!/usr/bin/env python3
"""Validate and join new-study ratings to the private allocation key locally."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from merlin_ddx.rebuttal_audit import (ALLOWED_ANSWERS, LEGACY_ANSWER_FIELDS,
                                      load_cases, validate_answers)


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def write_jsonl(path, rows):
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def export(study, out, *, allow_incomplete=False):
    study, out = Path(study), Path(out)
    if out.exists():
        raise ValueError("Export directory must not already exist")
    root = study / "annotation_inputs"
    if out.resolve().is_relative_to(root.resolve()):
        raise ValueError("Export must be outside the served data root")
    cases = load_cases(root)
    by_pair = {p["pair_id"]: p for case in cases for p in case["pairs"]}
    key = read_json(study / "private_analysis" / "allocation_key.json")
    allocation = {row["pair_id"]: row for row in key}
    if len(by_pair) != sum(len(c["pairs"]) for c in cases) or len(allocation) != len(key) or set(allocation) != set(by_pair):
        raise ValueError("Pair identifiers do not match allocation key")
    for pair_id, pair in by_pair.items():
        row = allocation[pair_id]
        if row["stage"] != pair["stage"] or row["hadm_id"] != pair["hadm_id"]:
            raise ValueError("Allocation key does not match served pairs")
        if set(row["arms"]) != {"A", "B"} or {a["condition"] for a in row["arms"].values()} != {"left", "right"}:
            raise ValueError("Invalid allocation")
    raters = [r["id"] for r in read_json(root / "app" / "annotators.json")
              if r["type"] == "human" and r.get("active", True)]
    if not raters or len(raters) != len(set(raters)):
        raise ValueError("Invalid study rater list")
    observed = {}
    ratings_dir = root / "rebuttal_audit_annotations"
    for rater in raters:
        records = ratings_dir / rater
        for path in sorted(records.glob("*.json")):
            record = read_json(path)
            if record["annotatorId"] != rater:
                raise ValueError("Rater identity mismatch")
            validate_answers(record["hadm_id"], record["pairs"], cases)
            for pair_id, answer in record["pairs"].items():
                if (rater, pair_id) in observed:
                    raise ValueError("Duplicate rater/pair record")
                observed[rater, pair_id] = answer

    trace_rows, pair_rows = [], []
    incomplete = 0
    for pair_id, pair in by_pair.items():
        row = allocation[pair_id]
        counts = {arm: {"q1": Counter(), "q2": Counter(), "composite": Counter()} for arm in "AB"}
        preferences = {"target": Counter(), "rationale": Counter()}
        same = pair["target_A"] == pair["target_B"]
        for rater in raters:
            answer = observed.get((rater, pair_id), {})
            valid = True
            for arm in "AB":
                q = []
                for num in (1, 2):
                    field = f"{arm}_Q{num}"
                    value = answer.get(field) or answer.get(LEGACY_ANSWER_FIELDS[field])
                    value = value if value in ALLOWED_ANSWERS else "Missing"
                    counts[arm][f"q{num}"][value] += 1
                    q.append(value)
                composite = ("Missing" if "Missing" in q else
                             "Yes" if q == ["Yes", "Yes"] else "No")
                counts[arm]["composite"][composite] += 1
                valid &= "Missing" not in q
            target = answer.get("target_preference_A_B_equal")
            rationale = answer.get("rationale_preference_A_B_equal") or answer.get("preference_A_B_equivalent")
            for label, value in (("target", target), ("rationale", rationale)):
                if label == "target" and same:
                    preferences[label]["Not applicable"] += 1
                    continue
                if value in ("A", "B"):
                    value = row["arms"][value]["condition"]
                elif value not in ("Equal", "Equivalent"):
                    value = "Missing"
                preferences[label][value] += 1
                valid &= value != "Missing"
            incomplete += not valid
        for arm in "AB":
            trace_rows.append({
                "pair_id": pair_id, "case_id": pair["hadm_id"], "source_hadm_id": row["source_hadm_id"],
                "stage": pair["stage"], **row["arms"][arm],
                "n_expected_raters": len(raters),
                **{f"{metric}_votes": dict(c) for metric, c in counts[arm].items()},
            })
        pair_rows.append({"pair_id": pair_id, "case_id": pair["hadm_id"], "stage": pair["stage"],
                          **{f"{metric}_preference_votes": dict(c) for metric, c in preferences.items()}})
    if incomplete and not allow_incomplete:
        raise ValueError(f"{incomplete} incomplete rater-pair judgments; use --allow-incomplete explicitly")
    out.mkdir(parents=True, mode=0o700)
    write_jsonl(out / "trace_ratings.jsonl", trace_rows)
    write_jsonl(out / "pair_ratings.jsonl", pair_rows)
    meta = {"pairs": len(by_pair), "raters": len(raters), "incomplete_rater_pairs": incomplete}
    (out / "export_summary.json").write_text(json.dumps(meta, indent=2) + "\n")
    return meta


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--study", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--allow-incomplete", action="store_true")
    args = parser.parse_args()
    summary = export(args.study, args.out, allow_incomplete=args.allow_incomplete)
    print(json.dumps(summary))


if __name__ == "__main__":
    main()
