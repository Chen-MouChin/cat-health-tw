#!/usr/bin/env python3
"""
貓健康站 工作檯（本機用）
========================
Python 標準庫 HTTP 伺服器 + Vue 3（CDN）單頁前端，不需要 npm、不需要 build。

用法：
    python workbench/server.py            # http://127.0.0.1:8010/
    python workbench/server.py --port 9000

提供：
    /                     工作檯前端（workbench/index.html）
    /site/...             正式站 frontend/ 的靜態檔（審核時 iframe 渲染文章用）
    /api/overview         總覽：文章品質分布、lint、文獻狀態、git
    /api/articles         文章清單（frontmatter + lint 摘要）
    /api/articles/<slug>  單篇：frontmatter、lint 明細、引用的文獻
    POST /api/articles/<slug>/quality   {quality, note}  改 frontmatter
    /api/citations        文獻清單
    POST /api/citations/<key>           {status, title_zh, abstract_zh, url_verified, notes}
    POST /api/verify/<key>              跑 verify_citation.py
    POST /api/build                     跑 build.py
    POST /api/lint                      跑 lint（全站）
    /api/git              status / log
    POST /api/git/commit  {message}     fetch → add -A → commit → 落後就 pull --rebase（不 stash；衝突就停）
    POST /api/git/push                  只推到 GitHub，不會上線
    POST /api/deploy                    publish_site.py --deploy：網站成品推到公開 repo 並觸發部署，這才是上線
    /api/deploy/status                  最近一次部署的狀態
    POST /api/articles/<slug>/restore   {mode: undo | original} 撤銷上一次修改、回到初稿
    /api/helper/...                     小幫手離線審稿：審稿包、匯入、選版本（負責人）；寄回、換審稿包、結束（小幫手端）

安全：預設只綁 127.0.0.1。--lan 另開 https://<區網 IP>（自簽憑證，加密傳輸）給小幫手：要帶啟動時印出的通行碼，只能審稿，commit／push／部署只限本機；
公網位址一律拒絕，Host 標頭不對也拒絕。POST 需帶 X-Workbench: 1 標頭（擋跨站表單）。
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import subprocess
import sys
import webbrowser
import urllib.parse
import hashlib
import hmac
import http.cookies
import ipaddress
import secrets
import socket
import ssl
import threading
import time
import difflib
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

# 小幫手模式：workbench/helper/helper_main.py（或打包好的「開始審稿.exe」）設定 WB_HELPER_ROOT，
# 工作檯改跑在小幫手電腦上的工作資料夾，只有審稿功能，沒有核准、git、部署
HELPER_ROOT = os.environ.get("WB_HELPER_ROOT", "")
HELPER = bool(HELPER_ROOT)
FROZEN = bool(getattr(sys, "frozen", False))
ROOT = Path(HELPER_ROOT).resolve() if HELPER else Path(__file__).resolve().parent.parent
FRONTEND = ROOT / "frontend"
ARTICLES = ROOT / "content" / "articles"
CITATIONS = ROOT / "content" / "references" / "citations.json"
WB = Path(__file__).resolve().parent

sys.path.insert(0, str(ROOT / "scripts"))
import lint_articles as lint  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
import reviews  # noqa: E402
import pack  # noqa: E402

LOCK = threading.Lock()
BUILD_LOCK = threading.Lock()          # build.py 一次只跑一個，兩個人同時按也會排隊
STORE = reviews.Store(ROOT)
VERSIONS = pack.Versions(ROOT)
HELPER_DIR = ROOT / "build" / "helper"   # 產生的審稿包與 exe（build/ 不進 git）
OWNER_NAME = "Chen-MouChin"
# 審稿程式的版本。改了小幫手看得到的功能就加一版，並同步更新 workbench/helper/使用手冊.txt 的版本與更新紀錄
# （test_workbench.py 會檢查兩邊一致）
VERSION = "1.4"
FOOTNOTE_RE = re.compile(r"\[\^([A-Za-z0-9][A-Za-z0-9_\-\.]*)\]")
PY = sys.executable
RESEARCH = ROOT / "research"
DEPLOY_WORKFLOW = "Deploy to GitHub Pages"
SITE_REPO = "Chen-MouChin/cat-health-tw"   # 公開 repo，只放網站成品
PUBLISHED = ("reviewed", "featured")


def held_categories() -> set[str]:
    """build.py 的 HELD_CATEGORIES：整類暫停上線，核准了 build 也當草稿。讀原始碼，小幫手版沒有 import build 也能用。"""
    try:
        m = re.search(r"^HELD_CATEGORIES = \{([^}]*)\}", (ROOT / "build.py").read_text(encoding="utf-8"), re.M)
    except OSError:
        return set()
    return set(re.findall(r"\"([^\"]+)\"", m.group(1))) if m else set()


def articles_on_hold() -> bool:
    """build.py 的 ARTICLES_ON_HOLD：True 時全部文章暫停上線，核准了也當草稿。"""
    try:
        return bool(re.search(r"^ARTICLES_ON_HOLD = True\b", (ROOT / "build.py").read_text(encoding="utf-8"), re.M))
    except OSError:
        return False


def is_held(category: str) -> bool:
    return articles_on_hold() or (category or "") in held_categories()


# 10 篇核心文章，審核佇列「核心優先」用
CORE_SLUGS = {
    "cat-ckd-complete-guide", "male-cat-urethral-obstruction", "cat-vaccination-wellness-taiwan",
    "cat-toxic-substances-taiwan", "cat-emergency-care-taiwan", "cat-common-symptoms-taiwan",
    "cat-fip-guide-taiwan", "cat-diabetes-care", "cat-hyperthyroidism-senior", "cat-neutering-aftercare-taiwan",
}


def build_site() -> dict:
    """重建網站並回填 cited_by。用 BUILD_LOCK 排隊，避免兩個 build 同時寫 frontend/。"""
    with BUILD_LOCK:
        r = run(py("build.py"), 600)
        r2 = run(py("scripts/sync_cited_by.py"), 120)
    r["stdout"] += "\n[sync_cited_by]\n" + r2["stdout"]
    r["ok"] = r["code"] == 0
    if not r["ok"]:
        r["error"] = (r["stderr"] or r["stdout"])[-400:]
    return r


def text_hash(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()[:16]


def gh_exe() -> str:
    """gh CLI：PATH 裡有就用，沒有就用 winget 的預設安裝位置。"""
    for cand in ("gh", r"C:\Program Files\GitHub CLI\gh.exe"):
        try:
            subprocess.run([cand, "--version"], capture_output=True, timeout=20)
            return cand
        except (OSError, subprocess.SubprocessError):
            continue
    return "gh"


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def py(script: str, *args: str) -> list[str]:
    """跑 repo 裡的 Python 腳本。打包成 exe 時沒有 python，由 exe 自己用 --run-script 代跑。"""
    if FROZEN:
        return [sys.executable, "--run-script", str(ROOT / script), *args]
    return [PY, script, *args]


def run(cmd: list[str], timeout: int = 600) -> dict:
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if HELPER else 0   # 小幫手那邊不要跳出黑色視窗
    try:
        p = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace",
                           timeout=timeout, env=env, creationflags=flags)
    except OSError as e:
        return {"code": 127, "stdout": "", "stderr": f"{cmd[0]}：{e}"}
    except subprocess.TimeoutExpired:
        return {"code": 124, "stdout": "", "stderr": f"超過 {timeout} 秒沒有跑完，已停止"}
    return {"code": p.returncode, "stdout": p.stdout or "", "stderr": p.stderr or ""}


def article_files() -> list[Path]:
    return sorted(p for p in ARTICLES.glob("*.md") if p.name != "README.md")


def parse_fm(text: str) -> tuple[dict, str, str]:
    """回傳 (frontmatter dict, frontmatter 原文, body)。"""
    m = re.match(r"^---\r?\n(.*?)\r?\n---\r?\n(.*)$", text, re.S)
    if not m:
        return {}, "", text
    fm: dict = {}
    for line in m.group(1).splitlines():
        mm = re.match(r"^([A-Za-z_]+):\s*(.*)$", line)
        if mm:
            fm[mm.group(1)] = mm.group(2).strip().strip('"')
    return fm, m.group(1), m.group(2)


CIT_IO = threading.Lock()   # citations.json 的讀與 replace 不重疊（Windows 會拒絕 replace 正在讀的檔）


def load_citations() -> dict:
    with CIT_IO:
        return json.loads(CITATIONS.read_text(encoding="utf-8"))


def save_citations(data: dict) -> None:
    meta = data.get("_meta", {})
    items = [v for k, v in data.items() if k != "_meta"]
    meta["total"] = len(items)
    meta["approved"] = sum(1 for v in items if v.get("status") == "approved")
    meta["pending_review"] = sum(1 for v in items if v.get("status") == "pending_review")
    meta["rejected"] = sum(1 for v in items if v.get("status") == "rejected")
    data["_meta"] = meta
    tmp = CITATIONS.with_suffix(".json.tmp")
    with CIT_IO:
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        reviews.replace_retry(tmp, CITATIONS)


_LINT_CACHE: dict[str, dict] = {}
_LINT_MTIME: dict[str, float] = {}


def lint_article(path: Path, citations: dict, slugs: set[str]) -> dict:
    mt = path.stat().st_mtime
    key = str(path)
    if _LINT_MTIME.get(key) == mt:
        return _LINT_CACHE[key]
    r = lint.lint_one(path, {k: v for k, v in citations.items() if k != "_meta"}, slugs)
    _LINT_CACHE[key] = r
    _LINT_MTIME[key] = mt
    return r


_NOTES_CACHE: dict[str, dict[str, str]] = {}


def batch_notes() -> dict[str, str]:
    """research/review-batch-*.md 裡每篇的「### slug」段，給審核側欄顯示「這篇要注意什麼」。research/ 不進 git，沒有就空。"""
    files = sorted(RESEARCH.glob("review-batch-*.md")) if RESEARCH.exists() else []
    sig = "|".join(f"{f.name}:{f.stat().st_mtime}" for f in files)
    if sig in _NOTES_CACHE:
        return _NOTES_CACHE[sig]
    notes: dict[str, str] = {}
    for f in files:
        text = f.read_text(encoding="utf-8")
        for m in re.finditer(r"^### ([\w-]+)\n(.*?)(?=^### |^## |\Z)", text, re.M | re.S):
            notes[m.group(1)] = (notes.get(m.group(1), "") + f"（{f.stem}）\n" + m.group(2).strip() + "\n").strip()
    _NOTES_CACHE.clear()
    _NOTES_CACHE[sig] = notes
    return notes


