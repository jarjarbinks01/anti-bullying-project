"""Focused synthetic JS/DOM checks. No service, database or research input."""
import csv
import io
import json
from pathlib import Path
import shutil
import subprocess

import pytest

from study2.static_period_ui import JS_SOURCE


COMMON = r'''
const assert=require('node:assert/strict'),{webcrypto,createHash}=require('node:crypto');
const copy=x=>JSON.parse(JSON.stringify(x)),hash=text=>createHash('sha256').update(text).digest('hex');
const FORMAT='study2_period_filters_v1',base='https://synthetic.test/research/';
const calls={fetch:[],queries:[],notices:[],tables:[],charts:[],cards:[],selects:[]};
function cube(mode='abcd',role='student') {return {format:FORMAT,release_id:'RUN_SYNTHETIC',mode,role,
 grade_anchor:'student_T0',grouping_anchor:'student_T0',source_filter_anchor:'student_T0',timezone:'Asia/Hong_Kong',date_policy:'native_calendar_response_v1',
 metrics:[{variable_id:'PHQ_total',kind:'continuous',unit:'score',available:true},{variable_id:'TBV_prevalence1',kind:'binary',unit:'proportion',available:true},{variable_id:'unavailable',kind:'continuous',unit:'score',available:false}],
 cell_fields:['date','wave','gender','stage','grade','source','mainstream','date_quality','n','values'],
 cells:[['2024-08-31','T0','0','primary','P3','qualtrics',true,'system_creation',1,[[1,0,1,0],[1,0,0],null]],['2026-03-14','T1','0','primary','P3','qualtrics',true,'system_creation',1,[[1,0,2,0],[1,0,1],null]]]};}
const Period={FORMAT,validate(c){assert.equal(c.format,FORMAT);return c;},query(c,s){
 calls.queries.push(copy(s));assert(['all','male_primary'].includes(s.group));
 const key=s.variable_id||'PHQ_total',m=c.metrics.find(m=>m.variable_id===key);assert(m,'Invalid metric');
 const size=s.grades.length&&s.sources.length?2:0,available=m.available;
 const rows=['T0','T1'].map(wave=>({wave,variable_id:key,kind:m.kind,unit:m.unit,available,sample_n:size,
  valid_n:available?size:null,missing_n:available?0:null,outside_range_n:available?0:null,
  mean:available&&size?(m.kind==='binary'?0:1.2345678901234567):null,sd:available&&size&&m.kind!=='binary'?0.1234567890123456:null,
  numerator:m.kind==='binary'?0:0,denominator:available?size:null,proportion:available&&size?0:null}));
 return {status:size?'available':'empty',whole_period:rows,
  statistics:rows.map(r=>({...r,period_id:s.from.slice(0,7),covered_start:s.from,covered_end:s.to,partial_period:true})),
  counts:['T0','T1'].map(wave=>({period_id:s.from.slice(0,7),wave,sample_n:size,covered_start:s.from,covered_end:s.to,partial_period:true,batch_date_n:0,manual_date_n:0})),
  date_quality:['T0','T1'].map(wave=>({wave,date_quality:'system_creation',input_n:size,included_n:size})),
  exclusions:['T0','T1'].map(wave=>({wave,stage:'period',remaining_n:size,excluded_n:0})),metadata:copy(s)};
}};
function setup(cubes=[cube()]) {const assets={},refs=[];
 for(const c of cubes)for(const eligibility of ['off','on']){const asset=`period-${eligibility}-${c.mode}-${c.role}.json`,text=JSON.stringify(c)+'\n';assets[asset]=text;
  refs.push({asset,sha256:hash(text),status:'available',code:null,release_id:c.release_id,mode:c.mode,role:c.role,eligibility,eligibility_revision:eligibility==='on'?'accepted-on-revision':null,extent:{start:'2024-08-31',end:'2026-03-14'}});}
 return {assets,snapshot:{release_id:'RUN_SYNTHETIC',minimum_cell_n:0,modes:{abcd:'Each wave',acbd:'Formal',ef:'Per-wave dyad',efmatched:'Formal dyad',independent_all:'Parent waves'},groups:{all:'All children',male_primary:'Male primary'},source_names:{all:'All sources',qualtrics:'Qualtrics',paperform:'Paper'},dictionary:[{variable_id:'PHQ_total',label:'PHQ total'},{variable_id:'TBV_prevalence1',label:'Bullying prevalence'}],
  period_selection:{format:FORMAT,status:'available',code:null,release_id:'RUN_SYNTHETIC',profile:'protected_researcher',minimum_cell_n:0,refs}}};}
const initialState=()=>({mode:'abcd',role:'student',grades:['P3','Unknown'],sources:['qualtrics','paperform'],mainstream:true,group:'male_primary',batch:false,trend_variable:'PHQ_total',trend_axis:'full',reading:'trends'});
function response(text,url){const bytes=Buffer.from(text);return {ok:true,status:200,url,arrayBuffer:async()=>bytes.buffer.slice(bytes.byteOffset,bytes.byteOffset+bytes.byteLength)};}
function fetcher(assets){return async(url,options)=>{calls.fetch.push({url,options});return response(assets[new URL(url).pathname.split('/').at(-1)],url);};}
class Element {constructor(tag,cls='',text){this.tag=tag;this.className=cls;this.textContent=text;this.children=[];this.dataset={};this.attributes={};}append(...xs){this.children.push(...xs);}setAttribute(k,v){this.attributes[k]=v;}}
const el=(...args)=>new Element(...args),walk=node=>[node,...(node.children||[]).flatMap(walk)];
function environment(snapshot,st,scope,loader,extra={}) {const host=el('section');return {host,snapshot,state:st,scope,loader,period:Period,
 isCurrent:()=>true,rerender:()=>{},el,select:(host,label,value,options,changed)=>{const node=el('select','',label);Object.assign(node,{value,options,changed});host.append(node);calls.selects.push(node);return node;},
 notice:(host,text,warning)=>{calls.notices.push(text);host.append(el('p',warning?'warning':'notice',text));},cards:(host,rows)=>calls.cards.push(copy(rows)),
 table:(host,rows,columns,name,wide,raw,scope)=>calls.tables.push({rows:copy(rows),columns,name,raw,scope}),lineChart:(...args)=>calls.charts.push(args),
 num:x=>x===null?'—':Number(x).toFixed(2),n:x=>String(x),present:Study2PeriodUI.present,...extra};}
function readyLoader(c,snapshot,scope='off'){return {load(){return {status:'ready',cube:c,ref:snapshot.period_selection.refs.find(r=>r.mode===c.mode&&r.role===c.role&&r.eligibility===scope)};}};}
'''


