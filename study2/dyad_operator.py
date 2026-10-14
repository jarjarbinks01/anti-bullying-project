"""Controlled local operator actions. Never sends invitations or survey data."""
from __future__ import annotations

import json
import os
import shutil
import sqlite3
import uuid
from datetime import timedelta
from pathlib import Path

from . import dyads
from .common import PipelineError, atomic_json, digest, dumps, file_hash, secure_directory, text, timestamp, utcnow
from .outputs import write_excel
from .store import backup_path, connect, current, writer_lock

TABLES = ('dyad_schema', 'dyad_registry', 'dyad_lineage', 'dyad_memberships', 'dyad_events',
          'dyad_resolutions', 'dyad_aliases', 'dyad_invitation_events')
STATES = {'active': '有效', 'new': '可首次登記', 'suspended': '暫停，待裁定',
          'awaiting_registration': '尚未登記，待裁定'}
FOLLOWUPS = {'both_complete': '兩者完成合資格T1', 'student_only': '只有學生完成',
             'parent_only': '只有家長完成', 'neither_complete': '兩者尚未完成', 'unconfirmed': '身份未確認'}
REASONS = {'contradictory_identity_component':'身份候選互相矛盾，須核實',
           'registered_identity_evidence_changed':'已登記的身份資料已改變',
           'registered_group_split_or_missing':'原登記群組被拆開或提交未能對應',
           'multiple_registered_families_merged':'多個永久登記被合併到同一群組',
           'registered_id_claimed_by_multiple_groups':'同一永久ID涉及多個群組',
           'no_current_confirmed_t0_pair':'目前沒有確認的T0親子組合',
           'missing_registered_submission':'原登記提交缺失',
           'registered_submission_not_assigned':'原追蹤提交已失去有效身份歸屬',
           'retired_registration_without_canonical_mapping':'原登記已停用，尚未有批准的有效對應'}


def readable_reason(value):
    return '；'.join(REASONS.get(v,v) for v in text(value).split(';') if v)


def safe_note(value):
    import re
    value = re.sub(r'\b[^\s@]+@[^\s@]+\.[^\s@]+\b', '[聯絡資料隱藏]', text(value))
    return re.sub(r'(?<!\d)\d{8,}(?!\d)', '[聯絡資料隱藏]', value)


def _context(db, cfg, expected_release=None):
    release = current(db)
    if not release:
        raise PipelineError('尚未有已發布資料版本')
    if expected_release and release['release_id'] != expected_release:
        raise PipelineError('發布版本已改變，請重新預覽')
    records = dyads.scientific_records(db, release['run_id'])
    cases = dyads.scientific_cases(db, release['release_id'])
    return release, records, cases


def _review_revision(db):
    """Canonical research decisions and labels, independent of admin events."""
    from .review import active_decisions
    return digest({'decisions': sorted(active_decisions(db), key=lambda d: d['payload']['target_key']),
                   'labels': [dict(r) for r in db.execute('SELECT * FROM labels ORDER BY case_id')]})


def require_published_reviews(db, release):
    """Applied review changes must reach a research release before invitations."""
    # A restored review workspace can be newer than the full main backup. Its
    # applied batches must be recovered in main before trusting an old release.
    main_path = Path(db.execute('PRAGMA database_list').fetchone()[2])
    review_path = main_path.parent / 'review.sqlite'
    if review_path.is_file():
        work = sqlite3.connect(review_path.resolve().as_uri() + '?mode=ro', uri=True)
        try:
            applied = {r[0] for r in work.execute("SELECT id FROM batches WHERE state='applied'")}
        except sqlite3.DatabaseError:
            raise PipelineError('審核工作區無法核對，不能匯出或新增邀請紀錄') from None
        finally:
            work.close()
        markers = {r[0] for r in db.execute('SELECT batch_id FROM review_applications')}
        if applied - markers:
            raise PipelineError('審核工作區有已套用但主資料庫缺少的批次；請先恢復人工裁定、重跑及發布，再處理邀請')
    path = Path(release['path']) / 'backup.sqlite'
    from .publication_baseline import read_baseline
    baseline=read_baseline(release['path'],release['release_id'])
    if baseline:
        if _review_revision(db)!=baseline['review_revision']:
            raise PipelineError('人工裁定或核實標記已更新但尚未發布；請先重跑及發布，再匯出或新增邀請紀錄')
        return
    if not path.is_file() and not path.with_name(path.name + '.gz').is_file():
        raise PipelineError('發布版本缺少人工裁定基線備份，不能匯出或新增邀請紀錄')
    with backup_path(path) as restored:
        snapshot = sqlite3.connect(restored.resolve().as_uri() + '?mode=ro', uri=True)
        snapshot.row_factory = sqlite3.Row
        try:
            expected = _review_revision(snapshot)
        except sqlite3.DatabaseError:
            raise PipelineError('發布版本的人工裁定基線無法核對，不能匯出或新增邀請紀錄') from None
        finally:
            snapshot.close()
    if _review_revision(db) != expected:
        raise PipelineError('人工裁定或核實標記已更新但尚未發布；請先重跑及發布，再匯出或新增邀請紀錄')


