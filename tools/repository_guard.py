"""Audit Git content without reading or publishing local research data.

Uses the index / committed blobs, so forced adds and earlier commits are checked.
This is a conservative path and content guard, not a claim to detect all PII.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from pathlib import PurePosixPath


EXACT_PATHS = {
    '.gitignore', '.gitattributes', 'README.md', 'pyproject.toml',
    'requirements.lock.txt', 'dashboard.py', 'config.example.json',
    'Prepare Batch.command', 'Run Pipeline.command', 'Start Dashboard.command',
    'Export Review.command', 'Review Centre.command', 'Dyad Centre.command',
    '.githooks/pre-commit', '.githooks/pre-push',
    'tools/repository_guard.py', 'tools/qa/synthetic_review.py',
    'tools/qa/review_workbook.mjs',
    'docs/DATA_MODEL.md', 'docs/STAGES.md', 'docs/REVIEW_CARDS_COLLEAGUES.md',
    'docs/REVIEW_CARDS_OPERATIONS.md', 'docs/MATCHING_RULES.md',
    'docs/REPOSITORY.md', 'docs/DYAD_TRACKING_OPERATIONS.md', 'docs/CODE_READING_GUIDE.md',
}
PYTHON_DIRECTORIES = {'study2', 'tests', 'mappings'}
TEMPLATE_PATH = 'study2/assets/review_template.xlsx'
TEMPLATE_SHA256 = 'edfbf5f5397e351c8894054c90030b47c31ab52f19c1dfce2957eea024d49189'
MAX_BLOB_BYTES = 2_000_000

CONTENT_PATTERNS = [
    ('private key', re.compile(r'-----BEGIN(?: [A-Z]+)* PRIVATE KEY-----')),
    ('GitHub credential', re.compile(r'\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{30,})\b')),
    ('AWS access key', re.compile(r'\bAKIA[A-Z0-9]{16}\b')),
    ('private research identifier', re.compile(r'\b(?:SUB|CASE|CHILD|RUN|REV|PKG|RB|DEC|DYAD|DRES|DEVENT|INV)_[0-9a-f]{20,}\b', re.I)),
    ('survey response identifier', re.compile(r'\bR_[A-Za-z0-9]{10,}\b')),
    ('machine-specific user path', re.compile(r'''/(?:Users|home)/[^/\s"'<>]+/''')),
    ('literal credential', re.compile(r'''\b(?:api[_-]?key|client_secret|access_token|password)["']?\s*[:=]\s*["'][^"'\n]{12,}["']''', re.I)),
]
EMAIL = re.compile(r'\b[A-Za-z0-9._%+-]+@([A-Za-z0-9.-]+\.[A-Za-z]{2,})\b')
EXAMPLE_DOMAINS = {'example.com', 'example.org', 'example.net'}


def allowed_path(path: str) -> bool:
    value = PurePosixPath(path)
    if any(ord(c) < 32 for c in path) or '\\' in path or value.is_absolute() or '..' in value.parts:
        return False
    if path in EXACT_PATHS or path == TEMPLATE_PATH:
        return True
    return str(value.parent) in PYTHON_DIRECTORIES and value.suffix == '.py'


def inspect_blob(path: str, content: bytes, mode: str = '100644') -> list[str]:
    if not allowed_path(path):
        return ['path is outside the reviewed code allowlist']
    if mode not in {'100644', '100755'}:
        return ['symlinks, submodules and unusual file modes are not allowed']
    if path == TEMPLATE_PATH:
        if hashlib.sha256(content).hexdigest() != TEMPLATE_SHA256:
            return ['blank layout fingerprint changed; inspect every sheet before approving a replacement']
        return []
    if len(content) > MAX_BLOB_BYTES:
        return ['unexpectedly large code/document blob']
    if b'\x00' in content or content.startswith((b'PK\x03\x04', b'SQLite format')):
        return ['binary or data content disguised as an allowed text file']
    try:
        text = content.decode('utf-8')
    except UnicodeDecodeError:
        return ['allowed code/documents must be UTF-8 text']
    problems = [name for name, pattern in CONTENT_PATTERNS if pattern.search(text)]
    if any(match.group(1).lower() not in EXAMPLE_DOMAINS for match in EMAIL.finditer(text)):
        problems.append('non-example email address')
    if path == 'config.example.json':
        try:
            cfg = json.loads(text)
            if any(source.get('columns') for source in cfg.get('sources', [])):
                problems.append('example must not contain a real source-column registration')
            if not isinstance(cfg.get('sources'), list):
                problems.append('example source registry must be a list')
        except (ValueError, AttributeError, TypeError):
            problems.append('invalid example configuration')
    return problems


def git(*args: str) -> bytes:
    return subprocess.check_output(['git', *args])


def index_files():
    for item in git('ls-files', '--stage', '-z').split(b'\x00'):
        if not item:
            continue
        header, name = item.split(b'\t', 1)
        mode, oid, stage = header.decode('ascii').split()
        if stage != '0':
            raise ValueError('Unresolved merge entries cannot be audited')
        yield name.decode('utf-8'), oid, mode


def committed_files(ref: str):
    for item in git('ls-tree', '-r', '-z', '--full-tree', ref).split(b'\x00'):
        if not item:
            continue
        header, name = item.split(b'\t', 1)
        mode, kind, oid = header.decode('ascii').split()
        if kind != 'blob':
            yield name.decode('utf-8'), oid, mode
        else:
            yield name.decode('utf-8'), oid, mode


def audit(entries, seen=None):
    seen = set() if seen is None else seen
    failures = []
    for path, oid, mode in entries:
        key = (path, oid, mode)
        if key in seen:
            continue
        seen.add(key)
        if mode not in {'100644', '100755'}:
            problems = ['symlinks / submodules cannot be published']
        else:
            problems = inspect_blob(path, git('cat-file', 'blob', oid), mode)
        if problems:
            # Never echo a matching phone, email, identifier or credential.
            failures.append({'path': path, 'checks': problems})
    return failures, seen


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    selection = parser.add_mutually_exclusive_group(required=True)
    selection.add_argument('--staged', action='store_true', help='Audit the full staged tree')
    selection.add_argument('--history', metavar='REF', help='Audit all commits reachable from REF')
    args = parser.parse_args()
    try:
        if args.staged:
            failures, seen = audit(index_files())
            count = 1
        else:
            refs = git('rev-list', args.history, '--').decode('ascii').splitlines()
            failures, seen = [], set()
            for ref in refs:
                issues, seen = audit(committed_files(ref), seen)
                failures.extend(issues)
            count = len(refs)
    except (subprocess.CalledProcessError, ValueError, UnicodeError):
        print('Repository audit could not read a complete Git tree; push is blocked.')
        return 1
    if failures:
        print('Repository audit blocked private / unapproved content:')
        print(json.dumps(failures, ensure_ascii=False, indent=2))
        return 1
    print(f'Repository audit passed: {len(seen)} reviewed file versions across {count} tree(s).')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
