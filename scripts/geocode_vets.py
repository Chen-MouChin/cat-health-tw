#!/usr/bin/env python3
"""
獸醫院地址 → 經緯度（OSM Nominatim）
====================================
台灣地址格式問題：OSM 不認 "X路Y號"，需要拆成 "Y號 X路 區 市"。
本腳本會嘗試多種格式直到命中。

OSM Nominatim 政策：
- 速率：≤ 1 req/s（我們用 1.5 秒，禮貌一點）
- User-Agent 必須含聯絡資訊
- https://operations.osmfoundation.org/policies/nominatim/

可中斷續跑：lat/lng 已存在的會跳過。
"""
from __future__ import annotations
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).parent.parent
VETS = ROOT / "data" / "vets" / "all_vets.json"
FAIL_LOG = ROOT / "data" / "vets" / "geocode-failures.json"

USER_AGENT = "NekoPedia/1.0 (https://chen-mouchin.github.io/cat-health-tw/about.html; https://chen-mouchin.github.io/cat-health-tw)"
RATE_SLEEP = 1.5  # 秒，OSM 政策上限為 1 req/s


def parse_address(addr, city, district):
    """從台灣地址提取門牌號 + 街道名。

    範例：
      "新北市新莊區中正路427-2號" → ("427-2", "中正路")
      "台中市西屯區台灣大道三段108號" → ("108", "台灣大道三段")
      "桃園市中壢區中山路 100 之 2 號" → ("100-2", "中山路")
    """
    # 移除城市/區塊（避免重複）
    s = addr
    if city:
        s = s.replace(city, "")
    if district:
        s = s.replace(district, "")
    s = s.strip()

    # 嘗試抓門牌號（X號 / X-Y號 / X之Y號）
    # pattern: 數字+選擇性「-Y」或「之Y」+號
    m = re.search(r"(\d+(?:[-之]\d+)?)\s*號", s)
    if m:
        no = m.group(1).replace("之", "-")
        street = s[:m.start()].strip()
        return no, street

    # 抓不到門牌號 → street 用全部
    return None, s


def try_query(q):
    """單次 OSM 查詢，回傳 (lat, lng) 或 None。"""
    url = "https://nominatim.openstreetmap.org/search?" + urllib.parse.urlencode({
        "q": q,
        "format": "json",
        "limit": 1,
        "countrycodes": "tw",
    })
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            data = json.loads(r.read())
            if data:
                return float(data[0]["lat"]), float(data[0]["lon"])
    except Exception:
        return None
    return None


def geocode(addr, city, district):
    """嘗試多種格式直到命中。

    回傳 (lat, lng, used_query) 或 (None, None, None)。
    每次查詢之間都會 sleep（在呼叫端控制總速率）。
    """
    no, street = parse_address(addr, city, district)
    attempts = []

    if no and street:
        # 主推格式：「號 街道 區 市」OSM 對這個最友善
        attempts.append(f"{no}號 {street} {district} {city}")
        attempts.append(f"{no} {street} {district} {city}")

    if street:
        # fallback 1：街道+區+市（精度差但能命中）
        attempts.append(f"{street} {district} {city}")

    # fallback 2：原始地址（OSM 偶爾會通）
    attempts.append(addr)

    # fallback 3：只有區+市（最差，但至少有區中心點）
    attempts.append(f"{district} {city}")

    for q in attempts:
        if not q.strip():
            continue
        result = try_query(q)
        if result:
            return result[0], result[1], q
        time.sleep(RATE_SLEEP)  # 失敗也要間隔

    return None, None, None


def main():
    data = json.loads(VETS.read_text(encoding="utf-8"))
    total = len(data)
    print(f"[Load] {total} vets", flush=True)

    have_latlng = sum(1 for v in data if v.get("lat") and v.get("lng"))
    todo = [(i, v) for i, v in enumerate(data) if not (v.get("lat") and v.get("lng"))]
    print(f"[Status] 已有 {have_latlng}, 待處理 {len(todo)}", flush=True)
    print(f"[ETA] 約 {len(todo) * RATE_SLEEP * 1.5 / 60:.0f} 分鐘（含失敗 retry）", flush=True)

    failures = []
    success = 0
    save_every = 30

    for idx, (orig_i, vet) in enumerate(todo, 1):
        addr = vet.get("address", "").strip()
        city = vet.get("city", "").strip()
        district = vet.get("district", "").strip()
        if not addr or not city:
            failures.append({"i": orig_i, "name": vet.get("name"), "reason": "no address/city"})
            continue

        lat, lng, q = geocode(addr, city, district)
        if lat is not None:
            vet["lat"] = lat
            vet["lng"] = lng
            vet["geocoded_at"] = time.strftime("%Y-%m-%d")
            vet["geocoded_by"] = "osm-nominatim"
            success += 1
            status = "✓"
        else:
            failures.append({
                "i": orig_i,
                "name": vet.get("name"),
                "address": addr,
                "city": city,
                "district": district,
                "reason": "no result (all formats failed)",
            })
            status = "✗"

        if idx % 5 == 0 or idx == len(todo):
            rate = success / idx * 100
            print(f"  [{idx}/{len(todo)}] {status} {vet.get('name','')[:20]} — 成功 {success} ({rate:.0f}%)", flush=True)

        if idx % save_every == 0:
            VETS.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"    [Saved] {idx}/{len(todo)}", flush=True)

        time.sleep(RATE_SLEEP)

    # 最終存檔
    VETS.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    if failures:
        FAIL_LOG.write_text(json.dumps(failures, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n[Done] 成功 {success} / 失敗 {len(failures)} / 總共 {len(todo)}", flush=True)
    print(f"  → {VETS}", flush=True)
    if failures:
        print(f"  → {FAIL_LOG}", flush=True)


if __name__ == "__main__":
    main()
