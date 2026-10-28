"""Synthetic release tests for lazy loading and protected download flows."""
import base64
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

from test_static_release_context import exported  # shared invented release fixture


def sri(data):
    return 'sha384-' + base64.b64encode(hashlib.sha384(data).digest()).decode()


def payload(path, prefix):
    return json.loads(path.read_text().split(prefix, 1)[1].removesuffix(';\n'))


def test_lazy_bootstrap_is_bound_to_complete_validated_release(exported):
    _, manifest, _, site = exported
    html = (site / 'index.html').read_text()
    boot_bytes = (site / 'bootstrap-on.js').read_bytes()
    boot = payload(site / 'bootstrap-on.js', 'window.STUDY2_LAZY_BOOTSTRAP=')
    assert 'src="bootstrap-on.js" integrity="' + sri(boot_bytes) + '"' in html
    assert all('src="' + name + '"' not in html for name in ('snapshot.js', 'scope-index.js', 'manual-exclusion.js'))
    assert boot['revision'] == manifest['revision']
    assert boot['off']['snapshot']['views'] == boot['on']['snapshot']['views'] == []
    wrapper = payload(site / 'manual-exclusion.js', 'window.STUDY2_MANUAL_EXCLUSION=')
    assert boot['bindings']['on_revision'] == wrapper['on_revision']
    for name, expected in boot['bindings']['scripts'].items():
        assert expected == sri((site / name).read_bytes())
    assert boot['on']['scope_export'] == wrapper['on']['scope_export']
    assert boot['impact'] == wrapper['impact']


