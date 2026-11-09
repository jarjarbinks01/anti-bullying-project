"""Explicit, process-local trust for accepted historical compatibility records.

Call configure_trust once at operator startup with a locally configured path and
an independently pinned file digest. Never take either from a proposal, request,
release manifest, or other evidence being verified. Unconfigured generic future
carry requires no profile; historical records fail closed without their anchors.

The v1 verifier contract accepts a recorded implementation identity only within
its exact reviewed profile. It does not alias scientific rules, skip proof
checks, authorize new decisions, or permit applying a stale proposal. New apply
paths still require the current implementation revision.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re

FORMAT = 'study2_trusted_compatibility_v1'
VERIFIER_CONTRACT = 'study2_pair_continuity_verifier_v1'
CONTINUITY_PROFILES = {}
ADMINISTRATIVE_PREVIEW = {}
_HISTORICAL_VERIFIERS = {}
_SCOPE_SHA256 = None
_CONFIGURED_SHA256 = None
_ADMINISTRATIVE_READ = None
ADMINISTRATIVE_READ_CONTRACT = "study2_administrative_historical_read_v1"


def _need(condition, code):
    if not condition:
        raise ValueError('compatibility_' + code)


def _hash(value):
    return isinstance(value, str) and re.fullmatch(r'[0-9a-f]{64}', value) is not None


def configure_trust(profile_path, expected_sha256):
    """Load a hash-pinned local trust profile; failures never partially configure.

    Repeated initialization of the same bytes is harmless. A different profile
    requires a fresh process, preventing mid-operation authority replacement.
    """
    global _SCOPE_SHA256, _CONFIGURED_SHA256, _ADMINISTRATIVE_READ
    _need(_hash(expected_sha256), 'file_hash_required')
    path = Path(profile_path)
    _need(path.is_absolute(), 'absolute_path_required')
    _need(not any(p.is_symlink() for p in (path, *path.parents)), 'regular_file_required')
    before = path.stat()
    _need(path.is_file() and not getattr(before, 'st_flags', 0) & 0x40000000,
          'regular_file_required')
    raw = path.read_bytes()
    after = path.stat()
    _need((before.st_ino, before.st_size, before.st_mtime_ns) ==
          (after.st_ino, after.st_size, after.st_mtime_ns), 'file_changed')
    _need(hashlib.sha256(raw).hexdigest() == expected_sha256, 'file_hash_changed')
    value = json.loads(raw)
    _need(isinstance(value, dict) and set(value) - {'administrative_read'} == {
        'format', 'continuity_profiles', 'administrative_preview',
        'administrative_scope_sha256', 'historical_verifiers'} and value['format'] == FORMAT,
        'format')
    profiles = value['continuity_profiles']
    _need(isinstance(profiles, dict), 'continuity_profiles')
    for release, profile in profiles.items():
        _need(isinstance(release, str) and bool(release) and isinstance(profile, dict) and
              profile.get('target_release_id') == release, 'continuity_profile')
        _need(all(_hash(v) for k, v in profile.items() if k.endswith('_sha256') or k.endswith('_revision')),
              'continuity_hash')
    preview = value['administrative_preview']
    _need(preview is None or isinstance(preview, dict) and
          isinstance(preview.get('id'), str) and isinstance(preview.get('inputs'), dict) and
          bool(preview['inputs']) and all(_hash(v) for v in preview['inputs'].values()), 'preview_profile')
    scope = value['administrative_scope_sha256']
    _need(scope is None or _hash(scope), 'scope_hash')
    from .analysis_eligibility import sha
    profile_revisions = {sha(p) for p in profiles.values()}
    contracts = value['historical_verifiers']
    _need(isinstance(contracts, list), 'verifier_contracts')
    accepted = {}
    for contract in contracts:
        _need(isinstance(contract, dict) and set(contract) == {
            'contract', 'profile_revision', 'implementation_revisions'} and
            contract['contract'] == VERIFIER_CONTRACT and
            contract['profile_revision'] in profile_revisions, 'verifier_contract')
        revisions = contract['implementation_revisions']
        _need(isinstance(revisions, list) and bool(revisions) and
              all(_hash(r) for r in revisions) and len(set(revisions)) == len(revisions), 'implementation_revisions')
        key = contract['profile_revision']
        _need(key not in accepted, 'duplicate_verifier_contract')
        accepted[key] = frozenset(revisions)
    read = value.get('administrative_read')
    if read is not None:
        _need(isinstance(read, dict) and set(read) == {
            'contract', 'scope_sha256', 'workload_pin', 'reader_rules_hash', 'reader_revision',
            'reader_code_sha256', 'recovery_manifest', 'recovery_root',
            'path_map', 'original_code'}, 'administrative_read_contract')
        _need(read['contract'] == ADMINISTRATIVE_READ_CONTRACT and
              _hash(read['scope_sha256']) and
              _hash(read['reader_rules_hash']) and _hash(read['reader_revision']), 'administrative_read_scope')
        for key in ('workload_pin', 'recovery_manifest'):
            pin = read[key]
            _need(isinstance(pin, dict) and set(pin) == {'path', 'sha256'} and
                  isinstance(pin['path'], str) and Path(pin['path']).is_absolute() and
                  _hash(pin['sha256']), 'administrative_read_pin')
        code = read['reader_code_sha256']
        _need(isinstance(code, dict) and bool(code) and
              all(isinstance(k, str) and re.fullmatch(r'[a-z_]+\.py', k) and _hash(v)
                  for k, v in code.items()), 'administrative_reader_code')
        _need(isinstance(read['recovery_root'], str) and Path(read['recovery_root']).is_absolute(),
              'administrative_recovery_root')
        for key in ('path_map', 'original_code'):
            mapping = read[key]
            _need(isinstance(mapping, dict) and bool(mapping), 'administrative_recovery_mapping')
            for source, relative in mapping.items():
                _need(isinstance(source, str) and isinstance(relative, str) and bool(relative) and
                      not Path(relative).is_absolute() and '..' not in Path(relative).parts,
                      'administrative_recovery_mapping')
        _need(all(Path(k).is_absolute() for k in read['path_map']) and
              read['workload_pin']['path'] in read['path_map'] and
              set(read['original_code']) == set(code), 'administrative_recovery_mapping')
    _need(_CONFIGURED_SHA256 in (None, expected_sha256), 'already_configured')
    if _CONFIGURED_SHA256 is not None:
        return
    CONTINUITY_PROFILES.update(deepcopy(profiles))
    ADMINISTRATIVE_PREVIEW.update(deepcopy(preview or {}))
    _HISTORICAL_VERIFIERS.update(accepted)
    _ADMINISTRATIVE_READ = deepcopy(read)
    _SCOPE_SHA256 = scope
    _CONFIGURED_SHA256 = expected_sha256


def administrative_scope_sha256():
    return _SCOPE_SHA256


def accepts_historical_implementation(profile, recorded, current):
    """Only read verification uses legacy identity; all proof checks still run."""
    if recorded == current:
        return True
    from .analysis_eligibility import sha
    return recorded in _HISTORICAL_VERIFIERS.get(sha(profile), ())


def administrative_read_contract():
    """Return isolated read-only trust, never a proposal-supplied authority."""
    return deepcopy(_ADMINISTRATIVE_READ)
