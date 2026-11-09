
"use strict";

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


const Study2ManualEligibility=(()=>{
  const FORMAT='study2_manual_exclusion_v1',POLICY='fixed_original_members_no_reselection';
  const CODES=['A','B','C','D','AC','BD','E','F','EF'],ROLES=['student','parent'];
  const hash=x=>typeof x==='string'&&/^[a-f0-9]{64}$/.test(x);
  const count=x=>Number.isSafeInteger(x)&&x>=0;
  const nullableCount=x=>x===null||count(x);
  const countFields=new Set(['sample_n','valid_n','missing_n','outside_range_n','numerator','denominator','pairs_n','paired_valid_n','paired_missing_n','only_t0_valid_n','only_t1_valid_n','both_missing_n','count','bin_index','matched_n']);
  const keys=(o,k)=>o&&typeof o==='object'&&!Array.isArray(o)&&Object.keys(o).sort().join('|')===k.slice().sort().join('|');
  const need=(v,code='manual_bundle_invalid')=>{if(!v)throw Error(code);};
  function canonical(v){
    if(v===null||typeof v==='boolean'||typeof v==='string')return JSON.stringify(v);
    if(typeof v==='number'){need(Number.isFinite(v));return JSON.stringify(v);}
    if(Array.isArray(v))return '['+v.map(canonical).join(',')+']';
    need(v&&typeof v==='object');return '{'+Object.keys(v).sort().map(k=>JSON.stringify(k)+':'+canonical(v[k])).join(',')+'}';
  }
  async function digest(v){
    need(typeof Study2EligibilityHash!=='undefined'&&typeof Study2EligibilityHash.digest==='function','manual_hash_unavailable');
    return Study2EligibilityHash.digest(v);
  }
  function freeze(v){if(v&&typeof v==='object'&&!Object.isFrozen(v)){Object.freeze(v);for(const x of Object.values(v))freeze(x);}return v;}
  function summary(row,unit){
    need(keys(row,unit?['code','baseline','active','excluded']:['baseline','active','excluded']));
    need([row.baseline,row.active,row.excluded].every(x=>x===null)||
      [row.baseline,row.active,row.excluded].every(count)&&row.active+row.excluded===row.baseline);
  }
  function impact(value){
    need(keys(value,['intake','samples','independent'])&&keys(value.intake,ROLES));
    for(const role of ROLES){const r=value.intake[role];need(keys(r,['baseline','excluded','retained'])&&Object.values(r).every(count)&&r.excluded+r.retained===r.baseline);}
    need(Array.isArray(value.samples)&&value.samples.length===9&&new Set(value.samples.map(r=>r.code)).size===9);
    for(const code of CODES){const row=value.samples.find(r=>r.code===code);summary(row,true);}
    if(value.independent!==null){need(keys(value.independent,['baselines','child_report_pairs','same_adult_pairs']));for(const row of Object.values(value.independent))summary(row,false);}
  }
  function scopeExport(value,release,engine){
    need(value?.format==='study2_static_scope_export_v1'&&value.release_id===release&&value.status==='available'&&hash(value.index_revision));
    engine.validate(value.index);need(value.index.meta.release_id===release);
  }
  function agreeSamples(rows,result){
    for(const row of rows){const s=result.samples.find(r=>r.code===row.code);need(s&&(s.status==='available'?s.count===row.active:row.active===null));}
  }
  function closedShape(value,template,path='view'){
    const cellVector=path.includes('.cells')&&(/\.(statistics|pairs)$/.test(path));
    if(value===null)return template===null||typeof template==='number'||cellVector;
    if(template===null)return false;
    if(typeof template!=='object')return typeof value===typeof template&&(typeof value!=='number'||Number.isFinite(value));
    if(Array.isArray(template)){
      if(!Array.isArray(value))return false;
      if(/\.(columns|statistic_fields|pair_fields|source_codes|grade_codes)$/.test(path))return canonical(value)===canonical(template);
      if(!template.length)return value.length===0;
      if(template.every(x=>x===null||typeof x==='number')){
        const counts=/\.statistics\[\]$/.test(path)?[0,1,2,3,7]:/\.pairs\[\]$/.test(path)?[0,1,2,3,4,5]:[];
        return value.length===template.length&&value.every((x,i)=>counts.includes(i)?count(x):x===null||typeof x==='number'&&Number.isFinite(x));
      }
      const fullCatalogue=path==='view.grade.cells'||path==='view.source_pairs.groups'||path==='view.source_pairs.groups[].cells';
      if(fullCatalogue&&value.length!==template.length)return false;
      if(!value.length)return true;
      if(template.every(x=>typeof x==='string'))return value.every(x=>typeof x==='string'&&template.includes(x));
      const identifiers=['group','grade_code','variable_id','wave','category_code','period','include_batch','t0_source','t1_source'];
      const seen=new Set();
      return value.every((item,i)=>{
        let example=template[i]??template[0];
        if(item&&typeof item==='object'&&!Array.isArray(item)){
          const identity=identifiers.filter(k=>Object.hasOwn(item,k));
          const signature=canonical(identity.map(k=>[k,item[k]]));
          if(seen.has(signature))return false;seen.add(signature);
          example=template.find(t=>t&&typeof t==='object'&&!Array.isArray(t)&&identity.every(k=>t[k]===item[k]));
          if(!example)return false;
        }
        return closedShape(item,example,path+'[]');
      });
    }
    if(keys(template,['columns','rows'])){
      const complete=path==='view.statistics';
      if(Array.isArray(value)&&!value.length)return !complete;
      if(!keys(value,['columns','rows'])||canonical(value.columns)!==canonical(template.columns)||!Array.isArray(value.rows))return false;
      if(complete&&value.rows.length!==template.rows.length)return false;
      const types=template.columns.map((_,i)=>template.rows.map(r=>r[i]).find(x=>x!==null));
      const identity=['variable_id','group','wave','category_code','bin_index','transition'].filter(k=>template.columns.includes(k));
      const fixed=new Set(['variable_id','variable','group','group_label','wave','section','kind','unit','category_code','category','transition']);
      const seen=new Set();
      return value.rows.every((row,rowIndex)=>{
        if(!Array.isArray(row)||row.length!==template.columns.length)return false;
        const signature=canonical(identity.map(k=>[k,row[template.columns.indexOf(k)]]));
        if(seen.has(signature))return false;seen.add(signature);
        const before=complete?template.rows[rowIndex]:template.rows.find(r=>identity.every(k=>r[template.columns.indexOf(k)]===row[template.columns.indexOf(k)]));
        if(!before)return false;
        return row.every((v,i)=>{
          const field=template.columns[i];
          if(fixed.has(field))return canonical(v)===canonical(before[i]);
          if(field==='inference_status')return ['estimated','insufficient_pairs','zero_change_variance','suppressed'].includes(v);
          if(field==='pair_detail_status')return ['available','not_provided','suppressed'].includes(v);
          if(field==='suppressed')return typeof v==='boolean';
          if(countFields.has(field))return nullableCount(v);
          return v===null||types[i]!==undefined&&typeof v===typeof types[i]&&typeof v!=='object'&&(typeof v!=='number'||Number.isFinite(v));
        });
      });
    }
    if(!keys(value,Object.keys(template)))return false;
    const fixed=new Set(['variable_id','variable','group','group_label','wave','section','kind','unit','category_code','category','transition','grouping_anchor','source_filter_anchor','anchor','status','code','statistics_schema','capabilities','detail_variables']);
    if(path.includes('.source_pairs'))fixed.add('pairs_schema');
    return Object.keys(template).every(key=>fixed.has(key)?canonical(value[key])===canonical(template[key]):
      countFields.has(key)||path.endsWith('.counts')&&['T0','T1'].includes(key)?nullableCount(value[key]):closedShape(value[key],template[key],path+'.'+key));
  }

  function validateSnapshots(off,on,wrapper){
    need(off?.format==='study2_static_v1'&&on?.format===off.format&&!Object.hasOwn(on,'manual_exclusion'));
    const mutable=new Set(['counts','views','independent_counts','samples','sources']);
    need(keys(on.counts,Object.keys(off.counts))&&keys(on.independent_counts,Object.keys(off.independent_counts)),'manual_count_mismatch');
    const activeCounts=new Set([...CODES,'parent_child_longitudinal','BD_alternative_followups','analysis_mainstream_rows','analysis_other_or_unknown_rows']);
    for(const [field,value] of Object.entries(on.counts)){
      need(nullableCount(value),'manual_count_mismatch');
      need(activeCounts.has(field)?off.counts[field]===null?value===null:count(value)&&value<=off.counts[field]:value===off.counts[field],'manual_count_mismatch');
    }
    for(const [field,value] of Object.entries(on.independent_counts))need(nullableCount(value)&&(off.independent_counts[field]===null?value===null:count(value)&&value<=off.independent_counts[field]),'manual_independent_count_mismatch');
    if(Object.hasOwn(on.counts,'parent_child_longitudinal'))need(on.counts.parent_child_longitudinal<=Math.min(on.counts.B,on.counts.D,off.counts.parent_child_longitudinal),'manual_supplementary_count_mismatch');
    need(keys(on,[...Object.keys(off),'eligibility_context']),'manual_snapshot_metadata_mismatch');
    need(keys(on.eligibility_context,['mode','revision','inventory_revision','policy'])&&on.eligibility_context.mode==='on'&&on.eligibility_context.revision===wrapper.revision&&on.eligibility_context.inventory_revision===wrapper.inventory_revision&&on.eligibility_context.policy===POLICY,'manual_context_mismatch');
    for(const name of Object.keys(off))if(!mutable.has(name))need(canonical(off[name])===canonical(on[name]),'manual_snapshot_metadata_mismatch');
    need(Array.isArray(off.samples)&&Array.isArray(on.samples)&&off.samples.length===on.samples.length,'manual_sample_rows_mismatch');
    need(new Set(off.samples.map(r=>r.sample)).size===off.samples.length&&new Set(on.samples.map(r=>r.sample)).size===off.samples.length,'manual_sample_rows_mismatch');
    for(const row of on.samples){const before=off.samples.find(r=>r.sample===row.sample),effect=wrapper.impact.samples.find(r=>r.code===row.sample);need(before&&keys(row,Object.keys(before)),'manual_sample_rows_mismatch');
      if(effect)need(row.count===effect.active,'manual_sample_rows_mismatch');
      else need(row.sample==='parent_child_longitudinal'&&row.count===on.counts.parent_child_longitudinal&&(before.count===null?row.count===null:count(row.count)&&row.count<=before.count),'manual_supplementary_count_mismatch');
      for(const key of Object.keys(before))if(key!=='count')need(canonical(row[key])===canonical(before[key]),'manual_sample_rows_mismatch');}
    if(canonical(off.sources)!==canonical(on.sources)){
      need(keys(on.sources,Object.keys(off.sources)),'manual_source_history_mismatch');
      const activeFields=new Set(['最終 T0','最終 T1','最終合計']);
      for(const role of Object.keys(off.sources)){const a=off.sources[role],b=on.sources[role];need(Array.isArray(a)&&Array.isArray(b)&&a.length===b.length,'manual_source_history_mismatch');
        for(let i=0;i<a.length;i++){need(keys(b[i],Object.keys(a[i])),'manual_source_history_mismatch');for(const key of Object.keys(a[i])){const x=a[i][key],y=b[i][key];need(activeFields.has(key)?x===null?y===null:count(x)&&count(y)&&y<=x:canonical(x)===canonical(y),'manual_source_history_mismatch');}}
      }
    }
    const viewKey=v=>JSON.stringify([v.mode,v.role,v.mainstream,v.source]);
    const original=new Map(off.views.map(v=>[viewKey(v),v]));
    need(Array.isArray(on.views)&&on.views.length===original.size&&new Set(on.views.map(viewKey)).size===original.size,'manual_view_set_mismatch');
    for(const v of on.views){const b=original.get(viewKey(v));need(b&&keys(v.counts,Object.keys(b.counts)),'manual_view_set_mismatch');need(closedShape(v,b),'manual_view_shape_invalid');
      for(const group of Object.keys(b.counts))for(const wave of ['T0','T1']){const x=v.counts[group][wave],y=b.counts[group][wave];need(y===null?x===null:count(x)&&count(y)&&x<=y,'manual_count_mismatch');}
    }
  }
  async function create(snapshot,scope,wrapper,engine){
    const off=Object.freeze({snapshot,scope_export:scope});
    let available=false,code=wrapper?'manual_bundle_invalid':'manual_exclusion_not_supplied',on=null,mode='off',active=off;
    let revision=null,inventory=null;
    try{
      if(wrapper===null||wrapper===undefined)throw Error('manual_exclusion_not_supplied');
      need(wrapper&&keys(wrapper,['format','hash_scheme','status','code','release_id','revision','inventory_revision','policy','off','on','impact','on_revision']));
      need(wrapper.format===FORMAT&&wrapper.hash_scheme==='typed_f64_utf16_v1'&&wrapper.policy===POLICY&&wrapper.release_id===snapshot.release_id,'manual_release_mismatch');
      need(keys(wrapper.off,['snapshot_revision','scope_revision'])&&Object.values(wrapper.off).every(hash));
      need(await digest(snapshot)===wrapper.off.snapshot_revision&&await digest(scope)===wrapper.off.scope_revision,'manual_off_hash_mismatch');
      need(['available','unavailable'].includes(wrapper.status));
      if(wrapper.status==='unavailable'){
        need(wrapper.on===null&&wrapper.impact===null&&wrapper.on_revision===null&&typeof wrapper.code==='string'&&/^[a-z][a-z0-9_]{0,127}$/.test(wrapper.code));
        need(wrapper.revision===null||hash(wrapper.revision));need(wrapper.inventory_revision===null||hash(wrapper.inventory_revision));
        revision=wrapper.revision;inventory=wrapper.inventory_revision;throw Error(wrapper.code);
      }
      need(wrapper.code===null&&hash(wrapper.revision)&&hash(wrapper.inventory_revision)&&hash(wrapper.on_revision));
      need(keys(wrapper.on,['snapshot','scope_export'])&&await digest(wrapper.on)===wrapper.on_revision,'manual_on_hash_mismatch');
      impact(wrapper.impact);validateSnapshots(snapshot,wrapper.on.snapshot,wrapper);
      scopeExport(scope,snapshot.release_id,engine);scopeExport(wrapper.on.scope_export,snapshot.release_id,engine);
      const original=engine.query(scope.index),selected=engine.query(wrapper.on.scope_export.index),e=selected.eligibility;
      need(e&&e.mode==='on'&&e.revision===wrapper.revision&&e.inventory_revision===wrapper.inventory_revision,'manual_scope_revision_mismatch');
      need(canonical(original.raw)===canonical(selected.raw)&&canonical(original.flow)===canonical(selected.flow),'manual_history_mismatch');
      need(canonical(e.intake)===canonical(wrapper.impact.intake)&&canonical(e.samples)===canonical(wrapper.impact.samples),'manual_impact_mismatch');
      agreeSamples(wrapper.impact.samples,selected);
      for(const row of wrapper.impact.samples){const s=original.samples.find(r=>r.code===row.code);need(s&&(s.status==='available'?s.count===row.baseline:row.baseline===null),'manual_impact_mismatch');
        if(row.baseline!==null){need(snapshot.counts?.[row.code]===row.baseline&&wrapper.on.snapshot.counts?.[row.code]===row.active,'manual_count_mismatch');}}
      if(wrapper.impact.independent!==null)for(const [key,row] of Object.entries(wrapper.impact.independent))need(snapshot.independent_counts?.[key]===row.baseline&&wrapper.on.snapshot.independent_counts?.[key]===row.active,'manual_independent_count_mismatch');
      revision=wrapper.revision;inventory=wrapper.inventory_revision;on=freeze(wrapper.on);available=true;code=null;
      freeze(snapshot);freeze(scope);freeze(wrapper.impact);
    }catch(error){code=typeof error.message==='string'&&/^[a-z][a-z0-9_]{0,127}$/.test(error.message)?error.message:'manual_bundle_invalid';}
    function metadata(){return Object.freeze({eligibility_mode:mode,eligibility_revision:revision||'not_available',eligibility_inventory_revision:inventory||'not_available',eligibility_release_id:snapshot.release_id,eligibility_policy:POLICY,eligibility_status:available?'available':'unavailable'});}
    function quality(result){
      need(active,'manual_requested_on_unavailable');
      let intake,samples;
      if(mode==='off'){
        intake=Object.fromEntries(ROLES.map(r=>[r,{baseline:result.raw[r],excluded:0,retained:result.raw[r]}]));
        samples=result.samples.map(s=>({code:s.code,baseline:s.count,active:s.count,excluded:s.status==='available'?0:null}));
      }else{
        const e=result.eligibility;need(e&&e.mode==='on'&&e.revision===revision&&e.inventory_revision===inventory,'manual_scope_revision_mismatch');
        const baseline=engine.query(scope.index,result.scope);need(canonical(result.raw)===canonical(baseline.raw),'manual_history_mismatch');
        intake=e.intake;samples=e.samples;
        need(Array.isArray(samples)&&samples.length===9);agreeSamples(samples,result);
        for(const row of samples){summary(row,true);const s=baseline.samples.find(s=>s.code===row.code);need(s&&s.count===row.baseline,'manual_impact_mismatch');}
      }
      return {format:'study2_manual_exclusion_ui_v1',mode,revision,inventory_revision:inventory,release_id:snapshot.release_id,policy:POLICY,status:available?'available':'unavailable',code,intake,samples};
    }
    return Object.freeze({configured:wrapper!==null&&wrapper!==undefined,available,reason:code,
      get mode(){return mode;},get bundle(){return active;},metadata,quality,
      select(requested){need(['off','on'].includes(requested),'manual_mode_invalid');mode=requested;active=requested==='off'?off:available?on:null;need(active,'manual_requested_on_unavailable');return active;}});
  }
  // The small initial bundle is generated only after the complete native
  // export has passed validate_manual_export. Its exact bytes are pinned by
  // the same-origin HTML's SRI. The metadata and both scope exports are
  // usable here; other descriptive views still require the complete bundle.
  function createBootstrap(boot,engine){
    need(keys(boot,['format','release_id','revision','inventory_revision','policy','off','on','impact','bindings']), 'bootstrap_shape');
    need(boot.format==='study2_lazy_bootstrap_v1'&&boot.policy===POLICY&&hash(boot.revision)&&hash(boot.inventory_revision),'bootstrap_metadata');
    need(keys(boot.off,['snapshot','scope_export'])&&keys(boot.on,['snapshot','scope_export']),'bootstrap_shape');
    const off=boot.off,on=boot.on,original=off.snapshot,active=on.snapshot;
    need(original.release_id===boot.release_id&&active.release_id===boot.release_id&&
      original.release_context?.release_id===boot.release_id&&original.release_context?.default_eligibility==='on'&&
      original.release_context?.flags?.manifest_revision===boot.revision,'bootstrap_release_mismatch');
    need(Array.isArray(original.views)&&!original.views.length&&Array.isArray(active.views)&&!active.views.length,'bootstrap_views_forbidden');
    need(keys(boot.bindings,['off_snapshot_revision','off_scope_revision','on_revision','scripts'])&&
      [boot.bindings.off_snapshot_revision,boot.bindings.off_scope_revision,boot.bindings.on_revision].every(hash)&&
      keys(boot.bindings.scripts,['snapshot.js','scope-index.js','manual-exclusion.js'])&&
      Object.values(boot.bindings.scripts).every(s=>typeof s==='string'&&/^sha384-[A-Za-z0-9+/]{64}$/.test(s)), 'bootstrap_bindings');
    impact(boot.impact);validateSnapshots(original,active,boot);
    scopeExport(off.scope_export,boot.release_id,engine);scopeExport(on.scope_export,boot.release_id,engine);
    const baseline=engine.query(off.scope_export.index),selected=engine.query(on.scope_export.index),e=selected.eligibility;
    need(!Object.hasOwn(off.scope_export.index,'eligibility')&&!Object.hasOwn(baseline,'eligibility'),'bootstrap_off_scope_invalid');
    need(e&&e.mode==='on'&&e.revision===boot.revision&&e.inventory_revision===boot.inventory_revision,'manual_scope_revision_mismatch');
    need(canonical(baseline.raw)===canonical(selected.raw)&&canonical(baseline.flow)===canonical(selected.flow),'manual_history_mismatch');
    need(canonical(e.intake)===canonical(boot.impact.intake)&&canonical(e.samples)===canonical(boot.impact.samples),'manual_impact_mismatch');
    agreeSamples(boot.impact.samples,selected);
    for(const row of boot.impact.samples){const s=baseline.samples.find(r=>r.code===row.code);
      need(s&&(s.status==='available'?s.count===row.baseline:row.baseline===null),'manual_impact_mismatch');
      if(row.baseline!==null)need(original.counts?.[row.code]===row.baseline&&active.counts?.[row.code]===row.active,'manual_count_mismatch');}
    if(boot.impact.independent!==null)for(const [key,row] of Object.entries(boot.impact.independent))
      need(original.independent_counts?.[key]===row.baseline&&active.independent_counts?.[key]===row.active,'manual_independent_count_mismatch');
    freeze(boot);let mode='on',activeBundle=on;
    function metadata(){return Object.freeze({eligibility_mode:mode,eligibility_revision:boot.revision,
      eligibility_inventory_revision:boot.inventory_revision,eligibility_release_id:boot.release_id,
      eligibility_policy:POLICY,eligibility_status:'available'});}
    function quality(result){
      if(mode==='off'){
        need(!Object.hasOwn(result,'eligibility'),'manual_scope_revision_mismatch');
        const intake=Object.fromEntries(ROLES.map(r=>[r,{baseline:result.raw[r],excluded:0,retained:result.raw[r]}]));
        const samples=result.samples.map(s=>({code:s.code,baseline:s.count,active:s.count,excluded:s.status==='available'?0:null}));
        return {format:'study2_manual_exclusion_ui_v1',mode,revision:boot.revision,inventory_revision:boot.inventory_revision,
          release_id:boot.release_id,policy:POLICY,status:'available',code:null,intake,samples};
      }
      const current=result.eligibility;need(current&&current.mode==='on'&&current.revision===boot.revision&&
        current.inventory_revision===boot.inventory_revision,'manual_scope_revision_mismatch');
      const before=engine.query(off.scope_export.index,result.scope);need(canonical(result.raw)===canonical(before.raw),'manual_history_mismatch');
      need(Array.isArray(current.samples)&&current.samples.length===9);agreeSamples(current.samples,result);
      for(const row of current.samples){summary(row,true);const s=before.samples.find(s=>s.code===row.code);need(s&&s.count===row.baseline,'manual_impact_mismatch');}
      return {format:'study2_manual_exclusion_ui_v1',mode:'on',revision:boot.revision,inventory_revision:boot.inventory_revision,
        release_id:boot.release_id,policy:POLICY,status:'available',code:null,intake:current.intake,samples:current.samples};
    }
    return Object.freeze({configured:true,available:true,reason:null,get mode(){return mode;},get bundle(){return activeBundle;},metadata,quality,
      select(requested){need(['off','on'].includes(requested),'manual_mode_invalid');mode=requested;activeBundle=requested==='on'?on:off;return activeBundle;}});
  }
  return Object.freeze({create,createBootstrap,digest,canonical});
})();


