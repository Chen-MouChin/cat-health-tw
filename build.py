"""
build.py — Full site builder for 貓健康站 (cat-health-tw).

Steps:
  [Articles]
  1. Read content/articles/*.md → parse YAML front matter → convert to HTML
  2. Write frontend/articles/{slug}.html (with ad slots + nav)
  3. Write frontend/articles/index.html (article listing, with ad slots)
  4. Copy citations.json / glossary.json / vets.json into frontend/data/

  [Breeds]
  5. Write frontend/breeds/{slug}.html from TheCatAPI data

  [SEO]
  6. Write frontend/sitemap.xml (drafts excluded)

Note: 商品比價功能已停用（本站轉型為貓健康知識庫）；相關程式碼已移除。

Usage:
  pip install markdown          # one-time setup
  python3 build.py
"""

import json
import re
import sys
import textwrap
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

# Windows 主控台預設 cp1252，印 → 或中文會崩潰
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).parent
CONTENT_DIR = ROOT / "content" / "articles"
FRONTEND_DIR = ROOT / "frontend"
ARTICLES_DIR = FRONTEND_DIR / "articles"
SITEMAP_XML = FRONTEND_DIR / "sitemap.xml"
# 未審核文章不上線：只有這些 quality 的文章會寫進 frontend/（進 git、進 Pages）
PUBLISHED_QUALITIES = ("reviewed", "featured")
# 品種圖鑑 68 頁是 TheCatAPI 翻譯、沒人審過：頁面 noindex、不進 sitemap。審完改 True
BREEDS_INDEXABLE = False
# 手寫頁（不是 build 產生的）；build 會把它們連到未上線文章的連結拆成純文字
HAND_PAGES = ("about.html", "breeds.html", "editorial.html", "library.html", "privacy.html", "vets.html")
# 全部文章（含草稿）的搜尋索引，給 test_search.py 用，不進 git
ALL_ARTICLES_JS = ROOT / "build" / "articles-data-all.js"
# 草稿的 HTML 寫到這裡（.gitignore），給工作檯本機預覽用；線上永遠看不到
DRAFTS_DIR = ROOT / "build" / "drafts" / "articles"
SITE_URL = "https://chen-mouchin.github.io/cat-health-tw"  # update when deployed


def write_meta_js(records: list[dict]):
    """生成 frontend/js/meta.js — 包含 build 時間與最新爬蟲日期，供 footer JS 使用。"""
    build_ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    build_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # 最新爬蟲日期：取 crawled_at 最新值
    crawled_dates = [r.get("crawled_at", "")[:10] for r in records if r.get("crawled_at")]
    data_updated = max(crawled_dates) if crawled_dates else build_date

    meta_js = FRONTEND_DIR / "js" / "meta.js"
    meta_js.parent.mkdir(parents=True, exist_ok=True)
    content = (
        f"// 由 build.py 自動生成，請勿手動修改\n"
        f"const SITE_META = {{\n"
        f'  built_at: "{build_ts}",\n'
        f'  data_updated: "{data_updated}",\n'
        f'  developer: "Chen-MouChin",\n'
        f'  developer_url: "https://github.com/Chen-MouChin"\n'
        f"}};\n"
    )
    meta_js.write_text(content, encoding="utf-8")
    print(f"  → {meta_js} (data_updated: {data_updated})")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Article builder — MD → HTML
# ---------------------------------------------------------------------------

