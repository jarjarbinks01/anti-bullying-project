"""Pure browser query module, served by a future accepted exporter integration.

JS_SOURCE declares Study2Scope and a CommonJS export for synthetic Node tests.
It performs no DOM, network, filesystem, storage, scoring or matching operations.
"""

JS_SOURCE = r'''"use strict";
const Study2Scope = (() => {
  const FORMAT = "study2_scope_v1", RESULT = "study2_scope_result_v1";
  const roles = ["student", "parent"];
  const slots = {A:["student"], B:["parent"], C:["student"], D:["parent"],
    AC:["student","student"], BD:["parent","parent"], E:["student","parent"],
    F:["student","parent"], EF:["student","parent","student","parent"]};
  const stages = ["screening","exact_copies","repeat_handling","selection"];
  const requiredChecks=["submissions","status_counts","2.1.3","2.1.4","2.1.6",...Object.keys(slots)];
  const reasons = {
    screening:["excluded_school","sparse_response","incomplete","unrecognized_survey"],
    exact_copies:["exact_input_repeat"], repeat_handling:["short_repeat","manual_excluded"],
    selection:["parent_no_reliable_student_baseline","parent_other_same_phase_response",
      "extra_followup","short_interval_followup","pending_chronology","parent_before_student_baseline"],
    selected:["selected"]};
  const adultPolicy = "same_child_valid_equal_birth_year_any_exact_contact_relationship_informational";
  const unsafe = /[<>\x00-\x08\x0a-\x1f\x7f]|(?:https?:\/\/|www\.|mailto:)|[\w.+-]+@[\w.-]+\.\w+|(?:[/\\][\w.-]+[/\\])|(?:SUB|GROUP|RESP|DYAD)_[A-Za-z0-9_-]+|(?:CHILD|CASE|REV|PKG|RB|DEC|DRES|DEVENT|INV)_[0-9a-f]{20,}|\bR_[A-Za-z0-9]{10,}\b/i;
  const privateReleaseLabel=/\bRUN_[A-Za-z0-9_-]+/i;
  const phone=/\+?[0-9][0-9 \t.()/\-\u2010-\u2015\u2212]{6,}[0-9]/;
  const academicContext=/\b(?:academic|school|study|survey|questionnaire)\b|學年|問卷|研究/i;
  const contactContext=/\b(?:contact|call|phone|telephone|mobile|whatsapp|tel)\b|電話|聯絡/i;
  function suspectLabel(value) {
    if(unsafe.test(value) || privateReleaseLabel.test(value)) return true;
    if(contactContext.test(value) && phone.test(value)) return true;
    const withoutDates=value.replace(/(?<![0-9])[0-9]{4}-[0-9]{2}-[0-9]{2}(?![0-9])/g,token=>{
      const year=Number(token.slice(0,4));
      try { iso(token); return year>=1900 && year<=2100 ? "":token; } catch(e) { return token; }
    });
    const withoutYears=withoutDates.replace(/(?<![0-9])([0-9]{4})[-/]([0-9]{4})(?![0-9])/g,(token,a,b)=>{
      const year=Number(a);
      return year>=1900 && year<2100 && Number(b)===year+1 && academicContext.test(value) ? "":token;
    });
    return phone.test(withoutYears);
  }
  const fail = message => { throw new Error(message); };
  const need = (test, message) => { if (!test) fail(message); };
  const fields = (value, keys) => need(value && typeof value === "object" && !Array.isArray(value) &&
    Object.keys(value).sort().join("|") === [...keys].sort().join("|"), "unexpected_fields");
  const count = value => need(Number.isSafeInteger(value) && value >= 0, "invalid_count");
  const token = value => need(typeof value === "string" && /^[A-Za-z0-9][A-Za-z0-9_.:-]{0,159}$/.test(value) && !unsafe.test(value) && !/^\d{8,}$/.test(value), "invalid_metadata");
  const label = (value, nullable=false) => {
    if (nullable && (value === null || value === "")) return;
    need(typeof value === "string" && value.trim().length > 0 && value.length <= 500 && !suspectLabel(value), "unsafe_or_missing_label");
  };
  const iso = value => {
    need(typeof value === "string" && /^\d{4}-\d{2}-\d{2}$/.test(value), "invalid_iso_date");
    const [y,m,d] = value.split("-").map(Number);
    const days = [31, y%4===0 && (y%100!==0 || y%400===0) ? 29 : 28,31,30,31,30,31,31,30,31,30,31];
    need(y>=1 && m>=1 && m<=12 && d>=1 && d<=days[m-1], "invalid_iso_date");
  };
  const zeros = names => Object.fromEntries(names.map(n => [n,0]));
  const equal = (a,b) => JSON.stringify(a)===JSON.stringify(b);
  function validate(index) {
    need(index && index.format===FORMAT, "compatible_scope_export_required");
    fields(index,["format","meta","sources","surveys","profiles","records","samples","schools"]);
    for (const name of ["sources","surveys","profiles","records","samples","schools"]) need(Array.isArray(index[name]),"invalid_array");
    const meta=index.meta;
    fields(meta,["release_id","schema","adult","flow","school","reconciliation"]);
    token(meta.release_id); need(meta.schema===FORMAT,"invalid_schema");
    for (const feature of ["adult","flow","school"]) {
      const item=meta[feature], key=feature==="adult" ? "policy" : "revision";
      fields(item,["status",key,"reason",...(feature==="adult" ? ["evidence"]:[]),...(feature==="school" && item.status==="available" ? ["statuses"] : [])]);
      need(["available","unavailable"].includes(item.status),"invalid_feature_status");
      if(item[key]!==null) token(item[key]); if(item.reason!==null) token(item.reason);
      if(item.status==="available") need(item.reason===null && item[key]!==null,"missing_feature_provenance");
      if(feature==="adult") need(item.status==="available" ? item.policy===adultPolicy && item.evidence==="formal_parent_longitudinal_artifact" : item.evidence===null,"unsupported_adult_policy_or_evidence");
    }
    fields(meta.reconciliation,["status","checked"]);
    need(["checked","partial"].includes(meta.reconciliation.status) && Array.isArray(meta.reconciliation.checked) &&
      new Set(meta.reconciliation.checked).size===meta.reconciliation.checked.length && meta.reconciliation.checked.every(
        k=>requiredChecks.includes(k)),"invalid_reconciliation");
    if(meta.reconciliation.status==="checked") need(requiredChecks.every(k=>meta.reconciliation.checked.includes(k)) &&
      meta.flow.status==="available" && meta.adult.status==="available","invalid_reconciliation");
    const sources = new Map(), surveys = new Map();
    for(const row of index.sources) {
      fields(row,["key","label"]); label(row.label);
      need(/^src_[0-9a-f]{24}$/.test(row.key) && !sources.has(row.key),"invalid_source_catalogue"); sources.set(row.key,row);
    }
    for(const row of index.surveys) {
      fields(row,["key","label","missing_name","source_key","role","form_id","form_version","identity_basis","provenance"]);
      label(row.label); label(row.form_id,true); label(row.form_version,true);
      need(/^svy_[0-9a-f]{24}$/.test(row.key) && !surveys.has(row.key) && sources.has(row.source_key) && roles.includes(row.role) &&
        typeof row.missing_name==="boolean" && (!row.missing_name || row.label==="Missing survey name") &&
        row.identity_basis===(row.form_id ? "form_metadata" : "source_role_name_only") && row.provenance==="answer.Survey","invalid_survey_catalogue");
      surveys.set(row.key,row);
    }
    const seenProfiles=new Set();
    for(const p of index.profiles) {
      fields(p,["source_key","survey_key","role","day","timing_basis","date_state"]);
      need(sources.has(p.source_key) && surveys.has(p.survey_key) && roles.includes(p.role),"invalid_profile_reference");
      const s=surveys.get(p.survey_key);
      need(s.source_key===p.source_key && s.role===p.role,"profile_catalogue_mismatch");
      need(["observed","manual_verified","accepted_batch","unknown"].includes(p.timing_basis) &&
        ["usable","missing","naive","invalid","untrusted"].includes(p.date_state),"invalid_timing_profile");
      if(p.day!==null) iso(p.day);
      need((p.day!==null)===(p.date_state==="usable") && (p.day===null || p.timing_basis!=="unknown"),"day_state_mismatch");
      const signature=JSON.stringify([p.source_key,p.survey_key,p.role,p.day,p.timing_basis,p.date_state]);
      need(!seenProfiles.has(signature),"duplicate_profile"); seenProfiles.add(signature);
    }
    const ref=p=>need(Number.isSafeInteger(p) && p>=0 && p<index.profiles.length,"invalid_profile_position");
    const total=zeros(index.profiles.map((_,i)=>i)), selected={...total}, singles={...total};
    let nraw=0;
    for(const r of index.records) {
      fields(r,["profile","exit_stage","reason","original_wave","count"]); ref(r.profile); count(r.count);
      need(r.count>0 && Object.hasOwn(reasons,r.exit_stage) && reasons[r.exit_stage].includes(r.reason) && ["T0","T1","unknown"].includes(r.original_wave),"invalid_record_fact");
      total[r.profile]+=r.count; nraw+=r.count; if(r.exit_stage==="selected") selected[r.profile]+=r.count;
    }
    count(nraw); need(Object.values(total).every(n=>n>0),"orphan_profile");
    for(const r of index.samples) {
      fields(r,["code","profiles","count"]); count(r.count);
      need(Object.hasOwn(slots,r.code) && Array.isArray(r.profiles) && r.profiles.length===slots[r.code].length && r.count>0 && r.count<=nraw,"invalid_sample_cell");
      r.profiles.forEach((p,i)=>{ref(p); need(index.profiles[p].role===slots[r.code][i],"sample_slot_role_mismatch");});
      need(r.code!=="BD" || meta.adult.status==="available","unavailable_adult_has_cells");
      if(r.profiles.length===1) singles[r.profiles[0]]+=r.count;
    }
    need(equal(singles,selected),"selected_sample_reconciliation");
    const margins=Object.fromEntries(["A","B","C","D"].map(c=>[c,zeros(index.profiles.map((_,i)=>i))]));
    for(const r of index.samples) if(Object.hasOwn(margins,r.code)) margins[r.code][r.profiles[0]]+=r.count;
    for(const [code,requirements] of Object.entries({AC:"AC",BD:"B?",E:"AB",F:"CD",EF:"ABCD"})) {
      const demands=[...requirements].map(()=>zeros(index.profiles.map((_,i)=>i))), rawDemands=zeros(index.profiles.map((_,i)=>i));
      for(const r of index.samples) if(r.code===code) r.profiles.forEach((p,i)=>{demands[i][p]+=r.count; rawDemands[p]+=r.count;});
      [...requirements].forEach((c,i)=>{
        const limit=c==="?" ? total:margins[c];
        need(Object.entries(demands[i]).every(([p,n])=>n<=limit[p]),"sample_marginal_exceeded");
      });
      need(Object.entries(rawDemands).every(([p,n])=>n<=total[p]),"sample_marginal_multiplicity_exceeded");
    }
    const statuses=meta.school.statuses || [];
    need(Array.isArray(statuses) && new Set(statuses).size===statuses.length,"invalid_school_statuses"); statuses.forEach(token);
    const schoolTotals={...total}; Object.keys(schoolTotals).forEach(k=>schoolTotals[k]=0);
    for(const r of index.schools) {
      fields(r,["profile","status","count"]); ref(r.profile); count(r.count);
      need(r.count>0 && statuses.includes(r.status),"invalid_school_cell"); schoolTotals[r.profile]+=r.count;
    }
    if(meta.school.status==="available") need(equal(schoolTotals,total),"school_record_reconciliation");
    for(const [name,keys] of [["records",["profile","exit_stage","reason","original_wave"]],["samples",["code","profiles"]],["schools",["profile","status"]]])
      need(new Set(index[name].map(r=>JSON.stringify(keys.map(k=>r[k])))).size===index[name].length,"duplicate_aggregate_cell");
    return index;
  }
  function defaults(index) {
    return {sources:index.sources.map(s=>s.key), surveys:index.surveys.map(s=>s.key),start:null,end:null,include_unknown:true};
  }
  function normalize(index, selection=null) {
    if(selection===null) return defaults(index);
    need(selection && typeof selection==="object" && !Array.isArray(selection) && Object.keys(selection).every(
      k=>["sources","surveys","start","end","include_unknown"].includes(k)),"invalid_selection_fields");
    const scope={...defaults(index),...selection};
    for(const name of ["sources","surveys"]) {
      const keys=new Set(index[name].map(r=>r.key));
      need(Array.isArray(scope[name]) && scope[name].every(k=>typeof k==="string" && keys.has(k)),"unknown_selection_key:"+name);
      scope[name]=[...new Set(scope[name])].sort();
    }
    for(const name of ["start","end"]) if(scope[name]!==null) iso(scope[name]);
    need(!(scope.start && scope.end && scope.start>scope.end),"reversed_date_bounds");
    if(!Object.hasOwn(selection,"include_unknown")) scope.include_unknown=!(scope.start || scope.end);
    need(typeof scope.include_unknown==="boolean","invalid_include_unknown"); return scope;
  }
  function transition(index,current,patch) {
    const old=normalize(index,current), next={...old,...patch};
    need(patch && typeof patch==="object" && !Array.isArray(patch),"invalid_selection_patch");
    if(!(old.start || old.end) && (next.start || next.end) && !Object.hasOwn(patch,"include_unknown")) next.include_unknown=false;
    return normalize(index,next);
  }
  function catalogueOptions(index,facet,search="") {
    need(["sources","surveys"].includes(facet) && typeof search==="string","invalid_catalogue_search");
    return index[facet].filter(r=>r.label.toLowerCase().includes(search.toLowerCase())).map(r=>({...r}));
  }
  function matches(p,s,ignore=null) {
    if(ignore!=="sources" && !s.sources.includes(p.source_key)) return false;
    if(ignore!=="surveys" && !s.surveys.includes(p.survey_key)) return false;
    if(p.day===null) return s.include_unknown;
    return (s.start===null || p.day>=s.start) && (s.end===null || p.day<=s.end);
  }
  function query(index,selection=null) {
    validate(index); const scope=normalize(index,selection), mask=index.profiles.map(p=>matches(p,scope));
    const raw=zeros(roles), outside=zeros(roles), unknownExcluded=zeros(roles);
    const sources=index.sources.map(s=>({source_key:s.key,label:s.label,student:0,parent:0}));
    const sourceMap=new Map(sources.map(s=>[s.source_key,s]));
    const facets={sources:zeros(index.sources.map(s=>s.key)),surveys:zeros(index.surveys.map(s=>s.key))};
    const basis=zeros(["observed","manual_verified","accepted_batch","unknown"]);
    const states=zeros(["usable","missing","naive","invalid","untrusted"]);
    const original=Object.fromEntries(roles.map(r=>[r,zeros(["T0","T1","unknown"])]));
    const lanes=Object.fromEntries(roles.map(r=>[r,Object.fromEntries(stages.map(s=>[s,{entering:0,remaining:0,exits:zeros(reasons[s])}]))]));
    for(const r of index.records) {
      const p=index.profiles[r.profile], role=p.role,n=r.count;
      for(const [name,key] of [["sources","source_key"],["surveys","survey_key"]]) if(matches(p,scope,name)) facets[name][p[key]]+=n;
      if(p.day===null && scope.sources.includes(p.source_key) && scope.surveys.includes(p.survey_key) && !scope.include_unknown) unknownExcluded[role]+=n;
      if(!mask[r.profile]) {outside[role]+=n;continue;}
      raw[role]+=n; sourceMap.get(p.source_key)[role]+=n; basis[p.timing_basis]+=n; states[p.date_state]+=n; original[role][r.original_wave]+=n;
      for(const stage of stages) {
        const lane=lanes[role][stage]; lane.entering+=n;
        if(r.exit_stage===stage) {lane.exits[r.reason]+=n; break;} lane.remaining+=n;
      }
    }
    const samples=Object.keys(slots).map(code=>{
      const available=code!=="BD" || index.meta.adult.status==="available";
      const n=index.samples.filter(r=>r.code===code && r.profiles.every(p=>mask[p])).reduce((a,r)=>a+r.count,0);
      return {code,status:available ? "available":"unavailable",count:available ? n:null,
        unit:slots[code].length===1 ? "questionnaire_records" : ["AC","BD"].includes(code) ? "longitudinal_cases":"dyads",
        policy:code==="BD" ? index.meta.adult.policy:"fixed_published_slots",
        continuity_evidence:code==="BD" ? index.meta.adult.evidence:null,reason:available ? null:index.meta.adult.reason};
    });
    const flow={...index.meta.flow,unit:"questionnaire_records",lanes:index.meta.flow.status==="available" ? lanes:null};
    const school={...index.meta.school,unit:"questionnaire_records",counts:null};
    if(school.status==="available") {
      school.counts=Object.fromEntries(school.statuses.map(s=>[s,zeros(roles)]));
      for(const r of index.schools) if(mask[r.profile]) school.counts[r.status][index.profiles[r.profile].role]+=r.count;
    }
    return {format:RESULT,release_id:index.meta.release_id,schema:FORMAT,scope,
      date_policy:{timezone:"Asia/Hong_Kong",inclusive:true,unknown_excluded:unknownExcluded,
        included_unknown_interval_unverified:Boolean((scope.start || scope.end) && scope.include_unknown && Object.entries(states).some(([k,n])=>k!=="usable" && n>0))},
      raw,out_of_scope:outside,sources,samples,flow,
      facets:Object.fromEntries(Object.entries(facets).map(([name,counts])=>[name,Object.entries(counts).map(([key,available])=>({key,available}))])),
      dates:{timing_basis:basis,date_state:states},original_waves:original,
      identity_groups:{status:"unavailable",count:null,unit:"identity_groups",reason:"represented_group_signatures_not_provided"},
      school:JSON.parse(JSON.stringify(school)),reconciliation:{...index.meta.reconciliation,checked:[...index.meta.reconciliation.checked]},
      scope_notice:"First-tab scope only; published matching and other tabs are unchanged."};
  }
  return Object.freeze({query,validate,defaultSelection:defaults,normalizeSelection:normalize,transitionSelection:transition,catalogueOptions,FORMAT});
})();
if (typeof module !== "undefined" && module.exports) module.exports=Study2Scope;
'''
