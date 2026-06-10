#!/usr/bin/env python3
"""
從 all_vets.json 產生 frontend/data/vets.js（前端使用的 slim 格式）
================================================================
- 加 is_24h 自動偵測（regex on name + business_hours）
- 加手動 24h 急診名單（KNOWN_24H）
- 加 lat/lng（如已 geocode）
- 短鍵減少體積：n=name, t=tel, a=address, c=city, d=district,
                g=gmaps_url, h=hours, e=is_24h, lat, lng
"""
from __future__ import annotations
import json
import re
import sys
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


def main():
    data = json.loads(SRC.read_text(encoding="utf-8"))
    print(f"[Load] {len(data)} vets")

    slim = []
    n_24h = 0
    n_cat = 0
    n_geo = 0
    for v in data:
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
        if v.get("lat") and v.get("lng"):
            item["lat"] = v["lat"]
            item["lng"] = v["lng"]
            n_geo += 1
        slim.append(item)

    js = "window.VETS = " + json.dumps(slim, ensure_ascii=False, separators=(",", ":")) + ";\n"
    DST.write_text(js, encoding="utf-8")
    print(f"[Out] {DST}  ({len(slim)} vets, {n_24h} 24h, {n_cat} cat-friendly, {n_geo} geocoded)")


if __name__ == "__main__":
    main()
