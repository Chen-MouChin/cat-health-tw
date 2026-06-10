#!/usr/bin/env python3
"""
文章 ↔ citations 反向索引（Phase 1E）
==================================
文章 .md 的 `sources` 欄位是自由文字（如 "IRIS Staging of CKD 2023: ..."），
與 citations.json 的 key（如 "IRIS-CKD-2023"）對不上。

此腳本：
1. 對每筆 citation 計算關鍵詞（title + keywords + source 組合）
2. 掃文章 sources，用 fuzzy match（包含關鍵詞）找到對應的 citation key
3. 輸出對應建議：`content/articles_citations_map.json`（人工校對用）
4. 同時為 citations.json 每筆加 `cited_by` 陣列

輸出：
  content/articles_citations_map.json  → 文章 → citations 對應草稿
  content/references/citations.json    → in-place 更新 cited_by 欄位
  research/inbox/citations-link-review.md → 人工審核模糊匹配結果
"""
from __future__ import annotations
import json
import re
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).parent.parent
ARTICLES_DIR = ROOT / "content" / "articles"
CITATIONS = ROOT / "content" / "references" / "citations.json"
MAP_OUT = ROOT / "content" / "articles_citations_map.json"
REVIEW_OUT = ROOT / "research" / "inbox" / "citations-link-review.md"


def parse_frontmatter(text):
    m = re.match(r"---\n(.*?)\n---", text, re.S)
    if not m:
        return None, text
    fm = {}
    cur = None
    for line in m.group(1).split("\n"):
        if not line.strip(): continue
        if not line.startswith(" ") and ":" in line:
            k, _, v = line.partition(":")
            cur = k.strip()
            v = v.strip().strip('"')
            fm[cur] = v if v else []
        elif line.lstrip().startswith("-") and cur:
            if not isinstance(fm[cur], list):
                fm[cur] = []
            fm[cur].append(line.lstrip()[1:].strip().strip('"'))
    return fm, text[m.end():]


GENERIC_WORDS = {"guideline", "guidelines", "consensus", "review", "study",
                 "cat", "cats", "feline", "the", "and", "for", "from",
                 "management", "diagnosis", "treatment", "disease"}


def citation_keywords(cid, cit):
    """citation 的可匹配關鍵詞集合"""
    kws = set()
    title = (cit.get("title") or "").lower()
    if title: kws.add(title)
    # 簡短版：取前 40 字
    if len(title) > 40:
        kws.add(title[:40])
    # 從 keywords 欄位
    for k in cit.get("keywords") or []:
        kws.add(k.lower())
    # source（如 "IRIS" "Cornell"）
    src = (cit.get("source") or "").lower()
    if src: kws.add(src)
    # 特殊 ID 關鍵詞（由 cid 推斷）— 過濾通用詞避免誤觸
    parts = cid.replace("-", " ").lower().split()
    for p in parts:
        if len(p) >= 3 and not p.isdigit() and p not in GENERIC_WORDS:
            kws.add(p)
    return kws


def match_source_to_citations(source_text, citations):
    """對一段 source 文字，計算與每筆 citation 的匹配分數"""
    src_low = source_text.lower()
    scores = []
    for cid, cit in citations.items():
        score = 0
        kws = citation_keywords(cid, cit)
        for kw in kws:
            if not kw or len(kw) < 3: continue
            if kw in src_low:
                score += len(kw)  # 較長的關鍵詞權重高
        if score > 0:
            scores.append((score, cid))
    scores.sort(reverse=True)
    return scores[:3]  # top 3 候選


