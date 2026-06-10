#!/usr/bin/env python3
"""
文獻收集爬蟲 — 從 Tier 1 學術來源自動收集指引/文章

用法：
  python scrapers/literature/crawler.py                    # 輸出審核清單
  python scrapers/literature/crawler.py --source aafp      # 只爬 AAFP
  python scrapers/literature/crawler.py --all              # 爬全部來源
  python scrapers/literature/crawler.py --verify           # 驗證所有 URL
  python scrapers/literature/crawler.py --report           # 輸出審核清單
"""
import argparse
import json
import logging
import re
import sys
from pathlib import Path

import requests
from bs4 import BeautifulSoup

sys.path.insert(0, str(Path(__file__).parent.parent))
from polite import wait_api, wait_detail

logging.basicConfig(level=logging.INFO, format="%(asctime)s [lit] %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("literature")

PROJECT_ROOT = Path(__file__).parent.parent.parent
SOURCES = Path(__file__).parent / "sources.json"
CITATIONS = PROJECT_ROOT / "content" / "references" / "citations.json"

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": "NekoPedia-LitBot/1.0 (literature collection; contact: https://chen-mouchin.github.io/cat-health-tw/about.html)",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9,zh-TW;q=0.8",
})


def load_citations():
    if CITATIONS.exists():
        return json.loads(CITATIONS.read_text(encoding="utf-8"))
    return {"_meta": {}}


def save_citations(data):
    # Update meta
    entries = {k: v for k, v in data.items() if k != "_meta"}
    data["_meta"] = {
        "description": "貓健康站 literature database",
        "total": len(entries),
        "pending_review": sum(1 for v in entries.values() if v.get("status") == "pending_review"),
        "approved": sum(1 for v in entries.values() if v.get("status") == "approved"),
        "rejected": sum(1 for v in entries.values() if v.get("status") == "rejected"),
    }
    CITATIONS.parent.mkdir(parents=True, exist_ok=True)
    CITATIONS.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def make_id(source, title, year):
    """Generate citation ID like AAFP-VACCINATION-2020"""
    slug = re.sub(r'[^a-zA-Z0-9]+', '-', title)[:40].strip('-').upper()
    return f"{source.upper()}-{slug}-{year}"


def fetch(url, timeout=15):
    """Polite fetch with delay"""
    wait_api()
    resp = SESSION.get(url, timeout=timeout)
    resp.raise_for_status()
    return resp


# ═══════════════════════════════════════════════════════════════════════
# AAFP
# ═══════════════════════════════════════════════════════════════════════

def crawl_aafp(existing):
    log.info("=== AAFP ===")
    try:
        resp = fetch("https://catvets.com/guidelines")
        soup = BeautifulSoup(resp.text, "html.parser")
    except Exception as e:
        log.error(f"AAFP fetch failed: {e}")
        return []

    new_entries = []
    # Find guideline links — look for links containing 'resource' or 'guidelines'
    links = soup.find_all("a", href=True)
    seen = set()
    for a in links:
        href = a.get("href", "")
        text = a.get_text(strip=True)
        if not text or len(text) < 10:
            continue
        if "/resource/" not in href and "/guidelines/" not in href:
            continue
        if href in seen:
            continue
        seen.add(href)

        # Extract year from text
        year_match = re.search(r'(20\d{2})', text)
        year = int(year_match.group(1)) if year_match else 2020

        url = href if href.startswith("http") else f"https://catvets.com{href}"
        cid = make_id("AAFP", text, year)

        if cid in existing:
            continue

        new_entries.append({
            "_id": cid,
            "title": text,
            "title_zh": "",
            "authors": "AAFP",
            "source": "AAFP",
            "journal": None,
            "url": url,
            "year": year,
            "type": "guideline",
            "language": "en",
            "open_access": True,
            "abstract_zh": "",
            "keywords": [],
            "disease_tags": [],
            "status": "pending_review",
            "url_verified": False,
            "notes": "auto-crawled from catvets.com/guidelines",
        })

    log.info(f"AAFP: found {len(new_entries)} new")
    return new_entries


# ═══════════════════════════════════════════════════════════════════════
# Cornell Feline Health Center
# ═══════════════════════════════════════════════════════════════════════

