"""Synthetic HTTP access, signed-session and deployment-isolation regressions."""
import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest

from study2.common import PipelineError
from study2.static_access import PUBLIC_FILES
from study2.static_export import DEPLOY_FILES, FORMAT, write_site


def sample():
    return dict(format=FORMAT,release_id='synthetic-release',generated_at='2026-01-01T00:00:00Z',
                published_at='2026-01-01T00:00:00Z',views=[])


@pytest.fixture(scope='module')
def site(tmp_path_factory):
    if not shutil.which('node'):pytest.skip('Node is required to execute the server access layer')
    path=tmp_path_factory.mktemp('access')/'site'
    write_site(sample(),path)
    return path


def node(site, body):
    setup='''
import assert from 'node:assert/strict';
const {gate,handleAuth,mintSession,verifiedSession,SESSION_SECONDS}=await import(process.argv[1]);
const pass=['synthetic','research','access'].join('-');
const env={STUDY2_ACCESS_PASSWORD:pass,STUDY2_SESSION_SECRET:'1'.repeat(64)};
const base='https://study2.example.org';
const request=(path='/',options={})=>new Request(base+path,options);
const post=(body,headers={})=>request('/api/auth',{method:'POST',
  headers:{origin:base,'content-type':'application/json',...headers},body:JSON.stringify(body)});
const signedRequest=(token,path='/snapshot.js')=>request(path,{headers:{cookie:'__Host-study2_session='+token}});
'''
    result=subprocess.run([shutil.which('node'),'--input-type=module','-e',setup+body,
                           (site/'server/access-core.js').as_uri()],text=True,capture_output=True)
    assert result.returncode==0,result.stderr
    return result.stdout


@pytest.mark.parametrize('path',['/','/index.html','/app.js','/snapshot.js','/bootstrap-on.js','/snapshot-manifest.json',
    '/scope-index.js','/scope-engine.js','/quality-ui.js',
    '/any-future-data.json','/server/access-core.js','/login.html/','/%2flogin.html'])
def test_every_nonpublic_route_blocks_unauthenticated_content(site,path):
    node(site,f'''
const response=gate(request({json.dumps(path)}),env);
assert.equal(response.status,401);assert.equal(response.headers.get('Cache-Control'),'private, no-store, max-age=0');
assert.equal(response.headers.get('Cross-Origin-Resource-Policy'),'same-origin');
assert.deepEqual(await response.json(),{{error:'authentication_required'}});
''')


def test_login_assets_are_public_and_document_navigation_redirects_without_data(site):
    node(site,'''
for(const path of ['/login.html','/login.css','/login.js','/api/auth'])assert.equal(gate(request(path),env),null);
const response=gate(request('/',{headers:{accept:'text/html'}}),env);
assert.equal(response.status,303);assert.equal(response.headers.get('location'),'/login.html');
for(const method of ['HEAD','OPTIONS','POST'])assert.equal(gate(request('/snapshot.js',{method}),env).status,401);
const ranged=gate(request('/snapshot.js',{headers:{range:'bytes=0-99','if-none-match':'cached-data'}}),env);
assert.equal(ranged.status,401);
''')


def test_missing_or_short_configuration_never_grants_access(site):
    node(site,'''
for(const config of [{},{STUDY2_ACCESS_PASSWORD:pass},{...env,STUDY2_SESSION_SECRET:'short'}]){
  assert.equal(gate(request('/snapshot.js'),config).status,503);
  const response=await handleAuth(post({action:'login',password:pass}),config);
  assert.equal(response.status,503);assert.equal(response.headers.get('set-cookie'),null);
}
''')