def first_h1(body: str) -> str:
    m = re.search(r"^# (.+)$", body, re.M)
    return m.group(1).strip() if m else ""


# ---------------------------------------------------------------------------
# 評級表：完稿度（自動）＋優先等級（人工評分），給負責人與小幫手理性排優先順序
# ---------------------------------------------------------------------------

def completion(body: str, lint_r: dict, citations: dict, rec: dict, stage: str) -> dict:
    """完稿度 0–100：每一項怎麼算都列出來，畫面直接顯示。"""
    keys = list(dict.fromkeys(FOOTNOTE_RE.findall(body)))
    appr = sum(1 for k in keys if (citations.get(k) or {}).get("status") == "approved")
    checks = len([v for v in (rec.get("checklist") or {}).values() if isinstance(v, dict)])
    open_c = len([c for c in rec.get("comments", []) if not c.get("resolved")])
    struct = "30 秒重點" in body and "常見問題" in body
    n_warn = len(lint_r.get("warns", []))
    parts = [
        {"label": "照寫作規範改寫過（有「30 秒重點」與「常見問題」）", "got": 20 if struct else 0, "max": 20,
         "note": "有" if struct else "還是舊稿"},
        {"label": "寫作規範檢查", "got": 0 if lint_r.get("fails") else max(0, 15 - 3 * n_warn), "max": 15,
         "note": f"{len(lint_r['fails'])} 個 FAIL" if lint_r.get("fails") else f"0 FAIL、{n_warn} 個 WARN（每個扣 3 分）"},
        {"label": "引用的文獻已核准", "got": round(25 * appr / len(keys)) if keys else 0, "max": 25,
         "note": f"{appr} / {len(keys)} 筆" if keys else "沒有引用文獻"},
        {"label": "審核清單有人勾", "got": round(20 * min(checks, len(reviews.CHECKLIST)) / len(reviews.CHECKLIST)), "max": 20,
         "note": f"{min(checks, len(reviews.CHECKLIST))} / {len(reviews.CHECKLIST)} 項"},
        {"label": "審稿階段", "got": 10 if stage in ("passed", "approved") else 5 if stage == "changes" else 0, "max": 10,
         "note": reviews.STAGES.get(stage, stage)},
        {"label": "沒有未解決的註解", "got": max(0, 10 - 5 * open_c), "max": 10,
         "note": f"{open_c} 則未解決（每則扣 5 分）" if open_c else "都處理完了"},
    ]
    return {"total": sum(x["got"] for x in parts), "parts": parts}


def priority_rating(rec: dict, comp_total: int) -> dict:
    """優先等級：讀者需求＋寫錯的風險（人工 1–3）＋離完稿多近（完稿度換算 1–3）。兩項人工都評過才給等級。"""
    rt = rec.get("rating") or {}
    need = (rt.get("need") or {}).get("value", 0)
    risk = (rt.get("risk") or {}).get("value", 0)
    close = 1 if comp_total < 50 else 2 if comp_total < 75 else 3
    score = need + risk + close if need and risk else 0
    level = ("A" if score >= 8 else "B" if score >= 6 else "C") if score else ""
    return {"need": need, "risk": risk, "close": close, "score": score, "level": level,
            "by": {k: {"by": v.get("by", ""), "at": v.get("at", "")} for k, v in rt.items() if isinstance(v, dict)}}


def list_articles() -> list[dict]:
    citations = load_citations()
    files = article_files()
    fms = []
    for p in files:
        fm, _, body = parse_fm(p.read_text(encoding="utf-8"))
        fms.append((p, fm, body))
    slugs = {fm.get("slug") or p.stem for p, fm, _ in fms}
    notes = batch_notes()
    recs = STORE.all()
    prio = priority_order()
    core = core_slugs()
    out = []
    for p, fm, body in fms:
        r = lint_article(p, citations, slugs)
        slug = fm.get("slug") or p.stem
        rec = recs.get(slug) or STORE.load(slug)
        rv = STORE.summary(rec, fm.get("quality", "draft"))
        comp = completion(body, r, citations, rec, rv["stage"])
        pr = priority_rating(rec, comp["total"])
        out.append({
            **rv,
            "completion": comp["total"], "rating_level": pr["level"], "rating_score": pr["score"],
            "core": slug in core,
            "priority": prio.get(slug, 0),
            "has_notes": slug in notes,
            "title_h1_mismatch": bool(fm.get("title")) and first_h1(body) != "" and fm.get("title") != first_h1(body),
            "file": p.name,
            "slug": fm.get("slug") or p.stem,
            "title": fm.get("title", ""),
            "category": fm.get("category", ""),
            "quality": fm.get("quality", "draft"),
            "last_reviewed": fm.get("last_reviewed", ""),
            "date": fm.get("date") or fm.get("created", ""),
            "chars": r["chars"],
            "footnotes": r["footnotes"],
            "fails": len(r["fails"]),
            "warns": len(r["warns"]),
            "html": f"/site/articles/{fm.get('slug') or p.stem}.html",
        })
    return out


def find_article(slug: str) -> Path | None:
    for p in article_files():
        fm, _, _ = parse_fm(p.read_text(encoding="utf-8"))
        if (fm.get("slug") or p.stem) == slug:
            return p
    return None


def article_detail(slug: str) -> dict | None:
    p = find_article(slug)
    if not p:
        return None
    text = p.read_text(encoding="utf-8")
    fm, fm_raw, body = parse_fm(text)
    citations = load_citations()
    slugs = {(parse_fm(q.read_text(encoding="utf-8"))[0].get("slug") or q.stem) for q in article_files()}
    r = lint_article(p, citations, slugs)
    keys = []
    for k in FOOTNOTE_RE.findall(body):
        if k not in keys:
            keys.append(k)
    cites = []
    paragraphs = [p.strip() for p in body.split("\n\n") if p.strip()]
    for k in keys:
        c = citations.get(k)
        ctx_list = []
        for p_text in paragraphs:
            if f"[^{k}]" in p_text:
                # strip markdown headings
                clean_text = re.sub(r'^#{1,6}\s*', '', p_text).strip()
                ctx_list.append(clean_text)
                
        cites.append({"key": k, "found": bool(c), "contexts": ctx_list, **({
            "title": c.get("title", ""), "title_zh": c.get("title_zh", ""), "status": c.get("status", ""),
            "abstract_zh": c.get("abstract_zh", ""), "url": c.get("url", ""), "year": c.get("year", ""),
            "url_verified": bool(c.get("url_verified")), "source": c.get("source", ""),
        } if c else {})})
    sources = re.findall(r'^\s+-\s+"?(.+?)"?\s*$', fm_raw.split("sources:")[1].split("\n\n")[0], re.M) if "sources:" in fm_raw else []
    h1 = first_h1(body)
    rec = STORE.load(slug)
    # 舊版寫在 frontmatter 的 review_notes 轉成一則註解（只轉一次）
    legacy = (fm.get("review_notes") or "").strip()
    if legacy and not rec.get("legacy_migrated"):
        with reviews.LOCK:
            rec = STORE.load(slug)
            if not rec.get("legacy_migrated"):   # 鎖內再檢查一次，同時多個請求也只轉一次
                STORE._add_comment(rec, "舊備註", "", legacy, "")
                rec["legacy_migrated"] = True
                STORE.save(rec)
    if not rec.get("original_hash"):
        # 第一次在工作檯打開：記下這時候的版本，「回到初稿」就是回到這裡
        with reviews.LOCK:
            rec = STORE.load(slug)
            if not rec.get("original_hash"):
                rec["original_hash"] = VERSIONS.put(slug, text)
                rec["original_at"] = reviews.now()
                STORE.save(rec)
    quality = fm.get("quality", "draft")
    missing_cites = [c["key"] for c in cites if not c["found"]]
    unapproved = [c["key"] for c in cites if c["found"] and c.get("status") != "approved"]
    cur_h = pack.content_hash(text)
    u = undo_target(rec, cur_h)
    inc = rec.get("incoming")
    return {
        "review": {**STORE.summary(rec, quality), "checklist": rec["checklist"], "comments": rec["comments"],
                   "log": rec["log"][-80:][::-1], "approved_by": rec.get("approved_by", ""),
                   "approved_at": rec.get("approved_at", ""),
                   "undo": {k: u[k] for k in ("who", "at", "action")} if u else None,
                   "undo_blocked": bool(not u and any(e.get("after") and not e.get("undone") and e.get("kind") != "undo" for e in rec["log"])),
                   "original_at": rec.get("original_at", ""),
                   "can_original": rec.get("original_hash", cur_h) != cur_h and bool(VERSIONS.get(slug, rec.get("original_hash", ""))),
                   "incoming": {"who": inc["who"], "at": inc["at"], "why": inc.get("why", "")} if inc else None},
        "checklist_def": reviews.CHECKLIST,
        "gate": {"fails": len(r["fails"]), "missing_cites": missing_cites, "unapproved_cites": unapproved},
        "raw_hash": text_hash(text),
        "file": p.name, "slug": slug, "frontmatter": fm, "sources": sources,
        "held": is_held(fm.get("category") or ""), "held_all": articles_on_hold(),
        "priority": priority_order().get(slug, 0),
        "core": slug in core_slugs(),
        "completion": (comp := completion(body, r, citations, rec, STORE.effective_stage(rec, quality))),
        "rating": priority_rating(rec, comp["total"]),
        "rating_def": reviews.RATING,
        "body": body, "lint": {"fails": r["fails"], "warns": r["warns"], "chars": r["chars"]},
        "citations": cites, "html": f"/site/articles/{slug}.html",
        "review_notes": fm.get("review_notes", ""),
        "batch_notes": batch_notes().get(slug, ""),
        "h1": h1, "title_h1_mismatch": bool(fm.get("title")) and h1 != "" and fm.get("title") != h1,
    }


