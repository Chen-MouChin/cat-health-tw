#!/usr/bin/env python3
"""清掉 citations.json 裡會造成 false-positive 匹配的泛用關鍵字。

像 'guideline'/'guidelines'/'consensus'/'cat'/'cats'/'feline' 太通用，
出現在任何 source 文字都會誤觸 — 從 keywords 拿掉這些，讓 fuzzy matcher 更乾淨。
"""
import json
from pathlib import Path

CITATIONS = Path(__file__).parent.parent / "content" / "references" / "citations.json"

GENERIC = {"guideline", "guidelines", "consensus", "cat", "cats", "feline", "review", "study"}


def main():
    raw = json.loads(CITATIONS.read_text(encoding="utf-8"))
    cleaned = 0
    for cid, c in raw.items():
        if cid == "_meta":
            continue
        kws = c.get("keywords") or []
        if not kws:
            continue
        new_kws = [k for k in kws if k.lower() not in GENERIC]
        if len(new_kws) != len(kws):
            removed = [k for k in kws if k.lower() in GENERIC]
            print(f"  {cid}: 刪 {removed}")
            c["keywords"] = new_kws
            cleaned += 1
    CITATIONS.write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[Done] 清了 {cleaned} 筆 citation 的泛用關鍵字")


if __name__ == "__main__":
    main()