def test_correct_login_sets_http_only_host_bound_cookie_but_never_returns_token(site):
    node(site,'''
const response=await handleAuth(post({action:'login',password:pass}),env);
assert.equal(response.status,200);assert.deepEqual(await response.json(),{authenticated:true});
const cookie=response.headers.get('set-cookie');
for(const part of ['__Host-study2_session=','Path=/','HttpOnly','Secure','SameSite=Strict','Max-Age=28800'])assert.ok(cookie.includes(part));
assert.ok(!cookie.includes(pass));
const token=cookie.split(';')[0].split('=')[1];
assert.equal(verifiedSession(signedRequest(token),env),true);
assert.equal(gate(signedRequest(token),env),null);
assert.equal(verifiedSession(new Request('https://other.example.org/snapshot.js',{headers:{cookie:cookie.split(';')[0]}}),env),false);
''')


def test_wrong_password_and_cross_origin_requests_cannot_create_or_clear_a_session(site):
    node(site,'''
const wrong=await handleAuth(post({action:'login',password:pass+'x'}),env);
assert.equal(wrong.status,401);assert.equal(wrong.headers.get('set-cookie'),null);
assert.ok(!(await wrong.text()).includes(pass));
for(const action of ['login','logout']){
  const response=await handleAuth(post({action,password:pass},{origin:'https://other.example.org'}),env);
  assert.equal(response.status,403);assert.equal(response.headers.get('set-cookie'),null);
}
const noOrigin=request('/api/auth',{method:'POST',headers:{'content-type':'application/json'},body:'{}'});
assert.equal((await handleAuth(noOrigin,env)).status,403);
''')


def test_tampering_expiry_rotation_and_duplicate_cookies_fail_closed(site):
    node(site,'''
const token=mintSession(request('/'),env,1000);
assert.equal(verifiedSession(signedRequest(token),env,1000),true);
assert.equal(verifiedSession(signedRequest(token),env,1000+SESSION_SECONDS-1),true);
assert.equal(verifiedSession(signedRequest(token),env,1000+SESSION_SECONDS),false);
assert.equal(verifiedSession(signedRequest(token),env,999),false);
assert.equal(verifiedSession(signedRequest(token+'x'),env,1000),false);
assert.equal(verifiedSession(signedRequest('junk'),env,1000),false);
assert.equal(verifiedSession(signedRequest(token),{...env,STUDY2_ACCESS_PASSWORD:pass+'x'},1000),false);
assert.equal(verifiedSession(signedRequest(token),{...env,STUDY2_SESSION_SECRET:'2'.repeat(64)},1000),false);
const duplicate=request('/',{headers:{cookie:'__Host-study2_session='+token+'; __Host-study2_session='+token}});
assert.equal(verifiedSession(duplicate,env,1000),false);
''')


def test_logout_is_post_only_and_clears_cookie_without_exposing_credentials(site):
    node(site,'''
const response=await handleAuth(post({action:'logout'}),env);
assert.equal(response.status,200);assert.ok(response.headers.get('set-cookie').includes('Max-Age=0'));
assert.deepEqual(await response.json(),{authenticated:false});
const get=await handleAuth(request('/api/auth?action=logout'),env);
assert.equal(get.headers.get('set-cookie'),null);assert.deepEqual(await get.json(),{authenticated:false});
assert.equal((await handleAuth(request('/api/auth',{method:'DELETE'}),env)).status,405);
''')


def test_invalid_json_content_type_and_large_chunked_body_are_rejected(site):
    node(site,'''
assert.equal((await handleAuth(post([]),env)).status,400);
assert.equal((await handleAuth(post({action:'login',password:pass},{'content-type':'text/plain'}),env)).status,415);
assert.equal((await handleAuth(post({action:'login',password:'x'.repeat(3000)}),env)).status,413);
const bad=request('/api/auth',{method:'POST',headers:{origin:base,'content-type':'application/json'},body:'{broken'});
assert.equal((await handleAuth(bad,env)).status,400);
''')


