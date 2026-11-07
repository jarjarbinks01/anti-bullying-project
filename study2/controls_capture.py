"""Read-only current-control capture from the installed, explicitly pinned package."""
import hashlib
import json
import os
from pathlib import Path
import sys

from contextlib import contextmanager
from threading import RLock

_ENV_LOCK = RLock()


def code_revision():
    """Relocation-independent inventory of installed Python and browser sources."""
    root = Path(__file__).resolve().parent
    files = {}
    for path in sorted(root.rglob('*')):
        if path.suffix not in {'.py', '.js', '.mjs', '.css'} or '__pycache__' in path.parts:
            continue
        if not path.is_file() or path.is_symlink():
            raise ValueError('backend_code_not_resident')
        files[path.relative_to(root).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    return hashlib.sha256(json.dumps(files, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


@contextmanager
def selected_environment(selected, allowed):
    # Restore the caller's environment even when the read fails. No launcher
    # selector or persistent runtime binding is changed.
    with _ENV_LOCK:
        before = {key: os.environ.get(key) for key in allowed}
        try:
            for key in allowed:
                os.environ.pop(key, None)
            for key, value in selected['environment'].items():
                if key in allowed:
                    os.environ[key] = value
            yield
        finally:
            for key, value in before.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value



def read_pin(pin):
    if not isinstance(pin,dict) or set(pin)!={'path','sha256'}:raise ValueError('pin_required')
    path=Path(pin['path']);s=path.lstat()
    if not path.is_file() or any(p.is_symlink() for p in [path,*path.parents]) or getattr(s,'st_flags',0)&0x40000000:
        raise ValueError('resident_regular_source_required')
    data=path.read_bytes()
    if hashlib.sha256(data).hexdigest()!=pin['sha256']:raise ValueError('source_changed')
    return json.loads(data)


def validate_selection(request,cfg,selected):
    """Accept the actual launcher selector without asserting a transition."""
    if (selected.get('coordinated_update_gate') is True or selected['state_dir']!=cfg['state_dir']
        or selected['config']!=request['config']['path']):
        raise ValueError('selected_context_changed')
    coordinated=cfg.get('coordinated_update')
    if coordinated is not None:
        if coordinated['selection_path']!=request['selection']['path']:
            raise ValueError('selected_context_changed')
        return
    fields={'canonical_config','canonical_config_sha256','config','enabled','entry','environment','format_version','state_dir'}
    if set(selected)!=fields or type(selected['format_version']) is not int or selected['format_version']!=1 or selected['enabled'] is not True:
        raise ValueError('legacy_selection_shape_changed')
    canonical=Path(selected['canonical_config'])
    if Path(request['selection']['path'])!=canonical.parent/'.study2-local-runtime.json':
        raise ValueError('legacy_selection_authority_changed')
    original=read_pin({'path':str(canonical),'sha256':selected['canonical_config_sha256']})
    if original.get('state_dir')!=cfg['state_dir'] or original.get('coordinated_update') is not None:
        raise ValueError('legacy_canonical_configuration_changed')
    expected={'STUDY2_FLAG_CONTROL','STUDY2_GROUP_POLICY_POINTER','STUDY2_MANUAL_EXCLUSION_MANIFEST',
              'STUDY2_CURRENT_REVIEW_WORKLOAD','STUDY2_REVIEW_STATE_DIR'}
    if set(selected['environment'])!=expected or selected['environment']['STUDY2_REVIEW_STATE_DIR']!=cfg['state_dir']:
        raise ValueError('legacy_selection_environment_changed')


def capture(request,*,prepare_context=False):
    if not isinstance(request,dict) or set(request)!={'config','selection','context','candidate','code_revision'}:raise ValueError('closed_request_required')
    if request['code_revision'] != code_revision():
        raise ValueError('backend_code_changed')
    from study2 import flag_binding as guard, group_cleaning_operator as group, review_workload, group_intent_review
    from study2.administrative_carry_current import _ro,controls
    from study2.static_release_context import validate_release_context
    cfg,selected=(read_pin(request[k]) for k in ('config','selection'))
    if prepare_context:
        if request['context'] is not None or request['candidate'] is not None:raise ValueError('context_preparation_only')
        context=None
    else:
        context=read_pin(request['context']);validate_release_context(context)
    lock=Path(cfg['state_dir'])/'writer.lock'
    if not lock.is_file() or lock.is_symlink():raise ValueError('existing_reader_lock_required')
    validate_selection(request,cfg,selected)
    allowed={guard.CONTROL_ENV,guard.POLICY_ENV,guard.MANIFEST_ENV,'STUDY2_CURRENT_REVIEW_WORKLOAD','STUDY2_REVIEW_STATE_DIR'}
    from study2 import static_controls as contract
    with selected_environment(selected, allowed), guard.guarded_current(cfg) as manifest_path:
        if manifest_path is None:raise ValueError('managed_binding_required')
        manifest=guard._json(manifest_path);active=group.read_active(Path(os.environ[guard.POLICY_ENV]).parent)
        folder=Path(manifest_path).parent
        spam={r['submission_id'] for r in guard._json(folder/'spam.json')['entries']}
        policy={r['submission_id'] for r in guard._json(folder/'policy.json')['entries']}
        expected_flags=dict(manifest_revision=manifest['revision'],inventory_revision=manifest['inventory_revision'],
            eric_records=len(spam),group_records=len(policy),overlap_records=len(spam&policy),combined_records=len(spam|policy))
        db=_ro(Path(cfg['state_dir'])/'study2.sqlite')
        try:
            state=controls(db)
            if prepare_context:
                from study2.store import current
                release=current(db)
                if release is None or release['release_id']!=manifest['release_id']:raise ValueError('current_publication_changed')
                run=db.execute('SELECT fingerprint FROM runs WHERE run_id=?',(release['run_id'],)).fetchone()
                if run is None:raise ValueError('current_analytical_run_missing')
                summary=json.loads(release['stats_json'])
                if summary['release_id']!=release['release_id']:raise ValueError('current_summary_changed')
                context={'format':'study2_dashboard_release_context_v1','release_id':release['release_id'],
                    'run_id':release['run_id'],'run_fingerprint':run['fingerprint'],'program_hash':summary['program_hash'],
                    'group_control_head':active['pointer']['manifest_sha256'],
                    'group_proposal_revision':active['proposal']['revision'],
                    'group_implementation_revision':group.implementation_revision(),
                    'review_control_revision':state['main_revision'],'flags':expected_flags}
        finally:db.close()
        if (context['release_id']!=manifest['release_id'] or context['flags']!=expected_flags
            or context['review_control_revision']!=state['main_revision']
            or context['group_control_head']!=active['pointer']['manifest_sha256']
            or context['group_proposal_revision']!=active['proposal']['revision']
            or context['group_implementation_revision']!=group.implementation_revision()):raise ValueError('current_controls_changed')
        workload,_=review_workload.load_summary(release_id=context['release_id'],decision_revision=state['decision_revision'],
            exclusion_revision=manifest['revision'],cfg=cfg,review_state=cfg['state_dir'])
        w=workload.get('active_workload',workload['native_workload'])
        expected=dict(child_groups=w['remaining_open_group_scopes'],phone_groups=w['similarity_scopes'],held_groups=w['held_scopes'],
            correction_comparisons=w['field_correction_comparisons'],correction_bundles=workload['correction_bundles'],adult_comparisons=w['separate_adult_comparisons'])
        if prepare_context:
            from study2.analysis_eligibility import sha
            context['workload']=expected;context['revision']=sha(context);validate_release_context(context)
        if context['workload']!=expected:raise ValueError('current_workload_changed')
        model=None
        if request['candidate'] is not None:
            proposal=read_pin(request['candidate']);model=group_intent_review.review_model(proposal)
            native=proposal
            if proposal.get('format')=='study2_admin_carry_preview_v1':
                from study2.administrative_carry_preview import validate_preview
                native,_=validate_preview(proposal)
            if native['base']['main_revision']!=state['main_revision']:raise ValueError('candidate_controls_changed')
        block=workload.get('administrative_disposition') or {}
        applied=block['projection'] if block.get('carry_forward') else None
        result=contract.project(context,candidate_model=model,applied_projection=applied)
        # Request files are immutable inputs too, including the selected pointer.
        for key in ('config','selection'):read_pin(request[key])
        validate_selection(request,cfg,read_pin(request['selection']))
        if not prepare_context:read_pin(request['context'])
        if request['candidate'] is not None:read_pin(request['candidate'])
        if request['code_revision'] != code_revision():
            raise ValueError('backend_code_changed')
        if prepare_context:return {'context':context,'manifest':{'path':str(manifest_path),
            'sha256':hashlib.sha256(Path(manifest_path).read_bytes()).hexdigest()}}
        return result


def main(argv=None, *, config_path=None):
    import argparse
    parser = argparse.ArgumentParser(description='Read-only pinned current-control aggregates')
    parser.add_argument('request_pin', nargs='?', help='JSON object with request-file path and SHA-256')
    parser.add_argument('--prepare-current-context', action='store_true')
    parser.add_argument('--code-revision', action='store_true')
    args = parser.parse_args(argv)
    if args.code_revision:
        if args.request_pin or args.prepare_current_context:
            parser.error('--code-revision cannot be combined with capture')
        print(code_revision())
        return
    if not args.request_pin:
        parser.error('a pinned request is required')
    request = read_pin(json.loads(args.request_pin))
    if config_path is not None and Path(request['config']['path']).resolve() != Path(config_path).resolve():
        raise ValueError('request_configuration_differs_from_public_entry')
    print(json.dumps(capture(request, prepare_context=args.prepare_current_context),
                     sort_keys=True, separators=(',', ':')))


if __name__ == '__main__':
    main()
