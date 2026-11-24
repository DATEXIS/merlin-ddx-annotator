#!/usr/bin/env python
"""Coverage, selection and set-agreement statistics of the 350-case DDx annotation study.

    python scripts/ddx_agreement.py --fixture .demo/ddx_fixture --out .demo/ddx_study/agreement.json

The original scale-up script (scripts/analyse_scaleup_annotations.py) computes
pairwise Cohen's kappa and Fleiss' kappa. The manuscript additionally reports
coverage, selection counts, exact-set agreement, Jaccard similarity and nesting,
which no archived script computes. This script computes them from the same case
construction (``analyse_annotations.build_cases``: candidate ``dN`` and added ``oN``
diagnoses resolved to labels, restricted to the sampling frame) with these
definitions:

* completed record: an annotator's record for a case with at least one positive mark;
* coverage: completed records per annotator; pairwise overlap; cases with completed
  records from at least two annotators and from all annotators;
* selections: mean number of positive diagnoses per completed record, share of
  records with more than one (multi-label), positives that are added diagnoses;
* for each pair, on cases both completed: exact-set agreement (identical positive
  sets), mean Jaccard |A n B| / |A u B|, and nesting (B's set contained in A's,
  identical sets included; A's strictly contained in B's);
* for each pair, the candidate-level 2 x 2 table behind Cohen's kappa, built exactly
  as ``cohen_kappa_binary`` builds it (candidates = WikiDoc list plus marked added
  diagnoses; unchecked = not selected) on the pairs the scale-up script uses (both
  annotators have a record, even one without a positive mark). Its kappa equals the
  scale-up script's.
"""
from __future__ import annotations

import argparse
import contextlib
import io
import json
import sys
from itertools import combinations
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))


def contingency(cases_a: dict, cases_b: dict, base) -> dict:
    a11 = a10 = a01 = a00 = 0
    for pid in sorted(set(cases_a) & set(cases_b)):
        sa, sb = set(cases_a[pid]["clinician_true"]), set(cases_b[pid]["clinician_true"])
        for candidate in base._case_universe(cases_a[pid], sa | sb):
            ca, cb = candidate in sa, candidate in sb
            a11 += ca and cb
            a10 += ca and not cb
            a01 += cb and not ca
            a00 += not ca and not cb
    total = a11 + a10 + a01 + a00
    p_o = (a11 + a00) / total
    p_a, p_b = (a11 + a10) / total, (a11 + a01) / total
    p_e = p_a * p_b + (1 - p_a) * (1 - p_b)
    return {"both_selected": a11, "only_first": a10, "only_second": a01, "neither": a00, "candidates": total,
            "p_o": p_o, "p_e": p_e, "kappa": (p_o - p_e) / (1 - p_e)}


def compute(data_root: Path, pool: Path, diagnoses: Path, sample_csv: Path, annotators: list[str]) -> dict:
    import pandas as pd

    import analyse_annotations as base
    from merlin_ddx.annotation_store import list_annotation_records, list_custom_diagnoses
    from merlin_ddx.paths import data_paths

    paths = data_paths(data_root)
    records = [r.to_json() for r in list_annotation_records(paths)]
    custom = {p.stem: [i.to_json() for i in list_custom_diagnoses(paths, p.stem)]
              for p in sorted(paths.custom_diagnoses_dir.glob("*.json"))}
    base.DIAG_DIR = diagnoses
    base._REGEX_CACHE.clear()
    base._VECTOR_CACHE.clear()
    base.fetch_custom_diagnoses = lambda pids, offline: {pid: custom.get(pid, []) for pid in pids}
    frame = set(pd.read_csv(sample_csv)["hadm_id"].astype(int))
    df = pd.read_parquet(pool)
    built: dict[str, dict[str, dict]] = {}
    for annotator in annotators:
        base.ANNOTATOR = annotator
        with contextlib.redirect_stdout(io.StringIO()):
            cases = base.build_cases(records, df, offline=True)
        built[annotator] = {c["pid"]: c for c in cases if c["hadm"] in frame}
    completed = {a: {pid: c for pid, c in cs.items() if c["clinician_true"]} for a, cs in built.items()}

    per_annotator = {}
    for annotator, cases in completed.items():
        n = len(cases)
        selections = [len(c["clinician_true"]) for c in cases.values()]
        added = sum(1 for c in cases.values() for d in c["clinician_true"] if d not in set(c["diseases"]))
        by_cc: dict[str, int] = {}
        for c in cases.values():
            by_cc[c["chief"]] = by_cc.get(c["chief"], 0) + 1
        per_annotator[annotator] = {
            "completed_records": n, "records_without_positive_mark": len(built[annotator]) - n,
            "completed_by_chief_complaint": dict(sorted(by_cc.items())),
            "positive_selections": sum(selections), "added_diagnosis_selections": added,
            "candidate_list_selections": sum(selections) - added,
            "mean_selections": sum(selections) / n if n else None,
            "multi_label_records": sum(s > 1 for s in selections),
            "multi_label_rate": sum(s > 1 for s in selections) / n if n else None,
        }
    pairs = []
    for a, b in combinations(annotators, 2):
        common = sorted(set(completed[a]) & set(completed[b]))
        sets = [(set(completed[a][p]["clinician_true"]), set(completed[b][p]["clinician_true"])) for p in common]
        n = len(common)
        pairs.append({
            "first": a, "second": b, "n_both_completed": n,
            "exact_set_agreement": sum(x == y for x, y in sets) / n if n else None,
            "identical_sets": sum(x == y for x, y in sets),
            "mean_jaccard": sum(len(x & y) / len(x | y) for x, y in sets) / n if n else None,
            "second_within_first": sum(y <= x for x, y in sets),
            "first_strictly_within_second": sum(x < y for x, y in sets),
            "n_kappa_cases": len(set(built[a]) & set(built[b])),
            "contingency": contingency(built[a], built[b], base) if set(built[a]) & set(built[b]) else None,
        })
    sets = [set(completed[a]) for a in annotators]
    union = set().union(*sets)
    at_least_two = {p for p in union if sum(p in s for s in sets) >= 2}
    return {
        "frame_size": len(frame), "annotators": annotators, "per_annotator": per_annotator, "pairs": pairs,
        "cases_with_any_completed_record": len(union),
        "cases_with_at_least_two_annotators": len(at_least_two),
        "cases_with_all_annotators": len(set.intersection(*sets)) if sets else 0,
        "definitions": "see the docstring of scripts/ddx_agreement.py and docs/ddx_annotation/analysis.md",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--fixture", type=Path, help="output directory of make_synthetic_ddx_fixture.py")
    parser.add_argument("--data-root", type=Path)
    parser.add_argument("--pool", type=Path)
    parser.add_argument("--diagnoses", type=Path)
    parser.add_argument("--sample-csv", type=Path)
    parser.add_argument("--annotators", default="synthetic_rater_1,synthetic_rater_2,synthetic_rater_3")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.fixture:
        args.data_root = args.data_root or args.fixture / "data_root"
        args.pool = args.pool or args.fixture / "pool.pq"
        args.diagnoses = args.diagnoses or args.fixture / "diagnoses"
        args.sample_csv = args.sample_csv or args.fixture / "sample.csv"
    if not all((args.data_root, args.pool, args.diagnoses, args.sample_csv)):
        parser.error("give --fixture or all of --data-root, --pool, --diagnoses, --sample-csv")
    result = compute(args.data_root, args.pool, args.diagnoses, args.sample_csv,
                     [a.strip() for a in args.annotators.split(",") if a.strip()])
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(f"[ddx_agreement] {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
