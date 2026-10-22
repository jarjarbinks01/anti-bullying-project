"""Exercise display projections against synthetic, already-published aggregates."""
import json
import csv
import io
import shutil
import subprocess

import pytest

from study2.static_assets import APP_JS, HTML, STYLES
from study2.static_export import FORMAT, write_site


def display_models(payload):
    node = shutil.which('node')
    if not node:
        pytest.skip('Node is required for the static JavaScript display checks')
    helpers = APP_JS.split('/* Pure display models:', 1)[1].split('*/', 1)[1]
    helpers = helpers.split('/* End pure display models. */', 1)[0]
    values = '\n'.join(line for line in APP_JS.splitlines()
                       if line.startswith(('const n=', 'const num=', 'function statValue(')))
    script = values + '\n' + helpers + '''
const input = JSON.parse(require('fs').readFileSync(0, 'utf8'));
const before = JSON.stringify(input.rows);
console.log(JSON.stringify({
  rows: comparisonRows(input.rows, input.changes || []),
  families: input.keys.map(familyOf),
  meanings: input.keys.map(scoreMeaning),
  bases: ['overview','paired','trends'].map(reading=>readingBasis({reading})),
  buckets: input.stages.map(stageBucket),
  period: periodComparison(input.periods || [], input.metric || 'PHQ_total'),
  suggested: availablePeriod(input.periods || [], input.metric || 'PHQ_total'),
  selection: input.periods?.length ? periodSelection(input.periods, input.metric || 'PHQ_total', input.selected || {}) : null,
  issues: periodIssues(input.periods || [], input.metric || 'PHQ_total'),
  segments: trendSegments(input.points || []),
  unchanged: before === JSON.stringify(input.rows)
}));
'''
    result = subprocess.run([node, '-e', script], input=json.dumps(payload),
                            text=True, capture_output=True, check=True)
    return json.loads(result.stdout)


def observation(wave, **values):
    return dict(variable_id='PHQ_total', variable='PHQ 總分', category_code='',
                category='', unit='分', kind='continuous', wave=wave,
                mean=0, sd=None, valid_n=1, missing_n=39, suppressed=False, **values)


def test_comparison_projection_keeps_zero_unknown_sd_and_wave_denominators():
    payload = dict(rows=[observation('T0'), {**observation('T1'), 'mean':3.5,
                   'sd':1.2, 'valid_n':40, 'missing_n':0}], keys=['PHQ_total'], stages=[])
    result = display_models(payload)
    row = result['rows'][0]
    assert row['T0'] == '0.00 (—)' and row['T1'] == '3.50 (1.20)'
    assert (row['T0_n'], row['T0_missing'], row['T1_n'], row['T1_missing']) == (1,39,40,0)
    assert row['scale'] == '0–12' and result['unchanged']


def test_category_projection_preserves_suppression_and_does_not_average_codes():
    category = {**observation('T0'), 'variable_id':'phq_band', 'kind':'category',
                'variable':'PHQ 分數分組', 'category_code':'0_2', 'category':'0–2分',
                'numerator':0, 'denominator':40, 'proportion':0, 'valid_n':40, 'missing_n':0}
    hidden = {**category, 'wave':'T1', 'suppressed':True, 'numerator':None,
              'denominator':None, 'proportion':None, 'valid_n':None, 'missing_n':None}
    result = display_models(dict(rows=[category,hidden], keys=['phq_band'], stages=[]))
    row = result['rows'][0]
    assert row['T0'] == '0 / 40 (0.00%)'
    assert row['T1'] == 'Suppressed (small sample)' and row['T1_n'] is None
    assert result['families'] == ['PHQ'] and result['unchanged']


