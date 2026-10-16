"""Auditable whole-group and independently validated contact-subgroup approval."""
import copy
import json
from itertools import permutations
from pathlib import Path

import pandas as pd
import pytest

from study2.matching import CONTACT_BRIDGE_RULE, identity_evidence, link_records, select_waves
from study2.parent_waves import POLICY as PARENT_POLICY
from study2.review_groups import build_groups
from test_identity_and_time import rec
from test_pipeline_integration import execute, project

POLICY = {'allow_one_digit_phone': True, 'allow_school_transfer': True,
          'allow_contact_bridge_components': True}
SUBGROUP_POLICY = {**POLICY, 'allow_contact_subgroups': True}


def bridge():
    a = rec('a', phone_value='61234567')
    b = rec('b', 120, role='parent', phone_value='61234567')
    b['answer']['contact_02'] = '98765432'
    c = rec('c', 240, phone_value='98765432')
    return [a, b, c]


def decision(a, b, action):
    return {'decision_id': action, 'payload': {'action': action,
        'record_a': a['submission_id'], 'record_b': b['submission_id'],
        'evidence_a': identity_evidence(a), 'evidence_b': identity_evidence(b)}}


@pytest.mark.parametrize('order', list(permutations(range(3))))
def test_connected_whole_group_has_stable_membership_and_direct_edge_proof(order):
    rows = bridge()
    groups, cases, _ = link_records([rows[i] for i in order], [], POLICY)
    assert groups == [['a', 'b', 'c']]
    assert all(c['status'] == 'confirmed' for c in cases)
    audit = next(c for c in cases if c['kind'] == 'identity_group')
    assert audit['rule'] == CONTACT_BRIDGE_RULE
    assert audit['component_evidence']['members'] == ['a', 'b', 'c']
    assert len(audit['component_evidence']['direct_edges']) == 2
    indirect = next(c for c in cases if {c['record_a'], c['record_b']} == {'a', 'c'})
    assert indirect['rule'] == CONTACT_BRIDGE_RULE
    assert indirect['automatic_group_id'] == audit['case_id']
    by_id = {r['submission_id']: dict(r, child_id='child') for r in rows}
    assert build_groups(by_id, {c['case_id']: c for c in cases}, [], POLICY) == {}


def test_disabled_flag_reproduces_pending_bridge():
    groups, cases, _ = link_records(bridge(), [], {**POLICY, 'allow_contact_bridge_components': False})
    assert groups == [['a'], ['b'], ['c']]
    assert all(c['status'] == 'pending' for c in cases)


def test_connected_subgraph_inside_unresolved_group_does_not_auto_pass():
    rows = bridge() + [rec('d', 300, phone_value='85432109')]
    groups, cases, _ = link_records(rows, [], POLICY)
    assert groups == [['a'], ['b'], ['c'], ['d']]
    assert not any(c['kind'] == 'identity_group' for c in cases)


def test_enabled_subgroup_passes_without_joining_or_rejecting_isolated_record():
    rows = bridge() + [rec('d', 300, phone_value='85432109')]
    groups, cases, _ = link_records(rows, [], SUBGROUP_POLICY)
    assert groups == [['a', 'b', 'c'], ['d']]
    audit = next(c for c in cases if c['kind'] == 'identity_group')
    proof = audit['component_evidence']
    assert proof['members'] == ['a', 'b', 'c']
    assert proof['scope'] == 'contact_subgroup' and proof['format'] == 2
    assert proof['review_group_id'] != audit['case_id']
    assert all(c['status'] == 'confirmed' for c in cases if c.get('record_b') and
               {c['record_a'], c['record_b']} <= {'a', 'b', 'c'})
    assert all(c['status'] == 'pending' for c in cases if c.get('record_b') and
               'd' in {c['record_a'], c['record_b']})
    children = {sid: str(i) for i, ids in enumerate(groups) for sid in ids}
    remaining = build_groups({r['submission_id']:dict(r, child_id=children[r['submission_id']]) for r in rows},
        {c['case_id']:c for c in cases}, [], SUBGROUP_POLICY)
    group = next(iter(remaining.values()))['group_review']
    assert group['issue'] == 'contact_gap'
    assert group['contact_components'] == [['a', 'b', 'c'], ['d']]
    assert len(group['unresolved_pairs']) == 3  # a-c is an accepted indirect link, not review work.