def _escape_html(s: str) -> str:
    """Minimal HTML escaping for user-supplied text in frontmatter fields."""
    if not s:
        return ""
    return (
        str(s)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _parse_front_matter(text: str) -> tuple[dict, str]:
    """Split YAML front matter from Markdown body. Returns (meta_dict, body)."""
    if not text.startswith("---"):
        return {}, text
    end = text.find("\n---", 3)
    if end == -1:
        return {}, text
    yaml_block = text[3:end].strip()
    body = text[end + 4:].strip()
    meta: dict = {}
    for line in yaml_block.splitlines():
        if ":" in line:
            key, _, val = line.partition(":")
            key = key.strip()
            val = val.strip().strip('"')
            # Handle list values (lines starting with "  - ")
            meta[key] = val
    # Re-parse lists for sources / tags / tldr / related — handle both multi-line and inline formats
    for list_key in ("sources", "tags", "tldr", "related"):
        # Multi-line format: key:\n  - item
        block_match = re.search(
            rf"^{list_key}:\s*\n((?:  - .+\n?)+)", yaml_block, re.MULTILINE
        )
        if block_match:
            items = re.findall(r"  - (.+)", block_match.group(1))
            meta[list_key] = [i.strip().strip('"') for i in items]
        # Inline format: key: [item1, item2, ...]
        elif list_key in meta and isinstance(meta[list_key], str):
            val = meta[list_key].strip()
            if val.startswith("[") and val.endswith("]"):
                meta[list_key] = [i.strip().strip('"\'') for i in val[1:-1].split(",") if i.strip()]

    # key_facts: list of dicts (label / value / note)
    # Format:
    #   key_facts:
    #     - label: 18h
    #       value: 治療窗
    #       note: 超過即不可逆
    kf_match = re.search(
        r"^key_facts:\s*\n((?:  - .+\n?(?:    .+\n?)*)+)", yaml_block, re.MULTILINE
    )
    if kf_match:
        facts = []
        current: dict | None = None
        for raw in kf_match.group(1).splitlines():
            if raw.startswith("  - "):
                if current is not None:
                    facts.append(current)
                current = {}
                rest = raw[4:].strip()
                if ":" in rest:
                    k, _, v = rest.partition(":")
                    current[k.strip()] = v.strip().strip('"')
            elif raw.startswith("    ") and current is not None and ":" in raw:
                k, _, v = raw.strip().partition(":")
                current[k.strip()] = v.strip().strip('"')
        if current is not None:
            facts.append(current)
        meta["key_facts"] = facts
    return meta, body


def _md_to_html(md_text: str) -> str:
    """Convert Markdown to HTML. Uses `markdown` package if available, else basic regex."""
    # 「**小標**」下一行直接接「- 項目」在 Markdown 規格裡不算清單（要先空一行），很多文章這樣寫，
    # 線上就變成一行行的「- 」純文字。段落後面緊接的清單自動補空行。
    lines = md_text.split("\n")
    fixed = []
    for i, line in enumerate(lines):
        if i and re.match(r"^\s*(?:[-*+]|\d+\.)\s", line) and lines[i - 1].strip() and not re.match(r"^\s*(?:[-*+]\s|\d+\.\s|>|\|)", lines[i - 1]) and not lines[i - 1].lstrip().startswith("#"):
            fixed.append("")
        fixed.append(line)
    md_text = "\n".join(fixed)
    try:
        import markdown as md_lib
        return md_lib.markdown(
            md_text,
            extensions=["tables", "fenced_code", "nl2br", "attr_list", "toc"],
            extension_configs={"toc": {"permalink": False}},
        )
    except ImportError:
        # Fallback: basic regex conversion
        html = md_text
        html = re.sub(r"^### (.+)$", r"<h3>\1</h3>", html, flags=re.MULTILINE)
        html = re.sub(r"^## (.+)$", r"<h2>\1</h2>", html, flags=re.MULTILINE)
        html = re.sub(r"^# (.+)$", r"<h1>\1</h1>", html, flags=re.MULTILINE)
        html = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", html)
        html = re.sub(r"\*(.+?)\*", r"<em>\1</em>", html)
        html = re.sub(r"`(.+?)`", r"<code>\1</code>", html)
        html = re.sub(r"^> (.+)$", r"<blockquote>\1</blockquote>", html, flags=re.MULTILINE)
        html = re.sub(r"^- (.+)$", r"<li>\1</li>", html, flags=re.MULTILINE)
        html = re.sub(r"(<li>.*</li>\n?)+", r"<ul>\g<0></ul>", html, flags=re.DOTALL)
        html = re.sub(r"\n\n", "</p><p>", html)
        html = f"<p>{html}</p>"
        return html


# ---------------------------------------------------------------------------
# 句內引用註腳：正文寫 [^KEY]，KEY 對應 content/references/citations.json
# 渲染為上標數字連到 library.html?id=KEY，文末自動產生「參考文獻」清單
# ---------------------------------------------------------------------------

_CITATIONS_CACHE: dict | None = None


def _load_citations() -> dict:
    global _CITATIONS_CACHE
    if _CITATIONS_CACHE is None:
        p = ROOT / "content" / "references" / "citations.json"
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            data = {}
        _CITATIONS_CACHE = {k: v for k, v in data.items() if k != "_meta"}
    return _CITATIONS_CACHE


FOOTNOTE_RE = re.compile(r"\[\^([A-Za-z0-9][A-Za-z0-9_\-\.]*)\]")


def _process_footnotes(body_md: str, slug: str) -> tuple[str, str, list[str]]:
    """把 [^KEY] 換成上標連結，回傳 (新 markdown, 參考文獻 HTML, 使用到的 key 依序)。

    同一個 KEY 多次出現共用同一個編號。找不到的 KEY 會印警告，仍照常連到 library。
    """
    citations = _load_citations()
    order: list[str] = []

    def repl(m: re.Match) -> str:
        key = m.group(1)
        if key not in order:
            order.append(key)
            if key not in citations:
                print(f"  [warn] {slug}: 註腳 [^{key}] 不在 citations.json")
        n = order.index(key) + 1
        c = citations.get(key, {})
        tip = _escape_html(c.get("title_zh") or c.get("title") or key)
        return (
            f'<sup class="fn"><a href="../library.html?id={key}" '
            f'title="{tip}" data-cite="{key}">{n}</a></sup>'
        )

    new_md = FOOTNOTE_RE.sub(repl, body_md)
    if not order:
        return new_md, "", []

    items = []
    for i, key in enumerate(order, 1):
        c = citations.get(key)
        if c:
            title = _escape_html(c.get("title_zh") or c.get("title") or key)
            en = c.get("title") if c.get("title_zh") and c.get("title") != c.get("title_zh") else ""
            meta_bits = [b for b in (c.get("authors", ""), c.get("source", ""), str(c.get("year", "") or "")) if b]
            meta = _escape_html(" · ".join(meta_bits))
            en_html = f'<div class="ref-en">{_escape_html(en)}</div>' if en else ""
            url = c.get("url", "")
            url_html = f' <a class="ref-url" href="{_escape_html(url)}" target="_blank" rel="noopener">原文</a>' if url else ""
            items.append(
                f'      <li id="ref-{key}"><a class="ref-title" href="../library.html?id={key}">{title}</a>{url_html}'
                f'{en_html}<div class="ref-meta">{meta}</div></li>'
            )
        else:
            items.append(f'      <li id="ref-{key}"><span class="ref-title">{_escape_html(key)}</span><div class="ref-meta">（文獻庫尚未收錄）</div></li>')
    refs_html = (
        '<div class="sources-box references">\n'
        '      <h3>參考文獻</h3>\n'
        '      <ol>\n' + "\n".join(items) + '\n      </ol>\n'
        '      <p class="ref-hint">點文獻標題可到文獻庫查看中文摘要與審核狀態。</p>\n'
        '    </div>'
    )
    return new_md, refs_html, order


CATEGORY_EMOJI = {
    "入門": "🆕", "健康": "❤️", "飲食": "🍖", "行為": "🐾",
    "環境": "🏠", "階段": "⏳", "品種": "🐈",
}

# slug → subcategory name
SUBCATEGORY_MAP: dict[str, str] = {
    # 醫療 — 常見疾病
    "cat-ckd-complete-guide": "常見疾病",
    "cat-fip-guide-taiwan": "常見疾病",
    "cat-hcm-heart-disease": "常見疾病",
    "fiv-felv-management-taiwan": "常見疾病",
    "cat-diabetes-care": "常見疾病",
    "cat-hyperthyroidism-senior": "常見疾病",
    "cat-hepatic-lipidosis": "常見疾病",
    "cat-ibd-intestinal-disease": "常見疾病",
    "cat-cancer-tumors-guide": "常見疾病",
    "cat-upper-respiratory-infection": "常見疾病",
    "cat-skin-allergies": "常見疾病",
    "cat-eye-problems": "常見疾病",
    "cat-ear-problems": "常見疾病",
    "cat-constipation-guide": "常見疾病",
    "cat-weight-loss-causes": "常見疾病",
    "cat-vomiting-guide": "常見疾病",
    "cat-cognitive-dysfunction": "常見疾病",
    # 醫療 — 預防保健
    "cat-vaccination-schedule-taiwan": "預防保健",
    "cat-deworming-taiwan": "預防保健",
    "cat-flea-control-complete": "預防保健",
    "cat-wellness-exam-guide": "預防保健",
    "cat-neutering-taiwan": "預防保健",
    "cat-spay-neuter-aftercare": "預防保健",
    "cat-toxoplasma-pregnancy": "預防保健",
    "choosing-vet-clinic-taiwan": "預防保健",
    # 醫療 — 急症辨識
    "cat-symptoms-emergency-guide": "急症辨識",
    "cat-emergency-first-aid": "急症辨識",
    "male-cat-urethral-obstruction": "急症辨識",
    # 醫療 — 口腔健康
    "cat-dental-care": "口腔健康",
    "cat-dental-disease-prevention": "口腔健康",
    # 飲食 — 飼料選擇
    "dry-vs-wet-food-cats": "飼料選擇",
    "reading-cat-food-labels": "飼料選擇",
    "evaluating-cat-food-quality": "飼料選擇",
    "cat-treat-selection-guide": "飼料選擇",
    "cat-supplements-guide": "飼料選擇",
    # 飲食 — 特殊飲食
    "barf-raw-food-taiwan": "特殊飲食",
    "pregnant-nursing-cat-diet": "特殊飲食",
    # 飲食 — 特殊需求
    "cat-urinary-health-diet": "特殊需求",
    "cat-obesity-weight-management": "特殊需求",
    "cat-food-by-life-stage": "特殊需求",
    "cat-daily-water-intake-taiwan": "特殊需求",
    "cat-hairball-complete-guide": "特殊需求",
    # 飲食 — 毒物安全
    "toxic-foods-for-cats-taiwan": "毒物安全",
    "toxic-plants-for-cats-taiwan": "毒物安全",
    # 行為 — 問題行為
    "cat-inappropriate-elimination": "問題行為",
    "cat-aggression-causes-treatment": "問題行為",
    "cat-anxiety-stress-management": "問題行為",
    # 行為 — 自然行為
    "cat-scratching-behavior": "自然行為",
    "cat-grooming-behavior": "自然行為",
    "cat-play-behavior-guide": "自然行為",
    "cat-zoomies-night-activity": "自然行為",
    "cat-body-language-guide": "自然行為",
    # 行為 — 多貓管理
    "multi-cat-household-guide": "多貓管理",
    "introducing-new-cat-to-resident-cats": "多貓管理",
    "cat-pheromone-products-guide": "多貓管理",
    # 行為 — 其他
    "cat-carrier-training": "訓練技巧",
    "solo-cat-mental-health": "心理健康",
    # 品種 — 短毛品種
    "british-shorthair-breed-guide": "短毛品種",
    "exotic-shorthair-breed-guide": "短毛品種",
    "russian-blue-breed-guide": "短毛品種",
    "siamese-cat-breed-guide": "短毛品種",
    "burmese-cat-breed-guide": "短毛品種",
    "abyssinian-breed-guide": "短毛品種",
    "bengal-cat-breed-guide": "短毛品種",
    # 品種 — 長毛品種
    "maine-coon-breed-guide": "長毛品種",
    "norwegian-forest-cat-breed-guide": "長毛品種",
    "ragdoll-breed-guide-taiwan": "長毛品種",
    "persian-cat-breed-guide": "長毛品種",
    # 品種 — 特殊
    "scottish-fold-breed-guide-taiwan": "特殊與健康爭議",
    "mixed-breed-cats-taiwan": "台灣本土貓",
    # 居家環境 — 安全防護
    "cat-home-safety-checklist": "安全防護",
    "cat-balcony-safety-taiwan": "安全防護",
    "preventing-cat-escape-taiwan": "安全防護",
    "cat-friendly-plants-taiwan": "安全防護",
    # 居家環境 — 空間設計
    "cat-vertical-space-design": "空間設計",
    "cat-environmental-enrichment-taiwan": "空間設計",
    "cat-litter-box-guide": "空間設計",
    "multi-cat-space-planning": "空間設計",
    # 居家環境 — 日常照料
    "cat-home-grooming-guide": "日常照料",
    "cat-boarding-options-taiwan": "日常照料",
    "cat-indoor-vs-outdoor-taiwan": "環境選擇",
    # 生命週期
    "kitten-care-0-6-months": "幼貓期",
    "kitten-weaning-solid-food": "幼貓期",
    "kitten-socialization": "幼貓期",
    "adult-cat-annual-care-1-7": "成貓期",
    "senior-cat-care-guide": "老貓期",
    "cat-aging-signs-recognition": "老貓期",
    "cat-queen-pregnancy-birth": "懷孕與生產",
    "cat-palliative-care-taiwan": "生命終結",
    "cat-grief-bereavement-guide": "生命終結",
    # 養貓入門
    "should-i-adopt-a-cat-self-assessment": "決策準備",
    "adopt-vs-buy-cat-taiwan": "決策準備",
    "cat-annual-cost-taiwan": "費用規劃",
    "cat-insurance-taiwan": "費用規劃",
    "cat-adoption-complete-guide-taiwan": "領養流程",
    "rehoming-cat-responsibly-taiwan": "領養流程",
    "new-cat-first-week-guide": "新貓到家",
    "senior-cat-adoption-guide": "特殊族群",
    # 法規
    "taiwan-animal-protection-law": "動物保護法",
    "stray-cats-tnr-law-taiwan": "流浪動物管理",
    "cat-microchip-registration-taiwan": "寵物管理",
    "renting-with-cats-taiwan": "飼主權益",
    "traveling-with-cats-taiwan-international": "出入境規定",
}

# Subcategory display order per category
CATEGORY_SUBCAT_ORDER: dict[str, list[str]] = {
    "入門": ["決策準備", "費用規劃", "領養流程", "新貓到家", "特殊族群",
              "動物保護法", "流浪動物管理", "寵物管理", "飼主權益", "出入境規定"],
    "健康": ["常見疾病", "預防保健", "急症辨識", "口腔健康"],
    "飲食": ["飼料選擇", "特殊需求", "毒物安全", "特殊飲食"],
    "行為": ["自然行為", "問題行為", "多貓管理", "訓練技巧", "心理健康"],
    "環境": ["安全防護", "空間設計", "日常照料", "環境選擇"],
    "階段": ["幼貓期", "成貓期", "老貓期", "懷孕與生產", "生命終結"],
    "品種": ["短毛品種", "長毛品種", "特殊與健康爭議", "台灣本土貓"],
}

# 頁首 Logo 與頁尾小貓：和首頁同一份圖，文章模板用 {brand_svg} {cat_svg} 帶入
BRAND_SVG = """<svg viewBox="0 0 180 47" aria-hidden="true" focusable="false"><g transform="translate(0,15.2) scale(0.750)" fill="currentColor"><path d="M4 20 V2 L14 10 Z"/><path d="M36 20 V2 L26 10 Z"/><circle cx="13" cy="18" r="2.2"/><circle cx="27" cy="18" r="2.2"/></g><g transform="translate(40.0,0) scale(0.340)"><path fill="currentColor" d="M79.79 93.26 65.04 93.46 49.61 93.65 48.24 93.75H41.21L40.72 64.45L40.82 45.31L45.21 44.73V44.63H46.00L46.48 44.53L48.83 44.43L61.13 43.95H81.25L89.16 44.73L91.89 46.78L92.48 64.84L92.29 85.94L91.89 93.75H85.74ZM59.08 65.43 58.79 57.91 54.59 58.01V60.35L54.69 65.53ZM71.78 65.23 77.05 65.33 76.95 57.91H71.88ZM59.08 82.71V76.95L54.98 77.15L55.08 82.71H58.40ZM71.97 82.62H76.95L77.15 77.54V76.86H71.88ZM17.58 85.45 24.41 85.16 25.68 81.35 20.21 84.28ZM68.85 9.96 76.37 9.67 83.98 10.55 83.79 19.63 92.68 19.92V27.25L91.80 33.30L83.01 32.91L82.91 35.25L82.52 41.50L73.24 41.02L68.85 40.43L68.95 32.62L60.06 32.81L60.45 40.33L51.56 41.11L46.97 41.41L46.29 33.30L40.62 33.59L39.75 27.54L39.65 20.61L45.41 20.31L45.02 12.30L52.83 10.84L58.89 10.94L59.38 19.73L69.14 19.34V16.50ZM32.62 8.89 36.23 13.38 39.26 20.21 32.81 23.14 22.17 27.25 7.71 31.84 5.86 27.44 4.79 20.02 15.04 17.09 23.73 13.67ZM6.15 35.94 10.64 32.91 15.72 30.66 18.16 35.45 20.61 41.11 16.41 43.46 11.82 45.70 9.47 41.80ZM19.24 30.96 24.71 27.15 29.49 25.29 32.23 29.98 34.18 34.08 36.72 31.74 41.11 36.43 44.53 42.77 37.21 47.17 33.20 49.22 37.01 56.54 40.14 70.51 38.87 84.77 36.43 91.41 32.23 94.73 24.51 95.12 19.14 94.24 18.55 89.45 16.80 85.74 10.74 88.38 8.79 85.35 7.13 78.42 16.31 74.51 23.05 70.80 26.17 68.36 25.68 66.41 19.92 69.63 11.82 73.14 10.06 70.70 7.71 63.57 19.53 58.20 22.17 56.45 21.29 54.69 19.53 55.47 10.35 58.69 8.20 54.98 6.15 47.85 13.96 45.51 25.59 40.23 30.18 37.30 29.30 37.70 24.22 39.16 21.48 34.47ZM134.08 77.73 129.88 75.20 129.78 83.20ZM153.12 68.36 150.97 73.05 153.80 74.51ZM177.44 28.12H180.95L180.86 25.49L177.54 25.29ZM177.44 41.02 180.76 41.21 180.86 38.28H177.44ZM165.13 75.29 156.54 75.49 165.13 78.22ZM136.62 44.53 138.96 38.67 136.52 38.38 132.22 38.57 131.44 33.01 128.80 40.92 126.36 46.58 130.66 48.05 130.07 62.40 129.98 68.46 134.57 62.79 140.04 66.60 141.99 61.23 139.35 60.74 135.25 60.35 134.27 55.18 133.88 49.51ZM164.35 7.71 173.73 7.62 178.12 8.69 177.93 13.87H185.64L191.99 14.55L194.33 17.09L194.23 28.32L199.61 28.42V35.45L198.73 39.06L194.04 38.87L193.16 50.78H187.40L185.93 50.59L177.44 50.29L177.54 52.64L191.89 53.12L191.99 59.18L191.30 63.18L185.05 62.60L177.63 62.50V65.14L189.55 65.33L197.16 65.82V71.78L196.38 76.46L186.52 75.49L177.73 75.20L177.83 79.20L171.09 79.00L165.72 78.42L167.38 78.91L181.44 80.86L195.60 81.45L195.21 89.06L194.14 94.43L176.56 92.77L164.35 90.53L151.17 86.72L145.11 83.89L142.77 87.79L137.59 94.24L131.93 89.84L129.78 86.72L129.88 94.53H122.85L117.38 93.75L117.77 72.56V65.72L115.52 70.31L109.57 66.21L105.66 61.23L111.03 50.49L116.60 35.84L120.50 22.75L123.34 9.86L132.61 12.01L137.59 14.94L134.18 25.20L142.87 25.00L148.82 25.49L151.17 31.64L152.05 38.28L150.48 42.87L146.97 49.22L151.07 49.41L153.61 50.29L155.17 56.25L155.46 61.33L154.39 65.62L165.23 65.23V62.50L157.91 62.79L156.93 58.30L157.22 52.93L165.23 52.73V50.29L155.27 50.49L154.59 46.78L154.68 41.21L165.04 41.11V38.28L153.61 38.38L152.83 32.71L153.02 28.12L164.94 28.03L164.84 25.39L155.37 25.49L154.49 21.00L154.39 14.16L164.55 13.96ZM271.09 42.87Q275.58 42.87 279.97 42.77Q280.07 41.41 280.17 40.14Q275.68 39.94 271.18 39.75Q271.09 40.62 271.09 41.50ZM271.18 54.10H279.58Q279.58 52.73 279.68 51.37Q279.29 51.37 278.80 51.37Q274.99 51.46 271.09 51.46Q271.18 52.83 271.18 54.10ZM271.28 70.02 279.29 66.99 286.12 64.06 287.79 63.09H286.42H279.29V62.60L271.28 62.70H271.18ZM273.53 73.34 271.28 70.31V72.75ZM255.36 6.35 266.40 8.40 270.79 9.08 270.50 15.14Q275.58 15.23 280.66 15.33H299.31L299.11 22.17L298.43 27.64L277.34 26.66L262.10 26.37L266.01 27.54L272.06 28.52Q271.96 29.88 271.87 31.15H280.46L292.47 32.13L294.91 34.28L294.62 43.16L302.82 43.36L302.14 48.05L301.95 52.05L294.33 51.86L293.64 63.09H290.91L293.06 66.60L296.96 71.58L291.50 74.22L287.30 75.78Q286.22 76.07 285.15 76.46L294.04 80.66L301.85 84.28L298.53 89.94L295.79 94.73L288.86 90.53L280.56 86.43L271.48 83.20Q271.57 87.01 271.67 90.92L270.11 92.97L265.03 94.82L255.07 95.21L253.31 91.02L251.26 87.21L254.88 86.91L257.61 86.23L257.32 76.66V73.63Q257.32 68.16 257.22 62.70H256.24L240.03 62.89L239.64 58.69L238.96 54.30H257.22L257.12 51.66Q253.61 51.66 250.19 51.76L236.12 51.86L235.44 46.78L234.95 43.07Q245.89 43.07 256.83 42.97V40.04L254.29 40.14H239.64L239.05 35.45L238.27 31.25L251.75 31.15H256.54L256.34 26.27Q255.07 26.27 253.90 26.17L230.27 26.56L235.54 28.12L233.98 53.71L232.12 68.46L228.70 83.98L225.48 94.04L219.91 91.31L212.49 88.87L216.11 75.78L218.25 64.65L219.82 53.22L220.40 38.18L220.99 24.32H221.09L220.79 21.09L220.01 15.43L231.44 15.04L255.85 14.84Q255.66 10.64 255.36 6.35ZM231.24 82.91 236.71 80.47 242.47 78.81 246.96 77.15 242.38 75.49 232.71 73.34 234.07 68.46 235.83 63.18 246.57 65.62 254.97 68.26 252.82 73.05 251.65 75.39 253.61 74.61 255.07 80.47 256.63 84.28 250.09 86.23 235.44 92.97 233.39 87.79ZM390.03 81.45Q390.12 78.52 390.22 75.68V69.04L379.68 68.65Q376.26 68.75 372.74 68.85Q372.74 71.68 372.84 74.51Q372.94 78.03 372.94 81.45Q375.96 81.54 378.99 81.64ZM328.21 15.82 336.32 15.72 342.66 16.70 342.08 24.02 341.98 29.30Q343.74 29.30 345.59 29.20H356.53V36.04L356.14 43.07L344.42 42.77L329.48 42.97L316.30 43.36L315.91 36.82L315.71 30.27L326.36 29.59H328.41V27.44ZM317.86 46.88 324.79 45.61 330.95 45.21 332.21 60.55 333.00 68.26 320.98 70.41 319.32 59.38ZM316.10 71.97 333.19 70.02 343.05 68.95 337.49 68.07 338.66 59.57 339.83 43.55 346.86 44.34 354.29 46.78 351.36 62.40 349.89 68.16 355.26 67.58 356.04 75.49 356.73 80.47 331.34 83.30 317.18 84.96 316.79 79.10ZM370.98 11.33 379.58 11.13 387.29 12.11 386.51 24.61V29.49L387.98 29.39L404.58 28.52L404.87 35.35L404.68 41.99L391.79 41.89Q389.15 41.99 386.41 42.09Q386.41 44.43 386.41 46.88V54.39L402.33 54.69L406.04 56.93V82.32L405.85 94.04L398.62 93.85L378.99 93.46Q374.50 93.46 370.01 93.46L364.54 93.75L358.58 93.65L358.19 90.62L358.09 73.54L357.80 54.98L364.44 54.79Q365.22 54.79 365.91 54.79Q365.91 54.69 365.91 54.59Q368.93 54.49 371.96 54.49Q371.86 45.41 371.77 36.33Z"/></g><g transform="translate(40.0,36.7) scale(0.579)"><path d="M0 9 H56 L61 9 L65 2 L70 15 L75 9 H150" fill="none" stroke="#b8860b" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/></g></svg>"""

CAT_SVG = """<svg viewBox="0 0 48 48" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
      <path class="cat-body" d="M12 36C12 36 10 26 15 22C19 18.8 24 21 28 22C32 23 37 20 40 23C42 25 41 33 36 36H12Z"/>
      <path d="M14 23L12 16L18 19"/>
      <path d="M22 19L27 16L26 22"/>
      <path d="M40 26C43 23 45 16 41 13C38 10 35 15 37 19"/>
      <circle cx="15.6" cy="26.3" r="1.15" fill="currentColor" stroke="none"/>
      <circle cx="21.6" cy="26.3" r="1.15" fill="currentColor" stroke="none"/>
      <path class="cat-nose" d="M17.5 28.2H19.7L18.6 29.7Z"/>
    </svg>"""

ARTICLE_TEMPLATE = """\
<!DOCTYPE html>
<html lang="zh-TW">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <link rel="icon" type="image/svg+xml" href="../favicon.svg">
  <link rel="icon" type="image/png" sizes="32x32" href="../favicon-32.png">
  <link rel="apple-touch-icon" href="../favicon-180.png">
  <meta property="og:image" content="{site_url}/images/og-default.png">
  <title>{title} — 貓健康站</title>
  <meta name="description" content="{description}">
  <meta property="og:title" content="{title}">
  <meta property="og:description" content="{description}">
  <meta property="og:type" content="article">
  <link rel="canonical" href="{site_url}/articles/{slug}.html">
  <script type="application/ld+json">
  {{
    "@context": "https://schema.org",
    "@type": "Article",
    "headline": {title_json},
    "datePublished": "{date}",{date_modified_json}
    "author": {{"@type": "Person", "name": "Chen-MouChin", "url": "https://github.com/Chen-MouChin"}},
    "publisher": {{"@type": "Organization", "name": "貓健康站", "url": "{site_url}", "publishingPrinciples": "{site_url}/editorial.html"}}
  }}
  </script>
  <link rel="stylesheet" href="../css/theme.css?v=20260929">
  <script src="../js/theme.js"></script>
  <style>
    /* 文章頁｜套首頁的「溫暖插畫 × 公共服務」：同一個頁首頁尾、同一組色票與圓角。
       內文欄 720px 以內（一行約 38 字），文獻區用襯線體的期刊排版。 */
    :root {{ --ui: -apple-system, BlinkMacSystemFont, "PingFang TC", "Noto Sans TC", "Microsoft JhengHei", sans-serif; --serif: "Noto Serif TC", "Source Han Serif TC", "PMingLiU", Georgia, serif; --r-card: 18px; --r-pill: 999px; }}
    * {{ box-sizing: border-box; }}
    body {{ margin: 0; background: var(--bg); color: var(--text); font: 17px/1.8 var(--ui); -webkit-font-smoothing: antialiased; }}
    .page {{ max-width: 600px; margin: 0 auto; padding: 0 20px 24px; }}
    .vh {{ position: absolute !important; width: 1px; height: 1px; margin: -1px; padding: 0; overflow: hidden; clip: rect(0 0 0 0); clip-path: inset(50%); white-space: nowrap; border: 0; }}
    .i {{ width: 24px; height: 24px; flex: none; fill: none; stroke: currentColor; stroke-width: 2; stroke-linecap: round; stroke-linejoin: round; }}
    .skip {{ position: absolute; left: 12px; top: -60px; z-index: 5; padding: 8px 12px; }}
    .skip:focus-visible {{ top: 8px; }}

    /* 頁首：與首頁相同 */
    .site-head {{ display: grid; grid-template-columns: 1fr auto; grid-template-areas: "brand er" "nav nav"; align-items: center; column-gap: 12px; padding-top: 12px; }}
    .brand {{ grid-area: brand; display: inline-flex; justify-self: start; color: var(--text); border-radius: 6px; }}
    .brand svg {{ display: block; height: 38px; width: auto; }}
    .er-pill {{ grid-area: er; display: inline-flex; align-items: center; gap: 6px; min-height: 44px; padding: 0 16px 0 12px; border-radius: var(--r-pill); background: var(--emergency); color: var(--accent-on); font-size: 16px; font-weight: 700; text-decoration: none; box-shadow: 0 2px 0 var(--emergency-deep); }}
    .er-pill:hover {{ background: var(--emergency-deep); color: var(--accent-on); }}
    .er-pill .i {{ width: 20px; height: 20px; }}
    .main-nav {{ grid-area: nav; display: flex; gap: 22px; margin-top: 6px; overflow-x: auto; border-bottom: 2px solid var(--primary-pale); scrollbar-width: none; }}
    .main-nav::-webkit-scrollbar {{ display: none; }}
    .main-nav a {{ display: flex; align-items: center; min-height: 46px; color: var(--text); font-size: 16px; font-weight: 600; text-decoration: none; white-space: nowrap; }}
    .main-nav a:hover {{ color: var(--primary); text-decoration: underline; }}
    .main-nav a[aria-current] {{ color: var(--primary-deep); box-shadow: inset 0 -3px 0 var(--primary); }}
    .main-nav a:focus-visible {{ outline-offset: -3px; }}

    /* 文章欄 */
    .article-col {{ max-width: 720px; margin: 0 auto; }}
    .crumb {{ display: flex; flex-wrap: wrap; align-items: center; gap: 6px 10px; margin: 22px 0 10px; font-size: 14px; color: var(--text-muted); }}
    .crumb a {{ font-weight: 600; }}
    .cat-badge {{ display: inline-flex; align-items: center; min-height: 28px; padding: 0 10px; border-radius: var(--r-pill); background: var(--gold-pale); color: var(--text); font-size: 13px; font-weight: 700; }}
    article h1 {{ margin: 0; font-size: 30px; line-height: 1.3; letter-spacing: 0.01em; text-wrap: balance; color: var(--text); }}
    .article-meta {{ display: flex; flex-wrap: wrap; align-items: center; gap: 6px 14px; margin: 12px 0 0; font-size: 14px; color: var(--text-muted); }}
    .article-meta a {{ font-weight: 600; }}
    .lede {{ margin-top: 10px; }}

    /* 內文 */
    article {{ margin-top: 8px; }}
    article h2 {{ display: flex; align-items: center; gap: 10px; margin: 40px 0 12px; font-size: 22px; line-height: 1.35; }}
    article h2::before {{ content: ""; width: 30px; height: 14px; flex: none; background: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 30 14' fill='none' stroke='%23b8860b' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpath d='M1 7.5h9l2.2-5 3.6 9.5 3-7.5 1.7 3H29'/%3E%3C/svg%3E") no-repeat center / contain; }}
    article h3 {{ margin: 26px 0 8px; font-size: 18px; line-height: 1.4; color: var(--primary-deep); }}
    article p {{ margin: 0 0 16px; }}
    article ul, article ol {{ margin: 0 0 18px; padding-left: 1.3em; }}
    article li {{ margin: 6px 0; }}
    article li::marker {{ color: var(--primary); }}
    article strong {{ font-weight: 700; }}
    article a {{ font-weight: 600; text-underline-offset: 0.22em; }}
    article table {{ width: 100%; border-collapse: separate; border-spacing: 0; margin: 8px 0 20px; font-size: 15px; line-height: 1.55; border: 1px solid var(--border-strong); border-radius: 12px; overflow: hidden; }}
    article th {{ background: var(--primary-pale); color: var(--primary-deep); padding: 10px 12px; text-align: left; font-weight: 700; }}
    article td {{ padding: 9px 12px; border-top: 1px solid var(--border); vertical-align: top; }}
    article blockquote {{ margin: 0 0 18px; padding: 14px 18px; border-radius: 12px; background: var(--gold-pale); color: var(--text-2); }}
    article blockquote p:last-child {{ margin-bottom: 0; }}
    article hr {{ border: 0; border-top: 2px solid var(--primary-pale); margin: 28px 0; }}
    article code {{ background: var(--primary-pale); padding: 0.1em 0.4em; border-radius: 6px; font-size: 0.9em; }}
    article img {{ max-width: 100%; height: auto; border-radius: 12px; }}
    mark {{ background: var(--focus); padding: 0 2px; border-radius: 3px; }}
    article h2[id], article h3[id] {{ scroll-margin-top: 1rem; }}
    .article-hero {{ width: 100%; aspect-ratio: 16/9; max-height: 380px; object-fit: cover; border-radius: var(--r-card); margin: 18px 0 6px; display: block; background: var(--primary-pale); }}
    .article-hero[src=""], .article-hero:not([src]) {{ display: none; }}

    /* 「哪些情況建議請獸醫看看」：白卡加苔綠邊，語氣是建議，不用紅色、不用警示圖示 */
    .er-box {{ margin: 32px 0 8px; padding: 18px 20px 20px; border: 1px solid var(--border-strong); border-left: 4px solid var(--primary); border-radius: var(--r-card); background: var(--bg-card); }}
    .er-box h2 {{ margin: 0 0 8px; color: var(--primary-deep); }}
    .er-box p:last-child, .er-box ul:last-child, .er-box table:last-child {{ margin-bottom: 0; }}

    /* 「30 秒重點」：淺苔綠色塊 */
    .key-box {{ margin: 28px 0 8px; padding: 18px 20px; border-radius: var(--r-card); background: var(--primary-pale); }}
    .key-box h2 {{ margin: 0 0 6px; color: var(--primary-deep); }}
    .key-box ol {{ margin-bottom: 0; }}
    .key-box li {{ margin: 8px 0; }}

    /* 章節重點（markdown: > ⚡ 重點） */
    .section-hint {{ display: grid; grid-template-columns: auto 1fr; gap: 10px; margin: 6px 0 18px; padding: 12px 14px; border-radius: 12px; background: var(--gold-pale); font-size: 15px; line-height: 1.65; }}
    .section-hint .hint-label {{ color: var(--draft-text); font-weight: 700; white-space: nowrap; }}

    /* 句內註腳與參考文獻（期刊排版） */
    sup.fn {{ font-size: 0.72em; line-height: 0; vertical-align: super; margin-left: 1px; }}
    sup.fn a {{ display: inline-block; min-width: 1.5em; padding: 0 4px; border-radius: 6px; background: var(--primary-pale); color: var(--primary-deep); text-decoration: none; font-weight: 700; text-align: center; }}
    sup.fn a:hover {{ background: var(--primary); color: var(--accent-on); }}
    .sources-box, .references {{ margin-top: 40px; padding-top: 18px; border-top: 2px solid var(--primary-pale); font-family: var(--serif); }}
    .references h2, .sources-box h3 {{ font-family: var(--ui); font-size: 20px; margin: 0 0 10px; }}
    .references h2::before {{ display: none; }}
    .references ol {{ margin: 0; padding-left: 1.6em; font-size: 15px; line-height: 1.6; }}
    .references li {{ margin: 8px 0; padding-left: 4px; }}
    .references li::marker {{ color: var(--text-muted); font-family: var(--ui); font-size: 13px; }}
    .references .ref-title {{ color: var(--text); font-weight: 700; text-decoration: none; }}
    .references .ref-title:hover {{ text-decoration: underline; }}
    .references .ref-url {{ display: inline-block; margin-left: 6px; font-family: var(--ui); font-size: 13px; }}
    .references .ref-en {{ color: var(--text-2); font-size: 14px; }}
    .references .ref-meta {{ color: var(--text-muted); font-size: 13px; font-family: var(--ui); }}
    .references .ref-hint {{ margin-top: 10px; font-family: var(--ui); font-size: 13px; color: var(--text-muted); }}
    .sources-box ul {{ padding-left: 1.3em; font-size: 15px; }}

    /* 草稿警語、免責、找獸醫、相關文章 */
    .draft-warning {{ display: flex; flex-wrap: wrap; align-items: baseline; gap: 6px 10px; margin: 16px 0 0; padding: 12px 16px; border-radius: 12px; background: var(--gold-pale); color: var(--text-2); font-size: 15px; line-height: 1.6; }}
    .draft-warning .lbl {{ padding: 0 8px; border-radius: 6px; background: var(--gold-pale-deep); color: var(--draft-text); font-size: 13px; font-weight: 700; line-height: 1.7; }}
    .disclaimer {{ margin: 28px 0 0; font-size: 14px; line-height: 1.6; color: var(--text-muted); }}
    .find-vet-cta {{ display: flex; flex-wrap: wrap; align-items: center; gap: 10px 14px; margin: 32px 0 0; padding: 18px 20px; border-radius: var(--r-card); background: var(--primary-pale); }}
    .find-vet-cta .label {{ font-weight: 700; color: var(--primary-deep); }}
    .find-vet-cta a {{ display: inline-flex; align-items: center; min-height: 44px; padding: 0 18px; border-radius: var(--r-pill); background: var(--primary); color: var(--accent-on); font-weight: 700; text-decoration: none; box-shadow: 0 2px 0 var(--primary-deep); }}
    .find-vet-cta a:hover {{ background: var(--primary-deep); color: var(--accent-on); }}
    .find-vet-cta a:active {{ transform: translateY(2px); box-shadow: none; }}
    .related-box {{ margin: 32px 0 0; }}
    .related-box h3 {{ display: flex; align-items: center; gap: 10px; margin: 0 0 10px; font-size: 20px; color: var(--text); }}
    .related-box ul {{ display: grid; gap: 10px; margin: 0; padding: 0; list-style: none; }}
    .related-box li {{ margin: 0; }}
    .related-box a {{ display: block; padding: 14px 16px; border: 1px solid var(--border-strong); border-radius: 14px; background: var(--bg-card); color: var(--primary-deep); text-decoration: none; }}
    .related-box a:hover {{ border-color: var(--primary); text-decoration: underline; }}
    .tldr-box {{ margin: 18px 0 0; padding: 16px 18px; border-radius: var(--r-card); background: var(--primary-pale); }}
    .tldr-box .tldr-label {{ font-size: 13px; letter-spacing: 0.08em; color: var(--primary-deep); font-weight: 700; margin-bottom: 4px; }}
    .tldr-box ul {{ margin: 0; padding-left: 1.2em; }}
    .key-facts-grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin: 16px 0 0; }}
    .key-fact {{ padding: 14px 10px; border: 1px solid var(--border-strong); border-radius: 14px; background: var(--bg-card); text-align: center; }}
    .key-fact .kf-value {{ font-size: 26px; font-weight: 800; line-height: 1.15; color: var(--primary-deep); font-variant-numeric: tabular-nums; }}
    .key-fact .kf-label {{ margin-top: 4px; font-size: 14px; font-weight: 600; }}
    .key-fact .kf-note {{ margin-top: 2px; font-size: 13px; color: var(--text-muted); line-height: 1.4; }}
    .related-products {{ display: none; }}

    /* 廣告位：AdSense 上線前先隱藏 */
    .ad {{ margin-top: 32px; }}
    .ad-label {{ display: block; margin-bottom: 4px; font-size: 13px; letter-spacing: 0.1em; color: var(--text-muted); }}

    /* 頁尾：與首頁相同 */
    .foot {{ display: grid; gap: 10px; margin-top: 48px; padding-top: 20px; border-top: 2px solid var(--primary-pale); font-size: 15px; color: var(--text-2); }}
    .foot-cat {{ width: 64px; color: var(--primary); }}
    .foot-cat svg {{ display: block; width: 100%; height: auto; }}
    .cat-body {{ fill: var(--bg-card); }}
    .cat-nose {{ fill: var(--blush); stroke: var(--blush); stroke-width: 0.8; stroke-linejoin: round; }}
    .foot nav {{ display: flex; flex-wrap: wrap; column-gap: 18px; }}
    .foot nav a {{ display: inline-flex; align-items: center; min-height: 44px; font-weight: 400; }}
    .foot-src {{ font-size: 13px; color: var(--text-muted); }}

    @media (min-width: 880px) {{
      .page {{ max-width: 1000px; padding: 0 32px 32px; }}
      .site-head {{ grid-template-columns: auto 1fr auto; grid-template-areas: "brand nav er"; padding: 16px 0; border-bottom: 2px solid var(--primary-pale); }}
      .main-nav {{ justify-content: flex-end; margin: 0 8px 0 0; border: 0; }}
      .crumb {{ margin-top: 32px; }}
      article h1 {{ font-size: 40px; }}
      article h2 {{ font-size: 24px; }}
      .key-facts-grid {{ grid-template-columns: repeat(3, 1fr); }}
      .related-box ul {{ grid-template-columns: 1fr 1fr; }}
    }}
  </style>
</head>
<body>
<div class="page">
<a class="skip" href="#main">跳到主要內容</a>
<svg width="0" height="0" style="position:absolute" aria-hidden="true" focusable="false">
  <symbol id="i-alert" viewBox="0 0 24 24"><path d="M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z"/><path d="M12 9v4"/><path d="M12 17h.01"/></symbol>
</svg>

<header class="site-head">
  <a class="brand" href="../index.html" aria-label="貓健康站首頁">{brand_svg}</a>
  <a class="er-pill" href="../vets.html?only24h=1&amp;near=1"><svg class="i" aria-hidden="true"><use href="#i-alert"/></svg>24h 急診</a>
  <nav class="main-nav" aria-label="主要分頁">
    <a href="index.html" aria-current="page">文章</a>
    <a href="../vets.html">獸醫院</a>
    <a href="../library.html">文獻庫</a>
    <a href="../breeds.html">品種</a>
    <a href="../about.html">關於</a>
  </nav>
</header>

<main id="main" class="article-col">
  <nav class="crumb" aria-label="你在這裡">
    <a href="../index.html">首頁</a><span aria-hidden="true">›</span>
    <a href="index.html">文章</a><span aria-hidden="true">›</span>
    <span class="cat-badge">{cat_emoji} {category}</span>
  </nav>
  <article>
    <h1>{title}</h1>
    <div class="article-meta">
      <span>{date}</span>
{editor_meta_html}
    </div>
{draft_warning_html}
{cover_image_html}
{tldr_html}
{key_facts_html}

    {body}

    {related_products_html}

    {find_vet_html}

    {related_html}

    <p class="disclaimer">本文僅供參考，不構成獸醫診療建議。如有健康疑慮，請諮詢專業獸醫師。</p>

    {sources_html}
  </article>

  <aside class="ad" aria-label="贊助" hidden>
    <span class="ad-label">贊助</span>
  </aside>
</main>

<footer class="foot">
  <div class="foot-cat" aria-hidden="true">{cat_svg}</div>
  <nav aria-label="頁尾">
    <a href="index.html">文章</a>
    <a href="../vets.html">獸醫院</a>
    <a href="../library.html">文獻庫</a>
    <a href="../breeds.html">品種</a>
    <a href="../about.html">關於</a>
    <a href="../editorial.html">編輯方針</a>
    <a href="../privacy.html">隱私權政策</a>
  </nav>
  <p>本站內容僅供參考，不取代獸醫師診斷。</p>
  <p class="foot-src">學術來源：ISFM · WSAVA · IRIS · AAFP · ABCD · Cornell · PubMed OA</p>
</footer>
</div>
  <script src="../js/meta.js"></script>
  <script>
  (function(){{
    var q=new URLSearchParams(location.search).get('q');
    if(!q)return;
    var terms=q.split(/\\s+/).filter(Boolean);
    function walk(n){{
      if(n.nodeType===3){{
        var h=n.textContent,changed=false;
        for(var i=0;i<terms.length;i++){{
          var e=terms[i].replace(/[.*+?^${{}}()|[\\]\\\\]/g,'\\\\$&');
          if(new RegExp(e).test(h)){{h=h.replace(new RegExp(e,'g'),'<mark>'+terms[i]+'</mark>');changed=true;}}
        }}
        if(changed){{var s=document.createElement('span');s.innerHTML=h;n.parentNode.replaceChild(s,n);}}
      }}else if(n.nodeType===1&&['SCRIPT','STYLE','MARK'].indexOf(n.tagName)<0){{
        var kids=Array.from(n.childNodes);for(var j=0;j<kids.length;j++)walk(kids[j]);
      }}
    }}
    var art=document.querySelector('article');
    if(art)walk(art);
    var first=document.querySelector('mark');
    if(first)first.scrollIntoView({{behavior:'smooth',block:'center'}});
  }})();
  </script>
</body>
</html>
"""

ARTICLES_INDEX_TEMPLATE = """\
<!DOCTYPE html>
<html lang="zh-TW">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <link rel="icon" type="image/svg+xml" href="../favicon.svg">
  <link rel="icon" type="image/png" sizes="32x32" href="../favicon-32.png">
  <link rel="apple-touch-icon" href="../favicon-180.png">
  <meta property="og:image" content="https://chen-mouchin.github.io/cat-health-tw/images/og-default.png">
  <title>貓咪知識庫文章列表 — 貓健康站</title>
  <meta name="description" content="台灣養貓人完整知識庫：飲食、醫療、行為、居家環境，全部文章均佐證學術來源。">
  <link rel="stylesheet" href="../css/ads.css">
  <link rel="stylesheet" href="../css/theme.css">
  <link rel="stylesheet" href="../css/nav.css?v=20260420b">
  <script src="../js/theme.js"></script>
  <style>
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{ font-family: system-ui, "Noto Sans TC", sans-serif; background: var(--bg, #fafafa); color: var(--text, #333); }}
    header {{ background: var(--header-bg, #1d1d1f); color: var(--header-text, #fff); padding: 1rem 2rem; display: flex; align-items: center; gap: 1rem; }}
    header a {{ color: var(--header-text, #fff); text-decoration: none; opacity: 0.8; }}
    header h1 {{ font-size: 1.3rem; flex: 1; }}
    .ad-wrap {{ background: var(--bg-card, #fff); border-top: 1px solid var(--border, #eee); border-bottom: 1px solid var(--border, #eee); padding: 0.4rem 0; }}
    main {{ max-width: 960px; margin: 2rem auto; padding: 0 1.5rem; }}
    /* Filter bar */
    .search-bar {{ margin-bottom: 1rem; }}
    .search-bar input {{
      width: 100%; padding: 0.85rem 1.1rem; font-size: 1rem;
      border: 1px solid var(--border, #e0e0e0); border-radius: 24px;
      background: var(--bg-card, #fff); color: var(--text, #333);
      transition: border-color 0.15s, box-shadow 0.15s;
    }}
    .search-bar input:focus {{
      border-color: var(--accent, #1d1d1f);
      box-shadow: 0 0 0 3px rgba(0,0,0,0.05);
    }}
    .filter-bar {{ display: flex; gap: 0.5rem; flex-wrap: wrap; margin-bottom: 2rem; }}
    .filter-btn {{
      padding: 0.35rem 0.9rem; border: 1px solid var(--border, #ccc); border-radius: 20px;
      background: var(--bg-card, #fff); cursor: pointer; font-size: 0.88rem; text-decoration: none; color: var(--text, #333);
    }}
    .filter-btn.active, .filter-btn:hover {{ background: var(--accent, #1d1d1f); color: #fff; border-color: var(--accent, #1d1d1f); }}
    /* Category sections */
    .cat-section {{ margin-bottom: 2.5rem; }}
    .cat-heading {{
      font-size: 1.3rem; font-weight: 800; color: var(--accent, #1d1d1f);
      border-bottom: 2px solid var(--accent, #1d1d1f); padding-bottom: 0.4rem; margin-bottom: 1.2rem;
      display: flex; align-items: center; gap: 0.5rem;
    }}
    .cat-heading .count {{
      font-size: 0.85rem; font-weight: 400; color: var(--text-muted, #888);
      background: var(--accent-light, #f0f0f3); border-radius: 20px; padding: 0.1rem 0.5rem;
    }}
    /* Subcategory sections */
    .subcat-section {{ margin-bottom: 1.5rem; }}
    .subcat-heading {{
      font-size: 0.9rem; font-weight: 700; color: var(--text-muted, #666);
      text-transform: uppercase; letter-spacing: 0.06em;
      padding: 0.25rem 0.7rem; margin-bottom: 0.8rem;
      border-left: 3px solid var(--accent, #1d1d1f);
      background: var(--accent-light, #f0faf4);
    }}
    /* Article cards */
    .article-list {{ display: flex; flex-direction: column; gap: 0.7rem; }}
    .article-card {{
      background: var(--bg-card, #fff); border: 1px solid var(--border, #e0e0e0); border-radius: 10px;
      overflow: hidden; text-decoration: none; color: var(--text, inherit);
      display: flex; flex-direction: row; align-items: stretch;
      transition: box-shadow 0.15s; gap: 0;
    }}
    .article-card:hover {{ box-shadow: 0 4px 12px var(--shadow, rgba(0,0,0,0.1)); }}
    .article-card-thumb {{
      width: 130px; min-width: 130px; max-width: 130px; height: 90px;
      background-color: var(--accent-light, #f0f0f3);
      flex-shrink: 0; align-self: stretch;
      position: relative; overflow: hidden;
      display: flex; align-items: center; justify-content: center;
    }}
    .thumb-emoji {{ font-size: 2rem; z-index: 0; }}  /* 底層 emoji placeholder */
    .thumb-img {{
      position: absolute; inset: 0; width: 100%; height: 100%;
      object-fit: cover; z-index: 1;  /* 蓋在 emoji 上 */
    }}
    .article-card-body {{ padding: 0.8rem 1rem; flex: 1 1 auto; min-width: 0; }}
    .article-card .meta {{ font-size: 0.78rem; color: var(--text-muted, #888); margin-bottom: 0.3rem; display: flex; gap: 0.5rem; flex-wrap: wrap; align-items: center; }}
    .article-card .subcat-pill {{
      background: var(--border, #eee); color: var(--text-muted, #666); padding: 0.05rem 0.45rem;
      border-radius: 10px; font-size: 0.72rem;
    }}
    .article-card h2 {{ font-size: 1rem; font-weight: 700; margin-bottom: 0.25rem; color: var(--accent, #1d1d1f); }}
    .article-card p {{ font-size: 0.85rem; color: var(--text-muted, #666); line-height: 1.45; }}
    /* Quality badges (Phase 1B) */
    .quality-badge {{ font-size: 0.7rem; padding: 1px 6px; border-radius: 8px; }}
    .q-draft {{ background: #f5f0e8; color: #735f33; border: 1px solid #d4c8b0; }}
    .q-reviewed {{ background: #f0f0f3; color: #1d1d1f; border: 1px solid #d2d2d7; }}
    .q-featured {{ background: #1d1d1f; color: #fff; }}
    .article-card.is-draft {{ opacity: 0.65; }}
    .article-card.is-draft:hover {{ opacity: 1; }}
    body.hide-drafts .article-card.is-draft {{ display: none; }}
    .pending-note {{ font-size: 0.9rem; color: var(--text-muted, #636368); background: var(--bg-card, #fff); border: 1px solid var(--border, #e5e5ea); border-radius: 8px; padding: 0.6rem 0.9rem; margin: 0 0 1.2rem; }}
    .quality-toggle {{
      display: inline-flex; align-items: center; gap: 0.4rem; font-size: 0.85rem;
      padding: 0.35rem 0.9rem; border: 1px solid var(--border, #ccc); border-radius: 20px;
      background: var(--bg-card, #fff); cursor: pointer;
    }}
    .quality-toggle.active {{ background: var(--accent, #1d1d1f); color: var(--accent-on, #fff); border-color: var(--accent, #1d1d1f); }}
    @media (max-width: 600px) {{
      .article-card-thumb {{ width: 90px; min-width: 90px; height: 72px; }}
      .article-card h2 {{ font-size: 0.95rem; }}
    }}
    footer {{ text-align: center; padding: 1.5rem 2rem 2rem; color: var(--text-muted, #999); font-size: 0.85rem; }}
  </style>
</head>
<body>
  <nav class="site-nav">
    <a class="nav-brand" href="../index.html" title="回首頁"><svg class="brand-logo" viewBox="0 0 180 47" aria-label="貓健康站" role="img"><g transform="translate(0,15.2) scale(0.750)" fill="currentColor"><path d="M4 20 V2 L14 10 Z"/><path d="M36 20 V2 L26 10 Z"/><circle cx="13" cy="18" r="2.2"/><circle cx="27" cy="18" r="2.2"/></g><g transform="translate(40.0,0) scale(0.340)"><path fill="currentColor" d="M79.79 93.26 65.04 93.46 49.61 93.65 48.24 93.75H41.21L40.72 64.45L40.82 45.31L45.21 44.73V44.63H46.00L46.48 44.53L48.83 44.43L61.13 43.95H81.25L89.16 44.73L91.89 46.78L92.48 64.84L92.29 85.94L91.89 93.75H85.74ZM59.08 65.43 58.79 57.91 54.59 58.01V60.35L54.69 65.53ZM71.78 65.23 77.05 65.33 76.95 57.91H71.88ZM59.08 82.71V76.95L54.98 77.15L55.08 82.71H58.40ZM71.97 82.62H76.95L77.15 77.54V76.86H71.88ZM17.58 85.45 24.41 85.16 25.68 81.35 20.21 84.28ZM68.85 9.96 76.37 9.67 83.98 10.55 83.79 19.63 92.68 19.92V27.25L91.80 33.30L83.01 32.91L82.91 35.25L82.52 41.50L73.24 41.02L68.85 40.43L68.95 32.62L60.06 32.81L60.45 40.33L51.56 41.11L46.97 41.41L46.29 33.30L40.62 33.59L39.75 27.54L39.65 20.61L45.41 20.31L45.02 12.30L52.83 10.84L58.89 10.94L59.38 19.73L69.14 19.34V16.50ZM32.62 8.89 36.23 13.38 39.26 20.21 32.81 23.14 22.17 27.25 7.71 31.84 5.86 27.44 4.79 20.02 15.04 17.09 23.73 13.67ZM6.15 35.94 10.64 32.91 15.72 30.66 18.16 35.45 20.61 41.11 16.41 43.46 11.82 45.70 9.47 41.80ZM19.24 30.96 24.71 27.15 29.49 25.29 32.23 29.98 34.18 34.08 36.72 31.74 41.11 36.43 44.53 42.77 37.21 47.17 33.20 49.22 37.01 56.54 40.14 70.51 38.87 84.77 36.43 91.41 32.23 94.73 24.51 95.12 19.14 94.24 18.55 89.45 16.80 85.74 10.74 88.38 8.79 85.35 7.13 78.42 16.31 74.51 23.05 70.80 26.17 68.36 25.68 66.41 19.92 69.63 11.82 73.14 10.06 70.70 7.71 63.57 19.53 58.20 22.17 56.45 21.29 54.69 19.53 55.47 10.35 58.69 8.20 54.98 6.15 47.85 13.96 45.51 25.59 40.23 30.18 37.30 29.30 37.70 24.22 39.16 21.48 34.47ZM134.08 77.73 129.88 75.20 129.78 83.20ZM153.12 68.36 150.97 73.05 153.80 74.51ZM177.44 28.12H180.95L180.86 25.49L177.54 25.29ZM177.44 41.02 180.76 41.21 180.86 38.28H177.44ZM165.13 75.29 156.54 75.49 165.13 78.22ZM136.62 44.53 138.96 38.67 136.52 38.38 132.22 38.57 131.44 33.01 128.80 40.92 126.36 46.58 130.66 48.05 130.07 62.40 129.98 68.46 134.57 62.79 140.04 66.60 141.99 61.23 139.35 60.74 135.25 60.35 134.27 55.18 133.88 49.51ZM164.35 7.71 173.73 7.62 178.12 8.69 177.93 13.87H185.64L191.99 14.55L194.33 17.09L194.23 28.32L199.61 28.42V35.45L198.73 39.06L194.04 38.87L193.16 50.78H187.40L185.93 50.59L177.44 50.29L177.54 52.64L191.89 53.12L191.99 59.18L191.30 63.18L185.05 62.60L177.63 62.50V65.14L189.55 65.33L197.16 65.82V71.78L196.38 76.46L186.52 75.49L177.73 75.20L177.83 79.20L171.09 79.00L165.72 78.42L167.38 78.91L181.44 80.86L195.60 81.45L195.21 89.06L194.14 94.43L176.56 92.77L164.35 90.53L151.17 86.72L145.11 83.89L142.77 87.79L137.59 94.24L131.93 89.84L129.78 86.72L129.88 94.53H122.85L117.38 93.75L117.77 72.56V65.72L115.52 70.31L109.57 66.21L105.66 61.23L111.03 50.49L116.60 35.84L120.50 22.75L123.34 9.86L132.61 12.01L137.59 14.94L134.18 25.20L142.87 25.00L148.82 25.49L151.17 31.64L152.05 38.28L150.48 42.87L146.97 49.22L151.07 49.41L153.61 50.29L155.17 56.25L155.46 61.33L154.39 65.62L165.23 65.23V62.50L157.91 62.79L156.93 58.30L157.22 52.93L165.23 52.73V50.29L155.27 50.49L154.59 46.78L154.68 41.21L165.04 41.11V38.28L153.61 38.38L152.83 32.71L153.02 28.12L164.94 28.03L164.84 25.39L155.37 25.49L154.49 21.00L154.39 14.16L164.55 13.96ZM271.09 42.87Q275.58 42.87 279.97 42.77Q280.07 41.41 280.17 40.14Q275.68 39.94 271.18 39.75Q271.09 40.62 271.09 41.50ZM271.18 54.10H279.58Q279.58 52.73 279.68 51.37Q279.29 51.37 278.80 51.37Q274.99 51.46 271.09 51.46Q271.18 52.83 271.18 54.10ZM271.28 70.02 279.29 66.99 286.12 64.06 287.79 63.09H286.42H279.29V62.60L271.28 62.70H271.18ZM273.53 73.34 271.28 70.31V72.75ZM255.36 6.35 266.40 8.40 270.79 9.08 270.50 15.14Q275.58 15.23 280.66 15.33H299.31L299.11 22.17L298.43 27.64L277.34 26.66L262.10 26.37L266.01 27.54L272.06 28.52Q271.96 29.88 271.87 31.15H280.46L292.47 32.13L294.91 34.28L294.62 43.16L302.82 43.36L302.14 48.05L301.95 52.05L294.33 51.86L293.64 63.09H290.91L293.06 66.60L296.96 71.58L291.50 74.22L287.30 75.78Q286.22 76.07 285.15 76.46L294.04 80.66L301.85 84.28L298.53 89.94L295.79 94.73L288.86 90.53L280.56 86.43L271.48 83.20Q271.57 87.01 271.67 90.92L270.11 92.97L265.03 94.82L255.07 95.21L253.31 91.02L251.26 87.21L254.88 86.91L257.61 86.23L257.32 76.66V73.63Q257.32 68.16 257.22 62.70H256.24L240.03 62.89L239.64 58.69L238.96 54.30H257.22L257.12 51.66Q253.61 51.66 250.19 51.76L236.12 51.86L235.44 46.78L234.95 43.07Q245.89 43.07 256.83 42.97V40.04L254.29 40.14H239.64L239.05 35.45L238.27 31.25L251.75 31.15H256.54L256.34 26.27Q255.07 26.27 253.90 26.17L230.27 26.56L235.54 28.12L233.98 53.71L232.12 68.46L228.70 83.98L225.48 94.04L219.91 91.31L212.49 88.87L216.11 75.78L218.25 64.65L219.82 53.22L220.40 38.18L220.99 24.32H221.09L220.79 21.09L220.01 15.43L231.44 15.04L255.85 14.84Q255.66 10.64 255.36 6.35ZM231.24 82.91 236.71 80.47 242.47 78.81 246.96 77.15 242.38 75.49 232.71 73.34 234.07 68.46 235.83 63.18 246.57 65.62 254.97 68.26 252.82 73.05 251.65 75.39 253.61 74.61 255.07 80.47 256.63 84.28 250.09 86.23 235.44 92.97 233.39 87.79ZM390.03 81.45Q390.12 78.52 390.22 75.68V69.04L379.68 68.65Q376.26 68.75 372.74 68.85Q372.74 71.68 372.84 74.51Q372.94 78.03 372.94 81.45Q375.96 81.54 378.99 81.64ZM328.21 15.82 336.32 15.72 342.66 16.70 342.08 24.02 341.98 29.30Q343.74 29.30 345.59 29.20H356.53V36.04L356.14 43.07L344.42 42.77L329.48 42.97L316.30 43.36L315.91 36.82L315.71 30.27L326.36 29.59H328.41V27.44ZM317.86 46.88 324.79 45.61 330.95 45.21 332.21 60.55 333.00 68.26 320.98 70.41 319.32 59.38ZM316.10 71.97 333.19 70.02 343.05 68.95 337.49 68.07 338.66 59.57 339.83 43.55 346.86 44.34 354.29 46.78 351.36 62.40 349.89 68.16 355.26 67.58 356.04 75.49 356.73 80.47 331.34 83.30 317.18 84.96 316.79 79.10ZM370.98 11.33 379.58 11.13 387.29 12.11 386.51 24.61V29.49L387.98 29.39L404.58 28.52L404.87 35.35L404.68 41.99L391.79 41.89Q389.15 41.99 386.41 42.09Q386.41 44.43 386.41 46.88V54.39L402.33 54.69L406.04 56.93V82.32L405.85 94.04L398.62 93.85L378.99 93.46Q374.50 93.46 370.01 93.46L364.54 93.75L358.58 93.65L358.19 90.62L358.09 73.54L357.80 54.98L364.44 54.79Q365.22 54.79 365.91 54.79Q365.91 54.69 365.91 54.59Q368.93 54.49 371.96 54.49Q371.86 45.41 371.77 36.33Z"/></g><g transform="translate(40.0,36.7) scale(0.579)"><path d="M0 9 H56 L61 9 L65 2 L70 15 L75 9 H150" fill="none" stroke="#b8860b" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/></g></svg><span class="brand-home" aria-hidden="true">🏠</span></a>
    <div class="nav-links">
      <a class="nav-link" href="../library.html" data-nav="library">📚 文獻庫</a>
      <a class="nav-link" href="../breeds.html" data-nav="breeds">🐈 品種</a>
      <a class="nav-link" href="../vets.html" data-nav="vets">🏥 獸醫院</a>
      <a class="nav-link active" href="index.html" data-nav="articles">📝 文章</a>
      <a class="nav-link" href="../about.html" data-nav="about">ℹ️ 關於</a>
    </div>
  </nav>

  <main>
    <div class="search-bar">
      <input type="search" id="articleSearch" placeholder="🔍 搜尋文章標題或內容（例：腎指數、亂尿尿、結紮）">
    </div>
    <div class="filter-bar">
      <button class="filter-btn" data-cat="全部">全部</button>
      <button class="filter-btn" data-cat="入門">🆕 入門</button>
      <button class="filter-btn" data-cat="健康">❤️ 健康</button>
      <button class="filter-btn" data-cat="飲食">🍖 飲食</button>
      <button class="filter-btn" data-cat="行為">🐾 行為</button>
      <button class="filter-btn" data-cat="環境">🏠 環境</button>
      <button class="filter-btn" data-cat="階段">⏳ 階段</button>
      <span style="margin-left:auto"></span>
      <label class="quality-toggle" id="qualityToggle">
        <input type="checkbox" id="hideDraftsCb" style="margin:0">
        <span>只看已審核</span>
      </label>
    </div>
{pending_note}
    <div id="articleSections">
{article_sections}
    </div>
  </main>

  <aside class="site-ad-banner" aria-label="贊助廣告">
    <div class="ad-card">
      <div class="ad-label">贊助 Sponsored</div>
      <div class="ad-slot"><span>Ad Slot · banner (responsive)</span></div>
    </div>
  </aside>

  <footer class="site-footer">
    <div class="f-nav">
      <a class="f-home" href="../index.html">🏠 回首頁</a>
      <a href="../library.html">📚 文獻庫</a>
      <a href="../breeds.html">🐈 品種圖鑑</a>
      <a href="../vets.html">🏥 獸醫院</a>
      <a href="index.html">📝 文章</a>
      <a href="../about.html">ℹ️ 關於本站</a>
      <a href="../editorial.html">📋 編輯方針</a>
      <a href="../privacy.html">🔒 隱私政策</a>
    </div>
    <div class="f-meta">
      貓健康站 · 學術來源：ISFM · WSAVA · IRIS · AAFP · ABCD · Cornell · PubMed OA<br>
      本站內容僅供參考，不取代獸醫師診斷<br>
      © 2026 · Built by <a href="https://github.com/Chen-MouChin" target="_blank" rel="noopener">Chen-MouChin</a>
    </div>
  </footer>

  <aside class="site-ad-anchor" aria-label="贊助廣告">
    <div class="ad-label">贊助</div>
    <div class="ad-slot"><span>Ad Slot · anchor (sticky bottom)</span></div>
    <button class="ad-close" aria-label="關閉廣告 24 小時" title="關閉 24 小時">✕</button>
  </aside>
  <script src="../js/ads.js"></script>
  <script src="../js/meta.js"></script>
  <script src="../js/i18n.js"></script>
  <script>
    var fd=document.getElementById('footer-date');if(fd&&typeof SITE_META!=='undefined')fd.textContent=SITE_META.data_updated;
    // Category filter
    (function(){{
      var sections = document.querySelectorAll('.cat-section');
      var btns = document.querySelectorAll('.filter-btn');
      function activate(cat) {{
        sections.forEach(function(s){{ s.style.display = (cat==='全部'||s.dataset.cat===cat)?'':'none'; }});
        btns.forEach(function(b){{ b.classList.toggle('active', b.dataset.cat===cat); }});
      }}
      btns.forEach(function(b){{ b.addEventListener('click', function(){{ activate(b.dataset.cat); }}); }});
      var init = new URLSearchParams(location.search).get('cat') || '全部';
      activate(init);
    }})();
    // 文章搜尋（標題 / 描述 / 副分類）
    (function(){{
      var input = document.getElementById('articleSearch');
      if (!input) return;
      var cards = document.querySelectorAll('.article-card');
      function filter(q) {{
        q = (q||'').trim().toLowerCase();
        cards.forEach(function(c){{
          var hay = c.textContent.toLowerCase();
          c.style.display = (q === '' || hay.indexOf(q) !== -1) ? '' : 'none';
        }});
        // 隱藏空的 subcat-section / cat-section
        document.querySelectorAll('.subcat-section').forEach(function(sec){{
          var visible = sec.querySelectorAll('.article-card:not([style*="none"])').length;
          sec.style.display = visible > 0 ? '' : 'none';
        }});
        document.querySelectorAll('.cat-section').forEach(function(sec){{
          var visible = sec.querySelectorAll('.article-card:not([style*="none"])').length;
          // 只有搜尋有內容時才隱藏空 cat-section（保留分類 filter 行為）
          if (q) sec.style.display = visible > 0 ? '' : 'none';
        }});
      }}
      input.addEventListener('input', function(){{ filter(input.value); }});
      // 從 URL ?q= 預填（首頁搜尋框跳轉用）
      var urlQ = new URLSearchParams(location.search).get('q');
      if (urlQ) {{ input.value = urlQ; filter(urlQ); }}
    }})();
    // Quality filter (hide drafts)
    (function(){{
      var cb = document.getElementById('hideDraftsCb');
      var lbl = document.getElementById('qualityToggle');
      var KEY = 'nekopedia_hide_drafts';
      // 統計 reviewed 文章數 — 若 0 則隱藏此 toggle 避免使用者誤勾後一片空白
      var reviewedCount = document.querySelectorAll('.article-card[data-quality="reviewed"], .article-card[data-quality="featured"]').length;
      if (reviewedCount === 0) {{
        // 強制取消任何 localStorage 殘留 + 隱藏 toggle
        document.body.classList.remove('hide-drafts');
        localStorage.removeItem(KEY);
        if (lbl) lbl.style.display = 'none';
        return;
      }}
      function apply(v) {{
        document.body.classList.toggle('hide-drafts', v);
        lbl.classList.toggle('active', v);
        localStorage.setItem(KEY, v ? '1' : '0');
      }}
      var saved = localStorage.getItem(KEY) === '1';
      cb.checked = saved;
      apply(saved);
      cb.addEventListener('change', function(){{ apply(cb.checked); }});
    }})();
  </script>
</body>
</html>
"""

CATEGORY_RELATED: dict[str, str] = {
    "飲食": "乾糧",
    "居家環境": "貓砂",
}


def build_articles() -> list[dict]:
    """Convert all content/articles/*.md → frontend/articles/{slug}.html"""
    ARTICLES_DIR.mkdir(parents=True, exist_ok=True)
    mds = sorted(CONTENT_DIR.glob("*.md"))
    articles_meta = []

    # Pass 1: 收集 slug → title，給 related 反向連結用；同時記下哪些 slug 已審核可上線
    slug_to_title: dict[str, str] = {}
    public_slugs: set[str] = set()
    for md_path in mds:
        if md_path.name == "README.md":
            continue
        try:
            _m, _ = _parse_front_matter(md_path.read_text(encoding="utf-8"))
            _slug = _m.get("slug") or md_path.stem
            slug_to_title[_slug] = _m.get("title", _slug)
            if (_m.get("quality") or "draft").strip().lower() in PUBLISHED_QUALITIES:
                public_slugs.add(_slug)
        except Exception:
            continue

    def strip_links_to_drafts(html: str) -> str:
        """已審文章內文若連到未審文章，拿掉 <a> 只留文字，線上才不會 404。"""
        def repl(m):
            target = m.group("slug")
            return m.group(0) if (target in public_slugs or target == "index") else m.group("text")
        return re.sub(r'<a\b[^>]*href="(?:\./)?(?P<slug>[\w-]+)\.html(?:#[^"]*)?"[^>]*>(?P<text>.*?)</a>', repl, html, flags=re.S)

    for md_path in mds:
        if md_path.name == "README.md":
            continue
        text = md_path.read_text(encoding="utf-8")
        meta, body_md = _parse_front_matter(text)
        # 過濾 HTML 註解（如「改寫參考連結」不進公開 HTML）
        body_md = re.sub(r'<!--.*?-->', '', body_md, flags=re.S)
        slug = meta.get("slug") or md_path.stem
        title = meta.get("title", slug)
        date = meta.get("date") or meta.get("created", "")
        category = meta.get("category", "")
        sources = meta.get("sources", [])
        quality = (meta.get("quality") or "draft").strip().lower()
        is_public = quality in PUBLISHED_QUALITIES
        last_reviewed = meta.get("last_reviewed", "")

        body_md, references_html, cited_keys = _process_footnotes(body_md, slug)
        body_html = _md_to_html(body_md)
        if is_public:
            body_html = strip_links_to_drafts(body_html)
        # 內文開頭的「# 標題」改由模板的 <h1> 顯示，這裡拿掉以免重複
        # （toc 擴充會替標題加 id，所以要容許 <h1 id="...">）
        body_html = re.sub(r"^\s*<h1\b[^>]*>.*?</h1>\s*", "", body_html, count=1, flags=re.S)
        # 章節重點約定：blockquote 以「⚡ 重點」開頭 → 渲染為 .section-hint 醒目盒
        body_html = re.sub(
            r'<blockquote>\s*<p>⚡\s*重點[:：]?\s*(.*?)</p>\s*</blockquote>',
            r'<div class="section-hint"><span class="hint-label">⚡ 重點</span>'
            r'<span class="hint-body">\1</span></div>',
            body_html,
            flags=re.S,
        )
        # 固定兩節包成色塊：「哪些情況建議請獸醫看看」白卡苔綠邊，「30 秒重點」淺苔綠；範圍到下一個 h2 為止
        def _wrap_section(html: str, heading_re: str, cls: str) -> str:
            m = re.search(r'<h2\b[^>]*>\s*' + heading_re + r'\s*</h2>', html)
            if not m:
                return html
            nxt = re.search(r'<h2\b', html[m.end():])
            end = m.end() + nxt.start() if nxt else len(html)
            return html[:m.start()] + f'<section class="{cls}">' + html[m.start():end].rstrip() + '</section>\n' + html[end:]
        body_html = _wrap_section(body_html, r'(?:哪些情況建議請獸醫看看|何時該立刻就醫|何時需要就醫[？?]?)', "er-box")
        body_html = _wrap_section(body_html, r'30\s*秒重點', "key-box")

        # Auto-generate description from first <p> if not in front matter
        description = meta.get("description", "")
        if not description:
            p_match = re.search(r"<p>(.*?)</p>", body_html, re.DOTALL)
            if p_match:
                description = re.sub(r"<[^>]+>", "", p_match.group(1))[:150].strip()

        # 有句內註腳 → 只顯示自動產生的「參考文獻」；沒有 → 退回 frontmatter sources 清單
        sources_html = ""
        if references_html:
            sources_html = references_html
        elif sources:
            items = "\n".join(f"      <li>{s}</li>" for s in sources)
            sources_html = f"""<div class="sources-box">
      <h3>資料來源</h3>
      <ul>
{items}
      </ul>
    </div>"""

        # 商品比價已 archived（見 research/archived-features.md），不再插入連結
        related_products_html = ""

        cat_emoji = CATEGORY_EMOJI.get(category, "📖")
        cover_image = meta.get("cover_image", "")
        cover_image_html = ""
        if cover_image:
            src = cover_image if cover_image.startswith("http") else f"../{cover_image}"
            # onerror: 圖載失敗時隱藏，避免破圖 icon（背景色已是 placeholder）
            cover_image_html = f'    <img class="article-hero" src="{src}" alt="{title}" loading="lazy" onerror="this.style.display=\'none\'">'

        # Draft warning banner (Phase 1B)
        draft_warning_html = ""
        if quality == "draft":
            draft_warning_html = (
                '    <div class="draft-warning">'
                '<span class="lbl">DRAFT</span>'
                '本文為 AI 草稿，尚未經人工審核校對，醫療資訊請務必再次與獸醫師確認，勿據此自行診斷或用藥。'
                '</div>'
            )

        # 編輯／審核揭露（E-E-A-T）：人類編輯 + AI 起草，連到 editorial.html
        # last_reviewed 為 null/空 → 只顯示編輯者；有日期 → 加「審核 {日期}」並寫進 schema dateModified
        lr = str(last_reviewed).strip() if last_reviewed not in (None, "", "null", "None") else ""
        editor_meta_html = (
            '      <span>✍️ 編輯 <a href="https://github.com/Chen-MouChin" target="_blank" rel="noopener">Chen-MouChin</a>'
            ' · AI 協助起草 · <a href="../editorial.html">編輯方針</a></span>'
        )
        if lr:
            editor_meta_html += f'\n      <span>✅ 審核 {_escape_html(lr)}</span>'
        date_modified_json = f'\n    "dateModified": "{_escape_html(lr)}",' if lr else ""

        # 文末「找獸醫」CTA（從文章 frontmatter 的 find_vet 欄位）
        # 值：cat_only（→ vets.html?cat=1）/ emergency（→ ?only24h=1&near=1，進站即定位）/ both
        find_vet_html = ""
        find_vet = (meta.get("find_vet") or "").strip().lower()
        if find_vet == "cat_only":
            find_vet_html = (
                '<div class="find-vet-cta">'
                '<span class="label">需要找獸醫？</span>'
                '<a href="../vets.html?cat=1">查貓專科醫院</a>'
                '</div>'
            )
        elif find_vet == "emergency":
            find_vet_html = (
                '<div class="find-vet-cta">'
                '<span class="label">需要找獸醫？</span>'
                '<a href="../vets.html?only24h=1&amp;near=1">查附近的 24 小時動物醫院</a>'
                '</div>'
            )
        elif find_vet == "both":
            find_vet_html = (
                '<div class="find-vet-cta">'
                '<span class="label">需要找獸醫？</span>'
                '<a href="../vets.html?cat=1">查貓專科醫院</a>'
                '<a href="../vets.html?only24h=1&amp;near=1">查附近 24 小時醫院</a>'
                '</div>'
            )

        # === UX 改造：重點速看 / Key Facts / Related（見 feedback_neko_ux_philosophy）===
        tldr_html = ""
        tldr = meta.get("tldr") or []
        if isinstance(tldr, list) and tldr:
            _rendered = []
            for t in tldr:
                # TL;DR bullets 支援 markdown（[文字](#錨點) / **粗體** 等）
                h = _md_to_html(str(t)).strip()
                h = re.sub(r"^<p>(.*?)</p>\s*$", r"\1", h, flags=re.S)
                _rendered.append(f"        <li>{h}</li>")
            _items = "\n".join(_rendered)
            tldr_html = (
                '    <div class="tldr-box">\n'
                '      <div class="tldr-label">⚡ 重點速看</div>\n'
                '      <ul>\n'
                f'{_items}\n'
                '      </ul>\n'
                '    </div>'
            )

        key_facts_html = ""
        kf = meta.get("key_facts") or []
        if isinstance(kf, list) and kf:
            cards = []
            for item in kf:
                if not isinstance(item, dict):
                    continue
                value = _escape_html(item.get("value", ""))
                label = _escape_html(item.get("label", ""))
                note = _escape_html(item.get("note", ""))
                note_html = f'        <div class="kf-note">{note}</div>\n' if note else ''
                cards.append(
                    '      <div class="key-fact">\n'
                    f'        <div class="kf-value">{value}</div>\n'
                    f'        <div class="kf-label">{label}</div>\n'
                    f'{note_html}'
                    '      </div>'
                )
            if cards:
                key_facts_html = (
                    '    <div class="key-facts-grid">\n'
                    + "\n".join(cards)
                    + '\n    </div>'
                )

        related_html = ""
        related = meta.get("related") or []
        # 內文已有手寫的「相關文章」一節（附一句說明）就不再加站內相關盒，免得同一批連結列兩次
        has_related_section = re.search(r"<h2\b[^>]*>\s*相關文章\s*</h2>", body_html)
        if isinstance(related, list) and related and not has_related_section:
            rel_items = []
            for rel_slug in related:
                rel_slug = rel_slug.strip()
                if not rel_slug:
                    continue
                if is_public and rel_slug not in public_slugs:
                    continue  # 上線的文章不列未審的相關文
                rel_title = slug_to_title.get(rel_slug, rel_slug)
                rel_items.append(
                    f'        <li><a href="./{rel_slug}.html">{_escape_html(rel_title)}</a></li>'
                )
            if rel_items:
                related_html = (
                    '    <div class="related-box">\n'
                    '      <h3>📚 站內相關</h3>\n'
                    '      <ul>\n'
                    + "\n".join(rel_items) + '\n'
                    '      </ul>\n'
                    '    </div>'
                )

        output = ARTICLE_TEMPLATE.format(
            brand_svg=BRAND_SVG,
            cat_svg=CAT_SVG,
            title=title,
            title_json=json.dumps(title),
            description=description,
            slug=slug,
            site_url=SITE_URL,
            category=category,
            cat_emoji=cat_emoji,
            date=str(date),
            date_modified_json=date_modified_json,
            editor_meta_html=editor_meta_html,
            body=body_html,
            sources_html=sources_html,
            related_products_html=related_products_html,
            cover_image_html=cover_image_html,
            draft_warning_html=draft_warning_html,
            find_vet_html=find_vet_html,
            tldr_html=tldr_html,
            key_facts_html=key_facts_html,
            related_html=related_html,
        )

        out_dir = ARTICLES_DIR if is_public else DRAFTS_DIR
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / f"{slug}.html").write_text(output, encoding="utf-8")
        subcategory = SUBCATEGORY_MAP.get(slug, meta.get("subcategory", ""))
        articles_meta.append({
            "slug": slug,
            "public": is_public,
            "title": title,
            "description": description,
            "date": str(date),
            "category": category,
            "subcategory": subcategory,
            "cover_image": cover_image,
            "tags": meta.get("tags", []),
            "quality": quality,
            "last_reviewed": str(last_reviewed) if last_reviewed else "",
            "citations": cited_keys,
            "body_text": re.sub(r"<[^>]+>", "", body_html)[:800],
        })

    # 清掉已下架或改回草稿的舊 HTML，frontend/articles/ 只能有已審文章
    removed = 0
    for old in ARTICLES_DIR.glob("*.html"):
        if old.name != "index.html" and not old.name.startswith("_") and old.stem not in public_slugs:
            old.unlink()
            removed += 1
    for old in DRAFTS_DIR.glob("*.html"):
        if old.stem in public_slugs or old.stem not in slug_to_title:
            old.unlink()
    n_pub = len(public_slugs)
    print(f"  Built {len(articles_meta)} articles：{n_pub} 篇已審 → {ARTICLES_DIR}/，"
          f"{len(articles_meta) - n_pub} 篇草稿 → {DRAFTS_DIR}/（不進 git）"
          + (f"；移除 {removed} 個未審 HTML" if removed else ""))
    return articles_meta