def test_families_scales_and_analysis_bases_remain_distinct():
    result = display_models(dict(rows=[], keys=['PHQ_total','PHQ_anxiety','FQOL_total',
        'SEC_total','TBV_mean','CBP_prevalence2','dem_child_age'],
        stages=['1.1','1.3/2.1.1/2.1.2','2.1.3','2.1.4','2.1.5','2.1.6','3.1.1','3.1.2/3.1.3']))
    assert result['families'] == ['PHQ','PHQ','FQOL','SEC','bullying','bullying','demographics']
    assert result['meanings'][0].startswith('0–12') and result['meanings'][1].startswith('0–6')
    assert result['buckets'] == [0,0,1,2,2,2,3,3]
    assert ['wave_valid','paired_valid','calendar_response'] == [v.split(' · ')[1] for v in result['bases']]
    assert result['rows'] == []


def test_every_export_uses_the_updated_presentation_and_valid_javascript(tmp_path):
    value = dict(format=FORMAT, release_id='synthetic-release', generated_at='2026-01-01T00:00:00Z',
                 published_at='2026-01-01T00:00:00Z', views=[])
    folder = tmp_path/'site'
    write_site(value, folder)
    assert (folder/'index.html').read_text() == HTML
    assert (folder/'app.js').read_text() == APP_JS
    assert (folder/'styles.css').read_text() == STYLES
    assert 'sample-sidebar' in STYLES and 'position:relative' in STYLES
    assert 'https://' not in HTML
    if node := shutil.which('node'):
        subprocess.run([node, '--check', str(folder/'app.js')], check=True, capture_output=True)


@pytest.mark.parametrize('settings', [
    {'minimum_cell_n':2,'small_sample_policy':'threshold'},
    {'minimum_cell_n':2,'small_sample_policy':'none'},
    {'minimum_cell_n':0,'small_sample_policy':'threshold'},
    {'minimum_cell_n':0,'small_sample_policy':'future'},
    {'minimum_cell_n':'0','small_sample_policy':'none'},
    {'minimum_cell_n':'2','small_sample_policy':'threshold'},
    {'minimum_cell_n':None,'small_sample_policy':'none'},
    {'minimum_cell_n':False,'small_sample_policy':'none'},
    {'minimum_cell_n':-1,'small_sample_policy':'none'},
    {'minimum_cell_n':.5,'small_sample_policy':'threshold'},
    {'minimum_cell_n':{},'small_sample_policy':'none'},
    {'minimum_cell_n':0}, {'small_sample_policy':'none'}, {},
    {'minimum_cell_n':0,'small_sample_policy':'none'},
])
def test_first_tab_requires_explicit_unsuppressed_snapshot_before_validating_or_mounting(settings):
    node=shutil.which('node')
    if not node:pytest.skip('Node is required for the static JavaScript display checks')
    overview='function overview() {'+APP_JS.split('function overview() {',1)[1].split('function controls(',1)[0]
    driver=r'''
const S=JSON.parse(require('fs').readFileSync(0,'utf8'));S.release_id='synthetic-policy';
const window={STUDY2_SCOPE_EXPORT:{format:'study2_static_scope_export_v1',status:'available',
  release_id:S.release_id,index_revision:'a'.repeat(64),index:{meta:{release_id:S.release_id}}}};
const calls={validate:0,mount:0,notices:[]},root={append(){}},tabs=['Data quality & progress'];
let qualityMount=null,qualitySelection=null;
function el(){return {};};function pageHeading(){};function notice(host,message){calls.notices.push(message);}
const Study2Scope={validate(){calls.validate++;}};
const Study2Quality={mount(){calls.mount++;return {};}};
OVERVIEW
overview();console.log(JSON.stringify(calls));
'''.replace('OVERVIEW',overview)
    result=subprocess.run([node,'-e',driver],input=json.dumps(settings),text=True,capture_output=True,check=True)
    calls=json.loads(result.stdout)
    allowed=type(settings.get('minimum_cell_n')) is int and settings.get('minimum_cell_n')==0 and settings.get('small_sample_policy')=='none'
    assert (calls['validate'],calls['mount'])==((1,1) if allowed else (0,0))
    assert len(calls['notices'])==(0 if allowed else 1)
    if not allowed:assert 'unavailable' in calls['notices'][0] and 'aggregate' in calls['notices'][0]


