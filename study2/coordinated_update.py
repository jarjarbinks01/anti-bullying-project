"""Reviewed selected-updater transitions. No approval creation or matching changes.

SQLite publication is authoritative. A durable gate remains closed across all
file/SQLite boundaries and recovery never replays scientific publication.
"""
from contextlib import contextmanager, ExitStack
from contextvars import ContextVar
import json
import os
import re
from pathlib import Path
import sqlite3
import uuid

from .common import PipelineError, atomic_json, file_hash as _file_hash, digest, utcnow
from .analysis_eligibility import sha
from .owned_locks import exclusive, assert_owned

JOURNAL = 'COORDINATED_UPDATE.json'
_context = ContextVar('study2_reviewed_publication', default=None)


def file_hash(path):
    return _file_hash(Path(path))


def need(ok, code):
    if not ok:
        raise PipelineError(code)


def _durable(path, value, fault=None, label='write'):
    fault = fault or (lambda phase: None)
    path = Path(path)
    need(path.parent.is_dir() and not path.is_symlink(), 'transition_output_path_invalid')
    name = ('CURRENT.pending.'+uuid.uuid4().hex+'.json') if path.name == 'CURRENT.json' else ('.'+path.name+'.pending-'+uuid.uuid4().hex)
    temporary = path.parent / name
    with temporary.open('x', encoding='utf-8') as handle:
        json.dump(value, handle, sort_keys=True, allow_nan=False)
        handle.write('\n'); handle.flush(); os.fsync(handle.fileno())
    fault(label+':after_temp_sync')
    os.replace(temporary, path)
    fault(label+':after_replace')
    fd = os.open(path.parent, os.O_RDONLY)
    try: os.fsync(fd)
    finally: os.close(fd)
    fault(label+':after_directory_sync')


def _journal_latest(state, expected):
    """CAS immutable journal identity while retaining validated added metadata."""
    actual = json.loads((Path(state)/JOURNAL).read_text())
    need(set(actual)-set(expected) <= {'post_tracking_revision'} and
         all(actual.get(key) == value for key,value in expected.items()), 'transition_journal_changed')
    if 'post_tracking_revision' in actual:
        need(isinstance(actual['post_tracking_revision'], str) and
             re.fullmatch('[0-9a-f]{64}',actual['post_tracking_revision']) is not None,
             'transition_post_tracking_revision_invalid')
    return actual


def _complete_journal(transaction, expected, *, recovered_to=None):
    # before_commit() durably adds post_tracking_revision. Do not overwrite it
    # with the pre-publication dictionary that the caller originally held.
    latest = _journal_latest(transaction.state, expected)
    from .flag_binding import _current_inventory
    current = _current_inventory(transaction.cfg).release_id
    if current == transaction.plan['target_release_id']:
        need(latest.get('post_tracking_revision') == digest(transaction.tracking()),
             'transition_post_tracking_revision_missing_or_changed')
    value = {**latest, 'status':'complete'}
    if recovered_to is not None:
        value['recovered_to'] = recovered_to
    _durable(transaction.state/JOURNAL, value, transaction.fault, 'completion')


def require_available(state):
    path = Path(state) / JOURNAL
    if path.exists():
        need(not path.is_symlink(), 'transition_journal_symlink')
        value = json.loads(path.read_text())
        if value.get('status') in {'draining', 'pending'}:
            current = _context.get()
            need(current is not None and current.state == Path(state).resolve(),
                 'coordinated_transition_recovery_required')
            assert_owned(Path(state) / 'writer.lock')


def publication_context(cfg, release):
    current = _context.get()
    if current is None:
        return None
    need(current.state == Path(cfg['state_dir']).resolve() and
         current.plan['target_release_id'] == release, 'transition_target_mismatch')
    current.assert_locks()
    return current


def review_reader(cfg):
    current = _context.get()
    if current is None or current.state != Path(cfg['state_dir']).resolve():
        return None
    current.assert_locks()
    db = sqlite3.connect((current.state / 'review.sqlite').as_uri() + '?mode=ro', uri=True)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA query_only=ON')
    return db


def _options(cfg):
    value = cfg.get('coordinated_update')
    need(isinstance(value, dict) and set(value) == {'review_root', 'reviewers', 'selection_path'},
         'explicit_coordinated_update_configuration_required')
    need(isinstance(value['reviewers'], list) and value['reviewers'] and
         all(isinstance(x, str) and x.strip() for x in value['reviewers']), 'trusted_reviewers_required')
    root = Path(value['review_root'])
    need(root.is_absolute() and root.is_dir() and not root.is_symlink(), 'trusted_review_root_required')
    selection = Path(value['selection_path'])
    need(selection.is_absolute() and selection.is_file() and not selection.is_symlink(),
         'selected_application_pointer_required')
    return value, root.resolve(), selection


