import copy

import pytest

from study2.common import contacts
from study2.matching import select_waves
from study2.respondents import (_adult_evidence, adult_decision_state, adult_evidence,
                                adult_evidence_matches, adult_followups, adult_match)
from study2.review_excel import comparison
from test_approved_merged_rules import parent

FIELDS = ('contact_01', 'contact_02', 'contact_03.1', 'contact_03.2', 'contact_03.3', 'contact_03.4')


def profile(sid, day=0, relation=1, birth=1980, **values):
    r = parent(sid, day, relation=relation, birth=birth, personal='')
    r['answer'].update({k: '' for k in FIELDS})
    r['answer'].update(values)
    r['child_id'] = 'child'
    r['source_label'] = 'qualtrics_parent_t0'
    return r


@pytest.mark.parametrize('field', FIELDS)
@pytest.mark.parametrize('shared', ['+852 6123-4567', 'Person@Example.org'])
def test_any_contact_field_can_confirm_regardless_of_relationship(field, shared):
    a = profile('a', relation=0, **{field: shared})
    b = profile('b', 120, relation='', contact_02='62345678', **{'contact_03.4': 'person@example.org' if '@' in shared else '61234567'})
    assert adult_match(a, b)[0] == 'confirmed'


@pytest.mark.parametrize('separator', [';', '；', ',', '，', '/', '\n'])
def test_multiple_contacts_accept_one_exact_overlap(separator):
    a = profile('a', contact_02=separator.join(['61234567', '62345678', 'Person@Example.org']))
    b = profile('b', 120, contact_02='63456789', **{'contact_03.2': 'person@example.org'})
    assert set(adult_evidence(a)['all_contacts']) == {'61234567', '62345678', 'person@example.org'}
    assert adult_match(a, b) == ('confirmed', 'same_adult_reported_birth_any_exact_contact')


def test_different_personal_numbers_still_accept_shared_general_phone():
    a = profile('a', contact_01='61234567', contact_02='62345678')
    b = profile('b', 120, relation=0, contact_01='61234567', contact_02='63456789')
    assert adult_match(a, b) == ('confirmed', 'same_adult_reported_birth_any_exact_contact')


@pytest.mark.parametrize('birth', ['', 'invalid', 1899, 2027, 1981])
def test_shared_contact_never_bypasses_birth_year_requirements(birth):
    a = profile('a', contact_01='61234567')
    b = profile('b', 120, birth=birth, contact_01='61234567')
    assert adult_match(a, b)[0] != 'confirmed'


@pytest.mark.parametrize('other', ['61234568', 'person2@example.org', '6123456', 'invalid'])
def test_fuzzy_and_invalid_contacts_do_not_confirm(other):
    a = profile('a', contact_02='61234567;person@example.org')
    b = profile('b', 120, contact_02=other)
    assert adult_match(a, b) == ('pending', 'no_exact_adult_contact')


def test_same_year_contact_cannot_pair_different_children():
    a = profile('a', contact_01='61234567')
    b = profile('b', 120, contact_01='61234567')
    b['child_id'] = 'other-child'
    assert adult_match(a, b) == ('rejected', 'different_child_identity')


def decision(a, b, action, *, legacy=False):
    evidence = (lambda r: _adult_evidence(r, legacy=True)) if legacy else adult_evidence
    return {'decision_id': 'manual', 'payload': {'action': action,
        'record_a': a['submission_id'], 'record_b': b['submission_id'],
        'version_a': a['version_id'], 'version_b': b['version_id'],
        'evidence_a': evidence(a), 'evidence_b': evidence(b)}}


def test_legacy_decision_carries_only_with_proven_original_source():
    a = profile('a', contact_02='61234567;62345678;person@example.org')
    saved = _adult_evidence(a, legacy=True)
    assert adult_evidence_matches(a, saved, a['version_id'])
    assert not adult_evidence_matches(a, saved)
    assert not adult_evidence_matches(a, saved, 'changed-source')
    a['answer']['adult_demographics_05'] = 1981
    assert not adult_evidence_matches(a, saved, a['version_id'])


