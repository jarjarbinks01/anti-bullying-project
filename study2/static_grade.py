"""Optional aggregate grade capability. Membership and validity stay shared.

Cells cover the Cartesian product of declared groups and 13 grade codes.
An explicit empty cell has null vectors; schemas define its genuine zeros.
No row identity is serialized. The JS below is composed into the existing app.
"""
import math
import numpy as np
import pandas as pd

from .common import PipelineError, plain
from .descriptive_data import attach_measurements
from .descriptive_spec import VERSION, DICTIONARY_VERSION, variables
from .descriptives import group_rows, values_and_status
from .descriptive_exploration import _validate_pairs

FORMAT='study2_descriptive_grade_v1'
CODES=[f'{stage}{n}' for stage in ('P','S') for n in range(1,7)]+['Unknown']
STAT=['sample_n','valid_n','missing_n','outside_range_n','mean','M2','numerator','denominator']
PAIR=['pairs_n','paired_valid_n','paired_missing_n','only_t0_valid_n','only_t1_valid_n','both_missing_n',
      't0_mean','t0_M2','t1_mean','t1_M2','mean_change','delta_M2']
FORMAL={'acbd','efmatched','independent_child','independent_adult'}


def header(release):
    return dict(format=FORMAT,release_id=release,report_version=VERSION,dictionary_version=DICTIONARY_VERSION,
                profile='protected_researcher',minimum_cell_n=0,grade_codes=list(CODES))


def grade_code(row):
    n=row.get('grade');stage=row.get('school_stage')
    if row.get('school_stage_status')!='valid' or stage not in ('primary','secondary'):
        return 'Unknown'
    if isinstance(n,(bool,np.bool_)) or not isinstance(n,(int,float,np.number)) or not np.isfinite(n) or n!=int(n) or not 1<=n<=6:
        return 'Unknown'
    return ('P' if stage=='primary' else 'S')+str(int(n))


def attach_grade(base,frame,measurements,mode,role):
    """Local overlay; unique lookup only, no row expansion or pair selection."""
    out=base.copy();out.attrs=base.attrs.copy()
    independent=mode.startswith('independent')
    baseline=mode in FORMAL
    anchor=('parent_report_' if independent else 'student_')+('T0' if baseline else 'wave')
    if independent or role=='student' and not baseline:
        lookup=base
    elif frame is None or measurements is None:
        out['_grade']='Unknown';return out,None
    else:
        lookup=attach_measurements(frame.loc[frame.role.eq('student')].copy(),measurements)
    if not lookup.empty and not {'grade','school_stage','school_stage_status'}<=set(lookup):
        out['_grade']='Unknown';return out,None
    keys=['child_id'] if baseline else ['child_id','wave']
    # Each independent base is already restricted to one branch by its caller.
    if baseline:lookup=lookup.loc[lookup.wave.eq('T0')]
    duplicates=lookup.duplicated(keys,keep=False)
    codes={tuple(row[k] for k in keys):grade_code(row) for row in lookup.loc[~duplicates].to_dict('records')}
    out['_grade']=[codes.get(tuple(row[k] for k in keys),'Unknown') for row in out.to_dict('records')]
    return out,anchor


def _need(value):
    if not value:raise ValueError('Invalid grade aggregate contract.')


def moments(values):
    a=np.asarray(values,dtype=float)
    if not len(a):return [None,0.]
    if not np.isfinite(a).all():raise PipelineError('Grade moments require finite valid values.')
    mean=float(a.mean());return [mean,float(((a-mean)**2).sum())]


