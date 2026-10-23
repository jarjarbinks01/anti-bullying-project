'use strict';
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const {chromium}=require('playwright'),input=JSON.parse(fs.readFileSync(0,'utf8'));
const result={status:'running',checks:[],viewports:[],page_errors:[],failed_requests:[]};
let browser;
async function login(context,size){
 const page=await context.newPage();await page.setViewportSize(size);
 page.on('pageerror',error=>result.page_errors.push(error.message));
 page.on('requestfailed',request=>result.failed_requests.push(request.url()));
 await page.goto(input.base+'/login.html');await page.locator('#password').fill(input.password);
 await page.locator('#submit').click();await page.waitForURL(input.base+'/');
 if(input.kind==='integration')result.first_tab_baseline=await page.locator('#content').innerText();
 await page.getByRole('button',{name:'Descriptive statistics',exact:true}).click();
 await page.locator('.sample-sidebar').waitFor();return page;
}
async function sidebarCase(page,size){
 const sidebar=page.locator('.sample-sidebar');await sidebar.scrollIntoViewIfNeeded();
 const initial=await sidebar.evaluate(s=>({scrollHeight:s.scrollHeight,clientHeight:s.clientHeight,scrollWidth:s.scrollWidth,clientWidth:s.clientWidth}));
 assert(initial.scrollHeight>initial.clientHeight,'long sidebar must scroll vertically');assert(initial.scrollWidth<=initial.clientWidth,'sidebar controls must fit horizontally');
 await page.getByRole('button',{name:'Clear filters',exact:true}).focus();
 const visited=[];let last=false;
 for(let i=0;i<75;i++){
  await page.keyboard.press('Tab');const key=await page.evaluate(()=>document.activeElement?.dataset.control);
  visited.push(key||null);if(key==='grade:Unknown'){last=true;break;}
 }
 assert(last,'last grade control must be reachable by actual Tab navigation');
 const visible=await page.locator('[data-grade="Unknown"]').evaluate(e=>{const a=e.getBoundingClientRect(),b=e.closest('.sample-sidebar').getBoundingClientRect();return a.top>=b.top&&a.bottom<=b.bottom;});assert(visible,'last control is inside scroll viewport');
 const before=await sidebar.evaluate(s=>s.scrollTop);
 await page.keyboard.press('Space');
 const active=await page.evaluate(()=>document.activeElement?.dataset.control);
 assert.equal(active,'grade:Unknown','render must retain checkbox keyboard focus');
 const after=await sidebar.evaluate(s=>s.scrollTop);assert(Math.abs(before-after)<=2,'render must retain inner scroll position');
 await page.screenshot({path:path.join(input.output,`${size.width}x${size.height}-last-control.png`)});
 fs.writeFileSync(path.join(input.output,`${size.width}x${size.height}-sidebar.html`),await sidebar.evaluate(s=>s.outerHTML));
 result.viewports.push({...size,...initial,last_reachable_by_tab:last,visited_controls:visited,focus_retained_after_change:active==='grade:Unknown',scroll_before_change:before,scroll_after_change:after});
 result.checks.push(`${size.width}x${size.height}: scroll, keyboard reach, focus/scroll preservation`);
}

