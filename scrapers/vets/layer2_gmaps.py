#!/usr/bin/env python3
"""
Layer 2: Google Maps 連結 + 評分

用法：
  python scrapers/vets/layer2_gmaps.py                     # 處理 all_vets.json
  python scrapers/vets/layer2_gmaps.py --city 台北市         # 只處理指定城市
  python scrapers/vets/layer2_gmaps.py --limit 50           # 只處理前 50 筆

前置條件：Layer 1 完成（all_vets.json 或各城市 JSON 存在）

方案選擇（擇一）：
  A. Google Places API（需 API key，精準但有費用）
  B. Google Maps 搜尋 URL 拼接（免費，不需 API key，但沒有評分）
  C. 爬 Google Maps 頁面（灰色地帶，可能被封）

MVP 先用方案 B（拼 URL），之後有 API key 再升級方案 A。
"""
import argparse
import json
import logging
import urllib.parse
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s [vets-L2] %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("vets-L2")

PROJECT_ROOT = Path(__file__).parent.parent.parent
DATA_DIR = PROJECT_ROOT / "data" / "vets"


def build_gmaps_url(name: str, address: str) -> str:
    """用名稱+地址拼 Google Maps 搜尋 URL"""
    query = f"{name} {address}"
    return f"https://www.google.com/maps/search/?api=1&query={urllib.parse.quote(query)}"


def enrich_with_gmaps(vets: list[dict]) -> list[dict]:
    """為每筆獸醫院加上 gmaps_url"""
    enriched = 0
    for vet in vets:
        if vet.get("gmaps_url"):
            continue
        name = vet.get("name", "")
        address = vet.get("address", "")
        if name:
            vet["gmaps_url"] = build_gmaps_url(name, address)
            enriched += 1
    log.info(f"Enriched {enriched} records with Google Maps URL")
    return vets


# TODO: Google Places API 版本（需 API key）
# def enrich_with_places_api(vets, api_key):
#     """用 Google Places API 取得 place_id, rating, reviews"""
#     for vet in vets:
#         query = f"{vet['name']} {vet['address']}"
#         resp = requests.get(
#             "https://maps.googleapis.com/maps/api/place/findplacefromtext/json",
#             params={"input": query, "inputtype": "textquery",
#                     "fields": "place_id,rating,user_ratings_total",
#                     "key": api_key}
#         )
#         ...


def main():
    parser = argparse.ArgumentParser(description="Layer 2: Google Maps enrichment")
    parser.add_argument("--input", default=str(DATA_DIR / "all_vets.json"), help="輸入 JSON")
    parser.add_argument("--city", help="只處理指定城市")
    parser.add_argument("--limit", type=int, help="只處理前 N 筆")
    args = parser.parse_args()

    input_path = Path(args.input)
    if not input_path.exists():
        log.error(f"{input_path} not found. Run layer1_opendata.py --merge first.")
        return

    vets = json.loads(input_path.read_text(encoding="utf-8"))
    log.info(f"Loaded {len(vets)} records from {input_path}")

    if args.city:
        vets = [v for v in vets if v.get("city") == args.city]
        log.info(f"Filtered to {len(vets)} for {args.city}")

    if args.limit:
        vets = vets[:args.limit]

    vets = enrich_with_gmaps(vets)

    input_path.write_text(
        json.dumps(vets, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    log.info(f"Saved back to {input_path}")


if __name__ == "__main__":
    main()