def test_csv_keeps_masked_cells_and_the_selected_analysis_context():
    node = shutil.which('node')
    if not node:
        pytest.skip('Node is required for the static JavaScript display checks')
    function = next(line for line in APP_JS.splitlines() if line.startswith('function csv('))
    script = function + '''
const S={release_id:'synthetic-release',generated_at:'2026-01-01'};
const page=1, parent={};
const state={mode:'acbd',role:'student',mainstream:false,source:'all',group:'all',
             reading:'paired',result:'table',family:'PHQ'};
console.log(JSON.stringify(csv([{item:'PHQ',count:0,estimate:null}],
                              {item:'指標',count:'有效 N',estimate:'數值'})));
'''
    result = subprocess.run([node,'-e',script], text=True, capture_output=True, check=True)
    table = list(csv.DictReader(io.StringIO(json.loads(result.stdout).lstrip('\ufeff'))))
    assert len(table) == 1
    assert table[0]['有效 N'] == '0' and table[0]['數值'] == ''
    assert table[0]['basis'] == 'paired_valid'
    assert table[0]['mode'] == 'acbd' and table[0]['family'] == 'all'
    assert table[0]['section'] == 'scales' and table[0]['download_type'] == 'paired_changes'
    assert 'result' not in table[0]
    assert table[0]['release_id'] == 'synthetic-release'


def g12_csv(rows, columns, *, download_scope=None, **selection):
    node = shutil.which('node')
    if not node:
        pytest.skip('Node is required for numeric download checks')
    function = next(line for line in APP_JS.splitlines() if line.startswith('function csv('))
    state = dict(mode='acbd', role='student', mainstream=False, source='all', group='all',
                 reading='overview', section='scales', family='all', result='table', variable='SEC_total',
                 trend_variable='PHQ_total', from_='2025-01', to='2025-03', batch=False)
    state['from'] = state.pop('from_')
    state.update(selection)
    metadata = dict(release_id='synthetic-release', generated_at='2026-01-01',
        report_version='synthetic-report', dictionary_version='synthetic-dictionary',
        inference_version='paired_t_dz_v1', descriptive_projection_version='study2_g12_v1',
        views=[dict(mode=state['mode'], role=state['role'], mainstream=state['mainstream'],
                    source=state['source'], grouping_anchor='student_T0', source_filter_anchor='student_T0')])
    script = function + '\nconst input=JSON.parse(require("fs").readFileSync(0,"utf8"));\n' + \
        'const S=input.S,page=1,state=input.state,parent={};console.log(JSON.stringify(csv(input.rows,input.columns,input.scope)));'
    result = subprocess.run([node, '-e', script], input=json.dumps(dict(S=metadata,
        state=state, rows=rows, columns=columns, scope=download_scope or {})), text=True, capture_output=True, check=True)
    return list(csv.DictReader(io.StringIO(json.loads(result.stdout).lstrip('\ufeff'))))


def test_g12_csv_retains_raw_precision_identity_headers_and_fixed_metadata():
    rows = [dict(variable_id='PHQ_total', variable='PHQ total', estimate=1/3,
                 p_value=0.0000002, count=0, sd=None, test_basis='paired_valid'),
            dict(variable_id='FQOL_total', variable='FQOL total', estimate=4/3,
                 p_value=.5, count=2, sd=.12345678912345, test_basis='paired_valid')]
    output = g12_csv(rows, dict(variable_id='Variable ID', variable='Metric', estimate='Mean (raw)',
        p_value='p-value (raw)', count='Valid N', sd='SD (raw)', test_basis='Test basis'),
        private_answer='must not enter metadata', source='paperform', group='female')
    assert [r['Metric'] for r in output] == ['PHQ total', 'FQOL total']
    assert [r['Variable ID'] for r in output] == ['PHQ_total', 'FQOL_total']
    assert float(output[0]['Mean (raw)']) == 1/3 and float(output[0]['p-value (raw)']) == .0000002
    assert output[0]['Valid N'] == '0' and output[0]['SD (raw)'] == ''
    assert float(output[1]['SD (raw)']) == .12345678912345
    for row in output:
        assert row['basis'] == 'wave_valid' and row['Test basis'] == 'paired_valid'
        assert row['source'] == 'paperform' and row['group'] == 'female'
        assert 'selection_variable' not in row and 'selection_period_variable' not in row
        assert row['section'] == 'scales' and row['family'] == 'all'
        assert row['report_version'] == 'synthetic-report' and row['dictionary_version'] == 'synthetic-dictionary'
        assert row['projection_version'] == 'study2_g12_v1' and row['grouping_anchor'] == 'student_T0'
        assert 'private_answer' not in row