def _trusted_pin(cfg, pin):
    from .group_cleaning_operator import _read_file
    _, root, _ = _options(cfg)
    path = Path(pin['path'])
    need(path.is_relative_to(root) and path.resolve().is_relative_to(root), 'untrusted_review_provenance')
    # Reject symlink ancestors, not just the last path component.
    need(all(not p.is_symlink() for p in [path, *list(path.parents)[:len(path.parts)-len(root.parts)]]),
         'untrusted_review_provenance')
    return json.loads(_read_file(pin)[1])


def _acceptance(cfg, pin, *, kind, subject, operator):
    value = _trusted_pin(cfg, pin)
    options, _, _ = _options(cfg)
    need(set(value) == {'format', 'kind', 'subject_revision', 'accepted', 'reviewer', 'reason'} and
         value['format'] == 'study2_independent_update_review_v1' and value['kind'] == kind and
         value['subject_revision'] == subject and value['accepted'] is True and
         value['reviewer'] in options['reviewers'] and value['reviewer'] != operator and
         isinstance(value['reason'], str) and value['reason'].strip(), 'independent_update_review_required')
    return value


def stage_policy(cfg, bundle_path, proposal_path, review_path, review_manifest_pin, *,
                 expected_old_release, operator, reason, fault=None):
    """Build a reviewed target generation in the EXISTING trusted policy root.

    Does not move any CURRENT pointer. Native proposal, input, rules, main,
    prior-head and release/backup validation remain in force.
    """
    from . import group_cleaning_operator as group, flag_binding as binding, runner
    from .continuity_integration import validate_bound
    bundle, data, options = group.load_bundle(bundle_path)
    proposal = group._json(proposal_path)
    validate_bound(proposal, data, options)
    review = group._review(review_path, proposal)
    subject = sha({'bundle_revision': bundle['revision'], 'proposal_revision': proposal['revision'],
                   'old_release_id': expected_old_release, 'target_release_id': bundle['release_id']})
    proof = _acceptance(cfg, review_manifest_pin, kind='group_policy', subject=subject, operator=operator)
    need(review['reviewer'] == proof['reviewer'] and review['review_manifest_sha256'] == review_manifest_pin['sha256'],
         'group_review_provenance_mismatch')
    need(data['config'] == cfg and bundle['release_id'] != expected_old_release, 'target_bundle_configuration_mismatch')
    with exclusive(Path(cfg['state_dir']) / 'writer.lock'):
        require_available(cfg['state_dir'])
        selected = binding._control(cfg)
        need(selected is not None, 'managed_update_required')
        _, _, policy_path, _ = selected
        with exclusive(policy_path.parent / 'writer.lock'):
            old_combined = binding._json(binding.resolve_current(cfg))  # Actual old tuple, no mocks.
            guard = {**proposal['base'], 'release_id': expected_old_release}
            group._guard_live(data, guard)
            with sqlite3.connect((Path(cfg['state_dir'])/'study2.sqlite').as_uri()+'?mode=ro', uri=True) as db:
                db.row_factory = sqlite3.Row
                old = runner.verify_release(db, expected_old_release)
                target = runner.verify_release(db, bundle['release_id'])
            inventory = binding.manual_flags.load_inventory(release_folder=target['path'])
            need(inventory.revision == proposal['base']['inventory_revision'] and
                 {r['submission_id']: binding.manual_flags._pin(r) for r in inventory.records} ==
                 {sid: binding.manual_flags._pin(r) for sid, r in data['records'].items()}, 'target_inventory_bundle_mismatch')
            current = group.read_active(policy_path.parent)
            prior = current['policy_manifest']['revision']
            if 'carry' in data:
                need(data['carry'] == group._carry_from_active(current, data, options) and
                     prior == proposal['base']['prior_policy_origin_revision'] and
                     current['pointer']['manifest_sha256'] == proposal['base']['prior_policy_head'], 'policy_carry_head_changed')
            else:
                need(prior == proposal['base']['prior_policy_revision'], 'policy_control_head_changed')
            old_pins = {r['submission_id']:r['version_id'] for r in current['policy_manifest']['entries']}
            proposed_pins = {r['submission_id']:r['version_id'] for r in proposal['flag_entries']}
            need(all(proposed_pins.get(sid) == version for sid,version in old_pins.items()), 'prior_policy_exclusion_pin_lost')
            operation = sha(['stage-publication-policy', subject, sha(review)])
            receipt = dict(format='study2_group_policy_application_v1', operation='stage_publication',
                operation_id=operation, release_id=bundle['release_id'], main_revision=bundle['main_revision'],
                rules_hash=bundle['rules_hash'], operator=operator, reason=reason, at=utcnow(), review=review,
                review_manifest_pin=review_manifest_pin, bundle_revision=bundle['revision'], previous_publication=expected_old_release,
                live_scientific_database_written=False)
            # Incomplete staging generations are retained; no acceptance is invented.
            staged = None
            for candidate in sorted(policy_path.parent.glob('gen_*/receipt.json')):
                if not candidate.is_symlink() and group._json(candidate).get('operation_id') == operation and (candidate.parent/'MANIFEST.json').is_file():
                    pointer = dict(format=group.POINTER_FORMAT, generation=candidate.parent.name,
                                   manifest_sha256=file_hash(candidate.parent/'MANIFEST.json'))
                    staged = group._load_generation(policy_path.parent, pointer)
                    break
            if staged is None:
                staged = group._stage(policy_path.parent, current, proposal, data, receipt,
                                      commit_pointer=False, guard_base=guard, fault=fault)
            need(group.read_active(policy_path.parent)['pointer'] == current['pointer'], 'staging_changed_active_policy')
            manifest = binding.prepare_generation(cfg, target['path'], policy_generation=staged['pointer'])
            target_pins = {r['submission_id']:r['version_id'] for r in binding._json(manifest)['entries']}
            need(all(target_pins.get(r['submission_id']) == r['version_id'] for r in old_combined['entries']), 'prior_combined_exclusion_pin_lost')
            return {'policy_pointer': staged['pointer'], 'manifest': str(manifest),
                    'manifest_revision': binding._json(manifest)['revision'], 'operation_id': operation}


