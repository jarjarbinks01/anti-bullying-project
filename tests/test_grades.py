import copy
from itertools import product

import pandas as pd
import pytest

from study2.adapters import normalize_records
from study2.grades import Grade, legacy_grade, parse_grade
from study2.matching import identity_evidence, identity_evidence_matches, link_records
from study2.review_hints import grade_position, pair_review_hints
from test_identity_and_time import rec


@pytest.mark.parametrize('raw,number,stage', [
    ('F.1', 1, 'secondary'), ('f.6', 6, 'secondary'), ('S. 6', 6, 'secondary'),
    ('P.4', 4, 'primary'), ('Form 1', 1, 'secondary'), ('Form. 2 A', 2, 'secondary'),
    ('Ｐ．４', 4, 'primary'), ('Ｆ．１Ａ', 1, 'secondary'), ('中⼀', 1, 'secondary'),
    ('小學三年級', 3, 'primary'), ('中学二年级', 2, 'secondary'), ('五年级', 5, None),
    ('G3', 3, None), ('G5A', 5, None), ('g4b', 4, None), ('Year 1', 1, None),
    ('Y3', 3, None), ('1.0', 1, None), (1.0, 1, None), ('一仁', 1, None),
    ('5信', 5, None), ('四乙', 4, None), ('1C2', 1, None), ('5CL', 5, None),
    ('2c1', 2, None), ('三年班', 3, None), ('小一', 1, 'primary'), ('中六', 6, 'secondary')])
def test_explicit_grade_and_class_formats(raw, number, stage):
    assert parse_grade(raw) == Grade(number, stage)


@pytest.mark.parametrize('raw', [None, '', 'F', 'ID', '7', '9', '12', 'G7', 'G11', 'K3',
                                  '升中二', '升四年級', '小4升小5', '中三升中四', '小四–中二',
                                  'F1/F2', '1 OR 2', '1至2', '1.5', '男', '女', 'test',
                                  '3B arbitrary person name', '高二'])
def test_ambiguous_foreign_stage_and_non_grade_values_stay_missing(raw):
    assert parse_grade(raw) == Grade(None, None)


def test_all_v1_supported_formats_keep_the_same_grade():
    for prefix, digit, suffix, space in product(
            ('', 'PRIMARY', 'SECONDARY', 'FORM', 'GRADE', 'CLASS', 'P', 'S', 'F', '小', '中'),
            '123456一二三四五六', ('', 'A', '年級', '年', '級', '班', ' b'), ('', ' ')):
        raw = prefix + space + digit + suffix
        assert legacy_grade(raw) is not None, raw
        assert parse_grade(raw).number == legacy_grade(raw), raw


@pytest.mark.parametrize('role', ['student', 'parent'])
def test_normalization_preserves_original_grade_and_is_repeatable(role):
    r = rec('a', role=role)
    demo = 'student_demographics_' if role == 'student' else 'adult_demographics_'
    r['answer'].update({'school_from_' + role: 'Example School', demo + '01': 'F.1',
        demo + ('06' if role == 'student' else '03'): '2012-01-01',
        demo + ('03' if role == 'student' else '04'): '0', role + '_PHQ_01': 0})
    r['issues'] = ['grade_unclear']
    dictionary = pd.DataFrame([{'normalized_key': 'example school', 'action': 'map',
        'canonical_school_name': 'Example School', 'school_type': 'secondary'}])
    once, _ = normalize_records([r], dictionary)
    assert once[0]['grade'] == once[0]['answer'][demo + '01'] == 1
    assert once[0]['grade_raw'] == 'F.1'
    assert 'grade_unclear' not in once[0]['issues']
    original = copy.deepcopy(once)
    twice, _ = normalize_records(once, dictionary)
    assert twice == original


def test_progression_uses_the_same_parser_in_mixed_schools():
    a = rec('a', grade=6, grade_raw='Ｐ．６', school_type='primary & secondary')
    b = rec('b', day=240, grade=1, grade_raw='F.1', school_type='primary & secondary')
    assert grade_position(a) == (6, 'primary')
    assert grade_position(b) == (7, 'secondary')
    assert 'grade_decreased' not in pair_review_hints(a, b)['review_warning_codes']
    a.update(grade=3, grade_raw='G3')
    assert grade_position(a) == (None, None)


