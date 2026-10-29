"""Synthetic page-specific lazy loading, validated scopes and navigation races."""
import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest

from study2.static_assets import APP_JS
from test_static_semester_integration import exported


@pytest.fixture(scope='module')
def synthetic_site(request):
    existing=os.environ.get('STUDY2_SYNTHETIC_SITE')
    site=Path(existing) if existing else request.getfixturevalue('exported')[3]
    raw=(site/'bootstrap-on.js').read_text()
    boot=json.loads(raw.split('window.STUDY2_LAZY_BOOTSTRAP=',1)[1].removesuffix(';\n'))
    assert boot['release_id']=='synthetic-r04'  # Never run this browser fixture on research data.
    assert boot['on']['snapshot']['period_semester_selection']['format']=='study2_period_semester_v1'
    return site


BROWSER = r'''
const fs=require('node:fs'),assert=require('node:assert/strict'),{createServer}=require('node:http');
const {Readable}=require('node:stream'),{randomBytes,createHash}=require('node:crypto'),{chromium}=require('playwright');
const input=JSON.parse(fs.readFileSync(0,'utf8'));
const env={STUDY2_ACCESS_PASSWORD:randomBytes(24).toString('hex'),STUDY2_SESSION_SECRET:randomBytes(32).toString('hex'),STUDY2_LOCAL_PREVIEW:'1'};
const assets=input.assets,requests=[],large=['/snapshot.js','/scope-index.js','/manual-exclusion.js'];
const sri=s=>'sha384-'+createHash('sha384').update(s,'utf8').digest('base64');
let gate,handleAuth,PRIVATE_HEADERS,server,browser,held=null,releaseHeld=null,tamper=false,invalid=false,failFullOnce=false;
function arm(){let seen,release;const requested=new Promise(r=>seen=r),waiting=new Promise(r=>release=r);held={seen,waiting};releaseHeld=release;return {requested,release};}
function malformed(offScope=false){const prefix='window.STUDY2_LAZY_BOOTSTRAP=',b=JSON.parse(assets['/bootstrap-on.js'].slice(prefix.length,-2));if(offScope)b.off.scope_export.index.eligibility=b.on.scope_export.index.eligibility;else b.revision='f'.repeat(64);const js=prefix+JSON.stringify(b).replaceAll('<','\\u003c')+';\n';return {js,html:assets['/index.html'].replace(/integrity="sha384-[A-Za-z0-9+/]+"/,'integrity="'+sri(js)+'"')};}
let bad=malformed();
const noLegacy=()=>assert(!requests.some(x=>large.includes(x)),'legacy data loaded during semester navigation');
async function semesterReady(page){await page.waitForFunction(()=>{const p=[...document.querySelectorAll('.semester-panel')];return p.length===2&&p.every(x=>x.querySelector('table'));});}
async function independentReady(page){await page.waitForFunction(()=>{const p=[...document.querySelectorAll('.semester-panel')];return p.length===2&&p[1].querySelector('table')&&p[0].textContent.includes('unavailable');});}
function parseCsv(text){let rows=[],row=[],v='',q=false;for(let i=0;i<text.length;i++){const c=text[i];if(i===0&&c==='\ufeff')continue;if(c==='"'){if(q&&text[i+1]==='"'){v+='"';i++;}else q=!q;}else if(c===','&&!q){row.push(v);v='';}else if((c==='\r'||c==='\n')&&!q){if(c==='\r'&&text[i+1]==='\n')i++;row.push(v);rows.push(row);row=[];v='';if(rows.length===2)break;}else v+=c;}if(rows.length===1){row.push(v);rows.push(row);}assert.equal(rows.length,2);return Object.fromEntries(rows[0].map((k,i)=>[k,rows[1][i]]));}
async function currentCsv(page){const down=page.waitForEvent('download');await page.locator('.semester-panel').first().getByRole('button',{name:'Download current table (CSV)',exact:true}).first().click();return parseCsv(fs.readFileSync(await (await down).path(),'utf8'));}
(async()=>{try{
 ({gate,handleAuth,PRIVATE_HEADERS}=await import(input.accessModule));
 server=createServer(async(req,res)=>{try{
  const url=new URL(req.url,'http://'+req.headers.host),init={method:req.method,headers:req.headers};
  if(!['GET','HEAD'].includes(req.method)){init.body=Readable.toWeb(req);init.duplex='half';}
  const request=new Request(url,init);let response=gate(request,env);if(!response&&url.pathname==='/api/auth')response=await handleAuth(request,env);
  if(!response){const name=url.pathname==='/'?'/index.html':url.pathname;requests.push(name);
   if(name==='/manual-exclusion.js'&&held){const latch=held;held=null;latch.seen();await latch.waiting;}
   if(failFullOnce&&name==='/manual-exclusion.js'){failFullOnce=false;response=new Response('unavailable',{status:503});}
   else{let body=invalid&&name==='/bootstrap-on.js'?bad.js:invalid&&name==='/index.html'?bad.html:assets[name];
    if(tamper&&name==='/period-semester-on-abcd-student.json')body+=' ';
    response=body===undefined?new Response('not found',{status:404}):new Response(body,{headers:{...PRIVATE_HEADERS,'Content-Type':name.endsWith('.js')?'text/javascript; charset=utf-8':name.endsWith('.css')?'text/css; charset=utf-8':name.endsWith('.json')?'application/json':'text/html; charset=utf-8'}});}}
  res.writeHead(response.status,Object.fromEntries(response.headers));res.end(Buffer.from(await response.arrayBuffer()));
 }catch{res.writeHead(500);res.end('test server error');}});
 await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));const base='http://127.0.0.1:'+server.address().port;
 assert.equal((await fetch(base+'/period-semester-on-abcd-student.json')).status,401);
 browser=await chromium.launch({headless:true});const context=await browser.newContext({acceptDownloads:true}),page=await context.newPage();
 await page.goto(base+'/');await page.getByLabel('Research access password').fill(env.STUDY2_ACCESS_PASSWORD);await page.getByRole('button',{name:'Open research dashboard'}).click();
 await page.locator('.manual-eligibility[data-state=ready][data-mode=on]').waitFor();await page.locator('.s2-quality[data-state=ready]').waitFor();noLegacy();
 await page.locator('#manual-exclusion-enabled').click();await page.locator('.manual-eligibility[data-mode=off]').waitFor();await page.locator('.s2-quality[data-state=ready]').waitFor();noLegacy();
 await page.locator('#manual-exclusion-enabled').click();await page.locator('.manual-eligibility[data-mode=on]').waitFor();await page.locator('.s2-quality[data-state=ready]').waitFor();noLegacy();
 await page.getByRole('button',{name:'Descriptive statistics',exact:true}).click();await semesterReady(page);noLegacy();
 assert(requests.includes('/period-semester-on-abcd-student.json')&&requests.includes('/period-semester-on-abcd-parent.json'));
 const allRecord=await currentCsv(page);assert.equal(allRecord.source,'all');assert.equal(allRecord.source_selection_status,'all');assert.equal(allRecord.source_labels,'All sources');assert.equal(allRecord.source_all,'true');
 const deep=await context.newPage();await deep.goto(base+'/#page=1');await semesterReady(deep);noLegacy();await deep.close();
 await page.locator('[data-control="semester:semesters:S2"]').uncheck();await semesterReady(page);
 await page.locator('[data-control="semester:waves:T1"]').uncheck();await semesterReady(page);
 const startDate=page.getByLabel('Start date (Hong Kong, inclusive)'),endDate=page.getByLabel('End date (Hong Kong, inclusive)');
 const originalStart=await startDate.inputValue(),narrowStart=await endDate.inputValue();assert(originalStart&&narrowStart&&originalStart<narrowStart);
 await startDate.fill(narrowStart);await startDate.dispatchEvent('change');await semesterReady(page);
 await page.getByRole('button',{name:'No sources',exact:true}).click();await page.locator('[data-control="source:qualtrics"]').check();await semesterReady(page);noLegacy();
 const record=await currentCsv(page);
 assert.equal(record.filter_source_codes,'qualtrics');assert.equal(record.source_selection_status,'single');assert.equal(record.source_all,'false');assert.equal(record.source_labels,'Qualtrics');assert.equal(record.eligibility_mode,'on');
 await page.locator('[data-control="source:paperform"]').check();await semesterReady(page);const pooled=await currentCsv(page);assert.equal(pooled.source,'multiple');assert.equal(pooled.source_selection_status,'pooled');assert.equal(pooled.filter_source_codes,'paperform|qualtrics');
 await page.getByRole('button',{name:'No sources',exact:true}).click();for(const name of ['legacy_online','paperform','qualtrics','school_batch','socialworkdream'])await page.locator('[data-control="source:'+name+'"]').check();await semesterReady(page);
 const explicitAll=await currentCsv(page);assert.equal(explicitAll.source,'all');assert.equal(explicitAll.source_selection_status,'all');assert.equal(explicitAll.source_all,'false');
 await page.getByRole('button',{name:'No sources',exact:true}).click();await page.locator('[data-control="source:qualtrics"]').check();await semesterReady(page);noLegacy();
 await page.locator('#manual-exclusion-enabled').click();await page.locator('.manual-eligibility[data-mode=off]').waitFor();await semesterReady(page);noLegacy();
 assert.equal(await page.locator('[data-control="semester:semesters:S2"]').isChecked(),false);assert.equal(await page.locator('[data-control="semester:waves:T1"]').isChecked(),false);assert.equal(await startDate.inputValue(),narrowStart);
 assert(requests.includes('/period-semester-off-abcd-student.json')&&requests.includes('/period-semester-off-abcd-parent.json'));
 const offRecord=await currentCsv(page);assert.equal(offRecord.eligibility_mode,'off');assert.equal(offRecord.eligibility_revision,'');assert.equal(offRecord.filter_source_codes,'qualtrics');assert.equal(offRecord.source_selection_status,'single');
 await page.locator('#manual-exclusion-enabled').click();await page.locator('.manual-eligibility[data-mode=on]').waitFor();await semesterReady(page);
 assert.equal(await page.locator('[data-control="semester:semesters:S2"]').isChecked(),false);assert.equal(await page.locator('[data-control="semester:waves:T1"]').isChecked(),false);assert.equal(await startDate.inputValue(),narrowStart);
 await page.locator('#manual-exclusion-enabled').click();await page.locator('.manual-eligibility[data-mode=off]').waitFor();await semesterReady(page);noLegacy();
 await startDate.fill(originalStart);await startDate.dispatchEvent('change');await semesterReady(page);
 await page.locator('[data-control="semester:semesters:S2"]').check();await semesterReady(page);
 await page.locator('[data-control="semester:waves:T1"]').check();await semesterReady(page);
 await page.getByRole('button',{name:'No grades',exact:true}).click();await semesterReady(page);
 for(let i=0;i<2;i++)assert((await page.locator('.semester-panel').nth(i).locator('table').first().innerText()).includes('No responses'));
 await page.getByRole('button',{name:'All grades',exact:true}).click();await semesterReady(page);noLegacy();
 await page.getByRole('button',{name:'Data quality & progress',exact:true}).click();await page.locator('.s2-quality[data-state=ready]').waitFor();assert.equal(await page.locator('#manual-exclusion-enabled').isChecked(),false);noLegacy();
 const qualityDown=page.waitForEvent('download');await page.getByRole('button',{name:'Download current aggregate JSON',exact:true}).click();
 const quality=JSON.parse(fs.readFileSync(await (await qualityDown).path(),'utf8'));assert.equal(quality.eligibility.mode,'off');assert(quality.eligibility.samples.every(x=>x.excluded===0||x.excluded===null));noLegacy();
 await page.getByRole('button',{name:'Independent parent analysis',exact:true}).click();await independentReady(page);noLegacy();
 assert(requests.includes('/period-semester-off-independent_child-parent.json'));
 await page.getByRole('button',{name:'Descriptive statistics',exact:true}).click();await semesterReady(page);noLegacy();
 await page.getByRole('button',{name:'Research overview',exact:true}).click();await page.locator('.sample-summary').waitFor();
 assert(large.every(x=>requests.includes(x)));assert.equal(await page.locator('#manual-exclusion-enabled').isChecked(),false);

 // A full legacy load already requested by the user may finish after a
 // different page is selected; it must not replace the newer navigation.
 const race=await context.newPage();await race.goto(base+'/');await race.locator('.manual-eligibility[data-mode=on]').waitFor();
 await race.getByRole('button',{name:'Descriptive statistics',exact:true}).click();await semesterReady(race);
 await race.locator('#manual-exclusion-enabled').click();await race.locator('.manual-eligibility[data-mode=off]').waitFor();await semesterReady(race);
 const latch=arm();await race.getByRole('button',{name:'Research overview',exact:true}).click();await latch.requested;
 await race.getByRole('button',{name:'Independent parent analysis',exact:true}).click();assert.equal(new URL(race.url()).hash,'#page=2');latch.release();
 await independentReady(race);assert.equal(await race.locator('#manual-exclusion-enabled').isChecked(),false);await race.close();

 // A failed explicitly requested legacy load must leave a working, correctly
 // scoped way back to semester trends.
 const failed=await context.newPage();await failed.goto(base+'/');await failed.locator('.manual-eligibility[data-mode=on]').waitFor();
 await failed.getByRole('button',{name:'Descriptive statistics',exact:true}).click();await semesterReady(failed);
 await failed.locator('#manual-exclusion-enabled').click();await failed.locator('.manual-eligibility[data-mode=off]').waitFor();await semesterReady(failed);
 failFullOnce=true;await failed.getByRole('button',{name:'Research overview',exact:true}).click();await failed.getByRole('button',{name:'Retry loading',exact:true}).waitFor();
 await failed.getByRole('button',{name:'Return to period trends',exact:true}).click();await semesterReady(failed);assert.equal(await failed.locator('#manual-exclusion-enabled').isChecked(),false);await failed.close();

 // A bad semester asset fails closed without asking for the large bundle.
 requests.length=0;tamper=true;const badAsset=await context.newPage();await badAsset.goto(base+'/');await badAsset.locator('.manual-eligibility[data-mode=on]').waitFor();
 await badAsset.getByRole('button',{name:'Descriptive statistics',exact:true}).click();await badAsset.locator('.semester-panel').first().getByText(/SHA-256 mismatch/).waitFor();noLegacy();await badAsset.close();tamper=false;
 // A tampered bootstrap, even with its transport hash recomputed, cannot
 // start the semester view or substitute unverified data.
 requests.length=0;invalid=true;const badBoot=await context.newPage();await badBoot.goto(base+'/#page=1');await badBoot.getByRole('button',{name:'Reload page',exact:true}).waitFor();
 assert(!requests.some(x=>x.startsWith('/period-semester-')));noLegacy();await badBoot.close();
 requests.length=0;bad=malformed(true);const badOff=await context.newPage();await badOff.goto(base+'/#page=1');await badOff.getByRole('button',{name:'Reload page',exact:true}).waitFor();
 assert(!requests.some(x=>x.startsWith('/period-semester-')));noLegacy();await badOff.close();invalid=false;
 await context.close();console.log(JSON.stringify({status:'passed',cold_trends:true,off_on_bootstrap:true,quality_off:true,independent:true,csv_source_metadata:true,legacy_deferred:true,race:true,tamper_rejected:true,invalid_boot_rejected:true}));
}finally{if(releaseHeld)releaseHeld();if(browser)await browser.close();if(server)await new Promise(resolve=>server.close(resolve));}})().catch(e=>{console.error(e.stack);process.exitCode=1;});
'''


def test_semester_pages_defer_legacy_and_preserve_scopes_and_races(synthetic_site):
    site=synthetic_site
    assets={'/'+p.name:p.read_text() for p in site.iterdir() if p.is_file() and p.suffix in {'.js','.css','.html','.json'}}
    assets['/app.js']=APP_JS
    modules=Path(os.environ.get('SOURCE_UI_NODE_MODULES',Path.home()/'.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules'))
    result=subprocess.run([shutil.which('node'),'--input-type=commonjs','-e',BROWSER],
        input=json.dumps({'assets':assets,'accessModule':(site/'server/access-core.js').as_uri()}),
        text=True,capture_output=True,env={**os.environ,'NODE_PATH':str(modules)},timeout=180)
    assert result.returncode==0,result.stdout+result.stderr
    assert json.loads(result.stdout)['status']=='passed'
