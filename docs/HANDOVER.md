# 交接文件

最後更新：2026-09-06
對象：接手這個 repo 的人或 AI session。讀完這份，應該能在 30 分鐘內跑起網站、知道每個工具做什麼、知道哪些事不能做。

進度看 [PROGRESS.md](PROGRESS.md)，計畫看 [ROADMAP.md](ROADMAP.md)，待辦看 [TODO.md](TODO.md)，寫作規範看 `.claude/skills/cat-health-writing/SKILL.md`。

**開工前先看 `docs/TODO.md` 的「等你回覆」那節**，那裡是卡在使用者身上的事項。

---

## 1. 這是什麼

貓健康站，台灣繁體中文的貓健康知識庫。定位：貓生病了第一個想到的網站，每個數字都有出處，不業配。

兩條主線：
- 醫療知識文章（SEO 長尾流量），`content/articles/*.md`
- 獸醫院查詢（全台 22 縣市 2,001 家，含 24 小時急診篩選），`frontend/vets.html`

變現只有 Google AdSense。不做業配、不做聯盟行銷、文章不出現品牌名。

## 2. 三十分鐘上手

```bash
python -m venv .venv && .venv/Scripts/activate
pip install -r requirements.txt            # markdown；fontTools 與 Pillow 只有做 Logo 才需要

python build.py                            # content/ → frontend/
python sandbox/serve.py                    # http://localhost:8000/ 預覽（sandbox/ 不進 git，沒有就用 python -m http.server 8000 --directory frontend）
python workbench/server.py                 # http://127.0.0.1:8010/ 審核工作檯
python scripts/lint_articles.py            # 寫作規範檢查，FAIL 必須為 0
```

部署：push 到 main，GitHub Actions 把 `frontend/` 原樣上傳到 GitHub Pages，**不跑 build.py**。所以產出物要 commit，而且 push 等於上線。

## 3. 目錄與角色

| 路徑 | 角色 | 進 git |
|---|---|---|
| `content/articles/*.md` | 文章原稿，frontmatter 決定品質狀態 | 是 |
| `content/articles/_archived/` | 淘汰的文章，build 不讀 | 是 |
| `content/references/citations.json` | 文獻庫，文章註腳 `[^KEY]` 對到這裡的 key | 是 |
| `build.py` | 唯一的產生器：Markdown 轉 HTML、註腳、參考文獻、sitemap、品種殼頁 | 是 |
| `frontend/` | 發佈根目錄，全部是產出物加靜態頁 | 是 |
| `frontend/images/logo/` | Logo SVG 資產，由 `scripts/build_logo.py` 產生 | 是 |
| `scripts/` | 工具：lint、logo、獸醫院資料處理、cited_by 回填 | 是 |
| `scrapers/` | 獸醫院三層爬蟲、文獻爬蟲、verify_citation | 是 |
| `data/vets/` | 獸醫院 JSON，`all_vets.json` 是主檔 | 是 |
| `workbench/` | 本機審核後台 | 是 |
| `.claude/skills/cat-health-writing/` | 寫作規範 skill | 是 |
| `.claude/settings.json` | PostToolUse hook：編輯文章後自動 lint | 是 |
| `docs/` | 本文件、進度、路線圖 | 是 |
| `research/` | 內部研究、審核腳本、品質報表、審核報告 | **否** |
| `sandbox/` | 本機試驗與預覽伺服器 | **否** |

`research/` 與 `sandbox/` 不進 git。換機器時這兩個目錄不存在，重要內容已搬到 `docs/`。56 篇的逐篇審核報告已複製到 `docs/audit-2026-09-06.md`。

## 4. 內容流程

```
寫或改 .md（依 skill）
  → hook 自動 lint，FAIL 清零
  → python build.py
  → 工作檯或手動把 quality 改 reviewed（只有人可以做這步）
  → 重建、commit、push
```

### 文章 frontmatter 關鍵欄位

| 欄位 | 值 | 效果 |
|---|---|---|
| `quality` | `draft` / `reviewed` / `featured` / `archived` | draft 頁首有「AI 草稿」警語、列表半透明、不進 sitemap |
| `last_reviewed` | 日期或 `null` | 顯示「審核 日期」並寫進 schema dateModified |
| `find_vet` | `cat_only` / `emergency` / `both` | 文末「找獸醫」按鈕樣式 |
| `related` | slug 清單 | 相關文章區塊 |
| `sources` | 自由文字 | 沒有註腳時的備援來源清單 |

### 引用機制

正文寫 `[^IRIS-CKD-2023]`，build.py 渲染成上標數字連到 `library.html?id=IRIS-CKD-2023`，文末自動產生「參考文獻」。`scripts/sync_cited_by.py` 把註腳反向寫回文獻庫的 `cited_by`。KEY 不存在會在 build 時印警告，lint 視為 FAIL。

