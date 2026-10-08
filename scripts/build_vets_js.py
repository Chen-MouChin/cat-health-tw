#!/usr/bin/env python3
"""
從 all_vets.json 產生 frontend/data/vets.js（前端使用的 slim 格式）
================================================================
- 加 is_24h 自動偵測（regex on name + business_hours）
- 加手動 24h 急診名單（KNOWN_24H）
- 加 lat/lng（如已 geocode）
- 加座標可信度 ap（見 coord_quality）；ap=2 的不輸出 lat/lng
- 短鍵減少體積：n=name, t=tel, a=address, c=city, d=district,
                g=gmaps_url, h=hours, e=is_24h, cat=貓專科, ap=座標可信度, lat, lng
"""
from __future__ import annotations
import heapq
import json
import math
import re
import statistics
import sys
from collections import defaultdict
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).parent.parent
SRC = ROOT / "data" / "vets" / "all_vets.json"
DST = ROOT / "frontend" / "data" / "vets.js"

# 已知 24h 急診醫院（人工維護，name 子字串比對）
# 來源：2026-04 Google 搜尋全台 6 都 + 業界常識
# 規則：僅列出明確標榜「24h」或「夜間急診」服務的醫院；連鎖會自動 catch 分院
KNOWN_24H = {
    # 全國連鎖（多分院 24h）
    "全國動物醫院",
    "慈愛動物醫院",
    "太僕動物醫院",
    "中興動物醫院",
    # 台北市
    "大安動物醫院",
    "全民連鎖動物醫院",
    "伊甸動物醫院",        # 北安路（不同於伊甸園）
    "伊甸園動物醫院",
    "杜克動物醫院",
    "展望動物醫院",
    "永春動物醫院",
    "布達羊急診動物醫院",
    "東湖動物醫院",
    "大群動物醫院",
    "聖地牙哥動物醫院",
    "蘇珊動物醫院",
    "夜間急診動物醫院",
    # 新北市
    "亞東動物醫院",
    "上弦動物醫院",        # 林口 + 板橋分院
    "中日動物醫院",
    "牧村動物醫院",
    "板橋中山動物醫院",
    # 桃園市
    "元氣動物醫院",        # 三民總院 + 南崁分院
    "品湛動物醫院",
    "青谷動物醫院",
    "磨鼻子動物醫院",
    # 台中市
    "夏洛克動物醫院",
    "艾利動物醫院",
    # 高雄市
    "宏力動物醫院",        # 三民 + 鳳山光復院
    "順心動物醫院",
    "希望動物醫院",
    "聯盟動物醫院",
    # 台南市
    "佳愛動物醫院",
    "凱旋動物醫院",
}

# 24h regex
RE_24H = re.compile(r"24\s*[小時hH]|24\s*[/-]?\s*7|急診|全天|夜間急診")

# ─────────────────────────────────────────
# 貓專科 / 貓友善偵測
# ─────────────────────────────────────────
# 名字含「貓」字 → 通常為貓專科或貓友善（排除誤判：「家畜」醫院不算）
RE_CAT_NAME = re.compile(r"貓|cat", re.IGNORECASE)
RE_LIVESTOCK = re.compile(r"家畜")  # 「家畜醫院」是傳統用詞，不是貓專科

# ISFM Cat Friendly Clinic 認證名單（國際公認標準）
# 來源：https://catfriendlyclinic.org/find-a-clinic/
# 維護方式：每季手動核對，加入 / 移除認證醫院（部分匹配）
# 註：這份清單目前為示範性質（小幫手 TODO：完整爬 ISFM 官網）
KNOWN_ISFM_CAT_FRIENDLY = {
    # TODO 小幫手補：去 catfriendlyclinic.org 找台灣 (Taiwan) 認證醫院
    # 範例（實際需查證）：
    # "貓本部 Cat Hospital",
    # "中山動物醫院",
}

# 已知貓專科 / 貓友善醫院（人工維護，補強 regex 抓不到的）
# 規則：單一物種貓門診 / 公開標榜貓專科服務
KNOWN_CAT_ONLY = {
    # TODO 小幫手補：PTT cat 板搜尋「貓專科」「貓醫院」彙整
}


def detect_cat_friendly(vet):
    """貓專科 / 貓友善偵測：1) 已知名單  2) 名字含「貓」且非家畜醫院"""
    name = vet.get("name", "") or ""

    # 1) 已知名單
    for known in KNOWN_ISFM_CAT_FRIENDLY | KNOWN_CAT_ONLY:
        if known in name:
            return True

    # 2) 名字含「貓」字（排除傳統「家畜醫院」）
    if RE_CAT_NAME.search(name) and not RE_LIVESTOCK.search(name):
        return True

    return False


def detect_24h(vet):
    """三層偵測：1) 已知名單  2) 名字含 24/急診/夜間  3) 營業時間含 24"""
    name = vet.get("name", "") or ""
    hours = vet.get("business_hours", "") or ""
    services = vet.get("services", "") or ""
    if isinstance(services, list):
        services = " ".join(str(s) for s in services)

    # 1) 已知名單（部分匹配）
    for known in KNOWN_24H:
        if known in name:
            return True

    # 2) 名字 / 服務 / 營業時間 regex
    if RE_24H.search(name):
        return True
    if RE_24H.search(services):
        return True
    if RE_24H.search(hours):
        return True

    return False


