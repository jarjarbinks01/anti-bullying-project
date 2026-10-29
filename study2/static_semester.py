"""Bounded protected semester aggregates and a pure browser query engine.

Builds only from already selected native cohorts. It never selects/relinks
people, changes scores, or exposes record-level fields to the browser.
"""
from collections import defaultdict
from datetime import date
import json
import math
import re

import numpy as np
import pandas as pd

from .common import PipelineError
from .descriptive_spec import GROUPS, variables
from .descriptive_trends import DATE_LABELS, TIMEZONE, dated_rows
from .descriptives import values_and_status
from .static_grade import CODES as GRADES, moments
from .static_period import _anchors
from .static_sources import PARTITIONS as SOURCES, source_code

FORMAT = 'study2_period_semester_v1'
RESULT_FORMAT = 'study2_period_semester_result_v1'
DATE_POLICY = 'native_calendar_response_v1'
MODES = ('abcd', 'ef', 'acbd', 'efmatched', 'independent_all', 'independent_child', 'independent_adult')
CELL_FIELDS = ['date', 'wave', 'gender', 'stage', 'grade', 'source', 'mainstream', 'date_quality', 'n', 'values', 'joint_roles']
QUALITIES = list(DATE_LABELS)
JOINT = (('bullying_roles_traditional', 'any', 'TBP_prevalence1', 'TBV_prevalence1'),
         ('bullying_roles_traditional', 'recurrent', 'TBP_prevalence2', 'TBV_prevalence2'),
         ('bullying_roles_cyber', 'any', 'CBP_prevalence1', 'CBV_prevalence1'),
         ('bullying_roles_cyber', 'recurrent', 'CBP_prevalence2', 'CBV_prevalence2'))
ROLE_CODES = ('perpetrator_only', 'victim_only', 'both', 'neither')


def _need(ok, code):
    if not ok:
        raise PipelineError('Invalid semester aggregate: ' + code)


def _hash(value):
    return isinstance(value, str) and re.fullmatch('[0-9a-f]{64}', value) is not None


def _subject(key, role):
    if key.startswith('PHQ_') or key == 'phq_band':
        return 'respondent_adult' if role == 'parent' else 'student_child'
    if key.startswith('FQOL_'):
        return 'family'
    return 'parent_reported_child' if role == 'parent' else 'student_child'


def _specs(role):
    return variables(role, 'scales')


def _metric_meta(var, role, available):
    return dict(variable_id=var.key, kind=var.kind,
                unit='score' if var.kind == 'continuous' else 'proportion',
                subject=_subject(var.key, role), available=available,
                categories=[code for code, _ in var.categories] if var.kind == 'category' else [])