def preview(cfg):
    db = connect(Path(cfg['state_dir']), readonly=True)
    try:
        release, records, cases = _context(db, cfg)
        rows = dyads.plan(db, release['run_id'], records, cases, cfg)
        return {'release_id': release['release_id'], 'read_only': True, 'summary': dyads.summary(rows), 'rows': rows}
    finally:
        db.close()


def workspace_snapshot(db):
    return {t: [dict(r) for r in db.execute(f'SELECT * FROM {t} ORDER BY 1')]
            for t in TABLES} if dyads.exists(db) else {}


def backup_tracking(db, cfg, reason='manual', promote=True):
    """Small complete administrative snapshot plus independently saved reviews.

    Main research recovery uses the full pipeline backup. This bundle protects
    administrative work performed after that release, including unpublished work.
    Callers hold the main writer lock.
    """
    from .review_core import backup_workspace
    folder = Path(cfg['state_dir']) / 'dyad_backups' / ('bundle_' + uuid.uuid4().hex)
    secure_directory(folder)
    data = workspace_snapshot(db)
    ledger = folder / 'tracking.json'
    atomic_json(ledger, {'schema_version': dyads.SCHEMA_VERSION, 'tables': data})
    ledger.chmod(0o600)
    review = backup_workspace(cfg, 'dyad_' + reason)
    if review:
        # Both paths are immutable snapshots. Share their storage without
        # linking the live workspace; deleting either path keeps the other.
        try:
            os.link(review, folder / 'review.sqlite')
        except OSError:
            shutil.copy2(review, folder / 'review.sqlite')
        (folder / 'review.sqlite').chmod(0o600)
    release = current(db)
    manifest = {'at': utcnow(), 'reason': reason, 'release_id': release['release_id'] if release else None,
                'files': {p.name: file_hash(p) for p in folder.iterdir() if p.is_file()},
                'tracking_hash': digest(data), 'schema_version': dyads.SCHEMA_VERSION}
    atomic_json(folder / 'manifest.json', manifest)
    (folder / 'manifest.json').chmod(0o600)
    # Last-known administrative history is kept outside release rollback.
    if promote:
        atomic_json(Path(cfg['state_dir']) / 'DYAD_LEDGER.json', {'bundle': str(folder), 'hash': manifest['tracking_hash']})
    return str(folder)


def verify_bundle(folder):
    folder = Path(folder)
    if (folder/'tracking.retention.json').is_file():
        raise PipelineError('This physical administrative backup was pruned; restore the latest complete checkpoint')
    manifest = json.loads((folder / 'manifest.json').read_text())
    if manifest.get('schema_version') != dyads.SCHEMA_VERSION:
        raise PipelineError('不支援此登記備份格式')
    for name, expected in manifest['files'].items():
        if Path(name).name != name or file_hash(folder / name) != expected:
            raise PipelineError('登記備份指紋不符')
    if (folder/'tracking.json').is_file():data=json.loads((folder/'tracking.json').read_text())['tables']
    else:
        import gzip
        try:
            with gzip.open(folder/'tracking.json.gz','rt',encoding='utf-8') as stream:data=json.load(stream)['tables']
        except (OSError,EOFError,ValueError) as error:raise PipelineError('Administrative checkpoint content is corrupt') from error
    if digest(data) != manifest['tracking_hash'] or set(data) not in (set(), set(TABLES)):
        raise PipelineError('登記備份內容不完整')
    if (folder / 'review.sqlite').exists():
        db = sqlite3.connect(f"file:{folder / 'review.sqlite'}?mode=ro", uri=True)
        try:
            if db.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                raise PipelineError('審核工作區備份損壞')
        finally:
            db.close()
    return manifest, data


