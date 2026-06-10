#!/usr/bin/env python3
"""
輕量效能 audit（Python 本機跑，無需 Node/Lighthouse）
=====================================================
量化：
- HTML 大小（gzipped / raw）
- 外部資源數量與總大小（CSS / JS / IMG）
- 關鍵 SEO meta 存在否（title / description / og / canonical / json-ld）
- 圖片 alt 屬性覆蓋率
- viewport / charset / lang 設定
- 內部連結數量

若要完整 Lighthouse（含 JS 執行時間、First Contentful Paint 等瀏覽器層級指標）：
→ 上 https://pagespeed.web.dev/ 貼網址即可

輸出：research/perf-report.md
"""
from __future__ import annotations
import gzip
import re
import sys
import time
import urllib.request
from urllib.error import URLError
from urllib.parse import urljoin, urlparse
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

BASE = sys.argv[sys.argv.index("--base") + 1] if "--base" in sys.argv else "http://localhost:8000/frontend"
ROOT = Path(__file__).parent.parent
REPORT = ROOT / "research" / "perf-report.md"

PAGES = [
    ("/", "首頁"),
    ("/index.html", "首頁（/index）"),
    ("/library.html", "文獻庫"),
    ("/breeds.html", "品種圖鑑"),
    ("/breeds/ragd.html", "品種詳頁（布偶）"),
    ("/vets.html", "獸醫院"),
    ("/about.html", "關於"),
]


def fetch(url, timeout=10):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "NekoPediaPerfAudit/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read()
            headers = dict(r.headers)
            return r.status, body, headers
    except Exception as e:
        return None, b"", {"error": str(e)}


def size_kb(b):
    return round(len(b) / 1024, 1)


def gzip_size(b):
    return round(len(gzip.compress(b)) / 1024, 1)


def audit_page(base, path, name):
    url = base + path
    status, body, headers = fetch(url)
    if status != 200:
        return {"name": name, "path": path, "error": headers.get("error", f"HTTP {status}")}

    html = body.decode("utf-8", errors="ignore")

    # 關鍵 meta 檢查
    def has(pattern):
        return bool(re.search(pattern, html, re.IGNORECASE))

    # CSS / JS / IMG
    css_refs = re.findall(r'<link[^>]+rel="stylesheet"[^>]+href="([^"]+)"', html)
    js_refs = re.findall(r'<script[^>]+src="([^"]+)"', html)
    imgs = re.findall(r'<img[^>]+src="([^"]+)"', html)
    imgs_with_alt = len(re.findall(r'<img[^>]+alt="[^"]*"', html))
    imgs_with_lazy = len(re.findall(r'<img[^>]+loading="lazy"', html))
    internal_links = len(re.findall(r'href="(?!https?:)(?!#)[^"]+\.html', html))
    external_links = len(re.findall(r'href="https?://', html))

    # 抓 CSS/JS/img 檔大小（只算前 3 個代表樣本）
    resource_size_total = 0
    resource_count = 0
    for refs in [css_refs[:5], js_refs[:5]]:
        for ref in refs:
            if ref.startswith("http"): continue
            full = urljoin(url, ref)
            r_status, r_body, _ = fetch(full, timeout=5)
            if r_status == 200:
                resource_size_total += len(r_body)
                resource_count += 1

    return {
        "name": name,
        "path": path,
        "status": status,
        "html_kb": size_kb(body),
        "html_gzip_kb": gzip_size(body),
        "css_count": len(css_refs),
        "js_count": len(js_refs),
        "img_count": len(imgs),
        "img_alt_pct": round(imgs_with_alt / len(imgs) * 100) if imgs else 100,
        "img_lazy_count": imgs_with_lazy,
        "internal_links": internal_links,
        "external_links": external_links,
        "resource_kb": round(resource_size_total / 1024, 1),
        "meta": {
            "title": has(r'<title>[^<]+</title>'),
            "description": has(r'<meta[^>]+name="description"'),
            "og_title": has(r'<meta[^>]+property="og:title"'),
            "og_description": has(r'<meta[^>]+property="og:description"'),
            "og_type": has(r'<meta[^>]+property="og:type"'),
            "og_image": has(r'<meta[^>]+property="og:image"'),
            "canonical": has(r'<link[^>]+rel="canonical"'),
            "json_ld": has(r'application/ld\+json'),
            "viewport": has(r'<meta[^>]+name="viewport"'),
            "charset": has(r'<meta[^>]+charset'),
            "lang": has(r'<html[^>]+lang='),
        },
    }


def score(result):
    """給 0-100 分 — 自訂啟發式（非 Lighthouse）"""
    if "error" in result: return 0
    pts = 100
    # HTML 太大扣分
    if result["html_kb"] > 200: pts -= 10
    if result["html_kb"] > 500: pts -= 10
    # 圖片 alt 覆蓋率
    pts -= (100 - result["img_alt_pct"]) / 2
    # 懶載覆蓋率（有 img 時）
    if result["img_count"] > 3 and result["img_lazy_count"] == 0: pts -= 5
    # Meta 缺失
    meta = result["meta"]
    for required in ["title", "description", "viewport", "charset", "lang"]:
        if not meta.get(required): pts -= 5
    for nice in ["og_title", "og_description", "og_type", "canonical"]:
        if not meta.get(nice): pts -= 3
    if not meta.get("json_ld"): pts -= 2  # 非必須但加分
    return max(0, round(pts))


