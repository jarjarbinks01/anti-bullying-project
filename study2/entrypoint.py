"""One public CLI boundary for module, console script and selected local entry.

Machine bindings belong to ignored local configuration. Importing this module
never opens state or starts an update. Internal scientific CLI stays separate.
"""
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import sys

from .common import PipelineError

ROOT = Path(__file__).resolve().parent.parent
ENTRY = ROOT / 'local_update_entry.py'
ENVIRONMENT_PATHS = frozenset({
    'STUDY2_CURRENT_REVIEW_WORKLOAD', 'STUDY2_FLAG_CONTROL',
    'STUDY2_GROUP_POLICY_POINTER', 'STUDY2_MANUAL_EXCLUSION_MANIFEST',
    'STUDY2_REVIEW_STATE_DIR',
})
HOUSEKEEPING_COMMANDS = frozenset({
    'init', 'manifest', 'run', 'watch', 'validate', 'review-export', 'review-import',
    'review-cards', 'review-evidence-add', 'review-receive', 'review-preview',
    'review-approve', 'review-apply', 'review-resolve', 'review-reopen',
    'review-report', 'review-console', 'review-queue', 'review-waiting-export',
    'dyad-console', 'dyad-preview', 'dyad-report', 'dyad-invitations',
    'dyad-record-invitation', 'dyad-adjudicate', 'dyad-backup', 'dyad-restore',
    'publish', 'rollback', 'restore', 'status', 'storage-report', 'storage-migrate',
    'storage-gc', 'checkpoint', 'checkpoint-restore', 'schedule',
})
REVIEWED_COMMANDS = frozenset({'reviewed-publish', 'reviewed-recover', 'reviewed-session'})


def split_arguments(arguments):
    """Separate global configuration once; reject conflicting repeated options."""
    args, paths, runtime_info = list(arguments), [], False
    while args and args[0].startswith('-'):
        item = args.pop(0)
        if item == '--config':
            if not args or args[0].startswith('-'):
                raise SystemExit('--config requires a path')
            paths.append(Path(args.pop(0)).expanduser().resolve())
        elif item.startswith('--config='):
            if not item.split('=', 1)[1]:
                raise SystemExit('--config requires a path')
            paths.append(Path(item.split('=', 1)[1]).expanduser().resolve())
        elif item == '--runtime-info':
            runtime_info = True
        elif item in {'--help', '-h'}:
            return (paths[-1] if paths else ROOT / 'config.local.json'), [item, *args], runtime_info
        else:
            raise SystemExit('Unknown global option; use --config, --runtime-info or --help')
    if paths and any(p != paths[0] for p in paths):
        raise SystemExit('Conflicting repeated --config arguments')
    return (paths[0] if paths else ROOT / 'config.local.json'), args, runtime_info


def prepare_activation(arguments):
    """Validate a local selector without importing science or mutating state."""
    args = list(arguments)
    if len(args) < 2 or args[0] != '--activation':
        raise SystemExit('An explicit local activation file is required')
    pointer = Path(args[1]).expanduser()
    if pointer.is_symlink() or not pointer.is_file():
        raise SystemExit('Local activation must be a regular selector file')
    pointer = pointer.resolve()
    active = json.loads(pointer.read_text())
    if Path(active['entry']).resolve() != ENTRY:
        raise SystemExit('Selection belongs to a different code installation; activation is a separate step')
    # Legacy recovery selectors omitted enabled; an explicit disable still wins.
    if active.get('enabled', True) is not True:
        raise SystemExit('Selected runtime is disabled')
    command = args[2:]
    recovery = bool(command and command[0] == 'reviewed-recover')
    if active.get('coordinated_update_gate') is True and not recovery:
        raise SystemExit('Reviewed dashboard transition is in progress; use reviewed-recover')
    canonical = Path(active['canonical_config'])
    if hashlib.sha256(canonical.read_bytes()).hexdigest() != active['canonical_config_sha256']:
        raise SystemExit('Canonical configuration changed; refresh the selected local configuration')
    cfg = json.loads(Path(active['config']).read_text())
    if cfg.get('recovery_policy', {}).get('mode') != 'lean':
        raise SystemExit('Selected configuration does not enable lean recovery')
    if cfg['state_dir'] != active['state_dir']:
        raise SystemExit('Selected configuration changed the canonical state directory')
    selected = cfg.get('coordinated_update', {}).get('selection_path')
    if selected and Path(selected).resolve() != pointer:
        raise SystemExit('Configuration and selection point to different transitions')
    journal = Path(cfg['state_dir']) / 'COORDINATED_UPDATE.json'
    if journal.exists():
        if journal.is_symlink() or not journal.is_file():
            raise SystemExit('Reviewed dashboard journal is unavailable')
        if json.loads(journal.read_text()).get('status') in {'draining', 'pending'} and not recovery:
            raise SystemExit('Reviewed dashboard transition requires recovery')
    return active, cfg, command


