// 舊網址的 service worker：審稿程式搬到 /cat-health-tw-workbench/ 了。
// 平板上還裝著舊版的，更新到這一版後把自己移除，再重新載入頁面，讓頁面轉到新網址。
// 快取不在這裡刪：新網址的 service worker 啟用時會清掉舊版本的快取。
self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', (e) => {
  e.waitUntil((async () => {
    await self.registration.unregister();
    for (const c of await self.clients.matchAll({ type: 'window' })) c.navigate(c.url);
  })());
});
