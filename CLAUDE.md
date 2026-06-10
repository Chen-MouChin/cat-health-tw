# CLAUDE.md

## 專案概述

**貓健康站** — 台灣最專業的貓健康知識庫。

核心價值：有學術引用、有實操細節、沒有業配、不噁心廣告。

兩條主線：
1. **醫療知識文章**（SEO 長尾流量）→ 15-20 篇深度內容
2. **獸醫院導流**（六都 1,415 家）→ 地圖+篩選+評分

### 不做的事（已移除，見 research/archived-features.md）
- 商品比價爬蟲（程式碼已清除）
- 顏文字工具（移至 Neko-emoji-dev 獨立專案）
- 品種圖鑑（保留資料，降優先）

## 架構

```
neko-pedia/
├── CLAUDE.md
├── TODO.md
├── frontend/
│   ├── index.html          # 首頁（極簡，疾病入口+獸醫院）
│   ├── search.html          # 知識庫搜尋
│   ├── vets.html            # 獸醫院查詢（待建）
│   ├── about.html
│   ├── privacy.html
│   ├── robots.txt
│   ├── sitemap.xml
│   ├── articles/            # 文章 HTML
│   ├── css/
│   ├── js/
│   └── images/
├── content/
│   └── articles/            # Markdown 原始文章（104 篇，待篩選改寫）
├── scrapers/
│   ├── polite.py            # 統一延遲模組
│   └── vets/                # 獸醫院爬蟲（三層）
│       ├── layer1_opendata.py
│       ├── layer2_gmaps.py
│       ├── layer3_website.py
│       └── refresh_vets.sh
├── data/
│   └── vets/                # 獸醫院 JSON（1,415 家）
│       ├── all_vets.json
│       └── {city}_vets.json
└── research/
    ├── archived-features.md  # 已移除功能的架構記錄
    └── ...
```

## 開發指令

```bash
cd neko-pedia

# 獸醫院爬蟲
python scrapers/vets/layer1_opendata.py --all    # Layer 1: 政府 open data
python scrapers/vets/layer2_gmaps.py             # Layer 2: Google Maps URL

# 前端預覽
python -m http.server 8000 --directory frontend/
```

## 設計原則

- Plain HTML，無框架，無 build step
- 手機友善（RWD）
- 每頁最多 3 個 AdSense
- 免責聲明放在醫療內容前面
- 學術引用：ISFM / WSAVA / IRIS / PubMed open-access
- 不引用 Frontiers 期刊
