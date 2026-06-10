#!/usr/bin/env python3
"""
文獻摘要核實腳本 — 確保摘要中的每個數值都有原文佐證

用法：
  python scrapers/literature/verify_citation.py IRIS-CKD-2023
  python scrapers/literature/verify_citation.py --all-approved
  python scrapers/literature/verify_citation.py --pending-review

流程：
  1. 讀 citations.json 中的摘要
  2. 從摘要提取所有數值聲明（藥物劑量、數值範圍、分期標準）
  3. 下載原文 PDF/HTML
  4. 逐項比對：摘要聲明 vs 原文
  5. 輸出 FOUND / NOT FOUND 報告
"""
import argparse
import json
import re
import sys
import io
from pathlib import Path

import requests

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

PROJECT_ROOT = Path(__file__).parent.parent.parent
CITATIONS = PROJECT_ROOT / "content" / "references" / "citations.json"
PDF_CACHE = PROJECT_ROOT / "content" / "references" / "pdf_cache"
PDF_CACHE.mkdir(parents=True, exist_ok=True)


def load_citations():
    return json.loads(CITATIONS.read_text(encoding="utf-8"))


def extract_claims(abstract_zh: str) -> list[dict]:
    """
    從中文摘要中提取可驗證的聲明。
    找：數字 + 單位（mg/dL, mmHg, %, mg/kg, μg/dL 等）
    """
    claims = []

    # 藥物劑量：name + dose
    for m in re.finditer(
        r'(\w[\w\s/]+?)\s+([\d.]+(?:\s*[-–]\s*[\d.]+)?)\s*(mg/kg|mg/day|mg|μg/dL|μg/dl|mmHg|mm Hg|mmol/L|mmol/l|mg/dL|mg/dl|pg/ml|%|ml|g/dL|g/dl|g/l)',
        abstract_zh
    ):
        drug = m.group(1).strip()[-30:]
        value = m.group(2).strip()
        unit = m.group(3).strip()
        claims.append({
            "text": f"{drug} {value} {unit}",
            "search_terms": [value, unit.replace("/", "").lower()],
            "value": value,
        })

    # Stage + 肌酸酐
    for m in re.finditer(r'Stage\s*(\d)\s*[：:（].*?(?:肌酸酐|creatinine)\s*([<>≤≥]?\s*[\d.]+)', abstract_zh):
        claims.append({
            "text": f"Stage {m.group(1)} creatinine {m.group(2)}",
            "search_terms": [m.group(2).strip().lstrip('<>≤≥ ')],
            "value": m.group(2).strip(),
        })

    # UPC 值
    for m in re.finditer(r'UPC\s*([<>]?\s*[\d.]+)', abstract_zh):
        claims.append({
            "text": f"UPC {m.group(1)}",
            "search_terms": [m.group(1).strip().lstrip('<> ')],
            "value": m.group(1).strip(),
        })

    # 血壓值
    for m in re.finditer(r'([<>≥≤]?\s*\d{2,3})\s*mmHg', abstract_zh):
        val = m.group(1).strip().lstrip('<>≥≤ ')
        claims.append({
            "text": f"{m.group(0)}",
            "search_terms": [val],
            "value": val,
        })

    # Deduplicate by value
    seen = set()
    unique = []
    for c in claims:
        if c["value"] not in seen:
            seen.add(c["value"])
            unique.append(c)

    return unique


