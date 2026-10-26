"""Buildless, dependency-free presentation for the aggregate-only snapshot.

Presentation is kept here so every future export carries the same interface.
Statistics, selected waves and disclosure rules remain in static_export.
"""

import json
from .static_english_catalog import text as english
from .static_quality_ui import STYLES as QUALITY_STYLES
from .static_grade import JS_SOURCE as GRADE_JS
from .static_sources import JS_SOURCE as SOURCE_JS
from .static_eligibility_ui import JS_SOURCE as ELIGIBILITY_JS

HTML = r'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex,nofollow"><title>Study 2 Research Dashboard</title>
<link rel="stylesheet" href="styles.css"><script defer src="snapshot.js"></script><script defer src="scope-index.js"></script><script defer src="scope-engine.js"></script><script defer src="quality-ui.js"></script><script defer src="app.js"></script><script defer src="access.js"></script></head>
<body><a class="skip" href="#content">Skip to content</a>
<header><div class="identity"><span class="mark" aria-hidden="true">S2</span><div>
<p class="eyebrow">HKU · ANTI-BULLYING RESEARCH</p><h1>Study 2 Research Dashboard</h1></div></div>
<div class="edition"><span class="status"><i></i>Published aggregate snapshot</span><span id="published">Loading</span><button id="sign-out" class="quiet" hidden>Sign out of the research workspace</button></div></header>
<div class="shell"><div id="load-status" class="notice" role="status">Loading the aggregate snapshot. If no result appears, check that snapshot.js is complete.</div><div class="release"><details class="release-details"><summary>Release version and scope of use</summary>
<p id="banner" class="caption">Loading the static release. If this message stays, check that snapshot.js is complete.</p><p id="version" class="meta"></p></details>
<button id="download-snapshot" class="quiet">Download aggregate snapshot</button></div>
<nav id="nav" aria-label="Study 2 research pages"></nav><main id="content" tabindex="-1"></main>
<footer>HKU - Study 2 anti-bullying research　<span id="footer-version"></span><br>Read-only aggregate snapshot - no research database connection - no individual submission detail</footer></div>
<noscript><p>This interactive page needs JavaScript. All data comes only from the aggregate snapshot supplied with the page.</p></noscript></body></html>'''

STYLES = r'''
:root{--ink:#24354e;--muted:#66758b;--primary:#293f70;--teal:#247b91;--blue:#df8751;--line:#dce2ed;--paper:#f5f7fb;--white:#fff;--gold:#a87928}
*{box-sizing:border-box}body{margin:0;color:var(--ink);background:var(--paper);font:15px/1.65 -apple-system,BlinkMacSystemFont,"Segoe UI","Noto Sans TC",sans-serif}
button,input,select{font:inherit}button{cursor:pointer}button:disabled{cursor:not-allowed}a{color:var(--primary)}
header{background:white;border-bottom:1px solid var(--line);padding:19px max(24px,calc((100vw - 1440px)/2));display:flex;justify-content:space-between;align-items:center;gap:20px}
.identity{display:flex;align-items:center;gap:13px}.mark{font-size:17px;font-weight:750;background:var(--primary);color:white;border-radius:9px;padding:10px 11px;letter-spacing:1px}
.eyebrow{font-size:10px;letter-spacing:1.8px;font-weight:700;color:var(--muted);margin:0 0 2px}h1{font-size:23px;letter-spacing:.3px;margin:0;font-weight:700}.edition{display:grid;gap:3px;font-size:11px;text-align:right;color:var(--muted)}.status{font-size:12px}.status i{display:inline-block;width:7px;height:7px;border-radius:50%;background:#44896d;margin-right:7px}
.shell{max-width:1488px;margin:auto;padding:0 24px}.release{display:flex;justify-content:space-between;align-items:center;gap:16px;margin:14px 0;color:var(--muted);font-size:12px}.release-details{padding:0;margin:0;border:0;background:none;flex:1}.release-details summary{font-weight:500}.release-details[open]{padding:10px 0}.release-details p{margin:7px 0 0}.release .quiet{flex-shrink:0}
nav{display:flex;gap:8px;border-bottom:1px solid var(--line);padding-bottom:16px;margin-bottom:24px;overflow-x:auto}nav button{white-space:nowrap;border:1px solid #d4dce9;border-radius:6px;background:white;padding:10px 15px;font-size:13px;font-weight:600;color:var(--ink)}nav button[aria-current=page]{background:var(--primary);border-color:var(--primary);color:white}
h2{font-size:22px;line-height:1.4;margin:0 0 7px}h3{font-size:16px;line-height:1.45;margin:0 0 12px}p{margin:0 0 14px}.caption,.muted{color:var(--muted);font-size:12px}.page-heading{margin:0 0 23px}.page-heading .eyebrow{color:#4660a0;margin-bottom:6px}.page-heading h2{font-size:27px}.page-heading p:last-child{margin-bottom:0}
.section{margin:24px 0}.grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:14px}.grid.two-cards{grid-template-columns:repeat(2,minmax(0,1fr))}.card,.panel{background:#fff;border:1px solid var(--line);border-radius:8px;padding:20px}.card{border-top:3px solid #576fba}.card .label{font-size:12px;font-weight:600;color:var(--muted)}.card .value{font-size:34px;line-height:1.3;font-weight:700;letter-spacing:-1px;margin-top:7px;font-variant-numeric:tabular-nums}.card .sub{font-size:11px;color:var(--muted);margin-top:8px}
.workspace{display:grid;grid-template-columns:245px minmax(0,1fr);gap:26px;align-items:start}.sample-sidebar{background:white;border:1px solid var(--line);border-radius:8px;padding:19px;min-width:0}.sidebar-title{display:flex;align-items:center;justify-content:space-between;gap:10px;margin-bottom:18px}.sidebar-title h3{margin:0}.sidebar-title button{padding:0;border:0;background:none;color:#405eac;font-size:12px}.control-group{border-bottom:1px solid var(--line);padding:0 0 17px;margin-bottom:18px}.control-group:last-of-type{border-bottom:0;margin-bottom:0}.control-title{font-size:10px;font-weight:750;color:#536a98;letter-spacing:1px;margin-bottom:11px}.sample-sidebar label{margin:10px 0 0}.sample-sidebar details{margin:0;padding:0;border:0}.sample-sidebar details summary{font-size:12px;font-weight:600}.sample-sidebar .caption{margin:13px 0 0;font-size:11px}
.analysis-body{min-width:0}.sample-summary{border:1px solid var(--line);border-top:3px solid #526bba;border-radius:8px;background:white;padding:18px 21px;margin-bottom:18px}.summary-top{display:flex;justify-content:space-between;align-items:center;gap:12px}.summary-top .eyebrow{font-size:10px;letter-spacing:1px}.summary-top h3{font-size:16px;margin:5px 0 0}.summary-n{display:flex;gap:24px;flex-shrink:0}.summary-n .wave{font-size:11px;color:var(--muted)}.summary-n strong{display:block;font-size:27px;line-height:1.3;font-variant-numeric:tabular-nums}.summary-description{font-size:12px;margin:13px 0 0;color:var(--muted);line-height:1.7}.chips{display:flex;flex-wrap:wrap;gap:6px;margin-top:13px}.chip,.badge{font-size:11px;background:#edf1fa;color:#38528c;border-radius:4px;padding:3px 8px}.chip.basis{background:#eaf4f4;color:#276975}
.switcher{display:flex;flex-wrap:wrap;gap:7px;margin:14px 0 21px;border-bottom:1px solid var(--line);padding-bottom:12px}.switcher button{border:1px solid transparent;border-radius:5px;background:transparent;padding:8px 12px;color:var(--muted);font-size:13px}.switcher button[aria-pressed=true]{color:var(--primary);background:#e9eef9;border-color:#cbd5ed;font-weight:650}.result-tabs{margin-top:20px}.controls{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:14px;margin:0 0 18px;background:white;border:1px solid var(--line);border-radius:8px;padding:17px}label{font-size:12px;color:var(--muted);display:block}select,input[type=month]{display:block;width:100%;border:1px solid #ccd5e5;border-radius:5px;padding:9px 10px;background:white;color:var(--ink);margin-top:6px;min-height:42px;max-width:100%}
.quiet{border:1px solid #ccd5e5;border-radius:5px;background:white;padding:7px 12px;color:var(--primary);font-size:12px}.quiet:hover,nav button:hover{border-color:#667fab}.toolbar{display:flex;align-items:center;justify-content:space-between;gap:12px;margin:12px 0}.table-wrap{overflow:auto;border:1px solid var(--line);border-radius:7px;background:white;max-height:590px;position:relative}table{border-collapse:separate;border-spacing:0;min-width:100%;font-size:12px;font-variant-numeric:tabular-nums}th{text-align:left;background:#edf1f8;color:var(--ink);position:sticky;top:0;font-weight:650;z-index:1}th,td{padding:11px 12px;border-bottom:1px solid #e6eaf2;white-space:nowrap;vertical-align:middle}th:first-child,td:first-child{white-space:normal;min-width:130px}th.numeric,td.numeric{text-align:right}thead.grouped tr:first-child th{height:39px}thead.grouped tr:nth-child(2) th{top:39px}thead.grouped th.wave-head{text-align:center;color:#344e86;border-left:1px solid #dce3ee}tbody tr:last-child td{border-bottom:0}tbody tr:hover{background:#f7f9fd}.wide-text td{white-space:normal;min-width:130px}.wide-text td:last-child{min-width:300px}.columns{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:16px}.triple{grid-template-columns:repeat(3,minmax(0,1fr))}.chart{width:100%;height:auto;display:block}.legend{display:flex;gap:18px;font-size:12px;margin-bottom:10px}.dot{display:inline-block;width:9px;height:9px;border-radius:2px;margin-right:5px}.teal{background:var(--teal)}.blue{background:var(--blue)}
.notice{padding:12px 15px;background:#edf2fa;border-left:3px solid #6b82ba;font-size:12px;color:#4b6084;margin:12px 0 18px;line-height:1.75}.warning{border-left-color:var(--gold);background:#faf3e3;color:#795b22}.empty{padding:30px;text-align:center;color:var(--muted)}.facts{margin:0;padding-left:23px}.facts li{margin:12px 0}.method-grid{display:grid;grid-template-columns:170px 1fr;border-top:1px solid var(--line);padding:16px 0}.method-grid b{font-weight:600}.meta{font-size:11px;overflow-wrap:anywhere;color:var(--muted)}details{border:1px solid var(--line);background:white;border-radius:7px;padding:14px 17px;margin:18px 0}summary{cursor:pointer;font-weight:600;font-size:13px}details .table-wrap{margin-top:15px}.family-block{background:white;border:1px solid var(--line);border-radius:8px;padding:19px;margin:17px 0}.family-block h3{margin-bottom:5px}.family-block .table-wrap{border-radius:5px}.family-block .toolbar{margin-top:11px}.family-note{font-size:11px;color:var(--muted);margin-bottom:8px}.stage-cards{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:13px}.stage-card{background:white;border:1px solid var(--line);border-radius:7px;padding:17px}.stage-card .step{font-size:10px;letter-spacing:1px;font-weight:700;color:#556eac}.stage-card h3{margin:7px 0;font-size:14px}.stage-card .stage-value{font-weight:650;font-size:15px;line-height:1.6}.stage-card p{font-size:11px;color:var(--muted);margin:9px 0 0}.scope-note{font-size:12px;color:var(--muted);margin:9px 0 18px}.page-actions{display:flex;align-items:center;gap:10px;flex-wrap:wrap}footer{color:var(--muted);font-size:11px;border-top:1px solid var(--line);margin-top:40px;padding:20px 0;line-height:1.9}.skip{position:absolute;left:-9999px}.skip:focus{left:8px;top:8px;background:white;padding:10px;z-index:10}:focus-visible{outline:3px solid #ad8138;outline-offset:3px}
.sample-sidebar{overflow-y:auto;overflow-x:hidden;max-height:calc(100vh - 36px);max-height:calc(100dvh - 36px);scrollbar-gutter:stable;overscroll-behavior:contain}
.sample-sidebar fieldset{border:0;padding:0;margin:0;min-width:0}.sample-sidebar legend{padding:0}.sample-sidebar .sidebar-title{flex-wrap:wrap}.sample-sidebar .page-actions{gap:7px}.sample-sidebar .page-actions button{max-width:100%;white-space:normal;text-align:left}.sample-sidebar label{overflow-wrap:anywhere}.sample-sidebar input[type=checkbox]{flex-shrink:0}.sample-sidebar .check-option{display:flex;align-items:flex-start;gap:7px}.sample-sidebar .check-option input{margin-top:4px}
@media(min-width:801px){.sample-sidebar{position:sticky;top:18px}}
@media(max-width:1100px){.workspace{grid-template-columns:220px minmax(0,1fr);gap:18px}.summary-top{align-items:flex-start;flex-wrap:wrap}.triple{grid-template-columns:1fr}.stage-cards{grid-template-columns:repeat(2,minmax(0,1fr))}}
@media(max-width:800px){.workspace{grid-template-columns:1fr}.grid{grid-template-columns:repeat(2,minmax(0,1fr))}.sample-sidebar{padding:16px;max-height:70vh;max-height:70dvh}.sample-sidebar .control-group{margin-bottom:12px;padding-bottom:12px}.columns{grid-template-columns:1fr}.controls{grid-template-columns:repeat(2,minmax(0,1fr))}header{padding:17px 18px}.shell{padding:0 16px}nav button{padding:9px 12px}.card .value{font-size:29px}.summary-top{flex-wrap:wrap}.sample-summary{padding:16px}.page-heading h2{font-size:24px}}
@media(max-width:520px){.controls{grid-template-columns:1fr}.grid{gap:10px}.card{padding:14px}.card .value{font-size:26px}h1{font-size:19px}.eyebrow{font-size:8px}.edition{font-size:10px;max-width:130px}.status{font-size:10px}.release{align-items:flex-start}.release .quiet{font-size:10px}.method-grid{grid-template-columns:1fr;gap:6px}.stage-cards{grid-template-columns:1fr}.family-block{padding:13px}.summary-n strong{font-size:25px}.switcher{gap:3px}.switcher button{padding:7px 9px}}
'''

APP_JS = r'''
"use strict";
(() => {
const baselineSnapshot=window.STUDY2_SNAPSHOT, root=document.querySelector('#content');
let S=baselineSnapshot,activeScope=window.STUDY2_SCOPE_EXPORT,eligibility=null,eligibilityLoading=true;
if(!S||S.format!=='study2_static_v1'){document.querySelector('#load-status').textContent="The snapshot did not load. Check that every file was uploaded.";return;}
const tabs=__R04_NAVIGATION__;
let contentHost=root;
let qualityMount=null, qualitySelection=null,qualityUIState=null;
const sidebarPositions=new Map();
let page=0, state={grades:[...Grade.codes],mode:'abcd',role:'student',mainstream:false,sources:['all'],group:'all',reading:'overview',trend_variable:'PHQ_total',trend_axis:'full',period_auto:false,variable:'PHQ_total',section:'scales',family:'all',result:'table',batch:false,from:'',to:''};
let parent={...state,sources:[...state.sources],grades:[...state.grades],mode:'independent_child',role:'parent'};
const n=v=>v===null||v===undefined?'—':Number(v).toLocaleString('en-HK');
const num=v=>v===null||v===undefined?'—':Number(v).toFixed(2);
const el=(tag,cls,text)=>{const x=document.createElement(tag);if(cls)x.className=cls;if(text!==undefined)x.textContent=text;return x;};
function section(title,note){const e=el('section','section');if(title)e.append(el('h2','',title));if(note)e.append(el('p','caption',note));contentHost.append(e);return e;}
function notice(host,text,warning=false){host.append(el('p','notice'+(warning?' warning':''),text));}
function cards(host,items){const g=el('div','grid'+(items.length===2?' two-cards':''));for(const [label,value,sub] of items){const c=el('div','card');c.append(el('div','label',label));if(!["Sample definition","Statistical scope"].includes(label))c.append(el('div','value',n(value)));if(sub)c.append(el('div','sub',sub));g.append(c);}host.append(g);}
function download(value,name,type='application/json'){if(eligibility&&!eligibility.bundle)return;if(eligibility?.configured)name=name.replace(/(?=\.[^.]+$)/,'-eligibility-'+eligibility.mode+'-'+String(eligibility.metadata().eligibility_revision).slice(0,12));const raw=typeof value==='string'?value:JSON.stringify(value,null,2);const url=URL.createObjectURL(new Blob([raw],{type}));const a=el('a');a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
function csv(rows,columns,scope={}){const context=page===1?state:page===2?parent:null;const view=context?(Array.isArray(context.sources)&&typeof Source!=='undefined'?Source.choose(S,context):S.views?.find(v=>v.mode===context.mode&&v.role===context.role&&v.mainstream===context.mainstream&&v.source===context.source)):null;const type=scope.type||(context?(context.reading==='paired'?'paired_changes':context.reading==='trends'?'period_summary':context.result==='distribution'?'histogram':'statistics'):'aggregate_table');const period=['period_summary','monthly_detail'].includes(type);const variable=scope.variable??(type==='histogram'?context?.variable:period?context?.trend_variable:undefined);const section=type==='statistics'?(scope.section??context?.section??'not_provided'):['paired_changes','histogram','transitions','monthly_detail'].includes(type)?'scales':type==='period_summary'?(variable==='volume'?'responses':'scales'):null;const family=type==='statistics'&&section==='scales'?(scope.family??context?.family??'not_provided'):type==='paired_changes'?'all':type==='transitions'?'bullying':type==='monthly_detail'&&variable==='volume'?'all':type==='histogram'||period&&variable!=='volume'?(scope.family??'not_provided'):null;const meta={...releaseMetadata(),...(eligibility?.configured?eligibility.metadata():{}),release_id:S.release_id,snapshot_generated_at:S.generated_at,report_version:S.report_version||'not_provided',dictionary_version:S.dictionary_version||'not_provided',inference_version:S.inference_version||'not_available',projection_version:S.descriptive_projection_version||'not_provided',download_type:type,...(context?{mode:context.mode,role:context.role,mainstream:String(context.mainstream),source:view?.source??context.source??'all',...(Array.isArray(context.sources)?{filter_source_codes:(view?.source_selection??context.sources).join('|'),source_all:String((view?.source_selection??context.sources).includes('all')),source_selection_status:view?.source_status||'unavailable',source_labels:(view?.source_labels||[]).join('|'),source_format:S.source_selection?.format||'not_provided'}:{}),group:context.group,reading:context.reading,...(Array.isArray(context.grades)?{filter_grade_codes:context.grades.join('|'),grade_anchor:view?.grade_anchor||view?.grade?.anchor||'not_provided',grade_format:S.grade?.format||'not_provided'}:{}),grouping_anchor:view?.grouping_anchor||'not_provided',source_filter_anchor:view?.source_filter_anchor||'not_provided',basis:scope.basis||(period?'calendar_response':type==='paired_changes'||type==='transitions'||context.reading==='paired'?'paired_valid':'wave_valid'),...(section?{section}:{}),...(family?{family}:{}),...(type==='histogram'?{selection_variable:variable}:{}),...(period?{selection_period_variable:variable,period_from:context.from,period_to:context.to,interval:'complete_month',timezone:'Asia/Hong_Kong',include_batch_dates:String(Boolean(context.batch))}:{})}:{})};rows=rows.map(r=>({...meta,...r}));columns={...Object.fromEntries(Object.keys(meta).map(k=>[k,k])),...columns};const keys=Object.keys(columns),cell=v=>'"'+String(v??'').replaceAll('"','""')+'"';return '\ufeff'+[keys.map(k=>cell(columns[k])).join(','),...rows.map(r=>keys.map(k=>cell(r[k])).join(','))].join('\r\n');}
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
  const panel=el('div','panel');panel.append(el('h3','',title+' · T0 → T1'),el('p','caption',periodLabel+"; each wave is the responses inside the period, not equally spaced calendar time"));
  const values=points.map(point=>point.value).filter(value=>value!==null&&Number.isFinite(value));
  if(!values.length){notice(panel,S.minimum_cell_n>0?"There is no displayable total in the selected period. See the month note above or use \"use the displayable period\"; the monthly audit detail can still be downloaded.":"There are no valid scores in the selected period. Check the months, the date source and the monthly detail.");host.append(panel);return;}
  const [low,high]=trendBounds(key,values,axis),range=high-low||1;
  panel.append(el('p','caption',(axis==='auto'&&key!=='volume'?"Vertical axis auto-scaled: ":"Vertical axis full range: ")+num(low)+'–'+num(high)));
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
    const tip=document.createElementNS(NS,'title');tip.textContent=point.period+'；'+periodLabel+'；'+(key==='volume'?"Response N="+n(point.value):"Mean="+num(point.value)+'；SD='+num(point.sd)+"; valid N="+n(point.valid_n)+"; missing N="+n(point.missing_n));dot.append(tip);
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
  controls(st,independent);const view=chosenView(st);
  if(!view){notice(contentHost,"This release does not provide that analysis.");return;}
  if(view.source_error||view.source_status==='empty'){sampleSummary(st,view);notice(contentHost,view.source_notice||(view.source_error?'This source selection is unavailable in this export.':'No sources selected. Zero responses are selected.'),Boolean(view.source_error));return;}
  if(view.source_notice)notice(contentHost,view.source_notice);
  if(view.grade_error){notice(contentHost,view.grade_error,true);return;}
  if(view.grade_custom){notice(contentHost,'Selected grades: '+(st.grades.join(', ')||'None')+'. Grade anchor: '+({student_wave:'selected student grade at each wave',student_T0:'selected student grade at baseline',parent_report_wave:'child grade reported by parent at each independent wave',parent_report_T0:'child grade reported by parent at independent baseline'}[view.grade_anchor])+'. Custom-grade p-values and dz are unavailable.');}
  sampleSummary(st,view);
  switches(contentHost,{overview:"Research overview",paired:"Longitudinal comparison",trends:"Period trends"},st.reading,value=>{st.reading=value;},"Reading mode");
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
function statisticsTable(view, st) {
  const pairBlock=view.source_capabilities?view.source_capabilities.paired_summaries:(!view.grade_custom||view.grade?.capabilities?.paired_summaries),inference=!view.grade_custom&&view.source_capabilities?.inference!==false;
  const host=section("Research results table","The T0 and T1 columns each use that wave's valid responses. The test on the right uses only the formal pairs that are valid in both waves, so the two N values can differ.");
  const controls=el('div','controls');host.append(controls);
  select(controls,"Metric category",st.section,{scales:"Scales and bullying",[st.role]:st.role==='parent'?"Parent characteristics":"Student characteristics"},value=>{st.section=value;render();});
  if(st.section==='scales')select(controls,"Scale family",st.family,families,value=>{st.family=value;render();});
  if(st.role==='parent')notice(host,"Parent PHQ describes the responding adult. A PHQ test is offered only for the formal same-adult sample and only when both submissions are inside the current selection. Parent SEC and the bullying items describe the child.");
  const selected=view.statistics.filter(row=>row.group===st.group&&row.section===st.section&&(st.section!=='scales'||st.family==='all'||familyOf(row.variable_id)===st.family));
  const changes=(view.changes||[]).filter(row=>row.group===st.group);
  const allRows=comparisonRows(selected,changes),bar=el('div','toolbar');bar.append(el('span','caption',"Sample N = valid N + missing N. Outside-range N is included in missing N. Full-precision values are retained in the download."));const button=el('button','quiet',"Download current category (CSV)");
  const auditColumns={variable_id:'Variable ID',category_code:'Category code',item:'Metric',category:'Category',unit:'Unit',T0:'T0 (wave-valid)',T0_sample_n:'T0 sample N',T0_n:'T0 valid N',T0_missing:'T0 missing N',T0_outside_range_n:'T0 outside-range N',T1:'T1 (wave-valid)',T1_sample_n:'T1 sample N',T1_n:'T1 valid N',T1_missing:'T1 missing N',T1_outside_range_n:'T1 outside-range N',formal_pairs_n:'Formal paired N',test_n:'Both-valid paired N',paired_missing_n:'Not both valid N',paired_only_t0_valid_n:'Only T0 valid N',paired_only_t1_valid_n:'Only T1 valid N',paired_both_missing_n:'Both missing N',paired_t0_mean:'T0 mean (paired-valid)',paired_t1_mean:'T1 mean (paired-valid)',p:'p-value',dz:'Cohen dz',pair_detail_status:'Paired availability status'};
  const rawColumns={...auditColumns,...Object.fromEntries(['T0','T1'].flatMap(w=>['mean','sd','numerator','denominator','proportion'].map(k=>[w+'_'+k,w+' '+k+' (raw)']))),p_value:'p-value (raw)',cohen_dz:'Cohen dz (raw)',mean_change:'Mean paired change (raw)',sd_change:'Change SD (raw)',inference_status:'Inference status',test_basis:'Test basis'};
  if(!pairBlock){for(const key of ['formal_pairs_n','test_n','paired_missing_n','paired_only_t0_valid_n','paired_only_t1_valid_n','paired_both_missing_n','paired_t0_mean','paired_t1_mean','p','dz','pair_detail_status','p_value','cohen_dz','mean_change','sd_change','inference_status','test_basis']){delete auditColumns[key];delete rawColumns[key];}}
  else if(!inference){for(const key of ['p','dz','p_value','cohen_dz']){delete auditColumns[key];delete rawColumns[key];}}
  button.onclick=()=>download(csv(allRows,rawColumns,{type:'statistics',section:st.section,family:st.section==='scales'?st.family:undefined}),'study2-statistics-'+st.mode+'-'+st.role+'-'+st.group+'.csv','text/csv;charset=utf-8');bar.append(button);host.append(bar);
  const blocks=st.section==='scales'?['PHQ','FQOL','SEC','bullying']:['demographics'];
  for(const family of blocks){
    const rows=selected.filter(row=>familyOf(row.variable_id)===family);if(!rows.length)continue;
    const block=el('section','family-block');block.append(el('h3','',families[family]||(st.role==='parent'?"Parent characteristics":"Student characteristics")));host.append(block);
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
  if(st.section==='scales')notice(host,!pairBlock?'The paired overview block is unavailable for this selection. Select an explicit longitudinal sample for supported baseline-grade summaries.':!inference?'Complete-pair counts and means use this selection. Paired p-values and dz are unavailable for the selected source or grade combination.':"The test paired N is the intersection of the formal longitudinal sample with the currently selected submissions in both waves, after deducting missing values for this metric. Two-sided paired t test; the p-value has no multiple-comparison correction; Cohen's dz = mean of the per-person differences / SD of the differences, direction T1 - T0. Category proportions are not tested. \"-\" means not provided, not enough pairs or a change SD of zero; see the audit detail.");
  const detail=el('details');detail.append(el('summary','',"Download the current analysis and the audit detail (including missing N)"));host.append(detail);table(detail,allRows,auditColumns,null);
}
function distribution(view,st){if(view.source_capabilities?.distributions===false){notice(contentHost,'Distributions and transitions are unavailable for the selected sources or grades. Select All sources and All grades to view them.');return;}if(view.grade_custom){notice(contentHost,'Grade-filtered distributions and transitions are unavailable in this version. No All-grade figure is substituted.');return;}const histograms=st.reading==='paired'?view.paired_histograms:view.histograms;const basis=st.reading==='paired'?'paired_valid':'wave_valid';const host=section("Score distribution","Uses the shared valid values and the complete-pair basis, binned on a fixed scale. T0 and T1 share the bin edges. Only all sources are offered.");if(!histograms){notice(host,"After a source filter the mean, SD and category detail are still available. Select all sources for the distribution chart.");return;}const keys=[...new Set(histograms.map(r=>r.variable_id))];if(!keys.length){notice(host,"This sample has no distribution to show.");return;}if(!keys.includes(st.variable))st.variable=keys[0];const box=el('div','controls');host.append(box);select(box,"Distribution metric",st.variable,Object.fromEntries(keys.map(k=>[k,S.dictionary.find(v=>v.variable_id===k)?.label||k])),v=>{st.variable=v;render();});const rows=histograms.filter(r=>r.group===st.group&&r.variable_id===st.variable&&r.wave!=='delta');const bins=[...new Set(rows.map(r=>r.bin_index))].sort((a,b)=>a-b);const labels=bins.map(k=>{const r=rows.find(r=>r.bin_index===k);return r.bin_left===null?"Suppressed":`${num(r.bin_left)}–${num(r.bin_right)}`;});chart(host,labels,['T0','T1'].map(w=>({name:w,values:bins.map(i=>rows.find(r=>r.wave===w&&r.bin_index===i)?.count??null)})),"T0 and T1 score distribution ("+(basis==='paired_valid'?"the same complete pairs":"each wave separately valid")+'）');host.append(el('p','caption',['T0','T1'].map(w=>{const block=rows.filter(r=>r.wave===w);return w+' valid N: '+(block.some(r=>r.count===null)?"Suppressed":n(block.reduce((sum,r)=>sum+r.count,0)));}).join('；')));const downloadBins=el('button','quiet','Download histogram bins (CSV)');downloadBins.onclick=()=>{const data=rows.map(row=>{const waveRows=rows.filter(r=>r.wave===row.wave);const denominator=waveRows.some(r=>r.count===null)?null:waveRows.reduce((sum,r)=>sum+r.count,0);return {...row,variable:S.dictionary.find(v=>v.variable_id===row.variable_id)?.label||row.variable_id,denominator,basis};});download(csv(data,{variable_id:'Variable ID',variable:'Metric',group:'Group',wave:'Wave',bin_index:'Bin index',bin_left:'Left edge (raw)',bin_right:'Right edge (raw)',count:'Count',denominator:'Valid N',basis:'Basis'},{type:'histogram',variable:st.variable,family:familyOf(st.variable),basis}),'study2-histogram-'+st.mode+'-'+st.variable+'.csv','text/csv;charset=utf-8');};host.append(downloadBins);}
function paired(view, st) {
  const permitted=['acbd','efmatched','independent_child','independent_adult'];
  const compact=st.mode==='acbd';
  if(compact&&typeof Source.withWaveSD==='function')view=Source.withWaveSD(S,st);
  const host=section("Complete-pair changes",compact?"Each row uses the same metric-specific cases with valid scores at T0 and T1.":"T1 minus T0 is computed per person first and then summarised. The valid N in both waves can differ for each metric.");
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
function trends(view,st) {
  const host=section("Selected-period T0 and T1 comparison","The selected complete months are combined into two points and each wave is averaged separately. The respondents inside the period can differ, so this is not a per-person change.");
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
  const c=S.release_context;if(!c)return {};
  return {analytical_run_id:c.run_id,analytical_run_fingerprint:c.run_fingerprint,analytical_program_hash:c.program_hash,export_program_hash:c.export_program_hash,release_context_revision:c.revision,group_control_head:c.group_control_head,group_proposal_revision:c.group_proposal_revision,review_control_revision:c.review_control_revision,composed_manifest_revision:c.flags.manifest_revision,workload_scope:c.workload_scope};
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
function methods(){const host=section("Definitions & methods","Scoring, sample selection and denominators reuse the existing Python calculation layer. The paired test is computed in Python. The period summary combines the published monthly statistics.");for(const [label,text]of S.notes){const row=el('div','method-grid');row.append(el('b','',label),el('div','',text));host.append(row);}const extra=[["Parent wave policy",S.parent_wave_policy==='student_anchored_hk_nearest_v2'?"Eligible parent responses on or after the student T1 date are selected as T1 first. The other responses give the parent baseline closest to the student T0, which may be earlier than the student, with no hard limit on the date gap. The parent has no 90-day threshold of its own. The independent-parent branch is counted separately.":"This release keeps its published parent wave policy."],["T0 to T1 test","Two-sided paired t test on the formal pairs that are valid in both waves, with a paired N counted again under the current filter. Cohen's dz = mean of the per-person T1 - T0 differences / SD of the differences. The p-value has no multiple-comparison correction and is exploratory only; category metrics are not tested. Nothing is estimated when the change SD is zero or there are not enough pairs."],["Two-point period chart","Inside the selected complete months, each wave mean is weighted by its valid N and the SD combines the within-month and between-month variation. The complete data period is the default and custom months are kept. Small months are included as normal. The two points are not a per-person change and carry no paired test."],["Static export scope","Keeps the four formal sample modes, the nine child groups, the respondent, the mainstream/all-school scope and freely combined declared source filters. Individual schools, free combinations of identity rules and per-case detail stay on the local machine."],["Distribution and trends","The distribution offers all sources only and the longitudinal distribution uses the both-waves-valid basis. The monthly trend offers all groups and sources only, can include batch dates, supports complete months only, weights the period mean by the valid N and combines the within-month and between-month variation in the SD. Arbitrary day boundaries are not supported."],["Summary display",S.minimum_cell_n>0?`This snapshot applies a minimum cell size of ${S.minimum_cell_n}.`:"The research-team release shows complete aggregates and does not suppress by cell size; the distribution keeps a fixed scale binning. Personal identifiers, raw answers and personal extremes remain outside the export scope."],["Version updates","This snapshot never reads new data by itself. Re-export after each local release, then deploy the whole output folder."],["Version",`${S.release_id} · ${S.report_version}`]];for(const [label,text]of extra){const row=el('div','method-grid');row.append(el('b','',label),el('div','',text));host.append(row);}table(section("Metric dictionary"),S.dictionary,{label:"Metric",role:"Respondent",unit:"Unit",note:"Note"},'dictionary',true);}
function render(){const focusKey=document.activeElement?.dataset.control;if(eligibilityLoading){root.replaceChildren();notice(root,'Validating optional manual exclusion data…');return;}if(eligibility&&!eligibility.bundle){if(qualityMount){qualitySelection=qualityMount.getSelection();qualityUIState=qualityMount.getUIState();qualityMount.destroy();qualityMount=null;}root.replaceChildren();notice(root,'Requested manual exclusion is unavailable. Select OFF to restore the original published data.',true);return;}if(qualityMount){qualitySelection=qualityMount.getSelection();qualityUIState=qualityMount.getUIState();qualityMount.destroy();qualityMount=null;}const previousSidebar=root.querySelector('.sample-sidebar');if(previousSidebar)sidebarPositions.set(previousSidebar.dataset.sidebar,previousSidebar.scrollTop);root.replaceChildren();contentHost=root;document.querySelectorAll('nav button').forEach((b,i)=>b.setAttribute('aria-current',i===page?'page':'false'));try{[overview,()=>research(false),()=>research(true),evidence,tracking,methods][page]();}catch(error){notice(contentHost,"The page could not be displayed. Reload the complete static output.",true);console.error(error);}if(focusKey){const target=[...document.querySelectorAll('[data-control]')].find(node=>node.dataset.control===focusKey);target?.focus({preventScroll:true});}const sidebar=root.querySelector('.sample-sidebar');if(sidebar)sidebar.scrollTop=sidebarPositions.get(sidebar.dataset.sidebar)||0;}
tabs.forEach((name,i)=>{const b=el('button','',name);b.onclick=()=>{page=i;location.hash='page='+i;render();};document.querySelector('#nav').append(b);});const hash=Number(new URLSearchParams(location.hash.slice(1)).get('page'));if(Number.isInteger(hash)&&hash>=0&&hash<tabs.length)page=hash;
document.querySelector('#load-status').hidden=true;
document.querySelector('#banner').textContent="Read-only aggregate snapshot of the published release. Filtering happens in the browser and does not connect to SQLite; per-case verification and administrative work stay on the local machine.";
const date=value=>new Date(value).toLocaleString('en-HK',{timeZone:'Asia/Hong_Kong',hour12:false});document.querySelector('#published').textContent='Published '+date(S.published_at);document.querySelector('#version').textContent=`${S.release_id} · Snapshot ${date(S.generated_at)}`;document.querySelector('#footer-version').textContent=S.report_version;document.querySelector('#download-snapshot').onclick=()=>{if(eligibility&&!eligibility.bundle)return;download(eligibility?.configured?{format:'study2_manual_exclusion_snapshot_download_v1',eligibility:eligibility.metadata(),snapshot:S}:S,'study2-aggregate-snapshot.json');};
if(S.release_context){const c=S.release_context,p=el('p','meta');p.id='release-context';p.textContent=`Analytical run ${c.run_id} · run fingerprint ${c.run_fingerprint} · calculation code ${c.program_hash} · export code ${c.export_program_hash} · composed flags ${c.flags.combined_records} (Eric ${c.flags.eric_records}; group policy ${c.flags.group_records}; overlap ${c.flags.overlap_records}) · manifest ${c.flags.manifest_revision} · group control ${c.group_control_head} · workload/context ${c.revision}`;document.querySelector('#version').after(p);}
const eligibilityBar=el('section','manual-eligibility'),eligibilityLabel=el('label'),eligibilityToggle=el('input'),eligibilityStatus=el('p','caption');
eligibilityBar.setAttribute('aria-label','Manual submission exclusion');eligibilityToggle.type='checkbox';eligibilityToggle.dataset.control='manual:enabled';eligibilityToggle.id='manual-exclusion-enabled';eligibilityToggle.disabled=true;
eligibilityLabel.append(eligibilityToggle,document.createTextNode('Exclude manually flagged submissions'));eligibilityStatus.setAttribute('role','status');eligibilityStatus.setAttribute('aria-live','polite');eligibilityBar.append(eligibilityLabel,eligibilityStatus);root.before(eligibilityBar);
function refreshEligibility(){
 eligibilityToggle.checked=eligibility?.mode==='on';eligibilityToggle.disabled=eligibilityLoading||(!eligibility?.available&&eligibility?.mode!=='on');
 eligibilityStatus.textContent=eligibilityLoading?'Validating optional exclusion bundle…':eligibility?.mode==='on'&&!eligibility.bundle?'Requested ON is unavailable: '+eligibility.reason+'. Select OFF to restore published data.':eligibility?.available?'Manual exclusion '+eligibility.mode.toUpperCase()+' · revision '+eligibility.metadata().eligibility_revision+' · original published membership; no reselection.':'OFF data is available. ON unavailable: '+(eligibility?.reason||'manual_exclusion_not_supplied')+'.';
 eligibilityBar.dataset.state=eligibilityLoading?'loading':eligibility?.available?'ready':'unavailable';eligibilityBar.dataset.mode=eligibility?.mode||'off';
 document.querySelector('#download-snapshot').disabled=eligibilityLoading||Boolean(eligibility&&!eligibility.bundle);
}
eligibilityToggle.onchange=()=>{
 try{const bundle=eligibility.select(eligibilityToggle.checked?'on':'off');S=bundle.snapshot;activeScope=bundle.scope_export;}
 catch{ /* A requested invalid ON state is explicit; the original OFF stays selectable. */ }
 refreshEligibility();render();
};
refreshEligibility();render();
Study2ManualEligibility.create(baselineSnapshot,activeScope,window.STUDY2_MANUAL_EXCLUSION,typeof Study2Scope==='undefined'?null:Study2Scope).then(controller=>{
 eligibility=controller;
 if(baselineSnapshot.release_context?.default_eligibility==='on'){
  try{const bundle=controller.select('on');S=bundle.snapshot;activeScope=bundle.scope_export;}catch{ /* Explicit requested-ON unavailable state; OFF remains selectable. */ }
 }
 eligibilityLoading=false;refreshEligibility();render();
});
})();
'''


# Accepted presenter styles remain unchanged; these rules isolate them from
# the existing application table defaults.
STYLES += QUALITY_STYLES + r"""
.manual-eligibility{border:1px solid var(--line);background:#fff;border-radius:7px;padding:13px 17px;margin:0 0 20px}.manual-eligibility label{display:flex;align-items:center;gap:9px;margin:0;font-weight:600}.manual-eligibility input{flex-shrink:0}.manual-eligibility p{margin:7px 0 0;overflow-wrap:anywhere}

.s2-quality th,.s2-quality td{white-space:normal;min-width:0}
.s2-quality details{padding:8px}
.s2-quality .q-panel{overflow-wrap:anywhere}
"""
APP_JS = APP_JS.replace('__R04_NAVIGATION__', json.dumps([english(key) for key in (
    'nav.data_quality_and_progress','nav.descriptive_statistics',
    'nav.independent_parent_analysis','nav.matching_evidence',
    'nav.family_tracking','nav.definitions_and_methods')]))

# Grade pooling uses the existing protected app asset, without a new endpoint.
APP_JS = APP_JS.replace('"use strict";', '"use strict";\n' + GRADE_JS + '\n' + SOURCE_JS + '\n' + ELIGIBILITY_JS, 1)