def test_g12_csv_calendar_context_is_complete_months_and_keeps_nulls_hidden():
    output = g12_csv([dict(variable='PHQ total', value=None, valid_n=None, status='suppressed')],
        dict(variable='Metric', value='Value (raw)', valid_n='Valid N', status='Status'),
        reading='trends', batch=True, **{'from':'2025-02','to':'2025-03'})[0]
    assert output['Value (raw)'] == output['Valid N'] == '' and output['Status'] == 'suppressed'
    assert output['basis'] == 'calendar_response' and output['interval'] == 'complete_month'
    assert output['period_from'] == '2025-02' and output['period_to'] == '2025-03'
    assert output['include_batch_dates'] == 'true' and output['timezone'] == 'Asia/Hong_Kong'


@pytest.mark.parametrize('scope,selection,section,family,variable,period', [
    ({'type':'statistics','section':'scales','family':'PHQ'},
     {'reading':'overview'}, 'scales', 'PHQ', None, None),
    ({'type':'paired_changes'}, {'reading':'paired'}, 'scales', 'all', None, None),
    ({'type':'histogram','variable':'FQOL_total','family':'FQOL','basis':'paired_valid'},
     {'reading':'paired'}, 'scales', 'FQOL', 'FQOL_total', None),
    ({'type':'statistics','section':'student'},
     {'reading':'overview','section':'student'}, 'student', None, None, None),
    ({'type':'statistics','section':'parent'},
     {'reading':'overview','section':'parent','role':'parent'}, 'parent', None, None, None),
    ({'type':'period_summary','variable':'FQOL_total','family':'FQOL'},
     {'reading':'trends'}, 'scales', 'FQOL', None, 'FQOL_total'),
    ({'type':'period_summary','variable':'volume'},
     {'reading':'trends'}, 'responses', None, None, 'volume'),
    ({'type':'monthly_detail','variable':'volume','family':'all'},
     {'reading':'trends'}, 'scales', 'all', None, 'volume'),
    ({'type':'transitions'}, {'reading':'paired'}, 'scales', 'bullying', None, None),
])
def test_g12_r2_download_scope_omits_inactive_remembered_controls(scope, selection, section, family, variable, period):
    rows=[dict(variable_id='FQOL_total',variable='FQOL total',mean=4/3,count=1,sd=None)]
    context=dict(family='PHQ',section='scales',result='table',variable='SEC_total',
                 trend_variable='PHQ_total',source='paperform',group='female')
    context.update(selection)
    row=g12_csv(rows,dict(variable_id='Variable ID',variable='Metric',mean='Mean (raw)',
        count='Valid N',sd='SD (raw)'),download_scope=scope,**context)[0]
    assert row['section']==section and row.get('family')==family
    assert row['download_type']==scope['type'] and 'result' not in row
    assert row.get('selection_variable')==variable and row.get('selection_period_variable')==period
    assert row['source']=='paperform' and row['group']=='female'
    assert row['Variable ID']=='FQOL_total' and row['Metric']=='FQOL total'
    assert float(row['Mean (raw)'])==4/3 and row['Valid N']=='1' and row['SD (raw)']==''
    assert row['report_version']=='synthetic-report' and row['dictionary_version']=='synthetic-dictionary'
    assert row['grouping_anchor']=='student_T0' and row['source_filter_anchor']=='student_T0'
    if period:
        assert row['basis']=='calendar_response' and row['period_from']=='2025-01'
        assert row['period_to']=='2025-03' and row['interval']=='complete_month'
    else:
        assert 'period_from' not in row and 'period_to' not in row and 'include_batch_dates' not in row


