// 平板版審稿的 service worker：
// 1. 把審稿程式和 Pyodide 存進快取，第一次開過之後沒有網路也能用
// 2. iframe 裡的網站預覽（…/review/site/…、…/review/manual）轉給頁面裡的 Python 回答
const CACHE = 'cat-review-045b0ca506';
const SCOPE = new URL('./', self.location).pathname;          // /cat-health-tw/review/
const PYODIDE = 'https://cdn.jsdelivr.net/pyodide/v0.26.4/full/';

// 第一次安裝就把審稿程式和 Pyodide 全部存起來：只開過一次、沒有重新整理就離線，也打得開
const APP_FILES = ["./", "index.html", "shim.js", "vendor/vue.global.prod.min.js", "vendor/Markdown-3.7-py3-none-any.whl", "py/server.py", "py/reviews.py", "py/pack.py", "py/web_bridge.py"];
const PYODIDE_CORE = ['pyodide.js', 'pyodide.asm.js', 'pyodide.asm.wasm', 'python_stdlib.zip', 'pyodide-lock.json'];
const PYODIDE_PKGS = ['ssl', 'openssl'];

async function precache() {
  const c = await openCache();
  if (!c) return;
  const jobs = APP_FILES.map((f) => new URL(f, self.location).href).map(async (u) => {
    const res = await fetch(u, { cache: 'no-store' });
    if (res.ok) await c.put(u, res);
  });
  jobs.push(...PYODIDE_CORE.map(async (f) => {
    const u = PYODIDE + f;
    if (await c.match(u)) return;
    const res = await fetch(u, { mode: 'cors' });
    if (res.ok) await c.put(u, res);
  }));
  // ssl、openssl 的檔名寫在 pyodide-lock.json 裡
  jobs.push((async () => {
    const lock = await (await fetch(PYODIDE + 'pyodide-lock.json', { mode: 'cors' })).json();
    for (const name of PYODIDE_PKGS) {
      const pkg = lock.packages[name];
      if (!pkg) continue;
      const u = PYODIDE + pkg.file_name;
      if (await c.match(u)) continue;
      const res = await fetch(u, { mode: 'cors' });
      if (res.ok) await c.put(u, res);
    }
  })());
  await Promise.allSettled(jobs);
}

self.addEventListener('install', (e) => { e.waitUntil(precache().catch(() => {})); self.skipWaiting(); });
self.addEventListener('activate', (e) => {
  e.waitUntil((async () => {
    for (const k of await caches.keys()) if (k.startsWith('cat-review-') && k !== CACHE) await caches.delete(k);
    await self.clients.claim();
  })());
});

async function askPage(path, clientId) {
  // 優先問發出請求的頁面；iframe 的導覽請求沒有 clientId，就找審稿程式的主畫面
  const all = await self.clients.matchAll({ type: 'window', includeUncontrolled: false });
  const main = all.find((c) => new URL(c.url).pathname === SCOPE || new URL(c.url).pathname === SCOPE + 'index.html') || all[0];
  if (!main) return new Response('審稿程式沒有開著', { status: 503 });
  const ch = new MessageChannel();
  const reply = new Promise((res) => { ch.port1.onmessage = (ev) => res(ev.data); });
  main.postMessage({ type: 'tb-site', path }, [ch.port2]);
  const r = await reply;
  return new Response(r.body, { status: r.status, headers: r.headers });
}

// 快取打不開（瀏覽器空間不足、私密瀏覽等）時照常走網路，只是沒有離線功能
async function openCache() {
  try { return await caches.open(CACHE); } catch (e) { return null; }
}

async function cached(req) {
  const c = await openCache();
  if (!c) return fetch(req);
  const hit = await c.match(req.url);
  if (hit) return hit;
  const res = await fetch(req);
  if (res.ok) c.put(req.url, res.clone());
  return res;
}

async function appFile(req) {
  // 審稿程式本身：有網路就拿新的（順便更新快取），沒網路用快取
  // 原樣轉送請求（頁面導覽的 Request 不能帶選項重送）；快取用不含查詢字串的網址當 key
  const c = await openCache();
  const key = new URL(req.url); key.search = '';
  try {
    const res = await fetch(req);
    if (c && res.ok && res.type === 'basic') await c.put(key.href, res.clone());
    return res;
  } catch (e) {
    const hit = c && await c.match(key.href);
    if (hit) return hit;
    return new Response('沒有網路，而且這個檔案還沒存進平板', { status: 503, headers: { 'Content-Type': 'text/plain; charset=utf-8' } });
  }
}

self.addEventListener('fetch', (e) => {
  const url = new URL(e.request.url);
  if (url.href.startsWith(PYODIDE)) { e.respondWith(cached(e.request)); return; }
  if (url.origin !== self.location.origin || !url.pathname.startsWith(SCOPE)) return;
  const rest = url.pathname.slice(SCOPE.length);
  if (rest.startsWith('site/') || rest === 'site' || rest === 'manual') {
    e.respondWith(askPage('/' + rest + url.search, e.clientId));
    return;
  }
  if (e.request.method === 'GET') e.respondWith(appFile(e.request).catch((err) => new Response('service worker 錯誤：' + (err && err.stack || err), { status: 500, headers: { 'Content-Type': 'text/plain; charset=utf-8' } })));
});