def test_loopback_cookie_mode_cannot_be_used_on_a_vercel_deployment(site):
    node(site,'''
const local=new Request('http://127.0.0.1:8766/api/auth',{method:'POST',
  headers:{origin:'http://127.0.0.1:8766','content-type':'application/json'},body:JSON.stringify({action:'login',password:pass})});
const response=await handleAuth(local,{...env,STUDY2_LOCAL_PREVIEW:'1'});
assert.equal(response.status,200);assert.ok(response.headers.get('set-cookie').startsWith('study2_local_session='));
const production={...env,STUDY2_LOCAL_PREVIEW:'1',VERCEL:'1'};
assert.equal(gate(new Request('http://127.0.0.1:8766/snapshot.js'),production).status,503);
assert.equal(gate(new Request('http://other.example.org/snapshot.js'),{...env,STUDY2_LOCAL_PREVIEW:'1'}).status,503);
''')


def test_production_build_copies_only_public_allowlist_and_rejects_modified_inputs(site,tmp_path):
    copy=tmp_path/'copy';shutil.copytree(site,copy)
    (copy/'private-note.txt').write_text('must never be served')
    result=subprocess.run([shutil.which('node'),'build.mjs'],cwd=copy,text=True,capture_output=True)
    assert result.returncode==0,result.stderr
    assert {p.name for p in (copy/'public').iterdir()}==set(PUBLIC_FILES)
    assert not (copy/'public/server').exists() and not (copy/'public/package.json').exists()
    (copy/'app.js').write_text('tampered')
    result=subprocess.run([shutil.which('node'),'build.mjs'],cwd=copy,text=True,capture_output=True)
    assert result.returncode!=0 and 'fingerprint changed' in result.stderr


def test_build_accepts_vercel_config_normalization_but_rejects_changed_headers(site,tmp_path):
    copy=tmp_path/'cloud-build';shutil.copytree(site,copy)
    config_path=copy/'vercel.json';config=json.loads(config_path.read_text())
    config.update(name='study2-dashboard',version=2)
    config_path.write_text(json.dumps(config,separators=(',',':')))
    env={**os.environ,'VERCEL':'1'}
    result=subprocess.run([shutil.which('node'),'build.mjs'],cwd=copy,env=env,text=True,capture_output=True)
    assert result.returncode==0,result.stderr
    config['headers'][0]['headers'][0]['value']='unsafe-change'
    config_path.write_text(json.dumps(config,separators=(',',':')))
    result=subprocess.run([shutil.which('node'),'build.mjs'],cwd=copy,env=env,text=True,capture_output=True)
    assert result.returncode!=0 and 'fingerprint changed: vercel.json' in result.stderr


def test_repeat_export_preserves_local_metadata_and_rejects_extra_compiled_files(tmp_path):
    root=tmp_path/'site';write_site(sample(),root)
    (root/'.gitignore').write_text('.vercel\n')
    (root/'node_modules').mkdir();(root/'node_modules/private-local-config').write_text('preserve locally')
    (root/'public').mkdir();(root/'public/index.html').write_text('old compiled page')
    write_site(sample(),root)
    assert (root/'.gitignore').read_text()=='.vercel\n'
    assert (root/'node_modules/private-local-config').read_text()=='preserve locally'
    assert not (root/'public').exists()
    (root/'public').mkdir();(root/'public/unknown.xlsx').write_text('unrelated private work')
    with pytest.raises(PipelineError):write_site(sample(),root)
    assert (root/'public/unknown.xlsx').exists()


def test_failed_gate_export_restores_the_entire_previous_deployment(tmp_path,monkeypatch):
    import study2.static_export as exporter
    root=tmp_path/'site';write_site(sample(),root)
    before={name:(root/name).read_bytes() for name in DEPLOY_FILES}
    (root/'node_modules').mkdir();(root/'node_modules/local-marker').write_text('retained')
    replace=exporter.os.replace
    def fail(source,destination):
        if Path(destination)==root and not str(source).endswith('-previous'):raise OSError('synthetic install failure')
        return replace(source,destination)
    monkeypatch.setattr(exporter.os,'replace',fail)
    with pytest.raises(OSError):write_site({**sample(),'release_id':'next-release'},root)
    assert all((root/name).read_bytes()==value for name,value in before.items())
    assert (root/'node_modules/local-marker').read_text()=='retained'