def sanitize_hand_pages(public_slugs: set[str]):
    """手寫頁連到未上線文章的 <a> 拆成 <span data-draft-link>，審核通過後自動還原成連結。"""
    public_slugs = set(public_slugs) | {"index"}  # articles/index.html 是列表頁，永遠存在
    pat_a = re.compile(r'<a\b(?P<pre>[^>]*?)\s*href="(?P<rel>(?:\.\./)?)articles/(?P<slug>[\w-]+)\.html"(?P<post>[^>]*)>(?P<text>.*?)</a>', re.S)
    pat_s = re.compile(r'<span\b(?P<pre>[^>]*?)\s*data-draft-link="(?P<rel>(?:\.\./)?)articles/(?P<slug>[\w-]+)\.html"(?P<post>[^>]*)>(?P<text>.*?)</span>', re.S)
    for name in HAND_PAGES:
        path = FRONTEND_DIR / name
        if not path.exists():
            continue
        src = path.read_text(encoding="utf-8")
        n = []

        def to_span(m):
            if m.group("slug") in public_slugs:
                return m.group(0)
            n.append(m.group("slug"))
            return f'<span{m.group("pre")} data-draft-link="{m.group("rel")}articles/{m.group("slug")}.html"{m.group("post")}>{m.group("text")}</span>'

        def to_a(m):
            if m.group("slug") not in public_slugs:
                return m.group(0)
            n.append(m.group("slug"))
            return f'<a{m.group("pre")} href="{m.group("rel")}articles/{m.group("slug")}.html"{m.group("post")}>{m.group("text")}</a>'

        html = pat_a.sub(to_span, src)
        html = pat_s.sub(to_a, html)
        if html != src:
            path.write_text(html, encoding="utf-8")
            print(f"  {name}：{len(n)} 個文章連結依審核狀態切換（{', '.join(n)}）")


