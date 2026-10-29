"""Synthetic-only semester UI checks; no research data or services."""
import json
import shutil
import subprocess

import pytest

from study2.static_period_ui import JS_SOURCE


COMMON = r'''
const assert=require('node:assert/strict'),{webcrypto,createHash}=require('node:crypto');
const copy=x=>JSON.parse(JSON.stringify(x)),hash=x=>createHash('sha256').update(x).digest('hex');
const REV='a'.repeat(64),BASE='https://synthetic.test/research/',FORMAT='study2_period_semester_v1';
const roleMap={abcd:['student','parent'],ef:['student','parent'],acbd:['student','parent'],efmatched:['student','parent'],independent_all:['parent'],independent_child:['parent'],independent_adult:['parent']};
const calls={fetch:[],queries:[],notices:[],tables:[],selects:[]};
class Element {
 constructor(tag,cls='',text=''){this.tag=tag;this.className=cls;this.textContent=text;this.children=[];this.dataset={};this.attributes={};}
 append(...children){this.children.push(...children);}setAttribute(k,v){this.attributes[k]=String(v);}
}
const el=(...args)=>new Element(...args),walk=node=>[node,...(node.children||[]).flatMap(walk)];
const document={createElementNS:(_,tag)=>el(tag)};
const metricList=[{variable_id:'PHQ_total',kind:'continuous',unit:'score',available:true},{variable_id:'FQOL_total',kind:'continuous',unit:'score',available:true},{variable_id:'phq_band',kind:'category',unit:'proportion',available:true},...['TBV','TBP','CBV','CBP'].flatMap(domain=>[{variable_id:domain+'_mean',kind:'continuous',unit:'score',available:true},...['1','2'].map(threshold=>({variable_id:domain+'_prevalence'+threshold,kind:'binary',unit:'proportion',available:true}))])];
function cube(role='student',mode='abcd',eligibility='off') {return {format:FORMAT,release_id:'RUN_SYNTHETIC',mode,role,eligibility,eligibility_revision:eligibility==='on'?REV:null,active_on_revision:REV,
 grade_anchor:'student_wave',grouping_anchor:'wave_response',source_filter_anchor:'wave_response',metrics:metricList.map(m=>({...m,subject:role==='student'?'student_child':m.variable_id.startsWith('PHQ_')?'respondent_adult':'parent_reported_child'})),
 joint_metrics:[{metric_id:'bullying_roles_traditional',threshold:'any',available:true},{metric_id:'bullying_roles_traditional',threshold:'recurrent',available:true},{metric_id:'bullying_roles_cyber',threshold:'any',available:true},{metric_id:'bullying_roles_cyber',threshold:'recurrent',available:true}],
 cell_fields:['date'],cells:[['2023-09-01'],['2024-02-01'],['2025-09-01']]};}
function setup(){const assets={},refs=[];
 for(const eligibility of ['off','on'])for(const [mode,roles] of Object.entries(roleMap))for(const role of roles){const c=cube(role,mode,eligibility),text=JSON.stringify(c),asset=`period-semester-${eligibility}-${mode}-${role}.json`;assets[asset]=text;refs.push({asset,sha256:hash(text),status:'available',code:null,release_id:'RUN_SYNTHETIC',mode,role,eligibility,eligibility_revision:eligibility==='on'?REV:null,extent:{start:'2023-09-01',end:'2026-08-31'}});}
 const snapshot={release_id:'RUN_SYNTHETIC',minimum_cell_n:0,release_context:{run_id:'RUN_SYNTHETIC'},modes:Object.fromEntries(Object.keys(roleMap).map(m=>[m,m])),dictionary:[{variable_id:'PHQ_total',label:'PHQ total'},{variable_id:'TBV_prevalence2',label:'Traditional victim recurrent'}],period_semester_selection:{format:FORMAT,status:'available',profile:'protected_researcher',minimum_cell_n:0,release_id:'RUN_SYNTHETIC',active_on_revision:REV,refs}};
 return {assets,snapshot};}
const state=()=>({mode:'abcd',role:'student',grades:['P3','Unknown'],sources:['qualtrics'],mainstream:true,group:'all',batch:false,reading:'trends'});
const scope=(mode='off')=>({mode,revision:mode==='on'?REV:null,active_on_revision:REV});
const response=(text,url)=>{const b=Buffer.from(text);return {ok:true,status:200,url,arrayBuffer:async()=>b.buffer.slice(b.byteOffset,b.byteOffset+b.byteLength)};};
const fetcher=assets=>async(url,options)=>{calls.fetch.push({url,options});return response(assets[new URL(url).pathname.split('/').at(-1)],url);};
function sampleRows(c,s){const rows=[];
 for(const year of s.academic_years)for(const semester of s.semesters)for(const wave of s.waves){
  const base={academic_year_start:year,semester,wave,period_start:year+'-09-01',period_end:(year+1)+'-01-31',covered_start:year+'-09-01',covered_end:(year+1)+'-01-31',partial_period:false,metric_id:s.metric_id,subject:c.role==='student'?'student_child':s.metric_id.startsWith('PHQ_')?'respondent_adult':'parent_reported_child',threshold:null,category_code:null,sample_n:4,valid_n:3,missing_n:1,outside_range_n:0,numerator:null,denominator:null,proportion:null,mean:null,sd:null,ci_low:null,ci_high:null,ci_method:null,status:'available'};
  if(s.metric_id.startsWith('bullying_roles_')){for(const threshold of s.threshold==='both'?['any','recurrent']:[s.threshold])for(const [i,category] of ['perpetrator_only','victim_only','both','neither'].entries())rows.push({...base,kind:'joint_roles',unit:'proportion',threshold,category_code:category,numerator:[1,1,0,1][i],denominator:3,proportion:[1/3,1/3,0,1/3][i]});}
  else if(/_prevalence[12]$/.test(s.metric_id))rows.push({...base,kind:'binary',unit:'proportion',threshold:s.threshold,numerator:1,denominator:3,proportion:1/3,...(s.ci==='wilson_95_unclustered'?{ci_low:0.05,ci_high:0.8,ci_method:'wilson_95_unclustered'}:{})});
  else rows.push({...base,kind:'continuous',unit:'score',mean:s.metric_id.endsWith('_mean')?(c.role==='student'?0.75:1.25):(c.role==='student'?2:5),sd:1});
 }return rows;}
const Period={validate(c){assert.equal(c.format,FORMAT);return true;},query(c,s){calls.queries.push({role:c.role,selection:copy(s)});return {format:'study2_period_semester_result_v1',release_id:c.release_id,eligibility:c.eligibility,eligibility_revision:c.eligibility_revision,active_on_revision:c.active_on_revision,mode:c.mode,role:c.role,selection:copy(s),anchors:{grade:c.grade_anchor},rows:sampleRows(c,s),date_quality:[{wave:'T0',date_quality:'system_creation',input_n:4,included_n:3}],date_exclusions:[{wave:'T0',stage:'period',remaining_n:3,excluded_n:1}]};}};
function environment(snapshot,st,loader,overrides={}){const host=el('section');return {host,snapshot,state:st,scope:scope(),loader,period:Period,isCurrent:()=>true,rerender:()=>{},el,
 select:(host,label,value,options,changed)=>{const node=el('select','',label);Object.assign(node,{value,options,changed});host.append(node);calls.selects.push(node);return node;},
 notice:(host,text,warning)=>{calls.notices.push(text);host.append(el('p',warning?'warning':'notice',text));},cards:()=>{},
 table:(host,rows,columns,name,wide,raw,scope)=>{calls.tables.push({name,rows:copy(rows),columns,scope});},lineChart:()=>{throw Error('Old two-point chart must not be used');},num:x=>x==null?'—':Number(x).toFixed(2),n:x=>x==null?'—':String(x),...overrides};}
function readyLoader(snapshot,mode='off'){return {load(_s,st){const ref=snapshot.period_semester_selection.refs.find(r=>r.mode===st.mode&&r.role===st.role&&r.eligibility===mode);return {status:'ready',cube:cube(st.role,st.mode,mode),ref};}};}
'''


