#!/usr/bin/env python
"""Build the synthetic demonstration inputs from ``examples/synthetic/demo_cases.json``.

Writes, in exactly the formats the study used:

* ``examples/synthetic/data_root/`` - what the annotation server reads
  (annotator list, blinded pair file, admission notes, ICD-10-CM catalog subset);
* ``examples/synthetic/allocation_key.csv`` - which response is loop / zero-shot,
  kept outside the server's data root as in the study (blinding);
* ``examples/synthetic/ratings/<rater>/<case>.json`` - synthetic rating exports in
  the app's record format, each validated with the study's server-side rules.

All content is synthetic. ``--check`` verifies the committed files are up to date.
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from merlin_ddx.rebuttal_audit import load_cases, validate_answers  # noqa: E402

EXAMPLES = ROOT / "examples" / "synthetic"
BLINDED_COLUMNS = ["pair_id", "hadm_id", "chief_complaint", "stage", "target_A", "reason_A", "target_B", "reason_B",
                   "preference_A_B_equivalent", "A_Q1_evidence_grounded", "A_Q2_supports_target",
                   "B_Q1_evidence_grounded", "B_Q2_supports_target", "rater_comment"]
KEY_COLUMNS = ["pair_id", "hadm_id", "stage", "_A_arm", "_B_arm", "_loop_score", "_loop_accepted", "_words_A", "_words_B"]
SAVED_AT = "2026-01-01T00:00:00Z"   # fixed so the build is deterministic


def _csv(rows: list[dict], columns: list[str]) -> bytes:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=columns, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue().encode("utf-8")


def _zip(member: str, data: bytes) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        info = zipfile.ZipInfo(member, date_time=(2026, 1, 1, 0, 0, 0))
        info.compress_type = zipfile.ZIP_DEFLATED
        archive.writestr(info, data)
    return buffer.getvalue()


def build() -> dict[Path, bytes]:
    spec = json.loads((EXAMPLES / "demo_cases.json").read_text(encoding="utf-8"))
    files: dict[Path, bytes] = {}
    data_root = EXAMPLES / "data_root"
    annotators = [{"id": r["id"], "name": r["name"], "type": "human", "active": True} for r in spec["raters"]]
    files[data_root / "app" / "annotators.json"] = (json.dumps(annotators, indent=2) + "\n").encode("utf-8")
    blinded, notes, key = [], [], []
    for case in spec["cases"]:
        notes.append({"hadm_id": case["hadm_id"], "chief_complaint": case["chief_complaint"],
                      "admission_note": case["admission_note"]})
        for pair in case["pairs"]:
            blinded.append({"pair_id": pair["pair_id"], "hadm_id": case["hadm_id"],
                            "chief_complaint": case["chief_complaint"], "stage": pair["stage"],
                            "target_A": pair["A"]["target"], "reason_A": pair["A"]["reason"],
                            "target_B": pair["B"]["target"], "reason_B": pair["B"]["reason"]})
            key.append({"pair_id": pair["pair_id"], "hadm_id": case["hadm_id"], "stage": pair["stage"],
                        "_A_arm": "loop" if pair["A"]["arm"] == "loop" else "zs",
                        "_B_arm": "loop" if pair["B"]["arm"] == "loop" else "zs",
                        "_loop_score": f"{pair['loop_score']:.2f}", "_loop_accepted": str(pair["loop_accepted"]),
                        "_words_A": str(len(pair["A"]["reason"].split())),
                        "_words_B": str(len(pair["B"]["reason"].split()))})
            if {pair["A"]["arm"], pair["B"]["arm"]} != {"loop", "zero_shot"}:
                raise SystemExit(f"pair {pair['pair_id']}: needs one loop and one zero_shot response")
    source = data_root / "source"
    files[source / "merlin_rebuttal_audit" / "audit_batch1_blinded.csv"] = _csv(blinded, BLINDED_COLUMNS)
    files[source / "merlin_rebuttal_audit" / "audit_batch1_notes.csv"] = _csv(notes, ["hadm_id", "chief_complaint", "admission_note"])
    catalog = (EXAMPLES / "icd10cm_order_2026_subset.txt").read_bytes()
    files[source / "icd10cm-Code-Descriptions-2026.zip"] = _zip("icd10cm-order-2026.txt", catalog)
    files[EXAMPLES / "allocation_key.csv"] = _csv(key, KEY_COLUMNS)

    # Validate every synthetic rating with the study's own server rules before writing it.
    with tempfile.TemporaryDirectory() as scratch:
        staging = Path(scratch)
        for path, content in files.items():
            if data_root in path.parents:
                target = staging / path.relative_to(data_root)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(content)
        cases = load_cases(staging)
        by_case = {c["hadm_id"]: c for c in cases}
        for rater, answers in spec["ratings"].items():
            for case in spec["cases"]:
                pairs = {}
                for pair in case["pairs"]:
                    a = answers[pair["pair_id"]]
                    answer = {"pair_id": pair["pair_id"], "hadm_id": case["hadm_id"],
                              "A_Q1": a["A_Q1"], "A_Q2": a["A_Q2"], "B_Q1": a["B_Q1"], "B_Q2": a["B_Q2"],
                              "target_preference_A_B_equal": a["target"],
                              "rationale_preference_A_B_equal": a["rationale"]}
                    if a.get("comment"):
                        answer["rater_comment"] = a["comment"]
                    pairs[pair["pair_id"]] = answer
                validate_answers(case["hadm_id"], pairs, cases)
                for pair in by_case[case["hadm_id"]]["pairs"]:
                    same = pair["target_A"] == pair["target_B"]
                    if same != (pairs[pair["pair_id"]]["target_preference_A_B_equal"] is None):
                        raise SystemExit(f"{rater} pair {pair['pair_id']}: target preference must be null exactly "
                                         "when the two targets are identical")
                record = {"annotatorId": rater, "hadm_id": case["hadm_id"], "updatedAt": SAVED_AT, "pairs": pairs}
                files[EXAMPLES / "ratings" / rater / f"{case['hadm_id']}.json"] = (
                    json.dumps(record, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    return files


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true", help="fail if committed files differ from a fresh build")
    args = parser.parse_args()
    files = build()
    stale = [p for p, c in files.items() if not p.is_file() or p.read_bytes() != c]
    if args.check:
        for path in stale:
            print(f"out of date: {path.relative_to(ROOT)}", file=sys.stderr)
        return 1 if stale else 0
    for path, content in files.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    print(f"wrote {len(files)} files ({len(stale)} changed)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