def fetch_source_text(entry: dict, cid: str) -> str:
    """下載原文，優先 PDF 快取 > PDF 下載 > HTML"""
    # Check PDF cache
    cache_path = PDF_CACHE / f"{cid}.txt"
    if cache_path.exists():
        return cache_path.read_text(encoding="utf-8")

    url = entry.get("url", "")

    # Try PDF download (IRIS style)
    if "iris-kidney.com" in url:
        pdf_map = {
            "IRIS-CKD-2023": "https://www.iris-kidney.com/s/2_IRIS_Staging_of_CKD_2023.pdf",
            "IRIS-CKD-TREATMENT-2023": "https://www.iris-kidney.com/s/IRIS_CAT_Treatment_Recommendations_2023.pdf",
        }
        pdf_url = pdf_map.get(cid)
        if pdf_url:
                try:
                    resp = requests.get(pdf_url, timeout=15, allow_redirects=True)
                    if resp.status_code == 200:
                        pdf_path = PDF_CACHE / f"{cid}.pdf"
                        pdf_path.write_bytes(resp.content)
                        # Extract text
                        try:
                            from PyPDF2 import PdfReader
                            reader = PdfReader(str(pdf_path))
                            text = "\n".join(page.extract_text() or "" for page in reader.pages)
                            cache_path.write_text(text, encoding="utf-8")
                            return text
                        except ImportError:
                            print("  WARNING: PyPDF2 not installed, cannot read PDF")
                except Exception as e:
                    print(f"  PDF download failed: {e}")

    # Try HTML
    try:
        resp = requests.get(url, timeout=15, headers={
            "User-Agent": "NekoPedia-LitBot/1.0 (verification; contact: https://chen-mouchin.github.io/cat-health-tw/about.html)"
        })
        if resp.status_code == 200:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(resp.text, "html.parser")
            text = soup.get_text(separator="\n")
            cache_path.write_text(text, encoding="utf-8")
            return text
    except Exception as e:
        print(f"  HTML fetch failed: {e}")

    return ""


def verify_citation(cid: str, data: dict):
    """核實一筆文獻的摘要"""
    entry = data.get(cid)
    if not entry:
        print(f"Citation {cid} not found")
        return

    abstract = entry.get("abstract_zh", "")
    if not abstract:
        print(f"[{cid}] No abstract_zh, skipping")
        return

    print(f"=== {cid} ===")
    print(f"  {entry.get('title_zh', entry.get('title', ''))}")
    print()

    # Extract claims
    claims = extract_claims(abstract)
    if not claims:
        print("  No verifiable claims found in abstract")
        return

    # Fetch source text
    print(f"  Fetching source text...")
    source = fetch_source_text(entry, cid)
    if not source:
        print("  ERROR: Could not fetch source text")
        return

    print(f"  Source text: {len(source)} chars")
    print()

    # Normalize source for matching
    source_norm = source.replace("\n", " ").replace("  ", " ")

    # Verify each claim
    found = 0
    not_found = 0
    for c in claims:
        # Search for the value in source
        matched = any(term in source_norm for term in c["search_terms"])
        # Try without spaces
        if not matched:
            matched = any(term.replace(" ", "") in source_norm.replace(" ", "") for term in c["search_terms"])
        # Try range format: "0.125-0.25" matches "0.125 to 0.25"
        if not matched:
            val = c["value"]
            if "-" in val or "–" in val:
                parts = re.split(r'[-–]', val)
                if len(parts) == 2:
                    matched = parts[0].strip() in source_norm and parts[1].strip() in source_norm

        icon = "V" if matched else "X"
        status = "FOUND" if matched else "NOT FOUND"
        print(f"  [{icon}] {c['text']}: {status}")

        if matched:
            found += 1
        else:
            not_found += 1

    print()
    print(f"  Result: {found}/{found+not_found} verified")
    if not_found > 0:
        print(f"  WARNING: {not_found} claims NOT verified — check manually")
    else:
        print(f"  ALL CLAIMS VERIFIED")

    return not_found == 0


def main():
    parser = argparse.ArgumentParser(description="Verify citation abstracts against source documents")
    parser.add_argument("citation_id", nargs="?", help="Specific citation ID to verify")
    parser.add_argument("--all-approved", action="store_true", help="Re-verify all approved citations")
    parser.add_argument("--pending", action="store_true", help="Verify pending citations")
    args = parser.parse_args()

    data = load_citations()

    if args.citation_id:
        verify_citation(args.citation_id, data)
    elif args.all_approved:
        for cid, entry in data.items():
            if cid == "_meta":
                continue
            if entry.get("status") == "approved":
                verify_citation(cid, data)
                print()
    elif args.pending:
        for cid, entry in data.items():
            if cid == "_meta":
                continue
            if entry.get("status") == "pending_review" and entry.get("abstract_zh"):
                verify_citation(cid, data)
                print()
    else:
        print("Usage:")
        print("  python verify_citation.py IRIS-CKD-2023")
        print("  python verify_citation.py --all-approved")
        print("  python verify_citation.py --pending")


if __name__ == "__main__":
    main()
