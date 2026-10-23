"""Isolated first-tab presentation. R04 owns export/app integration.

Load accepted static_scope_client.JS_SOURCE before JS_SOURCE, then call
Study2Quality.mount(element, index, options). No research logic or I/O here.
School projections must be validated by accepted R03 r3 on the local export side;
the optional host provider binds a supplied projection to one exact result key.
indexRevision is the host's immutable index pin. This view does not authenticate
that pin or implement a school query. A missing/stale binding stays unavailable.
"""

STYLES = r'''
.s2-quality{--ink:#24354e;--muted:#596b83;--line:#dce2ed;--paper:#f5f7fb;--accent:#293f70;color:var(--ink);font:15px/1.55 system-ui,sans-serif;max-width:1440px;margin:auto;min-width:0;overflow-wrap:anywhere}
.s2-quality *{box-sizing:border-box;min-width:0}.s2-quality h2{font-size:25px;margin:0 0 6px}.s2-quality h3{font-size:18px;margin:0 0 12px}.s2-quality h4{font-size:15px;margin:0 0 7px}.s2-quality p{margin:6px 0 12px}.s2-quality button,.s2-quality input{font:inherit}.s2-quality button{cursor:pointer;padding:7px 11px;background:white;color:var(--accent);border:1px solid #a9b7ce;border-radius:5px}.s2-quality button:disabled{cursor:default;opacity:.55}.s2-quality :focus-visible{outline:3px solid #af4c00;outline-offset:3px}.s2-quality input[type=search],.s2-quality input[type=date]{width:100%;padding:8px;border:1px solid #a9b7ce;border-radius:4px;background:white;color:var(--ink)}
.s2-quality .q-panel{background:white;border:1px solid var(--line);border-radius:8px;padding:18px;margin-bottom:18px}.s2-quality .q-note{color:var(--muted);font-size:13px}.s2-quality .q-notice{border-left:4px solid #526bba;padding:10px 13px;background:#edf2fb;overflow-wrap:anywhere}.s2-quality .q-controls,.s2-quality .q-two{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:18px}.s2-quality fieldset{border:1px solid var(--line);border-radius:6px;padding:12px;margin:0}.s2-quality legend{font-weight:700;padding:0 4px}.s2-quality .q-actions{display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin:10px 0}.s2-quality .q-list{max-height:270px;overflow:auto;scrollbar-gutter:stable;margin-top:9px;padding:3px}
.s2-quality .q-option{display:grid;grid-template-columns:20px minmax(0,1fr);gap:8px;padding:9px 3px;border-top:1px solid var(--line);overflow-wrap:anywhere;cursor:pointer}.s2-quality .q-option input{margin-top:5px;width:17px;height:17px}.s2-quality .q-option small{display:block;color:var(--muted);font-size:12px}.s2-quality .q-dates{display:grid;grid-template-columns:1fr 1fr 2fr;gap:16px;align-items:center;margin-top:16px}.s2-quality .q-dates label{display:block}.s2-quality .q-toggle{display:flex!important;gap:9px;align-items:start}.s2-quality .q-toggle input{margin-top:5px;flex-shrink:0}.s2-quality .q-top{display:flex;gap:16px;justify-content:space-between;align-items:center;flex-wrap:wrap}.s2-quality .q-number{font-size:36px;font-weight:750;line-height:1.3;font-variant-numeric:tabular-nums}.s2-quality .q-card{border-top:3px solid #526bba}.s2-quality .q-samples{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:16px}.s2-quality .q-sample{padding:12px 0;border-top:1px solid var(--line)}.s2-quality .q-sample strong{display:block;font-size:27px}.s2-quality .q-sample small{display:block;color:var(--muted)}
.s2-quality .q-lane{border:1px solid var(--line);border-radius:6px;padding:14px;background:var(--paper)}.s2-quality .q-node{background:white;border:1px solid var(--line);border-radius:6px;padding:13px}.s2-quality .q-node dl{display:grid;grid-template-columns:1fr auto;gap:4px;margin:0}.s2-quality dt,.s2-quality dd{margin:0}.s2-quality .q-arrow{text-align:center;font-weight:bold;color:#526bba;line-height:28px}.s2-quality details{margin:9px 0}.s2-quality summary{cursor:pointer;font-weight:600}.s2-quality table{width:100%;border-collapse:collapse;font-size:14px;table-layout:fixed}.s2-quality th,.s2-quality td{text-align:right;vertical-align:top;padding:9px;border-bottom:1px solid var(--line);overflow-wrap:anywhere}.s2-quality th:first-child,.s2-quality td:first-child{text-align:left}.s2-quality th{background:#eef2f9}.s2-quality .q-key{overflow-wrap:anywhere}.s2-quality .q-status{font-weight:650}.s2-quality [hidden]{display:none!important}
@media(max-width:760px){.s2-quality .q-controls,.s2-quality .q-two,.s2-quality .q-samples,.s2-quality .q-dates{grid-template-columns:1fr}.s2-quality .q-panel{padding:14px}.s2-quality .q-number{font-size:32px}.s2-quality .q-list{max-height:240px}.s2-quality h2{font-size:22px}}
'''

