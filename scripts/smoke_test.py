#!/usr/bin/env python3
"""
Smoke Test — 核心使用路徑自動化檢查
===================================
前置：本地 http server 跑在 8000 port（或傳 --base 指定）

檢查：
- 每頁 HTTP 200
- 全站連結無 404
- sitemap.xml 每筆都可開
- 各 breed 獨立 HTML 都可開
- 關鍵內容（如 breeds.js / data.js）能載入

輸出：
  research/smoke-test-report.md
"""
from __future__ import annotations
import re
import sys
import time
import urllib.request
from urllib.error import URLError, HTTPError
from urllib.parse import urljoin, urlparse
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

BASE = sys.argv[sys.argv.index("--base") + 1] if "--base" in sys.argv else "http://localhost:8000"  # python -m http.server 8000 --directory frontend
ROOT = Path(__file__).parent.parent
REPORT = ROOT / "research" / "smoke-test-report.md"


def http_head(url, timeout=5):
    try:
        req = urllib.request.Request(url, method="HEAD")
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status
    except HTTPError as e:
        if e.code == 405:  # HEAD not allowed, try GET
            try:
                with urllib.request.urlopen(url, timeout=timeout) as r:
                    return r.status
            except Exception as e2:
                return f"ERR: {e2}"
        return e.code
    except Exception as e:
        return f"ERR: {str(e)[:50]}"


def http_get(url, timeout=5):
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return r.status, r.read().decode("utf-8", errors="ignore")
    except Exception as e:
        return None, str(e)[:100]


def crawl(base, start):
    """從起點 BFS 所有內部連結"""
    visited = set()
    queue = [start]
    broken = []
    ok = []
    while queue:
        path = queue.pop(0)
        if path in visited: continue
        visited.add(path)
        url = base + path
        status, html = http_get(url)
        if status != 200:
            broken.append((path, status or "timeout", html[:80] if html else ""))
            continue
        ok.append(path)
        # 抽連結
        # (?<![\w-]) 排除 data-draft-href 這種「藏起來的連結」，它們刻意不是真的 href
        for href in re.findall(r'(?<![\w-])href="([^"#?][^"]*)"', html):
            if href.startswith("http") or href.endswith(".css") or href.endswith(".js"):
                continue
            if "${" in href: continue  # JS template
            full = urljoin(url, href)
            p = urlparse(full)
            if p.netloc != urlparse(base).netloc: continue
            new_path = p.path.replace("/frontend", "", 1)
            if new_path not in visited and (new_path.endswith(".html") or new_path.endswith("/")):
                queue.append(new_path)
    return ok, broken


def main():
    print(f"[Smoke Test] Base: {BASE}")
    start_time = time.time()

    # 1. BFS 從 index 爬
    print("\n[1/4] BFS 從首頁爬所有可達頁面...")
    ok, broken = crawl(BASE, "/index.html")
    print(f"  OK {len(ok)} / Broken {len(broken)}")

    # 2. 檢查關鍵資源
    print("\n[2/4] 檢查核心資源載入...")
    resources = [
        ("/css/theme.css", 200),
        ("/css/nav.css", 200),
        ("/js/theme.js", 200),
        ("/js/ads.js", 200),
        ("/data/breeds.js", 200),
        ("/data/vets.js", 200),
        ("/sitemap.xml", 200),
        ("/robots.txt", 200),
    ]
    resource_results = []
    for path, expected in resources:
        status = http_head(BASE + path)
        ok_flag = status == expected
        resource_results.append((path, status, ok_flag))
        print(f"  {'✓' if ok_flag else '✗'} {path} → {status}")

    # 3. Sitemap 每筆檢查
    print("\n[3/4] 掃 sitemap.xml 每筆 URL...")
    status, sitemap = http_get(BASE + "/sitemap.xml")
    sitemap_results = []
    if status == 200:
        urls = re.findall(r"<loc>([^<]+)</loc>", sitemap)
        # sitemap 是線上絕對網址（含 /cat-health-tw 這種子路徑），轉成本機路徑要先把站台根路徑剝掉
        site_root = min((urlparse(u).path for u in urls if urlparse(u).path.endswith("/")), key=len, default="/")
        for u in urls:
            local_path = "/" + urlparse(u).path[len(site_root):].lstrip("/")
            s = http_head(BASE + local_path)
            ok_flag = s == 200
            sitemap_results.append((u, s, ok_flag))
            if not ok_flag:
                print(f"  ✗ {u} → {s}")
        print(f"  共 {len(urls)} URLs，{sum(1 for _,_,o in sitemap_results if o)} OK")

    # 4. 抽 3 個品種頁檢查內容
    print("\n[4/4] 抽查品種頁內容...")
    sample_breeds = ["ragd", "pers", "bsho"]
    breed_results = []
    for bid in sample_breeds:
        status, html = http_get(f"{BASE}/breeds/{bid}.html")
        has_title = "品種資料" in (html or "")
        has_schema = "schema.org" in (html or "")
        ok_flag = status == 200 and has_title and has_schema
        breed_results.append((bid, ok_flag, f"status={status} title={has_title} schema={has_schema}"))
        print(f"  {'✓' if ok_flag else '✗'} /breeds/{bid}.html — {breed_results[-1][2]}")

    # 寫報告
    elapsed = time.time() - start_time
    lines = [
        "# Smoke Test Report",
        "",
        f"_Generated {time.strftime('%Y-%m-%d %H:%M')} · {elapsed:.1f}s · base={BASE}_",
        "",
        "## 總覽",
        f"- ✓ 可達頁面：{len(ok)}",
        f"- ✗ 死連結：{len(broken)}",
        f"- 資源：{sum(1 for _,_,o in resource_results if o)} / {len(resource_results)} OK",
        f"- Sitemap URLs：{sum(1 for _,_,o in sitemap_results if o)} / {len(sitemap_results)} OK",
        f"- 品種頁抽查：{sum(1 for _,o,_ in breed_results if o)} / {len(breed_results)} OK",
        "",
    ]

    if broken:
        lines.append("## ✗ 死連結")
        for p, s, msg in broken:
            lines.append(f"- `{p}` → {s} {msg}")
        lines.append("")

    bad_resources = [(p, s) for p, s, o in resource_results if not o]
    if bad_resources:
        lines.append("## ✗ 資源載入失敗")
        for p, s in bad_resources:
            lines.append(f"- `{p}` → {s}")
        lines.append("")

    bad_sitemap = [(u, s) for u, s, o in sitemap_results if not o]
    if bad_sitemap:
        lines.append("## ✗ Sitemap 壞連結")
        for u, s in bad_sitemap:
            lines.append(f"- {u} → {s}")
        lines.append("")

    bad_breeds = [(b, msg) for b, o, msg in breed_results if not o]
    if bad_breeds:
        lines.append("## ✗ 品種頁問題")
        for b, msg in bad_breeds:
            lines.append(f"- `{b}` — {msg}")
        lines.append("")

    if not broken and not bad_resources and not bad_sitemap and not bad_breeds:
        lines.append("## ✅ 全部通過")
        lines.append("")
        lines.append("沒有偵測到任何問題。")

    REPORT.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n[Report] {REPORT}")

    # 退出碼
    if broken or bad_resources or bad_sitemap or bad_breeds:
        sys.exit(1)


if __name__ == "__main__":
    main()
