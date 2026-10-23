"""Source unions over disjoint published moments, never research reselection.

Overview pairing needs two displayed source anchors. Its matrix contains only
aggregates of the existing exact formal slots. IDs exist only during construction.
"""
import math

import pandas as pd

from .common import PipelineError, plain
from .descriptive_spec import VERSION, DICTIONARY_VERSION, variables
from .descriptives import adult_continuity_confirmed, group_rows, values_and_status
from .descriptive_exploration import _validate_pairs
from .static_grade import PAIR, check_moments, moments, table, validate_cube

FORMAT = 'study2_descriptive_sources_v1'
CODES = ('legacy_online', 'paperform', 'qualtrics', 'school_batch', 'socialworkdream')
PARTITIONS = (*CODES, 'unknown')
OVERVIEW = {'abcd', 'ef', 'independent_all'}


def source_code(value):
    return value if isinstance(value, str) and value in CODES else 'unknown'


def header(release, views):
    return dict(format=FORMAT, release_id=release, report_version=VERSION,
                dictionary_version=DICTIONARY_VERSION, profile='protected_researcher',
                minimum_cell_n=0, source_codes=list(CODES),
                residual_present=any(v['source'] == 'unknown' for v in views))


def pair_vector(a, b):
    va, vb = a.notna(), b.notna()
    both = va & vb
    n = int(both.sum())
    return [len(a), n, len(a)-n, int((va & ~vb).sum()), int((~va & vb).sum()),
            int((~va & ~vb).sum()), *moments(a.loc[both]), *moments(b.loc[both]),
            *moments(b.loc[both]-a.loc[both])]


def build_pairs(selected, reference, role, groups, source_codes=CODES):
    """Keep dangling reference rows for eligibility, complete slots for moments.

The source comes from the displayed row, not the formal baseline anchor. The
adult gate runs before cell partitioning, including a visible dangling slot.
An unconfirmed source cannot publish adult PHQ paired moments through a cell.
"""
    specs = [v for v in variables(role, 'scales') if v.kind == 'continuous']
    schema = [dict(variable_id=v.key, variable=v.label, unit=v.unit) for v in specs]
    out = []
    for group in groups:
        visible = group_rows(selected, group)
        ids = ['submission_id', 'version_id']
        if visible.duplicated(ids).any():
            raise PipelineError('Source pair projection requires unique displayed slots.')
        lookup = {tuple(r[k] for k in ids): source_code(r['anchor_source_type'])
                  for r in visible.to_dict('records')}
        mask = pd.MultiIndex.from_frame(reference[ids]).isin(pd.MultiIndex.from_frame(visible[ids]))
        matched = reference.loc[mask].copy()
        matched.attrs = reference.attrs.copy()
        matched['_display_source'] = [lookup[tuple(r[k] for k in ids)] for r in matched.to_dict('records')]
        eligibility = {}
        for code in source_codes:
            block = matched.loc[matched['_display_source'].eq(code)]
            eligibility[code] = dict(matched_n=len(block), adult_confirmed=adult_continuity_confirmed(block))
        first = set(matched.loc[matched.wave.eq('T0'), 'child_id'])
        last = set(matched.loc[matched.wave.eq('T1'), 'child_id'])
        complete = matched.loc[matched.child_id.isin(first & last)].copy()
        a, b = _validate_pairs(complete)
        prepared = {v.key: (values_and_status(a, v)[0], values_and_status(b, v)[0]) for v in specs}
        cells = []
        for t0 in source_codes:
            for t1 in source_codes:
                take = a['_display_source'].eq(t0) & b['_display_source'].eq(t1)
                size = int(take.sum())
                pairs = None
                if size:
                    pairs = []
                    for v in specs:
                        permitted = role != 'parent' or not v.key.startswith('PHQ_') or (
                            eligibility[t0]['adult_confirmed'] and eligibility[t1]['adult_confirmed'])
                        av, bv = prepared[v.key]
                        pairs.append(pair_vector(av.loc[take], bv.loc[take]) if permitted else None)
                cells.append(dict(t0_source=t0, t1_source=t1, pairs_n=size, pairs=pairs))
        out.append(dict(group=group, pairs_schema=schema,
                        detail_variables=[v.key for v in specs if v.key in reference.columns],
                        source_eligibility=eligibility, cells=cells))
    return plain(dict(status='available', source_codes=list(source_codes), pair_fields=PAIR, groups=out))


