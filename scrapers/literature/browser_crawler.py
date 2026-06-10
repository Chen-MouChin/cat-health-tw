#!/usr/bin/env python3
"""
進階文獻收集爬蟲 — Playwright + 人類模擬

比 crawler.py 更強：
- Playwright headless 瀏覽器（處理 JS 渲染）
- 人類瀏覽行為模擬（滾動、隨機停留、滑鼠移動）
- 不規則延遲（對數常態分布，不是均勻分布）
- 自動重試（指數退避 + 抖動）
- Cloudflare/WAF 繞過（真實瀏覽器指紋）

用法：
  python scrapers/literature/browser_crawler.py --source aafp
  python scrapers/literature/browser_crawler.py --verify-failed
  python scrapers/literature/browser_crawler.py --all
"""
import argparse
import asyncio
import json
import logging
import math
import random
import time
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s [lit-pw] %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("lit-pw")

PROJECT_ROOT = Path(__file__).parent.parent.parent
CITATIONS = PROJECT_ROOT / "content" / "references" / "citations.json"


# ═══════════════════════════════════════════════════════════════════════
# 人類模擬延遲
# ═══════════════════════════════════════════════════════════════════════

def human_delay(base=3.0, variance=0.8):
    """
    對數常態分布延遲 — 比均勻分布更像人類。
    大部分等 2-4 秒，偶爾等 6-8 秒（像人分心了）。
    """
    delay = random.lognormvariate(math.log(base), variance)
    delay = max(1.0, min(delay, 15.0))  # clamp 1-15s
    time.sleep(delay)
    return delay


def page_read_delay():
    """模擬人類閱讀頁面的時間（3-8 秒）"""
    return human_delay(base=4.0, variance=0.5)


def between_pages_delay():
    """頁面之間的間隔（2-5 秒）"""
    return human_delay(base=2.5, variance=0.6)


# ═══════════════════════════════════════════════════════════════════════
# 自動重試（指數退避 + 抖動）
# ═══════════════════════════════════════════════════════════════════════

async def retry_with_backoff(fn, max_retries=3, base_delay=5.0):
    """
    指數退避重試：5s → 10s → 20s（加隨機抖動）
    """
    for attempt in range(max_retries + 1):
        try:
            return await fn()
        except Exception as e:
            if attempt >= max_retries:
                raise
            delay = base_delay * (2 ** attempt) + random.uniform(0, base_delay)
            log.warning(f"  Attempt {attempt+1} failed: {e}. Retrying in {delay:.1f}s...")
            await asyncio.sleep(delay)


# ═══════════════════════════════════════════════════════════════════════
# Playwright 瀏覽器管理
# ═══════════════════════════════════════════════════════════════════════

async def create_browser():
    """建立真實瀏覽器指紋的 Playwright instance"""
    from playwright.async_api import async_playwright

    pw = await async_playwright().start()
    browser = await pw.chromium.launch(
        headless=True,
        args=[
            "--disable-blink-features=AutomationControlled",
            "--no-sandbox",
        ]
    )
    context = await browser.new_context(
        viewport={"width": 1366, "height": 768},
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        locale="en-US",
        timezone_id="Asia/Taipei",
    )
    # 移除 webdriver 標記
    await context.add_init_script("""
        Object.defineProperty(navigator, 'webdriver', { get: () => false });
    """)
    return pw, browser, context


async def human_browse(page, url):
    """模擬人類瀏覽行為"""
    await page.goto(url, wait_until="domcontentloaded", timeout=30000)

    # 等頁面穩定
    await asyncio.sleep(1 + random.random())

    # 模擬滾動（人類會看看頁面）
    for _ in range(random.randint(1, 3)):
        scroll_y = random.randint(200, 600)
        await page.mouse.wheel(0, scroll_y)
        await asyncio.sleep(0.5 + random.random())

    # 隨機滑鼠移動
    await page.mouse.move(
        random.randint(100, 800),
        random.randint(100, 500)
    )

    return await page.content()


# ═══════════════════════════════════════════════════════════════════════
# 來源爬取
# ═══════════════════════════════════════════════════════════════════════

