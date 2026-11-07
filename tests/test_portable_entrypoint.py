"""Synthetic public-entry parity; never opens research state."""
import hashlib
import json
from pathlib import Path
import sys
import tomllib
from types import SimpleNamespace

import pytest

from study2 import entrypoint as entry


def save(path, value):
    path.write_text(json.dumps(value))
    return path


def selection(tmp_path):
    cfg = {'state_dir': str(tmp_path/'state'), 'recovery_policy': {'mode': 'lean'}}
    path = save(tmp_path/'config.json', cfg)
    pointer = save(tmp_path/'selection.json', {'entry': str(entry.ENTRY),
        'canonical_config': str(path), 'canonical_config_sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
        'config': str(path), 'state_dir': cfg['state_dir'], 'environment': {}, 'enabled': True})
    return pointer, path, cfg


def test_module_and_console_use_one_public_entry():
    root = Path(__file__).resolve().parents[1]
    project = tomllib.loads((root/'pyproject.toml').read_text())
    assert project['project']['scripts']['study2'] == 'study2.entrypoint:main'
    assert (root/'study2/__main__.py').read_text() == 'from .entrypoint import main\n\nmain()\n'
    assert 'prepare_activation as prepare' in (root/'local_update_entry.py').read_text()


def test_help_does_not_need_private_config(monkeypatch):
    called = []
    monkeypatch.setattr(entry, '_legacy_cli', lambda path, args: called.append(args))
    entry.main(['--config', '/not-a-local-config.json', '--help'])
    assert called == [['--help']]


def test_conflicting_config_arguments_are_not_silently_selected(tmp_path):
    with pytest.raises(SystemExit, match='Conflicting'):
        entry.split_arguments(['--config', str(tmp_path/'one'), '--config', str(tmp_path/'two'), 'run'])


def test_selected_gate_and_other_installation_fail_before_dispatch(tmp_path):
    pointer, _, _ = selection(tmp_path)
    active = json.loads(pointer.read_text())
    active['coordinated_update_gate'] = True
    save(pointer, active)
    with pytest.raises(SystemExit, match='transition'):
        entry.prepare_activation(['--activation', str(pointer), 'run'])
    entry.prepare_activation(['--activation', str(pointer), 'reviewed-recover'])
    active['entry'] = str(tmp_path/'other'/'local_update_entry.py')
    save(pointer, active)
    with pytest.raises(SystemExit, match='different code installation'):
        entry.prepare_activation(['--activation', str(pointer), 'reviewed-recover'])


def test_changed_canonical_configuration_is_rejected(tmp_path):
    pointer, config, _ = selection(tmp_path)
    config.write_text(config.read_text()+' ')
    with pytest.raises(SystemExit, match='Canonical configuration changed'):
        entry.prepare_activation(['--activation', str(pointer), 'watch'])


def test_explicit_config_honors_adjacent_selector(tmp_path, monkeypatch):
    pointer, config, cfg = selection(tmp_path)
    pointer.rename(tmp_path/'.study2-local-runtime.json')
    from study2 import common
    monkeypatch.setattr(common, 'load_config', lambda _: cfg)
    calls = []
    monkeypatch.setattr(entry, 'dispatch', lambda *a, **kw: calls.append((a, kw)))
    entry.main(['--config', str(config), 'status'])
    assert calls[0][0][2] == ['status']
    assert calls[0][1]['active']['entry'] == str(entry.ENTRY)


def test_environment_and_dynamic_manifest_are_restored(monkeypatch):
    name = 'STUDY2_MANUAL_EXCLUSION_MANIFEST'
    monkeypatch.delenv(name, raising=False)
    with entry.configured_environment({}):
        entry.os.environ[name] = 'synthetic-bound-manifest'
    assert name not in entry.os.environ


def test_trust_is_initialized_before_consumer_dispatch(monkeypatch, tmp_path):
    events = []
    from study2 import compatibility_profiles
    monkeypatch.setattr(compatibility_profiles, 'configure_trust', lambda *a: events.append('trust'))
    monkeypatch.setitem(sys.modules, 'study2.reviewed_switch_entry',
                        SimpleNamespace(run=lambda *a: events.append('consumer')))
    entry.dispatch(tmp_path/'cfg.json', {'compatibility': {'profile_path': str(tmp_path/'trust.json'),
                    'profile_sha256': 'a'*64}}, ['reviewed-recover'])
    assert events == ['trust', 'consumer']


def test_package_and_asset_boundaries_remain_default_deny():
    import importlib.util
    path = Path(__file__).resolve().parents[1]/'tools/repository_guard.py'
    spec = importlib.util.spec_from_file_location('portable_guard', path)
    guard = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(guard)
    assert guard.allowed_path('study2/presentation/descriptives.py')
    assert guard.allowed_path('study2/presentation/assets/app.js')
    assert not guard.allowed_path('study2/presentation/assets/participant.json')
    assert not guard.allowed_path('trusted-compatibility.private.json')


def test_dashboard_api_path_does_not_become_console_failure(monkeypatch, tmp_path):
    monkeypatch.setitem(sys.modules, 'study2.flag_binding', SimpleNamespace(
        MANIFEST_ENV='STUDY2_MANUAL_EXCLUSION_MANIFEST', resolve_current=lambda cfg: None))
    monkeypatch.setitem(sys.modules, 'study2.formal_dashboard', SimpleNamespace(
        main=lambda *a, **kw: tmp_path/'verified-site'))
    assert entry.dispatch(tmp_path/'cfg.json', {'state_dir': str(tmp_path/'state')},
                          ['dashboard', '--check']) == 0


@pytest.mark.parametrize('command', ['reviewed-publish', 'reviewed-session', 'reviewed-recover'])
def test_reviewed_help_needs_no_private_workspace(command, capsys):
    assert entry.main([command, '--help']) == 0
    assert command in capsys.readouterr().out


def test_controls_capture_uses_public_config_after_trust(monkeypatch, tmp_path):
    events = []
    cfg_path = tmp_path / 'config.json'
    from study2 import compatibility_profiles
    monkeypatch.setattr(compatibility_profiles, 'configure_trust', lambda *a: events.append('trust'))
    monkeypatch.setitem(sys.modules, 'study2.flag_binding', SimpleNamespace(
        MANIFEST_ENV='STUDY2_MANUAL_EXCLUSION_MANIFEST', resolve_current=lambda cfg: None))
    monkeypatch.setitem(sys.modules, 'study2.controls_capture', SimpleNamespace(
        main=lambda args, *, config_path: events.append((args, config_path))))
    entry.dispatch(cfg_path, {'state_dir': str(tmp_path / 'state'), 'compatibility': {
        'profile_path': str(tmp_path / 'trust.json'), 'profile_sha256': 'a' * 64}},
        ['controls-capture', 'synthetic-pin'])
    assert events == ['trust', (['synthetic-pin'], cfg_path)]


def test_controls_request_cannot_select_another_configuration(monkeypatch, tmp_path):
    from study2 import controls_capture
    monkeypatch.setattr(controls_capture, 'read_pin', lambda _: {
        'config': {'path': str(tmp_path / 'other.json')}})
    monkeypatch.setattr(controls_capture, 'capture', lambda *a, **kw: pytest.fail('capture must not run'))
    with pytest.raises(ValueError, match='request_configuration_differs'):
        controls_capture.main(['{}'], config_path=tmp_path / 'selected.json')
