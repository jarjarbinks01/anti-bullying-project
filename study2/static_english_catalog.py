"""Bounded English terminology catalogue for the Study 2 static dashboard.

Scope is presentation text only. This module holds plain mappings and simple
lookup/validation helpers; it imports nothing from the research pipeline so the
static exporter can use it without pulling research dependencies.

Rules that shaped this file (see the package brief and COMMON_RULES.md):

* English only for interface text. Original school names, survey-version names
  and questionnaire values stay as data and are never translated here.
* ``Unknown``, ``Unavailable``, ``Not reconciled``, ``None`` and numeric zero
  are five different things and have five different entries.
* ``Questionnaire entries``, ``Identity groups``, ``Longitudinal cases`` and
  ``Student-parent dyads`` are four different units and have four different
  entries.
* BD wording is policy dependent. Every alternative is a separate entry and the
  lookup helper refuses to guess; "same adult" is never a fallback.
* Existing translations are candidates to reuse, not proof of official
  questionnaire terminology. Where only a variable key or a previous translation
  exists, the entry is marked ``needs_codebook_confirmation`` and the
  instrument's official English name is left unresolved.

Values are ASCII by design so that CSV exports and locale-independent rendering
stay predictable. Use ordinary hyphens in prose.
"""
from __future__ import annotations

CATALOGUE_VERSION = 'study2_static_english_v1'

# Maximum number of catalogue entries this package is allowed to implement.
CORE_ENTRY_BUDGET = 120

# ---------------------------------------------------------------------------
# Evidence vocabulary used by EVIDENCE and by the returned CSV.
#
# codebook_confirmed      the English wording is established by a local
#                         codebook, document or source questionnaire field name
# codebook_partial        abbreviation, item count or subscale structure is
#                         established locally; the official wording is not
# needs_codebook_confirmation
#                         only a variable key or a previous translation is
#                         available; the proposal must not be asserted as
#                         verified
# translation_proposal    a rendering of the research team's own Chinese label;
#                         no claim is made about an official instrument name
# interface_text          interface chrome with no instrument or research
#                         definition claim
# raw_data_retained       original data that must stay as it is: school names,
#                         survey-version names, questionnaire values and
#                         internal keys. It is inventoried, not translated.
# ---------------------------------------------------------------------------

EVIDENCE_STATUSES = (
    'codebook_confirmed',
    'codebook_partial',
    'needs_codebook_confirmation',
    'translation_proposal',
    'interface_text',
    'raw_data_retained',
)

# ---------------------------------------------------------------------------
# Navigation and application chrome
# ---------------------------------------------------------------------------

NAVIGATION = {
    'nav.data_quality_and_progress': 'Data quality & progress',
    'nav.descriptive_statistics': 'Descriptive statistics',
    'nav.independent_parent_analysis': 'Independent parent analysis',
    'nav.matching_evidence': 'Matching evidence',
    'nav.family_tracking': 'Family tracking',
    'nav.definitions_and_methods': 'Definitions & methods',
    'app.title': 'Study 2 Research Dashboard',
    'app.nav_aria_label': 'Study 2 research pages',
    'app.skip_to_content': 'Skip to content',
    'app.footer': 'HKU Study 2 anti-bullying research - read-only aggregate snapshot',
}

# ---------------------------------------------------------------------------
# First-tab (Data quality & progress) filter controls.
#
# Key names follow FILTER_CONTRACT_DRAFT.md: sources and survey versions are
# selected-key sets, date bounds are one-sided or two-sided, missing/unusable
# dates are excluded once a bound is enabled unless the respondent opts back in.
# ---------------------------------------------------------------------------

FIRST_TAB = {
    'first_tab.heading': 'Data quality & progress',
    'first_tab.intro': 'From submissions and identity confirmation to analysis '
                        'samples, check how this release is composed.',
    'first_tab.filter_sources': 'Sources',
    'first_tab.filter_survey_versions': 'Survey versions',
    'first_tab.filter_date_from': 'From date (inclusive)',
    'first_tab.filter_date_to': 'To date (inclusive)',
    'first_tab.filter_include_unknown_dates': 'Include entries with unknown dates',
    'first_tab.filter_unknown_dates_note': 'The date interval is not known to be '
                                            'satisfied for these entries.',
    'first_tab.filter_reset': 'Reset filters',
    'first_tab.select_all_versions': 'Select all versions',
    'first_tab.facet_availability_label': 'Available under the other active filters',
    'first_tab.selected_count_label': 'Selected results',
    'first_tab.selection_caption': 'Selection changes the displayed scope of '
                                    'published results. It does not recompute '
                                    'matching and does not change the other tabs.',
    'first_tab.reverse_date_error': 'The start date must not be later than the end date.',
    'first_tab.missing_name_option': '(Missing name)',
    'first_tab.missing_version_option': '(Missing survey version)',
    'first_tab.unidentified_source_option': 'Unidentified source',
    'first_tab.date_basis_label': 'Date basis',
}

# ---------------------------------------------------------------------------
# Pipeline stages
# ---------------------------------------------------------------------------

STAGES = {
    'stage.1_1': 'Register submissions and sources; keep the original version '
                 'for traceability',
    'stage.1_3_2_1_1_2_1_2': 'Standardise paper and online data and merge into '
                            'A-D; this release joins the merged files directly',
    'stage.2_1_3': 'Tidy school names, grades and answer codes; check submission '
                   'eligibility',
    'stage.2_1_4': 'Confirm the same child and the child each parent refers to; '
                   'build identity groups',
    'stage.2_1_5': 'Select the wave and handle short-interval repeats. The parent '
                   'wave rule depends on the policy recorded for this release.',
    'stage.2_1_5.policy_default': 'Fix the earliest T0, handle short-interval '
                                   'repeats, and select the latest T1 at least 90 days later',
    'stage.2_1_5.policy_student_anchored_v1': 'Students keep the earliest T0 and the '
                                              'latest T1 at least 90 days later; parents '
                                              'are split into waves by the student\'s '
                                              'Hong Kong date, and same-wave repeats are '
                                              'handled within the wave',
    'stage.2_1_5.policy_student_anchored_nearest_v2': 'Students keep the earliest T0 '
                                                       'and the latest T1 at least 90 days '
                                                       'later; the parent T1 is kept first, '
                                                       'then the parent baseline closest to '
                                                       'the student T0 is chosen (it may be '
                                                       'earlier than the student). The parent '
                                                       'has no 90-day threshold of its own.',
    'stage.2_1_5.policy_unknown': 'The parent wave policy for this release is not '
                                  'recognised. Do not read the 90-day rule as this '
                                  'release\'s parent wave rule.',
    'stage.2_1_6': 'Apply approved manual corrections; keep correction and '
                   'exclusion records',
    'stage.3_1_1': 'Output per-wave student and parent responses and the AC/BD '
                   'longitudinal samples',
    'stage.3_1_2_3_1_3': 'Build the per-wave parent-child E/F samples and the '
                         'two-wave parent-child EF sample',
    'stage.group_1': 'Import and standardisation',
    'stage.group_2': 'School names and submission eligibility',
    'stage.group_3': 'Identity, repeats and manual corrections',
    'stage.group_4': 'Final responses and pairings',
    'stage.not_provided': 'Not provided in this release',
    'stage.unit_note': 'Stages count submissions, identity groups or pairs. '
                        'These counts are not the same unit and cannot be added.',
}

