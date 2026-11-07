"""Synthetic checks for the proposed current-run workload binding guard."""
import hashlib
import json
from pathlib import Path
import sqlite3

import pytest

from study2 import flag_binding as binding
from study2.common import PipelineError, digest
from test_flag_binding_candidate import setup, R1, R2


def save(path, value):
    path.write_text(json.dumps(value, sort_keys=True) + '\n')


def bind_workload(item, monkeypatch):
    state = item['state']
    item['db'].execute('CREATE TABLE decisions(decision_id TEXT, payload_json TEXT, supersedes TEXT)')
    item['db'].commit()
    directory = state / 'review_dispositions'
    directory.mkdir()
    path = directory / 'workload.json'
    summary = {'format': 'study2_current_review_workload_v1', 'release_id': R1,
               'decision_revision': digest([]),
               'exclusion_manifest_revision': json.loads(item['initial'].read_text())['revision'],
               'native_workload': {'remaining_pending_comparisons': 1},
               'correction_bundles': 0, 'source_groups_resolved': 0,
               'accepted_historical_policy_closures': 0,
               'original_answers': {'total': 0, 'same_child': 0, 'different_children': 0}}
    save(path, summary)
    pointer = {'release_id': R1, 'workload_path': str(path),
               'workload_sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
    save(state / 'CURRENT_REVIEW_DISPOSITION.json', pointer)
    monkeypatch.setenv('STUDY2_CURRENT_REVIEW_WORKLOAD', str(path))
    monkeypatch.setenv('STUDY2_REVIEW_STATE_DIR', str(state))
    return path, pointer, summary


@pytest.fixture
def bound(tmp_path, monkeypatch):
    item = setup(tmp_path, monkeypatch, overlapping_policy=True)
    item['workload'], item['pointer'], item['summary'] = bind_workload(item, monkeypatch)
    yield item
    item['db'].close()


def test_matching_binding_preserves_independent_group_flag(bound):
    assert binding.resolve_current(bound['cfg']) == bound['initial']
    with binding.guarded_current(bound['cfg']) as manifest:
        assert manifest == bound['initial']
        assert {entry['submission_id'] for entry in json.loads(manifest.read_text())['entries']} == {
            'keep', 'policy', 'remove'}


@pytest.mark.parametrize('field', ['workload_path', 'workload_sha256', 'release_id'])
def test_pointer_mismatch_blocks_both_consumers(bound, field):
    pointer = dict(bound['pointer'])
    pointer[field] = 'different'
    save(bound['state'] / 'CURRENT_REVIEW_DISPOSITION.json', pointer)
    with pytest.raises(PipelineError, match='review_disposition_binding_unavailable'):
        binding.resolve_current(bound['cfg'])
    with pytest.raises(PipelineError, match='review_disposition_binding_unavailable'):
        with binding.guarded_current(bound['cfg']):
            pytest.fail('mismatched binding must not be consumed')


def test_selection_switched_before_pointer_fails_until_pointer_catches_up(bound, monkeypatch):
    new_path = bound['workload'].parent / 'replacement.json'
    save(new_path, bound['summary'])
    monkeypatch.setenv('STUDY2_CURRENT_REVIEW_WORKLOAD', str(new_path))
    with pytest.raises(PipelineError, match='review_disposition_binding_unavailable'):
        binding.resolve_current(bound['cfg'])
    pointer = {**bound['pointer'], 'workload_path': str(new_path),
               'workload_sha256': hashlib.sha256(new_path.read_bytes()).hexdigest()}
    save(bound['state'] / 'CURRENT_REVIEW_DISPOSITION.json', pointer)
    assert binding.resolve_current(bound['cfg']) == bound['initial']


def test_stale_or_changed_workload_fails_even_if_pointer_checksum_matches(bound):
    summary = {**bound['summary'], 'exclusion_manifest_revision': 'wrong'}
    save(bound['workload'], summary)
    pointer = {**bound['pointer'],
               'workload_sha256': hashlib.sha256(bound['workload'].read_bytes()).hexdigest()}
    save(bound['state'] / 'CURRENT_REVIEW_DISPOSITION.json', pointer)
    with pytest.raises(PipelineError, match='review_disposition_binding_unavailable'):
        binding.resolve_current(bound['cfg'])


def test_changed_researcher_decision_fails_closed(bound):
    bound['db'].execute('INSERT INTO decisions VALUES(?,?,?)', ('synthetic', '{}', None))
    bound['db'].commit()
    with pytest.raises(PipelineError, match='review_disposition_binding_unavailable'):
        binding.resolve_current(bound['cfg'])


def test_wrong_review_state_and_admin_pointer_fail_closed(bound, monkeypatch):
    monkeypatch.setenv('STUDY2_REVIEW_STATE_DIR', str(bound['state'].parent))
    with pytest.raises(PipelineError, match='review_disposition_binding_unavailable'):
        binding.resolve_current(bound['cfg'])
    monkeypatch.setenv('STUDY2_REVIEW_STATE_DIR', str(bound['state']))
    save(bound['state'] / 'CURRENT_REVIEW_DISPOSITION.json',
         {**bound['pointer'], 'admin_revision': 'unexpected'})
    with pytest.raises(PipelineError, match='review_disposition_binding_unavailable'):
        binding.resolve_current(bound['cfg'])


def test_unreviewed_future_release_is_still_blocked(bound):
    with pytest.raises(PipelineError, match='reviewed_group_policy_required_for_release'):
        with binding.guarded_publication(bound['cfg'], bound['second'], R2):
            pytest.fail('unreviewed future policy must not publish')
    assert binding.resolve_current(bound['cfg']) == bound['initial']


def test_missing_disposition_or_mutated_workload_is_unavailable(bound):
    bound['workload'].write_bytes(b'{}')
    with pytest.raises(PipelineError):
        binding.resolve_current(bound['cfg'])


def test_real_synthetic_administrative_closure_and_dataset_binding(bound):
    from study2 import review_dispositions as admin
    review = sqlite3.connect(bound['state'] / 'review.sqlite')
    review.executescript('CREATE TABLE events(id INTEGER PRIMARY KEY,at TEXT,kind TEXT,target TEXT,payload TEXT);'
                         'CREATE TABLE followups(case_id TEXT PRIMARY KEY,task_id TEXT,state TEXT,payload TEXT);')
    bindings = {'release_id': R1, 'decision_revision': digest([]), 'rules_hash': 'synthetic',
                'source_bindings': {'source': 'synthetic'}, 'output_bindings': {'output': 'synthetic'}}
    case = {'case_id': 'synthetic-case', 'route': 'correction', 'record_a': 'a', 'record_b': 'b',
            'version_a': 'va', 'version_b': 'vb', 'evidence_hash': 'a' * 64, 'reasons': ['synthetic']}
    operation = 'synthetic-closure'
    admin.apply_closed_unresolvable(review, {'operation_id': operation, 'bindings': bindings,
        'authorization': {'authorizer': 'fixture', 'reference': 'fixture', 'reason': 'fixture'},
        'questions': [{'case_index': 1, 'question_index': 1, 'record_id': 'a', 'version_id': 'va',
                       'field': 'fixture', 'comparison_ids': ['synthetic-case']}], 'cases': [case]})
    projection = admin.project_closures(review, bindings, [case])
    revision = admin.administrative_revision(review)
    review.close()
    dataset = bound['workload'].parent / 'active-dataset.json'
    save(dataset, projection)
    summary = {**bound['summary'],
        'native_workload': {'remaining_pending_comparisons': 1, 'field_correction_comparisons': 1},
        'active_workload': {'remaining_pending_comparisons': 1, 'field_correction_comparisons': 0},
        'field_decisions_in_this_followup': 0,
        'administrative_disposition': {'bindings': bindings, 'case_inventory': [case],
            'admin_revision': revision, 'projection': projection, 'operation_id': operation}}
    save(bound['workload'], summary)
    pointer = {**bound['pointer'], 'workload_sha256': hashlib.sha256(bound['workload'].read_bytes()).hexdigest(),
               'admin_revision': revision, 'operation_id': operation, 'active_dataset_path': str(dataset)}
    save(bound['state'] / 'CURRENT_REVIEW_DISPOSITION.json', pointer)
    assert binding.resolve_current(bound['cfg']) == bound['initial']
    assert projection['closed_unresolvable_comparisons'] == 1
    save(dataset, {'projection_ready': True})
    with pytest.raises(PipelineError, match='review_disposition_binding_unavailable'):
        binding.resolve_current(bound['cfg'])
    (bound['state'] / 'CURRENT_REVIEW_DISPOSITION.json').unlink()
    with pytest.raises(PipelineError):
        binding.resolve_current(bound['cfg'])
