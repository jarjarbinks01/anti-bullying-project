"""Open a pinned protected formal dashboard; never export or change selectors.

Bindings live in ignored local configuration. This module reads only aggregate
site assets, current-control evidence and process metadata, never secret contents.
The separately pinned protected launcher owns credential checks and serving.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import webbrowser

from .controls_capture import capture, read_pin
from .static_release_context import validate_release_context


def pin(path):
    path = Path(path)
    if not path.is_file() or any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError('Dashboard input must be a regular non-symlink file')
    return {'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}


def verify_site(config, current_context, formal_root=None):
    site_path = Path(config['site'])
    if not site_path.is_absolute() or any(p.is_symlink() for p in (site_path, *site_path.parents)):
        raise ValueError('Formal dashboard site must be an absolute non-symlink directory')
    site = site_path.resolve()
    if formal_root is not None and not site.is_relative_to(Path(formal_root).resolve()):
        raise ValueError('Formal dashboard points outside the configured output root')
    manifest = read_pin({'path': str(site / 'snapshot-manifest.json'),
                         'sha256': config['manifest_sha256']})
    context = manifest['release_context']
    validate_release_context(current_context)
    validate_release_context(context, public=True)
    if (context['format'] != 'study2_dashboard_release_context_v1'
            or context['workload_scope'] != 'release_wide_applied_controls'
            or context['default_eligibility'] != 'on'
            or manifest['release_id'] != current_context['release_id']
            or {key: context.get(key) for key in current_context} != current_context):
        raise ValueError('Formal dashboard does not match current published controls')
    projection = manifest['bd_projection']
    if (projection['policy'] != 'selected_parent_waves_same_child_v1'
            or projection['source_release_id'] != manifest['release_id']):
        raise ValueError('Formal dashboard is not the selected same-child projection')
    files = manifest['files']
    if not isinstance(files, dict) or not {'index.html', 'preview.mjs'} <= files.keys():
        raise ValueError('Protected formal dashboard assets are incomplete')
    for name, expected in files.items():
        relative = Path(name)
        path = site / relative
        if relative.is_absolute() or '..' in relative.parts or not path.resolve().is_relative_to(site):
            raise ValueError('Unsafe formal dashboard asset path')
        if pin(path)['sha256'] != expected:
            raise ValueError('Formal dashboard asset changed')
    return site


def main(cfg=None, config_path=None, activation_path=None, argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true', help='Validate formal site and protected launcher without starting a server')
    args = parser.parse_args(argv)
    if cfg is None or config_path is None:
        raise ValueError('A local runtime config with dashboard_preview bindings is required')
    binding = cfg.get('dashboard_preview')
    if not isinstance(binding, dict) or not {'config', 'code_revision'} <= binding.keys():
        raise ValueError('Configure dashboard_preview config pin and reviewed code_revision locally')
    config = read_pin(binding['config'])
    packaged = 'launcher' not in binding
    launcher = (Path(__file__).parent / 'presentation/assets/local-preview.mjs' if packaged
                else Path(binding['launcher']['path']))
    launcher_pin = pin(launcher)
    if not packaged and launcher_pin != binding['launcher']:
        raise ValueError('Protected preview launcher changed')
    if not packaged and Path(binding['config']['path']).resolve() != launcher.parent.resolve() / 'preview-config.json':
        raise ValueError('External protected launcher requires its pinned adjacent preview-config.json')
    launcher_args = (['--config', binding['config']['path']] if packaged else [])
    selection = pin(activation_path) if activation_path is not None else binding.get('selection')
    if selection is None:
        raise ValueError('An explicit activation selector or dashboard_preview.selection pin is required')
    runtime_pin = pin(config_path)
    from .common import load_config
    if load_config(Path(config_path)) != cfg:
        raise ValueError('Runtime configuration changed')
    request = dict(config=runtime_pin, selection=selection, context=None, candidate=None,
                   code_revision=binding['code_revision'])
    current = capture(request, prepare_context=True)['context']
    site = verify_site(config, current, binding.get('site_root'))
    node = shutil.which(binding.get('node', 'node'))
    if node is None:
        raise ValueError('Configured Node executable is unavailable')
    subprocess.run([node, str(launcher), *launcher_args, '--check'], check=True)
    if read_pin(binding['config']) != config or pin(launcher) != launcher_pin:
        raise ValueError('Protected preview configuration changed during validation')
    if args.check:
        return site
    # Read only the process record adjacent to the secret path, not the secret.
    pid_path = Path(config['secret_file']).parent / 'preview-process.json'
    if pid_path.exists():
        record = read_pin(pin(pid_path))
        if type(record['pid']) is not int or record['pid'] <= 0:
            raise ValueError('Invalid protected preview process record')
        try:
            os.kill(record['pid'], 0)
        except ProcessLookupError:
            pass
        else:
            if (Path(record['site']).resolve() != site or record['port'] != config['port']
                    or Path(record['launcher']).resolve() != launcher.resolve()):
                raise ValueError('Another protected preview is running; no server was stopped')
            webbrowser.open(f"http://127.0.0.1:{config['port']}")
            return site
    os.execv(node, [node, str(launcher), *launcher_args])


if __name__ == '__main__':
    main()