@pytest.mark.parametrize('reverse', [False, True])
def test_multiple_contact_subgroups_pass_independently_with_same_demographics(reverse):
    first = bridge()
    second = bridge()
    for r in second:
        r.update(submission_id='x'+r['submission_id'], version_id='x'+r['version_id'])
        r['answer']['contact_01'] = '85432109' if r['submission_id'] != 'xc' else '73451280'
        if r['submission_id'] == 'xb':r['answer']['contact_02'] = '73451280'
    rows = first + second + [rec('z', phone_value='54321987')]
    groups, cases, _ = link_records(list(reversed(rows)) if reverse else rows, [], SUBGROUP_POLICY)
    assert groups == [['a','b','c'], ['xa','xb','xc'], ['z']]
    assert sum(c['kind'] == 'identity_group' for c in cases) == 2
    assert not any(c['status'] == 'rejected' for c in cases)


def test_manual_nonmatch_across_subgroups_does_not_block_safe_internal_links():
    rows = bridge() + [rec('d', 300, phone_value='85432109')]
    groups, cases, _ = link_records(rows, [decision(rows[0], rows[3], 'UNLINK')], SUBGROUP_POLICY)
    assert groups == [['a','b','c'], ['d']]
    assert next(c for c in cases if {c['record_a'],c['record_b']} == {'a','d'})['status'] == 'rejected'


@pytest.mark.parametrize('policy', [POLICY, SUBGROUP_POLICY])
@pytest.mark.parametrize('field,value', [('dob', None), ('dob', '2012-99-01'),
    ('gender', None), ('gender', '2'), ('school', None)])
def test_incomplete_identity_in_manual_component_blocks_new_bridge(field, value, policy):
    rows = bridge()
    extra = rec('d', 300, phone_value='85432109', **{field: value})
    manual = decision(rows[0], extra, 'LINK')
    groups, cases, _ = link_records(rows + [extra], [manual], policy)
    assert groups == [['a', 'd'], ['b'], ['c']]
    assert not any(c['kind'] == 'identity_group' for c in cases)


@pytest.mark.parametrize('policy', [POLICY, SUBGROUP_POLICY])
@pytest.mark.parametrize('field,value', [('dob', '2013-01-01'), ('gender', '1')])
def test_entire_manual_component_is_checked_for_contradictions(field, value, policy):
    rows = bridge()
    extra = rec('d', 300, phone_value='85432109', **{field: value})
    groups, cases, _ = link_records(rows + [extra], [decision(rows[0], extra, 'LINK')], policy)
    assert groups == [['a', 'd'], ['b'], ['c']]
    assert not any(c['kind'] == 'identity_group' for c in cases)


@pytest.mark.parametrize('policy', [POLICY, SUBGROUP_POLICY])
def test_manual_nonmatch_between_indirect_endpoints_blocks_complete_component(policy):
    rows = bridge()
    groups, cases, _ = link_records(rows, [decision(rows[0], rows[2], 'UNLINK')], policy)
    assert groups == [['a'], ['b'], ['c']]
    assert not any(c['kind'] == 'identity_group' for c in cases)
    assert next(c for c in cases if {c['record_a'], c['record_b']} == {'a', 'c'})['status'] == 'rejected'


@pytest.mark.parametrize('policy', [POLICY, SUBGROUP_POLICY])
def test_changed_manual_evidence_prevents_automatic_reconfirmation(policy):
    rows = bridge()
    old = decision(rows[0], rows[2], 'LINK')
    old['payload']['evidence_a']['dob'] = '2013-01-01'
    groups, cases, events = link_records(rows, [old], policy)
    assert groups == [['a'], ['b'], ['c']]
    assert events[0]['status'] == 'reopened'
    assert not any(c['kind'] == 'identity_group' for c in cases)


def test_odd_five_responses_select_waves_without_forcing_duplicate_or_even_count():
    rows = bridge()
    rows[0]['role'] = 'student'
    rows[1]['role'] = 'parent'
    rows[2]['role'] = 'student'
    p0 = copy.deepcopy(rows[1]);p0.update(submission_id='p0', version_id='v_p0', observed_at=rec('x', 1)['observed_at'])
    p1 = copy.deepcopy(rows[1]);p1.update(submission_id='p1', version_id='v_p1', observed_at=rows[2]['observed_at'])
    rows += [p0, p1]
    for r in rows:
        if r['role'] == 'parent':r['answer']['adult_demographics_05'] = None
    groups, _, _ = link_records(rows, [], POLICY)
    assert groups == [sorted(r['submission_id'] for r in rows)]
    selected, _ = select_waves(rows, {r['submission_id']: 'child' for r in rows},
        parent_requires_same_adult=True, matching_policy=POLICY, parent_wave_policy=PARENT_POLICY)
    assert len(selected) == 5
    assert {(r['role'], r['selected_wave']): r['submission_id'] for r in selected if r['selected_wave']} == {
        ('student','T0'):'a', ('student','T1'):'c', ('parent','T0'):'p0', ('parent','T1'):'p1'}
    assert next(r for r in selected if r['submission_id']=='b')['status'] == 'extra_followup'
    assert not any(r.get('duplicate_of') for r in selected)


