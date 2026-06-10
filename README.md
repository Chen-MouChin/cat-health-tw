# 貓健康站 🐱

台灣最專業的貓健康知識庫。

**定位：** 貓生病了第一個想到的網站 — 有學術引用、有實操細節、沒有業配
**變現：** Google AdSense（廣告位已內建於 `frontend/js/ads.js`）

🔗 **線上版：** https://chen-mouchin.github.io/cat-health-tw/ （未來自訂網域，如 cat-health.tw）

---

## 內容現況

| 模組 | 狀態 |
|------|------|
| 醫療文章 | 58 篇（已逐篇學術驗證 + 修正事實錯誤；上線中）|
| 獸醫院資料 | 1,415 家（六都，政府 open data + Google Maps）|
| 品種圖鑑 | TheCatAPI |
| 引用文獻庫 | `content/references/citations.json`（105 條，ISFM/WSAVA/Cornell/AAFP）|

**引用政策：** 只引 ISFM／WSAVA／ASPCA／VCA／Cornell／PubMed open-access。永不引 Frontiers。

## 架構（plain HTML，無 build step）

```
content/articles/*.md  →  build.py  →  frontend/data.js + frontend/articles/*.html
```

`frontend/` 是發佈根目錄。`build.py` 把 Markdown 文章打包成靜態 HTML 與 `data.js`。

## 開發

```bash
python -m venv .venv && .venv/Scripts/activate   # Windows
pip install -r requirements.txt

python build.py                                  # 重建前端
python -m http.server 8000 --directory frontend  # 預覽 localhost:8000
```

## 部署

推到 `main` → `.github/workflows/deploy.yml` 自動把 `frontend/` 發佈到 GitHub Pages。
（首次需在 repo Settings → Pages → Source 選「GitHub Actions」。）