def run_js(body):
    node = shutil.which('node')
    if not node:
        pytest.skip('Node is required')
    script = JS_SOURCE + '\n' + COMMON + '\n(async()=>{\n' + body + '\n})().catch(e=>{console.error(e);process.exitCode=1;});'
    result = subprocess.run([node, '-e', script], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout) if result.stdout.strip() else None


def test_lazy_catalog_hash_scope_and_parent_only():
    run_js(r'''
const {assets,snapshot}=setup(),loader=Study2PeriodUI.createSemesterLoader({getPeriod:()=>Period,fetcher:fetcher(assets),cryptoAPI:webcrypto,base:BASE});
assert.equal(calls.fetch.length,0);
for(const role of ['student','parent']){const entry=loader.load(snapshot,{...state(),role},scope('on'));await entry.promise;assert.equal(entry.status,'ready');}
assert.equal(calls.fetch.length,2);assert(calls.fetch.every(c=>c.options.credentials==='same-origin'&&c.options.cache==='no-store'));
assert.throws(()=>loader.load(snapshot,{...state(),role:'student'},scope('off')&&{...scope('off'),active_on_revision:'b'.repeat(64)}),/active control revision/);
assert.throws(()=>loader.load(snapshot,{...state(),mode:'independent_all',role:'student'},scope()),/unavailable/);
const parent=loader.load(snapshot,{...state(),mode:'independent_all',role:'parent'},scope());await parent.promise;assert.equal(parent.status,'ready');
''')


@pytest.mark.parametrize('fault', ['hash', 'cube_revision', 'redirect', 'path', 'catalog_missing', 'suppressed'])
def test_fail_closed_on_invalid_lazy_assets(fault):
    run_js(r'''
const kind=FAULT,{assets,snapshot}=setup(),ref=snapshot.period_semester_selection.refs.find(r=>r.mode==='abcd'&&r.role==='student'&&r.eligibility==='off');let fetch=fetcher(assets);
if(kind==='hash')ref.sha256='0'.repeat(64);
if(kind==='cube_revision'){const c=cube();c.active_on_revision='b'.repeat(64);assets[ref.asset]=JSON.stringify(c);ref.sha256=hash(assets[ref.asset]);}
if(kind==='redirect')fetch=async(url)=>response(assets[ref.asset],new URL('login.html',BASE).href);
if(kind==='path')ref.asset='../period-semester-off-abcd-student.json';
if(kind==='catalog_missing')snapshot.period_semester_selection.refs.pop();
if(kind==='suppressed')snapshot.minimum_cell_n=5;
const loader=Study2PeriodUI.createSemesterLoader({getPeriod:()=>Period,fetcher:fetch,cryptoAPI:webcrypto,base:BASE});
if(['path','catalog_missing','suppressed'].includes(kind))assert.throws(()=>loader.load(snapshot,state(),scope()));
else{const entry=loader.load(snapshot,state(),scope());await entry.promise;assert.equal(entry.status,'error');assert.equal(entry.cube,null);}
assert.equal(calls.queries.length,0);
'''.replace('FAULT', json.dumps(fault)))


def test_shared_disjoint_selection_independent_waves_and_csv_metadata():
    result = run_js(r'''
const {snapshot}=setup(),st=state(),env=environment(snapshot,st,readyLoader(snapshot));Study2PeriodUI.mountSemester(env);
assert.deepEqual(st.semester_trends.academic_years,[2023,2025]);assert.deepEqual(st.semester_trends.waves,['T0','T1']);
assert.equal(st.semester_trends.threshold,'recurrent');assert.equal(st.semester_trends.ci,'none');
assert.deepEqual(calls.queries.map(q=>q.role),['student','parent']);
for(const q of calls.queries){assert.deepEqual(q.selection.academic_years,[2023,2025]);assert.deepEqual(q.selection.semesters,['S1','S2']);assert.deepEqual(q.selection.waves,['T0','T1']);assert.deepEqual(q.selection.grades,['P3','Unknown']);assert.deepEqual(q.selection.sources,['qualtrics']);}
assert.equal(calls.tables.filter(t=>t.name.startsWith('semester-abcd-')).length,2);
const student=calls.tables.find(t=>t.name==='semester-abcd-student'),parent=calls.tables.find(t=>t.name==='semester-abcd-parent');
assert.equal(student.rows.length,8);assert(student.rows.every(row=>row.academic_year_start!==2024));assert(student.rows.some(row=>row.wave==='T0')&&student.rows.some(row=>row.wave==='T1'));
assert.equal(student.scope.metadata.eligibility_revision,null);assert.equal(student.scope.metadata.active_on_revision,REV);
assert.equal(parent.scope.metadata.role,'parent');assert.equal(student.scope.metadata.interval,'inclusive_day');assert.equal(student.scope.metadata.timezone,'Asia/Hong_Kong');
const panels=walk(env.host).filter(n=>n.className.split(' ').includes('semester-panel'));assert.equal(panels.length,2);assert(panels[0].children[0].textContent.includes('Student'));assert(panels[1].children[0].textContent.includes('Parent'));
assert(walk(env.host).some(n=>n.tag==='svg'&&n.attributes.role==='img'));assert(walk(env.host).some(n=>n.tag==='fieldset'));
console.log(JSON.stringify({student:student.scope.metadata,columns:student.columns}));
''')
    assert result['student']['academic_years'] == '2023|2025'
    assert result['student']['filter_grade_codes'] == 'P3|Unknown'
    assert 'outside_range_n' in result['columns']
    assert 'ci_method' in result['columns']


def test_empty_selections_remain_empty_and_controls_persist():
    run_js(r'''
const {snapshot}=setup(),st=state(),loader=readyLoader(snapshot);let env=environment(snapshot,st,loader);Study2PeriodUI.mountSemester(env);const initial=calls.queries.length;
st.semester_trends.academic_years=[];env=environment(snapshot,st,loader);Study2PeriodUI.mountSemester(env);assert.equal(calls.queries.length,initial);assert(calls.notices.some(x=>x.includes('No academic years')));assert.deepEqual(st.semester_trends.academic_years,[]);
st.semester_trends.academic_years=[2023];st.semester_trends.waves=[];env=environment(snapshot,st,loader);Study2PeriodUI.mountSemester(env);assert.equal(calls.queries.length,initial);
const button=walk(env.host).find(x=>x.dataset.control==='semester:waves:both');button.onclick();assert.deepEqual(st.semester_trends.waves,['T0','T1']);
st.grades=[];st.sources=[];Study2PeriodUI.mountSemester(environment(snapshot,st,loader));assert.deepEqual(calls.queries.at(-1).selection.grades,[]);assert.deepEqual(calls.queries.at(-1).selection.sources,[]);
assert.deepEqual(Study2PeriodUI.semesterSelection(st,{...st.semester_trends,semesters:['S1','S1']}).semesters,['S1']);
assert.throws(()=>Study2PeriodUI.semesterSelection({...st,sources:['bad']},st.semester_trends),/source/);
''')