def build_cube(rows, role, *, mode, grade_anchor, grouping_anchor, source_filter_anchor,
               release_id, eligibility, eligibility_revision, active_on_revision):
    _need(role in {'student', 'parent'} and mode in MODES and
          (not mode.startswith('independent') or role == 'parent'), 'mode_or_role')
    _need((grade_anchor, grouping_anchor, source_filter_anchor) == _anchors(mode, role), 'anchor_capability')
    _need(eligibility in {'off', 'on'} and
          ((eligibility == 'off' and eligibility_revision is None) or
           (eligibility == 'on' and _hash(eligibility_revision) and eligibility_revision == active_on_revision)) and
          (active_on_revision is None or _hash(active_on_revision)), 'eligibility_binding')
    required = {'role', '_grade', 'anchor_gender', 'anchor_school_stage', 'anchor_mainstream', 'anchor_source_type'}
    _need(required <= set(rows) and rows['role'].eq(role).all(), 'prepared_anchor_fields_required')
    _need(rows['_grade'].isin(GRADES).all(), 'grade_capability')
    dated = dated_rows(rows)
    gender = dated['anchor_gender'].fillna('').astype(str)
    stage = dated['anchor_school_stage']
    profiles = list(zip(gender.where(gender.isin(['0', '1']), 'unknown'),
        stage.where(stage.isin(['primary', 'secondary']), 'unknown'), dated['_grade'],
        dated['anchor_source_type'].map(source_code), dated['anchor_mainstream'].fillna(False).astype(bool)))
    buckets = defaultdict(list)
    for i, (day, wave, quality) in enumerate(zip(dated['_calendar_date'], dated['wave'], dated['_date_quality'])):
        normalized_day = day.isoformat() if quality not in {'unknown_basis', 'invalid_date'} else None
        buckets[normalized_day, wave, *profiles[i], quality].append(i)
    specs = _specs(role)
    schema, prepared, arrays_by_key = [], [], {}
    for var in specs:
        available = ('PHQ_total' in dated.columns if var.key == 'phq_band' else var.key in dated.columns)
        schema.append(_metric_meta(var, role, available))
        if not available:
            prepared.append(None)
            continue
        values, status = values_and_status(dated, var)
        outside = status.eq('outside_report_range').to_numpy(dtype=bool)
        values = (values.to_numpy(dtype=object) if var.kind == 'category' else
                  values.to_numpy(dtype=float, na_value=np.nan))
        prepared.append((values, outside))
        arrays_by_key[var.key] = values
    joint_schema = [dict(metric_id=metric, threshold=threshold,
                         available=perp in arrays_by_key and victim in arrays_by_key)
                    for metric, threshold, perp, victim in JOINT]
    cells = []
    for key in sorted(buckets, key=lambda k: (k[0] or '', *k[1:])):
        indices = buckets[key]
        statistics = []
        for var, arrays in zip(specs, prepared):
            if arrays is None:
                statistics.append(None)
                continue
            values, outside = arrays
            selected = values[indices]
            outside_n = int(outside[indices].sum())
            if var.kind == 'category':
                valid = selected[pd.notna(selected)]
                counts = [int((valid == code).sum()) for code, _ in var.categories]
                statistics.append([len(valid), outside_n, counts])
            else:
                valid = selected[np.isfinite(selected)]
                statistics.append([len(valid), outside_n, *moments(valid)] if var.kind == 'continuous'
                                  else [len(valid), outside_n, int((valid == 1).sum())])
        joint_vectors = []
        for meta, (_, _, perp, victim) in zip(joint_schema, JOINT):
            if not meta['available']:
                joint_vectors.append(None)
                continue
            p, v = arrays_by_key[perp][indices], arrays_by_key[victim][indices]
            valid = np.isfinite(p) & np.isfinite(v)
            p, v = p[valid], v[valid]
            joint_vectors.append([len(p), int(((p == 1) & (v == 0)).sum()),
                                  int(((p == 0) & (v == 1)).sum()), int(((p == 1) & (v == 1)).sum()),
                                  int(((p == 0) & (v == 0)).sum())])
        cells.append([*key, len(indices), statistics, joint_vectors])
    return validate_cube(dict(format=FORMAT, release_id=release_id, eligibility=eligibility,
        eligibility_revision=eligibility_revision, active_on_revision=active_on_revision,
        mode=mode, role=role, grade_anchor=grade_anchor, grouping_anchor=grouping_anchor,
        source_filter_anchor=source_filter_anchor, timezone=TIMEZONE, date_policy=DATE_POLICY,
        metrics=schema, joint_metrics=joint_schema, cell_fields=list(CELL_FIELDS), cells=cells))


