#!/usr/bin/env python3
"""
產生貓健康站 Logo 資產（定案：金線脈搏 × 貓啃什錦黑）
=====================================================
字標「貓健康站」以 fontTools 從字型檔取出外框，轉成 SVG path，
之後網站不需要載入字型也能顯示 Logo。

用法：
    python scripts/build_logo.py --font <MaokenAssortedSans-TC.ttf 路徑>

輸出：
    frontend/images/logo/mark.svg               貓耳記號（currentColor）
    frontend/images/logo/pulse.svg              金色脈搏線
    frontend/images/logo/wordmark.svg           字標外框（currentColor）
    frontend/images/logo/lockup-vertical.svg    直式：耳、字、脈搏
    frontend/images/logo/lockup-horizontal.svg  橫式：耳在左、字與脈搏在右（導覽列用）
    frontend/images/logo/lockup-dark.svg        深色背景版（米色字）
    frontend/favicon.svg / favicon-32.png / favicon-180.png / favicon.ico
    frontend/images/og-default.png              1200×630 分享圖
    frontend/fonts/maoken-assorted-logo.woff2   只含 Logo 用字的子集字型（備用）
    frontend/images/logo/inline-nav.html        導覽列用的 inline SVG 片段（build.py 與靜態頁引用）

字型授權：貓啃什錦黑繁體版 SIL OFL 1.1（https://github.com/Skr-ZERO/MaokenAssortedSans-TC）
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen
from fontTools.ttLib import TTFont

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "frontend" / "images" / "logo"
FRONT = ROOT / "frontend"

INK = "#1d1d1f"
CREAM = "#f9f6f0"
GOLD = "#b8860b"
GOLD_DARK = "#d4a52a"
WORD = "貓健康站"

# 元件（viewBox 座標）
EARS_PATHS = (
    '<path d="M4 20 V2 L14 10 Z"/><path d="M36 20 V2 L26 10 Z"/>'
    '<circle cx="13" cy="18" r="2.2"/><circle cx="27" cy="18" r="2.2"/>'
)
PULSE_D = "M0 9 H56 L61 9 L65 2 L70 15 L75 9 H150"


def wordmark_path(font: TTFont, text: str, size: float, tracking_em: float = 0.04) -> tuple[str, float, float]:
    """回傳 (path d, 寬, 高)，基線在 y=0 往上為負；輸出已翻轉為 y 向下、頂點對齊 0。"""
    upem = font["head"].unitsPerEm
    cmap = font.getBestCmap()
    glyphset = font.getGlyphSet()
    hmtx = font["hmtx"]
    scale = size / upem
    asc = font["OS/2"].sTypoAscender if font["OS/2"].sTypoAscender else font["hhea"].ascent
    desc = font["OS/2"].sTypoDescender if font["OS/2"].sTypoDescender else font["hhea"].descent
    # 用 CJK 字面框取代 ascender：以 em 方框頂為 0
    x = 0.0
    pen = SVGPathPen(glyphset, ntos=lambda v: f"{v:.2f}")
    top = asc * scale
    for ch in text:
        gname = cmap[ord(ch)]
        adv = hmtx[gname][0] * scale
        tpen = TransformPen(pen, (scale, 0, 0, -scale, x, top))
        glyphset[gname].draw(tpen)
        x += adv + tracking_em * size
    width = x - tracking_em * size
    height = (asc - desc) * scale
    return pen.getCommands(), width, height


def svg(w: float, h: float, body: str, extra_attrs: str = "") -> str:
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w:.0f} {h:.0f}" width="{w:.0f}" height="{h:.0f}" '
            f'role="img" aria-label="貓健康站"{extra_attrs}>{body}</svg>\n')


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--font", required=True, help="MaokenAssortedSans-TC.ttf 路徑")
    args = ap.parse_args()
    font = TTFont(args.font)
    OUT.mkdir(parents=True, exist_ok=True)
    (FRONT / "fonts").mkdir(exist_ok=True)

    # --- 字標外框（以 100px 字級產生，之後用 viewBox 縮放）
    d, ww, wh = wordmark_path(font, WORD, 100, tracking_em=0.04)
    # 裁掉字面框上下留白：什錦黑字面約佔 em 的 88%，直接取 em 框即可
    wordmark = f'<path fill="currentColor" d="{d}"/>'
    (OUT / "wordmark.svg").write_text(svg(ww, wh, wordmark, ' color="#1d1d1f"'), encoding="utf-8")

    # --- 記號與脈搏
    (OUT / "mark.svg").write_text(svg(40, 22, f'<g fill="currentColor">{EARS_PATHS}</g>', ' color="#1d1d1f"'), encoding="utf-8")
    (OUT / "pulse.svg").write_text(
        svg(150, 16, f'<path d="{PULSE_D}" fill="none" stroke="{GOLD}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>'),
        encoding="utf-8")

    # --- 直式 lockup：耳 44×24，字 ww×wh(100px)，脈搏 176×18，垂直間距 12
    W = max(ww, 200) + 40
    ears_w, ears_h = 56, 30.8
    pulse_w, pulse_h = ww * 0.88, ww * 0.88 * 16 / 150
    y = 20
    parts = []
    parts.append(f'<g transform="translate({(W-ears_w)/2:.1f},{y}) scale({ears_w/40:.3f})" fill="currentColor">{EARS_PATHS}</g>')
    y += ears_h + 14
    parts.append(f'<g transform="translate({(W-ww)/2:.1f},{y})"><path fill="currentColor" d="{d}"/></g>')
    y += wh + 6
    parts.append(f'<g transform="translate({(W-pulse_w)/2:.1f},{y}) scale({pulse_w/150:.3f})"><path d="{PULSE_D}" fill="none" stroke="{GOLD}" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"/></g>')
    y += pulse_h + 20
    H = y
    body = "".join(parts)
    (OUT / "lockup-vertical.svg").write_text(svg(W, H, body, ' color="#1d1d1f"'), encoding="utf-8")
    (OUT / "lockup-dark.svg").write_text(
        svg(W, H, f'<rect width="{W:.0f}" height="{H:.0f}" fill="{INK}"/>' + body.replace(GOLD, GOLD_DARK), f' color="{CREAM}"'),
        encoding="utf-8")

    # --- 橫式 lockup（導覽列）：高 40。耳 36×19.8 置左；字高 40 → scale 0.4；脈搏在字下
    s = 0.34
    tw, th = ww * s, wh * s
    ears_w2 = 30
    ears_h2 = ears_w2 * 22 / 40
    gap = 10
    pulse_w2 = tw * 0.62
    pulse_h2 = pulse_w2 * 16 / 150
    HW = ears_w2 + gap + tw
    HH = th + pulse_h2 + 2
    hbody = (
        f'<g transform="translate(0,{(HH-ears_h2)/2:.1f}) scale({ears_w2/40:.3f})" fill="currentColor">{EARS_PATHS}</g>'
        f'<g transform="translate({ears_w2+gap:.1f},0) scale({s:.3f})"><path fill="currentColor" d="{d}"/></g>'
        f'<g transform="translate({ears_w2+gap:.1f},{th+1:.1f}) scale({pulse_w2/150:.3f})"><path d="{PULSE_D}" fill="none" stroke="{GOLD}" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/></g>'
    )
    (OUT / "lockup-horizontal.svg").write_text(svg(HW, HH, hbody, ' color="#1d1d1f"'), encoding="utf-8")
    # inline 片段（不含 xmlns，給 HTML 用；currentColor 跟隨文字色）
    inline = (f'<svg class="brand-logo" viewBox="0 0 {HW:.0f} {HH:.0f}" aria-label="貓健康站" role="img">'
              f'{hbody}</svg>')
    (OUT / "inline-nav.html").write_text(inline, encoding="utf-8")

    # --- favicon.svg：方形，耳 + 脈搏
    fav = (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" width="64" height="64">'
        f'<rect width="64" height="64" rx="12" fill="{CREAM}"/>'
        f'<g transform="translate(9,8) scale(1.15)" fill="{INK}"><path d="M4 26 V6 L14 14 Z"/><path d="M36 26 V6 L26 14 Z"/><circle cx="13" cy="24" r="2.6"/><circle cx="27" cy="24" r="2.6"/></g>'
        f'<path d="M8 50 H24 L28 50 L32 40 L36 56 L40 50 H56" fill="none" stroke="{GOLD}" stroke-width="3.5" stroke-linecap="round" stroke-linejoin="round"/>'
        f'</svg>\n'
    )
    (FRONT / "favicon.svg").write_text(fav, encoding="utf-8")

    # --- PNG / ICO / OG 用 Pillow 畫
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        print("Pillow 未安裝，略過 PNG/ICO/OG")
        return 0

    def draw_favicon(size: int) -> "Image.Image":
        S = 8  # supersample
        img = Image.new("RGBA", (64 * S, 64 * S), (0, 0, 0, 0))
        dr = ImageDraw.Draw(img)
        dr.rounded_rectangle([0, 0, 64 * S - 1, 64 * S - 1], radius=12 * S, fill=CREAM)
        k = 1.15 * S
        ox, oy = 9 * S, 8 * S
        dr.polygon([(ox + 4 * k, oy + 26 * k), (ox + 4 * k, oy + 6 * k), (ox + 14 * k, oy + 14 * k)], fill=INK)
        dr.polygon([(ox + 36 * k, oy + 26 * k), (ox + 36 * k, oy + 6 * k), (ox + 26 * k, oy + 14 * k)], fill=INK)
        for cx in (13, 27):
            dr.ellipse([ox + (cx - 2.6) * k, oy + (24 - 2.6) * k, ox + (cx + 2.6) * k, oy + (24 + 2.6) * k], fill=INK)
        pts = [(8, 50), (24, 50), (28, 50), (32, 40), (36, 56), (40, 50), (56, 50)]
        dr.line([(x * S, y * S) for x, y in pts], fill=GOLD, width=int(3.5 * S), joint="curve")
        for x, y in pts:
            dr.ellipse([x * S - 1.75 * S, y * S - 1.75 * S, x * S + 1.75 * S, y * S + 1.75 * S], fill=GOLD)
        return img.resize((size, size), Image.LANCZOS)

    draw_favicon(32).save(FRONT / "favicon-32.png")
    draw_favicon(180).save(FRONT / "favicon-180.png")
    draw_favicon(64).save(FRONT / "favicon.ico", sizes=[(16, 16), (32, 32), (48, 48)])

    # OG 1200×630
    og = Image.new("RGB", (1200, 630), CREAM)
    dr = ImageDraw.Draw(og)
    fnt = ImageFont.truetype(args.font, 150)
    bbox = dr.textbbox((0, 0), WORD, font=fnt)
    tw_, th_ = bbox[2] - bbox[0], bbox[3] - bbox[1]
    tx = (1200 - tw_) // 2 - bbox[0]
    ty = 235 - bbox[1]
    # 耳朵
    k = 2.6
    ex, ey = 600 - 20 * k, 150
    dr.polygon([(ex + 4 * k, ey + 20 * k), (ex + 4 * k, ey + 2 * k), (ex + 14 * k, ey + 10 * k)], fill=INK)
    dr.polygon([(ex + 36 * k, ey + 20 * k), (ex + 36 * k, ey + 2 * k), (ex + 26 * k, ey + 10 * k)], fill=INK)
    for cx in (13, 27):
        dr.ellipse([ex + (cx - 2.2) * k, ey + (18 - 2.2) * k, ex + (cx + 2.2) * k, ey + (18 + 2.2) * k], fill=INK)
    dr.text((tx, ty), WORD, font=fnt, fill=INK)
    # 脈搏
    pw = tw_ * 0.9
    px0 = 600 - pw / 2
    py = 235 + th_ + 40
    ps = pw / 150
    pts = [(0, 9), (56, 9), (61, 9), (65, 2), (70, 15), (75, 9), (150, 9)]
    line = [(px0 + x * ps, py + (y - 9) * ps) for x, y in pts]
    dr.line(line, fill=GOLD, width=6, joint="curve")
    small = ImageFont.truetype(args.font, 34)
    tag = "台灣貓健康知識庫 · 引用回溯原文 · 無業配"
    tb = dr.textbbox((0, 0), tag, font=small)
    dr.text(((1200 - (tb[2] - tb[0])) // 2 - tb[0], py + 50), tag, font=small, fill="#6e6e73")
    og.save(FRONT / "images" / "og-default.png", optimize=True)

    # --- 子集字型（備用，例如標題想直接用字型）
    subprocess.run([sys.executable, "-m", "fontTools.subset", args.font, f"--text={WORD}台灣貓健康知識庫",
                    "--flavor=woff2", f"--output-file={FRONT / 'fonts' / 'maoken-assorted-logo.woff2'}", "--no-hinting"],
                   check=True, capture_output=True)

    print(f"wordmark {ww:.0f}×{wh:.0f}  horizontal {HW:.0f}×{HH:.0f}  vertical {W:.0f}×{H:.0f}")
    for p in sorted(OUT.glob("*")) + [FRONT / "favicon.svg", FRONT / "favicon.ico", FRONT / "images" / "og-default.png"]:
        print(f"  {p.relative_to(ROOT)}  {p.stat().st_size} bytes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
