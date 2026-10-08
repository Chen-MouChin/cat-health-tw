#!/usr/bin/env python3
"""
下載首頁主標用的 jf 粉圓（Huninn）子集字型。

首頁主標（frontend/index.html 的 <h1>）只載入用到的那幾個字，約 3 KB。
主標改字後執行一次：從 Google Fonts 以 text= 只抓主標的字，
存成 frontend/fonts/huninn-home.woff2，並更新 index.html 裡 @font-face 的 unicode-range。
build.py 發現主標有字不在子集時會提醒跑這支。

字型授權 SIL OFL 1.1（無保留字型名稱），見 frontend/fonts/Huninn-OFL.txt。

用法：python scripts/fetch_home_font.py
"""
import re
import sys
from pathlib import Path
from urllib.parse import quote
from urllib.request import Request, urlopen

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parent.parent
HOME = ROOT / "frontend" / "index.html"
OUT = ROOT / "frontend" / "fonts" / "huninn-home.woff2"
# Google Fonts 依 User-Agent 決定格式，要瀏覽器的 UA 才會給 woff2
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"


def fetch(url: str) -> bytes:
    return urlopen(Request(url, headers={"User-Agent": UA}), timeout=20).read()


def main():
    html = HOME.read_text(encoding="utf-8")
    h1 = re.search(r"<h1\b[^>]*>(.*?)</h1>", html, re.S)
    if not h1:
        sys.exit("index.html 找不到 <h1>")
    chars = sorted({c for c in re.sub(r"<[^>]+>", "", h1.group(1)) if not c.isspace()})
    text = "".join(chars)

    css = fetch("https://fonts.googleapis.com/css2?family=Huninn&text=" + quote(text)).decode("utf-8")
    m = re.search(r"url\((https://fonts\.gstatic\.com/[^)]+)\)\s*format\('woff2'\)", css)
    if not m:
        sys.exit("Google Fonts 沒有回 woff2，回應開頭：" + css[:200])
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_bytes(fetch(m.group(1)))

    rng = ", ".join(f"U+{ord(c):04X}" for c in chars)
    new_html, n = re.subn(r"(unicode-range:\s*)[^;]+;", lambda mm: mm.group(1) + rng + ";", html, count=1)
    if n != 1:
        sys.exit("index.html 找不到 @font-face 的 unicode-range")
    HOME.write_text(new_html, encoding="utf-8")

    print(f"主標 {len(chars)} 個字：{text}")
    print(f"→ {OUT.relative_to(ROOT)}（{OUT.stat().st_size:,} bytes），index.html 的 unicode-range 已更新")


if __name__ == "__main__":
    main()