def crawl_cornell(existing):
    log.info("=== Cornell ===")
    base = "https://www.vet.cornell.edu"
    index = f"{base}/departments-centers-and-institutes/cornell-feline-health-center/health-information/feline-health-topics"
    try:
        resp = fetch(index)
        soup = BeautifulSoup(resp.text, "html.parser")
    except Exception as e:
        log.error(f"Cornell fetch failed: {e}")
        return []

    new_entries = []
    links = soup.find_all("a", href=True)
    seen = set()
    for a in links:
        href = a.get("href", "")
        text = a.get_text(strip=True)
        if not text or len(text) < 5:
            continue
        if "feline-health-topics" not in href or href == index.replace(base, ""):
            continue
        if href in seen:
            continue
        seen.add(href)

        url = href if href.startswith("http") else f"{base}{href}"
        cid = make_id("CORNELL", text, 2024)

        if cid in existing:
            continue

        new_entries.append({
            "_id": cid,
            "title": text,
            "title_zh": "",
            "authors": "Cornell University College of Veterinary Medicine",
            "source": "Cornell",
            "journal": None,
            "url": url,
            "year": 2024,
            "type": "educational",
            "language": "en",
            "open_access": True,
            "abstract_zh": "",
            "keywords": [],
            "disease_tags": [],
            "status": "pending_review",
            "url_verified": False,
            "notes": "auto-crawled from Cornell Feline Health Topics",
        })

    log.info(f"Cornell: found {len(new_entries)} new")
    return new_entries


# ═══════════════════════════════════════════════════════════════════════
# IRIS
# ═══════════════════════════════════════════════════════════════════════

def crawl_iris(existing):
    log.info("=== IRIS ===")
    try:
        resp = fetch("http://www.iris-kidney.com/guidelines.html")
        soup = BeautifulSoup(resp.text, "html.parser")
    except Exception as e:
        log.error(f"IRIS fetch failed: {e}")
        return []

    new_entries = []
    links = soup.find_all("a", href=True)
    seen = set()
    for a in links:
        href = a.get("href", "")
        text = a.get_text(strip=True)
        if not text or len(text) < 5:
            continue
        if "guidelines" not in href and "staging" not in href and "treatment" not in href:
            continue
        if href in seen:
            continue
        seen.add(href)

        url = href if href.startswith("http") else f"http://www.iris-kidney.com/{href.lstrip('/')}"
        cid = make_id("IRIS", text, 2023)

        if cid in existing:
            continue

        new_entries.append({
            "_id": cid,
            "title": text,
            "title_zh": "",
            "authors": "International Renal Interest Society",
            "source": "IRIS",
            "journal": None,
            "url": url,
            "year": 2023,
            "type": "guideline",
            "language": "en",
            "open_access": True,
            "abstract_zh": "",
            "keywords": ["CKD", "AKI", "腎病"],
            "disease_tags": ["ckd"],
            "status": "pending_review",
            "url_verified": False,
            "notes": "auto-crawled from iris-kidney.com",
        })

    log.info(f"IRIS: found {len(new_entries)} new")
    return new_entries


# ═══════════════════════════════════════════════════════════════════════
# VCA Animal Hospitals
# ═══════════════════════════════════════════════════════════════════════

def crawl_vca(existing):
    log.info("=== VCA ===")
    # VCA has a search API — search for cat-specific topics
    cat_topics = ["kidney disease cat", "diabetes cat", "hyperthyroidism cat",
                  "heart disease cat", "urinary cat", "dental cat", "cancer cat",
                  "vomiting cat", "diarrhea cat", "fip cat", "feline leukemia",
                  "upper respiratory cat", "asthma cat", "pancreatitis cat"]
    new_entries = []
    seen_urls = set()

    for topic in cat_topics:
        try:
            resp = fetch(f"https://vcahospitals.com/know-your-pet?query={topic.replace(' ', '+')}")
            soup = BeautifulSoup(resp.text, "html.parser")
            links = soup.find_all("a", href=True)
            for a in links:
                href = a.get("href", "")
                text = a.get_text(strip=True)
                if "/know-your-pet/" not in href or len(text) < 10:
                    continue
                url = href if href.startswith("http") else f"https://vcahospitals.com{href}"
                if url in seen_urls:
                    continue
                seen_urls.add(url)
                cid = make_id("VCA", text, 2024)
                if cid in existing:
                    continue
                new_entries.append({
                    "_id": cid,
                    "title": text,
                    "title_zh": "",
                    "authors": "VCA Animal Hospitals",
                    "source": "VCA",
                    "journal": None,
                    "url": url,
                    "year": 2024,
                    "type": "educational",
                    "language": "en",
                    "open_access": True,
                    "abstract_zh": "",
                    "keywords": [],
                    "disease_tags": [],
                    "status": "pending_review",
                    "url_verified": False,
                    "notes": f"auto-crawled, search: {topic}",
                })
        except Exception as e:
            log.warning(f"VCA search '{topic}' failed: {e}")

    log.info(f"VCA: found {len(new_entries)} new")
    return new_entries