const grades=['P1','P2','P3','P4','P5','P6','S1','S2','S3','S4','S5','S6','Unknown'];
async function click(page,name){await page.getByRole('button',{name,exact:true}).click();}
async function sources(page,codes){await click(page,'No sources');for(const code of codes)await page.locator(`[data-source="${code}"]`).check();}
async function saved(page,name,button,meta){
 const wait=page.waitForEvent('download');await click(page,button);const item=await wait,file=name+'.csv';await item.saveAs(path.join(input.output,file));
 result.downloads.push({file,...meta});return fs.readFileSync(path.join(input.output,file),'utf8');
}
async function integration(page){
 result.downloads=[];const summary=()=>page.locator('.sample-summary .summary-n strong').allTextContents();
 const common={mode:'abcd',grades,sources:['all'],source_anchor:'wave_response',grade_anchor:'student_wave',kind:'statistics'};
 const initial=await summary();assert.deepEqual(initial,['11','11']);
 const unrestricted=await saved(page,'all-original','Download current category (CSV)',common);
 assert.equal(await page.locator('[data-source="unknown"]').count(),1,'residual option visible only with metadata');
 await click(page,'No sources');assert.deepEqual(await summary(),['0','0']);assert.equal(await page.locator('.analysis-body table,.analysis-body .chart').count(),0);
 assert.equal(await page.locator('.analysis-body button').filter({hasText:/CSV/}).count(),0);result.empty_has_no_stale_outputs=true;
 await sources(page,['qualtrics','legacy_online']);
 assert((await page.locator('.sample-summary').innerText()).includes('Legacy online'));
 assert((await page.locator('.sample-summary').innerText()).includes('Qualtrics'));
 await saved(page,'union-wave','Download current category (CSV)',{...common,sources:['legacy_online','qualtrics']});
 await page.getByLabel('School scope',{exact:true}).selectOption('true');
 await saved(page,'union-mainstream','Download current category (CSV)',{...common,sources:['legacy_online','qualtrics'],mainstream:true});
 await page.getByLabel('School scope',{exact:true}).selectOption('false');
 await click(page,'No grades');await page.locator('[data-grade="P3"]').check();
 await saved(page,'union-grade-p3','Download current category (CSV)',{...common,sources:['legacy_online','qualtrics'],grades:['P3']});
 await click(page,'Clear filters');assert.deepEqual(await summary(),initial);
 const restored=await saved(page,'all-reset','Download current category (CSV)',common);assert.equal(restored,unrestricted,'clear filters must reproduce exact unrestricted CSV');result.reset_restores_unrestricted=true;
 await sources(page,['legacy_online','paperform','qualtrics','school_batch','socialworkdream']);assert.deepEqual(await summary(),['10','11']);
 await click(page,'All sources');assert.deepEqual(await summary(),initial);result.all_retains_residual=true;
 // Render real All-source chart, then change selection while it is on screen.
 await click(page,'Score distribution');assert(await page.locator('.analysis-body .chart').count()>0);
 await sources(page,['legacy_online','qualtrics']);assert.equal(await page.locator('.analysis-body .chart').count(),0);assert.equal(await page.getByRole('button',{name:'Download histogram bins (CSV)',exact:true}).count(),0);
 await click(page,'Period trends');assert.equal(await page.locator('.analysis-body .chart,.analysis-body table').count(),0);assert.equal(await page.locator('.analysis-body button').filter({hasText:/CSV/}).count(),0);result.unsupported_has_no_stale_outputs=true;
 await click(page,'All sources');assert(await page.locator('.analysis-body .chart').count()>0,'All sources restores supported trend');
 await click(page,'Research overview');await click(page,'Results table');await click(page,'Clear filters');
 await page.getByLabel('Analysis sample',{exact:true}).selectOption('acbd');await sources(page,['qualtrics','legacy_online']);await click(page,'Longitudinal comparison');
 const formal={kind:'paired_changes',mode:'acbd',sources:['legacy_online','qualtrics'],grades,source_anchor:'student_T0',grade_anchor:'student_T0'};
 await saved(page,'formal-student-union','Download all paired changes (CSV)',formal);
 await click(page,'No grades');await page.locator('[data-grade="P3"]').check();await page.locator('[data-grade="P4"]').check();
 await saved(page,'formal-student-source-grade','Download all paired changes (CSV)',{...formal,grades:['P3','P4']});
 await click(page,'Research overview');
 await saved(page,'formal-overview-source-grade','Download current category (CSV)',{...formal,kind:'statistics',grades:['P3','P4']});
 await click(page,'Longitudinal comparison');
 await click(page,'Clear filters');await saved(page,'formal-all-inference','Download all paired changes (CSV)',{...formal,sources:['all']});
 await page.getByLabel('Respondent',{exact:true}).selectOption('parent');await sources(page,['legacy_online','qualtrics']);
 await saved(page,'formal-bd-parent-union','Download all paired changes (CSV)',{...formal,source_anchor:'BD_parent_T0'});
 await page.getByLabel('Analysis sample',{exact:true}).selectOption('efmatched');
 await saved(page,'formal-ef-parent-phq-blocked','Download all paired changes (CSV)',{...formal,mode:'efmatched',adult_phq_blocked:true});
 await click(page,'Independent parent analysis');assert.equal(await page.getByRole('button',{name:'All sources',exact:true}).getAttribute('aria-pressed'),'true','independent state must not inherit descriptive filters');
 await sources(page,['qualtrics','legacy_online']);await click(page,'Longitudinal comparison');
 const independent={...formal,mode:'independent_child',source_anchor:'independent_parent_T0',grade_anchor:'parent_report_T0'};
 await saved(page,'independent-child-phq-blocked','Download all paired changes (CSV)',{...independent,adult_phq_blocked:true});
 await page.getByLabel('Analysis sample',{exact:true}).selectOption('independent_adult');
 await saved(page,'independent-adult-union','Download all paired changes (CSV)',{...independent,mode:'independent_adult'});
 await click(page,'No grades');await page.locator('[data-grade="P3"]').check();await page.locator('[data-grade="P4"]').check();
 await saved(page,'independent-adult-source-grade','Download all paired changes (CSV)',{...independent,mode:'independent_adult',grades:['P3','P4']});
 await click(page,'Research overview');
 await saved(page,'independent-overview-source-grade','Download current category (CSV)',{...independent,mode:'independent_adult',kind:'statistics',grades:['P3','P4']});
 await page.screenshot({path:path.join(input.output,'source-union-independent.png'),fullPage:true});
 await click(page,'Data quality & progress');assert.equal(await page.locator('#content').innerText(),result.first_tab_baseline);result.first_tab_not_affected=true;await click(page,'Independent parent analysis');
 // Explicit older-format compatibility. New arrays still select old All/single
 // views, and a union cannot silently substitute the unfiltered result.
 const legacy=await page.evaluate(()=>{const s=JSON.parse(JSON.stringify(window.STUDY2_SNAPSHOT));delete s.source_selection;for(const v of s.views)delete v.source_pairs;return s;});
 await page.route('**/snapshot.js',route=>route.fulfill({status:200,contentType:'text/javascript',body:'window.STUDY2_SNAPSHOT='+JSON.stringify(legacy)+';'}));
 await page.reload();assert(await page.locator('.analysis-body table').count()>0);assert.equal(await page.locator('[data-source="unknown"]').count(),0);
 await sources(page,['paperform']);assert(await page.locator('.analysis-body table').count()>0);result.legacy_all_and_single_work=true;
 await page.locator('[data-source="qualtrics"]').check();assert.equal(await page.locator('.analysis-body table,.analysis-body .chart').count(),0);result.legacy_union_unavailable=true;
 await click(page,'All sources');assert(await page.locator('.analysis-body table').count()>0);
 await page.unroute('**/snapshot.js');const noResidual=JSON.parse(fs.readFileSync(input.no_residual,'utf8'));
 await page.route('**/snapshot.js',route=>route.fulfill({status:200,contentType:'text/javascript',body:'window.STUDY2_SNAPSHOT='+JSON.stringify(noResidual)+';'}));
 await page.reload();await click(page,'Descriptive statistics');assert.equal(await page.locator('[data-source="unknown"]').count(),0);
 await sources(page,['legacy_online','paperform','qualtrics','school_batch','socialworkdream']);assert.deepEqual(await summary(),['10','10']);
 await click(page,'Score distribution');assert(await page.locator('.analysis-body .chart').count()>0,'five named sources cover exact All when no residual exists');
 await click(page,'Period trends');assert(await page.locator('.analysis-body .chart').count()>0,'full named partition preserves supported trends');
 result.no_residual_complete_partition_is_all=true;
 result.checks.push('source combinations, empty, residual, source-grade, school scope, reset, actual CSV, formal/independent anchors, adult PHQ, unsupported output and legacy compatibility');
}

