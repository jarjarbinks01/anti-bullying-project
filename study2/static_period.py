"""Observed-day/disjoint-anchor moments for protected minimum-zero assets.

Consumes already prepared native cohorts. No files, identities, wave selection,
scoring or inference are produced here. Root owns protected lazy asset binding.
"""
from collections import defaultdict
from datetime import date
import json
import math
import re

import numpy as np

from .common import PipelineError
from .descriptive_spec import GROUPS, variables
from .descriptive_trends import DATE_LABELS, TIMEZONE, dated_rows
from .descriptives import values_and_status
from .static_grade import CODES as GRADES, moments
from .static_sources import PARTITIONS as SOURCES, source_code

FORMAT = 'study2_period_filters_v1'
DATE_POLICY = 'native_calendar_response_v1'
FOCUS = ('PHQ_total', 'FQOL_total', 'SEC_total', 'TBV_mean', 'TBP_mean', 'CBV_mean', 'CBP_mean')
BINARY = tuple(v.key for v in variables('student', 'scales') if v.kind == 'binary')
METRICS = (*FOCUS, *BINARY)
MODES = ('abcd', 'ef', 'acbd', 'efmatched', 'independent_all', 'independent_child', 'independent_adult')
CELL_FIELDS = ['date', 'wave', 'gender', 'stage', 'grade', 'source', 'mainstream', 'date_quality', 'n', 'values']
QUALITIES = list(DATE_LABELS)


def _need(ok, code):
    if not ok:
        raise PipelineError('Invalid period aggregate: ' + code)


def _anchors(mode, role):
    formal = mode in {'acbd', 'efmatched', 'independent_child', 'independent_adult'}
    grade = ('parent_report_' if mode.startswith('independent') else 'student_') + ('T0' if formal else 'wave')
    group = ('wave_response' if mode == 'abcd' else 'wave_student' if mode == 'ef' else
             'independent_parent_T0' if mode.startswith('independent') else
             'student_T0' if mode == 'efmatched' or role == 'student' else 'BD_parent_T0')
    return grade, group, 'wave_role_response' if mode == 'ef' else group


def _specs(role):
    by_key = {v.key: v for v in variables(role, 'scales')}
    return [by_key[key] for key in METRICS]


def build_cube(rows, role, *, mode, grade_anchor, grouping_anchor, source_filter_anchor, release_id):
    """Build once before group/grade/source/mainstream/date selections."""
    _need(role in {'student', 'parent'} and mode in MODES and
          (not mode.startswith('independent') or role == 'parent'), 'mode_or_role')
    _need((grade_anchor, grouping_anchor, source_filter_anchor) == _anchors(mode, role), 'anchor_capability')
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
        day = day.isoformat() if quality not in {'unknown_basis', 'invalid_date'} else None
        buckets[day, wave, *profiles[i], quality].append(i)
    specs = _specs(role)
    schema, prepared = [], []
    for var in specs:
        available = var.key in dated.columns
        schema.append(dict(variable_id=var.key, kind=var.kind,
                           unit='proportion' if var.kind == 'binary' else 'score', available=available))
        if available:
            values, status = values_and_status(dated, var)
            prepared.append((values.to_numpy(dtype=float, na_value=np.nan), status.eq('outside_report_range').to_numpy()))
        else:
            prepared.append(None)
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
            valid = selected[np.isfinite(selected)]
            n, out = len(valid), int(outside[indices].sum())
            statistics.append([n, out, *moments(valid)] if var.kind == 'continuous'
                              else [n, out, int((valid == 1).sum())])
        cells.append([*key, len(indices), statistics])
    return validate_cube(dict(format=FORMAT, release_id=release_id, mode=mode, role=role,
        grade_anchor=grade_anchor, grouping_anchor=grouping_anchor, source_filter_anchor=source_filter_anchor,
        timezone=TIMEZONE, date_policy=DATE_POLICY, metrics=schema, cell_fields=list(CELL_FIELDS), cells=cells))