@pytest.mark.parametrize('legacy', [False, True])
def test_manual_nonmatch_blocks_short_repeat_and_bd(legacy):
    a = profile('a', contact_01='61234567')
    b = profile('b', 20, relation=0, contact_01='61234567')
    d = decision(a, b, 'UNLINK_ADULT', legacy=legacy)
    rows, _ = select_waves([a, b], {'a': 'child', 'b': 'child'}, parent_requires_same_adult=True, adult_decisions=[d])
    assert b['status'] == 'short_interval_followup' and not b.get('duplicate_of')
    b['observed_at'] = profile('later', 120)['observed_at']
    rows, _ = select_waves(rows, {'a': 'child', 'b': 'child'}, parent_requires_same_adult=True, adult_decisions=[d])
    pairs, cases, events = adult_followups(rows, [d])
    assert not pairs and any(c['rule'] == 'reviewer_rejected_same_adult' for c in cases)
    assert events[0]['status'] == 'applied'


def test_manual_link_preserves_direct_unknown_year_exception_in_repeats():
    a = profile('a', contact_01='61234567')
    b = profile('b', 20, birth=1981, contact_01='61234567')
    d = decision(a, b, 'LINK_ADULT')
    d['payload']['adult_identity_exception'] = {'type': 'accepted_typo_unknown_year', 'child_id': 'child'}
    rows, _ = select_waves([a, b], {'a': 'child', 'b': 'child'}, parent_requires_same_adult=True, adult_decisions=[d])
    assert b['status'] == 'short_repeat' and a['selected_wave'] == 'T0'
    assert all(r['adult_birth_year_status'] == 'unconfirmed' for r in rows)


def test_legacy_changed_source_reopens_instead_of_deduplicating():
    a = profile('a', contact_01='61234567')
    b = profile('b', 20, contact_01='61234567')
    d = decision(a, b, 'LINK_ADULT', legacy=True)
    b['version_id'] = 'updated-source'
    rows, _ = select_waves([a, b], {'a': 'child', 'b': 'child'}, parent_requires_same_adult=True, adult_decisions=[d])
    assert b['status'] != 'short_repeat'
    assert adult_decision_state(rows, [d])[2][0]['status'] == 'reopened'


def test_contact_bridges_do_not_confirm_multiple_inconsistent_adults():
    rows = [profile('a', contact_01='a@example.org;b@example.org'),
            profile('b', 120, contact_01='a@example.org'), profile('c', 160, contact_01='b@example.org')]
    rows, _ = select_waves(rows, {r['submission_id']: 'child' for r in rows}, parent_requires_same_adult=True)
    pairs, cases, _ = adult_followups(rows, [])
    assert not pairs and all(c['status'] == 'pending' for c in cases)


@pytest.mark.parametrize('days', [(0, 10, 20), (120, 130, 140)])
def test_contact_bridges_do_not_collapse_inconsistent_repeat_clusters(days):
    rows = [profile('a', days[0], contact_01='a@example.org;b@example.org'),
            profile('b', days[1], contact_01='a@example.org'),
            profile('c', days[2], contact_01='b@example.org')]
    if days[0]:
        rows.insert(0, profile('baseline', contact_01='a@example.org;b@example.org'))
    rows, _ = select_waves(rows, {r['submission_id']: 'child' for r in rows}, parent_requires_same_adult=True)
    by_id = {r['submission_id']: r for r in rows}
    assert by_id['b'].get('duplicate_of', 'b') != by_id['c'].get('duplicate_of', 'c')


def test_manual_nonmatch_cannot_be_bypassed_by_repeat_contact_bridge():
    rows = [profile('baseline', contact_01='shared@example.org')]
    rows += [profile(sid, day, contact_01='shared@example.org') for sid,day in [('a',120),('b',130),('c',140)]]
    manual = decision(rows[1], rows[3], 'UNLINK_ADULT')
    rows, _ = select_waves(rows, {r['submission_id']: 'child' for r in rows},
                           parent_requires_same_adult=True, adult_decisions=[manual])
    by_id = {r['submission_id']:r for r in rows}
    assert by_id['a'].get('duplicate_of', 'a') != by_id['c'].get('duplicate_of', 'c')


def test_contact_parsing_does_not_change_child_evidence_or_source_values():
    r = profile('a', contact_02='61234567；62345678')
    old = copy.deepcopy(r)
    assert not contacts(r['answer'])  # Existing child parser is deliberately unchanged.
    assert adult_evidence(r)['all_contacts'] == ['61234567', '62345678']
    assert r == old
    assert comparison(['61234567', '62345678'], ['62345678', '63456789']) == '部分相同（有共同聯絡）'
    assert comparison([], []) == '兩方缺失'
