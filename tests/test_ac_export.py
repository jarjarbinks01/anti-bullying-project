"""Invented records and temporary files only; never consult research state."""
from copy import deepcopy
import csv
import gzip
import hashlib
import json
from pathlib import Path
import sqlite3

import pandas as pd
import pytest

from study2 import ac_export
from study2.ac_export import export_student_ac
from study2.analysis_eligibility import COPY_POLICY, MANIFEST_FORMAT, inventory_revision, manifest_revision
from study2.common import PipelineError, file_hash


@pytest.fixture
def published(tmp_path):
    state = tmp_path / 'source-state'
    folder = state / 'releases' / 'synthetic-release'
    folder.mkdir(parents=True)
    records = []
    for child in ('child-a', 'child-b'):
        for wave in ('T0', 'T1'):
            sid = f'{child}-student-{wave}'
            records.append(dict(submission_id=sid, version_id='version-'+sid,
                raw_hash=hashlib.sha256(sid.encode()).hexdigest(), role='student', child_id=child,
                selected_wave=wave, status='eligible',
                answer={'leading': '0012300', 'precise': 0.30000000000000004, 'zero': 0,
                        'false': False, 'missing': None, 'unicode': '合成資料\n"文字"',
                        'structured': {'items': [None, True, 0, '零'], 'nested': {'id': '0007'}}},
                raw={'source_value': '原值', 'leading': '0000123', 'missing': None},
                location={'sheet': 'Synthetic', 'row': len(records)+1}))
    for wave in ('T0', 'T1'):
        sid = 'parent-'+wave
        records.append(dict(submission_id=sid, version_id='version-'+sid,
            raw_hash=hashlib.sha256(sid.encode()).hexdigest(), role='parent', child_id='child-a',
            selected_wave=wave, status='eligible', answer={'parent_only': 'not joined'}, raw={}))
    records.append(dict(submission_id='spare-student', version_id='spare-version',
        raw_hash=hashlib.sha256(b'spare').hexdigest(), role='student', child_id='child-a',
        selected_wave=None, status='short_repeat', answer={'spare_only': 'not selected'}, raw={}))
    records[0]['answer']['future_field'] = 'retained without a field whitelist'
    records[0]['metadata_extension'] = {'nested': ['合成', None]}
    frame = pd.DataFrame([dict(submission_id=r['submission_id'], version_id=r['version_id'],
        role=r['role'], child_id=r['child_id'], wave=r['selected_wave'], longitudinal=True,
        precise=0.30000000000000004, score=float('nan') if r['submission_id']=='child-a-student-T0' else 0.0,
        active=r['selected_wave']=='T1', structured_score=[1.0, 2.0])
        for r in records if r['selected_wave']])
    dbfile = state / 'study2.sqlite'
    with sqlite3.connect(dbfile) as db:
        db.executescript('CREATE TABLE releases(release_id TEXT,run_id TEXT,created_at TEXT,path TEXT,stats_json TEXT);'
                         'CREATE TABLE publication(singleton INTEGER,release_id TEXT);')
        db.execute('INSERT INTO releases VALUES(?,?,?,?,?)',
            ('synthetic-release','synthetic-run','synthetic-date',str(folder),'{}'))
        db.execute('INSERT INTO publication VALUES(1,?)', ('synthetic-release',))
    def write():
        with gzip.open(folder / 'records.jsonl.gz', 'wt', encoding='utf-8') as stream:
            for r in records:
                stream.write(json.dumps(r, ensure_ascii=False)+'\n')
        frame.to_parquet(folder / 'analysis.parquet', index=False)
        (folder / 'checksums.json').write_text(json.dumps({name:file_hash(folder / name)
            for name in ('records.jsonl.gz','analysis.parquet')}))
    write()
    return dict(cfg={'state_dir': str(state)}, folder=folder, records=records,
                frame=frame, write=write, tmp=tmp_path)