def run_js(body):
    node = shutil.which('node')
    if not node:
        pytest.skip('Existing Node runtime required')
    script = JS_SOURCE + '\n' + COMMON + '\n(async()=>{\n' + body + '\n})().catch(error=>{console.error(error);process.exitCode=1;});'
    result = subprocess.run([node, '-e', script], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout) if result.stdout.strip() else None


def test_real_sha_lazy_scope_binding_and_bounded_lru():
    run_js(r'''
const {assets,snapshot}=setup([cube(),cube('abcd','parent'),cube('acbd'),cube('ef')]);
const loader=Study2PeriodUI.createLoader({getPeriod:()=>Period,fetcher:fetcher(assets),cryptoAPI:webcrypto,base});
assert.equal(calls.fetch.length,0,'constructor must not fetch at startup');
for(const [mode,role]of [['abcd','student'],['abcd','parent'],['acbd','student'],['ef','student']]){
 const entry=loader.load(snapshot,{...initialState(),mode,role},{mode:'off',revision:null});await entry.promise;assert.equal(entry.status,'ready');}
assert.equal(loader.size(),3);assert.equal(calls.fetch.length,4);
for(const call of calls.fetch){assert.equal(call.options.credentials,'same-origin');assert.equal(call.options.cache,'no-store');assert.equal(new URL(call.url).origin,new URL(base).origin);}
const on=loader.load(snapshot,initialState(),{mode:'on',revision:'accepted-on-revision'});await on.promise;assert.equal(on.status,'ready');
assert(loader.keys().some(k=>k.includes('accepted-on-revision')));
assert.throws(()=>loader.load(snapshot,initialState(),{mode:'on',revision:'wrong-revision'}),/exclusion revision/);
''')


