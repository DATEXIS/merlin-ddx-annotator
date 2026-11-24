#!/usr/bin/env python
"""Write synthetic inputs for the original DDx-annotation analysis.

    python scripts/make_synthetic_ddx_fixture.py --out .demo/ddx_fixture               # the 9 demo cases
    python scripts/make_synthetic_ddx_fixture.py --out .demo/ddx_full --full-size       # 70 + 350 cases

The original analysis (``scripts/analyse_annotations.py`` for the pilot,
``scripts/analyse_scaleup_annotations.py`` for the 350-case study) reads a case pool
with one row per admission and model, the per-chief-complaint candidate schemes, the
sampling frame of the 350-case study and the annotation store. This script writes
all of them, synthetically, in the same layout:

    <out>/pool.pq                         hadm_id, split, Chief Complaint, disease, diseases,
                                          diseases_cossim_scores, ICD_CODES, gen_model,
                                          v1_preds, v2_preds, v3_preds, v4_preds
    <out>/sample.csv, sample.meta.json    sampling frame of the 350-case study
    <out>/pilot_cohort.json               case ids of the pilot cohort
    <out>/annotators.json                 annotator roster
    <out>/diagnoses/<chief>.csv           candidate schemes (Disease, Synonyms, icd10_regex, features)
    <out>/data_root/annotations/<rater>/<case>.json, data_root/custom_diagnoses/<case>.json

Default: the demonstration cases and synthetic ratings of examples/synthetic/ddx/.
``--full-size``: a random cohort of the study's size (70 pilot cases, 10 per chief
complaint, half train / half test; 350 study cases, 50 per chief complaint) with
three synthetic raters. The rater overlap of the full-size cohort is arbitrary
(rater 1 all cases, rater 2 about 60%, rater 3 about 30% of the study cases) and is
not the study's.
"""
from __future__ import annotations

import argparse
import csv
import json
import random
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import build_synthetic_ddx_demo as demo  # noqa: E402

MODELS = ("Llama-3.3-70B-Instruct", "Qwen3-32B", "medgemma-27b-it")
MODEL_KEYS = {"llama": MODELS[0], "qwen": MODELS[1], "medgemma": MODELS[2]}
FULL_SEED = 20260101


def example_code(regex: str) -> str:
    """A code matching a scheme regex such as ``^I2[124]`` or ``^(K81|K80[01])``."""
    body = regex.lstrip("^")
    if body.startswith("("):
        body = body[1:].split(")")[0].split("|")[0]
    return re.sub(r"\[([A-Z0-9])[^\]]*\]", r"\1", body) + "9"


def pool_rows(spec: dict, cases: list[dict]) -> list[dict]:
    rows = []
    for case in cases:
        cc = demo.chief(case)
        hadm = int(case["id"].split("-", 1)[0])
        n = len(case["candidates"])
        for key, model in MODEL_KEYS.items():
            prediction = case["predictions"][key]
            rows.append({
                "hadm_id": hadm, "split": case["split"], "Chief Complaint": cc.replace("_", " ").capitalize(),
                "disease": case["candidates"][0], "diseases": list(case["candidates"]),
                "diseases_cossim_scores": [round(0.82 - 0.035 * i, 3) for i in range(n)],
                "ICD_CODES": [code for code, _ in case["icd"]], "gen_model": model,
                "v1_preds": list(prediction["v1"]), "v2_preds": list(prediction["v2"]),
                "v3_preds": list(prediction["v3"]), "v4_preds": list(prediction["v4"]),
            })
    return rows


