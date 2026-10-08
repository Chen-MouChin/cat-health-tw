# TODO

小型待辦清單。階段性目標看 [ROADMAP.md](ROADMAP.md)，進度看 [PROGRESS.md](PROGRESS.md)。

---

## 最優先

- [ ] **確認 GitHub Pages 是否真的啟用** — 2026-09-06 push 後，
      `https://chen-mouchin.github.io/cat-health-tw/` 回 404。
      從開發環境連不到 github.com 與 api.github.com（504），無法判斷是網路限制還是沒部署。
      檢查：repo → Actions 看 `Deploy to GitHub Pages` 有沒有跑成功；
      repo → Settings → Pages → Source 是否為「GitHub Actions」。

## 等你回覆

- [ ] **工作檯要調整** — 你說之後會提意見。收到意見前不動 `workbench/`。
      目前狀態：文章審核、文獻核對、建置發佈三塊都能用，寫入路徑已實測。
      已知可能要改的方向（等你確認再做）：版面配置、快捷鍵、審核佇列排序、
      多人同時審核時的衝突處理、是否要能直接編輯內文。
- [ ] **10 篇核心文章的審核** — 交給之後的人用工作檯做，不由 AI 標 reviewed。
      清單：CKD、公貓尿道阻塞、疫苗健檢、危險物質、急診判斷、常見症狀、
      FIP、糖尿病、甲狀腺亢進、結紮。
- [ ] **網域** — 買了才能申請 AdSense。買好後告訴我，DNS 以外的設定我做。

## 內容

- [ ] 29 篇文章的 `cover_image` 指向 pollinations.ai 的 AI 生成圖，上線前換掉或拿掉
- [ ] 其餘 46 篇依 skill 深度改寫（每批 10 篇）
- [ ] 六組文章合併：焦慮加費洛蒙、豐富化加獨居貓、生命階段加分齡飲食、
      法規吸收晶片段落、毒物吸收零食禁忌
- [ ] 五篇過短文章擴寫：居家美容、室內外、焦慮、新貓第一週、送養
- [ ] 213 個 lint WARN 多為「數值無出處」，逐篇補註腳時一起清

## 文獻

- [ ] 新增的 4 筆待逐字核對：MOA-CAT-REGISTRATION-2024、APHIA-CAT-RABIES-2025、
      GANDOLFI-2016-TRPV4、GUNN-MOORE-2007-FCDS
- [ ] approved 從 14 補到 40，url 驗證從 73% 到 90%，中文摘要從 72% 到 80%
- [ ] 品種中文名校正，約 40 個罕見品種音譯需人工看過

## 技術債

- [ ] `test_search.py` 45 筆失敗：仍假設 103 篇文章、查找已歸檔的 slug
- [ ] `research/quality_dashboard.py` 獸醫院門檻是六都時代的，資料已是 22 縣市
- [ ] `library.html` 有 3 個廣告位，超過每頁 2 個的自訂上限
- [ ] `frontend/data/vets.json` 是舊的雙北檔，`vets.html` 實際讀 `vets.js`，
      考慮讓 build.py 不要再複製那個 json
- [ ] `CLAUDE.md` 架構圖曾提到根目錄 `TODO.md`，實際位置改為 `docs/TODO.md`

## 已完成（留紀錄）

- [x] 全站 56 篇審核與事實修正
- [x] 句內註腳機制與參考文獻自動產生
- [x] 寫作規範 skill 與 lint、hook
- [x] Logo 定案與全站套用
- [x] 編輯方針頁
- [x] 工作檯第一版
- [x] 交接、進度、路線圖文件