def _need(ok):
    if not ok:
        raise ValueError('Invalid source aggregates.')


def _check_vector(row, size):
    count = lambda x: type(x) is int and 0 <= x <= 2**53-1
    _need(isinstance(row, list) and len(row) == len(PAIR) and all(count(x) for x in row[:6]))
    _need(row[0] == size and row[0] == row[1]+row[3]+row[4]+row[5] and row[2] == size-row[1])
    for i in (6, 8, 10):
        mean, m2 = row[i:i+2]
        _need(type(m2) in (int, float) and math.isfinite(m2) and m2 >= 0)
        _need((mean is None and m2 == 0) if row[1] == 0 else
              type(mean) in (int, float) and math.isfinite(mean) and (row[1] != 1 or m2 == 0))
    _need(not row[1] or math.isclose(row[10], row[8]-row[6], rel_tol=1e-9, abs_tol=1e-9))


def _reconcile_pairs(rows, expected):
    for i, key in enumerate(PAIR[:6]):
        _need(sum(r[i] for r in rows) == expected[key])
    check_moments(rows, 1, 6, 7, expected['t0_mean'])
    check_moments(rows, 1, 8, 9, expected['t1_mean'])
    check_moments(rows, 1, 10, 11, expected['mean_change'], expected['sd_change'])


def _reconcile_statistics(all_view, partitions):
    """Individual valid cubes do not prove their union equals the All view."""
    schema = ['wave', 'group', 'variable_id', 'variable', 'section', 'kind', 'unit', 'category_code', 'category']
    expected = table(all_view['statistics'])
    blocks = [table(p['statistics']) for p in partitions.values()]
    _need(all(len(b) == len(expected) for b in blocks))
    for i, target in enumerate(expected):
        rs = [b[i] for b in blocks]
        _need(all(all(r[k] == target[k] for k in schema) for r in rs))
        _need(all(sum(r[k] for r in rs) == target[k] for k in
                  ['sample_n', 'valid_n', 'missing_n', 'outside_range_n', 'denominator']))
        if target['kind'] == 'continuous':
            for row in [target, *rs]:
                n = row['valid_n']
                _need((row['mean'] is None) if n == 0 else
                      type(row['mean']) in (int, float) and math.isfinite(row['mean']))
                _need((row['sd'] is None) if n <= 1 else
                      type(row['sd']) in (int, float) and math.isfinite(row['sd']) and row['sd'] >= 0)
            ms = [[r['valid_n'], r['mean'], (r['valid_n']-1)*r['sd']**2 if r['valid_n'] > 1 else 0.] for r in rs]
            check_moments(ms, 0, 1, 2, target['mean'], target['sd'])
        else:
            _need(sum(r['numerator'] for r in rs) == target['numerator'])