# ═══════════════════════════════════════════════════════════════════════
# J-STAGE JVMS
# ═══════════════════════════════════════════════════════════════════════

def crawl_jstage(existing):
    log.info("=== J-STAGE JVMS ===")
    # J-STAGE has a search API
    search_url = "https://www.jstage.jst.go.jp/search/global/_search/-char/en?item1=keyword&word1=feline&magazinekey=jvms&count=50"
    try:
        resp = fetch(search_url)
        soup = BeautifulSoup(resp.text, "html.parser")
    except Exception as e:
        log.error(f"J-STAGE fetch failed: {e}")
        return []

    new_entries = []
    articles = soup.find_all("div", class_="searchlist-title") or soup.find_all("a", href=re.compile(r"/article/"))
    seen = set()
    for el in articles:
        a = el.find("a", href=True) if el.name == "div" else el
        if not a:
            continue
        href = a.get("href", "")
        text = a.get_text(strip=True)
        if not text or len(text) < 10 or href in seen:
            continue
        seen.add(href)

        url = href if href.startswith("http") else f"https://www.jstage.jst.go.jp{href}"
        year_match = re.search(r'(20\d{2})', href + text)
        year = int(year_match.group(1)) if year_match else 2020
        cid = make_id("JVMS", text[:30], year)

        if cid in existing:
            continue

        new_entries.append({
            "_id": cid,
            "title": text,
            "title_zh": "",
            "authors": "",
            "source": "JVMS (J-STAGE)",
            "journal": "Journal of Veterinary Medical Science",
            "url": url,
            "year": year,
            "type": "research_paper",
            "language": "en",
            "open_access": True,
            "abstract_zh": "",
            "keywords": ["feline"],
            "disease_tags": [],
            "status": "pending_review",
            "url_verified": False,
            "notes": "auto-crawled from J-STAGE, all OA",
        })

    log.info(f"J-STAGE: found {len(new_entries)} new")
    return new_entries


# ═══════════════════════════════════════════════════════════════════════
# KDCAT 台灣腎貓協會
# ═══════════════════════════════════════════════════════════════════════

def crawl_kdcat(existing):
    log.info("=== KDCAT 台灣腎貓協會 ===")
    try:
        resp = fetch("https://www.kdcat.org.tw/")
        soup = BeautifulSoup(resp.text, "html.parser")
    except Exception as e:
        log.error(f"KDCAT fetch failed: {e}")
        return []

    new_entries = []
    seen = set()
    for a in soup.find_all("a", href=True):
        href = a.get("href", "")
        text = a.get_text(strip=True)
        if not text or len(text) < 6 or href in seen:
            continue
        # KDCAT Wix structure: articles under /post/ or /blog
        if "/post/" not in href and "blog" not in href.lower() and "知識" not in text and "照護" not in text:
            continue
        seen.add(href)
        url = href if href.startswith("http") else f"https://www.kdcat.org.tw{href}"
        cid = make_id("KDCAT", text[:25], 2024)
        if cid in existing:
            continue
        new_entries.append({
            "_id": cid,
            "title": text,
            "title_zh": text,
            "authors": "台灣腎貓協會 (KDCAT)",
            "source": "KDCAT",
            "journal": None,
            "url": url,
            "year": 2024,
            "type": "educational",
            "language": "zh-TW",
            "open_access": True,
            "abstract_zh": "",
            "keywords": ["CKD", "腎病", "中文"],
            "disease_tags": ["ckd"],
            "status": "pending_review",
            "url_verified": False,
            "notes": "auto-crawled from kdcat.org.tw (Wix-hosted)",
        })

    log.info(f"KDCAT: found {len(new_entries)} new")
    return new_entries


