"""Dashboard-only draft projection; native accepted-manifest validation is unchanged."""
from contextlib import contextmanager
from contextvars import ContextVar
from ..analysis_eligibility import (
    MANIFEST_FORMAT,
    SCOPE_FORMAT,
    POLICY,
    COPY_POLICY,
    HASH_SCHEME,
    EligibilityError,
    _need,
    sha,
    _hash,
    _records,
    inventory_revision,
    manifest_revision,
    _members,
    _delta,
    Projection,
    independent_impact,
    scope_overlay,
    validate_scope_eligibility,
    query_scope_eligibility,
    projected_cohorts,
    validate_manifest as _accepted_manifest,
    _validate_manifest_inventory,
    _validate_manifest_entries,
    _project_eligibility)

_CANDIDATE_REVISION = ContextVar("candidate_exclusion_revision", default=None)


@contextmanager
def candidate_exclusion_scope(revision):
    """Explicit draft-only calculation scope; never used by the publication reader."""
    _need(_hash(revision), 'candidate_revision_required')
    token = _CANDIDATE_REVISION.set(revision)
    try:
        yield
    finally:
        _CANDIDATE_REVISION.reset(token)

def validate_manifest(manifest, records, release_id):
    """Accept native approved manifests or an explicitly scoped local draft."""
    if not (isinstance(manifest, dict) and
            manifest.get('format') == 'study2_candidate_exclusion_manifest_v1'):
        return _accepted_manifest(manifest, records, release_id)
    rows, by_id = _records(records)
    _need(set(manifest) == {'format', 'release_id', 'inventory_revision', 'revision',
          'status', 'copy_policy', 'entries', 'source_manifest_revision'},
          'invalid_candidate_manifest_shape')
    _need(manifest['status'] == 'draft_unapplied' and
          _CANDIDATE_REVISION.get() == manifest['revision'] and
          _hash(manifest['source_manifest_revision']), 'candidate_scope_required')
    _validate_manifest_inventory(manifest, rows, release_id)
    return _validate_manifest_entries(manifest, rows, by_id)


def project_eligibility(records, analysis, parent_longitudinal, manifest, release_id, *,
                        enabled=True, panel=None):
    """Use native projection with this boundary's explicitly scoped validator."""
    return _project_eligibility(records, analysis, parent_longitudinal, manifest, release_id,
                                enabled=enabled, panel=panel, validator=validate_manifest)