async def crawl_with_browser(source_name, url, extract_fn):
    """通用：用 Playwright 開頁面，提取文獻"""
    pw, browser, context = await create_browser()
    try:
        page = await context.new_page()
        log.info(f"  Opening {url}")

        html = await retry_with_backoff(
            lambda: human_browse(page, url)
        )

        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "html.parser")
        results = extract_fn(soup, url)
        log.info(f"  Found {len(results)} items")
        return results

    finally:
        await browser.close()
        await pw.stop()


def extract_aafp(soup, base_url):
    """從 AAFP guidelines 頁面提取"""
    import re
    entries = []
    seen = set()
    for a in soup.find_all("a", href=True):
        href = a.get("href", "")
        text = a.get_text(strip=True)
        if not text or len(text) < 10:
            continue
        if "/resource/" not in href:
            continue
        if href in seen:
            continue
        seen.add(href)
        url = href if href.startswith("http") else f"https://catvets.com{href}"
        year_match = re.search(r'(20\d{2})', text)
        year = int(year_match.group(1)) if year_match else 2020
        entries.append({"title": text, "url": url, "year": year, "source": "AAFP"})
    return entries


def extract_generic_links(soup, base_url, path_filter=""):
    """通用連結提取"""
    entries = []
    seen = set()
    for a in soup.find_all("a", href=True):
        href = a.get("href", "")
        text = a.get_text(strip=True)
        if not text or len(text) < 8 or href in seen:
            continue
        if path_filter and path_filter not in href:
            continue
        seen.add(href)
        url = href if href.startswith("http") else f"{base_url.rstrip('/')}/{href.lstrip('/')}"
        entries.append({"title": text, "url": url, "source": "unknown"})
    return entries


# ═══════════════════════════════════════════════════════════════════════
# URL 驗證（用 Playwright 驗證 requests 失敗的 URL）
# ═══════════════════════════════════════════════════════════════════════

async def verify_failed_urls():
    """用真實瀏覽器驗證 requests HEAD 失敗的 URL"""
    with open(CITATIONS, encoding="utf-8") as f:
        data = json.load(f)

    failed = [(cid, entry) for cid, entry in data.items()
              if cid != "_meta" and not entry.get("url_verified", False)]

    if not failed:
        log.info("No failed URLs to verify")
        return

    log.info(f"Verifying {len(failed)} failed URLs with Playwright...")
    pw, browser, context = await create_browser()

    try:
        page = await context.new_page()
        fixed = 0

        for cid, entry in failed:
            url = entry.get("url", "")
            if not url:
                continue

            try:
                response = await page.goto(url, wait_until="domcontentloaded", timeout=15000)
                status = response.status if response else 0

                if status < 400:
                    entry["url_verified"] = True
                    fixed += 1
                    log.info(f"  OK: {cid} ({status})")
                else:
                    log.warning(f"  FAIL: {cid} ({status})")

            except Exception as e:
                log.warning(f"  ERROR: {cid} ({e})")

            between_pages_delay()

        with open(CITATIONS, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        log.info(f"Fixed {fixed}/{len(failed)} URLs")

    finally:
        await browser.close()
        await pw.stop()


# ═══════════════════════════════════════════════════════════════════════
# main
# ═══════════════════════════════════════════════════════════════════════

async def async_main(args):
    if args.verify_failed:
        await verify_failed_urls()
    elif args.source:
        source_map = {
            "aafp": ("https://catvets.com/guidelines", extract_aafp),
        }
        if args.source not in source_map:
            log.error(f"Unknown source: {args.source}. Available: {list(source_map.keys())}")
            return
        url, extractor = source_map[args.source]
        results = await crawl_with_browser(args.source, url, extractor)
        log.info(f"Found {len(results)} items")
        for r in results[:5]:
            log.info(f"  {r['title'][:50]}")


def main():
    parser = argparse.ArgumentParser(description="Advanced literature crawler (Playwright)")
    parser.add_argument("--source", help="Crawl specified source")
    parser.add_argument("--verify-failed", action="store_true", help="Re-verify failed URLs with real browser")
    parser.add_argument("--all", action="store_true", help="Crawl all sources")
    args = parser.parse_args()

    asyncio.run(async_main(args))


if __name__ == "__main__":
    main()
