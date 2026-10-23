"""Human-invoked, LOCAL manual-flag ledger; never opens research state.

CSV projection is restricted to COLUMNS. Review selects a case-sensitive literal
substring, not a classifier. Seven fields match after NFKC and trim; integral
representation applies only to native numeric values, never numeric-looking
strings. Strict default requires all seven keys. The explicit merged-role option
projects only absent opposite-role fields to blank, leaving raw/hash untouched.
Dates, email case, telephone punctuation, containers and Email are not inferred.

Only an explicit registry path is writable. Imports merge flags transactionally;
absence in later CSVs cannot remove them. Removed flags need explicit restore.
Compile pins exact IDs AND versions/content/roles, blocks unresolved evidence,
and emits the existing accepted manifest_v1 contract without changing selection.
All IDs, history, fingerprints and reports in this module are private local data.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from contextlib import contextmanager
from copy import deepcopy
import csv
from dataclasses import dataclass
from decimal import Decimal
import gzip
import hashlib
import io
import json
import math
import os
from pathlib import Path
import sqlite3
import struct
import sys
import tempfile
import unicodedata
from urllib.parse import quote
import uuid

from .analysis_eligibility import (
    COPY_POLICY, MANIFEST_FORMAT, EligibilityError, inventory_revision,
    manifest_revision, sha, validate_manifest,
)
from .common import PipelineError, digest, utcnow

COLUMNS = ('Email', 'Survey', '建立時間', 'contact_01', 'contact_02',
           'student_demographics_06', 'contact_03.1', 'adult_demographics_03', 'Review')
MATCH_FIELDS = COLUMNS[1:-1]
MARKER = 'suspected fake case'
NORMALIZATION_RULE = 'all_seven_retained_fields_nfkc_trim_exact_v1'
RULE = 'review_literal_contains_case_sensitive__' + NORMALIZATION_RULE
STRICT_PROJECTION = 'strict_all_seven_keys_v1'
MERGED_ROLE_PROJECTION = 'merged_role_opposite_fields_structural_blank_v1'
ROLE_BLANK_FIELDS = {
    'student': frozenset({'contact_03.1', 'adult_demographics_03'}),
    'parent': frozenset({'student_demographics_06'}),
}
INVENTORY_FORMAT = 'study2_manual_flag_inventory_v1'
REGISTRY_FORMAT = 'study2_local_manual_flags_v1'
APP_ID = 0x5332464C
SCHEMA_VERSION = 1
DDL = (
    'CREATE TABLE metadata (id INTEGER PRIMARY KEY CHECK(id=1), value TEXT NOT NULL)',
    'CREATE TABLE ledger (id INTEGER PRIMARY KEY CHECK(id=1), value TEXT NOT NULL)',
    'CREATE TABLE events (seq INTEGER PRIMARY KEY, action TEXT NOT NULL, '
    'operator TEXT NOT NULL, reason TEXT NOT NULL, at TEXT NOT NULL, payload TEXT NOT NULL)',
    'CREATE TABLE snapshots (snapshot_id TEXT PRIMARY KEY, value TEXT NOT NULL)',
)


class FlagError(PipelineError):
    """Stable codes only; console errors must not disclose record-level evidence."""


def _need(ok, code):
    if not ok:
        raise FlagError(code)


def _json(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False,
                      separators=(',', ':'))


def _bytes(value):
    return (_json(value) + '\n').encode('utf-8')


def _sha256(data):
    return hashlib.sha256(data).hexdigest()


def scalar(value):
    """The approved CSV-only comparison rule; does not alter source answers."""
    if value is None or isinstance(value, float) and not math.isfinite(value):
        return ''
    _need(isinstance(value, (str, int, float, Decimal, bool)), 'unsupported_match_scalar')
    result = unicodedata.normalize('NFKC', str(value)).strip()
    _need(len(result) <= 4096, 'match_scalar_too_long')
    if isinstance(value, (int, float, Decimal)) and not isinstance(value, bool):
        number = Decimal(result)
        if number.is_finite() and number == number.to_integral_value():
            _need(number.is_zero() or number.adjusted() < 4096, 'match_scalar_too_long')
            return str(int(number))
    return result


def _key(values, *, role=None, merged_role_structural_blanks=False):
    if not isinstance(values, dict):
        return None
    missing = set(MATCH_FIELDS) - values.keys()
    allowed = ROLE_BLANK_FIELDS.get(role, frozenset()) if merged_role_structural_blanks else frozenset()
    if not missing <= allowed:
        return None
    key = tuple('' if name in missing else scalar(values[name]) for name in MATCH_FIELDS)
    return key if any(key) else None


def _pin(row):
    return {name: row[name] for name in ('submission_id', 'version_id', 'role', 'raw_hash')}


@dataclass(frozen=True)
class Inventory:
    release_id: str
    records: tuple
    revision: str
    provenance: dict

    @classmethod
    def from_records(cls, release_id, records, *, provenance=None):
        _need(isinstance(release_id, str) and bool(release_id.strip()), 'release_id_required')
        rows = records.to_dict('records') if hasattr(records, 'to_dict') else list(records)
        rows = deepcopy(rows)
        try:
            revision = inventory_revision(rows)
            for row in rows:
                if 'raw' in row:
                    _need(isinstance(row['raw'], dict) and digest(row['raw']) == row['raw_hash'],
                          'inventory_raw_hash_mismatch')
        except EligibilityError as error:
            raise FlagError(str(error)) from None
        return cls(release_id, tuple(rows), revision, deepcopy(provenance or {}))

    def checked(self):
        current = Inventory.from_records(self.release_id, self.records, provenance=self.provenance)
        _need(current.revision == self.revision, 'inventory_changed_after_pin')
        return current


def _read_pinned(path):
    path = Path(path).expanduser().absolute()
    _need(path.is_file() and not path.is_symlink(), 'regular_input_file_required')
    with path.open('rb') as handle:
        before = os.fstat(handle.fileno())
        data = handle.read()
        after = os.fstat(handle.fileno())
    _need((before.st_ino, before.st_size, before.st_mtime_ns) ==
          (after.st_ino, after.st_size, after.st_mtime_ns) and
          path.stat().st_ino == after.st_ino, 'input_changed_during_read')
    return data, {'path': str(path), 'sha256': _sha256(data)}


def load_inventory(*, inventory_path=None, release_folder=None):
    """Reads only caller-named files; no CURRENT pointer, sources or database."""
    _need((inventory_path is None) != (release_folder is None), 'one_inventory_input_required')
    try:
        if inventory_path is not None:
            data, pin = _read_pinned(inventory_path)
            value = json.loads(data)
            _need(isinstance(value, dict) and set(value) == {'format', 'release_id', 'records'}
                  and value['format'] == INVENTORY_FORMAT and isinstance(value['records'], list),
                  'inventory_file_shape_invalid')
            return Inventory.from_records(value['release_id'], value['records'], provenance=pin)
        root = Path(release_folder).expanduser().absolute()
        summary, summary_pin = _read_pinned(root / 'summary.json')
        compressed, records_pin = _read_pinned(root / 'records.jsonl.gz')
        rows = [json.loads(line) for line in gzip.decompress(compressed).decode('utf-8').splitlines()
                if line.strip()]
        release_id = json.loads(summary)['release_id']
        # Both files must still be the pinned files at the end of this read.
        _need(_read_pinned(root / 'summary.json')[1] == summary_pin and
              _read_pinned(root / 'records.jsonl.gz')[1] == records_pin,
              'input_changed_during_read')
        return Inventory.from_records(release_id, rows, provenance={
            'summary': summary_pin, 'records': records_pin})
    except (ValueError, KeyError, TypeError, UnicodeError, EOFError, gzip.BadGzipFile):
        raise FlagError('inventory_file_invalid') from None


def preview_csv(csv_path, inventory, *, copy_policy=None, field_container='raw',
                expected_csv_sha256=None, merged_role_structural_blanks=False):
    """Pure preview. Returns private pins and fingerprints, never writes a ledger."""
    inventory = inventory.checked()
    _need(copy_policy in {None, COPY_POLICY}, 'copy_policy_invalid')
    _need(field_container in {'raw', 'answer', 'record'}, 'field_container_invalid')
    _need(type(merged_role_structural_blanks) is bool, 'structural_blank_option_invalid')
    data, csv_pin = _read_pinned(csv_path)
    _need(expected_csv_sha256 is None or expected_csv_sha256 == csv_pin['sha256'],
          'csv_changed_since_preview')
    groups = defaultdict(list)
    unindexable = 0
    for record in inventory.records:
        key = _key(record if field_container == 'record' else record.get(field_container),
                   role=record['role'], merged_role_structural_blanks=merged_role_structural_blanks)
        if key is None:
            unindexable += 1
        else:
            groups[key].append(record)
    rows, selected, total = {}, 0, 0
    try:
        reader = csv.reader(io.StringIO(data.decode('utf-8-sig'), newline=''), strict=True)
        header = next(reader)
        _need(all(header.count(name) == 1 for name in COLUMNS), 'csv_projection_headers_invalid')
        offsets = {name: header.index(name) for name in COLUMNS}
        for number, row in enumerate(reader, 2):
            if not row:
                continue
            total += 1
            _need(len(row) > max(offsets.values()), 'csv_truncated_row')
            projected = {name: row[offsets[name]] for name in COLUMNS}
            if MARKER not in projected['Review']:
                continue
            selected += 1
            fingerprint = sha(projected)
            if fingerprint in rows:
                rows[fingerprint]['row_numbers'].append(number)
                continue
            matches = sorted(groups.get(_key(projected), []), key=lambda r: r['submission_id'])
            if not matches:
                outcome = 'unmatched'
            elif len(matches) == 1:
                outcome = 'matched'
            elif copy_policy != COPY_POLICY:
                outcome = 'copy_policy_required'
            elif len({(r['role'], r['raw_hash']) for r in matches}) != 1:
                outcome = 'ambiguous_nonidentical'
            elif not all(isinstance(r.get('raw'), dict) for r in matches):
                outcome = 'unverified_copies'
            else:
                outcome = 'matched'
            rows[fingerprint] = dict(row_fingerprint=fingerprint, row_numbers=[number],
                                     outcome=outcome, candidates=[_pin(r) for r in matches])
    except (UnicodeError, StopIteration, csv.Error):
        raise FlagError('csv_invalid') from None
    binding = dict(csv_sha256=csv_pin['sha256'], release_id=inventory.release_id,
                   inventory_revision=inventory.revision, rule=RULE, normalization_rule=NORMALIZATION_RULE,
                   projection_rule=MERGED_ROLE_PROJECTION if merged_role_structural_blanks else STRICT_PROJECTION,
                   copy_policy=copy_policy, field_container=field_container)
    batch_id = sha(binding)
    observations = []
    for row in rows.values():
        observations.append({**row, 'observation_id': sha([batch_id, row['row_fingerprint']])})
    return dict(format='study2_manual_flag_preview_v1', batch_id=batch_id, binding=binding,
                csv=csv_pin, inventory_provenance=inventory.provenance,
                total_csv_rows=total, selected_csv_rows=selected,
                unique_selected_rows=len(rows), unindexable_records=unindexable,
                matched_csv_rows=sum(len(r['row_numbers']) for r in observations if r['outcome'] == 'matched'),
                observations=observations)


def _empty_state():
    return dict(flags={}, batches={}, observations={}, absent_acks=[], seeds={})


def _schema(connection):
    return connection.execute("SELECT type,name,sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' ORDER BY name").fetchall()


def _expected_schema():
    with sqlite3.connect(':memory:') as connection:
        for statement in DDL:
            connection.execute(statement)
        return _schema(connection)


def _validate_db(connection):
    _need(connection.execute('PRAGMA application_id').fetchone()[0] == APP_ID and
          connection.execute('PRAGMA user_version').fetchone()[0] == SCHEMA_VERSION and
          _schema(connection) == _expected_schema(), 'foreign_or_invalid_registry')
    _need(connection.execute('PRAGMA quick_check').fetchall() == [('ok',)], 'registry_integrity_failure')
    try:
        metadata = json.loads(connection.execute('SELECT value FROM metadata WHERE id=1').fetchone()[0])
        state = json.loads(connection.execute('SELECT value FROM ledger WHERE id=1').fetchone()[0])
        _need(set(metadata) == {'format', 'registry_id', 'created_by', 'created_at'} and
              metadata['format'] == REGISTRY_FORMAT and
              set(state) == set(_empty_state()) and
              all(isinstance(state[name], dict) for name in ('flags', 'batches', 'observations', 'seeds')) and
              isinstance(state['absent_acks'], list), 'invalid_registry_state')
        events = dict(connection.execute('SELECT seq,action FROM events'))
        for sid, flag in state['flags'].items():
            _need(flag['pin']['submission_id'] == sid and flag['state'] in {'active', 'removed'}
                  and type(flag['event_seq']) is int and flag['event_seq'] in events,
                  'invalid_registry_flag')
            inventory_revision([flag['pin']])
        for key, row in state['observations'].items():
            _need(isinstance(row, dict) and row['observation_id'] == key and
                  row['event_seq'] in events and isinstance(row['candidates'], list) and
                  row['outcome'] in {'matched', 'unmatched', 'copy_policy_required',
                      'ambiguous_nonidentical', 'unverified_copies', 'held_existing_decision'} and
                  (row['dismissed_event'] is None or row['dismissed_event'] in events and
                   row['dismissed_event'] > row['event_seq']), 'invalid_registry_observation')
            inventory_revision(row['candidates'])
            _need(row['outcome'] != 'held_existing_decision' or row['candidates'],
                  'invalid_registry_observation')
            resolved = row.get('resolved_event')
            _need(resolved is None or row['outcome'] == 'held_existing_decision' and
                  type(resolved) is int and resolved > row['event_seq'] and
                  events.get(resolved) in {'remove', 'restore', 'rebind'}, 'invalid_registry_resolution')
        for ack in state['absent_acks']:
            _need(ack['submission_id'] == ack['pin']['submission_id'] and ack['event_seq'] in events,
                  'invalid_registry_acknowledgement')
            inventory_revision([ack['pin']])
    except (TypeError, KeyError, ValueError, EligibilityError):
        raise FlagError('invalid_registry_state') from None
    return metadata, state


def _path(path):
    result = Path(path).expanduser().absolute()
    _need(result.is_file() and not result.is_symlink(), 'registry_file_required')
    with result.open('rb') as handle:
        header = handle.read(100)
    _need(len(header) == 100 and header[:16] == b'SQLite format 3\0' and
          struct.unpack('>I', header[68:72])[0] == APP_ID, 'foreign_or_invalid_registry')
    # Do not perform implicit recovery, nor open another application's sidecars.
    _need(not any(Path(str(result) + suffix).exists() for suffix in ('-journal', '-wal', '-shm')),
          'registry_recovery_required')
    return result


def _uri(path, mode, immutable=False):
    return 'file:' + quote(str(path), safe='/') + '?mode=' + mode + ('&immutable=1' if immutable else '')


def initialize_registry(registry_path, *, operator):
    _actor(operator)
    path = Path(registry_path).expanduser().absolute()
    _need(path.parent.is_dir(), 'registry_parent_required')
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        raise FlagError('registry_already_exists') from None
    identity = os.fstat(fd).st_ino
    os.close(fd)
    try:
        with sqlite3.connect(_uri(path, 'rw'), uri=True) as connection:
            connection.execute('PRAGMA journal_mode=DELETE')
            connection.execute(f'PRAGMA application_id={APP_ID}')
            connection.execute(f'PRAGMA user_version={SCHEMA_VERSION}')
            for statement in DDL:
                connection.execute(statement)
            metadata = dict(format=REGISTRY_FORMAT, registry_id=str(uuid.uuid4()),
                            created_by=operator, created_at=utcnow())
            connection.execute('INSERT INTO metadata VALUES (1,?)', (_json(metadata),))
            connection.execute('INSERT INTO ledger VALUES (1,?)', (_json(_empty_state()),))
        return metadata
    except BaseException:
        if path.exists() and path.stat().st_ino == identity:
            path.unlink()
        raise


@contextmanager
def _registry(registry_path, *, write=False):
    path = _path(registry_path)
    identity = path.stat().st_ino
    with sqlite3.connect(_uri(path, 'ro', immutable=True), uri=True) as read:
        _validate_db(read)
    _need(path.stat().st_ino == identity, 'registry_replaced_during_open')
    connection = sqlite3.connect(_uri(path, 'rw' if write else 'ro', immutable=not write), uri=True)
    try:
        if write:
            connection.execute('BEGIN IMMEDIATE')
        metadata, state = _validate_db(connection)
        _record_held_resolutions(connection, state)
        yield connection, metadata, state
        if write:
            connection.execute('UPDATE ledger SET value=? WHERE id=1', (_json(state),))
            _commit(connection)
    except BaseException:
        connection.rollback()
        raise
    finally:
        connection.close()


def _commit(connection):
    connection.commit()


def _actor(operator, reason=None):
    _need(isinstance(operator, str) and bool(operator.strip()), 'operator_required')
    if reason is not None:
        _need(isinstance(reason, str) and bool(reason.strip()), 'reason_required')


def _event(connection, action, operator, reason, payload):
    return connection.execute('INSERT INTO events(action,operator,reason,at,payload) VALUES (?,?,?,?,?)',
                              (action, operator, reason, utcnow(), _json(payload))).lastrowid


def _apply_pins(state, pins, event):
    """Add only new flags. Existing tombstones and versions are never overwritten."""
    counts = dict(newly_active=0, already_active=0, held=0)
    for pin in pins:
        sid = pin['submission_id']
        old = state['flags'].get(sid)
        if old is None:
            state['flags'][sid] = dict(pin=pin, state='active', event_seq=event)
            counts['newly_active'] += 1
        elif old['state'] == 'active' and old['pin'] == pin:
            counts['already_active'] += 1
        else:
            counts['held'] += 1
    return counts


def _replay(original, state):
    """Historical effects are evidence, not effects of the idempotent replay."""
    result = deepcopy(original)
    result.update(idempotent=True, original_import_flag_counts=result['flag_counts'],
                  flag_counts=dict(newly_active=0, already_active=0, held=0))
    if 'unresolved_observations' in result:
        pending = {r['observation_id'] for r in _pending(state)}
        result['original_unresolved_observations'] = result['unresolved_observations']
        result['unresolved_observations'] = sum(r['observation_id'] in pending for r in result['observations'])
    return result


def import_csv(registry_path, csv_path, inventory, *, operator, copy_policy=None,
               field_container='raw', expected_csv_sha256=None, merged_role_structural_blanks=False):
    _actor(operator)
    report = preview_csv(csv_path, inventory, copy_policy=copy_policy,
                         field_container=field_container, expected_csv_sha256=expected_csv_sha256,
                         merged_role_structural_blanks=merged_role_structural_blanks)
    with _registry(registry_path, write=True) as (connection, _, state):
        if report['batch_id'] in state['batches']:
            return _replay(state['batches'][report['batch_id']], state)
        event = _event(connection, 'csv_import', operator, 'Explicit weekly CSV import', report)
        pins = {p['submission_id']: p for row in report['observations'] if row['outcome'] == 'matched'
                for p in row['candidates']}
        report['flag_counts'] = _apply_pins(state, pins.values(), event)
        report['distinct_matched_ids'] = len(pins)
        for observation in report['observations']:
            value = {**observation, 'batch_id': report['batch_id'], 'event_seq': event,
                     'dismissed_event': None}
            if value['outcome'] == 'matched' and any(
                    state['flags'][p['submission_id']]['state'] != 'active' or
                    state['flags'][p['submission_id']]['pin'] != p for p in value['candidates']):
                value['outcome'] = 'held_existing_decision'
                observation['outcome'] = value['outcome']
            state['observations'][value['observation_id']] = value
        report['unresolved_observations'] = sum(r['outcome'] != 'matched' for r in report['observations'])
        report['idempotent'] = False
        state['batches'][report['batch_id']] = deepcopy(report)
        return report


def seed_manifest(registry_path, manifest, inventory, *, operator, reason):
    _actor(operator, reason)
    inventory = inventory.checked()
    try:
        ids = validate_manifest(manifest, inventory.records, inventory.release_id)
    except EligibilityError as error:
        raise FlagError(str(error)) from None
    key = sha(manifest)
    with _registry(registry_path, write=True) as (connection, _, state):
        if key in state['seeds']:
            return _replay(state['seeds'][key], state)
        event = _event(connection, 'seed_manifest', operator, reason, dict(
            manifest=manifest, inventory_provenance=inventory.provenance))
        pins = [_pin(r) for r in inventory.records if r['submission_id'] in ids]
        counts = _apply_pins(state, pins, event)
        obs_id = sha(['seed', key])
        if counts['held']:
            state['observations'][obs_id] = dict(observation_id=obs_id, outcome='held_existing_decision',
                candidates=pins, event_seq=event, dismissed_event=None, seed_revision=key)
        value = dict(seed_revision=key, flag_counts=counts, idempotent=False)
        state['seeds'][key] = value
        return deepcopy(value)


def decide_flags(registry_path, submission_ids, *, action, operator, reason, inventory=None):
    """Explicit remove / restore / rebind. Rebind is never inferred by CSV import."""
    _actor(operator, reason)
    _need(action in {'remove', 'restore', 'rebind'}, 'flag_action_invalid')
    ids = sorted(set(submission_ids))
    _need(ids and all(isinstance(s, str) and s for s in ids), 'flag_ids_required')
    current = {}
    if action != 'remove':
        _need(isinstance(inventory, Inventory), 'inventory_required')
        inventory = inventory.checked()
        current = {r['submission_id']: _pin(r) for r in inventory.records}
        _need(all(s in current for s in ids), 'decision_identity_not_in_inventory')
    with _registry(registry_path, write=True) as (connection, _, state):
        _need(all(s in state['flags'] for s in ids), 'unknown_flag_identity')
        if action == 'rebind':
            _need(all(state['flags'][s]['state'] == 'active' for s in ids), 'removed_flag_needs_restore')
        changed = [s for s in ids if (state['flags'][s]['state'] != 'removed' if action == 'remove'
                   else state['flags'][s]['state'] != 'active' or state['flags'][s]['pin'] != current[s])]
        if not changed:
            return dict(action=action, changed=0, idempotent=True)
        before = {s: deepcopy(state['flags'][s]) for s in changed}
        event = _event(connection, action, operator, reason, dict(ids=changed, before=before,
            release_id=inventory.release_id if inventory else None,
            inventory_revision=inventory.revision if inventory else None,
            after_pins={s: current[s] for s in changed} if current else {}))
        for sid in changed:
            flag = state['flags'][sid]
            flag.update(state='removed' if action == 'remove' else 'active', event_seq=event)
            if action != 'remove':
                flag['pin'] = current[sid]
        _record_held_resolutions(connection, state)
        return dict(action=action, changed=len(changed), idempotent=False)


def dismiss_observations(registry_path, observation_ids, *, operator, reason):
    """Acknowledge/reject unresolved evidence; does not choose or unflag any ID."""
    _actor(operator, reason)
    ids = sorted(set(observation_ids))
    _need(ids, 'observation_ids_required')
    with _registry(registry_path, write=True) as (connection, _, state):
        _need(all(s in state['observations'] for s in ids), 'unknown_observation')
        changed = [s for s in ids if state['observations'][s]['dismissed_event'] is None]
        if changed:
            event = _event(connection, 'dismiss_observations', operator, reason, dict(ids=changed))
            for key in changed:
                state['observations'][key]['dismissed_event'] = event
        return dict(changed=len(changed), idempotent=not changed)


def acknowledge_absent(registry_path, submission_ids, inventory, *, operator, reason):
    """Omit absent flags for this inventory only; keep global active flags/history."""
    _actor(operator, reason)
    inventory = inventory.checked()
    ids = sorted(set(submission_ids))
    _need(ids, 'flag_ids_required')
    present = {r['submission_id'] for r in inventory.records}
    with _registry(registry_path, write=True) as (connection, _, state):
        _need(all(s not in present and s in state['flags'] and state['flags'][s]['state'] == 'active'
                  for s in ids), 'absent_active_flag_required')
        have = {(r['submission_id'], r['release_id'], r['inventory_revision'], sha(r['pin']))
                for r in state['absent_acks']}
        changed = [s for s in ids if (s, inventory.release_id, inventory.revision,
                                    sha(state['flags'][s]['pin'])) not in have]
        if changed:
            event = _event(connection, 'acknowledge_absent', operator, reason, dict(ids=changed,
                release_id=inventory.release_id, inventory_revision=inventory.revision))
            state['absent_acks'].extend(dict(submission_id=s, release_id=inventory.release_id,
                inventory_revision=inventory.revision, pin=deepcopy(state['flags'][s]['pin']),
                event_seq=event) for s in changed)
        return dict(changed=len(changed), idempotent=not changed)


def _record_held_resolutions(connection, state):
    """Close held evidence at its first proven explicit decision, permanently.

    Replay only candidate flags' explicit transitions. Their saved `before`
    states also recover a completed old observation from an r1/r2 registry after
    its flag has moved on. Read-only callers annotate an in-memory copy; write
    transactions persist the history reference without altering any candidate.
    """
    try:
        decisions = [(seq, action, json.loads(payload)) for seq, action, payload in connection.execute(
            "SELECT seq,action,payload FROM events WHERE action IN ('remove','restore','rebind') ORDER BY seq")]
        for row in state['observations'].values():
            if row['outcome'] != 'held_existing_decision' or row['dismissed_event'] is not None:
                continue
            pins = {p['submission_id']: p for p in row['candidates']}
            transitions = [(seq, action, payload) for seq, action, payload in decisions
                           if seq > row['event_seq'] and pins.keys() & payload['before'].keys()]
            flags = {sid: deepcopy(state['flags'][sid]) for sid in pins}
            for _, _, payload in reversed(transitions):
                for sid in pins.keys() & payload['before'].keys():
                    flags[sid] = deepcopy(payload['before'][sid])
            completed = None
            for seq, action, payload in transitions:
                for sid in pins.keys() & payload['before'].keys():
                    flags[sid] = dict(pin=flags[sid]['pin'] if action == 'remove' else payload['after_pins'][sid],
                                      state='removed' if action == 'remove' else 'active', event_seq=seq)
                if all((flags[sid]['state'] == 'active' and flags[sid]['pin'] == pin) or
                       (flags[sid]['state'] == 'removed' and flags[sid]['event_seq'] > row['event_seq'])
                       for sid, pin in pins.items()):
                    completed = seq
                    break
            _need(row.get('resolved_event') is None or row['resolved_event'] == completed,
                  'invalid_registry_resolution_history')
            if completed is not None:
                row['resolved_event'] = completed
    except (ValueError, KeyError, TypeError):
        raise FlagError('invalid_registry_resolution_history') from None


def _pending(state):
    result = []
    for key, row in sorted(state['observations'].items()):
        if row['dismissed_event'] is not None or row.get('resolved_event') is not None or row['outcome'] == 'matched':
            continue
        result.append(dict(code=row['outcome'], observation_id=key))
    return result


def status(registry_path, *, include_history=False):
    with _registry(registry_path) as (connection, metadata, state):
        result = dict(metadata=metadata, active=sum(v['state'] == 'active' for v in state['flags'].values()),
                      removed=sum(v['state'] == 'removed' for v in state['flags'].values()),
                      batches=len(state['batches']), pending=_pending(state),
                      flags=deepcopy(state['flags']), observations=deepcopy(state['observations']),
                      event_count=connection.execute('SELECT count(*) FROM events').fetchone()[0])
        if include_history:
            result['history'] = [dict(seq=r[0], action=r[1], operator=r[2], reason=r[3],
                                      at=r[4], payload=json.loads(r[5])) for r in connection.execute(
                                          'SELECT * FROM events ORDER BY seq')]
        return result


def compile_snapshot(registry_path, inventory, *, operator):
    """Persist accepted or blocked exact-release compilation; never a partial manifest."""
    _actor(operator)
    inventory = inventory.checked()
    current = {r['submission_id']: _pin(r) for r in inventory.records}
    with _registry(registry_path, write=True) as (connection, metadata, state):
        state_revision = sha(state)
        snapshot_id = sha([metadata['registry_id'], inventory.release_id, inventory.revision,
                           state_revision, RULE, COPY_POLICY])
        blockers = _pending(state)
        acks = {(r['submission_id'], r['release_id'], r['inventory_revision'], sha(r['pin']))
                for r in state['absent_acks']}
        entries = []
        for sid, flag in sorted(state['flags'].items()):
            if flag['state'] != 'active':
                continue
            if sid not in current:
                if (sid, inventory.release_id, inventory.revision, sha(flag['pin'])) not in acks:
                    blockers.append(dict(code='active_flag_absent', submission_id=sid))
            elif current[sid] != flag['pin']:
                blockers.append(dict(code='active_flag_content_changed', submission_id=sid,
                                     previous=flag['pin'], current=current[sid]))
            else:
                entries.append({k: flag['pin'][k] for k in ('submission_id', 'version_id')})
        manifest = dict(format=MANIFEST_FORMAT, status='accepted', release_id=inventory.release_id,
            inventory_revision=inventory.revision, copy_policy=COPY_POLICY, approved_by=operator,
            approved_at=utcnow(), entries=entries)
        manifest['revision'] = manifest_revision(manifest)
        if not blockers:
            try:
                validate_manifest(manifest, inventory.records, inventory.release_id)
            except EligibilityError as error:
                blockers.append(dict(code=str(error)))
        report = dict(format='study2_local_manual_flag_snapshot_v1', snapshot_id=snapshot_id,
            release_id=inventory.release_id, inventory_revision=inventory.revision,
            inventory_provenance=inventory.provenance, state_revision=state_revision,
            rule=RULE, copy_policy=COPY_POLICY, status='blocked' if blockers else 'accepted',
            blockers=blockers, manifest=None if blockers else manifest)
        old = connection.execute('SELECT value FROM snapshots WHERE snapshot_id=?', (snapshot_id,)).fetchone()
        if old:
            try:
                cached = json.loads(old[0])
                _need(isinstance(cached, dict) and set(cached) == set(report) and all(
                    cached[k] == report[k] for k in report if k not in {'manifest', 'inventory_provenance'}),
                    'invalid_cached_snapshot')
                if blockers:
                    _need(cached['manifest'] is None, 'invalid_cached_snapshot')
                else:
                    validate_manifest(cached['manifest'], inventory.records, inventory.release_id)
                    _need(cached['manifest']['entries'] == entries, 'invalid_cached_snapshot')
            except (ValueError, TypeError, KeyError, EligibilityError):
                raise FlagError('invalid_cached_snapshot') from None
            return cached
        connection.execute('INSERT INTO snapshots VALUES (?,?)', (snapshot_id, _json(report)))
        return report


def _exclusive_output(path, data):
    """Atomic create-only, or identical-byte no-op. Never replaces an accepted file."""
    path = Path(path).expanduser().absolute()
    _need(path.parent.is_dir() and not path.is_symlink(), 'output_path_invalid')
    if path.exists():
        _need(path.is_file() and path.read_bytes() == data, 'immutable_output_exists')
        return
    fd, temporary = tempfile.mkstemp(prefix='.manual-flags-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, path)
        except FileExistsError:
            _need(not path.is_symlink() and path.is_file() and path.read_bytes() == data,
                  'immutable_output_exists')
    finally:
        Path(temporary).unlink(missing_ok=True)


def export_manifest(registry_path, inventory, output_path, *, operator):
    report = compile_snapshot(registry_path, inventory, operator=operator)
    if report['status'] == 'accepted':
        _exclusive_output(output_path, _bytes(report['manifest']))
    return report


def _arguments():
    parser = argparse.ArgumentParser(description='Local manual-flag ledger. All paths are explicit; no research DB access.')
    sub = parser.add_subparsers(dest='command', required=True)
    for name in ('init', 'preview', 'import', 'seed', 'export', 'remove', 'restore', 'rebind',
                 'dismiss', 'ack-absent', 'status'):
        command = sub.add_parser(name)
        if name != 'preview':
            command.add_argument('--registry', required=True)
        if name not in {'preview', 'status'}:
            command.add_argument('--operator', required=True)
        if name in {'seed', 'remove', 'restore', 'rebind', 'dismiss', 'ack-absent'}:
            command.add_argument('--reason', required=True)
        if name in {'preview', 'import', 'seed', 'export', 'restore', 'rebind', 'ack-absent'}:
            group = command.add_mutually_exclusive_group(required=True)
            group.add_argument('--inventory')
            group.add_argument('--release-folder')
        if name in {'preview', 'import'}:
            command.add_argument('--csv', required=True)
            command.add_argument('--copy-policy', choices=[COPY_POLICY])
            command.add_argument('--field-container', choices=['raw', 'answer', 'record'], default='raw')
            command.add_argument('--expected-csv-sha256')
            command.add_argument('--merged-role-structural-blanks', action='store_true',
                                 help='Explicitly project only absent opposite-role fields to blank')
        if name == 'seed':
            command.add_argument('--manifest', required=True)
        if name == 'export':
            command.add_argument('--output', required=True)
        if name in {'remove', 'restore', 'rebind', 'ack-absent'}:
            command.add_argument('--submission-id', action='append', required=True)
        if name == 'dismiss':
            command.add_argument('--observation-id', action='append', required=True)
        if name == 'status':
            command.add_argument('--history', action='store_true')
        command.add_argument('--report', help='Optional new private JSON report path; never overwritten')
    return parser.parse_args()


def main():
    args = _arguments()
    try:
        inv = load_inventory(inventory_path=args.inventory, release_folder=args.release_folder) if hasattr(args, 'inventory') else None
        if args.command == 'init':
            result = initialize_registry(args.registry, operator=args.operator)
        elif args.command in {'preview', 'import'}:
            options = dict(copy_policy=args.copy_policy, field_container=args.field_container,
                           expected_csv_sha256=args.expected_csv_sha256,
                           merged_role_structural_blanks=args.merged_role_structural_blanks)
            result = (preview_csv(args.csv, inv, **options) if args.command == 'preview' else
                      import_csv(args.registry, args.csv, inv, operator=args.operator, **options))
        elif args.command == 'seed':
            data, _ = _read_pinned(args.manifest)
            result = seed_manifest(args.registry, json.loads(data), inv,
                                   operator=args.operator, reason=args.reason)
        elif args.command == 'export':
            result = export_manifest(args.registry, inv, args.output, operator=args.operator)
        elif args.command in {'remove', 'restore', 'rebind'}:
            result = decide_flags(args.registry, args.submission_id, action=args.command,
                                  operator=args.operator, reason=args.reason, inventory=inv)
        elif args.command == 'dismiss':
            result = dismiss_observations(args.registry, args.observation_id,
                                          operator=args.operator, reason=args.reason)
        elif args.command == 'ack-absent':
            result = acknowledge_absent(args.registry, args.submission_id, inv,
                                        operator=args.operator, reason=args.reason)
        else:
            result = status(args.registry, include_history=args.history)
        if args.report:
            _exclusive_output(args.report, _bytes(result))
        # No IDs, source paths, contacts or row-level evidence on stdout.
        console = {k: result[k] for k in ('status', 'batch_id', 'snapshot_id', 'selected_csv_rows',
                   'matched_csv_rows', 'distinct_matched_ids', 'unique_selected_rows', 'flag_counts',
                   'unresolved_observations', 'active', 'removed', 'batches', 'event_count',
                   'changed', 'idempotent') if k in result}
        if 'blockers' in result:
            console['blocker_count'] = len(result['blockers'])
        if 'pending' in result:
            console['pending_count'] = len(result['pending'])
        print(_json(console or {'status': 'ok'}))
        return 2 if result.get('status') == 'blocked' else 0
    except (FlagError, OSError, sqlite3.Error, ValueError) as error:
        code = str(error) if isinstance(error, FlagError) else 'local_flag_operation_failed'
        print(_json({'status': 'error', 'code': code}), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
