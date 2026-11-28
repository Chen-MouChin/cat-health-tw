/* 合併頁的互動（261128）：常見品種介紹 breeds/、各縣市動物醫院名單 vets/counties.html 共用。
   內容全部在原始碼裡，這支程式只控制怎麼看：
   1. 目錄黏在頁首下面，捲到哪一區就亮哪一個
   2. 頁內搜尋：只留下符合的區塊（比對 data-search）
   3. 右下角「回到目錄」按鈕
   4. 網址跟著區塊走（#slug），打開帶 # 的網址會停在那一區，收起來的區塊會自動展開
   縣市頁另外有：醫院名單的「只看夜間急診／只看貓專科」篩選 */
(function () {
  var nav = document.querySelector('[data-secnav]');
  if (!nav) return;
  var sections = [].slice.call(document.querySelectorAll('[data-sec]'));
  var chips = {};
  [].forEach.call(nav.querySelectorAll('a[href^="#"]'), function (a) { chips[a.getAttribute('href').slice(1)] = a; });
  var header = document.querySelector('.site-head, header');

  // ---- 1. 目錄黏在頁首下面：頁首在手機往下讀會收起來，目錄的位置跟著頁首實際的下緣 ----
  function headBottom() {
    if (!header) return 0;
    var r = header.getBoundingClientRect();
    return Math.max(0, Math.round(r.bottom));
  }
  var sentinel = document.createElement('div');
  nav.parentNode.insertBefore(sentinel, nav);
  function place() {
    var top = headBottom();
    nav.style.top = top + 'px';
    document.documentElement.style.setProperty('--secnav-offset', (top + nav.offsetHeight + 12) + 'px');
    nav.classList.toggle('is-stuck', sentinel.getBoundingClientRect().top < top + 1);
  }

  // ---- 2. 捲到哪一區就亮哪一個，網址跟著改（不跳動、不留歷史紀錄） ----
  var current = '';
  function setCurrent(id) {
    if (id === current) return;
    current = id;
    Object.keys(chips).forEach(function (k) { chips[k].classList.toggle('on', k === id); chips[k].removeAttribute('aria-current'); });
    var c = chips[id];
    if (c) {
      c.setAttribute('aria-current', 'location');
      var list = c.closest('ul');
      if (nav.classList.contains('is-stuck') && list) {   // 黏住時目錄是一排，把亮的那個捲進畫面
        list.scrollLeft = c.offsetLeft - list.clientWidth / 2 + c.offsetWidth / 2;
      }
    }
    try { history.replaceState(null, '', id ? '#' + id : location.pathname + location.search); } catch (e) {}
  }
  function spy() {
    // 手機往下讀時頁首會收起來，基準線至少放在畫面上方三分之一，跳過來的區塊才不會被算成前一區
    var line = Math.max(headBottom() + nav.offsetHeight + 40, window.innerHeight * 0.33);
    var id = '';
    for (var i = 0; i < sections.length; i++) {
      var s = sections[i];
      if (s.hidden) continue;
      if (s.getBoundingClientRect().top <= line) id = s.id; else break;
    }
    setCurrent(id);
    // 目錄黏住後 offsetTop 會跟著變，用它上方不會動的 sentinel 算原本的位置
    toTop.hidden = sentinel.getBoundingClientRect().top > -200;
  }

  // ---- 3. 回到目錄 ----
  var toTop = document.createElement('button');
  toTop.type = 'button';
  toTop.className = 'to-toc';
  toTop.hidden = true;
  toTop.textContent = '回到目錄';
  toTop.addEventListener('click', function () {
    window.scrollTo({ top: Math.max(0, sentinel.getBoundingClientRect().top + window.scrollY - headBottom() - 8), behavior: 'smooth' });
    setCurrent('');
  });
  document.body.appendChild(toTop);

  // ---- 4. 跳到某一區：先打開收起來的 details，再捲過去 ----
  function openUp(el) {
    for (var p = el; p; p = p.parentElement) if (p.tagName === 'DETAILS') p.open = true;
  }
  function go(id, smooth) {
    var el = id && document.getElementById(id);
    if (!el) return false;
    openUp(el);
    var y = el.getBoundingClientRect().top + window.scrollY - (headBottom() + nav.offsetHeight + 12);
    window.scrollTo({ top: Math.max(0, y), behavior: smooth ? 'smooth' : 'auto' });
    return true;
  }
  document.addEventListener('click', function (e) {
    var a = e.target.closest('a[href^="#"]');
    if (!a) return;
    var id = decodeURIComponent(a.getAttribute('href').slice(1));
    if (id === 'top') { e.preventDefault(); toTop.click(); return; }
    if (go(id, true)) { e.preventDefault(); try { history.replaceState(null, '', '#' + id); } catch (err) {} }
  });

  // ---- 頁內搜尋 ----
  var q = nav.querySelector('input[type="search"]');
  var empty = nav.querySelector('.secnav-empty');
  if (q) {
    q.addEventListener('input', function () {
      var t = q.value.trim().toLowerCase();
      var n = 0;
      sections.forEach(function (s) {
        var hit = !t || (s.getAttribute('data-search') || '').toLowerCase().indexOf(t) >= 0;
        s.hidden = !hit;
        if (chips[s.id]) chips[s.id].parentElement.hidden = !hit;
        if (hit) n++;
      });
      if (empty) empty.hidden = n > 0;
      spy();
    });
  }

  // ---- 縣市頁：只看夜間急診／只看貓專科 ----
  [].forEach.call(document.querySelectorAll('[data-vfilter]'), function (box) {
    var on = {};
    var scope = box.closest('[data-sec]') || document;
    box.addEventListener('click', function (e) {
      var b = e.target.closest('button[data-f]');
      if (!b || b.disabled) return;
      var f = b.getAttribute('data-f');
      on[f] = !on[f];
      b.setAttribute('aria-pressed', on[f] ? 'true' : 'false');
      [].forEach.call(scope.querySelectorAll('.vet-list > li'), function (li) {
        li.hidden = (on.er && !li.hasAttribute('data-er')) || (on.cat && !li.hasAttribute('data-cat'));
      });
      // 一家都不剩的行政區，標題和快速跳的按鈕一起藏起來
      [].forEach.call(scope.querySelectorAll('.dist'), function (d) {
        var any = d.querySelector('.vet-list > li:not([hidden])');
        d.hidden = !any;
        var jump = scope.querySelector('.dist-jump a[href="#' + d.id + '"]');
        if (jump) jump.parentElement.hidden = !any;
      });
    });
  });

  var ticking = false;
  window.addEventListener('scroll', function () {
    if (ticking) return;
    ticking = true;
    requestAnimationFrame(function () { place(); spy(); ticking = false; });
  }, { passive: true });
  window.addEventListener('resize', place);
  if (header) header.addEventListener('transitionend', function () { place(); });
  place();
  // 帶 # 進來（含舊單頁轉址過來）：停在那一區
  var h = decodeURIComponent(location.hash.slice(1));
  if (h) setTimeout(function () { go(h, false); spy(); }, 60);
  spy();
})();
