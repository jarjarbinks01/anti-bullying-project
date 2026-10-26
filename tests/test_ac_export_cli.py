import json
import sys

import pytest

from study2 import cli


def test_cli_passes_explicit_export_context_without_running_pipeline(monkeypatch, tmp_path, capsys):
    from study2 import ac_export
    calls = []
    monkeypatch.setattr(cli, 'load_config', lambda _: {'state_dir': str(tmp_path)})
    def export(cfg, output, **options):
        calls.append((cfg, output, options))
        return {'row_count': 1, 'fixed_AC_members': [['synthetic-a', 'synthetic-b']],
                'exclusion_manifest': {'entries': ['synthetic-private-target']}}
    monkeypatch.setattr(ac_export, 'export_student_ac', export)
    destination = tmp_path / 'new-output'
    manifest = tmp_path / 'accepted.json'
    monkeypatch.setattr(sys, 'argv', ['study2', 'student-ac-export', '--output', str(destination),
        '--exclusion-manifest', str(manifest), '--dataset-version', 'synthetic-v1'])
    cli.main()
    assert calls == [({'state_dir': str(tmp_path)}, destination,
        {'manifest_path': manifest, 'enabled': True, 'dataset_version': 'synthetic-v1'})]
    assert json.loads(capsys.readouterr().out) == {'row_count': 1}
    assert not destination.exists()


def test_cli_default_on_without_manifest_does_not_call_exporter(monkeypatch, tmp_path):
    from study2 import ac_export
    monkeypatch.setattr(cli, 'load_config', lambda _: {'state_dir': str(tmp_path)})
    def forbidden(*args, **kwargs):
        raise AssertionError('Missing manifest must fail before the exporter')
    monkeypatch.setattr(ac_export, 'export_student_ac', forbidden)
    monkeypatch.setattr(sys, 'argv', ['study2', 'student-ac-export', '--output', str(tmp_path / 'new')])
    with pytest.raises(SystemExit) as result:
        cli.main()
    assert result.value.code != 0