def undo_target(rec: dict, cur_h: str) -> dict | None:
    """「撤銷上一次修改」要撤的那一筆：最近一筆還沒撤銷的內文修改，而且文章現在就是它改完的樣子。
    文章在工作檯外被改過（例如 git pull），對不上就不給撤銷，只能回到初稿。"""
    for e in reversed(rec["log"]):
        if not e.get("after") or e.get("undone") or e.get("kind") == "undo":
            continue
        return e if e["after"] == cur_h else None
    return None


def restore(slug: str, mode: str, who: str) -> dict:
    """mode=undo：撤銷上一次修改（可以一直按，一步步往回）；mode=original：回到第一次在工作檯打開時的版本。
    兩種都不改上線狀態（quality），而且本身也記一筆，還原錯了可以再撤銷。"""
    p = find_article(slug)
    if not p:
        raise FileNotFoundError(slug)
    with LOCK:
        cur = p.read_text(encoding="utf-8")
        rec = STORE.load(slug)
        if mode == "undo":
            e = undo_target(rec, pack.content_hash(cur))
            if not e:
                return {"ok": False, "error": "沒有可以撤銷的修改" if not any(x.get("after") for x in rec["log"]) else
                        "這篇在工作檯以外被改過，沒辦法一步步撤銷；可以改用「回到初稿」"}
            target = VERSIONS.get(slug, e["before"])
            detail = f"撤銷 {e['who']} {e['at'][5:16].replace('T', ' ')} 的{e['action']}"
            action, kind = "撤銷修改", "undo"
        elif mode == "original":
            target = VERSIONS.get(slug, rec.get("original_hash", ""))
            detail = f"回到 {rec.get('original_at', '')[5:16].replace('T', ' ')} 第一次在工作檯打開時的版本"
            action, kind, e = "回到初稿", "restore", None
        else:
            raise ValueError("mode 只能是 undo 或 original")
        if target is None:
            return {"ok": False, "error": "找不到那個版本的備份"}
    res = save_raw(slug, pack.keep_status(target, cur), text_hash(cur), who, action, gate=False,
                   extra={"kind": kind, "detail": detail})
    if res.get("ok") and e:
        with reviews.LOCK:
            rec = STORE.load(slug)
            for x in rec["log"]:
                if x.get("at") == e["at"] and x.get("who") == e["who"] and x.get("action") == e["action"] and x.get("after") == e["after"]:
                    x["undone"] = True
            STORE.save(rec)
    return res


def save_raw(slug: str, raw: str, base_hash: str = "", who: str = "", action: str = "修改內文",
             gate: bool = True, extra: dict | None = None) -> dict:
    """工作檯直接編輯內文：先寫、跑 lint，有 FAIL 就還原並回報，壞的 Markdown 不進 build。
    base_hash 是打開編輯時的版本；檔案在那之後被改過就回 conflict，不蓋掉別人的修改。
    每次都把修改前後的版本存進 VERSIONS，撤銷與回到初稿靠這個。gate=False（撤銷、還原）時 lint 只回報、不擋。"""
    p = find_article(slug)
    if not p:
        raise FileNotFoundError(slug)
    with LOCK:
        before = p.read_text(encoding="utf-8")
        if base_hash and text_hash(before) != base_hash:
            last = next((e for e in reversed(STORE.load(slug)["log"]) if e["action"] in ("修改內文", "套用建議")), None)
            by = f"{last['who']} 在 {last['at'][11:16]} " if last else ""
            return {"ok": False, "conflict": True,
                    "error": f"這篇在你打開之後被{by}改過。你的修改還在編輯框裡，請先複製起來，重新載入後再貼上。"}
        if raw == before:
            return {"ok": True, "unchanged": True, "warns": []}
        p.write_text(raw, encoding="utf-8")
        _LINT_MTIME.clear()
        citations = load_citations()
        slugs = {(parse_fm(q.read_text(encoding="utf-8"))[0].get("slug") or q.stem) for q in article_files()}
        r = lint.lint_one(p, {k: v for k, v in citations.items() if k != "_meta"}, slugs)
        if r["fails"] and gate:
            p.write_text(before, encoding="utf-8")
            _LINT_MTIME.clear()
            return {"ok": False, "error": "lint 有 FAIL，沒有儲存", "fails": r["fails"]}
        extra = dict(extra or {})
        detail = extra.pop("detail", "")
        extra.update({"before": VERSIONS.put(slug, before), "after": VERSIONS.put(slug, raw)})
        STORE.note_event(slug, who or OWNER_NAME, action, detail, reviews.make_diff(before, raw), extra)
    return {"ok": True, "warns": r["warns"], "fails": r["fails"], "raw_hash": text_hash(raw)}


def approval_gate(slug: str) -> dict:
    """核准上線前的檢查：lint 沒有 FAIL、註腳都對得到文獻庫；引用的文獻還沒核准要另外確認。"""
    d = article_detail(slug)
    g = d["gate"]
    blockers = []
    if g["fails"]:
        blockers.append(f"lint 有 {g['fails']} 個 FAIL")
    if g["missing_cites"]:
        blockers.append("文獻庫沒有：" + "、".join(g["missing_cites"]))
    return {"blockers": blockers, "unapproved": g["unapproved_cites"], "stage": d["review"]["stage"]}


def set_quality(slug: str, quality: str, note: str, who: str = OWNER_NAME, confirm_unapproved: bool = False) -> dict:
    if quality not in ("draft", "reviewed", "featured", "archived"):
        raise ValueError("quality 只能是 draft / reviewed / featured / archived")
    p = find_article(slug)
    if not p:
        raise FileNotFoundError(slug)
    gate = None
    if quality in ("reviewed", "featured"):
        gate = approval_gate(slug)
        if gate["blockers"]:
            return {"ok": False, "error": "還不能上線：" + "；".join(gate["blockers"])}
        if gate["unapproved"] and not confirm_unapproved:
            return {"ok": False, "need_confirm": gate["unapproved"],
                    "error": f"這篇引用的 {len(gate['unapproved'])} 筆文獻還沒核准"}
    with LOCK:
        text = p.read_text(encoding="utf-8")
        m = re.match(r"^(---\r?\n)(.*?)(\r?\n---\r?\n)(.*)$", text, re.S)
        if not m:
            raise ValueError("frontmatter 解析失敗")
        head, fm_raw, sep, body = m.groups()
        today = dt.date.today().isoformat()
        lines = fm_raw.split("\n")

        def set_line(key: str, value: str | None):
            """value 為 None 時刪掉該行。"""
            nonlocal lines
            for i, l in enumerate(lines):
                if re.match(rf"^{key}:", l):
                    if value is None:
                        del lines[i]
                    else:
                        lines[i] = f"{key}: {value}"
                    return
            if value is not None:
                lines.append(f"{key}: {value}")

        set_line("quality", quality)
        set_line("last_reviewed", today if quality in ("reviewed", "featured") else "null")
        # 審稿備註改存在 research/reviews/（不進 git），frontmatter 不留
        set_line("review_notes", None)
        new = head + "\n".join(lines) + sep + body
        if quality == "archived":
            dest = ARTICLES / "_archived" / p.name
            dest.parent.mkdir(exist_ok=True)
            dest.write_text(new, encoding="utf-8")
            p.unlink()
            STORE.note_event(slug, who, "淘汰", note)
            return {"ok": True, "moved": str(dest.relative_to(ROOT))}
        p.write_text(new, encoding="utf-8")
    if quality in ("reviewed", "featured"):
        STORE.mark_approved(slug, who, quality, direct=gate["stage"] != "passed")
    else:
        STORE.owner_reject(slug, who, note)
    return {"ok": True}


def code_sig() -> str:
    """工作檯後端程式的指紋。和啟動時不一樣，代表檔案更新了但還在跑舊版，畫面會提醒重開。"""
    h = hashlib.sha256()
    for name in ("server.py", "reviews.py", "pack.py"):
        f = WB / name
        if f.exists():
            h.update(f.read_bytes())
    return h.hexdigest()[:12]


CODE_SIG = code_sig()


def overview() -> dict:
    arts = list_articles()
    q = {}
    for a in arts:
        q[a["quality"]] = q.get(a["quality"], 0) + 1
    cit = load_citations()
    items = [v for k, v in cit.items() if k != "_meta"]
    st = {}
    for v in items:
        st[v.get("status", "?")] = st.get(v.get("status", "?"), 0) + 1
    git = {"stdout": ""} if HELPER else run(["git", "status", "--porcelain"], 60)
    changed = [l for l in git["stdout"].splitlines() if l.strip()]
    # 上線 blocker：已審文章引用、但還沒 approved 的文獻
    pub_slugs = {a["slug"] for a in arts if a["quality"] in PUBLISHED and not is_held(a.get("category", ""))}
    blockers = sorted(
        k for k, v in cit.items()
        if k != "_meta" and v.get("status") != "approved" and set(v.get("cited_by") or []) & pub_slugs
    )
    title_h1 = sum(1 for a in arts if a["title_h1_mismatch"])
    stages = {}
    for a in arts:
        stages[a["stage"]] = stages.get(a["stage"], 0) + 1
    waiting = [{"slug": a["slug"], "title": a["title"], "by": a["last_by"], "at": a["last_activity"]}
               for a in arts if a["stage"] == "passed"]
    meta_js = FRONTEND / "js" / "meta.js"
    built = ""
    if meta_js.exists():
        mm = re.search(r'built_at: "([^"]+)"', meta_js.read_text(encoding="utf-8"))
        built = mm.group(1) if mm else ""
    return {
        "articles": {"total": len(arts), "by_quality": q,
                     "zero_fail": sum(1 for a in arts if a["fails"] == 0),
                     "fails": sum(a["fails"] for a in arts), "warns": sum(a["warns"] for a in arts),
                     "with_footnotes": sum(1 for a in arts if a["footnotes"]),
                     "core_reviewed": sum(1 for a in arts if a["core"] and a["quality"] in PUBLISHED),
                     "core_total": len(core_slugs()), "title_h1_mismatch": title_h1},
        "blockers": blockers,
        "review": {"stages": stages, "waiting": waiting, "labels": reviews.STAGES},
        "citations": {"total": len(items), "by_status": st,
                      "title_zh": sum(1 for v in items if v.get("title_zh")),
                      "abstract_zh": sum(1 for v in items if v.get("abstract_zh")),
                      "url_verified": sum(1 for v in items if v.get("url_verified")),
                      "cited": sum(1 for v in items if v.get("cited_by"))},
        "git": {"changed": len(changed), "branch": "" if HELPER else run(["git", "branch", "--show-current"], 30)["stdout"].strip()},
        "built_at": built,
        "thresholds": {"reviewed": 30, "approved": 40, "url_verified_pct": 90, "abstract_zh_pct": 80},
    }