BROWSER = r'''
const fs=require('node:fs'),assert=require('node:assert/strict'),{createServer}=require('node:http');
const {Readable}=require('node:stream'),{randomBytes,createHash}=require('node:crypto'),{chromium}=require('playwright');
const input=JSON.parse(fs.readFileSync(0,'utf8'));
let gate,handleAuth,PRIVATE_HEADERS;
const env={STUDY2_ACCESS_PASSWORD:randomBytes(24).toString('hex'),STUDY2_SESSION_SECRET:randomBytes(32).toString('hex'),STUDY2_LOCAL_PREVIEW:'1'};
const original=input.assets;let variant='normal',failOnce=false;const requests=[];
const sri=s=>'sha384-'+createHash('sha384').update(s,'utf8').digest('base64');
const parse=(s,prefix)=>JSON.parse(s.split(prefix)[1].replace(/;\s*$/,''));
const encode=x=>JSON.stringify(x).replaceAll('<','\\u003c');
const bootPrefix='window.STUDY2_LAZY_BOOTSTRAP=',manualPrefix='window.STUDY2_MANUAL_EXCLUSION=';
const altered=()=>{
 const wrapper=parse(original['/manual-exclusion.js'],manualPrefix);wrapper.release_id='wrong-synthetic-release';
 const manual=original['/manual-exclusion.js'].split(manualPrefix)[0]+manualPrefix+encode(wrapper)+';\n';
 const boot=parse(original['/bootstrap-on.js'],bootPrefix);boot.bindings.scripts['manual-exclusion.js']=sri(manual);
 const bootstrap=bootPrefix+encode(boot)+';\n';
 return {...original,'/manual-exclusion.js':manual,'/bootstrap-on.js':bootstrap,
  '/index.html':original['/index.html'].replace(/integrity="sha384-[A-Za-z0-9+/]+"/,'integrity="'+sri(bootstrap)+'"')};
};
const wrong=altered();let server,browser;
const invalidBoot=(()=>{const boot=parse(original['/bootstrap-on.js'],bootPrefix);boot.revision='f'.repeat(64);
 const bootstrap=bootPrefix+encode(boot)+';\n';return {...original,'/bootstrap-on.js':bootstrap,
  '/index.html':original['/index.html'].replace(/integrity="sha384-[A-Za-z0-9+/]+"/,'integrity="'+sri(bootstrap)+'"')};})();
(async()=>{try{
 ({gate,handleAuth,PRIVATE_HEADERS}=await import(input.accessModule));
 server=createServer(async(req,res)=>{try{
  const url=new URL(req.url,'http://'+req.headers.host),init={method:req.method,headers:req.headers};
  if(!['GET','HEAD'].includes(req.method)){init.body=Readable.toWeb(req);init.duplex='half';}
  const request=new Request(url,init);let response=gate(request,env);
  if(!response&&url.pathname==='/api/auth')response=await handleAuth(request,env);
  if(!response){let name=url.pathname==='/'?'/index.html':url.pathname;requests.push(name);
   if(failOnce&&name==='/manual-exclusion.js'){failOnce=false;response=new Response('unavailable',{status:503});}
   else {let chosen=variant==='wrong'?wrong:variant==='invalid'?invalidBoot:original,body=chosen[name];
    if(variant==='tamper'&&name==='/bootstrap-on.js')body+='\n/* tampered */';
    response=body===undefined?new Response('not found',{status:404}):new Response(body,{headers:{...PRIVATE_HEADERS,'Content-Type':name.endsWith('.js')?'text/javascript; charset=utf-8':name.endsWith('.css')?'text/css; charset=utf-8':name.endsWith('.json')?'application/json':'text/html; charset=utf-8'}});}}
  res.writeHead(response.status,Object.fromEntries(response.headers));res.end(Buffer.from(await response.arrayBuffer()));
 }catch{res.writeHead(500);res.end('test server error');}});
 await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));const base='http://127.0.0.1:'+server.address().port;
 assert.equal((await fetch(base+'/bootstrap-on.js')).status,401);assert.equal((await fetch(base+'/snapshot.js')).status,401);
 browser=await chromium.launch({headless:true});const context=await browser.newContext({acceptDownloads:true});const page=await context.newPage();
 await page.goto(base+'/');await page.getByLabel('Research access password').fill(env.STUDY2_ACCESS_PASSWORD);
 await page.getByRole('button',{name:'Open research dashboard'}).click();
 await page.locator('.manual-eligibility[data-state=ready][data-mode=on]').waitFor();await page.locator('.s2-quality[data-state=ready]').waitFor();
 assert(requests.includes('/bootstrap-on.js'));
 for(const name of ['/snapshot.js','/scope-index.js','/manual-exclusion.js'])assert(!requests.includes(name),'must be lazy: '+name);
 const date=page.getByLabel('Start date · Hong Kong',{exact:true});await date.fill('2025-01-02');await page.locator('.s2-quality[data-state=ready]').waitFor();
 const facets=page.locator('input[data-facet="sources"]');if(await facets.count()>1){await facets.first().uncheck();await page.locator('.s2-quality[data-state=ready]').waitFor();}
 const scope=()=>page.evaluate(()=>({date:document.querySelector('[aria-label="Start date · Hong Kong"]').value,sources:[...document.querySelectorAll('input[data-facet="sources"]:checked')].map(x=>x.dataset.key)}));
 const savedScope=await scope();
 const download=async label=>{const wait=page.waitForEvent('download');await page.getByRole('button',{name:label,exact:true}).click();return JSON.parse(fs.readFileSync(await (await wait).path(),'utf8'));};
 const before=await download('Download current aggregate JSON');assert.equal(before.eligibility.mode,'on');
 failOnce=true;await page.locator('#manual-exclusion-enabled').click();await page.getByRole('button',{name:'Retry loading',exact:true}).waitFor();
 assert.equal(await page.locator('[data-sample]').count(),0);assert.equal(await page.locator('#download-snapshot').isDisabled(),true);
 await page.getByRole('button',{name:'Retry loading',exact:true}).click();
 await page.locator('.manual-eligibility[data-state=ready][data-mode=off]').waitFor();await page.locator('.s2-quality[data-state=ready]').waitFor();
 assert.deepEqual(await scope(),savedScope);assert.equal((await download('Download current aggregate JSON')).eligibility.mode,'off');
 await page.locator('#manual-exclusion-enabled').click();await page.locator('.manual-eligibility[data-mode=on]').waitFor();await page.locator('.s2-quality[data-state=ready]').waitFor();
 assert.deepEqual(await scope(),savedScope);assert.deepEqual(await download('Download current aggregate JSON'),before);
 const full=await download('Download aggregate snapshot');assert.equal(full.eligibility.eligibility_mode,'on');
 assert.equal(full.snapshot.release_id,input.release);assert(full.snapshot.views.length>0);
 assert(['/snapshot.js','/scope-index.js','/manual-exclusion.js'].every(name=>requests.includes(name)));
 await page.getByRole('button',{name:'Descriptive statistics',exact:true}).click();await page.locator('.sample-sidebar').waitFor();

 // A direct link to another tab loads and validates its full data first.
 const deep=await context.newPage();await deep.goto(base+'/#page=1');await deep.locator('.sample-sidebar').waitFor();
 assert.equal(await deep.locator('#manual-exclusion-enabled').isChecked(),true);await deep.close();

 // A tampered initial bootstrap cannot become a usable ON or OFF view.
 variant='tamper';const bad=await context.newPage();await bad.goto(base+'/');
 await bad.getByText('The snapshot did not load. Check that every file was uploaded.',{exact:true}).waitFor();
 assert.equal(await bad.locator('.s2-quality').count(),0);await bad.close();

 // A structurally inconsistent bootstrap with a freshly recomputed SRI must
 // remain failed closed even if another tab is requested.
 variant='invalid';const invalid=await context.newPage();const mark=requests.length;await invalid.goto(base+'/');
 await invalid.getByRole('button',{name:'Reload page',exact:true}).waitFor();
 await invalid.getByRole('button',{name:'Descriptive statistics',exact:true}).click();
 assert.equal(await invalid.locator('.sample-sidebar').count(),0);
 assert(!requests.slice(mark).includes('/manual-exclusion.js'));await invalid.close();

 // Even with freshly recomputed transport integrity, a mixed-release full
 // bundle is rejected and cannot replace the valid initial ON data.
 variant='wrong';const mixed=await context.newPage();await mixed.goto(base+'/');
 await mixed.locator('.manual-eligibility[data-state=ready][data-mode=on]').waitFor();
 await mixed.getByRole('button',{name:'Descriptive statistics',exact:true}).click();
 await mixed.getByRole('button',{name:'Retry loading',exact:true}).waitFor();
 assert.equal(await mixed.locator('.sample-sidebar').count(),0);assert.equal(await mixed.locator('#download-snapshot').isDisabled(),true);
 await mixed.getByRole('button',{name:'Return to data quality',exact:true}).click();
 await mixed.locator('.manual-eligibility[data-state=ready][data-mode=on]').waitFor();
 await mixed.locator('.s2-quality[data-state=ready]').waitFor();
 await mixed.close();variant='normal';await page.getByRole('button',{name:'Sign out of the research workspace'}).click();
 await page.getByLabel('Research access password').waitFor();assert.equal((await page.request.get(base+'/bootstrap-on.js')).status(),401);
 await context.close();console.log(JSON.stringify({status:'passed',authenticated:true,logout:true,lazy:true,fail_retry:true,filters:true,downloads:true,tamper_rejected:true,invalid_boot_rejected:true,mixed_release_rejected:true}));
}finally{if(browser)await browser.close();if(server)await new Promise(resolve=>server.close(resolve));}})().catch(e=>{console.error(e.stack);process.exitCode=1;});
'''