def manifest(published, excluded=()):
    records = published['records']
    by_id = {r['submission_id']: r for r in records}
    result = dict(format=MANIFEST_FORMAT, release_id='synthetic-release', status='accepted',
        approved_by='Synthetic reviewer', approved_at='2025-01-01T00:00:00+00:00',
        inventory_revision=inventory_revision(records), copy_policy=COPY_POLICY,
        entries=[dict(submission_id=sid, version_id=by_id[sid]['version_id']) for sid in excluded])
    result['revision'] = manifest_revision(result)
    path = published['tmp'] / 'exclusions.json'
    path.write_text(json.dumps(result), encoding='utf-8')
    return path, result


def csv_rows(receipt):
    with Path(receipt['csv_path']).open(encoding='utf-8-sig', newline='') as stream:
        reader = csv.DictReader(stream)
        return reader.fieldnames, list(reader)


def test_full_fields_precision_types_and_no_outcome_restriction(published):
    p = published
    receipt = export_student_ac(p['cfg'], p['tmp'] / 'full')
    headers, rows = csv_rows(receipt)
    assert receipt['row_count'] == receipt['unique_children'] == 2
    assert receipt['selected_student_records'] == 4
    assert headers[:5] == list(ac_export.BASE_COLUMNS)
    assert len(headers) == len(set(headers))
    assert [r['child_id'] for r in rows] == ['child-a', 'child-b']
    first = rows[0]
    assert first['T0_current__leading'] == '0012300'
    assert first['T0_source__leading'] == '0000123'
    assert first['T0_current__precise'] == first['T0_analysis__precise'] == '0.30000000000000004'
    assert first['T0_analysis__score'] == first['T0_current__missing'] == ''
    assert first['T0_current__zero'] == '0'
    assert first['T1_analysis__score'] == '0.0'
    assert first['T0_current__false'] == first['T0_analysis__active'] == 'false'
    assert first['T1_analysis__active'] == 'true'
    assert first['T0_current__unicode'] == '合成資料\n"文字"'
    assert json.loads(first['T0_current__structured']) == {'items': [None, True, 0, '零'], 'nested': {'id': '0007'}}
    assert json.loads(first['T0_analysis__structured_score']) == [1.0, 2.0]
    assert first['T0_record__child_id'] == first['T0_analysis__child_id'] == 'child-a'
    assert first['T0_current__future_field'] == 'retained without a field whitelist'
    assert rows[1]['T0_current__future_field'] == ''
    assert json.loads(first['T0_record__metadata_extension']) == {'nested': ['合成', None]}
    for wave, record in zip(('T0', 'T1'), p['records'][:2]):
        assert all(f'{wave}_current__{key}' in headers for key in record['answer'])
        assert all(f'{wave}_source__{key}' in headers for key in record['raw'])
        assert all(f'{wave}_record__{key}' in headers for key in record if key not in {'answer','raw'})
        assert all(f'{wave}_analysis__{key}' in headers for key in p['frame'])
    assert not any('parent_only' in h or 'spare_only' in h for h in headers)
    assert Path(receipt['csv_path']).read_bytes().startswith(b'\xef\xbb\xbf')
    repeated = export_student_ac(p['cfg'], p['tmp'] / 'again')
    assert csv_rows(repeated) == (headers, rows)


def test_exact_pair_exclusion_never_selects_the_spare_response(published):
    p = published
    path, supplied = manifest(p, ['child-a-student-T0'])
    before = deepcopy(p['records'])
    receipt = export_student_ac(p['cfg'], p['tmp'] / 'excluded', manifest_path=path, enabled=True)
    _, rows = csv_rows(receipt)
    assert [r['child_id'] for r in rows] == ['child-b']
    assert receipt['fixed_AC_members'] == [['child-b-student-T0', 'child-b-student-T1']]
    assert receipt['exclusion_manifest']['manifest'] == supplied
    assert p['records'] == before
    off = export_student_ac(p['cfg'], p['tmp'] / 'off', manifest_path=path, enabled=False)
    assert off['row_count'] == 2 and off['manual_exclusion'] == 'OFF'
    path, _ = manifest(p, ['child-a-student-T0','child-b-student-T0'])
    empty = export_student_ac(p['cfg'], p['tmp'] / 'empty', manifest_path=path, enabled=True)
    assert empty['row_count'] == 0 and csv_rows(empty)[1] == []


