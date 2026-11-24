"""Synthetic audit only: the real blinded/keyed data are never analyzed here."""
import csv
import json
from pathlib import Path

import pandas as pd
import pytest

from merlin_ddx.rebuttal_analysis import AuditValidationError, load_annotation_export, run_pipeline


def make_synthetic_batch(root: Path) -> tuple[Path, Path, dict[str, Path]]:
    root.mkdir(parents=True, exist_ok=True)
    blinded = root / 'blind.csv'
    keyed = root / 'key.csv'
    blind_rows, key_rows = [], []
    annotations = {'rater_one': {}, 'rater_two': {}}
    complaints = ['abdominal_pain', 'back_pain', 'chest_pain', 'cough',
                  'diarrhea', 'dyspnea', 'headache']
    for admission in range(42):
        hadm = str(20_000_000 + admission)
        for stage_index, stage in enumerate(('V2', 'V4')):
            pair_id = str(admission * 2 + stage_index + 1)
            if stage == 'V2':
                target_a = 'Pneumonia'
                target_b = 'Pneumonia' if admission % 2 == 0 else 'Cough'
            else:
                target_a = 'J18.9'
                target_b = 'J18.9' if admission % 3 == 0 else 'J18.1'
            row = {'pair_id': pair_id, 'hadm_id': hadm,
                   'chief_complaint': complaints[admission // 6], 'stage': stage,
                   'target_A': target_a, 'reason_A': 'Synthetic rationale A',
                   'target_B': target_b, 'reason_B': 'Synthetic rationale B'}
            blind_rows.append(row)
            loop_is_a = admission % 2 == 0
            key_rows.append({**row, '_A_arm': 'loop' if loop_is_a else 'zero_shot',
                             '_B_arm': 'zero_shot' if loop_is_a else 'loop',
                             '_zs_in_gold': '1', '_loop_in_gold': '1',
                             '_v4_code_matched_cell': '1' if stage == 'V4' and admission % 3 == 0 else '0',
                             '_zs_score': '0.6', '_loop_score': '0.7',
                             '_loop_accepted': '1' if admission % 2 == 0 else '0',
                             '_confirmed_diagnosis': 'Pneumonia',
                             '_words_A': str(12 + admission % 4), '_words_B': str(16 + admission % 4)})
            for rater_index, rater in enumerate(annotations):
                answer = {'pair_id': pair_id, 'hadm_id': hadm,
                          'A_Q1': 'Unclear' if admission == 0 and rater_index == 0 else 'Yes',
                          'A_Q2': 'Yes', 'B_Q1': 'No' if admission % 5 == 0 else 'Yes',
                          'B_Q2': 'Yes',
                          'target_preference_A_B_equal': None if target_a == target_b else ('A' if admission % 4 else 'Equal'),
                          'rationale_preference_A_B_equal': 'A' if admission % 3 else 'Equivalent',
                          'rater_comment': ''}
                annotations[rater].setdefault(hadm, {})[pair_id] = answer
    for path, rows in ((blinded, blind_rows), (keyed, key_rows)):
        with path.open('w', newline='') as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
    export_paths = {}
    for rater, by_hadm in annotations.items():
        path = root / f'{rater}.json'
        path.write_text(json.dumps([{'annotatorId': rater, 'hadm_id': hadm, 'pairs': pairs}
                                    for hadm, pairs in by_hadm.items()]))
        export_paths[rater] = path
    return blinded, keyed, export_paths


def test_incomplete_export_stops_before_key_is_opened(tmp_path: Path):
    blinded, keyed, raters = make_synthetic_batch(tmp_path / 'inputs')
    records = json.loads(raters['rater_two'].read_text())
    del records[0]['pairs']['1']['rationale_preference_A_B_equal']
    raters['rater_two'].write_text(json.dumps(records))
    keyed.unlink()  # The missing key must not be the first reported error.
    output = tmp_path / 'out'
    with pytest.raises(AuditValidationError, match='Missing 1 rationale preferences'):
        run_pipeline(blinded_path=blinded, keyed_path=keyed, raters=raters, output_dir=output)
    assert not output.exists()


def test_json_directory_and_long_csv_export_formats(tmp_path: Path):
    _, _, raters = make_synthetic_batch(tmp_path / 'inputs')
    records = json.loads(raters['rater_one'].read_text())
    directory = tmp_path / 'json_records'
    directory.mkdir()
    for record in records:
        (directory / f"{record['hadm_id']}.json").write_text(json.dumps(record))
    assert len(load_annotation_export(directory, 'rater_one')) == 84
    records = json.loads(raters['rater_two'].read_text())
    rows = [{**answer, 'rater_id': 'rater_two'} for record in records
            for answer in record['pairs'].values()]
    csv_path = tmp_path / 'ratings.csv'
    with csv_path.open('w', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    assert len(load_annotation_export(csv_path, 'rater_two')) == 84


def test_keyed_randomization_must_match_frozen_blind_pairs(tmp_path: Path):
    blinded, keyed, raters = make_synthetic_batch(tmp_path / 'inputs')
    rows = list(csv.DictReader(keyed.open()))
    rows[0]['target_A'] = 'Changed diagnosis'
    with keyed.open('w', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    output = tmp_path / 'report'
    with pytest.raises(AuditValidationError, match='Keyed/blinded mismatch in target_A'):
        run_pipeline(blinded_path=blinded, keyed_path=keyed, raters=raters, output_dir=output)
    assert not output.exists()


def test_synthetic_completed_batch_produces_reproducible_outputs(tmp_path: Path, monkeypatch):
    monkeypatch.setenv('MPLCONFIGDIR', str(tmp_path / 'mplcache'))
    blinded, keyed, raters = make_synthetic_batch(tmp_path / 'inputs')
    originals = {path: path.read_bytes() for path in (blinded, keyed, *raters.values())}
    output = tmp_path / 'report'
    run_pipeline(blinded_path=blinded, keyed_path=keyed, raters=raters,
                 output_dir=output, bootstrap_replicates=10_000, seed=123)
    assert all(path.read_bytes() == content for path, content in originals.items())
    assert (output / 'audit_batch1_report.md').exists()
    assert (output / 'audit_batch1_summary.csv').exists()
    assert (output / 'figures/figure1_absolute_quality.pdf').exists()
    assert (output / 'figures/figure2_rationale_preference.png').exists()
    assert (output / 'figures/figure3_controlled_subsets.pdf').exists()
    analysis = pd.read_csv(output / 'audit_batch1_analysis.csv')
    assert len(analysis) == 168
    assert set(analysis.A_arm) == {'loop', 'zero_shot'}
    assert set(analysis.rationale_preferred) == {'loop', 'zero_shot', 'equivalent'}
    assert analysis.loc[analysis.same_target, 'target_preferred'].eq('not_applicable').all()
    report = (output / 'audit_batch1_report.md').read_text()
    assert 'Candidate rebuttal wording' in report
    assert 'We agree that our verifier does not establish step-level logical validity' in report
    with pytest.raises(AuditValidationError, match='already exists'):
        run_pipeline(blinded_path=blinded, keyed_path=keyed, raters=raters, output_dir=output)