def main():
    citations = json.loads(CITATIONS.read_text(encoding="utf-8"))
    citations.pop("_meta", None)
    # 清空 cited_by（重建）
    for cid, cit in citations.items():
        cit["cited_by"] = []

    MAP_OUT.parent.mkdir(parents=True, exist_ok=True)
    REVIEW_OUT.parent.mkdir(parents=True, exist_ok=True)

    article_map = {}  # {article_slug: [{source_text, top_matches: [(score, cid), ...]}]}
    review_items = []  # 需要人工看的模糊匹配

    for md_path in sorted(ARTICLES_DIR.glob("*.md")):
        if md_path.name.startswith("README"): continue
        text = md_path.read_text(encoding="utf-8")
        fm, body = parse_frontmatter(text)
        if not fm: continue
        slug = fm.get("slug") or md_path.stem
        sources = fm.get("sources") or []
        if not isinstance(sources, list): continue

        article_data = []
        for src in sources:
            matches = match_source_to_citations(src, citations)
            article_data.append({
                "source_text": src,
                "top_matches": [{"score": s, "cid": c} for s, c in matches],
                "best_match": matches[0][1] if matches else None,
                "confidence": "high" if matches and matches[0][0] >= 20 else "medium" if matches and matches[0][0] >= 10 else "low",
            })
            # 對 best match 建立 cited_by
            if matches and matches[0][0] >= 10:
                best_cid = matches[0][1]
                if slug not in citations[best_cid]["cited_by"]:
                    citations[best_cid]["cited_by"].append(slug)
            # 低信心的標示給人工看
            if not matches or matches[0][0] < 10:
                review_items.append({
                    "article": slug,
                    "source": src,
                    "candidates": [{"cid": c, "score": s} for s, c in matches[:3]],
                })

        article_map[slug] = article_data

    # 寫出
    MAP_OUT.write_text(json.dumps(article_map, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[Map] {MAP_OUT}")

    # 回寫 citations.json（含 cited_by）
    # 先保留 _meta
    final = {"_meta": json.loads(CITATIONS.read_text(encoding="utf-8")).get("_meta", {})}
    final.update(citations)
    CITATIONS.write_text(json.dumps(final, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[Citations] 更新 cited_by 欄位，{CITATIONS}")

    # 統計
    total_articles = len(article_map)
    articles_with_match = sum(1 for arts in article_map.values() if any(a.get("best_match") for a in arts))
    cited = sum(1 for cit in citations.values() if cit.get("cited_by"))
    uncited = len(citations) - cited
    print(f"[Stats]")
    print(f"  文章總數: {total_articles}")
    print(f"  至少一個 source 對到的: {articles_with_match}")
    print(f"  被引用的 citations: {cited} / {len(citations)}")
    print(f"  從未被引用: {uncited}")
    print(f"  低信心待人工: {len(review_items)}")

    # 寫審核清單
    lines = [
        "# Citations 反向索引 — 人工審核清單",
        "",
        f"_自動產出於 `scripts/link_sources_to_citations.py`_",
        "",
        f"## 總覽",
        f"- 文章總數：{total_articles}",
        f"- 被引用的 citations：{cited} / {len(citations)}",
        f"- 從未被引用（考慮 1C.1 砍掉）：{uncited}",
        f"- 低信心模糊匹配（需人工看）：{len(review_items)}",
        "",
        f"## 從未被引用的 citations（{uncited} 筆）",
        "",
        "這些 citation 沒被任何文章引用。若非高權威指引（IRIS / ISFM consensus 等），Phase 1C 階段可考慮砍掉。",
        "",
    ]
    uncited_list = [(cid, cit) for cid, cit in citations.items() if not cit.get("cited_by")]
    for cid, cit in uncited_list[:40]:
        title = cit.get("title") or cid
        lines.append(f"- `{cid}` — {title[:70]}")
    if len(uncited_list) > 40:
        lines.append(f"\n（還有 {len(uncited_list) - 40} 筆）")

    lines += ["", f"## 低信心匹配（{len(review_items)} 筆）請人工核對", ""]
    for item in review_items[:30]:
        lines.append(f"### 📝 {item['article']}")
        lines.append(f"原文 source：`{item['source'][:120]}...`")
        if item['candidates']:
            lines.append("建議候選：")
            for c in item['candidates']:
                lines.append(f"- `{c['cid']}`（分數 {c['score']}）")
        else:
            lines.append("**沒找到任何候選 — 可能需要新增 citation**")
        lines.append("")

    REVIEW_OUT.write_text("\n".join(lines), encoding="utf-8")
    print(f"[Review] {REVIEW_OUT}")


if __name__ == "__main__":
    main()
