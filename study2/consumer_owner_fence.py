"""Actual Popen ownership, the reviewed native start gate and a native lock.

This controls only children this session starts. It cannot adopt a PID, tool
session, launchd job or an alleged JSON termination receipt. Public admission
must use this actual object and its held lease. Nothing runs on import.
"""
from contextlib import contextmanager
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import signal
import stat
import subprocess
import time

CODE_ROOT = Path(__file__).resolve().parent.parent
ENTRY_SHA256 = hashlib.sha256((CODE_ROOT / 'local_update_entry.py').read_bytes()).hexdigest()


class OwnerFenceError(RuntimeError):
    pass


def need(ok, code):
    if not ok:
        raise OwnerFenceError(code)


def resident_file(path):
    path = Path(path)
    value = path.lstat()
    need(stat.S_ISREG(value.st_mode) and not (getattr(value, 'st_flags', 0) & 0x40000000),
         'resident_regular_owner_input_required')
    return path


def read_json(path):
    return json.loads(resident_file(path).read_bytes())


def check_pin(pin):
    need(isinstance(pin, dict) and set(pin) == {'path', 'sha256'}, 'owner_input_pin_required')
    data = resident_file(pin['path']).read_bytes()
    need(hashlib.sha256(data).hexdigest() == pin['sha256'], 'owner_input_changed')


def check_guarded_runtime(plan):
    root=Path(__file__).resolve().parent.parent
    for rel,expected in ScopedEmptyFence.GUARDS.items():
        path=root/rel
        matches=[p for p in plan['input_pins'] if p['path']==str(path)]
        need(len(matches)==1 and matches[0]['sha256']==expected,
             'reviewed_guarded_runtime_required')
        check_pin(matches[0])


def empty_recovery_request(cfg,inventory_pin):
    """Describe current owned-session recovery for independent review; no writes."""
    from study2.coordinated_update import _load_plan
    path=Path(cfg['state_dir'])/'COORDINATED_UPDATE.json'
    journal=read_json(path)
    need(journal.get('status') in {'draining','pending'},'pending_recovery_required')
    plan=_load_plan(cfg,journal['plan_pin'],journal['acceptance_pin'],journal['operator'])
    need(plan['consumer_owner_scope'].get('format')=='study2_owned_consumer_scope_v1' and
         journal['plan_revision']==plan['revision'],'original_owned_scope_required')
    return {'format':'study2_empty_session_recovery_v1','plan_revision':plan['revision'],
            'journal_sha256':hashlib.sha256(resident_file(path).read_bytes()).hexdigest(),
            'inventory_pin':deepcopy(inventory_pin)}


