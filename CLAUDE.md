# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 專案概述

**貓健康站（cat-health-tw）** — 台灣貓健康知識庫。Plain HTML 靜態站，無框架、無 npm、無 CI build。

核心價值：有學術引用、有實操細節、沒有業配、不噁心廣告。變現靠 AdSense。

兩條主線：
1. **醫療知識文章**（SEO 長尾流量）— `content/articles/*.md` 經 `build.py` 產出
2. **獸醫院導流** — `frontend/vets.html`，全台獸醫院資料（政府 open data + Google Maps）

已移除／降優先的功能見 `research/archived-features.md`（商品比價已刪；品種圖鑑保留但降優先）。

## 開發指令

```bash
# 一次性
python -m venv .venv && .venv/Scripts/activate      # Windows
pip install -r requirements.txt                     # 只有 markdown；爬蟲另裝 scrapers/requirements.txt

# 工作檯（人工審核用，本機）：文章 r/d/f/x、文獻 approve、重建、commit/push
python workbench/server.py                          # http://127.0.0.1:8010/ ；Vue 3 走 CDN，無 build

# 核心循環：改 content/ 或 build.py → 重建 → 本機預覽
python build.py                                     # 無參數，全量重建（見下方「Build pipeline」）
python sandbox/serve.py                             # http://localhost:8000/，服務 frontend/，關快取
# 或 python -m http.server 8000 --directory frontend

# 測試 / 檢查
python scripts/lint_articles.py [--slug X] [--fix]  # 文章寫作規範檢查（品牌、引用、路徑、AI 痕跡）；Edit 文章後 hook 會自動跑
python test_search.py                               # 搜尋演算法 100 案例；非 0 exit 代表失敗
python scripts/smoke_test.py --base http://localhost:8000   # 需先起 server；全站連結/sitemap 200 檢查
python scripts/perf_audit.py                        # 本機 SEO/大小 audit → research/perf-report.md
python research/quality_dashboard.py                # 三資料源品質報表 → research/quality-report.md

# 獸醫院資料
python scrapers/vets/layer1_opendata.py --all       # 政府 open data 各城市 → data/vets/{city}_vets.json + all_vets.json
python scrapers/vets/layer1_opendata.py --city kaohsiung
python scrapers/vets/layer2_gmaps.py [--city 台北市] [--limit N]
python scrapers/vets/layer3_website.py --city 台北市 --limit 50
python scripts/clean_vets.py                        # 補 district、抓重複 → cleanup-report.md
python scripts/geocode_vets.py                      # OSM Nominatim，1.5s/req，可中斷續跑
python scripts/build_vets_js.py                     # all_vets.json → frontend/data/vets.js（vets.html 真正讀的檔）

# 文獻
python scrapers/literature/crawler.py --report
python scrapers/literature/verify_citation.py <CITATION-KEY> | --all-approved
```

沒有 lint／formatter 設定。所有 Python 腳本都是 stdlib + requests 等級，直接 `python <path>` 執行，路徑用 `Path(__file__)` 相對推導，可從任何 cwd 跑。

## 架構

### Build pipeline（`build.py`，單檔約 1400 行）

```
content/articles/*.md ─┐
content/references/citations.json, glossary.json ─┤
data/breeds/breeds.json ─┘
        │  python build.py
        ▼
frontend/articles/{slug}.html      每篇文章（含 nav / ad slots / 免責 / 找獸醫 CTA）
frontend/articles/index.html       分類 → 子分類列表，有 draft 隱藏切換
frontend/js/articles-data.js       window.ARTICLES_INDEX（search.js 與 test_search.py 共用）
frontend/js/meta.js                build 時間（footer 用）
frontend/data/{citations,glossary,vets}.json   複製，讓 frontend/ 可獨立部署
frontend/breeds/{slug}.html        品種 SEO 殼頁，互動版在 breeds.html
frontend/sitemap.xml               只收 quality ∈ {reviewed, featured} 的文章
```

- 產出物**全部進 git**。GitHub Actions（`.github/workflows/deploy.yml`）只把 `frontend/` 原樣推上 Pages，**不跑 build.py**。改了 content/ 卻沒 `python build.py` 再 commit，線上不會變。
- 文章 HTML 模板（`ARTICLE_TEMPLATE`、`ARTICLES_INDEX_TEMPLATE`）是 build.py 內的 f-string，不是獨立檔；改版面要改 build.py。
- `SUBCATEGORY_MAP`（build.py）以 slug 硬編子分類，frontmatter `subcategory` 只是 fallback。
- `SITE_URL` 寫死在 build.py，換網域時要改。
- Markdown 內的 HTML 註解會在 build 時被剝除，可放內部備註。

### 文章 frontmatter 與品質狀態

`content/articles/YYYY-MM-DD-{slug}.md`，YAML frontmatter 關鍵欄位：

| 欄位 | 用途 |
|---|---|
| `slug` | 輸出檔名；缺省用檔名 stem |
| `quality` | `draft`（預設）/ `reviewed` / `featured` / `archived`。draft 頁面頂端顯示「未審」警語、列表半透明、**不進 sitemap** |
| `sources` | 自由文字列表；`scripts/link_sources_to_citations.py` 用 fuzzy match 對到 `citations.json` 的 key 並回填 `cited_by` |
| `find_vet` | `cat_only` / `emergency` / `both` → 文末「找獸醫」CTA 樣式 |
| `related` | 反向連結用 slug 列表 |

