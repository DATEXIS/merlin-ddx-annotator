#!/usr/bin/env python3
"""Validate and join new-study ratings to the private allocation key locally."""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
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


def read_observed(root, cases):
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

    return raters, observed



def export_reference(study, root, out, cases, *, allow_incomplete=False, include_corrections=False):
    """Export reference review separately; never conflate label validity with rationale validity."""
    key = read_json(study / "private_analysis" / "reference_key.json")
    by_pair = {p["pair_id"]: p for case in cases for p in case["pairs"]}
    by_key = {r["pair_id"]: r for r in key}
    if (len(by_pair) != sum(len(c["pairs"]) for c in cases)
            or len(by_key) != len(key) or set(by_pair) != set(by_key)):
        raise ValueError("Reference identifiers do not match")
    for pair_id, pair in by_pair.items():
        row = by_key[pair_id]
        if (pair.get("target_format") != "reference_label"
                or row.get("label_origin") != "reference"
                or row["case_id"] != pair["hadm_id"] or row["stage"] != pair["stage"]
                or row["label_source"] != pair["label_source"]
                or row["label_sha256"] != hashlib.sha256(pair["target_A"].encode("utf-8")).hexdigest()):
            raise ValueError("Reference key does not match reviewed label")
    raters, observed = read_observed(root, cases)
    labels, corrections = [], []
    incomplete = 0
    for pair_id, row in by_key.items():
        votes = Counter()
        suggestions = Counter()
        for rater in raters:
            answer = observed.get((rater, pair_id), {})
            value = answer.get("label_validity")
            value = value if value in ALLOWED_ANSWERS else "Missing"
            votes[value] += 1
            incomplete += value == "Missing"
            suggestion = answer.get("suggested_label", "").strip()
            if suggestion:
                suggestions[suggestion] += 1
        labels.append({**row, "label_validity_votes": dict(votes),
                       "n_expected_raters": len(raters), "n_suggestions": sum(suggestions.values())})
        if include_corrections and suggestions:
            corrections.append({"pair_id": pair_id, "case_id": row["case_id"], "stage": row["stage"],
                                "suggestions": [{"suggested_label": label, "count": count}
                                                for label, count in sorted(suggestions.items())]})
    if incomplete and not allow_incomplete:
        raise ValueError(f"{incomplete} incomplete reference judgments; use --allow-incomplete explicitly")
    out.mkdir(parents=True, mode=0o700)
    write_jsonl(out / "label_ratings.jsonl", labels)
    if include_corrections:
        write_jsonl(out / "private_suggested_corrections.jsonl", corrections)
    meta = {"study_type": "reference_label", "labels": len(labels),
            "raters": len(raters), "incomplete_rater_labels": incomplete}
    (out / "export_summary.json").write_text(json.dumps(meta, indent=2) + "\n")
    return meta



def export_label_comparison(study, root, out, cases, *, allow_incomplete=False):
    key = read_json(study / "private_analysis" / "label_comparison_key.json")
    by_pair = {p["pair_id"]: p for case in cases for p in case["pairs"]}
    by_key = {r["pair_id"]: r for r in key}
    if (len(by_pair) != sum(len(c["pairs"]) for c in cases)
            or len(by_key) != len(key) or set(by_pair) != set(by_key)):
        raise ValueError("Label comparison key does not match cases")
    for pair_id, pair in by_pair.items():
        row = by_key[pair_id]
        if (pair.get("target_format") != "label_comparison"
                or row["case_id"] != pair["hadm_id"] or row["stage"] != pair["stage"]
                or set(row["arms"]) != {"A", "B"}
                or {a["label_origin"] for a in row["arms"].values()} != {"generated", "reference"}):
            raise ValueError("Invalid label comparison allocation")
        for arm, meta in row["arms"].items():
            if meta["label_sha256"] != hashlib.sha256(pair[f"target_{arm}"].encode("utf-8")).hexdigest():
                raise ValueError("Reviewed label differs from allocation key")
    raters, observed = read_observed(root, cases)
    rows = []
    incomplete = 0
    for pair_id, pair in by_pair.items():
        key_row = by_key[pair_id]
        arms = {meta["label_origin"]: arm for arm, meta in key_row["arms"].items()}
        joint, preferences = Counter(), Counter()
        same = pair["target_A"] == pair["target_B"]
        for rater in raters:
            answer = observed.get((rater, pair_id), {})
            def judgment(origin):
                value = answer.get(f"{arms[origin]}_label_validity")
                return value if value in ALLOWED_ANSWERS else "Missing"
            generated, reference = judgment("generated"), judgment("reference")
            joint[(generated, reference)] += 1
            preference = answer.get("target_preference_A_B_equal")
            if same:
                preference = "Not applicable"
            elif preference in ("A", "B"):
                preference = key_row["arms"][preference]["label_origin"]
            elif preference != "Equal":
                preference = "Missing"
            preferences[preference] += 1
            incomplete += "Missing" in (generated, reference, preference)
        # Export joint counts, not individual ratings, and no clinical text.
        rows.append({**{k: v for k, v in key_row.items() if k != "arms"},
                     "generated": key_row["arms"][arms["generated"]],
                     "reference": key_row["arms"][arms["reference"]],
                     "identical_labels": same, "n_expected_raters": len(raters),
                     "joint_votes": [{"generated": g, "reference": r, "count": count}
                                     for (g, r), count in sorted(joint.items())],
                     "preference_votes": dict(preferences)})
    if incomplete and not allow_incomplete:
        raise ValueError(f"{incomplete} incomplete paired label judgments; use --allow-incomplete explicitly")
    out.mkdir(parents=True, mode=0o700)
    write_jsonl(out / "label_comparison_ratings.jsonl", rows)
    meta = {"study_type": "label_comparison", "pairs": len(rows),
            "raters": len(raters), "incomplete_rater_pairs": incomplete}
    (out / "export_summary.json").write_text(json.dumps(meta, indent=2) + "\n")
    return meta