@pytest.mark.parametrize('kind', ['hash', 'cube_binding', 'redirect', 'path', 'positive', 'unavailable'])
def test_invalid_assets_never_render_a_fallback(kind):
    run_js(r'''
const kind=KIND,{assets,snapshot}=setup(),ref=snapshot.period_selection.refs[0];let fetch=fetcher(assets);
if(kind==='hash')ref.sha256='0'.repeat(64);
if(kind==='cube_binding'){const bad=cube('abcd','parent');assets[ref.asset]=JSON.stringify(bad);ref.sha256=hash(assets[ref.asset]);}
if(kind==='redirect')fetch=async(url)=>response(assets[ref.asset],new URL('login.html',base).href);
if(kind==='path')ref.asset='../period-off-abcd-student.json';
if(kind==='positive')snapshot.minimum_cell_n=5;
if(kind==='unavailable'){ref.status='unavailable';ref.code='accepted_manifest_required';}
const loader=Study2PeriodUI.createLoader({getPeriod:()=>Period,fetcher:fetch,cryptoAPI:webcrypto,base});
if(['path','positive','unavailable'].includes(kind)){assert.throws(()=>loader.load(snapshot,initialState(),{mode:'off'}));assert.equal(calls.fetch.length,0);}
else{const entry=loader.load(snapshot,initialState(),{mode:'off'});await entry.promise;assert.equal(entry.status,'error');assert.equal(entry.cube,null);}
assert.equal(calls.queries.length,0);
'''.replace('KIND', json.dumps(kind)))


def test_academic_year_boundaries_custom_dates_and_empty_controls_persist():
    run_js(r'''
const c=cube(),{snapshot}=setup(),st=initialState();st.sources=[];st.grades=[];
const env=environment(snapshot,st,{mode:'off'},readyLoader(c,snapshot));Study2PeriodUI.mount(env);
assert.equal(st.period_day_from,'2024-08-31');assert.equal(st.period_day_to,'2026-03-14');
assert.deepEqual(calls.queries[0].sources,[]);assert.deepEqual(calls.queries[0].grades,[]);assert.equal(calls.queries[0].group,'male_primary');
assert(walk(env.host).filter(n=>n.tag==='input'&&n.type==='date').length===2);
assert(calls.notices.some(n=>n.includes('zero responses')));
const presets=calls.selects.find(n=>n.textContent==='Period preset');
assert(presets.options['academic:2023'].includes('2023-09-01 to 2024-08-31'));
assert(presets.options['academic:2025'].includes('2025-09-01 to 2026-08-31'));
assert(!Object.hasOwn(presets.options,'academic:2024'),'years derive from actual cube date cells');
presets.changed('academic:2025');assert.equal(st.period_day_from,'2025-09-01');assert.equal(st.period_day_to,'2026-08-31');
const input=walk(env.host).find(n=>n.dataset.control==='period-day:from');input.value='2031-02-04';input.onchange();
assert.equal(st.period_preset,'custom');
Object.assign(st,{period_day_to:'2031-02-06',batch:true});
Study2PeriodUI.mount(environment(snapshot,st,{mode:'on',revision:'accepted-on-revision'},readyLoader(c,snapshot,'on')));
assert.equal(st.period_day_from,'2031-02-04');assert.equal(st.period_day_to,'2031-02-06');
assert.equal(calls.queries.at(-1).from,'2031-02-04');assert(calls.queries.at(-1).include_batch);
assert(Study2PeriodUI.day('2024-02-29'));assert(!Study2PeriodUI.day('2025-02-29'));
''')


def test_loading_and_unavailable_states_keep_dates_metric_and_filters_visible():
    run_js(r'''
const {snapshot}=setup(),st={...initialState(),period_day_initialized:true,period_day_from:'2030-01-02',period_day_to:'2030-01-01'};
let env=environment(snapshot,st,{mode:'on',revision:'wrong'},Study2PeriodUI.createLoader({getPeriod:()=>Period,fetcher:()=>{throw Error('must not fetch');},cryptoAPI:webcrypto,base}));
Study2PeriodUI.mount(env);assert(walk(env.host).filter(n=>n.type==='date').length===2);assert(calls.selects.some(n=>n.textContent==='Period comparison metric'));
assert(calls.notices.some(n=>n.includes('No unfiltered period result')));assert.equal(calls.queries.length,0);
env=environment(snapshot,st,{mode:'off'},readyLoader(cube(),snapshot));Study2PeriodUI.mount(env);
assert(calls.notices.some(n=>n.includes('start date')));assert.equal(calls.queries.length,0);assert.equal(st.period_day_to,'2030-01-01');
''')


