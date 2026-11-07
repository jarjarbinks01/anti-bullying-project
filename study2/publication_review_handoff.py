"""Prepare an exact tuple review and check its receipt without publishing.

Inputs must come from native staging and a coherent native tuple capture.
This module creates no acceptance, owner permit, scientific validation or
deployment authorization. It never calls a publisher or writes a file.
"""
from copy import deepcopy
import re


COMPONENTS = frozenset({
    'old_release_id', 'target_release_id', 'target_release_path',
    'old_policy', 'target_policy', 'old_workload', 'target_workload',
    'old_selection', 'target_selection', 'old_manifest', 'target_manifest',
    'target_manifest_sha256', 'revisions', 'old_tracking_revision',
    'group_review_subject', 'input_pins',
})


def _native():
    # Use the chosen native runtime, including its typed revision algorithm.
    from study2 import coordinated_update
    return coordinated_update


def draft_review(components):
    """Return a plan and deliberately unaccepted template for independent review.

    A group-policy approval is an input to native staging. It is never reused
    as the publication-tuple approval produced by a separate reviewer.
    """
    native = _native()
    native.need(isinstance(components, dict) and
                set(components) in (COMPONENTS, COMPONENTS | {'consumer_owner_scope'}),
                'complete_native_tuple_components_required')
    plan = deepcopy(components)
    for key in ('old_release_id', 'target_release_id'):
        native.need(isinstance(plan[key], str) and
                    re.fullmatch(r'RUN_[0-9a-f]{32}', plan[key]) is not None,
                    'tuple_release_identity_invalid')
    native.need(plan['old_release_id'] != plan['target_release_id'],
                'tuple_requires_distinct_releases')
    native.need(isinstance(plan['old_selection'], dict) and
                isinstance(plan['target_selection'], dict) and
                plan['old_selection'].get('coordinated_update_gate') is not True and
                plan['target_selection'].get('coordinated_update_gate') is not True,
                'tuple_requires_ungated_endpoint_selections')
    plan['format'] = 'study2_coordinated_publication_plan_v1'
    plan['gate_selection'] = {**deepcopy(plan['old_selection']),
                              'coordinated_update_gate': True}
    plan['revision'] = native.sha(plan)
    template = {
        'format': 'study2_independent_update_review_v1',
        'kind': 'publication_tuple', 'subject_revision': plan['revision'],
        'accepted': False, 'reviewer': '', 'reason': '',
    }
    return {
        'plan': plan, 'independent_review_template': template,
        'receipt_validated': False, 'scientific_state_validated': False,
        'owner_fence_established': False, 'operational_authority': False,
        'user_authorization': 'Not determined by this technical helper; use the existing session authorization.',
    }


def verify_tuple_review(cfg, plan_pin, review_pin, *, operator):
    """Use native provenance, revision, reviewer and launcher-binding checks.

    Native _load_plan checks the review contract. Full native transition
    validation and a genuine owner fence are still required for publication.
    A successful return is a read-only report, never a publisher capability.
    """
    plan = _native()._load_plan(cfg, plan_pin, review_pin, operator)
    return {
        'plan_revision': plan['revision'],
        'old_release_id': plan['old_release_id'],
        'target_release_id': plan['target_release_id'],
        'receipt_validated': True, 'scientific_state_validated': False,
        'owner_fence_established': False, 'operational_authority': False,
        'user_authorization': 'Not determined by this technical receipt; use the existing session authorization.',
    }