def validate_cube(cube):
    """Strict aggregate allowlist; no private row fields can hide in metadata."""
    fields = {'format', 'release_id', 'mode', 'role', 'grade_anchor', 'grouping_anchor',
              'source_filter_anchor', 'timezone', 'date_policy', 'metrics', 'cell_fields', 'cells'}
    _need(isinstance(cube, dict) and set(cube) == fields, 'shape')
    _need(cube['format'] == FORMAT and cube['timezone'] == TIMEZONE and cube['date_policy'] == DATE_POLICY, 'format')
    _need(isinstance(cube['release_id'], str) and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}', cube['release_id']), 'release')
    _need(cube['mode'] in MODES and cube['role'] in {'student', 'parent'} and
          (not cube['mode'].startswith('independent') or cube['role'] == 'parent'), 'mode_or_role')
    _need(tuple(cube[k] for k in ('grade_anchor', 'grouping_anchor', 'source_filter_anchor')) ==
          _anchors(cube['mode'], cube['role']), 'anchors')
    _need(cube['cell_fields'] == CELL_FIELDS and isinstance(cube['cells'], list), 'cell_schema')
    specs = _specs(cube['role'])
    _need(isinstance(cube['metrics'], list) and len(cube['metrics']) == len(specs), 'metric_schema')
    for meta, var in zip(cube['metrics'], specs):
        _need(isinstance(meta, dict) and set(meta) == {'variable_id', 'kind', 'unit', 'available'}, 'metric_shape')
        _need(meta['variable_id'] == var.key and meta['kind'] == var.kind and
              meta['unit'] == ('proportion' if var.kind == 'binary' else 'score') and type(meta['available']) is bool, 'metric_metadata')
    count = lambda n: type(n) is int and 0 <= n <= 2**53-1
    finite = lambda n: type(n) in (int, float) and math.isfinite(n)
    seen = set()
    total = 0
    for cell in cube['cells']:
        _need(isinstance(cell, list) and len(cell) == 10, 'cell_shape')
        day, wave, gender, stage, grade, source, mainstream, quality, size, vectors = cell
        _need(wave in {'T0', 'T1'} and gender in {'0', '1', 'unknown'} and stage in {'primary', 'secondary', 'unknown'}
              and grade in GRADES and source in SOURCES and type(mainstream) is bool and quality in QUALITIES, 'cell_codes')
        _need(count(size) and size > 0, 'cell_count')
        if quality in {'unknown_basis', 'invalid_date'}:
            _need(day is None, 'invalid_quality_date')
        else:
            _need(isinstance(day, str) and re.fullmatch(r'\d{4}-\d{2}-\d{2}', day), 'date')
            try:
                _need(date.fromisoformat(day).isoformat() == day, 'date')
            except ValueError:
                raise PipelineError('Invalid period aggregate: date') from None
        key = tuple(cell[:8])
        _need(key not in seen, 'duplicate_cell')
        seen.add(key); total += size
        _need(count(total), 'count_overflow')
        _need(isinstance(vectors, list) and len(vectors) == len(specs), 'cell_values')
        for vector, meta in zip(vectors, cube['metrics']):
            if not meta['available']:
                _need(vector is None, 'unavailable_metric_values')
                continue
            length = 4 if meta['kind'] == 'continuous' else 3
            _need(isinstance(vector, list) and len(vector) == length, 'statistic_shape')
            n, outside = vector[:2]
            _need(count(n) and count(outside) and n <= size and outside <= size-n, 'statistic_counts')
            if length == 4:
                mean, m2 = vector[2:]
                _need((mean is None if not n else finite(mean)) and finite(m2) and m2 >= 0 and (n > 1 or m2 == 0), 'moments')
            else:
                _need(count(vector[2]) and vector[2] <= n, 'binary_numerator')
    return cube


_CONFIG = dict(format=FORMAT, date_policy=DATE_POLICY, modes=list(MODES), groups=list(GROUPS),
    grades=list(GRADES), sources=list(SOURCES), qualities=QUALITIES, cell_fields=CELL_FIELDS,
    metrics=[dict(variable_id=v.key, kind=v.kind, unit='proportion' if v.kind == 'binary' else 'score') for v in _specs('student')])