@contextmanager
def _fence(path):
    """SQLite itself fences every writer, including APIs without writer.lock."""
    path = Path(path)
    need(path.is_file() and not path.is_symlink(), 'fenced_database_required')
    db = sqlite3.connect(path.as_uri()+'?mode=rw', uri=True, timeout=0)
    try:
        db.execute('BEGIN IMMEDIATE')
        yield db
    finally:
        db.rollback()
        db.close()


class Transition:
    def __init__(self, cfg, plan, operator, fault=None):
        self.cfg, self.plan, self.operator = cfg, plan, operator
        self.state = Path(cfg['state_dir']).resolve()
        self.fault = fault or (lambda phase: None)
        self.main_db = None
        self.consumer_owner = None
        self.consumer_permit = None
        from .flag_binding import _control
        selected = _control(cfg)
        need(selected is not None, 'managed_update_required')
        self.control, self.registry, self.policy_path, self.descriptor = selected

    def assert_locks(self):
        assert_owned(self.state/'writer.lock')
        assert_owned(self.policy_path.parent/'writer.lock')
        if self.consumer_owner is not None:
            from .consumer_owner_fence import require_live_publication_fence
            require_live_publication_fence(self.consumer_owner, self.consumer_permit,
                                           self.cfg, self.plan)
        else:
            _require_control_binding(self.cfg, self.plan)

    def revisions(self):
        from .group_cleaning_operator import _main_revision
        from .lean_recovery import sqlite_revision
        if self.main_db is None:
            main = _main_revision(self.cfg)['main_revision']
        else:
            from .review import active_decisions
            main = digest(dict(decisions=active_decisions(self.main_db), labels=[dict(r) for r in self.main_db.execute('SELECT * FROM labels ORDER BY case_id')]))
        return {'main': main,
                'review': sqlite_revision(self.state/'review.sqlite'),
                'flags': sqlite_revision(self.registry)}

    def tracking(self):
        from .dyad_operator import workspace_snapshot
        if self.main_db is not None:
            return workspace_snapshot(self.main_db)
        with sqlite3.connect((self.state/'study2.sqlite').as_uri()+'?mode=ro', uri=True) as db:
            db.row_factory = sqlite3.Row
            return workspace_snapshot(db)

    def validate_inputs(self, *, check_tracking=True):
        from . import flag_binding as binding, group_cleaning_operator as group, runner
        self.assert_locks()
        need(self.revisions() == self.plan['revisions'], 'review_or_control_revision_changed')
        if check_tracking:
            expected = self.plan['old_tracking_revision']
            journal_path = self.state/JOURNAL
            if journal_path.exists():
                journal = binding._json(journal_path)
                if journal.get('plan_revision') == self.plan['revision'] and journal.get('post_tracking_revision'):
                    with sqlite3.connect((self.state/'study2.sqlite').as_uri()+'?mode=ro', uri=True) as read:
                        published = read.execute('SELECT release_id FROM publication WHERE singleton=1').fetchone()[0]
                    if published == self.plan['target_release_id']:
                        expected = journal['post_tracking_revision']
            need(digest(self.tracking()) == expected, 'issued_id_or_restriction_history_changed')
        for pin in self.plan['input_pins']:
            group._read_file(pin)
        with sqlite3.connect((self.state/'study2.sqlite').as_uri()+'?mode=ro', uri=True) as db:
            db.row_factory = sqlite3.Row
            for release in (self.plan['old_release_id'], self.plan['target_release_id']):
                runner.verify_release(db, release)
        active = group._load_generation(self.policy_path.parent, self.plan['target_policy'])
        receipt = active['receipt']
        subject = sha({'bundle_revision':receipt['bundle_revision'],
                       'proposal_revision':active['proposal']['revision'],
                       'old_release_id':receipt['previous_publication'],
                       'target_release_id':active['policy']['release_id']})
        need(subject == self.plan['group_review_subject'] and receipt['previous_pointer'] == self.plan['old_policy'] and
             receipt['previous_publication'] == self.plan['old_release_id'], 'target_policy_origin_changed')
        proof = _acceptance(self.cfg, receipt['review_manifest_pin'], kind='group_policy',
                            subject=subject, operator=receipt['operator'])
        need(active['policy']['release_id'] == self.plan['target_release_id'] and
             receipt['review']['reviewer'] == proof['reviewer'] and
             receipt['review']['review_manifest_sha256'] == receipt['review_manifest_pin']['sha256'], 'target_group_review_changed')
        inventory = binding.manual_flags.load_inventory(release_folder=self.plan['target_release_path'])
        need(inventory.release_id == self.plan['target_release_id'], 'target_release_path_mismatch')
        with binding._locked_registry(self.registry) as (metadata, state):
            manifest = binding._validate(self.cfg, self.control/'control.json', self.policy_path,
                self.descriptor, inventory, metadata, state, generation=self.plan['target_policy'])
        need(str(manifest) == self.plan['target_manifest'] and file_hash(manifest) == self.plan['target_manifest_sha256'],
             'target_manifest_changed')
        binding._require_current_workload(self.cfg, inventory, manifest, staged_pointer=self.plan['target_workload'])
        from .administrative_carry_current import validate_transition_source
        validate_transition_source(self.plan)
        return manifest

    @contextmanager
    def guard_manifest(self):
        from . import flag_binding as binding
        manifest = self.validate_inputs()
        with binding._locked_registry(self.registry):
            yield manifest

    def before_commit(self):
        self.assert_locks()
        self.validate_inputs(check_tracking=False)
        current = self.tracking()
        baseline = self.baseline_tracking
        need(set(current) == set(baseline), 'tracking_schema_changed')
        for table, old in baseline.items():
            after = current[table]
            if table == 'dyad_registry':
                indexed = {r['dyad_id']:r for r in after}
                need(set(indexed) == {r['dyad_id'] for r in old}, 'issued_id_set_changed')
                for row in old:
                    new = indexed[row['dyad_id']]
                    need(all(new[k] == v for k,v in row.items() if k not in {'lifecycle','first_published_run_id'}), 'issued_id_anchor_changed')
                    need(row['first_published_run_id'] is None or new['first_published_run_id'] == row['first_published_run_id'], 'issued_id_first_publication_changed')
                    need(row['lifecycle'] != 'retired' or new['lifecycle'] == 'retired', 'retired_id_reactivated')
            elif table == 'dyad_events':
                known = {digest(r) for r in old}
                need(known <= {digest(r) for r in after}, 'tracking_history_removed')
                added = [r for r in after if digest(r) not in known]
                need(all(r['kind'] == 'published_mapping' and json.loads(r['payload_json']).get('run_id') == self.plan['target_release_id'] for r in added), 'unrelated_tracking_history_changed')
            else:
                need(after == old, 'unrelated_tracking_table_changed')
        journal = _journal_latest(self.state, self.journal_seed)
        _durable(self.state/JOURNAL, {**journal,'post_tracking_revision':digest(current)}, self.fault, 'post_tracking')
        self.install('target')
        self.fault('before_sqlite_commit')
        self.assert_locks()

    def install(self, side):
        from . import group_cleaning_operator as group, flag_binding as binding
        _, _, selection = _options(self.cfg)
        for name, path, value in [
            ('policy', self.policy_path, self.plan[side+'_policy']),
            ('workload', self.state/'CURRENT_REVIEW_DISPOSITION.json', self.plan[side+'_workload']),
            ('selection', selection, self.plan[side+'_selection'])]:
            current = binding._json(path)
            allowed = [self.plan['old_'+name], self.plan['target_'+name]]
            if name == 'selection': allowed.append(self.plan['gate_selection'])
            need(current in allowed, 'unexpected_'+name+'_pointer_change')
            _durable(path, value, self.fault, name)
        self.set_environment(side)

    def set_environment(self, side):
        from .flag_binding import MANIFEST_ENV
        workload = self.plan[side+'_workload']
        os.environ[MANIFEST_ENV] = self.plan[side+'_manifest']
        os.environ['STUDY2_CURRENT_REVIEW_WORKLOAD'] = workload['workload_path']
        os.environ['STUDY2_REVIEW_STATE_DIR'] = str(self.state)