def test_accepted_phone_typo_and_school_transfer_can_connect_whole_group():
    rows = [rec('a'), rec('b', 120, phone_value='61234568'),
            rec('c', 240, phone_value='61234568', school='New School')]
    assert link_records(rows, [], POLICY)[0] == [['a', 'b', 'c']]


def test_same_child_group_does_not_imply_same_adult():
    from study2.respondents import classify_adult
    rows = bridge()
    rows[0]['role'] = rows[2]['role'] = 'parent'
    rows[0]['answer']['adult_demographics_05'] = '1980'
    rows[2]['answer']['adult_demographics_05'] = '1975'
    assert link_records(rows, [], POLICY)[0] == [['a', 'b', 'c']]
    assert classify_adult(rows[0], rows[2], POLICY)[0] == 'rejected'


def test_shared_contact_does_not_join_sibling_components_with_different_birthdays():
    first = bridge()
    second = bridge()
    for r in second:
        r.update(submission_id='sibling_'+r['submission_id'], dob='2013-02-02')
    groups, cases, _ = link_records(first+second, [], POLICY)
    assert groups == [['a','b','c'], ['sibling_a','sibling_b','sibling_c']]
    assert sum(c['kind']=='identity_group' for c in cases) == 2


def test_known_nonmatch_label_still_blocks_pipeline_publication(project):
    from study2.common import PipelineError, dumps, utcnow
    from study2.store import connect, current
    cfg, _, rows, _ = project
    cfg['matching_policy'] = {**POLICY, 'allow_contact_bridge_components': False}
    for r in rows:
        r['answer']['contact_01'] = '61234567' if r['submission_id'] in {'s0','p0'} else '98765432'
        if r['submission_id']=='p0':r['answer']['contact_02'] = '98765432'
    baseline = execute(project)
    db = connect(Path(cfg['state_dir']))
    pair = next(json.loads(r[0]) for r in db.execute('SELECT payload_json FROM release_candidates WHERE release_id=?',(baseline['release_id'],))
                if {json.loads(r[0])['record_a'],json.loads(r[0])['record_b']}=={'s0','s1'})
    with db:
        db.execute('INSERT INTO labels VALUES(?,?,?,?,?,?)',(pair['case_id'],'NONMATCH','Reviewer','Known false match',utcnow(),dumps(pair)))
    db.close()
    cfg['matching_policy'] = POLICY
    with pytest.raises(PipelineError,match='NONMATCH'):
        execute(project,force=True)
    db = connect(Path(cfg['state_dir']))
    assert current(db)['release_id'] == baseline['release_id']
    db.close()


def test_pipeline_exports_auditable_group_and_reuses_id_on_reordered_run(project):
    from study2.store import connect
    cfg, _, rows, _ = project
    cfg.update(matching_policy=POLICY, bd_requires_same_adult=True, parent_wave_policy=PARENT_POLICY)
    for r in rows:
        r['answer']['contact_01'] = '61234567' if r['submission_id'] in {'s0','p0'} else '98765432'
        if r['role']=='parent':
            r['answer'].update(adult_demographics_05=1980, contact_02='98765432')
    first = execute(project)
    assert first['auto_contact_bridge_groups'] == 1
    assert first['auto_contact_bridge_submissions'] == 4
    assert all(first[k] == 1 for k in ['A','B','C','D','AC','BD','E','F','EF'])
    folder = Path(cfg['release_dir'])/first['release_id']
    frame = pd.read_parquet(folder/'analysis.parquet')
    assert frame['identity_rules'].map(lambda s:CONTACT_BRIDGE_RULE in s.split(';')).all()
    assert len(pd.read_excel(folder/'automatic_child_groups.xlsx',sheet_name='自動確認群組')) == 1
    assert len(pd.read_excel(folder/'automatic_child_groups.xlsx',sheet_name='提交對應')) == 4
    db = connect(Path(cfg['state_dir']))
    original = [tuple(r) for r in db.execute('SELECT submission_id,child_id FROM identity_members WHERE run_id=? ORDER BY 1',(first['release_id'],))]
    proof = json.loads(db.execute("SELECT payload_json FROM release_candidates WHERE release_id=? AND json_extract(payload_json,'$.kind')='identity_group'",(first['release_id'],)).fetchone()[0])
    assert set(proof['component_evidence']['members']) == {'s0','s1','p0','p1'}
    assert db.execute('SELECT COUNT(*) FROM decisions').fetchone()[0] == 0
    db.close()
    rows.reverse()
    second = execute(project,force=True)
    assert second['auto_contact_bridge_groups'] == 1
    db = connect(Path(cfg['state_dir']))
    assert [tuple(r) for r in db.execute('SELECT submission_id,child_id FROM identity_members WHERE run_id=? ORDER BY 1',(second['release_id'],))] == original
    assert db.execute('SELECT COUNT(*) FROM submissions').fetchone()[0] == 4
    db.close()


