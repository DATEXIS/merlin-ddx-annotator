"""Synthetic numerical checks for multi-rater nominal agreement."""
from pathlib import Path
import sys
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
from analyze_interrater_agreement import multi_rater_agreement


def test_fleiss_classical_example():
    # Classical ten subjects, fourteen raters, five categories.
    counts = [[0, 0, 0, 0, 14], [0, 2, 6, 4, 2], [0, 0, 3, 5, 6],
              [0, 3, 9, 2, 0], [2, 2, 8, 1, 1], [7, 7, 0, 0, 0],
              [3, 2, 6, 3, 0], [2, 5, 3, 2, 2], [6, 5, 2, 1, 0],
              [0, 2, 2, 3, 7]]
    rows = [[str(k) for k, n in enumerate(row) for _ in range(n)] for row in counts]
    result = multi_rater_agreement(rows, 14)
    assert result["fleiss_kappa"]["kappa"] == pytest.approx(0.20993070442195522)
    assert result["fleiss_kappa"]["n_items"] == 10


def test_missing_aware_alpha_and_complete_case_kappa():
    # Pairable units contain 3, 2, and 2 ratings; singletons are excluded.
    rows = [["Yes", "Yes", "No"], ["Yes", None, "Yes"], ["No", "No", ""],
            ["Unclear", None, None], [None, None, None]]
    result = multi_rater_agreement(rows, 3)
    assert result["ratings_per_item_histogram"] == {"0": 1, "1": 1, "2": 2, "3": 1}
    f = result["fleiss_kappa"]
    assert f["n_items"] == 1 and f["excluded_items"] == 4
    assert f["kappa"] == pytest.approx(-0.5)
    a = result["krippendorff_alpha_nominal"]
    assert a["n_items"] == 3 and a["n_ratings"] == 7
    assert a["category_counts"] == {"Yes": 4, "No": 3}
    assert a["observed_disagreement"] == pytest.approx(2/7)
    assert a["expected_disagreement"] == pytest.approx(4/7)
    assert a["alpha"] == pytest.approx(0.5)


def test_perfect_disagreement_and_degenerate_cases():
    perfect = multi_rater_agreement([["Yes"]*3, ["No"]*3], 3)
    assert perfect["fleiss_kappa"]["kappa"] == 1
    assert perfect["krippendorff_alpha_nominal"]["alpha"] == 1
    opposite = multi_rater_agreement([["Yes", "No"], ["No", "Yes"]], 2)
    assert opposite["fleiss_kappa"]["kappa"] == -1
    assert opposite["krippendorff_alpha_nominal"]["alpha"] == pytest.approx(-0.5)
    for rows, n in [([], 3), ([["Yes"]*3], 3), ([["Yes"], ["No"]], 1)]:
        result = multi_rater_agreement(rows, n)
        assert result["fleiss_kappa"]["kappa"] is None
        assert result["krippendorff_alpha_nominal"]["alpha"] is None
    with pytest.raises(ValueError):
        multi_rater_agreement([["Yes"]], 2)


def test_unclear_is_a_category_not_missing():
    result = multi_rater_agreement([["Unclear", "Unclear"], ["Yes", "No"]], 2)
    assert result["krippendorff_alpha_nominal"]["category_counts"] == {"Unclear": 2, "Yes": 1, "No": 1}
    assert result["ratings_per_item_histogram"]["2"] == 2