def _require_control_binding(cfg, plan):
    """Use exactly the flag and policy locations approved in both endpoints."""
    keys = ('STUDY2_FLAG_CONTROL', 'STUDY2_GROUP_POLICY_POINTER')
    for key in keys:
        old = plan['old_selection']['environment'].get(key)
        target = plan['target_selection']['environment'].get(key)
        need(isinstance(old, str) and old and isinstance(target, str) and target and
             Path(old).is_absolute() and Path(target).is_absolute(),
             'reviewed_control_environment_required')
        expected = Path(old).absolute()
        need(Path(target).absolute() == expected, 'control_root_migration_not_supported')
        actual = os.environ.get(key)
        need(isinstance(actual, str) and actual and Path(actual).is_absolute() and
             Path(actual).absolute() == expected, 'reviewed_control_environment_mismatch')
        need(expected.is_file() and not expected.is_symlink(), 'reviewed_control_path_required')
        if key == 'STUDY2_FLAG_CONTROL':
            allowed = Path(cfg['state_dir']).resolve()/'analysis_eligibility'
            need(expected.resolve().is_relative_to(allowed), 'reviewed_flag_control_outside_state')
        else:
            need(expected.name == 'CURRENT.json', 'reviewed_policy_pointer_required')


def _load_plan(cfg, plan_pin, acceptance_pin, operator):
    plan = _trusted_pin(cfg, plan_pin)
    need(plan.get('format') == 'study2_coordinated_publication_plan_v1' and
         plan.get('revision') == sha({k:v for k,v in plan.items() if k != 'revision'}), 'transition_plan_revision')
    _acceptance(cfg, acceptance_pin, kind='publication_tuple', subject=plan['revision'], operator=operator)
    _, _, _ = _options(cfg)
    need(plan['old_release_id'] != plan['target_release_id'] and
         plan['gate_selection'] == {**plan['old_selection'], 'coordinated_update_gate': True} and
         plan['target_selection'].get('coordinated_update_gate') is not True,
         'transition_selection_contract_invalid')
    # Selected launchers must implement the gate; pin both entry files in input_pins.
    pins = {p['path']:p['sha256'] for p in plan['input_pins']}
    for side in ('old', 'target'):
        entry = plan[side+'_selection']['entry']
        need(entry in pins and file_hash(entry) == pins[entry] == file_hash(Path(__file__).parent.parent/'local_update_entry.py'),
             'selected_entry_has_no_verified_gate')
        environment = plan[side+'_selection']['environment']
        need(environment.get('STUDY2_CURRENT_REVIEW_WORKLOAD') == plan[side+'_workload']['workload_path'] and
             environment.get('STUDY2_MANUAL_EXCLUSION_MANIFEST') == plan[side+'_manifest'] and
             Path(environment.get('STUDY2_REVIEW_STATE_DIR', '')).resolve() == Path(cfg['state_dir']).resolve(),
             'selection_workload_tuple_mismatch')
    _require_control_binding(cfg, plan)
    return plan