class OwnedConsumerFence:
    """Bind actual controlled owners to an independently reviewable plan scope.

    consumer_owner_scope must be included in the exact publication plan before
    independent review. Its owner inventory still needs real operational
    verification; constructing this class does not prove inventory completeness.
    """
    def __init__(self, cfg, plan):
        from study2.coordinated_update import sha
        need(plan.get('format') == 'study2_coordinated_publication_plan_v1' and
             plan.get('revision') == sha({k: v for k, v in plan.items() if k != 'revision'}),
             'owner_plan_revision_invalid')
        self.plan = deepcopy(plan)
        self.state = Path(cfg['state_dir']).resolve()
        self.selection = Path(cfg['coordinated_update']['selection_path']).absolute()
        scope = plan.get('consumer_owner_scope')
        need(isinstance(scope, dict) and set(scope) == {'format', 'state_dir', 'selection_path', 'owners'}
             and scope['format'] == 'study2_owned_consumer_scope_v1'
             and Path(scope['state_dir']).resolve() == self.state
             and Path(scope['selection_path']).absolute() == self.selection,
             'exact_reviewed_owner_scope_required')
        need(isinstance(scope['owners'], dict) and bool(scope['owners']), 'actual_owner_coverage_required')
        self.specs = deepcopy(scope['owners'])
        self.entry = Path(plan['old_selection']['entry'])
        need(plan['target_selection']['entry'] == str(self.entry) and
             plan['gate_selection'] == {**plan['old_selection'], 'coordinated_update_gate': True},
             'supported_owner_gate_required')
        self._processes = {}
        self._lease = None
        self._closed = False
        self._check_sources()
        selected = read_json(self.selection)
        need(selected in [plan['old_selection'], plan['gate_selection'], plan['target_selection']],
             'owner_selection_changed')
        self._closed = selected != plan['old_selection']

    def _check_sources(self):
        need(hashlib.sha256(resident_file(self.entry).read_bytes()).hexdigest() == ENTRY_SHA256,
             'reviewed_gate_entry_required')
        entry_pins = [p for p in self.plan['input_pins'] if p['path'] == str(self.entry)]
        need(len(entry_pins) == 1 and entry_pins[0]['sha256'] == ENTRY_SHA256,
             'reviewed_gate_entry_pin_required')
        for spec in self.specs.values():
            need(isinstance(spec, dict) and set(spec) == {'kind', 'argv', 'input_pins'}
                 and spec['kind'] == 'owned_popen' and isinstance(spec['argv'], list)
                 and spec['argv'] and all(isinstance(x, str) and x for x in spec['argv'])
                 and isinstance(spec['input_pins'], list) and bool(spec['input_pins']),
                 'supported_owned_process_spec_required')
            args = spec['argv']
            need(str(self.entry) in args and '--activation' in args and
                 args.index('--activation') + 1 < len(args) and
                 args[args.index('--activation') + 1] == str(self.selection),
                 'owned_process_must_use_selected_gate')
            for pin in spec['input_pins']:
                need(Path(pin['path']).absolute() != self.selection, 'gate_is_not_an_immutable_input')
                check_pin(pin)

    def start(self, owner):
        need(not self._closed and self._lease is None and owner in self.specs
             and owner not in self._processes, 'owned_start_not_available')
        self._check_sources()
        need(read_json(self.selection) == self.plan['old_selection'], 'owner_start_gate_closed')
        journal = self.state / 'COORDINATED_UPDATE.json'
        if journal.exists():
            need(read_json(journal).get('status') == 'complete', 'owner_start_gate_closed')
        # Keep stdout free for reviewed-session JSON replies. Child diagnostics
        # inherit stderr instead of filling pipes that the owner never drains.
        process = subprocess.Popen(self.specs[owner]['argv'], cwd=self.state,
                                   stdin=subprocess.PIPE, stdout=2,
                                   stderr=None, text=True,
                                   start_new_session=True)
        self._processes[owner] = process
        return process

    def _coverage(self, *, stopped):
        need(set(self._processes) == set(self.specs), 'actual_owner_handles_missing')
        need(all(type(p) is subprocess.Popen for p in self._processes.values()),
             'actual_owned_process_handles_required')
        if stopped:
            need(all(p.poll() is not None for p in self._processes.values()),
                 'actual_owned_process_exit_required')
            need(all(not self._group_alive(p) for p in self._processes.values()),
                 'actual_owned_process_group_exit_required')

    @staticmethod
    def _group_alive(process):
        # Probe only a process group this exact Popen created with setsid.
        try:
            os.killpg(process.pid, 0)
        except ProcessLookupError:
            return False
        return True

    def _scope(self, cfg, plan):
        need(plan == self.plan and Path(cfg['state_dir']).resolve() == self.state and
             Path(cfg['coordinated_update']['selection_path']).absolute() == self.selection,
             'owner_lease_scope_changed')
        from study2.coordinated_update import _require_control_binding
        _require_control_binding(cfg, plan)

    def _scope_config(self):
        return {'state_dir': str(self.state),
                'coordinated_update': {'selection_path': str(self.selection)}}

    def _journal(self, *, active):
        value = read_json(self.state / 'COORDINATED_UPDATE.json')
        allowed = {'draining', 'pending'} if active else {'draining', 'pending', 'complete'}
        need(value.get('format') == 'study2_coordinated_publication_journal_v1' and
             value.get('plan_revision') == self.plan['revision'] and value.get('status') in allowed,
             'owner_transition_journal_required')
        return value

    def check_publish_ready(self, cfg, plan):
        self._scope(cfg, plan)
        self._check_sources()
        self._coverage(stopped=False)
        need(read_json(self.selection) == self.plan['old_selection'], 'owner_selection_changed')

    def check_recovery_ready(self, cfg, plan):
        self._scope(cfg, plan)
        self._check_sources()
        self._coverage(stopped=False)
        self._journal(active=True)
        need(read_json(self.selection) in [self.plan['old_selection'], self.plan['gate_selection'],
             self.plan['target_selection']], 'owner_selection_changed')

    def _stop_owned(self, process, timeout):
        deadline = time.monotonic() + timeout
        if process.poll() is None:
            # The still-owned parent anchors this group. Never signal a group
            # inferred from an old PID after the owning parent has exited.
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        process.wait(timeout=max(0, deadline - time.monotonic()))
        while self._group_alive(process) and time.monotonic() < deadline:
            time.sleep(0.01)
        need(not self._group_alive(process), 'actual_owned_process_group_exit_required')

    @contextmanager
    def fence(self, *, timeout=5, fault=None):
        from study2.coordinated_update import _durable
        from study2.owned_locks import exclusive
        need(self._lease is None, 'owner_session_already_used')
        self._scope(self._scope_config(), self.plan)
        self._coverage(stopped=False)
        self._check_sources()
        self._journal(active=True)
        selected = read_json(self.selection)
        need(selected in [self.plan['old_selection'], self.plan['gate_selection'],
                          self.plan['target_selection']], 'owner_selection_changed')
        # The real selected entry refuses new starts before old owners stop.
        if selected != self.plan['gate_selection']:
            _durable(self.selection, self.plan['gate_selection'], fault, 'owner_gate')
        self._closed = True
        for process in self._processes.values():
            self._stop_owned(process, timeout)
        self._coverage(stopped=True)
        with exclusive(self.state / 'writer.lock'):
            permit = object()
            self._lease = permit
            try:
                self.assert_closed(permit, self._scope_config(), self.plan)
                yield permit
            finally:
                self._lease = None
        # No automatic reopen. Only validated native tuple installation may do that.

    def assert_live(self, permit, cfg, plan):
        from study2.owned_locks import assert_owned
        need(permit is not None and permit is self._lease, 'actual_owner_lease_required')
        self._scope(cfg, plan)
        self._coverage(stopped=True)
        self._check_sources()
        self._journal(active=False)
        assert_owned(self.state / 'writer.lock')

    def assert_closed(self, permit, cfg, plan):
        self.assert_live(permit, cfg, plan)
        need(read_json(self.selection) == self.plan['gate_selection'], 'owner_start_gate_changed')

    def cleanup_owned(self):
        for process in self._processes.values():
            if type(process) is subprocess.Popen and process.poll() is None:
                self._stop_owned(process, 5)
            for stream in (process.stdin, process.stdout, process.stderr):
                if stream is not None:
                    stream.close()