def random_cases(spec: dict) -> tuple[list[dict], dict[str, dict[str, list[str]]], dict[str, list[dict]]]:
    rng = random.Random(FULL_SEED)
    cases, ratings, custom = [], {}, {}
    number = 910000
    for dataset, per_cc in (("pilot", 10), ("test350", 50)):
        for cc in sorted(spec["schemes"]):
            names = [row[0] for row in spec["schemes"][cc]]
            regex = {row[0]: row[1] for row in spec["schemes"][cc]}
            for index in range(per_cc):
                number += 1
                truth = rng.choice(names)
                candidates = rng.sample(names, len(names))
                others = [n for n in names if n != truth]
                distractor = rng.choice(others)
                icd = [(example_code(regex[truth]), truth)] if rng.random() < 0.85 else []
                icd.append((example_code(regex[distractor]), distractor))
                predictions = {}
                for key in MODEL_KEYS:
                    def ranking(hit: float) -> list[str]:
                        order = rng.sample(others, 4)
                        order.insert(0 if rng.random() < hit else rng.randint(1, 4), truth)
                        return order
                    v4 = [example_code(regex[truth])] if rng.random() < 0.6 else []
                    v4.append(example_code(regex[rng.choice(others)]))
                    predictions[key] = {"v1": [rng.randint(0, 1) for _ in spec["features"]],
                                        "v2": ranking(0.55), "v3": ranking(0.65), "v4": v4}
                split = ("train" if index < per_cc // 2 else "test") if dataset == "pilot" else "test"
                case_id = f"{number}-{cc}"
                cases.append({"id": case_id, "dataset": dataset, "split": split, "candidates": candidates,
                              "icd": icd, "predictions": predictions})
                raters = ["synthetic_rater_1"]
                if dataset == "test350":
                    raters += [r for r, p in (("synthetic_rater_2", 0.6), ("synthetic_rater_3", 0.3)) if rng.random() < p]
                case_ratings = {}
                for rater in raters:
                    roll = rng.random()
                    if roll < 0.05:
                        label = f"Synthetic added diagnosis {number}"
                        custom.setdefault(case_id, [{"label": label, "createdBy": rater}])
                        marks = [label]
                    else:
                        marks = [truth if roll < 0.85 else rng.choice(others)]
                        if rng.random() < 0.08:
                            marks.append(rng.choice([n for n in others if n not in marks]))
                    case_ratings[rater] = marks
                ratings[case_id] = case_ratings
    return cases, ratings, custom


def write_store(out: Path, cases: list[dict], ratings: dict, custom: dict) -> None:
    for case in cases:
        ids = {name: f"d{i}" for i, name in enumerate(case["candidates"], start=1)}
        added = [{"id": f"o{i}", "label": item["label"], "createdBy": item["createdBy"], "createdAt": demo.SAVED_AT}
                 for i, item in enumerate(custom.get(case["id"], []), start=1)]
        if added:
            path = out / "data_root" / "custom_diagnoses" / f"{case['id']}.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(added, indent=2) + "\n", encoding="utf-8")
        added_ids = {item["label"]: item["id"] for item in added}
        for rater, labels in ratings.get(case["id"], {}).items():
            path = out / "data_root" / "annotations" / rater / f"{case['id']}.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            marks = {(ids.get(label) or added_ids[label]): True for label in labels}
            path.write_text(json.dumps({"annotatorId": rater, "patientId": case["id"], "updatedAt": demo.SAVED_AT,
                                        "annotations": marks}, indent=2) + "\n", encoding="utf-8")


def build(out: Path, full_size: bool = False) -> dict[str, Path]:
    import pandas as pd

    spec = demo.load_spec()
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    if full_size:
        cases, ratings, custom = random_cases(spec)
        write_store(out, cases, ratings, custom)
    else:
        cases = spec["cases"]
        shutil.copytree(demo.DDX / "annotations", out / "data_root" / "annotations")
        shutil.copytree(demo.DDX / "custom_diagnoses", out / "data_root" / "custom_diagnoses")
    pd.DataFrame(pool_rows(spec, cases)).to_parquet(out / "pool.pq", index=False)
    study = [c for c in cases if c["dataset"] == "test350"]
    with (out / "sample.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(["hadm_id", "split", "Chief Complaint", "disease"])
        for case in study:
            writer.writerow([case["id"].split("-", 1)[0], "test", demo.chief(case), case["candidates"][0]])
    n_pilot = sum(c["dataset"] == "pilot" for c in cases)
    meta = {"seed": FULL_SEED if full_size else None, "target_per_chief": 50 if full_size else None,
            "gt_column": "disease", "frame": "synthetic test split", "pool_file": "pool.pq",
            "excluded_pilot_cases": n_pilot, "allocation": "synthetic (no sampling)",
            "total_selected": len(study), "note": "Synthetic fixture; not the study's sample."}
    (out / "sample.meta.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    pilot = [c["id"] for c in cases if c["dataset"] == "pilot"]
    (out / "pilot_cohort.json").write_text(json.dumps(pilot, indent=2) + "\n", encoding="utf-8")
    annotators = [{"id": f"synthetic_rater_{i}", "name": f"Synthetic rater {i}", "type": "human", "active": True}
                  for i in (1, 2, 3)]
    (out / "annotators.json").write_text(json.dumps(annotators, indent=2) + "\n", encoding="utf-8")
    (out / "diagnoses").mkdir()
    for cc in sorted(spec["schemes"]):
        (out / "diagnoses" / f"{cc}.csv").write_bytes(demo.scheme_csv(spec, cc))
    return {"pool": out / "pool.pq", "sample_csv": out / "sample.csv", "sample_meta": out / "sample.meta.json",
            "annotators_json": out / "annotators.json", "diagnoses": out / "diagnoses",
            "data_root": out / "data_root", "pilot_cohort": out / "pilot_cohort.json"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--full-size", action="store_true", help="random cohort of the study's size")
    args = parser.parse_args()
    paths = build(args.out.resolve(), args.full_size)
    print(json.dumps({k: str(v) for k, v in paths.items()}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
