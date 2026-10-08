#!/usr/bin/env python3
"""
Claude Code PostToolUse hook：編輯 content/articles/*.md 後自動跑 lint。

由 .claude/settings.json 註冊。從 stdin 讀 hook JSON，若被編輯的檔案是文章，
執行 scripts/lint_articles.py --file <path>：
  - 有 FAIL → exit 2 並把結果印到 stderr（Claude 會看到並修正）
  - 只有 WARN 或乾淨 → exit 0（安靜）
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0
    tool_input = payload.get("tool_input") or {}
    fp = tool_input.get("file_path") or tool_input.get("path") or ""
    if not fp:
        return 0
    p = Path(fp)
    try:
        rel = p.resolve().relative_to(ROOT)
    except Exception:
        return 0
    if not (str(rel).replace("\\", "/").startswith("content/articles/") and p.suffix == ".md" and p.name != "README.md"):
        return 0
    if "/_archived/" in str(rel).replace("\\", "/"):
        return 0

    proc = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "lint_articles.py"), "--file", str(p), "--strict"],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    if proc.returncode == 1:
        sys.stderr.write(f"[cat-health-writing lint] {rel} 有 FAIL，依 SKILL.md 修正後再繼續：\n")
        sys.stderr.write(proc.stdout)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
