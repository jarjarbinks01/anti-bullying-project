"""Vercel-only access templates. Credentials are runtime environment variables.

The browser receives no password verifier or session-signing material. Routing
middleware checks every deployed asset, including the aggregate snapshot.
"""
import json

PUBLIC_FILES = ('index.html', 'app.js', 'styles.css', 'snapshot.js',
                'scope-index.js', 'scope-engine.js', 'quality-ui.js', 'manual-exclusion.js',
                'snapshot-manifest.json', 'login.html', 'login.css', 'login.js', 'access.js')

ACCESS_CORE = r'''
import { createHash, createHmac, randomBytes, timingSafeEqual } from 'node:crypto';

export const SESSION_SECONDS = 8 * 60 * 60;
export const PRIVATE_HEADERS = {
  'Cache-Control': 'private, no-store, max-age=0',
  'CDN-Cache-Control': 'no-store',
  'Vercel-CDN-Cache-Control': 'no-store',
  'Vary': 'Cookie',
  'X-Content-Type-Options': 'nosniff',
  'Referrer-Policy': 'no-referrer',
  'X-Robots-Tag': 'noindex, nofollow',
  'Cross-Origin-Resource-Policy': 'same-origin',
};
const OPEN_FILES = new Set(['/login.html', '/login.js', '/login.css']);

function configuration(env) {
  const password = env.STUDY2_ACCESS_PASSWORD, secret = env.STUDY2_SESSION_SECRET;
  if (typeof password !== 'string' || password.length < 12 || password.length > 256 ||
      typeof secret !== 'string' || secret.length < 32 || secret.length > 1024) return null;
  // Rotating either environment value invalidates all previously issued cookies.
  const key = createHmac('sha256', secret).update('study2-session-v1\0').update(password).digest();
  return { password, key };
}

function cookiePolicy(request, env) {
  const url = new URL(request.url);
  const local = env.STUDY2_LOCAL_PREVIEW === '1' && env.VERCEL !== '1' &&
    url.protocol === 'http:' && ['127.0.0.1', 'localhost', '[::1]'].includes(url.hostname);
  return { name: local ? 'study2_local_session' : '__Host-study2_session',
           secure: !local, valid: url.protocol === 'https:' || local };
}

function readCookie(request, name) {
  const matches = (request.headers.get('cookie') || '').split(';')
    .map(part => part.trim()).filter(part => part.startsWith(name + '='));
  return matches.length === 1 ? matches[0].slice(name.length + 1) : null;
}

function equalPassword(candidate, expected) {
  const hash = value => createHash('sha256').update(value, 'utf8').digest();
  return timingSafeEqual(hash(candidate), hash(expected));
}

export function mintSession(request, env, now = Math.floor(Date.now() / 1000)) {
  const cfg = configuration(env), policy = cookiePolicy(request, env);
  if (!cfg || !policy.valid) throw new Error('Access configuration unavailable');
  const claims = { v: 1, scope: 'study2-dashboard', aud: new URL(request.url).origin,
                   iat: now, exp: now + SESSION_SECONDS, nonce: randomBytes(16).toString('hex') };
  const payload = Buffer.from(JSON.stringify(claims)).toString('base64url');
  return payload + '.' + createHmac('sha256', cfg.key).update(payload).digest('base64url');
}

export function verifiedSession(request, env, now = Math.floor(Date.now() / 1000)) {
  const cfg = configuration(env), policy = cookiePolicy(request, env);
  if (!cfg || !policy.valid) return false;
  const token = readCookie(request, policy.name);
  if (!token || token.length > 2048) return false;
  const parts = token.split('.');
  if (parts.length !== 2 || parts.some(part => !/^[A-Za-z0-9_-]+$/.test(part))) return false;
  const [payload, encoded] = parts, signature = Buffer.from(encoded, 'base64url');
  const expected = createHmac('sha256', cfg.key).update(payload).digest();
  if (signature.toString('base64url') !== encoded || signature.length !== expected.length ||
      !timingSafeEqual(signature, expected)) return false;
  try {
    const claims = JSON.parse(Buffer.from(payload, 'base64url').toString('utf8'));
    return claims.v === 1 && claims.scope === 'study2-dashboard' &&
      claims.aud === new URL(request.url).origin && Number.isInteger(claims.iat) &&
      Number.isInteger(claims.exp) && claims.iat <= now && claims.exp > now &&
      claims.exp - claims.iat === SESSION_SECONDS;
  } catch { return false; }
}

function json(value, status = 200, headers = {}) {
  return Response.json(value, { status, headers: { ...PRIVATE_HEADERS, ...headers } });
}

function cookie(request, env, token, maxAge) {
  const policy = cookiePolicy(request, env);
  return `${policy.name}=${token}; Path=/; HttpOnly; SameSite=Strict; Max-Age=${maxAge}` +
    (policy.secure ? '; Secure' : '');
}

async function smallJson(request) {
  if (!request.headers.get('content-type')?.toLowerCase().startsWith('application/json'))
    return { error: 'invalid_request', status: 415 };
  if (Number(request.headers.get('content-length')) > 2048)
    return { error: 'invalid_request', status: 413 };
  const reader = request.body?.getReader();
  if (!reader) return { error: 'invalid_request', status: 400 };
  const chunks = []; let size = 0;
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      size += value.byteLength;
      if (size > 2048) { await reader.cancel(); return { error: 'invalid_request', status: 413 }; }
      chunks.push(Buffer.from(value));
    }
    const body = JSON.parse(Buffer.concat(chunks).toString('utf8'));
    return body && typeof body === 'object' && !Array.isArray(body) ? { body } :
      { error: 'invalid_request', status: 400 };
  } catch { return { error: 'invalid_request', status: 400 }; }
}

export async function handleAuth(request, env) {
  if (request.method !== 'GET' && request.method !== 'POST')
    return json({ error: 'method_not_allowed' }, 405, { Allow: 'GET, POST' });
  if (request.method === 'POST' &&
      (request.headers.get('origin') !== new URL(request.url).origin ||
       request.headers.get('sec-fetch-site') === 'cross-site'))
    return json({ error: 'invalid_origin' }, 403);
  const policy = cookiePolicy(request, env);
  if (!policy.valid) return json({ error: 'https_required' }, 503);
  if (request.method === 'GET') {
    if (!configuration(env)) return json({ error: 'not_configured' }, 503);
    return json({ authenticated: verifiedSession(request, env) });
  }
  const input = await smallJson(request);
  if (input.error) return json({ error: input.error }, input.status);
  if (input.body.action === 'logout')
    return json({ authenticated: false }, 200, { 'Set-Cookie': cookie(request, env, '', 0) });
  const cfg = configuration(env);
  if (!cfg) return json({ error: 'not_configured' }, 503);
  const candidate = input.body.password;
  if (input.body.action !== 'login' || typeof candidate !== 'string' || candidate.length > 256)
    return json({ error: 'invalid_request' }, 400);
  if (!equalPassword(candidate, cfg.password)) {
    // A bounded delay is not a distributed rate limiter. Use the hosting WAF for that.
    await new Promise(resolve => setTimeout(resolve, 300));
    return json({ error: 'invalid_credentials' }, 401);
  }
  const token = mintSession(request, env);
  return json({ authenticated: true }, 200,
              { 'Set-Cookie': cookie(request, env, token, SESSION_SECONDS) });
}

export function gate(request, env) {
  const path = new URL(request.url).pathname;
  // Only the login's own assets and the auth API are public. No extension-based
  // exception: snapshot.js and every other present/future data URL are gated.
  if (path === '/api/auth' || (OPEN_FILES.has(path) && ['GET', 'HEAD'].includes(request.method))) return null;
  if (!configuration(env) || !cookiePolicy(request, env).valid)
    return json({ error: 'access_unavailable' }, 503);
  if (verifiedSession(request, env)) return null;
  const navigation = request.method === 'GET' && request.headers.get('accept')?.includes('text/html');
  if (navigation) return new Response(null, { status: 303,
    headers: { ...PRIVATE_HEADERS, Location: '/login.html' } });
  return json({ error: 'authentication_required' }, 401);
}
'''

