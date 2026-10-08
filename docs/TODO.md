# TODO

小型待辦清單。階段性目標看 [ROADMAP.md](ROADMAP.md)，進度看 [PROGRESS.md](PROGRESS.md)。

---

## 等你回覆

- [ ] **其他頁套首頁風格** — 2026-10-09 使用者定案：不委外，使用者畫的線條貓與首頁就是設計稿。
      文章頁、文章列表、獸醫院、文獻庫、about 依 `frontend/index.html` 的色票、字級、圓角色塊與線條貓重做，
      文獻區維持「醫學期刊」排版。需求書 `docs/design-prompts.md` 轉為內部參考。
      等你：先做哪一頁（建議文章頁，因為線上只有它和首頁有人看）；手機底部錨定廣告要不要留。
- [x] **縣市數寫 21 還是 22** — 2026-10-08 定案維持 22（資料覆蓋 22 縣市），`vets.html`、`about.html` 加註連江縣無登記動物醫院，
      並修正「本島 21」為「本島 19」。以下為原始紀錄：資料裡連江縣 0 家（爬蟲有抓，農業部登記沒有），實際有醫院的是 21 縣市。
      首頁照原稿維持 22（使用者要求文字不改，build 不自動改這個數）；`vets.html`、`about.html` 也寫「全台 22 縣市」，
      `vets.html` 的描述另有「本島 21 縣市＋澎湖金門」的錯誤算法。要不要全站改成 21？
- [ ] **急診區塊的四個狀況要不要留** — 首頁急診區塊已拿掉所有就醫建議，現在只剩標題、尿不出來／呼吸急促／抽搐／誤食、找 24h 急診的按鈕。四個狀況是原稿文字，先留著。
- [x] **工作檯調整**（2026-10-09 做完）— commit 不再 stash、push 與部署分開並加「部署到 Pages」按鈕、預設只綁 127.0.0.1、
      approve 需先勾 url 已驗證、審核側欄顯示 AI 改稿備註與 title≠H1、佇列可排序與進度、標完自動重建、通過要按兩次、
      編輯內文存前先 lint、儀表板加核心進度與上線 blocker。細節見 workbench/README.md。
- [ ] **10 篇核心文章的審核** — 交給之後的人用工作檯做，不由 AI 標 reviewed。
      已審 2 篇：CKD（2026-09-09）、甲狀腺亢進（2026-09-21）。
      待審：公貓尿道阻塞、疫苗健檢、危險物質、急診判斷、常見症狀、FIP、糖尿病、結紮。
- [ ] **網域** — 買了才能申請 AdSense。買好後告訴我，DNS 以外的設定我做。
- [x] **上線託管** — 2026-10-08 repo 改 public，GitHub Pages 開通（Source = GitHub Actions），
      https://chen-mouchin.github.io/cat-health-tw/ 已上線。`deploy.yml` 仍是手動觸發：
      改了內容要 `gh workflow run "Deploy to GitHub Pages"`（或 Actions 頁按 Run workflow）才會更新線上。

## 內容

- [ ] 29 篇文章的 `cover_image` 指向 pollinations.ai 的 AI 生成圖，上線前換掉或拿掉
- [ ] 2026-10-09 批次改寫的 30 篇等人審核（工作檯），對照 `research/review-batch-2026-10-09.md`；跨文章一致性 8 項要先決定
- [ ] 其餘 24 篇依 skill 改寫（其中 16 篇 title 與 H1 不一致、6 篇仍有「——」或對比句）
- [ ] 補文獻後回填數字：飲水量、嘔吐紅旗次數、減重速度、體溫、幼貓疫苗間隔、砂盆尺寸、皮膚科指引、脂肪肝專文、高血壓指引
- [ ] 上線前逐字核對：MOA-CAT-REGISTRATION-2024、APHIA-CAT-RABIES-2025（五篇依賴）、TW-ANIMAL-PROTECTION-ACT §29；合併重複 key（AAFP senior 兩筆、AAFP dental 兩筆）
- [ ] 六組文章合併：焦慮加費洛蒙、豐富化加獨居貓、生命階段加分齡飲食、
      法規吸收晶片段落、毒物吸收零食禁忌
- [ ] 五篇過短文章擴寫：居家美容、室內外、焦慮、新貓第一週、送養
- [ ] 213 個 lint WARN 多為「數值無出處」，逐篇補註腳時一起清

## 文獻