async function legacySummary(page){
 const expected=JSON.parse(fs.readFileSync(input.legacy_expected,'utf8'));result.downloads=[];result.legacy_cases=[];
 await page.getByLabel('Analysis sample',{exact:true}).selectOption('acbd');
 for(const role of ['student','parent'])for(const source of ['all','qualtrics']){
  await page.getByLabel('Respondent',{exact:true}).selectOption(role);
  if(source==='all')await click(page,'All sources');else await sources(page,['qualtrics']);
  const metric=role==='student'?'PHQ_total':'SEC_total',want=expected[role][source][metric];
  const original=await page.evaluate(({role,source,metric})=>{
   const v=window.STUDY2_SNAPSHOT.views.find(x=>x.mode==='acbd'&&x.role===role&&x.source===source&&!x.mainstream);
   const rows=Array.isArray(v.changes)?v.changes:v.changes.rows.map(r=>Object.fromEntries(v.changes.columns.map((k,i)=>[k,r[i]])));
   const row=rows.find(r=>r.variable_id===metric);
   const detail=['pair_detail_status','only_t0_valid_n','only_t1_valid_n','both_missing_n','t0_mean','t1_mean'];
   return {finite:row?.paired_valid_n>1&&['mean_change','sd_change','p_value','cohen_dz'].every(k=>Number.isFinite(row[k])),absent:detail.every(k=>!Object.hasOwn(row,k)),parent_phq_absent:role!=='parent'||!rows.some(r=>r.variable_id.startsWith('PHQ_'))};
  },{role,source,metric});assert(original.finite,'Fixture must retain finite original stored summary/inference');assert(original.absent,'Fixture must preserve absent newer details');assert(original.parent_phq_absent,'Adult negative fixture must not offer PHQ changes');
  await click(page,'Research overview');
  const overview=await page.getByRole('columnheader',{name:'p-value',exact:true}).count()>0;
  await saved(page,`legacy-${role}-${source}-overview`,'Download current category (CSV)',{role,source,kind:'statistics'});
  await click(page,'Longitudinal comparison');
  const available=await page.getByRole('button',{name:'Download all paired changes (CSV)',exact:true}).count()>0;
  let summary=false,detail=original.absent,parentAbsent=true;
  if(available){
   const row=page.locator('.family-block tbody tr').filter({has:page.getByText(metric,{exact:true})});assert.equal(await row.count(),1);
   const cells=await row.locator('td').allTextContents();summary=cells.length===6&&Number(cells[1])===want.paired_valid_n&&cells[5]===want.cohen_dz.toFixed(2)&&await page.getByRole('columnheader',{name:'p-value',exact:true}).count()>0;
   detail=detail&&cells[2]==='Unavailable'&&cells[3]==='Unavailable';
   if(role==='parent')parentAbsent=await page.locator('.family-block').getByText('PHQ_total',{exact:true}).count()===0;
   await saved(page,`legacy-${role}-${source}-paired`,'Download all paired changes (CSV)',{role,source,kind:'paired_changes'});
  }
  result.legacy_cases.push({role,source,stored_summary_finite:original.finite,overview_paired_headers_visible:overview,paired_download_available:available,paired_summary_visible:summary,new_detail_not_fabricated:detail,adult_phq_not_resurrected:parentAbsent});
  await page.screenshot({path:path.join(input.output,`legacy-${role}-${source}.png`),fullPage:true});
  fs.writeFileSync(path.join(input.output,`legacy-${role}-${source}.html`),await page.locator('.analysis-body').evaluate(e=>e.outerHTML));
 }
 await page.locator('[data-source="legacy_online"]').check();
 result.unsupported_legacy_union_unavailable=await page.locator('.analysis-body table,.analysis-body .chart').count()===0&&await page.locator('.analysis-body button').filter({hasText:/CSV/}).count()===0&&(await page.locator('.analysis-body').innerText()).toLowerCase().includes('unavailable');
 result.adult_negative_gate_preserved=result.legacy_cases.filter(c=>c.role==='parent').every(c=>c.adult_phq_not_resurrected);
 assert(result.unsupported_legacy_union_unavailable,'Missing legacy source capability must not enable unions');assert(result.adult_negative_gate_preserved,'Summary compatibility must not infer adult continuity');
 assert(result.legacy_cases.every(c=>c.overview_paired_headers_visible&&c.paired_download_available&&c.paired_summary_visible),'P2_LEGACY_SUMMARY_HIDDEN: valid stored All/single summaries and inference must remain visible and downloadable');
 assert(result.legacy_cases.every(c=>c.new_detail_not_fabricated),'Absent new detail is unavailable, never zero');
 result.checks.push('pre-detail legacy All/Qualtrics overview and paired CSV preserve original summary/inference; no fabricated detail, union or adult PHQ');
}
(async()=>{
 try{
  browser=await chromium.launch({headless:true});result.browser_version=browser.version();
  if(input.kind==='sidebar'){
   for(const size of [{width:1440,height:900},{width:1024,height:600},{width:390,height:844}]){
    const context=await browser.newContext({acceptDownloads:true});await context.route('**/*',route=>new URL(route.request().url()).hostname==='127.0.0.1'?route.continue():route.abort());
    const page=await login(context,size);await sidebarCase(page,size);await context.close();
   }
  }else if(input.kind==='integration'){const context=await browser.newContext({acceptDownloads:true});await context.route('**/*',route=>new URL(route.request().url()).hostname==='127.0.0.1'?route.continue():route.abort());const page=await login(context,{width:1440,height:900});await integration(page);await context.close();}else if(input.kind==='legacy_summary'){const context=await browser.newContext({acceptDownloads:true});await context.route('**/*',route=>new URL(route.request().url()).hostname==='127.0.0.1'?route.continue():route.abort());const page=await login(context,{width:1440,height:900});await legacySummary(page);await context.close();}else throw Error('Unknown browser case');
  assert.deepEqual(result.page_errors,[]);assert.deepEqual(result.failed_requests,[]);result.status='passed';
 }catch(error){result.status='failed';result.error={message:error.message,stack:error.stack};process.exitCode=1;
  if(browser){for(const c of browser.contexts())for(const p of c.pages())try{await p.screenshot({path:path.join(input.output,'failure.png'),fullPage:true});}catch{}}
 }finally{if(browser)await browser.close();fs.writeFileSync(path.join(input.output,'RESULTS.json'),JSON.stringify(result,null,2));console.log(JSON.stringify({status:result.status,checks:result.checks.length}));}
})();