@contextmanager
def configured_environment(cfg, active=None):
    values = dict(cfg.get('runtime_environment', {}))
    if active is not None:
        values.update(active.get('environment', {}))
    if not set(values).issubset(ENVIRONMENT_PATHS) or not all(isinstance(v, str) for v in values.values()):
        raise SystemExit('Local runtime_environment contains unsupported names or non-string values')
    saved = {key: os.environ.get(key) for key in ENVIRONMENT_PATHS}
    try:
        os.environ.update(values)
        compatibility = cfg.get('compatibility')
        if compatibility is not None:
            if not isinstance(compatibility, dict) or set(compatibility) != {'profile_path', 'profile_sha256'}:
                raise SystemExit('compatibility requires profile_path and profile_sha256')
            from .compatibility_profiles import configure_trust
            configure_trust(compatibility['profile_path'], compatibility['profile_sha256'])
        yield
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def _legacy_cli(config_path, arguments):
    from .cli import main as native_main
    previous = sys.argv
    try:
        sys.argv = ['study2', '--config', str(config_path), *arguments]
        return native_main()
    finally:
        sys.argv = previous


def dispatch(config_path, cfg, arguments, *, active=None, runtime_info=False):
    command = arguments[0] if arguments else ''
    with configured_environment(cfg, active):
        if command in REVIEWED_COMMANDS:
            from .reviewed_switch_entry import run
            return run(cfg, arguments)
        from .coordinated_update import require_available
        require_available(Path(cfg['state_dir']))
        if command in HOUSEKEEPING_COMMANDS and not runtime_info:
            from .journal_retirement import retire_if_complete
            retire_if_complete(cfg)
        from .flag_binding import MANIFEST_ENV, resolve_current
        bound = resolve_current(cfg)
        if bound is not None:
            os.environ[MANIFEST_ENV] = str(bound)
            from .lean_recovery import recovery_assets
            recovery_assets(cfg)
        if runtime_info:
            from .lean_recovery import enabled
            print(json.dumps({'runtime': str(ROOT), 'runner': str(ROOT/'study2/runner.py'),
                'config': str(config_path), 'state_dir': cfg['state_dir'],
                'lean_recovery': enabled(cfg), 'command': arguments,
                'update_executed': False, 'checkpoint_executed': False}, indent=2))
            return
        if command == 'static-export':
            from .static_export import main as export_main
            return export_main(['--config', str(config_path), *arguments[1:]])
        if command == 'controls-capture':
            from .controls_capture import main as capture_main
            return capture_main(arguments[1:], config_path=config_path)
        if command == 'dashboard':
            from .formal_dashboard import main as dashboard_main
            dashboard_main(cfg, config_path, argv=arguments[1:])
            return 0
        if command == 'review-prepare':
            from .review_preparation import main as review_main
            return review_main(['--config', str(config_path), *arguments[1:]])
        return _legacy_cli(config_path, arguments)


def main(argv=None):
    arguments = list(sys.argv[1:] if argv is None else argv)
    try:
        if arguments[:1] == ['--activation']:
            active, cfg, args = prepare_activation(arguments)
            info = args[:1] == ['--runtime-info']
            return dispatch(Path(active['config']), cfg, args[1:] if info else args,
                            active=active, runtime_info=info)
        config, args, info = split_arguments(arguments)
        if args[:1] == ['controls-capture'] and args[1:] == ['--code-revision']:
            from .controls_capture import main as capture_main
            return capture_main(['--code-revision'])
        # Help and initialization must work on a fresh checkout without private data.
        if not info and (not args or any(x in {'--help', '-h'} for x in args)):
            if args and args[0] in REVIEWED_COMMANDS:
                if args[0] == 'reviewed-recover':
                    print('study2 [--config CONFIG] reviewed-recover [RECOVERY-PIN ACCEPTANCE-PIN]')
                else:
                    print('study2 [--config CONFIG] ' + args[0] + ' PLAN-PIN ACCEPTANCE-PIN OPERATOR')
                return 0
            if args[:1] == ['controls-capture']:
                from .controls_capture import main as capture_main
                return capture_main(['--help'])
            if args[:1] == ['static-export']:
                from .static_export import main as export_main
                return export_main(['--help'])
            if args[:1] == ['dashboard']:
                from .formal_dashboard import main as dashboard_main
                return dashboard_main(argv=['--help'])
            if args[:1] == ['review-prepare']:
                from .review_preparation import main as review_main
                return review_main(['--help'])
            return _legacy_cli(config, args or ['--help'])
        if args[:1] == ['init']:
            return _legacy_cli(config, args)
        from .common import load_config
        cfg = load_config(config)
        pointer = cfg.get('coordinated_update', {}).get('selection_path')
        adjacent = config.parent / '.study2-local-runtime.json'
        if pointer or adjacent.exists():
            active, selected, command = prepare_activation(['--activation', str(pointer or adjacent), *args])
            allowed = {Path(active['config']).resolve(), Path(active['canonical_config']).resolve()}
            if config.resolve() not in allowed:
                raise SystemExit('Configuration is outside the selected local runtime')
            return dispatch(Path(active['config']), selected, command, active=active, runtime_info=info)
        return dispatch(config, cfg, args, runtime_info=info)
    except (OSError, ValueError, KeyError, PipelineError) as error:
        raise SystemExit('Pipeline stopped: ' + str(error)) from None