def test_stale_async_completion_never_repaints_a_new_role_or_page():
    run_js(r'''
const {assets,snapshot}=setup([cube(),cube('abcd','parent')]),pending=new Map();
const loader=Study2PeriodUI.createLoader({getPeriod:()=>Period,cryptoAPI:webcrypto,base,
 fetcher:(url)=>new Promise(resolve=>pending.set(new URL(url).pathname.split('/').at(-1),()=>resolve(response(assets[new URL(url).pathname.split('/').at(-1)],url))))});
let epoch=0,renders=0,current=initialState();
function render(){renders++;const token=++epoch;Study2PeriodUI.mount(environment(snapshot,current,{mode:'off'},loader,{isCurrent:()=>token===epoch,rerender:render}));}
render();current={...initialState(),role:'parent'};render();
pending.get('period-off-abcd-student.json')();await new Promise(r=>setTimeout(r,10));assert.equal(renders,2);
pending.get('period-off-abcd-parent.json')();await new Promise(r=>setTimeout(r,10));assert.equal(renders,3);assert(calls.queries.length===1);
current={...initialState(),mode:'abcd',role:'student'};epoch++; // A different page invalidates all previous render tokens.
assert.equal(renders,3);
''')


def test_metric_absence_is_distinct_from_missing_and_binary_has_denominator():
    result = run_js(r'''
const {snapshot}=setup(),st={...initialState(),trend_variable:'unavailable'};
Study2PeriodUI.mount(environment(snapshot,st,{mode:'off'},readyLoader(cube(),snapshot)));
assert(calls.tables[0].rows.every(r=>r.available===false&&r.valid_n===null&&r.missing_n===null));
assert(calls.tables[0].rows[0].estimate.includes('not all-missing'));
st.trend_variable='TBV_prevalence1';Study2PeriodUI.mount(environment(snapshot,st,{mode:'off'},readyLoader(cube(),snapshot)));
const binary=calls.tables.find(t=>t.rows.some(r=>r.variable_id==='TBV_prevalence1'));
assert(binary.rows.every(r=>r.numerator===0&&r.denominator===2&&r.proportion===0));
console.log(JSON.stringify({raw:binary.rows,metadata:binary.scope.metadata}));
''')
    assert result['metadata']['basis'] == 'calendar_response'
    assert result['metadata']['interval'] == 'inclusive_day'
    assert result['metadata']['period_asset_sha256']


def test_actual_research_entry_does_not_drop_controls_for_empty_source_grade_selection():
    from study2.static_assets import APP_JS
    research = APP_JS.split('function research(independent=false) {', 1)[1].split('function statisticsTable(', 1)[0]
    research = 'function research(independent=false) {' + research
    combined = APP_JS.split('function combinedTrends(st) {', 1)[1].split('function trends(', 1)[0]
    combined = 'function combinedTrends(st) {' + combined
    run_js(r'''
const {snapshot}=setup(),S=snapshot,eligibility=null,renderEpoch=4,st={...initialState(),sources:[],grades:[]};
const parent={},root=el('main');let contentHost=root;const state=st;
const periodLoader=readyLoader(cube(),snapshot),n=x=>String(x),num=x=>String(x);
function pageHeading(){}function render(){}function controls(){contentHost.append(el('aside','sample-sidebar'));}
function switches(host){host.append(el('div','switcher'));}function chosenView(){throw Error('Fine trends must precede legacy empty-source early return');}
function section(title,note){const node=el('section','',title);contentHost.append(node);return node;}
const env=environment(snapshot,st,{mode:'off'},periodLoader),{select,notice,cards,table}=env;
function periodLineChart(){}
RESEARCH
COMBINED
research(false);assert(walk(root).some(n=>n.className==='sample-sidebar'));assert(walk(root).filter(n=>n.type==='date').length===2);
assert.deepEqual(calls.queries[0].grades,[]);assert.deepEqual(calls.queries[0].sources,[]);
'''.replace('RESEARCH', research).replace('COMBINED', combined))