def test_on_without_manifest_fails_before_reading_publication(published, monkeypatch):
    def forbidden(*args):
        raise AssertionError('invalid invocation must fail before source reads')
    monkeypatch.setattr(ac_export, '_published_release', forbidden)
    with pytest.raises(PipelineError, match='manifest required'):
        export_student_ac(published['cfg'], published['tmp'] / 'missing-manifest', enabled=True)


@pytest.mark.parametrize('enabled', [False, True])
def test_explicit_invalid_manifest_is_rejected(published, enabled):
    p = published
    path, value = manifest(p)
    value['revision'] = '0' * 64
    path.write_text(json.dumps(value))
    output = p['tmp'] / 'invalid-manifest'
    with pytest.raises(PipelineError):
        export_student_ac(p['cfg'], output, manifest_path=path, enabled=enabled)
    assert not output.exists()


@pytest.mark.parametrize('defect', ['duplicate-record','missing-record','duplicate-analysis','role','wave','child','empty-child','version','missing-section'])
def test_invalid_or_missing_pair_evidence_fails(published, defect):
    p = published
    if defect == 'duplicate-record':
        p['records'].append(deepcopy(p['records'][0]))
    elif defect == 'missing-record':
        p['records'].pop(0)
    elif defect == 'duplicate-analysis':
        p['frame'].loc[len(p['frame'])] = p['frame'].iloc[0]
    elif defect == 'role':
        p['frame'].loc[0, 'role'] = 'parent'
    elif defect == 'wave':
        p['frame'].loc[0, 'wave'] = 'T1'
    elif defect == 'child':
        p['frame'].loc[0, 'child_id'] = 'wrong-child'
    elif defect == 'empty-child':
        p['records'][0]['child_id'] = p['records'][1]['child_id'] = ''
        p['frame'].loc[:1, 'child_id'] = ''
    elif defect == 'version':
        p['frame'].loc[0, 'version_id'] = 'stale-version'
    else:
        del p['records'][0]['raw']
    p['write']()
    output = p['tmp'] / 'invalid-pair'
    with pytest.raises(PipelineError):
        export_student_ac(p['cfg'], output)
    assert not output.exists()


@pytest.mark.parametrize('existing', ['empty-directory','file','broken-symlink'])
def test_never_overwrites_existing_output(published, existing):
    output = published['tmp'] / 'existing'
    if existing == 'empty-directory': output.mkdir()
    elif existing == 'file': output.write_text('keep')
    else: output.symlink_to(published['tmp'] / 'missing-target')
    with pytest.raises(FileExistsError):
        export_student_ac(published['cfg'], output)
    assert output.exists() or output.is_symlink()
    if existing == 'file': assert output.read_text() == 'keep'


def test_provenance_and_read_only_source_without_recovery(published, monkeypatch):
    import study2.store
    import study2.maintenance
    p = published
    path, supplied = manifest(p)
    sources = [p['folder'] / 'records.jsonl.gz', p['folder'] / 'analysis.parquet',
               Path(p['cfg']['state_dir']) / 'study2.sqlite', path]
    pins = {source: file_hash(source) for source in sources}
    def prohibited(*args, **kwargs):
        raise AssertionError('source recovery/writer entry point used')
    monkeypatch.setattr(study2.store, 'connect', prohibited)
    monkeypatch.setattr(study2.maintenance, 'recover_activation', prohibited)
    receipt = export_student_ac(p['cfg'], p['tmp'] / 'readonly', manifest_path=path, enabled=True)
    assert pins == {source: file_hash(source) for source in sources}
    saved = json.loads(Path(receipt['manifest_path']).read_text())
    assert saved['publication']['release_id'] == 'synthetic-release'
    assert saved['publication']['run_id'] == 'synthetic-run'
    assert saved['exclusion_manifest']['sha256'] == pins[path]
    assert saved['exclusion_manifest']['manifest'] == supplied
    assert saved['checks']['database_read_only'] and saved['local_only']
    for source, pin in saved['source_sha256'].items(): assert file_hash(Path(source)) == pin
    for name, pin in saved['output_sha256'].items(): assert file_hash(Path(receipt['output_dir']) / name) == pin
    assert file_hash(Path(receipt['manifest_path'])) == receipt['manifest_sha256']