def recovery_check(db, cfg):
    pointer = Path(cfg['state_dir']) / 'DYAD_LEDGER.json'
    if not pointer.exists():
        return
    p = json.loads(pointer.read_text())
    _, data = verify_bundle(p['bundle'])
    if p['hash'] != digest(data):
        raise PipelineError('登記歷史索引不一致，必須先核對還原')
    if not data:
        return
    if not dyads.exists(db):
        raise PipelineError('還原的主資料庫缺少已保存的永久登記，必須先還原追蹤備份')
    actual = workspace_snapshot(db)
    # Never drop issued IDs or invitation/adjudication events when restoring an
    # older research database. Extra newer live rows are safe, missing rows are not.
    keys = {'dyad_registry': 'dyad_id', 'dyad_invitation_events': 'operation_id',
            'dyad_resolutions': 'operation_id', 'dyad_events': 'event_id'}
    for table, key in keys.items():
        current_rows = {r[key]: r for r in actual[table]}
        for row in data[table]:
            if row[key] not in current_rows:
                raise PipelineError('還原的資料庫遺漏永久登記或行政歷史，必須核對及還原追蹤備份')
            if table != 'dyad_registry' and row != current_rows[row[key]]:
                raise PipelineError('登記行政歷史內容衝突，不能繼續操作')


def _require_restore_history(origin, data):
    """A tracking overlay must contain every issued ID and immutable main event."""
    if not dyads.exists(origin):
        return
    saved = workspace_snapshot(origin)
    keys = {'dyad_registry': 'dyad_id', 'dyad_events': 'event_id',
            'dyad_resolutions': 'operation_id', 'dyad_aliases': 'alias_id',
            'dyad_invitation_events': 'operation_id'}
    for table, key in keys.items():
        incoming = {r[key]: r for r in data.get(table, [])}
        for row in saved[table]:
            other = incoming.get(row[key])
            if not other:
                raise PipelineError('追蹤備份較舊或不完整，缺少主備份已有的登記／裁定／邀請歷史；請使用最新一致的追蹤備份')
            if table == 'dyad_registry':
                if row['lifecycle'] == 'retired' and other['lifecycle'] != 'retired':
                    raise PipelineError('追蹤備份會恢復已停用登記，拒絕還原；請使用最新一致的追蹤備份')
            elif row != other:
                raise PipelineError('備份之間的行政歷史互相衝突，拒絕還原')


def restore_bundle(folder, main_backup, destination):
    """Restore to a new state directory; never overwrite live databases."""
    with backup_path(main_backup) as restored:
        return _restore_bundle(folder, restored, destination)