# ---------------------------------------------------------------------------
# Sample definitions.
#
# The nine final samples are A, B, C, D, AC, BD, E, F and EF. The wording keeps
# the membership rule visible: which response is required in which wave.
# ---------------------------------------------------------------------------

SAMPLES = {
    'sample.a': 'A | All student T0 responses',
    'sample.b': 'B | All parent T0 responses',
    'sample.c': 'C | All student T1 responses',
    'sample.d': 'D | All parent T1 responses (the responding parent may differ)',
    'sample.ac': 'AC | Student T0 and T1 from the same student',
    'sample.bd': 'BD | Parent T0 and T1',
    'sample.bd.same_adult': 'BD | Parent T0 and T1 from the same adult',
    'sample.bd.same_child': 'BD | Parent T0 and T1 for the same child '
                            '(the responding adult may differ)',
    'sample.bd.policy_unknown': 'BD | Parent T0 and T1 (the adult continuity rule '
                                 'for this release is not established)',
    'sample.e': 'E | Student and parent at T0',
    'sample.f': 'F | Student and parent at T1',
    'sample.ef': 'EF | Student and parent at both waves (four responses)',
    'sample.parent_child_longitudinal': "Same child's parent T0 and T1 "
                                        '(the responding parent may differ)',
    'sample.unit_note': 'Each count is a formal sample unit. Candidate '
                        'comparisons are counted separately and are not final '
                        'sample counts.',
}

# ---------------------------------------------------------------------------
# BD (adult continuity) wording.
#
# Adult continuity and the source of the evidence are two different facts and
# are kept apart. The current automatic adult rule can confirm the same adult
# (valid and matching birth year plus an exact contact match), so a continuity
# statement must not imply that a reviewer decided it.
#
# These are alternatives, not a list to pick from casually. The lookup helpers
# require an explicit status and raise on anything else, so a caller with
# missing policy metadata can never silently show "same adult".
# ---------------------------------------------------------------------------

BD_CONTINUITY = {
    'bd.continuity.label': 'Adult continuity between waves',
    'bd.continuity.same_adult': 'The same adult responded at T0 and T1',
    'bd.continuity.same_child_only': 'The same child is tracked across waves, '
                                     'but the responding adult is not confirmed '
                                     'to be the same person',
    'bd.continuity.not_established': 'Adult continuity between waves is not '
                                     'established by the available evidence',
}

# The source of the continuity evidence, kept separate from the continuity
# statement itself. A caller may combine one continuity status with one
# evidence source, or omit the evidence source entirely.
BD_EVIDENCE_SOURCE = {
    'bd.evidence.label': 'Source of the continuity evidence',
    'bd.evidence.automatic_rule': 'The automatic adult rule: the same confirmed '
                                   'child, a valid and matching adult birth year, '
                                   'and an exact match on at least one contact field',
    'bd.evidence.reviewer': 'A reviewer decision',
    'bd.evidence.none': 'No continuity evidence source is recorded',
}

# Status values accepted by bd_continuity_text().
BD_CONTINUITY_STATUSES = (
    'same_adult',
    'same_child_only',
    'not_established',
)

# Evidence-source values accepted by bd_evidence_source_text().
BD_EVIDENCE_SOURCES = (
    'automatic_rule',
    'reviewer',
    'none',
)

# BD membership rules that the catalogue can name. The value is the policy
# token the caller holds, not a decision the catalogue makes.
BD_POLICIES = {
    'same_adult': 'sample.bd.same_adult',
    'same_child': 'sample.bd.same_child',
}

# ---------------------------------------------------------------------------
# Counting units.
#
# These four are different units and are never interchangeable.
# ---------------------------------------------------------------------------

COUNT_UNITS = {
    'unit.questionnaire_entries': 'Questionnaire entries',
    'unit.identity_groups': 'Identity groups',
    'unit.longitudinal_cases': 'Longitudinal cases',
    'unit.student_parent_dyads': 'Student-parent dyads',
    'unit.note': 'Questionnaire entries, identity groups, longitudinal cases and '
                 'student-parent dyads are different units. Counts in different '
                 'units cannot be added together.',
}

# ---------------------------------------------------------------------------
# Value states.
#
# Unknown, Unavailable, Not reconciled, None and numeric zero are deliberately
# five separate entries.
# ---------------------------------------------------------------------------

VALUE_STATES = {
    'state.unknown': 'Unknown',
    'state.unavailable': 'Unavailable',
    'state.not_reconciled': 'Not reconciled',
    'state.none': 'None',
    'state.zero': '0',
    'state.not_provided': 'Not provided',
    'state.suppressed': 'Suppressed (small sample)',
    'state.not_collected': 'Not collected',
    'state.note': 'Unknown means the value is not known. Unavailable means it '
                  'cannot be provided here. Not reconciled means a decision '
                  'record is missing. None means no value was recorded. 0 is a '
                  'real count and is never a substitute for any of them.',
}

# ---------------------------------------------------------------------------
# School review status messages
# ---------------------------------------------------------------------------

SCHOOL_STATUS = {
    'school.status.unknown_name': 'School name not recognised',
    'school.status.pending': 'School name pending review',
    'school.status.not_reconciled': 'School review not reconciled',
    'school.status.mainstream': 'Mainstream school',
    'school.status.non_mainstream': 'Non-mainstream school',
    'school.status.stage_unknown': 'School stage not determined',
    'school.scope.all': 'All schools (first-page basis)',
    'school.scope.mainstream_only': 'Mainstream schools only',
    'school.counts.in_current_scope': 'Records in the current scope',
    'school.counts.reviewed_release_wide': 'Schools reviewed in this release '
                                           '(all scopes)',
    'school.counts.note': 'Completed review counts cover the whole release. '
                          'Current record counts respond to the active filters.',
}