def build_404():
    """GitHub Pages 用根目錄的 404.html；路徑不定，連結與樣式一律用絕對網址。"""
    base = SITE_URL.rstrip("/")
    html = f"""<!DOCTYPE html>
<html lang="zh-TW">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta name="robots" content="noindex">
<title>找不到這一頁 — 貓健康站</title>
<link rel="icon" type="image/svg+xml" href="{base}/favicon.svg">
<link rel="stylesheet" href="{base}/css/theme.css">
<style>
  body {{ margin: 0; font-family: system-ui, "Noto Sans TC", sans-serif; background: var(--bg, #f9f6f0); color: var(--text, #1d1d1f); }}
  main {{ max-width: 560px; margin: 0 auto; padding: 4rem 1.25rem; }}
  h1 {{ font-size: 1.6rem; margin: 0 0 0.6rem; }}
  p {{ line-height: 1.7; color: var(--text-muted, #636368); }}
  ul {{ padding-left: 1.2rem; line-height: 2; }}
  a {{ color: var(--primary, #3b6a50); }}
</style>
</head>
<body>
<main>
  <h1>找不到這一頁</h1>
  <p>這個網址沒有內容。可能是文章還在審核、已經下架，或網址打錯了。</p>
  <ul>
    <li><a href="{base}/">回首頁</a></li>
    <li><a href="{base}/articles/index.html">已審核的文章</a></li>
    <li><a href="{base}/vets.html?only24h=1">找 24 小時急診動物醫院</a></li>
    <li><a href="{base}/library.html">學術文獻庫</a></li>
  </ul>
  <p>貓有狀況的話，建議直接聯絡附近的動物醫院。</p>
</main>
</body>
</html>
"""
    out = FRONTEND_DIR / "404.html"
    out.write_text(html, encoding="utf-8")
    print(f"  → {out}")