def _restore_bundle(folder, main_backup, destination):
    manifest, data = verify_bundle(folder)
    destination = Path(destination)
    if destination.exists():
        raise PipelineError('還原位置必須是尚未存在的新資料夾')
    origin = sqlite3.connect(f'file:{Path(main_backup).resolve()}?mode=ro', uri=True)
    origin.row_factory = sqlite3.Row
    target = None
    try:
        # Check before creating a destination or overwriting any mutable state.
        _require_restore_history(origin, data)
        if origin.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
            raise PipelineError('主資料庫備份損壞')
        secure_directory(destination)
        target = sqlite3.connect(destination / 'study2.sqlite')
        target.row_factory = sqlite3.Row
        origin.backup(target)
        dyads.migrate(target)
        with target:
            # Restore only history present in the full backup, then overlay all
            # administrative history. Runs absent from the old backup cannot be
            # invented; those staged memberships remain in the recovery bundle.
            for table in TABLES:
                for row in data.get(table, []):
                    if table == 'dyad_memberships' and not target.execute('SELECT 1 FROM runs WHERE run_id=?', (row['run_id'],)).fetchone():
                        continue
                    old = target.execute(f'SELECT * FROM {table} WHERE ' + {
                        'dyad_schema': 'version=?', 'dyad_registry': 'dyad_id=?',
                        'dyad_lineage': 'dyad_id=? AND submission_id=? AND evidence_hash=?',
                        'dyad_memberships': 'run_id=? AND membership_key=?', 'dyad_events': 'event_id=?',
                        'dyad_resolutions': 'operation_id=?', 'dyad_aliases': 'alias_id=?',
                        'dyad_invitation_events': 'operation_id=?'}[table], tuple(row[k] for k in {
                        'dyad_schema': ['version'], 'dyad_registry': ['dyad_id'],
                        'dyad_lineage': ['dyad_id', 'submission_id', 'evidence_hash'],
                        'dyad_memberships': ['run_id', 'membership_key'], 'dyad_events': ['event_id'],
                        'dyad_resolutions': ['operation_id'], 'dyad_aliases': ['alias_id'],
                        'dyad_invitation_events': ['operation_id']}[table])).fetchone()
                    if old:
                        if table in {'dyad_events', 'dyad_resolutions', 'dyad_invitation_events'} and dict(old) != row:
                            raise PipelineError('備份之間的行政歷史互相衝突')
                        if table == 'dyad_registry':
                            if any(old[k] != row[k] for k in row if k not in {'lifecycle','first_published_run_id'}):
                                raise PipelineError('備份之間的永久登記互相衝突')
                            if old['first_published_run_id'] and row['first_published_run_id'] and old['first_published_run_id'] != row['first_published_run_id']:
                                raise PipelineError('備份之間的首次發布版本互相衝突')
                            if not old['first_published_run_id'] and row['first_published_run_id']:
                                target.execute('UPDATE dyad_registry SET first_published_run_id=? WHERE dyad_id=?', (row['first_published_run_id'], row['dyad_id']))
                            target.execute('UPDATE dyad_registry SET lifecycle=? WHERE dyad_id=?', (row['lifecycle'], row['dyad_id']))
                        if table == 'dyad_lineage':
                            target.execute('UPDATE dyad_lineage SET active=? WHERE dyad_id=? AND submission_id=? AND evidence_hash=?',
                                           (row['active'], row['dyad_id'], row['submission_id'], row['evidence_hash']))
                        continue
                    target.execute(f"INSERT INTO {table} ({','.join(row)}) VALUES({','.join('?' for _ in row)})", tuple(row.values()))
        if target.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
            raise PipelineError('還原後完整性檢查失敗')
    finally:
        origin.close()
        if target is not None:
            target.close()
    (destination / 'study2.sqlite').chmod(0o600)
    if (Path(folder) / 'review.sqlite').exists():
        shutil.copy2(Path(folder) / 'review.sqlite', destination / 'review.sqlite')
        (destination / 'review.sqlite').chmod(0o600)
    retained = destination / 'recovered_tracking'
    shutil.copytree(folder, retained)
    atomic_json(destination / 'DYAD_LEDGER.json', {'bundle': str(retained), 'hash': manifest['tracking_hash']})
    return {'restored_state': str(destination), 'requires_config_and_source_check': True}