def validate_pairs(view, partitions):
    cube = view['source_pairs']
    codes = tuple(partitions)
    _need(set(cube) == {'status', 'source_codes', 'pair_fields', 'groups'})
    _need(cube['status'] == 'available' and cube['source_codes'] == list(codes) and cube['pair_fields'] == PAIR)
    _need([g['group'] for g in cube['groups']] == list(view['counts']))
    for block in cube['groups']:
        _need(set(block) == {'group', 'pairs_schema', 'detail_variables', 'source_eligibility', 'cells'})
        group = block['group']; schema = block['pairs_schema']; gates = block['source_eligibility']
        _need(set(gates) == set(codes))
        for code, gate in gates.items():
            _need(set(gate) == {'matched_n', 'adult_confirmed'} and type(gate['matched_n']) is int and gate['matched_n'] >= 0)
            _need(type(gate['adult_confirmed']) is bool and (not gate['adult_confirmed'] or gate['matched_n'] > 0))
            _need(gate['matched_n'] <= sum(partitions[code]['counts'][group].values()))
        specs = [v for v in variables(view['role'], 'scales') if v.kind == 'continuous']
        _need([m['variable_id'] for m in schema] == [v.key for v in specs])
        _need(all(set(m) == {'variable_id', 'variable', 'unit'} for m in schema))
        detail = block['detail_variables']
        _need(isinstance(detail, list) and len(set(detail)) == len(detail) and
              detail == [v.key for v in specs if v.key in detail])
        seen = set()
        for cell in block['cells']:
            _need(set(cell) == {'t0_source', 't1_source', 'pairs_n', 'pairs'})
            key = (cell['t0_source'], cell['t1_source'])
            _need(key not in seen and all(c in codes for c in key)); seen.add(key)
            n = cell['pairs_n']; _need(type(n) is int and n >= 0)
            if not n:
                _need(cell['pairs'] is None); continue
            _need(len(cell['pairs']) == len(schema))
            for meta, row in zip(schema, cell['pairs']):
                allowed = view['role'] != 'parent' or not meta['variable_id'].startswith('PHQ_') or all(gates[c]['adult_confirmed'] for c in key)
                if allowed: _check_vector(row, n)
                else: _need(row is None)
        _need(seen == {(a, b) for a in codes for b in codes})
        for code in codes:
            for wave, field in [('T0', 't0_source'), ('T1', 't1_source')]:
                n = sum(c['pairs_n'] for c in block['cells'] if c[field] == code)
                _need(n <= partitions[code]['counts'][group][wave] and n <= gates[code]['matched_n'])
        for source, target in [('all', view), *partitions.items()]:
            nonempty = [c for c in codes if gates[c]['matched_n']] if source == 'all' else ([source] if gates[source]['matched_n'] else [])
            allowed = [m for m in schema if view['role'] != 'parent' or not m['variable_id'].startswith('PHQ_') or
                       bool(nonempty) and all(gates[c]['adult_confirmed'] for c in nonempty)]
            expected = [r for r in table(target['changes']) if r['group'] == group]
            _need([m['variable_id'] for m in allowed] == [r['variable_id'] for r in expected])
            for meta, row in zip(allowed, expected):
                _need(all(meta[k] == row[k] for k in meta))
                j = schema.index(meta)
                cells = block['cells'] if source == 'all' else [c for c in block['cells'] if c['t0_source'] == source == c['t1_source']]
                rs = [c['pairs'][j] for c in cells if c['pairs_n']]
                _need(all(r is not None for r in rs))
                if row.get('pair_detail_status') == 'available':
                    _need(meta['variable_id'] in detail)
                    _reconcile_pairs(rs, row)
                else:
                    # Missing published score columns and an empty complete
                    # adult cohort retain original absent exploration detail.
                    empty_phq = view['role'] == 'parent' and meta['variable_id'].startswith('PHQ_') and row['pairs_n'] == 0
                    _need(row.get('pair_detail_status') == 'not_provided' and
                          (meta['variable_id'] not in detail or empty_phq))
                    _need(all(sum(r[i] for r in rs) == row[PAIR[i]] for i in range(3)))
                    _need(row['paired_valid_n'] == 0 and row['mean_change'] is None and row['sd_change'] is None)
                    _need(all(row[k] is None for k in ['only_t0_valid_n', 'only_t1_valid_n', 'both_missing_n', 't0_mean', 't1_mean']))


