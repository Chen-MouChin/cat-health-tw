# 獸醫院爬蟲 — 三層建置

## 架構

```
scrapers/vets/
├── README.md              # 本文件
├── __init__.py
├── layer1_opendata.py     # Layer 1: 政府 open data 登記清冊
├── layer2_gmaps.py        # Layer 2: Google Maps 連結 + 評分
├── layer3_website.py      # Layer 3: 官網/部落格偵測
└── refresh_vets.sh        # 一鍵執行全部
```

輸出到 `data/vets/`：
```
data/vets/
├── taipei_newtaipei_vets.json   # 已有（553 家）
├── kaohsiung_vets.json          # Layer 1 產出
├── taichung_vets.json           # Layer 1 產出
├── tainan_vets.json             # Layer 1 產出
├── taoyuan_vets.json            # Layer 1 產出
└── all_vets.json                # 合併全台（Layer 1 完成後產出）
```

## 城市優先序

1. 雙北（已完成）
2. 高雄
3. 台中
4. 台南
5. 桃園

## Layer 說明

### Layer 1：政府 open data

每個城市的動物醫院登記清冊，來源為各縣市政府 open data 平台。

輸出欄位：
- `name` — 醫院名稱
- `city` — 縣市
- `district` — 區
- `address` — 完整地址
- `tel` — 電話
- `business_hours` — 營業時間（有的話）
- `source` — 資料來源 URL
- `crawled_at` — 抓取時間

### Layer 2：Google Maps

用 Layer 1 的名稱+地址查 Google Maps，補充：
- `gmaps_url` — Google Maps 連結
- `gmaps_place_id` — Place ID
- `gmaps_rating` — 評分
- `gmaps_reviews` — 評論數

### Layer 3：官網/部落格偵測

掃描每家獸醫院是否有官網，官網是否有衛教文章：
- `website` — 官網 URL
- `has_blog` — 是否有部落格/衛教文章區
- `blog_url` — 部落格 URL
- `fb_page` — Facebook 粉專 URL
