"""Synthetic privacy, denominator, continuity and atomic output regressions."""
import json
from pathlib import Path

import pandas as pd
import pytest

from study2.common import PipelineError
from study2.descriptives import paired_changes, statistics
from study2.static_export import (DEPLOY_FILES, FORMAT, _exploration, _trends,
    count_table, pack_snapshot, safe_changes, safe_statistics, validate_snapshot, write_site)


def rows(role='student', mode='acbd', adult=True):
    result = []
    for child in range(40):
        for wave in ('T0', 'T1'):
            result.append(dict(child_id=f'person-{child}', submission_id=f'form-{child}-{wave}',
                version_id=f'version-{child}-{wave}', role=role, wave=wave, report_mode=mode,
                grouping_anchor='固定基線', anchor_gender='0', anchor_school_stage='primary',
                observed_at='2025-01-02T00:00:00Z' if wave == 'T0' else '2025-05-02T00:00:00Z',
                date_basis='system_creation', time_confidence='observed',
                adult_continuity_confirmed=adult,
                PHQ_total=float(child % 2 + (wave == 'T1')), FQOL_total=2., SEC_total=3.,
                TBV_mean=1., TBP_mean=1., CBV_mean=1., CBP_mean=1.))
            result[-1].update({domain + '_prevalence' + str(threshold): 1.
                               for domain in ('TBV', 'TBP', 'CBV', 'CBP') for threshold in (1, 2)})
    frame = pd.DataFrame(result)
    frame.attrs['mode'] = mode
    return frame


def snapshot():
    return dict(format=FORMAT, release_id='synthetic-release', generated_at='2026-01-01T00:00:00Z',
                published_at='2026-01-01T00:00:00Z', views=[])


def test_summary_values_are_identical_to_shared_statistics_without_raw_extremes():
    stats = statistics(rows(), 'student')
    safe = safe_statistics(stats)
    value = next(r for r in safe if r['variable_id'] == 'PHQ_total' and r['wave'] == 'T0')
    original = stats.loc[stats['variable_id'].eq('PHQ_total') & stats['wave'].eq('T0')].iloc[0]
    assert value['mean'] == original['mean'] == .5
    assert value['sd'] == original['sd']
    assert value['valid_n'] == 40 and value['missing_n'] == 0
    assert not value['suppressed']
    assert 'minimum' not in value and 'maximum' not in value and 'missing_detail' not in value


@pytest.mark.parametrize('negative_count', [1, 9, 39])
def test_researcher_export_keeps_small_binary_categories_and_complements(negative_count):
    frame = rows()
    frame['TBV_prevalence1'] = [float(int(child.removeprefix('person-')) >= negative_count)
                              for child in frame['child_id']]
    result = safe_statistics(statistics(frame, 'student'))
    target = [r for r in result if r['variable_id'] == 'TBV_prevalence1']
    assert all(not r['suppressed'] and r['numerator']==40-negative_count
               and r['denominator']==40 for r in target)


def test_a_few_missing_forms_do_not_hide_a_large_mean():
    frame = rows()
    frame.loc[0, 'PHQ_total'] = None
    records = safe_statistics(statistics(frame, 'student'))
    row = next(r for r in records if r['variable_id'] == 'PHQ_total' and r['wave'] == 'T0')
    assert not row['suppressed'] and row['sample_n'] == 40 and row['missing_n'] == 1
    assert row['valid_n'] == 39 and row['mean'] is not None and row['sd'] is not None


def test_same_adult_gate_remains_in_effect_for_paired_parent_phq():
    parents = rows('parent', 'efmatched', adult=False)
    changes = safe_changes(paired_changes(parents, 'parent'))
    assert not any(r['variable_id'].startswith('PHQ') for r in changes)
    histograms = _exploration(parents, 'parent', 'synthetic-release', True, 10)
    assert not any(r['variable_id'].startswith('PHQ') for r in histograms)
    accepted = rows('parent', 'acbd', adult=True)
    phq = next(r for r in safe_changes(paired_changes(accepted, 'parent')) if r['variable_id'] == 'PHQ_total')
    assert phq['paired_valid_n'] == 40 and phq['mean_change'] == 1


def test_histogram_rare_tails_merge_across_empty_bins_without_losing_n():
    frame = rows()
    frame['PHQ_total'] = 0.
    frame.loc[0, 'PHQ_total'] = 12.
    result = _exploration(frame, 'student', 'synthetic-release', False, 10)
    selected = [r for r in result if r['group']=='all' and r['variable_id']=='PHQ_total']
    assert all(r['count'] == 0 or r['count'] >= 10 for r in selected)
    assert sum(r['count'] for r in selected if r['wave']=='T0') == 40
    assert sum(r['count'] for r in selected if r['wave']=='T1') == 40
    for index in {r['bin_index'] for r in selected}:
        bounds = {(r['bin_left'], r['bin_right']) for r in selected if r['bin_index']==index}
        assert len(bounds) == 1