def _publish_fenced(cfg, plan_pin, acceptance_pin, *, operator, fault=None,
                    owner_fence=None, owner_permit=None):
    """Run the unchanged real publisher, with a reviewed coordinated tuple."""
    from . import flag_binding as binding, runner
    plan = _load_plan(cfg, plan_pin, acceptance_pin, operator)
    transaction = Transition(cfg, plan, operator, fault)
    transaction.consumer_owner, transaction.consumer_permit = owner_fence, owner_permit
    with exclusive(transaction.state/'writer.lock'), exclusive(transaction.policy_path.parent/'writer.lock'):
        if owner_fence is None:
            require_available(transaction.state)
        else:
            from .consumer_owner_fence import require_publication_fence
            require_publication_fence(owner_fence, owner_permit, cfg, plan)
            need(binding._json(transaction.state/JOURNAL) ==
                 _owner_journal(plan_pin, acceptance_pin, operator, plan),
                 'owner_draining_journal_changed')
        with _fence(transaction.state/'review.sqlite'), _fence(transaction.registry), _fence(transaction.state/'study2.sqlite') as main:
            main.row_factory = sqlite3.Row
            transaction.main_db = main
            token = _context.set(transaction)
            try:
                transaction.validate_inputs()
                actual = binding._current_inventory(cfg).release_id
                if actual == plan['target_release_id']:
                    need(owner_fence is None, 'coordinated_transition_recovery_required')
                    _, _, selected_path = _options(cfg)
                    need(binding._json(transaction.policy_path) == plan['target_policy'] and
                         binding._json(transaction.state/'CURRENT_REVIEW_DISPOSITION.json') == plan['target_workload'] and
                         binding._json(selected_path) == plan['target_selection'], 'completed_transition_tuple_changed')
                    transaction.set_environment('target')
                    binding.resolve_current(cfg)
                    return {'release_id':actual,'status':'complete','idempotent':True}
                need(actual == plan['old_release_id'], 'source_publication_changed')
                need(binding._json(transaction.policy_path) == plan['old_policy'], 'source_policy_changed')
                need(binding._json(transaction.state/'CURRENT_REVIEW_DISPOSITION.json') == plan['old_workload'], 'source_workload_changed')
                _, _, selection = _options(cfg)
                expected_selection = plan['old_selection'] if owner_fence is None else plan['gate_selection']
                need(binding._json(selection) == expected_selection, 'source_selection_changed')
                transaction.set_environment('old')
                binding.resolve_current(cfg)  # Real OLD ledger, policy and workload validation.
                # Revalidate the independently reviewed files before making the durable gate.
                _load_plan(cfg, plan_pin, acceptance_pin, operator)
                journal = {'format':'study2_coordinated_publication_journal_v1', 'status':'pending',
                           'plan_pin':plan_pin, 'acceptance_pin':acceptance_pin, 'operator':operator,
                           'plan_revision':plan['revision']}
                transaction.journal_seed = journal
                if owner_fence is not None:
                    need(binding._json(transaction.state/JOURNAL) ==
                         _owner_journal(plan_pin, acceptance_pin, operator, plan),
                         'owner_draining_journal_changed')
                _durable(transaction.state/JOURNAL, journal, transaction.fault, 'journal')
                transaction.baseline_tracking = transaction.tracking()
                if owner_fence is None:
                    _durable(selection, plan['gate_selection'], transaction.fault, 'gate')
                transaction.fault('after_gate')
                result = runner.publish_release(main, cfg, plan['target_release_id'])
                transaction.main_db = None
                transaction.fault('after_sqlite_commit')
                transaction.set_environment('target')
                binding.resolve_current(cfg)  # Real TARGET including actual admin projection.
                transaction.validate_inputs()
                _complete_journal(transaction, journal)
                return result
            finally:
                _context.reset(token)
                # On any exception, leave the durable gate PENDING. Recovery is
                # explicit and chooses by SQLite; never silently replay/undo data.