def build_articles_index(articles: list[dict], n_pending: int = 0):
    """Generate frontend/articles/index.html with category→subcategory grouping."""
    from collections import defaultdict

    # Group: category → subcategory → [articles sorted by date desc]
    grouped: dict[str, dict[str, list]] = defaultdict(lambda: defaultdict(list))
    for a in sorted(articles, key=lambda x: x["date"], reverse=True):
        cat = a["category"]
        sub = a.get("subcategory") or "其他"
        grouped[cat][sub].append(a)

    def make_card(a: dict) -> str:
        cover = a.get("cover_image", "")
        cat_emoji = CATEGORY_EMOJI.get(a["category"], "📖")
        # 結構：thumb div 內含 emoji + (可選) img
        # img absolute 蓋在 emoji 上：載入成功 → 顯示圖；載入失敗 → onerror 移除 img → emoji 顯示
        # overflow:hidden 防止破圖 alt 文字撐爆 layout
        if cover:
            thumb_src = cover if cover.startswith("http") else f"../{cover}"
            thumb_html = (
                f'<div class="article-card-thumb">'
                f'<span class="thumb-emoji">{cat_emoji}</span>'
                f'<img class="thumb-img" src="{thumb_src}" alt="" loading="lazy" onerror="this.remove()">'
                f'</div>'
            )
        else:
            thumb_html = f'<div class="article-card-thumb"><span class="thumb-emoji">{cat_emoji}</span></div>'
        sub = a.get("subcategory", "")
        subcat_pill = f'<span class="subcat-pill">{sub}</span>' if sub else ""
        # Draft / quality badge (Phase 1B)
        q = a.get("quality", "draft")
        if q == "draft":
            quality_badge = '<span class="quality-badge q-draft">DRAFT 未審</span>'
            extra_class = " is-draft"
        elif q == "reviewed":
            quality_badge = '<span class="quality-badge q-reviewed">已審核</span>'
            extra_class = ""
        elif q == "featured":
            quality_badge = '<span class="quality-badge q-featured">精選</span>'
            extra_class = ""
        elif q == "ai-reviewed":
            quality_badge = '<span class="quality-badge q-ai-reviewed">AI 初審</span>'
            extra_class = ""
        else:
            quality_badge = ""
            extra_class = ""
        return (
            f'          <a class="article-card{extra_class}" href="{a["slug"]}.html" data-quality="{q}">\n'
            f'            {thumb_html}\n'
            f'            <div class="article-card-body">\n'
            f'              <div class="meta">{subcat_pill}{quality_badge}<span>📅 {a["date"]}</span></div>\n'
            f'              <h2>{a["title"]}</h2>\n'
            f'              <p>{a["description"]}</p>\n'
            f'            </div>\n'
            f'          </a>'
        )

    # Category display order (品種已遷 breeds 系統，文章列表不顯示)
    cat_order = ["入門", "健康", "飲食", "行為", "環境", "階段"]
    sections_html = []
    for cat in cat_order:
        if cat not in grouped:
            continue
        cat_emoji = CATEGORY_EMOJI.get(cat, "📖")
        subcat_data = grouped[cat]
        subcat_order = CATEGORY_SUBCAT_ORDER.get(cat, sorted(subcat_data.keys()))
        # Ensure any subcategories not in order list appear at end
        extra = [s for s in subcat_data if s not in subcat_order]
        total = sum(len(v) for v in subcat_data.values())

        subcat_sections = []
        for sub in subcat_order + extra:
            if sub not in subcat_data:
                continue
            cards_html = "\n".join(make_card(a) for a in subcat_data[sub])
            subcat_sections.append(
                f'      <div class="subcat-section">\n'
                f'        <div class="subcat-heading">{sub}</div>\n'
                f'        <div class="article-list">\n'
                f'{cards_html}\n'
                f'        </div>\n'
                f'      </div>'
            )

        sections_html.append(
            f'    <div class="cat-section" data-cat="{cat}">\n'
            f'      <h2 class="cat-heading">{cat_emoji} {cat} <span class="count">{total} 篇</span></h2>\n'
            + "\n".join(subcat_sections) + "\n"
            f'    </div>'
        )

    pending_note = (
        f'    <p class="pending-note">目前公開 {len(articles)} 篇。另有 {n_pending} 篇完成撰寫、正在逐篇審核，通過後陸續上架。</p>'
        if n_pending else ""
    )
    html = ARTICLES_INDEX_TEMPLATE.format(article_sections="\n".join(sections_html), pending_note=pending_note)
    out = ARTICLES_DIR / "index.html"
    out.write_text(html, encoding="utf-8")
    print(f"  → {out} ({len(articles)} articles)")