def adjudicate(cfg, request):
    required = ('operation_id', 'release_id', 'action', 'reviewer', 'reason')
    if any(not text(request.get(k)) for k in required) or request['reviewer'] != 'Jarvis':
        raise PipelineError('裁定必須有固定操作ID、發布版本、Jarvis及理由')
    state = Path(cfg['state_dir'])
    with writer_lock(state):
        db = connect(state)
        try:
            dyads.migrate(db)
            recovery_check(db, cfg)
            prior = db.execute('SELECT payload_json FROM dyad_resolutions WHERE operation_id=?', (request['operation_id'],)).fetchone()
            if prior:
                if json.loads(prior[0])['request'] != request:
                    raise PipelineError('操作ID已用於另一項裁定')
                backup_tracking(db, cfg, 'recover_adjudication_retry')
                return {'unchanged': True, 'operation_id': request['operation_id']}
            release, records, cases = _context(db, cfg, request['release_id'])
            by_id = {r['submission_id']: r for r in records}
            current_plan = dyads.plan(db, release['run_id'], records, cases, cfg)
            targets = {r['child_id']: r for r in current_plan if r.get('child_id')}
            did = text(request.get('dyad_id'))
            reg = db.execute('SELECT * FROM dyad_registry WHERE dyad_id=?', (did,)).fetchone()
            if not reg or reg['lifecycle'] == 'retired':
                raise PipelineError('永久登記不存在或已停用')
            action = request['action']
            if action not in {'assign', 'merge', 'split', 'retire'}:
                raise PipelineError('裁定操作不合法')
            children = request.get('children') or ([request.get('child_id')] if action != 'retire' else [])
            if action in {'assign','merge'} and len(children) != 1 or action == 'retire' and children:
                raise PipelineError('保留／合併須有一個目標；停用不接受新的身份目標')
            if action == 'split' and len(children) < 2:
                raise PipelineError('拆分須指定原ID保留孩子及至少一個新登記孩子')
            if len(set(children)) != len(children):
                raise PipelineError('拆分目標重複')
            for child in children:
                row = targets.get(child)
                if not row or not row.get('student_t0_id') or not row.get('parent_t0_id'):
                    raise PipelineError('目標必須有目前已確認的T0親子樣本；先完成研究身份修正')
                if row['contradictory_candidates']:
                    raise PipelineError('身份矛盾仍未解決，先使用既有審核流程修正及重跑')
                if did not in row['candidate_dyad_ids']:
                    raise PipelineError('目標與此永久登記沒有提交關聯，不可把ID改指另一孩子')
                if request.get('signatures', {}).get(child) != row['evidence_signature']:
                    raise PipelineError('裁定證據版本不符，請重新預覽')
            merge_ids = request.get('merge_ids', [])
            if action == 'merge':
                if len(children) != 1 or not merge_ids or did in merge_ids or len(set(merge_ids)) != len(merge_ids):
                    raise PipelineError('合併須有一個保留ID及不同的被合併ID')
                for other in merge_ids:
                    r = db.execute('SELECT lifecycle FROM dyad_registry WHERE dyad_id=?', (other,)).fetchone()
                    if not r or r['lifecycle'] == 'retired' or other not in targets[children[0]]['candidate_dyad_ids']:
                        raise PipelineError('被合併登記不是此孩子的有效候選')
            elif merge_ids:
                raise PipelineError('此裁定不接受合併ID')
            allowed = {did, *merge_ids}
            for child in children:
                if set(targets[child]['candidate_dyad_ids']) - allowed:
                    raise PipelineError('目標涉及其他永久登記，需先明確裁定合併')
            before = workspace_snapshot(db)
            backup_path = backup_tracking(db, cfg, 'before_adjudication')
            assigned = []
            with db:
                if action == 'retire':
                    db.execute("UPDATE dyad_registry SET lifecycle='retired' WHERE dyad_id=?", (did,))
                    db.execute('UPDATE dyad_lineage SET active=0 WHERE dyad_id=?', (did,))
                else:
                    for other in merge_ids:
                        db.execute("UPDATE dyad_registry SET lifecycle='retired' WHERE dyad_id=?", (other,))
                        db.execute('UPDATE dyad_lineage SET active=0 WHERE dyad_id=?', (other,))
                        db.execute('INSERT INTO dyad_aliases VALUES(?,?,?)', (other, did, request['operation_id']))
                    db.execute('UPDATE dyad_lineage SET active=0 WHERE dyad_id=?', (did,))
                    for index, child in enumerate(children):
                        mapped = did if index == 0 else 'DYAD_' + uuid.uuid4().hex
                        row = targets[child]
                        if index:
                            anchors = [row['student_t0_id'], row['parent_t0_id']]
                            db.execute('INSERT INTO dyad_registry(dyad_id,first_student_id,first_parent_id,first_run_id,created_at,first_evidence,lifecycle) VALUES(?,?,?,?,?,?,?)',
                                       (mapped, *anchors, release['run_id'], utcnow(),
                                        dumps({sid: dyads.identity_evidence(by_id[sid]) for sid in anchors}), 'reserved'))
                        else:
                            db.execute("UPDATE dyad_registry SET lifecycle='suspended' WHERE dyad_id=?", (mapped,))
                        for sid in row['member_ids']:
                            db.execute('INSERT INTO dyad_lineage VALUES(?,?,?,1) ON CONFLICT(dyad_id,submission_id,evidence_hash) DO UPDATE SET active=1',
                                       (mapped, sid, dyads.evidence_hash(by_id[sid])))
                        assigned.append({'child_id': child, 'dyad_id': mapped})
                payload = {'request': request, 'assignments': assigned, 'before_hash': digest(before)}
                db.execute('INSERT INTO dyad_resolutions VALUES(?,?,?,?)',
                           (request['operation_id'], utcnow(), release['release_id'], dumps(payload)))
                dyads._event(db, action, did, 'Jarvis', request['reason'], payload, request['operation_id'])
            after = backup_tracking(db, cfg, 'after_adjudication')
            return {'operation_id': request['operation_id'], 'assignments': assigned, 'requires_republish': True,
                    'before_backup': backup_path, 'after_backup': after}
        finally:
            db.close()