def test_g12_comparison_has_numeric_wave_audit_and_paired_means_on_separate_bases():
    data=dict(rows=[{**observation('T0'), 'group':'all', 'sample_n':3, 'valid_n':3,
        'missing_n':0,'outside_range_n':0,'mean':6.,'sd':4.},
        {**observation('T1'),'group':'all','sample_n':3,'valid_n':2,
        'missing_n':1,'outside_range_n':1,'mean':4.5,'sd':.7071067811865476}],
        changes=[dict(variable_id='PHQ_total',group='all',pairs_n=3,paired_valid_n=2,
            paired_missing_n=1,only_t0_valid_n=1,only_t1_valid_n=0,both_missing_n=0,
            t0_mean=4.,t1_mean=4.5,mean_change=.5,sd_change=2.1213203435596424,
            p_value=.7951672353008665,cohen_dz=.23570226039551587,
            pair_detail_status='available',inference_status='estimated')],keys=[],stages=[])
    row=display_models(data)['rows'][0]
    assert row['T0_mean']==6 and row['paired_t0_mean']==4 and row['paired_t1_mean']==4.5
    assert row['T0_sample_n']==row['T0_n']+row['T0_missing']==3
    assert row['T1_sample_n']==row['T1_n']+row['T1_missing']==3
    assert row['T1_outside_range_n']==1 and row['paired_only_t1_valid_n']==0
    assert row['formal_pairs_n']==3 and row['paired_missing_n']==1
    data['changes']=[]
    old=display_models(data)['rows'][0]
    assert old['pair_detail_status']=='not_provided' and old['paired_t0_mean'] is None
    assert old['formal_pairs_n'] is None


def test_g12_category_code_and_raw_denominator_are_preserved():
    category={**observation('T0'),'group':'all','variable_id':'phq_band','kind':'category',
        'category_code':'3_5','category':'3-5 points','numerator':1,'denominator':3,
        'proportion':1/3,'valid_n':3,'sample_n':4,'missing_n':1,'outside_range_n':0}
    row=display_models(dict(rows=[category],keys=[],stages=[]))['rows'][0]
    assert row['category_code']=='3_5' and row['T0_numerator']==1
    assert row['T0_denominator']==3 and row['T0_proportion']==1/3 and row['test_n'] is None


def test_overview_joins_exact_indicator_and_group_and_keeps_pair_denominator_separate():
    change=dict(variable_id='PHQ_total',group='all',paired_valid_n=20,p_value=0.0000002,
                cohen_dz=-0.456,inference_status='estimated')
    data=dict(rows=[{**observation('T0'),'group':'all','valid_n':90},
                    {**observation('T1'),'group':'all','valid_n':40}],
              changes=[{**change,'group':'male','paired_valid_n':5},change],keys=[],stages=[])
    result=display_models(data)['rows'][0]
    assert result['test_n']==20 and result['T0_n']==90 and result['T1_n']==40
    assert result['p']=='<0.001' and result['dz']=='-0.46'
    assert result['p_value']==change['p_value'] and result['test_basis']=='paired_valid'
    data['changes']=[{**change,'paired_valid_n':None,'p_value':None,'cohen_dz':None,
                      'inference_status':'suppressed'}]
    hidden=display_models(data)['rows'][0]
    assert hidden['test_n'] is None and hidden['p']=='—' and hidden['dz']=='—'