def test_authenticated_lazy_loading_retry_filters_downloads_and_release_guards(exported, tmp_path):
    value, _, _, site = exported
    assets = {'/' + p.name: p.read_text() for p in site.iterdir()
              if p.is_file() and p.suffix in {'.js', '.css', '.html', '.json'}}
    node = shutil.which('node')
    modules = Path(os.environ.get('SOURCE_UI_NODE_MODULES', Path.home() / '.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules'))
    result = subprocess.run([node, '--input-type=commonjs', '-e', BROWSER],
        input=json.dumps(dict(assets=assets, accessModule=(site / 'server/access-core.js').as_uri(),
                              release=value['summary']['release_id'])), text=True, capture_output=True,
        env={**os.environ, 'NODE_PATH': str(modules)}, timeout=120)
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout)['status'] == 'passed'


RACE_BROWSER = r'''
const fs=require('node:fs'),assert=require('node:assert/strict'),{createServer}=require('node:http');
const {Readable}=require('node:stream'),{randomBytes}=require('node:crypto'),{chromium}=require('playwright');
const input=JSON.parse(fs.readFileSync(0,'utf8'));
const env={STUDY2_ACCESS_PASSWORD:randomBytes(24).toString('hex'),STUDY2_SESSION_SECRET:randomBytes(32).toString('hex'),STUDY2_LOCAL_PREVIEW:'1'};
let gate,handleAuth,PRIVATE_HEADERS,server,browser,held=null;
function arm(fail=false){
 let release,seen;const waiting=new Promise(r=>release=r),requested=new Promise(r=>seen=r);
 held={fail,waiting,requested,release,seen};return held;
}
const readDownload=async event=>JSON.parse(fs.readFileSync(await (await event).path(),'utf8'));
async function download(page,label){const event=page.waitForEvent('download');await page.getByRole('button',{name:label,exact:true}).click();return readDownload(event);}
const ready=page=>page.locator('.manual-eligibility[data-state=ready][data-mode=on]').waitFor();
(async()=>{try{
 ({gate,handleAuth,PRIVATE_HEADERS}=await import(input.accessModule));
 server=createServer(async(req,res)=>{try{
  const url=new URL(req.url,'http://'+req.headers.host),init={method:req.method,headers:req.headers};
  if(!['GET','HEAD'].includes(req.method)){init.body=Readable.toWeb(req);init.duplex='half';}
  const request=new Request(url,init);let response=gate(request,env);
  if(!response&&url.pathname==='/api/auth')response=await handleAuth(request,env);
  if(!response){const name=url.pathname==='/'?'/index.html':url.pathname;let failed=false;
   if(name==='/manual-exclusion.js'&&held){const slot=held;held=null;slot.seen();await slot.waiting;failed=slot.fail;}
   const body=input.assets[name];
   response=failed?new Response('unavailable',{status:503}):body===undefined?new Response('not found',{status:404}):
    new Response(body,{headers:{...PRIVATE_HEADERS,'Content-Type':name.endsWith('.js')?'text/javascript; charset=utf-8':name.endsWith('.css')?'text/css; charset=utf-8':name.endsWith('.json')?'application/json':'text/html; charset=utf-8'}});
  }
  res.writeHead(response.status,Object.fromEntries(response.headers));res.end(Buffer.from(await response.arrayBuffer()));
 }catch{res.writeHead(500);res.end('test server error');}});
 await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));const base='http://127.0.0.1:'+server.address().port;
 browser=await chromium.launch({headless:true});const context=await browser.newContext({acceptDownloads:true});const page=await context.newPage();
 await page.goto(base+'/');await page.getByLabel('Research access password').fill(env.STUDY2_ACCESS_PASSWORD);
 await page.getByRole('button',{name:'Open research dashboard'}).click();await ready(page);await page.locator('.s2-quality[data-state=ready]').waitFor();
 const date=page.getByLabel('Start date · Hong Kong',{exact:true});await date.fill('2025-01-02');await page.locator('.s2-quality[data-state=ready]').waitFor();
 const facets=page.locator('input[data-facet="sources"]');if(await facets.count()>1){await facets.first().uncheck();await page.locator('.s2-quality[data-state=ready]').waitFor();}
 const scope=()=>page.evaluate(()=>({date:document.querySelector('[aria-label="Start date · Hong Kong"]').value,sources:[...document.querySelectorAll('input[data-facet="sources"]:checked')].map(x=>x.dataset.key)}));
 const savedScope=await scope(),before=await download(page,'Download current aggregate JSON');

 // Keep one authenticated full asset in flight while OFF and a page change are requested.
 const first=arm();await page.locator('#manual-exclusion-enabled').click();await first.requested;
 assert.equal(await page.locator('#manual-exclusion-enabled').isChecked(),false);
 await page.getByRole('button',{name:'Descriptive statistics',exact:true}).click();
 assert.equal(new URL(page.url()).hash,'#page=1');first.release();
 await page.locator('.manual-eligibility[data-state=ready][data-mode=off]').waitFor();await page.locator('.sample-sidebar').waitFor();
 const off=await download(page,'Download aggregate snapshot');assert.equal(off.eligibility.eligibility_mode,'off');
 const original=JSON.parse(input.assets['/snapshot.js'].split('window.STUDY2_SNAPSHOT=')[1].replace(/;\s*$/,''));
 assert.deepEqual(off.snapshot,original);
 await page.locator('#manual-exclusion-enabled').click();await ready(page);
 await page.getByRole('button',{name:'Data quality & progress',exact:true}).click();await page.locator('.s2-quality[data-state=ready]').waitFor();
 assert.deepEqual(await scope(),savedScope);assert.deepEqual(await download(page,'Download current aggregate JSON'),before);

 // Retry after a failed delayed asset retains the explicit OFF and page choice.
 const retryPage=await context.newPage();await retryPage.goto(base+'/');await ready(retryPage);
 const failed=arm(true);await retryPage.locator('#manual-exclusion-enabled').click();await failed.requested;
 await retryPage.getByRole('button',{name:'Descriptive statistics',exact:true}).click();failed.release();
 await retryPage.getByRole('button',{name:'Retry loading',exact:true}).waitFor();
 assert.equal(await retryPage.locator('#download-snapshot').isDisabled(),true);assert.equal(await retryPage.locator('.sample-sidebar').count(),0);
 await retryPage.getByRole('button',{name:'Retry loading',exact:true}).click();
 await retryPage.locator('.manual-eligibility[data-state=ready][data-mode=off]').waitFor();await retryPage.locator('.sample-sidebar').waitFor();
 assert.equal((await download(retryPage,'Download aggregate snapshot')).eligibility.eligibility_mode,'off');await retryPage.close();

 // A real user can request a download and then navigate while it is pending.
 const downloadPage=await context.newPage();await downloadPage.goto(base+'/');await ready(downloadPage);
 const pending=arm(),downloadEvent=downloadPage.waitForEvent('download');
 await downloadPage.getByRole('button',{name:'Download aggregate snapshot',exact:true}).click();await pending.requested;
 await downloadPage.getByRole('button',{name:'Descriptive statistics',exact:true}).click();pending.release();
 assert.equal((await readDownload(downloadEvent)).eligibility.eligibility_mode,'on');
 await downloadPage.locator('.manual-eligibility[data-state=ready][data-mode=on]').waitFor();await downloadPage.locator('.sample-sidebar').waitFor();
 await downloadPage.close();await context.close();
 console.log(JSON.stringify({status:'passed',off_navigation:true,off_download:true,filters_restored:true,retry:true,pending_download_navigation:true}));
}finally{if(held)held.release();if(browser)await browser.close();if(server)await new Promise(resolve=>server.close(resolve));}})().catch(e=>{console.error(e.stack);process.exitCode=1;});
'''


def test_off_request_survives_page_and_download_during_lazy_load(exported):
    _, _, _, site = exported
    assets = {'/' + p.name: p.read_text() for p in site.iterdir()
              if p.is_file() and p.suffix in {'.js', '.css', '.html', '.json'}}
    modules = Path(os.environ.get('SOURCE_UI_NODE_MODULES', Path.home() / '.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules'))
    result = subprocess.run([shutil.which('node'), '--input-type=commonjs', '-e', RACE_BROWSER],
        input=json.dumps(dict(assets=assets, accessModule=(site / 'server/access-core.js').as_uri())),
        text=True, capture_output=True, env={**os.environ, 'NODE_PATH': str(modules)}, timeout=120)
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout)['status'] == 'passed'
