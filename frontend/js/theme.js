/* theme.js — 固定淺色主題（已移除夜間模式）。
   保留此檔以相容各頁的 <script> 引用，並清除可能殘留的舊 dark 設定。 */

(function () {
  document.documentElement.setAttribute("data-theme", "light");
  try { localStorage.removeItem("neko_theme"); } catch (e) {}
})();