def invitation_rows(db, cfg, release, records, cases, include_stopped=False):
    """Revalidate published registration against current administrative history."""
    require_published_reviews(db, release)
    live = {r.get('child_id'): r for r in dyads.plan(db, release['run_id'], records, cases, cfg) if r.get('child_id')}
    published = dyads.staged_rows(db, release['run_id'])
    by_id = {r['submission_id']: r for r in records}
    rows = []
    for row in published:
        current_row = live.get(row.get('child_id'))
        reg = db.execute('SELECT lifecycle FROM dyad_registry WHERE dyad_id=?', (row.get('dyad_id'),)).fetchone()
        if row['registration_state'] != 'active' or not current_row or current_row['registration_state'] != 'active':
            continue
        if current_row['dyad_id'] != row['dyad_id'] or not reg or reg['lifecycle'] != 'active':
            continue
        for role in ('student', 'parent'):
            if row.get(role + '_complete') or not row.get(role + '_due_at'):
                continue
            sid = row.get(role + '_t0_id')
            record = by_id[sid]
            a = record['answer']
            payload = {'release_id': release['release_id'], 'dyad_id': row['dyad_id'], 'role': role, 'wave': 'T1',
                't0_submission_id': sid, 't0_at': record.get('observed_at'), 'due_at': row[role + '_due_at'],
                'family_due_at': row.get('family_due_at'), 'date_basis': record.get('date_basis'),
                'time_confidence': record['time_confidence'], 'identity_candidate_pending': row['identity_candidate_pending'],
                'school': record.get('school'), 'source_file': record.get('location', {}).get('file'),
                'source_row': record.get('location', {}).get('row'), 'source_version': record.get('version_id'),
                **{k: a.get(k) for k in ('contact_01', 'contact_02', 'contact_03.1', 'contact_03.2', 'contact_03.3', 'contact_03.4')}}
            payload['eligibility_signature'] = digest({k: v for k, v in payload.items()})
            family_ids = dyads.related_ids(db,row['dyad_id'])
            marks = ','.join('?' for _ in family_ids)
            events = [json.loads(r[0]) for r in db.execute(f'SELECT payload_json FROM dyad_invitation_events WHERE dyad_id IN ({marks}) AND role=? ORDER BY at,operation_id', (*family_ids, role))]
            payload['sent_count'] = sum(e['action'] == 'sent' for e in events)
            payload['last_sent_at'] = next((e['occurred_at'] for e in reversed(events) if e['action'] == 'sent'), None)
            payload['invitation_state'] = events[-1]['action'] if events else 'not_sent'
            if include_stopped or payload['invitation_state'] != 'stop':
                rows.append(payload)
    return rows


def export_invitations(cfg, output):
    state = Path(cfg['state_dir'])
    with writer_lock(state):
        db = connect(state)
        try:
            recovery_check(db, cfg)
            release, records, cases = _context(db, cfg)
            if not dyads.exists(db):
                raise PipelineError('尚未發布永久親子登記')
            rows = invitation_rows(db, cfg, release, records, cases)
            write_excel(Path(output), {'受控邀請清單': rows, '使用說明': [
                {'說明': '只供指定執行者使用；含個人聯絡資料，不上傳或公開。'},
                {'說明': 'due_at為該角色T0加90日；family_due_at為共同邀請建議日期。'},
                {'說明': '本清單不會發送訊息。發送後使用追蹤中心記錄實際日期。'},
                {'說明': '沒有Qualtrics背景代碼；問卷仍須經身份核實。'},
                {'說明': '日期欄為可排序的Excel日期，顯示UTC。技術簽章隱藏，但保留供指定執行者核對。'}]}, tracking=True)
            return {'release_id': release['release_id'], 'rows': len(rows), 'output': str(Path(output).resolve())}
        finally:
            db.close()