# ---------------------------------------------------------------------------
# Scale families and subscales.
#
# SCALE_FAMILY holds the label that can be shown today. SCALE_FAMILY_UNCONFIRMED
# holds proposed expansions of the abbreviations. The expansion of PHQ and SEC
# is not established anywhere in this repository, so it must not be presented as
# the official instrument name until the research team confirms it.
# ---------------------------------------------------------------------------

SCALE_FAMILY = {
    'scale.family.all': 'All scales',
    'scale.family.phq': 'PHQ (mental health)',
    'scale.family.fqol': 'FQOL family quality of life',
    'scale.family.sec': 'SEC (social-emotional competence)',
    'scale.family.bullying': 'Bullying indicators',
    'scale.family.demographics': 'Participant characteristics',
    'scale.phq.anxiety': 'PHQ anxiety',
    'scale.phq.depression': 'PHQ depression',
    'scale.phq.total': 'PHQ total',
    'scale.phq.band': 'PHQ total-score categories',
    'scale.fqol.total': 'FQOL total',
    'scale.fqol.family_interaction': 'FQOL family interaction',
    'scale.fqol.parenting': 'FQOL parenting',
    'scale.fqol.emotional_wellbeing': 'FQOL emotional well-being',
    'scale.fqol.physical_wellbeing': 'FQOL physical and material well-being',
    'scale.sec.total': 'SEC total',
    'scale.sec.responsible_decision_making': 'SEC responsible decision-making',
    'scale.sec.social_awareness': 'SEC social awareness',
    'scale.sec.self_management': 'SEC self-management',
    'scale.sec.relationship_skills': 'SEC relationship skills',
    'scale.sec.self_awareness': 'SEC self-awareness',
    'scale.bullying.tbv': 'Traditional bullying victimisation',
    'scale.bullying.tbp': 'Traditional bullying perpetration',
    'scale.bullying.cbv': 'Cyberbullying victimisation',
    'scale.bullying.cbp': 'Cyberbullying perpetration',
}

# Proposed expansions of the abbreviations. Not shown by default.
SCALE_FAMILY_UNCONFIRMED = {
    'scale.expansion.phq': 'Patient Health Questionnaire-4 (PHQ-4)',
    'scale.expansion.fqol': 'Family Quality of Life scale (FQOL)',
    'scale.expansion.sec': 'Full English name of the SEC instrument is not '
                            'established in this repository',
}

# Variable-id prefixes that belong to each scale family.
SCALE_FAMILY_BY_PREFIX = (
    ('PHQ_', 'scale.family.phq'),
    ('FQOL_', 'scale.family.fqol'),
    ('SEC_', 'scale.family.sec'),
)

# ---------------------------------------------------------------------------
# Merged catalogue
#
# Export and download labels, login and error strings are outside the core
# entry budget. Their proposed English lives in the coverage inventory that
# accompanies this module, not here.
# ---------------------------------------------------------------------------

TEXT = {}
for _group in (NAVIGATION, FIRST_TAB, STAGES, SAMPLES, BD_CONTINUITY,
               BD_EVIDENCE_SOURCE, COUNT_UNITS, VALUE_STATES, SCHOOL_STATUS,
               SCALE_FAMILY):
    TEXT.update(_group)
del _group

# Every semantic key this package knows about, including the proposals that
# are deliberately kept out of the default text.
ALL_KEYS = frozenset(TEXT) | frozenset(SCALE_FAMILY_UNCONFIRMED)

# ---------------------------------------------------------------------------
# Provenance
#
# One row per catalogue entry. source_file and source_locator are generic code
# paths only. There are no participant content and no machine-local paths.
# ---------------------------------------------------------------------------

_EV = (
    'study2/static_assets.py',
    'study2/dashboard_views.py',
    'study2/descriptive_spec.py',
    'study2/outputs.py',
    'mappings/2.1.1_produce_ABCD.py',
)

