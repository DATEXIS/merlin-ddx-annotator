#!/usr/bin/env python
"""Summarize synthetic demo ratings the way the study aggregated clinician ratings.

    python scripts/demo_summary.py                       # committed synthetic ratings
    python scripts/demo_summary.py --ratings .demo/data_root/rebuttal_audit_annotations
    python scripts/demo_summary.py --check               # verify examples/synthetic/expected/

Decodes the blinded A/B answers with the separate allocation key (as the offline
analysis did), then reports, per stage and arm, the rating distributions, Q1/Q2
Yes-rates and the composite (valid = Q1 Yes and Q2 Yes), the decoded target and
rationale preferences, and raw agreement and Cohen's kappa computed with the
original agreement function (``merlin_ddx.rebuttal_analysis._agreement``).

The original analysis pipeline itself is fixed to the study design (42 admissions,
84 pairs) and refuses a 5-admission demo; see ``scripts/run_original_analysis.py``
for running it on a full-size synthetic dataset. Demo numbers are illustrations of
the procedure only, not study results.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from merlin_ddx.rebuttal_analysis import _agreement  # noqa: E402

SYNTHETIC = ROOT / "examples" / "synthetic"
JUDGMENTS = ["Yes", "No", "Unclear"]


def _rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def summarize(ratings_dir: Path) -> dict:
    blinded = {r["pair_id"]: r for r in _rows(SYNTHETIC / "data_root/source/merlin_rebuttal_audit/audit_batch1_blinded.csv")}
    key = {r["pair_id"]: r for r in _rows(SYNTHETIC / "allocation_key.csv")}
    raters = sorted(p.name for p in ratings_dir.iterdir() if p.is_dir())
    if len(raters) != 2:
        raise SystemExit(f"Expected exactly two rater directories in {ratings_dir}; found {raters}")
    decoded: dict[str, dict[str, dict]] = {r: {} for r in raters}
    for rater in raters:
        for record_path in sorted((ratings_dir / rater).glob("*.json")):
            record = json.loads(record_path.read_text(encoding="utf-8"))
            for pair_id, answer in record["pairs"].items():
                arms = {"A": "loop" if key[pair_id]["_A_arm"] == "loop" else "zero_shot",
                        "B": "loop" if key[pair_id]["_B_arm"] == "loop" else "zero_shot"}
                row = {"stage": blinded[pair_id]["stage"], "same_target": blinded[pair_id]["target_A"] == blinded[pair_id]["target_B"]}
                for side, arm in arms.items():
                    q1, q2 = answer.get(f"{side}_Q1") or "", answer.get(f"{side}_Q2") or ""
                    row[f"{arm}_Q1"], row[f"{arm}_Q2"] = q1, q2
                    row[f"{arm}_valid"] = "valid" if q1 == q2 == "Yes" else "not_valid"
                decode = lambda choice, tie: arms.get(choice, tie) if choice else "not_applicable"  # noqa: E731
                row["target_preference"] = decode(answer.get("target_preference_A_B_equal"), "equal")
                row["rationale_preference"] = decode(answer.get("rationale_preference_A_B_equal"), "equivalent")
                row["has_comment"] = bool((answer.get("rater_comment") or "").strip())
                decoded[rater][pair_id] = row
    pair_ids = sorted(blinded, key=int)
    missing = [(r, p) for r in raters for p in pair_ids if p not in decoded[r]]
    if missing:
        raise SystemExit(f"Incomplete ratings: {len(missing)} rater-pair answers missing")
    summary: dict = {"_note": "SYNTHETIC demonstration ratings; illustrates the procedure, not study results.",
                     "raters": raters, "n_admissions": len({blinded[p]["hadm_id"] for p in pair_ids}),
                     "n_pairs": len(pair_ids), "stages": {}}
    for stage in ("V2", "V4"):
        ids = [p for p in pair_ids if blinded[p]["stage"] == stage]
        rows = [decoded[r][p] for r in raters for p in ids]
        stage_summary: dict = {"n_pairs": len(ids), "n_judgments": len(rows),
                               "loop_accepted_pairs": sum(key[p]["_loop_accepted"] == "True" for p in ids),
                               "arms": {}, "preferences": {}, "agreement": {}}
        for arm in ("loop", "zero_shot"):
            arm_summary = {}
            for criterion, categories in (("Q1", JUDGMENTS), ("Q2", JUDGMENTS), ("valid", ["valid", "not_valid"])):
                counts = Counter(row[f"{arm}_{criterion}"] for row in rows)
                favourable = "valid" if criterion == "valid" else "Yes"
                arm_summary[criterion] = {"distribution": {c: counts.get(c, 0) for c in categories},
                                          "favourable_pct": round(100 * counts.get(favourable, 0) / len(rows), 1)}
            stage_summary["arms"][arm] = arm_summary
        stage_summary["valid_difference_loop_minus_zero_shot_pp"] = round(
            stage_summary["arms"]["loop"]["valid"]["favourable_pct"] - stage_summary["arms"]["zero_shot"]["valid"]["favourable_pct"], 1)
        for preference, tie in (("target_preference", "equal"), ("rationale_preference", "equivalent")):
            counts = Counter(row[preference] for row in rows)
            stage_summary["preferences"][preference] = {c: counts.get(c, 0) for c in ("loop", "zero_shot", tie, "not_applicable")}
        first, second = raters
        for criterion, categories in (("Q1", JUDGMENTS), ("Q2", JUDGMENTS), ("valid", ["valid", "not_valid"])):
            left = [decoded[first][p][f"{arm}_{criterion}"] for p in ids for arm in ("loop", "zero_shot")]
            right = [decoded[second][p][f"{arm}_{criterion}"] for p in ids for arm in ("loop", "zero_shot")]
            observed, kappa = _agreement(left, right, categories)
            stage_summary["agreement"][criterion] = {"n_items": len(left), "raw_agreement": round(observed, 4),
                                                     "cohen_kappa": None if kappa is None else round(kappa, 4)}
        for preference, categories in (("rationale_preference", ["loop", "zero_shot", "equivalent"]),
                                       ("target_preference", ["loop", "zero_shot", "equal"])):
            applicable = [p for p in ids if decoded[first][p][preference] != "not_applicable"]
            left = [decoded[first][p][preference] for p in applicable]
            right = [decoded[second][p][preference] for p in applicable]
            observed, kappa = _agreement(left, right, categories)
            stage_summary["agreement"][preference] = {
                "n_items": len(left), "raw_agreement": None if observed is None else round(observed, 4),
                "cohen_kappa": None if kappa is None else round(kappa, 4)}
        summary["stages"][stage] = stage_summary
    summary["n_comments"] = sum(row["has_comment"] for r in raters for row in decoded[r].values())
    return summary


def markdown(summary: dict) -> str:
    lines = ["# Synthetic demo: expected analysis output", "",
             "**Synthetic ratings by two synthetic raters on five synthetic admissions.** These numbers show how the "
             "study aggregated ratings; they are not study results.", ""]
    for stage, s in summary["stages"].items():
        lines += [f"## {stage} ({s['n_pairs']} pairs, {s['n_judgments']} rater-pair judgments)", "",
                  "| Arm | Q1 Yes % | Q2 Yes % | Valid % | Q1 Yes/No/Unclear | Q2 Yes/No/Unclear |", "|---|---|---|---|---|---|"]
        for arm, a in s["arms"].items():
            q1, q2 = a["Q1"]["distribution"], a["Q2"]["distribution"]
            lines.append(f"| {arm} | {a['Q1']['favourable_pct']} | {a['Q2']['favourable_pct']} | {a['valid']['favourable_pct']} | "
                         f"{q1['Yes']}/{q1['No']}/{q1['Unclear']} | {q2['Yes']}/{q2['No']}/{q2['Unclear']} |")
        lines += ["", f"Loop minus zero-shot validity: {s['valid_difference_loop_minus_zero_shot_pp']} pp.", "",
                  "| Preference | Loop | Zero-shot | Tie | Not applicable |", "|---|---|---|---|---|"]
        for name, p in s["preferences"].items():
            tie = p.get("equal", p.get("equivalent"))
            lines.append(f"| {name} | {p['loop']} | {p['zero_shot']} | {tie} | {p['not_applicable']} |")
        lines += ["", "| Agreement | Items | Raw agreement | Cohen's kappa |", "|---|---|---|---|"]
        for name, a in s["agreement"].items():
            lines.append(f"| {name} | {a['n_items']} | {a['raw_agreement']} | {a['cohen_kappa']} |")
        lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--ratings", type=Path, default=SYNTHETIC / "ratings",
                        help="directory with one sub-directory of JSON records per rater")
    parser.add_argument("--check", action="store_true", help="fail if examples/synthetic/expected/ is out of date")
    parser.add_argument("--out", type=Path, default=SYNTHETIC / "expected")
    args = parser.parse_args()
    summary = summarize(args.ratings)
    outputs = {args.out / "demo_summary.json": json.dumps(summary, indent=2) + "\n",
               args.out / "demo_summary.md": markdown(summary)}
    if args.check:
        stale = [p for p, text in outputs.items() if not p.is_file() or p.read_text(encoding="utf-8") != text]
        for path in stale:
            print(f"out of date: {path}", file=sys.stderr)
        return 1 if stale else 0
    if args.ratings.resolve() != (SYNTHETIC / "ratings").resolve() and args.out == SYNTHETIC / "expected":
        print(markdown(summary))
        return 0
    args.out.mkdir(parents=True, exist_ok=True)
    for path, text in outputs.items():
        path.write_text(text, encoding="utf-8")
    print(f"wrote {', '.join(p.name for p in outputs)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