def test_trends_respect_batch_policy_hong_kong_month_and_do_not_reselect_waves():
    frame = rows()
    frame.loc[frame['wave'].eq('T0'), ['date_basis', 'time_confidence']] = ['batch_assigned_creation', 'accepted_creation_time']
    frame.loc[frame['wave'].eq('T1'), 'observed_at'] = '2025-04-30T17:00:00Z'
    result = _trends(frame, 'student', 10)
    without = [r for r in result if not r['include_batch']]
    with_batch = [r for r in result if r['include_batch']]
    assert without[0]['period'] == '2025-05' and without[0]['counts'] == {'T0': 0, 'T1': 40}
    assert with_batch[0]['period'] == '2025-01' and with_batch[0]['counts'] == {'T0': 40, 'T1': 0}
    assert all('observed_at' not in str(r) and 'form-' not in str(r) for r in result)


@pytest.mark.parametrize('bad', [{'submission_id': 'hidden'}, {'text': 'CHILD_private'},
                                  {'nested': [{'email': 'hidden'}]}, {'x': 'contact@example.org'},
                                  {'x': '/home/' + 'example/secret'}])
def test_privacy_validation_rejects_identifiers_paths_and_contacts(bad):
    with pytest.raises(PipelineError):
        validate_snapshot(bad)


def test_researcher_export_keeps_small_source_counts_and_totals():
    value = count_table([{'source': 'paperform', 'count': 1}, {'source': 'qualtrics', 'count': 39},
                         {'source': 'total', 'count': 40}])
    assert [row['count'] for row in value]==[1,39,40]


@pytest.mark.parametrize('size',[1,2,9])
def test_researcher_export_keeps_small_means_and_valid_pair_counts(size):
    frame=rows().iloc[:2*size].copy()
    frame.attrs['mode']='acbd'
    result=safe_statistics(statistics(frame,'student'))
    phq=[r for r in result if r['variable_id']=='PHQ_total']
    assert all(not r['suppressed'] and r['sample_n']==size and r['valid_n']==size for r in phq)
    assert all(r['mean'] is not None for r in phq)
    changes=safe_changes(paired_changes(frame,'student'))
    phq_change=next(r for r in changes if r['variable_id']=='PHQ_total')
    assert not phq_change['suppressed'] and phq_change['paired_valid_n']==size
    # Lack of small-cell masking does not fabricate statistically undefined tests.
    assert phq_change['p_value'] is None and phq_change['cohen_dz'] is None
    assert phq_change['inference_status'] in {'insufficient_pairs','zero_change_variance'}


def test_small_month_and_single_response_histogram_are_exported_in_full():
    frame=rows().iloc[:2].copy()
    frame.attrs['mode']='acbd'
    result=_trends(frame,'student',0)
    first=next(p for p in result if p['period']=='2025-01' and not p['include_batch'])
    assert first['counts']=={'T0':1,'T1':0}
    phq=next(r for r in first['statistics'] if r['variable_id']=='PHQ_total' and r['wave']=='T0')
    assert phq['mean']==0. and phq['valid_n']==1 and not phq['suppressed']
    hist=_exploration(frame,'student','synthetic-release',False,0)
    points=[r for r in hist if r['group']=='all' and r['variable_id']=='PHQ_total']
    assert sum(r['count'] for r in points if r['wave']=='T0')==1
    assert sum(r['count'] for r in points if r['wave']=='T1')==1
    assert all(r['bin_left'] is not None and r['count'] is not None for r in points)


def test_output_is_self_contained_and_does_not_contain_database_or_remote_dependencies(tmp_path):
    destination = tmp_path / 'website'
    result = write_site(snapshot(), destination)
    assert not result['deployed']
    assert {p.relative_to(destination).as_posix() for p in destination.rglob('*') if p.is_file()} == DEPLOY_FILES
    html = (destination / 'index.html').read_text()
    assert 'snapshot.js' in html and 'app.js' in html and 'https://' not in html
    config = json.loads((destination / 'vercel.json').read_text())
    assert config['framework'] is None and config['buildCommand'] == 'npm run build'
    assert config['installCommand'] == 'npm ci --ignore-scripts' and config['outputDirectory'] == 'public'
    assert 'connect-src' in config['headers'][0]['headers'][3]['value']