def build_cube(rows,role,view,groups,anchor):
    if anchor is None:return dict(status='unavailable',code='published_grade_fields_unavailable')
    first=next(iter(groups));schema=[]
    keys=['wave','variable_id','variable','section','kind','unit','category_code','category']
    for r in view['statistics']:
        if r['group']==first:schema.append({k:r[k] for k in keys})
    paired=view['mode'] in FORMAL
    # Freeze eligibility from the original whole scope, before partitioning.
    pschema=[{k:r[k] for k in ('variable_id','variable','unit')} for r in view['changes'] if r['group']==first and r.get('pair_detail_status')=='available'] if paired else []
    varmap={v.key:v for v in variables(role)}
    cells=[]
    for group in groups:
        block=group_rows(rows,group)
        waves={w:block.loc[block.wave.eq(w)] for w in ('T0','T1')}
        prepared={}
        for meta in schema:
            key=(meta['wave'],meta['variable_id'])
            if key not in prepared:prepared[key]=values_and_status(waves[meta['wave']],varmap[meta['variable_id']])
        if pschema:
            a,b=_validate_pairs(block)
            if not a['_grade'].reset_index(drop=True).equals(b['_grade'].reset_index(drop=True)):
                raise PipelineError('Formal grade cohort must remain fixed at baseline.')
            pair_values={m['variable_id']:(values_and_status(a,varmap[m['variable_id']])[0],
                values_and_status(b,varmap[m['variable_id']])[0]) for m in pschema}
        for code in CODES:
            counts={w:int(waves[w]._grade.eq(code).sum()) for w in waves}
            cell=dict(group=group,grade_code=code,counts=counts,statistics=None,pairs=None)
            if sum(counts.values()):
                stats=[]
                for meta in schema:
                    wave=meta['wave'];values,status=prepared[(wave,meta['variable_id'])]
                    mask=waves[wave]._grade.eq(code);v=values.loc[mask].dropna();s=status.loc[mask]
                    n=len(v);mean,m2=moments(v) if meta['kind']=='continuous' else (None,None)
                    num=None
                    if meta['kind']!='continuous':
                        category=meta['category_code']
                        num=int(v.eq(1).sum()) if meta['kind']=='binary' else int(v.map(lambda x:category in str(x).split(';')).sum()) if meta['kind']=='multi' else int(v.eq(category).sum())
                    stats.append([counts[wave],n,counts[wave]-n,int(s.eq('outside_report_range').sum()),mean,m2,num,n])
                pairs=[]
                for meta in pschema:
                    av,bv=pair_values[meta['variable_id']];mask=a._grade.eq(code)
                    av,bv=av.loc[mask],bv.loc[mask];va,vb=av.notna(),bv.notna();both=va&vb
                    n=int(both.sum());pairs.append([len(av),n,len(av)-n,int((va&~vb).sum()),int((~va&vb).sum()),int((~va&~vb).sum()),
                        *moments(av.loc[both]),*moments(bv.loc[both]),*moments(bv.loc[both]-av.loc[both])])
                cell.update(statistics=stats,pairs=pairs)
            cells.append(cell)
    return plain(dict(status='available',code=None,anchor=anchor,statistics_schema=schema,pairs_schema=pschema,
        statistic_fields=STAT,pair_fields=PAIR,cells=cells,
        capabilities=dict(wave_statistics=True,paired_summaries=paired,inference=False,monthly_trends=False,distributions=False)))


def table(value):
    return value if isinstance(value,list) else [dict(zip(value['columns'],r)) for r in value['rows']]


def check_moments(rows,n_index,mean_index,m2_index,mean,sd=None):
    n=sum(r[n_index] for r in rows)
    actual=math.fsum(r[n_index]*r[mean_index] for r in rows if r[n_index])/n if n else None
    if n:
        _need(mean is not None and math.isclose(actual,mean,rel_tol=1e-9,abs_tol=1e-9))
        if sd is not None:
            m2=math.fsum(r[m2_index]+r[n_index]*(r[mean_index]-actual)**2 for r in rows if r[n_index])
            _need(math.isclose(m2,(n-1)*sd**2,rel_tol=1e-8,abs_tol=1e-8))
    else:_need(mean is None)


def validate_grade(snapshot):
    present='grade' in snapshot or any('grade' in v for v in snapshot.get('views',[]))
    if not present:return
    if type(snapshot.get('minimum_cell_n')) not in (int,float) or snapshot['minimum_cell_n']!=0 or snapshot.get('small_sample_policy')!='none':raise PipelineError('Grade capability requires the minimum-zero researcher snapshot.')
    if snapshot.get('grade')!=header(snapshot['release_id']) or type(snapshot['grade'].get('minimum_cell_n')) is not int:raise PipelineError('Unsupported grade capability header.')
    for view in snapshot['views']:
        validate_cube(view)


