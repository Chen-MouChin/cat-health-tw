#!/usr/bin/env python3
"""
TheCatAPI 品種爬蟲
================
抓取常見貓咪品種的結構化資料 + 圖片 URL。

輸出：data/breeds/raw_thecatapi.json

API 說明：
- https://api.thecatapi.com/v1/breeds  ← 全部品種
- https://api.thecatapi.com/v1/breeds/{id}  ← 單一品種
- https://api.thecatapi.com/v1/images/search?breed_ids={id}&limit=5  ← 該品種圖片
- 不需要 API key（但有 rate limit ~10 req/min）
- 進階用 key：免費註冊 https://thecatapi.com → 設定 THECATAPI_KEY 環境變數

第一批：台灣常見 10 種（見 research/breeds-progress.md）
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).parent.parent
OUT_DIR = ROOT / "data" / "breeds"
OUT_PATH = OUT_DIR / "raw_thecatapi.json"

API_BASE = "https://api.thecatapi.com/v1"
API_KEY = os.environ.get("THECATAPI_KEY", "").strip()

# 抓全部 67 品種（TheCatAPI 收錄全數）
# 未列於 BREED_NAME_ZH 的會用英文名呈現，待未來人工翻譯
COMMON_BREED_IDS = None  # None = 抓全部

# 67 品種中文名對照（多數為台灣愛貓協會/常見譯法；拉丁/罕見譯以音譯）
BREED_NAME_ZH = {
    "abob": "美國短尾貓",
    "abys": "阿比西尼亞貓",
    "acur": "美國捲耳貓",
    "aege": "愛琴海貓",
    "amau": "阿拉伯梅奧貓",
    "amis": "澳洲霧貓",
    "asho": "美國短毛貓",
    "awir": "美國硬毛貓",
    "bali": "峇里貓",
    "bamb": "矮腳貓（Bambino）",
    "beng": "孟加拉貓",
    "birm": "伯曼貓",
    "bomb": "孟買貓",
    "bsho": "英國短毛貓",
    "bslo": "英國長毛貓",
    "bure": "緬甸貓",
    "buri": "緬甸玳瑁貓",
    "char": "沙特爾貓",
    "chau": "喬西貓",
    "chee": "奇多貓",
    "crex": "康瓦耳捲毛貓",
    "csho": "重點色短毛貓",
    "cspa": "加州閃亮貓",
    "ctif": "香緹蒂芬妮貓",
    "cymr": "曼島長毛貓",
    "cypr": "塞普勒斯貓",
    "dons": "頓斯科伊貓",
    "drex": "德文捲毛貓",
    "ebur": "歐洲緬甸貓",
    "emau": "埃及貓",
    "esho": "異國短毛貓",
    "hbro": "哈瓦那棕貓",
    "hima": "喜馬拉雅貓",
    "java": "爪哇貓",
    "jbob": "日本短尾貓",
    "khao": "暹羅玉貓",
    "kora": "科拉特貓",
    "kuri": "千島貓",
    "lape": "拉邦貓",
    "lihu": "中國狸花貓",
    "mala": "馬來亞貓",
    "manx": "曼島貓",
    "mcoo": "緬因貓",
    "munc": "曼赤肯短腿貓",
    "nebe": "尼比隆貓",
    "norw": "挪威森林貓",
    "ocic": "歐西貓",
    "orie": "東方貓",
    "pers": "波斯貓",
    "pixi": "狸貓（Pixie-bob）",
    "raga": "襤褸貓",
    "ragd": "布偶貓",
    "rblu": "俄羅斯藍貓",
    "sava": "沙瓦娜貓",
    "sfol": "蘇格蘭摺耳貓",
    "siam": "暹羅貓",
    "sibe": "西伯利亞貓",
    "sing": "新加坡貓",
    "snow": "雪鞋貓",
    "soma": "索馬利貓",
    "sphy": "斯芬克斯無毛貓",
    "srex": "塞爾凱克捲毛貓",
    "tang": "土耳其安哥拉貓",
    "tonk": "東奇尼貓",
    "toyg": "玩具虎貓",
    "tvan": "土耳其梵貓",
    "ycho": "約克巧克力貓",
}


def http_get(url: str, retries: int = 3, delay: float = 2.0) -> dict | list:
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; NekoPediaBot/1.0; +https://chen-mouchin.github.io/cat-health-tw)",
    }
    if API_KEY:
        headers["x-api-key"] = API_KEY

    for attempt in range(retries):
        try:
            req = Request(url, headers=headers)
            with urlopen(req, timeout=15) as r:
                return json.loads(r.read().decode("utf-8"))
        except HTTPError as e:
            if e.code == 429 and attempt < retries - 1:
                wait = delay * (2 ** attempt)
                print(f"  [429] rate limited, waiting {wait}s...")
                time.sleep(wait)
                continue
            raise
        except (URLError, TimeoutError) as e:
            if attempt < retries - 1:
                wait = delay * (2 ** attempt)
                print(f"  [retry {attempt+1}] {e}, waiting {wait}s...")
                time.sleep(wait)
                continue
            raise


def fetch_breed(breed_id: str) -> dict:
    print(f"[{breed_id}] {BREED_NAME_ZH.get(breed_id, '?')}")
    breed = http_get(f"{API_BASE}/breeds/{breed_id}")
    if not breed:
        print(f"  [WARN] empty response")
        return {}

    # 抓 5 張圖
    time.sleep(1.5)
    images = http_get(f"{API_BASE}/images/search?breed_ids={breed_id}&limit=5")
    image_urls = [img.get("url") for img in (images or []) if img.get("url")]

    return {
        "id": breed_id,
        "name_en": breed.get("name", ""),
        "name_zh_hint": BREED_NAME_ZH.get(breed_id, ""),
        "alt_names": breed.get("alt_names", "").split(",") if breed.get("alt_names") else [],
        "origin": breed.get("origin", ""),
        "country_code": breed.get("country_code", ""),
        "description_en": breed.get("description", ""),
        "temperament_en": [t.strip() for t in breed.get("temperament", "").split(",") if t.strip()],
        "life_span": breed.get("life_span", ""),  # e.g. "12 - 17"
        "weight": {
            "imperial": breed.get("weight", {}).get("imperial", ""),
            "metric": breed.get("weight", {}).get("metric", ""),
        },
        "scores": {
            "energy": breed.get("energy_level"),
            "grooming": breed.get("grooming"),
            "intelligence": breed.get("intelligence"),
            "affection": breed.get("affection_level"),
            "child_friendly": breed.get("child_friendly"),
            "stranger_friendly": breed.get("stranger_friendly"),
            "social_needs": breed.get("social_needs"),
            "vocalisation": breed.get("vocalisation"),
            "health_issues": breed.get("health_issues"),
            "shedding": breed.get("shedding_level"),
            "adaptability": breed.get("adaptability"),
        },
        "tags": {
            "hairless": bool(breed.get("hairless")),
            "natural": bool(breed.get("natural")),
            "rare": bool(breed.get("rare")),
            "rex": bool(breed.get("rex")),
            "suppressed_tail": bool(breed.get("suppressed_tail")),
            "short_legs": bool(breed.get("short_legs")),
            "hypoallergenic": bool(breed.get("hypoallergenic")),
            "indoor": bool(breed.get("indoor")),
            "lap": bool(breed.get("lap")),
        },
        "wikipedia_url": breed.get("wikipedia_url", ""),
        "images": image_urls,
        "_source": "thecatapi.com",
        "_fetched_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    # 若 COMMON_BREED_IDS 是 None，抓 /breeds 全部列表
    if COMMON_BREED_IDS is None:
        print("[TheCatAPI] fetching full breed list...")
        all_breeds = http_get(f"{API_BASE}/breeds")
        ids = [b["id"] for b in all_breeds]
        print(f"  Total: {len(ids)} breeds")
    else:
        ids = COMMON_BREED_IDS

    print(f"[TheCatAPI] fetching {len(ids)} breeds")
    print(f"  API key: {'set' if API_KEY else 'not set (using rate limited public access)'}")
    print()

    breeds = {}
    for i, bid in enumerate(ids, 1):
        print(f"({i}/{len(ids)})", end=" ")
        try:
            breeds[bid] = fetch_breed(bid)
        except Exception as e:
            print(f"  [ERROR] {bid}: {e}")
            breeds[bid] = {"id": bid, "_error": str(e)}
        # 禮貌延遲
        if i < len(ids):
            time.sleep(2.5)

    out = {
        "_meta": {
            "source": "thecatapi.com",
            "fetched_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "count": len(breeds),
            "api_key_used": bool(API_KEY),
        },
        "breeds": breeds,
    }
    OUT_PATH.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n[Done] {len(breeds)} breeds → {OUT_PATH}")
    ok = sum(1 for v in breeds.values() if "_error" not in v)
    print(f"  OK: {ok} / Error: {len(breeds) - ok}")


if __name__ == "__main__":
    main()
