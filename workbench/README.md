# 工作檯（本機審核後台）

給人工審核用的單頁後台。Python 標準庫伺服器 + Vue 3（CDN），不需要 npm，改完 `index.html` 重新整理即可。

```bash
python workbench/server.py          # http://127.0.0.1:8010/
python workbench/server.py --port 9000
```

## 四個分頁

| 分頁 | 做什麼 | 寫到哪裡 |
|---|---|---|
| 儀表板 | reviewed 篇數、lint FAIL、文獻 approved 與完整度，對照 workflow.md 門檻 | 唯讀 |
| 文章審核 | 左列表、中間渲染後的文章、右邊 lint 與句內引用的文獻。快捷鍵 `r` 通過、`f` 精選、`d` 退回、`x` 淘汰、`n`/`p` 上下篇 | `content/articles/*.md` 的 `quality`、`last_reviewed`、`review_notes`；淘汰移到 `_archived/` |
| 文獻核對 | 依狀態篩選，改中文標題與摘要，approve / reject，跑 `verify_citation.py` | `content/references/citations.json` |
| 建置與發佈 | 重建（build.py + sync_cited_by）、全站 lint、commit、push | `frontend/`、git |

## 流程

1. 文章審核分頁讀一篇，右邊確認引用的文獻都有原文連結。
2. 按 `r`。frontmatter 會寫成 `quality: reviewed`、`last_reviewed: 今天`。
3. 順手把該篇引用的文獻按 approve。
4. 到建置與發佈：重建 → lint 應為 0 FAIL → commit → push。push 後 GitHub Pages 幾分鐘內更新。

## 安全

- 只綁 127.0.0.1，外部連不到。
- 所有 POST 要帶 `X-Workbench: 1` 標頭，瀏覽器跨站表單無法觸發。
- commit 前會先 `git fetch`，落後遠端就 `pull --rebase`，有衝突則中止並還原，不自行解決。
- `/site/` 只服務 `frontend/` 目錄，路徑會正規化後檢查。

## 依賴

- `scripts/lint_articles.py`（直接 import 用它的 `lint_one`）
- `build.py`、`scripts/sync_cited_by.py`、`scrapers/literature/verify_citation.py`（subprocess）
- Vue 3.4 從 cdnjs 載入，離線時前端無法啟動