def git_commit(message: str) -> dict:
    if not message.strip():
        return {"ok": False, "error": "commit 訊息不能空"}
    # 不用 stash：先把本機改動 commit 起來，再 rebase 到遠端；衝突就停下來交給人，不自動還原別人的檔案
    steps = []
    f = run(["git", "fetch"], 120); steps.append(("fetch", f))
    add = run(["git", "add", "-A"], 120); steps.append(("add", add))
    full = message.rstrip() + "\n"
    c = run(["git", "commit", "-m", full], 120); steps.append(("commit", c))
    if c["code"] != 0:
        return {"ok": False, "steps": steps, "error": c["stderr"] or c["stdout"]}
    st = run(["git", "status", "-sb"], 30)
    behind = "behind" in st["stdout"].splitlines()[0] if st["stdout"] else False
    if behind:
        pr = run(["git", "pull", "--rebase"], 300); steps.append(("pull --rebase", pr))
        if pr["code"] != 0:
            run(["git", "rebase", "--abort"], 60)
            return {"ok": False, "error": "已 commit，但 rebase 到遠端時有衝突，已中止；請在終端機手動 git pull --rebase 解衝突", "steps": steps}
    return {"ok": True, "steps": steps, "error": ""}


def deploy() -> dict:
    # 原始碼 repo 是私有的；網站成品由 publish_site.py 推到公開 repo，再觸發公開 repo 的 Pages 部署
    r = run([sys.executable, str(ROOT / "scripts" / "publish_site.py"), "--deploy"], 600)
    if r["code"] != 0:
        r["error"] = "gh 觸發失敗。沒登入請在終端機跑 gh auth login。" if "auth" in (r["stderr"] + r["stdout"]).lower() else (r["stderr"] or r["stdout"])
    return r


def deployed_source_sha(site_sha: str) -> str:
    """公開 repo 的 commit 訊息寫著「來源 abc1234」，取出線上這版對應的原始碼 commit。"""
    if not site_sha:
        return ""
    r = run([gh_exe(), "api", f"repos/{SITE_REPO}/commits/{site_sha}", "--jq", ".commit.message"], 60)
    m = re.search(r"來源 ([0-9a-f]{7,})", r["stdout"] or "")
    return m.group(1)[:7] if m else ""


def deploy_status() -> dict:
    gh = gh_exe()
    r = run([gh, "run", "list", "-R", SITE_REPO, "--workflow", DEPLOY_WORKFLOW, "--limit", "1",
             "--json", "status,conclusion,createdAt,url,headSha"], 60)
    if r["code"] != 0:
        return {"ok": False, "error": r["stderr"] or r["stdout"]}
    try:
        runs = json.loads(r["stdout"] or "[]")
    except ValueError:
        return {"ok": False, "error": r["stdout"]}
    head = run(["git", "rev-parse", "HEAD"], 30)["stdout"].strip()
    remote = run(["git", "rev-parse", "origin/main"], 30)["stdout"].strip()
    last = runs[0] if runs else None
    return {"ok": True, "last": last, "head": head[:7], "remote": remote[:7],
            "deployed_sha": deployed_source_sha((last or {}).get("headSha", "")),
            "site": "https://chen-mouchin.github.io/cat-health-tw/"}



# ---------------------------------------------------------------------------
# 小幫手離線審稿：負責人這邊（產生審稿包、匯入結果、逐段選版本）
# ---------------------------------------------------------------------------

PACKS_LOG = ROOT / "research" / "reviews" / "_packs.json"
IMPORTS_LOG = ROOT / "research" / "reviews" / "_imports.json"


def _jload(p: Path, default):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _jsave(p: Path, data) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    reviews.replace_retry(tmp, p)


# 負責人指定的優先審稿順序（slug 列表，前面的先審）；審核佇列排在最前面，不進 git
PRIORITY_FILE = RESEARCH / "reviews" / "_priority.json"


def priority_order() -> dict[str, int]:
    """slug → 第幾優先（1 起算）；沒指定的不在裡面。"""
    return {s: i + 1 for i, s in enumerate(_jload(PRIORITY_FILE, []))}


# 核心文章：負責人在文章頁勾選，存在 research/reviews/_core.json；檔案還沒有時用 CORE_SLUGS 當預設
CORE_FILE = RESEARCH / "reviews" / "_core.json"


def core_slugs() -> set[str]:
    data = _jload(CORE_FILE, None)
    return set(data) if isinstance(data, list) else set(CORE_SLUGS)


def set_core(slug: str, on: bool) -> list[str]:
    cur = core_slugs()
    (cur.add if on else cur.discard)(slug)
    lst = sorted(cur)
    _jsave(CORE_FILE, lst)
    return lst


def set_priority(slug: str, on: bool) -> list[str]:
    lst = [s for s in _jload(PRIORITY_FILE, []) if s != slug]
    if on:
        lst.append(slug)
    _jsave(PRIORITY_FILE, lst)
    return lst


def all_slugs() -> dict[str, Path]:
    out = {}
    for p in article_files():
        fm, _, _ = parse_fm(p.read_text(encoding="utf-8"))
        out[fm.get("slug") or p.stem] = p
    return out


def helper_exe():
    sys.path.insert(0, str(WB / "helper"))
    import build_exe  # noqa: E402
    return build_exe


def create_pack(body: dict) -> dict:
    slugs = all_slugs()
    focus = [s for s in body.get("focus") or [] if s in slugs]
    if not focus:
        return {"ok": False, "error": "至少勾一篇要請小幫手看的文章"}
    exe = None
    if body.get("full"):
        exe, err = helper_exe().ensure_exe()
        if not exe:
            return {"ok": False, "error": err}
    recs = {k: v for k, v in STORE.all().items() if k in slugs} if body.get("comments", True) else {}
    r = pack.make_pack(ROOT, HELPER_DIR / "packs", focus=focus, slugs=slugs, records=recs, versions=VERSIONS,
                       owner=OWNER_NAME, exe=exe)
    packs = _jload(PACKS_LOG, [])
    packs.append({"id": r["id"], "at": reviews.now(), "file": r["file"].name, "focus": len(focus),
                  "total": len(slugs), "full": bool(exe), "returns": []})
    _jsave(PACKS_LOG, packs[-50:])
    return {"ok": True, "name": r["file"].name, "size": r["size"], "id": r["id"]}


def _common_cells(a: list[str], b: list[str]) -> list[str]:
    """找不到審稿包當時的版本時，用兩邊都有的段落當共同祖先：兩邊不一樣的地方都會變成要選的。"""
    sm = difflib.SequenceMatcher(None, a, b, autojunk=False)
    return [c for blk in sm.get_matching_blocks() for c in a[blk.a:blk.a + blk.size]]


def _chunks(slug: str, cur: str, theirs: str, base_h: str) -> list[dict]:
    mine_c, theirs_c = pack.split_cells(pack.norm(cur)), pack.split_cells(pack.norm(theirs))
    base = VERSIONS.get(slug, base_h)
    base_c = pack.split_cells(pack.norm(base)) if base is not None else _common_cells(mine_c, theirs_c)
    return pack.merge3(base_c, mine_c, theirs_c)


def _set_incoming(slug: str, data: dict | None) -> None:
    with reviews.LOCK:
        rec = STORE.load(slug)
        if data:
            rec["incoming"] = data
        else:
            rec.pop("incoming", None)
        STORE.save(rec)


def apply_incoming(slug: str, theirs: str, base_h: str, who: str, at: str) -> dict:
    """小幫手改過的文章：這邊沒動過就直接套用；兩邊改的段落不重疊就自動合併；重疊才留給負責人選。"""
    p = find_article(slug)
    cur = p.read_text(encoding="utf-8")
    ch = pack.content_hash
    if ch(cur) == ch(theirs):
        return {"kind": "same", "result": "已經是這個版本"}
    base = VERSIONS.get(slug, base_h)
    n = pack.changed_cells(base if base is not None else cur, theirs)
    why = ""
    if ch(cur) == base_h:
        res = save_raw(slug, pack.keep_status(theirs, cur), text_hash(cur), who, "匯入審稿結果",
                       extra={"detail": f"{who} 改的 {n} 處"})
        if res.get("ok"):
            _set_incoming(slug, None)
            return {"kind": "applied", "result": f"已套用 {n} 處改字"}
        why = "寫作規範沒過：" + "、".join(f[0] for f in res.get("fails", []))
    else:
        chunks = _chunks(slug, cur, theirs, base_h)
        if base is not None and not any(c["t"] == "conflict" for c in chunks):
            merged = pack.keep_status(pack.merged_text(chunks, []), cur)
            res = save_raw(slug, merged, text_hash(cur), who, "匯入審稿結果",
                           extra={"detail": f"{who} 改的 {n} 處，和你的修改沒有重疊，自動合併"})
            if res.get("ok"):
                _set_incoming(slug, None)
                return {"kind": "merged", "result": f"已套用 {n} 處，和你的修改合併"}
            why = "合併後寫作規範沒過：" + "、".join(f[0] for f in res.get("fails", []))
    _set_incoming(slug, {"who": who, "at": at, "base": base_h, "raw": theirs, "why": why})
    return {"kind": "conflict", "result": why or "你也改過這篇，要選版本"}


