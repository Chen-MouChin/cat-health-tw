# 審核工作檯

給人工審核用的單頁後台。Python 標準庫伺服器加 Vue 3（CDN），不需要 npm；改完 `index.html` 重新整理就生效。

## 啟動

```bash
python workbench/server.py                 # http://127.0.0.1:8010/，只給本機
python workbench/server.py --port 9000
python workbench/server.py --lan           # 開給同區網的小幫手審稿
```

### 區網審稿（`--lan`）

- 啟動時會印出一個含通行碼的網址（`http://192.168.x.x:8010/?t=…`），傳給小幫手。通行碼每次啟動都會換，關掉再開，舊網址就失效。
- 小幫手開過一次網址後，通行碼存在瀏覽器 cookie，網址列不留通行碼。
- 小幫手可以審文章（r/d/x、編輯內文）、核對文獻、重建預覽、跑 lint。commit、push、部署只能在主機本機操作，「建置與發佈」頁不會顯示給小幫手。
- 只接受私有網段（192.168.x.x、10.x.x.x、172.16–31.x.x）的連線，公網位址一律拒絕；Host 標頭對不上也拒絕。
- 只在自己的辦公室網路開。Windows 防火牆跳出詢問時，只勾「私人網路」。用完 Ctrl+C 關掉。
- 傳輸是 http，沒有加密，同網路的人技術上看得到流量。所以只在信任的網路上用。

## 審核流程

1. **儀表板**先看三個數字：核心 10 篇審了幾篇、全站 reviewed 幾篇、上線 blocker（已審文章引用但還沒 approved 的文獻）有幾筆。blocker 可以直接點進文獻核對。
2. **文章審核**：左側清單預設「未審優先」，核心文章標「核心」，title 與 H1 不一致的標「≠H1」。選一篇後右欄最上面是「這篇要注意什麼」，內容來自 `research/review-batch-*.md`：AI 改稿時刪掉的數字、需要人判斷的點。中間是渲染後的文章，草稿從 `build/drafts/` 讀，和上線版同一個模板。
3. 看完按 `r` 兩次通過（防誤觸）、`d` 退回並留備註、`x` 淘汰、`n`/`p` 上下篇。任何一種都會自動重建，不用再跑建置。
4. **文獻核對**：被引用的文獻先打開原文，核對摘要有沒有寫錯，勾「url 已驗證」才能 approve。沒勾的 approve 按鈕是灰的，後端也會擋。
5. **建置與發佈**：commit（先 fetch，落後就 rebase，不 stash；衝突會停下來交給人）、push（只推到 GitHub）、**部署到 Pages**（這才是上線，跑 GitHub Actions，約 1 到 2 分鐘）。卡片會顯示本機、遠端、線上三個 commit 短碼，哪一段還沒推一眼看得出來。

## 編輯內文

文章審核頁右上「編輯內文」可以直接改 Markdown。儲存時先跑 lint，有 FAIL 不會存、會列出哪裡錯；過了才 build。

## 技術

- 後端 `server.py`：`ThreadingHTTPServer`。讀寫 `content/articles/*.md` 的 frontmatter（quality、last_reviewed、review_notes）、`content/references/citations.json`；透過 subprocess 跑 `build.py`、`scripts/sync_cited_by.py`、`scripts/lint_articles.py`、`scrapers/literature/verify_citation.py`、git、gh。
- 前端 `index.html`：Vue 3 單檔，沒有其他框架。
- `/site/` 只能讀 `frontend/`；`/site/articles/` 找不到的草稿從 `build/drafts/articles/` 補。
- 所有 POST 要帶 `X-Workbench: 1` 標頭，擋跨站表單。
- 部署用 gh CLI，第一次要在終端機 `gh auth login`。沒裝的話 winget 的預設位置 `C:\Program Files\GitHub CLI\gh.exe` 也會找。
- commit 訊息自動加 `Co-Authored-By: Claude`。

## API

| 方法 | 路徑 | 做什麼 |
|---|---|---|
| GET | `/api/overview` | 統計、blocker、git 狀態 |
| GET | `/api/articles` | 清單（含 core、has_notes、title_h1_mismatch） |
| GET | `/api/articles/<slug>` | 單篇：frontmatter、lint、引用文獻與上下文、改稿備註 |
| GET/POST | `/api/articles/<slug>/raw` | 讀寫 Markdown 原文；POST 先 lint |
| POST | `/api/articles/<slug>/quality` | 改 quality，順手 build |
| GET/POST | `/api/citations[/<key>]` | 文獻清單與修改；approve 需 url_verified |
| POST | `/api/verify/<key>` | 跑 verify_citation.py |
| POST | `/api/build`、`/api/lint` | 重建、全站 lint |
| GET | `/api/git`、POST `/api/git/commit`、`/api/git/push` | git |
| GET | `/api/deploy/status`、POST `/api/deploy` | 部署狀態、觸發部署 |
