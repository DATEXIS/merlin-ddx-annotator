#!/usr/bin/env python3
"""Local inter-rater agreement for arbitrary new studies; no patient text in summary."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from itertools import combinations
import json
from pathlib import Path

from export_annotations import read_json, read_observed
from merlin_ddx.rebuttal_audit import load_cases, ALLOWED_ANSWERS


def kappa(pairs):
    n = len(pairs)
    if not n:
        return {"n": 0, "observed_agreement": None, "kappa": None, "contingency": {}}
    a, b = (Counter(p[i] for p in pairs) for i in (0, 1))
    observed = sum(x == y for x, y in pairs) / n
    expected = sum(a[k] * b[k] for k in set(a) | set(b)) / n**2
    cells = Counter(pairs)
    return {"n": n, "observed_agreement": observed, "expected_agreement": expected,
            "kappa": (observed - expected) / (1 - expected) if expected < 1 else None,
            "contingency": {x: {y: cells[x, y] for y in sorted(b)} for x in sorted(a)}}



def multi_rater_agreement(items, n_raters):
    """Nominal agreement on an item-by-rater matrix; None/empty = missing.

    Fleiss uses all configured raters on complete items. Alpha uses all
    pairable items, weighting each coincidence by 1/(m_i-1). Singleton
    ratings do not enter either the observed or expected coincidences.
    """
    if n_raters < 1:
        raise ValueError("At least one configured rater required")
    rows = [tuple(row) for row in items]
    if any(len(row) != n_raters for row in rows):
        raise ValueError("Rating rows must match the configured rater count")
    counts = [Counter(v for v in row if v is not None and v != "") for row in rows]
    sizes = [sum(c.values()) for c in counts]
    complete = [c for c, m in zip(counts, sizes) if m == n_raters and m >= 2]
    pairable = [c for c, m in zip(counts, sizes) if m >= 2]
    histogram = {str(m): sizes.count(m) for m in range(n_raters + 1)}
    f = {"n_items": len(complete), "excluded_items": len(rows) - len(complete),
         "ratings_per_item": n_raters, "n_ratings": len(complete) * n_raters,
         "observed_agreement": None, "expected_agreement": None, "kappa": None,
         "category_counts": {}}
    if complete:
        marginal = sum(complete, Counter())
        total = f["n_ratings"]
        observed = sum(sum(v * (v - 1) for v in c.values()) for c in complete) / (
            total * (n_raters - 1))
        expected = sum(v * v for v in marginal.values()) / total**2
        f.update(observed_agreement=observed, expected_agreement=expected,
                 kappa=(observed - expected) / (1 - expected) if expected < 1 else None,
                 category_counts=dict(sorted(marginal.items())))
    a = {"n_items": len(pairable), "excluded_items": len(rows) - len(pairable),
         "n_ratings": sum(sum(c.values()) for c in pairable),
         "observed_disagreement": None, "expected_disagreement": None, "alpha": None,
         "category_counts": {}}
    if pairable:
        marginal = sum(pairable, Counter())
        total = a["n_ratings"]
        # Ordered unequal-label coincidences, weighted by the number of
        # other raters on the same item. Expected disagreement uses the
        # finite pooled population without replacement.
        observed = sum((m*m - sum(v*v for v in c.values())) / (m-1)
                       for c in pairable for m in (sum(c.values()),)) / total
        expected = (total*total - sum(v*v for v in marginal.values())) / (total*(total-1))
        a.update(observed_disagreement=observed, expected_disagreement=expected,
                 alpha=1 - observed / expected if expected > 0 else None,
                 category_counts=dict(sorted(marginal.items())))
    return {"expected_items": len(rows), "configured_raters": n_raters,
            "ratings_per_item_histogram": histogram,
            "fleiss_kappa": f, "krippendorff_alpha_nominal": a}


def rubric_fields(pair):
    kind = pair.get("target_format")
    fields = (["label_validity"] if kind == "reference_label" else
              ["A_Q1", "A_Q2"] if kind == "single_reasoning" else
              ["A_label_validity", "B_label_validity"] if kind == "label_comparison" else
              ["A_Q1", "A_Q2", "B_Q1", "B_Q2", "rationale_preference_A_B_equal"])
    if kind not in ("reference_label", "single_reasoning") and pair["target_A"] != pair["target_B"]:
        fields.append("target_preference_A_B_equal")
    return fields


def ddx_selections(root):
    cases = read_json(root / "app" / "patients_study.json")
    fixed = {c["id"]: {d["id"]: d["label"] for d in c["diagnoses"]} for c in cases}
    raters = [r["id"] for r in read_json(root / "app" / "annotators.json") if r["type"] == "human" and r.get("active", True)]
    selections = {}
    for rid in raters:
        for path in sorted((root / "annotations" / rid).glob("*.json")):
            record = read_json(path)
            cid = record["patientId"]
            if record["annotatorId"] != rid or cid not in fixed or path.stem != cid:
                raise ValueError("Invalid DDx rating identity")
            extra = root / "custom_diagnoses" / (cid + ".json")
            labels = {**fixed[cid], **({v["id"]: v["label"] for v in read_json(extra)} if extra.is_file() else {})}
            if not set(record["annotations"]) <= set(labels) or any(type(v) is not bool for v in record["annotations"].values()):
                raise ValueError("Unknown or invalid DDx annotation")
            chosen = {labels[k].strip().casefold() for k, v in record["annotations"].items() if v}
            # Preserve historical positive-selection completion rule: empty records
            # cannot distinguish an unfinished case from an intentional empty set.
            if chosen:
                selections[rid, cid] = chosen
    return raters, fixed, selections


def analyze(study):
    root = Path(study) / "annotation_inputs"
    manifest = read_json(Path(study) / "private_analysis" / "manifest.json")
    output = []
    multirater = []
    if manifest["study_type"] == "ddx":
        raters, fixed, selections = ddx_selections(root)
        matrix = [
            [("Yes" if label.strip().casefold() in selections[rid, cid] else "No")
             if (rid, cid) in selections else None
             for rid in raters]
            for cid, labels in fixed.items() for label in labels.values()
        ]
        # Missing DDx case-level annotations contribute no candidate decisions.
        multirater.append({"field": "fixed_candidate_selection",
                           **multi_rater_agreement(matrix, len(raters))})
        for i, j in combinations(range(len(raters)), 2):
            a, b = raters[i], raters[j]
            overlap = sorted(cid for cid in fixed if (a, cid) in selections and (b, cid) in selections)
            sets = [(selections[a, cid], selections[b, cid]) for cid in overlap]
            decisions = []
            for cid, (x, y) in zip(overlap, sets):
                # Fixed candidates only; custom labels have no common prespecified universe.
                decisions.extend(("Yes" if label.strip().casefold() in x else "No",
                                  "Yes" if label.strip().casefold() in y else "No")
                                 for label in fixed[cid].values())
            output.append({"raters": [i + 1, j + 1], "completed_overlap": len(overlap),
                           "exact_set_agreement": sum(x == y for x, y in sets)/len(sets) if sets else None,
                           "mean_jaccard": sum(len(x & y)/len(x | y) for x, y in sets)/len(sets) if sets else None,
                           "fixed_candidate_agreement": kappa(decisions)})
    else:
        cases = load_cases(root)
        raters, observed = read_observed(root, cases)
        matrices = defaultdict(list)
        for case in cases:
            for p in case["pairs"]:
                for field in rubric_fields(p):
                    matrices[p["stage"], field].append(
                        [observed.get((rid, p["pair_id"]), {}).get(field) for rid in raters])
        for (stage, field), matrix in sorted(matrices.items()):
            multirater.append({"stage": stage, "field": field,
                               **multi_rater_agreement(matrix, len(raters))})
        for i, j in combinations(range(len(raters)), 2):
            a, b = raters[i], raters[j]
            groups = defaultdict(list)
            expected = Counter()
            for case in cases:
                for p in case["pairs"]:
                    for field in rubric_fields(p):
                        group = (p["stage"], field)
                        expected[group] += 1
                        x = observed.get((a, p["pair_id"]), {}).get(field)
                        y = observed.get((b, p["pair_id"]), {}).get(field)
                        if x and y:
                            groups[group].append((x, y))
            for stage, field in sorted(expected):
                output.append({"raters": [i + 1, j + 1], "stage": stage, "field": field,
                               "expected_items": expected[stage, field], **kappa(groups[stage, field])})
    return {"study_type": manifest["study_type"], "n_raters": len(raters),
            "pairwise_agreement": output,
            "multi_rater_agreement": multirater,
            "note": "Local analysis; review small contingency cells before sharing."}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--study", required=True, type=Path)
    p.add_argument("--out", required=True, type=Path)
    a = p.parse_args()
    result = analyze(a.study)
    if a.out.resolve().is_relative_to((a.study / "annotation_inputs").resolve()):
        p.error("Output must be outside served data root")
    with a.out.open("x", encoding="utf-8") as handle:
        json.dump(result, handle, indent=2, allow_nan=False)
        handle.write("\n")
    print("Agreement analysis complete.")


if __name__ == "__main__":
    main()
