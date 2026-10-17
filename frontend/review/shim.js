// 平板版審稿：把工作檯畫面送出的 /api/* 請求，改由瀏覽器裡的 Python（Pyodide）跑 workbench/server.py 回答。
// 文章與審稿紀錄只存在這台平板的瀏覽器（IndexedDB），不會上傳到任何伺服器。
(function () {
  'use strict';
  var PYODIDE_URL = 'https://cdn.jsdelivr.net/pyodide/v0.26.4/full/';
  // IndexedDB 掛在 /data；工作資料夾和安裝時的暫存資料夾（work.new）要在同一個掛載點，才能直接搬檔
  var DATA = '/data', WORK = '/data/work';
  var APP = new URL('.', location.href);           // 審稿程式所在的資料夾（…/review/）
  var realFetch = window.fetch.bind(window);
  var py = null, bridge = null, booted = null, syncing = Promise.resolve();

  // ---------- 開機畫面 ----------
  var css = '#tb-boot{position:fixed;inset:0;z-index:9999;display:flex;align-items:center;justify-content:center;background:#f9f6f0;' +
    'font-family:system-ui,-apple-system,"PingFang TC","Noto Sans TC",sans-serif;color:#1d1d1f}' +
    '#tb-boot .box{max-width:460px;margin:0 20px;text-align:center;line-height:1.7}' +
    '#tb-boot h1{font-size:24px;margin:0 0 8px}#tb-boot p{color:#6e6e73;margin:0 0 14px;font-size:16px}' +
    '#tb-boot label.btn,#tb-dl a{display:inline-block;padding:12px 22px;border-radius:12px;background:#3b6a50;color:#fff;font-weight:700;font-size:17px;cursor:pointer;text-decoration:none}' +
    '#tb-boot .err{color:#b04a3a;white-space:pre-wrap;text-align:left;font-size:13px}' +
    '#tb-dl{position:fixed;inset:0;z-index:9998;display:flex;align-items:center;justify-content:center;background:rgba(0,0,0,.35)}' +
    '#tb-dl .box{background:#fff;border-radius:16px;padding:22px 24px;max-width:420px;margin:0 20px;text-align:center;line-height:1.7;font-family:inherit}' +
    '#tb-dl button{margin-top:12px;font:inherit;border:0;background:none;color:#6e6e73;text-decoration:underline;cursor:pointer}';
  var st = document.createElement('style'); st.textContent = css; document.head.appendChild(st);
  var boot = document.createElement('div'); boot.id = 'tb-boot';
  boot.innerHTML = '<div class="box"><h1>貓健康站 審稿（平板版）</h1><p id="tb-msg">正在準備審稿程式…第一次開大約需要 20 秒，之後沒有網路也能用。</p><div id="tb-act"></div></div>';
  var domReady = new Promise(function (res) {
    if (document.readyState !== 'loading') res(); else document.addEventListener('DOMContentLoaded', res, { once: true });
  });
  // shim.js 在 <head> 執行，這時還沒有 <body>：等頁面建好再放開機畫面
  function showBoot() { domReady.then(function () { if (!boot.isConnected) document.body.appendChild(boot); }); }
  function hideBoot() { boot.remove(); }
  function msg(t) { var m = boot.querySelector('#tb-msg'); if (m) m.textContent = t; }
  showBoot();

  function syncFS() {
    // 寫進 IndexedDB；排隊執行，避免兩次同步重疊
    syncing = syncing.then(function () {
      return new Promise(function (res) { py.FS.syncfs(false, function () { res(); }); });
    });
    return syncing;
  }

  function askPack() {
    return new Promise(function (resolve) {
      msg('請選擇負責人傳給你的審稿包（.zip 檔）。檔案只會存在這台平板上。');
      var act = boot.querySelector('#tb-act');
      act.innerHTML = '<label class="btn">選擇審稿包<input type="file" accept=".zip,application/zip" hidden></label>';
      act.querySelector('input').addEventListener('change', function (e) {
        var f = e.target.files[0];
        if (!f) return;
        act.innerHTML = '';
        msg('正在載入審稿包…');
        f.arrayBuffer().then(function (buf) { resolve(new Uint8Array(buf)); });
      });
    });
  }

  // 第一次開：等 service worker 接手這個頁面（clients.claim，不用重新整理），之後 Pyodide 的下載才會經過它、存進快取
  function swReady() {
    if (!('serviceWorker' in navigator)) return Promise.resolve();
    var reg = navigator.serviceWorker.register(new URL('sw.js', APP).href).catch(function () { /* 不支援就沒有離線功能 */ });
    if (navigator.serviceWorker.controller) return reg;
    return Promise.race([
      new Promise(function (res) { navigator.serviceWorker.addEventListener('controllerchange', res, { once: true }); }),
      new Promise(function (res) { setTimeout(res, 8000); }),
    ]);
  }

  async function loadPyodideScript() {
    for (var i = 0; i < 3; i++) {
      try {
        if (!window.loadPyodide) {
          await new Promise(function (res, rej) {
            var s = document.createElement('script'); s.src = PYODIDE_URL + 'pyodide.js';
            s.onload = res; s.onerror = function () { s.remove(); rej(new Error('下載不到 Pyodide')); };
            document.head.appendChild(s);
          });
        }
        return await window.loadPyodide({ indexURL: PYODIDE_URL });
      } catch (e) {
        if (i === 2) throw new Error('下載不到審稿程式需要的檔案，請確認第一次開啟時有網路。（' + e + '）');
        msg('網路不穩，重新下載中…');
        await new Promise(function (res) { setTimeout(res, 1500 * (i + 1)); });
      }
    }
  }

  async function start() {
    showBoot();
    await domReady;
    await swReady();
    py = await loadPyodideScript();
    msg('正在載入審稿程式…');
    await py.loadPackage(['ssl', new URL('vendor/Markdown-3.7-py3-none-any.whl', APP).href]);
    // 工作檯的 Python 程式
    py.FS.mkdirTree('/app');
    var files = ['server.py', 'reviews.py', 'pack.py', 'web_bridge.py'];
    for (var i = 0; i < files.length; i++) {
      var r = await realFetch(new URL('py/' + files[i], APP));
      py.FS.writeFile('/app/' + files[i], new Uint8Array(await r.arrayBuffer()));
    }
    // 審稿資料存在 IndexedDB，關掉網頁再開還在
    py.FS.mkdirTree(DATA);
    py.FS.mount(py.FS.filesystems.IDBFS, {}, DATA);
    await new Promise(function (res) { py.FS.syncfs(true, function () { res(); }); });
    py.FS.mkdirTree(WORK);
    py.runPython('import sys; sys.path.insert(0, "/app")');
    bridge = py.pyimport('web_bridge');
    if (!bridge.has_pack(WORK)) {
      var zip = await askPack();
      var res = bridge.install(WORK, zip).toJs({ dict_converter: Object.fromEntries });
      if (!res.ok) throw new Error('審稿包裝不進去');
      await syncFS();
    }
    msg('正在打開文章…');
    bridge.start(WORK);
    hideBoot();
  }

  function fail(e) {
    showBoot();
    msg('審稿程式打不開。');
    var act = boot.querySelector('#tb-act');
    act.innerHTML = '<p class="err"></p>';
    act.querySelector('.err').textContent = String(e && e.stack || e);
  }

  function ready() {
    if (!booted) booted = start().catch(function (e) { fail(e); throw e; });
    return booted;
  }

  // 工作檯回的 JSON 裡 "/site/…" 是從網站根目錄算的，平板版要改成相對於審稿程式資料夾
  function fixPaths(text) { return text.replace(/"\/site\//g, '"site/').replace(/"\/manual"/g, '"manual"'); }

  async function call(method, path, headers, body) {
    await ready();
    var bytes = body ? new Uint8Array(body) : new Uint8Array(0);
    var out = bridge.handle(method, path, py.toPy(headers || {}), bytes);
    var res = out.toJs();
    out.destroy();
    var status = res[0], hdrs = res[1], payload = res[2];
    if (method === 'POST') syncFS();
    return { status: status, headers: hdrs, body: payload };
  }

  // ---------- 匯出：把審稿結果交給使用者存到「檔案」或傳出去 ----------
  function offerDownload(name, bytes) {
    var url = URL.createObjectURL(new Blob([bytes], { type: 'application/zip' }));
    var old = document.getElementById('tb-dl'); if (old) old.remove();
    var d = document.createElement('div'); d.id = 'tb-dl';
    d.innerHTML = '<div class="box"><div style="font-weight:700;font-size:18px;margin-bottom:6px">審稿結果準備好了</div>' +
      '<div style="color:#6e6e73;font-size:15px;margin-bottom:14px">按下面的按鈕存到「檔案」，再用 LINE、Email 或 AirDrop 傳給負責人。</div>' +
      '<a download></a><br><button type="button">關閉</button></div>';
    var a = d.querySelector('a'); a.href = url; a.download = name; a.textContent = '下載審稿結果';
    d.querySelector('button').onclick = function () { d.remove(); };
    document.body.appendChild(d);
  }

  window.fetch = async function (input, init) {
    var url = new URL(typeof input === 'string' ? input : input.url, location.href);
    var idx = url.pathname.indexOf('/api/');
    if (url.origin !== location.origin || idx < 0) return realFetch(input, init);
    init = init || {};
    var path = url.pathname.slice(idx) + url.search;
    var method = (init.method || 'GET').toUpperCase();
    var headers = {};
    if (init.headers) new Headers(init.headers).forEach(function (v, k) { headers[k] = v; });
    var body = init.body == null ? null : (typeof init.body === 'string' ? new TextEncoder().encode(init.body) : await new Response(init.body).arrayBuffer());
    try {
      var r = await call(method, path, headers, body);
      var h = new Headers(r.headers);
      var payload = r.body;
      if ((h.get('Content-Type') || '').indexOf('application/json') === 0) {
        var text = fixPaths(new TextDecoder().decode(payload));
        // 匯出的檔案在平板的虛擬資料夾裡，讀出來給使用者下載
        if (path.indexOf('/api/helper/export') === 0 || path.indexOf('/api/helper/open-folder') === 0) {
          try {
            var j = JSON.parse(text);
            var p = j.path || (window.__tbLastExport || '');
            if (j.ok && p) { window.__tbLastExport = p; offerDownload(p.split('/').pop(), py.FS.readFile(p)); }
          } catch (e) { /* 照常回給畫面 */ }
        }
        payload = new TextEncoder().encode(text);
      }
      return new Response(payload, { status: r.status, headers: h });
    } catch (e) {
      return new Response(JSON.stringify({ error: '平板版審稿程式出錯：' + e }), { status: 500, headers: { 'Content-Type': 'application/json' } });
    }
  };

  // ---------- 網站預覽（iframe 裡的 site/…）由 service worker 轉過來 ----------
  if ('serviceWorker' in navigator) {
    navigator.serviceWorker.addEventListener('message', async function (ev) {
      if (!ev.data || ev.data.type !== 'tb-site') return;
      var port = ev.ports[0];
      try {
        var r = await call('GET', ev.data.path, {}, null);
        port.postMessage({ status: r.status, headers: r.headers, body: r.body }, [r.body.buffer]);
      } catch (e) {
        port.postMessage({ status: 500, headers: [['Content-Type', 'text/plain; charset=utf-8']], body: new TextEncoder().encode(String(e)) });
      }
    });
  }
  ready();
})();