MIDDLEWARE = r'''
import { next } from '@vercel/functions';
import { gate, PRIVATE_HEADERS } from './server/access-core.js';

// Run before the CDN on EVERY route, including .js, .json and deep links.
export const config = { matcher: '/:path*', runtime: 'nodejs' };
export default function middleware(request) {
  return gate(request, process.env) || next({ headers: PRIVATE_HEADERS });
}
'''

AUTH_API = r'''
import { handleAuth } from '../server/access-core.js';
export default { fetch(request) { return handleAuth(request, process.env); } };
'''

LOGIN_HTML = r'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex,nofollow"><title>Study 2 · Research sign-in</title>
<link rel="stylesheet" href="/login.css"><script defer src="/login.js"></script></head>
<body><main class="login-shell"><div class="identity"><span class="mark">S2</span><span>HKU · ANTI-BULLYING RESEARCH</span></div>
<section class="login-card" aria-labelledby="title"><div class="access-badge"><span></span>PRIVATE RESEARCH ACCESS</div>
<h1 id="title">Study 2 Research Dashboard</h1><p class="intro">Sign in with the password supplied by the research team.</p>
<form id="login-form"><label for="password">Research access password</label>
<div class="password-row"><input id="password" name="password" type="password" autocomplete="current-password" required maxlength="256" aria-describedby="message"><button type="button" id="reveal" aria-pressed="false">Show</button></div>
<p id="message" class="message" role="status" aria-live="polite">Checking sign-in status…</p>
<button id="submit" type="submit" class="submit">Open research dashboard <span aria-hidden="true">→</span></button></form>
<p class="access-note">For authorised researchers only. Sessions last 8 hours. Sign out when finished.</p></section>
<footer>Study 2 · Anti-bullying research<br>Contact the research lead if you need access.</footer></main></body></html>'''

LOGIN_CSS = r'''
:root{color-scheme:light;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","Noto Sans TC",sans-serif;color:#24354e;background:#f4f6fb}
*{box-sizing:border-box}body{margin:0;min-height:100vh;display:grid;place-items:center;padding:35px 20px}.login-shell{width:min(100%,460px)}
.identity{display:flex;align-items:center;justify-content:center;gap:12px;margin-bottom:27px;font-size:10px;letter-spacing:1.5px;color:#66758b;font-weight:650}.mark{background:#293f70;color:white;border-radius:8px;padding:12px;font-size:18px;letter-spacing:1px}
.login-card{background:white;border:1px solid #dce2ed;border-radius:12px;padding:34px 36px;box-shadow:0 15px 40px #23345508;border-top:4px solid #526bba}.access-badge{font-size:9px;font-weight:700;letter-spacing:1.6px;color:#586e96}.access-badge span{display:inline-block;width:7px;height:7px;border-radius:50%;background:#44896d;margin-right:8px}h1{font-size:27px;margin:16px 0 12px;letter-spacing:.2px}.intro{font-size:14px;color:#66758b;line-height:1.8;margin:0 0 27px}label{display:block;font-size:12px;font-weight:600;margin-bottom:8px}.password-row{display:flex;border:1px solid #cbd5e4;border-radius:6px;overflow:hidden}.password-row:focus-within{outline:3px solid #c5d2ef;outline-offset:2px}input{border:0;outline:none;font:inherit;min-width:0;width:100%;padding:12px 13px;color:#24354e;background:white}.password-row button{flex-shrink:0;white-space:nowrap;border:0;background:white;color:#536a98;padding:0 13px;font-size:12px;cursor:pointer}.message{font-size:12px;line-height:1.7;min-height:24px;color:#66758b;margin:11px 0}.message.error{color:#a62f3a}.submit{display:flex;justify-content:space-between;align-items:center;width:100%;font:inherit;font-size:14px;font-weight:600;background:#293f70;color:white;border:0;border-radius:6px;padding:13px 16px;cursor:pointer}.submit:hover{background:#354f88}.submit:disabled{opacity:.6;cursor:wait}.access-note{font-size:11px;color:#66758b;line-height:1.8;border-top:1px solid #e4e9f1;padding-top:20px;margin:25px 0 0}footer{text-align:center;font-size:10px;color:#8490a5;line-height:1.9;margin-top:24px}button:focus-visible{outline:3px solid #b08b49;outline-offset:3px}@media(max-width:480px){.login-card{padding:27px 23px}h1{font-size:24px}}
'''

LOGIN_JS = r'''
"use strict";
(() => {
  const form=document.querySelector('#login-form'), password=document.querySelector('#password');
  const button=document.querySelector('#submit'), message=document.querySelector('#message');
  const show=(text,error=false)=>{message.textContent=text;message.className='message'+(error?' error':'');};
  const errors={invalid_credentials:'Incorrect password. Try again.',not_configured:'Research access is not configured. Contact the administrator.',https_required:'Use the HTTPS address supplied by the administrator.'};
  document.querySelector('#reveal').onclick=()=>{const visible=password.type==='password';password.type=visible?'text':'password';const control=document.querySelector('#reveal');control.textContent=visible?'Hide':'Show';control.setAttribute('aria-pressed',String(visible));};
  fetch('/api/auth',{credentials:'same-origin',cache:'no-store'}).then(async response=>{
    const result=await response.json();
    if(response.ok&&result.authenticated){location.replace('/');return;}
    show(response.ok?'':errors[result.error]||'Research access is temporarily unavailable. Try again later.',!response.ok);
  }).catch(()=>show('Research access is temporarily unavailable. Try again later.',true));
  form.addEventListener('submit',async event=>{
    event.preventDefault();if(button.disabled)return;button.disabled=true;show('Checking credentials…');
    try{
      const response=await fetch('/api/auth',{method:'POST',credentials:'same-origin',cache:'no-store',headers:{'Content-Type':'application/json'},body:JSON.stringify({action:'login',password:password.value})});
      password.value='';const result=await response.json();
      if(response.ok&&result.authenticated){show('Signed in. Opening dashboard…');location.replace('/');return;}
      show(errors[result.error]||'Sign-in could not be completed. Try again later.',true);
    }catch{password.value='';show('Research access is temporarily unavailable. Try again later.',true);}
    button.disabled=false;password.focus();
  });
})();
'''

ACCESS_JS = r'''
"use strict";
(() => {
  if(!['http:','https:'].includes(location.protocol))return;
  const button=document.querySelector('#sign-out');if(!button)return;button.hidden=false;
  function leave(){document.querySelector('#content')?.replaceChildren();delete window.STUDY2_SNAPSHOT;delete window.STUDY2_SCOPE_EXPORT;location.replace('/login.html');}
  async function check(){try{const response=await fetch('/api/auth',{credentials:'same-origin',cache:'no-store'});const state=await response.json();if(!response.ok||!state.authenticated)leave();}catch{/* An offline page already received by an authorised browser is not a new grant. */}}
  button.onclick=async()=>{
    button.disabled=true;
    try{const response=await fetch('/api/auth',{method:'POST',credentials:'same-origin',cache:'no-store',headers:{'Content-Type':'application/json'},body:JSON.stringify({action:'logout'})});if(response.ok){leave();return;}}catch{}
    button.disabled=false;button.textContent='Sign-out failed. Try again.';
  };
  window.addEventListener('pageshow',event=>{if(event.persisted){document.body.hidden=true;location.reload();}});
  document.addEventListener('visibilitychange',()=>{if(!document.hidden)check();});
  setInterval(check,60000);check();
})();
'''

BUILD_JS = r'''
import { copyFileSync, existsSync, lstatSync, mkdirSync, readdirSync, readFileSync } from 'node:fs';
import { createHash } from 'node:crypto';
import { resolve, join } from 'node:path';
const files=__PUBLIC_FILES__;
const root=import.meta.dirname, output=join(root,'public');
if(existsSync(output)&&(lstatSync(output).isSymbolicLink()||!lstatSync(output).isDirectory()))throw new Error('Unsafe public output');
if(existsSync(output)&&readdirSync(output).some(name=>!files.includes(name)))throw new Error('Unexpected files in public output');
const manifest=JSON.parse(readFileSync(join(root,'snapshot-manifest.json'),'utf8'));
for(const [name,expected]of Object.entries(manifest.files)){
  if(['.vercelignore','preview.mjs','DEPLOYMENT.md'].includes(name))continue;
  const path=resolve(root,name);if(!path.startsWith(root+'/')||!lstatSync(path).isFile()||lstatSync(path).isSymbolicLink())throw new Error('Invalid deployment input');
  let input=readFileSync(path);
  // Vercel compacts this file and adds project metadata before running the build.
  if(name==='vercel.json'&&process.env.VERCEL==='1'){
    const config=JSON.parse(input);if(config.version===2)delete config.version;if(typeof config.name==='string')delete config.name;
    input=Buffer.from(JSON.stringify(config,null,2));
  }
  if(createHash('sha256').update(input).digest('hex')!==expected)throw new Error('Deployment input fingerprint changed: '+name);
}
mkdirSync(output,{recursive:true});
for(const name of files){const source=join(root,name),target=join(output,name);if(lstatSync(source).isSymbolicLink()||existsSync(target)&&lstatSync(target).isSymbolicLink())throw new Error('Unsafe public asset');copyFileSync(source,target);}
console.log('Prepared '+files.length+' allowlisted public assets. Access credentials remain runtime-only.');
'''.replace('__PUBLIC_FILES__', json.dumps(PUBLIC_FILES))

PREVIEW_JS = r'''
// Loopback-only preview of the SAME gate/API. It is not a production host.
import { createServer } from 'node:http';
import { readFile } from 'node:fs/promises';
import { resolve } from 'node:path';
import { Readable } from 'node:stream';
import { gate, handleAuth, PRIVATE_HEADERS } from './server/access-core.js';
const files=__PUBLIC_FILES__, root=import.meta.dirname;
const env={...process.env,STUDY2_LOCAL_PREVIEW:'1'};
const server=createServer(async(req,res)=>{
  try{
    const url=new URL(req.url,'http://'+req.headers.host);
    const init={method:req.method,headers:req.headers};
    if(!['GET','HEAD'].includes(req.method)){init.body=Readable.toWeb(req);init.duplex='half';}
    const request=new Request(url,init);
    let response=gate(request,env);
    if(!response&&url.pathname==='/api/auth')response=await handleAuth(request,env);
    if(!response){const name=url.pathname==='/'?'index.html':url.pathname.slice(1);response=files.includes(name)?new Response(await readFile(resolve(root,name)),{headers:{...PRIVATE_HEADERS,'Content-Type':name.endsWith('.js')?'text/javascript; charset=utf-8':name.endsWith('.css')?'text/css; charset=utf-8':name.endsWith('.json')?'application/json':'text/html; charset=utf-8'}}):new Response('Not found',{status:404});}
    res.writeHead(response.status,Object.fromEntries(response.headers));res.end(req.method==='HEAD'?undefined:Buffer.from(await response.arrayBuffer()));
  }catch{res.writeHead(500,PRIVATE_HEADERS);res.end('Preview unavailable');}
});
server.listen(Number(process.env.PORT)||8766,'127.0.0.1',()=>console.log('Local preview: http://127.0.0.1:'+server.address().port));
'''.replace('__PUBLIC_FILES__', json.dumps(PUBLIC_FILES))

PACKAGE = json.dumps(dict(name='study2-protected-dashboard',version='1.0.0',private=True,
    type='module',engines=dict(node='24.x'),scripts=dict(build='node build.mjs',preview='node preview.mjs'),
    dependencies={'@vercel/functions':'3.10.1'}), indent=2) + '\n'

ACCESS_FILES = {'server/access-core.js':ACCESS_CORE,'middleware.js':MIDDLEWARE,
                'api/auth.js':AUTH_API,'login.html':LOGIN_HTML,'login.css':LOGIN_CSS,
                'login.js':LOGIN_JS,'access.js':ACCESS_JS,'build.mjs':BUILD_JS,
                'preview.mjs':PREVIEW_JS,'package.json':PACKAGE}

DEPLOYMENT_GUIDE = r'''# Study 2：登入設定及 Vercel 部署

這份版本加入研究團隊共用密碼。頁面、JavaScript、JSON 及彙總快照均經伺服器登入檢查。未登入時不會傳送研究資料；密碼沒有預設值，也不會寫入瀏覽器程式。

## 1. 準備部署資料夾

使用最新的 `study2-static-dashboard.zip` 解壓，或在 pipeline_v3 內執行：

```sh
./.venv/bin/python -m study2 static-export
cd static_dashboard
```

只部署這個匯出資料夾。不要在研究專案根目錄執行部署，也不要把 SQLite、原始問卷、releases 或審核包加入部署。

資料夾應包括 `package.json`、`package-lock.json`、`middleware.js`、`api/auth.js`、`server/access-core.js`、`vercel.json` 及 `snapshot.js`。不能只上載 `index.html`，也不能只部署 build 後的 public 子資料夾，否則缺少伺服器登入層。

Node.js 建議使用 24 LTS。Vercel 會在遠端安裝已鎖定的登入依賴；不需要 Python。

## 2. 登入 Vercel 並連結專案

在上述匯出資料夾內執行：

```sh
npx vercel login
npx vercel link
```

選擇你有權使用的 Vercel 帳戶／team。新部署建立一個 Study 2 專案；已有對應專案則選它。程式碼目錄選目前的 `./`。

設定由 vercel.json 提供：

| 項目 | 設定 |
| --- | --- |
| Framework | Other |
| Node.js | 24.x |
| Install Command | npm ci --ignore-scripts |
| Build Command | npm run build |
| Output Directory | public |

這仍是預先計算資料的 Dashboard，但現在需要 Vercel 的 Routing Middleware 和一個登入 Function。一般純靜態 HTTP 主機不會執行登入檢查。

## 3. 設定兩個伺服器環境變數

在 Vercel 專案 → Settings → Environment Variables，新增下列兩項。兩項均勾選 **Production 及 Preview**，以 Secret／Sensitive 類型保存；不要使用 NEXT_PUBLIC_ 等公開前綴。

| 名稱 | 填寫內容 |
| --- | --- |
| STUDY2_ACCESS_PASSWORD | 你另行選擇的研究團隊密碼，12–256 字元，建議至少 16 字元。登入頁不會預先填入密碼。 |
| STUDY2_SESSION_SECRET | 至少 32 字元的隨機簽署金鑰，只供伺服器使用，不要當成同事登入密碼。 |

可在自己的終端產生簽署金鑰，再貼到 Vercel 後台：

```sh
openssl rand -hex 32
```

不要把密碼或金鑰寫入任何 HTML、JavaScript、vercel.json、ZIP 或 Git。不要沿用其他研究網站的密碼。若缺少環境變數或長度不符，研究資料會拒絕存取；登入頁會提示入口尚未啟用。

亦可用 CLI 的隱藏輸入：

```sh
npx vercel env add STUDY2_ACCESS_PASSWORD production
npx vercel env add STUDY2_SESSION_SECRET production
npx vercel env add STUDY2_ACCESS_PASSWORD preview
npx vercel env add STUDY2_SESSION_SECRET preview
```

不要把實際值直接放在命令參數或 URL。官方參考：[環境變數 CLI](https://vercel.com/docs/cli/env)。

## 4. 先部署 Preview

```sh
npx vercel
```

開啟命令回傳的 Preview 網址。若先出現 Vercel 帳戶登入，通過後仍應看到 Study 2 自己的登入頁。

用全新的私密視窗驗收：

1. 首頁先顯示 Study 2 研究登入，沒有樣本數或圖表。
2. 錯誤密碼不能開啟 Dashboard；正確密碼可讀取本版資料。
3. 在另一個未登入的私密視窗直接開啟 `/snapshot.js`、`/snapshot-manifest.json`、`/index.html`，不能取得研究內容；瀏覽器可能轉到登入頁。
4. 登出後重新開啟首頁及資料網址，仍須登入。
5. 核對首頁發布版本與本機匯出相同。

可另外從未帶 Cookie 的終端檢查：

```sh
curl -I https://YOUR-PREVIEW-DOMAIN/snapshot.js
```

正常已設定的入口應回傳 401。503 表示入口設定尚未完成；200 並帶有資料則表示登入層未正確部署，先不要發放網址。

## 5. 部署正式版

Preview 通過後，在同一資料夾執行：

```sh
npx vercel --prod
```

使用命令回傳的正式網址。以新的私密視窗重做上一節的登入、直接資料網址及登出檢查。只向已授權同事發放網址及共用密碼。

本輪程式開發與本機測試不等於已驗證 Vercel 的正式路由；正式部署後的直接資料網址檢查必須通過。

## 6. 日後更新

本機 pipeline 已發布新版本後，執行 Export Static Dashboard.command，或：

```sh
./.venv/bin/python -m study2 static-export
cd static_dashboard
npx vercel --prod
```

從 pipeline_v3 開始執行上述指令。重新匯出會保留 `.vercel` 的專案連結，登入設定由 Vercel 保管。每次更新後核對發布版本，並確認未登入仍不能直接讀取 snapshot.js。

## 7. 密碼、登入狀態及舊部署

- 登入狀態有效 8 小時，Cookie 使用 HttpOnly、Secure、SameSite=Strict，並綁定網址。
- 這是團隊共用密碼，沒有每人帳戶、角色或個別撤銷權限。登出會清除目前瀏覽器的 Cookie。
- 更換密碼或簽署金鑰後，重新部署目前正式版本，舊 Cookie 就不能用於新版。
- 更換環境變數不會改寫舊部署的環境。若曾上載無登入保護的版本，或需要撤銷舊密碼，請在 Vercel 停用／刪除相關舊部署，或另以平台保護限制它們。
- 可在 Vercel Firewall 對 POST /api/auth 設定登入嘗試的速率限制。程式內的錯誤延遲不是分散式防暴力嘗試機制。
- 已授權使用者可下載彙總資料；登入功能不會撤回已下載的副本。

本機直接開啟 index.html 只供研究負責人檢視自己的匯出，並不代表公開 HTTP 主機已有保護。部署必須保留 middleware.js 與 api/auth.js。

技術依據：[Routing Middleware](https://vercel.com/docs/routing-middleware/getting-started)、[Node.js Functions](https://vercel.com/docs/functions/runtimes/node-js)、[Vercel 部署 CLI](https://vercel.com/docs/cli/deploy)。
'''
ACCESS_FILES['DEPLOYMENT.md'] = DEPLOYMENT_GUIDE

PACKAGE_LOCK = r'''{
  "name": "study2-protected-dashboard",
  "version": "1.0.0",
  "lockfileVersion": 3,
  "requires": true,
  "packages": {
    "": {
      "name": "study2-protected-dashboard",
      "version": "1.0.0",
      "dependencies": {
        "@vercel/functions": "3.10.1"
      },
      "engines": {
        "node": "24.x"
      }
    },
    "node_modules/@vercel/cli-config": {
      "version": "0.3.1",
      "resolved": "https://registry.npmjs.org/@vercel/cli-config/-/cli-config-0.3.1.tgz",
      "integrity": "sha512-sISbygqlFXYb8qfPu/+2Cf/A8IjrlAuZePdag3EDQr2PRA455s7UZtl9Ro674CWsB/saBRmz3jEkw0YsQs8OoQ==",
      "license": "Apache-2.0",
      "dependencies": {
        "xdg-app-paths": "5",
        "zod": "4.1.11"
      }
    },
    "node_modules/@vercel/cli-exec": {
      "version": "1.0.1",
      "resolved": "https://registry.npmjs.org/@vercel/cli-exec/-/cli-exec-1.0.1.tgz",
      "integrity": "sha512-g9XerViJ/paZujufXYcu5XYI2vU2rtB4sgdpjUHde5RnOkdmpu0ngH46LCFGHoPXO/C+qDPSczIHIRN+8Q2YKQ==",
      "license": "Apache-2.0",
      "dependencies": {
        "execa": "5.1.1"
      },
      "engines": {
        "node": ">= 18"
      }
    },
    "node_modules/@vercel/functions": {
      "version": "3.10.1",
      "resolved": "https://registry.npmjs.org/@vercel/functions/-/functions-3.10.1.tgz",
      "integrity": "sha512-Ca7peSyID6CW5a9Pyu6rDK2AC3n9hyJD0aTBuO74x9eL50Z+rgXIR0H0umI6j0gb9NMG7jvrx7DUhMGuuOFxsg==",
      "license": "Apache-2.0",
      "dependencies": {
        "@vercel/oidc": "4.0.1"
      },
      "engines": {
        "node": ">= 20"
      },
      "peerDependencies": {
        "@aws-sdk/credential-provider-web-identity": "*",
        "ws": ">=8"
      },
      "peerDependenciesMeta": {
        "@aws-sdk/credential-provider-web-identity": {
          "optional": true
        },
        "ws": {
          "optional": true
        }
      }
    },
    "node_modules/@vercel/oidc": {
      "version": "4.0.1",
      "resolved": "https://registry.npmjs.org/@vercel/oidc/-/oidc-4.0.1.tgz",
      "integrity": "sha512-l//xMmDTj2WR6EMtfA2BEF2oR7ViKCD1SCxqFKCn1/8wOZBxgxhxkegSGi90ICTc1rB50ZbKuPIslc8aJxAqew==",
      "license": "Apache-2.0",
      "dependencies": {
        "@vercel/cli-config": "0.3.1",
        "@vercel/cli-exec": "1.0.1",
        "jose": "^5.9.6"
      },
      "engines": {
        "node": ">= 20"
      }
    },
    "node_modules/cross-spawn": {
      "version": "7.0.6",
      "resolved": "https://registry.npmjs.org/cross-spawn/-/cross-spawn-7.0.6.tgz",
      "integrity": "sha512-uV2QOWP2nWzsy2aMp8aRibhi9dlzF5Hgh5SHaB9OiTGEyDTiJJyx0uy51QXdyWbtAHNua4XJzUKca3OzKUd3vA==",
      "license": "MIT",
      "dependencies": {
        "path-key": "^3.1.0",
        "shebang-command": "^2.0.0",
        "which": "^2.0.1"
      },
      "engines": {
        "node": ">= 8"
      }
    },
    "node_modules/execa": {
      "version": "5.1.1",
      "resolved": "https://registry.npmjs.org/execa/-/execa-5.1.1.tgz",
      "integrity": "sha512-8uSpZZocAZRBAPIEINJj3Lo9HyGitllczc27Eh5YYojjMFMn8yHMDMaUHE2Jqfq05D/wucwI4JGURyXt1vchyg==",
      "license": "MIT",
      "dependencies": {
        "cross-spawn": "^7.0.3",
        "get-stream": "^6.0.0",
        "human-signals": "^2.1.0",
        "is-stream": "^2.0.0",
        "merge-stream": "^2.0.0",
        "npm-run-path": "^4.0.1",
        "onetime": "^5.1.2",
        "signal-exit": "^3.0.3",
        "strip-final-newline": "^2.0.0"
      },
      "engines": {
        "node": ">=10"
      },
      "funding": {
        "url": "https://github.com/sindresorhus/execa?sponsor=1"
      }
    },
    "node_modules/get-stream": {
      "version": "6.0.1",
      "resolved": "https://registry.npmjs.org/get-stream/-/get-stream-6.0.1.tgz",
      "integrity": "sha512-ts6Wi+2j3jQjqi70w5AlN8DFnkSwC+MqmxEzdEALB2qXZYV3X/b1CTfgPLGJNMeAWxdPfU8FO1ms3NUfaHCPYg==",
      "license": "MIT",
      "engines": {
        "node": ">=10"
      },
      "funding": {
        "url": "https://github.com/sponsors/sindresorhus"
      }
    },
    "node_modules/human-signals": {
      "version": "2.1.0",
      "resolved": "https://registry.npmjs.org/human-signals/-/human-signals-2.1.0.tgz",
      "integrity": "sha512-B4FFZ6q/T2jhhksgkbEW3HBvWIfDW85snkQgawt07S7J5QXTk6BkNV+0yAeZrM5QpMAdYlocGoljn0sJ/WQkFw==",
      "license": "Apache-2.0",
      "engines": {
        "node": ">=10.17.0"
      }
    },
    "node_modules/is-stream": {
      "version": "2.0.1",
      "resolved": "https://registry.npmjs.org/is-stream/-/is-stream-2.0.1.tgz",
      "integrity": "sha512-hFoiJiTl63nn+kstHGBtewWSKnQLpyb155KHheA1l39uvtO9nWIop1p3udqPcUd/xbF1VLMO4n7OI6p7RbngDg==",
      "license": "MIT",
      "engines": {
        "node": ">=8"
      },
      "funding": {
        "url": "https://github.com/sponsors/sindresorhus"
      }
    },
    "node_modules/isexe": {
      "version": "2.0.0",
      "resolved": "https://registry.npmjs.org/isexe/-/isexe-2.0.0.tgz",
      "integrity": "sha512-RHxMLp9lnKHGHRng9QFhRCMbYAcVpn69smSGcq3f36xjgVVWThj4qqLbTLlq7Ssj8B+fIQ1EuCEGI2lKsyQeIw==",
      "license": "ISC"
    },
    "node_modules/jose": {
      "version": "5.10.0",
      "resolved": "https://registry.npmjs.org/jose/-/jose-5.10.0.tgz",
      "integrity": "sha512-s+3Al/p9g32Iq+oqXxkW//7jk2Vig6FF1CFqzVXoTUXt2qz89YWbL+OwS17NFYEvxC35n0FKeGO2LGYSxeM2Gg==",
      "license": "MIT",
      "funding": {
        "url": "https://github.com/sponsors/panva"
      }
    },
    "node_modules/merge-stream": {
      "version": "2.0.0",
      "resolved": "https://registry.npmjs.org/merge-stream/-/merge-stream-2.0.0.tgz",
      "integrity": "sha512-abv/qOcuPfk3URPfDzmZU1LKmuw8kT+0nIHvKrKgFrwifol/doWcdA4ZqsWQ8ENrFKkd67Mfpo/LovbIUsbt3w==",
      "license": "MIT"
    },
    "node_modules/mimic-fn": {
      "version": "2.1.0",
      "resolved": "https://registry.npmjs.org/mimic-fn/-/mimic-fn-2.1.0.tgz",
      "integrity": "sha512-OqbOk5oEQeAZ8WXWydlu9HJjz9WVdEIvamMCcXmuqUYjTknH/sqsWvhQ3vgwKFRR1HpjvNBKQ37nbJgYzGqGcg==",
      "license": "MIT",
      "engines": {
        "node": ">=6"
      }
    },
    "node_modules/npm-run-path": {
      "version": "4.0.1",
      "resolved": "https://registry.npmjs.org/npm-run-path/-/npm-run-path-4.0.1.tgz",
      "integrity": "sha512-S48WzZW777zhNIrn7gxOlISNAqi9ZC/uQFnRdbeIHhZhCA6UqpkOT8T1G7BvfdgP4Er8gF4sUbaS0i7QvIfCWw==",
      "license": "MIT",
      "dependencies": {
        "path-key": "^3.0.0"
      },
      "engines": {
        "node": ">=8"
      }
    },
    "node_modules/onetime": {
      "version": "5.1.2",
      "resolved": "https://registry.npmjs.org/onetime/-/onetime-5.1.2.tgz",
      "integrity": "sha512-kbpaSSGJTWdAY5KPVeMOKXSrPtr8C8C7wodJbcsd51jRnmD+GZu8Y0VoU6Dm5Z4vWr0Ig/1NKuWRKf7j5aaYSg==",
      "license": "MIT",
      "dependencies": {
        "mimic-fn": "^2.1.0"
      },
      "engines": {
        "node": ">=6"
      },
      "funding": {
        "url": "https://github.com/sponsors/sindresorhus"
      }
    },
    "node_modules/os-paths": {
      "version": "4.4.0",
      "resolved": "https://registry.npmjs.org/os-paths/-/os-paths-4.4.0.tgz",
      "integrity": "sha512-wrAwOeXp1RRMFfQY8Sy7VaGVmPocaLwSFOYCGKSyo8qmJ+/yaafCl5BCA1IQZWqFSRBrKDYFeR9d/VyQzfH/jg==",
      "license": "MIT",
      "engines": {
        "node": ">= 6.0"
      }
    },
    "node_modules/path-key": {
      "version": "3.1.1",
      "resolved": "https://registry.npmjs.org/path-key/-/path-key-3.1.1.tgz",
      "integrity": "sha512-ojmeN0qd+y0jszEtoY48r0Peq5dwMEkIlCOu6Q5f41lfkswXuKtYrhgoTpLnyIcHm24Uhqx+5Tqm2InSwLhE6Q==",
      "license": "MIT",
      "engines": {
        "node": ">=8"
      }
    },
    "node_modules/shebang-command": {
      "version": "2.0.0",
      "resolved": "https://registry.npmjs.org/shebang-command/-/shebang-command-2.0.0.tgz",
      "integrity": "sha512-kHxr2zZpYtdmrN1qDjrrX/Z1rR1kG8Dx+gkpK1G4eXmvXswmcE1hTWBWYUzlraYw1/yZp6YuDY77YtvbN0dmDA==",
      "license": "MIT",
      "dependencies": {
        "shebang-regex": "^3.0.0"
      },
      "engines": {
        "node": ">=8"
      }
    },
    "node_modules/shebang-regex": {
      "version": "3.0.0",
      "resolved": "https://registry.npmjs.org/shebang-regex/-/shebang-regex-3.0.0.tgz",
      "integrity": "sha512-7++dFhtcx3353uBaq8DDR4NuxBetBzC7ZQOhmTQInHEd6bSrXdiEyzCvG07Z44UYdLShWUyXt5M/yhz8ekcb1A==",
      "license": "MIT",
      "engines": {
        "node": ">=8"
      }
    },
    "node_modules/signal-exit": {
      "version": "3.0.7",
      "resolved": "https://registry.npmjs.org/signal-exit/-/signal-exit-3.0.7.tgz",
      "integrity": "sha512-wnD2ZE+l+SPC/uoS0vXeE9L1+0wuaMqKlfz9AMUo38JsyLSBWSFcHR1Rri62LZc12vLr1gb3jl7iwQhgwpAbGQ==",
      "license": "ISC"
    },
    "node_modules/strip-final-newline": {
      "version": "2.0.0",
      "resolved": "https://registry.npmjs.org/strip-final-newline/-/strip-final-newline-2.0.0.tgz",
      "integrity": "sha512-BrpvfNAE3dcvq7ll3xVumzjKjZQ5tI1sEUIKr3Uoks0XUl45St3FlatVqef9prk4jRDzhW6WZg+3bk93y6pLjA==",
      "license": "MIT",
      "engines": {
        "node": ">=6"
      }
    },
    "node_modules/which": {
      "version": "2.0.2",
      "resolved": "https://registry.npmjs.org/which/-/which-2.0.2.tgz",
      "integrity": "sha512-BLI3Tl1TW3Pvl70l3yq3Y64i+awpwXqsGBYWkkqMtnbXgrMD+yj7rhW0kuEDxzJaYXGjEW5ogapKNMEKNMjibA==",
      "license": "ISC",
      "dependencies": {
        "isexe": "^2.0.0"
      },
      "bin": {
        "node-which": "bin/node-which"
      },
      "engines": {
        "node": ">= 8"
      }
    },
    "node_modules/xdg-app-paths": {
      "version": "5.5.1",
      "resolved": "https://registry.npmjs.org/xdg-app-paths/-/xdg-app-paths-5.5.1.tgz",
      "integrity": "sha512-hI3flOB4PLZIy5prbtTpirobtPE2ZtZ52szO+2mM9Efp6ErM398La+C1lIpNWDfNoQk+6Lsi6nMcCwVB7pxeMQ==",
      "license": "MIT",
      "dependencies": {
        "os-paths": "^4.0.1",
        "xdg-portable": "^7.2.0"
      },
      "engines": {
        "node": ">= 6.0"
      }
    },
    "node_modules/xdg-portable": {
      "version": "7.3.0",
      "resolved": "https://registry.npmjs.org/xdg-portable/-/xdg-portable-7.3.0.tgz",
      "integrity": "sha512-sqMMuL1rc0FmMBOzCpd0yuy9trqF2yTTVe+E9ogwCSWQCdDEtQUwrZPT6AxqtsFGRNxycgncbP/xmOOSPw5ZUw==",
      "license": "MIT",
      "dependencies": {
        "os-paths": "^4.0.1"
      },
      "engines": {
        "node": ">= 6.0"
      }
    },
    "node_modules/zod": {
      "version": "4.1.11",
      "resolved": "https://registry.npmjs.org/zod/-/zod-4.1.11.tgz",
      "integrity": "sha512-WPsqwxITS2tzx1bzhIKsEs19ABD5vmCVa4xBo2tq/SrV4RNZtfws1EnCWQXM6yh8bD08a1idvkB5MZSBiZsjwg==",
      "license": "MIT",
      "funding": {
        "url": "https://github.com/sponsors/colinhacks"
      }
    }
  }
}
'''
ACCESS_FILES['package-lock.json'] = PACKAGE_LOCK