def validate_cube(view):
    cube=view.get('grade')
    if not isinstance(cube,dict):raise PipelineError('Missing grade projection.')
    if cube==dict(status='unavailable',code='published_grade_fields_unavailable'):return
    try:
        _need(set(cube)=={'status','code','anchor','statistics_schema','pairs_schema','statistic_fields','pair_fields','cells','capabilities'})
        _need(cube['status']=='available' and cube['code'] is None and cube['anchor'] in {'student_wave','student_T0','parent_report_wave','parent_report_T0'})
        _need(cube['statistic_fields']==STAT and cube['pair_fields']==PAIR)
        _need(cube['capabilities']==dict(wave_statistics=True,paired_summaries=view['mode'] in FORMAL,inference=False,monthly_trends=False,distributions=False))
        schema=cube['statistics_schema'];pschema=cube['pairs_schema']
        _need(len({(s['wave'],s['variable_id'],s['category_code']) for s in schema})==len(schema))
        _need(len({s['variable_id'] for s in pschema})==len(pschema))
        _need(bool(pschema) is False or view['mode'] in FORMAL)
        _need(all(set(s)=={'wave','variable_id','variable','section','kind','unit','category_code','category'} for s in schema))
        _need(all(set(s)=={'variable_id','variable','unit'} for s in pschema))
        seen=set()
        count=lambda n:type(n) is int and 0<=n<=2**53-1
        moment=lambda n,mean,m2: (type(m2) in (int,float) and math.isfinite(m2) and m2>=0 and
            (mean is None and m2==0 if n==0 else type(mean) in (int,float) and math.isfinite(mean) and (n!=1 or m2==0)))
        for cell in cube['cells']:
            _need(set(cell)=={'group','grade_code','counts','statistics','pairs'})
            key=(cell['group'],cell['grade_code']);_need(key not in seen and key[0] in view['counts'] and key[1] in CODES);seen.add(key)
            counts=cell['counts'];_need(set(counts)=={'T0','T1'} and all(count(v) for v in counts.values()))
            if sum(counts.values())==0:_need(cell['statistics'] is None and cell['pairs'] is None);continue
            _need(len(cell['statistics'])==len(schema) and len(cell['pairs'])==len(pschema))
            for meta,r in zip(schema,cell['statistics']):
                _need(len(r)==len(STAT) and all(count(r[i]) for i in (0,1,2,3,7)))
                _need(r[0]==counts[meta['wave']] and r[0]==r[1]+r[2] and r[3]<=r[2] and r[7]==r[1])
                if meta['kind']=='continuous':_need(r[6] is None and moment(r[1],r[4],r[5]))
                else:_need(r[4] is None and r[5] is None and count(r[6]) and r[6]<=r[7])
            for r in cell['pairs']:
                _need(len(r)==len(PAIR) and all(count(r[i]) for i in range(6)))
                _need(r[0]==counts['T0']==counts['T1'] and r[0]==sum(r[i] for i in (1,3,4,5)) and r[2]==r[0]-r[1])
                _need(all(moment(r[1],r[i],r[i+1]) for i in (6,8,10)))
                _need(not r[1] or math.isclose(r[10],r[8]-r[6],rel_tol=1e-9,abs_tol=1e-9))
        _need(seen=={(g,c) for g in view['counts'] for c in CODES})
        for group,totals in view['counts'].items():
            cells=[c for c in cube['cells'] if c['group']==group]
            _need(all(sum(c['counts'][w] for c in cells)==totals[w] for w in totals))
            # Schemas must match every existing metric, not an attacker-supplied subset.
            expected=[r for r in table(view['statistics']) if r['group']==group]
            _need([(r['wave'],r['variable_id'],r['category_code']) for r in expected]==[(r['wave'],r['variable_id'],r['category_code']) for r in schema])
            _need(all(all(row[k]==meta[k] for k in meta) for row,meta in zip(expected,schema)))
            for j,row in enumerate(expected):
                rs=[c['statistics'][j] for c in cells if c['statistics'] is not None]
                _need(all(sum(r[i] for r in rs)==row[f] for i,f in [(0,'sample_n'),(1,'valid_n'),(2,'missing_n'),(3,'outside_range_n')]))
                if row['kind']!='continuous':_need(sum(r[6] for r in rs)==row['numerator'])
                else:check_moments(rs,1,4,5,row['mean'],row['sd'])
            expected_pairs=[r for r in table(view['changes']) if r['group']==group and r.get('pair_detail_status')=='available'] if view['mode'] in FORMAL else []
            _need([r['variable_id'] for r in expected_pairs]==[r['variable_id'] for r in pschema])
            _need(all(all(row[k]==meta[k] for k in meta) for row,meta in zip(expected_pairs,pschema)))
            for j,row in enumerate(expected_pairs):
                rs=[c['pairs'][j] for c in cells if c['pairs'] is not None]
                _need(all(sum(r[i] for r in rs)==row[f] for i,f in enumerate(PAIR[:6])))
                check_moments(rs,1,6,7,row['t0_mean'])
                check_moments(rs,1,8,9,row['t1_mean'])
                check_moments(rs,1,10,11,row['mean_change'],row['sd_change'])
    except (AssertionError,KeyError,TypeError,ValueError,IndexError) as error:
        raise PipelineError('Invalid, incomplete or unreconciled grade aggregate projection.') from error