- 目前所有文章都還是 `draft`；審核流程在 `research/`（`review_batch.py` → 人工回 `<#> r/d/x` → `apply_review.py` 改 frontmatter）。
- 已淘汰文章移到 `content/articles/_archived/`，build.py 只 glob 頂層 `*.md`，所以移進去即下架。

### 獸醫院資料流

```
scrapers/vets/layer1 → data/vets/{city}_vets.json → --merge → data/vets/all_vets.json
                       ↓ layer2（gmaps_url/rating）↓ layer3（website/blog）
scripts/clean_vets.py / geocode_vets.py（in-place 改 all_vets.json）
scripts/build_vets_js.py → frontend/data/vets.js（短鍵 n/t/a/c/d/g/h/e/lat/lng + KNOWN_24H 手動名單）
```

注意：build.py 也會把舊的 `taipei_newtaipei_vets.json` 複製成 `frontend/data/vets.json`，但 `vets.html` 實際載入的是 `vets.js`。改獸醫院資料後要跑 `build_vets_js.py`，不是只跑 build.py。

### 前端

- 每頁獨立 HTML，共用 `css/theme.css`、`css/nav.css`、`css/ads.css` 與 `js/theme.js`、`js/ads.js`。
- `search.js` 的計分（title 10 / tags 5 / description 3 / body 1）與分隔符正規化在 `test_search.py` 有一份 Python 鏡像。**改 search.js 的演算法必須同步改 test_search.py**。
- `test_search.py` 目前有 45 筆既有失敗：它仍假設 103 篇文章，並查找已移進 `_archived/` 的 slug（波斯貓、跳蚤、TNR 等）。改動搜尋前先把這些案例更新到現有 56 篇，否則分不出新舊失敗。
- 文章頁的編輯揭露（`✍️ 編輯 Chen-MouChin · AI 協助起草`）與 JSON-LD 的 `author: Person`、`publishingPrinciples` 由 build.py 產生；有 `last_reviewed` 日期時會多顯示「✅ 審核」並寫入 `dateModified`。方針內容在 `frontend/editorial.html`（手寫，不由 build 產生）。
- `library.html` 讀 `frontend/data/citations.json`＋`glossary.json`（文獻庫，目前唯一被 sitemap 視為可信的內容頁）。

### 爬蟲共通

- 所有爬蟲 import `scrapers/polite.py` 的 `wait_page / wait_detail / wait_api`（±50% 抖動），不要自己 `time.sleep`。
- User-Agent 帶聯絡信箱；OSM Nominatim ≤1 req/s。

### 不進 git 的目錄

`research/`（內部研究、審核工具、品質報表）與 `sandbox/`（本機試驗、`serve.py`）都在 `.gitignore`。這些檔案只存在於本機，另一台機器 clone 不會有；不要在 committed 程式碼裡依賴它們。進度與計畫的 source of truth 已搬到 `docs/`（PROGRESS.md、ROADMAP.md）；`research/workflow.md` 是舊版，僅供參考。

## 文件

- `docs/HANDOVER.md`：交接，含已核對的法規事實、品牌資產、外部帳號狀態、已知陷阱。開新工作前先讀。
- `docs/PROGRESS.md`：進度紀錄，由新到舊。有實質進展就加一段並更新頂端數字。
- `docs/ROADMAP.md`：階段門檻與決策紀錄。改變方向時在這裡記決策。
- `docs/TODO.md`：小型待辦。**開場先看「等你回覆」那節**，裡面有待使用者決定的事項。

## 寫作與審核

- 撰寫、改寫、審核任何 `content/articles/*.md` 前，先載入專案 skill `cat-health-writing`（`.claude/skills/cat-health-writing/SKILL.md`）。它定義結構、句內引用、品牌政策、去 AI 痕跡與交稿自檢。
- 最近一次全站審核：`docs/audit-2026-09-06.md`（56 篇逐篇判定、6 處事實錯誤、7 組跨文章矛盾、16 篇品牌問題）。改文章前查該篇的「必修」欄。

## 設計原則

- Plain HTML，無框架，無 build step（build.py 只是 Markdown → HTML 產生器）
- 手機友善（RWD）
- 每頁最多 3 個 AdSense 位；sticky anchor 廣告可關（24h localStorage）
- 免責聲明放在醫療內容前面
- 學術引用只用：ISFM / WSAVA / IRIS / AAFP / Cornell / VCA / ASPCA / PubMed open-access
- **不引用 Frontiers 期刊**
- 文獻摘要（`abstract_zh`）必須 paraphrase，不可複製原文
- 繁體中文、台灣用語；程式註解與 docstring 也用中文

## Windows 注意事項

- 主控台預設 cp1252，印中文會崩潰。新腳本開頭加：
  ```python
  if hasattr(sys.stdout, "reconfigure"):
      sys.stdout.reconfigure(encoding="utf-8")
  ```
- 所有讀寫檔明確 `encoding="utf-8"`。
- `refresh_vets.sh` 是 bash 腳本，PowerShell 下直接跑各層 Python 檔即可。