## 5. 編輯方針（已公開在 frontend/editorial.html，必須遵守）

- AI（Claude）起草，人（Chen-MouChin）逐篇審核並負責。未審核的一律掛 draft 警語。
- 每個數值、劑量、分期、比例句尾要有註腳。沒有來源的數字不寫。
- 只引 ISFM、AAFP、WSAVA、IRIS、ABCD、ACVIM、Cornell、同儕審查期刊、農業部與各縣市動保處。**不引 Frontiers**。
- 文獻中文摘要一律改寫，不複製原文。
- 文章不出現飼料、藥品、用品的品牌名，用成分名或通用描述。唯一例外是為了排除危險（例如「含 permethrin 的犬用驅蟲劑對貓有毒」）。
- 事實錯誤確認後 7 天內修正並註記；危及安全的錯誤立即處理。

## 6. 已核對的法規事實（改文章時不要改回去）

| 事實 | 依據 |
|---|---|
| 貓自 2025-01-01 起為應辦理登記之寵物，緩衝一年，2026-01-01 起未登記罰 3,000 至 15,000 元（動保法 §31） | 農業部 2024-12-16 公告，citations.json `MOA-CAT-REGISTRATION-2024` |
| 遺棄罰 3 萬至 15 萬（§29）；虐待致死或重傷 2 年以下徒刑併科 20 萬至 200 萬（§25） | 動保法原文，`TW-ANIMAL-PROTECTION-ACT` |
| 犬貓滿 3 月齡須接種狂犬病疫苗，之後每年一劑，罰 3 萬至 15 萬；2025-07-01 起完全室內、外出用箱籠且經縣市公告的貓可免 | 防檢署 Q&A，`APHIA-CAT-RABIES-2025` |
| 台灣自 2013 年起為狂犬病疫區（野生鼬獾） | 同上 |
| 動保法沒有 TNR 專條 | 全文查無 |

## 7. 品牌資產

- Logo 定案：金線脈搏 × 貓啃什錦黑。耳朵記號、字標外框、金色脈搏線。
- 字型：貓啃什錦黑繁體版，SIL OFL 1.1，來源 github.com/Skr-ZERO/MaokenAssortedSans-TC v0.90。字型檔不進 git，只留 `frontend/fonts/maoken-assorted-logo.woff2` 子集與外框化的 SVG。
- 重新產生：`python scripts/build_logo.py --font <MaokenAssortedSans-TC.ttf>`
- 色票：奶油米 `#f9f6f0`、近黑 `#1d1d1f`、苔綠 `#5b8a6e`、金 `#b8860b`。全在 `frontend/css/theme.css`。
- 設計過程與未採用方案在 Claude 設計畫布：https://claude.ai/code/artifact/36152237-a431-4ddf-bd6a-fa77a539e066

## 8. 外部帳號與待辦設定

| 項目 | 狀態 | 誰 |
|---|---|---|
| GitHub repo `Chen-MouChin/cat-health-tw` | 有，Pages 用 Actions 部署 | 已設 |
| 自訂網域 | 未買。README 寫 cat-health.tw。買好後：Cloudflare DNS 指 GitHub Pages IP、`frontend/CNAME`、Pages 設定勾 Enforce HTTPS、改 build.py `SITE_URL` 與所有 canonical | 買網域是你 |
| AdSense | 未申請。github.io 子網域不會過，要先有網域。站內隱私政策與廣告佔位已備。申請時機：20 到 30 篇 reviewed 之後 | 申請是你 |
| Google Search Console | 未設 | 網域好後 |

## 9. 已知陷阱

- **push 等於上線。** 沒有 staging。draft 警語是保護機制，別在 reviewed 之前把警語拿掉。
- `frontend/data/vets.js` 由 `scripts/build_vets_js.py` 產生，不是 build.py。改獸醫院資料要跑它。
- 文章內部連結一律相對路徑（`../vets.html`）。站台在子路徑下，`/vets.html` 會 404。
- `test_search.py` 有 45 筆既有失敗，它還假設 103 篇文章，改搜尋前先更新案例。
- `research/quality_dashboard.py` 的獸醫院門檻是六都時代寫的，現在資料是 22 縣市，「缺 district 812」多為外島與非六都，指標要改。
- 29 篇文章 `cover_image` 指向 pollinations.ai 的 AI 生成圖，上線前要換掉或拿掉。
- `build.py` 沒裝 `markdown` 套件時會退回 regex 轉換，品質差。確認 `pip install markdown`。
- Windows 主控台印中文會崩潰，腳本開頭都有 `sys.stdout.reconfigure(encoding="utf-8")`，新腳本照做。
- commit 或 push 前先 `git fetch`，落後就 `pull --rebase`；工作檯的 commit 按鈕已內建這個流程。

## 10. 聯絡

開發者 Chen-MouChin，GitHub 同名。站內回饋表單寄到開發者信箱，或在 repo 開 Issue。