JS_SOURCE=r'''
const Grade=(()=>{
const codes=['P1','P2','P3','P4','P5','P6','S1','S2','S3','S4','S5','S6','Unknown'];
const stat=['sample_n','valid_n','missing_n','outside_range_n','mean','M2','numerator','denominator'];
const pair=['pairs_n','paired_valid_n','paired_missing_n','only_t0_valid_n','only_t1_valid_n','both_missing_n','t0_mean','t0_M2','t1_mean','t1_M2','mean_change','delta_M2'];
const keys=(o,w)=>o&&typeof o==='object'&&!Array.isArray(o)&&Object.keys(o).sort().join()===w.slice().sort().join();
const fail=()=>{throw Error('Grade aggregates are missing, incompatible or invalid. Select All grades to use the published aggregate views.');};
function selection(value){if(!Array.isArray(value)||value.some(c=>!codes.includes(c)))fail();return codes.filter(c=>value.includes(c));}
const all=value=>selection(value).length===codes.length;
function moment(rows,nKey,meanKey,m2Key){let n=0,mean=0,m2=0;for(const r of rows){const k=r[nKey];if(!k)continue;const next=n+k,delta=r[meanKey]-mean;m2+=r[m2Key]+delta*delta*n*k/next;mean+=delta*k/next;n=next;}return {n,mean:n?mean:null,sd:n>1?Math.sqrt(m2/(n-1)):null};}
const unpack=(r,fields)=>Object.fromEntries(fields.map((k,i)=>[k,r[i]]));
function agree(rows,n,a,b,mean,sd){const m=moment(rows,n,a,b);if(m.n? !Number.isFinite(mean)||Math.abs(m.mean-mean)>1e-8*Math.max(1,Math.abs(mean)):mean!==null)fail();if(sd!==null&&sd!==undefined&&m.n>1&&Math.abs(m.sd-sd)>1e-8*Math.max(1,Math.abs(sd)))fail();}
function validate(S,v){
 const h=S.grade,c=v.grade;if(S.minimum_cell_n!==0||S.small_sample_policy!=='none'||!h||h.format!=='study2_descriptive_grade_v1'||h.profile!=='protected_researcher'||h.minimum_cell_n!==0||h.release_id!==S.release_id||h.report_version!==S.report_version||h.dictionary_version!==S.dictionary_version||JSON.stringify(h.grade_codes)!==JSON.stringify(codes))fail();
 if(!c||c.status!=='available'||!['student_wave','student_T0','parent_report_wave','parent_report_T0'].includes(c.anchor)||JSON.stringify(c.statistic_fields)!==JSON.stringify(stat)||JSON.stringify(c.pair_fields)!==JSON.stringify(pair))fail();
 const formal=['acbd','efmatched','independent_child','independent_adult'].includes(v.mode);
 const caps={wave_statistics:true,paired_summaries:formal,inference:false,monthly_trends:false,distributions:false};if(!c.capabilities||Object.keys(c.capabilities).length!==Object.keys(caps).length||Object.entries(caps).some(([k,v])=>c.capabilities[k]!==v))fail();
 if(!keys(h,['format','release_id','report_version','dictionary_version','profile','minimum_cell_n','grade_codes'])||!keys(c,['status','code','anchor','statistics_schema','pairs_schema','statistic_fields','pair_fields','cells','capabilities'])||c.code!==null)fail();
 const count=x=>Number.isSafeInteger(x)&&x>=0,mom=(n,a,b)=>Number.isFinite(b)&&b>=0&&(n===0?a===null&&b===0:Number.isFinite(a)&&(n!==1||b===0));
 const seen=new Set(),groups=Object.keys(v.counts),ss=c.statistics_schema,ps=c.pairs_schema;
 if(new Set(ss.map(r=>JSON.stringify([r.wave,r.variable_id,r.category_code]))).size!==ss.length||new Set(ps.map(r=>r.variable_id)).size!==ps.length||!formal&&ps.length)fail();
 if(ss.some(x=>!keys(x,['wave','variable_id','variable','section','kind','unit','category_code','category']))||ps.some(x=>!keys(x,['variable_id','variable','unit'])))fail();
 for(const cell of c.cells){if(!keys(cell,['group','grade_code','counts','statistics','pairs']))fail();const key=JSON.stringify([cell.group,cell.grade_code]);if(seen.has(key)||!groups.includes(cell.group)||!codes.includes(cell.grade_code)||Object.keys(cell.counts).sort().join()!=='T0,T1'||!Object.values(cell.counts).every(count))fail();seen.add(key);
  if(!cell.counts.T0&&!cell.counts.T1){if(cell.statistics!==null||cell.pairs!==null)fail();continue;}
  if(!Array.isArray(cell.statistics)||cell.statistics.length!==ss.length||!Array.isArray(cell.pairs)||cell.pairs.length!==ps.length)fail();
  cell.statistics.forEach((r,i)=>{const m=ss[i];if(r.length!==stat.length||![0,1,2,3,7].every(k=>count(r[k]))||r[0]!==cell.counts[m.wave]||r[0]!==r[1]+r[2]||r[3]>r[2]||r[7]!==r[1]||(m.kind==='continuous'?r[6]!==null||!mom(r[1],r[4],r[5]):r[4]!==null||r[5]!==null||!count(r[6])||r[6]>r[7]))fail();});
  cell.pairs.forEach(r=>{if(r.length!==pair.length||![0,1,2,3,4,5].every(k=>count(r[k]))||r[0]!==cell.counts.T0||r[0]!==cell.counts.T1||r[0]!==r[1]+r[3]+r[4]+r[5]||r[2]!==r[0]-r[1]||![6,8,10].every(k=>mom(r[1],r[k],r[k+1]))||r[1]&&Math.abs(r[10]-(r[8]-r[6]))>1e-8)fail();});
 }
 if(seen.size!==groups.length*codes.length)fail();
 for(const g of groups){const cells=c.cells.filter(x=>x.group===g);for(const w of ['T0','T1'])if(cells.reduce((n,x)=>n+x.counts[w],0)!==v.counts[g][w])fail();
  const expected=v.statistics.filter(x=>x.group===g);if(JSON.stringify(expected.map(x=>[x.wave,x.variable_id,x.category_code]))!==JSON.stringify(ss.map(x=>[x.wave,x.variable_id,x.category_code])))fail();
  expected.forEach((r,i)=>{if(Object.keys(ss[i]).some(k=>ss[i][k]!==r[k]))fail();for(const k of [0,1,2,3])if(cells.reduce((n,x)=>n+(x.statistics?.[i]?.[k]||0),0)!==r[stat[k]])fail();if(r.kind!=='continuous'&&cells.reduce((n,x)=>n+(x.statistics?.[i]?.[6]||0),0)!==r.numerator)fail();if(r.kind==='continuous')agree(cells.filter(x=>x.statistics).map(x=>unpack(x.statistics[i],stat)),'valid_n','mean','M2',r.mean,r.sd);});
  const pairs=formal?v.changes.filter(x=>x.group===g&&x.pair_detail_status==='available'):[];if(JSON.stringify(pairs.map(x=>x.variable_id))!==JSON.stringify(ps.map(x=>x.variable_id)))fail();pairs.forEach((r,i)=>{if(Object.keys(ps[i]).some(k=>ps[i][k]!==r[k]))fail();for(let k=0;k<6;k++)if(cells.reduce((n,x)=>n+(x.pairs?.[i]?.[k]||0),0)!==r[pair[k]])fail();const rows=cells.filter(x=>x.pairs).map(x=>unpack(x.pairs[i],pair));agree(rows,'paired_valid_n','t0_mean','t0_M2',r.t0_mean);agree(rows,'paired_valid_n','t1_mean','t1_M2',r.t1_mean);agree(rows,'paired_valid_n','mean_change','delta_M2',r.mean_change,r.sd_change);});
 }
 return c;
}
function withWaveSD(S,v){
 if(!['acbd','efmatched','independent_child','independent_adult'].includes(v.mode))return v;
 const out={...v,changes:v.changes.map(r=>({...r,t0_sd:null,t1_sd:null}))};
 try{
  const c=validate(S,v),expectedAnchor=v.mode.startsWith('independent_')?'parent_report_T0':'student_T0';
  if(c.anchor!==expectedAnchor)return out;
  const near=(a,b)=>a===null?b===null:Number.isFinite(b)&&Math.abs(a-b)<=64*Number.EPSILON*Math.max(1,Math.abs(a),Math.abs(b));
  out.changes=out.changes.map(r=>{
   if(r.suppressed||r.pair_detail_status!=='available')return r;
   const i=c.pairs_schema.findIndex(m=>m.variable_id===r.variable_id);
   if(i<0||Object.keys(c.pairs_schema[i]).some(k=>c.pairs_schema[i][k]!==r[k]))return r;
   const rows=c.cells.filter(x=>x.group===r.group&&x.pairs!==null).map(x=>unpack(x.pairs[i],pair));
   if(pair.slice(0,6).some(k=>rows.reduce((n,x)=>n+x[k],0)!==r[k]))return r;
   const a=moment(rows,'paired_valid_n','t0_mean','t0_M2'),b=moment(rows,'paired_valid_n','t1_mean','t1_M2'),d=moment(rows,'paired_valid_n','mean_change','delta_M2');
   if(a.n!==r.paired_valid_n||b.n!==a.n||d.n!==a.n||!near(a.mean,r.t0_mean)||!near(b.mean,r.t1_mean)||!near(d.mean,r.mean_change))return r;
   if(a.n<2||!Number.isFinite(a.sd)||!Number.isFinite(b.sd))return r;
   return {...r,t0_sd:a.sd,t1_sd:b.sd};
  });
 }catch(error){/* Optional moments must never hide the original stored summary. */}
 return out;
}
function pool(S,v,chosen,options={}){const selected=selection(chosen),c=validate(S,v),sdAnchor=c.anchor===(v.mode.startsWith('independent_')?'parent_report_T0':'student_T0'),out={...v,statistics:[],changes:[],counts:{},grade_custom:true,grade_anchor:c.anchor};
 delete out.histograms;delete out.paired_histograms;delete out.transitions;delete out.trends;
 for(const g of Object.keys(v.counts)){const cells=c.cells.filter(x=>x.group===g&&selected.includes(x.grade_code));out.counts[g]=Object.fromEntries(['T0','T1'].map(w=>[w,cells.reduce((n,x)=>n+x.counts[w],0)]));
  c.statistics_schema.forEach((m,i)=>{const rows=cells.filter(x=>x.statistics!==null).map(x=>unpack(x.statistics[i],stat));const sum=k=>rows.reduce((n,r)=>n+r[k],0);const mm=moment(rows,'valid_n','mean','M2');const denominator=sum('denominator'),numerator=m.kind==='continuous'?null:sum('numerator');out.statistics.push({...m,group:g,sample_n:sum('sample_n'),valid_n:sum('valid_n'),missing_n:sum('missing_n'),outside_range_n:sum('outside_range_n'),mean:m.kind==='continuous'?mm.mean:null,sd:m.kind==='continuous'?mm.sd:null,numerator,denominator,proportion:numerator!==null&&denominator?numerator/denominator:null,suppressed:false});});
  c.pairs_schema.forEach((m,i)=>{const rows=cells.filter(x=>x.pairs!==null).map(x=>unpack(x.pairs[i],pair));const sums=Object.fromEntries(pair.slice(0,6).map(k=>[k,rows.reduce((n,r)=>n+r[k],0)]));const a=moment(rows,'paired_valid_n','t0_mean','t0_M2'),b=moment(rows,'paired_valid_n','t1_mean','t1_M2'),d=moment(rows,'paired_valid_n','mean_change','delta_M2');out.changes.push({...m,...sums,group:g,t0_mean:a.mean,t1_mean:b.mean,mean_change:d.mean,sd_change:d.sd,p_value:null,cohen_dz:null,inference_status:'custom_grade_inference_unavailable',pair_detail_status:'available',suppressed:false,...(options.wave_sd===true?{t0_sd:sdAnchor&&Number.isFinite(a.sd)&&Number.isFinite(b.sd)?a.sd:null,t1_sd:sdAnchor&&Number.isFinite(a.sd)&&Number.isFinite(b.sd)?b.sd:null}:{})});});
 }return out;
}
return Object.freeze({codes,selection,all,pool,validate,moment,withWaveSD});})();
'''
