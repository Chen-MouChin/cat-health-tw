# 審核工作檯 (Workbench)

給人工審核用的單頁後台。採用 Python 標準庫伺服器 + Vue 3 (CDN)，不需要 npm，改完 `index.html` 重新整理即可。

## 啟動方式

```bash
python workbench/server.py          # 預設綁定 0.0.0.0:8010，支援同區網連入
python workbench/server.py --port 9000
python workbench/server.py --host 127.0.0.1  # 限制僅本機存取
```

啟動後，本機可以透過 `http://127.0.0.1:8010/` 存取；同網路（區網）內的其他電腦或手機可以透過這台電腦的 IP 連入，例如 `http://192.168.x.x:8010/`。

---

## 👨‍⚕️ 審核人員使用手冊 (Reviewer Guide)

此工具專為確保文章內容準確性與文獻合規性所設計。

### 核心工作流程
1. **開啟「文章審核」分頁**：在左側列表選擇一篇待審核的 `draft` 文章。
2. **對照文獻**：文章渲染畫面右側會列出所有引用的文獻，請確保每一個引用都有提供真實可查的原文連結。
3. **查核文獻庫**：若有新的文獻，請至「文獻核對」分頁核對文獻的中文標題、摘要，並按下 approve。
4. **通過審核**：確認無誤後，於文章審核頁按下快捷鍵 `r` (Review 通過)，系統會自動標記 `quality: reviewed`。
5. **發佈與上線**：前往「建置與發佈」分頁，依序點擊重建、Lint (確保無錯誤)、Commit (提交更動)、Push (推送至 GitHub)，數分鐘後正式網站即會更新。

### 快捷鍵說明 (文章審核頁)
- `r`：通過 (Reviewed)
- `f`：設為精選 (Featured)
- `d`：退回草稿 (Draft)
- `x`：淘汰並移至封存 (Archived)
- `n` / `p`：切換至下/上一篇

---

## 💻 開發人員使用手冊 (Developer Guide)

本工具為純本地端伺服器，直接讀寫檔案與執行系統指令，無使用者權限管理。

### 技術架構
- **後端**：`server.py` 使用 Python 內建的 `ThreadingHTTPServer`。
- **前端**：`index.html` 內嵌 Vue 3 (CDN)、Bootstrap (CDN)，無需編譯打包。
- **依賴腳本**：
  - `scripts/lint_articles.py`：使用其中的 `lint_one` 進行格式與規範檢查。
  - `build.py`、`scripts/sync_cited_by.py`、`scrapers/literature/verify_citation.py`：透過 `subprocess` 呼叫執行。

### 安全與網路機制
- **X-Workbench 標頭**：所有的 POST 請求都必須夾帶 `X-Workbench: 1`，用以防止瀏覽器跨站請求偽造 (CSRF) 攻擊。
- **Git 保護**：在 commit 之前會自動執行 `git fetch`，若落後遠端則 `pull --rebase`；若遇到衝突將自動中止並復原，確保不產生難以挽回的狀態。
- **預設公開綁定**：預設綁定 `0.0.0.0` 允許同網域存取。若要限制存取，建議使用 `--host 127.0.0.1`。
- **靜態檔服務**：`/site/` 路徑會被正規化並嚴格限制只能讀取 `frontend/` 目錄下的檔案，避免路徑穿越攻擊 (Path Traversal)。

### 四個主要分頁與對應修改目標

| 分頁 | 系統操作 | 讀寫目標 |
|---|---|---|
| **儀表板** | 統計 reviewed 篇數、lint FAIL、文獻 approved 等狀態。 | 唯讀 |
| **文章審核** | 渲染文章內容，提供審核狀態修改介面。 | 修改 `content/articles/*.md` 內的 `quality`、`last_reviewed`、`review_notes`；淘汰的文章會被搬移至 `_archived/`。 |
| **文獻核對** | 編輯文獻內容、呼叫 `verify_citation.py` 驗證連結。 | 修改 `content/references/citations.json` |
| **建置與發佈** | 執行外部腳本進行 build、lint、git commit 與 push。 | 寫入 `frontend/`，並執行 Git 指令。 |