def test_period_two_point_means_and_sd_are_weighted_by_valid_responses():
    import numpy as np
    a=np.array([0.,1.,2.,3.]*3)
    b=np.array([4.,5.,6.,7.]*8)
    periods=[]
    for month,values in [('2025-01',a),('2025-02',b)]:
        stats=dict(wave='T0',variable_id='PHQ_total',sample_n=len(values)+2,
                   valid_n=len(values),missing_n=2,mean=float(values.mean()),
                   sd=float(values.std(ddof=1)),suppressed=False)
        periods.append(dict(period=month,counts={'T0':len(values)+2,'T1':0},statistics=[stats]))
    result=display_models(dict(rows=[],keys=[],stages=[],periods=periods))['period']
    t0,t1=result
    all_values=np.concatenate([a,b])
    assert t0['value']==pytest.approx(all_values.mean())
    assert t0['sd']==pytest.approx(all_values.std(ddof=1))
    assert t0['valid_n']==44 and t0['missing_n']==4 and t0['sample_n']==48
    assert t1['value'] is None and t1['valid_n']==0
    single=display_models(dict(rows=[],keys=[],stages=[],periods=periods[1:]))['period'][0]
    assert single['value']==pytest.approx(b.mean()) and single['valid_n']==32


def test_masked_month_blocks_the_whole_wave_and_never_connects_a_hidden_point():
    periods=[dict(period='2025-01',counts={'T0':20,'T1':0},statistics=[dict(
        wave='T0',variable_id='PHQ_total',sample_n=20,valid_n=20,missing_n=0,
        mean=0.,sd=0.,suppressed=False)]),dict(period='2025-02',counts={'T0':None,'T1':0},
        statistics=[dict(wave='T0',variable_id='PHQ_total',sample_n=None,
            valid_n=None,missing_n=None,mean=None,sd=None,suppressed=True)])]
    points=[dict(value=0.),dict(value=None),dict(value=2.)]
    result=display_models(dict(rows=[],keys=[],stages=[],periods=periods,points=points))
    assert result['period'][0]['value'] is None and result['period'][0]['status']=='suppressed'
    assert [len(segment) for segment in result['segments']]==[1,1]
    assert result['segments'][0][0]['value']==0


def trend_month(month, *, t0=20, t1=20, hidden=(), mean=2.):
    """Synthetic published month, including explicit empty and hidden waves."""
    stats=[]
    counts={}
    for wave, size in [('T0',t0),('T1',t1)]:
        masked=wave in hidden
        counts[wave]=None if masked else size
        stats.append(dict(wave=wave,variable_id='PHQ_total',
            valid_n=None if masked else size, missing_n=None if masked else 0,
            mean=None if masked or not size else mean,
            sd=None if masked or size<2 else 1.,suppressed=masked))
    return dict(period=month,counts=counts,statistics=stats)


def trend_models(periods, **values):
    return display_models(dict(rows=[],keys=[],stages=[],periods=periods,**values))


def test_default_period_uses_longest_unbroken_visible_run_and_keeps_zero_months():
    periods=[trend_month('2025-01'),trend_month('2025-02',hidden=('T1',)),
             trend_month('2025-03'),trend_month('2025-04',t0=0,t1=0),
             trend_month('2025-05',mean=0.),trend_month('2025-06',hidden=('T0',)),
             trend_month('2025-07')]
    result=trend_models(periods)
    assert result['suggested']=={'from':'2025-03','to':'2025-05','months':3}
    assert result['selection']['automatic']
    assert result['selection']['from']=='2025-03' and result['selection']['to']=='2025-05'
    points=trend_models(periods[2:5])['period']
    assert all(point['valid_n']==40 and point['value']==1. for point in points)
    assert result['issues'][0]['suppressed']==['2025-06']
    assert result['issues'][1]['suppressed']==['2025-02']