def test_publication_change_fails_and_removes_only_owned_output(published, monkeypatch):
    p = published
    read = ac_export._published_release
    count = 0
    def changing(state):
        nonlocal count
        value = read(state)
        count += 1
        return value if count == 1 else {**value, 'release_id': 'synthetic-other-release'}
    monkeypatch.setattr(ac_export, '_published_release', changing)
    output = p['tmp'] / 'changed'
    with pytest.raises(PipelineError, match='publication changed'):
        export_student_ac(p['cfg'], output)
    assert not output.exists()


def test_failure_preserves_foreign_files_in_reserved_directory(published, monkeypatch):
    output = published['tmp'] / 'interrupted'
    def failed(path, *args):
        (path.parent / 'foreign.txt').write_text('keep')
        raise RuntimeError('synthetic failure')
    monkeypatch.setattr(ac_export, '_verify_csv', failed)
    with pytest.raises(RuntimeError, match='synthetic failure'):
        export_student_ac(published['cfg'], output)
    assert (output / 'foreign.txt').read_text() == 'keep'
    assert sorted(p.name for p in output.iterdir()) == ['foreign.txt']


def test_source_change_during_export_fails_without_partial_output(published, monkeypatch):
    p = published
    source = p['folder'] / 'summary.json'
    source.write_text('{}')
    checksum_path = p['folder'] / 'checksums.json'
    checksum_path.write_text(json.dumps({**json.loads(checksum_path.read_text()), 'summary.json':file_hash(source)}))
    verify = ac_export._verify_csv
    def changed(*args):
        verify(*args)
        source.write_text('{"external":"change"}')
    monkeypatch.setattr(ac_export, '_verify_csv', changed)
    output = p['tmp'] / 'changed-source'
    with pytest.raises(PipelineError, match='source changed'):
        export_student_ac(p['cfg'], output)
    assert not output.exists()


@pytest.mark.parametrize('defect', ['missing-inventory','corrupt-records','corrupt-analysis','uncatalogued-summary'])
def test_published_consumed_checksums_are_required(published, defect):
    p = published
    folder = p['folder']
    if defect == 'missing-inventory':
        (folder / 'checksums.json').unlink()
    elif defect == 'corrupt-records':
        p['records'][0]['answer']['leading'] = 'different synthetic value'
        with gzip.open(folder / 'records.jsonl.gz', 'wt') as stream:
            for row in p['records']: stream.write(json.dumps(row)+'\n')
    elif defect == 'corrupt-analysis':
        p['frame'].assign(score=123.0).to_parquet(folder / 'analysis.parquet', index=False)
    else:
        (folder / 'summary.json').write_text('{}')
    output = p['tmp'] / 'invalid-published-artifact'
    with pytest.raises(PipelineError, match='published checksum|published artifact|published checksums'):
        export_student_ac(p['cfg'], output)
    assert not output.exists()


def test_logical_gzip_checksum_verifies_consumed_archive_not_plain_copy(published):
    p = published
    folder = p['folder']
    path = folder / 'checksums.json'
    expected = json.loads(path.read_text())
    content = gzip.decompress((folder / 'records.jsonl.gz').read_bytes())
    del expected['records.jsonl.gz']
    expected['records.jsonl'] = hashlib.sha256(content).hexdigest()
    # Unrelated backup entries are intentionally not scanned by this exporter.
    expected['unconsumed-backup.sqlite'] = '0'*64
    path.write_text(json.dumps(expected))
    receipt = export_student_ac(p['cfg'], p['tmp'] / 'logical-checksum')
    assert receipt['published_checksums']['records.jsonl.gz']['inventory_key'] == 'records.jsonl'
    (folder / 'records.jsonl').write_bytes(content)
    with (folder / 'records.jsonl.gz').open('ab') as stream:
        # A second gzip member is valid and changes the consumed logical bytes.
        stream.write(gzip.compress(b'\n'))
    with pytest.raises(PipelineError, match='published artifact checksum mismatch'):
        export_student_ac(p['cfg'], p['tmp'] / 'archive-changed')
