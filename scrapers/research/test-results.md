# 爬蟲測試結果記錄（S6–S7）

測試日期：2026-04-08

---

## 汪喵星球（dogcatstar.com）— ✅ 成功

| 項目 | 結果 |
|------|------|
| 工具 | `requests` + `BeautifulSoup4` |
| 成功筆數 | 10/10 |
| 測試檔 | `data/products/dogcatstar_test.json` |

### 發現問題與修正

| # | 問題 | 修正方式 |
|---|------|---------|
| 1 | `h1.product_title`（底線）找不到元素 | 改為 `h1.product-title`（連字號）|
| 2 | 圖片 `src` 為 base64 佔位符（lazy load）| 改取 `data-src` 或 `og:image` meta tag |
| 3 | sitemap 含海外版 `_sgmy`, `/hk/`, `/sg/` 商品 | 過濾含這些字串的 URL，台灣版 99 件 |
| 4 | 部分商品為「加購品」非獨立販售商品 | slug 含 `add_` 前綴，後續可選擇性過濾 |

### 正確 Selector 總結

```python
name   = soup.find("h1", class_="product-title").get_text(strip=True)
price  = soup.select_one("p.price ins .woocommerce-Price-amount bdi")  # 促銷價
orig   = soup.select_one("p.price del .woocommerce-Price-amount bdi")  # 原價
plain  = soup.select_one("p.price .woocommerce-Price-amount bdi")      # 無促銷時
image  = soup.find("meta", property="og:image").get("content")
```

---

## 毛孩時代（petstimes.com.tw）— ✅ 成功（比預期更好）

| 項目 | 結果 |
|------|------|
| 工具 | 直接打 JSON API（**不需要 Playwright**）|
| 成功筆數 | 10/10 |
| 測試檔 | `data/products/petstimes_test.json` |

### 關鍵發現

**CYBERBIZ 平台有 Shopify 風格的 JSON API：**

```
GET /collections/{handle}/products.json?limit=N
```

回傳完整商品資料，包含：`title`, `price`, `compare_at_price`, `variants[]`, `sku`, `inventory_quantity`, `photo`, `url`, `total_sold`

→ **不需要 Playwright，直接 requests 即可，爬取速度和複雜度大幅降低。**

### 注意事項

| # | 注意事項 |
|---|---------|
| 1 | `inventory_quantity=0` 不等於缺貨，需看 `inventory_policy`（`deny` = 無庫存不販售）|
| 2 | 圖片 URL 為相對路徑（`/media/...`），需補上 base URL |
| 3 | `compare_at_price` 全部商品都有設定（作為對比價），要確認是否為真實原價 |
| 4 | 分頁：`?limit=24&page=2`（CYBERBIZ 標準），可枚舉所有頁面 |

---

## momo 購物網（momoshop.com.tw）— ✅ 成功

| 項目 | 結果 |
|------|------|
| 工具 | Playwright（headless Chromium）|
| 成功筆數 | 8/8 |
| 測試檔 | `data/products/momo_test.json` |

### 正確分類 URL

| 分類 | l_code | URL |
|------|--------|-----|
| 貓飼料/乾糧 | 4700300000 | `...LgrpCategory.jsp?l_code=4700300000&ctype=B` |
| 貓罐頭/鮮食 | 4701000000 | `...LgrpCategory.jsp?l_code=4701000000&ctype=B` |
| 貓砂/便盆 | 4700100000 | `...LgrpCategory.jsp?l_code=4700100000&ctype=B` |
| 寵物零食/保健 | 4700500000 | `...LgrpCategory.jsp?l_code=4700500000&ctype=B` |

### 正確 Selector

```python
names  = page.query_selector_all(".prdName")
prices = page.query_selector_all("[class*='Price']")
links  = page.query_selector_all("a[href*='GoodsDetail']")
# links[0] 通常為空連結，從 links[1] 開始對應 names[0]
```

### 發現問題

| # | 問題 | 說明 |
|---|------|------|
| 1 | 初始 l_code（2900000000）為錯誤分類（非寵物）| 已找到正確貓咪食品 l_code |
| 2 | `.goodsItem` selector 未找到元素 | 改用 `.prdName` + `[class*='Price']` |
| 3 | 第一個商品連結為空（廣告位）| links 需從 index 1 開始對應 names |
| 4 | 商品名稱含廣告文字（「使用新鮮&生鮮食材」等）| 擷取後需清理 |
| 5 | `networkidle` 等待時間長（需額外 sleep(4)）| 正式爬蟲需妥善處理等待策略 |
| 6 | 無法直接攔截到 JSON 商品 API（ajaxTool 回傳格式需研究）| DOM 抓取較可靠 |

---

## 蝦皮（shopee.tw）— ⬜ 跳過

**決策：不爬蟲，改用官方 affiliate link。**

理由：
1. 反爬機制強（fingerprinting、行為偵測）
2. 有官方聯盟行銷計畫，可得到 affiliate link，符合倫理且合法
3. 爬蟲複雜度高，ROI 低

---

## 方法學修正（回到 S1 循環）

根據測試結果，更新工具對照表：

| 網站 | 原規劃 | 修正後 |
|------|-------|-------|
| 汪喵星球 | requests + BS4 | requests + BS4 ✅（selector 修正）|
| 毛孩時代 | Playwright（預期 CSR）| **requests + JSON API** ✅（比預期簡單）|
| momo | Playwright | Playwright ✅（selector 修正）|
| 蝦皮 | 不爬 | 不爬（維持）|

### 下一步優化重點

1. **汪喵星球**：過濾 `add_` 前綴的加購品、確認商品分類欄位（貓/狗）
2. **毛孩時代**：枚舉所有分頁、驗證 `compare_at_price` 是否為真實原價
3. **momo**：清理商品名稱廣告文字、確認 25 筆商品中無重複
4. **跨平台比價匹配**：三站抓到同一品牌不同平台，如何正規化比對（brand + name 模糊匹配）
