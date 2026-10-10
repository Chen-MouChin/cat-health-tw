# 審核工作檯

給人工審核用的單頁後台。Python 標準庫伺服器加 Vue 3（CDN），不需要 npm；改完 `index.html` 重新整理就生效。

## 啟動

```bash
python workbench/server.py                 # http://127.0.0.1:8010/，只給本機
python workbench/server.py --port 9000
python workbench/server.py --lan           # 開給同區網的小幫手審稿
```

### 區網審稿（`--lan`）

- 啟動時會印出一個含通行碼的 HTTPS 網址（`https://192.168.x.x:8010/?t=…`）和憑證指紋，傳給小幫手。通行碼每次啟動都會換，關掉再開，舊網址就失效。
- 本機自己用的還是 `http://127.0.0.1:8010/`；區網那一路只綁區網 IP、走 HTTPS（TLS 1.2 以上），不綁 0.0.0.0。
- 憑證是自簽的，存在 `build/workbench-cert/`（不進 git），IP 換了或快過期會自動重產。小幫手第一次開會看到「連線不是私人連線」：點網址列的警告圖示看憑證，SHA-256 指紋和工作檯印出的一樣，再按「繼續前往」。指紋不一樣就不要繼續，代表中間有人攔截。
- 需要 `cryptography` 套件（`pip install cryptography`）。
- 小幫手開過一次網址後，通行碼存在瀏覽器 cookie，網址列不留通行碼。
- 小幫手是「審稿者」：可以認領、加註解、勾檢查清單、按初審通過或退回修改、編輯內文、核對文獻原文與摘要、重建預覽。核准上線、文獻核准、commit、push、部署只有主機本機的負責人能做，「建置與發佈」頁不會顯示給小幫手。
- 小幫手第一次進來會被問名字，顯示在註解與紀錄上；只存在工作檯，不進 git。
- 只接受私有網段（192.168.x.x、10.x.x.x、172.16–31.x.x）的連線，公網位址一律拒絕；Host 標頭對不上也拒絕。
- 只在自己的辦公室網路開。Windows 防火牆跳出詢問時，只勾「私人網路」。用完 Ctrl+C 關掉。

## 審核流程（兩段式）

```
待審 → 審稿中（有人認領）→ 初審通過 → 負責人核准上線
                    ↘ 退回修改 ↗
```

**小幫手（或負責人自己）做初審：**
1. 「文章審核」清單預設只列「可以審的」。點一篇，按「我來審這篇」。認領 2 小時沒動作會自動釋出，別人看得到誰在審哪篇。
2. 讀中間的文章。**反白一段字 → 加註解**；想直接改字，在「建議改成」寫新句子。註解會在文章上標黃，點標記跳到那則註解。
3. 右欄「文獻」頁：每個註腳附上它在文中的句子和文獻摘要，逐筆對照。點文章裡的註腳編號也會跳過來。
4. 「審稿」頁勾完 5 項檢查清單（每項可選「沒問題」或「不適用」）。
5. 所有註解處理完（套用建議、回覆後標成已解決）才能按「初審通過」；要改的按「退回修改」並寫原因。

**負責人核准：**
- 儀表板「等你核准」列出初審通過的文章，頁首「文章審核」也有數字提示。
- 核准前自動檢查：lint 有 FAIL 或註腳對不到文獻庫就不能核准；引用的文獻還沒核准會要你再確認一次。沒經過初審也能直接核准，但會跳提醒並記在紀錄上。
- 核准會把 frontmatter 改成 `quality: reviewed`（或 featured）、寫 `last_reviewed`、重建。之後到「建置與發佈」commit、push、部署才會上線。

**修改紀錄：** 每次存檔與套用建議都記下是誰、什麼時候、改了哪幾行（中間欄「修改紀錄」）。兩個人同時改同一篇時，後存的人會收到「這篇在你打開之後被某某改過」，不會蓋掉別人的修改。

**資料存在哪：** 審稿階段、註解、檢查清單、紀錄存在 `research/reviews/{slug}.json`（不進 git，公開 repo 看不到小幫手名字與註解）。只有核准結果寫回文章 frontmatter。要備份就備份 `research/`。

網址 `#review/<slug>` 會直接打開那篇，可以把連結傳給小幫手。

## 測試

```bash
python workbench/test_workbench.py    # 25 項：單元、API 權限、兩段式審核、存檔衝突、build 排隊、git、部署（假 gh）
python workbench/e2e_workbench.py     # 選用：用 Chrome 走一遍小幫手審稿到負責人核准，截圖在 build/e2e/（要 pip install playwright）
```

兩個都在暫存資料夾的 repo 複製上跑，另建假遠端，不碰真的文章與 git。改工作檯之後先跑 `test_workbench.py` 再 commit。

## 技術

- 後端 `server.py`：`ThreadingHTTPServer`。讀寫 `content/articles/*.md` 的 frontmatter（quality、last_reviewed）、`research/reviews/*.json`（審稿流程，`reviews.py`）、`content/references/citations.json`；透過 subprocess 跑 `build.py`、`scripts/sync_cited_by.py`、`scripts/lint_articles.py`、`scrapers/literature/verify_citation.py`、git、gh。
- 前端 `index.html`：Vue 3 單檔，沒有其他框架。
- `/site/` 只能讀 `frontend/`；`/site/articles/` 找不到的草稿從 `build/drafts/articles/` 補。
- 所有 POST 要帶 `X-Workbench: 1` 標頭，擋跨站表單；審稿者名字放在 `X-Reviewer`。
- build 用一把鎖排隊，兩個人同時觸發不會互相覆蓋。
- 部署用 gh CLI，第一次要在終端機 `gh auth login`。沒裝的話 winget 的預設位置 `C:\Program Files\GitHub CLI\gh.exe` 也會找。
- commit 訊息自動加 `Co-Authored-By: Claude`。

## API

| 方法 | 路徑 | 做什麼 |
|---|---|---|
| GET | `/api/overview` | 統計、blocker、git 狀態 |
| GET | `/api/articles` | 清單（含 core、has_notes、title_h1_mismatch） |
| GET | `/api/articles/<slug>` | 單篇：frontmatter、lint、引用文獻與上下文、改稿備註 |
| GET/POST | `/api/articles/<slug>/raw` | 讀寫 Markdown 原文；POST 帶 base_hash，版本不符回 409；先 lint |
| POST | `/api/articles/<slug>/quality` | 核准上線／下架／淘汰（只限負責人），核准前把關，順手 build |
| POST | `/api/review/<slug>/claim`、`release` | 認領、放下 |
| POST | `/api/review/<slug>/check` | 檢查清單一項（ok / na / 空） |
| POST | `/api/review/<slug>/stage` | 初審通過（passed）、退回修改（changes） |
| POST | `/api/review/<slug>/comment` | 加註解（quote、text、suggestion） |
| POST | `/api/review/<slug>/comment/<id>/reply`、`resolve`、`delete`、`apply` | 回覆、解決、刪除、套用建議 |
| GET | `/api/activity` | 最近審稿動態 |
| GET/POST | `/api/citations[/<key>]` | 文獻清單與修改；核准需 url_verified，核准與不採用只限負責人 |
| POST | `/api/verify/<key>` | 跑 verify_citation.py |
| POST | `/api/build`、`/api/lint` | 重建、全站 lint |
| GET | `/api/git`、POST `/api/git/commit`、`/api/git/push` | git |
| GET | `/api/deploy/status`、POST `/api/deploy` | 部署狀態、觸發部署 |