def test_selection_normalizes_valid_duplicates_but_rejects_invalid_codes_and_source_mix():
    run_js(r'''
const st={...state(),grades:['P4','P3','P4'],sources:['paperform','qualtrics','paperform']};
const options={academic_years:[2025,2023,2025],semesters:['S2','S1','S2'],waves:['T1','T0','T1'],
 from:'2023-09-01',to:'2026-08-31',metric_id:'PHQ_total',threshold:'recurrent',ci:'none'};
const selected=Study2PeriodUI.semesterSelection(st,options);
assert.deepEqual(selected.academic_years,[2023,2025]);assert.deepEqual(selected.semesters,['S1','S2']);
assert.deepEqual(selected.waves,['T0','T1']);assert.deepEqual(selected.grades,['P3','P4']);
assert.deepEqual(selected.sources,['paperform','qualtrics']);
assert.deepEqual(Study2PeriodUI.semesterSelection({...st,sources:['all','all']},options).sources,['all']);
assert.throws(()=>Study2PeriodUI.semesterSelection({...st,sources:['all','qualtrics']},options),/All sources/);
assert.throws(()=>Study2PeriodUI.semesterSelection(st,{...options,semesters:['S1','S3']}),/semester/);
assert.throws(()=>Study2PeriodUI.semesterSelection(st,{...options,academic_years:[2025,'2023']}),/academic year/);
''')


def test_mean_overlay_axes_series_visibility_and_independent_downloads():
    run_js(r'''
const {snapshot}=setup(),st=state(),loader=readyLoader(snapshot);Study2PeriodUI.mountSemester(environment(snapshot,st,loader));
st.semester_trends.overlay='TBV_mean';let env=environment(snapshot,st,loader);Study2PeriodUI.mountSemester(env);
const queries=calls.queries.slice(-4);assert.deepEqual(queries.map(q=>[q.role,q.selection.metric_id]),[['student','PHQ_total'],['student','TBV_mean'],['parent','PHQ_total'],['parent','TBV_mean']]);
for(let i=0;i<4;i+=2){const a=queries[i].selection,b=queries[i+1].selection;assert.deepEqual({...a,metric_id:b.metric_id,ci:'none'},b);}
const panels=walk(env.host).filter(n=>n.className.split(' ').includes('semester-panel')),student=panels[0],parent=panels[1];
assert(walk(student).some(n=>n.textContent.includes('Left axis: PHQ total')&&n.textContent.includes('0.00–12.00')));
assert(walk(student).some(n=>n.textContent.includes('Right axis: Traditional bullying victimization mean score')&&n.textContent.includes('0.00–4.00')));
assert(walk(student).some(n=>n.attributes?.['data-series']==='overlay'));
assert(walk(student).some(n=>n.tag==='title'&&n.textContent.includes('SD 1.00')&&n.textContent.includes('valid N 3')&&n.textContent.includes('missing N 1')));
const primaryPoint=walk(student).find(n=>n.tag==='circle'&&n.attributes?.['data-wave']==='T0'),overlayPoint=walk(student).find(n=>n.tag==='rect'&&n.attributes?.['data-series']==='overlay'&&n.attributes?.['data-wave']==='T0');
assert(Math.abs(Number(primaryPoint.attributes.cy)-(250-190*2/12))<1e-8);assert(Math.abs(Number(overlayPoint.attributes.y)+4-(250-190*.75/4))<1e-8);
const primary=calls.tables.filter(t=>t.name==='semester-abcd-student').at(-1),over=calls.tables.filter(t=>t.name==='semester-overlay-abcd-student-TBV_mean').at(-1);
assert.equal(primary.rows[0].mean,2);assert.equal(over.rows[0].mean,.75);assert.equal(over.rows[0].unit,'score');assert.equal(over.scope.variable,'TBV_mean');assert.equal(over.scope.metadata.role,'student');assert.equal(over.scope.metadata.chart_series,'overlay');assert.equal(over.scope.metadata.eligibility_revision,null);assert(over.scope.metadata.score_definition.includes('average of 7 items'));
const toggle=walk(student).find(n=>n.dataset.control==='semester:visible:student:T1');toggle.checked=false;toggle.onchange();
env=environment(snapshot,st,loader);Study2PeriodUI.mountSemester(env);
const panels2=walk(env.host).filter(n=>n.className.split(' ').includes('semester-panel'));
assert(!walk(panels2[0]).some(n=>n.attributes?.['data-wave']==='T1'));assert(walk(panels2[1]).some(n=>n.attributes?.['data-wave']==='T1'));
assert.deepEqual(st.semester_trends.waves,['T0','T1']);assert.equal(calls.tables.filter(t=>t.name==='semester-abcd-student').at(-1).rows.length,primary.rows.length);
st.semester_trends.axis='auto';env=environment(snapshot,st,loader);Study2PeriodUI.mountSemester(env);
assert(walk(env.host).some(n=>n.textContent.includes('Left axis: PHQ total')&&n.textContent.includes('Auto zoom')));
assert(walk(env.host).some(n=>n.textContent.includes('Right axis: Traditional bullying victimization mean score')&&n.textContent.includes('Auto zoom')));
''')


def test_tooltips_identify_role_wave_period_metric_and_binary_counts():
    run_js(r'''
const {snapshot}=setup(),st=state(),loader=readyLoader(snapshot);Study2PeriodUI.mountSemester(environment(snapshot,st,loader));st.semester_trends.overlay='TBV_mean';
let env=environment(snapshot,st,loader);Study2PeriodUI.mountSemester(env);
let panels=walk(env.host).filter(n=>n.className.split(' ').includes('semester-panel'));
const studentTip=walk(panels[0]).find(n=>n.attributes?.role==='tooltip'),parentTip=walk(panels[1]).find(n=>n.attributes?.role==='tooltip');
const studentPrimary=walk(panels[0]).find(n=>n.tag==='circle'&&n.attributes?.['data-wave']==='T0');
studentPrimary.onmouseenter();assert.equal(studentTip.hidden,false);assert(studentTip.textContent.includes('Student self-report')&&studentTip.textContent.includes('2023–2024 S1')&&studentTip.textContent.includes('2023-09-01 to 2024-01-31')&&studentTip.textContent.includes('PHQ total')&&studentTip.textContent.includes('mean 2.00')&&studentTip.textContent.includes('SD 1.00')&&studentTip.textContent.includes('valid N 3'));studentPrimary.onmouseleave();assert(studentTip.hidden);
const parentOverlay=walk(panels[1]).find(n=>n.tag==='rect'&&n.attributes?.['data-series']==='overlay'&&n.attributes?.['data-wave']==='T1');
parentOverlay.onfocus();assert(parentTip.textContent.includes('Parent report about the child')&&parentTip.textContent.includes('T1')&&parentTip.textContent.includes('Traditional bullying victimization mean score (overlay)')&&parentTip.textContent.includes('mean 1.25'));assert(!parentTip.textContent.includes('PHQ total'));parentOverlay.onkeydown({key:'Escape'});assert(parentTip.hidden);
st.semester_trends.metric_id='TBV_prevalence2';st.semester_trends.overlay='none';
env=environment(snapshot,st,loader);Study2PeriodUI.mountSemester(env);panels=walk(env.host).filter(n=>n.className.split(' ').includes('semester-panel'));
const binary=walk(panels[0]).find(n=>n.tag==='circle'&&n.attributes?.['data-series']==='primary'),binaryTip=walk(panels[0]).find(n=>n.attributes?.role==='tooltip');
binary.onfocus();assert(binaryTip.textContent.includes('1 case / 3 valid responses (33.33%)'));assert(!binaryTip.textContent.includes('mean ')&&!binaryTip.textContent.includes('SD '));
const one={...Period,query(c,s){const out=Period.query(c,s);out.rows[0]={...out.rows[0],valid_n:1,missing_n:3,sd:null};return out;}};
st.semester_trends.metric_id='PHQ_total';env=environment(snapshot,st,loader,{period:one});Study2PeriodUI.mountSemester(env);
const point=walk(env.host).find(n=>n.tag==='circle'&&n.attributes?.['data-series']==='primary');point.onfocus();assert(walk(env.host).find(n=>n.attributes?.role==='tooltip').textContent.includes('SD unavailable'));
''')