def validate_sources(snapshot):
    if 'source_selection' not in snapshot:
        if any('source_pairs' in v for v in snapshot.get('views', [])):
            raise PipelineError('Source pair projection requires its pinned header.')
        return
    try:
        _need(snapshot['minimum_cell_n'] == 0 and type(snapshot['minimum_cell_n']) is int and snapshot['small_sample_policy'] == 'none')
        _need(snapshot['source_selection'] == header(snapshot['release_id'], snapshot['views']))
        _need(type(snapshot['source_selection']['residual_present']) is bool and type(snapshot['source_selection']['minimum_cell_n']) is int)
        scopes = {}
        for view in snapshot['views']:
            key = (view['mode'], view['role'], view['mainstream'])
            group = scopes.setdefault(key, {})
            _need(view['source'] in ('all', *PARTITIONS) and view['source'] not in group)
            group[view['source']] = view
        for scope in scopes.values():
            codes = PARTITIONS if snapshot['source_selection']['residual_present'] else CODES
            _need(set(scope) == {'all', *codes})
            all_view = scope['all']; parts = {c: scope[c] for c in codes}
            for v in scope.values():
                validate_cube(v)
                _need(v['grouping_anchor'] == all_view['grouping_anchor'] and v['source_filter_anchor'] == all_view['source_filter_anchor'])
                _need(set(v['counts']) == set(all_view['counts']))
                _need(all(set(c) == {'T0', 'T1'} and all(type(n) is int and 0 <= n <= 2**53-1
                          for n in c.values()) for c in v['counts'].values()))
            for g, counts in all_view['counts'].items():
                _need(all(sum(p['counts'][g][w] for p in parts.values()) == counts[w] for w in ('T0', 'T1')))
            _reconcile_statistics(all_view, parts)
            if all_view['mode'] in OVERVIEW:
                if 'source_pairs' in all_view:
                    validate_pairs(all_view, parts)
                else:
                    # No dedicated BD artifact means there is no formal parent
                    # reference to project. Wave summaries remain usable.
                    _need(not table(all_view['changes']))
            else:
                _need('source_pairs' not in all_view)
            _need(all('source_pairs' not in v for v in parts.values()))
    except (KeyError, TypeError, ValueError, IndexError) as error:
        raise PipelineError('Invalid, incomplete or unreconciled source projection.') from error