def test_subgroup_upgrade_preserves_unrelated_permanent_id_and_leaves_only_cross_group_review(project):
    from study2 import review_core
    from study2.dyads import staged_rows
    from study2.store import connect
    cfg, _, rows, _ = project
    cfg.update(matching_policy=POLICY, bd_requires_same_adult=True, parent_wave_policy=PARENT_POLICY)
    for r in rows:
        r['answer']['contact_01'] = '61234567' if r['submission_id'] in {'s0','p0'} else '98765432'
        if r['submission_id'] == 'p0':r['answer']['contact_02'] = '98765432'
        if r['role'] == 'parent':r['answer']['adult_demographics_05'] = 1980
    for original, sid in [(rows[0], 'u0'), (rows[2], 'up')]:
        extra = copy.deepcopy(original)
        extra.update(submission_id=sid, version_id='v_'+sid, source_key=sid, raw_hash='v_'+sid)
        extra['answer']['contact_01'] = '85432109'
        extra['answer'].pop('contact_02', None)
        rows.append(extra)
    baseline = execute(project)
    db = connect(Path(cfg['state_dir']))
    child = db.execute('SELECT child_id FROM identity_members WHERE run_id=? AND submission_id=?',
                       (baseline['release_id'], 'u0')).fetchone()[0]
    registration = next(r for r in staged_rows(db, baseline['release_id']) if r.get('child_id') == child)
    assert registration['registration_state'] == 'active'
    db.close()
    cfg['matching_policy'] = SUBGROUP_POLICY
    changed = execute(project, force=True)
    assert changed['auto_contact_subgroups'] == 1
    assert changed['auto_contact_subgroup_submissions'] == 4
    assert (changed['A'], changed['C'], changed['E'], changed['F'], changed['EF']) == (2,1,2,1,1)
    db = connect(Path(cfg['state_dir']))
    same = next(r for r in staged_rows(db, changed['release_id']) if r.get('child_id') == child)
    assert same['dyad_id'] == registration['dyad_id'] and same['registration_state'] == 'active'
    context = review_core.Context(db,cfg)
    group = next(iter(context.group_cases.values()))['group_review']
    assert sorted(map(len, group['contact_components'])) == [2,4]
    assert len(group['unresolved_pairs']) == 8
    assert db.execute('SELECT COUNT(*) FROM decisions').fetchone()[0] == 0
    membership = [tuple(r) for r in db.execute('SELECT submission_id,child_id FROM identity_members WHERE run_id=? ORDER BY 1',
                                              (changed['release_id'],))]
    db.close()
    review_core.register_review_evidence(cfg,next(iter(context.group_cases)), '既有收集紀錄',
        '合成測試收集紀錄第 7 行', '核對兩個已確認子群是否有同一孩子的收集編號')
    package = review_core.create_package(cfg, 'synthetic helper', Path(cfg['state_dir'])/'subgroups.xlsx')
    from openpyxl import load_workbook
    book = load_workbook(Path(cfg['state_dir'])/'subgroups.xlsx')
    text_values = '\n'.join(str(c.value) for row in book['群組參考'] for c in row if c.value)
    assert 'SG001' in text_values and 'SG002' in text_values
    assert '已確認子群內的間接連結' in text_values
    assert '只核實跨子群連結' in text_values
    book.close()
    assert len(package['tasks']) == 1
    rows.reverse()
    repeated = execute(project, force=True)
    db = connect(Path(cfg['state_dir']))
    assert [tuple(r) for r in db.execute('SELECT submission_id,child_id FROM identity_members WHERE run_id=? ORDER BY 1',
                                       (repeated['release_id'],))] == membership
    assert len(staged_rows(db, repeated['release_id'])) == len(staged_rows(db, changed['release_id']))
    db.close()
