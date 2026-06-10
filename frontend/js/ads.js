/* 貓健康站 廣告位邏輯
 * - Sticky bottom anchor ad 可關（24h localStorage 記住）
 * - body 自動補 padding 避免擋到 footer
 *
 * 上線時 AdSense 載入後會自動填入廣告，不需改動此檔。
 */
(function () {
  const KEY = 'neko_anchor_dismissed_at';
  const TTL_MS = 24 * 3600 * 1000;

  function isDismissed() {
    const t = parseInt(localStorage.getItem(KEY) || '0', 10);
    return t && (Date.now() - t < TTL_MS);
  }

  function dismiss() {
    localStorage.setItem(KEY, String(Date.now()));
    const a = document.querySelector('.site-ad-anchor');
    if (a) a.classList.add('hidden');
    document.body.classList.add('ad-dismissed');
  }

  document.addEventListener('DOMContentLoaded', function () {
    const anchor = document.querySelector('.site-ad-anchor');
    if (!anchor) return;
    if (isDismissed()) {
      anchor.classList.add('hidden');
      document.body.classList.add('ad-dismissed');
      return;
    }
    document.body.classList.add('has-anchor-ad');
    const closeBtn = anchor.querySelector('.ad-close');
    if (closeBtn) closeBtn.addEventListener('click', dismiss);
  });
})();
