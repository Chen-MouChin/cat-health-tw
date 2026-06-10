# 爬蟲策略規劃文件

調研日期：2026-04-08  
範圍：neko-pedia 商品比價模組

---

## S1 目標網站調研

### 1. 汪喵星球（DogCatStar）

| 項目 | 內容 |
|------|------|
| 正確網址 | https://www.dogcatstar.com |
| 平台 | **WooCommerce**（WordPress）|
| robots.txt 限制 | 禁止 `?product_cat=*`、`?product$`、`?orderby*`、`?add-to-cart=*`（均為 query string，乾淨 URL 不受限）|
| 允許爬取？ | ✅ 乾淨路徑 `/product/slug/`、`/shop/` **允許** |
| 渲染方式 | **SSR（Server-Side Rendered）**— 商品名稱、價格在初始 HTML 中 |
| 需要 JS？ | ❌ 不需要 |
| 推薦工具 | `requests` + `BeautifulSoup4` |
| 爬取難度 | 🟢 低 |
| sitemap | https://www.dogcatstar.com/sitemap_index.xml |
| 注意事項 | WooCommerce 商品 slug 規則穩定，可直接枚舉 sitemap |

---

### 2. 毛孩時代（PetsTimes）

| 項目 | 內容 |
|------|------|
| 正確網址 | https://www.petstimes.com.tw |
| 平台 | **CYBERBIZ**（台灣電商平台）|
| robots.txt 限制 | 僅禁止 `/admin/`、`/user/sign_in`、`/cart`、`/account` |
| 允許爬取？ | ✅ `/collections/`、`/products/` **允許** |
| 渲染方式 | **CSR（Client-Side Rendered）**— 商品資料由 JS 動態載入 |
| 需要 JS？ | ✅ 需要 |
| 推薦工具 | **Playwright**（執行 JS 後抓取）|
| 爬取難度 | 🟡 中 |
| sitemap | https://www.petstimes.com.tw/sitemap.xml |
| 分頁方式 | 每頁 24 筆，非無限滾動（傳統分頁）|

---

### 3. momo 購物網寵物館

| 項目 | 內容 |
|------|------|
| 正確網址 | https://www.momoshop.com.tw |
| 平台 | 自建（JSP / Java 後端）|
| robots.txt 限制 | Googlebot 完全開放；其他 bot 禁止 `/ajax/*`、`/api/*`、`/event/*`、`/order/*`、`/mypage/*` |
| 允許爬取？ | 🟡 商品頁路徑未明文禁止，但 API 端點禁止 |
| 渲染方式 | **CSR**— 商品列表透過 JS + AJAX 載入 |
| 需要 JS？ | ✅ 需要 |
| 推薦工具 | **Playwright** |
| 爬取難度 | 🟠 較高 |
| 注意事項 | robots.txt 禁止 `/api/*`，需用瀏覽器模擬，不可直接打 API |

---

### 4. 蝦皮（Shopee）

| 項目 | 內容 |
|------|------|
| 正確網址 | https://shopee.tw |
| 平台 | 自建（Next.js）|
| robots.txt 限制 | 非 Google bot 設 **1 秒 crawl-delay**；禁止 `/cart/`、`/user/`、`/search?`（部分）|
| 允許爬取？ | 🔴 商品頁面技術上未禁止，但有反爬機制 |
| 渲染方式 | **CSR + 反爬措施**（fingerprinting、行為偵測）|
| 需要 JS？ | ✅ 需要，且有 bot 偵測 |
| 推薦工具 | Playwright + stealth 模式（或放棄）|
| 爬取難度 | 🔴 高，風險大 |
| 注意事項 | 蝦皮有**聯盟行銷 API**，建議改用官方 affiliate link，不爬蟲 |

---

## S2 網站 → 爬蟲類型對照表