def test_chart_controls_are_shared_but_keep_bullying_out_of_scale_picker():
    run_js(r'''
const {snapshot}=setup(),st=state(),loader=readyLoader(snapshot);let env=environment(snapshot,st,loader);Study2PeriodUI.mountSemester(env);
const control=(role,key)=>walk(env.host).find(n=>n.dataset.control===`semester:control:${role}:${key}`);
let studentMetric=control('student','metric'),parentMetric=control('parent','metric');
for(const picker of [studentMetric,parentMetric]){assert(Object.hasOwn(picker.options,'PHQ_total'));assert(!Object.keys(picker.options).some(id=>/^(TBV|TBP|CBV|CBP)_|^bullying_roles_/.test(id)));}
for(const role of ['student','parent']){const panel=walk(env.host).find(n=>n.className.split(' ').includes('semester-panel')&&n.children[0].textContent.toLowerCase().includes(role));const controls=walk(panel).filter(n=>n.dataset.control?.startsWith(`semester:control:${role}:`)).map(n=>n.dataset.control.split(':').at(-1));assert.equal(controls[0],'metric');assert.equal(controls[1],'overlay');assert(!Object.hasOwn(control(role,'bullying_display').options,'mean'));}
assert(!walk(env.host).some(n=>n.textContent.includes('Hover over or focus')||n.textContent.includes('Visibility controls affect')));
control('student','bullying_display').changed('prevalence');env=environment(snapshot,st,loader);Study2PeriodUI.mountSemester(env);
assert.equal(control('parent','bullying_display').value,'prevalence');assert.equal(st.semester_trends.metric_id,'TBV_prevalence2');
for(const role of ['student','parent']){const panel=walk(env.host).find(n=>n.className.split(' ').includes('semester-panel')&&n.children[0].textContent.toLowerCase().includes(role));const controls=walk(panel).filter(n=>n.dataset.control?.startsWith(`semester:control:${role}:`)).map(n=>n.dataset.control.split(':').at(-1));assert.equal(controls.indexOf('ci'),controls.indexOf('threshold')+1);}
control('parent','bullying_domain').changed('CBP');env=environment(snapshot,st,loader);Study2PeriodUI.mountSemester(env);assert.equal(control('student','bullying_domain').value,'CBP');assert.equal(st.semester_trends.metric_id,'CBP_prevalence2');
control('student','threshold').changed('any');env=environment(snapshot,st,loader);Study2PeriodUI.mountSemester(env);assert.equal(control('parent','threshold').value,'any');assert.equal(calls.queries.at(-1).selection.threshold,'any');
control('student','bullying_display').changed('roles');env=environment(snapshot,st,loader);Study2PeriodUI.mountSemester(env);assert.equal(st.semester_trends.metric_id,'bullying_roles_traditional');
control('parent','bullying_roles_domain').changed('cyber');env=environment(snapshot,st,loader);Study2PeriodUI.mountSemester(env);assert.equal(control('student','bullying_roles_domain').value,'cyber');assert.equal(st.semester_trends.metric_id,'bullying_roles_cyber');
control('student','metric').changed('PHQ_total');env=environment(snapshot,st,loader);Study2PeriodUI.mountSemester(env);assert.equal(st.semester_trends.metric_id,'PHQ_total');
control('student','overlay').changed('TBV_mean');env=environment(snapshot,st,loader);Study2PeriodUI.mountSemester(env);
const before=calls.tables.filter(t=>t.name==='semester-abcd-student').at(-1),beforeOverlay=calls.tables.filter(t=>t.name==='semester-overlay-abcd-student-TBV_mean').at(-1);control('parent','threshold').changed('recurrent');env=environment(snapshot,st,loader);Study2PeriodUI.mountSemester(env);
const after=calls.tables.filter(t=>t.name==='semester-abcd-student').at(-1),afterOverlay=calls.tables.filter(t=>t.name==='semester-overlay-abcd-student-TBV_mean').at(-1);assert.equal(after.rows[0].mean,before.rows[0].mean);assert.equal(after.scope.metadata.threshold_selection,'not_applicable');assert.equal(afterOverlay.rows[0].mean,beforeOverlay.rows[0].mean);assert.equal(afterOverlay.scope.metadata.threshold_selection,'not_applicable');
control('student','metric').changed('PHQ_total');env=environment(snapshot,st,loader);Study2PeriodUI.mountSemester(env);assert.equal(st.semester_trends.bullying_display,'none');assert.equal(st.semester_trends.metric_id,'PHQ_total');
''')


def test_dedicated_bullying_controls_reach_all_domains_and_role_distributions():
    run_js(r'''
const {snapshot}=setup(),st=state(),loader=readyLoader(snapshot);let env=environment(snapshot,st,loader);Study2PeriodUI.mountSemester(env);
const control=key=>walk(env.host).find(n=>n.dataset.control===`semester:control:student:${key}`),render=()=>{env=environment(snapshot,st,loader);Study2PeriodUI.mountSemester(env);};
control('bullying_display').changed('prevalence');render();
for(const domain of ['TBV','TBP','CBV','CBP']){control('bullying_domain').changed(domain);render();for(const threshold of ['any','recurrent','both']){control('threshold').changed(threshold);render();const q=calls.queries.at(-1).selection;assert.equal(q.metric_id,domain+'_prevalence2');assert.equal(q.threshold,threshold);}}
control('bullying_display').changed('roles');render();
for(const domain of ['traditional','cyber']){control('bullying_roles_domain').changed(domain);render();for(const threshold of ['any','recurrent','both']){control('threshold').changed(threshold);render();const q=calls.queries.at(-1).selection;assert.equal(q.metric_id,'bullying_roles_'+domain);assert.equal(q.threshold,threshold);}}
control('metric').changed('PHQ_total');render();for(const domain of ['TBV','TBP','CBV','CBP']){control('overlay').changed(domain+'_mean');render();assert.equal(calls.queries.at(-1).selection.metric_id,domain+'_mean');}
''')


def test_previous_bullying_selection_survives_control_migration():
    run_js(r'''
const {snapshot}=setup(),st=state();st.semester_trends={academic_years:[2023],semesters:['S1'],waves:['T0'],from:'2023-09-01',to:'2024-01-31',metric_id:'TBP_prevalence1',threshold:'any',ci:'none',chart:'line',axis:'auto',overlay:'CBV_mean'};
const env=environment(snapshot,st,readyLoader(snapshot));Study2PeriodUI.mountSemester(env);
assert.equal(st.semester_trends.metric_id,'TBP_prevalence1');assert.equal(st.semester_trends.bullying_display,'prevalence');assert.equal(st.semester_trends.bullying_domain,'TBP');assert.equal(st.semester_trends.threshold,'any');assert.equal(st.semester_trends.axis,'auto');assert.equal(st.semester_trends.overlay,'CBV_mean');
assert(calls.queries.some(q=>q.selection.metric_id==='TBP_prevalence1')&&calls.queries.some(q=>q.selection.metric_id==='CBV_mean'));
''')


