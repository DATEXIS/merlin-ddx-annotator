"""Published contingency matrices reproduce the published and reported agreement statistics."""
from __future__ import annotations

import csv
import io
import json

import pytest

from conftest import ROOT, load_script

kappa = load_script("kappa_from_contingency")


def test_published_matrices_reproduce_every_kappa(monkeypatch):
    monkeypatch.setattr("sys.argv", ["kappa_from_contingency.py", "--results", str(ROOT / "results")])
    assert kappa.main() == 0


def test_reported_coding_stage_agreement():
    with (ROOT / "results" / "agreement_contingency_matrices.csv").open(newline="", encoding="utf-8") as handle:
        table = kappa.kappa_table(list(csv.DictReader(handle)))
    composite = table["V4.valid_composite"]
    assert composite["level"] == "full"
    assert round(composite["p_o"], 2) == 0.73 and round(composite["kappa"], 2) == 0.39


def test_known_matrix():
    rows = [{"measure_id": "m", "n_items": "4", "disclosure_level": "full", "cell_type": "joint",
             "rater_A_category": a, "rater_B_category": b, "count": str(n)}
            for a, b, n in (("Yes", "Yes", 1), ("Yes", "No", 0), ("No", "Yes", 1), ("No", "No", 2))]
    rows += [{"measure_id": "m", "n_items": "4", "disclosure_level": "full", "cell_type": kind,
              "rater_A_category": a if kind.endswith("A") else "", "rater_B_category": "" if kind.endswith("A") else a,
              "count": str(n)} for kind, a, n in (("marginal_rater_A", "Yes", 1), ("marginal_rater_A", "No", 3),
                                                  ("marginal_rater_B", "Yes", 2), ("marginal_rater_B", "No", 2))]
    result = kappa.kappa_table(rows)["m"]
    assert result["p_o"] == pytest.approx(0.75) and result["p_e"] == pytest.approx(0.5) and result["kappa"] == pytest.approx(0.5)


def test_public_results_carry_no_item_level_data():
    for path in (ROOT / "results").iterdir():
        text = path.read_text(encoding="utf-8")
        if path.suffix == ".csv":
            header = next(csv.reader(io.StringIO(text)))
            assert not {"item_id", "pair_id", "case_id", "hadm_id", "rater", "rationale_text"} & set(header), path.name
    statistics = json.loads((ROOT / "results" / "agreement_statistics.json").read_text())
    for measure in statistics["measures"]:
        if "rows" in measure["contingency"]:
            assert (measure["contingency"]["rows"], measure["contingency"]["columns"]) == ("rater_A", "rater_B")