def build_search_index(articles: list[dict]):
    """Generate frontend/js/articles-data.js and copy vet data to frontend."""
    import shutil as _shutil, json as _json
    js_out = FRONTEND_DIR / "js" / "articles-data.js"
    js_out.parent.mkdir(parents=True, exist_ok=True)
    js_out.write_text(
        "window.ARTICLES_INDEX = " + _json.dumps(articles, ensure_ascii=False, indent=2) + ";\n",
        encoding="utf-8"
    )
    print(f"  → {js_out} ({len(articles)} articles)")
    vet_src = ROOT / "data" / "vets" / "taipei_newtaipei_vets.json"
    vet_dst = FRONTEND_DIR / "data" / "vets.json"
    if vet_src.exists():
        vet_dst.parent.mkdir(parents=True, exist_ok=True)
        _shutil.copy2(vet_src, vet_dst)
        print(f"  → {vet_dst}")
    else:
        print(f"  [vets] {vet_src} not found — skipping")

    # 複製 library.html 需要的 JSON（讓 frontend/ 可獨立部署，不需 serve content/）
    for fname in ("citations.json", "glossary.json"):
        src = ROOT / "content" / "references" / fname
        dst = FRONTEND_DIR / "data" / fname
        if src.exists():
            dst.parent.mkdir(parents=True, exist_ok=True)
            _shutil.copy2(src, dst)
            print(f"  → {dst}")