def test_period_selection_ties_choose_recent_run_without_using_scores():
    periods=[trend_month('2025-01',mean=0.),trend_month('2025-02',mean=0.),
             trend_month('2025-03',hidden=('T0',)),trend_month('2025-04',mean=12.),
             trend_month('2025-05',mean=12.)]
    expected={'from':'2025-04','to':'2025-05','months':2}
    assert trend_models(periods)['suggested']==expected
    for period in periods:
        for stat in period['statistics']:
            if stat['mean'] is not None:
                stat['mean']=12.-stat['mean']
    assert trend_models(periods)['suggested']==expected


def test_manual_range_is_retained_even_if_hidden_and_auto_recomputes_stale_dates():
    periods=[trend_month('2025-01',hidden=('T1',)),trend_month('2025-02'),
             trend_month('2025-03')]
    manual=dict(period_auto=False,**{'from':'2025-01','to':'2025-03'})
    result=trend_models(periods,selected=manual)
    assert result['selection']['from']=='2025-01'
    assert result['selection']['to']=='2025-03' and not result['selection']['automatic']
    assert result['period'][1]['value'] is None
    automatic=trend_models(periods,selected={**manual,'period_auto':True})['selection']
    assert automatic['from']=='2025-02' and automatic['to']=='2025-03'
    # A manual interval outside a newly selected cohort is also kept explicit.
    assert trend_models(periods[1:],selected=manual)['selection']==result['selection']


def test_missing_calendar_month_splits_available_runs_instead_of_bridging_a_gap():
    periods=[trend_month('2025-01'),trend_month('2025-02'),trend_month('2025-04')]
    assert trend_models(periods)['suggested']=={'from':'2025-01','to':'2025-02','months':2}


def test_no_two_wave_interval_is_reported_without_fabricating_a_second_point():
    periods=[trend_month('2025-01',t1=0),trend_month('2025-02',t1=0)]
    result=trend_models(periods,selected=dict(period_auto=True,**{'from':'2020-01','to':'2020-02'}))
    assert result['suggested'] is None
    assert result['selection']['from']=='2025-01' and result['selection']['to']=='2025-02'
    assert result['period'][0]['value']==2. and result['period'][1]['value'] is None


def test_metric_masking_and_count_masking_control_availability_separately():
    periods=[trend_month('2025-01'),trend_month('2025-02')]
    periods[0]['statistics'][0].update(suppressed=True,valid_n=None,missing_n=None,mean=None,sd=None)
    assert trend_models(periods)['suggested']=={'from':'2025-02','to':'2025-02','months':1}
    # Response volume remains visible when only the score is hidden.
    assert trend_models(periods,metric='volume')['suggested']['months']==2
    periods[1]['counts']['T0']=None
    result=trend_models(periods)
    assert result['suggested'] is None
    assert result['issues'][0]['counts_suppressed']==['2025-02']
    # A hidden count is never recovered from a visible score's valid N.
    assert result['period'][0]['sample_n'] is None
    assert result['issues'][0]['suppressed']==['2025-01']


def test_incomplete_statistic_blocks_default_and_is_distinct_from_suppression():
    periods=[trend_month('2025-01'),trend_month('2025-02')]
    periods[0]['statistics'][0]['sd']=None
    result=trend_models(periods)
    assert result['suggested']['from']=='2025-02'
    assert result['issues'][0]['unavailable']==['2025-01']
    assert result['issues'][0]['suppressed']==[]


def test_full_period_keeps_single_response_months_in_each_wave():
    periods=[trend_month('2025-01',t0=1,t1=1,mean=0.),
             trend_month('2025-02',t0=1,t1=1,mean=4.)]
    result=trend_models(periods,selected={'period_auto':False})
    assert result['selection']['from']=='2025-01' and result['selection']['to']=='2025-02'
    for wave in result['period']:
        assert wave['sample_n']==2 and wave['valid_n']==2 and wave['value']==2.
        assert wave['sd']==pytest.approx(2**1.5)
    assert all(not issue['suppressed'] and not issue['counts_suppressed'] for issue in result['issues'])
