"""Bind a private spam ledger and independent group policy to each release.

The scientific publication row selects an immutable, release-specific
generation. A generation is prepared before publication, so an interruption
cannot make the preceding release use a new or partial exclusion list.
"""
from __future__ import annotations

from contextlib import contextmanager
import fcntl
import functools
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import tempfile

from .analysis_eligibility import sha, validate_manifest
from .common import PipelineError, digest
from .group_cleaning import combined_manifest, exclusion_manifest
from .group_cleaning_operator import REVIEW_FORMAT, read_active, _main_revision
from . import continuity_integration as _continuity
from .continuity_integration import check_inventory_binding
from .review_core import rules_hash as _rules_hash
from . import manual_flags

CONTROL_ENV = 'STUDY2_FLAG_CONTROL'
POLICY_ENV = 'STUDY2_GROUP_POLICY_POINTER'
MANIFEST_ENV = 'STUDY2_MANUAL_EXCLUSION_MANIFEST'
CONTROL_FORMAT = 'study2_reason_preserving_flag_control_v1'
GENERATION_FORMAT = 'study2_flag_release_generation_v1'
RELEASE = re.compile(r'RUN_[0-9a-f]{32}\Z')


def _need(condition, code):
    if not condition:
        raise PipelineError(code)


def _json(path):
    path = Path(path)
    _need(path.is_file() and not path.is_symlink(), 'flag_control_file_missing')
    try:
        return json.loads(path.read_bytes())
    except (ValueError, OSError):
        raise PipelineError('flag_control_json_invalid') from None