def build_breed_pages() -> list[dict]:
    """Generate frontend/breeds/{slug}.html for each breed (SEO)
    Lightweight redirect-style page: server-rendered metadata + link back to breeds.html?id=xx.
    The actual UX lives in breeds.html via JS; these standalone pages exist for search engines."""
    breeds_json = ROOT / "data" / "breeds" / "breeds.json"
    if not breeds_json.exists():
        print("  [breeds] data/breeds/breeds.json not found, skip")
        return []
    data = json.loads(breeds_json.read_text(encoding="utf-8"))
    breeds = data.get("breeds", [])
    out_dir = FRONTEND_DIR / "breeds"
    out_dir.mkdir(parents=True, exist_ok=True)
    built = []
    for b in breeds:
        slug = b.get("slug") or b.get("id")
        if not slug:
            continue
        name_zh = b.get("name_zh", "")
        name_en = b.get("name_en", "")
        origin = b.get("origin", "")
        life = b.get("life_span_years") or []
        weight = b.get("weight_kg") or []
        temperament = ", ".join((b.get("temperament_zh") or [])[:5])
        desc = b.get("description_zh") or b.get("description_en", "")
        desc_meta = (desc[:160] + "…") if len(desc) > 160 else desc
        images = b.get("images") or []
        hero = ""
        if images:
            first = images[0]
            hero = first if isinstance(first, str) else first.get("url", "")

        life_str = f"{life[0]}-{life[1]} 年" if len(life) == 2 else ""
        weight_str = f"{weight[0]}-{weight[1]} kg" if len(weight) == 2 else ""

        # 結構化資料（schema.org）
        schema = {
            "@context": "https://schema.org",
            "@type": "Article",
            "headline": f"{name_zh} {name_en}｜品種資料",
            "description": desc_meta,
            "author": {"@type": "Organization", "name": "貓健康站"},
            "publisher": {"@type": "Organization", "name": "貓健康站"},
            "about": {
                "@type": "Thing",
                "name": name_en or name_zh,
                "alternateName": name_zh,
            },
        }
        if hero:
            schema["image"] = hero
        breed_robots_meta = "" if BREEDS_INDEXABLE else '<meta name="robots" content="noindex,follow">'

        html = f"""<!DOCTYPE html>
<html lang="zh-TW">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
{breed_robots_meta}
<link rel="icon" type="image/svg+xml" href="../favicon.svg">
<link rel="icon" type="image/png" sizes="32x32" href="../favicon-32.png">
<link rel="apple-touch-icon" href="../favicon-180.png">
<meta property="og:image" content="https://chen-mouchin.github.io/cat-health-tw/images/og-default.png">
<title>{name_zh}（{name_en}）品種資料 — 貓健康站</title>
<meta name="description" content="{name_zh} 品種資料：原產 {origin}、壽命 {life_str}、體重 {weight_str}。{desc_meta}">
<meta property="og:title" content="{name_zh}（{name_en}）— 貓健康站 品種圖鑑">
<meta property="og:description" content="{desc_meta}">
<meta property="og:type" content="article">
{f'<meta property="og:image" content="{hero}">' if hero else ''}
<link rel="canonical" href="{SITE_URL}/breeds/{slug}.html">
<link rel="alternate" href="{SITE_URL}/breeds.html?id={b.get('id', slug)}" title="完整互動版（篩選 / 比較）">
<script type="application/ld+json">{json.dumps(schema, ensure_ascii=False)}</script>
<link rel="stylesheet" href="../css/theme.css">
<link rel="stylesheet" href="../css/nav.css?v=20260420b">
<script src="../js/theme.js"></script>
<style>
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{ font-family: system-ui, "Noto Sans TC", sans-serif; background: var(--bg, #fafafa); color: var(--text, #1d1d1f); }}
main {{ max-width: 760px; margin: 1.5rem auto; padding: 0 1rem 2rem; }}
h1 {{ font-size: 1.6rem; margin-bottom: 0.3rem; }}
h1 .en {{ font-size: 0.95rem; font-weight: 400; color: var(--text-muted, #6e6e73); margin-left: 0.3rem; }}
.alt {{ font-size: 0.82rem; color: var(--text-faint, #a1a1a6); margin-bottom: 0.8rem; }}
.hero {{ width: 100%; max-height: 360px; object-fit: contain; background: var(--accent-light, #f0ede6); border-radius: 10px; margin-bottom: 1rem; display: block; }}
.attrs {{ display: grid; grid-template-columns: 1fr 1fr; gap: 0.4rem 1rem; font-size: 0.9rem; margin: 0.8rem 0 1.2rem; }}
.attrs .lbl {{ color: var(--text-muted, #6e6e73); }}
.desc {{ font-size: 0.95rem; line-height: 1.75; color: var(--text); margin-bottom: 1.5rem; }}
.cta {{
  display: inline-block; padding: 0.6rem 1.2rem;
  background: var(--accent, #1d1d1f); color: var(--accent-on, #fff);
  border-radius: 20px; text-decoration: none; font-weight: 600; font-size: 0.9rem;
}}
.cta:hover {{ background: var(--accent-hover, #424245); }}
.tags {{ margin: 0.8rem 0 1.2rem; display: flex; flex-wrap: wrap; gap: 0.3rem; }}
.tags .t {{ background: var(--accent-light, #f0ede6); padding: 2px 9px; border-radius: 10px; font-size: 0.78rem; color: var(--text, #1d1d1f); }}
</style>
</head>
<body>
<nav class="site-nav">
  <a class="nav-brand" href="../index.html" title="回首頁"><svg class="brand-logo" viewBox="0 0 180 47" aria-label="貓健康站" role="img"><g transform="translate(0,15.2) scale(0.750)" fill="currentColor"><path d="M4 20 V2 L14 10 Z"/><path d="M36 20 V2 L26 10 Z"/><circle cx="13" cy="18" r="2.2"/><circle cx="27" cy="18" r="2.2"/></g><g transform="translate(40.0,0) scale(0.340)"><path fill="currentColor" d="M79.79 93.26 65.04 93.46 49.61 93.65 48.24 93.75H41.21L40.72 64.45L40.82 45.31L45.21 44.73V44.63H46.00L46.48 44.53L48.83 44.43L61.13 43.95H81.25L89.16 44.73L91.89 46.78L92.48 64.84L92.29 85.94L91.89 93.75H85.74ZM59.08 65.43 58.79 57.91 54.59 58.01V60.35L54.69 65.53ZM71.78 65.23 77.05 65.33 76.95 57.91H71.88ZM59.08 82.71V76.95L54.98 77.15L55.08 82.71H58.40ZM71.97 82.62H76.95L77.15 77.54V76.86H71.88ZM17.58 85.45 24.41 85.16 25.68 81.35 20.21 84.28ZM68.85 9.96 76.37 9.67 83.98 10.55 83.79 19.63 92.68 19.92V27.25L91.80 33.30L83.01 32.91L82.91 35.25L82.52 41.50L73.24 41.02L68.85 40.43L68.95 32.62L60.06 32.81L60.45 40.33L51.56 41.11L46.97 41.41L46.29 33.30L40.62 33.59L39.75 27.54L39.65 20.61L45.41 20.31L45.02 12.30L52.83 10.84L58.89 10.94L59.38 19.73L69.14 19.34V16.50ZM32.62 8.89 36.23 13.38 39.26 20.21 32.81 23.14 22.17 27.25 7.71 31.84 5.86 27.44 4.79 20.02 15.04 17.09 23.73 13.67ZM6.15 35.94 10.64 32.91 15.72 30.66 18.16 35.45 20.61 41.11 16.41 43.46 11.82 45.70 9.47 41.80ZM19.24 30.96 24.71 27.15 29.49 25.29 32.23 29.98 34.18 34.08 36.72 31.74 41.11 36.43 44.53 42.77 37.21 47.17 33.20 49.22 37.01 56.54 40.14 70.51 38.87 84.77 36.43 91.41 32.23 94.73 24.51 95.12 19.14 94.24 18.55 89.45 16.80 85.74 10.74 88.38 8.79 85.35 7.13 78.42 16.31 74.51 23.05 70.80 26.17 68.36 25.68 66.41 19.92 69.63 11.82 73.14 10.06 70.70 7.71 63.57 19.53 58.20 22.17 56.45 21.29 54.69 19.53 55.47 10.35 58.69 8.20 54.98 6.15 47.85 13.96 45.51 25.59 40.23 30.18 37.30 29.30 37.70 24.22 39.16 21.48 34.47ZM134.08 77.73 129.88 75.20 129.78 83.20ZM153.12 68.36 150.97 73.05 153.80 74.51ZM177.44 28.12H180.95L180.86 25.49L177.54 25.29ZM177.44 41.02 180.76 41.21 180.86 38.28H177.44ZM165.13 75.29 156.54 75.49 165.13 78.22ZM136.62 44.53 138.96 38.67 136.52 38.38 132.22 38.57 131.44 33.01 128.80 40.92 126.36 46.58 130.66 48.05 130.07 62.40 129.98 68.46 134.57 62.79 140.04 66.60 141.99 61.23 139.35 60.74 135.25 60.35 134.27 55.18 133.88 49.51ZM164.35 7.71 173.73 7.62 178.12 8.69 177.93 13.87H185.64L191.99 14.55L194.33 17.09L194.23 28.32L199.61 28.42V35.45L198.73 39.06L194.04 38.87L193.16 50.78H187.40L185.93 50.59L177.44 50.29L177.54 52.64L191.89 53.12L191.99 59.18L191.30 63.18L185.05 62.60L177.63 62.50V65.14L189.55 65.33L197.16 65.82V71.78L196.38 76.46L186.52 75.49L177.73 75.20L177.83 79.20L171.09 79.00L165.72 78.42L167.38 78.91L181.44 80.86L195.60 81.45L195.21 89.06L194.14 94.43L176.56 92.77L164.35 90.53L151.17 86.72L145.11 83.89L142.77 87.79L137.59 94.24L131.93 89.84L129.78 86.72L129.88 94.53H122.85L117.38 93.75L117.77 72.56V65.72L115.52 70.31L109.57 66.21L105.66 61.23L111.03 50.49L116.60 35.84L120.50 22.75L123.34 9.86L132.61 12.01L137.59 14.94L134.18 25.20L142.87 25.00L148.82 25.49L151.17 31.64L152.05 38.28L150.48 42.87L146.97 49.22L151.07 49.41L153.61 50.29L155.17 56.25L155.46 61.33L154.39 65.62L165.23 65.23V62.50L157.91 62.79L156.93 58.30L157.22 52.93L165.23 52.73V50.29L155.27 50.49L154.59 46.78L154.68 41.21L165.04 41.11V38.28L153.61 38.38L152.83 32.71L153.02 28.12L164.94 28.03L164.84 25.39L155.37 25.49L154.49 21.00L154.39 14.16L164.55 13.96ZM271.09 42.87Q275.58 42.87 279.97 42.77Q280.07 41.41 280.17 40.14Q275.68 39.94 271.18 39.75Q271.09 40.62 271.09 41.50ZM271.18 54.10H279.58Q279.58 52.73 279.68 51.37Q279.29 51.37 278.80 51.37Q274.99 51.46 271.09 51.46Q271.18 52.83 271.18 54.10ZM271.28 70.02 279.29 66.99 286.12 64.06 287.79 63.09H286.42H279.29V62.60L271.28 62.70H271.18ZM273.53 73.34 271.28 70.31V72.75ZM255.36 6.35 266.40 8.40 270.79 9.08 270.50 15.14Q275.58 15.23 280.66 15.33H299.31L299.11 22.17L298.43 27.64L277.34 26.66L262.10 26.37L266.01 27.54L272.06 28.52Q271.96 29.88 271.87 31.15H280.46L292.47 32.13L294.91 34.28L294.62 43.16L302.82 43.36L302.14 48.05L301.95 52.05L294.33 51.86L293.64 63.09H290.91L293.06 66.60L296.96 71.58L291.50 74.22L287.30 75.78Q286.22 76.07 285.15 76.46L294.04 80.66L301.85 84.28L298.53 89.94L295.79 94.73L288.86 90.53L280.56 86.43L271.48 83.20Q271.57 87.01 271.67 90.92L270.11 92.97L265.03 94.82L255.07 95.21L253.31 91.02L251.26 87.21L254.88 86.91L257.61 86.23L257.32 76.66V73.63Q257.32 68.16 257.22 62.70H256.24L240.03 62.89L239.64 58.69L238.96 54.30H257.22L257.12 51.66Q253.61 51.66 250.19 51.76L236.12 51.86L235.44 46.78L234.95 43.07Q245.89 43.07 256.83 42.97V40.04L254.29 40.14H239.64L239.05 35.45L238.27 31.25L251.75 31.15H256.54L256.34 26.27Q255.07 26.27 253.90 26.17L230.27 26.56L235.54 28.12L233.98 53.71L232.12 68.46L228.70 83.98L225.48 94.04L219.91 91.31L212.49 88.87L216.11 75.78L218.25 64.65L219.82 53.22L220.40 38.18L220.99 24.32H221.09L220.79 21.09L220.01 15.43L231.44 15.04L255.85 14.84Q255.66 10.64 255.36 6.35ZM231.24 82.91 236.71 80.47 242.47 78.81 246.96 77.15 242.38 75.49 232.71 73.34 234.07 68.46 235.83 63.18 246.57 65.62 254.97 68.26 252.82 73.05 251.65 75.39 253.61 74.61 255.07 80.47 256.63 84.28 250.09 86.23 235.44 92.97 233.39 87.79ZM390.03 81.45Q390.12 78.52 390.22 75.68V69.04L379.68 68.65Q376.26 68.75 372.74 68.85Q372.74 71.68 372.84 74.51Q372.94 78.03 372.94 81.45Q375.96 81.54 378.99 81.64ZM328.21 15.82 336.32 15.72 342.66 16.70 342.08 24.02 341.98 29.30Q343.74 29.30 345.59 29.20H356.53V36.04L356.14 43.07L344.42 42.77L329.48 42.97L316.30 43.36L315.91 36.82L315.71 30.27L326.36 29.59H328.41V27.44ZM317.86 46.88 324.79 45.61 330.95 45.21 332.21 60.55 333.00 68.26 320.98 70.41 319.32 59.38ZM316.10 71.97 333.19 70.02 343.05 68.95 337.49 68.07 338.66 59.57 339.83 43.55 346.86 44.34 354.29 46.78 351.36 62.40 349.89 68.16 355.26 67.58 356.04 75.49 356.73 80.47 331.34 83.30 317.18 84.96 316.79 79.10ZM370.98 11.33 379.58 11.13 387.29 12.11 386.51 24.61V29.49L387.98 29.39L404.58 28.52L404.87 35.35L404.68 41.99L391.79 41.89Q389.15 41.99 386.41 42.09Q386.41 44.43 386.41 46.88V54.39L402.33 54.69L406.04 56.93V82.32L405.85 94.04L398.62 93.85L378.99 93.46Q374.50 93.46 370.01 93.46L364.54 93.75L358.58 93.65L358.19 90.62L358.09 73.54L357.80 54.98L364.44 54.79Q365.22 54.79 365.91 54.79Q365.91 54.69 365.91 54.59Q368.93 54.49 371.96 54.49Q371.86 45.41 371.77 36.33Z"/></g><g transform="translate(40.0,36.7) scale(0.579)"><path d="M0 9 H56 L61 9 L65 2 L70 15 L75 9 H150" fill="none" stroke="#b8860b" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/></g></svg><span class="brand-home" aria-hidden="true">🏠</span></a>
  <div class="nav-links">
    <a class="nav-link" href="../library.html" data-nav="library">📚 文獻庫</a>
    <a class="nav-link active" href="../breeds.html" data-nav="breeds">🐈 品種</a>
    <a class="nav-link" href="../vets.html" data-nav="vets">🏥 獸醫院</a>
    <a class="nav-link" href="../articles/index.html" data-nav="articles">📝 文章</a>
    <a class="nav-link" href="../about.html" data-nav="about">ℹ️ 關於</a>
  </div>
</nav>

<main>
  <h1>{name_zh}<span class="en">{name_en}</span></h1>
  {f'<div class="alt">別名：{", ".join(b.get("alt_names", []))}</div>' if b.get("alt_names") else ''}
  {f'<img class="hero" src="{hero}" alt="{name_zh}">' if hero else ''}

  <div class="attrs">
    <div><span class="lbl">📍 原產：</span>{origin}</div>
    <div><span class="lbl">⏳ 壽命：</span>{life_str}</div>
    <div><span class="lbl">⚖️ 體重：</span>{weight_str}</div>
    <div><span class="lbl">💗 代表性格：</span>{temperament}</div>
  </div>

  {f'<div class="tags">{"".join(f"<span class=\'t\'>{t}</span>" for t in (b.get("temperament_zh") or [])[:8])}</div>' if b.get("temperament_zh") else ''}

  <div class="desc">{desc}</div>

  <a class="cta" href="../breeds.html?id={b.get('id', slug)}">進入互動版（搜尋 / 比較 / 學術研究觀察）→</a>
</main>

<aside class="site-ad-banner" aria-label="贊助廣告">
  <div class="ad-card">
    <div class="ad-label">贊助 Sponsored</div>
    <div class="ad-slot"><span>Ad Slot · banner (responsive)</span></div>
  </div>
</aside>

<footer class="site-footer">
  <div class="f-nav">
    <a class="f-home" href="../index.html">🏠 回首頁</a>
    <a href="../library.html">📚 文獻庫</a>
    <a href="../breeds.html">🐈 品種圖鑑</a>
    <a href="../vets.html">🏥 獸醫院</a>
    <a href="../articles/index.html">📝 文章</a>
    <a href="../about.html">ℹ️ 關於本站</a>
    <a href="../editorial.html">📋 編輯方針</a>
    <a href="../privacy.html">🔒 隱私政策</a>
  </div>
  <div class="f-meta">
    貓健康站 · 品種資料 © TheCatAPI (CC0) + Wikimedia Commons（CC BY-SA）<br>
    本站內容僅供參考，不取代獸醫師診斷
  </div>
</footer>
<aside class="site-ad-anchor" aria-label="贊助廣告">
  <div class="ad-label">贊助</div>
  <div class="ad-slot"><span>Ad Slot · anchor (sticky bottom)</span></div>
  <button class="ad-close" aria-label="關閉廣告 24 小時" title="關閉 24 小時">✕</button>
</aside>
<script src="../js/ads.js"></script>
</body>
</html>
"""
        (out_dir / f"{slug}.html").write_text(html, encoding="utf-8")
        built.append({"slug": slug, "id": b.get("id", slug), "name_zh": name_zh})
    print(f"  Built {len(built)} breed pages → {out_dir}/")
    return built