def test_repeat_export_preserves_vercel_association_but_refuses_unrelated_files(tmp_path):
    destination = tmp_path / 'website'
    write_site(snapshot(), destination)
    (destination / '.vercel').mkdir()
    (destination / '.vercel' / 'project.json').write_text('{"projectId":"synthetic"}')
    write_site(snapshot(), destination)
    assert json.loads((destination / '.vercel' / 'project.json').read_text())['projectId'] == 'synthetic'
    (destination / 'private.txt').write_text('must survive')
    with pytest.raises(PipelineError):
        write_site(snapshot(), destination)
    assert (destination / 'private.txt').read_text() == 'must survive'


def test_failed_output_replacement_restores_previous_export(tmp_path, monkeypatch):
    import study2.static_export as module
    destination = tmp_path / 'website'
    write_site(snapshot(), destination)
    old = (destination / 'snapshot.js').read_bytes()
    original = module.os.replace
    def fail_install(source, target):
        if Path(target) == destination and not str(source).endswith('-previous'):
            raise OSError('synthetic interrupted install')
        return original(source, target)
    monkeypatch.setattr(module.os, 'replace', fail_install)
    changed = {**snapshot(), 'release_id': 'next-release'}
    with pytest.raises(OSError):
        write_site(changed, destination)
    assert (destination / 'snapshot.js').read_bytes() == old


def test_output_rejects_symlinks(tmp_path):
    target = tmp_path / 'target'
    target.mkdir()
    link = tmp_path / 'link'
    link.symlink_to(target)
    with pytest.raises(PipelineError):
        write_site(snapshot(), link)
    assert list(target.iterdir()) == []


def test_column_encoding_preserves_precision_missing_values_and_original_object():
    stats = safe_statistics(statistics(rows(), 'student'))
    value = {**snapshot(), 'views': [dict(statistics=stats, changes=[], trends=[dict(statistics=stats)])]}
    packed = pack_snapshot(value)
    table = packed['views'][0]['statistics']
    restored = [dict(zip(table['columns'], row)) for row in table['rows']]
    assert restored == stats
    assert value['views'][0]['statistics'] is stats
    assert packed['views'][0]['changes'] == []
    assert packed['views'][0]['trends'][0]['statistics'] == table


def test_real_export_boundary_uses_formal_membership_without_copying_private_columns(tmp_path, monkeypatch):
    import study2.static_export as module
    from study2.common import file_hash
    from study2.descriptive_spec import DICTIONARY_VERSION, VERSION
    first = rows()
    second = rows('parent')
    second['submission_id'] = 'parent-' + second['submission_id']
    second['version_id'] = 'parent-' + second['version_id']
    frame = pd.concat([first, second], ignore_index=True)
    for key, value in dict(school='Private Example School', school_type='primary', mainstream=True,
                           gender='0', grade=4, identity_rules='exact', source_type='qualtrics',
                           source_label='private source locator', longitudinal=True, child_report_longitudinal=True,
                           dyad=True, longitudinal_dyad=True, email='private@example.com').items():
        frame[key] = value
    measurements = frame[['submission_id', 'version_id', 'observed_at']].copy()
    measurements['descriptive_dictionary_version'] = DICTIONARY_VERSION
    measurements['school_stage'] = 'primary'
    frame.to_parquet(tmp_path / 'analysis.parquet')
    frame.loc[frame['role'].eq('parent')].to_parquet(tmp_path / 'parent_longitudinal.parquet')
    measurements.to_parquet(tmp_path / 'descriptive_measurements.parquet')
    fingerprints = {p: file_hash(p) for p in tmp_path.iterdir()}
    summary = dict(release_id='synthetic-release', descriptive={'version': VERSION}, submissions=160,
                   stage_counts={'1.1': 160}, **{key: 40 for key in
                   ('A','B','C','D','AC','BD','E','F','EF','parent_child_longitudinal')})
    imported = pd.DataFrame([dict(source_type='qualtrics', role=role, wave=wave, submissions=40)
                             for role in ('student','parent') for wave in ('T0','T1')])
    monkeypatch.setattr(module, 'MODES', {'abcd': '全部', 'acbd': '跨期'})
    monkeypatch.setattr(module, 'SOURCE_NAMES', {'qualtrics': 'Qualtrics'})
    monkeypatch.setattr(module, 'GROUPS', {'all': '全部'})
    value = module.build_snapshot(tmp_path, summary, imported)
    assert value['minimum_cell_n']==0 and value['small_sample_policy']=='none'
    serialized = json.dumps(value, ensure_ascii=False)
    for text in ('Private Example School', 'private source locator', 'private@example.com', 'form-0-T0', 'person-0'):
        assert text not in serialized
    selected = next(v for v in value['views'] if v['mode']=='acbd' and v['role']=='parent'
                    and v['source']=='all' and not v['mainstream'])
    assert selected['counts']['all'] == {'T0': 40, 'T1': 40}
    assert all(file_hash(p) == before for p, before in fingerprints.items())
