"""Optional aggregate-bundle UI adapter. No record mapping or statistics here."""

JS_SOURCE = r'''
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
  // the same-origin HTML's SRI, and only the first-tab data is usable here.
  // OFF and all other tabs still require the complete existing validator.
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
    need(e&&e.mode==='on'&&e.revision===boot.revision&&e.inventory_revision===boot.inventory_revision,'manual_scope_revision_mismatch');
    need(canonical(baseline.raw)===canonical(selected.raw)&&canonical(baseline.flow)===canonical(selected.flow),'manual_history_mismatch');
    need(canonical(e.intake)===canonical(boot.impact.intake)&&canonical(e.samples)===canonical(boot.impact.samples),'manual_impact_mismatch');
    agreeSamples(boot.impact.samples,selected);
    for(const row of boot.impact.samples){const s=baseline.samples.find(r=>r.code===row.code);
      need(s&&(s.status==='available'?s.count===row.baseline:row.baseline===null),'manual_impact_mismatch');
      if(row.baseline!==null)need(original.counts?.[row.code]===row.baseline&&active.counts?.[row.code]===row.active,'manual_count_mismatch');}
    if(boot.impact.independent!==null)for(const [key,row] of Object.entries(boot.impact.independent))
      need(original.independent_counts?.[key]===row.baseline&&active.independent_counts?.[key]===row.active,'manual_independent_count_mismatch');
    freeze(boot);
    function metadata(){return Object.freeze({eligibility_mode:'on',eligibility_revision:boot.revision,
      eligibility_inventory_revision:boot.inventory_revision,eligibility_release_id:boot.release_id,
      eligibility_policy:POLICY,eligibility_status:'available'});}
    function quality(result){
      const current=result.eligibility;need(current&&current.mode==='on'&&current.revision===boot.revision&&
        current.inventory_revision===boot.inventory_revision,'manual_scope_revision_mismatch');
      const before=engine.query(off.scope_export.index,result.scope);need(canonical(result.raw)===canonical(before.raw),'manual_history_mismatch');
      need(Array.isArray(current.samples)&&current.samples.length===9);agreeSamples(current.samples,result);
      for(const row of current.samples){summary(row,true);const s=before.samples.find(s=>s.code===row.code);need(s&&s.count===row.baseline,'manual_impact_mismatch');}
      return {format:'study2_manual_exclusion_ui_v1',mode:'on',revision:boot.revision,inventory_revision:boot.inventory_revision,
        release_id:boot.release_id,policy:POLICY,status:'available',code:null,intake:current.intake,samples:current.samples};
    }
    return Object.freeze({configured:true,available:true,reason:null,mode:'on',bundle:on,metadata,quality,
      select(requested){need(requested==='on','bootstrap_full_required');return on;}});
  }
  return Object.freeze({create,createBootstrap,digest,canonical});
})();
'''