EVIDENCE = {
    # Navigation -------------------------------------------------------------
    'nav.data_quality_and_progress': (
        'study2/static_assets.py', 'APP_JS:tabs', 'interface_text',
        'Existing tab label; same order as the static page tabs.'),
    'nav.descriptive_statistics': (
        'study2/static_assets.py', 'APP_JS:tabs', 'interface_text',
        'Existing tab label.'),
    'nav.independent_parent_analysis': (
        'study2/static_assets.py', 'APP_JS:tabs', 'interface_text',
        'Existing tab label.'),
    'nav.matching_evidence': (
        'study2/static_assets.py', 'APP_JS:tabs', 'interface_text',
        'Existing tab label.'),
    'nav.family_tracking': (
        'study2/static_assets.py', 'APP_JS:tabs', 'interface_text',
        'Existing tab label.'),
    'nav.definitions_and_methods': (
        'study2/static_assets.py', 'APP_JS:tabs', 'interface_text',
        'Existing tab label.'),
    'app.title': (
        'study2/static_assets.py', 'HTML:title', 'interface_text',
        'Existing document title.'),
    'app.nav_aria_label': (
        'study2/static_assets.py', 'HTML:nav[aria-label]', 'interface_text',
        'Existing landmark label.'),
    'app.skip_to_content': (
        'study2/static_assets.py', 'HTML:a.skip', 'interface_text',
        'Existing skip link.'),
    'app.footer': (
        'study2/static_assets.py', 'HTML:footer', 'interface_text',
        'Existing footer strapline; punctuation normalised to ASCII.'),

    # First-tab controls -----------------------------------------------------
    'first_tab.heading': (
        'study2/static_assets.py', 'APP_JS:overview/pageHeading', 'interface_text',
        'First-tab heading in the current static build.'),
    'first_tab.intro': (
        'study2/static_assets.py', 'APP_JS:overview/pageHeading', 'interface_text',
        'First-tab caption in the current static build.'),
    'first_tab.filter_sources': (
        'FILTER_CONTRACT_DRAFT.md', 'Selection', 'interface_text',
        'Contract requires an explicit source selected-key set.'),
    'first_tab.filter_survey_versions': (
        'FILTER_CONTRACT_DRAFT.md', 'Selection', 'interface_text',
        'Contract requires an explicit survey-version selected-key set.'),
    'first_tab.filter_date_from': (
        'FILTER_CONTRACT_DRAFT.md', 'Selection', 'interface_text',
        'Inclusive lower bound; one-sided bounds allowed.'),
    'first_tab.filter_date_to': (
        'FILTER_CONTRACT_DRAFT.md', 'Selection', 'interface_text',
        'Inclusive upper bound; one-sided bounds allowed.'),
    'first_tab.filter_include_unknown_dates': (
        'FILTER_CONTRACT_DRAFT.md', 'Selection', 'interface_text',
        'Explicit opt-in named in the contract.'),
    'first_tab.filter_unknown_dates_note': (
        'FILTER_CONTRACT_DRAFT.md', 'Selection', 'interface_text',
        'Contract requires the statement that the interval is not known to hold.'),
    'first_tab.filter_reset': (
        'study2/static_assets.py', 'APP_JS:controls/reset', 'interface_text',
        'Existing reset button wording for the analysis sidebar.'),
    'first_tab.select_all_versions': (
        'FILTER_CONTRACT_DRAFT.md', 'Selection', 'interface_text',
        'Contract: select all means the whole catalogue, including hidden values.'),
    'first_tab.facet_availability_label': (
        'FILTER_CONTRACT_DRAFT.md', 'Selection', 'interface_text',
        'Contract: facet availability uses all active filters except that facet.'),
    'first_tab.selected_count_label': (
        'FILTER_CONTRACT_DRAFT.md', 'Selection', 'interface_text',
        'Contract: selected-result counts use all filters.'),
    'first_tab.selection_caption': (
        'FILTER_CONTRACT_DRAFT.md', 'Scope and terminology', 'interface_text',
        'Contract: persistent caption that selection does not change matching.'),
    'first_tab.reverse_date_error': (
        'FILTER_CONTRACT_DRAFT.md', 'Selection', 'interface_text',
        'Contract: reversed bounds show a validation error and are not swapped.'),
    'first_tab.missing_name_option': (
        'FILTER_CONTRACT_DRAFT.md', 'Selection', 'interface_text',
        'Contract: group missing names under a visible explicit missing-name option.'),
    'first_tab.missing_version_option': (
        'FILTER_CONTRACT_DRAFT.md', 'Selection', 'interface_text',
        'Contract: catalogue labels retain complete original names; a missing '
        'version needs its own visible option.'),
    'first_tab.unidentified_source_option': (
        'study2/dashboard_views.py', 'source_wave_counts', 'interface_text',
        'Existing unidentified-source wording in the source table.'),
    'first_tab.date_basis_label': (
        'FILTER_CONTRACT_DRAFT.md', 'Selection', 'interface_text',
        'Contract: accepted batch dates retain their date-basis marker.'),

    # Stages -----------------------------------------------------------------
    'stage.1_1': (
        'study2/dashboard_views.py', 'STAGE_PURPOSES', 'codebook_confirmed',
        'Stage purpose text in the published stage table.'),
    'stage.1_3_2_1_1_2_1_2': (
        'study2/dashboard_views.py', 'STAGE_PURPOSES', 'codebook_confirmed',
        'Stage purpose text in the published stage table.'),
    'stage.2_1_3': (
        'study2/dashboard_views.py', 'STAGE_PURPOSES', 'codebook_confirmed',
        'Stage purpose text in the published stage table.'),
    'stage.2_1_4': (
        'study2/dashboard_views.py', 'STAGE_PURPOSES', 'codebook_confirmed',
        'Stage purpose text in the published stage table.'),
    'stage.2_1_5': (
        'study2/dashboard_views.py', 'STAGE_PURPOSES', 'codebook_confirmed',
        'Purpose-only text. The parent wave rule depends on the policy recorded '
        'for the release, so the generic stage text does not name one rule.'),
    'stage.2_1_5.policy_default': (
        'study2/dashboard_views.py', 'STAGE_PURPOSES[2.1.5]', 'codebook_confirmed',
        'The historical per-role selection used when no parent wave policy is '
        'recorded. The 90-day rule applies to the student in this policy.'),
    'stage.2_1_5.policy_student_anchored_v1': (
        'study2/dashboard_views.py', 'stage_overview: parent_wave_policy set',
        'codebook_confirmed',
        'The text stage_overview() shows for a student-anchored policy that is '
        'not nearest_v2. Parents are split into waves by the student Hong Kong '
        'date.'),
    'stage.2_1_5.policy_student_anchored_nearest_v2': (
        'study2/dashboard_views.py', 'stage_overview: student_anchored_hk_nearest_v2',
        'codebook_confirmed',
        'The current policy confirmed on 2026-10-16. The parent T1 is kept '
        'first, then the parent baseline closest to the student T0 is chosen, '
        'and the parent 90-day threshold is removed. BD still requires the same '
        'adult.'),
    'stage.2_1_5.policy_unknown': (
        'study2/dashboard_views.py', 'stage_overview: parent_wave_policy set',
        'interface_text',
        'An unrecognised policy token must not be read as the 90-day rule.'),
    'stage.2_1_6': (
        'study2/dashboard_views.py', 'STAGE_PURPOSES', 'codebook_confirmed',
        'Stage purpose text in the published stage table.'),
    'stage.3_1_1': (
        'study2/dashboard_views.py', 'STAGE_PURPOSES', 'codebook_confirmed',
        'Stage purpose text in the published stage table.'),
    'stage.3_1_2_3_1_3': (
        'study2/dashboard_views.py', 'STAGE_PURPOSES', 'codebook_confirmed',
        'Stage purpose text in the published stage table.'),
    'stage.group_1': (
        'study2/static_assets.py', 'APP_JS:appendStageSummary/labels', 'interface_text',
        'Existing first-tab stage card heading.'),
    'stage.group_2': (
        'study2/static_assets.py', 'APP_JS:appendStageSummary/labels', 'interface_text',
        'Existing first-tab stage card heading.'),
    'stage.group_3': (
        'study2/static_assets.py', 'APP_JS:appendStageSummary/labels', 'interface_text',
        'Existing first-tab stage card heading.'),
    'stage.group_4': (
        'study2/static_assets.py', 'APP_JS:appendStageSummary/labels', 'interface_text',
        'Existing first-tab stage card heading.'),
    'stage.not_provided': (
        'study2/static_assets.py', 'APP_JS:appendStageSummary', 'interface_text',
        'Existing placeholder when a stage has no rows in this release.'),
    'stage.unit_note': (
        'study2/static_assets.py', 'APP_JS:appendStageSummary/notes', 'interface_text',
        'Existing note that stage counts are not one additive funnel.'),

    # Samples ----------------------------------------------------------------
    'sample.a': (
        'study2/dashboard_views.py', 'SAMPLE_NAMES', 'codebook_confirmed',
        'Published sample label; membership rule unchanged.'),
    'sample.b': (
        'study2/dashboard_views.py', 'SAMPLE_NAMES', 'codebook_confirmed',
        'Published sample label; membership rule unchanged.'),
    'sample.c': (
        'study2/dashboard_views.py', 'SAMPLE_NAMES', 'codebook_confirmed',
        'Published sample label; membership rule unchanged.'),
    'sample.d': (
        'study2/dashboard_views.py', 'SAMPLE_NAMES', 'codebook_confirmed',
        'Published sample label; the responding parent may differ.'),
    'sample.ac': (
        'study2/dashboard_views.py', 'SAMPLE_NAMES', 'codebook_confirmed',
        'Published sample label; the same student across both waves.'),
    'sample.bd': (
        'study2/dashboard_views.py', 'SAMPLE_NAMES[BD]', 'codebook_confirmed',
        'Neutral BD label. It states neither continuity rule, so a caller that '
        'has not resolved the policy cannot mislead the reader.'),
    'sample.e': (
        'study2/dashboard_views.py', 'SAMPLE_NAMES', 'codebook_confirmed',
        'Published sample label.'),
    'sample.f': (
        'study2/dashboard_views.py', 'SAMPLE_NAMES', 'codebook_confirmed',
        'Published sample label.'),
    'sample.ef': (
        'study2/dashboard_views.py', 'SAMPLE_NAMES', 'codebook_confirmed',
        'Published sample label; four required response slots.'),
    'sample.parent_child_longitudinal': (
        'study2/dashboard_views.py', 'SAMPLE_NAMES', 'codebook_confirmed',
        'Published sample label; same child, responding adult may differ.'),
    'sample.unit_note': (
        'study2/static_assets.py', 'APP_JS:evidence', 'interface_text',
        'Existing note that a formal sample unit is not a candidate comparison.'),

    # BD continuity ----------------------------------------------------------
    'bd.continuity.label': (
        'FILTER_CONTRACT_DRAFT.md', 'Fixed membership', 'interface_text',
        'Contract: same-adult BD evidence must be explicit.'),
    'bd.continuity.same_adult': (
        'docs/MATCHING_RULES.md', '同一成人與 BD', 'codebook_confirmed',
        'BD requires the same child and the same adult. The wording states the '
        'continuity only and does not claim where the evidence came from.'),
    'bd.continuity.same_child_only': (
        'study2/dashboard_views.py', 'SAMPLE_NAMES[parent_child_longitudinal]',
        'codebook_confirmed',
        'The same-child wording belongs to the separate parent-child '
        'longitudinal set, not to BD. Use it only for a policy that explicitly '
        'supports it.'),
    'bd.continuity.not_established': (
        'FILTER_CONTRACT_DRAFT.md', 'Fixed membership', 'interface_text',
        'Use when policy metadata is missing or continuity is unsupported.'),
    'bd.evidence.label': (
        'FILTER_CONTRACT_DRAFT.md', 'Fixed membership', 'interface_text',
        'The evidence source is a separate fact from the continuity.'),
    'bd.evidence.automatic_rule': (
        'docs/MATCHING_RULES.md', '同一成人與 BD', 'codebook_confirmed',
        'The automatic adult rule confirmed on 2026-10-15: both parent '
        'responses point to the same confirmed child, the adult birth year is '
        'valid and consistent, and at least one contact field matches exactly.'),
    'bd.evidence.reviewer': (
        'docs/MATCHING_RULES.md', '同一成人與 BD', 'codebook_confirmed',
        'A valid manual decision takes priority over the automatic rule.'),
    'bd.evidence.none': (
        'FILTER_CONTRACT_DRAFT.md', 'Fixed membership', 'interface_text',
        'No evidence source is recorded. Do not imply one.'),
    'sample.bd.same_adult': (
        'study2/dashboard_views.py', 'SAMPLE_NAMES[BD]', 'codebook_confirmed',
        'The published BD label is 同一成人 T0／T1, so the same-adult rule is the '
        'default reading of BD.'),
    'sample.bd.same_child': (
        'study2/dashboard_views.py', 'SAMPLE_NAMES[parent_child_longitudinal]',
        'codebook_confirmed',
        'Use only for a policy that explicitly supports a same-child BD.'),
    'sample.bd.policy_unknown': (
        'FILTER_CONTRACT_DRAFT.md', 'Fixed membership', 'interface_text',
        'A missing or unrecognised policy must not pick either continuity rule.'),

    # Counting units ---------------------------------------------------------
    'unit.questionnaire_entries': (
        'study2/static_assets.py', 'APP_JS:overview/cards', 'interface_text',
        'Submission count unit. Distinct from identity groups and dyads.'),
    'unit.identity_groups': (
        'study2/dashboard_views.py', 'stage_overview[2.1.4]', 'interface_text',
        'Identity group unit at stage 2.1.4; includes unresolved groups.'),
    'unit.longitudinal_cases': (
        'study2/dashboard_views.py', 'SAMPLE_NAMES', 'interface_text',
        'Longitudinal case unit for AC, BD and the parent-child longitudinal set.'),
    'unit.student_parent_dyads': (
        'study2/dashboard_views.py', 'SAMPLE_NAMES', 'interface_text',
        'Parent-child pair unit for E, F and EF.'),
    'unit.note': (
        'COMMON_RULES.md', 'Preserve the study', 'interface_text',
        'Rule that record counts, identity groups, longitudinal cases and dyads '
        'are different units.'),

    # Value states -----------------------------------------------------------
    'state.unknown': (
        'study2/static_assets.py', 'APP_JS:statValue', 'interface_text',
        'Value not known.'),
    'state.unavailable': (
        'study2/static_assets.py', 'APP_JS:statValue', 'interface_text',
        'Value cannot be provided in this view.'),
    'state.not_reconciled': (
        'README.md', 'Known blockers and limits', 'interface_text',
        'Explicit not-reconciled state required until the school review record '
        'is located.'),
    'state.none': (
        'study2/descriptive_spec.py', 'STATUS_LABELS', 'interface_text',
        'No value recorded. Distinct from unknown and from zero.'),
    'state.zero': (
        'study2/static_assets.py', 'APP_JS:cards', 'interface_text',
        'Numeric zero, shown as a real count and never as a missing marker.'),
    'state.not_provided': (
        'study2/static_assets.py', 'APP_JS:statValue', 'interface_text',
        'Existing not-provided marker.'),
    'state.suppressed': (
        'study2/static_assets.py', 'APP_JS:statValue', 'interface_text',
        'Existing small-sample suppression marker.'),
    'state.not_collected': (
        'study2/descriptive_spec.py', 'STATUS_LABELS', 'interface_text',
        'Item was not collected in the questionnaire.'),
    'state.note': (
        'packages/MM-R01_ENGLISH_CATALOGUE.md', 'Work item 4', 'interface_text',
        'Requirement to distinguish unknown, unavailable, not reconciled, none '
        'and numeric zero.'),

    # School status ----------------------------------------------------------
    'school.status.unknown_name': (
        'study2/static_assets.py', 'APP_JS:overview/quality', 'interface_text',
        'School name not yet recognised in the local dictionary.'),
    'school.status.pending': (
        'study2/static_assets.py', 'APP_JS:overview/quality', 'interface_text',
        'School name pending review item.'),
    'school.status.not_reconciled': (
        'README.md', 'Known blockers and limits', 'interface_text',
        'The 87 reviewed labels are not present in the inspected dictionary, so '
        'the state must stay explicitly not reconciled.'),
    'school.status.mainstream': (
        'study2/static_assets.py', 'APP_JS:controls/scope', 'interface_text',
        'Mainstream school scope option.'),
    'school.status.non_mainstream': (
        'study2/static_assets.py', 'APP_JS:controls/scope', 'interface_text',
        'Non-mainstream schools remain in the all-schools scope.'),
    'school.status.stage_unknown': (
        'study2/descriptive_spec.py', 'STATUS_LABELS', 'interface_text',
        'School stage could not be determined for the record.'),
    'school.scope.all': (
        'study2/static_assets.py', 'APP_JS:controls/scope', 'interface_text',
        'All-schools scope option on the analysis sidebar.'),
    'school.scope.mainstream_only': (
        'study2/static_assets.py', 'APP_JS:controls/scope', 'interface_text',
        'Mainstream-only scope option on the analysis sidebar.'),
    'school.counts.in_current_scope': (
        'FILTER_CONTRACT_DRAFT.md', 'Suggested exact export representation',
        'interface_text',
        'Contract: current in-scope record counts must respond to filters.'),
    'school.counts.reviewed_release_wide': (
        'FILTER_CONTRACT_DRAFT.md', 'Suggested exact export representation',
        'interface_text',
        'Contract: completed review counts may be release-wide if clearly marked.'),
    'school.counts.note': (
        'FILTER_CONTRACT_DRAFT.md', 'Suggested exact export representation',
        'interface_text',
        'Contract note separating release-wide review counts from filtered '
        'record counts.'),

    # Scale families and subscales ------------------------------------------
    'scale.family.all': (
        'study2/static_assets.py', 'APP_JS:families', 'interface_text',
        'Existing family selector label.'),
    'scale.family.phq': (
        'study2/descriptive_spec.py',
        'SCALE_LABELS',
        'needs_codebook_confirmation',
        'PHQ is 4 items with anxiety (items 1-2) and depression (items 3-4), '
        'confirmed in study2/outputs.py:metrics. The abbreviation and the item '
        'structure are code-established. The English family wording "mental '
        'health" renders the team label and is not established by a local '
        'codebook, so it is not presented as verified.'),
    'scale.family.fqol': (
        'mappings/2.1.1_produce_ABCD.py',
        'map_student_scales: panel_student_family_quality_of_life_',
        'codebook_confirmed',
        'The family wording is established by the mapping comment "# Family '
        'Quality of Life (21 items)" in mappings/2.1.1_produce_ABCD.py and by '
        'the source questionnaire field name '
        'panel_student_family_quality_of_life_. 21 items confirmed in '
        'study2/outputs.py:metrics. That comment does not establish the full '
        'instrument name or the subscale names.'),
    'scale.family.sec': (
        'study2/descriptive_spec.py',
        'SCALE_LABELS',
        'needs_codebook_confirmation',
        'SEC is 22 items in five subscales, confirmed in '
        'study2/outputs.py:metrics. No English expansion of SEC exists in this '
        'repository. The family wording "social-emotional competence" renders '
        'the team label and is not established by a local codebook.'),
    'scale.family.bullying': (
        'study2/descriptive_spec.py', 'BULLY_LABELS', 'interface_text',
        'Existing family selector label.'),
    'scale.family.demographics': (
        'study2/static_assets.py', 'APP_JS:statisticsTable', 'interface_text',
        'Existing population-characteristics family label.'),
    'scale.phq.anxiety': (
        'study2/outputs.py',
        'metrics: PHQ_anxiety (PHQ items 1-2)',
        'needs_codebook_confirmation',
        'Subscale membership is code-established: PHQ items 1-2. The English '
        'subscale name is the team label rendered into English and is not '
        'confirmed by a local codebook.'),
    'scale.phq.depression': (
        'study2/outputs.py',
        'metrics: PHQ_depression (PHQ items 3-4)',
        'needs_codebook_confirmation',
        'Subscale membership is code-established: PHQ items 3-4. The English '
        'subscale name is the team label rendered into English and is not '
        'confirmed by a local codebook.'),
    'scale.phq.total': (
        'study2/outputs.py',
        'metrics: PHQ_total (PHQ items 1-4)',
        'needs_codebook_confirmation',
        'The sum of the four PHQ items and the 0-12 range are code-established '
        'in study2/outputs.py:metrics. The English name is the team label '
        'rendered into English and is not confirmed by a local codebook.'),
    'scale.phq.band': (
        'study2/descriptive_spec.py',
        'SCALES: phq_band',
        'needs_codebook_confirmation',
        'The band boundaries 0-2, 3-5, 6-8 and 9-12 are code-established in '
        'study2/descriptive_spec.py. The English name is the team label '
        'rendered into English and is not confirmed by a local codebook.'),
    'scale.fqol.total': (
        'study2/outputs.py',
        'metrics: FQOL_total (FQOL items 1-21)',
        'needs_codebook_confirmation',
        'The item range 1-21 is code-established in study2/outputs.py:metrics. '
        'The English name is the team label rendered into English and is not '
        'confirmed by a local codebook.'),
    'scale.fqol.family_interaction': (
        'study2/outputs.py',
        'metrics: FQOL_family_interaction (items 1-6)',
        'needs_codebook_confirmation',
        'Subscale membership is code-established: FQOL items 1-6. The English '
        'name is the team label rendered into English and is not confirmed by a '
        'local codebook. docs/DESCRIPTIVE_ANALYSIS.md records that the Chinese '
        'and English FQOL agreement and satisfaction wording already differs.'),
    'scale.fqol.parenting': (
        'study2/outputs.py',
        'metrics: FQOL_parenting (items 7-12)',
        'needs_codebook_confirmation',
        'Subscale membership is code-established: FQOL items 7-12. The English '
        'name is the team label rendered into English and is not confirmed by a '
        'local codebook.'),
    'scale.fqol.emotional_wellbeing': (
        'study2/outputs.py',
        'metrics: FQOL_emotional_wellbeing (items 13-16)',
        'needs_codebook_confirmation',
        'Subscale membership is code-established: FQOL items 13-16. The English '
        'name is the team label rendered into English and is not confirmed by a '
        'local codebook.'),
    'scale.fqol.physical_wellbeing': (
        'study2/outputs.py',
        'metrics: FQOL_physical_wellbeing (items 17-21)',
        'needs_codebook_confirmation',
        'Subscale membership is code-established: FQOL items 17-21. The English '
        'name is the team label rendered into English and is not confirmed by a '
        'local codebook.'),
    'scale.sec.total': (
        'study2/outputs.py',
        'metrics: SEC_total (SEC items 1-22)',
        'needs_codebook_confirmation',
        'The item range 1-22 is code-established in study2/outputs.py:metrics. '
        'The English name is the team label rendered into English and is not '
        'confirmed by a local codebook.'),
    'scale.sec.responsible_decision_making': (
        'study2/outputs.py',
        'metrics: SEC_responsible_decision_making',
        'needs_codebook_confirmation',
        'Subscale membership is code-established. The English name is the team '
        'label rendered into English and is not confirmed by a local codebook.'),
    'scale.sec.social_awareness': (
        'study2/outputs.py',
        'metrics: SEC_social_awareness',
        'needs_codebook_confirmation',
        'Subscale membership is code-established: SEC items 2, 6, 10 and 14. '
        'The English name is the team label rendered into English and is not '
        'confirmed by a local codebook.'),
    'scale.sec.self_management': (
        'study2/outputs.py',
        'metrics: SEC_self_management',
        'needs_codebook_confirmation',
        'Subscale membership is code-established. The English name is the team '
        'label rendered into English and is not confirmed by a local codebook.'),
    'scale.sec.relationship_skills': (
        'study2/outputs.py',
        'metrics: SEC_relationship_skills',
        'needs_codebook_confirmation',
        'Subscale membership is code-established. The English name is the team '
        'label rendered into English and is not confirmed by a local codebook.'),
    'scale.sec.self_awareness': (
        'study2/outputs.py',
        'metrics: SEC_self_awareness (items 17-22)',
        'needs_codebook_confirmation',
        'Subscale membership is code-established: SEC items 17-22. The English '
        'name is the team label rendered into English and is not confirmed by a '
        'local codebook.'),
    'scale.bullying.tbv': (
        'mappings/2.1.1_produce_ABCD.py',
        'map_student_scales: panel_student_tbv-olweus_',
        'needs_codebook_confirmation',
        'The source field name panel_student_tbv-olweus_ establishes the Olweus '
        'attribution and 7 items are confirmed in study2/outputs.py:metrics. '
        'The English domain name is the team label rendered into English and is '
        'not confirmed by a local codebook.'),
    'scale.bullying.tbp': (
        'mappings/2.1.1_produce_ABCD.py',
        'map_student_scales: panel_student_tbp-olweus_',
        'needs_codebook_confirmation',
        'The source field name panel_student_tbp-olweus_ establishes the Olweus '
        'attribution and 7 items are confirmed in study2/outputs.py:metrics. '
        'The English domain name is the team label rendered into English and is '
        'not confirmed by a local codebook.'),
    'scale.bullying.cbv': (
        'mappings/2.1.1_produce_ABCD.py',
        'map_student_scales: panel_student_cyberbully_victim_',
        'needs_codebook_confirmation',
        'The source field name panel_student_cyberbully_victim_ establishes the '
        'cyberbullying attribution and 6 items are confirmed in '
        'study2/outputs.py:metrics. The English domain name is the team label '
        'rendered into English and is not confirmed by a local codebook.'),
    'scale.bullying.cbp': (
        'mappings/2.1.1_produce_ABCD.py',
        'map_student_scales: panel_student_cyberbully_bully_',
        'needs_codebook_confirmation',
        'The source field name panel_student_cyberbully_bully_ establishes the '
        'cyberbullying attribution and 6 items are confirmed in '
        'study2/outputs.py:metrics. The English domain name is the team label '
        'rendered into English and is not confirmed by a local codebook.'),

    # Export -----------------------------------------------------------------
}