@pytest.mark.parametrize('mean_metric', ['TBV_mean','TBP_mean','CBV_mean','CBP_mean'])
def test_previous_mean_migrates_to_matching_overlay_and_preserves_prior_scale(mean_metric):
    run_js(r'''
const {snapshot}=setup(),st=state(),mean=MEAN;st.semester_trends={academic_years:[2023],semesters:['S1'],waves:['T0'],from:'2023-09-01',to:'2024-01-31',metric_id:mean,scale_metric:'FQOL_total',bullying_display:'mean',threshold:'any',ci:'none',chart:'bars',axis:'auto',overlay:'CBV_mean',visible_lines:{student:['T0'],parent:[]},visible_overlay:{student:true,parent:false}};
const env=environment(snapshot,st,readyLoader(snapshot));Study2PeriodUI.mountSemester(env);
assert.equal(st.semester_trends.metric_id,'FQOL_total');assert.equal(st.semester_trends.bullying_display,'none');assert.equal(st.semester_trends.overlay,mean);
assert.equal(st.semester_trends.mean_migration.mean,mean);assert.equal(st.semester_trends.mean_migration.primary,'FQOL_total');
assert.equal(st.semester_trends.mean_migration.previous_overlay,mean==='CBV_mean'?null:'CBV_mean');
assert.equal(st.semester_trends.threshold,'any');assert.equal(st.semester_trends.axis,'auto');assert.equal(st.semester_trends.chart,'bars');assert.deepEqual(st.semester_trends.waves,['T0']);assert.deepEqual(st.semester_trends.visible_lines.parent,[]);assert.equal(st.semester_trends.visible_overlay.parent,false);
assert(calls.queries.some(q=>q.selection.metric_id==='FQOL_total')&&calls.queries.some(q=>q.selection.metric_id===mean));
assert(walk(env.host).some(n=>n.textContent.includes('is now the overlay')&&n.textContent.includes('FQOL_total')));
if(mean!=='CBV_mean')assert(walk(env.host).some(n=>n.textContent.includes('earlier Cyberbullying victimization overlay can be selected again')));
const overlayControl=walk(env.host).find(n=>n.dataset.control==='semester:control:student:overlay');overlayControl.changed('CBV_mean');assert.equal(st.semester_trends.mean_migration,undefined);
'''.replace('MEAN', json.dumps(mean_metric)))


def test_legacy_mean_without_scale_defaults_to_phq_and_without_scale_fails_closed():
    run_js(r'''
const {snapshot}=setup(),st=state();st.semester_trends={academic_years:[2023],semesters:['S1'],waves:['T0'],from:'2023-09-01',to:'2024-01-31',metric_id:'TBV_mean',threshold:'recurrent',ci:'none',chart:'line',axis:'full',overlay:'none'};
Study2PeriodUI.mountSemester(environment(snapshot,st,readyLoader(snapshot)));assert.equal(st.semester_trends.metric_id,'PHQ_total');assert.equal(st.semester_trends.overlay,'TBV_mean');assert.equal(st.semester_trends.bullying_display,'none');
const noScale={load(_snapshot,current){const ref=snapshot.period_semester_selection.refs.find(r=>r.mode===current.mode&&r.role===current.role&&r.eligibility==='off'),c=cube(current.role);c.metrics=c.metrics.filter(m=>m.variable_id==='TBV_mean');c.joint_metrics=[];return {status:'ready',ref,cube:c};}};
const missing=state();missing.semester_trends={academic_years:[2023],semesters:['S1'],waves:['T0'],from:'2023-09-01',to:'2024-01-31',metric_id:'TBV_mean',threshold:'recurrent',ci:'none',chart:'line',axis:'full',overlay:'none'};
const before=calls.queries.length;Study2PeriodUI.mountSemester(environment(snapshot,missing,noScale));assert.equal(calls.queries.length,before);assert.equal(missing.semester_trends.metric_id,'TBV_mean');assert(calls.notices.some(n=>n.includes('cannot be migrated safely')));
''')


def test_overlay_reuses_the_two_validated_role_assets_without_extra_fetches():
    run_js(r'''
const {assets,snapshot}=setup(),st=state(),loader=Study2PeriodUI.createSemesterLoader({getPeriod:()=>Period,fetcher:fetcher(assets),cryptoAPI:webcrypto,base:BASE});
Study2PeriodUI.mountSemester(environment(snapshot,st,loader));
await Promise.all(['student','parent'].map(role=>loader.load(snapshot,{...st,role},scope()).promise));
Study2PeriodUI.mountSemester(environment(snapshot,st,loader));assert.equal(calls.fetch.length,2);
st.semester_trends.overlay='TBV_mean';Study2PeriodUI.mountSemester(environment(snapshot,st,loader));
assert.equal(calls.fetch.length,2);assert(calls.queries.some(q=>q.role==='student'&&q.selection.metric_id==='TBV_mean'));assert(calls.queries.some(q=>q.role==='parent'&&q.selection.metric_id==='TBV_mean'));
assert(calls.fetch.every(call=>new URL(call.url).pathname.includes('period-semester-off-abcd-')));
''')


@pytest.mark.parametrize('metric,item_count', [('TBV_mean',7),('TBP_mean',7),('CBV_mean',6),('CBP_mean',6)])
def test_each_bullying_overlay_keeps_its_own_metric_and_definition(metric, item_count):
    result = run_js(r'''
const {snapshot}=setup(),st=state(),loader=readyLoader(snapshot);Study2PeriodUI.mountSemester(environment(snapshot,st,loader));
st.semester_trends.overlay=METRIC;Study2PeriodUI.mountSemester(environment(snapshot,st,loader));
const t=calls.tables.find(t=>t.name==='semester-overlay-abcd-student-'+METRIC);assert(t);assert(t.rows.every(row=>row.metric_id===METRIC));
console.log(JSON.stringify({definition:t.scope.metadata.score_definition,unit:t.rows[0].unit}));
'''.replace('METRIC', json.dumps(metric)))
    assert f'average of {item_count} items' in result['definition']
    assert result['unit'] == 'score'


def test_overlay_mismatch_and_missing_are_explicit_and_do_not_replace_primary():
    run_js(r'''
const {snapshot}=setup(),st=state(),loader=readyLoader(snapshot);Study2PeriodUI.mountSemester(environment(snapshot,st,loader));st.semester_trends.overlay='TBV_mean';
const mismatch={...Period,query(c,s){const out=Period.query(c,s);if(s.metric_id==='TBV_mean')out.active_on_revision='b'.repeat(64);return out;}};
let env=environment(snapshot,st,loader,{period:mismatch});Study2PeriodUI.mountSemester(env);
assert(calls.notices.some(x=>x.includes('binding mismatch')&&x.includes('no overlay is substituted')));
assert(calls.tables.some(t=>t.name==='semester-abcd-student'));assert(!calls.tables.some(t=>t.name==='semester-overlay-abcd-student-TBV_mean'));
const wrongSubject={...Period,query(c,s){const out=Period.query(c,s);if(s.metric_id==='TBV_mean'&&c.role==='parent')out.rows[0].subject='respondent_adult';return out;}};
Study2PeriodUI.mountSemester(environment(snapshot,st,loader,{period:wrongSubject}));
assert(calls.notices.some(x=>x.includes('metric, unit or respondent is incompatible')));
const empty={...Period,query(c,s){const out=Period.query(c,s);if(s.metric_id==='TBV_mean')out.rows=out.rows.map(r=>({...r,status:'no_valid_scores',valid_n:0,missing_n:4,mean:null,sd:null}));return out;}};
env=environment(snapshot,st,loader,{period:empty});Study2PeriodUI.mountSemester(env);
assert(calls.notices.some(x=>x.includes('overlay has no valid values')));assert(!walk(env.host).some(n=>n.attributes?.['data-series']==='overlay'));
assert(calls.tables.filter(t=>t.name==='semester-overlay-abcd-student-TBV_mean').at(-1).rows.every(r=>r.mean===null));
''')


def test_binary_percentage_and_mean_overlay_use_separately_labelled_axes():
    run_js(r'''
const {snapshot}=setup(),st=state(),loader=readyLoader(snapshot);Study2PeriodUI.mountSemester(environment(snapshot,st,loader));
st.semester_trends.metric_id='TBV_prevalence2';st.semester_trends.overlay='TBP_mean';
const env=environment(snapshot,st,loader);Study2PeriodUI.mountSemester(env);
assert(walk(env.host).some(n=>n.textContent.includes('Left axis: Traditional bullying victimization proportion')&&n.textContent.includes('0.00–100.00%')));
assert(walk(env.host).some(n=>n.textContent.includes('Right axis: Traditional bullying perpetration mean score')&&n.textContent.includes('0.00–4.00')));
const primary=calls.tables.filter(t=>t.name==='semester-abcd-student').at(-1),overlay=calls.tables.filter(t=>t.name==='semester-overlay-abcd-student-TBP_mean').at(-1);
assert.equal(primary.rows[0].proportion,1/3);assert.equal(overlay.rows[0].mean,.75);assert.equal(overlay.rows[0].metric_id,'TBP_mean');
''')