JS = r'''
const Period = (()=>{
'use strict';
const C=__CONFIG__, waves=['T0','T1'];
const need=(ok,code)=>{if(!ok)throw Error('Invalid period aggregate: '+code);};
const object=v=>v!==null&&typeof v==='object'&&!Array.isArray(v);
const keys=(v,ks)=>object(v)&&Object.keys(v).length===ks.length&&ks.every(k=>Object.hasOwn(v,k));
const equal=(a,b)=>Array.isArray(a)&&Array.isArray(b)&&a.length===b.length&&a.every((v,i)=>v===b[i]);
const count=n=>Number.isSafeInteger(n)&&n>=0;
const finite=n=>typeof n==='number'&&Number.isFinite(n);
const day=v=>typeof v==='string'&&/^\d{4}-\d{2}-\d{2}$/.test(v)&&Number(v.slice(0,4))>=1&&Number.isFinite(Date.parse(v+'T00:00:00Z'))&&new Date(v+'T00:00:00Z').toISOString().slice(0,10)===v;
function anchors(mode,role){const formal=['acbd','efmatched','independent_child','independent_adult'].includes(mode),ind=mode.startsWith('independent');const g=mode==='abcd'?'wave_response':mode==='ef'?'wave_student':ind?'independent_parent_T0':mode==='efmatched'||role==='student'?'student_T0':'BD_parent_T0';return [(ind?'parent_report_':'student_')+(formal?'T0':'wave'),g,mode==='ef'?'wave_role_response':g];}
function validate(c){
 need(keys(c,['format','release_id','mode','role','grade_anchor','grouping_anchor','source_filter_anchor','timezone','date_policy','metrics','cell_fields','cells']),'shape');
 need(c.format===C.format&&c.timezone==='Asia/Hong_Kong'&&c.date_policy===C.date_policy,'format');
 need(typeof c.release_id==='string'&&/^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$/.test(c.release_id),'release');
 need(C.modes.includes(c.mode)&&['student','parent'].includes(c.role)&&(!c.mode.startsWith('independent')||c.role==='parent'),'mode_or_role');
 need(equal([c.grade_anchor,c.grouping_anchor,c.source_filter_anchor],anchors(c.mode,c.role)),'anchors');
 need(equal(c.cell_fields,C.cell_fields)&&Array.isArray(c.cells),'cell_schema');
 need(Array.isArray(c.metrics)&&c.metrics.length===C.metrics.length,'metric_schema');
 c.metrics.forEach((m,i)=>{need(keys(m,['variable_id','kind','unit','available']),'metric_shape');need(Object.keys(C.metrics[i]).every(k=>m[k]===C.metrics[i][k])&&typeof m.available==='boolean','metric_metadata');});
 const seen=new Set();let total=0;
 c.cells.forEach(cell=>{need(Array.isArray(cell)&&cell.length===10,'cell_shape');const [d,w,g,stage,grade,source,mainstream,q,n,vs]=cell;need(waves.includes(w)&&['0','1','unknown'].includes(g)&&['primary','secondary','unknown'].includes(stage)&&C.grades.includes(grade)&&C.sources.includes(source)&&typeof mainstream==='boolean'&&C.qualities.includes(q),'cell_codes');need(count(n)&&n>0,'cell_count');need(['unknown_basis','invalid_date'].includes(q)?d===null:day(d),'date');const key=JSON.stringify(cell.slice(0,8));need(!seen.has(key),'duplicate_cell');seen.add(key);total+=n;need(count(total),'count_overflow');need(Array.isArray(vs)&&vs.length===c.metrics.length,'cell_values');vs.forEach((v,i)=>{const m=c.metrics[i];if(!m.available){need(v===null,'unavailable_metric_values');return;}need(Array.isArray(v)&&v.length===(m.kind==='continuous'?4:3),'statistic_shape');const [valid,outside]=v;need(count(valid)&&count(outside)&&valid<=n&&outside<=n-valid,'statistic_counts');if(m.kind==='continuous')need((valid?finite(v[2]):v[2]===null)&&finite(v[3])&&v[3]>=0&&(valid>1||v[3]===0),'moments');else need(count(v[2])&&v[2]<=valid,'binary_numerator');});});return true;
}
function selection(c,s){const required=['group','grades','sources','mainstream','include_batch','from','to'];need(object(s)&&required.every(k=>Object.hasOwn(s,k))&&Object.keys(s).every(k=>[...required,'variable_id'].includes(k)),'selection_shape');need(C.groups.includes(s.group)&&typeof s.mainstream==='boolean'&&typeof s.include_batch==='boolean','selection_filters');for(const [k,codes] of [['grades',C.grades],['sources',['all',...C.sources]]])need(Array.isArray(s[k])&&new Set(s[k]).size===s[k].length&&s[k].every(v=>codes.includes(v)),'selection_'+k);need(!s.sources.includes('all')||s.sources.length===1,'selection_sources');need(day(s.from)&&day(s.to)&&s.from<=s.to,'selection_dates');if(Object.hasOwn(s,'variable_id'))need(c.metrics.some(m=>m.variable_id===s.variable_id),'selection_metric');return {group:s.group,grades:C.grades.filter(v=>s.grades.includes(v)),sources:s.sources.includes('all')?['all']:C.sources.filter(v=>s.sources.includes(v)),mainstream:s.mainstream,include_batch:s.include_batch,from:s.from,to:s.to,...(Object.hasOwn(s,'variable_id')?{variable_id:s.variable_id}:{})};}
function bins(from,to){const result=[];let y=Number(from.slice(0,4)),m=Number(from.slice(5,7));while(true){const id=String(y).padStart(4,'0')+'-'+String(m).padStart(2,'0');if(id>to.slice(0,7))break;const leap=y%4===0&&(y%100!==0||y%400===0),last=[31,leap?29:28,31,30,31,30,31,31,30,31,30,31][m-1];const lo=id+'-01',hi=id+'-'+last,cs=lo<from?from:lo,ce=hi>to?to:hi;result.push({period_id:id,period_start:lo,period_end:hi,covered_start:cs,covered_end:ce,partial_period:cs!==lo||ce!==hi});if(m===12){y++;m=1;}else m++;}return result;}
function matches(r,s){const [,,g,stage,grade,source,mainstream]=r;return s.grades.includes(grade)&&(s.sources.includes('all')||s.sources.includes(source))&&(!s.mainstream||mainstream)&&(!s.group.startsWith('male')||g==='0')&&(!s.group.startsWith('female')||g==='1')&&(!s.group.endsWith('primary')||stage==='primary')&&(!s.group.endsWith('secondary')||stage==='secondary');}
const allowed=(q,batch)=>['system_creation','manual_verified'].includes(q)||batch&&q==='batch_assigned_creation';
function empty(c){return {n:0,batch:0,manual:0,v:c.metrics.map(m=>!m.available?null:m.kind==='continuous'?[0,0,null,0]:[0,0,0])};}
function add(a,cell,c){const [,,,,,,,q,size,vs]=cell;a.n+=size;if(q==='batch_assigned_creation')a.batch+=size;if(q==='manual_verified')a.manual+=size;vs.forEach((b,i)=>{if(b===null)return;const v=a.v[i],n=v[0]+b[0];if(c.metrics[i].kind==='continuous'&&b[0]){if(!v[0]){v[2]=b[2];v[3]=b[3];}else{const delta=b[2]-v[2];v[3]+=b[3]+delta*delta*v[0]*b[0]/n;v[2]+=delta*b[0]/n;}need(finite(v[2])&&finite(v[3]),'pooled_moments_overflow');}else if(c.metrics[i].kind==='binary')v[2]+=b[2];v[0]=n;v[1]+=b[1];});}
function rows(c,a,w,s,period={}){return c.metrics.flatMap((m,i)=>{if(s.variable_id&&s.variable_id!==m.variable_id)return [];const v=a.v[i],n=v?.[0]??null,continuous=m.kind==='continuous',proportion=v&&!continuous&&n?v[2]/n:null;return [{...period,wave:w,variable_id:m.variable_id,kind:m.kind,unit:m.unit,available:m.available,sample_n:a.n,valid_n:n,missing_n:v?a.n-n:null,outside_range_n:v?v[1]:null,mean:continuous?(v?v[2]:null):proportion,sd:v&&continuous&&n>1?Math.sqrt(v[3]/(n-1)):null,numerator:v&&!continuous?v[2]:null,denominator:n,proportion}];});}
function query(c,input){validate(c);const s=selection(c,input),cells=c.cells.filter(r=>matches(r,s)),whole={T0:empty(c),T1:empty(c)},bs=bins(s.from,s.to),monthly=new Map(bs.map(p=>[p.period_id,{T0:empty(c),T1:empty(c)}]));const quality={T0:{},T1:{}};waves.forEach(w=>C.qualities.forEach(q=>quality[w][q]={input:0,included:0}));
 cells.forEach(cell=>{const [d,w,,,,,,q,n]=cell;quality[w][q].input+=n;if(!allowed(q,s.include_batch)||d<s.from||d>s.to)return;quality[w][q].included+=n;add(whole[w],cell,c);add(monthly.get(d.slice(0,7))[w],cell,c);});
 const statistics=[],counts=[],date_quality=[],exclusions=[];bs.forEach(p=>waves.forEach(w=>{const a=monthly.get(p.period_id)[w];statistics.push(...rows(c,a,w,s,p));counts.push({...p,wave:w,sample_n:a.n,batch_date_n:a.batch,manual_date_n:a.manual});}));waves.forEach(w=>{const qs=quality[w];C.qualities.forEach(q=>date_quality.push({wave:w,date_quality:q,input_n:qs[q].input,included_n:qs[q].included}));const n=C.qualities.reduce((sum,q)=>sum+qs[q].input,0),valid=n-qs.invalid_date.input-qs.unknown_basis.input,accepted=valid-(s.include_batch?0:qs.batch_assigned_creation.input);let previous=n;[['input',n],['known_dates',valid],['date_source',accepted],['period',whole[w].n]].forEach(([stage,remaining_n])=>{exclusions.push({wave:w,stage,remaining_n,excluded_n:previous-remaining_n});previous=remaining_n;});});
 const metadata={format:c.format,release_id:c.release_id,mode:c.mode,role:c.role,...s,basis:'calendar_response',timezone:c.timezone,date_policy:c.date_policy,grade_anchor:c.grade_anchor,grouping_anchor:c.grouping_anchor,source_filter_anchor:c.source_filter_anchor};return {status:whole.T0.n+whole.T1.n?'available':'empty',whole_period:waves.flatMap(w=>rows(c,whole[w],w,s)),statistics,counts,date_quality,exclusions,metadata};
}
return Object.freeze({FORMAT:C.format,validate,query});})();
'''.replace('__CONFIG__', json.dumps(_CONFIG, ensure_ascii=False, separators=(',', ':')))

JS_SOURCE = JS
