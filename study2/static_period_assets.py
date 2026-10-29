"""Finite, lazy, protected aggregate assets for combined calendar filters."""
from __future__ import annotations

import hashlib
import json
import re

MODES = {'abcd': ('student', 'parent'), 'ef': ('student', 'parent'),
         'acbd': ('student', 'parent'), 'efmatched': ('student', 'parent'),
         'independent_all': ('parent',), 'independent_child': ('parent',),
         'independent_adult': ('parent',)}
PERIOD_V1_FILES = tuple(f'period-{eligibility}-{mode}-{role}.json'
                    for eligibility in ('off', 'on') for mode, roles in MODES.items() for role in roles)
SEMESTER_FILES = tuple(f'period-semester-{eligibility}-{mode}-{role}.json'
                       for eligibility in ('off', 'on') for mode, roles in MODES.items() for role in roles)
PERIOD_FILES = (*PERIOD_V1_FILES, *SEMESTER_FILES)
CODES = {'compatible_period_aggregates_required', 'accepted_manifest_required',
         'published_cohort_unavailable', 'period_grade_anchor_unavailable',
         'day_aggregates_require_unsuppressed_profile', 'accepted_manifest_invalid'}


def _need(ok, message):
    if not ok:
        from .common import PipelineError
        raise PipelineError('Period assets: ' + message)


def _text(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False) + '\n'