def _owner_control(owner):
    from .consumer_owner_fence import OwnedConsumerFence, ScopedEmptyFence
    need(type(owner) in (OwnedConsumerFence, ScopedEmptyFence),
         'coordinated_consumer_owner_fence_not_implemented')


def _owner_journal(plan_pin, acceptance_pin, operator, plan):
    return {'format':'study2_coordinated_publication_journal_v1', 'status':'draining',
            'plan_pin':plan_pin, 'acceptance_pin':acceptance_pin, 'operator':operator,
            'plan_revision':plan['revision']}


def _completed_publication_retry(cfg, journal, plan_pin, acceptance_pin, operator):
    plan = _load_plan(cfg, plan_pin, acceptance_pin, operator)
    need(journal['plan_pin'] == plan_pin and journal['acceptance_pin'] == acceptance_pin and
         journal['operator'] == operator and journal['plan_revision'] == plan['revision'],
         'completed_transition_identity_changed')
    result = _verify_completed(cfg, journal)
    return {**result, 'release_id':plan[result['verified_side']+'_release_id']}


def publish(cfg, plan_pin, acceptance_pin, *, operator, fault=None, owner_fence=None):
    """Require actual owned controls; journal before draining; never replay a retry."""
    state = Path(cfg['state_dir']).resolve()
    path = state/JOURNAL
    if path.exists():
        need(path.is_file() and not path.is_symlink(), 'transition_journal_required')
        journal = json.loads(path.read_text())
        if journal.get('status') == 'complete':
            return _completed_publication_retry(cfg, journal, plan_pin, acceptance_pin, operator)
        _owner_control(owner_fence)
        raise PipelineError('coordinated_transition_recovery_required')
    _owner_control(owner_fence)
    plan = _load_plan(cfg, plan_pin, acceptance_pin, operator)
    owner_fence.check_publish_ready(cfg, plan)
    # Separate from writer.lock: existing readers must be stopped before EX.
    with exclusive(state/'consumer-maintenance.lock'):
        need(not path.exists(), 'coordinated_transition_recovery_required')
        plan = _load_plan(cfg, plan_pin, acceptance_pin, operator)
        owner_fence.check_publish_ready(cfg, plan)
        _durable(path, _owner_journal(plan_pin, acceptance_pin, operator, plan),
                 fault, 'owner_journal')
        with owner_fence.fence(fault=fault) as permit:
            return _publish_fenced(cfg, plan_pin, acceptance_pin, operator=operator,
                fault=fault, owner_fence=owner_fence, owner_permit=permit)