def test_any_and_recurrent_thresholds_keep_distinct_series():
    run_js(r'''
const {snapshot}=setup(),st=state(),loader=readyLoader(snapshot);Study2PeriodUI.mountSemester(environment(snapshot,st,loader));
st.semester_trends.metric_id='TBV_prevalence2';st.semester_trends.threshold='both';
const comparison={...Period,query(c,s){const result=Period.query(c,s);if(s.metric_id==='TBV_prevalence2')result.rows=result.rows.flatMap(row=>[{...row,metric_id:'TBV_prevalence1',threshold:'any'}, {...row,threshold:'recurrent',proportion:0,numerator:0}]);return result;}};
const env=environment(snapshot,st,loader,{period:comparison});Study2PeriodUI.mountSemester(env);
const panel=walk(env.host).find(n=>n.className.split(' ').includes('semester-panel'));
const a=walk(panel).find(n=>n.tag==='circle'&&n.attributes?.['data-wave']==='T0'&&n.attributes?.['data-threshold']==='any');
const b=walk(panel).find(n=>n.tag==='circle'&&n.attributes?.['data-wave']==='T0'&&n.attributes?.['data-threshold']==='recurrent');
assert(a&&b);assert.notEqual(a.attributes.fill,b.attributes.fill);
''')


def test_full_scale_extends_to_include_outside_values_without_clipping():
    run_js(r'''
const {snapshot}=setup(),st=state(),loader=readyLoader(snapshot),wide={...Period,query(c,s){const out=Period.query(c,s);if(c.role==='student')out.rows[0].mean=15.125;return out;}};
const env=environment(snapshot,st,loader,{period:wide});Study2PeriodUI.mountSemester(env);
assert(walk(env.host).some(n=>n.textContent.includes('Full scale: 0.00–15.13')&&n.textContent.includes('extended to include observed values')));
assert.equal(calls.tables.find(t=>t.name==='semester-abcd-student').rows[0].mean,15.125);
''')


def test_roles_use_separate_four_part_stacks_and_do_not_invent_counts():
    run_js(r'''
const {snapshot}=setup(),st=state(),loader=readyLoader(snapshot);Study2PeriodUI.mountSemester(environment(snapshot,st,loader));
st.semester_trends.metric_id='bullying_roles_traditional';st.semester_trends.threshold='both';const env=environment(snapshot,st,loader);Study2PeriodUI.mountSemester(env);
const t=calls.tables.filter(t=>t.name==='semester-abcd-student').at(-1);assert(t.rows.some(r=>r.threshold==='any')&&t.rows.some(r=>r.threshold==='recurrent'));
assert.equal(new Set(t.rows.map(r=>r.category_code)).size,4);assert(walk(env.host).filter(n=>n.tag==='rect').length>0);
assert(calls.notices.some(x=>x.includes('past three months, grouped by response semester')));
const badPeriod={...Period,query(c,s){const result=Period.query(c,s);result.rows[0].numerator=99;return result;}};
Study2PeriodUI.mountSemester(environment(snapshot,st,loader,{period:badPeriod}));assert(calls.notices.some(x=>x.includes('incomplete or inconsistent')));
''')


def test_unavailable_no_valid_and_interval_are_not_imputed():
    run_js(r'''
const {snapshot}=setup(),st=state(),loader=readyLoader(snapshot);Study2PeriodUI.mountSemester(environment(snapshot,st,loader));
st.semester_trends.metric_id='TBV_prevalence2';st.semester_trends.ci='wilson_95_unclustered';
const noData={...Period,query(c,s){const r=Period.query(c,s);r.rows[0]={...r.rows[0],status:'no_valid_scores',numerator:null,denominator:0,proportion:null,ci_low:null,ci_high:null,ci_method:null,valid_n:0,missing_n:4};return r;}};
const env=environment(snapshot,st,loader,{period:noData});Study2PeriodUI.mountSemester(env);
const table=calls.tables.filter(t=>t.name==='semester-abcd-student').at(-1);assert.equal(table.rows[0].display,'No valid scores');assert.equal(table.rows[0].proportion,null);assert(calls.notices.some(x=>x.includes('not school-cluster-adjusted')));
assert(walk(env.host).some(x=>x.tag==='line'));assert(table.rows.some(r=>r.ci_method==='wilson_95_unclustered'));
''')


def test_stale_loading_completion_cannot_repaint_and_retry_keeps_settings():
    run_js(r'''
const {assets,snapshot}=setup(),pending=[];let current=true,renders=0;
const loader=Study2PeriodUI.createSemesterLoader({getPeriod:()=>Period,cryptoAPI:webcrypto,base:BASE,fetcher:(url)=>new Promise(resolve=>pending.push(()=>resolve(response(assets[new URL(url).pathname.split('/').at(-1)],url))))});
const st=state(),env=environment(snapshot,st,loader,{isCurrent:()=>current,rerender:()=>renders++});Study2PeriodUI.mountSemester(env);assert.equal(pending.length,2);current=false;pending.forEach(fn=>fn());await new Promise(r=>setTimeout(r,10));assert.equal(renders,0);
const failing={load(_s,st){return {key:st.role,status:'error',error:'request failed'};},retry(key){this.retried=key;}};st.semester_trends={academic_years:[2023],semesters:['S1'],waves:['T0'],from:'2023-09-01',to:'2024-01-31',metric_id:'PHQ_total',threshold:'recurrent',ci:'none',chart:'line'};
const retryEnv=environment(snapshot,st,failing);Study2PeriodUI.mountSemester(retryEnv);const button=walk(retryEnv.host).find(x=>x.dataset.control==='semester:retry:parent');button.onclick();assert.equal(failing.retried,'parent');assert.deepEqual(st.semester_trends.waves,['T0']);
''')


