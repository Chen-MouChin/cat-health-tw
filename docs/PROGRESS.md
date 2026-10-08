# 進度紀錄

由新到舊。每次有實質進展就加一段，數字以當天為準。

---

## 目前狀態（2026-10-08）

| 指標 | 數字 | 上線門檻 |
|---|---|---|
| 文章總數 | 56 篇（另 71 篇在 `_archived/`） | |
| 文章 reviewed + featured | 2（CKD、甲亢，工作檯人工審） | 軟上線 10，正式 30 |
| 依 skill 模板深度改寫完成 | 10 篇 | |
| 寫作規範 lint | FAIL 0，WARN 213（缺固定段落 80、數值無出處 56、無內部連結 42、過短 21、粗體密度 13） | FAIL 0 |
| 句內註腳 | 112 個，涵蓋 46 筆文獻 | |
| 文獻總數 | 113 筆 | |
| 文獻 approved | 15 | 40 |
| 文獻 url 已驗證 | 81（72%） | 90% |
| 文獻中文摘要 | 83（73%） | 80% |
| 獸醫院 | 2,001 家，22 縣市；1,988 家座標可算距離（179 家約略、13 家錯位待修） | |
| sitemap 收錄文章 | 2 篇 | |
| 網域 | 無 | 有 |
| 公開網站 | 無：repo 私有、沒開 Pages，先內部開發，用 ngrok 測試 | 上線時決定託管 |
| AdSense | 未申請 | |

---

## 2026-10-08

**總覽與文章掃描，清掉一批壞資料**
- 本機有一批 9 月中未 commit 的工作，其中「第一輪擴充」把 30 篇文章的 frontmatter `sources` 自動灌成 105 筆 `AUTO-xxxxxx` 文獻（無 url、無年份、無作者）並塞進首段註腳，再標成不存在的 `quality: ai-reviewed`。整批退掉：文章還原、`citations.json` 刪 105 筆、`IRIS-CKD-2023`／`WILHELMY-2016`／`LITCHFIELD-2017` 被誤改的狀態改回 approved。
- 保留的本機工作：CKD 文加 `AAHA-FLUID-2024` 並改寫皮下輸液段（reviewed 2026-09-09）；甲亢文標題去「老貓」、補症狀（reviewed 2026-09-21）；生食文加 WSAVA／ASPCA／ISFM 三筆（pending_review，待核）；攻擊行為文改標題；工作檯加原文讀寫 API、引用上下文、`--host` 區網連線。
- `build.py` 加 `sys.stdout.reconfigure`，Windows 主控台不再在印 `→` 時崩潰。
- 掃描結果：56 篇 lint FAIL 0；112 個註腳全部對得到文獻；無 Frontiers；事實面沿用 `docs/audit-2026-09-06.md`，無新發現。
- 本機與遠端 2026-09-29 的 13 個 commit 同步完成，無衝突。

## 2026-09-29

**全站錯誤修正（視覺提案不論選哪個方向都要修的六項）**
- 文章 H1 重複：`build.py` 本來就要刪內文開頭的 `<h1>`，但比對規則沒考慮 toc 擴充加的 id，一直沒生效。56 篇現在都只有一個 H1。
- 「相關文章」列兩次：內文已有手寫「## 相關文章」一節的 9 篇不再加站內相關盒；只有 frontmatter `related` 的 2 篇照舊。
- 手機導覽列 Logo 旁兩個 🏠：拿掉 `nav.css` 用 `::after` 補的那個。
- 內文連結是瀏覽器預設藍：`theme.css` 加 `--link`（目前同 accent 近黑）與連結基底樣式，改版換主色只改這一個變數。
- 首頁數字：57 篇改 56 篇、113 筆改 109 筆（含 meta 描述與結構化資料）。`build.py` 新增首頁數字檢查，文章或文獻增減後會印 `[warn]`。
- 對比：`--text-faint` #a1a1a6（2.4:1）改 #6b6b70（4.9:1），`--text-muted` #6e6e73 改 #636368（淺米區塊上也過 4.5）；24h 標籤底改 #b93a2e、貓專科標籤底改 #3b6a50、草稿標籤字改 #735f33、「⚡ 重點」標籤改 #a84d16。全站 CSS 低於 4.5:1 的規則從 50 條降到 10 條，剩下的是沒在用的舊樣式、廣告佔位字、停用按鈕與轉址頁。
- 驗證：搜尋測試維持 78/123（同樣 45 筆既有失敗，無新增）；全站連結 64 頁 0 壞；瀏覽器實測 19 項通過。