# Provenance for the unconfirmed expansion proposals.
EVIDENCE.update({
    'scale.expansion.phq': (
        'mappings/2.1.1_produce_ABCD.py', 'map_student_scales: PHQ-4 (4 items)',
        'needs_codebook_confirmation',
        'Item count and the English severity-frequency response anchors are '
        'local. The expansion of the abbreviation is not established locally.'),
    'scale.expansion.fqol': (
        'mappings/2.1.1_produce_ABCD.py', 'map_student_scales: Family Quality of Life (21 items)',
        'needs_codebook_confirmation',
        'The wording "Family Quality of Life" is established, but the instrument '
        'is not named as a "scale" anywhere locally.'),
    'scale.expansion.sec': (
        'mappings/2.1.1_produce_ABCD.py', 'map_student_scales: SEC (22 items)',
        'needs_codebook_confirmation',
        'No English expansion of SEC exists in this repository. The response '
        'anchors are established; the instrument name is not.'),
})


class MissingTermError(KeyError):
    """Raised when a semantic key is not present in the catalogue."""

    def __init__(self, key):
        self.key = key
        super().__init__(
            f'Unknown catalogue key: {key!r}. Look it up in TEXT and add an '
            f'EVIDENCE row before using it.')


def has(key):
    """Return True when the semantic key exists."""
    return key in TEXT


