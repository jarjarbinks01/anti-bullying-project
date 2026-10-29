"""Protected sparse-period asset loading and presentation only; no statistics."""

JS_SOURCE = r'''
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
'''