def import_result(data: bytes) -> dict:
    sha = hashlib.sha256(data).hexdigest()
    seen = _jload(IMPORTS_LOG, {})
    if sha in seen:
        return {**seen[sha], "again": True}
    manifest, arts, recs = pack.read_result(data)
    who = pack.safe_name(str(manifest.get("reviewer") or "小幫手"))
    at = str(manifest.get("exported_at") or reviews.now())[:19]
    slugs = all_slugs()
    titles = {a["slug"]: a["title"] for a in list_articles()}
    rows, rebuilt = [], False
    for slug in sorted(set(arts) | set(recs), key=lambda s: (s not in arts, s)):
        row = {"slug": slug, "title": titles.get(slug, slug), "judgment": "還在看", "comments": 0}
        if slug not in slugs:
            rows.append({**row, "kind": "gone", "result": "這篇已經不在了（可能淘汰了）"})
            continue
        if slug in recs:
            inc = recs[slug]
            with reviews.LOCK:
                local = STORE.load(slug)
                reviews.merge_record(local, inc, who_from=who)
                STORE.save(local)
            row["judgment"] = {"passed": "通過", "changes": "需修改"}.get(inc.get("stage"), "還在看")
            row["comments"] = sum(1 for c in inc.get("comments") or [] if c.get("who") == who)
        if slug in arts:
            base_h = str((manifest.get("articles") or {}).get(slug, {}).get("base", ""))
            r = apply_incoming(slug, arts[slug], base_h, who, at)
            rebuilt |= r["kind"] in ("applied", "merged")
            row.update(r)
        else:
            row.update(kind="notes", result="註解已加入" if row["comments"] else "審稿紀錄已加入")
        rows.append(row)
    summary = {"ok": True, "who": who, "exported_at": at, "pack_id": manifest.get("pack_id", ""), "rows": rows,
               "at": reviews.now(), "build_ok": build_site()["ok"] if rebuilt else None}
    seen[sha] = summary
    _jsave(IMPORTS_LOG, seen)
    packs = _jload(PACKS_LOG, [])
    for pk in packs:
        if pk["id"] == summary["pack_id"]:
            pk["returns"].append({"who": who, "at": at, "done": sum(1 for r in rows if r["judgment"] != "還在看")})
    _jsave(PACKS_LOG, packs)
    return summary


def conflict_detail(slug: str) -> dict:
    rec = STORE.load(slug)
    inc = rec.get("incoming")
    p = find_article(slug)
    if not inc or not p:
        return {"ok": False, "error": "這篇沒有等你決定的版本"}
    cur = p.read_text(encoding="utf-8")
    chunks = _chunks(slug, cur, inc["raw"], inc["base"])
    fm, _, _ = parse_fm(cur)
    return {"ok": True, "slug": slug, "title": fm.get("title", slug), "who": inc["who"], "at": inc["at"],
            "why": inc.get("why", ""), "conflicts": pack.conflict_view(chunks), "hash": text_hash(cur),
            "known_base": VERSIONS.get(slug, inc["base"]) is not None}


def resolve_conflict(slug: str, body: dict, who: str) -> dict:
    rec = STORE.load(slug)
    inc = rec.get("incoming")
    p = find_article(slug)
    if not inc or not p:
        return {"ok": False, "error": "這篇沒有等你決定的版本"}
    if body.get("discard"):
        _set_incoming(slug, None)
        STORE.note_event(slug, who, "不採用小幫手的修改", f"{inc['who']} {inc['at'][5:16].replace('T', ' ')} 寄回的版本")
        return {"ok": True}
    cur = p.read_text(encoding="utf-8")
    if body.get("hash") and body["hash"] != text_hash(cur):
        return {"ok": False, "error": "這篇在你打開之後又被改過，請重新整理再選一次"}
    choices = [str(c) for c in body.get("choices") or []]
    merged = pack.keep_status(pack.merged_text(_chunks(slug, cur, inc["raw"], inc["base"]), choices), cur)
    pick = {"mine": "你的", "theirs": inc["who"] + "的", "both": "兩個都留"}
    res = save_raw(slug, merged, text_hash(cur), who, "合併小幫手的修改",
                   extra={"detail": f"{inc['who']} 的版本：" + "、".join(f"第 {i + 1} 處用{pick.get(c, c)}" for i, c in enumerate(choices))})
    if res.get("ok"):
        _set_incoming(slug, None)
    return res


def helper_overview() -> dict:
    incoming = [{"slug": slug, "who": r["incoming"]["who"], "at": r["incoming"]["at"], "why": r["incoming"].get("why", "")}
                for slug, r in STORE.all().items() if r.get("incoming")]
    imports = sorted(_jload(IMPORTS_LOG, {}).values(), key=lambda x: x.get("at", ""), reverse=True)[:5]
    return {"packs": _jload(PACKS_LOG, [])[::-1][:10], "incoming": incoming, "imports": imports,
            "exe": helper_exe().status(), "core": sorted(core_slugs())}


# ---------------------------------------------------------------------------
# 小幫手離線審稿：小幫手電腦這邊（寄回結果、換審稿包、結束）
# ---------------------------------------------------------------------------

HELPER_STATE = {"ping": 0.0, "servers": []}


def helper_name() -> str:
    return pack.helper_state(ROOT).get("name", "")


def unsent_slugs() -> list[str]:
    meta = _jload(ROOT / "pack.json", {})
    since = max(meta.get("installed_at", ""), pack.helper_state(ROOT).get("last_export_at", ""))
    return sorted(slug for slug, rec in STORE.all().items()
                  if any(not e.get("remote") and e.get("at", "") > since for e in rec["log"]))


def helper_info() -> dict:
    meta = _jload(ROOT / "pack.json", {})
    focus = meta.get("focus", [])
    recs = STORE.all()
    done = [s for s in focus if (recs.get(s) or {}).get("stage") in ("passed", "changes")]
    st = pack.helper_state(ROOT)
    return {"pack_id": meta.get("id", ""), "created_at": meta.get("created_at", ""), "owner": meta.get("owner", OWNER_NAME),
            "focus": focus, "done": len(done), "unsent": unsent_slugs(), "name": st.get("name", ""),
            "last_export_at": st.get("last_export_at", ""), "last_export_file": st.get("last_export_file", "")}


def helper_export(suffix: str = "") -> dict:
    name = helper_name() or "小幫手"
    data, counts = pack.make_result(ROOT, STORE.all(), name, all_slugs())
    out = pack.downloads_dir() / f"審稿結果-{pack.safe_name(name)}-{dt.date.today().strftime('%m%d')}{suffix}.zip"
    tmp = out.with_suffix(".tmp")
    tmp.write_bytes(data)
    tmp.replace(out)      # 同一天再寄一次就蓋掉舊的；新的包含到目前為止的全部進度
    pack.save_helper_state(ROOT, last_export_at=reviews.now(), last_export_file=str(out))
    return {"ok": True, "file": out.name, "path": str(out), "folder": str(out.parent), "counts": counts}


def helper_load_pack(src) -> dict:
    kept = None
    if (ROOT / "pack.json").exists() and unsent_slugs():
        kept = helper_export("-自動保留")
    with LOCK, BUILD_LOCK:
        meta = pack.install_pack(ROOT, src, lambda local, inc: reviews.merge_record(local, inc, remote=True))
        _LINT_MTIME.clear()
    return {"ok": True, "kept": kept["file"] if kept else "", "focus": len(meta.get("focus", [])),
            "created_at": meta.get("created_at", "")}


def open_folder(path: str) -> None:
    p = Path(path)
    if os.name == "nt":
        subprocess.Popen(["explorer", "/select,", str(p)] if p.is_file() else ["explorer", str(p)])
    else:
        webbrowser.open((p.parent if p.is_file() else p).as_uri())


def open_app_window(url: str) -> None:
    """小幫手那邊用 Edge 的 app 模式開，看起來像一般視窗、沒有網址列；沒有 Edge 就用預設瀏覽器。"""
    for base in (os.environ.get("ProgramFiles(x86)", ""), os.environ.get("ProgramFiles", ""), os.environ.get("LOCALAPPDATA", "")):
        edge = Path(base) / "Microsoft" / "Edge" / "Application" / "msedge.exe"
        if base and edge.exists():
            subprocess.Popen([str(edge), f"--app={url}", "--window-size=1320,880"])
            return
    webbrowser.open(url)

# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------

# 區網模式的設定，main() 啟動時填入
ACCESS = {"token": "", "hosts": set()}
OWNER_ONLY = ("/api/git/commit", "/api/git/push", "/api/deploy")


def client_role(ip: str, cookie_header: str, query_token: str) -> str:
    """回傳 owner（本機）、reviewer（區網且通行碼正確）或空字串（拒絕）。"""
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return ""
    if getattr(addr, "ipv4_mapped", None):
        addr = addr.ipv4_mapped
    if addr.is_loopback:
        return "reviewer" if HELPER else "owner"
    if HELPER or not ACCESS["token"] or not addr.is_private or addr.is_link_local:
        return ""
    jar = http.cookies.SimpleCookie()
    try:
        jar.load(cookie_header or "")
    except http.cookies.CookieError:
        pass
    given = query_token or (jar["wb_token"].value if "wb_token" in jar else "")
    return "reviewer" if given and hmac.compare_digest(given, ACCESS["token"]) else ""


CERT_DIR = ROOT / "build" / "workbench-cert"   # build/ 不進 git