class ScopedEmptyFence(OwnedConsumerFence):
    """Reviewed bounded inventory plus real guarded-reader/SQLite exclusion.

    This attests only to declared project activities. It never asserts global
    process absence, adopts a process, signals a service or creates a canary.
    Inventory evidence alone is insufficient: the actual native EX state lease
    and the publisher's native group/SQLite fences are still mandatory.
    """
    # Reviewed plans pin the actual installed code. A code edit invalidates the
    # plan; release-specific binary hashes do not belong inside reusable source.
    GUARDS = {name: hashlib.sha256((CODE_ROOT/name).read_bytes()).hexdigest()
              for name in ('study2/reviewed_switch_entry.py', 'local_update_entry.py',
                           'study2/entrypoint.py', 'study2/compatibility_profiles.py',
                           'dashboard.py', 'study2/flag_binding.py', 'study2/static_export.py')}
    EXCLUDED_ENTRIES = {
        '5f7bc64fbb46be5f8daaa3cfa99116f86efbbfc01a55342320a738ae632aeb93',
        '8bef33766528796ea0ff854267d81638a3123f208e97c7d5377fe265bac9b0a6',
        '5b84e4bef53dafe212ffa30dcc75971eeb5be7842cb978206ac606f42bfb398d',
        '9c9e02ffadea28c2a54a95e3e532e18d907776b8349e282de4c40fc9053045bb',
        ENTRY_SHA256,
    }

    def __init__(self, cfg, plan, *, recovery=None):
        from study2.coordinated_update import sha
        need(plan.get('format') == 'study2_coordinated_publication_plan_v1' and
             plan.get('revision') == sha({k:v for k,v in plan.items() if k != 'revision'}),
             'owner_plan_revision_invalid')
        self._cfg = deepcopy(cfg)
        self.plan = deepcopy(plan)
        self.state = Path(cfg['state_dir']).resolve()
        self.release = Path(cfg['release_dir']).resolve()
        self.selection = Path(cfg['coordinated_update']['selection_path']).absolute()
        self._recovery=deepcopy(recovery)
        scope = plan.get('consumer_owner_scope')
        if recovery is None:
            need(isinstance(scope, dict) and set(scope) == {'format','state_dir','selection_path','inventory_pin'}
                 and scope['format'] == 'study2_bounded_empty_owner_scope_v1'
                 and Path(scope['state_dir']).resolve() == self.state
                 and Path(scope['selection_path']).absolute() == self.selection,
                 'reviewed_empty_owner_scope_required')
            self.inventory_pin = deepcopy(scope['inventory_pin'])
        else:
            need(isinstance(scope,dict) and scope.get('format')=='study2_owned_consumer_scope_v1'
                 and isinstance(scope.get('owners'),dict) and scope['owners']
                 and Path(scope['state_dir']).resolve()==self.state
                 and Path(scope['selection_path']).absolute()==self.selection,'original_owned_scope_required')
            self.inventory_pin=deepcopy(self._checked_recovery()['inventory_pin'])
        self.entry = Path(plan['old_selection']['entry'])
        need(plan['target_selection']['entry'] == str(self.entry) and
             self.entry.resolve() == Path(__file__).resolve().parent.parent/'local_update_entry.py'
             and plan['gate_selection'] == {**plan['old_selection'],'coordinated_update_gate':True},
             'supported_owner_gate_required')
        self.specs = {}; self._processes = {}; self._lease = None
        self._database_ids = None
        self._directory_ids = None
        self._check_sources()
        selected = read_json(self.selection)
        need(selected in [plan['old_selection'],plan['gate_selection'],plan['target_selection']],
             'owner_selection_changed')
        self._closed = selected != plan['old_selection']

    def _scope_config(self):
        return self._cfg

    def _checked_recovery(self):
        from study2.coordinated_update import _acceptance, _load_plan, sha
        need(isinstance(self._recovery,dict) and set(self._recovery)=={'request_pin','acceptance_pin'},
             'independent_empty_recovery_required')
        path=self.state/'COORDINATED_UPDATE.json';journal=read_json(path)
        request=self._trusted_document(self._recovery['request_pin'])
        need(isinstance(request,dict) and set(request)=={'format','plan_revision','journal_sha256','inventory_pin'}
             and request['format']=='study2_empty_session_recovery_v1'
             and journal.get('status') in {'draining','pending'}
             and request['journal_sha256']==hashlib.sha256(resident_file(path).read_bytes()).hexdigest()
             and request['plan_revision']==journal['plan_revision']==self.plan['revision'],
             'recovery_journal_or_scope_changed')
        accepted=_load_plan(self._cfg,journal['plan_pin'],journal['acceptance_pin'],journal['operator'])
        need(accepted==self.plan,'recovery_original_plan_changed')
        _acceptance(self._cfg,self._recovery['acceptance_pin'],kind='empty_session_recovery',
                    subject=sha(request),operator=journal['operator'])
        return request

    def check_publish_ready(self,cfg,plan):
        need(self._recovery is None,'recovery_scope_cannot_publish')
        super().check_publish_ready(cfg,plan)

    def _scope(self, cfg, plan):
        super()._scope(cfg, plan)
        need(Path(cfg['release_dir']).resolve() == self.release and
             cfg['coordinated_update'] == self._cfg['coordinated_update'],
             'empty_scope_configuration_changed')

    def _trusted_document(self, pin):
        from study2.coordinated_update import _trusted_pin
        resident_file(pin['path'])
        return _trusted_pin(self._cfg, pin)

    @staticmethod
    def _document(pin):
        check_pin(pin)
        return read_json(pin['path'])

    @staticmethod
    def _directory(value):
        need(isinstance(value, str) and Path(value).is_absolute(), 'inventory_absolute_resource_required')
        path = Path(value)
        need(path.is_dir() and not path.is_symlink(), 'inventory_resource_directory_required')
        return path.resolve()

    def _exclude_runtime(self, record, target_dirs):
        need(isinstance(record, dict) and set(record) == {
            'selection_pin','configuration_pin','canonical_configuration_pin','entry_pin'},
            'excluded_runtime_evidence_required')
        selection = self._document(record['selection_pin'])
        config = self._document(record['configuration_pin'])
        canonical = self._document(record['canonical_configuration_pin'])
        check_pin(record['entry_pin'])
        need(record['entry_pin']['sha256'] in self.EXCLUDED_ENTRIES and
             selection.get('enabled') is True and selection.get('entry') == record['entry_pin']['path']
             and selection.get('config') == record['configuration_pin']['path']
             and selection.get('canonical_config') == record['canonical_configuration_pin']['path']
             and selection.get('canonical_config_sha256') == record['canonical_configuration_pin']['sha256']
             and selection.get('state_dir') == config.get('state_dir'),
             'excluded_runtime_binding_changed')
        environment = selection.get('environment', {})
        directories = [self._directory(config['state_dir']), self._directory(config['release_dir']),
                       self._directory(canonical['state_dir']), self._directory(canonical['release_dir'])]
        for key in ('STUDY2_FLAG_CONTROL','STUDY2_GROUP_POLICY_POINTER'):
            value = environment.get(key)
            need(isinstance(value, str) and Path(value).is_absolute(), 'excluded_control_resource_required')
            directories.append(self._directory(str(Path(value).parent)))
        for excluded in directories:
            for target in target_dirs:
                need(not (excluded == target or excluded in target.parents or target in excluded.parents),
                     'excluded_runtime_overlaps_target')
        leaves = [Path(config['state_dir'])/'study2.sqlite', Path(config['state_dir'])/'review.sqlite',
                  Path(canonical['state_dir'])/'study2.sqlite', Path(canonical['state_dir'])/'review.sqlite',
                  Path(environment['STUDY2_FLAG_CONTROL']).parent/'registry.sqlite3',
                  Path(environment['STUDY2_FLAG_CONTROL']), Path(environment['STUDY2_GROUP_POLICY_POINTER']),
                  Path(config['release_dir'])/'CURRENT.json', Path(canonical['release_dir'])/'CURRENT.json',
                  Path(config['state_dir'])/'CURRENT_REVIEW_DISPOSITION.json']
        controls = [self.selection, self.release/'CURRENT.json',
                    self.state/'CURRENT_REVIEW_DISPOSITION.json',
                    Path(self.plan['old_selection']['environment']['STUDY2_FLAG_CONTROL']),
                    Path(self.plan['old_selection']['environment']['STUDY2_GROUP_POLICY_POINTER'])]
        target_ids = set(self._database_ids.values())
        for path in controls:
            value = resident_file(path).stat()
            need(value.st_nlink == 1, 'target_control_has_aliases')
            target_ids.add((value.st_dev,value.st_ino))
        for path in leaves:
            if path.exists() or path.is_symlink():
                try:
                    value = path.stat()
                except OSError:
                    raise OwnerFenceError('excluded_database_metadata_unavailable') from None
                need(stat.S_ISREG(value.st_mode), 'excluded_database_metadata_required')
                need((value.st_dev,value.st_ino) not in target_ids,
                     'excluded_runtime_overlaps_target')
        need(Path(record['selection_pin']['path']).resolve() != self.selection.resolve(),
             'excluded_runtime_overlaps_target')

    def _target_identity(self, directories):
        control = Path(self.plan['old_selection']['environment']['STUDY2_FLAG_CONTROL'])
        paths = {'main':self.state/'study2.sqlite','review':self.state/'review.sqlite',
                 'flags':control.parent/'registry.sqlite3'}
        identities = {}
        for name,path in paths.items():
            value = resident_file(path).stat()
            need(value.st_nlink == 1, 'target_database_has_aliases')
            identities[name] = (value.st_dev,value.st_ino)
        need(len(set(identities.values())) == len(paths), 'target_database_has_aliases')
        dirs = {}
        for path in directories:
            value = path.stat()
            dirs[str(path)] = (value.st_dev,value.st_ino)
        if self._database_ids is None:
            self._database_ids, self._directory_ids = identities, dirs
        need(identities == self._database_ids and dirs == self._directory_ids,
             'target_resource_identity_changed')

    def _check_sources(self):
        check_guarded_runtime(self.plan)
        if self._recovery is not None:
            need(self._checked_recovery()['inventory_pin']==self.inventory_pin,'recovery_inventory_changed')
        document = self._trusted_document(self.inventory_pin)
        need(isinstance(document, dict) and set(document) == {
             'format','scope','state_dir','release_dir','selection_path','declared_participants',
             'active_target_consumers','observation_pins','excluded_runtimes'}
             and document['format'] == 'study2_bounded_consumer_inventory_v1'
             and document['scope'] == 'declared_project_target_activities_only'
             and Path(document['state_dir']).resolve() == self.state
             and Path(document['release_dir']).resolve() == self.release
             and Path(document['selection_path']).absolute() == self.selection,
             'bounded_inventory_required')
        need(document['active_target_consumers'] == [] and
             isinstance(document['active_target_consumers'], list), 'known_target_consumers_not_empty')
        declared = document['declared_participants']
        observations = document['observation_pins']
        need(isinstance(declared,list) and declared and len(set(declared)) == len(declared)
             and all(isinstance(x,str) and x for x in declared)
             and isinstance(observations,list) and observations, 'bounded_activity_evidence_required')
        seen = set();exited=set()
        for pin in observations:
            item = self._trusted_document(pin)
            need(item.get('format') == 'study2_target_activity_observation_v1'
                 and item.get('scope') == 'target_state_only'
                 and Path(item['state_dir']).resolve() == self.state
                 and item.get('participant') in declared
                 and item.get('process_state') in {'not_started','exited'},
                 'target_activity_not_quiescent')
            if item['process_state'] == 'exited':
                need(isinstance(item.get('session_id'),str) and item['session_id'] and
                     type(item.get('exit_code')) is int, 'observed_target_exit_required')
                exited.add(item['participant'])
            else:
                need(item.get('session_id') is None and item.get('exit_code') is None,
                     'bounded_not_started_evidence_required')
            seen.add(item['participant'])
        need(seen == set(declared), 'bounded_participant_coverage_incomplete')
        if self._recovery is not None:
            required={'owner:'+name for name in self.plan['consumer_owner_scope']['owners']}
            need(required<=exited,'original_owned_reader_exit_coverage_required')
        environment = self.plan['old_selection']['environment']
        targets = [self._directory(str(self.state)), self._directory(str(self.release)),
            self._directory(str(Path(environment['STUDY2_FLAG_CONTROL']).parent)),
            self._directory(str(Path(environment['STUDY2_GROUP_POLICY_POINTER']).parent))]
        self._target_identity(targets)
        excluded = document['excluded_runtimes']
        need(isinstance(excluded,list) and excluded, 'excluded_project_runtime_evidence_required')
        for record in excluded:
            self._exclude_runtime(record, targets)

    def _coverage(self, *, stopped):
        need(self._processes == {}, 'empty_scope_must_not_own_consumers')
        self._check_sources()

    def _journal(self, *, active):
        from study2.coordinated_update import _load_plan
        value = super()._journal(active=active)
        accepted = _load_plan(self._cfg, value['plan_pin'], value['acceptance_pin'], value['operator'])
        need(accepted == self.plan, 'empty_scope_approved_journal_required')
        return value


def require_publication_fence(owner, permit, cfg, plan):
    """Admission check for a future reviewed public integration; never publishes."""
    need(type(owner) in (OwnedConsumerFence, ScopedEmptyFence), 'actual_consumer_owner_fence_required')
    owner.assert_closed(permit, cfg, plan)


def require_live_publication_fence(owner, permit, cfg, plan):
    """Keep actual handle/lock ownership checked after native tuple installation."""
    need(type(owner) in (OwnedConsumerFence, ScopedEmptyFence), 'actual_consumer_owner_fence_required')
    owner.assert_live(permit, cfg, plan)