def validate_cube(cube):
    fields = {'format', 'release_id', 'eligibility', 'eligibility_revision', 'active_on_revision',
              'mode', 'role', 'grade_anchor', 'grouping_anchor', 'source_filter_anchor',
              'timezone', 'date_policy', 'metrics', 'joint_metrics', 'cell_fields', 'cells'}
    _need(isinstance(cube, dict) and set(cube) == fields, 'shape')
    _need(cube['format'] == FORMAT and cube['timezone'] == TIMEZONE and cube['date_policy'] == DATE_POLICY, 'format')
    _need(isinstance(cube['release_id'], str) and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}', cube['release_id']), 'release')
    role, mode = cube['role'], cube['mode']
    _need(mode in MODES and role in {'student', 'parent'} and (not mode.startswith('independent') or role == 'parent'), 'mode_or_role')
    _need(tuple(cube[k] for k in ('grade_anchor', 'grouping_anchor', 'source_filter_anchor')) == _anchors(mode, role), 'anchors')
    _need(cube['eligibility'] in {'off', 'on'} and
          (cube['active_on_revision'] is None or _hash(cube['active_on_revision'])) and
          ((cube['eligibility'] == 'off' and cube['eligibility_revision'] is None) or
           (cube['eligibility'] == 'on' and _hash(cube['eligibility_revision']) and cube['eligibility_revision'] == cube['active_on_revision'])), 'eligibility_binding')
    _need(cube['cell_fields'] == CELL_FIELDS and isinstance(cube['cells'], list), 'cell_schema')
    specs = _specs(role)
    _need(isinstance(cube['metrics'], list) and len(cube['metrics']) == len(specs), 'metric_schema')
    for meta, var in zip(cube['metrics'], specs):
        _need(isinstance(meta, dict) and type(meta.get('available')) is bool and
              meta == _metric_meta(var, role, meta['available']), 'metric_metadata')
    available = {m['variable_id']: m['available'] for m in cube['metrics']}
    joint = [dict(metric_id=metric, threshold=threshold, available=available[perp] and available[victim])
             for metric, threshold, perp, victim in JOINT]
    _need(cube['joint_metrics'] == joint, 'joint_metadata')
    indices = {m['variable_id']: i for i, m in enumerate(cube['metrics'])}
    joint_indices = [(indices[perp], indices[victim]) for _, _, perp, victim in JOINT]
    count = lambda n: type(n) is int and 0 <= n <= 2**53-1
    finite = lambda n: type(n) in (int, float) and math.isfinite(n)
    seen = set(); total = 0
    for cell in cube['cells']:
        _need(isinstance(cell, list) and len(cell) == len(CELL_FIELDS), 'cell_shape')
        day, wave, gender, stage, grade, source, mainstream, quality, size, vectors, joint_vectors = cell
        _need(wave in {'T0', 'T1'} and gender in {'0', '1', 'unknown'} and stage in {'primary', 'secondary', 'unknown'}
              and grade in GRADES and source in SOURCES and type(mainstream) is bool and quality in QUALITIES, 'cell_codes')
        _need(count(size) and size > 0, 'cell_count')
        if quality in {'unknown_basis', 'invalid_date'}:
            _need(day is None, 'invalid_quality_date')
        else:
            try:
                _need(isinstance(day, str) and date.fromisoformat(day).isoformat() == day, 'date')
            except ValueError:
                raise PipelineError('Invalid semester aggregate: date') from None
        key = tuple(cell[:8]); _need(key not in seen, 'duplicate_cell'); seen.add(key)
        total += size; _need(count(total), 'count_overflow')
        _need(isinstance(vectors, list) and len(vectors) == len(specs), 'cell_values')
        for vector, meta in zip(vectors, cube['metrics']):
            if not meta['available']:
                _need(vector is None, 'unavailable_metric_values'); continue
            length = 4 if meta['kind'] == 'continuous' else 3
            _need(isinstance(vector, list) and len(vector) == length, 'statistic_shape')
            n, outside = vector[:2]
            _need(count(n) and count(outside) and n <= size and outside <= size-n, 'statistic_counts')
            if meta['kind'] == 'continuous':
                mean, m2 = vector[2:]
                _need((mean is None if not n else finite(mean)) and finite(m2) and m2 >= 0 and (n > 1 or m2 == 0), 'moments')
            elif meta['kind'] == 'binary':
                _need(count(vector[2]) and vector[2] <= n, 'binary_numerator')
            else:
                _need(isinstance(vector[2], list) and len(vector[2]) == len(meta['categories']) and
                      all(count(x) for x in vector[2]) and sum(vector[2]) == n, 'category_counts')
        _need(isinstance(joint_vectors, list) and len(joint_vectors) == len(JOINT), 'joint_shape')
        for vector, meta, (perp_i, victim_i) in zip(joint_vectors, joint, joint_indices):
            if not meta['available']:
                _need(vector is None, 'unavailable_joint_values'); continue
            _need(isinstance(vector, list) and len(vector) == 5 and all(count(x) for x in vector) and
                  vector[0] <= size and sum(vector[1:]) == vector[0], 'joint_counts')
            perp, victim = vectors[perp_i], vectors[victim_i]
            _, perp_only, victim_only, both, neither = vector
            _need(max(0, perp[0] - (size - victim[0])) <= vector[0] <= min(perp[0], victim[0]) and
                  perp_only + both <= perp[2] and victim_only + neither <= perp[0] - perp[2] and
                  victim_only + both <= victim[2] and perp_only + neither <= victim[0] - victim[2],
                  'joint_domain_mismatch')
    return cube