def test_ui_runs_against_actual_semester_engine_with_missing_and_outside_periods():
    import pandas as pd
    from study2.static_semester import JS as SEMESTER_JS, build_cube

    records = []
    for role in ('student', 'parent'):
        for i, (wave, observed, score) in enumerate([
            ('T0', '2023-09-01T00:00:00Z', 2.0),
            ('T1', '2024-02-01T00:00:00Z', 4.0),
            ('T0', '2025-09-01T00:00:00Z', None),
        ]):
            records.append(dict(submission_id=f'synthetic-{role}-{i}', version_id=f'v-{role}-{i}',
                role=role, wave=wave, observed_at=observed, date_basis='system_creation',
                time_confidence='observed', report_mode='abcd', grouping_anchor='wave_response',
                _grade='P3', anchor_gender='0', anchor_school_stage='primary',
                anchor_mainstream=True, anchor_source_type='qualtrics', PHQ_total=score, TBV_mean=0.75,
                TBV_prevalence1=1, TBV_prevalence2=0, TBP_prevalence1=0, TBP_prevalence2=0))
    frames = pd.DataFrame(records)
    cubes = {role: build_cube(frames.loc[frames.role == role].copy(), role, mode='abcd',
                grade_anchor='student_wave', grouping_anchor='wave_response', source_filter_anchor='wave_response',
                release_id='RUN_SYNTHETIC', eligibility='off', eligibility_revision=None,
                active_on_revision='a'*64) for role in ('student','parent')}
    body = r'''
const cubes=CUBES,{snapshot}=setup(),st=state();
const loader={load(_s,st){const c=cubes[st.role],ref=snapshot.period_semester_selection.refs.find(r=>r.mode==='abcd'&&r.role===st.role&&r.eligibility==='off');return {status:'ready',cube:c,ref};}};
const env=environment(snapshot,st,loader,{period:Study2Semester});Study2PeriodUI.mountSemester(env);
let t=calls.tables.find(t=>t.name==='semester-abcd-student');assert(t,'Actual engine results must render');
assert.deepEqual(st.semester_trends.academic_years,[2023,2025]);
assert(t.rows.some(r=>r.status==='available'&&r.mean===2));assert(t.rows.some(r=>r.status==='no_valid_scores'&&r.mean===null));
st.semester_trends.overlay='TBV_mean';Study2PeriodUI.mountSemester(environment(snapshot,st,loader,{period:Study2Semester}));
let overlay=calls.tables.filter(t=>t.name==='semester-overlay-abcd-student-TBV_mean').at(-1);assert(overlay.rows.some(r=>r.status==='available'&&r.mean===.75));assert.equal(overlay.scope.metadata.score_definition.includes('Traditional bullying victimization'),true);
st.semester_trends.from='2023-09-01';st.semester_trends.to='2024-01-31';st.semester_trends.metric_id='TBV_prevalence2';st.semester_trends.threshold='both';
Study2PeriodUI.mountSemester(environment(snapshot,st,loader,{period:Study2Semester}));
t=calls.tables.filter(t=>t.name==='semester-abcd-student').at(-1);assert(t.rows.some(r=>r.status==='outside_date_range'&&r.proportion===null));assert(t.rows.some(r=>r.threshold==='any')&&t.rows.some(r=>r.threshold==='recurrent'));
st.semester_trends.metric_id='bullying_roles_traditional';st.semester_trends.threshold='both';
Study2PeriodUI.mountSemester(environment(snapshot,st,loader,{period:Study2Semester}));
t=calls.tables.filter(t=>t.name==='semester-abcd-student').at(-1);assert(t.rows.some(r=>r.kind==='joint_roles'&&r.status==='available'));assert(!calls.notices.some(n=>n.includes('Joint role counts are incomplete')));
st.grades=[];Study2PeriodUI.mountSemester(environment(snapshot,st,loader,{period:Study2Semester}));
t=calls.tables.filter(t=>t.name==='semester-abcd-student').at(-1);assert(t.rows.every(r=>r.status!=='available'&&r.proportion===null));
'''.replace('CUBES', json.dumps(cubes))
    script = SEMESTER_JS + '\n' + JS_SOURCE + '\n' + COMMON + '\n(async()=>{\n' + body + '\n})().catch(e=>{console.error(e);process.exitCode=1;});'
    result = subprocess.run([shutil.which('node'), '-e', script], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_actual_csv_function_preserves_semester_metadata_and_full_precision():
    import csv
    import io
    from study2.static_assets import APP_JS
    csv_function = next(line for line in APP_JS.splitlines() if line.startswith('function csv('))
    result = run_js(r'''
const {snapshot}=setup(),st=state();Study2PeriodUI.mountSemester(environment(snapshot,st,readyLoader(snapshot)));
const t=calls.tables.find(t=>t.name==='semester-abcd-parent');
const output=((S,state,metadata,row,columns)=>{const page=1,parent={},eligibility=null,Source={choose:()=>({})},releaseMetadata=()=>({analytical_run_id:'RUN_SYNTHETIC'});
CSV_FUNCTION
return csv([{...row,mean:1.2345678901234567}],columns,{type:'semester_trends',metadata});})(snapshot,st,t.scope.metadata,t.rows[0],t.columns);
console.log(JSON.stringify(output));
'''.replace('CSV_FUNCTION', csv_function))
    row = next(csv.DictReader(io.StringIO(result.lstrip('\ufeff'))))
    assert row['role'] == 'parent'
    assert row['active_on_revision'] == 'a'*64
    assert row['eligibility_mode'] == 'off'
    assert row['eligibility_revision'] == ''
    assert row['academic_years'] == '2023|2025'
    assert row['interval'] == 'inclusive_day'
    assert row['Mean (raw)'] == '1.2345678901234567'
    assert json.loads(row['date_provenance'])[0]['date_quality'] == 'system_creation'


def test_actual_browser_layout_keyboard_controls_and_csv():
    import os
    from study2.static_assets import APP_JS, STYLES
    node = shutil.which('node')
    if not node:
        pytest.skip('Node is required')
    check = subprocess.run([node, '-e', "try{require('playwright')}catch(e){process.exit(2)}"], capture_output=True)
    if check.returncode:
        pytest.skip('Playwright is unavailable')
    helpers = APP_JS[APP_JS.index('function download('):APP_JS.index('function chart(')]
    fixture = r'''
const REV='a'.repeat(64),snapshot={release_id:'RUN_SYNTHETIC',minimum_cell_n:0,generated_at:'2026-01-01',release_context:{run_id:'RUN_SYNTHETIC'},dictionary:[{variable_id:'PHQ_total',label:'PHQ total'}]};
const state=window.semesterState={mode:'abcd',role:'student',grades:['P3'],sources:['qualtrics'],mainstream:true,group:'all',batch:false,reading:'trends'},parent={},S=snapshot,page=1,eligibility=null;
const Source={choose:()=>({})},releaseMetadata=()=>({analytical_run_id:'RUN_SYNTHETIC'}),n=v=>v==null?'—':String(v),num=v=>v==null?'—':Number(v).toFixed(2),el=(tag,cls,text)=>{const x=document.createElement(tag);if(cls)x.className=cls;if(text!==undefined)x.textContent=text;return x;};
HELPERS
const notice=(host,text,warning)=>host.append(el('p','notice'+(warning?' warning':''),text)),root=document.querySelector('#app');
const scope={mode:'off',revision:null,active_on_revision:REV};
const loader={load(_snapshot,st){return {status:'ready',ref:{sha256:'b'.repeat(64),extent:{start:'2023-09-01',end:'2026-08-31'}},cube:{format:'study2_period_semester_v1',release_id:'RUN_SYNTHETIC',role:st.role,metrics:[{variable_id:'PHQ_total',kind:'continuous',unit:'score'},{variable_id:'TBV_mean',kind:'continuous',unit:'score',subject:st.role==='student'?'student_child':'parent_reported_child'},{variable_id:'TBV_prevalence2',kind:'binary',unit:'proportion'}],joint_metrics:[],cell_fields:['date'],cells:[['2023-09-01'],['2025-09-01']]}};}};
const period={query(c,s){const binary=s.metric_id==='TBV_prevalence2';return {format:'study2_period_semester_result_v1',release_id:c.release_id,eligibility:'off',eligibility_revision:null,active_on_revision:REV,mode:'abcd',role:c.role,selection:s,anchors:{grade_anchor:'student_wave'},date_quality:[],date_exclusions:[],rows:s.academic_years.flatMap(year=>s.semesters.flatMap(semester=>s.waves.map(wave=>({academic_year_start:year,semester,wave,period_start:year+'-09-01',period_end:(year+1)+'-01-31',covered_start:year+'-09-01',covered_end:(year+1)+'-01-31',partial_period:false,metric_id:s.metric_id,kind:binary?'binary':'continuous',unit:binary?'proportion':'score',subject:c.role==='student'?'student_child':s.metric_id==='PHQ_total'?'respondent_adult':'parent_reported_child',threshold:binary?s.threshold:null,category_code:null,sample_n:3,valid_n:2,missing_n:1,outside_range_n:0,numerator:binary?1:null,denominator:binary?2:null,proportion:binary?0.5:null,mean:binary?null:s.metric_id==='TBV_mean'?0.75:(c.role==='student'?2:4),sd:binary?null:1,ci_low:null,ci_high:null,ci_method:null,status:'available'}))))};}};
function render(){const focus=document.activeElement?.dataset.control;root.replaceChildren();Study2PeriodUI.mountSemester({host:root,snapshot,state,scope,loader,period,isCurrent:()=>true,rerender:render,el,select,notice,cards:()=>{},table,lineChart:()=>{},num,n});if(focus)[...root.querySelectorAll('[data-control]')].find(x=>x.dataset.control===focus)?.focus();}
render();
'''.replace('HELPERS', helpers)
    payload = json.dumps({'ui': JS_SOURCE, 'styles': STYLES, 'fixture': fixture})
    browser_script = r'''
'use strict';
const fs=require('node:fs'),assert=require('node:assert/strict'),{chromium}=require('playwright');
const input=JSON.parse(fs.readFileSync(0,'utf8'));
(async()=>{
 const browser=await chromium.launch({headless:true});
 try{
  for(const viewport of [{width:1280,height:900},{width:390,height:844}]){
   const page=await browser.newPage({viewport,acceptDownloads:true}),errors=[];
   page.setDefaultTimeout(6000);
   page.on('pageerror',e=>errors.push(e.message));
   await page.setContent('<!doctype html><html><head><style>'+input.styles+'</style></head><body><main id="app"></main></body></html>');
   await page.addScriptTag({content:input.ui});
   await page.addScriptTag({content:input.fixture});
   assert.equal(await page.locator('.semester-panel').count(),2);
   const student=await page.locator('.semester-panel').nth(0).boundingBox(),parent=await page.locator('.semester-panel').nth(1).boundingBox();
   assert(parent.y>student.y,'student must appear above parent at every viewport');
   assert(Math.abs(parent.width-student.width)<1,'both panels must use the same full width');
   assert.equal(await page.locator('.semester-panel svg[role="img"]').count(),2);
   const chart=await page.locator('.semester-panel .analysis-body').first().boundingBox(),chartControls=await page.locator('.semester-panel .semester-chart-settings').first().boundingBox();
   if(viewport.width>800){assert(chartControls.x>chart.x,'chart controls should sit to the right of the chart');const svg=await page.locator('.semester-panel svg').first().boundingBox();assert(svg.width>chart.width*.8,'chart should use available chart width');}
   else assert(chartControls.y<chart.y,'narrow controls should stack before the chart');
   assert(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth),'charts and controls must not cause page-level horizontal overflow');
   assert(await page.locator('[data-control="semester:academic_years:2023"]').isChecked());
   await page.locator('[data-control="semester:academic_years:2023"]').focus();await page.keyboard.press('Space');
   assert.deepEqual(await page.evaluate(()=>window.semesterState.semester_trends.academic_years),[2025]);
   assert.equal(await page.evaluate(()=>document.activeElement?.dataset.control),'semester:academic_years:2023');
   await page.locator('[data-control="semester:waves:T1"]').focus();await page.keyboard.press('Space');
   assert.deepEqual(await page.evaluate(()=>window.semesterState.semester_trends.waves),['T0']);
   await page.getByRole('button',{name:'Both waves',exact:true}).click();
   assert.deepEqual(await page.evaluate(()=>window.semesterState.semester_trends.waves),['T0','T1']);
   const scaleOptions=await page.locator('[data-control="semester:control:student:metric"] option').evaluateAll(opts=>opts.map(o=>o.value));
   assert(scaleOptions.includes('PHQ_total')&&!scaleOptions.some(v=>/^(TBV|TBP|CBV|CBP)_|^bullying_roles_/.test(v)));
   await page.locator('[data-control="semester:control:student:overlay"]').focus();await page.locator('[data-control="semester:control:student:overlay"]').selectOption('TBV_mean');
   assert.equal(await page.evaluate(()=>document.activeElement?.dataset.control),'semester:control:student:overlay');
   assert.equal(await page.locator('[data-control="semester:control:parent:overlay"]').inputValue(),'TBV_mean');
   assert.equal(await page.locator('.semester-panel').first().locator('svg [data-series="overlay"]').count()>0,true);
   assert((await page.locator('.semester-panel').first().innerText()).includes('Right axis: Traditional bullying victimization mean score'));
   await page.locator('[data-control="semester:visible:student:T1"]').uncheck();
   assert.deepEqual(await page.evaluate(()=>window.semesterState.semester_trends.waves),['T0','T1']);
   assert.equal(await page.locator('.semester-panel').first().locator('svg [data-wave="T1"]').count(),0);
   assert(await page.locator('.semester-panel').nth(1).locator('svg [data-wave="T1"]').count()>0);
   const studentOverlayPoint=page.locator('.semester-panel').first().locator('rect[data-series="overlay"][data-wave="T0"]').first();
   await studentOverlayPoint.hover();let tip=page.locator('.semester-panel').first().getByRole('tooltip');await tip.waitFor({state:'visible'});
   let tipText=await tip.innerText();assert(tipText.includes('Overlapping points:')&&tipText.includes('PHQ total')&&tipText.includes('Traditional bullying victimization mean score (overlay)'));
   await page.locator('[data-control="semester:visible:student:overlay"]').uncheck();
   const primaryPoint=page.locator('.semester-panel').first().locator('circle[data-series="primary"][data-wave="T0"]').first();
   await primaryPoint.hover();tip=page.locator('.semester-panel').first().getByRole('tooltip');await tip.waitFor({state:'visible'});
   tipText=await tip.innerText();assert(tipText.includes('Student self-report')&&tipText.includes('2025–2026 S1')&&tipText.includes('PHQ total')&&tipText.includes('mean 2.00')&&tipText.includes('SD 1.00')&&tipText.includes('valid N 2'));
   await page.locator('[data-control="semester:visible:student:overlay"]').check();
   const parentPoint=page.locator('.semester-panel').nth(1).locator('rect[data-series="overlay"][data-wave="T1"]').first();await parentPoint.focus();tip=page.locator('.semester-panel').nth(1).getByRole('tooltip');await tip.waitFor({state:'visible'});tipText=await tip.innerText();assert(tipText.includes('Parent report about the child')&&tipText.includes('Traditional bullying victimization mean score (overlay)')&&tipText.includes('mean 0.75'));await parentPoint.press('Escape');assert(await tip.isHidden());
   const downloadPromise=page.waitForEvent('download');
   await page.locator('.semester-panel').first().getByRole('button',{name:'Download current table (CSV)',exact:true}).first().click();
   const download=await downloadPromise,text=fs.readFileSync(await download.path(),'utf8');
   assert(text.includes('active_on_revision')&&text.includes('Academic year start')&&text.includes('calendar_response'));
   assert(text.includes('RUN_SYNTHETIC')&&text.includes('student')&&text.includes('2025'));
   await page.locator('.semester-panel').first().getByText('Bullying overlay: results and CSV',{exact:true}).click();
   const overlayDownloadPromise=page.waitForEvent('download');
   await page.locator('.semester-panel').first().locator('details').filter({hasText:'Bullying overlay: results and CSV'}).getByRole('button',{name:'Download current table (CSV)',exact:true}).click();
   const overlayDownload=await overlayDownloadPromise,overlayText=fs.readFileSync(await overlayDownload.path(),'utf8');
   assert(overlayText.includes('TBV_mean')&&overlayText.includes('chart_series')&&overlayText.includes('overlay'));
   await page.locator('[data-control="semester:control:student:bullying_display"]').selectOption('prevalence');
   assert.equal(await page.locator('[data-control="semester:control:parent:bullying_display"]').inputValue(),'prevalence');
   const binaryPoint=page.locator('.semester-panel').first().locator('circle[data-series="primary"][data-wave="T0"]').first();await binaryPoint.focus();tip=page.locator('.semester-panel').first().getByRole('tooltip');await tip.waitFor({state:'visible'});tipText=await tip.innerText();assert(tipText.includes('1 case / 2 valid responses (50.00%)')&&!tipText.includes('mean ')&&!tipText.includes('SD '));
   assert.equal(errors.length,0,errors.join('; '));
   await page.close();
  }
  process.stdout.write(JSON.stringify({viewports:2,checks:'layout, controls, chart, CSV'}));
 }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
'''
    result = subprocess.run([node, '-e', browser_script],
                            input=payload, capture_output=True, text=True, timeout=45, env=os.environ.copy())
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)['viewports'] == 2