JS_SOURCE = r'''
const Source=(()=>{
const codes=Object.freeze(['legacy_online','paperform','qualtrics','school_batch','socialworkdream']);
const parts=[...codes,'unknown'],formal=['acbd','efmatched','independent_child','independent_adult'];
const labels={all:'All sources',legacy_online:'Legacy online',paperform:'Paperform',qualtrics:'Qualtrics',school_batch:'School batch',socialworkdream:'Social Work Dream',unknown:'Other / unidentified'};
const stat=['sample_n','valid_n','missing_n','outside_range_n','mean','M2','numerator','denominator'];
const pair=['pairs_n','paired_valid_n','paired_missing_n','only_t0_valid_n','only_t1_valid_n','both_missing_n','t0_mean','t0_M2','t1_mean','t1_M2','mean_change','delta_M2'];
const equal=(a,b)=>JSON.stringify(a)===JSON.stringify(b),keys=(o,k)=>o&&typeof o==='object'&&!Array.isArray(o)&&equal(Object.keys(o).sort(),k.slice().sort());
const fail=()=>{throw Error('Invalid or unavailable source aggregate contract.');};
const table=x=>Array.isArray(x)?x:x&&Array.isArray(x.columns)&&Array.isArray(x.rows)?x.rows.map(r=>Object.fromEntries(x.columns.map((k,i)=>[k,r[i]]))):fail();
function decode(v){const out={...v};for(const k of ['statistics','changes','histograms','paired_histograms','transitions'])if(k in v)out[k]=table(v[k]);if('trends' in v)out.trends=v.trends.map(p=>({...p,statistics:table(p.statistics)}));return out;}
function options(S){return (S.source_selection?.residual_present===true?parts:codes).map(code=>({code,label:labels[code]}));}
function selection(S,v){if(!Array.isArray(v)||new Set(v).size!==v.length||v.some(c=>typeof c!=='string'||!['all',...options(S).map(x=>x.code)].includes(c))||v.includes('all')&&v.length!==1)fail();return v.includes('all')?['all']:parts.filter(c=>v.includes(c));}
const unpack=(r,fields)=>Object.fromEntries(fields.map((k,i)=>[k,r[i]]));
function vector(rows,fields){const out=fields.map(()=>0),p=fields===pair,n=p?'paired_valid_n':'valid_n';
 const rs=rows.map(r=>unpack(r,fields)),sum=k=>rs.reduce((a,r)=>a+r[k],0);
 for(let i=0;i<(p?6:4);i++)out[i]=sum(fields[i]);
 for(const [mi,m2i] of p?[[6,7],[8,9],[10,11]]:[[4,5]]){if(!p&&rows.length&&rows[0][5]===null){out[mi]=out[m2i]=null;continue;}const m=Grade.moment(rs,n,fields[mi],fields[m2i]);out[mi]=m.mean;out[m2i]=m.n>1?m.sd*m.sd*(m.n-1):0;}
 if(!p){out[6]=rows.length&&rows[0][6]===null?null:sum('numerator');out[7]=sum('denominator');}return out;
}
function statsFrom(meta,rows,g){const r=unpack(vector(rows,stat),stat);return {...meta,group:g,sample_n:r.sample_n,valid_n:r.valid_n,missing_n:r.missing_n,outside_range_n:r.outside_range_n,mean:meta.kind==='continuous'?r.mean:null,sd:meta.kind==='continuous'&&r.valid_n>1?Math.sqrt(r.M2/(r.valid_n-1)):null,numerator:meta.kind==='continuous'?null:r.numerator,denominator:r.denominator,proportion:meta.kind!=='continuous'&&r.denominator?r.numerator/r.denominator:null,suppressed:false};}
function pairFrom(meta,rows,g,waveSD=false,sdCompatible=true){const r=unpack(vector(rows,pair),pair),finiteWaveM2=Number.isFinite(r.t0_M2)&&Number.isFinite(r.t1_M2);return {...meta,group:g,...Object.fromEntries(pair.slice(0,6).map(k=>[k,r[k]])),t0_mean:r.t0_mean,t1_mean:r.t1_mean,mean_change:r.mean_change,sd_change:r.paired_valid_n>1?Math.sqrt(r.delta_M2/(r.paired_valid_n-1)):null,p_value:null,cohen_dz:null,inference_status:'custom_source_inference_unavailable',pair_detail_status:'available',suppressed:false,...(waveSD?{t0_sd:sdCompatible&&finiteWaveM2&&r.paired_valid_n>1?Math.sqrt(r.t0_M2/(r.paired_valid_n-1)):null,t1_sd:sdCompatible&&finiteWaveM2&&r.paired_valid_n>1?Math.sqrt(r.t1_M2/(r.paired_valid_n-1)):null}:{})};}
function strip(v){const out={...v};for(const k of ['histograms','paired_histograms','transitions','trends','source_pairs','grade'])delete out[k];return out;}
function caps(v){
 // Stored paired summaries predate optional complete-pair detail fields.
 // Expose only the existing rows; this does not fill detail or authorize unions.
 const hasSummary=v.changes.length>0;
 return {statistics:true,paired_summaries:hasSummary,inference:!v.grade_custom&&hasSummary,distributions:!v.grade_custom&&Array.isArray(v.histograms),monthly_trends:!v.grade_custom&&Array.isArray(v.trends)};
}
function mark(v,selected,status,cap,notice='',error){return {...v,source_status:status,source_selection:selected,source_labels:selected.map(c=>labels[c]),source_custom:status==='pooled',source_capabilities:cap,source_notice:notice,...(error?{source_error:error}:{})};}
function absent(v,selected,status,error){const zero=status==='empty';return mark({...strip(v),source:'multiple',counts:Object.fromEntries(Object.keys(v.counts).map(g=>[g,{T0:zero?0:null,T1:zero?0:null}])),statistics:[],changes:[]},selected,status,{statistics:false,paired_summaries:false,inference:false,distributions:false,monthly_trends:false},zero?'No sources selected.':'This source combination is unavailable in this snapshot.',error);}
function find(S,c,source){const vs=S.views.filter(v=>v.mode===c.mode&&v.role===c.role&&v.mainstream===c.mainstream&&v.source===source);if(vs.length!==1)fail();return decode(vs[0]);}
function header(S){const h=S.source_selection;if(!keys(h,['format','release_id','report_version','dictionary_version','profile','minimum_cell_n','source_codes','residual_present'])||h.format!=='study2_descriptive_sources_v1'||h.release_id!==S.release_id||h.report_version!==S.report_version||h.dictionary_version!==S.dictionary_version||h.profile!=='protected_researcher'||h.minimum_cell_n!==0||S.minimum_cell_n!==0||S.small_sample_policy!=='none'||!equal(h.source_codes,codes)||typeof h.residual_present!=='boolean')fail();}
function agree(rows,expected){for(let k=0;k<6;k++)if(rows.reduce((n,r)=>n+r[k],0)!==expected[pair[k]])fail();for(const [n,a,b] of [['paired_valid_n','t0_mean','t0_M2'],['paired_valid_n','t1_mean','t1_M2'],['paired_valid_n','mean_change','delta_M2']]){const m=Grade.moment(rows.map(r=>unpack(r,pair)),n,a,b);if(m.n? !Number.isFinite(expected[a])||Math.abs(m.mean-expected[a])>1e-8*Math.max(1,Math.abs(expected[a])):expected[a]!==null)fail();if(a==='mean_change'&&m.n>1&&(!Number.isFinite(expected.sd_change)||Math.abs(m.sd-expected.sd_change)>1e-8*Math.max(1,Math.abs(expected.sd_change))))fail();}}
function validatePairs(v,ps){const active=Object.keys(ps),c=v.source_pairs;if(!keys(c,['status','source_codes','pair_fields','groups'])||c.status!=='available'||!equal(c.source_codes,active)||!equal(c.pair_fields,pair)||!equal(c.groups.map(x=>x.group),Object.keys(v.counts)))fail();
 const count=x=>Number.isSafeInteger(x)&&x>=0,mom=(n,a,b)=>Number.isFinite(b)&&b>=0&&(n===0?a===null&&b===0:Number.isFinite(a)&&(n!==1||b===0));
 const expectedSchema=v.grade.statistics_schema.filter(x=>x.wave==='T0'&&x.kind==='continuous'&&x.section==='scales').map(x=>x.variable_id);
 for(const g of c.groups){if(!equal(g.pairs_schema.map(x=>x.variable_id),expectedSchema))fail();if(!keys(g,['group','pairs_schema','detail_variables','source_eligibility','cells'])||!keys(g.source_eligibility,active)||new Set(g.pairs_schema.map(m=>m.variable_id)).size!==g.pairs_schema.length||g.pairs_schema.some(m=>!keys(m,['variable_id','variable','unit'])))fail();
  for(const s of active){const e=g.source_eligibility[s];if(!keys(e,['matched_n','adult_confirmed'])||!count(e.matched_n)||typeof e.adult_confirmed!=='boolean'||e.adult_confirmed&&!e.matched_n||e.matched_n>ps[s].counts[g.group].T0+ps[s].counts[g.group].T1)fail();}
  if(!Array.isArray(g.detail_variables)||new Set(g.detail_variables).size!==g.detail_variables.length||!equal(g.detail_variables,g.pairs_schema.filter(m=>g.detail_variables.includes(m.variable_id)).map(m=>m.variable_id)))fail();
  const seen=new Set();for(const cell of g.cells){if(!keys(cell,['t0_source','t1_source','pairs_n','pairs'])||!active.includes(cell.t0_source)||!active.includes(cell.t1_source)||!count(cell.pairs_n))fail();const key=JSON.stringify([cell.t0_source,cell.t1_source]);if(seen.has(key))fail();seen.add(key);if(!cell.pairs_n){if(cell.pairs!==null)fail();continue;}if(!Array.isArray(cell.pairs)||cell.pairs.length!==g.pairs_schema.length)fail();cell.pairs.forEach((r,i)=>{const ok=v.role!=='parent'||!g.pairs_schema[i].variable_id.startsWith('PHQ_')||[cell.t0_source,cell.t1_source].every(s=>g.source_eligibility[s].adult_confirmed);if(!ok){if(r!==null)fail();return;}if(!Array.isArray(r)||r.length!==12||!r.slice(0,6).every(count)||r[0]!==cell.pairs_n||r[0]!==r[1]+r[3]+r[4]+r[5]||r[2]!==r[0]-r[1]||![6,8,10].every(k=>mom(r[1],r[k],r[k+1]))||r[1]&&Math.abs(r[10]-(r[8]-r[6]))>1e-8)fail();});}
  if(seen.size!==active.length**2)fail();for(const s of active)for(const [w,f] of [['T0','t0_source'],['T1','t1_source']]){const n=g.cells.filter(x=>x[f]===s).reduce((n,x)=>n+x.pairs_n,0);if(n>ps[s].counts[g.group][w]||n>g.source_eligibility[s].matched_n)fail();}
  for(const s of ['all',...active]){const target=s==='all'?v:ps[s],nonempty=(s==='all'?active:[s]).filter(k=>g.source_eligibility[k].matched_n),allowed=g.pairs_schema.filter(m=>v.role!=='parent'||!m.variable_id.startsWith('PHQ_')||nonempty.length&&nonempty.every(k=>g.source_eligibility[k].adult_confirmed)),expected=target.changes.filter(x=>x.group===g.group);if(!equal(allowed.map(x=>x.variable_id),expected.map(x=>x.variable_id)))fail();allowed.forEach((m,i)=>{if(Object.keys(m).some(k=>m[k]!==expected[i][k]))fail();const index=g.pairs_schema.indexOf(m),cs=g.cells.filter(x=>x.pairs_n&&(s==='all'||x.t0_source===s&&x.t1_source===s)),rs=cs.map(x=>x.pairs[index]);if(rs.some(r=>r===null))fail();if(expected[i].pair_detail_status==='available'){if(!g.detail_variables.includes(m.variable_id))fail();agree(rs,expected[i]);}else{const r=expected[i],emptyPHQ=v.role==='parent'&&m.variable_id.startsWith('PHQ_')&&r.pairs_n===0;if(r.pair_detail_status!=='not_provided'||g.detail_variables.includes(m.variable_id)&&!emptyPHQ||r.paired_valid_n!==0||r.mean_change!==null||r.sd_change!==null||['only_t0_valid_n','only_t1_valid_n','both_missing_n','t0_mean','t1_mean'].some(k=>r[k]!==null))fail();for(let k=0;k<3;k++)if(rs.reduce((n,x)=>n+x[k],0)!==r[pair[k]])fail();}});}
 }return c;
}
function choose(S,c){let selected,base;try{selected=selection(S,c.sources);base=find(S,c,'all');}catch(e){return absent({mode:c.mode,role:c.role,mainstream:c.mainstream,counts:{}},[], 'unavailable','invalid_source_selection');}
 if(!selected.length)return absent(base,selected,'empty');
 try{
  const grades=c.grades===undefined?Grade.codes:Grade.selection(c.grades),customGrade=!Grade.all(grades),waveSD=c.paired_wave_sd===true&&formal.includes(c.mode);
  if(selected[0]==='all'||selected.length===1){let v=selected[0]==='all'?base:find(S,c,selected[0]);if(customGrade)v=Grade.pool(S,v,grades,{wave_sd:waveSD});else if(waveSD)v=Grade.withWaveSD(S,v);return mark(v,selected,selected[0]==='all'?'all':'single',caps(v));}
  header(S);const active=S.source_selection.residual_present?parts:codes,ps=Object.fromEntries(active.map(s=>[s,find(S,c,s)]));
  for(const v of [base,...Object.values(ps)]){if(Object.values(v.counts).some(x=>!keys(x,['T0','T1'])||Object.values(x).some(n=>!Number.isSafeInteger(n)||n<0)))fail();if(!equal(Object.keys(v.counts),Object.keys(base.counts))||v.grouping_anchor!==base.grouping_anchor||v.source_filter_anchor!==base.source_filter_anchor)fail();Grade.validate(S,v);}
  for(const g of Object.keys(base.counts))for(const w of ['T0','T1'])if(active.reduce((n,s)=>n+ps[s].counts[g][w],0)!==base.counts[g][w])fail();
  for(const v of Object.values(ps))if(!equal(v.grade.statistics_schema,base.grade.statistics_schema)||v.grade.anchor!==base.grade.anchor)fail();
  for(const g of Object.keys(base.counts)){const cs=Object.values(ps).flatMap(v=>v.grade.cells.filter(x=>x.group===g&&x.statistics));base.grade.statistics_schema.forEach((m,i)=>{const a=statsFrom(m,cs.map(x=>x.statistics[i]),g),b=base.statistics.find(x=>x.group===g&&x.wave===m.wave&&x.variable_id===m.variable_id&&x.category_code===m.category_code);if(!b)fail();for(const k of ['sample_n','valid_n','missing_n','outside_range_n','denominator','numerator'])if(a[k]!==b[k])fail();for(const k of ['mean','sd','proportion'])if(a[k]===null?b[k]!==null:!Number.isFinite(b[k])||Math.abs(a[k]-b[k])>1e-8*Math.max(1,Math.abs(b[k])))fail();});}
  const residual=ps.unknown&&Object.values(ps.unknown.counts).some(x=>x.T0||x.T1);if(residual&&!S.source_selection.residual_present)fail();
  if(selected.length===(S.source_selection.residual_present?6:5)){let v=customGrade?Grade.pool(S,base,grades,{wave_sd:waveSD}):waveSD?Grade.withWaveSD(S,base):base;return mark(v,selected,'all',caps(v));}
  const views=selected.map(s=>ps[s]),ss=base.grade.statistics_schema,sdCompatible=views.every(v=>v.grade.anchor===(c.mode.startsWith('independent_')?'parent_report_T0':'student_T0'));
  if(views.some(v=>!equal(v.grade.statistics_schema,ss)||v.grade.anchor!==base.grade.anchor))fail();
  const nonempty=views.filter(v=>Object.values(v.counts).some(x=>x.T0||x.T1));
  const metas=nonempty.length?nonempty[0].grade.pairs_schema.filter(m=>nonempty.every(v=>v.grade.pairs_schema.some(x=>equal(x,m)))):[];
  const out={...strip(base),source:'multiple',counts:{},statistics:[],changes:[],grade_custom:customGrade,grade_anchor:base.grade.anchor};delete out.grade;
  for(const g of Object.keys(base.counts)){const cells=views.flatMap(v=>v.grade.cells.filter(x=>x.group===g&&grades.includes(x.grade_code)).map(x=>({cell:x,view:v})));
   out.counts[g]=Object.fromEntries(['T0','T1'].map(w=>[w,cells.reduce((n,x)=>n+x.cell.counts[w],0)]));
   ss.forEach((m,i)=>out.statistics.push(statsFrom(m,cells.filter(x=>x.cell.statistics).map(x=>x.cell.statistics[i]),g)));
   if(formal.includes(c.mode))metas.forEach(m=>out.changes.push(pairFrom(m,cells.filter(x=>x.cell.pairs).map(x=>x.cell.pairs[x.view.grade.pairs_schema.findIndex(y=>y.variable_id===m.variable_id)]),g,waveSD,sdCompatible)));
  }
  let paired=formal.includes(c.mode),notice='Results combine the selected sources. Paired p-values and effect sizes, distributions and time trends are unavailable for this combination.';
  if(!formal.includes(c.mode)&&!customGrade){try{const cube=validatePairs(base,ps);for(const g of cube.groups){const ne=selected.filter(s=>g.source_eligibility[s].matched_n);g.pairs_schema.forEach((m,i)=>{if(c.role==='parent'&&m.variable_id.startsWith('PHQ_')&&(!ne.length||ne.some(s=>!g.source_eligibility[s].adult_confirmed)))return;const rs=g.cells.filter(x=>x.pairs_n&&selected.includes(x.t0_source)&&selected.includes(x.t1_source)).map(x=>x.pairs[i]);const row=pairFrom(m,rs,g.group);if(!g.detail_variables.includes(m.variable_id)||c.role==='parent'&&m.variable_id.startsWith('PHQ_')&&!row.pairs_n){for(const k of ['only_t0_valid_n','only_t1_valid_n','both_missing_n','t0_mean','t1_mean'])row[k]=null;row.pair_detail_status='not_provided';}out.changes.push(row);});}paired=true;}catch(e){notice+=' Overview paired summaries require compatible cross-source evidence.';}}
  if(!formal.includes(c.mode)&&customGrade)notice+=' Overview paired summaries are unavailable with custom grades.';
  return mark(out,selected,'pooled',{statistics:true,paired_summaries:paired,inference:false,distributions:false,monthly_trends:false},notice);
 }catch(e){return absent(base,selected,'unavailable','source_aggregates_unavailable');}
}
const withWaveSD=(S,context)=>choose(S,{...context,paired_wave_sd:true});
return Object.freeze({codes,options,selection,choose,withWaveSD});})();
'''
