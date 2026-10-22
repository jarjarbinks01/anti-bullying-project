"""Tests for the bounded English terminology catalogue.

The catalogue is presentation text only. These checks cover the package
acceptance items and the review findings for r1:

* unique semantic keys
* required navigation and first-tab coverage
* absence of contacts, credentials and private identifiers
* explicit missing-key behaviour
* the zero/unknown distinctions
* complete provenance rows for the scale family entries
* BD wording that keeps the adult continuity rule, the evidence source and
  the policy apart
* stage 2.1.5 wording that follows the recorded parent wave policy
* phq_band classified with the other PHQ metrics
* English instrument names that are not confirmed locally

A string being ASCII is not treated as evidence that an instrument name is
correct. The instrument names are checked against their provenance rows.
"""
import re

import pytest

from study2.static_english_catalog import (
    ALL_KEYS,
    BD_CONTINUITY,
    BD_CONTINUITY_STATUSES,
    BD_EVIDENCE_SOURCES,
    BD_EVIDENCE_SOURCE,
    BD_POLICIES,
    COUNT_UNITS,
    CORE_ENTRY_BUDGET,
    EVIDENCE,
    EVIDENCE_STATUSES,
    FIRST_TAB,
    NAVIGATION,
    SAMPLES,
    SCALE_FAMILY,
    SCALE_FAMILY_UNCONFIRMED,
    SCHOOL_STATUS,
    STAGES,
    TEXT,
    VALUE_STATES,
    MissingTermError,
    bd_continuity_text,
    bd_evidence_source_text,
    bd_sample_text,
    evidence,
    get,
    has,
    require,
    scale_family_label,
    stage_2_1_5_text,
    text,
    unconfirmed_expansion,
    validate_catalogue,
    value_state,
)

CJK = re.compile(r'[\u3400-\u9fff\u3000-\u303f\uff00-\uffef]')
EMAIL = re.compile(r'[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}')
LONG_DIGITS = re.compile(r'\d{8,}')
URL = re.compile(r'https?://|\bwww\.', re.IGNORECASE)
LOCAL_PATH = re.compile(r'(/(?:Users|home|Volumes)/|[A-Za-z]:\\\\)')
SECRET_ASSIGNMENT = re.compile(
    r'(?i)\b(api[_-]?key|secret|token|bearer|authorization|password)\b\s*[=:]')
UUID = re.compile(r'(?i)\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b')
SCHOOL_NAME = re.compile(r'\b(?:Primary|Secondary|Middle|Government)\s+School\b')

# Access material that must never travel inside interface text.
PRIVATE_IDENTIFIERS = (
    'STUDY2_ACCESS_PASSWORD',
    'STUDY2_SESSION_SECRET',
    'STUDY2_LOCAL_PREVIEW',
    'study2_local_session',
    '__Host-study2_session',
    '/api/auth',
)

REQUIRED_NAVIGATION = (
    'nav.data_quality_and_progress',
    'nav.descriptive_statistics',
    'nav.independent_parent_analysis',
    'nav.matching_evidence',
    'nav.family_tracking',
    'nav.definitions_and_methods',
)

REQUIRED_FIRST_TAB = (
    'first_tab.filter_sources',
    'first_tab.filter_survey_versions',
    'first_tab.filter_date_from',
    'first_tab.filter_date_to',
    'first_tab.filter_include_unknown_dates',
    'first_tab.filter_unknown_dates_note',
    'first_tab.filter_reset',
    'first_tab.select_all_versions',
    'first_tab.facet_availability_label',
    'first_tab.selected_count_label',
    'first_tab.selection_caption',
    'first_tab.reverse_date_error',
    'first_tab.missing_name_option',
)

REQUIRED_SAMPLES = ('sample.a', 'sample.b', 'sample.c', 'sample.d',
                    'sample.ac', 'sample.bd', 'sample.e', 'sample.f',
                    'sample.ef')

# Each final sample must state the responses it requires. The label is the
# only place a reader can see the membership rule, so the rule cannot be
# reduced to the sample code alone.
REQUIRED_SAMPLE_MEMBERSHIP = {
    'sample.a': ('A', ('student', 'T0')),
    'sample.b': ('B', ('parent', 'T0')),
    'sample.c': ('C', ('student', 'T1')),
    'sample.d': ('D', ('parent', 'T1')),
    'sample.ac': ('AC', ('student', 'T0', 'T1')),
    'sample.bd': ('BD', ('parent', 'T0', 'T1')),
    'sample.e': ('E', ('student', 'parent', 'T0')),
    'sample.f': ('F', ('student', 'parent', 'T1')),
    'sample.ef': ('EF', ('student', 'parent', 'wave')),
    'sample.parent_child_longitudinal': (None, ('parent', 'T0', 'T1')),
}