const Period = (()=>{
'use strict';
const C={"format":"study2_period_filters_v1","date_policy":"native_calendar_response_v1","modes":["abcd","ef","acbd","efmatched","independent_all","independent_child","independent_adult"],"groups":["all","male","female","primary","secondary","male_primary","female_primary","male_secondary","female_secondary"],"grades":["P1","P2","P3","P4","P5","P6","S1","S2","S3","S4","S5","S6","Unknown"],"sources":["legacy_online","paperform","qualtrics","school_batch","socialworkdream","unknown"],"qualities":["system_creation","manual_verified","batch_assigned_creation","unknown_basis","invalid_date"],"cell_fields":["date","wave","gender","stage","grade","source","mainstream","date_quality","n","values"],"metrics":[{"variable_id":"PHQ_total","kind":"continuous","unit":"score"},{"variable_id":"FQOL_total","kind":"continuous","unit":"score"},{"variable_id":"SEC_total","kind":"continuous","unit":"score"},{"variable_id":"TBV_mean","kind":"continuous","unit":"score"},{"variable_id":"TBP_mean","kind":"continuous","unit":"score"},{"variable_id":"CBV_mean","kind":"continuous","unit":"score"},{"variable_id":"CBP_mean","kind":"continuous","unit":"score"},{"variable_id":"TBV_prevalence1","kind":"binary","unit":"proportion"},{"variable_id":"TBV_prevalence2","kind":"binary","unit":"proportion"},{"variable_id":"TBP_prevalence1","kind":"binary","unit":"proportion"},{"variable_id":"TBP_prevalence2","kind":"binary","unit":"proportion"},{"variable_id":"CBV_prevalence1","kind":"binary","unit":"proportion"},{"variable_id":"CBV_prevalence2","kind":"binary","unit":"proportion"},{"variable_id":"CBP_prevalence1","kind":"binary","unit":"proportion"},{"variable_id":"CBP_prevalence2","kind":"binary","unit":"proportion"}]}, waves=['T0','T1'];
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


const Study2Semester = (()=>{
'use strict';
const C={"format":"study2_period_semester_v1","result_format":"study2_period_semester_result_v1","date_policy":"native_calendar_response_v1","modes":["abcd","ef","acbd","efmatched","independent_all","independent_child","independent_adult"],"groups":["all","male","female","primary","secondary","male_primary","female_primary","male_secondary","female_secondary"],"grades":["P1","P2","P3","P4","P5","P6","S1","S2","S3","S4","S5","S6","Unknown"],"sources":["legacy_online","paperform","qualtrics","school_batch","socialworkdream","unknown"],"qualities":["system_creation","manual_verified","batch_assigned_creation","unknown_basis","invalid_date"],"cell_fields":["date","wave","gender","stage","grade","source","mainstream","date_quality","n","values","joint_roles"],"metrics":{"student":[{"variable_id":"PHQ_anxiety","kind":"continuous","unit":"score","subject":"student_child","available":true,"categories":[]},{"variable_id":"PHQ_depression","kind":"continuous","unit":"score","subject":"student_child","available":true,"categories":[]},{"variable_id":"PHQ_total","kind":"continuous","unit":"score","subject":"student_child","available":true,"categories":[]},{"variable_id":"FQOL_total","kind":"continuous","unit":"score","subject":"family","available":true,"categories":[]},{"variable_id":"FQOL_family_interaction","kind":"continuous","unit":"score","subject":"family","available":true,"categories":[]},{"variable_id":"FQOL_parenting","kind":"continuous","unit":"score","subject":"family","available":true,"categories":[]},{"variable_id":"FQOL_emotional_wellbeing","kind":"continuous","unit":"score","subject":"family","available":true,"categories":[]},{"variable_id":"FQOL_physical_wellbeing","kind":"continuous","unit":"score","subject":"family","available":true,"categories":[]},{"variable_id":"SEC_total","kind":"continuous","unit":"score","subject":"student_child","available":true,"categories":[]},{"variable_id":"SEC_responsible_decision_making","kind":"continuous","unit":"score","subject":"student_child","available":true,"categories":[]},{"variable_id":"SEC_social_awareness","kind":"continuous","unit":"score","subject":"student_child","available":true,"categories":[]},{"variable_id":"SEC_self_management","kind":"continuous","unit":"score","subject":"student_child","available":true,"categories":[]},{"variable_id":"SEC_relationship_skills","kind":"continuous","unit":"score","subject":"student_child","available":true,"categories":[]},{"variable_id":"SEC_self_awareness","kind":"continuous","unit":"score","subject":"student_child","available":true,"categories":[]},{"variable_id":"TBV_mean","kind":"continuous","unit":"score","subject":"student_child","available":true,"categories":[]},{"variable_id":"TBV_prevalence1","kind":"binary","unit":"proportion","subject":"student_child","available":true,"categories":[]},{"variable_id":"TBV_prevalence2","kind":"binary","unit":"proportion","subject":"student_child","available":true,"categories":[]},{"variable_id":"TBP_mean","kind":"continuous","unit":"score","subject":"student_child","available":true,"categories":[]},{"variable_id":"TBP_prevalence1","kind":"binary","unit":"proportion","subject":"student_child","available":true,"categories":[]},{"variable_id":"TBP_prevalence2","kind":"binary","unit":"proportion","subject":"student_child","available":true,"categories":[]},{"variable_id":"CBV_mean","kind":"continuous","unit":"score","subject":"student_child","available":true,"categories":[]},{"variable_id":"CBV_prevalence1","kind":"binary","unit":"proportion","subject":"student_child","available":true,"categories":[]},{"variable_id":"CBV_prevalence2","kind":"binary","unit":"proportion","subject":"student_child","available":true,"categories":[]},{"variable_id":"CBP_mean","kind":"continuous","unit":"score","subject":"student_child","available":true,"categories":[]},{"variable_id":"CBP_prevalence1","kind":"binary","unit":"proportion","subject":"student_child","available":true,"categories":[]},{"variable_id":"CBP_prevalence2","kind":"binary","unit":"proportion","subject":"student_child","available":true,"categories":[]},{"variable_id":"phq_band","kind":"category","unit":"proportion","subject":"student_child","available":true,"categories":["0_2","3_5","6_8","9_12"]}],"parent":[{"variable_id":"PHQ_anxiety","kind":"continuous","unit":"score","subject":"respondent_adult","available":true,"categories":[]},{"variable_id":"PHQ_depression","kind":"continuous","unit":"score","subject":"respondent_adult","available":true,"categories":[]},{"variable_id":"PHQ_total","kind":"continuous","unit":"score","subject":"respondent_adult","available":true,"categories":[]},{"variable_id":"FQOL_total","kind":"continuous","unit":"score","subject":"family","available":true,"categories":[]},{"variable_id":"FQOL_family_interaction","kind":"continuous","unit":"score","subject":"family","available":true,"categories":[]},{"variable_id":"FQOL_parenting","kind":"continuous","unit":"score","subject":"family","available":true,"categories":[]},{"variable_id":"FQOL_emotional_wellbeing","kind":"continuous","unit":"score","subject":"family","available":true,"categories":[]},{"variable_id":"FQOL_physical_wellbeing","kind":"continuous","unit":"score","subject":"family","available":true,"categories":[]},{"variable_id":"SEC_total","kind":"continuous","unit":"score","subject":"parent_reported_child","available":true,"categories":[]},{"variable_id":"SEC_responsible_decision_making","kind":"continuous","unit":"score","subject":"parent_reported_child","available":true,"categories":[]},{"variable_id":"SEC_social_awareness","kind":"continuous","unit":"score","subject":"parent_reported_child","available":true,"categories":[]},{"variable_id":"SEC_self_management","kind":"continuous","unit":"score","subject":"parent_reported_child","available":true,"categories":[]},{"variable_id":"SEC_relationship_skills","kind":"continuous","unit":"score","subject":"parent_reported_child","available":true,"categories":[]},{"variable_id":"SEC_self_awareness","kind":"continuous","unit":"score","subject":"parent_reported_child","available":true,"categories":[]},{"variable_id":"TBV_mean","kind":"continuous","unit":"score","subject":"parent_reported_child","available":true,"categories":[]},{"variable_id":"TBV_prevalence1","kind":"binary","unit":"proportion","subject":"parent_reported_child","available":true,"categories":[]},{"variable_id":"TBV_prevalence2","kind":"binary","unit":"proportion","subject":"parent_reported_child","available":true,"categories":[]},{"variable_id":"TBP_mean","kind":"continuous","unit":"score","subject":"parent_reported_child","available":true,"categories":[]},{"variable_id":"TBP_prevalence1","kind":"binary","unit":"proportion","subject":"parent_reported_child","available":true,"categories":[]},{"variable_id":"TBP_prevalence2","kind":"binary","unit":"proportion","subject":"parent_reported_child","available":true,"categories":[]},{"variable_id":"CBV_mean","kind":"continuous","unit":"score","subject":"parent_reported_child","available":true,"categories":[]},{"variable_id":"CBV_prevalence1","kind":"binary","unit":"proportion","subject":"parent_reported_child","available":true,"categories":[]},{"variable_id":"CBV_prevalence2","kind":"binary","unit":"proportion","subject":"parent_reported_child","available":true,"categories":[]},{"variable_id":"CBP_mean","kind":"continuous","unit":"score","subject":"parent_reported_child","available":true,"categories":[]},{"variable_id":"CBP_prevalence1","kind":"binary","unit":"proportion","subject":"parent_reported_child","available":true,"categories":[]},{"variable_id":"CBP_prevalence2","kind":"binary","unit":"proportion","subject":"parent_reported_child","available":true,"categories":[]},{"variable_id":"phq_band","kind":"category","unit":"proportion","subject":"respondent_adult","available":true,"categories":["0_2","3_5","6_8","9_12"]}]},"joint":[{"metric_id":"bullying_roles_traditional","threshold":"any","perpetration":"TBP_prevalence1","victimization":"TBV_prevalence1"},{"metric_id":"bullying_roles_traditional","threshold":"recurrent","perpetration":"TBP_prevalence2","victimization":"TBV_prevalence2"},{"metric_id":"bullying_roles_cyber","threshold":"any","perpetration":"CBP_prevalence1","victimization":"CBV_prevalence1"},{"metric_id":"bullying_roles_cyber","threshold":"recurrent","perpetration":"CBP_prevalence2","victimization":"CBV_prevalence2"}],"role_codes":["perpetrator_only","victim_only","both","neither"]}, WAVES=['T0','T1'], SEMESTERS=['S1','S2'];
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


const Study2PeriodUI = (() => {
  const day = value => typeof value === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(value) &&
    Number.isFinite(Date.parse(value+'T00:00:00Z')) && new Date(value+'T00:00:00Z').toISOString().slice(0,10) === value;
  const need = (ok, message) => {if(!ok)throw new Error(message);};
  function extent(value) {
    if(!value)return null;
    const from=value.start??value.from??value.min,to=value.end??value.to??value.max;
    return day(from)&&day(to)&&from<=to?{from,to}:null;
  }
  function academicPeriods(bounds,dates=null) {
    const result={};bounds=extent(bounds);if(!bounds)return result;
    const academic=value=>Number(value.slice(0,4))-(Number(value.slice(5,7))<9?1:0);
    const years=dates?[...new Set(dates.filter(day).map(academic))].sort((a,b)=>a-b):Array.from({length:academic(bounds.to)-academic(bounds.from)+1},(_,i)=>academic(bounds.from)+i);
    for(const year of years){
      const from=String(year).padStart(4,'0')+'-09-01',to=String(year+1).padStart(4,'0')+'-08-31';
      result['academic:'+year]={from,to,label:`${year}–${year+1} academic year · ${from} to ${to}`};
    }
    return result;
  }
  function refFor(snapshot,state,scope,period) {
    need(snapshot.minimum_cell_n===0,'Fine period filters require a minimum-0 protected snapshot.');
    need(period&&typeof period.validate==='function'&&typeof period.query==='function','The period query engine is unavailable.');
    const index=snapshot.period_selection;
    need(index&&index.format===period.FORMAT&&index.status==='available'&&index.profile==='protected_researcher'&&index.minimum_cell_n===0&&index.release_id===snapshot.release_id&&Array.isArray(index.refs),'The protected period catalog is unavailable or incompatible.');
    need(scope&&['off','on'].includes(scope.mode),'The exclusion scope is unavailable.');
    const matches=index.refs.filter(r=>r.mode===state.mode&&r.role===state.role&&r.eligibility===scope.mode);
    need(matches.length===1,'This sample/respondent/exclusion scope has no unique declared period asset.');
    const ref=matches[0];
    need(ref.status==='available','Period data unavailable: '+(ref.code||'not_provided')+'.');
    need(ref.release_id===snapshot.release_id&&/^[0-9a-f]{64}$/.test(ref.sha256),'The period asset binding is invalid.');
    const roles={abcd:['student','parent'],ef:['student','parent'],acbd:['student','parent'],efmatched:['student','parent'],independent_all:['parent'],independent_child:['parent'],independent_adult:['parent']};
    need(Object.hasOwn(snapshot.modes||{},state.mode)&&Object.hasOwn(roles,state.mode)&&roles[state.mode].includes(state.role),'Unknown period sample/respondent.');
    need(ref.asset===`period-${scope.mode}-${state.mode}-${state.role}.json`,'The asset is outside the declared finite period catalog.');
    need(scope.mode==='off'?ref.eligibility_revision===null:typeof scope.revision==='string'&&ref.eligibility_revision===scope.revision,'The period asset exclusion revision differs from the active scope.');
    return ref;
  }
  function createLoader({getPeriod,fetcher=(...args)=>fetch(...args),cryptoAPI=globalThis.crypto,base=globalThis.location?.href,capacity=3}={}) {
    need(Number.isInteger(capacity)&&capacity>=1&&capacity<=3,'Period cache must contain at most three entries.');
    const cache=new Map();
    function load(snapshot,state,scope) {
      const period=getPeriod(),ref=refFor(snapshot,state,scope,period);
      const origin=new URL(base),url=new URL(ref.asset,origin);
      need(url.origin===origin.origin&&url.pathname.endsWith('/'+ref.asset)&&!url.search&&!url.hash,'Period assets must use the same origin.');
      const key=JSON.stringify([snapshot.release_context?.run_id||snapshot.release_id,snapshot.release_id,state.mode,state.role,scope.mode,scope.revision??null,ref.sha256]);
      if(cache.has(key)){const entry=cache.get(key);cache.delete(key);cache.set(key,entry);return entry;}
      const controller=typeof AbortController==='undefined'?null:new AbortController();
      const entry={key,ref,status:'loading',cube:null,error:null,controller,promise:null};cache.set(key,entry);
      while(cache.size>capacity){const oldest=cache.keys().next().value,removed=cache.get(oldest);cache.delete(oldest);if(removed.status==='loading')removed.controller?.abort();}
      entry.promise=(async()=>{
        try {
          need(cryptoAPI?.subtle,'SHA-256 validation is unavailable in this browser.');
          const response=await fetcher(url.href,{credentials:'same-origin',cache:'no-store',...(controller?{signal:controller.signal}:{})});
          need(response.ok,'Period asset request failed ('+response.status+').');
          if(response.url)need(new URL(response.url).href===url.href,'Period asset redirected outside its declared URL.');
          const bytes=await response.arrayBuffer(),hash=[...new Uint8Array(await cryptoAPI.subtle.digest('SHA-256',bytes))].map(v=>v.toString(16).padStart(2,'0')).join('');
          need(hash===ref.sha256,'Period asset SHA-256 mismatch.');
          const cube=JSON.parse(new TextDecoder('utf-8',{fatal:true}).decode(bytes));
          need(cube.format===snapshot.period_selection.format,'Period cube format mismatch.');
          need(cube.release_id===ref.release_id&&cube.mode===ref.mode&&cube.role===ref.role,'Period cube release/sample/respondent mismatch.');
          need(period.validate(cube)!==false,'Invalid period cube.');
          entry.cube=cube;entry.status='ready';
        } catch(error){entry.error=error?.message||'Period data unavailable.';entry.status='error';}
        return entry;
      })();
      return entry;
    }
    return {load,retry:key=>{cache.get(key)?.controller?.abort();cache.delete(key);},size:()=>cache.size,keys:()=>[...cache.keys()]};
  }
  function selection(state) {
    need(day(state.period_day_from)&&day(state.period_day_to),'Choose valid inclusive start and end dates.');
    need(state.period_day_from<=state.period_day_to,'The start date must not be later than the end date.');
    return {group:state.group,grades:[...state.grades],sources:[...state.sources],mainstream:state.mainstream,
      include_batch:state.batch,from:state.period_day_from,to:state.period_day_to};
  }
  function csvMetadata(snapshot,state,scope,cube,result) {
    return {period_format:cube.format,period_asset_release_id:cube.release_id,eligibility_mode:scope.mode,
      eligibility_revision:scope.revision??'not_applicable',filter_source_codes:state.sources.join('|'),
      filter_grade_codes:state.grades.join('|'),source_all:String(state.sources.includes('all')),group:state.group,
      mode:state.mode,role:state.role,mainstream:String(state.mainstream),period_from:state.period_day_from,
      period_to:state.period_day_to,interval:'inclusive_day',timezone:'Asia/Hong_Kong',include_batch_dates:String(state.batch),
      grade_anchor:cube.grade_anchor,grouping_anchor:cube.grouping_anchor,source_filter_anchor:cube.source_filter_anchor,
      basis:'calendar_response',denominator_basis:'selected responses inside inclusive HK dates; metric valid N excludes missing/outside-range',
      date_provenance:JSON.stringify(result.date_quality??[]),date_exclusions:JSON.stringify(result.exclusions??[]),period_selection:JSON.stringify(result.metadata??selection(state)),
      interpretation:'Each selected response uses its own date; T0/T1 respondents may differ; no paired change/test.'};
  }
  function mount(env) {
    const {host,snapshot,state,scope,loader,period,isCurrent,rerender,el,select,notice,cards,table,lineChart,num,n}=env;
    const controls=el('div','controls');host.append(controls);
    let entry=null,failure=null;
    try {entry=loader.load(snapshot,state,scope);}catch(error){failure=error.message;}
    const cube=entry?.status==='ready'?entry.cube:null,dateIndex=cube?.cell_fields.indexOf('date'),dates=cube?cube.cells.map(row=>row[dateIndex]).filter(day).sort():null;
    const bounds=extent(entry?.ref?.extent)||(dates?.length?{from:dates[0],to:dates.at(-1)}:null);
    if(!state.period_day_initialized&&bounds){state.period_day_from=bounds.from;state.period_day_to=bounds.to;state.period_day_initialized=true;state.period_preset='full';}
    const academic=academicPeriods(bounds,dates),presets={full:'Full available date period',custom:'Custom inclusive dates',...Object.fromEntries(Object.entries(academic).map(([k,v])=>[k,v.label]))};
    const selectedPreset=state.period_preset||'custom';
    if(!Object.hasOwn(presets,selectedPreset))presets[selectedPreset]='Selected academic year · '+(state.period_day_from||'')+' to '+(state.period_day_to||'');
    select(controls,'Period preset',selectedPreset,presets,value=>{
      const chosen=value==='full'?bounds:academic[value];state.period_preset=value;
      if(chosen){state.period_day_from=chosen.from;state.period_day_to=chosen.to;state.period_day_initialized=true;}
      rerender();
    });
    for(const [key,label]of [['from','Start date (Hong Kong, inclusive)'],['to','End date (Hong Kong, inclusive)']]){
      const lab=el('label','',label),input=el('input');input.type='date';input.dataset.control='period-day:'+key;input.setAttribute('aria-label',label);input.value=state['period_day_'+key]||'';
      input.onchange=()=>{state['period_day_'+key]=input.value;state.period_day_initialized=true;state.period_preset='custom';rerender();};lab.append(input);controls.append(lab);
    }
    select(controls,'Date source',String(state.batch),{false:'Only system or manually verified dates',true:'Also include accepted batch dates'},value=>{state.batch=value==='true';rerender();});
    const schema=cube?.metrics||[],metricOptions={volume:'Number of formally selected responses'};
    for(const metric of schema){const key=metric.variable_id;metricOptions[key]=(snapshot.dictionary?.find(v=>v.variable_id===key)?.label||key)+(metric.available===false?' (not available in this scope)':'');}
    if(!Object.hasOwn(metricOptions,state.trend_variable))metricOptions[state.trend_variable]=snapshot.dictionary?.find(v=>v.variable_id===state.trend_variable)?.label||state.trend_variable+' (not available in this scope)';
    select(controls,'Period comparison metric',state.trend_variable,metricOptions,value=>{state.trend_variable=value;rerender();});
    if(state.trend_variable!=='volume'&&schema.find(m=>m.variable_id===state.trend_variable)?.kind!=='binary')select(controls,'Vertical axis range',state.trend_axis||'full',{full:'Full scale range',auto:'Auto scale (range is labelled)'},value=>{state.trend_axis=value;rerender();});
    host.append(el('p','caption','Active intersection: '+(snapshot.groups?.[state.group]||state.group)+' · grades '+(state.grades.join(', ')||'None')+' · sources '+(state.sources.map(c=>snapshot.source_names?.[c]||c).join(', ')||'None')+' · '+(state.mainstream?'mainstream schools':'all schools')+' · '+scope.mode.toUpperCase()+'.'));
    host.append(el('p','caption','Inclusive Hong Kong dates: '+(state.period_day_from||'not set')+' to '+(state.period_day_to||'not set')+'. Custom day boundaries and all selections are kept across filters and OFF/ON. Academic years use full September 1–August 31 boundaries.'));
    if(bounds)host.append(el('p','caption','Available date extent before this intersection: '+bounds.from+' to '+bounds.to+'.'));
    if(failure){notice(host,failure+' No unfiltered period result is substituted.',true);return;}
    if(entry.status==='loading'){notice(host,'Loading and validating this protected period asset…');entry.promise.then(()=>{if(isCurrent())rerender();});return;}
    if(entry.status==='error'){
      notice(host,entry.error+' No unfiltered period result is substituted.',true);
      const retry=el('button','quiet','Retry this period asset');retry.dataset.control='period:retry';retry.onclick=()=>{loader.retry(entry.key);rerender();};host.append(retry);return;
    }
    let result;
    try {result=period.query(cube,{...selection(state),...(state.trend_variable==='volume'?{}:{variable_id:state.trend_variable})});}catch(error){notice(host,error.message+' No unfiltered period result is substituted.',true);return;}
    env.present({host,snapshot,state,scope,cube,result,env:{...env,assetHash:entry.ref.sha256}});
  }
  function present({host,snapshot,state,scope,cube,result,env}) {
    const {el,notice,cards,table,lineChart,num,n}=env,key=state.trend_variable;
    const metrics=cube.metrics,metric=metrics.find(m=>m.variable_id===key);
    const label=key==='volume'?'Number of formally selected responses':snapshot.dictionary?.find(v=>v.variable_id===key)?.label||key;
    const counts=wave=>result.counts.filter(r=>r.wave===wave).reduce((sum,r)=>sum+r.sample_n,0);
    const metadata={...csvMetadata(snapshot,state,scope,cube,result),period_asset_sha256:env.assetHash,
      metric_available:key==='volume'?'not_applicable':String(metric?.available===true),
      denominator_basis:key==='volume'?'selected responses in inclusive HK dates':'metric valid N inside inclusive HK dates'};
    host.append(el('p','caption','Grade anchor: '+cube.grade_anchor+'. Grouping anchor: '+cube.grouping_anchor+'. Source filter anchor: '+cube.source_filter_anchor+'. Formal anchors stay at baseline; each response is date-filtered independently.'));
    notice(host,'Calendar-response description only: T0 and T1 may contain different respondents. Parent PHQ describes the responding adult at each wave. This is not a paired change, paired test or effect size.');
    cards(host,['T0','T1'].map(wave=>['In-period '+wave+' response N',counts(wave),'Exact current group, grade, source, school scope, date-source and inclusive day intersection']));
    if(!counts('T0')&&!counts('T1'))notice(host,'The selected intersection has zero responses. Every filter and date boundary is kept; use the visible controls to change it.');
    const rows=key==='volume'?['T0','T1'].map(wave=>({wave,variable_id:'volume',kind:'count',available:true,sample_n:counts(wave),mean:counts(wave),sd:null,valid_n:counts(wave),missing_n:0,outside_range_n:0})):
      result.whole_period.filter(r=>r.variable_id===key);
    const points=rows.map(row=>({...row,period:row.wave,value:row.available===false?null:row.kind==='binary'?row.proportion:row.mean,
      status:row.available===false?'unavailable':key!=='volume'&&!row.valid_n?'no_valid_scores':'estimated'}));
    if(key!=='volume'&&metric?.available===false)notice(host,'This metric is unavailable for this scope, rather than an all-missing score. Response counts and date provenance remain available.',true);
    else lineChart(host,points,label,key,state.trend_axis||'full',state.period_day_from+' to '+state.period_day_to+' inclusive HK dates');
    const formatted=points.map(row=>({...row,estimate:row.available===false?'Metric unavailable (not all-missing)':key==='volume'?n(row.sample_n):!row.valid_n?'No valid responses':row.kind==='binary'?`${n(row.numerator)} / ${n(row.denominator)} (${num(100*row.proportion)}%)`:`${num(row.mean)} (${num(row.sd)})`}));
    table(host,formatted,{wave:'Wave',estimate:key==='volume'?'Response count':metric?.kind==='binary'?'Prevalence / valid denominator':'Period mean (SD)',sample_n:'Response N',...(key==='volume'?{}:{valid_n:'Valid N',missing_n:'Missing N',outside_range_n:'Outside range N'})},
      'period-comparison-'+state.mode+'-'+state.role,false,{variable_id:'Variable ID',available:'Metric available',mean:'Mean (raw)',sd:'SD (raw)',numerator:'Numerator',denominator:'Denominator',proportion:'Proportion (raw)'},{type:'period_summary',variable:key,metadata});
    const quality=el('details');quality.append(el('summary','','Date provenance and exclusions'));host.append(quality);
    table(quality,result.date_quality,{wave:'Wave',date_quality:'Date provenance',input_n:'Selected before dates N',included_n:'Included in period N'},'period-date-quality',false,{}, {type:'period_provenance',metadata});
    table(quality,result.exclusions,{wave:'Wave',stage:'Date filter stage',remaining_n:'Remaining N',excluded_n:'Excluded N'},'period-date-exclusions',false,{}, {type:'period_provenance',metadata});
    const detail=el('details');detail.append(el('summary','','Monthly audit detail and download'));host.append(detail);
    const monthly=key==='volume'?result.counts.map(row=>({...row,variable_id:'volume'})):result.statistics.filter(row=>row.variable_id===key);
    table(detail,monthly,{period_id:'Month',wave:'Wave',covered_start:'Included start',covered_end:'Included end',partial_period:'Clipped month',sample_n:'Response N',...(key==='volume'?{}:{valid_n:'Valid N',missing_n:'Missing N',mean:metric?.kind==='binary'?'Proportion':'Mean',sd:'SD',numerator:'Numerator',denominator:'Denominator'})},
      'monthly-'+state.mode+'-'+state.role,false,{variable_id:'Variable ID',available:'Metric available',outside_range_n:'Outside range N',mean:'Mean (raw)',sd:'SD (raw)',proportion:'Proportion (raw)',batch_date_n:'Accepted batch dates N',manual_date_n:'Manually verified dates N'}, {type:'monthly_detail',variable:key,metadata});
  }
  /* Semester trends are additive. The older period API above remains unchanged. */
  const semesterFormat='study2_period_semester_v1', semesterResult='study2_period_semester_result_v1';
  const semesterRoles={abcd:['student','parent'],ef:['student','parent'],acbd:['student','parent'],efmatched:['student','parent'],independent_all:['parent'],independent_child:['parent'],independent_adult:['parent']};
  const hash64=value=>typeof value==='string'&&/^[0-9a-f]{64}$/.test(value);
  function semesterCatalog(snapshot,scope,period) {
    need(snapshot?.minimum_cell_n===0,'Semester trends require the protected minimum-0 profile.');
    need(period&&typeof period.validate==='function'&&typeof period.query==='function','The semester query engine is unavailable.');
    const catalog=snapshot.period_semester_selection;
    need(catalog&&catalog.format===semesterFormat&&catalog.status==='available'&&catalog.profile==='protected_researcher'&&catalog.minimum_cell_n===0&&catalog.release_id===snapshot.release_id&&Array.isArray(catalog.refs),'The protected semester catalog is unavailable or incompatible.');
    need(scope&&['off','on'].includes(scope.mode),'The exclusion scope is unavailable.');
    need(hash64(catalog.active_on_revision)&&scope.active_on_revision===catalog.active_on_revision,'The active control revision does not match the semester catalog.');
    need(scope.mode==='off'?scope.revision===null:scope.revision===catalog.active_on_revision,'The selected exclusion revision is incompatible with the active controls.');
    const expected=[];
    for(const eligibility of ['off','on'])for(const [mode,roles] of Object.entries(semesterRoles))for(const role of roles)expected.push(`period-semester-${eligibility}-${mode}-${role}.json`);
    need(catalog.refs.length===expected.length,'The semester catalog is incomplete.');
    const seen=new Set();
    for(const ref of catalog.refs){
      need(ref&&semesterRoles[ref.mode]?.includes(ref.role)&&['off','on'].includes(ref.eligibility),'The semester catalog contains an invalid scope.');
      const name=`period-semester-${ref.eligibility}-${ref.mode}-${ref.role}.json`;
      need(ref.asset===name&&expected.includes(name)&&!seen.has(name)&&ref.release_id===snapshot.release_id&&hash64(ref.sha256)&&['available','unavailable'].includes(ref.status),'The semester catalog contains an invalid asset binding.');
      if(ref.status==='available')need(ref.eligibility==='off'?ref.eligibility_revision===null:ref.eligibility_revision===catalog.active_on_revision,'A semester catalog exclusion revision is invalid.');
      seen.add(name);
    }
    return catalog;
  }
  function semesterRef(snapshot,state,scope,period) {
    const catalog=semesterCatalog(snapshot,scope,period);
    need(Object.hasOwn(snapshot.modes||{},state.mode)&&semesterRoles[state.mode]?.includes(state.role),'This respondent is unavailable for the selected sample.');
    const ref=catalog.refs.find(r=>r.mode===state.mode&&r.role===state.role&&r.eligibility===scope.mode);
    need(ref&&ref.status==='available','Semester data unavailable: '+(ref?.code||'not_provided')+'.');
    return ref;
  }
  function createSemesterLoader({getPeriod,fetcher=(...args)=>fetch(...args),cryptoAPI=globalThis.crypto,base=globalThis.location?.href,capacity=3}={}) {
    need(Number.isInteger(capacity)&&capacity>=2&&capacity<=3,'Semester cache must contain two or three entries.');
    const cache=new Map();
    function load(snapshot,state,scope){
      const period=getPeriod(),ref=semesterRef(snapshot,state,scope,period),catalog=snapshot.period_semester_selection;
      const origin=new URL(base),url=new URL(ref.asset,origin);
      need(url.origin===origin.origin&&url.pathname.endsWith('/'+ref.asset)&&!url.search&&!url.hash,'Semester assets must use the same origin.');
      const key=JSON.stringify([snapshot.release_context?.run_id||snapshot.release_id,snapshot.release_id,catalog.active_on_revision,state.mode,state.role,scope.mode,scope.revision,ref.sha256]);
      if(cache.has(key)){const entry=cache.get(key);cache.delete(key);cache.set(key,entry);return entry;}
      const controller=typeof AbortController==='undefined'?null:new AbortController();
      const entry={key,ref,status:'loading',cube:null,error:null,controller,promise:null};cache.set(key,entry);
      while(cache.size>capacity){const oldest=cache.keys().next().value,removed=cache.get(oldest);cache.delete(oldest);if(removed.status==='loading')removed.controller?.abort();}
      entry.promise=(async()=>{
        try{
          need(cryptoAPI?.subtle,'SHA-256 validation is unavailable in this browser.');
          const response=await fetcher(url.href,{credentials:'same-origin',cache:'no-store',...(controller?{signal:controller.signal}:{})});
          need(response.ok,'Semester asset request failed ('+response.status+').');
          if(response.url)need(new URL(response.url).href===url.href,'Semester asset redirected outside its declared URL.');
          const bytes=await response.arrayBuffer(),hash=[...new Uint8Array(await cryptoAPI.subtle.digest('SHA-256',bytes))].map(v=>v.toString(16).padStart(2,'0')).join('');
          need(hash===ref.sha256,'Semester asset SHA-256 mismatch.');
          const cube=JSON.parse(new TextDecoder('utf-8',{fatal:true}).decode(bytes));
          need(cube.format===semesterFormat&&cube.release_id===ref.release_id&&cube.mode===ref.mode&&cube.role===ref.role&&cube.eligibility===ref.eligibility&&cube.eligibility_revision===ref.eligibility_revision&&cube.active_on_revision===catalog.active_on_revision,'Semester cube release, respondent or control binding mismatch.');
          need(period.validate(cube)!==false,'Invalid semester cube.');
          entry.cube=cube;entry.status='ready';
        }catch(error){entry.error=error?.message||'Semester data unavailable.';entry.status='error';}
        return entry;
      })();
      return entry;
    }
    return {load,retry:key=>{cache.get(key)?.controller?.abort();cache.delete(key);},size:()=>cache.size,keys:()=>[...cache.keys()]};
  }
  function ordered(values,allowed,label){
    need(Array.isArray(values)&&values.every(v=>allowed.includes(v)),'Invalid '+label+' selection.');
    return allowed.filter(v=>values.includes(v));
  }
  function semesterSelection(state,options){
    const years=options.academic_years;
    need(Array.isArray(years)&&years.every(y=>Number.isInteger(y)&&y>=1&&y<=9998),'Invalid academic year selection.');
    const grades=typeof Grade==='undefined'?['P1','P2','P3','P4','P5','P6','S1','S2','S3','S4','S5','S6','Unknown']:Grade.codes;
    const sources=['all','legacy_online','paperform','qualtrics','school_batch','socialworkdream','unknown'];
    const selectedSources=ordered(state.sources,sources,'source');
    need(!selectedSources.includes('all')||selectedSources.length===1,'All sources cannot be combined with individual sources.');
    need(day(options.from)&&day(options.to)&&options.from<=options.to,'Choose valid inclusive Hong Kong start and end dates.');
    need(['recurrent','any','both'].includes(options.threshold)&&['none','wilson_95_unclustered'].includes(options.ci),'Invalid threshold or interval selection.');
    need(typeof options.metric_id==='string'&&options.metric_id.length>0,'Choose a metric.');
    return {academic_years:[...new Set(years)].sort((a,b)=>a-b),semesters:ordered(options.semesters,['S1','S2'],'semester'),waves:ordered(options.waves,['T0','T1'],'wave'),
      from:options.from,to:options.to,group:state.group,grades:ordered(state.grades,grades,'grade'),sources:selectedSources,mainstream:state.mainstream,
      include_batch:state.batch,metric_id:options.metric_id,threshold:options.threshold,ci:options.ci};
  }
  function semesterYears(entries){
    const years=new Set();
    for(const entry of entries){const cube=entry?.cube;if(!cube)continue;const i=cube.cell_fields?.indexOf('date');if(i<0)continue;
      for(const cell of cube.cells||[]){const value=cell[i];if(day(value)){const year=Number(value.slice(0,4))-(Number(value.slice(5,7))<9?1:0);if(year>=1&&year<=9998)years.add(year);}}}
    return [...years].sort((a,b)=>a-b);
  }
  function semesterMetricId(metric){return metric?.metric_id??metric?.variable_id;}
  function semesterLabel(snapshot,id){
    const bullying={TBV:'Traditional bullying victimization',TBP:'Traditional bullying perpetration',CBV:'Cyberbullying victimization',CBP:'Cyberbullying perpetration'};
    const domain=/^(TBV|TBP|CBV|CBP)_prevalence[12]$/.exec(id);
    if(domain)return bullying[domain[1]];
    const meanDomain=/^(TBV|TBP|CBV|CBP)_mean$/.exec(id);
    if(meanDomain)return bullying[meanDomain[1]];
    if(id==='bullying_roles_traditional')return 'Traditional bullying: four exclusive roles';
    if(id==='bullying_roles_cyber')return 'Cyberbullying: four exclusive roles';
    return snapshot.dictionary?.find(v=>v.variable_id===id||v.metric_id===id)?.label||id;
  }
  function semesterResultChecked(result,snapshot,state,scope,role,selected){
    need(result&&result.format===semesterResult&&result.release_id===snapshot.release_id&&result.mode===state.mode&&result.role===role&&result.eligibility===scope.mode&&result.eligibility_revision===scope.revision&&result.active_on_revision===scope.active_on_revision,'Semester result binding mismatch.');
    need(Array.isArray(result.rows)&&Array.isArray(result.date_quality)&&Array.isArray(result.date_exclusions)&&result.selection,'The semester result is incomplete.');
    for(const [key,value] of Object.entries(selected))need(JSON.stringify(result.selection[key])===JSON.stringify(value),'The semester result does not match the selected filters.');
    const statuses=['available','no_responses','no_valid_scores','metric_unavailable','outside_date_range','suppressed'];
    for(const row of result.rows){
      need(statuses.includes(row.status)&&selected.academic_years.includes(row.academic_year_start)&&selected.semesters.includes(row.semester)&&selected.waves.includes(row.wave),'The semester result contains an invalid period or status.');
      if(row.status!=='available')need(row.mean==null&&row.sd==null&&row.proportion==null&&row.ci_low==null&&row.ci_high==null,'An unavailable result contains an estimate.');
      if(row.status==='suppressed')need(row.sample_n==null&&row.valid_n==null&&row.missing_n==null&&row.outside_range_n==null&&row.numerator==null&&row.denominator==null,'A suppressed result contains recoverable counts.');
      if(row.kind!=='binary')need(row.ci_low==null&&row.ci_high==null,'Intervals are supported only for binary proportions.');
    }
    return result;
  }
  function semesterCSVMetadata(snapshot,state,scope,cube,result,selected,assetHash){
    const bullying=/^(TBV|TBP|CBV|CBP)_|^bullying_roles_/.test(selected.metric_id);
    const thresholded=/_prevalence[12]$|^bullying_roles_/.test(selected.metric_id),definition=snapshot.dictionary?.find(v=>v.variable_id===selected.metric_id||v.metric_id===selected.metric_id);
    const domainMean=/^(TBV|TBP|CBV|CBP)_mean$/.exec(selected.metric_id);
    return {period_format:cube.format,period_asset_sha256:assetHash,period_asset_release_id:cube.release_id,
      analytical_run_id:snapshot.release_context?.run_id||snapshot.release_id,active_on_revision:scope.active_on_revision,
      eligibility_mode:scope.mode,eligibility_revision:scope.revision,mode:state.mode,role:cube.role,
      academic_years:selected.academic_years.join('|'),semesters:selected.semesters.join('|'),waves:selected.waves.join('|'),
      period_from:selected.from,period_to:selected.to,interval:'inclusive_day',timezone:'Asia/Hong_Kong',
      group:selected.group,filter_grade_codes:selected.grades.join('|'),filter_source_codes:selected.sources.join('|'),
      mainstream:String(selected.mainstream),include_batch_dates:String(selected.include_batch),threshold_selection:thresholded?selected.threshold:'not_applicable',ci_selection:selected.ci,
      grade_anchor:result.anchors?.grade_anchor??'not_provided',grouping_anchor:result.anchors?.grouping_anchor??'not_provided',
      source_filter_anchor:result.anchors?.source_filter_anchor??'not_provided',anchors:JSON.stringify(result.anchors),
      date_provenance:JSON.stringify(result.date_quality),date_exclusions:JSON.stringify(result.date_exclusions),
      basis:'calendar_response',recall:bullying?'Past three months, grouped by response semester':'not_applicable',
      score_definition:semesterLabel(snapshot,selected.metric_id)+(definition?.note?'; '+definition.note:'')+(domainMean?`; complete-domain average of ${domainMean[1].startsWith('T')?7:6} items; score points, nominal range 0–4`:'')+(thresholded?'; any >=1, recurrent >=2; complete domains required':'')+(selected.metric_id.startsWith('bullying_roles_')?'; joint validity requires both perpetration and victimization domains':''),
      interpretation:'Independent T0 and T1 response series; no paired inference. Parent PHQ describes the responding adult.'};
  }
  /* These are the existing published score ranges used by static_assets.trendBounds. */
  function semesterScale(id,kind){
    if(['binary','category','joint_roles'].includes(kind))return [0,1];
    if(id==='PHQ_total')return [0,12];
    if(['PHQ_anxiety','PHQ_depression'].includes(id))return [0,6];
    if(/^FQOL_(total|family_interaction|parenting|emotional_wellbeing|physical_wellbeing)$/.test(id))return [1,5];
    if(/^SEC_(total|responsible_decision_making|social_awareness|self_management|relationship_skills|self_awareness)$/.test(id))return [1,4];
    if(/^(TBV|TBP|CBV|CBP)_mean$/.test(id))return [0,4];
    return null;
  }
  function semesterRange(rows,id,kind,mode){
    const expected=semesterScale(id,kind),values=[];
    for(const row of rows){if(row.status!=='available')continue;const v=kind==='continuous'?row.mean:row.proportion;
      if(Number.isFinite(v))values.push(v);if(kind==='binary')for(const bound of [row.ci_low,row.ci_high])if(Number.isFinite(bound))values.push(bound);}
    if(!values.length)return expected?{range:expected,mode:'full',extended:false}:null;
    const observedLow=Math.min(...values),observedHigh=Math.max(...values);
    if(mode!=='auto'||['category','joint_roles'].includes(kind)){
      if(!expected)return null;
      return {range:[Math.min(expected[0],observedLow),Math.max(expected[1],observedHigh)],mode:'full',extended:observedLow<expected[0]||observedHigh>expected[1]};
    }
    const pad=Math.max((observedHigh-observedLow)*0.15,0.05),minimum=expected?Math.min(expected[0],observedLow):-Infinity,maximum=expected?Math.max(expected[1],observedHigh):Infinity;
    return {range:[Math.max(minimum,observedLow-pad),Math.min(maximum,observedHigh+pad)],mode:'auto',extended:false};
  }
  function semesterBullyingId(id){return /^(TBV|TBP|CBV|CBP)(?:_|$)|^bullying_/i.test(id);}
  function semesterDisplayState(options,metrics){
    const id=options.metric_id||'',domain=/^(TBV|TBP|CBV|CBP)_(mean|prevalence[12])$/.exec(id),roles=/^bullying_roles_(traditional|cyber)$/.exec(id);
    if(options.bullying_display===undefined)options.bullying_display=domain?(domain[2]==='mean'?'mean':'prevalence'):roles?'roles':'none';
    if(options.bullying_domain===undefined)options.bullying_domain=domain?.[1]||'TBV';
    if(options.bullying_roles_domain===undefined)options.bullying_roles_domain=roles?.[1]||'traditional';
    if(options.scale_metric===undefined)options.scale_metric=id&&!semesterBullyingId(id)?id:(metrics.has('PHQ_total')?'PHQ_total':[...metrics.keys()].find(key=>!semesterBullyingId(key))||'');
    if(domain?.[2]==='mean'){
      const primary=options.scale_metric&&!semesterBullyingId(options.scale_metric)?options.scale_metric:(metrics.has('PHQ_total')?'PHQ_total':[...metrics.keys()].find(key=>!semesterBullyingId(key))||'');
      if(!primary)return 'A non-bullying primary metric is unavailable; the previous bullying mean cannot be migrated safely.';
      const previousOverlay=options.overlay??'none';
      options.scale_metric=primary;options.metric_id=primary;options.bullying_display='none';options.overlay=id;
      options.mean_migration={mean:id,primary,previous_overlay:previousOverlay!=='none'&&previousOverlay!==id?previousOverlay:null};
    }
    return null;
  }
  function semesterSetBullyingMetric(options){
    if(options.bullying_display==='none')options.metric_id=options.scale_metric;
    else if(options.bullying_display==='prevalence')options.metric_id=options.bullying_domain+'_prevalence2';
    else if(options.bullying_display==='roles')options.metric_id='bullying_roles_'+options.bullying_roles_domain;
  }
  function semesterPanelControls(aside,role,env,metrics){
    const {el,select,rerender,snapshot,state}=env,options=state.semester_trends,roleLabel=role==='student'?'Student':'Parent';
    aside.append(el('h3','','Chart controls'),el('p','caption','Chart settings are shared by both charts.'));
    function control(key,label,value,choices,changed){const input=select(aside,label,value,choices,changed);if(input){input.dataset.control=`semester:control:${role}:${key}`;input.setAttribute('aria-label',`${roleLabel} ${label} (shared)`);}}
    const choices=Object.fromEntries([...metrics.keys()].filter(id=>!semesterBullyingId(id)).map(id=>[id,semesterLabel(snapshot,id)]));
    if(options.scale_metric&&!semesterBullyingId(options.scale_metric)&&!Object.hasOwn(choices,options.scale_metric))choices[options.scale_metric]=semesterLabel(snapshot,options.scale_metric)+' (not available in this scope)';
    control('metric','Metric',options.scale_metric,choices,value=>{options.scale_metric=value;options.bullying_display='none';delete options.mean_migration;semesterSetBullyingMetric(options);rerender();});
    control('overlay','Mean bullying overlay',options.overlay,{none:'None',TBV_mean:'TBV · traditional victimization mean score',TBP_mean:'TBP · traditional perpetration mean score',CBV_mean:'CBV · cybervictimization mean score',CBP_mean:'CBP · cyberperpetration mean score'},value=>{options.overlay=value;delete options.mean_migration;rerender();});
    if(options.mean_migration){const m=options.mean_migration;aside.append(el('p','caption',`The previous ${semesterLabel(snapshot,m.mean)} mean is now the overlay, with ${semesterLabel(snapshot,m.primary)} as the primary metric.`+(m.previous_overlay?` The earlier ${semesterLabel(snapshot,m.previous_overlay)} overlay can be selected again.`:'')));}
    control('bullying_display','Bullying display',options.bullying_display,{none:'None · use the scale metric',prevalence:'Bullying prevalence',roles:'Bullying role distribution'},value=>{options.bullying_display=value;delete options.mean_migration;semesterSetBullyingMetric(options);rerender();});
    aside.append(el('p','caption','The scale metric is shown when Bullying display is None. A selected bullying display replaces the main series; the mean overlay is separate.'));
    if(options.bullying_display==='prevalence')control('bullying_domain','Bullying domain',options.bullying_domain,{TBV:'Traditional victimization',TBP:'Traditional perpetration',CBV:'Cybervictimization',CBP:'Cyberperpetration'},value=>{options.bullying_domain=value;semesterSetBullyingMetric(options);rerender();});
    if(options.bullying_display==='roles')control('bullying_roles_domain','Bullying role domain',options.bullying_roles_domain,{traditional:'Traditional',cyber:'Cyber'},value=>{options.bullying_roles_domain=value;semesterSetBullyingMetric(options);rerender();});
    control('threshold','Bullying frequency',options.threshold,{recurrent:'Recurrent (at least 2)',any:'Any (at least 1)',both:'Compare both thresholds'},value=>{options.threshold=value;rerender();});
    const binary=metrics.get(options.metric_id)?.kind==='binary';
    if(binary)control('ci','Binary confidence intervals',options.ci,{none:'Hidden',wilson_95_unclustered:'95% Wilson, not cluster-adjusted'},value=>{options.ci=value;rerender();});
    aside.append(el('p','caption','Frequency applies to prevalence and role distributions. It does not change a bullying mean score or the mean overlay.'));
    control('chart','Chart',options.chart,{line:'Line',bars:'Grouped bars'},value=>{options.chart=value;rerender();});
    control('axis','Axis range',options.axis,{full:'Full stated scale',auto:'Auto zoom (range labelled)'},value=>{options.axis=value;rerender();});
    if(options.bullying_display==='roles')aside.append(el('p','caption','Bullying roles use 100% stacked bars with a joint valid denominator.'));
  }
  function semesterTooltipText(row,period,label,role,env){
    const {num,n}=env,who=role==='student'?'Student self-report':row.subject==='respondent_adult'?'Parent self-report (adult)':row.subject==='family'?'Parent family report':'Parent report about the child',start=row.covered_start||row.period_start||'not available',end=row.covered_end||row.period_end||'not available';
    const prefix=`${who}; ${period.label}; ${start} to ${end}; ${row.wave}; ${label}`+(row.threshold?`; ${row.threshold}`:'')+(row.category_code?`; ${row.category_code}`:'');
    if(row.status!=='available')return `${prefix}; ${row.status.replaceAll('_',' ')}`;
    const totals=`response N ${n(row.sample_n)}; valid N ${n(row.valid_n)}; missing N ${n(row.missing_n)}; outside-range N ${n(row.outside_range_n)}`;
    if(row.kind==='continuous')return `${prefix}; mean ${num(row.mean)}; SD ${Number.isFinite(row.sd)?num(row.sd):'unavailable'}; ${totals}`;
    return `${prefix}; ${n(row.numerator)} ${row.numerator===1?'case':'cases'} / ${n(row.denominator)} valid responses (${num(100*row.proportion)}%); ${totals}`;
  }
  function semesterBindTooltip(mark,text,tooltip,points,position){
    const native=document.createElementNS('http://www.w3.org/2000/svg','title');native.textContent=text;mark.append(native);mark.setAttribute('aria-label',text);mark.setAttribute('aria-describedby',tooltip.id);
    const point={text,position};if(position)points.push(point);
    const showFocus=()=>{tooltip.textContent=text;tooltip.hidden=false;},showHover=()=>{
      const matches=position?points.filter(p=>Math.abs(p.position.x-position.x)<0.01&&Math.abs(p.position.y-position.y)<10):[point];
      tooltip.textContent=matches.length>1?'Overlapping points: '+matches.map(p=>p.text).join(' | '):text;tooltip.hidden=false;},hide=()=>{tooltip.hidden=true;};
    mark.onpointerenter=showHover;mark.onmouseenter=showHover;mark.onpointerleave=hide;mark.onmouseleave=hide;mark.onfocus=showFocus;mark.onblur=hide;
    mark.onkeydown=event=>{if(event.key==='Escape')hide();else if(event.key==='Enter'||event.key===' ')showFocus();};
  }
  function semesterGraph(host,rows,selected,range,env,overlay){
    const {el,notice,num,n}=env,visible=selected.visible_waves,role=env.chartRole;
    if(!rows.length){notice(host,'There are no results for this selection.');return;}
    const kind=rows[0].kind,roleChart=rows.some(r=>r.category_code&&['perpetrator_only','victim_only','both','neither'].includes(r.category_code));
    const mainRows=rows.filter(r=>visible.includes(r.wave)),overlayRows=(overlay?.rows||[]).filter(r=>visible.includes(r.wave));
    const periods=selected.academic_years.flatMap(year=>selected.semesters.map(semester=>({year,semester,key:year+':'+semester,label:year+'–'+(year+1)+' '+semester})));
    const value=row=>row.status==='available'?(row.kind==='continuous'?row.mean:row.proportion):null;
    const hasMain=mainRows.some(row=>Number.isFinite(value(row))),hasOverlay=overlayRows.some(row=>Number.isFinite(value(row)));
    if(!hasMain&&!hasOverlay){notice(host,visible.length?'No valid values are available for the visible series. Missing results are not zero.':'All chart series are hidden. The result tables below are unchanged.');return;}
    if(!range){notice(host,'The full scale range is not defined for this metric. Select auto zoom to show the available values.',true);return;}
    if(hasOverlay&&!overlay.range){notice(host,'The overlay scale range is unavailable. No overlay is substituted.',true);return;}
    const NS='http://www.w3.org/2000/svg',svg=document.createElementNS(NS,'svg'),width=Math.max(500,periods.length*115+170,(Number(host.clientWidth)||0)-48),height=370;
    const tooltip=el('div','notice semester-tooltip'),tooltipPoints=[];tooltip.id='semester-tooltip-'+role;tooltip.setAttribute('role','tooltip');tooltip.setAttribute('aria-live','polite');tooltip.hidden=true;
    svg.setAttribute('viewBox',`0 0 ${width} ${height}`);svg.setAttribute('width',width);svg.setAttribute('height',height);svg.setAttribute('class','semester-chart');svg.setAttribute('role','img');
    svg.setAttribute('aria-label',(roleChart?'Four exclusive roles, 100 percent stacked':kind==='continuous'?'Score means':'Proportions')+' by response semester'+(hasOverlay?'; dashed overlay has its own labelled right axis':'')+'. Exact values and denominators are in the tables below.');
    const add=(tag,attrs,text)=>{const node=document.createElementNS(NS,tag);for(const [k,v] of Object.entries(attrs))node.setAttribute(k,v);if(text!==undefined)node.textContent=text;svg.append(node);return node;};
    const [low,high]=range.range,scale=high-low||1,plotLeft=72,plotRight=width-(hasOverlay?95:30);
    const y=v=>250-190*(v-low)/scale,x=i=>plotLeft+(i+.5)*(plotRight-plotLeft)/Math.max(periods.length,1);
    for(let i=0;i<=4;i++){const v=low+scale*i/4;add('line',{x1:plotLeft,x2:plotRight,y1:y(v),y2:y(v),stroke:'#dce2ed'});add('text',{x:plotLeft-10,y:y(v)+4,'text-anchor':'end',fill:'#66758b','font-size':11},kind==='continuous'?num(v):num(v*100)+'%');}
    periods.forEach((p,i)=>add('text',{x:x(i),y:276,'text-anchor':'middle',fill:'#24354e','font-size':10},p.label));
    const colours=['#247b91','#b56a36','#526bba','#8e5d91','#587d45','#9d7044','#637082','#b44d68'],waveColour=wave=>wave==='T0'?colours[0]:colours[1];
    if(roleChart){
      const categories=['perpetrator_only','victim_only','both','neither'],groups=new Map();
      for(const row of mainRows){const k=[row.academic_year_start,row.semester,row.wave,row.threshold].join('|');if(!groups.has(k))groups.set(k,[]);groups.get(k).push(row);}
      for(const [key,items] of groups){
        if(items.every(r=>r.status!=='available'))continue;
        need(items.length===4&&categories.every(c=>items.filter(r=>r.category_code===c).length===1)&&items.every(r=>r.status==='available'&&r.denominator===items[0].denominator&&r.valid_n===items[0].valid_n&&Number.isSafeInteger(r.numerator)&&r.numerator>=0&&Number.isFinite(r.proportion)&&Math.abs(r.proportion-r.numerator/r.denominator)<1e-10)&&items[0].denominator>0&&items.reduce((sum,r)=>sum+r.numerator,0)===items[0].denominator,'Joint role counts are incomplete or inconsistent.');
        const [year,semester,wave,threshold]=key.split('|'),index=periods.findIndex(p=>String(p.year)===year&&p.semester===semester),series=[...new Set(mainRows.map(r=>r.wave+'|'+r.threshold))].sort(),offset=series.indexOf(wave+'|'+threshold),barWidth=Math.min(28,75/Math.max(series.length,1));let top=0;
        for(const [j,category] of categories.entries()){const row=items.find(r=>r.category_code===category),v=row.proportion,rect=add('rect',{x:x(index)+(offset-(series.length-1)/2)*barWidth-barWidth/2,y:y(top+v),width:barWidth-2,height:190*v,fill:colours[j],tabindex:0,'data-wave':wave});semesterBindTooltip(rect,semesterTooltipText(row,periods[index],semesterLabel(env.snapshot,selected.metric_id),role,env),tooltip,tooltipPoints,null);top+=v;}
      }
      add('text',{x:plotLeft,y:310,fill:'#24354e','font-size':11},'Stack order: perpetrator only, victim only, both, neither.');
    }else{
      const series=[...new Set(mainRows.map(r=>[r.wave,r.threshold||'',r.category_code||''].join('|')))];
      series.forEach((key,j)=>{
        const parts=key.split('|'),points=periods.map(p=>mainRows.find(r=>r.academic_year_start===p.year&&r.semester===p.semester&&r.wave===parts[0]&&(r.threshold||'')===parts[1]&&(r.category_code||'')===parts[2]));
        const useBars=kind!=='continuous'&&kind!=='binary'||selected.chart==='bars',colour=parts[2]?colours[j%colours.length]:parts[1]?(parts[0]==='T0'?(parts[1]==='any'?colours[0]:colours[4]):(parts[1]==='any'?colours[1]:colours[3])):waveColour(parts[0]);let segment=[];
        const flush=()=>{if(segment.length>1)add('polyline',{points:segment.join(' '),fill:'none',stroke:colour,'stroke-width':2,'pointer-events':'none','data-wave':parts[0],'data-threshold':parts[1],'data-series':'primary'});segment=[];};
        points.forEach((row,i)=>{const v=row?value(row):null;if(!Number.isFinite(v)){flush();return;}
          const px=x(i),py=y(v);let mark,markerX=px;
          if(useBars){const bw=Math.min(28,75/Math.max(series.length,1));markerX=px+(j-(series.length-1)/2)*bw;mark=add('rect',{x:markerX-bw/2,y:py,width:bw-2,height:Math.max(0,y(low)-py),fill:colour,tabindex:0,'data-wave':parts[0],'data-threshold':parts[1],'data-series':'primary'});}
          else{segment.push(px+','+py);mark=add('circle',{cx:px,cy:py,r:5,fill:colour,tabindex:0,'data-wave':parts[0],'data-threshold':parts[1],'data-series':'primary'});}
          semesterBindTooltip(mark,semesterTooltipText(row,periods[i],semesterLabel(env.snapshot,selected.metric_id),role,env),tooltip,tooltipPoints,useBars?null:{x:px,y:py});
          if(kind==='binary'&&Number.isFinite(row.ci_low)&&Number.isFinite(row.ci_high))add('line',{x1:markerX,x2:markerX,y1:y(row.ci_low),y2:y(row.ci_high),stroke:colour,'stroke-width':2,'pointer-events':'none'});
        });flush();
        add('text',{x:plotLeft+(j%3)*Math.max(150,(plotRight-plotLeft)/3),y:310+Math.floor(j/3)*14,fill:colour,'font-size':11},parts.filter(Boolean).join(' · '));
      });
    }
    if(hasOverlay){
      const [overlayLow,overlayHigh]=overlay.range.range,overlayScale=overlayHigh-overlayLow||1,oy=v=>250-190*(v-overlayLow)/overlayScale;
      for(let i=0;i<=4;i++){const v=overlayLow+overlayScale*i/4;add('text',{x:plotRight+8,y:oy(v)+4,fill:'#66758b','font-size':11},num(v));}
      for(const wave of selected.waves.filter(w=>visible.includes(w))){let segment=[];
        const flush=()=>{if(segment.length>1)add('polyline',{points:segment.join(' '),fill:'none',stroke:waveColour(wave),'stroke-width':2,'stroke-dasharray':'6 4','pointer-events':'none','data-wave':wave,'data-series':'overlay'});segment=[];};
        periods.forEach((p,i)=>{const row=overlayRows.find(r=>r.academic_year_start===p.year&&r.semester===p.semester&&r.wave===wave),v=row?value(row):null;
          if(!Number.isFinite(v)){flush();return;}const px=x(i),py=oy(v);segment.push(px+','+py);
          const mark=add('rect',{x:px-4,y:py-4,width:8,height:8,fill:waveColour(wave),tabindex:0,'data-wave':wave,'data-series':'overlay'});
          semesterBindTooltip(mark,semesterTooltipText(row,p,overlay.label+' mean score (overlay)',role,env),tooltip,tooltipPoints,{x:px,y:py});});flush();
      }
    }
    const wrapper=el('div','table-wrap semester-chart-wrap');wrapper.append(svg);host.append(wrapper,tooltip);
  }
  function semesterPanel(panel,entry,result,selected,range,env,overlay){
    const {el,notice,table,num,n,snapshot,state,scope,rerender}=env,role=entry.cube.role,options=state.semester_trends;
    const label=semesterLabel(snapshot,selected.metric_id),kind=result.rows[0]?.kind;
    panel.append(el('h3','',role==='student'?'Student self-report':'Parent report'));
    panel.append(el('p','caption',role==='student'?'Student responses.':'Bullying and SEC are parent reports about the child; PHQ describes the responding adult; FQOL describes the family.'));
    const workspace=el('div','workspace semester-chart-workspace'),aside=el('aside','panel semester-chart-settings'),chart=el('div','analysis-body');
    workspace.setAttribute('dir','rtl');aside.setAttribute('dir','ltr');chart.setAttribute('dir','ltr');workspace.append(aside,chart);panel.append(workspace);
    semesterPanelControls(aside,role,env,env.metrics);
    const lines=el('fieldset');lines.append(el('legend','','Show lines · this chart only'));
    for(const wave of selected.waves){const lab=el('label','check-option'),input=el('input');input.type='checkbox';input.checked=options.visible_lines[role].includes(wave);input.dataset.control=`semester:visible:${role}:${wave}`;input.setAttribute('aria-label',`${role==='student'?'Student':'Parent'} ${wave} chart line`);
      input.onchange=()=>{options.visible_lines[role]=input.checked?[...options.visible_lines[role],wave]:options.visible_lines[role].filter(value=>value!==wave);rerender();};lab.append(input,el('span','',wave));lines.append(lab);}
    if(overlay?.selected){const lab=el('label','check-option'),input=el('input');input.type='checkbox';input.checked=options.visible_overlay[role];input.dataset.control=`semester:visible:${role}:overlay`;input.setAttribute('aria-label',`${role==='student'?'Student':'Parent'} bullying overlay line`);
      input.onchange=()=>{options.visible_overlay[role]=input.checked;rerender();};lab.append(input,el('span','','Show bullying overlay'));lines.append(lab);}
    aside.append(lines);
    const axisText=(info,percentage)=>info?`${info.mode==='auto'?'Auto zoom':'Full scale'}: ${num(info.range[0]*(percentage?100:1))}–${num(info.range[1]*(percentage?100:1))}${percentage?'%':''}${info.extended?' (extended to include observed values outside the expected range)':''}`:'Full scale is not defined for this metric.';
    chart.append(el('p','caption',`Left axis: ${label} ${kind==='continuous'?'mean score':'proportion'} · ${axisText(range,kind!=='continuous')}. The same scale is used for both roles when comparable.`));
    chart.append(el('p','caption','Missing values are gaps; their status is in the table. Outside-range N is included in missing N.'));
    if(/^(TBV|TBP|CBV|CBP)|role|bully/i.test(selected.metric_id)||overlay?.selected)notice(chart,'Bullying experiences: past three months, grouped by response semester.');
    if(selected.metric_id.startsWith('bullying_roles_')){const order=[...new Set(result.rows.map(r=>r.wave+' '+r.threshold))].sort();chart.append(el('p','caption','For each semester, stacks run left to right: '+order.join(', ')+'. Each stack runs bottom to top: perpetrator only, victim only, both, neither.'));}
    if(selected.ci==='wilson_95_unclustered'&&result.rows.some(r=>r.kind==='binary'))notice(chart,'95% Wilson intervals are descriptive and not school-cluster-adjusted.');
    if(overlay?.error)notice(chart,overlay.error+' The primary results remain available; no overlay is substituted.',true);
    if(overlay?.result){const visibleOverlay=options.visible_overlay[role]&&overlay.result.rows.some(r=>options.visible_lines[role].includes(r.wave)&&r.status==='available'&&Number.isFinite(r.mean));
      if(visibleOverlay)chart.append(el('p','caption',`Right axis: ${overlay.label} mean score · ${axisText(overlay.range,false)}. Dashed lines with square markers are the ${role==='student'?'student self-report':'parent report about the child'} overlay: T0 teal, T1 orange. Overlaying series does not establish a correlation.`));
      else chart.append(el('p','caption','The selected overlay has no visible points in this chart. Its results remain in the overlay table.'));
      if(overlay.selection.metric_id===selected.metric_id)chart.append(el('p','caption','The selected overlay repeats the primary metric.'));
      if(!overlay.result.rows.some(r=>r.status==='available'&&Number.isFinite(r.mean)))notice(chart,'The requested bullying overlay has no valid values for this selection.');}
    const chartSelection={...selected,chart:options.chart,visible_waves:options.visible_lines[role]};
    try{semesterGraph(chart,result.rows,chartSelection,range,{...env,chartRole:role},overlay?.result&&options.visible_overlay[role]?{rows:overlay.result.rows,range:overlay.range,label:overlay.label}:null);}catch(error){notice(chart,error.message+' No chart was substituted.',true);return;}
    const columns={academic_year_start:'Academic year start',semester:'Semester',wave:'Wave',display:'Estimate',sample_n:'Response N',valid_n:'Valid N',missing_n:'Missing N',sd:'SD (raw)',outside_range_n:'Outside range N',metric_id:'Metric ID',kind:'Metric kind',unit:'Unit',subject:'Reported subject',threshold:'Threshold',category_code:'Category',status:'Status',period_start:'Semester start',period_end:'Semester end',covered_start:'Included start',covered_end:'Included end',partial_period:'Partial semester',numerator:'Numerator',denominator:'Denominator',proportion:'Proportion (raw)',mean:'Mean (raw)',ci_low:'CI lower (raw)',ci_high:'CI upper (raw)',ci_method:'CI method'};
    const formatted=rows=>rows.map(row=>({...row,display:row.status!=='available'?({no_responses:'No responses',no_valid_scores:'No valid scores',metric_unavailable:'Metric unavailable',outside_date_range:'Outside date range',suppressed:'Suppressed'}[row.status]||row.status):row.kind==='continuous'?`${num(row.mean)} (${num(row.sd)})`:row.proportion==null?'No valid denominator':`${n(row.numerator)} / ${n(row.denominator)} (${num(100*row.proportion)}%)`}));
    const metadata=semesterCSVMetadata(snapshot,state,scope,entry.cube,result,selected,entry.ref.sha256);
    table(panel,formatted(result.rows),columns,'semester-'+state.mode+'-'+role,false,{}, {type:'semester_trends',variable:selected.metric_id,metadata});
    if(overlay?.result){const detail=el('details');detail.append(el('summary','','Bullying overlay: results and CSV'));panel.append(detail);
      const overlayMetadata={...semesterCSVMetadata(snapshot,state,scope,entry.cube,overlay.result,overlay.selection,entry.ref.sha256),chart_series:'overlay'};
      table(detail,formatted(overlay.result.rows),columns,'semester-overlay-'+state.mode+'-'+role+'-'+overlay.selection.metric_id,false,{}, {type:'semester_trends',variable:overlay.selection.metric_id,metadata:overlayMetadata});}
    const quality=el('details');quality.append(el('summary','','Date provenance and exclusions'));panel.append(quality);
    table(quality,result.date_quality,{wave:'Wave',date_quality:'Date provenance',input_n:'Selected before dates N',included_n:'Included N'},'semester-date-provenance-'+role,false,{}, {type:'semester_provenance',metadata});
    table(quality,result.date_exclusions,{wave:'Wave',stage:'Date filter stage',remaining_n:'Remaining N',excluded_n:'Excluded N'},'semester-date-exclusions-'+role,false,{}, {type:'semester_provenance',metadata});
  }
  function mountSemester(env){
    const {host,snapshot,state,scope,loader,period,isCurrent,rerender,el,select,notice}=env,entries={},errors={};
    if(snapshot.minimum_cell_n!==0){notice(host,'Semester trends are unavailable for this suppression profile. No unfiltered results are substituted.',true);return;}
    for(const role of ['student','parent']){
      if(!semesterRoles[state.mode]?.includes(role)){errors[role]='This respondent is unavailable for the selected sample.';continue;}
      try{entries[role]=loader.load(snapshot,{...state,role},scope);}catch(error){errors[role]=error.message;}
    }
    const loading=Object.values(entries).filter(entry=>entry.status==='loading');
    if(loading.length){notice(host,'Loading and validating the selected protected semester assets…');Promise.all(loading.map(entry=>entry.promise)).then(()=>{if(isCurrent())rerender();});return;}
    const ready=Object.values(entries).filter(entry=>entry.status==='ready'),boundsList=ready.map(entry=>extent(entry.ref.extent)).filter(Boolean);
    if(!ready.length){const panels=el('div','semester-stacked');host.append(panels);
      for(const role of ['student','parent']){const panel=el('section','section panel semester-panel'),entry=entries[role];panels.append(panel);panel.append(el('h3','',role==='student'?'Student self-report':'Parent report'));
        notice(panel,(errors[role]||entry?.error||'Semester results unavailable.')+' No unfiltered result is substituted.',true);
        if(entry?.status==='error'){const retry=el('button','quiet','Retry '+role+' data');retry.type='button';retry.dataset.control='semester:retry:'+role;retry.onclick=()=>{loader.retry(entry.key);rerender();};panel.append(retry);}}
      return;}
    const bounds=boundsList.length?{from:boundsList.map(b=>b.from).sort()[0],to:boundsList.map(b=>b.to).sort().at(-1)}:null;
    const availableYears=semesterYears(ready),metrics=new Map();
    for(const entry of ready)for(const metric of [...(entry.cube.metrics||[]),...(entry.cube.joint_metrics||[])]){const id=semesterMetricId(metric);if(typeof id==='string'&&!metrics.has(id))metrics.set(id,metric);}
    if(!state.semester_trends){const oldDates=state.period_day_initialized&&day(state.period_day_from)&&day(state.period_day_to)&&state.period_day_from<=state.period_day_to;
      state.semester_trends={academic_years:availableYears,semesters:['S1','S2'],waves:['T0','T1'],from:oldDates?state.period_day_from:bounds?.from||'',to:oldDates?state.period_day_to:bounds?.to||'',metric_id:metrics.has('PHQ_total')?'PHQ_total':metrics.keys().next().value||'',threshold:'recurrent',ci:'none',chart:'line'};}
    const options=state.semester_trends,controls=el('div','controls');host.append(controls);
    if(options.axis===undefined)options.axis='full';
    if(options.overlay===undefined)options.overlay='none';
    if(!options.visible_lines)options.visible_lines={student:['T0','T1'],parent:['T0','T1']};
    for(const role of ['student','parent'])if(!Array.isArray(options.visible_lines[role]))options.visible_lines[role]=['T0','T1'];
    if(!options.visible_overlay)options.visible_overlay={student:true,parent:true};
    for(const role of ['student','parent'])if(typeof options.visible_overlay[role]!=='boolean')options.visible_overlay[role]=true;
    const displayError=semesterDisplayState(options,metrics);if(displayError){notice(host,displayError+' No broader result was substituted.',true);return;}
    function checks(label,key,choices){const field=el('fieldset');field.dataset.control='semester:'+key;field.append(el('legend','',label));
      for(const [value,text] of choices){const lab=el('label','check-option'),input=el('input');input.type='checkbox';input.checked=options[key].includes(value);input.dataset.control=`semester:${key}:${value}`;input.onchange=()=>{options[key]=input.checked?[...options[key],value]:options[key].filter(v=>v!==value);rerender();};lab.append(input,el('span','',text));field.append(lab);}controls.append(field);return field;}
    checks('Academic years','academic_years',[...new Set([...availableYears,...options.academic_years])].sort((a,b)=>a-b).map(y=>[y,`${y}–${y+1}`]));
    checks('Semesters','semesters',[['S1','S1 · Sep 1 to Jan 31'],['S2','S2 · Feb 1 to Aug 31']]);
    const waves=checks('Waves','waves',[['T0','T0'],['T1','T1']]),both=el('button','quiet','Both waves');both.type='button';both.dataset.control='semester:waves:both';both.onclick=()=>{options.waves=['T0','T1'];rerender();};waves.append(both);
    for(const [key,label] of [['from','Start date (Hong Kong, inclusive)'],['to','End date (Hong Kong, inclusive)']]){const lab=el('label','',label),input=el('input');input.type='date';input.value=options[key];input.dataset.control='semester:date:'+key;input.setAttribute('aria-label',label);input.onchange=()=>{options[key]=input.value;rerender();};lab.append(input);controls.append(lab);}
    select(controls,'Date source',String(state.batch),{false:'Only system or manually verified dates',true:'Also include accepted batch dates'},value=>{state.batch=value==='true';rerender();});
    const binaryMetric=metrics.get(options.metric_id)?.kind==='binary';
    host.append(el('p','caption','Each response is assigned to its response semester in Hong Kong time. T0 and T1 are separate series and may contain different respondents; this is not a paired change.'));
    let selected;try{selected=semesterSelection(state,{...options,ci:binaryMetric?options.ci:'none'});}catch(error){notice(host,error.message+' No broader result was substituted.',true);return;}
    if(!selected.academic_years.length||!selected.semesters.length||!selected.waves.length){notice(host,'No academic years, semesters or waves selected. Select at least one of each to display results.');return;}
    const results={},overlays={},overlayErrors={},overlayIds=['none','TBV_mean','TBP_mean','CBV_mean','CBP_mean'];
    if(!['full','auto'].includes(options.axis)||!overlayIds.includes(options.overlay)||!['none','prevalence','roles'].includes(options.bullying_display)||!['TBV','TBP','CBV','CBP'].includes(options.bullying_domain)||!['traditional','cyber'].includes(options.bullying_roles_domain)){notice(host,'Invalid chart, bullying display or overlay selection. No broader result was substituted.',true);return;}
    for(const role of ['student','parent']){
      const entry=entries[role];if(entry?.status==='error')errors[role]=entry.error;
      if(entry?.status==='ready')try{results[role]=semesterResultChecked(period.query(entry.cube,selected),snapshot,state,scope,role,selected);}catch(error){errors[role]=error.message;}
      if(entry?.status==='ready'&&results[role]&&options.overlay!=='none')try{
        const metric=entry.cube.metrics?.find(m=>semesterMetricId(m)===options.overlay),subject=role==='student'?'student_child':'parent_reported_child';
        need(metric&&metric.kind==='continuous'&&metric.unit==='score'&&metric.subject===subject,'The selected bullying mean score is unavailable or incompatible.');
        const overlaySelection={...selected,metric_id:options.overlay,ci:'none'};
        const result=semesterResultChecked(period.query(entry.cube,overlaySelection),snapshot,state,scope,role,overlaySelection);
        need(result.rows.every(row=>row.metric_id===options.overlay&&row.kind==='continuous'&&row.unit==='score'&&row.subject===subject),'The bullying overlay metric, unit or respondent is incompatible.');
        overlays[role]={result,selection:overlaySelection};
      }catch(error){overlayErrors[role]=error.message;}
    }
    const allRows=Object.values(results).flatMap(result=>result.rows),kind=allRows[0]?.kind||metrics.get(selected.metric_id)?.kind,
      primaryRange=semesterRange(allRows,selected.metric_id,kind,options.axis),overlayRows=Object.values(overlays).flatMap(value=>value.result.rows),
      overlayRange=options.overlay==='none'?null:semesterRange(overlayRows,options.overlay,'continuous',options.axis);
    const panels=el('div','semester-stacked');host.append(panels);
    for(const role of ['student','parent']){const panel=el('section','section panel semester-panel');panels.append(panel);
      if(errors[role]||!results[role]){panel.append(el('h3','',role==='student'?'Student self-report':'Parent report'));notice(panel,(errors[role]||'Semester results unavailable.')+' No unfiltered result is substituted.',true);
        const entry=entries[role];if(entry?.status==='error'){const retry=el('button','quiet','Retry '+role+' data');retry.type='button';retry.dataset.control='semester:retry:'+role;retry.onclick=()=>{loader.retry(entry.key);rerender();};panel.append(retry);}continue;}
      const overlay=options.overlay==='none'?null:{selected:true,label:semesterLabel(snapshot,options.overlay),range:overlayRange,
        result:overlays[role]?.result,selection:overlays[role]?.selection,error:overlayErrors[role]};
      semesterPanel(panel,entries[role],results[role],selected,primaryRange,{...env,metrics},overlay);
    }
  }
  return {createLoader,refFor,day,extent,academicPeriods,selection,csvMetadata,mount,present,createSemesterLoader,semesterRef,semesterSelection,semesterCSVMetadata,mountSemester};
})();

(() => {
const boot=window.STUDY2_LAZY_BOOTSTRAP||null;
const baselineSnapshot=boot?boot.off.snapshot:window.STUDY2_SNAPSHOT, root=document.querySelector('#content');
let S=boot?boot.on.snapshot:baselineSnapshot,activeScope=boot?boot.on.scope_export:window.STUDY2_SCOPE_EXPORT,eligibility=null,eligibilityLoading=true;
let bootstrapController=null,fullReady=!boot,fullPromise=null,fullError=null,pendingFull=null,requestedMode='on',pendingDownload=false;
const loadedScripts=new Map();
if(!S||S.format!=='study2_static_v1'){document.querySelector('#load-status').textContent="The snapshot did not load. Check that every file was uploaded.";return;}
const tabs=["Data quality & progress", "Descriptive statistics", "Independent parent analysis", "Matching evidence", "Family tracking", "Definitions & methods"];
let contentHost=root;
let qualityMount=null, qualitySelection=null,qualityUIState=null;
const sidebarPositions=new Map();
let renderEpoch=0;
const periodLoader=Study2PeriodUI.createLoader({getPeriod:()=>typeof Period==='undefined'?null:Period});
let semesterLoader=null;
const hasBootstrapSemesters=()=>Boolean(boot&&S.period_semester_selection?.status==='available'&&Array.isArray(S.period_semester_selection.refs)&&S.period_semester_selection.refs.some(ref=>ref?.mode==='abcd'&&ref.eligibility==='on'&&ref.status==='available'));
const initialReading=hasBootstrapSemesters()?'trends':'overview';
let page=0, state={grades:[...Grade.codes],mode:'abcd',role:'student',mainstream:false,sources:['all'],group:'all',reading:initialReading,trend_variable:'PHQ_total',trend_axis:'full',period_auto:false,variable:'PHQ_total',section:'scales',family:'all',result:'table',batch:false,from:'',to:''};
let parent={...state,sources:[...state.sources],grades:[...state.grades],mode:'independent_child',role:'parent'};
function bootstrapSemesterPage(i){const st=i===1?state:i===2?parent:null;return Boolean(boot&&!fullReady&&st?.reading==='trends'&&hasBootstrapSemesters());}
const n=v=>v===null||v===undefined?'—':Number(v).toLocaleString('en-HK');
const num=v=>v===null||v===undefined?'—':Number(v).toFixed(2);
const el=(tag,cls,text)=>{const x=document.createElement(tag);if(cls)x.className=cls;if(text!==undefined)x.textContent=text;return x;};
function section(title,note){const e=el('section','section');if(title)e.append(el('h2','',title));if(note)e.append(el('p','caption',note));contentHost.append(e);return e;}
function notice(host,text,warning=false){host.append(el('p','notice'+(warning?' warning':''),text));}
function cards(host,items){const g=el('div','grid'+(items.length===2?' two-cards':''));for(const [label,value,sub] of items){const c=el('div','card');c.append(el('div','label',label));if(!["Sample definition","Statistical scope"].includes(label))c.append(el('div','value',n(value)));if(sub)c.append(el('div','sub',sub));g.append(c);}host.append(g);}
function download(value,name,type='application/json'){if(eligibility&&!eligibility.bundle)return;if(eligibility?.configured)name=name.replace(/(?=\.[^.]+$)/,'-eligibility-'+eligibility.mode+'-'+String(eligibility.metadata().eligibility_revision).slice(0,12));const raw=typeof value==='string'?value:JSON.stringify(value,null,2);const url=URL.createObjectURL(new Blob([raw],{type}));const a=el('a');a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
function semesterCSVView(context){const selected=Source.selection(S,context.sources),options=Source.options(S),labels=Object.fromEntries(options.map(x=>[x.code,x.label]));labels.all='All sources';const all=selected[0]==='all'||selected.length===options.length;return {source:all?'all':selected.length===1?selected[0]:'multiple',source_selection:selected,source_status:!selected.length?'empty':all?'all':selected.length===1?'single':'pooled',source_labels:selected.map(x=>labels[x])};}
function csv(rows,columns,scope={}){const context=page===1?state:page===2?parent:null;const view=context?(typeof boot!=='undefined'&&boot&&typeof fullReady!=='undefined'&&!fullReady&&['semester_trends','semester_provenance'].includes(scope.type)?semesterCSVView(context):Array.isArray(context.sources)&&typeof Source!=='undefined'?Source.choose(S,context):S.views?.find(v=>v.mode===context.mode&&v.role===context.role&&v.mainstream===context.mainstream&&v.source===context.source)):null;const type=scope.type||(context?(context.reading==='paired'?'paired_changes':context.reading==='trends'?'period_summary':context.result==='distribution'?'histogram':'statistics'):'aggregate_table');const period=['period_summary','monthly_detail'].includes(type);const variable=scope.variable??(type==='histogram'?context?.variable:period?context?.trend_variable:undefined);const section=type==='statistics'?(scope.section??context?.section??'not_provided'):['paired_changes','histogram','transitions','monthly_detail'].includes(type)?'scales':type==='period_summary'?(variable==='volume'?'responses':'scales'):null;const family=type==='statistics'&&section==='scales'?(scope.family??context?.family??'not_provided'):type==='paired_changes'?'all':type==='transitions'?'bullying':type==='monthly_detail'&&variable==='volume'?'all':type==='histogram'||period&&variable!=='volume'?(scope.family??'not_provided'):null;const meta={...releaseMetadata(),...(eligibility?.configured?eligibility.metadata():{}),release_id:S.release_id,snapshot_generated_at:S.generated_at,report_version:S.report_version||'not_provided',dictionary_version:S.dictionary_version||'not_provided',inference_version:S.inference_version||'not_available',projection_version:S.descriptive_projection_version||'not_provided',download_type:type,...(context?{mode:context.mode,role:context.role,mainstream:String(context.mainstream),source:view?.source??context.source??'all',...(Array.isArray(context.sources)?{filter_source_codes:(view?.source_selection??context.sources).join('|'),source_all:String((view?.source_selection??context.sources).includes('all')),source_selection_status:view?.source_status||'unavailable',source_labels:(view?.source_labels||[]).join('|'),source_format:S.source_selection?.format||'not_provided'}:{}),group:context.group,reading:context.reading,...(Array.isArray(context.grades)?{filter_grade_codes:context.grades.join('|'),grade_anchor:view?.grade_anchor||view?.grade?.anchor||'not_provided',grade_format:S.grade?.format||'not_provided'}:{}),grouping_anchor:view?.grouping_anchor||'not_provided',source_filter_anchor:view?.source_filter_anchor||'not_provided',basis:scope.basis||(period?'calendar_response':type==='paired_changes'||type==='transitions'||context.reading==='paired'?'paired_valid':'wave_valid'),...(section?{section}:{}),...(family?{family}:{}),...(type==='histogram'?{selection_variable:variable}:{}),...(period?{selection_period_variable:variable,period_from:context.from,period_to:context.to,interval:'complete_month',timezone:'Asia/Hong_Kong',include_batch_dates:String(Boolean(context.batch))}:{})}:{})};Object.assign(meta,scope.metadata||{});rows=rows.map(r=>({...meta,...r}));columns={...Object.fromEntries(Object.keys(meta).map(k=>[k,k])),...columns};const keys=Object.keys(columns),cell=v=>'"'+String(v??'').replaceAll('"','""')+'"';return '\ufeff'+[keys.map(k=>cell(columns[k])).join(','),...rows.map(r=>keys.map(k=>cell(r[k])).join(','))].join('\r\n');}
function table(host, rows, columns, name, wide=false, rawColumns={}, csvScope={}) {
  if(!rows.length){host.append(el('p','empty',"There are no summary results to show for this selection."));return;}
  const bar=el('div','toolbar');bar.append(el('span','caption',`${n(rows.length)} aggregate results`));
  if(name){const button=el('button','quiet',"Download current table (CSV)");button.onclick=()=>download(csv(rows,{...columns,...rawColumns},csvScope),'study2-'+name+'.csv','text/csv;charset=utf-8');bar.append(button);}host.append(bar);
  const wrap=el('div','table-wrap'+(wide?' wide-text':'')),t=el('table'),head=el('thead'),keys=Object.keys(columns);
  const grouped=keys.includes('T0_n')&&keys.includes('T1_n');
  if(grouped){
    head.className='grouped';const first=el('tr'),second=el('tr');
    const tests=['test_n','p','dz'].filter(key=>keys.includes(key));
    for(const key of keys.filter(key=>!/^T[01]/.test(key)&&!tests.includes(key))){const cell=el('th','',columns[key]);cell.rowSpan=2;cell.scope='col';first.append(cell);}
    for(const wave of ['T0','T1']){const waveKeys=keys.filter(key=>key===wave||key.startsWith(wave+'_'));const cell=el('th','wave-head',wave);cell.colSpan=waveKeys.length;cell.scope='colgroup';first.append(cell);for(const key of waveKeys){const sub=el('th','numeric',columns[key]);sub.scope='col';second.append(sub);}}
    if(tests.length){const cell=el('th','wave-head',"T0 to T1 (complete pairs)");cell.colSpan=tests.length;cell.scope='colgroup';first.append(cell);for(const key of tests){const sub=el('th','numeric',columns[key]);sub.scope='col';second.append(sub);}}
    head.append(first,second);
  }else{const row=el('tr');for(const [i,title]of Object.values(columns).entries()){const cell=el('th',i?'numeric':'',title);cell.scope='col';row.append(cell);}head.append(row);}
  t.append(head);const body=el('tbody');
  for(const row of rows){const r=el('tr');for(const [i,key]of keys.entries()){const value=row[key],cell=el('td',i&&!wide?'numeric':'',value===null||value===undefined?'—':typeof value==='number'?n(value):String(value));if(['test_n','p','dz'].includes(key))cell.title=inferenceNote(row.inference_status)+(row.mean_change===null||row.mean_change===undefined?'':' Paired mean change: '+num(row.mean_change)+"; change SD: "+num(row.sd_change));r.append(cell);}body.append(r);}
  t.append(body);wrap.append(t);host.append(wrap);
}
function select(host,label,value,options,onchange){const lab=el('label','',label),s=el('select');s.dataset.control='select:'+label;s.setAttribute('aria-label',label);for(const [key,text]of Object.entries(options)){const opt=el('option','',text);opt.value=key;s.append(opt);}s.value=String(value);s.onchange=()=>onchange(s.value);lab.append(s);host.append(lab);return s;}
function chart(host,labels,series,title){const panel=el('div','panel');panel.append(el('h3','',title));const valid=series.flatMap(s=>s.values).filter(v=>v!==null&&Number.isFinite(v));if(!labels.length||!valid.length){panel.append(el('p','empty',"There are no valid values to show."));host.append(panel);return;}const legend=el('div','legend');series.forEach((s,i)=>{const k=el('span');k.append(el('i','dot '+(i?'blue':'teal')),document.createTextNode(s.name));legend.append(k);});panel.append(legend);const NS='http://www.w3.org/2000/svg',svg=document.createElementNS(NS,'svg');svg.setAttribute('viewBox','0 0 720 290');svg.setAttribute('class','chart');svg.setAttribute('role','img');svg.setAttribute('aria-label',title);const titleNode=document.createElementNS(NS,'title');titleNode.textContent=title;svg.append(titleNode);const lo=Math.min(0,...valid),hi=Math.max(1,...valid),h=195,w=615,step=w/labels.length;
const add=(tag,attrs,text)=>{const x=document.createElementNS(NS,tag);for(const [k,v]of Object.entries(attrs))x.setAttribute(k,v);if(text!==undefined)x.textContent=text;svg.append(x);return x;};
for(let i=0;i<=4;i++){const v=lo+(hi-lo)*i/4,y=225-h*i/4;add('line',{x1:65,x2:680,y1:y,y2:y,stroke:'#e1e9e6'});add('text',{x:55,y:y+4,'text-anchor':'end',fill:'#60777a','font-size':11},Math.abs(v)<10?v.toFixed(1):Math.round(v).toLocaleString());}
labels.forEach((label,j)=>{const x=65+j*step;series.forEach((s,i)=>{const v=s.values[j];if(v===null||v===undefined)return;const y=225-h*(v-lo)/(hi-lo),zero=225-h*(0-lo)/(hi-lo);const r=add('rect',{x:x+step*.12+i*step*.35,y:Math.min(y,zero),width:Math.max(1,step*.31),height:Math.max(1,Math.abs(zero-y)),fill:i?'#86afb8':'#176b6d',rx:1});const tt=document.createElementNS(NS,'title');tt.textContent=`${label} · ${s.name}: ${v}`;r.append(tt);});if(labels.length<15||j%Math.ceil(labels.length/10)===0)add('text',{x:x+step/2,y:250,'text-anchor':'middle',fill:'#60777a','font-size':11},String(label));});panel.append(svg);host.append(panel);}
function periodLineChart(host,points,title,key,axis,periodLabel) {
  const binary=points.some(point=>point.kind==='binary');
  const panel=el('div','panel');panel.append(el('h3','',title+' · T0 → T1'),el('p','caption',periodLabel+"; each wave is the responses inside the period, not equally spaced calendar time"));
  const values=points.map(point=>point.value).filter(value=>value!==null&&Number.isFinite(value));
  if(!values.length){notice(panel,S.minimum_cell_n>0?"There is no displayable total in the selected period. See the month note above or use \"use the displayable period\"; the monthly audit detail can still be downloaded.":"There are no valid scores in the selected period. Check the months, the date source and the monthly detail.");host.append(panel);return;}
  const [low,high]=binary?[0,1]:trendBounds(key,values,axis),range=high-low||1;
  panel.append(el('p','caption',(binary?"Prevalence proportion axis (0–1): ":axis==='auto'&&key!=='volume'?"Vertical axis auto-scaled: ":"Vertical axis full range: ")+num(low)+'–'+num(high)));
  const NS='http://www.w3.org/2000/svg',svg=document.createElementNS(NS,'svg');svg.setAttribute('viewBox','0 0 720 310');svg.setAttribute('class','chart');svg.setAttribute('role','img');svg.setAttribute('aria-label',title+'，'+periodLabel+'；'+points.map(point=>point.period+' '+(point.value===null?"not provided or suppressed":num(point.value)+(key==='volume'?', response N '+n(point.sample_n):', valid N '+n(point.valid_n)))).join('；'));
  const add=(tag,attrs,text)=>{const node=document.createElementNS(NS,tag);for(const [name,value]of Object.entries(attrs))node.setAttribute(name,value);if(text!==undefined)node.textContent=text;svg.append(node);return node;};
  const x=index=>180+index*360,y=value=>225-175*(value-low)/range;
  for(let tick=0;tick<=4;tick++){const value=low+range*tick/4,pos=y(value);add('line',{x1:65,x2:680,y1:pos,y2:pos,stroke:'#e1e7f0'});add('text',{x:55,y:pos+4,'text-anchor':'end',fill:'#66758b','font-size':11},key==='volume'?n(Math.round(value)):num(value));}
  for(const segment of trendSegments(points)){if(segment.length>1)add('polyline',{points:segment.map(point=>x(point.index)+','+y(point.value)).join(' '),fill:'none',stroke:'#526b93','stroke-width':2.5});}
  points.forEach((point,index)=>{
    add('text',{x:x(index),y:258,'text-anchor':'middle',fill:'#24354e','font-size':13},point.period);
    add('text',{x:x(index),y:280,'text-anchor':'middle',fill:'#66758b','font-size':11},key==='volume'?'Response N = '+n(point.sample_n):'Valid N = '+n(point.valid_n));
    if(point.value===null){add('text',{x:x(index),y:130,'text-anchor':'middle',fill:'#66758b','font-size':12},point.status==='suppressed'?"the whole period is suppressed":point.status==='unavailable'?"the summary is incomplete":"there are no valid scores");return;}
    const dot=add('circle',{cx:x(index),cy:y(point.value),r:6,fill:index?'#df8751':'#247b91',stroke:'white','stroke-width':2,tabindex:0});
    const tip=document.createElementNS(NS,'title');tip.textContent=point.period+'；'+periodLabel+'；'+(key==='volume'?"Response N="+n(point.value):point.kind==='binary'?"Proportion="+num(point.value)+"; numerator="+n(point.numerator)+"; denominator="+n(point.denominator)+"; missing N="+n(point.missing_n):"Mean="+num(point.value)+'；SD='+num(point.sd)+"; valid N="+n(point.valid_n)+"; missing N="+n(point.missing_n));dot.append(tip);
    add('text',{x:x(index),y:Math.max(20,y(point.value)-15),'text-anchor':'middle',fill:'#24354e','font-size':14,'font-weight':650},key==='volume'?n(point.value):num(point.value));
  });
  panel.append(svg);host.append(panel);
}
function chosenView(st){if(Array.isArray(st.sources))return Source.choose(S,st);const v=S.views.find(v=>v.mode===st.mode&&v.role===st.role&&v.mainstream===st.mainstream&&v.source===st.source);if(!v)return null;const decode=t=>Array.isArray(t)?t:t.rows.map(row=>Object.fromEntries(t.columns.map((c,i)=>[c,row[i]])));const view={...v};for(const key of ['statistics','changes','histograms','paired_histograms','transitions'])if(key in view)view[key]=decode(view[key]);if(view.trends)view.trends=view.trends.map(period=>({...period,statistics:decode(period.statistics)}));try{return Grade.all(st.grades??Grade.codes)?view:Grade.pool(S,view,st.grades);}catch(error){return {...view,grade_error:error.message};}}
function statValue(row){if(!row)return "Not provided";if(row.suppressed)return "Suppressed (small sample)";if(row.kind==='continuous')return `${num(row.mean)} (${num(row.sd)})`;return row.denominator?`${n(row.numerator)} / ${n(row.denominator)} (${num(100*row.proportion)}%)`:"Missing";}

/* Pure display models: no scoring, wave selection or suppression changes. */
function familyOf(key) {
  if (key.startsWith('PHQ_') || key === 'phq_band') return 'PHQ';
  if (key.startsWith('FQOL_')) return 'FQOL';
  if (key.startsWith('SEC_')) return 'SEC';
  return key.startsWith('dem_') ? 'demographics' : 'bullying';
}
function scoreMeaning(key) {
  if (key.startsWith('PHQ_')) return key === 'PHQ_total' ? "0–12; higher means more reported symptoms" : "0–6; higher means more reported symptoms";
  if (key.startsWith('FQOL_')) return "1-5; higher means higher reported family quality of life";
  if (key.startsWith('SEC_')) return "1-4; higher means higher reported social-emotional competence";
  if (key.endsWith('_mean')) return "0-4; higher means a more frequent reported rate";
  return '';
}
function pValue(value) { return value===null||value===undefined ? '—' : value<0.001 ? '<0.001' : value.toFixed(3); }
function inferenceNote(status) {
  return {estimated:"Two-sided paired t test; no multiple-comparison correction. Cohen's dz = mean of the per-person differences / SD of the differences; direction is T1 - T0.",suppressed:"There are not enough complete pairs to meet the disclosure threshold, so the statistic is suppressed.",insufficient_pairs:"There are not enough complete pairs, so no test or effect size was estimated.",zero_change_variance:"All per-person differences are identical, so the change SD is zero. No test or effect size was estimated."}[status]||"There is no usable formal paired comparison, or the same adult is not confirmed. Per-wave means are not used as a substitute for a paired test.";
}
function comparisonRows(selected, changes=[]) {
  const pairs = new Map();
  for (const row of selected) {
    const key = row.variable_id + '|' + row.category_code;
    if (!pairs.has(key)) {
      const test=row.kind==='continuous'?changes.find(test=>test.variable_id===row.variable_id&&test.group===row.group):null;
      pairs.set(key, {variable_id:row.variable_id,group:row.group,category_code:row.category_code,item:row.variable, category:row.category || '', unit:row.unit, scale:scoreMeaning(row.variable_id).split(';')[0],test_n:test?.paired_valid_n??null,p:pValue(test?.p_value),dz:num(test?.cohen_dz),p_value:test?.p_value??null,cohen_dz:test?.cohen_dz??null,mean_change:test?.mean_change??null,sd_change:test?.sd_change??null,inference_status:test?.inference_status||'not_available',test_basis:'paired_valid',formal_pairs_n:test?.pairs_n??null,paired_missing_n:test?.paired_missing_n??null,paired_only_t0_valid_n:test?.only_t0_valid_n??null,paired_only_t1_valid_n:test?.only_t1_valid_n??null,paired_both_missing_n:test?.both_missing_n??null,paired_t0_mean:test?.t0_mean??null,paired_t1_mean:test?.t1_mean??null,pair_detail_status:test?.pair_detail_status||'not_provided'});
    }
    const target = pairs.get(key);
    target[row.wave] = statValue(row);
    target[row.wave + '_n'] = row.valid_n;
    target[row.wave + '_missing'] = row.missing_n;
    for(const field of ['sample_n','outside_range_n','mean','sd','numerator','denominator','proportion'])target[row.wave+'_'+field]=row[field]??null;
  }
  return [...pairs.values()];
}
function periodComparison(periods, variable) {
  // Merge only visible sufficient statistics. A hidden month blocks the WHOLE
  // wave; do not drop it, infer it, or show an unweighted mean of monthly means.
  return ['T0','T1'].map(wave=>{
    const counts=periods.map(period=>period.counts[wave]);
    const sample=counts.some(value=>value===null||value===undefined)?null:counts.reduce((sum,value)=>sum+value,0);
    const base={period:wave,value:null,sample_n:sample,valid_n:null,missing_n:null,sd:null};
    if(variable==='volume')return {...base,value:sample,status:sample===null?'suppressed':'estimated'};
    const stats=periods.map(period=>period.statistics.find(row=>row.wave===wave&&row.variable_id===variable));
    if(stats.some((row,index)=>!row&&counts[index]!==0||row&&(row.suppressed||row.valid_n===null||row.missing_n===null)))return {...base,status:'suppressed'};
    let total=0,mean=0,m2=0,missing=0;
    for(const row of stats){
      if(!row)continue;missing+=row.missing_n;
      const size=row.valid_n;if(!size)continue;
      if(!Number.isFinite(row.mean)||(size>1&&!Number.isFinite(row.sd)))return {...base,status:'unavailable'};
      const next=total+size,difference=row.mean-mean;
      m2+=(size>1?(size-1)*row.sd*row.sd:0)+difference*difference*total*size/next;
      mean+=difference*size/next;total=next;
    }
    return {...base,value:total?mean:null,valid_n:total,missing_n:missing,sd:total>1?Math.sqrt(Math.max(0,m2/(total-1))):null,status:total?'estimated':'no_valid_scores'};
  });
}
function availablePeriod(periods, variable) {
  // Choose by availability and calendar length only, never by score values.
  // Keep masked months as boundaries; an explicit zero month may stay in a run.
  const ordered=[...periods].sort((a,b)=>a.period.localeCompare(b.period));
  const monthNumber=period=>{const [year,month]=period.split('-').map(Number);return year*12+month-1;};
  let run=[],best=null;
  function consider() {
    if(!run.length)return;
    const points=periodComparison(run,variable);
    const comparable=points.every(point=>point.status==='estimated'&&Number.isFinite(point.value)&&(variable==='volume'?point.sample_n>0:point.valid_n>0));
    if(comparable&&(!best||run.length>=best.months))best={from:run[0].period,to:run.at(-1).period,months:run.length};
  }
  for(const period of ordered){
    const points=periodComparison([period],variable);
    const visible=points.every(point=>['estimated','no_valid_scores'].includes(point.status)&&Number.isFinite(point.sample_n));
    if(run.length&&(!visible||monthNumber(period.period)!==monthNumber(run.at(-1).period)+1)){consider();run=[];}
    if(visible)run.push(period);
  }
  consider();return best;
}
function periodSelection(periods, variable, selected) {
  const suggested=availablePeriod(periods,variable),automatic=selected.period_auto!==false;
  return {automatic,suggested,
    from:automatic?suggested?.from||periods[0].period:selected.from||periods[0].period,
    to:automatic?suggested?.to||periods.at(-1).period:selected.to||periods.at(-1).period};
}
function periodIssues(periods, variable) {
  return ['T0','T1'].map(wave=>{
    const issues={wave,suppressed:[],unavailable:[],counts_suppressed:[]};
    for(const period of periods){
      const point=periodComparison([period],variable).find(point=>point.period===wave);
      if(point.status==='suppressed')issues.suppressed.push(period.period);
      if(point.status==='unavailable')issues.unavailable.push(period.period);
      if(point.sample_n===null)issues.counts_suppressed.push(period.period);
    }
    return issues;
  });
}
function trendSegments(points) {
  const segments=[];let current=[];
  points.forEach((point,index)=>{if(point.value!==null&&Number.isFinite(point.value))current.push({...point,index});else if(current.length){segments.push(current);current=[];}});
  if(current.length)segments.push(current);return segments;
}
function trendBounds(key,values,axis) {
  const bounds=key.startsWith('PHQ_')?[0,key==='PHQ_total'?12:6]:key.startsWith('FQOL_')?[1,5]:key.startsWith('SEC_')?[1,4]:key.endsWith('_mean')?[0,4]:[0,Math.max(1,...values)];
  if(axis!=='auto'||key==='volume')return [Math.min(bounds[0],...values),Math.max(bounds[1],...values)];
  const low=Math.min(...values),high=Math.max(...values),pad=Math.max((high-low)*0.15,0.05);
  return [Math.min(low,Math.max(bounds[0],low-pad)),Math.max(high,Math.min(bounds[1],high+pad))];
}
function readingBasis(st) {
  if (st.reading === 'trends') return "Responses inside the period · calendar_response";
  return st.reading === 'paired' ? "Same longitudinal units · paired_valid" : "Each wave separately valid · wave_valid";
}
function stageBucket(stage) {
  if (['1.1','1.3/2.1.1/2.1.2'].includes(stage)) return 0;
  if (stage === '2.1.3') return 1;
  if (['2.1.4','2.1.5','2.1.6'].includes(stage)) return 2;
  return 3;
}
/* End pure display models. */
const families = {all:"All scales",PHQ:"PHQ",FQOL:"FQOL family quality of life",SEC:"SEC",bullying:"Bullying indicators"};
function pageHeading(title, note) {
  const heading=el('div','page-heading');
  heading.append(el('p','eyebrow','STUDY 2 / RESEARCH WORKSPACE'),el('h2','',title));
  if(note) heading.append(el('p','caption',note));
  root.append(heading);
}
function switches(host, options, selected, changed, label) {
  const bar=el('div','switcher');bar.setAttribute('role','group');bar.setAttribute('aria-label',label);
  for(const [key,text] of Object.entries(options)) {
    const button=el('button','',text);button.dataset.control='switch:'+label+':'+key;button.type='button';button.setAttribute('aria-pressed',String(key===selected));
    button.onclick=()=>{changed(key);render();};bar.append(button);
  }
  host.append(bar);
}
function selectReading(st,value){st.reading=value;if(boot&&!fullReady&&value!=='trends')requestFull({type:'page'});}
function sampleSummary(st, view) {
  const selected=view.counts?.[st.group] || {}, band=el('section','sample-summary');
  band.setAttribute('aria-label',"Current analysis sample");
  const top=el('div','summary-top'),description=el('div');
  description.append(el('p','eyebrow',st.reading==='trends'?"Sample before date filtering":"Currently selected sample"),el('h3','',S.modes[st.mode]));
  const numbers=el('div','summary-n');
  for(const wave of ['T0','T1']) {const item=el('div');item.append(el('span','wave',wave+' response N'),el('strong','',n(selected[wave])));numbers.append(item);}
  top.append(description,numbers);band.append(top);
  const chips=el('div','chips');
  for(const [i,text] of [readingBasis(st).split(' · ')[0],st.role==='student'?"Student respondents":"Parent respondents",st.mainstream?"Mainstream schools only":"All schools",S.groups[st.group],view.source_labels?.length?view.source_labels.join(', '):view.source_status==='empty'?'No sources selected':S.source_names[st.source]||'All sources'].entries()) chips.append(el('span','chip'+(i===0?' basis':''),text));
  band.append(chips);
  let note=st.reading==='paired'?"The formal sample and the metric-specific valid N are shown separately. The paired valid N can differ between scales.":st.reading==='trends'?"The month and date-source filters are not applied here. The in-period N is shown below. The T0 and T1 respondents can differ.":"N is the number of selected responses. Each metric deducts its own missing values. The respondents answering at T0 and T1 can differ, so this is not read as a per-person change.";
  if(st.reading==='overview'&&['acbd','efmatched','independent_child','independent_adult'].includes(st.mode)) note="The sample is limited to the same longitudinal units, but each wave still deducts its own metric missing values. For a per-person change, select Longitudinal comparison and use the units that are valid in both waves.";
  if(st.mode.startsWith('independent')) note+=' Independent-parent waves are separate and do not contribute to first-tab BD/E/F/EF.';
  band.append(el('p','summary-description',note));
  const anchorNames={wave_response:'that wave response',wave_student:'that wave student',student_T0:'student baseline',BD_parent_T0:'BD parent baseline',independent_parent_T0:'independent parent baseline',wave_role_response:'that wave respondent'};
  if(view.grouping_anchor)band.append(el('p','caption','Grouping anchor: '+(anchorNames[view.grouping_anchor]||view.grouping_anchor)+'. Source filter anchor: '+(anchorNames[view.source_filter_anchor]||view.source_filter_anchor)+'. These descriptive filters do not inherit the first-tab entry selection.'));
  contentHost.append(band);
}
function appendStageSummary(host) {
  const labels=["Import and standardisation","School names and submission eligibility","Identity, repeats and manual corrections","Final responses and pairings"];
  const notes=["Original submissions; the source record is kept","School names are tidied and submission eligibility is checked; counted in submissions","Submissions and identity groups are read separately; a kept response is not necessarily selected into T0 or T1","Responses, AC/BD and E/F/EF cannot be added together"];
  const display=el('div','stage-cards');
  for(let index=0;index<4;index++) {
    const card=el('article','stage-card');card.append(el('div','step','0'+(index+1)),el('h3','',labels[index]));
    const rows=S.stages.filter(row=>stageBucket(row['階段'])===index);
    if(!rows.length) card.append(el('div','stage-value',"Not provided in this release"));
    for(const row of rows) {card.append(el('p','',row['階段']),el('div','stage-value',row['數量／結果']));}
    card.append(el('p','',notes[index]));display.append(card);
  }
  host.append(display);
}

function overview() {
  const exported=activeScope;
  const reasons={
    exact_scope_incompatible_with_suppression:'Exact first-tab filtering is unavailable under this snapshot\'s cell-suppression policy. Existing aggregate analyses remain available.',
    complete_published_records_required:'Exact first-tab filtering requires the complete published record artifact. Export a compatible release; other tabs remain available.',
    compatible_scope_export_required:'Exact first-tab filtering requires a compatible scope export. Other validated aggregate tabs remain available.'
  };
  // A same-release sidecar can still belong to an unsuppressed export.
  // Only explicit, consistent zero-threshold snapshot metadata permits it.
  if(!Number.isSafeInteger(S.minimum_cell_n)||S.minimum_cell_n!==0||S.small_sample_policy!=='none'){
    pageHeading(tabs[0],'First-tab filters do not change the other tabs or published matching.');
    notice(root,typeof S.minimum_cell_n==='number'&&S.minimum_cell_n>0?reasons.exact_scope_incompatible_with_suppression:
      'Exact first-tab filtering is unavailable because this snapshot has missing or inconsistent cell-suppression settings. Other aggregate tabs remain available.',true);return;
  }
  if(!exported||exported.format!=='study2_static_scope_export_v1'||exported.status!=='available'||
     exported.release_id!==S.release_id||typeof Study2Scope==='undefined'||typeof Study2Quality==='undefined'||
     !/^[0-9a-f]{64}$/.test(exported.index_revision||'')){
    pageHeading(tabs[0],'First-tab filters do not change the other tabs or published matching.');
    notice(root,reasons[exported?.code]||reasons.compatible_scope_export_required,true);return;
  }
  try{Study2Scope.validate(exported.index);if(exported.index.meta.release_id!==S.release_id)throw Error('release_mismatch');}
  catch{pageHeading(tabs[0]);notice(root,'The scope index is unsupported or incompatible with this release. Request a compatible export; other tabs remain available.',true);return;}
  const host=el('div');root.append(host);
  qualityMount=Study2Quality.mount(host,exported.index,{
    indexRevision:exported.index_revision,
    ...(S.release_context?{onDownload:value=>download({...value,release_context:S.release_context},"study2-quality-aggregate.json")}:{}),
    ...(eligibility?.configured?{eligibilityFor:({result})=>eligibility.quality(result)}:{}),
    schoolProjectionFor:({key,result})=>{
      // Lookup supplied, locally validated public projections only. This does
      // not query school signatures or reconstruct a record-to-label binding.
      const wanted=JSON.stringify(Study2Scope.normalizeSelection(exported.index,result.scope));
      const bound=(exported.school_bindings||[]).find(row=>JSON.stringify(Study2Scope.normalizeSelection(exported.index,row.scope))===wanted);
      return bound?{key,validatedBy:'R03-r3',projection:bound.projection}:null;
    }
  });
  if(qualityUIState)qualityMount.setUIState(qualityUIState);else if(qualitySelection)qualityMount.setSelection(qualitySelection);
  reviewWorkload();
}
function controls(st, independent) {
  const workspace=el('div','workspace'),sidebar=el('aside','sample-sidebar'),body=el('div','analysis-body');sidebar.setAttribute('aria-label',"Analysis sample filters");sidebar.dataset.sidebar=independent?'independent':'descriptive';
  const title=el('div','sidebar-title');title.append(el('h3','',"Select the analysis sample"));const reset=el('button','',"Clear filters");reset.type='button';reset.dataset.control='clear-filters';reset.onclick=()=>{Object.assign(st,{mainstream:false,sources:['all'],group:'all',grades:[...Grade.codes]});render();};title.append(reset);sidebar.append(title);
  function group(title){const block=el('div','control-group');block.append(el('div','control-title',title));sidebar.append(block);return block;}
  const sample=group("01  Sample and respondent"),modeNames=Object.fromEntries(Object.entries(S.modes).filter(([key])=>key.startsWith('independent_')===independent));
  select(sample,"Analysis sample",st.mode,modeNames,value=>{st.mode=value;render();});
  if(!independent)select(sample,"Respondent",st.role,{student:"Student",parent:"Parent"},value=>{st.role=value;st.section='scales';render();});
  const scope=group("02  School scope");select(scope,"School scope",String(st.mainstream),{false:"All schools (first-page basis)",true:"Mainstream schools only"},value=>{st.mainstream=value==='true';render();});
  const advanced=group("03  Child grouping");select(advanced,"Child gender / school stage",st.group,S.groups,value=>{st.group=value;render();});
  const sources=group('04  Data sources'),field=el('fieldset'),legend=el('legend','','Sources'),sourceActions=el('div','page-actions');field.append(legend);sources.append(field);
  const selectedSources=Source.selection(S,st.sources),sourceOptions=Source.options(S),isAll=selectedSources.includes('all');
  for(const [name,codes]of [['All sources',['all']],['No sources',[]]]){const b=el('button','quiet',name);b.type='button';b.dataset.control='source-action:'+name;b.setAttribute('aria-pressed',String(name==='All sources'?isAll:!selectedSources.length));b.onclick=()=>{st.sources=[...codes];render();};sourceActions.append(b);}field.append(sourceActions);
  for(const {code,label:text}of sourceOptions){const label=el('label','check-option'),input=el('input');input.type='checkbox';input.dataset.source=code;input.dataset.control='source:'+code;input.checked=isAll||selectedSources.includes(code);input.onchange=()=>{const values=new Set(isAll?sourceOptions.map(o=>o.code):selectedSources);input.checked?values.add(code):values.delete(code);st.sources=Source.selection(S,[...values]);render();};label.append(input,document.createTextNode(text));field.append(label);}
  field.append(el('p','caption',sourceOptions.some(o=>o.code==='unknown')?'All sources includes Other / unidentified. Named combinations include only checked sources. No sources selects zero responses.':'All sources includes the complete published intake. No sources selects zero responses.'));
  const grades=group('05  Child grade'),actions=el('div','page-actions');
  for(const [name,codes]of [['All grades',Grade.codes],['Known grades',Grade.codes.slice(0,12)],['No grades',[]]]){const b=el('button','quiet',name);b.type='button';b.dataset.control='grade-action:'+name;b.onclick=()=>{st.grades=[...codes];render();};actions.append(b);}grades.append(actions);
  for(const code of Grade.codes){const label=el('label','check-option'),input=el('input');input.type='checkbox';input.dataset.grade=code;input.dataset.control='grade:'+code;input.checked=(st.grades??Grade.codes).includes(code);input.onchange=()=>{const values=new Set(st.grades??Grade.codes);input.checked?values.add(code):values.delete(code);st.grades=Grade.selection([...values]);render();};label.append(input,document.createTextNode(' '+code));grades.append(label);}
  grades.append(el('p','caption','All includes Unknown. Longitudinal cohorts use baseline grade. Grade filtering does not change the first tab.'));
  sidebar.append(el('p','caption',"Only published aggregates are selected. Longitudinal grouping is fixed at baseline. The nine groups overlap and cannot be added."));
  workspace.append(sidebar,body);root.append(workspace);contentHost=body;return body;
}
function research(independent=false) {
  const st=independent?parent:state;
  pageHeading(independent?"Independent parent analysis":"Descriptive statistics",independent?"No student questionnaire is required as an anchor. The independent baseline and the follow-up at least 90 days later are counted separately.":"Choose the sample and the respondent first, then view the per-wave results, the complete pairs or the response-month trends.");
  controls(st,independent);
  if(st.reading==='trends'&&(S.period_semester_selection||(S.period_selection&&S.minimum_cell_n===0))){
    switches(contentHost,{overview:"Research overview",paired:"Longitudinal comparison",trends:"Period trends"},st.reading,value=>selectReading(st,value),"Reading mode");
    combinedTrends(st);return;
  }
  const view=chosenView(st);
  if(!view){notice(contentHost,"This release does not provide that analysis.");return;}
  if(view.source_error||view.source_status==='empty'){sampleSummary(st,view);notice(contentHost,view.source_notice||(view.source_error?'This source selection is unavailable in this export.':'No sources selected. Zero responses are selected.'),Boolean(view.source_error));return;}
  if(view.source_notice)notice(contentHost,view.source_notice);
  if(view.grade_error){notice(contentHost,view.grade_error,true);return;}
  if(view.grade_custom){notice(contentHost,'Selected grades: '+(st.grades.join(', ')||'None')+'. Grade anchor: '+({student_wave:'selected student grade at each wave',student_T0:'selected student grade at baseline',parent_report_wave:'child grade reported by parent at each independent wave',parent_report_T0:'child grade reported by parent at independent baseline'}[view.grade_anchor])+'. Custom-grade p-values and dz are unavailable.');}
  sampleSummary(st,view);
  switches(contentHost,{overview:"Research overview",paired:"Longitudinal comparison",trends:"Period trends"},st.reading,value=>selectReading(st,value),"Reading mode");
  if(independent){const details=el('details'),summary=el('summary','',"Independent-parent totals for this release (not affected by the current filters)");details.append(summary);const c=S.independent_counts;cards(details,[["Independent-parent baselines",c.baselines],["Same child across waves",c.child_report_pairs,"The responding adult may change"],["Same adult across waves",c.same_adult_pairs],["Same adult, alternative T1",c.same_adult_alternative_T1]]);contentHost.append(details);}
  if(!(st.mode==='acbd'&&st.reading==='paired'&&S.minimum_cell_n===0))notice(contentHost,S.minimum_cell_n>0?`Unavailable or suppressed values are not zero. Cell threshold: ${S.minimum_cell_n}. Do not infer hidden counts from totals.`:"This research-team release shows complete aggregates and does not suppress by cell size. \"-\" means not provided or not computable; a missing value is not treated as 0.");
  if(st.reading==='trends'){if(view.grade_custom)notice(contentHost,'Monthly trends require All grades in this version. No unfiltered trend is shown.');else trends(view,st);return;}
  if(st.reading==='paired'){paired(view,st);return;}
  switches(contentHost,{table:"Results table",distribution:"Score distribution",charts:"Scale total charts"},st.result,value=>{st.result=value;},"Research overview content");
  if(st.result==='distribution'){distribution(view,st);return;}
  if(st.result==='charts'){
    const host=section("Scale total overview","Each wave uses its own valid responses. The chart shows the per-wave mean and is not a per-person change."),charts=el('div','columns');host.append(charts);
    for(const key of ['PHQ_total','FQOL_total','SEC_total']){const rows=view.statistics.filter(row=>row.group===st.group&&row.variable_id===key);chart(charts,['T0','T1'],[{name:"Mean per wave",values:['T0','T1'].map(wave=>rows.find(row=>row.wave===wave)?.mean??null)}],S.dictionary.find(variable=>variable.variable_id===key)?.label||key);}
    return;
  }
  statisticsTable(view,st);
}
function demographicTable(host, rows, wave) {
  const selected=rows.filter(row=>row.wave===wave);
  if(!selected.length){notice(host,`There are no demographic results for ${wave} in this selection.`);return;}
  const groups=new Map();
  for(const row of selected){
    if(!groups.has(row.variable_id))groups.set(row.variable_id,[]);
    groups.get(row.variable_id).push(row);
  }
  const wrap=el('div','table-wrap demographic-table'),t=el('table');
  wrap.tabIndex=0;wrap.setAttribute('role','region');wrap.setAttribute('aria-label',`${wave} characteristics table; scroll to see all columns`);
  t.append(el('caption','',`${wave} characteristics: mean (SD) or n (%)`));
  const head=el('thead'),heading=el('tr');
  for(const [i,title] of ['Characteristic','Unit','Mean (SD) / n (%)','Denominator N','Sample N','Valid N','Missing N','Outside-range N'].entries()){
    const th=el('th',i>1?'numeric':'',title);th.scope='col';heading.append(th);
  }
  head.append(heading);t.append(head);
  const ordered=[...groups.values()].sort((a,b)=>Number(a[0].kind!=='continuous')-Number(b[0].kind!=='continuous'));
  for(const items of ordered){
    const body=el('tbody'),first=items[0],continuous=first.kind==='continuous';
    if(!continuous){const tr=el('tr'),th=el('th','demographic-heading',first.variable);th.scope='rowgroup';th.colSpan=8;tr.append(th);body.append(tr);}
    for(const row of items){
      const tr=el('tr'),th=el('th',continuous?'':'demographic-category',continuous?row.variable:row.category);th.scope='row';tr.append(th);
      let value;
      if(row.suppressed)value='Suppressed (small sample)';
      else if(continuous)value=statValue(row);
      else if(row.denominator===0)value='No valid responses';
      else value=`${n(row.numerator)} (${row.proportion===null||row.proportion===undefined?'—':num(100*row.proportion)+'%'})`;
      const cells=[row.unit||'—',value,row.denominator,row.sample_n,row.valid_n,row.missing_n,row.outside_range_n];
      cells.forEach((cell,i)=>tr.append(el('td',i?'numeric':'',i>1?(row.suppressed?'—':n(cell)):cell)));
      body.append(tr);
    }
    t.append(body);
  }
  wrap.append(t);host.append(el('p','family-note demographic-scroll-hint','Scroll the table horizontally to see all columns.'),wrap);
}
function statisticsTable(view, st) {
  const pairBlock=view.source_capabilities?view.source_capabilities.paired_summaries:(!view.grade_custom||view.grade?.capabilities?.paired_summaries),inference=!view.grade_custom&&view.source_capabilities?.inference!==false;
  const host=section("Research results table",st.section==='scales'?"The T0 and T1 columns each use that wave's valid responses. The test on the right uses only the formal pairs that are valid in both waves, so the two N values can differ.":"Each response wave is shown separately. The CSV retains both waves in separate columns.");
  const controls=el('div','controls');host.append(controls);
  select(controls,"Metric category",st.section,{scales:"Scales and bullying",[st.role]:st.role==='parent'?"Parent characteristics":"Student characteristics"},value=>{st.section=value;render();});
  if(st.section==='scales')select(controls,"Scale family",st.family,families,value=>{st.family=value;render();});
  else select(controls,"Response wave",st.demographic_wave||'T0',{T0:'T0',T1:'T1'},value=>{st.demographic_wave=value;render();});
  if(st.role==='parent'&&st.section==='scales')notice(host,S.bd_pairing_policy==='selected_parent_waves_same_child_v1'?"Parent PHQ describes the responding adult. BD pairs responses for the same child, and the adult may differ. Per-wave PHQ summaries are available; paired PHQ results require confirmed same-adult continuity for every pair in the selection. Parent SEC and the bullying items describe the child.":"Parent PHQ describes the responding adult. A PHQ test is offered only for the formal same-adult sample and only when both submissions are inside the current selection. Parent SEC and the bullying items describe the child.");
  const selected=view.statistics.filter(row=>row.group===st.group&&row.section===st.section&&(st.section!=='scales'||st.family==='all'||familyOf(row.variable_id)===st.family));
  const changes=(view.changes||[]).filter(row=>row.group===st.group);
  const allRows=comparisonRows(selected,changes),bar=el('div','toolbar'+(st.section==='scales'?'':' demographics-toolbar'));bar.append(el('span','caption',"Sample N = valid N + missing N. Outside-range N is included in missing N. Full-precision values are retained in the download."));const button=el('button','quiet',"Download current category (CSV)");
  const auditColumns={variable_id:'Variable ID',category_code:'Category code',item:'Metric',category:'Category',unit:'Unit',T0:'T0 (wave-valid)',T0_sample_n:'T0 sample N',T0_n:'T0 valid N',T0_missing:'T0 missing N',T0_outside_range_n:'T0 outside-range N',T1:'T1 (wave-valid)',T1_sample_n:'T1 sample N',T1_n:'T1 valid N',T1_missing:'T1 missing N',T1_outside_range_n:'T1 outside-range N',formal_pairs_n:'Formal paired N',test_n:'Both-valid paired N',paired_missing_n:'Not both valid N',paired_only_t0_valid_n:'Only T0 valid N',paired_only_t1_valid_n:'Only T1 valid N',paired_both_missing_n:'Both missing N',paired_t0_mean:'T0 mean (paired-valid)',paired_t1_mean:'T1 mean (paired-valid)',p:'p-value',dz:'Cohen dz',pair_detail_status:'Paired availability status'};
  const rawColumns={...auditColumns,...Object.fromEntries(['T0','T1'].flatMap(w=>['mean','sd','numerator','denominator','proportion'].map(k=>[w+'_'+k,w+' '+k+' (raw)']))),p_value:'p-value (raw)',cohen_dz:'Cohen dz (raw)',mean_change:'Mean paired change (raw)',sd_change:'Change SD (raw)',inference_status:'Inference status',test_basis:'Test basis'};
  if(!pairBlock){for(const key of ['formal_pairs_n','test_n','paired_missing_n','paired_only_t0_valid_n','paired_only_t1_valid_n','paired_both_missing_n','paired_t0_mean','paired_t1_mean','p','dz','pair_detail_status','p_value','cohen_dz','mean_change','sd_change','inference_status','test_basis']){delete auditColumns[key];delete rawColumns[key];}}
  else if(!inference){for(const key of ['p','dz','p_value','cohen_dz']){delete auditColumns[key];delete rawColumns[key];}}
  button.onclick=()=>download(csv(allRows,rawColumns,{type:'statistics',section:st.section,family:st.section==='scales'?st.family:undefined}),'study2-statistics-'+st.mode+'-'+st.role+'-'+st.group+'.csv','text/csv;charset=utf-8');bar.append(button);host.append(bar);
  const blocks=st.section==='scales'?['PHQ','FQOL','SEC','bullying']:['demographics'];
  for(const family of blocks){
    const rows=selected.filter(row=>familyOf(row.variable_id)===family);if(!rows.length)continue;
    const block=el('section','family-block');block.append(el('h3','',families[family]||(st.role==='parent'?"Parent characteristics":"Student characteristics")));host.append(block);
    if(family==='demographics'){
      block.append(el('p','family-note',"Percentages use the valid denominator for each characteristic. A missing answer is not 'no'; multi-select proportions can exceed 100%."));
      demographicTable(block,rows,st.demographic_wave||'T0');continue;
    }
    for(const continuous of [true,false]){
      let items=rows.filter(row=>(row.kind==='continuous')===continuous);if(!items.length)continue;
      items=[...items].sort((a,b)=>Number(!a.variable_id.endsWith('_total'))-Number(!b.variable_id.endsWith('_total')));
      const first=items[0],meaning=continuous?scoreMeaning(first.variable_id):"Count / valid denominator (%); a missing answer is not \"no\", and multi-select proportions can exceed 100%";
      block.append(el('p','family-note',family==='PHQ'&&continuous?"The total is 0-12; anxiety and depression are 0-6 each. Higher means more reported symptoms.":meaning));
      const tests=continuous&&family!=='demographics'&&pairBlock?{test_n:"Paired N",...(inference?{p:'p-value',dz:'Cohen’s dz'}:{})}:{};
      const columns={item:"Metric",...(continuous?(family==='demographics'?{unit:"Unit"}:{scale:"Scale range"}):{category:"Category"}),T0:continuous?"Mean (SD)":"n / valid N (%)",T0_n:"Valid N",T1:continuous?"Mean (SD)":"n / valid N (%)",T1_n:"Valid N",...tests};
      table(block,comparisonRows(items,changes),columns,null);
      if(family==='PHQ'&&!continuous)block.append(el('p','family-note',"PHQ score categories describe the distribution only. They are not a clinical diagnosis."));
    }
  }
  if(!selected.length)notice(host,"There are no summary results to show for this selection.");
  if(st.section==='scales')notice(host,!pairBlock?'The paired overview block is unavailable for this selection. Select an explicit longitudinal sample for supported baseline-grade summaries.':!inference?'Complete-pair counts and means use this selection. Paired p-values and dz are unavailable for the selected source or grade combination.':"The test paired N is the intersection of the formal longitudinal sample with the currently selected submissions in both waves, after deducting missing values for this metric. Two-sided paired t test; the p-value has no multiple-comparison correction; Cohen's dz = mean of the per-person differences / SD of the differences, direction T1 - T0. Category proportions are not tested. \"-\" means not provided, not enough pairs or a change SD of zero; see the CSV download.");
}
function distribution(view,st){if(view.source_capabilities?.distributions===false){notice(contentHost,'Distributions and transitions are unavailable for the selected sources or grades. Select All sources and All grades to view them.');return;}if(view.grade_custom){notice(contentHost,'Grade-filtered distributions and transitions are unavailable in this version. No All-grade figure is substituted.');return;}const histograms=st.reading==='paired'?view.paired_histograms:view.histograms;const basis=st.reading==='paired'?'paired_valid':'wave_valid';const host=section("Score distribution","Uses the shared valid values and the complete-pair basis, binned on a fixed scale. T0 and T1 share the bin edges. Only all sources are offered.");if(!histograms){notice(host,"After a source filter the mean, SD and category detail are still available. Select all sources for the distribution chart.");return;}const keys=[...new Set(histograms.map(r=>r.variable_id))];if(!keys.length){notice(host,"This sample has no distribution to show.");return;}if(!keys.includes(st.variable))st.variable=keys[0];const box=el('div','controls');host.append(box);select(box,"Distribution metric",st.variable,Object.fromEntries(keys.map(k=>[k,S.dictionary.find(v=>v.variable_id===k)?.label||k])),v=>{st.variable=v;render();});const rows=histograms.filter(r=>r.group===st.group&&r.variable_id===st.variable&&r.wave!=='delta');const bins=[...new Set(rows.map(r=>r.bin_index))].sort((a,b)=>a-b);const labels=bins.map(k=>{const r=rows.find(r=>r.bin_index===k);return r.bin_left===null?"Suppressed":`${num(r.bin_left)}–${num(r.bin_right)}`;});chart(host,labels,['T0','T1'].map(w=>({name:w,values:bins.map(i=>rows.find(r=>r.wave===w&&r.bin_index===i)?.count??null)})),"T0 and T1 score distribution ("+(basis==='paired_valid'?"the same complete pairs":"each wave separately valid")+'）');host.append(el('p','caption',['T0','T1'].map(w=>{const block=rows.filter(r=>r.wave===w);return w+' valid N: '+(block.some(r=>r.count===null)?"Suppressed":n(block.reduce((sum,r)=>sum+r.count,0)));}).join('；')));const downloadBins=el('button','quiet','Download histogram bins (CSV)');downloadBins.onclick=()=>{const data=rows.map(row=>{const waveRows=rows.filter(r=>r.wave===row.wave);const denominator=waveRows.some(r=>r.count===null)?null:waveRows.reduce((sum,r)=>sum+r.count,0);return {...row,variable:S.dictionary.find(v=>v.variable_id===row.variable_id)?.label||row.variable_id,denominator,basis};});download(csv(data,{variable_id:'Variable ID',variable:'Metric',group:'Group',wave:'Wave',bin_index:'Bin index',bin_left:'Left edge (raw)',bin_right:'Right edge (raw)',count:'Count',denominator:'Valid N',basis:'Basis'},{type:'histogram',variable:st.variable,family:familyOf(st.variable),basis}),'study2-histogram-'+st.mode+'-'+st.variable+'.csv','text/csv;charset=utf-8');};host.append(downloadBins);}
function paired(view, st) {
  const permitted=['acbd','efmatched','independent_child','independent_adult'];
  const compact=st.mode==='acbd';
  if(compact&&typeof Source.withWaveSD==='function')view=Source.withWaveSD(S,st);
  const host=section("Complete-pair changes",compact?"Each row uses the same metric-specific cases with valid scores at T0 and T1.":"T1 minus T0 is computed for each eligible longitudinal unit and then summarised. The valid N in both waves can differ for each metric.");
  if(!permitted.includes(st.mode)){notice(host,"This is a per-wave sample. Select AC/BD, the EF longitudinal sample or an independent-parent longitudinal sample in the sidebar, then check the new N.");return;}
  if(!compact)notice(host,"Only scores that are valid in both waves for the same longitudinal unit are used; BD uses its own selected T1. A longitudinal change in parent PHQ additionally requires confirmed same-adult continuity, and unconfirmed results are not offered here.");
  if(view.source_capabilities?.paired_summaries===false){notice(host,view.source_notice||'Paired summaries are unavailable for this source selection.');return;}
  const filtered=view.changes.filter(row=>row.group===st.group);
  const columns={variable:'Metric',pairs_n:'Formal paired N',paired_valid_n:'Valid in both waves N',only_t0_valid_n:'Only T0 valid N',only_t1_valid_n:'Only T1 valid N',both_missing_n:'Both missing N',paired_missing_n:'Not both valid N',t0_display:'T0 mean (paired-valid)',t1_display:'T1 mean (paired-valid)',change:'T1 - T0 mean change',sd:'Change SD',p:'p-value',dz:'Cohen dz'};
  const rawColumns={...columns,variable_id:'Variable ID',t0_mean:'T0 mean (raw, paired-valid)',t1_mean:'T1 mean (raw, paired-valid)',mean_change:'Mean change (raw)',sd_change:'Change SD (raw)',p_value:'p-value (raw)',cohen_dz:'Cohen dz (raw)',inference_status:'Inference status',pair_detail_status:'Availability status'};
  const inference=!(view.grade_custom||view.source_capabilities?.inference===false);
  if(!inference){for(const key of ['p','dz','p_value','cohen_dz']){delete columns[key];delete rawColumns[key];}}
  if(compact)Object.assign(rawColumns,{t0_sd:'T0 SD (raw, paired-valid)',t1_sd:'T1 SD (raw, paired-valid)'});
  const displayColumns=compact?{variable:'Metric',paired_valid_n:'Valid in both waves, N',t0_summary:'T0 Mean (SD)',t1_summary:'T1 Mean (SD)',p:'p-value',dz:"Cohen's d"}:columns;
  const waveSummary=(row,wave)=>row.suppressed?'Suppressed (small sample)':row[wave+'_mean']===null||row[wave+'_mean']===undefined?'Unavailable':num(row[wave+'_mean'])+' ('+(row[wave+'_sd']===null||row[wave+'_sd']===undefined?'SD unavailable':num(row[wave+'_sd']))+')';
  if(!compact)notice(host,'Both-valid + only T0 valid + only T1 valid + both missing = formal paired N. The two means below use exactly the same complete pairs. Missing detail in an older snapshot is unavailable, not zero.');
  const display=row=>({...row,basis:'paired_valid',t0_display:num(row.t0_mean),t1_display:num(row.t1_mean),change:row.suppressed?'Suppressed (small sample)':num(row.mean_change),sd:num(row.sd_change),p:compact&&!inference?'Unavailable':compact&&row.p_value==null?'Unavailable':pValue(row.p_value),dz:compact&&!inference?'Unavailable':compact&&row.cohen_dz==null?'Unavailable':num(row.cohen_dz),t0_summary:waveSummary(row,'t0'),t1_summary:waveSummary(row,'t1')});
  const bar=el('div','toolbar'),downloadAll=el('button','quiet',"Download all paired changes (CSV)");
  downloadAll.onclick=()=>download(csv(filtered.map(row=>({...display(row),p:pValue(row.p_value),dz:num(row.cohen_dz)})),rawColumns,{type:'paired_changes'}),'study2-paired-'+st.mode+'-'+st.group+'.csv','text/csv;charset=utf-8');
  bar.append(el('span','caption',"Read each scale family separately; the download keeps every metric"),downloadAll);host.append(bar);
  for(const family of ['PHQ','FQOL','SEC','bullying']){
    const rows=filtered.filter(row=>familyOf(row.variable_id)===family).sort((a,b)=>Number(!a.variable_id.endsWith('_total'))-Number(!b.variable_id.endsWith('_total'))).map(display);if(!rows.length)continue;
    const block=el('section','family-block');block.append(el('h3','',families[family]));host.append(block);
    table(block,rows,displayColumns,null);
  }
  if(compact)host.append(el('p','caption',"Two-sided paired t-test; no multiple-comparison correction. Cohen's d is dz = mean(T1 - T0) / SD(T1 - T0); positive means higher T1. Unavailable values are not estimated."));
  if(!filtered.length)notice(host,"There are no complete-pair changes available for this selection.");
  const transitions=(view.source_capabilities?.distributions===false?[]:view.transitions||[]).filter(row=>row.group===st.group).map(row=>({...row,percent:row.proportion===null?'—':num(100*row.proportion)+'%'}));
  if(transitions.length){const target=section("Bullying metrics: four-cell transition between the two waves","The denominator is the paired N that is valid in both waves for that metric. It is separate from the per-wave valid denominators.");table(target,transitions,{variable:"Metric",transition:"Two-wave state",count:"Paired count",denominator:"Valid in both waves N",percent:"Percentage"},'binary-transitions-'+st.mode+'-'+st.group,false,{variable_id:'Variable ID',proportion:'Proportion (raw)'},{type:'transitions'});}
  const detail=el('details');detail.append(el('summary','',"See the T0 and T1 distribution of the same complete pairs"));contentHost.append(detail);
  const previous=contentHost;contentHost=detail;distribution(view,st);contentHost=previous;
}
function combinedTrends(st) {
  const host=section("Selected-period T0 and T1 comparison","Combine child group, grades, sources and school scope, then filter each selected response by its own inclusive Hong Kong date. No wave reselection or paired inference."),epoch=renderEpoch,snapshot=S;
  const scope={mode:eligibility?.mode||'off',revision:eligibility?.mode==='on'?eligibility.metadata().eligibility_revision:null,
    active_on_revision:eligibility?.available?eligibility.metadata().eligibility_revision:null};
  if(snapshot.period_semester_selection){
    if(snapshot.minimum_cell_n!==0){notice(host,'Semester trends are unavailable for this suppression profile.',true);return;}
    if(typeof Study2PeriodUI.mountSemester!=='function'||typeof Study2PeriodUI.createSemesterLoader!=='function'||typeof Study2Semester==='undefined'){
      notice(host,'Semester trends are unavailable in this export.',true);return;
    }
    if(!semesterLoader)semesterLoader=Study2PeriodUI.createSemesterLoader({getPeriod:()=>Study2Semester});
    Study2PeriodUI.mountSemester({host,snapshot,state:st,scope,loader:semesterLoader,period:Study2Semester,
      isCurrent:()=>renderEpoch===epoch&&S===snapshot&&st.reading==='trends',rerender:render,
      el,select,notice,cards,table,lineChart:periodLineChart,num,n});
    return;
  }
  Study2PeriodUI.mount({host,snapshot,state:st,scope,loader:periodLoader,period:typeof Period==='undefined'?null:Period,
    isCurrent:()=>renderEpoch===epoch&&S===snapshot&&st.reading==='trends',rerender:render,
    el,select,notice,cards,table,lineChart:periodLineChart,num,n,present:Study2PeriodUI.present});
}
function trends(view,st) {
  const host=section("Selected-period T0 and T1 comparison","The selected complete months are combined into two points and each wave is averaged separately. The respondents inside the period can differ, so this is not a per-person change.");
  notice(host,"Legacy period snapshot: complete months and All group/grade/source only. Combined day-filter aggregates are unavailable in this snapshot; unsupported selections never receive an unfiltered substitute.");
  if(st.group!=='all'||(view.source_capabilities?view.source_capabilities.monthly_trends===false:st.source!=='all')){notice(host,"The static period comparison offers only all groups and all sources. Clear those two filters; the group statistics on the other pages still work.");return;}
  if(!view.trends?.length){notice(host,"This sample has no usable dates.");return;}
  const box=el('div','controls');host.append(box);
  select(box,"Date source",String(st.batch),{'false':"Only system or manually verified dates",'true':"Also include accepted batch dates"},v=>{st.batch=v==='true';render();});
  const all=view.trends.filter(row=>row.include_batch===st.batch);
  if(!all.length){notice(host,"This date-source setting has no usable responses.");return;}
  const metricKeys=[...new Set(all.flatMap(period=>period.statistics.map(row=>row.variable_id)))];
  const options={volume:"Number of formally selected responses",...Object.fromEntries(metricKeys.map(key=>[key,S.dictionary.find(variable=>variable.variable_id===key)?.label||key]))};
  if(!Object.hasOwn(options,st.trend_variable))st.trend_variable=metricKeys[0]||'volume';
  const selection=periodSelection(all,st.trend_variable,st),{from,to,suggested}=selection;
  // Store effective dates in CSV context while keeping automatic/manual intent.
  Object.assign(st,{from,to,period_auto:selection.automatic});
  for(const [key,label]of [['from',"Start month"],['to',"End month"]]){
    const lab=el('label','',label),input=el('input');input.type='month';input.dataset.control='month:'+key;input.min=all[0].period;input.max=all.at(-1).period;input.value=st[key];
    input.onchange=()=>{st[key]=input.value;st.period_auto=false;render();};lab.append(input);box.append(lab);
  }
  select(box,"Period comparison metric",st.trend_variable,options,value=>{st.trend_variable=value;render();});
  if(st.trend_variable!=='volume')select(box,"Vertical axis range",st.trend_axis||'full',{full:"Full scale range",auto:"Auto scale (range is labelled)"},value=>{st.trend_axis=value;render();});
  if(!(S.minimum_cell_n>0))host.append(el('p','caption',"Current period: "+from+' to '+to+". By default this covers the complete data period. You can adjust the months; every month is included in its own T0 and T1 totals."));
  else if(selection.automatic&&suggested)notice(host,"Default displayable period: "+from+' to '+to+'（'+suggested.months+' complete months). The longest continuous displayable period is chosen by availability, with the most recent tie. Scores do not determine the period. Complete data period: '+all[0].period+' to '+all.at(-1).period+'。');
  else if(!suggested)notice(host,"The current settings do not give a continuous period that both waves can display. Change the analysis sample, the metric or the date source; the per-wave results and the monthly detail below still work.",true);
  else host.append(el('p','caption',"Custom period: "+from+' to '+to+". This range is kept when the metric, sample or date source changes."));
  const actions=el('div','page-actions');
  if(S.minimum_cell_n>0&&suggested){const available=el('button','quiet',"Use the displayable period: "+suggested.from+' to '+suggested.to);available.dataset.control='period:available';available.onclick=()=>{st.period_auto=true;render();};actions.append(available);}
  const full=el('button','quiet',"Select the complete data period");full.dataset.control='period:full';full.onclick=()=>{Object.assign(st,{from:all[0].period,to:all.at(-1).period,period_auto:false});render();};actions.append(full);host.append(actions);
  if(from>to){notice(host,"The start month must not be later than the end month.",true);return;}
  const rows=all.filter(row=>row.period>=from&&row.period<=to);
  if(!rows.length){notice(host,"There are no usable responses in the selected months.");return;}
  for(const issues of periodIssues(rows,st.trend_variable)){
    if(issues.suppressed.length)notice(host,issues.wave+' metric-suppressed months: '+issues.suppressed.join('、')+". The total for that wave is therefore not shown. Those months are not skipped and their values are not estimated. Adjust the range with the \"use the displayable period\" action above.",true);
    if(issues.unavailable.length)notice(host,issues.wave+' months without complete metric summaries: '+issues.unavailable.join('、')+". That wave therefore cannot be totalled.",true);
    if(issues.counts_suppressed.length)host.append(el('p','caption',issues.wave+' months with suppressed response N: '+issues.counts_suppressed.join('、')+"; the response N is not totalled and the metric is shown according to its own availability."));
  }
  cards(host,['T0','T1'].map(wave=>['Selected months '+wave+' response N',rows.some(row=>row.counts[wave]===null)?null:rows.reduce((sum,row)=>sum+row.counts[wave],0),S.minimum_cell_n>0?"Counts only the selected date source; a suppressed month stops the total":"Counts only the formally selected responses in the selected period and date source"]));
  const points=periodComparison(rows,st.trend_variable),label=options[st.trend_variable];
  periodLineChart(host,points,label,st.trend_variable,st.trend_axis||'full',from+' to '+to);
  const formatted=points.map(point=>({...point,wave:point.period,mean_sd:point.status==='suppressed'?"the whole period is suppressed":point.status==='unavailable'?"the summary is incomplete":point.status==='no_valid_scores'?"there are no valid scores":st.trend_variable==='volume'?n(point.value):num(point.value)+' ('+num(point.sd)+')'}));
  table(host,formatted,{wave:"Wave",mean_sd:st.trend_variable==='volume'?"Response count":"Period mean (SD)",...(st.trend_variable==='volume'?{}:{valid_n:"Valid N",missing_n:"Missing N"})},'period-comparison-'+st.mode+'-'+st.role,false,{value:'Value (raw)',sd:'SD (raw)',sample_n:'Sample N'},{type:'period_summary',variable:st.trend_variable,family:st.trend_variable==='volume'?undefined:familyOf(st.trend_variable)});
  notice(host,"The period mean is weighted by each month's valid N. The SD combines the within-month and between-month variation; monthly means are not averaged directly."+(S.minimum_cell_n>0?"If the metric is suppressed in any month, the whole wave is not totalled.":"Small months are included and no response is dropped because a month had few respondents.")+"Only a descriptive comparison is offered here. There is no paired p-value and no effect size.");
  const detail=el('details');detail.append(el('summary','',"Monthly audit detail and download"));host.append(detail);
  const stats=rows.flatMap(period=>period.statistics.filter(row=>st.trend_variable==='volume'||row.variable_id===st.trend_variable).map(row=>({...row,period:period.period,value:statValue(row)})));
  table(detail,stats,{period:"Month",wave:"Wave",variable:"Metric",value:"Mean (SD)",valid_n:"Valid N",missing_n:"Missing N"},'monthly-'+st.mode+'-'+st.role,false,{variable_id:'Variable ID',mean:'Mean (raw)',sd:'SD (raw)',sample_n:'Sample N',outside_range_n:'Outside-range N'},{type:'monthly_detail',variable:st.trend_variable,family:st.trend_variable==='volume'?'all':familyOf(st.trend_variable)});
}
function releaseMetadata(){
  const c=S.release_context,bd=S.bd_pairing_policy?{bd_pairing_policy:S.bd_pairing_policy,...(S.bd_projection?{bd_projection_revision:S.bd_projection.revision,bd_projection_source_run:S.bd_projection.source_release_id}:{})}:{};
  if(!c)return bd;
  return {...bd,analytical_run_id:c.run_id,analytical_run_fingerprint:c.run_fingerprint,analytical_program_hash:c.program_hash,export_program_hash:c.export_program_hash,release_context_revision:c.revision,group_control_head:c.group_control_head,group_proposal_revision:c.group_proposal_revision,review_control_revision:c.review_control_revision,composed_manifest_revision:c.flags.manifest_revision,workload_scope:c.workload_scope};
}
function reviewWorkload(){
  const host=section("Current review workload","Release-wide work under the pinned applied controls. These counts do not change with analytical ON/OFF or source, questionnaire, date, grade and sample filters.");
  const c=S.release_context;
  if(!c){notice(host,"Current control-bound workload is unavailable in this snapshot. Historical candidate comparisons below are not a substitute.");return;}
  const w=c.workload;
  const rows=[{item:"Open child identity groups",count:w.child_groups,unit:"groups"},{item:"Similar valid phone evidence",count:w.phone_groups,unit:"child groups"},{item:"Edge cases awaiting evidence",count:w.held_groups,unit:"child groups"},{item:"Field-correction work bundles",count:w.correction_bundles,unit:"bundles"},{item:"Field-correction evidence comparisons",count:w.correction_comparisons,unit:"comparisons within those bundles"},{item:"Separate adult identity comparisons",count:w.adult_comparisons,unit:"comparisons"}];
  table(host,rows,{item:"Work item",count:"Count",unit:"Unit"},'current-review-workload');
  notice(host,"Phone and held groups partition the open child groups. Correction bundles and their comparisons are two views of the same work. Records may overlap across work types; groups, bundles, comparisons and participants must not be added.");
}
function evidence(){
  reviewWorkload();
  let host=section("Final analysis sample reconciliation","This tab uses the same release as the first tab. Each count is a formal sample unit, not a number of candidate comparisons.");
  table(host,S.samples,{sample:"Sample code",label:"Sample definition",count:"Formal sample units"},'sample-counts');
  host=section("Historical candidate comparison inventory","Original candidate-discovery status stored with this analytical run. Pending here is historical inventory, not the current review workload above. Several comparisons can refer to the same submission.");
  table(host,S.evidence,{status:"Historical status",count:"Historical candidate comparisons"},'historical-evidence-counts');
  notice(host,"Case evidence, submission IDs, schools, dates of birth and contact details are only available in the local research system. The static version cannot receive or apply review decisions.");
}
function tracking(){const host=section("Family tracking overview","Reflects only the published tracking status at export time. It does not read later administrative records or invitation updates.");if(S.tracking?.length)table(host,S.tracking,{item:"Tracking status",count:"Families / registrations"},'tracking');else notice(host,"This release does not provide a tracking summary.");notice(host,"Permanent parent-child IDs, family details, invitation lists and contact history stay on the local machine. This page is a progress reference only and is not a basis for sending invitations.");}
function methods(){const finePeriod=S.period_selection?.status==='available'&&S.minimum_cell_n===0;const host=section("Definitions & methods",finePeriod?"Scoring, sample selection and denominators reuse the native layer. Protected period queries pool checksum-validated disjoint day-cell sufficient statistics; dates do not reselect formal waves.":"Scoring, sample selection and denominators reuse the existing Python calculation layer. The paired test is computed in Python. The period summary combines the published monthly statistics.");for(const [label,text]of S.notes){const row=el('div','method-grid');row.append(el('b','',label),el('div','',text));host.append(row);}const extra=[["Parent wave policy",S.parent_wave_policy==='student_anchored_hk_nearest_v2'?"Eligible parent responses on or after the student T1 date are selected as T1 first. The other responses give the parent baseline closest to the student T0, which may be earlier than the student, with no hard limit on the date gap. The parent has no 90-day threshold of its own. The independent-parent branch is counted separately.":"This release keeps its published parent wave policy."],["T0 to T1 test","Two-sided paired t test on the formal pairs that are valid in both waves, with a paired N counted again under the current filter. Cohen's dz = mean of the per-person T1 - T0 differences / SD of the differences. The p-value has no multiple-comparison correction and is exploratory only; category metrics are not tested. Nothing is estimated when the change SD is zero or there are not enough pairs."],["Two-point period chart",finePeriod?"Each wave uses only its selected responses inside the inclusive Hong Kong day boundaries. Continuous means and SD pool sufficient statistics with within-cell and between-cell variation. Prevalence uses its own valid numerator/denominator and a 0–1 axis. Neither is a paired change or paired test.":"Inside the selected complete months, each wave mean is weighted by its valid N and the SD combines the within-month and between-month variation. The complete data period is the default and custom months are kept. Small months are included as normal. The two points are not a per-person change and carry no paired test."],["Static export scope","Keeps the four formal sample modes, the nine child groups, the respondent, the mainstream/all-school scope and freely combined declared source filters. Individual schools, free combinations of identity rules and per-case detail stay on the local machine."],["Distribution and trends",S.period_selection?.status==='available'&&S.minimum_cell_n===0?"The period view combines one child group, arbitrary grade/source unions and school scope with inclusive Hong Kong dates. Academic presets use full September 1–August 31 boundaries. Each selected response uses its own date; formal anchors remain fixed. The result is not a paired change.":"The distribution offers all sources only and the longitudinal distribution uses the both-waves-valid basis. The monthly trend offers all groups and sources only, can include batch dates, supports complete months only, weights the period mean by the valid N and combines the within-month and between-month variation in the SD. Arbitrary day boundaries are not supported."],["Summary display",S.minimum_cell_n>0?`This snapshot applies a minimum cell size of ${S.minimum_cell_n}.`:"The research-team release shows complete aggregates and does not suppress by cell size; the distribution keeps a fixed scale binning. Personal identifiers, raw answers and personal extremes remain outside the export scope."],["Version updates","This snapshot never reads new data by itself. Re-export after each local release, then deploy the whole output folder."],["Version",`${S.release_id} · ${S.report_version}`]];for(const [label,text]of extra){const row=el('div','method-grid');row.append(el('b','',label),el('div','',text));host.append(row);}table(section("Metric dictionary"),S.dictionary,{label:"Metric",role:"Respondent",unit:"Unit",note:"Note"},'dictionary',true);}
function preserveQuality(){if(qualityMount){qualitySelection=qualityMount.getSelection();qualityUIState=qualityMount.getUIState();qualityMount.destroy();qualityMount=null;}}
function render(){renderEpoch++;document.querySelectorAll('nav button').forEach((b,i)=>b.setAttribute('aria-current',i===page?'page':'false'));const focusKey=document.activeElement?.dataset.control;if(eligibilityLoading){root.replaceChildren();notice(root,'Loading and validating the requested aggregate data…');return;}if(fullError){root.replaceChildren();notice(root,'The requested data could not be loaded or validated. No results were substituted.',true);const retry=el('button','quiet',fullError==='bootstrap_invalid'?'Reload page':'Retry loading');retry.onclick=()=>{if(fullError==='bootstrap_invalid')location.reload();else requestFull(pendingFull);};root.append(retry);if(bootstrapController){const back=el('button','quiet','Return to data quality');back.onclick=()=>{fullError=null;pendingFull=null;pendingDownload=false;page=0;location.hash='page=0';eligibility=bootstrapController;const bundle=bootstrapController.select(requestedMode);S=bundle.snapshot;activeScope=bundle.scope_export;refreshEligibility();render();};root.append(back);if((page===1||page===2)&&hasBootstrapSemesters()){const trends=el('button','quiet','Return to period trends');trends.onclick=()=>{fullError=null;pendingFull=null;pendingDownload=false;eligibility=bootstrapController;const bundle=bootstrapController.select(requestedMode);S=bundle.snapshot;activeScope=bundle.scope_export;(page===1?state:parent).reading='trends';refreshEligibility();render();};root.append(trends);}}return;}if(eligibility&&!eligibility.bundle){preserveQuality();root.replaceChildren();notice(root,'Requested manual exclusion is unavailable. Select OFF to restore the original published data.',true);return;}preserveQuality();const previousSidebar=root.querySelector('.sample-sidebar');if(previousSidebar)sidebarPositions.set(previousSidebar.dataset.sidebar,previousSidebar.scrollTop);root.replaceChildren();contentHost=root;try{[overview,()=>research(false),()=>research(true),evidence,tracking,methods][page]();}catch(error){notice(contentHost,"The page could not be displayed. Reload the complete static output.",true);console.error(error);}if(focusKey){const target=[...document.querySelectorAll('[data-control]')].find(node=>node.dataset.control===focusKey);target?.focus({preventScroll:true});}const sidebar=root.querySelector('.sample-sidebar');if(sidebar)sidebar.scrollTop=sidebarPositions.get(sidebar.dataset.sidebar)||0;}
function hashPage(){
 const value=Number(new URLSearchParams(location.hash.slice(1)).get('page'));
 return Number.isInteger(value)&&value>=0&&value<tabs.length?value:0;
}
function navigatePage(next){
 // A click renders immediately; its subsequent hashchange is a no-op.
 // Back/Forward uses the same lazy-loading path and keeps all filter state.
 if(next===page)return;
 page=next;
 if(boot&&!fullReady&&!eligibilityLoading&&page!==0&&!bootstrapSemesterPage(page))requestFull({type:'page'});
 else render();
}
tabs.forEach((name,i)=>{const b=el('button','',name);b.onclick=()=>{location.hash='page='+i;navigatePage(i);};document.querySelector('#nav').append(b);});
window.addEventListener('hashchange',()=>navigatePage(hashPage()));
page=hashPage();
document.querySelector('#load-status').hidden=true;
document.querySelector('#banner').textContent="Read-only aggregate snapshot of the published release. Filtering happens in the browser and does not connect to SQLite; per-case verification and administrative work stay on the local machine.";
const date=value=>new Date(value).toLocaleString('en-HK',{timeZone:'Asia/Hong_Kong',hour12:false});document.querySelector('#published').textContent='Published '+date(S.published_at);document.querySelector('#version').textContent=`${S.release_id} · Snapshot ${date(S.generated_at)}`;document.querySelector('#footer-version').textContent=S.report_version;function downloadSnapshot(){if(eligibility&&!eligibility.bundle)return;download(eligibility?.configured?{format:'study2_manual_exclusion_snapshot_download_v1',eligibility:eligibility.metadata(),snapshot:S}:S,'study2-aggregate-snapshot.json');}document.querySelector('#download-snapshot').onclick=()=>{if(boot&&!fullReady)requestFull({type:'download'});else downloadSnapshot();};
if(S.release_context){const c=S.release_context,p=el('p','meta');p.id='release-context';p.textContent=`Analytical run ${c.run_id} · run fingerprint ${c.run_fingerprint} · calculation code ${c.program_hash} · export code ${c.export_program_hash} · composed flags ${c.flags.combined_records} (Eric ${c.flags.eric_records}; group policy ${c.flags.group_records}; overlap ${c.flags.overlap_records}) · manifest ${c.flags.manifest_revision} · group control ${c.group_control_head} · workload/context ${c.revision}`;document.querySelector('#version').after(p);}
if(S.bd_projection){const p=el('p','meta');p.id='bd-projection';p.textContent=`BD is a same-child projection of the selected parent responses in analytical run ${S.bd_projection.source_release_id}. Projection revision ${S.bd_projection.revision}. The responding adult may differ.`;document.querySelector('#version').after(p);}
const eligibilityBar=el('section','manual-eligibility'),eligibilityLabel=el('label'),eligibilityToggle=el('input'),eligibilityStatus=el('p','caption');
eligibilityBar.setAttribute('aria-label','Manual submission exclusion');eligibilityToggle.type='checkbox';eligibilityToggle.dataset.control='manual:enabled';eligibilityToggle.id='manual-exclusion-enabled';eligibilityToggle.disabled=true;
eligibilityLabel.append(eligibilityToggle,document.createTextNode('Exclude manually flagged submissions'));eligibilityStatus.setAttribute('role','status');eligibilityStatus.setAttribute('aria-live','polite');eligibilityBar.append(eligibilityLabel,eligibilityStatus);root.before(eligibilityBar);
function refreshEligibility(){
 const shownMode=boot&&!fullReady?requestedMode:(eligibility?.mode||'off');
 eligibilityToggle.checked=shownMode==='on';eligibilityToggle.disabled=eligibilityLoading||Boolean(fullError)||(!eligibility?.available&&eligibility?.mode!=='on');
 eligibilityStatus.textContent=eligibilityLoading?'Loading and validating the requested aggregate data…':fullError?'Requested data is unavailable. Retry or return to data quality.':eligibility?.mode==='on'&&!eligibility.bundle?'Requested ON is unavailable: '+eligibility.reason+'. Select OFF to restore published data.':eligibility?.available?'Manual exclusion '+eligibility.mode.toUpperCase()+' · revision '+eligibility.metadata().eligibility_revision+' · original published membership; no reselection.':'OFF data is available. ON unavailable: '+(eligibility?.reason||'manual_exclusion_not_supplied')+'.';
 eligibilityBar.dataset.state=eligibilityLoading?'loading':fullError?'unavailable':eligibility?.available?'ready':'unavailable';eligibilityBar.dataset.mode=shownMode;
 document.querySelector('#download-snapshot').disabled=eligibilityLoading||Boolean(fullError)||Boolean(eligibility&&!eligibility.bundle);
}
eligibilityToggle.onchange=()=>{
 const mode=eligibilityToggle.checked?'on':'off';
 if(boot&&!fullReady&&!hasBootstrapSemesters()){requestFull({type:mode});return;}
 if(boot&&!fullReady){try{const bundle=bootstrapController.select(mode);requestedMode=mode;S=bundle.snapshot;activeScope=bundle.scope_export;}
  catch{fullError='bootstrap_invalid';}refreshEligibility();render();return;}
 try{const bundle=eligibility.select(mode);S=bundle.snapshot;activeScope=bundle.scope_export;}
 catch{ /* A requested invalid ON state is explicit; the original OFF stays selectable. */ }
 refreshEligibility();render();
};
function loadPinnedScript(name){
 if(loadedScripts.has(name))return loadedScripts.get(name);
 const integrity=boot.bindings.scripts[name];
 const promise=new Promise((resolve,reject)=>{const script=document.createElement('script');script.async=true;script.integrity=integrity;
  script.onload=()=>resolve();script.onerror=()=>{script.remove();reject(Error('lazy_asset_unavailable'));};script.src=name;document.head.append(script);});
 loadedScripts.set(name,promise);promise.catch(()=>loadedScripts.delete(name));return promise;
}
async function requestFull(action){
 if(boot&&!bootstrapController){fullError='bootstrap_invalid';eligibilityLoading=false;refreshEligibility();render();return;}
 if(action?.type==='on'||action?.type==='off')requestedMode=action.type;
 if(action?.type==='download')pendingDownload=true;
 pendingFull=action;if(fullPromise)return fullPromise;
 preserveQuality();fullError=null;eligibilityLoading=true;refreshEligibility();render();
 fullPromise=(async()=>{try{
  await Promise.all(['snapshot.js','scope-index.js','manual-exclusion.js'].map(loadPinnedScript));
  const snapshot=window.STUDY2_SNAPSHOT,scope=window.STUDY2_SCOPE_EXPORT,wrapper=window.STUDY2_MANUAL_EXCLUSION;
  if(!snapshot||!scope||!wrapper||wrapper.release_id!==boot.release_id||wrapper.revision!==boot.revision||
    wrapper.inventory_revision!==boot.inventory_revision||wrapper.off?.snapshot_revision!==boot.bindings.off_snapshot_revision||
    wrapper.off?.scope_revision!==boot.bindings.off_scope_revision||wrapper.on_revision!==boot.bindings.on_revision)throw Error('lazy_release_mismatch');
  const metadata=x=>({...x,views:[]}),same=(x,y)=>Study2ManualEligibility.canonical(x)===Study2ManualEligibility.canonical(y);
  if(!same(metadata(snapshot),boot.off.snapshot)||!same(metadata(wrapper.on?.snapshot),boot.on.snapshot)||
    !same(scope,boot.off.scope_export)||!same(wrapper.on?.scope_export,boot.on.scope_export)||!same(wrapper.impact,boot.impact))throw Error('lazy_bootstrap_mismatch');
  const controller=await Study2ManualEligibility.create(snapshot,scope,wrapper,Study2Scope);
  if(!controller.available)throw Error('lazy_validation_failed');
  const bundle=controller.select(requestedMode);
  eligibility=controller;S=bundle.snapshot;activeScope=bundle.scope_export;fullReady=true;fullError=null;
 }catch(error){fullError='lazy_data_unavailable';}
 eligibilityLoading=false;refreshEligibility();render();
 if(!fullError&&pendingDownload){pendingDownload=false;downloadSnapshot();}
 })();
 try{return await fullPromise;}finally{fullPromise=null;}
}
refreshEligibility();render();
if(boot){
 try{bootstrapController=Study2ManualEligibility.createBootstrap(boot,Study2Scope);eligibility=bootstrapController;eligibilityLoading=false;refreshEligibility();
  if(page!==0&&!bootstrapSemesterPage(page))requestFull({type:'page'});else render();
 }catch(error){eligibilityLoading=false;fullError='bootstrap_invalid';refreshEligibility();render();}
}else Study2ManualEligibility.create(baselineSnapshot,activeScope,window.STUDY2_MANUAL_EXCLUSION,typeof Study2Scope==='undefined'?null:Study2Scope).then(controller=>{
 eligibility=controller;
 if(baselineSnapshot.release_context?.default_eligibility==='on'){
  try{const bundle=controller.select('on');S=bundle.snapshot;activeScope=bundle.scope_export;}catch{ /* Explicit requested-ON unavailable state; OFF remains selectable. */ }
 }
 eligibilityLoading=false;refreshEligibility();render();
});
})();
