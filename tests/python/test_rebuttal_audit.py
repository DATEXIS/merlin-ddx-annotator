import csv
from pathlib import Path
from zipfile import ZipFile

from fastapi.testclient import TestClient

from merlin_ddx.sync_api import create_app


def test_blinded_audit_order_privacy_and_independent_stage_answers(tmp_path: Path):
    source = tmp_path / 'source' / 'merlin_rebuttal_audit'
    source.mkdir(parents=True)
    with (source / 'audit_batch1_notes.csv').open('w', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=['hadm_id', 'chief_complaint', 'admission_note'])
        writer.writeheader()
        writer.writerow({'hadm_id': '123', 'chief_complaint': 'cough', 'admission_note': 'Exact\n note text.'})
    with (source / 'audit_batch1_blinded.csv').open('w', newline='') as handle:
        fields = ['pair_id', 'hadm_id', 'chief_complaint', 'stage', 'target_A', 'reason_A', 'target_B', 'reason_B']
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerow(dict(zip(fields, ['2', '123', 'cough', 'V4', 'J18.9', 'Why A', 'R05.9', 'Why B'])))
        writer.writerow(dict(zip(fields, ['1', '123', 'cough', 'V2', 'Pneumonia', 'Earlier A', 'Pneumonia', 'Earlier B'])))
    (source / 'audit_batch1_keyed.csv').write_text('SECRET_KEYED_FIELD\n')
    with ZipFile(tmp_path / 'source' / 'icd10cm-Code-Descriptions-2026.zip', 'w') as archive:
        archive.writestr('icd10cm-order-2026.txt', '\n'.join(
            f"00001 {code:<7} 1{'':63}{description}" for code, description in [
                ('J189', 'Pneumonia, unspecified organism'), ('R059', 'Cough, unspecified')
            ]
        ))
    client = TestClient(create_app(tmp_path, sync_git=False))
    response = client.get('/api/rebuttal-audit')
    assert response.status_code == 200
    body = response.json()
    assert 'SECRET_KEYED_FIELD' not in response.text
    assert body[0]['admission_note'] == 'Exact\n note text.'
    assert [pair['stage'] for pair in body[0]['pairs']] == ['V2', 'V4']
    assert body[0]['pairs'][1]['target_A'] == 'J18.9'
    assert body[0]['pairs'][1]['description_A'] == 'Pneumonia, unspecified organism'
    url = '/api/rebuttal-audit/annotations/clinician/123'
    legacy_v2 = {'A_Q1_evidence_grounded': 'Yes', 'A_Q2_supports_target': 'No',
                 'B_Q1_evidence_grounded': 'Unclear', 'B_Q2_supports_target': 'Yes'}
    assert client.put(url, json={'pairs': {'1': {**legacy_v2, 'preference_A_B_equivalent': 'A'}}}).status_code == 200
    assert client.put(url, json={'pairs': {'2': {'A_Q1': 'Yes'}}}).status_code == 200
    assert client.put(url, json={'pairs': {'2': {'target_preference_A_B_equal': 'A'}}}).status_code == 400
    assert client.put(url, json={'pairs': {'2': {'rationale_preference_A_B_equal': 'B'}}}).status_code == 400
    assert client.put(url, json={'pairs': {'1': {'target_preference_A_B_equal': 'Equal'}}}).status_code == 400
    v4 = {'A_Q1': 'Yes', 'A_Q2': 'No', 'B_Q1': 'Unclear', 'B_Q2': 'Yes'}
    assert client.put(url, json={'pairs': {'2': {**v4, 'target_preference_A_B_equal': 'Equal',
                                               'rationale_preference_A_B_equal': 'Equivalent'}}}).status_code == 200
    new_v2 = {'A_Q1': 'Yes', 'A_Q2': 'No', 'B_Q1': 'Unclear', 'B_Q2': 'Yes'}
    assert client.put(url, json={'pairs': {'1': {**new_v2, 'rationale_preference_A_B_equal': 'A'}}}).status_code == 200
    saved = client.get('/api/rebuttal-audit/annotations/clinician').json()[0]
    assert saved['hadm_id'] == '123'
    assert saved['pairs']['1']['pair_id'] == '1'
    assert saved['pairs']['1']['target_preference_A_B_equal'] is None
    assert saved['pairs']['1']['preference_A_B_equivalent'] == 'A'
    assert saved['pairs']['2']['target_preference_A_B_equal'] == 'Equal'
    assert saved['pairs']['2']['rationale_preference_A_B_equal'] == 'Equivalent'
    assert saved['pairs']['2']['A_Q1'] == 'Yes'
    assert client.put(url, json={'pairs': saved['pairs']}).status_code == 200
