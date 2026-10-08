#!/usr/bin/env python3
"""
從文章的 [^KEY] 註腳回填 citations.json 的 cited_by
====================================================
build.py 產生每篇文章的 citations 清單；本腳本反向更新文獻庫，
讓 library.html 的「📚 ×N」與「被以下文章引用」跟句內註腳一致。

用法：
    python scripts/sync_cited_by.py            # 更新並印出變動
    python scripts/sync_cited_by.py --check    # 只比對，不寫入（exit 1 代表有差異）

規則：
- cited_by = 既有值 ∪ 註腳來源（不刪除舊的 fuzzy match 結果，除非加 --replace）
- 註腳指向不存在的 KEY 會列出警告
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parent.parent
ARTICLES = ROOT / "content" / "articles"
CITATIONS = ROOT / "content" / "references" / "citations.json"
FOOTNOTE_RE = re.compile(r"\[\^([A-Za-z0-9][A-Za-z0-9_\-\.]*)\]")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--replace", action="store_true", help="cited_by 只保留註腳來源")
    args = ap.parse_args()

    data = json.loads(CITATIONS.read_text(encoding="utf-8"))
    from_fn: dict[str, set[str]] = {}
    missing: list[tuple[str, str]] = []
    for p in sorted(ARTICLES.glob("*.md")):
        if p.name == "README.md":
            continue
        text = p.read_text(encoding="utf-8")
        m = re.search(r"^slug:\s*(.+)$", text, re.M)
        slug = (m.group(1).strip().strip('"') if m else p.stem)
        for key in set(FOOTNOTE_RE.findall(text)):
            if key not in data or key == "_meta":
                missing.append((slug, key))
                continue
            from_fn.setdefault(key, set()).add(slug)

    changes = 0
    for key, entry in data.items():
        if key == "_meta":
            continue
        old = set(entry.get("cited_by") or [])
        new = from_fn.get(key, set()) if args.replace else old | from_fn.get(key, set())
        if new != old:
            changes += 1
            print(f"  {key}: {sorted(old)} -> {sorted(new)}")
            if not args.check:
                entry["cited_by"] = sorted(new)

    for slug, key in missing:
        print(f"  [warn] {slug} 引用不存在的 [^{key}]")

    if args.check:
        print(f"{changes} 筆有差異")
        return 1 if changes or missing else 0
    if changes:
        CITATIONS.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"更新 {changes} 筆 cited_by；註腳涵蓋 {len(from_fn)} 筆文獻")
    return 0


if __name__ == "__main__":
    sys.exit(main())
