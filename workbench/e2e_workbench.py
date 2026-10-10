"""工作檯畫面端到端測試（選用）：用真的 Chrome 走一遍小幫手審稿到負責人核准。

需要 playwright（pip install playwright），使用本機已安裝的 Chrome，不另外下載瀏覽器。
和 test_workbench.py 一樣在暫存複製上跑，不碰真的 repo。截圖存到 build/e2e/。

    python workbench/e2e_workbench.py
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_workbench as tw  # noqa: E402

from playwright.sync_api import sync_playwright, expect  # noqa: E402

SHOTS = tw.REAL_ROOT / "build" / "e2e"


def main() -> int:
    SHOTS.mkdir(parents=True, exist_ok=True)
    errors: list[str] = []
    steps: list[str] = []

    def ok(msg):
        steps.append(msg)
        print("  ✓", msg)

    tw.setup_repo()
    tw.start_server()
    try:
        if not tw.SERVER.get("lan_url"):
            print("找不到區網 IP，無法測小幫手流程")
            return 1
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="chrome", headless=True)

            # ---------- 小幫手 ----------
            # 測試用的自簽憑證，瀏覽器層忽略憑證警告（真實使用時由人比對指紋）
            ctx = browser.new_context(ignore_https_errors=True, viewport={"width": 1500, "height": 950}, locale="zh-TW")
            page = ctx.new_page()
            page.on("console", lambda m: m.type == "error" and errors.append("小幫手 console：" + m.text))
            page.on("pageerror", lambda e: errors.append("小幫手 頁面錯誤：" + str(e)))
            page.on("dialog", lambda d: d.accept())
            page.goto(tw.SERVER["lan_url"])

            expect(page.get_by_text("你的名字")).to_be_visible()
            page.get_by_placeholder("例如：小美").fill("小美")
            page.get_by_role("button", name="開始").click()
            expect(page.get_by_text("謝謝你幫忙審稿")).to_be_visible()
            page.screenshot(path=str(SHOTS / "01-guide.png"))
            page.get_by_role("button", name="知道了").click()
            ok("第一次進來：填名字、看到說明")

            expect(page.locator("nav.tabs")).not_to_contain_text("建置與發佈")
            ok("小幫手看不到「建置與發佈」")

            page.locator(".list-item").first.click()
            page.get_by_role("button", name="我來審這篇").click()
            expect(page.get_by_text("你正在審這篇")).to_be_visible()
            ok("認領文章")

            frame = page.frame_locator("iframe")
            frame.locator("article p").first.wait_for()
            iframe = page.frames[1]
            # 在第一段落的純文字節點反白 12 個字，觸發 mouseup
            quote = iframe.evaluate("""() => {
                const root = document.querySelector('article');
                const w = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
                let n;
                while ((n = w.nextNode())) {
                    const t = n.nodeValue.trim();
                    if (n.parentElement.closest('p') && !n.parentElement.closest('.article-meta, .draft-banner, aside') && /[\\u4e00-\\u9fff]{14}/.test(n.nodeValue)) {
                        const i = n.nodeValue.search(/[\\u4e00-\\u9fff]{14}/);
                        const r = document.createRange();
                        r.setStart(n, i); r.setEnd(n, i + 12);
                        const s = getSelection(); s.removeAllRanges(); s.addRange(r);
                        n.parentElement.dispatchEvent(new MouseEvent('mouseup', {bubbles: true}));
                        return r.toString();
                    }
                }
                return '';
            }""")
            assert quote, "找不到可以反白的段落"
            add_btn = frame.locator(".wb-add")
            expect(add_btn).to_be_visible()
            page.screenshot(path=str(SHOTS / "02-select.png"))
            add_btn.click()
            expect(page.locator(".composer .quote")).to_contain_text(quote)
            page.get_by_placeholder("哪裡有問題？", exact=False).fill("這句可以更口語")
            page.get_by_placeholder("建議改成（選填）", exact=False).fill(quote + "（小美建議）")
            page.get_by_role("button", name="送出註解").click()
            expect(page.locator(".cmt .body").first).to_have_text("這句可以更口語")
            expect(frame.locator("mark.wb-hl")).to_have_count(1)
            page.screenshot(path=str(SHOTS / "03-comment.png"))
            ok("反白文字加註解，文章上出現標記")

            # 初審通過按鈕：有未解決註解時不能按
            page.locator(".stabs button", has_text="審稿").click()
            expect(page.get_by_role("button", name="初審通過", exact=True)).to_be_disabled()
            ok("有未處理註解時，不能初審通過")

            page.locator(".stabs button", has_text="註解").click()
            page.get_by_role("button", name="套用建議").click()
            expect(page.locator(".toast")).to_contain_text("已套用")
            expect(frame.locator("article")).to_contain_text(quote + "（小美建議）", timeout=15000)
            ok("套用建議，預覽更新成新句子")

            page.locator(".seg button", has_text="修改紀錄").click()
            expect(page.locator(".diff .add").first).to_contain_text("小美建議")
            page.screenshot(path=str(SHOTS / "04-history.png"))
            ok("修改紀錄顯示誰改了哪一行")
            page.locator(".seg button", has_text="閱讀").click()

            page.locator(".stabs button", has_text="審稿").click()
            for b in page.locator(".check .opts button.ok").all():
                b.click()
            expect(page.get_by_text("檢查清單（5/5）")).to_be_visible()
            page.get_by_role("button", name="初審通過", exact=True).click()
            expect(page.locator(".toast")).to_contain_text("初審通過")
            ok("勾完清單，按初審通過")
            ctx.close()

            # ---------- 負責人 ----------
            octx = browser.new_context(viewport={"width": 1500, "height": 950}, locale="zh-TW")
            op = octx.new_page()
            op.on("console", lambda m: m.type == "error" and errors.append("負責人 console：" + m.text))
            op.on("pageerror", lambda e: errors.append("負責人 頁面錯誤：" + str(e)))
            op.on("dialog", lambda d: d.accept())
            op.goto(f"http://127.0.0.1:{tw.SERVER['port']}/#dash")
            card = op.locator(".card", has_text="等你核准")
            expect(card.locator(".big")).to_have_text("1")
            expect(op.locator(".feed")).to_contain_text("小美")
            op.screenshot(path=str(SHOTS / "05-owner-dash.png"))
            ok("負責人儀表板看到「等你核准 1」與小美的動態")

            card.locator("a").first.click()
            expect(op.locator(".pane .pill").first).to_have_text("初審通過")
            op.get_by_role("button", name="核准上線", exact=True).click()
            expect(op.locator(".pane .pill").first).to_have_text("已上線", timeout=30000)
            op.screenshot(path=str(SHOTS / "06-approved.png"))
            ok("負責人核准上線")
            octx.close()
            browser.close()
    except Exception:
        for e in errors:
            print("  ✗", e)
        print("".join(tw.SERVER.get("log", []))[-1500:])
        raise
    finally:
        tw.stop_server()
        try:
            tw.rm_tree(tw.TMP)
        except OSError:
            pass

    print(f"\n畫面測試：{len(steps)} 步通過；console 錯誤 {len(errors)} 筆")
    for e in errors:
        print("  ✗", e)
    print(f"截圖：{SHOTS}")
    return 1 if errors else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:  # noqa: BLE001
        print("✗ 畫面測試失敗：", e)
        sys.exit(1)