**視覺改版設計需求書第二版**
- 風格定案：全站主調「溫暖插畫 × 公共服務」（GOV.UK／NHS 的大字、單欄、底線連結、金黃焦點框，加圓角、淺色色塊、單線條貓插畫）；學術文獻庫與註腳、參考文獻用「醫學期刊」排版（思源宋體子集、書目格式、旁註）；主色深苔綠 #3b6a50，紅色只留給急診。
- 動態分兩階段：這次設計數字跑碼、脈搏線畫出、插畫小動作、微互動、定位中動畫；互動急症判斷、計算工具、互動圖表、捲動敘事先畫草圖。
- `docs/design-prompts.md` 改寫為第二版：需求書十一節、首頁加五個頁面 prompt、兩組情緒板。範例資料都用站上實際數字（台北車站 5 km 內 203 家、ISFM CKD 指引的書目等）。

**首頁原型**
- 使用者用首頁 prompt 產生了一份 AI 首頁稿與小貓插畫，原樣存在 `docs/design/`。
- 依稿改成 `docs/design/home-prototype.html`：頁首常駐急診鈕、急診區塊按鈕進手機首屏、數字跑碼同步且 HTML 先放最終值、小貓眼鼻分開、尾巴只甩兩下、GOV.UK 式焦點框、主標用粉圓子集。改動清單見 `docs/design/README.md`。
- Playwright 驗證：手機與桌機無橫向捲動、五個數字約 1 秒同時到位、減少動態時直接顯示最終狀態、鍵盤焦點黃底黑框、無 JS 錯誤。

**新首頁上線（分支）**
- `frontend/index.html` 依原型重寫：頁首常駐「24h 急診」、急診區塊按鈕在手機首屏內、數字跑碼、四個入口加線條圖示、常見狀況、先讀這三篇、我們怎麼寫。免責聲明併進主標副標。
- `build.py` 的 `check_home_stats` 改成 `sync_home_stats`：數字與草稿標籤依實際資料寫回首頁，不再只警告。資料裡連江縣 0 家，所以縣市數由 22 變 21（其他頁待決，見 TODO）。
- 主標粉圓改成站內子集字型（2.6 KB，SIL OFL），不再連 Google Fonts；`scripts/fetch_home_font.py` 可重抓。
- 線條貓的臉改成兩眼＋粉紅倒三角鼻（使用者指定），兩眼拉開、置中在兩耳下方；載入後眨一次眼，耳朵不再動。`theme.css` 加 `--blush`，只給插畫用。
- 使用者同意上線，並要求：首頁文字照原稿、急診區塊不給建議。副標、搜尋提示字、入口卡片說明、「推薦文章」恢復原稿文字；縣市數恢復 22（build 不再自動改）；急診區塊拿掉「不要等天亮」與原型加的兩句，只留標題、四個狀況與找 24h 急診的按鈕。原稿提示字在窄手機會被切，改 CSS（字級隨寬度縮小、隱藏空白時的清除鈕），文字不動。需求書的急診區塊指引同步改成不給建議。

**合併與部署**
- PR #1 合併進 main（1c03daf）。部署在 configure-pages 失敗：repo 沒開 GitHub Pages，這就是之前線上 404 的原因。
- repo 是 private，開 Pages 要 GitHub Pro（每年 48 美元）且站會公開。使用者決定先內部開發、用 ngrok 測試；`deploy.yml` 改成只能手動觸發，合併到 main 不再跑失敗的部署。
- 收尾：HANDOVER 加「下次開工」（同步 main、ngrok 測試步驟與手機測試清單、清掉失敗部署、待決事項）。雲端 session 連不到 ngrok（網路政策擋掉），ngrok 測試要在使用者電腦跑。
- 全站：連結色換深苔綠（`--link`），`:focus-visible` 改 3px 近黑外框、連結加黃底；拿掉 5 處 `outline: none`（about、breeds、vets、library、文章列表）。
- 驗證：全站 64 頁 0 死連結；搜尋測試維持 78/123；132 頁 208 個綠色連結對比都 ≥ 4.5:1；首頁 Playwright 20 項通過（首屏、跑碼、焦點順序、減少動態、搜尋送出、急診連結）。

---

## 2026-09-28

**獸醫院：手機定位找附近**
- `vets.html`「📍 找我附近的獸醫院」：定位後進附近模式，範圍可選 1／3／5／10／20 km／不限（預設 5 km），由近到遠先列 10 家；範圍內一家都沒有就改列最近 5 家。24h、貓專科、搜尋可疊加。
- 手機定位先試 GPS，室內逾時或失敗再退回網路定位；顯示精度，超過 1 km 會提醒。權限被拒時列出 iPhone／Android 的開啟路徑，LINE／FB 內建瀏覽器另外提示。
- 每張卡片加「🧭 導航」（Google 地圖路線，用文字地址；地址缺縣市的會補上）。
- `vets.html?near=1` 進站即定位，`&r=` 指定範圍。首頁急診條與文章 `find_vet: emergency/both` 的 CTA 改連 `?only24h=1&near=1`（文章內文的連結沒動）。
- `build_vets_js.py` 新增座標可信度 `ap`：179 家跟其他地址共用同一點（街道或區中心），距離標「約」；13 家落在別縣市或離同區太遠（例：台南「仁美動物醫院」被對到台北的北安路），vets.js 不輸出座標、不列入距離。`all_vets.json` 沒改。
- 隱私政策加「位置資訊」段；about 與 vets.html 的「100% 有座標」改成實際情況。
- 用 Playwright 模擬手機定位實測：台北、高雄重新定位、台東池上 + 24h、權限被拒、GPS 逾時退回、錯位醫院排除。

