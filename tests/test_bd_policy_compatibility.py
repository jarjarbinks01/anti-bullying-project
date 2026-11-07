"""Optional native BD policy preserves the historical configuration boundary."""
import sqlite3

from study2 import runner
from study2.bd_pairing import POLICY


def test_policy_fingerprint_preserves_legacy_rule_vector(monkeypatch, tmp_path):
    from study2 import dyads, legacy
    monkeypatch.setattr(runner, 'calculation_hash', lambda cfg: 'synthetic-code')
    monkeypatch.setattr(runner, 'file_hash', lambda path: 'synthetic-dictionary')
    monkeypatch.setattr(runner, 'active_decisions', lambda db: [])
    monkeypatch.setattr(runner, 'digest', lambda payload: payload)
    monkeypatch.setattr(dyads, 'administrative_fingerprint', lambda db: 'synthetic-registration')
    monkeypatch.setattr(legacy, 'legacy_files', lambda cfg: [])
    cfg = dict(state_dir=str(tmp_path), project_root=str(tmp_path), mapping_hashes={},
               sources=[], duplicate_days=30, minimum_followup_days=90,
               bd_requires_same_adult=True, parent_wave_policy='synthetic-wave-policy')
    db = sqlite3.connect(':memory:')
    db.execute('CREATE TABLE labels (case_id TEXT)')
    try:
        original = runner.fingerprint(cfg, {'sources': []}, db)
        assert original['rules'] == [30, 90, {}, True, None, 'synthetic-wave-policy']
        explicit_null = runner.fingerprint({**cfg, 'bd_pairing_policy': None}, {'sources': []}, db)
        assert explicit_null == original
        selected_child = runner.fingerprint({**cfg, 'bd_pairing_policy': POLICY}, {'sources': []}, db)
        assert selected_child['rules'] == original['rules'] + [POLICY]
        assert cfg['bd_requires_same_adult'] is True and 'bd_pairing_policy' not in cfg
    finally:
        db.close()