def get(key, default=None):
    """Return the English text for a key, or ``default`` when it is absent."""
    return TEXT.get(key, default)


def text(key):
    """Return the English text for a key, or raise MissingTermError.

    Missing keys are never silently replaced by a plausible default.
    """
    try:
        return TEXT[key]
    except KeyError:
        raise MissingTermError(key) from None


def require(key):
    """Alias of :func:`text`, for call sites that read better this way."""
    return text(key)


def evidence(key):
    """Return the provenance row for a key as a dict."""
    try:
        source_file, source_locator, status, note = EVIDENCE[key]
    except KeyError:
        raise MissingTermError(key) from None
    return {'semantic_key': key, 'english_text': _english_text(key),
            'source_file': source_file, 'source_locator': source_locator,
            'evidence_status': status, 'note': note}


def _english_text(key):
    """Return the English text for a key, including the proposals that are
    deliberately kept out of the default text."""
    if key in TEXT:
        return TEXT[key]
    return SCALE_FAMILY_UNCONFIRMED.get(key, '')


def bd_continuity_text(status):
    """Return the BD wording for an explicit continuity status.

    The caller must choose. An unknown or missing status raises instead of
    falling back, because "same adult" must never be used as a default. The
    wording states the continuity only; it never states where the evidence
    came from. Use :func:`bd_evidence_source_text` for that.
    """
    if status not in BD_CONTINUITY_STATUSES:
        raise MissingTermError(f'bd.continuity.{status}')
    return TEXT[f'bd.continuity.{status}']


