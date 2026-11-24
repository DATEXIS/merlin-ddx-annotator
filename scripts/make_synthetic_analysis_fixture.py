#!/usr/bin/env python
"""Write a full-size synthetic dataset for the ORIGINAL analysis pipeline.

    python scripts/make_synthetic_analysis_fixture.py --out .demo/analysis_fixture

The original analysis (``merlin_ddx/rebuttal_analysis.py``) checks the study design
before it computes anything: exactly 42 admissions, 7 chief complaints x 6
admissions, 84 blinded pairs (one V2 and one V4 pair per admission) and two
complete rater exports. The five hand-written demo cases are too few, so this
script generates a deterministic placeholder dataset of that exact shape:

* ``audit_batch1_blinded.csv``  - what raters saw (A/B order, no arm identity);
* ``audit_batch1_keyed.csv``    - the allocation key, opened only after completion;
* ``exports/<rater>/<admission>.json`` - rating records in the app's export format.

Texts are random placeholder words, targets are placeholders, and ratings are drawn
at random: the dataset exercises the code path and has no clinical meaning.
"""
from __future__ import annotations

import argparse
import csv
import json
import random
from pathlib import Path

WORDS = ("amber basil cedar delta ember fjord garnet harbor indigo juniper kestrel lumen maple "
         "nectar onyx pepper quartz raven sable tundra umber velvet willow xenon yarrow zephyr").split()
COMPLAINTS = ("synthetic complaint a", "synthetic complaint b", "synthetic complaint c", "synthetic complaint d",
              "synthetic complaint e", "synthetic complaint f", "synthetic complaint g")
TEMPLATE = ("preference_A_B_equivalent", "A_Q1_evidence_grounded", "A_Q2_supports_target",
            "B_Q1_evidence_grounded", "B_Q2_supports_target", "rater_comment")
RATERS = ("synthetic_rater_1", "synthetic_rater_2")


def _sentence(rng: random.Random, n: int = 14) -> str:
    return " ".join(rng.choice(WORDS) for _ in range(n)) + "."


def _write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def build(out: Path, seed: int = 7) -> dict[str, Path]:
    rng = random.Random(seed)
    admissions = [f"SYNA{index:03d}" for index in range(1, 43)]
    rng.shuffle(admissions)
    blinded, keyed = [], []
    pair_id = 0
    for index, admission in enumerate(admissions):
        complaint = COMPLAINTS[index % 7]
        for stage in ("V2", "V4"):
            pair_id += 1
            same = rng.random() < 0.4
            if stage == "V2":
                loop_target = f"Synthetic diagnosis {rng.choice(WORDS)}"
                zero_target = loop_target if same else f"Synthetic diagnosis {rng.choice(WORDS)} two"
            else:
                loop_target = f"Z{rng.randint(10, 99)}.{rng.randint(0, 9)}"
                zero_target = loop_target if same else f"Z{rng.randint(10, 99)}"
            loop_text, zero_text = _sentence(rng), _sentence(rng)
            loop_first = rng.random() < 0.55
            score = round(rng.random(), 3)
            a, b = ((loop_target, loop_text), (zero_target, zero_text)) if loop_first else \
                ((zero_target, zero_text), (loop_target, loop_text))
            row = {"pair_id": str(pair_id), "hadm_id": admission, "chief_complaint": complaint, "stage": stage,
                   "target_A": a[0], "reason_A": a[1], "target_B": b[0], "reason_B": b[1], **{c: "" for c in TEMPLATE}}
            blinded.append(row)
            keyed.append({**row, "_A_arm": "loop" if loop_first else "zs", "_B_arm": "zs" if loop_first else "loop",
                          "_v4_code_matched_cell": str(stage == "V4" and same), "_loop_score": str(score),
                          "_loop_accepted": str(score >= 0.4),
                          "_confirmed_diagnosis": loop_target if stage == "V2" else "synthetic",
                          "_words_A": str(len(a[1].split())), "_words_B": str(len(b[1].split()))})
    _write_csv(out / "audit_batch1_blinded.csv", blinded)
    _write_csv(out / "audit_batch1_keyed.csv", keyed)
    exports = {}
    for rater in RATERS:
        directory = out / "exports" / rater
        directory.mkdir(parents=True, exist_ok=True)
        for admission in admissions:
            pairs = {}
            for row in (r for r in blinded if r["hadm_id"] == admission):
                answer = {"pair_id": row["pair_id"], "hadm_id": admission,
                          **{q: rng.choice(["Yes", "Yes", "Yes", "No", "Unclear"]) for q in ("A_Q1", "A_Q2", "B_Q1", "B_Q2")},
                          "target_preference_A_B_equal": None if row["target_A"] == row["target_B"]
                          else rng.choice(["A", "B", "Equal"]),
                          "rationale_preference_A_B_equal": rng.choice(["A", "B", "Equivalent"])}
                pairs[row["pair_id"]] = answer
            record = {"annotatorId": rater, "hadm_id": admission, "updatedAt": "2026-01-01T00:00:00Z", "pairs": pairs}
            (directory / f"{admission}.json").write_text(json.dumps(record, indent=1) + "\n", encoding="utf-8")
        exports[rater] = directory
    return {"blinded": out / "audit_batch1_blinded.csv", "keyed": out / "audit_batch1_keyed.csv", **exports}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", type=Path, default=Path(".demo") / "analysis_fixture")
    parser.add_argument("--seed", type=int, default=7)
    args = parser.parse_args()
    if args.out.exists() and any(args.out.iterdir()):
        parser.error(f"{args.out} is not empty")
    paths = build(args.out, args.seed)
    print(json.dumps({k: str(v) for k, v in paths.items()}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