# ═══════════════════════════════════════════════════════════════════════
# WSAVA Guidelines
# ═══════════════════════════════════════════════════════════════════════

def crawl_wsava(existing):
    log.info("=== WSAVA ===")
    pages = [
        "https://wsava.org/global-guidelines/",
        "https://wsava.org/committees/",
    ]
    new_entries = []
    seen = set()
    for page_url in pages:
        try:
            resp = fetch(page_url)
            soup = BeautifulSoup(resp.text, "html.parser")
        except Exception as e:
            log.warning(f"WSAVA {page_url}: {e}")
            continue
        for a in soup.find_all("a", href=True):
            href = a.get("href", "")
            text = a.get_text(strip=True)
            if not text or len(text) < 8 or href in seen:
                continue
            if "guideline" not in (href + text).lower() and "committee" not in href.lower():
                continue
            seen.add(href)
            url = href if href.startswith("http") else f"https://wsava.org{href}"
            year_match = re.search(r'(20\d{2})', text)
            year = int(year_match.group(1)) if year_match else 2022
            cid = make_id("WSAVA", text[:30], year)
            if cid in existing:
                continue
            new_entries.append({
                "_id": cid,
                "title": text,
                "title_zh": "",
                "authors": "WSAVA",
                "source": "WSAVA",
                "journal": None,
                "url": url,
                "year": year,
                "type": "guideline",
                "language": "en",
                "open_access": True,
                "abstract_zh": "",
                "keywords": ["WSAVA", "guideline"],
                "disease_tags": [],
                "status": "pending_review",
                "url_verified": False,
                "notes": "auto-crawled from wsava.org",
            })

    log.info(f"WSAVA: found {len(new_entries)} new")
    return new_entries


# ═══════════════════════════════════════════════════════════════════════
# ASPCA Toxic Plants/Foods
# ═══════════════════════════════════════════════════════════════════════

def crawl_aspca(existing):
    log.info("=== ASPCA ===")
    pages = [
        ("https://www.aspca.org/pet-care/animal-poison-control/toxic-and-non-toxic-plants",
         "Toxic Plants Database", "toxicology"),
        ("https://www.aspca.org/pet-care/animal-poison-control/people-foods-avoid-feeding-your-pets",
         "People Foods to Avoid", "toxicology"),
        ("https://www.aspca.org/pet-care/animal-poison-control/cats-plant-list",
         "Cat Plant List", "toxicology"),
    ]
    new_entries = []
    for url, title, tag in pages:
        cid = make_id("ASPCA", title, 2024)
        if cid in existing:
            continue
        new_entries.append({
            "_id": cid,
            "title": title,
            "title_zh": "",
            "authors": "ASPCA Animal Poison Control",
            "source": "ASPCA",
            "journal": None,
            "url": url,
            "year": 2024,
            "type": "database",
            "language": "en",
            "open_access": True,
            "abstract_zh": "",
            "keywords": ["毒物", "中毒", "ASPCA"],
            "disease_tags": [tag],
            "status": "pending_review",
            "url_verified": False,
            "notes": "ASPCA poison database",
        })

    log.info(f"ASPCA: found {len(new_entries)} new")
    return new_entries


# ═══════════════════════════════════════════════════════════════════════
# 農業部動物保護司（台灣政府）
# ═══════════════════════════════════════════════════════════════════════

def crawl_moa(existing):
    log.info("=== MOA 農業部 ===")
    try:
        resp = fetch("https://animal.moa.gov.tw/Frontend/Know/Index")
        soup = BeautifulSoup(resp.text, "html.parser")
    except Exception as e:
        log.warning(f"MOA: {e}")
        return []

    new_entries = []
    seen = set()
    for a in soup.find_all("a", href=True):
        href = a.get("href", "")
        text = a.get_text(strip=True)
        if not text or len(text) < 4 or href in seen:
            continue
        if "Know" not in href and "Detail" not in href:
            continue
        seen.add(href)
        url = href if href.startswith("http") else f"https://animal.moa.gov.tw{href}"
        cid = make_id("MOA", text[:25], 2024)
        if cid in existing:
            continue
        new_entries.append({
            "_id": cid,
            "title": text,
            "title_zh": text,
            "authors": "農業部動物保護司",
            "source": "MOA",
            "journal": None,
            "url": url,
            "year": 2024,
            "type": "government",
            "language": "zh-TW",
            "open_access": True,
            "abstract_zh": "",
            "keywords": ["動保", "政府", "台灣"],
            "disease_tags": ["regulation"],
            "status": "pending_review",
            "url_verified": False,
            "notes": "auto-crawled from animal.moa.gov.tw",
        })

    log.info(f"MOA: found {len(new_entries)} new")
    return new_entries