def _hash(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def empty_assets(release_id):
    return {name: _text(dict(status='unavailable', code='compatible_period_aggregates_required',
                            release_id=release_id)) for name in PERIOD_V1_FILES}


def _anchors(mode, role):
    grouping = ('wave_response' if mode == 'abcd' else 'wave_student' if mode == 'ef'
                else 'independent_parent_T0' if mode.startswith('independent')
                else 'student_T0' if mode == 'efmatched' or role == 'student' else 'BD_parent_T0')
    source = 'wave_role_response' if mode == 'ef' else grouping
    return grouping, source


def _safe_cube(cube):
    forbidden = {'submission_id', 'child_id', 'version_id', 'case_id', 'dyad_id',
                 'phone', 'email', 'dob', 'school', 'raw', 'answer', 'observed_at', 'path'}
    pattern = re.compile(r'(?:\b(?:SUB|CHILD|CASE|REV|DYAD|PKG|DEC)_[A-Za-z0-9_-]+|/(?:Users|home)/|'
                         r'[\w.+-]+@[\w.-]+\.[A-Za-z]{2,})')
    def visit(value):
        if isinstance(value, dict):
            _need(not forbidden.intersection(value), 'private field in aggregate cube')
            for item in value.values(): visit(item)
        elif isinstance(value, list):
            for item in value: visit(item)
        elif isinstance(value, str):
            _need(not pattern.search(value), 'private value in aggregate cube')
    visit(cube)


def prepare_assets(frame, parents, measurements, summary, *, records=None, manifest=None,
                   panel=None, minimum=0, progress=None):
    """Use native cohorts once per mode/role and eligibility; no subset matrix."""
    from .static_period import FORMAT, build_cube, validate_cube
    from .static_grade import attach_grade
    from .static_sources import source_code
    from .descriptives import cohort, independent_cohort
    from .descriptive_spec import MODES as FORMAL_MODES
    from .descriptive_trends import dated_rows, date_mask
    from .analysis_eligibility import project_eligibility, projected_cohorts, EligibilityError
    release = summary['release_id']
    assets = empty_assets(release)
    references = {}
    for eligibility in ('off', 'on'):
        for mode, roles in MODES.items():
            for role in roles:
                name = f'period-{eligibility}-{mode}-{role}.json'
                code = ('day_aggregates_require_unsuppressed_profile' if minimum != 0
                        else 'published_cohort_unavailable' if eligibility == 'off' else 'accepted_manifest_required')
                assets[name] = _text(dict(format=FORMAT, status='unavailable', code=code,
                                         release_id=release, mode=mode, role=role, eligibility=eligibility))
                references[eligibility, mode, role] = dict(asset=name, sha256=_hash(assets[name]),
                    status='unavailable', code=code, release_id=release, mode=mode, role=role,
                    eligibility=eligibility, eligibility_revision=None, extent=None)
    catalog = dict(format=FORMAT, status='available' if minimum == 0 else 'unavailable',
                   code=None if minimum == 0 else 'day_aggregates_require_unsuppressed_profile',
                   release_id=release, profile='protected_researcher', minimum_cell_n=minimum,
                   refs=list(references.values()))
    if minimum != 0:
        return catalog, assets
    scopes = [('off', None, [(mode, role, cohort(frame, parents, measurements, mode, role))
                for mode in FORMAL_MODES for role in ('student', 'parent')
                if not (parents is None and mode == 'acbd' and role == 'parent')])]
    if panel is not None:
        for mode, branch, paired in [('independent_all', 'child_report', False),
                                      ('independent_child', 'child_report', True),
                                      ('independent_adult', 'same_adult', True)]:
            scopes[0][2].append((mode, 'parent', independent_cohort(panel['analysis'], measurements, branch, paired)))
    if manifest is not None:
        try:
            projection = project_eligibility(records, frame, parents, manifest, release, enabled=True, panel=panel)
            scopes.append(('on', manifest['revision'],
                           projected_cohorts(records, frame, parents, measurements, projection, panel=panel)))
        except EligibilityError:
            for (eligibility, mode, role), ref in references.items():
                if eligibility == 'on':
                    ref['code'] = 'accepted_manifest_invalid'
                    assets[ref['asset']] = _text({k: ref[k] for k in
                        ('status', 'code', 'release_id', 'mode', 'role', 'eligibility')})
                    ref['sha256'] = _hash(assets[ref['asset']])
    for eligibility, revision, scope_rows in scopes:
        for mode, role, base in scope_rows:
            if progress: progress(f'Combined periods / {eligibility} / {mode} / {role}')
            rows, grade_anchor = attach_grade(base, frame, measurements, mode, role)
            ref = references[eligibility, mode, role]
            if grade_anchor is None:
                ref['code'] = 'period_grade_anchor_unavailable'
                assets[ref['asset']] = _text({k: ref[k] for k in
                    ('status', 'code', 'release_id', 'mode', 'role', 'eligibility')})
                ref['sha256'] = _hash(assets[ref['asset']])
                continue
            rows['anchor_source_type'] = rows['anchor_source_type'].map(source_code)
            grouping, source = _anchors(mode, role)
            cube = build_cube(rows, role, mode=mode, grade_anchor=grade_anchor,
                              grouping_anchor=grouping, source_filter_anchor=source, release_id=release)
            validate_cube(cube)
            _safe_cube(cube)
            text = _text(cube)
            assets[ref['asset']] = text
            dates = dated_rows(rows)
            known = dates.loc[date_mask(dates, True), '_calendar_date']
            extent = dict(start=known.min().isoformat(), end=known.max().isoformat()) if len(known) else None
            ref.update(status='available', code=None, sha256=_hash(text),
                       eligibility_revision=revision, extent=extent)
    validate_catalog(catalog, release)
    return catalog, assets


def validate_catalog(catalog, release_id):
    from .static_period import FORMAT
    _need(isinstance(catalog, dict) and set(catalog) == {'format','status','code','release_id','profile','minimum_cell_n','refs'}, 'catalog fields')
    _need(catalog['format'] == FORMAT and catalog['release_id'] == release_id and
          catalog['profile'] == 'protected_researcher' and type(catalog['minimum_cell_n']) is int and
          catalog['minimum_cell_n'] >= 0, 'catalog binding')
    enabled = catalog['minimum_cell_n'] == 0
    _need(catalog['status'] == ('available' if enabled else 'unavailable') and
          catalog['code'] == (None if enabled else 'day_aggregates_require_unsuppressed_profile'), 'catalog availability')
    refs = catalog['refs']
    _need(isinstance(refs,list) and len(refs) == len(PERIOD_V1_FILES), 'finite catalog required')
    seen = set()
    for ref in refs:
        _need(isinstance(ref,dict) and set(ref) == {'asset','sha256','status','code','release_id','mode','role','eligibility','eligibility_revision','extent'}, 'reference fields')
        mode, role, eligibility = ref['mode'], ref['role'], ref['eligibility']
        _need(mode in MODES and role in MODES[mode] and eligibility in ('off','on'), 'reference scope')
        expected = f'period-{eligibility}-{mode}-{role}.json'
        _need(ref['asset'] == expected and expected not in seen and ref['release_id'] == release_id and
              isinstance(ref['sha256'],str) and re.fullmatch('[0-9a-f]{64}',ref['sha256']), 'reference binding')
        seen.add(expected)
        _need(ref['status'] in ('available','unavailable'), 'reference availability')
        if ref['status'] == 'available':
            _need(enabled and ref['code'] is None, 'fine aggregates require minimum zero')
            _need((eligibility == 'off' and ref['eligibility_revision'] is None) or
                  (eligibility == 'on' and isinstance(ref['eligibility_revision'],str) and
                   re.fullmatch('[0-9a-f]{64}',ref['eligibility_revision'])), 'exclusion revision binding')
        else:
            _need(ref['code'] in CODES and ref['eligibility_revision'] is None and ref['extent'] is None, 'unavailable reference')
        if ref['extent'] is not None:
            from datetime import date
            extent = ref['extent']
            _need(isinstance(extent,dict) and set(extent)=={'start','end'}, 'extent fields')
            _need(date.fromisoformat(extent['start']).isoformat()==extent['start'] and
                  date.fromisoformat(extent['end']).isoformat()==extent['end'] and extent['start']<=extent['end'], 'extent dates')
    return catalog


def validate_assets(catalog, assets, release_id):
    from .static_period import validate_cube
    _need(set(assets) == set(PERIOD_V1_FILES), 'finite asset set required')
    validate_catalog(catalog,release_id)
    for ref in catalog['refs']:
        text = assets[ref['asset']]
        _need(isinstance(text,str) and _hash(text) == ref['sha256'], 'asset checksum mismatch')
        cube = json.loads(text)
        if ref['status']=='available':
            validate_cube(cube)
            _safe_cube(cube)
            _need(cube['release_id']==release_id and cube['mode']==ref['mode'] and cube['role']==ref['role'], 'cube reference mismatch')
        else:
            _need(cube.get('status')=='unavailable' and cube.get('release_id')==release_id, 'unavailable asset mismatch')
    return assets


def empty_semester_assets(release_id):
    return {name: _text(dict(status='unavailable', code='compatible_period_aggregates_required',
                            release_id=release_id)) for name in SEMESTER_FILES}


def prepare_semester_assets(frame, parents, measurements, summary, *, records=None, manifest=None,
                            panel=None, minimum=0, progress=None):
    """Build a separate semester catalogue from the unchanged native cohorts."""
    from .static_semester import FORMAT, build_cube
    from .static_grade import attach_grade
    from .static_sources import source_code
    from .descriptives import cohort, independent_cohort
    from .descriptive_spec import MODES as FORMAL_MODES
    from .descriptive_trends import dated_rows, date_mask
    from .analysis_eligibility import project_eligibility, projected_cohorts, EligibilityError

    release = summary['release_id']
    active = manifest.get('revision') if isinstance(manifest, dict) else None
    _need(active is None or isinstance(active, str) and re.fullmatch('[0-9a-f]{64}', active),
          'invalid active exclusion revision')
    scopes = []
    invalid_manifest = False
    if minimum == 0:
        off = [(mode, role, cohort(frame, parents, measurements, mode, role))
               for mode in FORMAL_MODES for role in ('student', 'parent')
               if not (parents is None and mode == 'acbd' and role == 'parent')]
        if panel is not None:
            for mode, branch, paired in [('independent_all', 'child_report', False),
                                          ('independent_child', 'child_report', True),
                                          ('independent_adult', 'same_adult', True)]:
                off.append((mode, 'parent', independent_cohort(panel['analysis'], measurements, branch, paired)))
        scopes.append(('off', None, off))
        if manifest is not None:
            try:
                projection = project_eligibility(records, frame, parents, manifest, release,
                                                 enabled=True, panel=panel)
                scopes.append(('on', active, projected_cohorts(records, frame, parents, measurements,
                                                                projection, panel=panel)))
            except EligibilityError:
                active = None
                invalid_manifest = True

    references, assets = {}, {}
    for eligibility in ('off', 'on'):
        for mode, roles in MODES.items():
            for role in roles:
                name = f'period-semester-{eligibility}-{mode}-{role}.json'
                code = ('day_aggregates_require_unsuppressed_profile' if minimum != 0 else
                        'published_cohort_unavailable' if eligibility == 'off' else
                        'accepted_manifest_invalid' if invalid_manifest else 'accepted_manifest_required')
                payload = dict(format=FORMAT, status='unavailable', code=code, release_id=release,
                               mode=mode, role=role, eligibility=eligibility, eligibility_revision=None,
                               active_on_revision=active)
                assets[name] = _text(payload)
                references[eligibility, mode, role] = dict(asset=name, sha256=_hash(assets[name]),
                    status='unavailable', code=code, release_id=release, mode=mode, role=role,
                    eligibility=eligibility, eligibility_revision=None, extent=None)
    catalog = dict(format=FORMAT, status='available' if minimum == 0 else 'unavailable',
                   code=None if minimum == 0 else 'day_aggregates_require_unsuppressed_profile',
                   release_id=release, profile='protected_researcher', minimum_cell_n=minimum,
                   active_on_revision=active, refs=list(references.values()))
    for eligibility, revision, scope_rows in scopes:
        for mode, role, base in scope_rows:
            if progress:
                progress(f'Semester trends / {eligibility} / {mode} / {role}')
            rows, grade_anchor = attach_grade(base, frame, measurements, mode, role)
            ref = references[eligibility, mode, role]
            if grade_anchor is None:
                ref['code'] = 'period_grade_anchor_unavailable'
                payload = dict(format=FORMAT, status='unavailable', code=ref['code'], release_id=release,
                               mode=mode, role=role, eligibility=eligibility, eligibility_revision=None,
                               active_on_revision=active)
                assets[ref['asset']] = _text(payload)
                ref['sha256'] = _hash(assets[ref['asset']])
                continue
            rows['anchor_source_type'] = rows['anchor_source_type'].map(source_code)
            grouping, source = _anchors(mode, role)
            cube = build_cube(rows, role, mode=mode, grade_anchor=grade_anchor, grouping_anchor=grouping,
                              source_filter_anchor=source, release_id=release, eligibility=eligibility,
                              eligibility_revision=revision, active_on_revision=active)
            _safe_cube(cube)
            assets[ref['asset']] = _text(cube)
            dates = dated_rows(rows)
            known = dates.loc[date_mask(dates, True), '_calendar_date']
            extent = dict(start=known.min().isoformat(), end=known.max().isoformat()) if len(known) else None
            ref.update(status='available', code=None, sha256=_hash(assets[ref['asset']]),
                       eligibility_revision=revision, extent=extent)
    validate_semester_assets(catalog, assets, release)
    return catalog, assets


def validate_semester_catalog(catalog, release_id):
    from datetime import date
    from .static_semester import FORMAT
    _need(isinstance(catalog, dict) and set(catalog) == {'format', 'status', 'code', 'release_id',
          'profile', 'minimum_cell_n', 'active_on_revision', 'refs'}, 'semester catalog fields')
    _need(catalog['format'] == FORMAT and catalog['release_id'] == release_id and
          catalog['profile'] == 'protected_researcher' and type(catalog['minimum_cell_n']) is int and
          catalog['minimum_cell_n'] >= 0, 'semester catalog binding')
    active = catalog['active_on_revision']
    _need(active is None or isinstance(active, str) and re.fullmatch('[0-9a-f]{64}', active),
          'semester active exclusion revision')
    enabled = catalog['minimum_cell_n'] == 0
    _need(catalog['status'] == ('available' if enabled else 'unavailable') and
          catalog['code'] == (None if enabled else 'day_aggregates_require_unsuppressed_profile'),
          'semester catalog availability')
    refs = catalog['refs']
    _need(isinstance(refs, list) and len(refs) == len(SEMESTER_FILES), 'finite semester catalog required')
    seen = set()
    for ref in refs:
        _need(isinstance(ref, dict) and set(ref) == {'asset', 'sha256', 'status', 'code', 'release_id',
              'mode', 'role', 'eligibility', 'eligibility_revision', 'extent'}, 'semester reference fields')
        mode, role, eligibility = ref['mode'], ref['role'], ref['eligibility']
        _need(mode in MODES and role in MODES[mode] and eligibility in ('off', 'on'), 'semester reference scope')
        expected = f'period-semester-{eligibility}-{mode}-{role}.json'
        _need(ref['asset'] == expected and expected not in seen and ref['release_id'] == release_id and
              isinstance(ref['sha256'], str) and re.fullmatch('[0-9a-f]{64}', ref['sha256']), 'semester reference binding')
        seen.add(expected)
        _need(ref['status'] in ('available', 'unavailable'), 'semester reference availability')
        if ref['status'] == 'available':
            _need(enabled and ref['code'] is None and
                  (eligibility == 'off' and ref['eligibility_revision'] is None or
                   eligibility == 'on' and active is not None and ref['eligibility_revision'] == active),
                  'semester exclusion revision binding')
        else:
            _need(ref['code'] in CODES and ref['eligibility_revision'] is None and ref['extent'] is None,
                  'unavailable semester reference')
        if ref['extent'] is not None:
            extent = ref['extent']
            _need(isinstance(extent, dict) and set(extent) == {'start', 'end'}, 'semester extent fields')
            try:
                _need(all(isinstance(extent[k], str) and date.fromisoformat(extent[k]).isoformat() == extent[k]
                          for k in ('start', 'end')) and extent['start'] <= extent['end'], 'semester extent dates')
            except ValueError:
                _need(False, 'semester extent dates')
    return catalog


def validate_semester_assets(catalog, assets, release_id):
    from .static_semester import FORMAT, validate_cube
    _need(isinstance(assets, dict) and set(assets) == set(SEMESTER_FILES), 'finite semester asset set required')
    validate_semester_catalog(catalog, release_id)
    for ref in catalog['refs']:
        text = assets[ref['asset']]
        _need(isinstance(text, str) and _hash(text) == ref['sha256'], 'semester asset checksum mismatch')
        try:
            cube = json.loads(text)
        except (ValueError, TypeError):
            _need(False, 'invalid semester asset JSON')
        if ref['status'] == 'available':
            validate_cube(cube)
            _safe_cube(cube)
            _need(all(cube[k] == ref[k] for k in ('release_id', 'mode', 'role', 'eligibility',
                                                   'eligibility_revision')) and
                  cube['active_on_revision'] == catalog['active_on_revision'], 'semester cube reference mismatch')
        else:
            _need(cube == dict(format=FORMAT, status='unavailable', code=ref['code'], release_id=release_id,
                              mode=ref['mode'], role=ref['role'], eligibility=ref['eligibility'],
                              eligibility_revision=None, active_on_revision=catalog['active_on_revision']),
                  'unavailable semester asset mismatch')
    return assets