def record_invitation(cfg, request):
    required = ('operation_id', 'release_id', 'dyad_id', 'role', 'action', 'occurred_at', 'operator', 'reason')
    if any(not text(request.get(k)) for k in required):
        raise PipelineError('邀請紀錄缺少操作ID、版本、家庭、角色、日期、執行者或理由')
    if request['role'] not in {'student', 'parent'} or request['action'] not in {'sent', 'stop', 'resume', 'failed'}:
        raise PipelineError('邀請角色或操作不合法')
    if not timestamp(request['occurred_at']):
        raise PipelineError('實際日期格式不合法')
    if timestamp(request['occurred_at']) > timestamp(utcnow()):
        raise PipelineError('實際事件日期不能在未來')
    if request['action'] == 'sent' and (not text(request.get('method')) or not text(request.get('result'))):
        raise PipelineError('已發送紀錄須填方式及結果')
    with writer_lock(Path(cfg['state_dir'])):
        db = connect(Path(cfg['state_dir']))
        try:
            dyads.migrate(db)
            recovery_check(db, cfg)
            previous = db.execute('SELECT payload_json FROM dyad_invitation_events WHERE operation_id=?', (request['operation_id'],)).fetchone()
            if previous:
                if json.loads(previous[0])['request'] != request:
                    raise PipelineError('操作ID已用於另一項邀請紀錄')
                backup_tracking(db, cfg, 'recover_invitation_retry')
                return {'unchanged': True, 'operation_id': request['operation_id']}
            release, records, cases = _context(db, cfg, request['release_id'])
            candidates = invitation_rows(db, cfg, release, records, cases, include_stopped=True)
            selected = next((r for r in candidates if r['dyad_id'] == request['dyad_id'] and r['role'] == request['role']), None)
            if not selected:
                raise PipelineError('此角色已完成、登記暫停、日期未確認或清單已失效，不能記錄新的邀請')
            if request['action'] == 'resume':
                # Resume changes only the stop marker; sent still requires fresh eligibility.
                if selected['invitation_state'] != 'stop':
                    raise PipelineError('此角色沒有暫停邀請紀錄')
            else:
                if selected['invitation_state'] == 'stop':
                    raise PipelineError('此角色已暫停邀請，須先明確恢復')
                if request.get('eligibility_signature') != selected['eligibility_signature']:
                    raise PipelineError('邀請證據或聯絡來源已改變，請重新匯出')
            event_key = digest({k: request.get(k) for k in ('dyad_id', 'role', 'action', 'occurred_at', 'method', 'result', 'operator', 'reason')})
            if db.execute('SELECT 1 FROM dyad_invitation_events WHERE event_key=?', (event_key,)).fetchone():
                return {'unchanged': True, 'note': '相同實際邀請事件已保存'}
            before = backup_tracking(db, cfg, 'before_invitation')
            payload = {k: request.get(k) for k in required}
            payload.update(request=request, method=request.get('method'), result=request.get('result'),
                           eligibility=selected, action=request['action'],
                           before_eligibility_date=bool(selected and timestamp(request['occurred_at']) < timestamp(selected['due_at'])))
            with db:
                db.execute('INSERT INTO dyad_invitation_events VALUES(?,?,?,?,?,?,?)',
                    (request['operation_id'], utcnow(), release['release_id'], request['dyad_id'], request['role'], dumps(payload), event_key))
            after = backup_tracking(db, cfg, 'after_invitation')
            return {'saved': True, 'operation_id': request['operation_id'], 'before_backup': before, 'after_backup': after,
                    'note': '行政紀錄已保存；沒有發送訊息或改動研究樣本'}
        finally:
            db.close()


def report(cfg):
    db = connect(Path(cfg['state_dir']), readonly=True)
    try:
        release, records, cases = _context(db, cfg)
        if not dyads.exists(db):
            return {'release_id': release['release_id'], 'available': False}
        recovery_check(db, cfg)
        published = dyads.staged_rows(db, release['run_id'])
        latest = db.execute('SELECT MAX(at) FROM dyad_invitation_events').fetchone()[0]
        return {'release_id': release['release_id'], 'available': bool(published), 'published_summary': dyads.summary(published),
                'administrative_updated_at': latest, 'pending': [r for r in dyads.plan(db, release['run_id'], records, cases, cfg) if r['registration_state'] not in {'active', 'new'}],
                'events': [dict(r) for r in db.execute('SELECT * FROM dyad_events ORDER BY at,event_id')],
                'invitations': [dict(r) for r in db.execute('SELECT * FROM dyad_invitation_events ORDER BY at,operation_id')]}
    finally:
        db.close()