@pytest.mark.parametrize('start,end,first,last,transfer,warning', [
    ('2024-09-01T00:00:00+08:00', '2025-08-31T23:59:59+08:00', 'P.3', 'P.3', False, None),
    ('2024-09-01T00:00:00+08:00', '2025-08-31T23:59:59+08:00', 'P.3', 'P.4', False, 'grade_advance_exceeds_school_years'),
    ('2025-08-31T15:59:59+00:00', '2025-08-31T16:00:00+00:00', 'P.3', 'P.4', False, None),
    ('2025-06-01T00:00:00+08:00', '2025-09-01T00:00:00+08:00', 'P.3', 'P.4', False, None),
    ('2025-06-01T00:00:00+08:00', '2025-09-01T00:00:00+08:00', 'P.6', 'F.1', True, None),
    ('2025-06-01T00:00:00+08:00', '2025-07-01T00:00:00+08:00', 'P.6', 'F.1', True, 'grade_advance_exceeds_school_years')])
def test_confirmed_academic_year_and_primary_secondary_rules(start, end, first, last, transfer, warning):
    g0, g1 = parse_grade(first), parse_grade(last)
    a = rec('a', observed_at=start, grade=g0.number, grade_raw=first, school_type=g0.stage)
    b = rec('b', observed_at=end, grade=g1.number, grade_raw=last, school_type=g1.stage,
            school='New School' if transfer else a['school'])
    hints = pair_review_hints(a, b)['review_warning_codes']
    assert hints == ([warning] if warning else [])
    assert pair_review_hints(b, a)['review_warning_codes'] == hints
    # Progression is supporting information. Even an anomalous grade does not
    # veto complete DOB/sex and research-approved contact evidence.
    groups, cases, _ = link_records([a, b], [], {'allow_school_transfer': True})
    assert groups == [['a', 'b']] and cases[0]['status'] == 'confirmed'


def upgraded_record():
    old = rec('a', grade=None, grade_raw='F.1')
    saved = identity_evidence(old)
    return {**old, 'grade': 1}, saved


def test_parser_upgrade_recognises_existing_frozen_evidence():
    changed, saved = upgraded_record()
    assert identity_evidence_matches(changed, saved)
    b = rec('b', 120)
    decision = {'decision_id': 'old', 'payload': {'action': 'UNLINK', 'record_a': 'a', 'record_b': 'b',
        'evidence_a': saved, 'evidence_b': identity_evidence(b)}}
    groups, cases, events = link_records([changed, b], [decision])
    assert groups == [['a'], ['b']]
    assert events[0]['status'] == 'applied' and cases[0]['status'] == 'rejected'


@pytest.mark.parametrize('field', ['dob', 'gender', 'school', 'observed_at', 'contact', 'roll'])
def test_parser_compatibility_never_waives_other_evidence(field):
    changed, saved = upgraded_record()
    if field in ('contact', 'roll'):
        changed['answer']['contact_01' if field == 'contact' else 'student_demographics_02'] = 'other'
    else:
        changed[field] = 'other'
    assert not identity_evidence_matches(changed, saved)


def test_older_release_grade_evidence_remains_compatible_after_upgrade():
    changed, saved = upgraded_record()
    upgraded = identity_evidence(changed)
    changed['grade'] = None
    assert identity_evidence_matches(changed, upgraded)


@pytest.mark.parametrize('raw,grade', [('F.1', 2), ('unresolved', 1), ('3', None)])
def test_compatibility_requires_exact_parser_proof(raw, grade):
    changed, saved = upgraded_record()
    if grade is None:
        saved['grade'] = 3  # The v1 parser already knew this grade; no missing-value upgrade applies.
    changed.update(grade_raw=raw, grade=grade)
    assert not identity_evidence_matches(changed, saved)