def _recover_fenced(cfg, *, owner_fence=None, owner_permit=None, fault=None):
    """Private fixture engine only; pending recovery may reopen consumers."""
    from . import flag_binding as binding
    state = Path(cfg['state_dir']).resolve()
    path = state/JOURNAL
    need(path.is_file() and not path.is_symlink(), 'transition_journal_required')
    journal = binding._json(path)
    was_complete = journal.get('status') == 'complete'
    plan = _load_plan(cfg, journal['plan_pin'], journal['acceptance_pin'], journal['operator'])
    need(plan['revision'] == journal['plan_revision'], 'transition_journal_plan_changed')
    transaction = Transition(cfg, plan, journal['operator'], fault)
    transaction.consumer_owner, transaction.consumer_permit = owner_fence, owner_permit
    with exclusive(state/'writer.lock'), exclusive(transaction.policy_path.parent/'writer.lock'):
        if owner_fence is not None:
            from .consumer_owner_fence import require_publication_fence
            require_publication_fence(owner_fence, owner_permit, cfg, plan)
        need(binding._json(path) == journal, 'transition_journal_changed')
        with _fence(state/'review.sqlite'), _fence(transaction.registry), _fence(state/'study2.sqlite') as main:
            main.row_factory = sqlite3.Row
            transaction.main_db = main
            token = _context.set(transaction)
            try:
                transaction.validate_inputs()
                actual = binding._current_inventory(cfg).release_id
                need(actual in {plan['old_release_id'],plan['target_release_id']}, 'unexpected_publication_during_recovery')
                side = 'old' if actual == plan['old_release_id'] else 'target'
                if was_complete:
                    _, _, selection = _options(cfg)
                    need(binding._json(transaction.policy_path) == plan[side+'_policy'] and
                         binding._json(state/'CURRENT_REVIEW_DISPOSITION.json') == plan[side+'_workload'] and
                         binding._json(selection) == plan[side+'_selection'], 'completed_transition_tuple_changed')
                    transaction.set_environment(side)
                    binding.resolve_current(cfg)
                    return {'status':'complete','idempotent':True,'verified_side':side}
                transaction.install(side)
                # Repair the derived scientific pointer through its native API.
                from .runner import recover_pointer
                with sqlite3.connect(state/'study2.sqlite') as db:
                    db.row_factory=sqlite3.Row
                    recover_pointer(db,cfg)
                binding.resolve_current(cfg)
                _complete_journal(transaction, journal, recovered_to=side)
                return {'status':'complete','recovered_to':side,'idempotent':False}
            finally:
                _context.reset(token)