| 網站 | 工具 | 方法 | 優先順序 |
|------|------|------|---------|
| 汪喵星球 | `requests` + `BeautifulSoup4` | 直接 HTTP GET → 解析 HTML | **P1（最先）** |
| 毛孩時代 | `Playwright` | 等待 JS 渲染後抓取 DOM | **P2** |
| momo 寵物館 | `Playwright` | 等待商品列表載入 | **P3** |
| 蝦皮 | 不爬蟲 → **Affiliate API** | 使用官方聯盟行銷連結 | — |

---

## S3 禮儀爬蟲規則（Ethics Rules）

### 3.1 必須遵守

```python
# 所有爬蟲共用設定
CRAWL_DELAY_MIN = 2.0   # 請求間最短等待秒數
CRAWL_DELAY_MAX = 5.0   # 請求間最長等待秒數（隨機）
MAX_CONCURRENT = 1      # 不並發，單執行緒
RESPECT_ROBOTS = True   # 所有 Disallow 路徑均不訪問

USER_AGENT = (
    "NekoPedia-PriceBot/1.0 "
    "(+https://chen-mouchin.github.io/cat-health-tw/about; "
    "price comparison bot; "
    "contact: your@email.com)"
)
```

### 3.2 行為準則

| 規則 | 說明 |
|------|------|
| ✅ 遵守 robots.txt | 所有 Disallow 路徑不爬 |
| ✅ 隨機延遲 2–5 秒 | 不超載伺服器 |
| ✅ 標示真實 User-Agent | 說明是比價機器人，附聯絡方式 |
| ✅ 只抓公開頁面 | 不模擬登入、不繞過付費牆 |
| ✅ 每筆資料附 `source_url` | 讓用戶可追溯原始頁面 |
| ✅ 標記 `crawled_at` 時間戳 | 價格過期必須顯示警告 |
| ✅ 給引流連結 | 比價結果必附「前往購買」原平台連結 |
| ❌ 不爬個人資料 | 不抓取用戶評論中的個人資訊 |
| ❌ 不繞過 Cloudflare / 反爬機制 | 遇到阻擋即停止，不用破解工具 |
| ❌ 不爬需登入頁面 | 只抓訪客可見的公開商品資料 |
| ❌ 不並發請求 | 每次只發一個請求 |

### 3.3 台灣法律邊界

| 行為 | 法律風險 |
|------|---------|
| 抓取公開商品名稱 + 價格 | ✅ 低風險（價格非著作權保護標的）|
| 抓取商品圖片並儲存 | ⚠️ 注意著作權，僅做連結不存圖 |
| 繞過 Cloudflare / WAF | 🔴 可能觸刑法第 358–359 條（妨害電腦使用）|
| 抓取用戶評論個人資訊 | 🔴 違反個資法第 19 條 |
| 大量請求導致服務中斷 | 🔴 可能構成 DoS，刑事責任 |

**結論：** 抓取公開商品名稱、價格、規格、URL，標注來源，給引流連結 → 法律風險極低。

---

## S4 流程設計

### 4.1 Pipeline 架構

```
scrapers/
├── base.py              # 共用 BaseSpider（delay、UA、session）
├── dogcatstar.py        # 汪喵星球（requests + BS4）
├── petstimes.py         # 毛孩時代（Playwright）
├── momo_pets.py         # momo 寵物館（Playwright）
└── research/
    └── scraping-strategy.md  # 本文件

data/products/
├── dogcatstar_raw.json       # 原始抓取結果
├── petstimes_raw.json
├── momo_raw.json
└── products.json             # 合併後的標準 schema（build.py 讀取）
```

### 4.2 商品資料 Schema

```json
{
  "id": "dogcatstar-fantasticcat-200g",
  "name": "幻貓無穀主食罐 200g",
  "brand": "汪喵星球",
  "category": "主食罐",
  "species": "cat",
  "weight_g": 200,
  "price": 85,
  "currency": "TWD",
  "source_platform": "dogcatstar",
  "source_url": "https://www.dogcatstar.com/product/fantasticcat/",
  "image_url": "https://cdn-v2.dogcatstar.com/...",
  "in_stock": true,
  "crawled_at": "2026-04-08T10:30:00+08:00",
  "raw_price_text": "NT$85"
}
```

