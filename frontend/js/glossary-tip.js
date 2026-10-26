// 文章內的專有名詞提示：滑鼠移過去、點一下或用鍵盤聚焦，顯示名詞解釋；有文獻庫條目的附連結
// 名詞資料由 build.py 寫在 #gl-data（只含這篇用到的）；內容只用 textContent 放進去
(function () {
  var holder = document.getElementById('gl-data');
  if (!holder) return;
  var data;
  try { data = JSON.parse(holder.textContent); } catch (e) { return; }

  var pop = document.createElement('div');
  pop.className = 'gl-pop';
  pop.id = 'gl-pop';
  pop.setAttribute('role', 'tooltip');
  pop.hidden = true;
  document.body.appendChild(pop);

  var current = null, pinned = false, hideTimer = null;

  function fill(key) {
    var g = data[key];
    pop.textContent = '';
    var t = document.createElement('div'); t.className = 'gl-t'; t.textContent = g.t; pop.appendChild(t);
    if (g.en) { var en = document.createElement('div'); en.className = 'gl-en'; en.textContent = g.en; pop.appendChild(en); }
    if (g.d) { var d = document.createElement('p'); d.className = 'gl-d'; d.textContent = g.d; pop.appendChild(d); }
    if (g.lib) {
      var a = document.createElement('a');
      a.href = '../library.html?term=' + encodeURIComponent(key);
      a.textContent = '在文獻庫看完整解釋';
      pop.appendChild(a);
    }
  }

  function place(el) {
    var r = el.getBoundingClientRect();
    var w = Math.min(320, document.documentElement.clientWidth - 24);
    pop.style.width = w + 'px';
    var left = Math.max(12, Math.min(r.left + window.scrollX, window.scrollX + document.documentElement.clientWidth - w - 12));
    pop.style.left = left + 'px';
    pop.style.top = (r.bottom + window.scrollY + 8) + 'px';
    // 下面放不下就改放上面
    var h = pop.offsetHeight;
    if (r.bottom + 8 + h > window.innerHeight && r.top - 8 - h > 0) pop.style.top = (r.top + window.scrollY - h - 8) + 'px';
  }

  function show(el) {
    clearTimeout(hideTimer);
    var key = el.getAttribute('data-gl');
    if (!data[key]) return;
    if (current && current !== el) current.removeAttribute('aria-describedby');
    current = el;
    fill(key);
    pop.hidden = false;
    place(el);
    el.setAttribute('aria-describedby', 'gl-pop');
  }

  function hide() {
    pop.hidden = true;
    pinned = false;
    if (current) current.removeAttribute('aria-describedby');
    current = null;
  }

  function hideSoon() {
    if (pinned) return;
    clearTimeout(hideTimer);
    hideTimer = setTimeout(hide, 250);   // 留一點時間讓滑鼠移進提示框點連結
  }

  var terms = document.querySelectorAll('.gl[data-gl]');
  for (var i = 0; i < terms.length; i++) {
    var el = terms[i];
    el.addEventListener('mouseenter', function () { if (!pinned) show(this); });
    el.addEventListener('mouseleave', hideSoon);
    el.addEventListener('focus', function () { show(this); });
    el.addEventListener('blur', function () { if (!pinned) hideSoon(); });
    el.addEventListener('click', function (ev) {
      ev.preventDefault();
      if (pinned && current === this) { hide(); return; }
      show(this);
      pinned = true;          // 點過就固定，手機上要點外面才收起來
    });
    el.addEventListener('keydown', function (ev) {
      if (ev.key === 'Enter' || ev.key === ' ') { ev.preventDefault(); show(this); pinned = true; }
    });
  }
  pop.addEventListener('mouseenter', function () { clearTimeout(hideTimer); });
  pop.addEventListener('mouseleave', hideSoon);
  document.addEventListener('click', function (ev) {
    if (pop.hidden) return;
    if (pop.contains(ev.target) || (ev.target.closest && ev.target.closest('.gl'))) return;
    hide();
  });
  document.addEventListener('keydown', function (ev) { if (ev.key === 'Escape' && !pop.hidden) { var c = current; hide(); if (c) c.focus(); } });
  window.addEventListener('resize', function () { if (current && !pop.hidden) place(current); });
})();