@contextmanager
def _read_snapshot(path):
    """Pin an existing SQLite snapshot without recovery, writes or chmod."""
    path = Path(path)
    need(path.is_file() and not path.is_symlink(), 'verification_database_required')
    db = sqlite3.connect(path.as_uri()+'?mode=ro',uri=True,timeout=0)
    db.row_factory = sqlite3.Row
    try:
        db.execute('PRAGMA query_only=ON')
        db.execute('BEGIN')
        db.execute('SELECT name FROM sqlite_master LIMIT 1').fetchall()
        yield db
    finally:
        db.close()


def _verify_completed(cfg, journal):
    """Read-only completed verification; never repairs or opens any gate."""
    from . import flag_binding as binding
    state = Path(cfg['state_dir']).resolve()
    plan = _load_plan(cfg,journal['plan_pin'],journal['acceptance_pin'],journal['operator'])
    need(plan['revision'] == journal['plan_revision'],'transition_journal_plan_changed')
    transaction = Transition(cfg,plan,journal['operator'])
    locks = (state/'writer.lock',transaction.policy_path.parent/'writer.lock')
    need(all(p.is_file() and not p.is_symlink() for p in locks),'verification_lock_missing')
    with exclusive(locks[0]), exclusive(locks[1]):
        need(binding._json(state/JOURNAL) == journal and journal.get('status') == 'complete',
             'transition_journal_changed')
        with _read_snapshot(state/'study2.sqlite') as main, _read_snapshot(state/'review.sqlite'), binding._locked_registry(transaction.registry) as (metadata, ledger):
            transaction.main_db = main
            transaction.validate_inputs()
            inventory = binding._current_inventory(cfg)
            actual = inventory.release_id
            need(actual in {plan['old_release_id'],plan['target_release_id']},'unexpected_publication_during_recovery')
            side = 'old' if actual == plan['old_release_id'] else 'target'
            _, _, selection = _options(cfg)
            pointers = {transaction.policy_path:plan[side+'_policy'],
                        state/'CURRENT_REVIEW_DISPOSITION.json':plan[side+'_workload'],
                        selection:plan[side+'_selection']}
            need(all(binding._json(path) == value for path,value in pointers.items()),'completed_transition_tuple_changed')
            manifest = binding._validate(cfg,transaction.control/'control.json',transaction.policy_path,
                                         transaction.descriptor,inventory,metadata,ledger)
            need(str(manifest) == plan[side+'_manifest'],'completed_transition_manifest_changed')
            binding._require_current_workload(cfg,inventory,manifest,staged_pointer=plan[side+'_workload'])
            derived = binding._json(Path(cfg['release_dir'])/'CURRENT.json')
            row = main.execute('SELECT path FROM releases WHERE release_id=?',(actual,)).fetchone()
            locations = state/'release_locations.json'
            expected_path = binding._json(locations).get(actual,row[0]) if locations.is_file() else row[0]
            need(derived.get('release_id') == actual and derived.get('path') == expected_path,
                 'completed_transition_derived_pointer_changed')
            transaction.validate_inputs()
            need(binding._json(state/JOURNAL) == journal and
                 all(binding._json(path) == value for path,value in pointers.items()),'completed_transition_tuple_changed')
            return {'status':'complete','idempotent':True,'verified_side':side,'read_only':True}


def recover(cfg, *, owner_fence=None, fault=None):
    """Completed verification is read-only; repair requires genuine owned controls."""
    state = Path(cfg['state_dir']).resolve()
    path = state/JOURNAL
    need(path.is_file() and not path.is_symlink(),'transition_journal_required')
    journal = json.loads(path.read_text())
    if journal.get('status') == 'complete':
        return _verify_completed(cfg,journal)
    _owner_control(owner_fence)
    need(journal.get('status') in {'draining', 'pending'}, 'transition_journal_status_invalid')
    plan = _load_plan(cfg, journal['plan_pin'], journal['acceptance_pin'], journal['operator'])
    need(plan['revision'] == journal['plan_revision'], 'transition_journal_plan_changed')
    owner_fence.check_recovery_ready(cfg, plan)
    with exclusive(state/'consumer-maintenance.lock'):
        need(json.loads(path.read_text()) == journal, 'transition_journal_changed')
        owner_fence.check_recovery_ready(cfg, plan)
        with owner_fence.fence(fault=fault) as permit:
            return _recover_fenced(cfg, owner_fence=owner_fence,
                owner_permit=permit, fault=fault)