def test_real_csv_retains_exact_day_anchor_scope_provenance_and_full_precision():
    from study2.static_assets import APP_JS
    function = next(line for line in APP_JS.splitlines() if line.startswith('function csv('))
    result = run_js(r'''
const {snapshot}=setup(),state=Object.assign(globalThis.stateFactory||{}, {mode:'acbd',role:'parent',sources:['qualtrics'],grades:['P3'],group:'male_primary',mainstream:true,reading:'trends',trend_variable:'PHQ_total',batch:false,period_day_from:'2025-09-03',period_day_to:'2026-03-30'}),S={...snapshot,generated_at:'synthetic'};
const page=1,parent={},eligibility={configured:true,metadata:()=>({eligibility_revision:'accepted-on-revision'})},releaseMetadata=()=>({analytical_run_id:'RUN_SYNTHETIC'}),Source={choose:()=>({})};
const meta=Study2PeriodUI.csvMetadata(S,state,{mode:'on',revision:'accepted-on-revision'},cube('acbd','parent'),{date_quality:[{wave:'T0',input_n:4,included_n:2}],exclusions:[],metadata:{from:state.period_day_from,to:state.period_day_to}});
CSV_FUNCTION
const continuous=csv([{wave:'T0',mean:1.2345678901234567,valid_n:2,missing_n:0}],{wave:'Wave',mean:'Mean (raw)',valid_n:'Valid N',missing_n:'Missing N'},{type:'period_summary',metadata:meta});
state.trend_variable='TBV_prevalence1';
const binary=csv([{wave:'T0',proportion:0.12345678901234566,numerator:10,denominator:81}],{wave:'Wave',proportion:'Proportion (raw)',numerator:'Numerator',denominator:'Denominator'},{type:'period_summary',metadata:meta});
console.log(JSON.stringify({continuous,binary}));
'''.replace('CSV_FUNCTION', function))
    row = next(csv.DictReader(io.StringIO(result['continuous'].lstrip('\ufeff'))))
    binary = next(csv.DictReader(io.StringIO(result['binary'].lstrip('\ufeff'))))
    assert binary['Proportion (raw)'] == '0.12345678901234566'
    assert binary['Numerator'] == '10' and binary['Denominator'] == '81'
    assert row['Mean (raw)'] == '1.2345678901234567'
    assert row['period_from'] == '2025-09-03' and row['period_to'] == '2026-03-30'
    assert row['interval'] == 'inclusive_day' and row['timezone'] == 'Asia/Hong_Kong'
    assert row['filter_grade_codes'] == 'P3' and row['filter_source_codes'] == 'qualtrics'
    assert row['grade_anchor'] == 'student_T0' and row['eligibility_revision'] == 'accepted-on-revision'
    assert json.loads(row['date_provenance'])[0]['included_n'] == 2


def test_actual_binary_chart_has_proportion_axis_and_numerator_denominator_tooltips():
    from study2.static_assets import APP_JS
    chart = 'function periodLineChart(' + APP_JS.split('function periodLineChart(', 1)[1].split('function chosenView(', 1)[0]
    helpers = 'function trendSegments(' + APP_JS.split('function trendSegments(', 1)[1].split('function readingBasis(', 1)[0]
    run_js(r'''
const S={minimum_cell_n:0},document={createElementNS:(ns,tag)=>el(tag)},host=el('section'),n=x=>String(x),num=x=>x===null?'—':Number(x).toFixed(2);
function notice(host,text){host.append(el('p','notice',text));}
HELPERS
CHART
periodLineChart(host,[{period:'T0',kind:'binary',value:0,proportion:0,numerator:0,denominator:2,valid_n:2,missing_n:1},
 {period:'T1',kind:'binary',value:0.25,proportion:0.25,numerator:1,denominator:4,valid_n:4,missing_n:0}],
 'Bullying prevalence','TBV_prevalence1','auto','2025-09-01 to 2026-08-31');
const nodes=walk(host),tips=nodes.filter(n=>n.tag==='title').map(n=>n.textContent);
assert(nodes.some(n=>String(n.textContent).includes('Prevalence proportion axis (0–1): 0.00–1.00')));
assert(tips.some(t=>t.includes('Proportion=0.25; numerator=1; denominator=4')));
assert(tips.every(t=>!t.includes('Mean=')&&!t.includes('SD=')));
'''.replace('HELPERS', helpers).replace('CHART', chart))


