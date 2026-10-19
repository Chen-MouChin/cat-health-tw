/* theme.js — 每頁都在 <head> 載入。
   1. 固定淺色主題（已移除夜間模式），清除可能殘留的舊 dark 設定。
   2. 頁首頁尾的行為（樣式在 css/shell.css）：手機選單、手機往下讀時收起頁首、捲動後頁首加陰影、
      桌機滑鼠滾輪的阻尼捲動。結構參考負責人做的實驗室網站。 */

(function () {
  document.documentElement.setAttribute("data-theme", "light");
  try { localStorage.removeItem("neko_theme"); } catch (e) {}
})();

document.addEventListener("DOMContentLoaded", function () {
  // 標題右邊的線條貓：viewBox 裁到圖案實際範圍，高度設成標題區塊的高度，上下緣才會和標題對齊；
  // 最寬不超過整列的 30%，超過時縮小、垂直置中
  var titleRows = [];
  document.querySelectorAll(".title-row").forEach(function (row) {
    var cat = row.querySelector(".title-cat"), text = row.firstElementChild, svg = cat && cat.querySelector("svg");
    if (!svg || text === cat) return;
    try {
      var b = svg.getBBox(), p = 1.2;
      if (!b.width || !b.height) return;
      svg.setAttribute("viewBox", (b.x - p) + " " + (b.y - p) + " " + (b.width + 2 * p) + " " + (b.height + 2 * p));
      titleRows.push({ row: row, cat: cat, text: text, ratio: (b.width + 2 * p) / (b.height + 2 * p) });
    } catch (e) {}
  });
  function fitTitleCats() {
    titleRows.forEach(function (t) {
      var h = t.text.getBoundingClientRect().height, w = h * t.ratio, max = t.row.clientWidth * 0.3;
      if (w > max) { w = max; h = w / t.ratio; }
      t.cat.style.width = w + "px";
      t.cat.style.height = h + "px";
    });
  }
  if (titleRows.length) {
    fitTitleCats();
    if (window.ResizeObserver) {
      var ro = new ResizeObserver(function () { window.requestAnimationFrame(fitTitleCats); });
      titleRows.forEach(function (t) { ro.observe(t.text); });
    } else {
      window.addEventListener("resize", fitTitleCats);
    }
    if (document.fonts && document.fonts.ready) document.fonts.ready.then(fitTitleCats);
  }

  var root = document.documentElement;
  var head = document.querySelector(".site-head");
  var nav = document.getElementById("mainNav");
  var toggle = document.querySelector(".nav-toggle");
  var small = window.matchMedia("(max-width: 879px)");
  var reduce = window.matchMedia("(prefers-reduced-motion: reduce)");

  // 手機選單：點按鈕開關；點連結、點外面、按 Esc、轉成桌機寬度都會收起來
  function setMenu(open) {
    if (!nav || !toggle) return;
    nav.classList.toggle("open", open);
    toggle.setAttribute("aria-expanded", open ? "true" : "false");
    if (open) root.classList.remove("head-hidden");
  }
  if (nav && toggle) {
    toggle.addEventListener("click", function () { setMenu(!nav.classList.contains("open")); });
    nav.addEventListener("click", function (e) { if (e.target.closest("a")) setMenu(false); });
    document.addEventListener("click", function (e) { if (head && !head.contains(e.target)) setMenu(false); });
    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape" && nav.classList.contains("open")) { setMenu(false); toggle.focus(); }
    });
    if (small.addEventListener) small.addEventListener("change", function () { setMenu(false); });
  }

  // 捲動：離開頂端後頁首加陰影；手機往下讀時收起頁首，往上滑、回到頂端、選單開著或頁首有焦點時都顯示
  if (head) {
    var lastY = Math.max(0, window.scrollY), ticking = false;
    var update = function () {
      ticking = false;
      var y = Math.max(0, window.scrollY);   // iOS 回彈時會出現負值
      root.classList.toggle("head-scrolled", y > 4);
      var menuOpen = nav && nav.classList.contains("open");
      if (!small.matches || y <= head.offsetHeight || menuOpen) {
        root.classList.remove("head-hidden"); lastY = y; return;
      }
      if (Math.abs(y - lastY) < 8) return;   // 小抖動不理，累積夠了才動
      root.classList.toggle("head-hidden", y > lastY);
      lastY = y;
    };
    window.addEventListener("scroll", function () {
      if (!ticking) { ticking = true; requestAnimationFrame(update); }
    }, { passive: true });
    head.addEventListener("focusin", function () { root.classList.remove("head-hidden"); });
    update();
  }

  // 桌機滑鼠滾輪的阻尼捲動：每格滾輪移動目標位置，頁面緩緩滑過去再停下。
  // 觸控板和手機本來就有慣性，不處理；Ctrl 縮放、橫向捲動、內層可捲區塊、彈窗開著（背景鎖住）、減少動態設定都照原生。
  var desktop = window.matchMedia("(hover: hover) and (pointer: fine)");
  var EASE = 0.14;   // 每一格 60Hz 畫面走完剩下距離的比例
  var target = window.scrollY, current = target, running = false, last = 0;
  var maxScroll = function () { return document.documentElement.scrollHeight - window.innerHeight; };
  var isMouseWheel = function (e) { return e.deltaMode !== 0 || (e.wheelDeltaY && Math.abs(e.wheelDeltaY) % 120 === 0); };
  var innerScroller = function (e, dy) {
    for (var el = e.target; el && el !== document.body && el !== document.documentElement; el = el.parentElement) {
      if (el.scrollHeight <= el.clientHeight) continue;
      var oy = getComputedStyle(el).overflowY;
      if (oy !== "auto" && oy !== "scroll") continue;
      if (dy < 0 ? el.scrollTop > 0 : el.scrollTop + el.clientHeight < el.scrollHeight - 1) return true;
    }
    return false;
  };
  var step = function (now) {
    var dt = last ? Math.min(64, now - last) : 16.7; last = now;
    current += (target - current) * (1 - Math.pow(1 - EASE, dt / 16.7));
    if (Math.abs(target - current) < 0.5) current = target;
    window.scrollTo({ top: current, behavior: "instant" });
    if (current !== target) requestAnimationFrame(step); else running = false;
  };
  window.addEventListener("wheel", function (e) {
    if (!desktop.matches || reduce.matches || e.ctrlKey || e.metaKey || e.shiftKey || e.defaultPrevented) return;
    if (Math.abs(e.deltaX) > Math.abs(e.deltaY) || !isMouseWheel(e) || innerScroller(e, e.deltaY)) return;
    if (getComputedStyle(document.body).overflow === "hidden") return;
    e.preventDefault();
    if (!running) { target = current = window.scrollY; }
    var dy = e.deltaMode === 1 ? e.deltaY * 40 : e.deltaMode === 2 ? e.deltaY * window.innerHeight : e.deltaY;
    target = Math.max(0, Math.min(maxScroll(), target + dy));
    if (!running) { running = true; last = 0; requestAnimationFrame(step); }
  }, { passive: false });
  // 拖捲軸、按鍵、錨點跳轉會自己移動頁面：停止緩動，跟著走
  ["keydown", "mousedown", "touchstart"].forEach(function (type) {
    window.addEventListener(type, function () { if (running) { target = current = window.scrollY; } }, { passive: true });
  });
});
