import json
import sqlite3
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import pytest

from study2.cli import main, watch_once
from study2.common import PipelineError, atomic_json, digest
from study2.legacy import legacy_files, migrate_legacy
from study2.review import active_decisions, apply_field_decisions, export_review, import_review
from study2.store import connect, current
from test_pipeline_integration import execute, project


def test_partial_batch_is_ignored_and_invalid_ready_preserves_current(project):
    first = execute(project)
    cfg, manifest, _, _ = project
    inbox = Path(cfg['project_root']) / 'inbox'
    inbox.mkdir()
    cfg['inbox_dir'] = str(inbox)
    atomic_json(inbox / 'partial.json', manifest)
    assert watch_once(cfg) == []
    broken = {**manifest, 'sources': []}
    atomic_json(inbox / 'broken.ready.json', broken)
    result = watch_once(cfg)
    assert result[0]['error'] and (inbox / 'failed' / 'broken.ready.json').exists()
    assert (inbox / 'partial.json').exists()
    db = connect(Path(cfg['state_dir']))
    assert current(db)['release_id'] == first['release_id']
    db.close()


def test_backup_cli_restores_its_release_without_overwriting(project, capsys):
    first = execute(project)
    cfg, _, _, _ = project
    cfg['inbox_dir'] = str(Path(cfg['project_root']) / 'inbox')
    config = Path(cfg['project_root']) / 'config.json'
    atomic_json(config, cfg)
    backup = Path(cfg['release_dir']) / first['release_id'] / 'backup.sqlite'
    destination = Path(cfg['project_root']) / 'restored.sqlite'
    argv = ['study2', '--config', str(config), 'restore', str(backup), '--destination', str(destination)]
    with patch('sys.argv', argv):
        main()
    restored = sqlite3.connect(destination)
    assert restored.execute('SELECT release_id FROM publication').fetchone()[0] == first['release_id']
    assert restored.execute('SELECT COUNT(*) FROM submissions').fetchone()[0] == 4
    restored.close()
    with patch('sys.argv', argv), pytest.raises(SystemExit) as error:
        main()
    assert error.value.code == 1 and 'never overwrite' in capsys.readouterr().err


def test_unreadable_ready_handoff_sets_dashboard_failure_without_changing_release(project):
    first = execute(project)
    cfg, _, _, _ = project
    inbox = Path(cfg['project_root']) / 'inbox'
    inbox.mkdir()
    cfg['inbox_dir'] = str(inbox)
    path = inbox / 'locked.ready.json'
    path.write_text('{}')
    original_read = Path.read_text

    def locked_read(target, *args, **kwargs):
        if target == path:
            raise OSError(11, 'Resource deadlock avoided')
        return original_read(target, *args, **kwargs)

    with patch.object(Path, 'read_text', locked_read):
        result = watch_once(cfg)
    event = json.loads((Path(cfg['state_dir']) / 'last_failure.json').read_text())
    assert event['batch'] == path.name and 'Resource deadlock' in event['error']
    assert result[0]['error'] and (inbox / 'failed' / path.name).exists()
    db = connect(Path(cfg['state_dir']))
    assert current(db)['release_id'] == first['release_id']
    assert db.execute('SELECT COUNT(*) FROM submissions').fetchone()[0] == 4
    db.close()


def test_excel_field_correction_is_validated_applied_and_idempotent(project):
    execute(project)
    cfg, _, _, _ = project
    db = connect(Path(cfg['state_dir']))
    path = Path(cfg['project_root']) / 'review.xlsx'
    export_review(db, cfg, path)
    sheets = {key: value.fillna('') for key, value in pd.read_excel(path, sheet_name=None, dtype=str).items()}
    index = sheets['submissions'].query("role == 'student'").iloc[0]
    release = current(db)
    correction = {'release_id': release['release_id'], 'case_id': 'NEW_RECORD',
                  'record_a': index['submission_id'], 'version_a': index['version_id'],
                  'record_b': '', 'action': 'SET_FIELD', 'reviewer': 'Synthetic reviewer',
                  'reason': 'Verified source transcription', 'value': json.dumps({'field': 'student_PHQ_01', 'value': 4})}
    sheets['cases'] = pd.DataFrame([correction])
    def save():
        with pd.ExcelWriter(path) as writer:
            for key, frame in sheets.items():
                frame.to_excel(writer, sheet_name=key, index=False)
    save()
    with pytest.raises(PipelineError, match='outside questionnaire coding'):
        import_review(db, cfg, path)
    assert db.execute('SELECT COUNT(*) FROM decisions').fetchone()[0] == 0
    sheets['cases'].loc[0, 'value'] = json.dumps({'field': 'student_PHQ_01', 'value': 2})
    save()
    assert import_review(db, cfg, path)['corrections'] == 1
    import_review(db, cfg, path)
    assert db.execute('SELECT COUNT(*) FROM decisions').fetchone()[0] == 1
    record = json.loads(db.execute('SELECT payload_json FROM normalized_records WHERE submission_id=?', (index['submission_id'],)).fetchone()[0])
    before = dict(record['raw'])
    corrected = apply_field_decisions([record], active_decisions(db))[0]
    assert corrected['answer']['student_PHQ_01'] == 2 and corrected['raw'] == before
    db.close()


def test_changed_source_content_adds_version_without_new_submission(project):
    first = execute(project)
    cfg, _, rows, _ = project
    row = rows[0]
    row['raw'] = {'answer': 'updated synthetic response'}
    row['raw_hash'] = digest(row['raw'])
    row['version_id'] = digest([row['submission_id'], row['raw_hash']])
    row['answer']['student_PHQ_01'] = 2
    second = execute(project, force=True)
    assert second['submissions'] == first['submissions'] == 4
    db = connect(Path(cfg['state_dir']))
    assert db.execute('SELECT COUNT(*) FROM submissions').fetchone()[0] == 4
    assert db.execute('SELECT COUNT(*) FROM submission_versions').fetchone()[0] == 5
    assert db.execute('SELECT COUNT(*) FROM submission_versions WHERE submission_id=?', (row['submission_id'],)).fetchone()[0] == 2
    db.close()


def test_unresolvable_legacy_aliases_are_not_applied_as_current_ids(tmp_path):
    db = connect(tmp_path / 'state')
    folder = tmp_path / '2.1.6_manual_swap'
    folder.mkdir()
    pd.DataFrame([{'entry_id_1': 'stale_a', 'entry_id_2': 'stale_b'}]).to_excel(folder / 'false-single.xlsx', index=False)
    report = migrate_legacy(db, {'project_root': str(tmp_path)}, [])
    assert report[0]['migration_status'] == 'pending_unresolved_observation'
    assert db.execute('SELECT COUNT(*) FROM decisions').fetchone()[0] == 0
    db.close()


def test_qualtrics_only_scope_does_not_read_historical_manual_data(tmp_path):
    db = connect(tmp_path / 'state')
    folder = tmp_path / '2.1.6_manual_swap'
    folder.mkdir()
    (folder / 'false-single.xlsx').write_bytes(b'Unrelated invalid workbook must not be read')
    cfg = {'project_root': str(tmp_path), 'source_scope': 'qualtrics_only'}
    assert legacy_files(cfg) == []
    assert migrate_legacy(db, cfg, []) == []
    db.close()