CRAWLERS = {
    "aafp": crawl_aafp,
    "cornell": crawl_cornell,
    "iris": crawl_iris,
    "vca": crawl_vca,
    "jvms_jstage": crawl_jstage,
    "kdcat": crawl_kdcat,
    "wsava": crawl_wsava,
    "aspca": crawl_aspca,
    "moa": crawl_moa,
}


# ═══════════════════════════════════════════════════════════════════════
# URL 驗證
# ═══════════════════════════════════════════════════════════════════════

def verify_urls():
    citations = load_citations()
    total = ok = fail = 0
    for cid, entry in citations.items():
        if cid == "_meta":
            continue
        url = entry.get("url", "")
        if not url:
            continue
        total += 1
        try:
            resp = SESSION.head(url, timeout=10, allow_redirects=True)
            if resp.status_code < 400:
                entry["url_verified"] = True
                ok += 1
            else:
                entry["url_verified"] = False
                fail += 1
                log.warning(f"  {cid}: HTTP {resp.status_code}")
        except Exception as e:
            entry["url_verified"] = False
            fail += 1
            log.warning(f"  {cid}: {e}")
        wait_api()

    save_citations(citations)
    log.info(f"URL verify: {ok}/{total} OK, {fail} failed")


# ═══════════════════════════════════════════════════════════════════════
# 審核清單
# ═══════════════════════════════════════════════════════════════════════

def print_review():
    citations = load_citations()
    i = 0
    for cid, entry in citations.items():
        if cid == "_meta":
            continue
        i += 1
        status = entry.get("status", "?")
        icon = {"pending_review": "?", "approved": "V", "rejected": "X"}.get(status, "?")
        title_zh = entry.get("title_zh") or entry.get("title", "")
        abstract = (entry.get("abstract_zh") or "")[:60]
        url = entry.get("url", "")
        keywords = ", ".join(entry.get("keywords", []))
        verified = "V" if entry.get("url_verified") else "?"
        oa = "OA" if entry.get("open_access") else "$$"

        print(f"[{i:02d}] {cid}")
        print(f"     {icon} {oa} URL:{verified}")
        print(f"     {title_zh}")
        if abstract:
            print(f"     {abstract}")
        print(f"     {url}")
        if keywords:
            print(f"     tags: {keywords}")
        print()

    meta = citations.get("_meta", {})
    print(f"Total: {meta.get('total', i)} | Pending: {meta.get('pending_review', '?')} | Approved: {meta.get('approved', 0)}")


# ═══════════════════════════════════════════════════════════════════════
# main
# ═══════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="Literature crawler")
    parser.add_argument("--source", help="Only crawl specified source")
    parser.add_argument("--verify", action="store_true", help="Verify all URLs")
    parser.add_argument("--report", action="store_true", help="Print review list")
    parser.add_argument("--all", action="store_true", help="Crawl all sources")
    args = parser.parse_args()

    if args.verify:
        verify_urls()
    elif args.report:
        print_review()
    elif args.source:
        crawler = CRAWLERS.get(args.source)
        if not crawler:
            log.error(f"Unknown source: {args.source}. Available: {list(CRAWLERS.keys())}")
            return
        citations = load_citations()
        new = crawler(citations)
        for entry in new:
            cid = entry.pop("_id")
            citations[cid] = entry
        save_citations(citations)
        log.info(f"Added {len(new)} new citations. Total: {len(citations)-1}")
    elif args.all:
        citations = load_citations()
        total_new = 0
        for name, crawler in CRAWLERS.items():
            new = crawler(citations)
            for entry in new:
                cid = entry.pop("_id")
                citations[cid] = entry
            total_new += len(new)
        save_citations(citations)
        log.info(f"Total new: {total_new}. Total citations: {len(citations)-1}")
    else:
        print_review()


if __name__ == "__main__":
    main()
