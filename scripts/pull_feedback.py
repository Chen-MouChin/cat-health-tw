"""把 GitHub 上標了 feedback 的 Issue 整理成 research/feedback.md（本機，不進 git）。

網站「關於」頁的回饋表單會開一個預填好的 Issue（範本在 .github/ISSUE_TEMPLATE/feedback.yml）。
這支腳本把它們拉下來，未處理的排前面，方便一次看完。

用法：
    python scripts/pull_feedback.py            # 開放中與已關閉的都抓
    python scripts/pull_feedback.py --open     # 只抓還沒處理的
repo 是公開的，不用登入；有 gh CLI 登入時會用它的 token，額度比較高。
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import urllib.request
from datetime import datetime
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "research" / "feedback.md"
REPO = "Chen-MouChin/cat-health-tw"
LABEL = "feedback"


def gh_token() -> str:
    for cand in ("gh", r"C:\Program Files\GitHub CLI\gh.exe"):
        if shutil.which(cand) or Path(cand).exists():
            try:
                r = subprocess.run([cand, "auth", "token"], capture_output=True, text=True, timeout=20)
                if r.returncode == 0:
                    return r.stdout.strip()
            except (OSError, subprocess.SubprocessError):
                pass
    return ""


def fetch_issues(state: str) -> list[dict]:
    token = gh_token()
    issues, page = [], 1
    while True:
        url = f"https://api.github.com/repos/{REPO}/issues?labels={LABEL}&state={state}&per_page=100&page={page}"
        req = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json", "User-Agent": "cat-health-tw-feedback"})
        if token:
            req.add_header("Authorization", f"Bearer {token}")
        with urllib.request.urlopen(req, timeout=30) as r:
            batch = json.loads(r.read().decode("utf-8"))
        batch = [i for i in batch if "pull_request" not in i]
        issues += batch
        if len(batch) < 100:
            return issues
        page += 1


def parse_body(body: str) -> dict:
    """Issue 表單的內文是「### 欄位名稱」加內容的 markdown，拆成 dict。"""
    fields = {}
    for m in re.finditer(r"^### (.+?)\n+(.*?)(?=^### |\Z)", body or "", re.M | re.S):
        val = m.group(2).strip()
        fields[m.group(1).strip()] = "" if val == "_No response_" else val
    return fields


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--open", action="store_true", help="只抓還沒處理（open）的")
    args = ap.parse_args()
    issues = fetch_issues("open" if args.open else "all")
    issues.sort(key=lambda i: (i["state"] != "open", i["created_at"]), reverse=False)
    n_open = sum(1 for i in issues if i["state"] == "open")

    lines = [
        "# 網站回饋",
        "",
        f"_更新 {datetime.now():%Y-%m-%d %H:%M} · 共 {len(issues)} 則，未處理 {n_open} 則 · 來源 GitHub Issue（標籤 {LABEL}）_",
        "",
        "處理完在 GitHub 上回覆並關閉 Issue，下次執行就會移到「已處理」。",
        "",
    ]
    for section, want in (("未處理", "open"), ("已處理", "closed")):
        group = [i for i in issues if i["state"] == want]
        if not group:
            continue
        lines += [f"## {section}（{len(group)}）", ""]
        for i in group:
            f = parse_body(i.get("body", ""))
            topic = f.get("主題", "")
            lines += [
                f"### #{i['number']} {i['title']}",
                "",
                f"- 主題：{topic or '（未填）'}",
                f"- 時間：{i['created_at'][:10]} · 來自 @{i['user']['login']}",
                f"- 頁面：{f.get('你在看的頁面') or '（未填）'}",
                f"- 連結：{i['html_url']}",
                "",
                f.get("訊息") or (i.get("body") or "").strip() or "（沒有內容）",
                "",
            ]
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"→ {OUT}（{len(issues)} 則，未處理 {n_open} 則）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
