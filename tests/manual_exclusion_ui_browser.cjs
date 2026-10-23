'use strict';
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const {chromium}=require('playwright');
const input=JSON.parse(fs.readFileSync(0,'utf8'));
const result={status:'running',stage:input.stage,downloads:[],checks:[],page_errors:[],requests:[],sidebars:[]};
let browser;
const click=(page,name)=>page.getByRole('button',{name,exact:true}).click();
const ready=page=>page.locator('.s2-quality[data-state=ready]').waitFor();
async function save(page,file,button,metadata={}){
 const wait=page.waitForEvent('download');await click(page,button);const d=await wait;await d.saveAs(path.join(input.output,file));
 result.downloads.push({file,suggested:d.suggestedFilename(),...metadata});return fs.readFileSync(path.join(input.output,file),'utf8');
}
async function toggle(page,on){await page.locator('#manual-exclusion-enabled').setChecked(on);await page.waitForFunction(on=>document.querySelector('.manual-eligibility')?.dataset.mode===(on?'on':'off'),on);}
async function source(page,codes){await click(page,'No sources');for(const code of codes)await page.locator(`[data-source="${code}"]`).check();}
async function app(page){
 await page.goto('https://manual-ui.test/');await page.locator('.manual-eligibility[data-state=ready]').waitFor();await ready(page);
 assert.equal(await page.locator('#manual-exclusion-enabled').isChecked(),false,'default OFF');
 const raw=()=>page.locator('[data-raw]').allTextContents();
 const originalRaw=await raw();assert.deepEqual(originalRaw,['22','23']);
 const off=await save(page,'off-quality.json','Download current aggregate JSON',{mode:'off',kind:'quality'});
 await save(page,'off-snapshot.json','Download aggregate snapshot',{mode:'off',kind:'snapshot'});
 await toggle(page,true);await ready(page);assert.deepEqual(await raw(),originalRaw,'raw history stays original');
 for(const code of ['A','B','C','D','AC','BD','E','F','EF']){
  const expected=['A','AC','E','EF'].includes(code)?10:11;
  assert.equal(await page.locator(`[data-sample="${code}"]`).textContent(),String(expected));
  const delta=await page.locator(`[data-sample-delta="${code}"]`).innerText();assert(delta.includes('Δ '+(expected===10?'-1':'0')),code+' visible delta');
 }
 assert((await page.locator('[data-eligibility-intake=student]').innerText()).includes('Actively excluded intake: 1'));
 await save(page,'on-quality.json','Download current aggregate JSON',{mode:'on',kind:'quality'});
 await save(page,'on-snapshot.json','Download aggregate snapshot',{mode:'on',kind:'snapshot'});
 await page.locator('.q-samples').locator('..').screenshot({path:path.join(input.output,'nine-sample-deltas.png')});
 fs.writeFileSync(path.join(input.output,'first-tab-on.html'),await page.locator('#content').innerHTML());
 await toggle(page,false);await ready(page);
 const restored=await save(page,'off-quality-restored.json','Download current aggregate JSON',{mode:'off',kind:'quality'});assert.equal(restored,off,'exact OFF/ON/OFF quality download restoration');
 result.checks.push('OFF/ON/OFF, unchanged raw/stage history, each nine-sample delta and JSON provenance');
 // First-tab source, questionnaire version, HK date and search state survive.
 const legacy=input.scope.index.sources.find(s=>s.label==='legacy_online').key;
 const version=input.scope.index.surveys.find(s=>s.source_key===legacy&&s.role==='student').key;
 await click(page,'Clear sources');await page.locator(`[data-facet=sources][data-key="${legacy}"]`).check();
 await click(page,'Clear questionnaire versions');await page.locator(`[data-facet=surveys][data-key="${version}"]`).check();
 await page.getByLabel('Search sources',{exact:true}).fill('legacy');
 await page.getByLabel('Start date · Hong Kong',{exact:true}).fill('2025-01-02');
 await page.getByLabel('End date · Hong Kong',{exact:true}).fill('2025-05-02');await ready(page);
 const scopeState=()=>page.evaluate(()=>({sources:[...document.querySelectorAll('[data-facet=sources]:checked')].map(x=>x.dataset.key),surveys:[...document.querySelectorAll('[data-facet=surveys]:checked')].map(x=>x.dataset.key),dates:[...document.querySelectorAll('input[type=date]')].map(x=>x.value),search:document.querySelector('[aria-label="Search sources"]').value}));
 const before=await scopeState();await toggle(page,true);await ready(page);assert.deepEqual(await scopeState(),before);
 assert.equal(await page.locator('[data-sample=AC]').textContent(),'1','same profile excludes only one native case');
 await save(page,'on-scoped-quality.json','Download current aggregate JSON',{mode:'on',kind:'quality',scoped:true});
 await toggle(page,false);await ready(page);assert.deepEqual(await scopeState(),before);assert.equal(await page.locator('[data-sample=AC]').textContent(),'2');
 result.checks.push('source/version/HK dates/search preserved; flagged and unflagged same-profile records remain distinct');
 await toggle(page,true);await ready(page);await click(page,'Descriptive statistics');await page.locator('.sample-sidebar').waitFor();
 await save(page,'on-overview.csv','Download current category (CSV)',{mode:'on',kind:'statistics',sample:'abcd',sources:['all'],grades:'all'});
 await page.getByLabel('Analysis sample',{exact:true}).selectOption('acbd');await click(page,'Longitudinal comparison');
 await save(page,'on-paired.csv','Download all paired changes (CSV)',{mode:'on',kind:'paired_changes',sample:'acbd',sources:['all'],grades:'all'});
 const headers=await page.locator('.family-block').first().locator('th').allTextContents();assert.deepEqual(headers,['Metric','Valid in both waves, N','T0 Mean (SD)','T1 Mean (SD)','p-value',"Cohen's d"]);
 await source(page,['legacy_online','qualtrics']);await click(page,'No grades');for(const code of ['P3','P4'])await page.locator(`[data-grade="${code}"]`).check();
 await save(page,'on-custom-paired.csv','Download all paired changes (CSV)',{mode:'on',kind:'paired_changes',sample:'acbd',sources:['legacy_online','qualtrics'],grades:['P3','P4']});
 for(const row of await page.locator('.family-block tbody tr').all()){const cells=await row.locator('td').allTextContents();assert.deepEqual(cells.slice(4),['Unavailable','Unavailable']);}
 const selected=()=>page.evaluate(()=>({sample:document.querySelector('[aria-label="Analysis sample"]').value,sources:[...document.querySelectorAll('[data-source]:checked')].map(x=>x.dataset.source),grades:[...document.querySelectorAll('[data-grade]:checked')].map(x=>x.dataset.grade)}));
 const filters=await selected();await toggle(page,false);assert.deepEqual(await selected(),filters);
 await save(page,'off-custom-paired.csv','Download all paired changes (CSV)',{mode:'off',kind:'paired_changes',sample:'acbd',sources:['legacy_online','qualtrics'],grades:['P3','P4']});
 await click(page,'Clear filters');assert.equal(await page.locator('#manual-exclusion-enabled').isChecked(),false);
 await click(page,'No sources');await toggle(page,true);assert.equal(await page.locator('.analysis-body table,.analysis-body .chart').count(),0);assert.equal(await page.getByRole('button',{name:'Download all paired changes (CSV)',exact:true}).count(),0,'empty selection has no stale download');
 await click(page,'All sources');await click(page,'Clear filters');
 result.checks.push('atomic descriptive/paired bundle, full precision CSV mode/revision, custom source/grade inference unavailable, empty selections');
 await click(page,'Independent parent analysis');assert.equal(await page.locator('[data-source=qualtrics]').isChecked(),true,'independent filters remain separate');
 await click(page,'Longitudinal comparison');
 await save(page,'on-independent-child.csv','Download all paired changes (CSV)',{mode:'on',kind:'paired_changes',sample:'independent_child',adult_phq_blocked:true});
 await page.getByLabel('Analysis sample',{exact:true}).selectOption('independent_adult');
 const independentOn=await save(page,'on-independent-adult.csv','Download all paired changes (CSV)',{mode:'on',kind:'paired_changes',sample:'independent_adult'});
 await toggle(page,false);await save(page,'off-independent-adult.csv','Download all paired changes (CSV)',{mode:'off',kind:'paired_changes',sample:'independent_adult'});
 result.checks.push('independent branch distinction and adult PHQ restriction; student flag does not remove unrelated parent');
 await click(page,'Descriptive statistics');
 for(const size of [{width:1440,height:900},{width:1024,height:600},{width:390,height:844}]){
  await page.setViewportSize(size);const sidebar=page.locator('.sample-sidebar');const last=page.locator('[data-grade=Unknown]');await last.scrollIntoViewIfNeeded();await last.focus();
  const before=await sidebar.evaluate(s=>({top:s.scrollTop,scrollHeight:s.scrollHeight,clientHeight:s.clientHeight,scrollWidth:s.scrollWidth,clientWidth:s.clientWidth}));
  const old=await page.locator('#manual-exclusion-enabled').isChecked();await page.evaluate(()=>document.querySelector('#manual-exclusion-enabled').click());
  assert.equal(await page.locator('#manual-exclusion-enabled').isChecked(),!old);assert.equal(await page.evaluate(()=>document.activeElement?.dataset.control),'grade:Unknown');
  const after=await sidebar.evaluate(s=>s.scrollTop);assert(Math.abs(before.top-after)<=2,'sidebar scroll survives bundle switch');assert(before.scrollWidth<=before.clientWidth);
  result.sidebars.push({...size,...before,after,focus_retained:true});
 }
 await page.setViewportSize({width:1440,height:1000});await click(page,'Data quality & progress');await ready(page);
 await page.getByLabel('Start date · Hong Kong',{exact:true}).fill('2025-08-01');await page.locator('.s2-quality[data-state=unavailable]').waitFor();
 await page.evaluate(()=>document.querySelector('#manual-exclusion-enabled').click());await page.locator('.s2-quality[data-state=unavailable]').waitFor();
 assert.equal(await page.locator('[data-sample]').count(),0,'invalid date cannot revive stale results after mode change');
 assert.equal(await page.getByLabel('Start date · Hong Kong',{exact:true}).inputValue(),'2025-08-01');
 assert.equal(await page.evaluate(()=>document.activeElement?.dataset.control),'quality:date:start','invalid date focus retained');
 result.checks.push('three viewport focus/scroll and invalid-date state survive bundle changes');
}
async function coreGenerated(page){
 await page.goto('https://manual-ui.test/');
 await page.waitForFunction(()=>document.querySelector('.manual-eligibility')?.dataset.state!=='loading');
 assert.equal(await page.locator('.manual-eligibility').getAttribute('data-state'),'ready',await page.locator('.manual-eligibility [role=status]').innerText());await ready(page);
 const originalRaw=await page.locator('[data-raw]').allTextContents();
 const original=await save(page,'core-off-quality.json','Download current aggregate JSON',{mode:'off',kind:'quality'});
 await toggle(page,true);await ready(page);assert.deepEqual(await page.locator('[data-raw]').allTextContents(),originalRaw);
 for(const row of input.wrapper.impact.samples){assert.equal(await page.locator(`[data-sample="${row.code}"]`).textContent(),row.active===null?'Unavailable':String(row.active));assert((await page.locator(`[data-sample-delta="${row.code}"]`).innerText()).includes(row.excluded===null?'Unavailable':`Δ ${row.excluded?'-'+row.excluded:'0'}`));}
 await save(page,'core-on-quality.json','Download current aggregate JSON',{mode:'on',kind:'quality'});
 await save(page,'core-on-snapshot.json','Download aggregate snapshot',{mode:'on',kind:'snapshot'});
 await page.locator('.q-samples').locator('..').screenshot({path:path.join(input.output,'core-nine-sample-deltas.png')});
 fs.writeFileSync(path.join(input.output,'core-first-tab-on.html'),await page.locator('#content').innerHTML());
 await click(page,'Descriptive statistics');
 assert.equal(input.snapshot.samples.length,10);assert.equal(input.wrapper.impact.samples.length,9);
 assert.equal(await page.locator('[data-source=unknown]').count(),1,'zero unknown-source option remains in ON');
 assert.equal(await page.locator('[data-source=unknown]').isDisabled(),false);
 await save(page,'core-on-overview.csv','Download current category (CSV)',{mode:'on',kind:'statistics',sample:'abcd',role:'student'});
 await page.getByLabel('Analysis sample',{exact:true}).selectOption('acbd');await click(page,'Longitudinal comparison');
 await save(page,'core-on-ac.csv','Download all paired changes (CSV)',{mode:'on',kind:'paired_changes',sample:'acbd',role:'student'});
 assert.deepEqual(await page.locator('.family-block').first().locator('th').allTextContents(),['Metric','Valid in both waves, N','T0 Mean (SD)','T1 Mean (SD)','p-value',"Cohen's d"]);
 await page.getByLabel('Respondent',{exact:true}).selectOption('parent');
 await save(page,'core-on-bd.csv','Download all paired changes (CSV)',{mode:'on',kind:'paired_changes',sample:'acbd',role:'parent'});
 await click(page,'Independent parent analysis');await page.getByLabel('Analysis sample',{exact:true}).selectOption('independent_adult');await click(page,'Longitudinal comparison');
 await save(page,'core-on-independent-adult.csv','Download all paired changes (CSV)',{mode:'on',kind:'paired_changes',sample:'independent_adult',role:'parent'});
 await page.getByLabel('Analysis sample',{exact:true}).selectOption('independent_child');
 assert(!(await page.locator('.family-block h3').allTextContents()).includes('PHQ'),'child-report PHQ remains gated');
 await click(page,'Descriptive statistics');await page.getByLabel('Respondent',{exact:true}).selectOption('student');
 await source(page,['qualtrics','paperform']);await click(page,'No grades');await page.locator('[data-grade=P4]').check();
 for(const row of await page.locator('.family-block tbody tr').all())assert.deepEqual((await row.locator('td').allTextContents()).slice(4),['Unavailable','Unavailable']);
 if(await page.getByRole('button',{name:'Download all paired changes (CSV)',exact:true}).count())await save(page,'core-on-custom.csv','Download all paired changes (CSV)',{mode:'on',kind:'paired_changes',sample:'acbd',role:'student',custom:true});
 const before=await page.evaluate(()=>({mode:document.querySelector('[aria-label="Analysis sample"]').value,grades:[...document.querySelectorAll('[data-grade]:checked')].map(x=>x.dataset.grade),sources:[...document.querySelectorAll('[data-source]:checked')].map(x=>x.dataset.source)}));
 await toggle(page,false);assert.deepEqual(await page.evaluate(()=>({mode:document.querySelector('[aria-label="Analysis sample"]').value,grades:[...document.querySelectorAll('[data-grade]:checked')].map(x=>x.dataset.grade),sources:[...document.querySelectorAll('[data-source]:checked')].map(x=>x.dataset.source)})),before);
 await click(page,'Data quality & progress');await ready(page);
 const restored=await save(page,'core-off-restored-quality.json','Download current aggregate JSON',{mode:'off',kind:'quality'});assert.equal(restored,original);
 const hashes=await page.evaluate(async rows=>{for(const row of rows)if(await Study2EligibilityHash.digest(row.value)!==row.digest)throw Error('actual core Python/browser typed hash mismatch');return rows.length;},input.hash_cases);result.hash_cases=hashes;
 result.checks.push('actual frozen core bundle and scope engine: nine exact deltas, original history, OFF restoration, AC/BD/independent CSVs and hashes, retained source/grade controls');
}

