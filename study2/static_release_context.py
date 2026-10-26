"""Closed aggregate provenance for a freshly calculated dashboard release.

The calculation owner supplies the independently reconciled control aggregates.
This module binds them to the selected run and exact accepted exclusion manifest;
it neither discovers private controls nor calculates scientific memberships.
"""
from copy import deepcopy
import re

from .analysis_eligibility import sha, validate_manifest
from .common import PipelineError

FORMAT = 'study2_dashboard_release_context_v1'
FIELDS = {'format', 'release_id', 'run_id', 'run_fingerprint', 'program_hash',
          'group_control_head', 'group_proposal_revision', 'group_implementation_revision',
          'review_control_revision', 'flags', 'workload', 'revision'}
HASH_FIELDS = {'run_fingerprint', 'program_hash', 'group_control_head',
               'group_proposal_revision', 'group_implementation_revision',
               'review_control_revision', 'revision'}
FLAG_FIELDS = {'manifest_revision', 'inventory_revision', 'eric_records', 'group_records',
               'overlap_records', 'combined_records'}
WORK_FIELDS = {'child_groups', 'phone_groups', 'held_groups', 'correction_comparisons',
               'correction_bundles', 'adult_comparisons'}
PUBLIC_EXTRA = {'default_eligibility', 'workload_scope', 'export_program_hash'}


def _need(ok, code):
    if not ok:
        raise PipelineError('Dashboard release context: ' + code)


def _hash(value):
    return isinstance(value, str) and re.fullmatch('[0-9a-f]{64}', value) is not None


def validate_release_context(value, *, public=False):
    _need(isinstance(value, dict) and set(value) == FIELDS | (PUBLIC_EXTRA if public else set()),
          'unsupported_fields')
    _need(value['format'] == FORMAT, 'unsupported_format')
    for key in ('release_id', 'run_id'):
        token = value[key]
        _need(isinstance(token, str) and re.fullmatch('[A-Za-z0-9][A-Za-z0-9_-]{0,95}', token)
              and not re.match(r'(?:SUB|CHILD|CASE|REV|DYAD|PKG|DEC)_', token), 'invalid_public_run_token')
    _need(all(_hash(value[k]) for k in HASH_FIELDS), 'invalid_revision')
    flags, workload = value['flags'], value['workload']
    _need(isinstance(flags, dict) and set(flags) == FLAG_FIELDS and
          all(_hash(flags[k]) for k in ('manifest_revision', 'inventory_revision')), 'invalid_flag_fields')
    _need(isinstance(workload, dict) and set(workload) == WORK_FIELDS, 'invalid_workload_fields')
    _need(all(type(v) is int and 0 <= v <= 2**53-1 for k, v in flags.items()
              if k not in {'manifest_revision', 'inventory_revision'}) and
          all(type(v) is int and 0 <= v <= 2**53-1 for v in workload.values()), 'invalid_aggregate_count')
    _need(flags['overlap_records'] <= min(flags['eric_records'], flags['group_records']) and
          flags['combined_records'] == flags['eric_records'] + flags['group_records'] - flags['overlap_records'],
          'flag_union_mismatch')
    _need(workload['child_groups'] == workload['phone_groups'] + workload['held_groups'] and
          workload['correction_bundles'] <= workload['correction_comparisons'], 'workload_units_mismatch')
    body = {k: value[k] for k in FIELDS if k != 'revision'}
    _need(value['revision'] == sha(body), 'revision_mismatch')
    if public:
        _need(value['default_eligibility'] in {'off', 'on'} and
              value['workload_scope'] == 'release_wide_applied_controls' and
              _hash(value['export_program_hash']), 'invalid_public_context')
    return value


def bind_release_context(value, release, summary, run_fingerprint, records, manifest, *, default_eligibility='off'):
    """Return only closed aggregates, after exact current-run/manifest checks."""
    validate_release_context(value)
    _need(default_eligibility in {'off', 'on'}, 'unsupported_default_eligibility')
    _need(value['release_id'] == release['release_id'] == summary['release_id'] and
          value['run_id'] == release['run_id'] and value['run_fingerprint'] == run_fingerprint and
          value['program_hash'] == summary.get('program_hash'), 'selected_run_mismatch')
    _need(manifest is not None, 'accepted_composed_manifest_required')
    excluded = validate_manifest(manifest, records, release['release_id'])
    flags = value['flags']
    _need(flags['manifest_revision'] == manifest['revision'] and
          flags['inventory_revision'] == manifest['inventory_revision'] and
          flags['combined_records'] == len(excluded), 'accepted_manifest_mismatch')
    from .runner import program_hash
    result = deepcopy(value)
    result.update(default_eligibility=default_eligibility, workload_scope='release_wide_applied_controls',
                  export_program_hash=program_hash())
    validate_release_context(result, public=True)
    return result