# The published parent wave policies, plus an unknown token.
PARENT_WAVE_POLICIES = (
    ('', 'stage.2_1_5.policy_default'),
    ('student_anchored_hk_v1', 'stage.2_1_5.policy_student_anchored_v1'),
    ('student_anchored_hk_nearest_v2',
     'stage.2_1_5.policy_student_anchored_nearest_v2'),
)

# English names of the instruments and their subscales. None of them is
# established by a local codebook, so each one must be marked as still to be
# confirmed.
UNCONFIRMED_ENGLISH_NAMES = (
    'scale.family.phq',
    'scale.family.sec',
    'scale.phq.anxiety',
    'scale.phq.depression',
    'scale.phq.total',
    'scale.phq.band',
    'scale.fqol.total',
    'scale.fqol.family_interaction',
    'scale.fqol.parenting',
    'scale.fqol.emotional_wellbeing',
    'scale.fqol.physical_wellbeing',
    'scale.sec.total',
    'scale.sec.responsible_decision_making',
    'scale.sec.social_awareness',
    'scale.sec.self_management',
    'scale.sec.relationship_skills',
    'scale.sec.self_awareness',
    'scale.bullying.tbv',
    'scale.bullying.tbp',
    'scale.bullying.cbv',
    'scale.bullying.cbp',
)


def test_catalogue_is_internally_consistent():
    assert validate_catalogue() == []


def test_semantic_keys_are_unique_and_every_entry_has_text():
    seen = {}
    for group in (NAVIGATION, FIRST_TAB, STAGES, SAMPLES, BD_CONTINUITY,
                  BD_EVIDENCE_SOURCE, COUNT_UNITS, VALUE_STATES, SCHOOL_STATUS,
                  SCALE_FAMILY):
        for key, value in group.items():
            assert key not in seen, f'duplicate semantic key {key}'
            seen[key] = group
            assert isinstance(value, str) and value.strip(), key
    assert len(TEXT) == len(seen)
    assert len(set(TEXT)) == len(TEXT)


def test_core_entry_budget_is_respected():
    assert len(TEXT) <= CORE_ENTRY_BUDGET
    assert 80 <= len(TEXT) <= 120


def test_navigation_covers_all_six_static_tabs():
    for key in REQUIRED_NAVIGATION:
        assert key in NAVIGATION
        assert NAVIGATION[key] == TEXT[key]
        assert NAVIGATION[key].strip()


def test_first_tab_covers_the_contract_controls():
    for key in REQUIRED_FIRST_TAB:
        assert key in FIRST_TAB
        assert FIRST_TAB[key] == TEXT[key]
        assert FIRST_TAB[key].strip()


def test_the_nine_final_samples_are_all_defined():
    for key in REQUIRED_SAMPLES:
        assert key in SAMPLES
        assert SAMPLES[key] == TEXT[key]
    codes = {key.rsplit('.', 1)[1] for key in SAMPLES if key.startswith('sample.')}
    assert {'a', 'b', 'c', 'd', 'ac', 'bd', 'e', 'f', 'ef'} <= codes


def test_sample_definitions_state_their_membership_rule():
    for key, (code, tokens) in REQUIRED_SAMPLE_MEMBERSHIP.items():
        label = SAMPLES[key]
        if code is not None:
            assert label.startswith(code + ' '), \
                f'{key} does not start with its sample code'
        for token in tokens:
            assert token.lower() in label.lower(), \
                f'{key} does not state that it requires {token}'


def test_missing_key_behaviour_is_explicit():
    assert has('nav.matching_evidence') is True
    assert has('does.not.exist') is False
    assert get('does.not.exist') is None
    assert get('does.not.exist', 'fallback') == 'fallback'
    with pytest.raises(MissingTermError) as error:
        text('does.not.exist')
    assert 'does.not.exist' in str(error.value)
    with pytest.raises(MissingTermError):
        require('does.not.exist')
    with pytest.raises(MissingTermError):
        evidence('does.not.exist')


def test_no_missing_key_ever_returns_a_plausible_default():
    # A wrong key must not silently become a real sentence.
    for key in ('nav.not_a_tab', 'sample.Z', 'state.maybe'):
        assert key not in TEXT
        with pytest.raises(MissingTermError):
            text(key)