def ensure_cert(ip: str) -> tuple[Path, Path, str]:
    """區網 HTTPS 用的自簽憑證。沒有、過期或 IP 換了就重產。回傳 (cert, key, SHA-256 指紋)。"""
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID

    cert_p, key_p = CERT_DIR / "cert.pem", CERT_DIR / "key.pem"
    if cert_p.exists() and key_p.exists():
        cert = x509.load_pem_x509_certificate(cert_p.read_bytes())
        try:
            sans = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
            ips = {str(a) for a in sans.get_values_for_type(x509.IPAddress)}
        except x509.ExtensionNotFound:
            ips = set()
        still_valid = cert.not_valid_after_utc > dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=7)
        if ip in ips and still_valid:
            return cert_p, key_p, cert.fingerprint(hashes.SHA256()).hex(":").upper()

    CERT_DIR.mkdir(parents=True, exist_ok=True)
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "cat-health workbench")])
    now = dt.datetime.now(dt.timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name).issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - dt.timedelta(minutes=5))
        .not_valid_after(now + dt.timedelta(days=365))
        .add_extension(x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address(ip))]), critical=False)
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .sign(key, hashes.SHA256())
    )
    key_p.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                        serialization.NoEncryption()))
    cert_p.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    return cert_p, key_p, cert.fingerprint(hashes.SHA256()).hex(":").upper()


def lan_ip() -> str:
    """本機在區網的 IP（只查路由，不送封包）。"""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


class EventLog:
    """黑色視窗的訊息：存檔等動作成功印一行 ✓；錯誤照印，但 30 秒內相同的錯誤只印第一次，
    之後合併成「又發生 n 次」。錯誤同時寫進 build/workbench-errors.log（不進 git），事後可以查。"""
    WINDOW = 30

    LABELS = [
        (r"/raw$", "存檔內文"), (r"/comment/[0-9a-f]+/apply$", "套用建議"), (r"/restore$", "還原"),
        (r"/stage$", "判斷"), (r"/comment$", "加註解"), (r"/reply$", "回覆註解"), (r"/resolve$", "註解狀態"),
        (r"/delete$", "刪除註解"), (r"/check$", "檢查清單"), (r"/claim$", "認領"), (r"/release$", "放下"),
        (r"/quality$", "改上線狀態"), (r"^/api/citations/", "更新文獻"), (r"^/api/build$", "重建網站"),
        (r"^/api/git/commit$", "commit"), (r"^/api/git/push$", "push"), (r"^/api/deploy$", "觸發部署"),
        (r"^/api/helper/pack$", "產生審稿包"), (r"^/api/helper/import$", "匯入審稿結果"),
        (r"^/api/helper/conflict/", "合併小幫手的版本"), (r"^/api/helper/export$", "寄回結果"),
        (r"^/api/helper/load-pack$", "換審稿包"), (r"^/api/helper/name$", "設定名字"),
    ]

    def __init__(self):
        self.lock = threading.Lock()
        self.seen: dict[tuple, dict] = {}
        self.file = ROOT / "build" / "workbench-errors.log"

    @staticmethod
    def _out(line: str) -> None:
        if sys.stdout:
            try:
                sys.stdout.write(line + "\n")
                sys.stdout.flush()
            except (OSError, ValueError):
                pass

    def _save(self, text: str) -> None:
        try:
            self.file.parent.mkdir(parents=True, exist_ok=True)
            with self.file.open("a", encoding="utf-8") as f:
                f.write(text + "\n")
        except OSError:
            pass

    def done(self, who: str, path: str, res: dict) -> None:
        path = urllib.parse.unquote(path.split("?")[0])
        label = next((l for pat, l in self.LABELS if re.search(pat, path)), "")
        if not label:
            return
        m = re.search(r"/(?:articles|review|conflict)/([A-Za-z0-9\-]+)", path)
        extra = []
        if res.get("build_ok") is False:
            extra.append("預覽重建失敗")
        elif res.get("build_ok"):
            extra.append("預覽已重建")
        if res.get("warns"):
            extra.append(f"WARN {len(res['warns'])}")
        if res.get("name") and label == "產生審稿包":
            extra.append(res["name"])
        if res.get("file") and label == "寄回結果":
            extra.append(res["file"])
        self._out(f"{dt.datetime.now():%H:%M:%S} ✓ {who} {label}" + (f" {m.group(1)}" if m else "")
                  + (f"（{'，'.join(extra)}）" if extra else ""))

    def error(self, kind: str, where: str, client: str, exc: BaseException | None = None, tb: bool = False) -> None:
        import traceback
        key = (kind, where, type(exc).__name__ if exc else "")
        now = time.time()
        with self.lock:
            ent = self.seen.get(key)
            if ent and now - ent["t"] < self.WINDOW:
                ent["n"] += 1
                return
            self.seen[key] = {"t": now, "n": 0, "line": f"{kind} {where}".strip()}
        line = f"{dt.datetime.now():%H:%M:%S} ✗ {kind} {where}（{client}）" + (f"：{type(exc).__name__} {exc}" if exc else "")
        self._out(line)
        detail = traceback.format_exc() if tb and exc else ""
        if detail:
            self._out(detail.rstrip())
        self._save(line + ("\n" + detail.rstrip() if detail else ""))

    def flush(self) -> None:
        """30 秒到了：被合併的錯誤印一行總數。"""
        now = time.time()
        with self.lock:
            due = [(k, e) for k, e in self.seen.items() if now - e["t"] >= self.WINDOW]
            for k, _ in due:
                del self.seen[k]
        for _, e in due:
            if e["n"]:
                line = f"{dt.datetime.now():%H:%M:%S} ✗ {e['line']}：前 30 秒內又發生 {e['n']} 次（已合併）"
                self._out(line)
                self._save(line)

    def start(self) -> None:
        def loop():
            while True:
                time.sleep(5)
                self.flush()
        threading.Thread(target=loop, daemon=True).start()


EVENTS = EventLog()