# ─────────────────────────────────────────
# 座標可信度（前端「找我附近」用）
# ─────────────────────────────────────────
# geocode_vets.py 查不到門牌時會退回「街道 / 區 / 縣市」中心點；
# 地址缺縣市、區前綴（台南、台中常見）時還可能對到別縣市的同名路。
# 這裡只在產出 vets.js 時標記，不改 all_vets.json：
#   ap=1  跟其他不同地址的醫院共用同一點 → 多半是街道或行政區中心，距離只能當約略值
#   ap=2  座標落在別的縣市，或離同區其他醫院太遠 → 不輸出 lat/lng，前端不拿它算距離
OUTLIER_KM = 15   # 最近的同縣市醫院、或同區中位點超過這個距離 → 視為錯位
KNN = 5           # 最近 5 家全在別縣市 → 視為落在別縣市
MIN_GROUP = 4     # 同區至少幾家才用中位點判斷
RE_DISTRICT = re.compile(r"^([^\d\s]{1,3}?[區鄉鎮市])")


def _km(lat1, lng1, lat2, lng2):
    """等距圓柱近似距離（km）。台灣尺度誤差遠小於門檻，比 Haversine 快。"""
    x = math.radians(lng2 - lng1) * math.cos(math.radians((lat1 + lat2) / 2))
    y = math.radians(lat2 - lat1)
    return 6371 * math.hypot(x, y)


def _norm_addr(s):
    return re.sub(r"\s+", "", s or "").replace("臺", "台")


def _district_key(vet):
    """行政區：優先用 district 欄位，否則從地址開頭（去掉縣市後）抽「XX區/鄉/鎮/市」。"""
    d = (vet.get("district") or "").replace("臺", "台")
    if d:
        return d
    addr = _norm_addr(vet.get("address")).replace(vet.get("city", "") or "", "")
    m = RE_DISTRICT.match(addr)
    return m.group(1) if m else ""


def coord_quality(data):
    """回傳 {index: 1 或 2}；沒列入的代表座標看起來正常。"""
    pts = [(i, v) for i, v in enumerate(data) if v.get("lat") and v.get("lng")]
    flags = {}

    # ap=2 (a) 落在別縣市：最近的同縣市醫院超過 OUTLIER_KM，且最近 KNN 家全是別縣市
    for i, v in pts:
        city = v.get("city")
        dists = [(_km(v["lat"], v["lng"], w["lat"], w["lng"]), w.get("city"))
                 for j, w in pts if j != i]
        same_city = min((d for d, c in dists if c == city), default=math.inf)
        # 該縣市只有這一家時沒得比（例：離島只有一家），不判
        if same_city <= OUTLIER_KM or same_city == math.inf:
            continue
        if all(c != city for _, c in heapq.nsmallest(KNN, dists)):
            flags[i] = 2

    # ap=2 (b) 離同區中位點太遠（兩家以上一起錯位到別縣市時 (a) 抓不到）
    groups = defaultdict(list)
    for i, v in pts:
        dk = _district_key(v)
        if dk:
            groups[(v.get("city"), dk)].append((i, v))
    for members in groups.values():
        if len(members) < MIN_GROUP:
            continue
        mlat = statistics.median(v["lat"] for _, v in members)
        mlng = statistics.median(v["lng"] for _, v in members)
        for i, v in members:
            if _km(mlat, mlng, v["lat"], v["lng"]) > OUTLIER_KM:
                flags[i] = 2

    # ap=1 同一點上有不同地址（同址分院不算）
    by_point = defaultdict(list)
    for i, v in pts:
        by_point[(round(v["lat"], 6), round(v["lng"], 6))].append(i)
    for idx in by_point.values():
        if len({_norm_addr(data[i].get("address")) for i in idx}) >= 2:
            for i in idx:
                flags.setdefault(i, 1)
    return flags


def main():
    data = json.loads(SRC.read_text(encoding="utf-8"))
    print(f"[Load] {len(data)} vets")

    quality = coord_quality(data)

    slim = []
    n_24h = 0
    n_cat = 0
    n_geo = 0
    for i, v in enumerate(data):
        is_24h = detect_24h(v)
        is_cat = detect_cat_friendly(v)
        if is_24h:
            n_24h += 1
        if is_cat:
            n_cat += 1
        item = {
            "n": v.get("name", "") or "",
            "t": v.get("tel", "") or "",
            "a": v.get("address", "") or "",
            "c": v.get("city", "") or "",
            "d": v.get("district", "") or "",
            "g": v.get("gmaps_url", "") or "",
            "h": v.get("business_hours", "") or "",
        }
        if is_24h:
            item["e"] = 1
        if is_cat:
            item["cat"] = 1
        if i in quality:
            item["ap"] = quality[i]
        if v.get("lat") and v.get("lng") and quality.get(i) != 2:
            item["lat"] = v["lat"]
            item["lng"] = v["lng"]
            n_geo += 1
        slim.append(item)

    js = "window.VETS = " + json.dumps(slim, ensure_ascii=False, separators=(",", ":")) + ";\n"
    DST.write_text(js, encoding="utf-8")
    n_ap1 = sum(1 for q in quality.values() if q == 1)
    n_ap2 = sum(1 for q in quality.values() if q == 2)
    print(f"[Out] {DST}  ({len(slim)} vets, {n_24h} 24h, {n_cat} cat-friendly, {n_geo} geocoded)")
    print(f"[Geo] 約略座標 ap=1: {n_ap1} · 疑似錯位 ap=2（已拿掉座標）: {n_ap2}")
    for i, q in sorted(quality.items()):
        if q == 2:
            v = data[i]
            print(f"  ap=2 {v.get('city')} {v.get('name')} | {v.get('address')} → {v['lat']:.4f},{v['lng']:.4f}")


if __name__ == "__main__":
    main()
