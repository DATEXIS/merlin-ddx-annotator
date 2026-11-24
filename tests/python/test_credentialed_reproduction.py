"""Per-item aggregates (the credentialed release format) reproduce the original pipeline exactly."""
from __future__ import annotations

import pandas as pd
import pytest

from conftest import load_script, per_item_aggregates
from merlin_ddx.rebuttal_analysis import run_pipeline

reproduce = load_script("reproduce_from_credentialed")


@pytest.fixture(scope="module")
def both(analysis_fixture, tmp_path_factory):
    out = tmp_path_factory.mktemp("run") / "batch"
    raters = {k: v for k, v in analysis_fixture.items() if k not in ("blinded", "keyed")}
    run_pipeline(blinded_path=analysis_fixture["blinded"], keyed_path=analysis_fixture["keyed"], raters=raters,
                 output_dir=out)
    return out, reproduce.reproduce(per_item_aggregates(analysis_fixture))


def test_rates_and_intervals_match(both):
    run, mine = both
    quality = pd.read_csv(run / "table2_quality.csv")
    quality = quality[quality.group == "pooled"]
    for _, row in quality.iterrows():
        for key, criterion in (("Q1", "Q1_evidence_grounded"), ("Q2", "Q2_supports_target"), ("valid", "valid_composite")):
            ours = mine["rates"][(row.stage, row.arm, criterion)]
            pct = row[f"{key}_yes_pct"] if key != "valid" else row["valid_pct"]
            low = row[f"{key}_ci_low"] if key != "valid" else row["valid_ci_low"]
            high = row[f"{key}_ci_high"] if key != "valid" else row["valid_ci_high"]
            assert ours["pct"] == pytest.approx(pct, abs=1e-9)
            assert ours["ci_low"] == pytest.approx(100 * low, abs=1e-9)
            assert ours["ci_high"] == pytest.approx(100 * high, abs=1e-9)


def test_differences_and_preference_margins_match(both):
    run, mine = both
    differences = pd.read_csv(run / "primary_differences.csv")
    for _, row in differences[differences.group == "pooled"].iterrows():
        for key, criterion in (("Q1", "Q1_evidence_grounded"), ("Q2", "Q2_supports_target"), ("valid", "valid_composite")):
            ours = mine["differences"][(row.stage, criterion)]
            assert ours["estimate"] == pytest.approx(row[f"delta_{key}_pp"], abs=1e-9)
            assert ours["ci_low"] == pytest.approx(row[f"delta_{key}_ci_low"], abs=1e-9)
            assert ours["ci_high"] == pytest.approx(row[f"delta_{key}_ci_high"], abs=1e-9)
    preferences = pd.read_csv(run / "table3_preferences.csv")
    for _, row in preferences[preferences.group == "pooled"].iterrows():
        ours = mine["preferences"][(row.stage, f"{row.preference_type}_preference")]
        assert (ours["loop_n"], ours["zero_shot_n"]) == (row.loop_n, row.zero_shot_n)
        assert ours["margin"] == pytest.approx(row.margin_pp, abs=1e-9)
        assert ours["ci_low"] == pytest.approx(row.margin_ci_low, abs=1e-9)
        assert ours["ci_high"] == pytest.approx(row.margin_ci_high, abs=1e-9)


def test_raw_agreement_matches_but_kappa_needs_more_than_aggregates(both):
    run, mine = both
    reliability = pd.read_csv(run / "table5_reliability.csv")
    names = {"Q1": "Q1_evidence_grounded", "Q2": "Q2_supports_target", "valid": "valid_composite",
             "rationale_preference": "rationale_preference", "target_preference": "target_preference"}
    for _, row in reliability.iterrows():
        assert mine["raw_agreement"][f"{row.stage}.{names[row.outcome]}"] == pytest.approx(row.raw_agreement, abs=1e-12)
    assert not any("kappa" in key for key in mine)