def test_zero_unknown_unavailable_none_and_not_reconciled_stay_distinct():
    values = {key: TEXT[key] for key in ('state.zero', 'state.unknown',
                                         'state.unavailable', 'state.none',
                                         'state.not_reconciled')}
    assert len(set(values.values())) == len(values)
    assert values['state.zero'] == '0'
    for key, value in values.items():
        if key == 'state.zero':
            continue
        assert not value.isdigit(), f'{key} must not look like a count'
    assert value_state(0) == 'state.zero'
    assert value_state(0.0) == 'state.zero'
    assert value_state(None) == 'state.none'
    assert value_state('') == 'state.unavailable'
    assert value_state('   ') == 'state.unavailable'
    assert value_state('whatever') == 'state.unknown'
    assert value_state(True) == 'state.unknown'


def test_the_four_counting_units_are_distinct():
    units = {key: TEXT[key] for key in ('unit.questionnaire_entries',
                                        'unit.identity_groups',
                                        'unit.longitudinal_cases',
                                        'unit.student_parent_dyads')}
    assert len(set(units.values())) == 4
    assert units['unit.questionnaire_entries'] == 'Questionnaire entries'
    assert units['unit.identity_groups'] == 'Identity groups'
    assert units['unit.longitudinal_cases'] == 'Longitudinal cases'
    assert units['unit.student_parent_dyads'] == 'Student-parent dyads'


def test_bd_continuity_requires_an_explicit_choice():
    assert bd_continuity_text('same_adult') == TEXT['bd.continuity.same_adult']
    assert bd_continuity_text('same_child_only') == \
        TEXT['bd.continuity.same_child_only']
    assert bd_continuity_text('not_established') == \
        TEXT['bd.continuity.not_established']
    for status in BD_CONTINUITY_STATUSES:
        assert f'bd.continuity.{status}' in BD_CONTINUITY
    # An unknown or missing status must raise, never fall back to "same adult".
    for status in ('', None, 'same_adult_confirmed', 'unknown_status'):
        with pytest.raises(MissingTermError):
            bd_continuity_text(status)


def test_same_adult_is_never_the_fallback_wording():
    fallback = TEXT['bd.continuity.not_established']
    assert 'same adult' not in fallback.lower()
    child_only = TEXT['bd.continuity.same_child_only']
    assert 'same adult' not in child_only.lower()
    assert 'not confirmed' in child_only.lower()


# --------------------------------------------------------------------------
# Review r1, P2-1: the BD wording must keep the adult continuity rule, the
# evidence source and the release policy apart.
# --------------------------------------------------------------------------

def test_bd_sample_label_is_neutral_until_the_policy_is_known():
    neutral = TEXT['sample.bd']
    assert 'same adult' not in neutral.lower()
    assert 'may differ' not in neutral.lower()
    assert bd_sample_text(None) == neutral
    assert bd_sample_text('') == neutral
    assert bd_sample_text('unrecognised_policy') == \
        TEXT['sample.bd.policy_unknown']


def test_bd_sample_label_follows_an_explicit_policy():
    assert bd_sample_text('same_adult') == TEXT['sample.bd.same_adult']
    assert 'same adult' in TEXT['sample.bd.same_adult'].lower()
    assert bd_sample_text('same_child') == TEXT['sample.bd.same_child']
    assert 'may differ' in TEXT['sample.bd.same_child'].lower()
    # The catalogue never chooses between the two supported policies.
    assert set(BD_POLICIES) == {'same_adult', 'same_child'}
    for key in BD_POLICIES.values():
        assert key in TEXT


def test_bd_sample_label_never_mislabels_the_same_child_set():
    # The published BD label is the same adult. The same-child wording belongs
    # to the separate parent-child longitudinal sample.
    assert 'same adult' in TEXT['sample.bd.same_adult'].lower()
    assert 'may differ' not in TEXT['sample.bd.same_adult'].lower()
    assert 'same child' in TEXT['sample.parent_child_longitudinal'].lower()
    assert 'may differ' in TEXT['sample.parent_child_longitudinal'].lower()
    assert 'same adult' not in TEXT['sample.parent_child_longitudinal'].lower()
    assert TEXT['sample.bd'] != TEXT['sample.parent_child_longitudinal']


