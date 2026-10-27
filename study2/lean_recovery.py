"""Opt-in recovery policy. No historical deletion or live configuration changes.

All cache hits are verified by content, not mtime. Unknown code remains part of
the scientific revision. External dependencies must be explicitly registered.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from .common import PipelineError, atomic_json, digest, file_hash


# These are presentation entry points, not the shared statistical engines.
PRESENTATION_MODULES = frozenset({
    'static_assets.py', 'static_eligibility_ui.py', 'dashboard_header.py',
    'descriptive_dashboard.py', 'descriptive_trend_dashboard.py',
    'descriptive_workbench.py', 'parent_panel_dashboard.py',
})
CONTROL_DIRECTORIES = ('analysis_eligibility', 'review_dispositions')
CONTROL_FILES = ('CURRENT_REVIEW_DISPOSITION.json',)
ENVIRONMENT_PATHS = ('STUDY2_MANUAL_EXCLUSION_MANIFEST',
                     'STUDY2_CURRENT_REVIEW_WORKLOAD', 'STUDY2_REVIEW_STATE_DIR')


def enabled(cfg):
    mode = cfg.get('recovery_policy', {}).get('mode')
    if mode not in (None, 'legacy', 'lean'):
        raise PipelineError('Unknown recovery policy; refusing a fallback to legacy retention')
    return mode == 'lean'


def scientific_program_hash(directory):
    return digest({p.name: file_hash(p) for p in sorted(Path(directory).glob('*.py'))
                   if p.name not in PRESENTATION_MODULES})


def sqlite_revision(path):
    """Include WAL bytes; never reuse a main-file-only signature of a WAL DB."""
    path = Path(path)
    journal = path.with_name(path.name + '-journal')
    if journal.exists() and journal.stat().st_size:
        raise PipelineError('Database has an active rollback journal; retry after writer completes')
    wal = path.with_name(path.name + '-wal')
    return {'database': file_hash(path), 'wal': file_hash(wal) if wal.exists() else None}


def cached_review(cfg, revision):
    index = Path(cfg['state_dir']) / 'REVIEW_BACKUP_CACHE.json'
    if not index.is_file():
        return None
    value = json.loads(index.read_text())
    if value.get('source_revision') != revision:
        return None
    path = Path(value['path'])
    if path.is_symlink() or not path.is_file() or file_hash(path) != value['snapshot_sha256']:
        raise PipelineError('Cached review recovery snapshot is missing or corrupt')
    return str(path)


def record_review_cache(cfg, revision, path, checksum):
    atomic_json(Path(cfg['state_dir']) / 'REVIEW_BACKUP_CACHE.json', {
        'source_revision': revision, 'path': str(path), 'snapshot_sha256': checksum})


def recovery_assets(cfg):
    """Add the complete state control directories plus explicit external assets.

    No discovery outside declared roots and no following symlinks. SQLite
    dependencies must be quiescent DELETE-journal files; main/review use the
    checkpoint's existing SQLite online-backup path instead.
    """
    state = Path(cfg['state_dir']).resolve()
    result = {}
    declared = cfg.get('recovery_policy', {}).get('required_assets')
    if not isinstance(declared, list):
        raise PipelineError('Lean recovery requires an explicit required_assets inventory (an empty list is allowed)')

    def add(path, relative):
        path = Path(path)
        if path.is_symlink() or not path.is_file():
            raise PipelineError('Required recovery asset must be a regular file: ' + str(path))
        with path.open('rb') as stream:
            sqlite = stream.read(16) == b'SQLite format 3\0'
        if sqlite:
            revision = sqlite_revision(path)
            if revision['wal'] is not None:
                raise PipelineError('External SQLite recovery asset must have no WAL: ' + str(path))
        name = str(relative)
        if name in result and result[name] != path:
            raise PipelineError('Duplicate recovery destination: ' + name)
        result[name] = path

    def tree(path, relative):
        if path.is_symlink() or not path.is_dir():
            raise PipelineError('Required recovery directory is missing or linked: ' + str(path))
        for p in sorted(path.rglob('*')):
            if p.is_symlink():
                raise PipelineError('Recovery dependency contains a symlink: ' + str(p))
            if p.is_file():
                add(p, relative / p.relative_to(path))

    for name in CONTROL_DIRECTORIES:
        if (state / name).exists():
            tree(state / name, Path(name))
    for name in CONTROL_FILES:
        if (state / name).exists():
            add(state / name, Path(name))
    for item in declared:
        path = Path(item['path']).expanduser()
        relative = Path(item['restore_path'])
        if not path.is_absolute() or relative.is_absolute() or '..' in relative.parts or not relative.parts or relative.parts[0] != 'dependencies':
            raise PipelineError('Explicit recovery assets need absolute sources and dependencies/ restore paths')
        if item.get('kind') == 'directory':
            tree(path, relative)
        elif item.get('kind') == 'file':
            add(path, relative)
        else:
            raise PipelineError('Recovery asset kind must be file or directory')
    # Capture the actual dashboard bindings without copying secrets or the
    # entire environment. Every path must be covered by the declared inventory.
    for name in ENVIRONMENT_PATHS:
        value = os.environ.get(name)
        if not value:
            continue
        path = Path(value).expanduser().resolve()
        if name == 'STUDY2_REVIEW_STATE_DIR':
            if path != state:
                raise PipelineError('Review environment is bound to a different state directory')
        elif path not in {p.resolve() for p in result.values()}:
            raise PipelineError('Dashboard dependency is not covered by recovery assets: ' + name)
    return result


def recovery_bindings(cfg, assets):
    paths = {str(Path(p).resolve()): name for name, p in assets.items()}
    environment = {}
    for name in ENVIRONMENT_PATHS:
        value = os.environ.get(name)
        if value:
            environment[name] = '.' if name == 'STUDY2_REVIEW_STATE_DIR' else paths[str(Path(value).expanduser().resolve())]
    return {'environment': environment, 'source_to_restore': paths,
            'external_dependencies': cfg.get('recovery_policy', {}).get('required_assets', [])}


def retention_plan(cfg, final, previous=None):
    """Review-only checkpoint inventory. Never a deletion authorization."""
    state = Path(cfg['state_dir'])
    retained = {str(Path(final).resolve()): 'current verified recovery'}
    if previous:
        retained[str(Path(previous).resolve())] = 'previous verified rollback'
    for item in cfg.get('recovery_policy', {}).get('required_assets', []):
        retained[str(Path(item['path']).resolve())] = 'explicit runtime/control dependency'
    for value in cfg.get('recovery_policy', {}).get('protected_paths', []):
        retained[str(Path(value).resolve())] = 'operator recovery pin'
    ledger = state / 'DYAD_LEDGER.json'
    if ledger.is_file():
        retained[str(Path(json.loads(ledger.read_text())['bundle']).resolve())] = 'active administrative ledger'
    rows = []
    for path in sorted((state / 'checkpoints').glob('CHECKPOINT_*')):
        resolved = path.resolve()
        reasons = [reason for target, reason in retained.items()
                   if resolved == Path(target) or Path(target).is_relative_to(resolved)]
        rows.append({'path': str(path), 'disposition': 'retain' if reasons else 'needs_dependency_review',
                     'reasons': reasons, 'deletion_authorized': False})
    return {'format_version': 1, 'mode': 'review_only', 'automatic_deletion': False,
            'checkpoints': rows, 'protected_paths': retained,
            'note': 'No size/savings claim; hardlinks and external launch references require review before deletion.'}
