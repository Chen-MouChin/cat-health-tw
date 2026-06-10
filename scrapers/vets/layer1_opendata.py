#!/usr/bin/env python3
"""
Layer 1: 政府 open data 動物醫院登記清冊

用法：
  python scrapers/vets/layer1_opendata.py                 # 爬全部四都
  python scrapers/vets/layer1_opendata.py --city kaohsiung # 只爬高雄
  python scrapers/vets/layer1_opendata.py --merge          # 合併全台 → all_vets.json

資料來源：
  - 農業部全國 API（高雄、桃園用此）
  - 台中市 open data API（有業務類別欄位）
  - 台南市 open data API（有行政區欄位）
"""
import argparse
import json
import logging
import re
import time
import random
from datetime import datetime, timezone
from pathlib import Path

import requests

# 加入上層目錄讓 import 找到 polite
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
from polite import wait_api

logging.basicConfig(level=logging.INFO, format="%(asctime)s [vets-L1] %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("vets-L1")

PROJECT_ROOT = Path(__file__).parent.parent.parent
DATA_DIR = PROJECT_ROOT / "data" / "vets"
DATA_DIR.mkdir(parents=True, exist_ok=True)

NOW = datetime.now(timezone.utc).isoformat()
SESSION = requests.Session()
SESSION.headers.update({"User-Agent": "NekoPedia-VetBot/1.0 (vet clinic data; contact: https://chen-mouchin.github.io/cat-health-tw/about.html)"})

# ── 農業部全國 API ─────────────────────────────────────────────────────────
# 獸醫師(佐)開業執照，涵蓋全台 2000+ 筆
# https://data.gov.tw/dataset/8705
MOA_API = "https://data.moa.gov.tw/Service/OpenData/DataFileService.aspx?UnitId=078&IsTransData=1"

# ── 台中市 API ─────────────────────────────────────────────────────────────
# 臺中市合法動物醫院名冊（282 筆，有業務類別）
# https://data.gov.tw/dataset/83762
TAICHUNG_API = "https://newdatacenter.taichung.gov.tw/api/v1/no-auth/resource.download?rid=bb3f1ae3-e890-4c16-b5df-6a3a8676131f"

# ── 台南市 API ─────────────────────────────────────────────────────────────
# 臺南市動物醫院及診所名單（153 筆，有行政區）
# https://data.tainan.gov.tw/dataset/animalhospital
TAINAN_API = "https://soa.tainan.gov.tw/Api/Service/Get/f3baa10c-93ec-4bc5-b526-00959a5168ab"

# ── 城市設定 ───────────────────────────────────────────────────────────────

CITY_CONFIG = {
    "kaohsiung": {
        "name": "高雄市",
        "output": DATA_DIR / "kaohsiung_vets.json",
        "source": "農業部 open data (data.gov.tw/dataset/8705)",
    },
    "taichung": {
        "name": "台中市",
        "output": DATA_DIR / "taichung_vets.json",
        "source": "台中市 open data (data.gov.tw/dataset/83762)",
    },
    "tainan": {
        "name": "台南市",
        "output": DATA_DIR / "tainan_vets.json",
        "source": "台南市 open data (data.tainan.gov.tw/dataset/animalhospital)",
    },
    "taoyuan": {
        "name": "桃園市",
        "output": DATA_DIR / "taoyuan_vets.json",
        "source": "農業部 open data (data.gov.tw/dataset/8705)",
    },
    # 偏鄉擴充（2026-04-20）— 急診比都會更稀缺，更需要查詢入口
    "hsinchu_city": {
        "name": "新竹市",
        "output": DATA_DIR / "hsinchu_city_vets.json",
        "source": "農業部 open data (data.gov.tw/dataset/8705)",
    },
    "hsinchu_county": {
        "name": "新竹縣",
        "output": DATA_DIR / "hsinchu_county_vets.json",
        "source": "農業部 open data (data.gov.tw/dataset/8705)",
    },
    "yilan": {
        "name": "宜蘭縣",
        "output": DATA_DIR / "yilan_vets.json",
        "source": "農業部 open data (data.gov.tw/dataset/8705)",
    },
    "hualien": {
        "name": "花蓮縣",
        "output": DATA_DIR / "hualien_vets.json",
        "source": "農業部 open data (data.gov.tw/dataset/8705)",
    },
    "taitung": {
        "name": "台東縣",
        "output": DATA_DIR / "taitung_vets.json",
        "source": "農業部 open data (data.gov.tw/dataset/8705)",
    },
    # 全台補完（2026-04-21）— 其他媒體多半只做六都，我們做完整台灣
    "keelung": {
        "name": "基隆市",
        "output": DATA_DIR / "keelung_vets.json",
        "source": "農業部 open data (data.gov.tw/dataset/8705)",
    },
    "miaoli": {
        "name": "苗栗縣",
        "output": DATA_DIR / "miaoli_vets.json",
        "source": "農業部 open data (data.gov.tw/dataset/8705)",
    },
    "changhua": {
        "name": "彰化縣",
        "output": DATA_DIR / "changhua_vets.json",
        "source": "農業部 open data (data.gov.tw/dataset/8705)",
    },
    "nantou": {
        "name": "南投縣",
        "output": DATA_DIR / "nantou_vets.json",
        "source": "農業部 open data (data.gov.tw/dataset/8705)",
    },
    "yunlin": {
        "name": "雲林縣",
        "output": DATA_DIR / "yunlin_vets.json",
        "source": "農業部 open data (data.gov.tw/dataset/8705)",
    },
    "chiayi_city": {
        "name": "嘉義市",
        "output": DATA_DIR / "chiayi_city_vets.json",
        "source": "農業部 open data (data.gov.tw/dataset/8705)",
    },
    "chiayi_county": {
        "name": "嘉義縣",
        "output": DATA_DIR / "chiayi_county_vets.json",
        "source": "農業部 open data (data.gov.tw/dataset/8705)",
    },
    "pingtung": {
        "name": "屏東縣",
        "output": DATA_DIR / "pingtung_vets.json",
        "source": "農業部 open data (data.gov.tw/dataset/8705)",
    },
    "penghu": {
        "name": "澎湖縣",
        "output": DATA_DIR / "penghu_vets.json",
        "source": "農業部 open data (data.gov.tw/dataset/8705)",
    },
    "kinmen": {
        "name": "金門縣",
        "output": DATA_DIR / "kinmen_vets.json",
        "source": "農業部 open data (data.gov.tw/dataset/8705)",
    },
    "lienchiang": {
        "name": "連江縣",
        "output": DATA_DIR / "lienchiang_vets.json",
        "source": "農業部 open data (data.gov.tw/dataset/8705)",
    },
}

# 農業部 API 的縣市名用「臺」不是「台」(parser 兩種都試)
MOA_CITY_MAP = {
    "kaohsiung": "高雄市",
    "tainan": "台南市",
    "taoyuan": "桃園市",
    "hsinchu_city": "新竹市",
    "hsinchu_county": "新竹縣",
    "yilan": "宜蘭縣",
    "hualien": "花蓮縣",
    "taitung": "台東縣",
    "keelung": "基隆市",
    "miaoli": "苗栗縣",
    "changhua": "彰化縣",
    "nantou": "南投縣",
    "yunlin": "雲林縣",
    "chiayi_city": "嘉義市",
    "chiayi_county": "嘉義縣",
    "pingtung": "屏東縣",
    "penghu": "澎湖縣",
    "kinmen": "金門縣",
    "lienchiang": "連江縣",
}


def _delay():
    wait_api()


def _extract_district(address: str, city: str) -> str:
    """從地址提取行政區"""
    # 去掉縣市名前綴
    addr = address.replace(city, "").strip()
    m = re.match(r"([\u4e00-\u9fff]{2,3}[區鄉鎮市])", addr)
    return m.group(1) if m else ""


# ── 農業部全國 API parser ──────────────────────────────────────────────────

def _fetch_moa_all() -> list[dict]:
    """一次拉農業部全國資料（~2000 筆）"""
    log.info("Fetching MOA national API...")
    all_records = []
    skip = 0
    batch = 1000

    while True:
        url = f"{MOA_API}&$top={batch}&$skip={skip}"
        resp = SESSION.get(url, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        if not data:
            break
        all_records.extend(data)
        log.info(f"  fetched {len(data)} (total {len(all_records)})")
        if len(data) < batch:
            break
        skip += batch
        _delay()

    log.info(f"MOA total: {len(all_records)}")
    return all_records


_moa_cache: list[dict] | None = None


def _get_moa_data() -> list[dict]:
    global _moa_cache
    if _moa_cache is None:
        _moa_cache = _fetch_moa_all()
    return _moa_cache


def _parse_moa_city(city_key: str) -> list[dict]:
    """從農業部 API 篩選指定城市"""
    moa_city_name = MOA_CITY_MAP.get(city_key, CITY_CONFIG[city_key]["name"])
    all_data = _get_moa_data()

    # 農業部用「臺」，我們也試「台」
    alt_name = moa_city_name.replace("台", "臺")
    records = [r for r in all_data if r.get("縣市") in (moa_city_name, alt_name)]

    # 只留開業中
    active = [r for r in records if r.get("狀態") == "開業"]
    log.info(f"  {moa_city_name}: {len(records)} total, {len(active)} active")

    result = []
    for r in active:
        addr = r.get("機構地址", "")
        city_display = CITY_CONFIG[city_key]["name"]
        result.append({
            "name": r.get("機構名稱", "").strip(),
            "city": city_display,
            "district": _extract_district(addr, city_display),
            "address": addr.strip(),
            "tel": r.get("機構電話", "").strip(),
            "business_hours": "",
            "vet_name": r.get("負責獸醫", "").strip(),
            "license": r.get("字號", "").strip(),
            "source": CITY_CONFIG[city_key]["source"],
            "crawled_at": NOW,
        })
    return result


# ── 台中市 parser ──────────────────────────────────────────────────────────

def _parse_taichung() -> list[dict]:
    """台中市合法動物醫院名冊"""
    log.info("Fetching Taichung city API...")
    resp = SESSION.get(TAICHUNG_API, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    log.info(f"  Taichung: {len(data)} records")

    result = []
    for r in data:
        name = r.get("醫院名稱", "").strip()
        addr = r.get("地址-街路門牌", "").strip()
        services = r.get("業務類別", "")
        result.append({
            "name": name,
            "city": "台中市",
            "district": _extract_district(addr, "台中市") if addr else "",
            "address": addr,
            "tel": r.get("電話", "").strip(),
            "business_hours": "",
            "license": r.get("開業證號", "").strip(),
            "services": services,
            "source": CITY_CONFIG["taichung"]["source"],
            "crawled_at": NOW,
        })
    return result


# ── 台南市 parser ──────────────────────────────────────────────────────────

def _parse_tainan() -> list[dict]:
    """台南市動物醫院 — 先試 city API，失敗用農業部 API fallback"""
    log.info("Fetching Tainan city API...")
    try:
        resp = SESSION.get(TAINAN_API, timeout=30)
        resp.raise_for_status()
        raw = resp.json()
        # 台南 API 回傳 wrapper dict，實際資料在 data 欄位
        if isinstance(raw, dict):
            data = raw.get("data") or []
        else:
            data = raw
        data = [r for r in data if isinstance(r, dict)]
        if len(data) >= 50:
            log.info(f"  Tainan city API: {len(data)} records")
            active = [r for r in data if r.get("狀態") == "開業"]
            result = []
            for r in active:
                village = r.get("Village", "").strip()
                street = r.get("StreetDoorPlate", "").strip()
                addr = f"台南市{village}{street}" if village else street
                result.append({
                    "name": r.get("機構名稱", "").strip(),
                    "city": "台南市",
                    "district": village,
                    "address": addr,
                    "tel": r.get("機構電話", "").strip(),
                    "business_hours": "",
                    "vet_name": r.get("負責獸醫", "").strip(),
                    "license": r.get("字號", "").strip(),
                    "source": CITY_CONFIG["tainan"]["source"],
                    "crawled_at": NOW,
                })
            return result
    except Exception as e:
        log.warning(f"  Tainan city API failed: {e}")

    # Fallback: 農業部 API
    log.info("  Falling back to MOA national API for Tainan...")
    return _parse_moa_city("tainan")


# ── dispatcher ─────────────────────────────────────────────────────────────

PARSERS = {
    "kaohsiung": lambda: _parse_moa_city("kaohsiung"),
    "taichung": _parse_taichung,
    "tainan": _parse_tainan,
    "taoyuan": lambda: _parse_moa_city("taoyuan"),
    "hsinchu_city": lambda: _parse_moa_city("hsinchu_city"),
    "hsinchu_county": lambda: _parse_moa_city("hsinchu_county"),
    "yilan": lambda: _parse_moa_city("yilan"),
    "hualien": lambda: _parse_moa_city("hualien"),
    "taitung": lambda: _parse_moa_city("taitung"),
    "keelung": lambda: _parse_moa_city("keelung"),
    "miaoli": lambda: _parse_moa_city("miaoli"),
    "changhua": lambda: _parse_moa_city("changhua"),
    "nantou": lambda: _parse_moa_city("nantou"),
    "yunlin": lambda: _parse_moa_city("yunlin"),
    "chiayi_city": lambda: _parse_moa_city("chiayi_city"),
    "chiayi_county": lambda: _parse_moa_city("chiayi_county"),
    "pingtung": lambda: _parse_moa_city("pingtung"),
    "penghu": lambda: _parse_moa_city("penghu"),
    "kinmen": lambda: _parse_moa_city("kinmen"),
    "lienchiang": lambda: _parse_moa_city("lienchiang"),
}


def scrape_city(city_key: str):
    cfg = CITY_CONFIG.get(city_key)
    if not cfg:
        log.error(f"Unknown city: {city_key}")
        return 0

    log.info(f"=== {cfg['name']} ===")
    parser_fn = PARSERS[city_key]
    results = parser_fn()

    if not results:
        log.warning(f"{cfg['name']}: 0 results")
        return 0

    cfg["output"].write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    log.info(f"{cfg['name']}: {len(results)} records -> {cfg['output']}")
    return len(results)


def merge_all():
    """合併全台獸醫院 -> all_vets.json
    重要：保留既有 all_vets.json 的 geocode（lat/lng/geocoded_at/geocoded_by）
    避免每次 merge 把跑了好幾分鐘的 OSM Nominatim 結果洗掉。
    """
    all_vets = []

    # 已有的雙北
    existing = DATA_DIR / "taipei_newtaipei_vets.json"
    if existing.exists():
        all_vets.extend(json.loads(existing.read_text(encoding="utf-8")))

    # 各城市
    for cfg in CITY_CONFIG.values():
        if cfg["output"].exists():
            city_data = json.loads(cfg["output"].read_text(encoding="utf-8"))
            all_vets.extend(city_data)

    # 從舊 all_vets.json 拉 geocode 回來（key = name+address）
    out = DATA_DIR / "all_vets.json"
    geo_map: dict[tuple[str, str], dict] = {}
    if out.exists():
        try:
            old = json.loads(out.read_text(encoding="utf-8"))
            for v in old:
                if v.get("lat") and v.get("lng"):
                    key = (v.get("name", "").strip(), v.get("address", "").strip())
                    geo_map[key] = {
                        "lat": v["lat"],
                        "lng": v["lng"],
                        "geocoded_at": v.get("geocoded_at"),
                        "geocoded_by": v.get("geocoded_by"),
                    }
            log.info(f"Preserving geocode from {len(geo_map)} existing entries")
        except Exception as e:
            log.warning(f"Could not load existing all_vets.json for geocode preservation: {e}")

    restored = 0
    for v in all_vets:
        key = (v.get("name", "").strip(), v.get("address", "").strip())
        if key in geo_map:
            for k, val in geo_map[key].items():
                if val is not None:
                    v[k] = val
            restored += 1

    out.write_text(json.dumps(all_vets, ensure_ascii=False, indent=2), encoding="utf-8")
    log.info(f"Merged: {len(all_vets)} total ({restored} geocodes preserved) -> {out}")

    # 統計
    from collections import Counter
    cities = Counter(v.get("city", "?") for v in all_vets)
    for c, n in cities.most_common():
        log.info(f"  {c}: {n}")

    return len(all_vets)


def main():
    parser = argparse.ArgumentParser(description="Layer 1: open data vet clinics")
    parser.add_argument("--city", help="Only scrape specified city (kaohsiung/taichung/tainan/taoyuan)")
    parser.add_argument("--merge", action="store_true", help="Merge all -> all_vets.json")
    parser.add_argument("--all", action="store_true", help="Scrape all + merge")
    args = parser.parse_args()

    if args.city:
        scrape_city(args.city)
    elif args.all:
        for city_key in CITY_CONFIG:
            scrape_city(city_key)
            _delay()
        merge_all()
    elif args.merge:
        merge_all()
    else:
        for city_key in CITY_CONFIG:
            scrape_city(city_key)
            _delay()
        merge_all()


if __name__ == "__main__":
    main()