def export_single_reasoning(study, root, out, cases, *, allow_incomplete=False):
    key = read_json(study / "private_analysis" / "single_reasoning_key.json")
    pairs = {p["pair_id"]: p for case in cases for p in case["pairs"]}
    by_key = {r["pair_id"]: r for r in key}
    if len(by_key) != len(key) or set(pairs) != set(by_key):
        raise ValueError("Standalone key does not match cases")
    raters, observed = read_observed(root, cases)
    rows = []
    incomplete = 0
    for pair_id, meta in by_key.items():
        p = pairs[pair_id]
        if (p.get("target_format") != "single_reasoning" or p["hadm_id"] != meta["case_id"]
                or p["stage"] != meta["stage"] or any(
                    meta[field + "_sha256"] != hashlib.sha256(p[column].encode()).hexdigest()
                    for field, column in (("target", "target_A"), ("reason", "reason_A")))):
            raise ValueError("Standalone provenance mismatch")
        counts = {metric: Counter() for metric in ("q1", "q2", "composite")}
        for rater in raters:
            answer = observed.get((rater, pair_id), {})
            q = [answer.get("A_Q1"), answer.get("A_Q2")]
            q = [v if v in ALLOWED_ANSWERS else "Missing" for v in q]
            counts["q1"][q[0]] += 1
            counts["q2"][q[1]] += 1
            counts["composite"]["Missing" if "Missing" in q else "Yes" if q == ["Yes", "Yes"] else "No"] += 1
            incomplete += "Missing" in q
        rows.append({**meta, "n_expected_raters": len(raters),
                     **{metric + "_votes": dict(v) for metric, v in counts.items()}})
    if incomplete and not allow_incomplete:
        raise ValueError(f"{incomplete} incomplete standalone judgments; use --allow-incomplete explicitly")
    out.mkdir(parents=True, mode=0o700)
    write_jsonl(out / "single_reasoning_ratings.jsonl", rows)
    result = {"study_type": "single_reasoning", "traces": len(rows), "raters": len(raters),
              "incomplete_rater_traces": incomplete}
    (out / "export_summary.json").write_text(json.dumps(result, indent=2) + "\n")
    return result


def export(study, out, *, allow_incomplete=False, include_corrections=False):
    study, out = Path(study), Path(out)
    if out.exists():
        raise ValueError("Export directory must not already exist")
    root = study / "annotation_inputs"
    if out.resolve().is_relative_to(root.resolve()):
        raise ValueError("Export must be outside the served data root")
    cases = load_cases(root)
    if (study / "private_analysis" / "single_reasoning_key.json").is_file():
        if include_corrections:
            raise ValueError("Correction export is only for reference-label studies")
        return export_single_reasoning(study, root, out, cases, allow_incomplete=allow_incomplete)
    if (study / "private_analysis" / "label_comparison_key.json").is_file():
        if include_corrections:
            raise ValueError("Correction export is only for reference-label studies")
        return export_label_comparison(study, root, out, cases, allow_incomplete=allow_incomplete)
    if (study / "private_analysis" / "reference_key.json").is_file():
        return export_reference(study, root, out, cases, allow_incomplete=allow_incomplete,
                                include_corrections=include_corrections)
    if include_corrections:
        raise ValueError("Correction export is only for reference-label studies")
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
    raters, observed = read_observed(root, cases)

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
    parser.add_argument("--include-corrections", action="store_true",
                        help="Export sensitive suggested reference labels separately, local use only")
    args = parser.parse_args()
    summary = export(args.study, args.out, allow_incomplete=args.allow_incomplete,
                     include_corrections=args.include_corrections)
    print(json.dumps(summary))


if __name__ == "__main__":
    main()