def build_sitemap(articles: list[dict], breeds: list[dict] = None):
    """Generate frontend/sitemap.xml — exclude draft articles (Phase 1B policy)"""
    today = datetime.now().strftime("%Y-%m-%d")
    # Phase 1 期間，只露出 library.html（唯一可信內容）+ 首頁/about
    # articles/index.html 全是 draft 不上 sitemap；search.html 已重定向至 library
    urls = [
        f"  <url><loc>{SITE_URL}/</loc><changefreq>weekly</changefreq><priority>1.0</priority></url>",
        f"  <url><loc>{SITE_URL}/library.html</loc><changefreq>weekly</changefreq><priority>0.9</priority></url>",
        f"  <url><loc>{SITE_URL}/breeds.html</loc><changefreq>weekly</changefreq><priority>0.9</priority></url>",
        f"  <url><loc>{SITE_URL}/vets.html</loc><changefreq>monthly</changefreq><priority>0.8</priority></url>",
        f"  <url><loc>{SITE_URL}/about.html</loc><changefreq>monthly</changefreq><priority>0.4</priority></url>",
        f"  <url><loc>{SITE_URL}/editorial.html</loc><changefreq>monthly</changefreq><priority>0.4</priority></url>",
    ]
    published = [a for a in articles if a.get("quality") in ("reviewed", "featured")]
    skipped_drafts = len(articles) - len(published)
    for a in published:
        urls.append(
            f'  <url><loc>{SITE_URL}/articles/{a["slug"]}.html</loc>'
            f'<lastmod>{a["date"]}</lastmod><changefreq>monthly</changefreq><priority>0.7</priority></url>'
        )
    # 品種頁內容未經人工審核，先不給搜尋引擎（頁面本身也標 noindex）；審過再把 BREEDS_INDEXABLE 打開
    for br in (breeds or []) if BREEDS_INDEXABLE else []:
        urls.append(
            f'  <url><loc>{SITE_URL}/breeds/{br["slug"]}.html</loc>'
            f'<changefreq>monthly</changefreq><priority>0.6</priority></url>'
        )
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        + "\n".join(urls)
        + "\n</urlset>\n"
    )
    SITEMAP_XML.write_text(xml, encoding="utf-8")
    print(f"  → {SITEMAP_XML} ({len(urls)} URLs, excluded {skipped_drafts} drafts)")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

# 首頁「數字＋單位」對應的統計鍵
HOME_STAT_UNITS = {"篇": "articles", "筆": "citations", "種": "breeds", "家": "vets"}


def sync_home_stats(articles: list, n_breeds: int, n_public: int | None = None):
    """首頁 index.html 是手寫的，但上面的數字與草稿標籤由這裡依實際資料寫入，文章或文獻增刪後不必手改。
    - data-stat="vets|articles|citations|breeds" 的元素：改內文與 data-to（數字跑碼的終點）
    - 其他「數字＋單位」的文字（meta 描述、結構化資料、報讀器說明句、「看全部 N 篇」）：直接改數字
    - data-quality-of="slug" 的標籤：依該篇 quality 寫「草稿」或「已審核」
    縣市數照使用者原稿寫 22，不在這裡改（資料裡連江縣 0 家，要不要改 21 待使用者決定，見 docs/TODO.md）。
    另外檢查主標的字是否都在粉圓子集裡。
    """
    home = FRONTEND_DIR / "index.html"
    if not home.exists():
        return
    # 首頁的「N 篇」是線上看得到的篇數（已審），不是全部草稿
    actual = {"articles": len(articles) if n_public is None else n_public, "breeds": n_breeds}
    try:
        cites = json.loads((ROOT / "content" / "references" / "citations.json").read_text(encoding="utf-8"))
        actual["citations"] = len([k for k in cites if not k.startswith("_")])
    except (OSError, ValueError):
        pass
    try:
        vets = json.loads((ROOT / "data" / "vets" / "all_vets.json").read_text(encoding="utf-8"))
        actual["vets"] = len(vets)
    except (OSError, ValueError):
        pass

    src = home.read_text(encoding="utf-8")
    changed = []

    def stat_elem(m):
        key = m.group("key")
        if key not in actual:
            return m.group(0)
        old, new = m.group("text"), f"{actual[key]:,}"
        if old != new:
            changed.append(f"{key} {old} → {new}")
        open_tag = re.sub(r'data-to="\d+"', f'data-to="{actual[key]}"', m.group("open"))
        return f"{open_tag}{new}{m.group('close')}"

    html = re.sub(r'(?P<open><(?P<tag>\w+)\b[^>]*\bdata-stat="(?P<key>\w+)"[^>]*>)(?P<text>[^<]*)(?P<close></(?P=tag)>)',
                  stat_elem, src)

    def stat_text(m):
        key = HOME_STAT_UNITS[m.group(3)]
        if key not in actual:
            return m.group(0)
        new = f"{actual[key]:,}"
        if m.group(1) != new:
            changed.append(f"{m.group(1)} {m.group(3)} → {new} {m.group(3)}")
        return f"{new}{m.group(2)}{m.group(3)}"

    html = re.sub(r"(\d[\d,]*)(\s*)(篇|筆|種|家)", stat_text, html)

    quality = {a["slug"]: (a.get("quality") or "draft") for a in articles}
    missing = []

    def quality_tag(m):
        slug = m.group("slug")
        if slug not in quality:
            missing.append(slug)
            return m.group(0)
        if quality[slug] in ("reviewed", "featured"):
            new = f'<span class="tag-reviewed" data-quality-of="{slug}">已審核</span>'
        else:
            new = f'<span class="tag-draft" data-quality-of="{slug}">草稿</span>'
        if new != m.group(0):
            changed.append(f"{slug} 標籤 → {'已審核' if 'reviewed' in new else '草稿'}")
        return new

    html = re.sub(r'<span class="tag-(?:draft|reviewed)" data-quality-of="(?P<slug>[\w-]+)">[^<]*</span>', quality_tag, html)

    # 未審文章線上沒有頁面：主題捷徑的 <li> 加 hidden、推薦文章的標題連結改成純文字；審核通過後自動還原
    def pill(m):
        slug = m.group("slug")
        if slug not in quality:
            return m.group(0)
        if quality[slug] in PUBLISHED_QUALITIES:
            return f'<li><a class="pill" href="articles/{slug}.html">'
        # 草稿：整個 li 藏起來，而且不留 href，連結檢查工具才不會抓到 404
        return f'<li hidden data-draft-of="{slug}"><a class="pill" data-draft-href="articles/{slug}.html">'
    html2 = re.sub(r'<li(?: hidden data-draft-of="[\w-]+")?><a class="pill" (?:href|data-draft-href)="articles/(?P<slug>[\w-]+)\.html">', pill, html)

    def card(m):
        slug, text = m.group("slug") or m.group("slug2"), m.group("text")
        if slug not in quality:
            return m.group(0)
        if quality[slug] in PUBLISHED_QUALITIES:
            return f'<h3><a href="articles/{slug}.html">{text}</a></h3>'
        return f'<h3><span data-draft-link="articles/{slug}.html">{text}</span></h3>'
    html2 = re.sub(r'<h3>(?:<a href="articles/(?P<slug>[\w-]+)\.html">|<span data-draft-link="articles/(?P<slug2>[\w-]+)\.html">)'
                   r'(?P<text>[^<]*)</(?:a|span)></h3>', card, html2)
    # 推薦文章整張卡：草稿就整個 hidden，不只拿掉連結
    def post_card(m):
        inner = m.group("inner")
        slugs = re.findall(r'data-quality-of="([\w-]+)"', inner)
        is_draft = any(quality.get(s, "draft") not in PUBLISHED_QUALITIES for s in slugs)
        return f'<article class="post"{" hidden" if is_draft else ""}>{inner}</article>'
    html2 = re.sub(r'<article class="post"(?: hidden)?>(?P<inner>.*?)</article>', post_card, html2, flags=re.S)
    if html2 != html:
        changed.append("未審文章的首頁捷徑與推薦卡已隱藏")
        html = html2

    if html != src:
        home.write_text(html, encoding="utf-8")
        print("  index.html 已依實際資料更新：" + "；".join(dict.fromkeys(changed)))
    else:
        print("  index.html 的數字與草稿標籤與實際一致")
    for slug in missing:
        print(f"  [warn] index.html 列了不存在的文章 {slug}（已歸檔或改名？）")

    # about.html 的「資料品質實況」數字也手寫：只動有 data-stat 的元素，不做全文「數字＋單位」替換
    # （about 有「46 筆 stub」這種歷史事實，全文替換會改錯）
    try:
        vets_js = (FRONTEND_DIR / "data" / "vets.js").read_text(encoding="utf-8")
        actual["vets_approx"] = vets_js.count('"ap":1')
        actual["vets_misplaced"] = vets_js.count('"ap":2')
    except OSError:
        pass
    about = FRONTEND_DIR / "about.html"
    if about.exists():
        changed.clear()
        a_src = about.read_text(encoding="utf-8")
        a_html = re.sub(r'(?P<open><(?P<tag>\w+)\b[^>]*\bdata-stat="(?P<key>\w+)"[^>]*>)(?P<text>[^<]*)(?P<close></(?P=tag)>)',
                        stat_elem, a_src)
        if a_html != a_src:
            about.write_text(a_html, encoding="utf-8")
            print("  about.html 數字已更新：" + "；".join(dict.fromkeys(changed)))

    # 主標用的粉圓是子集字型，改了主標要重抓
    rng = re.search(r"unicode-range:\s*([^;]+);", html)
    h1 = re.search(r"<h1\b[^>]*>(.*?)</h1>", html, re.S)
    if rng and h1:
        covered = set()
        for part in rng.group(1).split(","):
            part = part.strip().upper().removeprefix("U+")
            lo, _, hi = part.partition("-")
            covered.update(range(int(lo, 16), int(hi or lo, 16) + 1))
        lacking = sorted({c for c in re.sub(r"<[^>]+>", "", h1.group(1)) if not c.isspace() and ord(c) not in covered})
        if lacking:
            print(f"  [warn] 首頁主標有字不在粉圓子集：{''.join(lacking)}，執行 python scripts/fetch_home_font.py")


def main():
    print("=== build.py ===")

    # --- Meta（頁尾 build 日期）---
    # 商品比價功能已停用（本站轉型為貓健康知識庫）。
    # 不再產生 5MB 的 frontend/data.js；只寫空 meta.js 供頁尾顯示 build 日期。
    print("\n[Meta]")
    write_meta_js([])

    # --- Articles ---
    print("\n[Articles]")
    articles = build_articles()
    # 列表、搜尋索引、首頁數字只看已審文章；sitemap 與首頁標籤自己會依 quality 判斷
    public_articles = [a for a in articles if a.get("public")]
    build_articles_index(public_articles, n_pending=len(articles) - len(public_articles))
    build_search_index(public_articles)
    # 全集索引給 test_search.py（build/ 不進 git）
    ALL_ARTICLES_JS.parent.mkdir(parents=True, exist_ok=True)
    ALL_ARTICLES_JS.write_text("window.ARTICLES_INDEX = " + json.dumps(articles, ensure_ascii=False) + ";\n", encoding="utf-8")
    sanitize_hand_pages({a["slug"] for a in public_articles})
    build_404()

    # --- Breeds data ---
    breeds_src = ROOT / "data" / "breeds_en.json"
    breeds_dst = FRONTEND_DIR / "data" / "breeds_en.json"
    if breeds_src.exists():
        breeds_dst.parent.mkdir(parents=True, exist_ok=True)
        import shutil
        shutil.copy2(breeds_src, breeds_dst)
        print(f"\n[Breeds] → {breeds_dst}")
    else:
        print("\n[Breeds] data/breeds_en.json not found — run scrapers/thecatapi.py")

    # --- Breed pages ---
    print("\n[Breeds]")
    breeds = build_breed_pages()

    # --- SEO ---
    print("\n[SEO]")
    build_sitemap(articles, breeds)

    # --- 首頁數字檢查 ---
    print("\n[Home stats]")
    sync_home_stats(articles, len(breeds), n_public=len(public_articles))

    print("\nDone.")


if __name__ == "__main__":
    main()