def bd_evidence_source_text(source):
    """Return the wording for where the BD continuity evidence came from.

    The automatic adult rule can confirm the same adult on its own, so the
    source of the evidence is a separate fact from the continuity itself.
    """
    if source not in BD_EVIDENCE_SOURCES:
        raise MissingTermError(f'bd.evidence.{source}')
    return TEXT[f'bd.evidence.{source}']


def bd_sample_text(policy):
    """Return the BD sample label for an explicit membership policy.

    ``same_adult`` and ``same_child`` are the only two policies this
    catalogue can name. A missing or unrecognised policy returns the neutral
    BD label, which states neither continuity rule. The function never
    chooses between the two supported policies.
    """
    if policy in BD_POLICIES:
        return TEXT[BD_POLICIES[policy]]
    if policy is None or policy == '':
        return TEXT['sample.bd']
    return TEXT['sample.bd.policy_unknown']


def stage_2_1_5_text(policy):
    """Return the stage 2.1.5 purpose text for a parent wave policy token.

    ``''`` or ``None`` is the historical per-role selection with no
    student-anchored policy recorded. An unrecognised token returns the
    "policy not recognised" text; it is never guessed into the 90-day rule.
    """
    if policy in (None, ''):
        return TEXT['stage.2_1_5.policy_default']
    if policy == 'student_anchored_hk_v1':
        return TEXT['stage.2_1_5.policy_student_anchored_v1']
    if policy == 'student_anchored_hk_nearest_v2':
        return TEXT['stage.2_1_5.policy_student_anchored_nearest_v2']
    return TEXT['stage.2_1_5.policy_unknown']


