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
import textwrap
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).parent
CONTENT_DIR = ROOT / "content" / "articles"
FRONTEND_DIR = ROOT / "frontend"
ARTICLES_DIR = FRONTEND_DIR / "articles"
SITEMAP_XML = FRONTEND_DIR / "sitemap.xml"
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

ARTICLE_TEMPLATE = """\
<!DOCTYPE html>
<html lang="zh-TW">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
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
    "datePublished": "{date}",
    "author": {{"@type": "Organization", "name": "貓健康站"}},
    "publisher": {{"@type": "Organization", "name": "貓健康站", "url": "https://chen-mouchin.github.io/cat-health-tw"}}
  }}
  </script>
  <link rel="stylesheet" href="../css/ads.css">
  <link rel="stylesheet" href="../css/theme.css">
  <link rel="stylesheet" href="../css/nav.css?v=20260420b">
  <script src="../js/theme.js"></script>
  <style>
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{ font-family: system-ui, "Noto Sans TC", sans-serif; background: var(--bg, #fafafa); color: var(--text, #333); line-height: 1.7; }}
    header {{ background: var(--header-bg, #1d1d1f); color: var(--header-text, #fff); padding: 1rem 2rem; display: flex; align-items: center; gap: 1rem; }}
    header a {{ color: var(--header-text, #fff); text-decoration: none; opacity: 0.8; }}
    header h1 {{ font-size: 1.2rem; flex: 1; }}
    .ad-wrap {{ background: var(--bg-card, #fff); border-top: 1px solid var(--border, #eee); border-bottom: 1px solid var(--border, #eee); padding: 0.4rem 0; }}
    article {{ max-width: 760px; margin: 2rem auto; padding: 0 1.5rem; }}
    .article-meta {{ color: var(--text-muted, #888); font-size: 0.85rem; margin-bottom: 1.5rem; display: flex; gap: 1rem; flex-wrap: wrap; }}
    .article-meta .cat-badge {{
      background: var(--accent-light, #f0f0f3); color: var(--accent, #1d1d1f); padding: 0.15rem 0.6rem;
      border-radius: 20px; font-size: 0.8rem;
    }}
    article h1 {{ font-size: 1.7rem; line-height: 1.3; margin-bottom: 1rem; color: var(--accent, #1d1d1f); }}
    article h2 {{ font-size: 1.25rem; margin: 2rem 0 0.8rem; color: var(--accent, #1d1d1f); border-bottom: 2px solid var(--accent-light, #f0f0f3); padding-bottom: 0.3rem; }}
    article h3 {{ font-size: 1.05rem; margin: 1.5rem 0 0.5rem; color: var(--text, #333); }}
    article p {{ margin: 0.8rem 0; }}
    article ul, article ol {{ margin: 0.8rem 0 0.8rem 1.5rem; }}
    article li {{ margin: 0.3rem 0; }}
    article table {{ width: 100%; border-collapse: collapse; margin: 1rem 0; font-size: 0.9rem; }}
    article th {{ background: var(--accent-light, #f0f0f3); padding: 0.5rem 0.7rem; text-align: left; font-weight: 600; }}
    article td {{ padding: 0.4rem 0.7rem; border-top: 1px solid var(--border, #eee); }}
    article tr:nth-child(even) td {{ background: var(--bg, #f9f9f9); }}
    article blockquote {{
      border-left: 4px solid var(--accent, #1d1d1f); margin: 1rem 0;
      padding: 0.6rem 1rem; background: var(--accent-light, #f5f5f7); color: var(--text-muted, #555);
    }}
    article code {{ background: var(--bg, #f0f0f0); padding: 0.1rem 0.4rem; border-radius: 3px; font-size: 0.88rem; }}
    article pre {{ background: var(--bg, #f0f0f0); padding: 1rem; border-radius: 6px; overflow-x: auto; }}
    article hr {{ border: none; border-top: 1px solid var(--border, #e0e0e0); margin: 1.5rem 0; }}
    mark {{ background: #f5f5f7; padding: 0 2px; border-radius: 2px; }}
    .article-hero {{
      width: 100%; aspect-ratio: 16/9; max-height: 380px;
      object-fit: cover; border-radius: 10px;
      margin-bottom: 1.5rem; display: block;
      background: linear-gradient(135deg, var(--accent-light, #f0ede6), var(--bg, #f9f6f0));
    }}
    .article-hero[src=""], .article-hero:not([src]) {{ display: none; }}
    .sources-box {{
      background: var(--bg-card, #f5f5f5); border-radius: 8px; padding: 1rem 1.2rem;
      margin-top: 2rem; font-size: 0.85rem; color: var(--text-muted, #666);
    }}
    .sources-box h3 {{ color: var(--text-muted, #555); margin-bottom: 0.5rem; font-size: 0.9rem; }}
    .disclaimer {{
      background: #fff8e1; border-left: 4px solid #ffc107;
      padding: 0.6rem 1rem; margin: 1.5rem 0; font-size: 0.88rem; color: #555;
    }}
    .find-vet-cta {{
      background: var(--accent-light, #f0ede6); border: 1px solid var(--border, #e8e4db);
      border-radius: 8px; padding: 1rem 1.2rem; margin: 1.5rem 0;
      display: flex; align-items: center; gap: 0.8rem; flex-wrap: wrap;
    }}
    .find-vet-cta .label {{ font-weight: 600; color: var(--text, #1d1d1f); }}
    .find-vet-cta a {{
      display: inline-block; padding: 0.4rem 0.9rem;
      background: var(--accent, #1d1d1f); color: var(--accent-on, #fff);
      border-radius: 16px; text-decoration: none; font-size: 0.88rem;
    }}
    .find-vet-cta a:hover {{ background: var(--accent-hover, #424245); }}
    .draft-warning {{
      background: #f5f0e8; border: 1px solid #d4c8b0; border-left: 3px solid #8a7340;
      color: #5c4a25;
      padding: 0.7rem 1rem; margin-bottom: 1.5rem; border-radius: 6px;
      font-size: 0.85rem; line-height: 1.55;
    }}
    .draft-warning .lbl {{ background: #8a7340; color: #fff; padding: 2px 8px; border-radius: 3px; margin-right: 0.5rem; font-size: 0.7rem; font-weight: 600; letter-spacing: 0.05em; }}
    .related-products {{
      background: var(--accent-light, #f0f0f3); border-radius: 8px; padding: 1rem 1.2rem; margin-top: 2rem;
    }}
    .related-products a {{ color: var(--accent, #1d1d1f); font-weight: 600; }}

    /* === UX 改造：TL;DR / Key Facts / Related === */
    .tldr-box {{
      background: linear-gradient(135deg, #fff8e1, #fff3cd);
      border-left: 4px solid #e0a800;
      border-radius: 8px; padding: 0.9rem 1.1rem; margin: 1.3rem 0;
    }}
    .tldr-box .tldr-label {{
      font-size: 0.72rem; letter-spacing: 0.08em;
      color: #8a6400; font-weight: 700;
      text-transform: uppercase; margin-bottom: 0.35rem;
    }}
    .tldr-box ul {{ margin: 0 0 0 1.1rem; padding: 0; }}
    .tldr-box li {{ margin: 0.2rem 0; font-size: 0.95rem; color: #1d1d1f; line-height: 1.55; }}

    .key-facts-grid {{
      display: grid; grid-template-columns: repeat(3, 1fr);
      gap: 0.7rem; margin: 1.3rem 0;
    }}
    @media (max-width: 540px) {{
      .key-facts-grid {{ grid-template-columns: 1fr 1fr; }}
    }}
    .key-fact {{
      background: var(--bg-card, #fff); border: 1px solid var(--border, #e8e4db);
      border-radius: 10px; padding: 0.85rem 0.7rem; text-align: center;
      box-shadow: 0 1px 3px var(--shadow, rgba(0,0,0,0.03));
    }}
    .key-fact .kf-value {{
      font-size: 1.45rem; font-weight: 800; line-height: 1.2;
      color: var(--accent, #1d1d1f);
    }}
    .key-fact .kf-label {{
      font-size: 0.76rem; color: var(--text-muted, #6e6e73);
      margin-top: 0.3rem; font-weight: 600;
    }}
    .key-fact .kf-note {{
      font-size: 0.7rem; color: var(--text-faint, #999);
      margin-top: 0.25rem; line-height: 1.4;
    }}

    .related-box {{
      background: var(--accent-light, #f0ede6); border-radius: 8px;
      padding: 0.9rem 1.1rem; margin: 2rem 0 1rem;
    }}
    .related-box h3 {{
      font-size: 0.88rem; margin-bottom: 0.45rem;
      color: var(--text-muted, #555); font-weight: 600;
    }}
    .related-box ul {{ margin: 0 0 0 1.1rem; padding: 0; }}
    .related-box li {{ margin: 0.22rem 0; font-size: 0.9rem; }}
    .related-box a {{
      color: var(--text, #1d1d1f); text-decoration: none;
      border-bottom: 1px dotted var(--border-strong, #c2c2c7);
    }}
    .related-box a:hover {{ color: var(--accent, #1d1d1f); border-bottom-color: currentColor; }}

    /* 章節重點（markdown: > ⚡ 重點：xxx） */
    .section-hint {{
      background: #fff8f0;
      border-left: 3px solid #ff8c42;
      padding: 0.55rem 0.9rem;
      margin: 0.6rem 0 1.1rem;
      border-radius: 4px;
      font-size: 0.93rem;
      line-height: 1.6;
    }}
    .section-hint .hint-label {{
      color: #d96a1f; font-weight: 700;
      margin-right: 0.5rem; font-size: 0.82rem;
      letter-spacing: 0.04em;
    }}
    .section-hint .hint-body {{ color: #333; }}
    .section-hint a {{ color: #b4521a; }}

    /* 修掉 sticky nav 蓋住 anchor 跳轉目標 */
    article h2[id], article h3[id] {{ scroll-margin-top: 5rem; }}

    footer {{ text-align: center; padding: 1.5rem 2rem 2rem; color: var(--text-muted, #999); font-size: 0.85rem; }}
  </style>
</head>
<body>
  <nav class="site-nav">
    <a class="nav-brand" href="../index.html" title="回首頁"><span class="b-icon">🐱</span><span class="brand-text">貓健康站</span><span class="brand-home" aria-hidden="true">🏠</span></a>
    <div class="nav-links">
      <a class="nav-link" href="../library.html" data-nav="library">📚 文獻庫</a>
      <a class="nav-link" href="../breeds.html" data-nav="breeds">🐈 品種</a>
      <a class="nav-link" href="../vets.html" data-nav="vets">🏥 獸醫院</a>
      <a class="nav-link active" href="index.html" data-nav="articles">📝 文章</a>
      <a class="nav-link" href="../about.html" data-nav="about">ℹ️ 關於</a>
    </div>
  </nav>

  <article>
    <div class="article-meta">
      <span class="cat-badge">{cat_emoji} {category}</span>
      <span>📅 {date}</span>
    </div>
    <h1>{title}</h1>
{draft_warning_html}
{cover_image_html}
{tldr_html}
{key_facts_html}

    {body}

    <div style="clear:both"></div>

    {related_products_html}

    {find_vet_html}

    {related_html}

    <div class="disclaimer">
      ⚠️ 本文僅供參考，不構成獸醫診療建議。如有健康疑慮，請諮詢專業獸醫師。
    </div>

    {sources_html}
  </article>

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
  <script>var fd=document.getElementById('footer-date');if(fd&&typeof SITE_META!=='undefined')fd.textContent=SITE_META.data_updated;</script>
  <script>
  (function(){{
    var q=new URLSearchParams(location.search).get('q');
    if(!q)return;
    var terms=q.split(/\s+/).filter(Boolean);
    function walk(n){{
      if(n.nodeType===3){{
        var h=n.textContent,changed=false;
        for(var i=0;i<terms.length;i++){{
          var e=terms[i].replace(/[.*+?^${{}}()|[\]\\]/g,'\\$&');
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
      outline: none; border-color: var(--accent, #1d1d1f);
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
    .q-draft {{ background: #f5f0e8; color: #8a7340; border: 1px solid #d4c8b0; }}
    .q-reviewed {{ background: #f0f0f3; color: #1d1d1f; border: 1px solid #d2d2d7; }}
    .q-featured {{ background: #1d1d1f; color: #fff; }}
    .article-card.is-draft {{ opacity: 0.65; }}
    .article-card.is-draft:hover {{ opacity: 1; }}
    body.hide-drafts .article-card.is-draft {{ display: none; }}
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
    <a class="nav-brand" href="../index.html" title="回首頁"><span class="b-icon">🐱</span><span class="brand-text">貓健康站</span><span class="brand-home" aria-hidden="true">🏠</span></a>
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

    # Pass 1: 收集 slug → title，給 related 反向連結用
    slug_to_title: dict[str, str] = {}
    for md_path in mds:
        if md_path.name == "README.md":
            continue
        try:
            _m, _ = _parse_front_matter(md_path.read_text(encoding="utf-8"))
            _slug = _m.get("slug") or md_path.stem
            slug_to_title[_slug] = _m.get("title", _slug)
        except Exception:
            continue

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
        last_reviewed = meta.get("last_reviewed", "")

        body_html = _md_to_html(body_md)
        # Strip the leading <h1> if the markdown starts with # Title (avoids duplicate)
        body_html = re.sub(r"^\s*<h1>[^<]*</h1>\s*", "", body_html, count=1)
        # 章節重點約定：blockquote 以「⚡ 重點」開頭 → 渲染為 .section-hint 醒目盒
        body_html = re.sub(
            r'<blockquote>\s*<p>⚡\s*重點[:：]?\s*(.*?)</p>\s*</blockquote>',
            r'<div class="section-hint"><span class="hint-label">⚡ 重點</span>'
            r'<span class="hint-body">\1</span></div>',
            body_html,
            flags=re.S,
        )

        # Auto-generate description from first <p> if not in front matter
        description = meta.get("description", "")
        if not description:
            p_match = re.search(r"<p>(.*?)</p>", body_html, re.DOTALL)
            if p_match:
                description = re.sub(r"<[^>]+>", "", p_match.group(1))[:150].strip()

        sources_html = ""
        if sources:
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

        # 文末「找獸醫」CTA（從文章 frontmatter 的 find_vet 欄位）
        # 值：cat_only（→ vets.html?cat=1）/ emergency（→ ?only24h=1）/ both
        find_vet_html = ""
        find_vet = (meta.get("find_vet") or "").strip().lower()
        if find_vet == "cat_only":
            find_vet_html = (
                '<div class="find-vet-cta">'
                '<span class="label">📍 需要找獸醫？</span>'
                '<a href="../vets.html?cat=1">🐈 找台灣貓專科獸醫院 →</a>'
                '</div>'
            )
        elif find_vet == "emergency":
            find_vet_html = (
                '<div class="find-vet-cta">'
                '<span class="label">🚨 緊急狀況？</span>'
                '<a href="../vets.html?only24h=1">找 24h 急診動物醫院 →</a>'
                '</div>'
            )
        elif find_vet == "both":
            find_vet_html = (
                '<div class="find-vet-cta">'
                '<span class="label">📍 需要找獸醫？</span>'
                '<a href="../vets.html?cat=1">🐈 貓專科 →</a>'
                '<a href="../vets.html?only24h=1">🚨 24h 急診 →</a>'
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
        if isinstance(related, list) and related:
            rel_items = []
            for rel_slug in related:
                rel_slug = rel_slug.strip()
                if not rel_slug:
                    continue
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
            title=title,
            title_json=json.dumps(title),
            description=description,
            slug=slug,
            site_url=SITE_URL,
            category=category,
            cat_emoji=cat_emoji,
            date=str(date),
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

        out_path = ARTICLES_DIR / f"{slug}.html"
        out_path.write_text(output, encoding="utf-8")
        subcategory = SUBCATEGORY_MAP.get(slug, meta.get("subcategory", ""))
        articles_meta.append({
            "slug": slug,
            "title": title,
            "description": description,
            "date": str(date),
            "category": category,
            "subcategory": subcategory,
            "cover_image": cover_image,
            "tags": meta.get("tags", []),
            "quality": quality,
            "last_reviewed": str(last_reviewed) if last_reviewed else "",
            "body_text": re.sub(r"<[^>]+>", "", body_html)[:800],
        })

    print(f"  Built {len(articles_meta)} articles → {ARTICLES_DIR}/")
    return articles_meta


def build_articles_index(articles: list[dict]):
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

    html = ARTICLES_INDEX_TEMPLATE.format(article_sections="\n".join(sections_html))
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

        html = f"""<!DOCTYPE html>
<html lang="zh-TW">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
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
  <a class="nav-brand" href="../index.html" title="回首頁"><span class="b-icon">🐱</span><span class="brand-text">貓健康站</span><span class="brand-home" aria-hidden="true">🏠</span></a>
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
    ]
    published = [a for a in articles if a.get("quality") in ("reviewed", "featured")]
    skipped_drafts = len(articles) - len(published)
    for a in published:
        urls.append(
            f'  <url><loc>{SITE_URL}/articles/{a["slug"]}.html</loc>'
            f'<lastmod>{a["date"]}</lastmod><changefreq>monthly</changefreq><priority>0.7</priority></url>'
        )
    for br in (breeds or []):
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
    build_articles_index(articles)
    build_search_index(articles)

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

    print("\nDone.")


if __name__ == "__main__":
    main()