**跨平台比價合併邏輯（build.py）：**
- 以 `brand + name + weight_g` 做模糊匹配
- 同一商品跨平台價格合併為 `price_comparison[]` 陣列
- 前端顯示最低價 + 各平台連結

### 4.3 Checkpoint 機制

```python
# 每爬 10 筆存一次 checkpoint
# 程式中斷可從上次停止點繼續（參考 CardPick 模式）
CHECKPOINT_FILE = "data/products/{site}_checkpoint.json"
```

### 4.4 執行指令（規劃）

```bash
# 單站爬取
python3 scrapers/dogcatstar.py        # 最快，測試用
python3 scrapers/petstimes.py
python3 scrapers/momo_pets.py

# 全站爬取（按順序）
./scrapers/refresh.sh

# 打包前端資料
python3 build.py
```

---

## S5 風險與潛在問題清單（待 S6 測試後更新）

| 問題 | 網站 | 嚴重度 | 對策 |
|------|------|-------|------|
| CSR 需要 Playwright | 毛孩時代、momo | 🟠 中 | 已納入工具選型 |
| 蝦皮反爬強，放棄爬蟲 | 蝦皮 | 🔴 高 → 已迴避 | 改用 affiliate link |
| momo API 禁止，只能走瀏覽器 | momo | 🟡 中 | Playwright 模擬瀏覽 |
| 汪喵星球商品 slug 是否穩定 | 汪喵星球 | 🟢 低 | 從 sitemap 枚舉 |
| 價格含/不含運費、促銷價 | 全站 | 🟠 中 | 只抓頁面顯示價，標注「不含運費」 |
| 網站改版結構變動 | 全站 | 🟡 中 | Selector 模組化，易於更新 |
| 商品圖片著作權 | 全站 | 🟡 中 | 只存 URL，不下載圖片 |
| `crawled_at` 過期超過 7 天 | 全站 | 🟢 低 | 前端顯示警告 |

---

## 下一步（S6）

1. 對汪喵星球爬取 5–10 筆，驗證 selector 正確性
2. 對毛孩時代用 Playwright 爬取 5 筆，確認 JS 等待策略
3. 對 momo 爬取 5 筆，確認頁面結構
4. 記錄所有錯誤 → S7 文件

---

## S5 回顧：規劃缺口與優化（2026-04-08）

### 發現的缺口

| # | 問題 | 嚴重度 | 對策 |
|---|------|-------|------|
| 1 | 汪喵星球 `/product/slug/` 是否真的 SSR 需實測確認 | 🟡 中 | S6 第一個測試 |
| 2 | 毛孩時代 CYBERBIZ 是否有 JSON API 可直接打（省去 Playwright）| 🟠 中 | S6 開 DevTools 觀察 Network tab |
| 3 | momo 貓咪食品分類 URL 未確認 | 🟡 中 | S6 前先查 |
| 4 | Schema 缺 `original_price`（原價）和 `discount_price`（促銷價）| 🟠 中 | 更新 Schema |
| 5 | `base.py` Playwright browser context 共用設計未規劃 | 🟢 低 | 開發時處理 |
| 6 | 蝦皮 affiliate link 格式未研究 | 🟡 中 | 申請後確認 |

### Schema 更新（補加欄位）

```json
{
  "...": "...",
  "price": 85,
  "original_price": 100,
  "discount_price": 85,
  "discount_note": "限時 85 折",
  "price_per_100g": 42.5
}
```

### S6 執行前需先確認

- [ ] 汪喵星球 `/product/fantasticcat/` 用 `curl -A "NekoPedia-Bot"` 確認 HTML 含商品資料
- [ ] 毛孩時代 DevTools → Network → XHR，找 CYBERBIZ 商品 API endpoint
- [ ] momo 貓咪食品分類 URL（搜尋網站確認正確路徑）

---

> 最後更新：2026-04-08（S1–S5 完成，S6–S7 待執行）
