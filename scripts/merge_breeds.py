#!/usr/bin/env python3
"""
合併品種資料 → 前端格式
=====================
讀取：
  data/breeds/raw_thecatapi.json
  data/breeds/translations.json
  data/breeds/manual_overrides.json（可選，手補台灣化資訊）
輸出：
  data/breeds/breeds.json      → 前端用主資料
  frontend/data/breeds.js      → window.BREEDS 給 breeds.html 讀
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).parent.parent
RAW = ROOT / "data" / "breeds" / "raw_thecatapi.json"
TRANS = ROOT / "data" / "breeds" / "translations.json"
OVERRIDES = ROOT / "data" / "breeds" / "manual_overrides.json"
OUT_JSON = ROOT / "data" / "breeds" / "breeds.json"
OUT_JS = ROOT / "frontend" / "data" / "breeds.js"


def parse_range(s: str) -> list[float]:
    """解析 '12 - 17' 或 '5 - 9' 為 [12.0, 17.0]"""
    if not s:
        return []
    nums = re.findall(r"\d+(?:\.\d+)?", s)
    return [float(n) for n in nums[:2]]


def translate_temperament(en_list: list[str], dic: dict) -> list[str]:
    """英文性格詞 → 中文，未知保留英文
    大小寫不敏感：'Calm' / 'calm' / 'CALM' 都匹配到同一個翻譯"""
    # 建立 lowercase 對照（保留第一個遇到的翻譯）
    lc_map = {}
    for k, v in dic.items():
        lc = k.lower()
        if lc not in lc_map:
            lc_map[lc] = v
    result = []
    for t in en_list:
        key = t.strip()
        zh = dic.get(key) or lc_map.get(key.lower()) or ""
        result.append(zh if zh else t)
    return result


def normalize_images(images):
    """統一圖片為 {url, author, license, source} 格式
    純 URL string → wrap to {url: ..., author/license/source: ''}（TheCatAPI 來源）
    """
    out = []
    for img in images:
        if isinstance(img, str):
            out.append({
                "url": img,
                "author": "",
                "license": "",
                "source": "thecatapi.com",
            })
        elif isinstance(img, dict) and img.get("url"):
            out.append({
                "url": img["url"],
                "author": img.get("author", ""),
                "license": img.get("license", ""),
                "source": img.get("source", ""),
            })
    return out


def main():
    raw = json.loads(RAW.read_text(encoding="utf-8"))
    trans = json.loads(TRANS.read_text(encoding="utf-8"))
    overrides = {}
    if OVERRIDES.exists():
        overrides = json.loads(OVERRIDES.read_text(encoding="utf-8"))
        overrides.pop("_meta", None)

    breeds = []

    # 1. 處理 TheCatAPI 來的品種
    for bid, b in raw["breeds"].items():
        if "_error" in b:
            continue

        slug = bid

        merged = {
            "id": bid,
            "slug": slug,
            "name_zh": b.get("name_zh_hint", b.get("name_en", "")),
            "name_en": b.get("name_en", ""),
            "alt_names": b.get("alt_names", []),
            "origin": trans["origin"].get(b.get("origin", ""), b.get("origin", "")),
            "origin_en": b.get("origin", ""),
            "country_code": b.get("country_code", ""),
            "life_span_years": parse_range(b.get("life_span", "")),
            "weight_kg": parse_range(b.get("weight", {}).get("metric", "")),
            "temperament_zh": translate_temperament(b.get("temperament_en", []), trans["temperament"]),
            "temperament_en": b.get("temperament_en", []),
            "scores": b.get("scores", {}),
            "score_labels": trans["score_label"],
            "tags": b.get("tags", {}),
            "description_en": b.get("description_en", ""),
            "description_zh": "",
            "description_zh_status": "pending",
            "tw_notes": {},
            "wikipedia_url_en": b.get("wikipedia_url", ""),
            "wikipedia_url_zh": "",
            "images": normalize_images(b.get("images", [])),
            "thecatapi_url": f"https://thecatapi.com/breeds/{bid}",
            "data_source": "thecatapi",
        }

        if bid in overrides:
            ov = overrides[bid]
            for k, v in ov.items():
                if k.startswith("_"): continue
                if k == "images":
                    merged["images"] = normalize_images(v)
                elif v:
                    merged[k] = v

        breeds.append(merged)

    # 2. 處理 manual_only 品種（TheCatAPI 沒收錄、靠手補）
    for bid, ov in overrides.items():
        if bid in [b["id"] for b in breeds]:
            continue  # 已處理過
        if not ov.get("_manual_only"):
            continue
        merged = {
            "id": ov.get("id", bid),
            "slug": ov.get("slug", bid),
            "name_zh": ov.get("name_zh", ""),
            "name_en": ov.get("name_en", ""),
            "alt_names": ov.get("alt_names", []),
            "origin": ov.get("origin", ""),
            "origin_en": ov.get("origin_en", ""),
            "country_code": ov.get("country_code", ""),
            "life_span_years": ov.get("life_span_years", []),
            "weight_kg": ov.get("weight_kg", []),
            "temperament_zh": ov.get("temperament_zh", []),
            "temperament_en": ov.get("temperament_en", []),
            "scores": ov.get("scores", {}),
            "score_labels": trans["score_label"],
            "tags": ov.get("tags", {}),
            "description_en": ov.get("description_en", ""),
            "description_zh": ov.get("description_zh", ""),
            "description_zh_status": ov.get("description_zh_status", "pending"),
            "tw_notes": ov.get("tw_notes", {}),
            "wikipedia_url_en": ov.get("wikipedia_url_en", ""),
            "wikipedia_url_zh": ov.get("wikipedia_url_zh", ""),
            "images": normalize_images(ov.get("images", [])),
            "thecatapi_url": "",
            "data_source": "manual",
            "manual_note": ov.get("_note", "TheCatAPI 未收錄，本筆為手動補充。"),
        }
        breeds.append(merged)

    # 排序：依中文名
    breeds.sort(key=lambda b: b["name_zh"])

    out = {
        "_meta": {
            "count": len(breeds),
            "generated_at": __import__("datetime").datetime.now().strftime("%Y-%m-%d %H:%M"),
        },
        "breeds": breeds,
    }

    OUT_JSON.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[Done] {len(breeds)} breeds → {OUT_JSON}")

    OUT_JS.parent.mkdir(parents=True, exist_ok=True)
    OUT_JS.write_text(
        "window.BREEDS = " + json.dumps(out, ensure_ascii=False, indent=2) + ";\n",
        encoding="utf-8",
    )
    print(f"[Done] frontend → {OUT_JS}")


if __name__ == "__main__":
    main()
