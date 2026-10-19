"""Prepare only the demographic measurements needed by published reports.

Never mutate answers, identity decisions, selected waves or existing scores.
Every unavailable value has a separate reason, including source-code ambiguity.
"""
import math
import re
from zoneinfo import ZoneInfo

import pandas as pd

from .common import text, timestamp
from .descriptive_spec import DICTIONARY_VERSION, REPORT_RANGES
from .grades import parse_grade


def number(value, *, integer=False, positive=False):
    raw = text(value)
    if not raw or raw in {'999', '999.0'}:
        return None, 'missing'
    try:
        result = float(raw)
    except (TypeError, ValueError):
        return None, 'invalid'
    if not math.isfinite(result) or (integer and not result.is_integer()) or (result <= 0 if positive else result < 0):
        return None, 'invalid'
    return int(result) if integer else result, 'valid'


def category(value, allowed):
    n, status = number(value, integer=True)
    if status != 'valid':
        return None, status
    code = str(n)
    return (code, 'valid') if code in allowed else (None, 'invalid')


def report_measurement(key, result):
    """A demographic reporting gate, never an edit to the recorded answer."""
    value, status = result
    if status != 'valid':
        return result
    bounds = REPORT_RANGES[key]
    if bounds is None:
        return None, 'range_pending'
    return (value, 'valid') if bounds[0] <= value <= bounds[1] else (None, 'outside_report_range')


def sen(value):
    raw = text(value)
    if not raw or raw in {'999', '999.0'}:
        return None, 'missing'
    parts = re.split(r'[,;，；/\s]+', raw)
    parsed = [category(token, {'0', '1', '2', '3', '4'}) for token in parts]
    if not parts or any(status != 'valid' for _, status in parsed):
        return None, 'invalid'
    codes = {code for code, _ in parsed}
    if '3' in codes and len(codes) > 1:
        return None, 'conflict'
    return ';'.join(sorted(codes)), 'valid'


def school_stage(record):
    school = text(record.get('answer', {}).get('school_type', record.get('school_type'))).lower()
    declared = parse_grade(record.get('grade_raw', record.get('grade'))).stage
    fixed = {'primary': 'primary', 'primary school': 'primary',
             'secondary': 'secondary', 'secondary school': 'secondary'}.get(school)
    if fixed:
        return (None, 'conflict') if declared and fixed != declared else (fixed, 'valid')
    if school in {'through-train school', 'primary & secondary', 'primary or secondary'}:
        return (declared, 'valid') if declared else (None, 'unknown_stage')
    return None, 'unknown_stage'


def demographic_values(record, base):
    answer, role = record.get('answer', {}), record['role']
    out = {'submission_id': record['submission_id'], 'version_id': record.get('version_id'),
           'observed_at': record.get('observed_at'), 'descriptive_dictionary_version': DICTIONARY_VERSION}

    def put(key, result):
        out['dem_' + key], out['dem_' + key + '__status'] = result

    put('child_gender', category(record.get('gender'), {'0', '1'}))
    age = base.get('age_at_observation')
    if age is not None and pd.notna(age):
        child_age = (age, 'valid')
    elif 'invalid_child_dob' in record.get('issues', []):
        child_age = (None, 'invalid')
    elif not record.get('dob'):
        child_age = (None, 'missing')
    else:
        child_age = (None, 'unverified_date')
    put('child_age', report_measurement('child_age', child_age))
    put('stage', school_stage(record))
    out['school_stage'] = out['dem_stage']
    out['school_stage_status'] = out['dem_stage__status']
    if role == 'student':
        for key, suffix, codes in [('birthplace', '07', {'0', '1', '2'}),
                                   ('years_hk', '10', {'0', '1', '2'}),
                                   ('performance', '11', {'0', '1', '2', '3', '4'})]:
            put(key, category(answer.get('student_demographics_' + suffix), codes))
        siblings = []
        for i, key in enumerate(['older_brothers', 'older_sisters', 'younger_brothers', 'younger_sisters'], 1):
            result = report_measurement(key, number(answer.get('student_demographics_09.' + str(i)), integer=True))
            put(key, result)
            siblings.append(result)
        put('siblings_total', report_measurement('siblings_total', (sum(value for value, _ in siblings), 'valid'))
            if all(s == 'valid' for _, s in siblings) else (None,
                next((s for s in ('invalid', 'outside_report_range', 'range_pending')
                      if any(status == s for _, status in siblings)), 'missing')))
        h, hs = report_measurement('height', number(answer.get('student_demographics_04'), positive=True))
        w, ws = report_measurement('weight', number(answer.get('student_demographics_05'), positive=True))
        put('height', (h, hs)); put('weight', (w, ws))
        put('bmi', (w / (h / 100) ** 2, 'valid') if hs == ws == 'valid'
            else (None, next((s for s in ('invalid', 'outside_report_range', 'range_pending')
                              if s in {hs, ws}), 'missing')))
        put('grade', category(record.get('grade'), {str(i) for i in range(1, 7)}))
    else:
        put('adult_gender', (None, 'not_collected'))
        for key, suffix, allowed in [('relationship', '06', range(3)), ('carer', '07', range(4)),
                                     ('marital', '09', range(6)), ('employment', '10', range(4)),
                                     ('textbook', '11', range(3)), ('cohabit', '13', range(2))]:
            put(key, category(answer.get('adult_demographics_' + suffix), {str(i) for i in allowed}))
        edu, es = category(answer.get('adult_demographics_08'), {str(i) for i in range(9)})
        grouped = None if edu is None else '0' if int(edu) <= 1 else '1' if int(edu) <= 5 else '2' if int(edu) <= 7 else '3'
        put('education', (grouped, es))
        # Jarvis confirmed that only Qualtrics coding is interpretable for now.
        source_label = text(record.get('source_label', answer.get('Survey')))
        count = category(answer.get('adult_demographics_12'), {'1', '2', '3', '4'})
        if 'qualtrics' not in source_label.lower():
            count = (None, 'missing' if not text(answer.get('adult_demographics_12')) else 'unverified_encoding')
        put('children_count', count)
        year, status = number(answer.get('adult_demographics_05'), integer=True)
        observed = timestamp(record.get('observed_at'))
        if record.get('adult_birth_year_status') == 'unconfirmed':
            adult_age = (None, 'unconfirmed_year')
        elif status != 'valid':
            adult_age = (None, status)
        elif record.get('time_confidence') not in {'observed', 'manual_verified'} or not observed:
            adult_age = (None, 'unverified_date')
        else:
            observed_year = observed.astimezone(ZoneInfo('Asia/Hong_Kong')).year
            adult_age = (observed_year - year, 'valid') if 1900 <= year <= observed_year else (None, 'invalid')
        put('adult_age', report_measurement('adult_age', adult_age))
        codes, status = sen(answer.get('adult_demographics_14'))
        put('sen_types', (codes, status))
        put('sen', ('no' if codes == '3' else 'yes', 'valid') if status == 'valid' else (None, status))
    return out


def attach_measurements(frame, measurements):
    """Retain the caller's exact membership/order and existing score columns."""
    if measurements['submission_id'].duplicated().any():
        raise ValueError('Descriptive measurements are not unique per submission')
    columns = ['submission_id'] + [c for c in measurements if c != 'submission_id' and c not in frame]
    result = frame.merge(measurements[columns], on='submission_id', how='left', validate='many_to_one', sort=False)
    if len(result) != len(frame) or result['descriptive_dictionary_version'].isna().any():
        raise ValueError('Published descriptive measurements do not cover selected submissions')
    return result