def render_report(results):
    lines = [
        "# 效能 Audit 報告",
        "",
        f"_產出 {time.strftime('%Y-%m-%d %H:%M')} · base={BASE}_",
        "",
        "> **注意**：這是本機輕量 audit（無 JS 執行時間分析）。",
        "> 要完整 Lighthouse 報告（含 LCP / FID / CLS）請上 <https://pagespeed.web.dev/>",
        "",
        "## 總覽",
        "",
        "| 頁面 | 分數 | HTML (raw/gzip) | CSS/JS | 圖 | alt % | 連結 |",
        "|---|---:|---|---:|---:|---:|---|",
    ]
    for r in results:
        if "error" in r:
            lines.append(f"| {r['name']} | — | ERR | — | — | — | {r['error']} |")
            continue
        s = score(r)
        badge = "🟢" if s >= 90 else "🟡" if s >= 70 else "🔴"
        lines.append(
            f"| {r['name']} | {badge} {s} "
            f"| {r['html_kb']}/{r['html_gzip_kb']} KB "
            f"| {r['css_count']}/{r['js_count']} "
            f"| {r['img_count']} "
            f"| {r['img_alt_pct']}% "
            f"| {r['internal_links']}內/{r['external_links']}外 |"
        )

    lines += ["", "## 詳細每頁", ""]
    for r in results:
        if "error" in r:
            lines.append(f"### ✗ {r['name']}  `{r['path']}`")
            lines.append(f"- Error: {r['error']}")
            lines.append("")
            continue
        s = score(r)
        lines += [
            f"### {r['name']}  `{r['path']}`  （分數 {s}）",
            f"- HTML: **{r['html_kb']} KB**（gzip 後 {r['html_gzip_kb']} KB）",
            f"- 資源：{r['css_count']} CSS + {r['js_count']} JS + {r['img_count']} IMG",
            f"- 前 10 個外部資源合計：{r['resource_kb']} KB",
            f"- 圖片 alt 覆蓋率：{r['img_alt_pct']}% · 懶載 {r['img_lazy_count']} / {r['img_count']}",
            f"- 連結：內部 {r['internal_links']} · 外部 {r['external_links']}",
            "",
            "**Meta 檢查**：",
        ]
        m = r["meta"]
        for k, v in m.items():
            lines.append(f"  - {'✓' if v else '✗'} `{k}`")
        lines.append("")

    # 彙整建議
    lines += ["---", "", "## 🔴 優化建議（按優先序）", ""]

    # 收集跨頁問題
    low_alt = [r for r in results if "error" not in r and r["img_alt_pct"] < 90 and r["img_count"] > 0]
    if low_alt:
        lines.append("### 圖片 alt 屬性補完")
        for r in low_alt:
            lines.append(f"- `{r['path']}` — alt 覆蓋 {r['img_alt_pct']}% / {r['img_count']} 張圖")
        lines.append("")

    no_lazy = [r for r in results if "error" not in r and r["img_count"] > 3 and r["img_lazy_count"] < r["img_count"] / 2]
    if no_lazy:
        lines.append("### 圖片懶載未普及")
        for r in no_lazy:
            lines.append(f"- `{r['path']}` — 只有 {r['img_lazy_count']}/{r['img_count']} 加 loading=\"lazy\"")
        lines.append("")

    big_html = [r for r in results if "error" not in r and r["html_kb"] > 100]
    if big_html:
        lines.append("### HTML 過大（考慮拆 CSS/JS 或外部 data.js）")
        for r in big_html:
            lines.append(f"- `{r['path']}` — {r['html_kb']} KB")
        lines.append("")

    no_og = [r for r in results if "error" not in r and not r["meta"].get("og_title")]
    if no_og:
        lines.append("### 缺 Open Graph（社群分享縮圖）")
        for r in no_og:
            lines.append(f"- `{r['path']}`")
        lines.append("")

    no_jsonld = [r for r in results if "error" not in r and not r["meta"].get("json_ld")]
    if no_jsonld:
        lines.append("### 缺結構化資料（JSON-LD，SEO 加分）")
        for r in no_jsonld:
            lines.append(f"- `{r['path']}`")
        lines.append("")

    lines += [
        "---",
        "",
        "## 外部工具補充",
        "",
        "- **完整 Lighthouse**：<https://pagespeed.web.dev/>",
        "- **行動版模擬**：Chrome DevTools > Lighthouse（本機）",
        "- **CDN 壓縮檢查**：<https://gtmetrix.com/>",
        "- **Core Web Vitals 實測**：Search Console > 網頁體驗（需 Google Search Console 認證）",
    ]
    return "\n".join(lines)


def main():
    print(f"[Perf Audit] base={BASE}")
    results = []
    for path, name in PAGES:
        print(f"  scanning {path} ...")
        r = audit_page(BASE, path, name)
        results.append(r)
    REPORT.write_text(render_report(results), encoding="utf-8")
    print(f"\n[Report] {REPORT}")


if __name__ == "__main__":
    main()