def _hash(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def _sync_dir(path):
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _control(cfg):
    value, policy = os.environ.get(CONTROL_ENV), os.environ.get(POLICY_ENV)
    if not value and not policy:
        return None
    _need(bool(value and policy), 'flag_control_environment_incomplete')
    control, policy_pointer = Path(value).absolute(), Path(policy).absolute()
    allowed = (Path(cfg['state_dir']).resolve() / 'analysis_eligibility').resolve()
    _need(not control.is_symlink() and control.is_file()
          and control.resolve().is_relative_to(allowed), 'flag_control_path_invalid')
    descriptor = _json(control)
    _need(isinstance(descriptor, dict) and set(descriptor) == {
        'format', 'baseline_release_id', 'baseline_policy_head'}
        and descriptor['format'] == CONTROL_FORMAT
        and isinstance(descriptor['baseline_release_id'], str)
        and RELEASE.fullmatch(descriptor['baseline_release_id']) is not None
        and isinstance(descriptor['baseline_policy_head'], str)
        and re.fullmatch(r'[0-9a-f]{64}', descriptor['baseline_policy_head']) is not None,
        'flag_control_descriptor_invalid')
    _need(policy_pointer.name == 'CURRENT.json' and not policy_pointer.is_symlink()
          and policy_pointer.is_file(), 'group_policy_pointer_invalid')
    root = control.parent
    registry = root / 'registry.sqlite3'
    manual_flags._path(registry)
    return root, registry, policy_pointer, descriptor


@contextmanager
def _locked_registry(path):
    """Hold a SQLite read transaction while a generation is used or published."""
    path = manual_flags._path(path)
    db = sqlite3.connect(manual_flags._uri(path, 'ro'), uri=True)
    try:
        db.execute('PRAGMA query_only=ON')
        db.execute('BEGIN')
        metadata, state = manual_flags._validate_db(db)
        manual_flags._record_held_resolutions(db, state)
        _need(not manual_flags._pending(state), 'flag_ledger_pending_evidence')
        yield metadata, state
    finally:
        db.close()


def _group_policy(policy_pointer, inventory, descriptor, cfg=None, *, generation=None):
    if generation is None:
        active = read_active(Path(policy_pointer).parent)
    else:
        from .group_cleaning_operator import _load_generation
        active = _load_generation(Path(policy_pointer).parent, generation)
    _need(active is not None and active['policy'].get('policy_active'),
          'group_policy_inactive')
    head = active['pointer']['manifest_sha256']
    check_inventory_binding(active, inventory)
    if inventory.release_id in _continuity.PROFILES:
        _need(isinstance(cfg, dict), 'continuity_live_config_required')
        from .coordinated_update import publication_context
        transition = publication_context(cfg, inventory.release_id)
        if transition is not None and transition.main_db is not None:
            # Reuse the owned native transaction, including its uncommitted
            # control edits. The ordinary immutable reader rejects its journal.
            control_revision = transition.revisions()['main']
        else:
            control_revision = _main_revision(cfg)['main_revision']
        _need(control_revision == active['policy'].get('main_revision') ==
              active['proposal'].get('base', {}).get('main_revision'), 'continuity_main_control_changed')
        _need(_rules_hash(cfg) == active['proposal'].get('base', {}).get('rules_hash'),
              'continuity_scientific_rules_changed')
    if inventory.release_id == descriptor['baseline_release_id']:
        _need(head == descriptor['baseline_policy_head'], 'baseline_group_policy_head_changed')
    else:
        # Existing group controls require a separately reviewed proposal for a
        # changed published inventory. Never silently carry the old policy.
        review = active.get('receipt', {}).get('review', {})
        proposal = active.get('proposal') or {}
        _need(active['policy'].get('release_id') == inventory.release_id
              and isinstance(review, dict)
              and set(review) == {'format', 'proposal_revision', 'accepted', 'reviewer', 'reason', 'review_manifest_sha256'}
              and review.get('format') == REVIEW_FORMAT and review.get('accepted') is True
              and isinstance(review.get('proposal_revision'), str)
              and re.fullmatch(r'[0-9a-f]{64}', review['proposal_revision']) is not None
              and review.get('proposal_revision') == proposal.get('revision') == active['policy'].get('proposal_revision')
              and isinstance(review.get('reviewer'), str) and review['reviewer'].strip()
              and isinstance(review.get('reason'), str) and review['reason'].strip()
              and isinstance(review.get('review_manifest_sha256'), str)
              and re.fullmatch(r'[0-9a-f]{64}', review['review_manifest_sha256']) is not None,
              'reviewed_group_policy_required_for_release')
    flags = manual_flags.status(active['folder'] / 'policy-flags.sqlite')['flags']
    pins = {sid: row['pin'] for sid, row in flags.items() if row['state'] == 'active'}
    published = {e['submission_id']: e['version_id'] for e in active['policy_manifest']['entries']}
    _need(set(pins) == set(published) and all(pins[s]['version_id'] == v for s, v in published.items()),
          'group_policy_ledger_mismatch')
    current = {r['submission_id']: manual_flags._pin(r) for r in inventory.records}
    _need(all(sid in current and current[sid] == pin for sid, pin in pins.items()),
          'group_policy_pin_changed')
    result = exclusion_manifest(inventory.records, inventory.release_id, pins,
        operator='Codex policy carry without changing group decisions',
        at=active['policy_manifest']['approved_at'])
    return head, result


def _expected_spam(inventory, state):
    pins = {r['submission_id']: manual_flags._pin(r) for r in inventory.records}
    acks = {(x['submission_id'], x['release_id'], x['inventory_revision'], sha(x['pin']))
            for x in state['absent_acks']}
    expected = set()
    for sid, flag in state['flags'].items():
        if flag['state'] == 'removed':
            # A genuine finding covered a particular source version. A later
            # changed record requires review, not automatic reinstatement.
            _need(sid not in pins or pins[sid] == flag['pin'], 'removed_flag_content_changed')
            continue
        if sid not in pins:
            _need((sid, inventory.release_id, inventory.revision, sha(flag['pin'])) in acks,
                  'active_flag_absent')
        else:
            _need(pins[sid] == flag['pin'], 'active_flag_content_changed')
            expected.add(sid)
    return expected


def _validate(cfg, control, policy_pointer, descriptor, inventory, metadata, state, *, generation=None):
    root = Path(control).parent
    folder = root / 'releases' / inventory.release_id
    _need(RELEASE.fullmatch(inventory.release_id) is not None and folder.is_dir()
          and not folder.is_symlink(), 'flag_generation_missing')
    info = _json(folder / 'generation.json')
    _need(isinstance(info, dict) and set(info) == {
        'format', 'release_id', 'inventory_revision', 'registry_id', 'state_revision',
        'policy_head', 'files', 'combined_revision', 'control_sha256'}, 'flag_generation_invalid')
    _need(info['format'] == GENERATION_FORMAT and info['release_id'] == inventory.release_id
          and info['inventory_revision'] == inventory.revision
          and info['registry_id'] == metadata['registry_id']
          and info['state_revision'] == sha(state)
          and info['control_sha256'] == _hash(control), 'flag_ledger_generation_mismatch')
    _need(set(info['files']) == {'spam.json', 'policy.json', 'combined.json'},
          'flag_generation_files_invalid')
    for name, expected in info['files'].items():
        path = folder / name
        _need(path.is_file() and not path.is_symlink() and _hash(path) == expected,
              'flag_generation_file_changed')
    spam, policy, combined = (_json(folder / name) for name in ('spam.json', 'policy.json', 'combined.json'))
    spam_ids = set(validate_manifest(spam, inventory.records, inventory.release_id))
    policy_ids = set(validate_manifest(policy, inventory.records, inventory.release_id))
    combined_ids = set(validate_manifest(combined, inventory.records, inventory.release_id))
    _need(spam_ids == _expected_spam(inventory, state), 'spam_manifest_ledger_mismatch')
    head, carried = _group_policy(policy_pointer, inventory, descriptor, cfg, generation=generation)
    _need(info['policy_head'] == head
          and policy_ids == set(validate_manifest(carried, inventory.records, inventory.release_id)),
          'group_policy_generation_mismatch')
    _need(combined_ids == spam_ids | policy_ids and combined['revision'] == info['combined_revision'],
          'combined_manifest_layer_mismatch')
    return folder / 'combined.json'


def _prepare_generation(cfg, release_folder, *, policy_generation=None):
    """Prepare a complete immutable generation; caller holds the state writer lock."""
    selected = _control(cfg)
    if selected is None:
        return None
    root, registry, policy_pointer, descriptor = selected
    inventory = manual_flags.load_inventory(release_folder=release_folder)
    _need(RELEASE.fullmatch(inventory.release_id) is not None, 'flag_release_id_invalid')
    if policy_generation is not None:
        from .owned_locks import assert_owned
        assert_owned(Path(cfg['state_dir'])/'writer.lock')
        assert_owned(policy_pointer.parent/'writer.lock')
    # Reject an unreviewed/invalid target before any registry or generation write.
    head, policy = _group_policy(policy_pointer, inventory, descriptor, cfg, generation=policy_generation)
    report = manual_flags.compile_snapshot(registry, inventory, operator='Codex staged compilation', persist=False)
    _need(report['status'] == 'accepted', 'flag_ledger_export_blocked')
    with _locked_registry(registry) as (_, state):
        _need(report['state_revision'] == sha(state), 'flag_ledger_generation_mismatch')
        _need(set(validate_manifest(report['manifest'], inventory.records, inventory.release_id))
              == _expected_spam(inventory, state), 'spam_manifest_ledger_mismatch')
    spam = report['manifest']
    combined = combined_manifest(inventory.records, inventory.release_id, spam, policy,
        operator='Codex staged composition', at=spam['approved_at'])
    releases = root / 'releases'
    releases.mkdir(mode=0o700, exist_ok=True)
    _need(not releases.is_symlink(), 'flag_generations_path_invalid')
    folder = releases / inventory.release_id
    if not folder.exists():
        temporary = Path(tempfile.mkdtemp(prefix='.pending-', dir=releases))
        for name, value in (('spam.json', spam), ('policy.json', policy), ('combined.json', combined)):
            manual_flags._exclusive_output(temporary / name, manual_flags._bytes(value))
        info = dict(format=GENERATION_FORMAT, release_id=inventory.release_id,
            inventory_revision=inventory.revision, registry_id=manual_flags.status(registry)['metadata']['registry_id'],
            state_revision=report['state_revision'], policy_head=head, control_sha256=_hash(root / 'control.json'),
            files={name: _hash(temporary / name) for name in ('spam.json', 'policy.json', 'combined.json')},
            combined_revision=combined['revision'])
        manual_flags._exclusive_output(temporary / 'generation.json', manual_flags._bytes(info))
        _sync_dir(temporary)
        # The state writer lock serializes installations. A crash leaves an
        # unreferenced staging directory, never a partially active generation.
        _need(not folder.exists(), 'flag_generation_already_exists')
        os.rename(temporary, folder)
        _sync_dir(releases)
    with _locked_registry(registry) as (metadata, state):
        return _validate(cfg, root / 'control.json', policy_pointer, descriptor, inventory, metadata, state, generation=policy_generation)


def prepare_generation(cfg, release_folder, *, policy_generation=None):
    from .owned_locks import exclusive
    selected = _control(cfg)
    if selected is None:
        return None
    with exclusive(Path(cfg['state_dir'])/'writer.lock'), exclusive(selected[2].parent/'writer.lock'):
        return _prepare_generation(cfg, release_folder, policy_generation=policy_generation)


@contextmanager
def _guarded_publication(cfg, release_folder, release_id):
    """Pin the ledger until SQLite commits the new published release."""
    selected = _control(cfg)
    if selected is None:
        _need(release_id not in _continuity.PROFILES, 'continuity_managed_flags_required')
        yield None
        return
    root, registry, policy_pointer, descriptor = selected
    # A direct publish/rollback call must not turn an unreviewed ledger or
    # policy change into a newly accepted generation.
    from .coordinated_update import publication_context
    transition = publication_context(cfg, release_id)
    if transition is not None:
        with transition.guard_manifest() as bound:
            yield bound
        return
    resolve_current(cfg)
    prepared = prepare_generation(cfg, release_folder)
    inventory = manual_flags.load_inventory(release_folder=release_folder)
    _need(inventory.release_id == release_id, 'flag_target_release_mismatch')
    with _locked_registry(registry) as (metadata, state):
        bound = _validate(cfg, root / 'control.json', policy_pointer, descriptor, inventory, metadata, state)
        _need(bound == prepared, 'flag_generation_changed')
        yield bound


@contextmanager
def guarded_publication(cfg, release_folder, release_id):
    from .owned_locks import exclusive
    selected = _control(cfg)
    if selected is None:
        _need(release_id not in _continuity.PROFILES, 'continuity_managed_flags_required')
        yield None
        return
    with exclusive(Path(cfg['state_dir'])/'writer.lock'), exclusive(selected[2].parent/'writer.lock'):
        with _guarded_publication(cfg, release_folder, release_id) as manifest:
            yield manifest


def _current_inventory(cfg):
    state_dir = Path(cfg['state_dir'])
    db_path = state_dir / 'study2.sqlite'
    _need(db_path.is_file() and not db_path.is_symlink(), 'publication_database_missing')
    with sqlite3.connect(db_path.resolve().as_uri() + '?mode=ro', uri=True) as db:
        db.execute('PRAGMA query_only=ON')
        row = db.execute('SELECT r.release_id,r.path FROM releases r JOIN publication p '
                         'ON r.release_id=p.release_id WHERE p.singleton=1').fetchone()
    _need(row is not None and RELEASE.fullmatch(row[0]) is not None, 'publication_missing')
    release_id, path = row
    locations = state_dir / 'release_locations.json'
    if locations.is_file():
        path = _json(locations).get(release_id, path)
    inventory = manual_flags.load_inventory(release_folder=path)
    _need(inventory.release_id == release_id, 'flag_publication_release_mismatch')
    return inventory


def _require_current_workload(cfg, inventory, manifest, *, staged_pointer=None):
    """Fail closed while selection and disposition references differ.

    These files are independently atomic; the activation procedure must install
    the managed selection first and then its matching disposition pointer.
    Until both references and their actual data agree, no managed ON consumer
    may accept a generation.
    """
    from .review_workload import load_summary
    try:
        state = Path(cfg['state_dir']).resolve()
        pointer_path = state / 'CURRENT_REVIEW_DISPOSITION.json'
        workload_value = staged_pointer.get('workload_path') if staged_pointer is not None else os.environ.get('STUDY2_CURRENT_REVIEW_WORKLOAD')
        review_state = cfg['state_dir'] if staged_pointer is not None else os.environ.get('STUDY2_REVIEW_STATE_DIR')
        _need(bool(workload_value and review_state), 'review_disposition_binding_unavailable')
        workload_path = Path(workload_value).absolute()
        _need(Path(review_state).resolve() == state
              and not workload_path.is_symlink() and workload_path.is_file()
              and workload_path.resolve().is_relative_to((state / 'review_dispositions').resolve()),
              'review_disposition_binding_unavailable')
        pointer = staged_pointer if staged_pointer is not None else _json(pointer_path)
        _need(isinstance(pointer, dict) and pointer.get('release_id') == inventory.release_id
              and isinstance(pointer.get('workload_path'), str)
              and Path(pointer['workload_path']).absolute() == workload_path
              and isinstance(pointer.get('workload_sha256'), str),
              'review_disposition_binding_unavailable')
        before = _hash(workload_path)
        _need(before == pointer['workload_sha256'], 'review_disposition_binding_unavailable')
        with sqlite3.connect((state / 'study2.sqlite').resolve().as_uri() + '?mode=ro', uri=True) as db:
            db.execute('PRAGMA query_only=ON')
            revision = digest([tuple(row) for row in db.execute(
                'SELECT decision_id,payload_json,supersedes FROM decisions ORDER BY decision_id')])
        combined = _json(manifest)
        workload, _ = load_summary(release_id=inventory.release_id, decision_revision=revision,
                                   exclusion_revision=combined['revision'], path=workload_path, review_state=state,cfg=cfg,inventory=inventory)
        administrative = workload.get('administrative_disposition')
        if administrative is not None:
            _need(pointer.get('admin_revision') == administrative.get('admin_revision')
                  and pointer.get('operation_id') == administrative.get('operation_id'),
                  'review_disposition_binding_unavailable')
            dataset_value = pointer.get('active_dataset_path')
            _need(isinstance(dataset_value, str), 'review_disposition_binding_unavailable')
            dataset = Path(dataset_value).absolute()
            _need(not dataset.is_symlink() and dataset.is_file()
                  and dataset.resolve().is_relative_to((state / 'review_dispositions').resolve()),
                  'review_disposition_binding_unavailable')
            dataset_hash = _hash(dataset)
            _need(_json(dataset) == administrative.get('projection') and _hash(dataset) == dataset_hash,
                  'review_disposition_binding_unavailable')
        else:
            _need(pointer.get('admin_revision') is None and pointer.get('operation_id') is None,
                  'review_disposition_binding_unavailable')
        _need(_hash(workload_path) == before and (staged_pointer is not None or _json(pointer_path) == pointer),
              'review_disposition_binding_unavailable')
    except PipelineError:
        raise
    except (OSError, ValueError, TypeError, KeyError, sqlite3.Error):
        raise PipelineError('review_disposition_binding_unavailable') from None


def resolve_current(cfg):
    """Resolve the manifest for the authoritative SQLite publication, read-only."""
    from .coordinated_update import require_available
    require_available(Path(cfg['state_dir']))
    selected = _control(cfg)
    if selected is None:
        return None
    root, registry, policy_pointer, descriptor = selected
    inventory = _current_inventory(cfg)
    with _locked_registry(registry) as (metadata, state):
        manifest = _validate(cfg, root / 'control.json', policy_pointer, descriptor, inventory, metadata, state)
        _require_current_workload(cfg, inventory, manifest)
        return manifest


@contextmanager
def guarded_current(cfg):
    """Pin the publication and both flag layers while an export is produced."""
    from .coordinated_update import require_available
    require_available(Path(cfg['state_dir']))
    selected = _control(cfg)
    if selected is None:
        yield None
        return
    root, registry, policy_pointer, descriptor = selected
    lock_path = Path(cfg['state_dir']) / 'writer.lock'
    with lock_path.open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_SH | fcntl.LOCK_NB)
        except BlockingIOError:
            raise PipelineError('publication_or_policy_update_in_progress') from None
        try:
            inventory = _current_inventory(cfg)
            with _locked_registry(registry) as (metadata, state):
                manifest = _validate(cfg, root / 'control.json', policy_pointer, descriptor, inventory, metadata, state)
                _require_current_workload(cfg, inventory, manifest)
                yield manifest
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def guarded_consumer(function):
    @functools.wraps(function)
    def wrapper(cfg, *args, **kwargs):
        with guarded_current(cfg):
            return function(cfg, *args, **kwargs)
    return wrapper
