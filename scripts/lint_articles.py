#!/usr/bin/env python3
"""
文章 lint — cat-health-writing skill 的自動檢查工具
=================================================
把 .claude/skills/cat-health-writing/SKILL.md 第八節「交稿前自檢」變成可執行的檢查。

用法：
    python scripts/lint_articles.py                     # 全部文章，摘要表
    python scripts/lint_articles.py --slug cat-ckd-complete-guide
    python scripts/lint_articles.py --file content/articles/2026-04-08-xxx.md
    python scripts/lint_articles.py --strict            # 有 FAIL 就 exit 1（給 hook / CI 用）
    python scripts/lint_articles.py --fix               # 套用安全的自動修正（絕對路徑、HTML 註解）
    python scripts/lint_articles.py --json              # 機器可讀輸出

檢查項目（F = 失敗，W = 警告）：
    F  fn-missing      註腳 [^KEY] 不在 citations.json
    F  brand           出現品牌 / 商品名
    F  abs-path        內部連結用 /xxx.html 絕對路徑（子路徑部署會 404）
    F  dead-link       內部連結指到不存在的文章或 #
    F  dash-arrow      正文出現 —— — → ≠（表格列除外）
    F  emoji-heading   標題含 emoji
    F  absolute-word   絕對化用語（絕對不、永遠不、一定能、保證、必定、毫無疑問）
    F  ai-phrase       AI 慣用句（值得注意的是、讓我們、不只是…更是、總而言之）
    F  quoted-para     引號包住的整句中文轉述（疑似偽直接引句）
    F  html-block      正文含 <div>/<span> 等 HTML 區塊
    F  html-comment    文末殘留 <!-- 改寫參考連結 --> 註解
    F  frontmatter     缺必要欄位
    W  uncited-number  含數值但同句無註腳
    W  section         缺「何時就醫 / 重點 / 常見問題」段（依類別）
    W  bold-density    單段粗體超過 1 處
    W  short           內文少於 1,500 字
    W  no-links        內部連結少於 2 個
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parent.parent
ARTICLES = ROOT / "content" / "articles"
CITATIONS = ROOT / "content" / "references" / "citations.json"

# ---------------------------------------------------------------------------
# 規則表（要調整就改這裡）
# ---------------------------------------------------------------------------

BRANDS = [
    # 飼料
    "Hill's", "Hills ", "希爾思", "Royal Canin", "法國皇家", "皇家", "Purina", "普瑞納", "Pro Plan",
    "Orijen", "Acana", "愛肯拿", "Instinct", "Ziwi", "Wellness", "Blue Buffalo",
    "Weruva", "Farmina", "法米納", "Nutro", "Iams", "Sheba", "Fancy Feast", "Whiskas", "偉嘉",
    "汪喵星球", "毛孩時代", "幻貓", "k/d", "y/d", "z/d", "t/d", "c/d", "Anallergenic",
    # 費洛蒙
    "Feliway", "費利威", "法蘭克", "Adaptil",
    # 驅蟲藥商品名（成分名可用）
    "Revolution", "大寵愛", "Stronghold", "心疥爽", "Bravecto", "博來恩", "Frontline", "蚤不到",
    "NexGard", "Profender", "Milbemax", "萬滅蟲", "Advantage", "Advocate", "Broadline", "Seresto",
    "Drontal", "Greenies", "Apoquel", "Cytopoint", "Lantus", "Anipryl", "保栓通", "Tumil",
    # 用品
    "Nature's Miracle", "Urine Off", "BioKit", "MYZOO", "MEOW BOY", "IKEA", "Catit", "PetSafe",
    "Litter-Robot", "竹貓星球", "Nekko", "喵宅到", "咪噠", "黑貓白貓", "潔客", "貓博士", "喵行者",
    # 通路
    "momo", "PChome", "蝦皮", "博客來", "PetCo",
]
BRAND_RE = re.compile("|".join(re.escape(b) for b in BRANDS), re.I)

# 只抓語氣加強型的絕對化；「不一定能」「保證成分」「仍非絕對」「所有貓咪腫瘤」屬正常用法
ABSOLUTE_RE = re.compile(r"絕對(?:不|禁止|避免|能|要|會)|永遠(?!有食物)|(?<!不)一定能|保證(?!金|成分)|必定|毫無疑問|從不(?!吃)")
AI_PHRASE_RE = re.compile(r"值得注意的是|重要的是|讓我們|一起來|不只是[^，。]{1,20}更是|總而言之|換句話說|這意味著|毫無疑問|你有沒有想過")
DASH_RE = re.compile(r"——|—|→|≠")
EMOJI_RE = re.compile(
    "[\U0001F300-\U0001FAFF\U00002600-\U000027BF\U0001F000-\U0001F2FF⭐⭕‼⁉™ℹ↔-↙↩↪⌚⌛⌨⏏⏩-⏳⏸-⏺Ⓜ▪▫▶◀◻-◾⤴⤵⬅-⬇⬛⬜〰〽㊗㊙️✅❌❎❓-❕❗➕-➗➰➿]"
)
NUMBER_RE = re.compile(r"\d+(?:[.,]\d+)?\s*(?:%|mg|mL|ml|µmol|umol|mmol|nmol|µg|g/|kcal|mmHg|kg|°C|歲|週|天|個月|年|倍|dL|IU|ppm|小時|分鐘|公分|cm|mm|次)")
CITE_HINT_RE = re.compile(r"\[\^|（[^（）]*(?:IRIS|ISFM|WSAVA|AAFP|Cornell|ABCD|ACVIM|JFMS|JVIM|PubMed|VCA|ASPCA|FDA|農業部|動保處|et al|\b(?:19|20)\d\d\b)[^（）]*）|\([^()]*(?:IRIS|ISFM|WSAVA|AAFP|Cornell|ABCD|ACVIM|JFMS|et al|\b(?:19|20)\d\d\b)[^()]*\)")
QUOTED_PARA_RE = re.compile(r"^>\s*\*\*[^*]+\*\*[：:]\s*「.{20,}」\s*$", re.M)
HTML_BLOCK_RE = re.compile(r"<(div|span|table|section|aside|img|iframe|script)\b", re.I)
HTML_COMMENT_RE = re.compile(r"<!--.*?-->", re.S)
LINK_RE = re.compile(r"\[([^\]]*)\]\(([^)\s]+)\)")
FOOTNOTE_RE = re.compile(r"\[\^([A-Za-z0-9][A-Za-z0-9_\-\.]*)\]")

REQUIRED_FM = ["title", "slug", "date", "category", "description"]
MEDICAL_CATEGORIES = {"健康"}


# ---------------------------------------------------------------------------
# 解析
# ---------------------------------------------------------------------------

def parse(md: str) -> tuple[dict, str]:
    m = re.match(r"^---\r?\n(.*?)\r?\n---\r?\n(.*)$", md, re.S)
    if not m:
        return {}, md
    fm_raw, body = m.group(1), m.group(2)
    fm: dict = {}
    for line in fm_raw.splitlines():
        mm = re.match(r"^([A-Za-z_]+):\s*(.*)$", line)
        if mm:
            fm[mm.group(1)] = mm.group(2).strip().strip('"')
    return fm, body


def sentences(text: str) -> list[str]:
    return [s for s in re.split(r"(?<=[。！？\n])", text) if s.strip()]


def is_table_line(line: str) -> bool:
    return line.lstrip().startswith("|")


# ---------------------------------------------------------------------------
# 檢查
# ---------------------------------------------------------------------------

def lint_one(path: Path, citations: dict, known_slugs: set[str]) -> dict:
    raw = path.read_text(encoding="utf-8")
    fm, body = parse(raw)
    slug = fm.get("slug") or path.stem
    fails: list[tuple[str, str]] = []
    warns: list[tuple[str, str]] = []
    lines = body.splitlines()

    # frontmatter
    for k in REQUIRED_FM:
        if not fm.get(k) and not (k == "date" and fm.get("created")):
            fails.append(("frontmatter", f"缺 {k}"))

    # footnotes
    keys = FOOTNOTE_RE.findall(body)
    for k in sorted(set(keys)):
        if k not in citations:
            fails.append(("fn-missing", f"[^{k}] 不在 citations.json"))

    # brands
    for i, line in enumerate(lines, 1):
        for m in BRAND_RE.finditer(line):
            fails.append(("brand", f"L{i}: {m.group(0)}"))

    # links
    internal = 0
    for m in LINK_RE.finditer(body):
        href = m.group(2)
        if href.startswith("http") or href.startswith("mailto:"):
            continue
        if href.startswith("/"):
            fails.append(("abs-path", f"{href}"))
            continue
        if href in ("#", ""):
            fails.append(("dead-link", f"[{m.group(1)}](#)"))
            continue
        internal += 1
        target = href.split("#")[0].split("?")[0]
        if target.endswith(".html") and "/" not in target:
            if target[:-5] not in known_slugs:
                fails.append(("dead-link", f"{href} 沒有這篇文章"))
    if internal < 2:
        warns.append(("no-links", f"內部連結 {internal} 個"))

    # dashes / arrows（表格列與程式碼區塊除外）
    in_code = False
    for i, line in enumerate(lines, 1):
        if line.strip().startswith("```"):
            in_code = not in_code
            continue
        if in_code or is_table_line(line):
            continue
        for m in DASH_RE.finditer(line):
            fails.append(("dash-arrow", f"L{i}: {m.group(0)}"))

    # emoji headings
    for i, line in enumerate(lines, 1):
        if line.startswith("#") and EMOJI_RE.search(line):
            fails.append(("emoji-heading", f"L{i}: {line.strip()[:40]}"))

    # absolute words / AI phrases
    for i, line in enumerate(lines, 1):
        for m in ABSOLUTE_RE.finditer(line):
            fails.append(("absolute-word", f"L{i}: …{line[max(0, m.start()-8):m.end()+8].strip()}…"))
        for m in AI_PHRASE_RE.finditer(line):
            fails.append(("ai-phrase", f"L{i}: {m.group(0)}"))

    # fake direct quotes
    for m in QUOTED_PARA_RE.finditer(body):
        fails.append(("quoted-para", m.group(0)[:50] + "…"))

    # html
    if HTML_BLOCK_RE.search(body):
        fails.append(("html-block", "正文含 HTML 區塊，改用 frontmatter find_vet 或 markdown"))
    if HTML_COMMENT_RE.search(body):
        fails.append(("html-comment", "文末殘留 HTML 註解（改寫參考連結）"))

    # uncited numbers
    uncited = 0
    total_num = 0
    for s in sentences(body):
        if is_table_line(s) or s.lstrip().startswith("#"):
            continue
        if NUMBER_RE.search(s):
            total_num += 1
            if not CITE_HINT_RE.search(s):
                uncited += 1
    if uncited:
        warns.append(("uncited-number", f"{uncited}/{total_num} 句含數值但無出處"))

    # sections
    cat = fm.get("category", "")
    has_urgent = bool(re.search(r"^##+ .*(就醫|急診)", body, re.M))
    has_key = bool(re.search(r"^##+ .*(重點|最該記住|最該知道|最該先想)", body, re.M))
    has_faq = bool(re.search(r"^##+ .*(常見問題|FAQ)", body, re.M))
    if cat in MEDICAL_CATEGORIES and not has_urgent:
        warns.append(("section", "缺「何時該立刻就醫」段"))
    if not has_key:
        warns.append(("section", "缺「30 秒重點」段"))
    if not has_faq:
        warns.append(("section", "缺「常見問題」段"))

    # bold density
    for i, para in enumerate(re.split(r"\n\s*\n", body)):
        if para.lstrip().startswith(("#", "|", "-", "*", ">", "1", "2", "3")):
            continue
        n = para.count("**") // 2
        if n > 1:
            warns.append(("bold-density", f"段落 {i+1} 粗體 {n} 處"))
            break  # 只報第一個，避免洗版

    # length
    length = len(re.sub(r"\s", "", body))
    if length < 1500:
        warns.append(("short", f"{length} 字"))

    return {
        "file": str(path.relative_to(ROOT)).replace("\\", "/"),
        "slug": slug,
        "category": cat,
        "chars": length,
        "footnotes": len(set(keys)),
        "fails": fails,
        "warns": warns,
    }


# ---------------------------------------------------------------------------
# 自動修正（只做無爭議的）
# ---------------------------------------------------------------------------

def fix_one(path: Path) -> list[str]:
    raw = path.read_text(encoding="utf-8")
    new = raw
    done = []
    # /vets.html → ../vets.html ; /vets → ../vets.html
    n = len(re.findall(r"\]\(/vets(?:\.html)?(\?[^)]*)?\)", new))
    new = re.sub(r"\]\(/vets(?:\.html)?(\?[^)]*)?\)", r"](../vets.html\1)", new)
    if n:
        done.append(f"絕對路徑 ×{n}")
    n2 = len(re.findall(r"\]\(/([a-z\-]+\.html)", new))
    new = re.sub(r"\]\(/([a-z\-]+\.html)", r"](../\1", new)
    if n2:
        done.append(f"其他絕對路徑 ×{n2}")
    # 文末 HTML 註解
    if HTML_COMMENT_RE.search(new):
        new = HTML_COMMENT_RE.sub("", new).rstrip() + "\n"
        done.append("刪 HTML 註解")
    if new != raw:
        path.write_text(new, encoding="utf-8")
    return done


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--slug")
    ap.add_argument("--file")
    ap.add_argument("--strict", action="store_true")
    ap.add_argument("--fix", action="store_true")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--verbose", "-v", action="store_true", help="逐項列出所有 FAIL/WARN")
    args = ap.parse_args()

    citations = {k: v for k, v in json.loads(CITATIONS.read_text(encoding="utf-8")).items() if k != "_meta"}
    files = sorted(p for p in ARTICLES.glob("*.md") if p.name != "README.md")
    known_slugs = set()
    for p in files:
        fm, _ = parse(p.read_text(encoding="utf-8"))
        known_slugs.add(fm.get("slug") or p.stem)

    if args.file:
        files = [Path(args.file).resolve()]
    elif args.slug:
        files = [p for p in files if (parse(p.read_text(encoding="utf-8"))[0].get("slug") or p.stem) == args.slug]
        if not files:
            print(f"找不到 slug={args.slug}")
            return 2

    if args.fix:
        for p in files:
            done = fix_one(p)
            if done:
                print(f"[fix] {p.name}: {', '.join(done)}")

    results = [lint_one(p, citations, known_slugs) for p in files]

    if args.json:
        print(json.dumps(results, ensure_ascii=False, indent=1))
        return 1 if args.strict and any(r["fails"] for r in results) else 0

    single = len(results) == 1
    total_f = total_w = 0
    print(f"{'slug':44} {'字數':>5} {'註腳':>3} {'FAIL':>4} {'WARN':>4}  主要問題")
    for r in results:
        total_f += len(r["fails"])
        total_w += len(r["warns"])
        kinds = {}
        for k, _ in r["fails"]:
            kinds[k] = kinds.get(k, 0) + 1
        summary = ", ".join(f"{k}×{n}" if n > 1 else k for k, n in kinds.items())
        print(f"{r['slug'][:44]:44} {r['chars']:5} {r['footnotes']:3} {len(r['fails']):4} {len(r['warns']):4}  {summary}")
        if single or args.verbose:
            for k, msg in r["fails"]:
                print(f"    FAIL {k:14} {msg}")
            for k, msg in r["warns"]:
                print(f"    warn {k:14} {msg}")
    print(f"\n{len(results)} 篇 · FAIL {total_f} · WARN {total_w}")
    clean = sum(1 for r in results if not r["fails"])
    print(f"零 FAIL：{clean}/{len(results)} 篇")
    return 1 if args.strict and total_f else 0


if __name__ == "__main__":
    sys.exit(main())