def test_bd_continuity_does_not_claim_an_evidence_source():
    for status in BD_CONTINUITY_STATUSES:
        wording = bd_continuity_text(status).lower()
        for claim in ('reviewer', 'automatic rule', 'manually verified',
                      'confirmed by reviewer'):
            assert claim not in wording, \
                f'bd.continuity.{status} claims where the evidence came from'


def test_bd_evidence_source_is_separate_from_the_continuity():
    assert bd_evidence_source_text('automatic_rule') == \
        TEXT['bd.evidence.automatic_rule']
    assert bd_evidence_source_text('reviewer') == TEXT['bd.evidence.reviewer']
    assert bd_evidence_source_text('none') == TEXT['bd.evidence.none']
    for source in BD_EVIDENCE_SOURCES:
        assert f'bd.evidence.{source}' in BD_EVIDENCE_SOURCE
    for source in ('', None, 'unknown_source'):
        with pytest.raises(MissingTermError):
            bd_evidence_source_text(source)
    # The automatic rule can confirm the same adult on its own.
    automatic = TEXT['bd.evidence.automatic_rule'].lower()
    assert 'automatic' in automatic
    assert 'reviewer' not in automatic


# --------------------------------------------------------------------------
# Review r1, P2-2: the stage 2.1.5 text must follow the recorded policy.
# --------------------------------------------------------------------------

def test_stage_2_1_5_text_follows_the_parent_wave_policy():
    for policy, key in PARENT_WAVE_POLICIES:
        assert stage_2_1_5_text(policy) == TEXT[key]
    assert stage_2_1_5_text(None) == TEXT['stage.2_1_5.policy_default']
    assert stage_2_1_5_text('some_unknown_policy') == \
        TEXT['stage.2_1_5.policy_unknown']


def test_an_unknown_policy_is_not_guessed_as_the_90_day_rule():
    unknown = TEXT['stage.2_1_5.policy_unknown']
    # The text may name the 90-day rule in order to rule it out, but it must
    # not state a selection rule of its own.
    assert 'not recognised' in unknown.lower()
    assert 'at least 90 days later' not in unknown
    assert 'earliest' not in unknown.lower()
    default = TEXT['stage.2_1_5.policy_default']
    assert '90' in default


def test_the_current_policy_text_does_not_apply_the_90_day_rule_to_parents():
    nearest = TEXT['stage.2_1_5.policy_student_anchored_nearest_v2']
    # The 90-day rule belongs to the student. The parent has no threshold of
    # its own, and the parent baseline may be earlier than the student.
    assert 'closest' in nearest.lower()
    assert 'earlier' in nearest.lower()
    assert '90' in nearest
    assert 'parent' in nearest.lower()
    assert 'no 90-day threshold of its own' in nearest.lower()


def test_the_generic_stage_text_does_not_name_a_wave_rule():
    generic = TEXT['stage.2_1_5']
    assert '90' not in generic
    assert 'policy' in generic.lower()


# --------------------------------------------------------------------------
# Review r1, P3-1: phq_band belongs to the PHQ family.
# --------------------------------------------------------------------------

def test_phq_band_is_classified_with_the_phq_metrics():
    assert scale_family_label('phq_band') == TEXT['scale.family.phq']
    assert scale_family_label('phq_band') == scale_family_label('PHQ_total')
    assert scale_family_label('phq_band') == scale_family_label('PHQ_anxiety')


# --------------------------------------------------------------------------
# Review r1, P3-2: an English instrument name that is not confirmed locally
# must be marked as still to be confirmed.
# --------------------------------------------------------------------------

def test_unconfirmed_english_instrument_names_are_marked_as_such():
    for key in UNCONFIRMED_ENGLISH_NAMES:
        assert key in EVIDENCE, key
        assert EVIDENCE[key][2] == 'needs_codebook_confirmation', (
            f'{key} must be marked needs_codebook_confirmation, '
            f'not {EVIDENCE[key][2]}')


def test_the_fqol_family_wording_cites_the_mapping_comment():
    status, locator, note = EVIDENCE['scale.family.fqol'][2], \
        EVIDENCE['scale.family.fqol'][1], EVIDENCE['scale.family.fqol'][3]
    assert status == 'codebook_confirmed'
    assert 'Family Quality of Life' in locator or 'Family Quality of Life' in note
    assert 'panel_student_family_quality_of_life_' in locator


def test_a_confirmed_instrument_name_is_not_marked_as_unconfirmed():
    # The FQOL family wording is established by a local source field name, so
    # it is the one family label that is not waiting for confirmation.
    assert EVIDENCE['scale.family.fqol'][2] == 'codebook_confirmed'


