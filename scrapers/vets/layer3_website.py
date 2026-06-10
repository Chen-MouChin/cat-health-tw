#!/usr/bin/env python3
"""
Layer 3: 官網 / 部落格偵測

用法：
  python scrapers/vets/layer3_website.py                    # 處理 all_vets.json
  python scrapers/vets/layer3_website.py --city 台北市       # 只處理指定城市
  python scrapers/vets/layer3_website.py --limit 20         # 只處理前 20 筆

策略（無 GCP API key 版本）：
  1. DuckDuckGo HTML 版搜「{醫院名} 官網」（不違反 ToS）
  2. 篩選結果，挑最像官網的 URL
  3. 抓官網首頁，掃 /blog /article 等部落格路徑
  4. 偵測 Facebook 粉專
"""
import argparse
import json
import logging
import re
import sys
import urllib.parse
from pathlib import Path

import requests
from bs4 import BeautifulSoup

sys.path.insert(0, str(Path(__file__).parent.parent))
from polite import wait_detail, wait_api

logging.basicConfig(level=logging.INFO, format="%(asctime)s [vets-L3] %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("vets-L3")

PROJECT_ROOT = Path(__file__).parent.parent.parent
DATA_DIR = PROJECT_ROOT / "data" / "vets"

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.8",
})

BLOG_PATHS = ['/blog', '/article', '/articles', '/knowledge', '/health',
              '/news', '/column', '/education', '/pet-care', '/info']

EXCLUDE_DOMAINS = {
    'facebook.com', 'fb.com', 'instagram.com', 'youtube.com', 'twitter.com',
    'google.com', 'wikipedia.org', 'mobile01.com', 'ptt.cc', 'dcard.tw',
    'maps.google.com', 'play.google.com', 'apple.com', 'pchome.com.tw',
    'shopee.tw', 'momo.com.tw', 'foodpanda.com', 'ubereats.com',
    'gov.tw', 'edu.tw',  # 政府/學校通常不是獸醫院官網
    'kdcat.org.tw', 'tavim.org', 'tw-tvma.org',  # 協會
}


def search_duckduckgo(query: str) -> list[str]:
    """用 DuckDuckGo HTML 版搜尋，回傳 URL 清單"""
    try:
        url = f"https://html.duckduckgo.com/html/?q={urllib.parse.quote(query)}"
        resp = SESSION.get(url, timeout=15)
        if resp.status_code != 200:
            return []
        soup = BeautifulSoup(resp.text, "html.parser")
        urls = []
        for a in soup.select("a.result__a"):
            href = a.get("href", "")
            # DuckDuckGo redirect: /l/?uddg=...
            if href.startswith("//duckduckgo.com/l/"):
                m = re.search(r'uddg=([^&]+)', href)
                if m:
                    href = urllib.parse.unquote(m.group(1))
            if href.startswith("http"):
                urls.append(href)
            if len(urls) >= 5:
                break
        return urls
    except Exception as e:
        log.warning(f"DDG search failed: {e}")
        return []


def is_likely_clinic_site(url: str, vet_name: str) -> bool:
    """判斷 URL 是否像是這家獸醫院的官網"""
    try:
        domain = urllib.parse.urlparse(url).netloc.lower().replace("www.", "")
    except Exception:
        return False
    # Exclude social/aggregator sites
    for excl in EXCLUDE_DOMAINS:
        if excl in domain:
            return False
    # Prefer sites with vet/animal/pet keywords in domain
    keywords = ['vet', 'animal', 'pet', 'hospital', 'clinic', '動物', 'cat', 'dog']
    if any(k in domain for k in keywords):
        return True
    # Check if vet name appears in URL (transliterated or similar)
    return False


def detect_blog(website_url: str) -> tuple[bool, str]:
    """掃官網是否有部落格頁"""
    try:
        resp = SESSION.get(website_url, timeout=10)
        if resp.status_code != 200:
            return False, ""
        soup = BeautifulSoup(resp.text, "html.parser")
        # Check links for blog paths
        for a in soup.find_all("a", href=True):
            href = a.get("href", "").lower()
            text = a.get_text(strip=True)
            for pattern in BLOG_PATHS:
                if pattern in href:
                    full_url = href if href.startswith("http") else urllib.parse.urljoin(website_url, href)
                    return True, full_url
            # Chinese keywords
            if any(k in text for k in ['部落格', '衛教', '文章', '知識', '健康資訊']):
                href_full = href if href.startswith("http") else urllib.parse.urljoin(website_url, href)
                return True, href_full
        return False, ""
    except Exception:
        return False, ""


def detect_fb(urls: list[str]) -> str:
    """從搜尋結果找 Facebook 粉專"""
    for url in urls:
        if "facebook.com" in url and "/profile" not in url and "/posts" not in url:
            return url
    return ""


def detect_website(vet: dict) -> dict:
    """嘗試偵測獸醫院官網和部落格"""
    name = vet.get("name", "")
    if not name:
        return {"website": None, "has_blog": False, "blog_url": None, "fb_page": None}

    # Search
    query = f"{name} 動物醫院 官網"
    urls = search_duckduckgo(query)
    wait_detail()  # be polite

    # Pick most likely website
    website = None
    for url in urls:
        if is_likely_clinic_site(url, name):
            website = url
            break

    # Detect blog
    has_blog = False
    blog_url = None
    if website:
        has_blog, blog_url = detect_blog(website)
        wait_detail()

    # FB page
    fb = detect_fb(urls)

    return {
        "website": website or None,
        "has_blog": has_blog,
        "blog_url": blog_url or None,
        "fb_page": fb or None,
    }


def enrich_with_website(vets: list[dict], limit: int | None = None) -> list[dict]:
    count = 0
    found_web = 0
    found_blog = 0
    for vet in vets:
        if vet.get("website") is not None:  # already processed
            continue
        if limit and count >= limit:
            break

        result = detect_website(vet)
        vet.update(result)
        count += 1
        if result["website"]:
            found_web += 1
        if result["has_blog"]:
            found_blog += 1

        if count % 10 == 0:
            log.info(f"  Processed {count}: {found_web} websites, {found_blog} blogs")

    log.info(f"Website detection: {count} processed, {found_web} websites, {found_blog} blogs")
    return vets


def main():
    parser = argparse.ArgumentParser(description="Layer 3: website/blog detection")
    parser.add_argument("--input", default=str(DATA_DIR / "all_vets.json"))
    parser.add_argument("--city", help="Only process specified city")
    parser.add_argument("--limit", type=int, help="Max records to process")
    args = parser.parse_args()

    input_path = Path(args.input)
    if not input_path.exists():
        log.error(f"{input_path} not found.")
        return

    vets = json.loads(input_path.read_text(encoding="utf-8"))
    log.info(f"Loaded {len(vets)} records")

    if args.city:
        target = [v for v in vets if v.get("city") == args.city]
        log.info(f"Filtered to {len(target)} for {args.city}")
        target = enrich_with_website(target, args.limit)
        target_names = {v["name"] for v in target}
        vets = [v for v in vets if v["name"] not in target_names] + target
    else:
        vets = enrich_with_website(vets, args.limit)

    input_path.write_text(
        json.dumps(vets, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    log.info(f"Saved back to {input_path}")


if __name__ == "__main__":
    main()