class Handler(SimpleHTTPRequestHandler):
    role = ""

    def _gate(self, query_token: str = "") -> bool:
        """所有請求先過這關：Host 標頭、來源位址、通行碼。不通過就回 403。"""
        host = (self.headers.get("Host") or "").lower()
        if host not in ACCESS["hosts"]:
            self._json({"error": "Host not allowed"}, 403)
            return False
        self.role = client_role(self.client_address[0], self.headers.get("Cookie", ""), query_token)
        name = urllib.parse.unquote(self.headers.get("X-Reviewer", "")).strip()
        name = re.sub(r"[\x00-\x1f<>]", "", name)[:20]
        self.who = OWNER_NAME if self.role == "owner" else ((helper_name() if HELPER else "") or name or "小幫手")
        if not self.role:
            self._json({"error": "需要通行碼：請用工作檯啟動時印出的網址開啟"}, 403)
            return False
        return True

    def log_message(self, fmt, *args):
        # 成功的請求不印（存檔等動作另外印一行「✓」）；4xx、5xx 才印，相同的 30 秒內合併
        if len(args) >= 2 and str(args[1]).isdigit() and int(args[1]) >= 400 and "/api/helper/ping" not in str(args[0]):
            EVENTS.error(f"HTTP {args[1]}", str(args[0]).split(" HTTP/")[0], self.client_address[0])

    def _json(self, obj, code=200):
        if self.command == "POST" and code == 200 and isinstance(obj, dict) and obj.get("ok") and not obj.get("unchanged"):
            EVENTS.done(getattr(self, "who", ""), self.path, obj)
        data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _file(self, path: Path):
        if not path.is_file():
            self.send_error(404)
            return
        ctype = self.guess_type(str(path))
        if path.suffix in (".html", ".js", ".css", ".json", ".svg", ".md"):
            ctype += "; charset=utf-8"
        data = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _bytes(self, limit: int) -> bytes:
        n = int(self.headers.get("Content-Length") or 0)
        if n > limit:
            raise ValueError("檔案太大")
        return self.rfile.read(n) if n else b""

    def _body(self) -> dict:
        if self.headers.get("Content-Type", "").startswith("application/zip"):
            return {}
        raw = self._bytes(20_000_000)
        return json.loads(raw.decode("utf-8")) if raw else {}

    def _download(self, path: Path):
        data = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "application/zip")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Content-Disposition", "attachment; filename*=UTF-8''" + urllib.parse.quote(path.name))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        u = urllib.parse.urlsplit(self.path)
        path = urllib.parse.unquote(u.path)
        qs = urllib.parse.parse_qs(u.query)
        if not self._gate(qs.get("t", [""])[0]):
            return
        try:
            if path in ("/", "/index.html"):
                if qs.get("t") and self.role == "reviewer":
                    # 通行碼換成 cookie，網址列不留通行碼
                    self.send_response(303)
                    self.send_header("Set-Cookie", f"wb_token={ACCESS['token']}; HttpOnly; Secure; SameSite=Strict; Path=/")
                    self.send_header("Location", "/")
                    self.end_headers()
                    return
                return self._file(WB / "index.html")
            if path == "/manual":
                # 使用手冊（純文字）；exe 裡放在程式旁邊，原始碼在 workbench/helper/
                f = next((x for x in (WB / "helper" / "使用手冊.txt", WB / "使用手冊.txt") if x.exists()), None)
                if not f:
                    return self.send_error(404)
                data = f.read_text(encoding="utf-8").replace("{owner}", OWNER_NAME).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
                return
            if path.startswith("/vendor/"):
                # 前端函式庫放本機，辦公室網路斷線也能用
                name = path[len("/vendor/"):]
                if not re.match(r"^[\w.\-]+$", name):
                    return self.send_error(404)
                return self._file(WB / "vendor" / name)
            if path.startswith("/site/"):
                rel = path[len("/site/"):] or "index.html"
                target = (FRONTEND / rel).resolve()
                if not str(target).startswith(str(FRONTEND.resolve())):
                    return self.send_error(403)
                if target.is_dir():
                    target = target / "index.html"
                # 草稿不進 frontend/，build.py 把它們寫到 build/drafts/，預覽時從那裡補
                if not target.exists() and rel.startswith("articles/"):
                    draft = (ROOT / "build" / "drafts" / rel).resolve()
                    if draft.exists():
                        target = draft
                return self._file(target)
            if path == "/api/overview":
                return self._json({**overview(), "role": self.role, "who": self.who, "owner": OWNER_NAME,
                                   "code_stale": not FROZEN and code_sig() != CODE_SIG, "version": VERSION,
                                   "helper": helper_info() if HELPER else None})
            if path.startswith("/api/helper/"):
                return self._helper_get(path)
            if path == "/api/activity":
                return self._json(STORE.activity())
            if path == "/api/deploy/status":
                return self._json(deploy_status())
            if path == "/api/articles":
                return self._json(list_articles())
            m_raw = re.match(r"^/api/articles/([A-Za-z0-9\-]+)/raw$", path)
            if m_raw:
                slug = m_raw.group(1)
                p = ARTICLES / f"{slug}.md"
                if not p.exists():
                    files = list(ARTICLES.glob(f"*-{slug}.md"))
                    if files: p = files[0]
                if not p.exists():
                    return self._json({"error": "not found"}, 404)
                text = p.read_text(encoding="utf-8")
                return self._json({"raw": text, "raw_hash": text_hash(text)})
            
            m = re.match(r"^/api/articles/([A-Za-z0-9\-]+)$", path)
            if m:
                d = article_detail(m.group(1))
                return self._json(d) if d else self._json({"error": "not found"}, 404)
            if path == "/api/citations":
                data = load_citations()
                status = qs.get("status", [""])[0]
                items = []
                for k, v in data.items():
                    if k == "_meta":
                        continue
                    if status and v.get("status") != status:
                        continue
                    items.append({"key": k, **{f: v.get(f, "") for f in (
                        "title", "title_zh", "authors", "source", "year", "url", "pdf_url", "status", "abstract_zh", "notes", "type")},
                        "url_verified": bool(v.get("url_verified")), "cited_by": v.get("cited_by") or []})
                return self._json(items)
            if path == "/api/git":
                st = run(["git", "status", "--porcelain"], 60)
                lg = run(["git", "log", "--oneline", "-15"], 60)
                sb = run(["git", "status", "-sb"], 60)
                return self._json({"status": st["stdout"], "log": lg["stdout"], "branch_line": sb["stdout"].splitlines()[0] if sb["stdout"] else ""})
            return self.send_error(404)
        except DISCONNECTED as e:
            # 瀏覽器自己中斷了（例如預覽重新載入），沒有人在等回應；記一筆，不回應
            EVENTS.error("瀏覽器中斷連線", f"{self.command} {self.path.split('?')[0]}", self.client_address[0], e)
            return
        except Exception as e:  # noqa: BLE001
            EVENTS.error("工作檯錯誤", f"{self.command} {self.path.split('?')[0]}", self.client_address[0], e, tb=True)
            return self._json({"error": str(e)}, 500)

    def _helper_get(self, path: str):
        if self.role != "owner":
            return self._json({"error": "只有網站負責人可以用"}, 403)
        if path == "/api/helper/packs":
            return self._json(helper_overview())
        m = re.match(r"^/api/helper/download/([^/\\]+\.zip)$", path)
        if m:
            f = HELPER_DIR / "packs" / m.group(1)
            return self._download(f) if f.is_file() and f.parent == HELPER_DIR / "packs" else self.send_error(404)
        m = re.match(r"^/api/helper/conflict/([A-Za-z0-9\-]+)$", path)
        if m:
            return self._json(conflict_detail(m.group(1)))
        return self.send_error(404)

    def _helper_post(self, path: str):
        """/api/helper/*：負責人的審稿包與匯入，小幫手的寄回、換審稿包、結束。"""
        owner_acts = ("/api/helper/pack", "/api/helper/import")
        if path in owner_acts or path.startswith("/api/helper/conflict/"):
            if self.role != "owner":
                return self._json({"error": "只有網站負責人可以用"}, 403)
            if path == "/api/helper/pack":
                return self._json(create_pack(self._body()))
            if path == "/api/helper/import":
                return self._json(import_result(self._bytes(60_000_000)))
            slug = path.rsplit("/", 1)[1]
            if not re.match(r"^[A-Za-z0-9\-]+$", slug):
                return self.send_error(404)
            res = resolve_conflict(slug, self._body(), self.who)
            if res.get("ok") and not res.get("unchanged") and "raw_hash" in res:
                res["build_ok"] = build_site()["ok"]
            return self._json(res)
        if not HELPER:
            return self.send_error(404)
        HELPER_STATE["ping"] = time.time()
        if path == "/api/helper/ping":
            return self._json({"ok": True})
        if path == "/api/helper/name":
            name = pack.safe_name(str(self._body().get("name", "")))
            pack.save_helper_state(ROOT, name=name)
            return self._json({"ok": True, "name": name})
        if path == "/api/helper/export":
            return self._json(helper_export())
        if path == "/api/helper/open-folder":
            f = pack.helper_state(ROOT).get("last_export_file", "")
            open_folder(f if f and Path(f).exists() else str(pack.downloads_dir()))
            return self._json({"ok": True})
        if path == "/api/helper/load-pack":
            res = helper_load_pack(self._bytes(200_000_000))
            return self._json(res)
        if path == "/api/helper/quit":
            self._json({"ok": True})
            threading.Timer(0.5, lambda: [s.shutdown() for s in HELPER_STATE["servers"]]).start()
            return
        return self.send_error(404)

    def do_POST(self):
        if self.headers.get("X-Workbench") != "1":
            return self._json({"error": "missing X-Workbench header"}, 403)
        path = urllib.parse.unquote(urllib.parse.urlsplit(self.path).path)
        if not self._gate():
            return
        if HELPER and (path in OWNER_ONLY or path.startswith("/api/verify/") or path == "/api/lint"):
            return self._json({"error": "小幫手的審稿程式沒有這個功能"}, 403)
        if path in OWNER_ONLY and self.role != "owner":
            return self._json({"error": "commit、push、部署只能在主機本機操作"}, 403)
        if re.match(r"^/api/articles/[A-Za-z0-9\-]+/quality$", path) and self.role != "owner":
            return self._json({"error": "核准上線、退回與淘汰由網站負責人操作；你可以按「初審通過」或「退回修改」"}, 403)
        try:
            if path.startswith("/api/helper/"):
                return self._helper_post(path)
            body = self._body()
            m_res = re.match(r"^/api/articles/([A-Za-z0-9\-]+)/restore$", path)
            if m_res:
                res = restore(m_res.group(1), body.get("mode", ""), self.who)
                if res.get("ok") and not res.get("unchanged"):
                    res["build_ok"] = build_site()["ok"]
                return self._json(res)
            m_raw = re.match(r"^/api/articles/([A-Za-z0-9\-]+)/raw$", path)
            if m_raw:
                if "raw" not in body:
                    return self._json({"error": "沒有 raw"}, 400)
                res = save_raw(m_raw.group(1), body["raw"], body.get("base_hash", ""), self.who)
                if res.get("ok") and not res.get("unchanged"):
                    b = build_site()
                    res["build_ok"] = b["ok"]
                return self._json(res, 409 if res.get("conflict") else 200)

            m = re.match(r"^/api/review/([A-Za-z0-9\-]+)/(claim|release|check|stage|comment|rating)$", path)
            if m:
                slug, act = m.groups()
                if not find_article(slug):
                    return self._json({"error": "not found"}, 404)
                if act == "claim":
                    return self._json(STORE.claim(slug, self.who, force=bool(body.get("force")) and self.role == "owner"))
                if act == "release":
                    return self._json(STORE.release(slug, self.who))
                if act == "check":
                    return self._json(STORE.set_check(slug, self.who, body.get("key", ""), body.get("value", "")))
                if act == "stage":
                    return self._json(STORE.set_stage(slug, self.who, body.get("stage", ""), body.get("note", "")))
                if act == "rating":
                    return self._json(STORE.set_rating(slug, self.who, body.get("key", ""), int(body.get("value") or 0)))
                return self._json(STORE.add_comment(slug, self.who, body.get("quote", ""), body.get("text", ""), body.get("suggestion", "")))
            m = re.match(r"^/api/review/([A-Za-z0-9\-]+)/comment/([0-9a-f]{8})/(reply|resolve|delete|apply)$", path)
            if m:
                slug, cid, act = m.groups()
                if act == "reply":
                    return self._json(STORE.reply(slug, self.who, cid, body.get("text", "")))
                if act == "resolve":
                    return self._json(STORE.resolve(slug, self.who, cid, bool(body.get("resolved", True))))
                if act == "delete":
                    return self._json(STORE.delete_comment(slug, self.who, cid, self.role == "owner"))
                # 套用建議：原文剛好出現一次才自動改，經過 lint 把關，再重建
                c = next((x for x in STORE.load(slug)["comments"] if x["id"] == cid), None)
                if not c or not c.get("suggestion"):
                    return self._json({"ok": False, "error": "這則註解沒有建議文字"})
                fp = find_article(slug)
                before = fp.read_text(encoding="utf-8")
                new, why = reviews.apply_suggestion(before, c["quote"], c["suggestion"])
                if new is None:
                    return self._json({"ok": False, "error": why})
                res = save_raw(slug, new, text_hash(before), self.who, "套用建議")
                if not res.get("ok"):
                    return self._json(res)
                STORE.resolve(slug, self.who, cid, True, "已套用")
                b = build_site()
                res["build_ok"] = b["ok"]
                return self._json(res)

            m = re.match(r"^/api/articles/([A-Za-z0-9\-]+)/quality$", path)
            if m:
                res = set_quality(m.group(1), body.get("quality", ""), body.get("note", ""), self.who,
                                  bool(body.get("confirm_unapproved")))
                if not res.get("ok"):
                    return self._json(res)
                _LINT_MTIME.clear()
                # 核准了就從優先審清單拿掉，後面的自動往前補
                if body.get("quality") in PUBLISHED:
                    set_priority(m.group(1), False)
                # 品質一改，frontend/ 的已審清單就變了（上架或下架），順手重建
                b = build_site()
                res["build_ok"] = b["ok"]
                res["build_out"] = (b["stdout"] + b.get("stderr", ""))[-800:]
                return self._json(res)
            m = re.match(r"^/api/citations/([A-Za-z0-9][A-Za-z0-9_\-\.]*)$", path)
            if m:
                with LOCK:
                    data = load_citations()
                    key = m.group(1)
                    if key not in data:
                        return self._json({"error": "not found"}, 404)
                    # 核准文獻只給擁有者；審稿者可以核對原文、改摘要、標成需要再看
                    if body.get("status") in ("approved", "rejected") and self.role != "owner" and body.get("status") != data[key].get("status"):
                        return self._json({"error": "文獻的核准與不採用由網站負責人操作"}, 403)
                    # approve 前必須先開過原文：url_verified 要是 true（本次送的或已存的）
                    if body.get("status") == "approved":
                        verified = body["url_verified"] if "url_verified" in body else data[key].get("url_verified")
                        if not verified:
                            return self._json({"error": "要先打開原文核對並勾「url 已驗證」，才能 approve"}, 400)
                    for f in ("status", "title_zh", "abstract_zh", "notes", "url"):
                        if f in body:
                            data[key][f] = body[f]
                    if "url_verified" in body:
                        data[key]["url_verified"] = bool(body["url_verified"])
                        if body["url_verified"]:
                            data[key]["verified_at"] = dt.date.today().isoformat()
                    save_citations(data)
                return self._json({"ok": True})
            if path == "/api/priority/by-rating":
                if self.role != "owner":
                    return self._json({"error": "優先順序由網站負責人設定"}, 403)
                arts = [a for a in list_articles() if a["rating_level"] in ("A", "B") and a["quality"] not in PUBLISHED]
                arts.sort(key=lambda a: (-a["rating_score"], -a["completion"], a["file"]))
                order = [a["slug"] for a in arts]
                _jsave(PRIORITY_FILE, order)
                return self._json({"ok": True, "order": order,
                                   "unrated": sum(1 for a in list_articles() if not a["rating_level"] and a["quality"] not in PUBLISHED)})
            if path == "/api/priority/order":
                # 拖曳排序：整串新順序，只能是目前優先清單裡的文章重新排列
                if self.role != "owner":
                    return self._json({"error": "優先順序由網站負責人設定"}, 403)
                order = [str(x) for x in (body.get("order") or [])]
                cur = _jload(PRIORITY_FILE, [])
                if sorted(order) != sorted(cur) or len(set(order)) != len(order):
                    return self._json({"error": "順序和目前的優先清單對不起來，請重新整理再試"}, 409)
                _jsave(PRIORITY_FILE, order)
                return self._json({"ok": True, "order": order})
            if path == "/api/core":
                # 核心文章只給負責人勾選
                if self.role != "owner":
                    return self._json({"error": "核心文章由網站負責人設定"}, 403)
                slug = str(body.get("slug", ""))
                if slug not in all_slugs():
                    return self._json({"error": "沒有這篇文章"}, 404)
                return self._json({"ok": True, "core": set_core(slug, bool(body.get("on")))})
            if path == "/api/priority":
                # 優先審稿順序只給負責人改
                if self.role != "owner":
                    return self._json({"error": "優先順序由網站負責人設定"}, 403)
                slug = str(body.get("slug", ""))
                if slug not in all_slugs():
                    return self._json({"error": "沒有這篇文章"}, 404)
                return self._json({"ok": True, "order": set_priority(slug, bool(body.get("on")))})
            m = re.match(r"^/api/verify/([A-Za-z0-9][A-Za-z0-9_\-\.]*)$", path)
            if m:
                cmd = [PY, "scrapers/literature/verify_citation.py", m.group(1), "--json"] + (["--refresh"] if body.get("refresh") else [])
                r = run(cmd, 180)
                try:
                    res = json.loads(r["stdout"].strip().splitlines()[-1])
                except (ValueError, IndexError):
                    return self._json({"error": "verify_citation 沒有正常結束：" + (r["stderr"] or r["stdout"])[-600:]})
                return self._json({"ok": True, "result": res})
            if path == "/api/build":
                return self._json(build_site())
            if path == "/api/lint":
                _LINT_MTIME.clear()
                r = run([PY, "scripts/lint_articles.py"], 300)
                return self._json(r)
            if path == "/api/git/commit":
                return self._json(git_commit(body.get("message", "")))
            if path == "/api/git/push":
                return self._json(run(["git", "push"], 300))
            if path == "/api/deploy":
                return self._json(deploy())
            return self.send_error(404)
        except (ValueError, FileNotFoundError) as e:
            return self._json({"ok": False, "error": str(e)}, 400)
        except DISCONNECTED as e:
            # 瀏覽器自己中斷了（例如預覽重新載入），沒有人在等回應；記一筆，不回應
            EVENTS.error("瀏覽器中斷連線", f"{self.command} {self.path.split('?')[0]}", self.client_address[0], e)
            return
        except Exception as e:  # noqa: BLE001
            EVENTS.error("工作檯錯誤", f"{self.command} {self.path.split('?')[0]}", self.client_address[0], e, tb=True)
            return self._json({"error": str(e)}, 500)


