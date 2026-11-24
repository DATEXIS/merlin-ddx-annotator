"""Shared helpers for the synthetic-only test suite."""
from __future__ import annotations

import csv
import importlib.util
import json
import shutil
import sys
from itertools import combinations
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SYNTHETIC = ROOT / "examples" / "synthetic"
sys.path.insert(0, str(ROOT))


def load_script(name: str):
    """Import a file from scripts/ as a module."""
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def demo_data_root(tmp_path: Path) -> Path:
    """A writable copy of the synthetic data root."""
    target = tmp_path / "data_root"
    shutil.copytree(SYNTHETIC / "data_root", target)
    return target


@pytest.fixture(scope="session")
def analysis_fixture(tmp_path_factory) -> dict[str, Path]:
    """Full-size (42 admissions, 84 pairs) synthetic dataset for the original pipeline."""
    out = tmp_path_factory.mktemp("analysis_fixture")
    return load_script("make_synthetic_analysis_fixture").build(out)


def per_item_aggregates(fixture: dict[str, Path]) -> list[dict[str, str]]:
    """Per-item aggregates in the credentialed (PhysioNet) schema, built from synthetic exports.

    Mirrors the released format: for each rationale (Pnnn-L / Pnnn-Z) and pair item, the
    unordered distribution of the two raters' categories. case_id is the admission ID, so
    sorting case_ids reproduces the original bootstrap order.
    """
    with fixture["keyed"].open(newline="", encoding="utf-8") as handle:
        key = {r["pair_id"]: r for r in csv.DictReader(handle)}
    raters = [k for k in fixture if k not in ("blinded", "keyed")]
    answers = {}
    for rater in raters:
        for record_path in sorted(fixture[rater].glob("*.json")):
            record = json.loads(record_path.read_text(encoding="utf-8"))
            for pair_id, answer in record["pairs"].items():
                answers[(rater, pair_id)] = answer
    rows = []
    for pair_id, k in sorted(key.items(), key=lambda item: int(item[0])):
        arms = {"A": "loop" if k["_A_arm"] == "loop" else "zero_shot", "B": "loop" if k["_B_arm"] == "loop" else "zero_shot"}
        same = k["target_A"] == k["target_B"]
        base = {"case_id": k["hadm_id"], "pair_id": f"P{int(pair_id):03d}", "stage": k["stage"]}
        for side, arm in arms.items():
            values = {"Q1_evidence_grounded": [], "Q2_supports_target": [], "valid_composite": []}
            for rater in raters:
                q1, q2 = answers[(rater, pair_id)][f"{side}_Q1"], answers[(rater, pair_id)][f"{side}_Q2"]
                values["Q1_evidence_grounded"].append(q1)
                values["Q2_supports_target"].append(q2)
                values["valid_composite"].append("valid" if q1 == q2 == "Yes" else "not_valid")
            scales = {"Q1_evidence_grounded": ["Yes", "No", "Unclear"], "Q2_supports_target": ["Yes", "No", "Unclear"],
                      "valid_composite": ["valid", "not_valid"]}
            for criterion, ratings in values.items():
                rows.append(_row(base, f"P{int(pair_id):03d}-{'L' if arm == 'loop' else 'Z'}", arm, criterion,
                                 scales[criterion], ratings))
        for criterion, field, tie in (("target_preference", "target_preference_A_B_equal", "equal"),
                                      ("rationale_preference", "rationale_preference_A_B_equal", "equivalent")):
            ratings = []
            for rater in raters:
                choice = answers[(rater, pair_id)].get(field)
                ratings.append("not_applicable" if criterion == "target_preference" and same else arms.get(choice, tie))
            rows.append(_row(base, f"P{int(pair_id):03d}", "loop_vs_zero_shot", criterion, ["loop", "zero_shot", tie], ratings))
    return rows


def _row(base: dict, item_id: str, condition: str, criterion: str, scale: list[str], ratings: list[str]) -> dict[str, str]:
    valid = [r for r in ratings if r in scale]
    pairs = list(combinations(valid, 2))
    return {**base, "item_id": item_id, "condition": condition, "criterion": criterion, "scale": "|".join(scale),
            "n_raters": str(len(valid)), "n_missing": "0", "n_not_applicable": str(ratings.count("not_applicable")),
            "rating_distribution": json.dumps({c: valid.count(c) for c in scale}, separators=(",", ":")),
            "agreement_fraction": f"{sum(a == b for a, b in pairs) / len(pairs):.4f}" if pairs else ""}
