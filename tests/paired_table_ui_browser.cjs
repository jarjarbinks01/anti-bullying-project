'use strict';
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const {chromium}=require('playwright');
const input=JSON.parse(fs.readFileSync(0,'utf8'));
const expected=JSON.parse(fs.readFileSync(input.cases,'utf8'));
const headers=['Metric','Valid in both waves, N','T0 Mean (SD)','T1 Mean (SD)','p-value',"Cohen's d"];
const result={status:'running',cases:[],page_errors:[],failed_requests:[]};
let browser;
const click=(page,name)=>page.getByRole('button',{name,exact:true}).click();
async function run(phase){
 const context=await browser.newContext({acceptDownloads:true,viewport:{width:1440,height:1000}});
 await context.route('**/*',route=>new URL(route.request().url()).hostname==='127.0.0.1'?route.continue():route.abort());
 if(phase==='baseline')await context.route('**/app.js',route=>route.fulfill({status:200,contentType:'text/javascript',body:fs.readFileSync(input.baseline_app,'utf8')}));
 const page=await context.newPage();
 page.on('pageerror',e=>result.page_errors.push(e.message));
 page.on('requestfailed',r=>result.failed_requests.push(r.url()));
 await page.goto(input.base+'/login.html');await page.locator('#password').fill(input.password);await page.locator('#submit').click();await page.waitForURL(input.base+'/');
 await click(page,'Descriptive statistics');
 let variant='normal',originalAll;
 for(const c of expected){
  if(c.variant!==variant){
   await page.unroute('**/snapshot.js');
   const body='window.STUDY2_SNAPSHOT='+fs.readFileSync(input.variants[c.variant],'utf8')+';';
   await page.route('**/snapshot.js',route=>route.fulfill({status:200,contentType:'text/javascript',body}));
   await page.reload();await page.locator('.sample-sidebar').waitFor();variant=c.variant;
  }
  await click(page,'Clear filters');await page.getByLabel('Analysis sample',{exact:true}).selectOption(c.mode);
  await page.getByLabel('Respondent',{exact:true}).selectOption(c.role);
  if(c.sources[0]!=='all'){await click(page,'No sources');for(const source of c.sources)await page.locator(`[data-source="${source}"]`).check();}
  if(c.grades.length!==13){await click(page,'No grades');for(const grade of c.grades)await page.locator(`[data-grade="${grade}"]`).check();}
  await click(page,'Longitudinal comparison');
  const tables=await page.locator('.family-block').evaluateAll(blocks=>blocks.map(block=>({family:block.querySelector('h3').textContent,headers:[...block.querySelectorAll('thead th')].map(x=>x.textContent),rows:[...block.querySelectorAll('tbody tr')].map(row=>[...row.children].map(x=>x.textContent)),width:block.clientWidth,scrollWidth:block.querySelector('.table-wrap').scrollWidth,clientWidth:block.querySelector('.table-wrap').clientWidth})));
  assert(tables.length>0,c.name+' must have actual outcome tables');
  const compact=c.mode==='acbd';
  if(phase==='candidate'&&compact){for(const table of tables){assert.deepEqual(table.headers,headers,c.name+': exact six headers');assert(table.scrollWidth<=table.clientWidth,c.name+': desktop table fits');for(const row of table.rows)assert.equal(row.length,6,c.name+': six cells');}}
  if(phase==='candidate'&&!compact){for(const table of tables)assert(table.headers.includes('Change SD')&&table.headers.includes('Formal paired N'),'other cohort layouts retained');}
  const download=page.waitForEvent('download');await click(page,'Download all paired changes (CSV)');const item=await download;
  const file=phase+'-'+c.name+'.csv';await item.saveAs(path.join(input.output,file));
  if(c.name==='all')originalAll=fs.readFileSync(path.join(input.output,file),'utf8');
  let reset=false;
  if(c.name==='union-grades'){
   await click(page,'Clear filters');const wait=page.waitForEvent('download');await click(page,'Download all paired changes (CSV)');const d=await wait;
   const resetFile=phase+'-reset.csv';await d.saveAs(path.join(input.output,resetFile));
   reset=fs.readFileSync(path.join(input.output,resetFile),'utf8')===originalAll;assert(reset,'AC/BD reset restores exact unrestricted audit CSV');
  }
  const summary=await page.locator('.sample-summary .summary-n strong').allTextContents();
  const body=await page.locator('.analysis-body').innerText();
  if(phase==='candidate'&&compact){assert(body.includes('Two-sided paired t-test')&&body.includes('dz = mean(T1 - T0) / SD(T1 - T0)')&&body.includes('positive means higher T1'),'exact method and direction footnote');}
  if(phase==='candidate'&&c.name==='ef-adult-block')assert(!tables.some(t=>t.family==='PHQ'),'adult PHQ remains excluded');
  if(phase==='candidate'&&['all','union','one-pair','zero-pairs','legacy-all','suppressed'].includes(c.name)){
   if(c.name==='all'){
    const table=page.locator('.family-block').first();await table.scrollIntoViewIfNeeded();
    await table.screenshot({path:path.join(input.output,'six-column-table.png')});
   }
   fs.writeFileSync(path.join(input.output,c.name+'.html'),await page.locator('.analysis-body').evaluate(x=>x.outerHTML));
  }
  result.cases.push({phase,name:c.name,variant:c.variant,role:c.role,mode:c.mode,sources:c.sources,grades:c.grades,tables,file,summary,reset});
 }
 await context.close();
}
(async()=>{
 try{browser=await chromium.launch({headless:true});result.browser_version=browser.version();await run('baseline');await run('candidate');assert.deepEqual(result.page_errors,[]);assert.deepEqual(result.failed_requests,[]);result.status='passed';}
 catch(error){result.status='failed';result.error={message:error.message,stack:error.stack};process.exitCode=1;}
 finally{if(browser)await browser.close();fs.writeFileSync(path.join(input.output,'RESULTS.json'),JSON.stringify(result,null,2));console.log(JSON.stringify({status:result.status,cases:result.cases.length}));}
})();