def test_actual_period_engine_drives_combined_ui_and_exact_hk_days():
    import pandas as pd
    from study2.static_period import JS as PERIOD_JS, build_cube

    specification = [
        ('T0', '2025-09-02T16:00:00Z', 'P3', 'qualtrics', '0', True, 0.),
        ('T0', '2025-09-04T00:00:00Z', 'P4', 'paperform', '0', True, 4.),
        ('T1', '2026-03-30T15:59:59Z', 'P3', 'qualtrics', '0', True, 8.),
        ('T1', '2026-03-30T16:00:00Z', 'P3', 'qualtrics', '0', True, 12.),
        ('T0', '2025-09-02T15:59:59Z', 'P3', 'qualtrics', '0', True, 10.),
        ('T0', '2025-09-04T00:00:00Z', 'P3', 'qualtrics', '1', True, 12.),
        ('T1', '2026-03-30T00:00:00Z', 'P3', 'qualtrics', '0', False, 1.),
    ]
    rows = pd.DataFrame([dict(submission_id=f'synthetic-only-{i}', version_id=f'synthetic-version-{i}',
        role='student', wave=wave, observed_at=date, date_basis='system_creation', time_confidence='observed',
        report_mode='abcd', grouping_anchor='wave_response', _grade=grade, anchor_gender=gender,
        anchor_school_stage='primary', anchor_mainstream=mainstream, anchor_source_type=source,
        PHQ_total=value, TBV_prevalence1=float(value > 0))
        for i, (wave, date, grade, source, gender, mainstream, value) in enumerate(specification)])
    value = build_cube(rows, 'student', mode='abcd', grade_anchor='student_wave',
                       grouping_anchor='wave_response', source_filter_anchor='wave_response', release_id='RUN_SYNTHETIC')
    common = COMMON.replace('const Period={FORMAT,', 'const FakePeriod={FORMAT,')
    script = PERIOD_JS + '\n' + JS_SOURCE + '\n' + common + r'''
const c=CUBE,{snapshot}=setup([c]),st={...initialState(),grades:['P3','P4'],period_day_initialized:true,
 period_preset:'custom',period_day_from:'2025-09-03',period_day_to:'2026-03-30'};
Study2PeriodUI.mount(environment(snapshot,st,{mode:'off'},readyLoader(c,snapshot)));
const period=calls.tables.find(t=>t.name==='period-comparison-abcd-student');
assert.equal(period.rows[0].sample_n,2);assert.equal(period.rows[0].valid_n,2);assert.equal(period.rows[0].mean,2);
assert.equal(period.rows[1].sample_n,1);assert.equal(period.rows[1].mean,8);assert.equal(period.rows[1].sd,null);
assert.equal(period.scope.metadata.grade_anchor,'student_wave');
assert.equal(period.scope.metadata.period_from,'2025-09-03');assert.equal(period.scope.metadata.period_to,'2026-03-30');
st.sources=[];Study2PeriodUI.mount(environment(snapshot,st,{mode:'off'},readyLoader(c,snapshot)));
assert(calls.tables.filter(t=>t.name==='period-comparison-abcd-student').at(-1).rows.every(r=>r.sample_n===0&&r.valid_n===0));
assert.equal(st.period_day_from,'2025-09-03');
'''.replace('CUBE', json.dumps(value))
    result = subprocess.run([shutil.which('node'), '-e', script], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_legacy_unsupported_intersection_remains_explicit_with_no_result():
    from study2.static_assets import APP_JS
    legacy = 'function trends(view,st) {' + APP_JS.split('function trends(view,st) {', 1)[1].split('function releaseMetadata(', 1)[0]
    run_js(r'''
const host=el('section');function section(){return host;}function notice(h,t){calls.notices.push(t);}
LEGACY
trends({source_capabilities:{monthly_trends:true}},{group:'male_primary'});
trends({source_capabilities:{monthly_trends:false}},{group:'all'});
assert.equal(calls.tables.length,0);assert.equal(calls.charts.length,0);
assert(calls.notices.filter(t=>t.includes('only all groups and all sources')).length===2);
assert(calls.notices.some(t=>t.includes('Legacy period snapshot')));
'''.replace('LEGACY', legacy))
