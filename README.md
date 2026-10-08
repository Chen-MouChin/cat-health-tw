# 貓健康站 🐱

台灣最專業的貓健康知識庫。

**定位：** 貓生病了第一個想到的網站 — 有學術引用、有實操細節、沒有業配
**變現：** Google AdSense（廣告位已內建於 `frontend/js/ads.js`）

🔗 **線上版：** https://chen-mouchin.github.io/cat-health-tw/ （未來自訂網域，如 cat-health.tw）

---

## 內容現況

| 模組 | 狀態（2026-09-06） |
|------|------|
| 醫療文章 | 56 篇，全部仍為 draft 待人工審核；10 篇已依寫作規範深度改寫，數字帶句內註腳 |
| 獸醫院資料 | 2,001 家（22 縣市，政府 open data，100% 有座標，可篩 24h 急診）|
| 品種圖鑑 | 68 種，TheCatAPI |
| 引用文獻庫 | `content/references/citations.json`（109 筆，14 筆 approved）|
| 編輯方針 | `frontend/editorial.html`，公開 AI 起草加人工審核的分工 |

文件：[交接](docs/HANDOVER.md) · [進度](docs/PROGRESS.md) · [路線圖](docs/ROADMAP.md)

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
python scripts/lint_articles.py                  # 寫作規範檢查
python workbench/server.py                       # 審核工作檯 127.0.0.1:8010
```

## 部署

推到 `main` → `.github/workflows/deploy.yml` 自動把 `frontend/` 發佈到 GitHub Pages。
（首次需在 repo Settings → Pages → Source 選「GitHub Actions」。）