_CONFIG = dict(format=FORMAT, result_format=RESULT_FORMAT, date_policy=DATE_POLICY,
    modes=list(MODES), groups=list(GROUPS), grades=list(GRADES), sources=list(SOURCES), qualities=QUALITIES,
    cell_fields=CELL_FIELDS, metrics={role: [_metric_meta(v, role, True) for v in _specs(role)]
                                     for role in ('student', 'parent')},
    joint=[dict(metric_id=x[0], threshold=x[1], perpetration=x[2], victimization=x[3]) for x in JOINT],
    role_codes=list(ROLE_CODES))

JS = r'''
const Study2Semester = (()=>{
'use strict';
const C=__CONFIG__, WAVES=['T0','T1'], SEMESTERS=['S1','S2'];
const need=(ok,code)=>{if(!ok)throw Error('Invalid semester aggregate: '+code);};
const object=v=>v!==null&&typeof v==='object'&&!Array.isArray(v);
const keys=(v,ks)=>object(v)&&Object.keys(v).length===ks.length&&ks.every(k=>Object.hasOwn(v,k));
const equal=(a,b)=>Array.isArray(a)&&Array.isArray(b)&&a.length===b.length&&a.every((v,i)=>v===b[i]);
const count=n=>Number.isSafeInteger(n)&&n>=0;
const finite=n=>typeof n==='number'&&Number.isFinite(n);
const hash=v=>typeof v==='string'&&/^[0-9a-f]{64}$/.test(v);
const day=v=>typeof v==='string'&&/^\d{4}-\d{2}-\d{2}$/.test(v)&&Number(v.slice(0,4))>=1&&Number.isFinite(Date.parse(v+'T00:00:00Z'))&&new Date(v+'T00:00:00Z').toISOString().slice(0,10)===v;
function anchors(mode,role){const formal=['acbd','efmatched','independent_child','independent_adult'].includes(mode),ind=mode.startsWith('independent');const g=mode==='abcd'?'wave_response':mode==='ef'?'wave_student':ind?'independent_parent_T0':mode==='efmatched'||role==='student'?'student_T0':'BD_parent_T0';return [(ind?'parent_report_':'student_')+(formal?'T0':'wave'),g,mode==='ef'?'wave_role_response':g];}
function validate(c){
 need(keys(c,['format','release_id','eligibility','eligibility_revision','active_on_revision','mode','role','grade_anchor','grouping_anchor','source_filter_anchor','timezone','date_policy','metrics','joint_metrics','cell_fields','cells']),'shape');
 need(c.format===C.format&&c.timezone==='Asia/Hong_Kong'&&c.date_policy===C.date_policy,'format');
 need(typeof c.release_id==='string'&&/^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$/.test(c.release_id),'release');
 need(C.modes.includes(c.mode)&&['student','parent'].includes(c.role)&&(!c.mode.startsWith('independent')||c.role==='parent'),'mode_or_role');
 need(equal([c.grade_anchor,c.grouping_anchor,c.source_filter_anchor],anchors(c.mode,c.role)),'anchors');
 need(['off','on'].includes(c.eligibility)&&(c.active_on_revision===null||hash(c.active_on_revision))&&(c.eligibility==='off'?c.eligibility_revision===null:hash(c.eligibility_revision)&&c.eligibility_revision===c.active_on_revision),'eligibility_binding');
 need(equal(c.cell_fields,C.cell_fields)&&Array.isArray(c.cells),'cell_schema');
 need(Array.isArray(c.metrics)&&c.metrics.length===C.metrics[c.role].length,'metric_schema');
 c.metrics.forEach((m,i)=>{const wanted=C.metrics[c.role][i];need(keys(m,['variable_id','kind','unit','subject','available','categories']),'metric_shape');need(m.variable_id===wanted.variable_id&&m.kind===wanted.kind&&m.unit===wanted.unit&&m.subject===wanted.subject&&equal(m.categories,wanted.categories)&&typeof m.available==='boolean','metric_metadata');});
 need(Array.isArray(c.joint_metrics)&&c.joint_metrics.length===C.joint.length,'joint_schema');
 c.joint_metrics.forEach((m,i)=>{const j=C.joint[i],p=c.metrics.find(x=>x.variable_id===j.perpetration),v=c.metrics.find(x=>x.variable_id===j.victimization);need(keys(m,['metric_id','threshold','available'])&&m.metric_id===j.metric_id&&m.threshold===j.threshold&&m.available===(p.available&&v.available),'joint_metadata');});
 const jointIndices=C.joint.map(j=>[c.metrics.findIndex(m=>m.variable_id===j.perpetration),c.metrics.findIndex(m=>m.variable_id===j.victimization)]);
 const seen=new Set();let total=0;
 c.cells.forEach(cell=>{
  need(Array.isArray(cell)&&cell.length===11,'cell_shape');const [d,w,g,stage,grade,source,mainstream,q,n,vs,js]=cell;
  need(WAVES.includes(w)&&['0','1','unknown'].includes(g)&&['primary','secondary','unknown'].includes(stage)&&C.grades.includes(grade)&&C.sources.includes(source)&&typeof mainstream==='boolean'&&C.qualities.includes(q),'cell_codes');
  need(count(n)&&n>0,'cell_count');need(['unknown_basis','invalid_date'].includes(q)?d===null:day(d),'date');
  const key=JSON.stringify(cell.slice(0,8));need(!seen.has(key),'duplicate_cell');seen.add(key);total+=n;need(count(total),'count_overflow');
  need(Array.isArray(vs)&&vs.length===c.metrics.length,'cell_values');
  vs.forEach((v,i)=>{const m=c.metrics[i];if(!m.available){need(v===null,'unavailable_metric_values');return;}
   need(Array.isArray(v)&&v.length===(m.kind==='continuous'?4:3),'statistic_shape');const [valid,outside]=v;
   need(count(valid)&&count(outside)&&valid<=n&&outside<=n-valid,'statistic_counts');
   if(m.kind==='continuous')need((valid?finite(v[2]):v[2]===null)&&finite(v[3])&&v[3]>=0&&(valid>1||v[3]===0),'moments');
   else if(m.kind==='binary')need(count(v[2])&&v[2]<=valid,'binary_numerator');
   else need(m.kind==='category'&&Array.isArray(v[2])&&v[2].length===m.categories.length&&v[2].every(count)&&v[2].reduce((a,b)=>a+b,0)===valid,'category_counts');
  });
  need(Array.isArray(js)&&js.length===c.joint_metrics.length,'joint_shape');
  js.forEach((v,i)=>{if(!c.joint_metrics[i].available){need(v===null,'unavailable_joint_values');return;}need(Array.isArray(v)&&v.length===5&&v.every(count)&&v[0]<=n&&v.slice(1).reduce((a,b)=>a+b,0)===v[0],'joint_counts');
   const [p,q]=jointIndices[i].map(index=>vs[index]),[,perpOnly,victimOnly,both,neither]=v;
   need(v[0]>=Math.max(0,p[0]-(n-q[0]))&&v[0]<=Math.min(p[0],q[0])&&perpOnly+both<=p[2]&&victimOnly+neither<=p[0]-p[2]&&victimOnly+both<=q[2]&&perpOnly+neither<=q[0]-q[2],'joint_domain_mismatch');});
 });return true;
}
function normalize(c,s){
 const required=['academic_years','semesters','waves','from','to','group','grades','sources','mainstream','include_batch','metric_id','threshold','ci'];
 need(keys(s,required),'selection_shape');need(C.groups.includes(s.group)&&typeof s.mainstream==='boolean'&&typeof s.include_batch==='boolean','selection_filters');
 need(day(s.from)&&day(s.to)&&s.from<=s.to,'selection_dates');need(['recurrent','any','both'].includes(s.threshold)&&['none','wilson_95_unclustered'].includes(s.ci),'selection_options');
 need(Array.isArray(s.academic_years)&&s.academic_years.every(y=>Number.isInteger(y)&&y>=1&&y<=9998),'selection_years');
 const years=[...new Set(s.academic_years)].sort((a,b)=>a-b);
 function codes(value,allowed,name){need(Array.isArray(value)&&value.every(x=>allowed.includes(x)),name);return allowed.filter(x=>value.includes(x));}
 const semesters=codes(s.semesters,SEMESTERS,'selection_semesters'),waves=codes(s.waves,WAVES,'selection_waves');
 const grades=codes(s.grades,C.grades,'selection_grades'),allSources=codes(s.sources,['all',...C.sources],'selection_sources');
 need(!allSources.includes('all')||allSources.length===1,'selection_sources');
 const sources=allSources;
 const metricExists=s.metric_id==='volume'||c.metrics.some(m=>m.variable_id===s.metric_id)||c.joint_metrics.some(m=>m.metric_id===s.metric_id);
 need(typeof s.metric_id==='string'&&metricExists,'selection_metric');
 return {academic_years:years,semesters,waves,from:s.from,to:s.to,group:s.group,grades,sources,
         mainstream:s.mainstream,include_batch:s.include_batch,metric_id:s.metric_id,threshold:s.threshold,ci:s.ci};
}
function period(year,semester,s){
 const y=String(year).padStart(4,'0'),next=String(year+1).padStart(4,'0');
 const start=semester==='S1'?y+'-09-01':next+'-02-01',end=semester==='S1'?next+'-01-31':next+'-08-31';
 const lo=start<s.from?s.from:start,hi=end>s.to?s.to:end,overlap=lo<=hi;
 return {academic_year_start:year,semester,period_id:y+'-'+semester,period_start:start,period_end:end,
         covered_start:overlap?lo:null,covered_end:overlap?hi:null,partial_period:overlap&&(lo!==start||hi!==end),overlap};
}
function matches(cell,s){const [,,g,stage,grade,source,mainstream]=cell;return s.grades.includes(grade)&&(s.sources.includes('all')||s.sources.includes(source))&&(!s.mainstream||mainstream)&&(!s.group.startsWith('male')||g==='0')&&(!s.group.startsWith('female')||g==='1')&&(!s.group.endsWith('primary')||stage==='primary')&&(!s.group.endsWith('secondary')||stage==='secondary');}
const allowed=(q,batch)=>['system_creation','manual_verified'].includes(q)||(batch&&q==='batch_assigned_creation');
function empty(c){return {n:0,v:c.metrics.map(m=>!m.available?null:m.kind==='continuous'?[0,0,null,0]:m.kind==='binary'?[0,0,0]:[0,0,m.categories.map(()=>0)]),j:c.joint_metrics.map(m=>m.available?[0,0,0,0,0]:null)};}
function add(a,cell,c){const size=cell[8],vs=cell[9],js=cell[10];a.n+=size;need(count(a.n),'count_overflow');
 vs.forEach((b,i)=>{if(b===null)return;const v=a.v[i],n=v[0]+b[0];need(count(n),'count_overflow');
  if(c.metrics[i].kind==='continuous'&&b[0]){if(!v[0]){v[2]=b[2];v[3]=b[3];}else{const delta=b[2]-v[2];v[3]+=b[3]+delta*delta*v[0]*b[0]/n;v[2]+=delta*b[0]/n;}need(finite(v[2])&&finite(v[3]),'pooled_moments_overflow');}
  else if(c.metrics[i].kind==='binary')v[2]+=b[2];else if(c.metrics[i].kind==='category')b[2].forEach((x,j)=>{v[2][j]+=x;});
  v[0]=n;v[1]+=b[1];need(count(v[1]),'count_overflow');
 });
 js.forEach((b,i)=>{if(b===null)return;b.forEach((x,j)=>{a.j[i][j]+=x;need(count(a.j[i][j]),'count_overflow');});});
}
function wilson(k,n){if(!n)return [null,null];const z=1.959963984540054,z2=z*z,p=k/n,den=1+z2/n,mid=(p+z2/(2*n))/den,half=z*Math.sqrt(p*(1-p)/n+z2/(4*n*n))/den;return [Math.max(0,mid-half),Math.min(1,mid+half)];}
function chosen(c,s){
 const joint=c.joint_metrics.some(m=>m.metric_id===s.metric_id),thresholds=s.threshold==='both'?['any','recurrent']:[s.threshold];
 if(joint)return thresholds.map(t=>({joint:c.joint_metrics.findIndex(m=>m.metric_id===s.metric_id&&m.threshold===t),threshold:t}));
 const domain=/^(TBV|TBP|CBV|CBP)_prevalence[12]$/.exec(s.metric_id);
 if(domain)return thresholds.map(t=>({metric:c.metrics.findIndex(m=>m.variable_id===domain[1]+'_prevalence'+(t==='any'?'1':'2')),threshold:t}));
 return s.metric_id==='volume'?[{volume:true}]:[{metric:c.metrics.findIndex(m=>m.variable_id===s.metric_id),threshold:null}];
}
function rowsFor(c,a,p,w,s){
 const selected=chosen(c,s),base={academic_year_start:p.academic_year_start,semester:p.semester,period_id:p.period_id,
  wave:w,period_start:p.period_start,period_end:p.period_end,covered_start:p.covered_start,covered_end:p.covered_end,partial_period:p.partial_period};
 const result=[];
 function row(extra){result.push({...base,metric_id:s.metric_id,kind:null,unit:null,subject:null,threshold:null,category_code:null,
  sample_n:p.overlap?a.n:null,valid_n:null,missing_n:null,outside_range_n:null,numerator:null,denominator:null,proportion:null,
  mean:null,sd:null,ci_low:null,ci_high:null,ci_method:null,status:p.overlap?'no_responses':'outside_date_range',...extra});}
 for(const item of selected){
  if(item.volume){row({metric_id:'volume',kind:'count',unit:'responses',subject:c.role==='parent'?'parent_response':'student_response',
   valid_n:p.overlap?a.n:null,missing_n:p.overlap?0:null,status:!p.overlap?'outside_date_range':a.n?'available':'no_responses'});continue;}
  if(Object.hasOwn(item,'joint')){const meta=c.joint_metrics[item.joint],v=a.j[item.joint],status=!p.overlap?'outside_date_range':!meta.available?'metric_unavailable':!a.n?'no_responses':!v[0]?'no_valid_scores':'available';
   C.role_codes.forEach((code,i)=>row({metric_id:meta.metric_id,kind:'joint_roles',unit:'proportion',subject:c.role==='parent'?'parent_reported_child':'student_child',threshold:item.threshold,category_code:code,
    valid_n:p.overlap&&v?v[0]:null,missing_n:p.overlap&&v?a.n-v[0]:null,numerator:p.overlap&&v?v[i+1]:null,denominator:p.overlap&&v?v[0]:null,
    proportion:p.overlap&&v&&v[0]?v[i+1]/v[0]:null,status}));continue;}
  const meta=c.metrics[item.metric],v=a.v[item.metric],status=!p.overlap?'outside_date_range':!meta.available?'metric_unavailable':!a.n?'no_responses':!v[0]?'no_valid_scores':'available';
  const detail={metric_id:meta.variable_id,kind:meta.kind,unit:meta.unit,subject:meta.subject,threshold:item.threshold,
   valid_n:p.overlap&&v?v[0]:null,missing_n:p.overlap&&v?a.n-v[0]:null,outside_range_n:p.overlap&&v?v[1]:null,status};
  if(meta.kind==='continuous'){row({...detail,mean:p.overlap&&v?v[2]:null,sd:p.overlap&&v&&v[0]>1?Math.sqrt(v[3]/(v[0]-1)):null});continue;}
  if(meta.kind==='binary'){
   const bounds=p.overlap&&v&&v[0]&&s.ci==='wilson_95_unclustered'?wilson(v[2],v[0]):[null,null];
   row({...detail,numerator:p.overlap&&v?v[2]:null,denominator:p.overlap&&v?v[0]:null,proportion:p.overlap&&v&&v[0]?v[2]/v[0]:null,
    ci_low:bounds[0],ci_high:bounds[1],ci_method:bounds[0]===null?null:'wilson_95_unclustered'});continue;
  }
  meta.categories.forEach((code,i)=>row({...detail,category_code:code,numerator:p.overlap&&v?v[2][i]:null,denominator:p.overlap&&v?v[0]:null,proportion:p.overlap&&v&&v[0]?v[2][i]/v[0]:null}));
 }
 return result;
}
function query(c,input){
 validate(c);const s=normalize(c,input),metadata={format:C.result_format,release_id:c.release_id,eligibility:c.eligibility,eligibility_revision:c.eligibility_revision,active_on_revision:c.active_on_revision,mode:c.mode,role:c.role,selection:s,
  anchors:{grade_anchor:c.grade_anchor,grouping_anchor:c.grouping_anchor,source_filter_anchor:c.source_filter_anchor},timezone:c.timezone,date_policy:c.date_policy,basis:'calendar_response'};
 if(!s.academic_years.length||!s.semesters.length||!s.waves.length)return {...metadata,status:'empty_selection',rows:[],date_quality:[],date_exclusions:[]};
 const periods=s.academic_years.flatMap(y=>s.semesters.map(q=>period(y,q,s))),lookup=new Map(),quality={};
 periods.forEach(p=>{lookup.set(p.period_id,Object.fromEntries(s.waves.map(w=>[w,empty(c)])));});
 s.waves.forEach(w=>{quality[w]={};C.qualities.forEach(q=>quality[w][q]={input:0,included:0});});
 c.cells.forEach(cell=>{const [d,w,,,,,,q,n]=cell;if(!s.waves.includes(w)||!matches(cell,s))return;
  quality[w][q].input+=n;need(count(quality[w][q].input),'count_overflow');
  if(!allowed(q,s.include_batch)||!d||d<s.from||d>s.to)return;
  const year=Number(d.slice(0,4)),month=Number(d.slice(5,7)),academic=month>=9?year:year-1,semester=month>=9||month===1?'S1':'S2';
  const id=String(academic).padStart(4,'0')+'-'+semester;if(!lookup.has(id))return;
  quality[w][q].included+=n;need(count(quality[w][q].included),'count_overflow');add(lookup.get(id)[w],cell,c);
 });
 const rows=[],date_quality=[],date_exclusions=[];
 periods.forEach(p=>s.waves.forEach(w=>rows.push(...rowsFor(c,lookup.get(p.period_id)[w],p,w,s))));
 s.waves.forEach(w=>{const qs=quality[w];C.qualities.forEach(q=>date_quality.push({wave:w,date_quality:q,input_n:qs[q].input,included_n:qs[q].included}));
  const n=C.qualities.reduce((sum,q)=>sum+qs[q].input,0),known=n-qs.invalid_date.input-qs.unknown_basis.input,accepted=known-(s.include_batch?0:qs.batch_assigned_creation.input),included=C.qualities.reduce((sum,q)=>sum+qs[q].included,0);let previous=n;
  [['input',n],['known_dates',known],['date_source',accepted],['period',included]].forEach(([stage,remaining_n])=>{date_exclusions.push({wave:w,stage,remaining_n,excluded_n:previous-remaining_n});previous=remaining_n;});
 });
 return {...metadata,status:rows.some(r=>r.sample_n>0)?'available':'empty',rows,date_quality,date_exclusions};
}
return Object.freeze({FORMAT:C.format,RESULT_FORMAT:C.result_format,validate,query,normalize});})();
'''.replace('__CONFIG__', json.dumps(_CONFIG, ensure_ascii=False, separators=(',', ':')))