- [ ] 新增的 4 筆待逐字核對：MOA-CAT-REGISTRATION-2024、APHIA-CAT-RABIES-2025、
      GANDOLFI-2016-TRPV4、GUNN-MOORE-2007-FCDS
- [ ] 生食文 2026-09 新增 3 筆待核對 url 與摘要：WSAVA-RAW-MEAT-2021、ASPCA-RAW-FOOD、ISFM-RAW-DIET
- [ ] approved 從 15 補到 40，url 驗證從 72% 到 90%，中文摘要從 73% 到 80%
- [ ] 不要再用「自動把 frontmatter sources 轉成文獻」的做法（2026-10-08 退掉 105 筆 AUTO 空殼）；
      新文獻一律有 url、年份、作者再進 `citations.json`
- [ ] 品種中文名校正，約 40 個罕見品種音譯需人工看過

## 視覺改版實作時

- [ ] 閱讀時間：需求書的文章頁與列表有「約 N 分鐘」，站上目前沒有。`build.py` 以每分鐘約 500 字估
- [x] 數字跑碼要用真實數字：`build.py` 的 `sync_home_stats` 依資料寫回首頁（2026-09-29）
- [ ] 動態一律尊重 `prefers-reduced-motion`，急診按鈕與醫院清單不加延遲出現的動畫（首頁已照做，其他頁改版時沿用）
- [x] 首頁從 `docs/design/home-prototype.html` 移植（2026-09-29）
- [ ] 其他頁的導覽列與頁尾照首頁改（現在首頁一套、內頁 `nav.css` 一套，內頁仍有 emoji 圖示）
- [ ] 拆 `--accent`：主按鈕與選取狀態換深苔綠，文章標題留近黑（build.py 模板與各頁 CSS）
- [ ] AdSense 上線時，首頁拿掉 `.ad` 的 hidden 放廣告碼

## 技術債

- [x] `test_search.py` 改讀 `build/articles-data-all.js` 全集、案例更新到現有 56 篇，117/117（2026-10-09）
- [ ] **上線基礎（等你決定）**：analytics 用哪家（Plausible／Umami 無 cookie，或 GA4）；Google Search Console 驗證（HTML 檔放 frontend/ 即可）；網域
- [ ] 品種圖鑑 68 頁目前 noindex、不進 sitemap（`build.py` 的 `BREEDS_INDEXABLE`）；審過品種中文名與內容再打開
- [ ] 獸醫院資料：2026-06-10 後沒更新；gmaps/rating/website 三欄全空（第二、三層爬蟲沒跑完）；24h 89 家、貓專科 71 家是名字猜的，要人工核；每季重跑 layer1
- [ ] 文章頁、列表、獸醫院、文獻庫、about 套首頁風格（先出文章頁草稿）
- [ ] 隱私政策接 AdSense 後補 Google 要求條款；文章頁加授權聲明（可否轉載）
- [ ] `research/quality_dashboard.py` 獸醫院門檻是六都時代的，資料已是 22 縣市
- [ ] `library.html` 有 3 個廣告位，超過每頁 2 個的自訂上限
- [ ] `frontend/data/vets.json` 是舊的雙北檔，`vets.html` 實際讀 `vets.js`，
      考慮讓 build.py 不要再複製那個 json
- [ ] `CLAUDE.md` 架構圖曾提到根目錄 `TODO.md`，實際位置改為 `docs/TODO.md`
- [ ] 重新 geocode 座標可疑的獸醫院：`python scripts/build_vets_js.py` 會列出 13 家 ap=2（錯位），
      另有 179 家 ap=1（共用街道或區中心點）。台南、台中的地址缺縣市與區前綴，要先補區再查；
      `geocode_vets.py` 也該記下命中的是哪一層 fallback（門牌／街道／區）。
- [ ] 24h 急診名單只涵蓋 12 縣市，花蓮、台東、宜蘭、屏東等地一家都沒有。
      台東池上開「只看 24h」，最近的是直線 90 km 外的嘉義。需人工確認各縣市夜間急診補進 `KNOWN_24H`。

## 已完成（留紀錄）

- [x] 全站 56 篇審核與事實修正
- [x] 句內註腳機制與參考文獻自動產生
- [x] 寫作規範 skill 與 lint、hook
- [x] Logo 定案與全站套用
- [x] 編輯方針頁
- [x] 工作檯第一版
- [x] 交接、進度、路線圖文件