# 瀏覽器中途斷線（換頁、預覽重新載入、關掉分頁）。不算錯誤，不印 traceback
DISCONNECTED = (ConnectionError, ssl.SSLError, TimeoutError)


class WBServer(ThreadingHTTPServer):
    """port 被占用時要真的報錯。Windows 的 SO_REUSEADDR 會讓第二個工作檯綁上同一個 port，請求亂分給兩邊。"""
    allow_reuse_address = False

    def server_bind(self):
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()

    def handle_error(self, request, client_address):
        e = sys.exc_info()[1]
        EVENTS.error("瀏覽器中斷連線" if isinstance(e, DISCONNECTED) else "連線錯誤", "", client_address[0], e,
                     tb=not isinstance(e, DISCONNECTED))


def helper_start(pack_dir: Path | None, port: int = 8011, open_window: bool = True) -> int:
    """小幫手電腦上的審稿程式（開始審稿.exe 從這裡進來）。只綁 127.0.0.1，角色固定是審稿者。"""
    url = f"http://127.0.0.1:{port}/"
    ACCESS["hosts"] = {f"127.0.0.1:{port}", f"localhost:{port}"}
    srv = None
    for attempt in range(2):
        try:
            srv = WBServer(("127.0.0.1", port), Handler)
            break
        except OSError:
            if attempt:
                break
            # 上一次的審稿程式還開著：請它先關掉（進度都在硬碟上），這次才能載入新的審稿包
            try:
                import urllib.request
                req = urllib.request.Request(url + "api/helper/quit", data=b"{}", method="POST",
                                             headers={"X-Workbench": "1", "Content-Type": "application/json"})
                urllib.request.urlopen(req, timeout=5).read()
            except OSError:
                pass
            time.sleep(1.5)
    if srv is None:
        if open_window:
            open_app_window(url)
        return 2
    if pack_dir and (pack_dir / "pack.json").exists():
        new = _jload(pack_dir / "pack.json", {})
        if new.get("id") and new.get("id") != _jload(ROOT / "pack.json", {}).get("id"):
            helper_load_pack(pack_dir)
    EVENTS.start()
    HELPER_STATE["servers"] = [srv]
    HELPER_STATE["ping"] = time.time()

    def watchdog():
        # 視窗關掉之後頁面就不會再 ping；15 分鐘沒動靜就自己結束，不留在背景
        while True:
            time.sleep(30)
            if time.time() - HELPER_STATE["ping"] > 900:
                srv.shutdown()
                return
    threading.Thread(target=watchdog, daemon=True).start()
    if open_window:
        open_app_window(url)
    try:
        srv.serve_forever()
    finally:
        srv.server_close()
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--lan", action="store_true", help="開給同區網的小幫手審稿（要通行碼；commit／push／部署只限本機）")
    ap.add_argument("--port", type=int, default=8010)
    ap.add_argument("--open", action="store_true", help="啟動後自動開瀏覽器；工作檯已經在跑就只開頁面")
    args = ap.parse_args()
    url = f"http://127.0.0.1:{args.port}/"
    ACCESS["hosts"] = {f"127.0.0.1:{args.port}", f"localhost:{args.port}"}
    # 本機：http，只綁 127.0.0.1
    try:
        srv = WBServer(("127.0.0.1", args.port), Handler)
    except OSError:
        if args.open:
            print(f"工作檯已經在跑，直接開 {url}")
            webbrowser.open(url)
            return 0
        print(f"port {args.port} 被占用：工作檯可能已經在跑，或換 --port")
        return 2
    print(f"貓健康站 工作檯 → {url}   (Ctrl+C 停止)")
    servers = [srv]
    if args.lan:
        # 區網：https，只綁區網 IP；同一個 port，位址不同不衝突
        ip = lan_ip()
        if ip == "127.0.0.1":
            print("找不到區網 IP，--lan 沒有開。")
            return 2
        try:
            cert_p, key_p, fp = ensure_cert(ip)
        except ImportError:
            print("區網 HTTPS 需要 cryptography：pip install cryptography")
            return 2
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.minimum_version = ssl.TLSVersion.TLSv1_2
        ctx.load_cert_chain(cert_p, key_p)
        lan = WBServer((ip, args.port), Handler)
        lan.socket = ctx.wrap_socket(lan.socket, server_side=True)
        servers.append(lan)
        ACCESS["token"] = secrets.token_urlsafe(12)
        ACCESS["hosts"].add(f"{ip}:{args.port}")
        print(f" 區網審稿網址（給小幫手，含通行碼，每次啟動都會換）：https://{ip}:{args.port}/?t={ACCESS['token']}")
        print(f" 憑證指紋 SHA-256：{fp}")
        print(" 第一次開會出現「連線不是私人連線」：先在瀏覽器的憑證資訊比對上面的指紋，一樣再按「繼續前往」。")
        print(" 小幫手可以審文章、核對文獻、重建預覽；commit、push、部署只能在這台電腦操作。")
        print(" 只在自己的辦公室網路開；Windows 防火牆只允許「私人網路」。用完 Ctrl+C 關掉。")
    EVENTS.start()
    for s in servers[1:]:
        threading.Thread(target=s.serve_forever, daemon=True).start()
    if args.open:
        webbrowser.open(url)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        for s in servers:
            s.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