async function invalidAndHash(page){
 await page.goto('https://manual-ui.test/');await page.locator('.manual-eligibility[data-state=ready]').waitFor();
 const checked=await page.evaluate(async cases=>{
  const out=[];for(const row of cases){const got=await Study2EligibilityHash.digest(row.value);if(got!==row.digest)throw Error('cross-language typed hash mismatch');out.push(got);}return out;
 },input.hash_cases);result.hash_cases=checked.length;
 result.invalid=await page.evaluate(async()=>{
  const off=window.STUDY2_SNAPSHOT,scope=window.STUDY2_SCOPE_EXPORT,original=window.STUDY2_MANUAL_EXCLUSION,results=[];
  const cases=[['missing',null],['unknown_keys',{...original,private_record_ids:[]}],['wrong_release',{...original,release_id:'other'}],['stale_off_hash',{...original,off:{...original.off,snapshot_revision:'0'.repeat(64)}}],['stale_on_hash',{...original,on_revision:'0'.repeat(64)}]];
  for(const name of ['wrong_revision','bad_impact','suppression_changed','partial_views','negative_count','unknown_count_key','independent_count_mismatch','view_private','table_private','metric_label']){
   const w=structuredClone(original);
   if(name==='wrong_revision')w.on.scope_export.index.eligibility.revision='c'.repeat(64);
   if(name==='bad_impact')w.impact.samples[0].active+=1;
   if(name==='suppression_changed')w.on.snapshot.minimum_cell_n=1;
   if(name==='partial_views')w.on.snapshot.views.pop();
   if(name==='negative_count')w.on.snapshot.views[0].counts.all.T0=-1;
   if(name==='unknown_count_key')w.on.snapshot.counts.extra=1;
   if(name==='independent_count_mismatch')w.on.snapshot.independent_counts.same_adult_pairs=10;
   if(name==='view_private')w.on.snapshot.views[0].private_response_ids=['synthetic-private-id'];
   if(name==='table_private'){const t=w.on.snapshot.views[0].statistics;t.columns.push('private_response_ids');for(const row of t.rows)row.push('synthetic-private-id');}
   if(name==='metric_label'){const t=w.on.snapshot.views[0].statistics;t.rows[0][t.columns.indexOf('variable')]='synthetic-private-id';}
   w.on_revision=await Study2EligibilityHash.digest(w.on);cases.push([name,w]);
  }
  for(const [name,w] of cases){
   const ui=await Study2ManualEligibility.create(off,scope,w,Study2Scope);if(ui.available)throw Error(name+' must disable ON');
   let rejected=false;try{ui.select('on');}catch{rejected=true;}if(!rejected||ui.bundle!==null||ui.mode!=='on')throw Error(name+' silently fell back');
   if(ui.select('off').snapshot!==off)throw Error(name+' lost canonical OFF');results.push({name,reason:ui.reason,off_preserved:true});
  }
  return results;
 });
 const prefix=input.assets['/manual-exclusion.js'].split('\nwindow.STUDY2_MANUAL_EXCLUSION=')[0];
 const bad={...input.wrapper,on_revision:'0'.repeat(64)};
 input.assets['/manual-exclusion.js']=prefix+'\nwindow.STUDY2_MANUAL_EXCLUSION='+JSON.stringify(bad)+';';
 await page.goto('https://manual-ui.test/');await page.locator('.manual-eligibility[data-state=unavailable]').waitFor();await ready(page);
 assert.equal(await page.locator('#manual-exclusion-enabled').isDisabled(),true);assert.equal(await page.locator('[data-sample=A]').textContent(),'11');
 await page.evaluate(()=>{const x=document.querySelector('#manual-exclusion-enabled');x.disabled=false;x.click();});
 assert((await page.locator('#content').innerText()).includes('Requested manual exclusion is unavailable'));
 assert.equal(await page.locator('[data-sample]').count(),0);assert.equal(await page.locator('#download-snapshot').isDisabled(),true);
 await toggle(page,false);await ready(page);assert.equal(await page.locator('[data-sample=A]').textContent(),'11');result.invalid_app_state=true;
 result.checks.push('Python/browser f64/UTF16 hashes; malformed/stale bundles fail closed while OFF remains canonical; requested invalid ON clears app/downloads');
}
(async()=>{
 try{
  browser=await chromium.launch({headless:true});const context=await browser.newContext({acceptDownloads:true,viewport:{width:1440,height:1000}});
  await context.route('**/*',route=>{const url=new URL(route.request().url());result.requests.push(url.pathname);if(url.origin!=='https://manual-ui.test')return route.abort();const body=input.assets[url.pathname];return route.fulfill({status:body===undefined?404:200,contentType:url.pathname==='/'?'text/html':url.pathname.endsWith('.css')?'text/css':'text/javascript',body:body===undefined?'':body});});
  const page=await context.newPage();page.on('pageerror',e=>result.page_errors.push(e.message));
  if(input.check==='integration')await app(page);else if(input.check==='core_generated')await coreGenerated(page);else await invalidAndHash(page);
  assert.deepEqual(result.page_errors,[]);result.status='passed';await context.close();
 }catch(error){result.status='failed';result.error={message:error.message,stack:error.stack};process.exitCode=1;}
 finally{if(browser)await browser.close();fs.writeFileSync(path.join(input.output,'RESULTS.json'),JSON.stringify(result,null,2));console.log(JSON.stringify({status:result.status,checks:result.checks.length,downloads:result.downloads.length}));}
})();