---

## 2026-09-06

**審核與工具**
- 全站 56 篇逐篇審核，報告在 `docs/audit-2026-09-06.md`。找出 6 處事實錯誤、7 組跨文章矛盾、16 篇品牌問題。
- 建 `.claude/skills/cat-health-writing/SKILL.md` 寫作規範，取代外部英文 humanizer skill。
- 建 `scripts/lint_articles.py`（17 項檢查）、`scripts/lint_hook.py` 加 `.claude/settings.json` hook（編輯文章後自動 lint）、`scripts/sync_cited_by.py`。
- `build.py` 支援 `[^KEY]` 句內註腳與自動參考文獻。lint FAIL 從 671 降到 0。

**內容**
- 事實錯誤全部修正：狂犬病法規（犬貓皆法定，室內貓 2025-07 起有條件免）、狂犬病疫區、Lokivetmab 犬用、結紮文體溫矛盾、Feliway 中文名、DHA/AHA 錯字。
- 法規罰則依動保法原文修正；貓晶片登記依農業部 2024-12-16 公告統一三篇文章。
- 16 篇去品牌，驅蟲藥表改成分為主鍵；絕對化用語、emoji 標題、破折號、箭頭全站清理。
- 深度改寫 10 篇：CKD、尿道阻塞、疫苗、中毒、急診、常見症狀、FIP、糖尿病、甲亢、結紮。每篇有「何時該立刻就醫」「30 秒重點」「常見問題」。
- citations.json 新增 4 筆：MOA-CAT-REGISTRATION-2024、APHIA-CAT-RABIES-2025、GANDOLFI-2016-TRPV4、GUNN-MOORE-2007-FCDS。

**站台**
- 新增 `frontend/editorial.html` 編輯方針，公開 AI 起草加人工審核的分工、引用政策、品牌政策、更正政策。
- 文章 JSON-LD author 改為 Person Chen-MouChin，加 publishingPrinciples；文章頁顯示編輯者與審核日期。
- 全站頁尾加編輯方針連結。

**品牌**
- Logo 定案：金線脈搏 × 貓啃什錦黑。產出 SVG 系列、favicon、OG 圖，替換全站導覽列與首頁。設計過程在 Claude 設計畫布。

**工作檯**
- 建 `workbench/`：Python 標準庫伺服器加 Vue 3 CDN。文章審核（r/f/d/x 快捷鍵、iframe 渲染、右側引用文獻）、文獻核對、重建、commit、push。

**文件**
- 重寫 CLAUDE.md；新增 docs/HANDOVER.md、PROGRESS.md、ROADMAP.md。

**已 push**：`ab74372`（223 檔）與 `b07584a`（工作檯修正加 TODO）。
56 篇文章仍全部為 draft，頁首保留「AI 草稿」警語，sitemap 不含任何文章。
審核交由之後的人用工作檯進行，AI 不代標 reviewed。

**待確認**：push 後從開發環境無法連到 GitHub 網頁與 API（api.github.com 回 504、
github.com 連不上），`chen-mouchin.github.io/cat-health-tw/` 回 404。可能是開發環境的
網路限制，也可能是 Pages 從未啟用（repo Settings → Pages → Source 要選 GitHub Actions）。
**下次開工第一件事：確認 Actions 的 deploy 有跑成功、Pages 設定正確、線上頁面打得開。**

## 2026-06-10 至 06-11

- 首次 commit `3a41075 init: 貓健康站`。
- 獸醫院資料從六都 1,415 家擴到 22 縣市 2,001 家，geocode 完成，台北市 46 筆缺地址用農業部 API 補齊。
- about.html 補資料品質實況與變現原則。
- 動保法 §25、§19 逐字核對。

## 2026-04-18 至 04-22

- Phase 1A 品質儀表板 `research/quality_dashboard.py` 上線。
- 文章淘汰賽：104 篇篩到 56 篇，其餘移到 `_archived/`。合併多篇成主題文（毒物、急診、疫苗、常見症狀）。
- draft 警語、sitemap 排除、列表灰化機制進 build.py。
- `scripts/link_sources_to_citations.py` 建立文章與文獻的 fuzzy 對應與 cited_by。

## 2026-04-08 至 04-16

- 專案從 neko-pedia 轉型為貓健康知識庫，移除商品比價爬蟲，顏文字工具獨立成另一專案。
- 104 篇 AI 草稿產出。
- 獸醫院三層爬蟲（open data、Google Maps、官網）建立，六都 1,415 家。
- 文獻庫 105 筆建立。