JS_SOURCE = r'''"use strict";
const Study2Quality = (() => {
  const stages={screening:"Screening",exact_copies:"Exact duplicate copies",repeat_handling:"Repeat responses",selection:"Published selection"};
  const reasons={excluded_school:"School exclusion",sparse_response:"Insufficient answers",incomplete:"Incomplete response",unrecognized_survey:"Unrecognized questionnaire",exact_input_repeat:"Exact duplicate",short_repeat:"Short-interval repeat",manual_excluded:"Reviewed exclusion",parent_no_reliable_student_baseline:"No reliable student baseline",parent_other_same_phase_response:"Other parent response in the same phase",extra_followup:"Additional follow-up",short_interval_followup:"Follow-up below the interval rule",pending_chronology:"Chronology not established",parent_before_student_baseline:"Parent response before student baseline"};
  const units={questionnaire_records:"questionnaire records",longitudinal_cases:"longitudinal cases",dyads:"dyads"};
  const names={A:"Student baseline",C:"Student follow-up",AC:"Same student across waves",B:"Parent baseline",D:"Parent follow-up",BD:"Parent across waves",E:"Baseline student-parent pair",F:"Follow-up student-parent pair",EF:"Student-parent pair across waves"};
  const stateNames={mapped:"Mapped",invalid:"Verified invalid",historical_only:"Historical only",pending:"Verified pending",unreviewed:"Unreviewed",not_reconciled:"Not reconciled",no_queue_label:"Outside the review queue"};
  const roles=["student","parent"], roleName=r=>r==="student"?"Students":"Parents";
  const copy=x=>JSON.parse(JSON.stringify(x));
  // JSON object member order is insignificant; array order and presence matter.
  function same(a,b){
    if(a===b)return true;
    if(a===null||b===null||typeof a!=="object"||typeof b!=="object")return false;
    if(Array.isArray(a)!==Array.isArray(b))return false;
    if(Array.isArray(a)&&a.length!==b.length)return false;
    const keys=Object.keys(a);
    return keys.length===Object.keys(b).length&&keys.every(key=>Object.hasOwn(b,key)&&same(a[key],b[key]));
  }
  const n=x=>Number.isSafeInteger(x)&&x>=0?x.toLocaleString("en-HK"):"Unavailable";
  function text(tag,value,cls){const e=document.createElement(tag);if(value!==undefined)e.textContent=String(value);if(cls)e.className=cls;return e;}
  function button(label,handler){const b=text("button",label);b.type="button";b.addEventListener("click",handler);return b;}
  function panel(host,title){const e=text("section",undefined,"q-panel");if(title)e.append(text("h3",title));host.append(e);return e;}
  function note(host,value){host.append(text("p",value,"q-note"));}
  function table(host,headers,rows){const t=text("table"),head=text("thead"),tr=text("tr");for(const h of headers){const c=text("th",h);c.scope="col";tr.append(c);}head.append(tr);t.append(head);const body=text("tbody");for(const row of rows){const r=text("tr");for(const value of row)r.append(text("td",value));body.append(r);}t.append(body);host.append(t);return t;}
  function detail(host,title){const d=text("details");d.append(text("summary",title));host.append(d);return d;}
  function eligibilityContext(value,result){
    const need=(ok)=>{if(!ok)throw Error("invalid_eligibility_ui_context");};
    const count=n=>Number.isSafeInteger(n)&&n>=0;
    need(value&&value.format==="study2_manual_exclusion_ui_v1"&&["off","on"].includes(value.mode)&&value.release_id===result.release_id&&value.policy==="fixed_original_members_no_reselection");
    need(["available","unavailable"].includes(value.status)&&(value.mode!=="on"||value.status==="available")&&value.intake&&Array.isArray(value.samples)&&value.samples.length===9);
    for(const role of roles){const r=value.intake[role];need(r&&Object.values(r).every(count)&&Object.keys(r).sort().join() === "baseline,excluded,retained"&&r.baseline===result.raw[role]&&r.retained+r.excluded===r.baseline&&(value.mode!=="off"||r.excluded===0));}
    const codes=["A","B","C","D","AC","BD","E","F","EF"];
    need(new Set(value.samples.map(r=>r.code)).size===9);
    for(const code of codes){const r=value.samples.find(r=>r.code===code),active=result.samples.find(r=>r.code===code);need(r&&active&&Object.keys(r).sort().join()==="active,baseline,code,excluded");
      if(active.status!=="available")need(r.baseline===null&&r.active===null&&r.excluded===null);
      else need([r.baseline,r.active,r.excluded].every(count)&&r.active===active.count&&r.active+r.excluded===r.baseline&&(value.mode!=="off"||r.excluded===0));
    }
    return copy(value);
  }

  function mount(root,index,options={}) {
    if(!(root instanceof Element))throw new Error("quality_root_required");
    const E=Study2Scope;let selection=null,current=null,sequence=0,destroyed=false,searches={sources:"",surveys:""},draftDates=null;
    root.classList.add("s2-quality");root.replaceChildren();
    const heading=panel(root);heading.append(text("h2","Data quality and progress"));
    heading.append(text("p",options.eligibilityFor?"Source, questionnaire and date scope applies to this tab. Manual exclusion mode applies across analysis tabs; published matching remains fixed.":"First-tab scope only; published matching and other tabs are unchanged.","q-notice"));
    const controls=panel(root,"Choose the published scope"), status=text("p","Loading compatible aggregate export…","q-status");status.setAttribute("role","status");status.setAttribute("aria-live","polite");root.append(status);
    const summary=panel(root),body=text("div");root.append(body);
    const download=button("Download current aggregate JSON",()=>{if(!current)return;const value=copy(current);if(options.onDownload)options.onDownload(value);else{const url=URL.createObjectURL(new Blob([JSON.stringify(value,null,2)],{type:"application/json"}));const a=text("a");a.href=url;a.download="study2-quality-aggregate.json";a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}});download.disabled=true;heading.append(download);
    const lists={},searchInputs={},dateInputs={};let unknown;
    function clear(message){current=null;download.disabled=true;body.replaceChildren();summary.replaceChildren();status.textContent=message;root.dataset.state="unavailable";root.setAttribute("aria-busy","false");}
    function updateControls(result){
      const focused=document.activeElement,focusFacet=focused?.dataset.facet,focusKey=focused?.dataset.key;
      for(const facet of ["sources","surveys"]){
        lists[facet].replaceChildren();const rows=E.catalogueOptions(index,facet,searches[facet]);
        const availability=new Map((result?.facets[facet]||[]).map(r=>[r.key,r.available]));
        if(!rows.length)note(lists[facet],"No catalogue options match this search. Selection is unchanged.");
        for(const row of rows){const label=text("label",undefined,"q-option"),input=document.createElement("input");input.type="checkbox";input.checked=selection[facet].includes(row.key);input.dataset.facet=facet;input.dataset.key=row.key;input.dataset.control="quality:"+facet+":"+row.key;input.addEventListener("change",()=>{const chosen=new Set(selection[facet]);input.checked?chosen.add(row.key):chosen.delete(row.key);selection=E.normalizeSelection(index,{...selection,[facet]:[...chosen]});request();});
          const description=text("span"),name=text("span",row.label);description.append(name);
          if(facet==="surveys"){const source=index.sources.find(s=>s.key===row.source_key);description.append(text("small",`${roleName(row.role)} · ${source.label}${row.form_id?" · Form "+row.form_id:""}${row.form_version?" · Version "+row.form_version:""}`));description.append(text("small",row.identity_basis==="form_metadata"?"Identity from supplied form metadata":"Name, source and role only; form identity is not independently resolved."));}
          description.append(text("small",`${availability.has(row.key)?n(availability.get(row.key)):"Unavailable"} available · ${input.checked?"Selected":"Not selected"}`));label.append(input,description);lists[facet].append(label);
        }
      }
      dateInputs.start.value=(draftDates||selection).start||"";dateInputs.end.value=(draftDates||selection).end||"";unknown.checked=selection.include_unknown;
      if(focusFacet)Array.from(lists[focusFacet].querySelectorAll("input")).find(i=>i.dataset.key===focusKey)?.focus({preventScroll:true});
    }
    function scopeSummary(result,eligibility){
      summary.replaceChildren();summary.append(text("h3","Current scope"));
      summary.append(text("p",`${selection.sources.length} of ${index.sources.length} sources · ${selection.surveys.length} of ${index.surveys.length} questionnaire versions`));
      if(eligibility)note(summary,`Manual exclusion: ${eligibility.mode.toUpperCase()} · revision: ${eligibility.revision||"Unavailable"} · fixed original membership; no reselection.`);
      const chosen=detail(summary,"Selected source and questionnaire names");
      for(const facet of ["sources","surveys"]){const ul=text("ul");for(const row of index[facet].filter(r=>selection[facet].includes(r.key))){let label=row.label;if(facet==="surveys")label+=` · ${roleName(row.role)} · ${index.sources.find(s=>s.key===row.source_key).label}${row.form_id?" · Form "+row.form_id:""}${row.form_version?" · Version "+row.form_version:""}`;ul.append(text("li",label));}chosen.append(text("h4",facet==="sources"?"Sources":"Questionnaire versions"),ul);if(!ul.children.length)note(chosen,"None selected.");}
      summary.append(text("p",`${selection.start||"No start bound"} to ${selection.end||"No end bound"} · inclusive Hong Kong calendar days (Asia/Hong_Kong)`));
      note(summary,`Unknown dates: ${selection.include_unknown?"included":"excluded"}. Release: ${result.release_id}. Schema: ${result.schema}. Reconciliation: ${result.reconciliation.status}.`);
      note(summary,`Date basis — observed: ${n(result.dates.timing_basis.observed)}; manually verified: ${n(result.dates.timing_basis.manual_verified)}; accepted batch dates: ${n(result.dates.timing_basis.accepted_batch)}; unknown: ${n(result.dates.timing_basis.unknown)}.`);
      note(summary,`Date usability in this scope · missing: ${n(result.dates.date_state.missing)}; timezone absent: ${n(result.dates.date_state.naive)}; invalid: ${n(result.dates.date_state.invalid)}; untrusted: ${n(result.dates.date_state.untrusted)} questionnaire records. These entries have unknown or unusable Hong Kong dates.`);
      note(summary,`Unknown or unusable dates excluded by this date selection: students ${n(result.date_policy.unknown_excluded.student)}, parents ${n(result.date_policy.unknown_excluded.parent)}. Out-of-scope entries are not cleaning exclusions.`);
      if(result.date_policy.included_unknown_interval_unverified)summary.append(text("p","Included unknown-date responses are not known to satisfy this interval.","q-notice"));
    }
    function render(result,school,eligibility){
      body.replaceChildren();scopeSummary(result,eligibility);const intake=text("div",undefined,"q-two");body.append(intake);
      for(const role of roles){const card=panel(intake,roleName(role)+" · raw intake");card.classList.add("q-card");const value=text("div",n(result.raw[role]),"q-number");value.dataset.raw=role;card.append(value);note(card,"Questionnaire records before cleaning, within the current scope.");note(card,`Outside this scope: ${n(result.out_of_scope[role])} questionnaire records.`);if(eligibility){const e=eligibility.intake[role];note(card,"Historical published intake; manual exclusions are a separate analytical overlay.");const counts=text("p");counts.append(text("span",`Actively excluded intake: ${n(e.excluded)}`),text("br"),text("span",`Retained intake: ${n(e.retained)}`));counts.dataset.eligibilityIntake=role;card.append(counts);}}
      const flow=panel(body,"Follow the questionnaire records");note(flow,eligibility?"Historical published checkpoints; each lane counts questionnaire records. Manual exclusions are shown separately and do not rewrite this history.":"Effective published checkpoints; each lane counts questionnaire records. Published matching is fixed.");
      if(result.flow.status!=="available")flow.append(text("p","Processing flow unavailable: persisted checkpoint evidence is missing or incompatible.","q-notice"));
      else{const lanes=text("div",undefined,"q-two");flow.append(lanes);for(const role of roles){const lane=text("section",undefined,"q-lane");lane.setAttribute("aria-label",roleName(role)+" processing lane");lane.append(text("h4",roleName(role)));lanes.append(lane);let i=0;for(const [key,title] of Object.entries(stages)){if(i++)lane.append(text("div","↓","q-arrow"));const x=result.flow.lanes[role][key],node=text("div",undefined,"q-node");node.append(text("h4",title));const dl=text("dl");for(const [label,value]of [["Entering",x.entering],[key==="selection"?"Selected":"Remaining",x.remaining]])dl.append(text("dt",label),text("dd",n(value)));node.append(dl);const d=detail(node,key==="selection"?"Retained but not selected · reasons":"Exits · mutually exclusive reasons");for(const [reason,count]of Object.entries(x.exits))note(d,`${reasons[reason]||reason}: ${n(count)} questionnaire records`);lane.append(node);}}}
      const outputs=panel(body,"Nine published samples");note(outputs,"Samples overlap. Do not add these counts. Every required published slot must satisfy the same scope; no replacements are selected.");const groups=text("div",undefined,"q-samples");outputs.append(groups);
      for(const [title,codes]of [["Students",["A","C","AC"]],["Parents",["B","D","BD"]],["Student-parent dyads",["E","F","EF"]]]){const g=text("section");g.append(text("h4",title));groups.append(g);for(const code of codes){const s=result.samples.find(x=>x.code===code),card=text("div",undefined,"q-sample");let label=names[code];if(code==="BD"&&s.status==="available"&&s.continuity_evidence==="formal_parent_longitudinal_artifact")label="Same adult across waves";card.append(text("span",`${label} (${code})`));const count=text("strong",s.status==="available"?n(s.count):"Unavailable");count.dataset.sample=code;card.append(count,text("small",units[s.unit]));if(eligibility){const e=eligibility.samples.find(r=>r.code===code),delta=e.excluded===null?"Unavailable":e.excluded?"-"+n(e.excluded):"0",audit=text("small",`Baseline ${n(e.baseline)} → active ${n(e.active)}; Δ ${delta}`);audit.dataset.sampleDelta=code;card.append(audit);}if(code==="BD")note(card,s.status==="available"?"Uses the formal parent longitudinal artifact; its follow-up can differ from D/F.":"Formal same-adult artifact or policy is unavailable; same-child membership does not establish the same adult.");g.append(card);}}
      const sources=panel(body,"Raw intake by source");table(sources,["Source","Student records","Parent records"],result.sources.map(s=>[s.label,n(s.student),n(s.parent)]));note(sources,"Raw questionnaire records within the current scope. Source rows are supplied by the same query result.");const original=detail(sources,"Original claimed-wave intake audit");table(original,["Role","T0","T1","Unknown"],roles.map(r=>[roleName(r),n(result.original_waves[r].T0),n(result.original_waves[r].T1),n(result.original_waves[r].unknown)]));
      renderSchool(panel(body,"School-review evidence"),result,school);
      note(body,"Identity-group counts are unavailable: represented-group signatures are not supplied. They are not part of the questionnaire funnel.");
    }
    function renderSchool(host,result,school){
      if(school.status!=="available"){host.append(text("p","Unavailable / not reconciled for this scope","q-notice"));note(host,school.reason);if(result.school.status==="available")table(host,["Record status","Students","Parents"],Object.entries(result.school.counts).map(([s,c])=>[stateNames[s]||s,n(c.student),n(c.parent)]));return;}
      const p=school.projection;host.append(text("p",p.reconciliation_status==="reconciled"?"Reconciled evidence; pending tasks can still remain.":"Not reconciled — do not treat zero pending as completed review.","q-notice"));
      if(p.availability!=="available"){note(host,"Compatible school evidence is unavailable. Counts have not been supplied.");return;}
      const wide=p.release_wide.labels;note(host,`Release-wide historical labels: ${n(wide.historical_queue)}. Accounted for: ${n(wide.historical_accounted)}; approved resolved: ${n(wide.historical_resolved)}. Accounting is not approval.`);
      table(host,["Release-wide label state","Distinct labels"],Object.entries(wide.states).map(([s,c])=>[stateNames[s],n(c)]));
      note(host,`Release-wide verified reviewed canonical names: ${n(p.release_wide.schools.verified_reviewed_canonical_schools)}. This is not a count of institutions or all study schools.`);
      const c=p.current_scope;table(host,["Current-scope questionnaire records","Students","Parents"],[["Raw records",c.raw],["Affected by queue labels",c.affected],["Persisted school exclusions",c.excluded_school],["Verified queue-attributed exclusions",c.verified_queue_attributed_exclusion],["Actionable pending",c.actionable_pending]].map(([label,x])=>[label,n(x.student),n(x.parent)]));
      const partition=detail(host,"Current-scope school record states · mutually exclusive display partition");table(partition,["Record status","Students","Parents"],Object.entries(c.status_partition).map(([s,x])=>[stateNames[s]||s,n(x.student),n(x.parent)]));note(partition,"Outside the review queue does not mean manually reviewed. This display partition does not change research status.");
      note(host,`Current-scope distinct labels: ${n(c.labels.affected)}; verified actionable pending: ${n(c.labels.actionable_pending)}; unreviewed: ${n(c.labels.unreviewed)}; not reconciled: ${n(c.labels.not_reconciled)}.`);note(host,"Labels, schools and questionnaire records are different units. Distinct school counts for this filtered scope are unavailable.");note(host,`R03 revision: ${p.revision}. Dictionary: ${p.evidence.dictionary_sha256}. Review state: ${p.evidence.review_state}. Decision revision: ${p.evidence.decision_revision||"No recorded decision"}. Criteria revision: ${p.evidence.criteria_revision||"Unavailable"}.`);
    }
    async function suppliedSchool(result,key){
      if(!options.schoolProjectionFor||!options.indexRevision)return {status:"unavailable",reason:"No validated R03 projection bound to this exact export and selection. Distinct-label browser filtering is not supplied."};
      try{const bound=await options.schoolProjectionFor({key,result:copy(result),indexRevision:options.indexRevision});const p=bound?.projection;
        if(!bound||bound.key!==key||bound.validatedBy!=="R03-r3"||!p||p.format!=="study2_school_status_v1"||p.release_id!==result.release_id||!["available","unavailable"].includes(p.availability)||!["reconciled","not_reconciled"].includes(p.reconciliation_status))throw Error();
        if(p.availability==="available"&&(!p.current_scope||!same(p.current_scope.raw,result.raw)))throw Error();
        return {status:"available",binding:key,validatedBy:bound.validatedBy,projection:copy(p)};
      }catch(e){return {status:"unavailable",reason:"Supplied school projection is absent, stale, unvalidated or incompatible with this scope."};}
    }
    async function request(){
      const ticket=++sequence;current=null;download.disabled=true;body.replaceChildren();summary.replaceChildren();root.dataset.state="loading";root.setAttribute("aria-busy","true");status.textContent="Updating all counts and the aggregate download…";
      let scoped;
      try{if(draftDates){selection=E.transitionSelection(index,selection,draftDates);draftDates=null;}scoped=E.normalizeSelection(index,selection);updateControls(null);const result=await (options.query||E.query)(index,copy(scoped));
        if(destroyed||ticket!==sequence)return;
        if(!result||result.format!=="study2_scope_result_v1"||result.schema!==index.meta.schema||result.date_policy?.timezone!=="Asia/Hong_Kong"||result.date_policy?.inclusive!==true||result.release_id!==index.meta.release_id||!same(result.scope,scoped))throw Error("result_scope_mismatch");
        const eligibility=options.eligibilityFor?eligibilityContext(await options.eligibilityFor({result:copy(result),scope:copy(scoped)}),result):null;
        if(destroyed||ticket!==sequence)return;
        const key=JSON.stringify([options.indexRevision||null,result.release_id,result.schema,result.scope,eligibility?.mode,eligibility?.revision]),school=await suppliedSchool(result,key);
        if(destroyed||ticket!==sequence)return;selection=scoped;updateControls(result);render(result,school,eligibility);
        current={format:"study2_quality_download_v1",index_revision:options.indexRevision||null,result:copy(result),school:copy(school),...(eligibility?{eligibility:copy(eligibility)}:{})};
        download.disabled=false;status.textContent="Current scope loaded. All figures and download use this result.";root.dataset.state="ready";root.setAttribute("aria-busy","false");
      }catch(error){if(destroyed||ticket!==sequence)return;clear(draftDates?"Invalid date interval: start must not be after end. Correct the date or reset. No previous counts are displayed.":"Counts unavailable. Check the inclusive dates and the compatible published scope export; no previous counts are displayed.");}
    }
    try{
      E.validate(index);selection=E.defaultSelection(index);const columns=text("div",undefined,"q-controls");controls.append(columns);
      for(const [facet,title]of [["sources","Sources"],["surveys","Questionnaire versions"]]){const field=text("fieldset");field.append(text("legend",title));const label=text("label","Search "+title.toLowerCase()),input=document.createElement("input");input.type="search";input.dataset.control="quality:search:"+facet;input.setAttribute("aria-label","Search "+title.toLowerCase());input.addEventListener("input",()=>{searches[facet]=input.value;updateControls(current?.result||null);});label.append(input);field.append(label);searchInputs[facet]=input;const actions=text("div",undefined,"q-actions");actions.append(button("Select all "+title.toLowerCase(),()=>{selection=E.normalizeSelection(index,{...selection,[facet]:E.defaultSelection(index)[facet]});request();}),button("Clear "+title.toLowerCase(),()=>{selection=E.normalizeSelection(index,{...selection,[facet]:[]});request();}));field.append(actions);note(field,"Availability uses all active filters except this facet's own selection. Search changes visibility only; select all includes hidden options.");lists[facet]=text("div",undefined,"q-list");field.append(lists[facet]);columns.append(field);}
      const dates=text("div",undefined,"q-dates");for(const [key,title]of [["start","Start date · Hong Kong"],["end","End date · Hong Kong"]]){const label=text("label",title),input=document.createElement("input");input.type="date";input.dataset.control="quality:date:"+key;input.setAttribute("aria-label",title);input.addEventListener("change",()=>{draftDates={...(draftDates||{start:selection.start,end:selection.end}),[key]:input.value||null};request();});label.append(input);dates.append(label);dateInputs[key]=input;}
      const toggle=text("label",undefined,"q-toggle");unknown=document.createElement("input");unknown.type="checkbox";unknown.dataset.control="quality:unknown";unknown.addEventListener("change",()=>{selection=E.transitionSelection(index,selection,{include_unknown:unknown.checked});request();});toggle.append(unknown,text("span","Include entries with unknown or unusable dates"));dates.append(toggle);controls.append(dates);
      function reset(){draftDates=null;selection=E.defaultSelection(index);searches={sources:"",surveys:""};for(const i of Object.values(searchInputs))i.value="";return request();}
      controls.append(button("Reset scope and search",reset));request();
    }catch(error){controls.replaceChildren();clear("Compatible scope export required. This snapshot cannot support exact first-tab filters; ask the coordinator for a validated scope export.");}
    return {getUIState:()=>({selection:selection?copy(selection):null,searches:copy(searches),draftDates:copy(draftDates),scroll:Object.fromEntries(Object.entries(lists).map(([k,v])=>[k,v.scrollTop]))}),
      setUIState:value=>{try{selection=E.normalizeSelection(index,value.selection);searches={sources:String(value.searches?.sources||""),surveys:String(value.searches?.surveys||"")};draftDates=value.draftDates?copy(value.draftDates):null;for(const facet of ["sources","surveys"])searchInputs[facet].value=searches[facet];updateControls(null);return request().then(()=>{for(const facet of ["sources","surveys"])lists[facet].scrollTop=value.scroll?.[facet]||0;});}catch{++sequence;clear("Invalid retained scope selection. Reset before continuing.");}},
      getSelection:()=>selection?copy(selection):null,getDownload:()=>current?copy(current):null,setSelection:value=>{try{draftDates=null;selection=E.normalizeSelection(index,value);return request();}catch(e){++sequence;clear("Invalid scope selection. Reset before continuing.");}},reset:()=>{draftDates=null;selection=E.defaultSelection(index);searches={sources:"",surveys:""};for(const i of Object.values(searchInputs))i.value="";return request();},destroy:()=>{destroyed=true;++sequence;root.replaceChildren();root.classList.remove("s2-quality");root.removeAttribute("aria-busy");}};
  }
  return Object.freeze({mount,text});
})();
if(typeof module!=="undefined")module.exports=Study2Quality;
'''
