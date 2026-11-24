"""The original analysis pipeline runs end-to-end on full-size synthetic data."""
from __future__ import annotations

from collections import Counter

import pandas as pd
import pytest

from merlin_ddx.rebuttal_analysis import AuditValidationError, run_pipeline


@pytest.fixture(scope="module")
def original_run(analysis_fixture, tmp_path_factory):
    out = tmp_path_factory.mktemp("run") / "batch"
    raters = {k: v for k, v in analysis_fixture.items() if k not in ("blinded", "keyed")}
    run_pipeline(blinded_path=analysis_fixture["blinded"], keyed_path=analysis_fixture["keyed"], raters=raters,
                 output_dir=out)
    return out


def test_pipeline_writes_the_tables_behind_the_paper(original_run):
    for name in ("table1_accounting", "table2_quality", "primary_differences", "table3_preferences",
                 "table5_reliability", "loop_accepted", "run_metadata"):
        assert any(original_run.glob(f"{name}.*")), name
    accounting = pd.read_csv(original_run / "table1_accounting.csv")
    assert accounting.n_pairs.tolist() == [42, 42] and accounting.n_rater_judgments.tolist() == [84, 84]


def test_kappa_matches_an_independent_count(original_run, analysis_fixture):
    analysis = pd.read_csv(original_run / "audit_batch1_analysis.csv", dtype=str, keep_default_na=False)
    reliability = pd.read_csv(original_run / "table5_reliability.csv")
    for stage in ("V2", "V4"):
        rows = analysis[analysis.stage == stage]
        first, second = sorted(rows.rater_id.unique())
        a = rows[rows.rater_id == first].set_index("pair_id").sort_index()
        b = rows[rows.rater_id == second].set_index("pair_id").sort_index()
        left = [*a.loop_valid, *a.zero_shot_valid]
        right = [*b.loop_valid, *b.zero_shot_valid]
        n = len(left)
        p_o = sum(x == y for x, y in zip(left, right)) / n
        lc, rc = Counter(left), Counter(right)
        p_e = sum(lc[c] * rc[c] for c in set(left) | set(right)) / n ** 2
        published = reliability[(reliability.stage == stage) & (reliability.outcome == "valid")].iloc[0]
        assert published.raw_agreement == pytest.approx(p_o)
        assert published.cohen_kappa == pytest.approx((p_o - p_e) / (1 - p_e))


def test_pipeline_refuses_incomplete_ratings(analysis_fixture, tmp_path):
    exports = {k: v for k, v in analysis_fixture.items() if k not in ("blinded", "keyed")}
    rater, directory = next(iter(exports.items()))
    partial = tmp_path / rater
    partial.mkdir()
    for path in sorted(directory.glob("*.json"))[:-1]:
        (partial / path.name).write_bytes(path.read_bytes())
    with pytest.raises(AuditValidationError):
        run_pipeline(blinded_path=analysis_fixture["blinded"], keyed_path=analysis_fixture["keyed"],
                     raters={**exports, rater: partial}, output_dir=tmp_path / "out")
    assert not (tmp_path / "out").exists()
