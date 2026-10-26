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
  return {createLoader,refFor,day,extent,academicPeriods,selection,csvMetadata,mount,present};
})();
'''