def test_evidence_statuses_come_from_the_declared_vocabulary():
    for key, row in EVIDENCE.items():
        assert row[2] in EVIDENCE_STATUSES, key


def test_every_catalogue_key_has_a_provenance_row():
    for key in ALL_KEYS:
        assert key in EVIDENCE, f'{key} has no provenance row'
        assert evidence(key)['english_text'] == TEXT.get(
            key, SCALE_FAMILY_UNCONFIRMED.get(key, ''))


def test_instrument_expansions_are_not_asserted_as_verified():
    # The abbreviation is usable, the expansion is a proposal only.
    assert TEXT['scale.family.phq'].startswith('PHQ')
    assert TEXT['scale.family.fqol'].startswith('FQOL')
    assert TEXT['scale.family.sec'].startswith('SEC')
    for key in SCALE_FAMILY_UNCONFIRMED:
        assert key not in TEXT, f'{key} must not be shown by default'
        assert EVIDENCE[key][2] == 'needs_codebook_confirmation', key
    assert unconfirmed_expansion('scale.expansion.phq')
    with pytest.raises(MissingTermError):
        unconfirmed_expansion('scale.expansion.not_a_scale')


def test_instrument_names_are_backed_by_provenance_not_by_ascii():
    # The FQOL wording comes from a local source field name. PHQ and SEC have
    # no local English expansion, so their labels must not claim one.
    assert EVIDENCE['scale.family.fqol'][2] == 'codebook_confirmed'
    assert 'family_quality_of_life' in EVIDENCE['scale.family.fqol'][1]
    assert 'Patient Health Questionnaire' not in TEXT['scale.family.phq']
    assert 'Patient Health Questionnaire' not in TEXT['scale.family.sec']
    assert 'Patient Health Questionnaire' not in TEXT['scale.phq.total']
    assert 'Patient Health Questionnaire' not in TEXT['scale.phq.anxiety']


def test_scale_family_labels_resolve_from_variable_ids():
    assert scale_family_label('PHQ_total') == TEXT['scale.family.phq']
    assert scale_family_label('FQOL_total') == TEXT['scale.family.fqol']
    assert scale_family_label('SEC_total') == TEXT['scale.family.sec']
    assert scale_family_label('dem_child_age') == TEXT['scale.family.demographics']
    assert scale_family_label('TBV_mean') == TEXT['scale.family.bullying']
    assert scale_family_label('TBV_prevalence1') == TEXT['scale.family.bullying']
    assert scale_family_label('not_a_variable') is None


def test_no_contacts_credentials_or_private_identifiers_in_the_catalogue():
    for key, value in TEXT.items():
        assert not EMAIL.search(value), f'{key} looks like an email address'
        assert not LONG_DIGITS.search(value), f'{key} looks like a phone number'
        assert not URL.search(value), f'{key} contains a URL'
        assert not LOCAL_PATH.search(value), f'{key} contains a local path'
        assert not SECRET_ASSIGNMENT.search(value), \
            f'{key} looks like a credential assignment'
        assert not UUID.search(value), f'{key} looks like an identifier'
        assert not SCHOOL_NAME.search(value), \
            f'{key} looks like a translated school name'
        for identifier in PRIVATE_IDENTIFIERS:
            assert identifier not in value, \
                f'{key} contains the private identifier {identifier}'


def test_the_interface_is_english_only():
    for key, value in TEXT.items():
        assert not CJK.search(value), f'{key} still contains Chinese text'
        assert all(ord(char) < 128 for char in value), \
            f'{key} contains non-ASCII characters'


def test_no_research_data_is_carried_in_the_catalogue():
    # Original school names, survey-version names and questionnaire values stay
    # as data. The catalogue holds interface wording only.
    for key, value in TEXT.items():
        lowered = value.lower()
        for marker in ('.xlsx', '.csv', 'qualtrics export', 'survey name:'):
            assert marker not in lowered, f'{key} carries source data'
        assert 'school name:' not in lowered, f'{key} carries a school name'


def test_school_status_distinguishes_unknown_from_not_reconciled():
    unknown = TEXT['school.status.unknown_name']
    pending = TEXT['school.status.pending']
    not_reconciled = TEXT['school.status.not_reconciled']
    assert len({unknown, pending, not_reconciled}) == 3
    assert 'reconcil' not in unknown.lower()
    assert 'reconcil' not in pending.lower()
    assert 'reconcil' in not_reconciled.lower()