def value_state(value):
    """Return the catalogue key describing a possibly missing value.

    ``None`` is "none", ``0`` is "zero", an empty string is "unavailable" and
    anything the caller could not interpret is "unknown". "Not reconciled" is a
    policy state about a missing decision record; it is never inferred from a
    value and must be named explicitly by the caller.
    """
    if value is None:
        return 'state.none'
    if isinstance(value, bool):
        return 'state.unknown'
    if isinstance(value, (int, float)) and value == 0:
        return 'state.zero'
    if isinstance(value, str) and not value.strip():
        return 'state.unavailable'
    return 'state.unknown'


def scale_family_label(variable_id):
    """Return the scale-family label for a variable id, or None.

    ``phq_band`` is a lower-case special key and belongs to the PHQ family,
    the same way the existing JavaScript ``familyOf()`` classifies it.
    """
    if variable_id == 'phq_band':
        return TEXT['scale.family.phq']
    for prefix, key in SCALE_FAMILY_BY_PREFIX:
        if variable_id.startswith(prefix):
            return TEXT[key]
    if variable_id.startswith('dem_'):
        return TEXT['scale.family.demographics']
    if variable_id.endswith('_mean') or '_prevalence' in variable_id:
        return TEXT['scale.family.bullying']
    return None


def unconfirmed_expansion(key):
    """Return a proposed instrument expansion that is not confirmed locally."""
    if key not in SCALE_FAMILY_UNCONFIRMED:
        raise MissingTermError(key)
    return SCALE_FAMILY_UNCONFIRMED[key]


def validate_catalogue():
    """Return a list of catalogue problems. An empty list means the catalogue
    is internally consistent. This never raises, so it can be used in a
    report."""
    problems = []
    seen = {}
    for group_name, group in (('NAVIGATION', NAVIGATION), ('FIRST_TAB', FIRST_TAB),
                              ('STAGES', STAGES), ('SAMPLES', SAMPLES),
                              ('BD_CONTINUITY', BD_CONTINUITY),
                              ('BD_EVIDENCE_SOURCE', BD_EVIDENCE_SOURCE),
                              ('COUNT_UNITS', COUNT_UNITS),
                              ('VALUE_STATES', VALUE_STATES),
                              ('SCHOOL_STATUS', SCHOOL_STATUS),
                              ('SCALE_FAMILY', SCALE_FAMILY)):
        for key, value in group.items():
            if key in seen:
                problems.append(f'duplicate semantic key: {key} '
                                f'({seen[key]} and {group_name})')
            seen[key] = group_name
            if not isinstance(value, str) or not value.strip():
                problems.append(f'empty or non-string text: {key}')
            if any(ord(char) > 127 for char in value):
                problems.append(f'non-ASCII text: {key}')
    for key, value in SCALE_FAMILY_UNCONFIRMED.items():
        if key in seen:
            problems.append(f'duplicate semantic key: {key} '
                            f'({seen[key]} and SCALE_FAMILY_UNCONFIRMED)')
        seen[key] = 'SCALE_FAMILY_UNCONFIRMED'
        if not isinstance(value, str) or not value.strip():
            problems.append(f'empty or non-string text: {key}')
        if any(ord(char) > 127 for char in value):
            problems.append(f'non-ASCII text: {key}')
    for key in ALL_KEYS:
        if key not in EVIDENCE:
            problems.append(f'missing provenance row: {key}')
    for key in EVIDENCE:
        if key not in ALL_KEYS:
            problems.append(f'provenance row without a catalogue entry: {key}')
        else:
            status = EVIDENCE[key][2]
            if status not in EVIDENCE_STATUSES:
                problems.append(f'unknown evidence status for {key}: {status}')
            if not EVIDENCE[key][0] or not EVIDENCE[key][1]:
                problems.append(f'incomplete provenance row: {key}')
    for key in SCALE_FAMILY:
        if key not in EVIDENCE:
            problems.append(f'scale family entry without provenance: {key}')
    for status in BD_CONTINUITY_STATUSES:
        if f'bd.continuity.{status}' not in TEXT:
            problems.append(f'missing BD continuity alternative: {status}')
    if len(TEXT) > CORE_ENTRY_BUDGET:
        problems.append(f'catalogue exceeds the core entry budget: '
                        f'{len(TEXT)} > {CORE_ENTRY_BUDGET}')
    return problems