def console(cfg):
    """Chinese local menu. Research/dashboard remain read-only to colleagues."""
    while True:
        print('\n親子追蹤中心：1 預覽登記／待裁定  2 匯出邀請清單  3 保存實際邀請紀錄')
        print('4 Jarvis身份登記裁定  5 備份追蹤及審核工作  6 查看歷史  0 離開')
        choice = input('選項：').strip()
        if choice == '0':
            return {'closed': True}
        try:
            state = Path(cfg['state_dir'])
            if choice == '1':
                value = preview(cfg)
                path = state / 'dyad_preview.xlsx'
                write_excel(path, {'登記預覽': dyads.safe_tracking_rows(value['rows']),
                                  '待裁定': dyads.safe_tracking_rows([r for r in value['rows'] if r['registration_state'] not in {'active','new'}])}, tracking=True)
                print(dumps({'發布版本': value['release_id'], '摘要': value['summary'], '檔案': str(path)}))
            elif choice == '2':
                path = input('儲存xlsx位置（留空使用本機預設）：').strip()
                print(dumps(export_invitations(cfg, Path(path) if path else state / 'dyad_invitations.xlsx')))
            elif choice == '3':
                db = connect(state, readonly=True)
                try:
                    release, records, cases = _context(db, cfg)
                    if not dyads.exists(db):
                        raise PipelineError('先完成永久登記及發布')
                    rows = invitation_rows(db, cfg, release, records, cases, include_stopped=True)
                finally:
                    db.close()
                did = input('永久親子ID：').strip()
                role = {'1':'student','2':'parent'}.get(input('角色：1學生／2家長：').strip())
                row = next((r for r in rows if r['dyad_id'] == did and r['role'] == role), None)
                if not row:
                    raise PipelineError('沒有符合條件的已發布家庭／角色')
                action = {'1':'sent','2':'failed','3':'stop','4':'resume'}.get(input('紀錄：1已發送／2發送失敗／3停止邀請／4恢復邀請：').strip())
                request = {'operation_id':'INV_' + uuid.uuid4().hex, 'release_id': release['release_id'],
                           'dyad_id':did,'role':role,'action':action,'eligibility_signature':row['eligibility_signature'],
                           'occurred_at':input('實際日期及時間（ISO，如2025-05-01T10:00:00+08:00）：').strip(),
                           'operator':input('執行者：').strip(), 'method':input('聯絡方式：').strip(),
                           'result':input('實際結果：').strip(), 'reason':input('理由／紀錄依據：').strip()}
                secure_directory(state / 'dyad_requests')
                path = state / 'dyad_requests' / (request['operation_id'] + '.json')
                atomic_json(path, request)
                print('只保存紀錄，不會發送訊息。重試請沿用已保存的請求檔：' + str(path))
                print(dumps(record_invitation(cfg, request)))
            elif choice == '4':
                value = preview(cfg)
                print('先用既有審核流程修正身份、重跑及發布。此處只裁定永久ID歸屬。')
                action = {'1':'assign','2':'merge','3':'split','4':'retire'}.get(input('1保留／重新對應 2合併登記 3拆分登記 4停用：').strip())
                did = input('保留或處理的永久親子ID：').strip()
                children = [] if action == 'retire' else [s.strip() for s in input('目前孩子群組ID（拆分用逗號分隔，第一個保留原ID）：').split(',') if s.strip()]
                by_child = {r.get('child_id'):r for r in value['rows']}
                request = {'operation_id':'DRES_' + uuid.uuid4().hex,'release_id':value['release_id'],
                           'action':action,'dyad_id':did,'reviewer':input('批准者（須填Jarvis）：').strip(),
                           'reason':input('裁定理由及已核實依據：').strip(),'children':children,
                           'signatures':{c:by_child[c]['evidence_signature'] for c in children if c in by_child}}
                if action == 'merge':
                    request['merge_ids'] = [s.strip() for s in input('被合併永久ID，用逗號分隔：').split(',') if s.strip()]
                secure_directory(state / 'dyad_requests')
                path = state / 'dyad_requests' / (request['operation_id'] + '.json')
                atomic_json(path, request)
                print('裁定請求已保存：' + str(path))
                print(dumps(adjudicate(cfg, request)))
            elif choice == '5':
                with writer_lock(state):
                    db = connect(state)
                    try:
                        recovery_check(db, cfg)
                        print('備份：' + backup_tracking(db, cfg, 'operator'))
                    finally:
                        db.close()
            elif choice == '6':
                value = report(cfg)
                path = state / 'dyad_report.json'
                atomic_json(path, value)
                path.chmod(0o600)
                print('完整本機歷史：' + str(path))
            else:
                print('請輸入0至6。')
        except (PipelineError, ValueError, OSError) as error:
            print('未保存：' + str(error))


from .checkpoints import protect_mutation
adjudicate=protect_mutation(adjudicate)
record_invitation=protect_mutation(record_invitation)
