"""Synthetic checks for the code-only Git boundary; no research files read."""
import hashlib
import importlib.util
import subprocess
from pathlib import Path

import pytest


spec = importlib.util.spec_from_file_location('repository_guard', Path(__file__).resolve().parents[1] / 'tools/repository_guard.py')
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)


@pytest.mark.parametrize('path', [
    'config.local.json', 'config.merged.json', 'study2/participant.csv',
    'tests/results.json', 'releases/result.parquet', 'inbox/batch.ready.json',
    'docs/dashboard.png', 'docs/actual_counts.md', 'review_packages/cards.xlsx',
    'tools/qa/private_case.py', 'study2/secret/records.py',
])
def test_private_or_unreviewed_paths_are_rejected_even_when_forced(path):
    assert guard.inspect_blob(path, b'private fixture')


def test_data_disguised_as_code_and_symlink_are_rejected():
    assert guard.inspect_blob('study2/new.py', b'SQLite format 3\x00data')
    assert guard.inspect_blob('tests/new.py', b'PK\x03\x04data')
    assert guard.inspect_blob('study2/new.py', b'../private', '120000')


def test_private_identifiers_emails_and_user_paths_are_rejected_without_echoing_values():
    values = ['SUB_' + 'a' * 26, 'DYAD_' + 'b' * 32, 'INV_' + 'c' * 32,
              'DRES_' + 'd' * 32, 'DEVENT_' + 'e' * 64,
              'person' + '@' + 'private-school.hk', '/Users/' + 'private-user/data/file']
    for value in values:
        issues = guard.inspect_blob('study2/new.py', value.encode())
        assert issues
        assert all(value not in issue for issue in issues)
    assert guard.inspect_blob('tests/new.py', b'email = "student@example.org"') == []


def test_changed_blank_template_is_rejected():
    content = b'synthetic workbook bytes'
    assert guard.inspect_blob(guard.TEMPLATE_PATH, content)
    assert hashlib.sha256(content).hexdigest() != guard.TEMPLATE_SHA256


def test_example_config_must_not_include_registered_columns():
    assert guard.inspect_blob('config.example.json', b'{"sources":[{"columns":["real_column"]}]}')
    assert guard.inspect_blob('config.example.json', b'{"sources":[{"columns":[]}]}') == []


def test_allowlist_does_not_allow_path_traversal_or_unrelated_files():
    assert not guard.allowed_path('study2/../private.py')
    assert not guard.allowed_path('/study2/a.py')
    assert not guard.allowed_path('other/study2/a.py')
    assert guard.allowed_path('study2/review_core.py')


@pytest.mark.parametrize('path', [
    'tests/static_source_ui_browser.cjs',
    'tests/paired_table_ui_browser.cjs',
])
def test_reviewed_browser_harnesses_keep_content_and_mode_guards(path):
    assert guard.inspect_blob(path, b'console.log("synthetic fixture");') == []
    assert guard.inspect_blob(path, ('SUB_' + 'a' * 26).encode())
    assert guard.inspect_blob(path, ('person' + '@' + 'private-school.hk').encode())
    assert guard.inspect_blob(path, ('/Users/' + 'private-user/data/file').encode())
    assert guard.inspect_blob(path, b'SQLite format 3\x00data')
    assert guard.inspect_blob(path, b'../private', '120000')


def test_browser_allowlist_remains_exact_and_gitignore_agrees(tmp_path):
    root = Path(__file__).resolve().parents[1]
    (tmp_path / '.gitignore').write_bytes((root / '.gitignore').read_bytes())
    subprocess.run(['git', 'init', '-q', str(tmp_path)], check=True)
    cases = {
        'tests/static_source_ui_browser.cjs': False,
        'tests/paired_table_ui_browser.cjs': False,
        'tests/private_case.cjs': True,
        'study2/static_source_ui_browser.cjs': True,
        'tests/results.csv': True,
        'tests/source_snapshot.json': True,
    }
    for path, ignored in cases.items():
        result = subprocess.run(['git', 'check-ignore', '--quiet', '--no-index', path],
                                cwd=tmp_path, check=False)
        assert result.returncode == int(not ignored)
        if ignored:
            assert not guard.allowed_path(path)
