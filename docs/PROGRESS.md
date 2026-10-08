# 進度紀錄

由新到舊。每次有實質進展就加一段，數字以當天為準。

---

## 目前狀態（2026-09-06）

| 指標 | 數字 | 上線門檻 |
|---|---|---|
| 文章總數 | 56 篇（另 71 篇在 `_archived/`） | |
| 文章 reviewed + featured | 0 | 軟上線 10，正式 30 |
| 依 skill 模板深度改寫完成 | 10 篇 | |
| 寫作規範 lint | FAIL 0，WARN 213（多為數值無出處） | FAIL 0 |
| 句內註腳 | 108 個，涵蓋 42 筆文獻 | |
| 文獻總數 | 109 筆 | |
| 文獻 approved | 14 | 40 |
| 文獻 url 已驗證 | 80（73%） | 90% |
| 文獻中文摘要 | 79（72%） | 80% |
| 獸醫院 | 2,001 家，22 縣市，100% 有座標 | |
| sitemap 收錄文章 | 0 篇（全部 draft） | |
| 網域 | 無 | 有 |
| AdSense | 未申請 | |

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
