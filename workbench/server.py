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
    POST /api/deploy                    gh workflow run「Deploy to GitHub Pages」，這才是上線
    /api/deploy/status                  最近一次部署的狀態

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
import urllib.parse
import hashlib
import hmac
import http.cookies
import ipaddress
import secrets
import socket
import ssl
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parent.parent
FRONTEND = ROOT / "frontend"
ARTICLES = ROOT / "content" / "articles"
CITATIONS = ROOT / "content" / "references" / "citations.json"
WB = Path(__file__).resolve().parent

sys.path.insert(0, str(ROOT / "scripts"))
import lint_articles as lint  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
import reviews  # noqa: E402

LOCK = threading.Lock()
BUILD_LOCK = threading.Lock()          # build.py 一次只跑一個，兩個人同時按也會排隊
STORE = reviews.Store(ROOT)
OWNER_NAME = "Chen-MouChin"
FOOTNOTE_RE = re.compile(r"\[\^([A-Za-z0-9][A-Za-z0-9_\-\.]*)\]")
PY = sys.executable
RESEARCH = ROOT / "research"
DEPLOY_WORKFLOW = "Deploy to GitHub Pages"
PUBLISHED = ("reviewed", "featured")
# 10 篇核心文章，審核佇列「核心優先」用
CORE_SLUGS = {
    "cat-ckd-complete-guide", "male-cat-urethral-obstruction", "cat-vaccination-wellness-taiwan",
    "cat-toxic-substances-taiwan", "cat-emergency-care-taiwan", "cat-common-symptoms-taiwan",
    "cat-fip-guide-taiwan", "cat-diabetes-care", "cat-hyperthyroidism-senior", "cat-neutering-aftercare-taiwan",
}


def build_site() -> dict:
    """重建網站並回填 cited_by。用 BUILD_LOCK 排隊，避免兩個 build 同時寫 frontend/。"""
    with BUILD_LOCK:
        r = run([PY, "build.py"], 600)
        r2 = run([PY, "scripts/sync_cited_by.py"], 120)
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

def run(cmd: list[str], timeout: int = 600) -> dict:
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    p = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace",
                       timeout=timeout, env=env)
    return {"code": p.returncode, "stdout": p.stdout, "stderr": p.stderr}


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
    out = []
    for p, fm, body in fms:
        r = lint_article(p, citations, slugs)
        slug = fm.get("slug") or p.stem
        rv = STORE.summary(recs.get(slug) or STORE.load(slug), fm.get("quality", "draft"))
        out.append({
            **rv,
            "core": slug in CORE_SLUGS,
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
    quality = fm.get("quality", "draft")
    missing_cites = [c["key"] for c in cites if not c["found"]]
    unapproved = [c["key"] for c in cites if c["found"] and c.get("status") != "approved"]
    return {
        "review": {**STORE.summary(rec, quality), "checklist": rec["checklist"], "comments": rec["comments"],
                   "log": rec["log"][-80:][::-1], "approved_by": rec.get("approved_by", ""),
                   "approved_at": rec.get("approved_at", "")},
        "checklist_def": reviews.CHECKLIST,
        "gate": {"fails": len(r["fails"]), "missing_cites": missing_cites, "unapproved_cites": unapproved},
        "raw_hash": text_hash(text),
        "file": p.name, "slug": slug, "frontmatter": fm, "sources": sources,
        "body": body, "lint": {"fails": r["fails"], "warns": r["warns"], "chars": r["chars"]},
        "citations": cites, "html": f"/site/articles/{slug}.html",
        "review_notes": fm.get("review_notes", ""),
        "batch_notes": batch_notes().get(slug, ""),
        "h1": h1, "title_h1_mismatch": bool(fm.get("title")) and h1 != "" and fm.get("title") != h1,
    }


def save_raw(slug: str, raw: str, base_hash: str = "", who: str = "", action: str = "修改內文") -> dict:
    """工作檯直接編輯內文：先寫、跑 lint，有 FAIL 就還原並回報，壞的 Markdown 不進 build。
    base_hash 是打開編輯時的版本；檔案在那之後被改過就回 conflict，不蓋掉別人的修改。"""
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
        if r["fails"]:
            p.write_text(before, encoding="utf-8")
            _LINT_MTIME.clear()
            return {"ok": False, "error": "lint 有 FAIL，沒有儲存", "fails": r["fails"]}
        STORE.note_event(slug, who or OWNER_NAME, action, diff=reviews.make_diff(before, raw))
    return {"ok": True, "warns": r["warns"], "raw_hash": text_hash(raw)}


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
    git = run(["git", "status", "--porcelain"], 60)
    changed = [l for l in git["stdout"].splitlines() if l.strip()]
    # 上線 blocker：已審文章引用、但還沒 approved 的文獻
    pub_slugs = {a["slug"] for a in arts if a["quality"] in PUBLISHED}
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
                     "core_total": len(CORE_SLUGS), "title_h1_mismatch": title_h1},
        "blockers": blockers,
        "review": {"stages": stages, "waiting": waiting, "labels": reviews.STAGES},
        "citations": {"total": len(items), "by_status": st,
                      "title_zh": sum(1 for v in items if v.get("title_zh")),
                      "abstract_zh": sum(1 for v in items if v.get("abstract_zh")),
                      "url_verified": sum(1 for v in items if v.get("url_verified")),
                      "cited": sum(1 for v in items if v.get("cited_by"))},
        "git": {"changed": len(changed), "branch": run(["git", "branch", "--show-current"], 30)["stdout"].strip()},
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
    full = message.rstrip() + "\n\nCo-Authored-By: Claude <noreply@anthropic.com>\n"
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
    gh = gh_exe()
    r = run([gh, "workflow", "run", DEPLOY_WORKFLOW, "--ref", "main"], 120)
    if r["code"] != 0:
        r["error"] = "gh 觸發失敗。沒登入請在終端機跑 gh auth login。" if "auth" in (r["stderr"] + r["stdout"]).lower() else (r["stderr"] or r["stdout"])
    return r


def deploy_status() -> dict:
    gh = gh_exe()
    r = run([gh, "run", "list", "--workflow", DEPLOY_WORKFLOW, "--limit", "1",
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
            "deployed_sha": (last or {}).get("headSha", "")[:7],
            "site": "https://chen-mouchin.github.io/cat-health-tw/"}


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
        return "owner"
    if not ACCESS["token"] or not addr.is_private or addr.is_link_local:
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
        self.who = OWNER_NAME if self.role == "owner" else (name or "小幫手")
        if not self.role:
            self._json({"error": "需要通行碼：請用工作檯啟動時印出的網址開啟"}, 403)
            return False
        return True

    def log_message(self, fmt, *args):  # 安靜一點
        if "/api/" in (str(args[0]) if args else ""):
            sys.stdout.write("%s - %s\n" % (self.address_string(), fmt % args))

    def _json(self, obj, code=200):
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

    def _body(self) -> dict:
        n = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(n) if n else b""
        return json.loads(raw.decode("utf-8")) if raw else {}

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
                return self._json({**overview(), "role": self.role, "who": self.who})
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
                        "title", "title_zh", "authors", "source", "year", "url", "status", "abstract_zh", "notes", "type")},
                        "url_verified": bool(v.get("url_verified")), "cited_by": v.get("cited_by") or []})
                return self._json(items)
            if path == "/api/git":
                st = run(["git", "status", "--porcelain"], 60)
                lg = run(["git", "log", "--oneline", "-15"], 60)
                sb = run(["git", "status", "-sb"], 60)
                return self._json({"status": st["stdout"], "log": lg["stdout"], "branch_line": sb["stdout"].splitlines()[0] if sb["stdout"] else ""})
            return self.send_error(404)
        except Exception as e:  # noqa: BLE001
            return self._json({"error": str(e)}, 500)

    def do_POST(self):
        if self.headers.get("X-Workbench") != "1":
            return self._json({"error": "missing X-Workbench header"}, 403)
        path = urllib.parse.unquote(urllib.parse.urlsplit(self.path).path)
        if not self._gate():
            return
        if path in OWNER_ONLY and self.role != "owner":
            return self._json({"error": "commit、push、部署只能在主機本機操作"}, 403)
        if re.match(r"^/api/articles/[A-Za-z0-9\-]+/quality$", path) and self.role != "owner":
            return self._json({"error": "核准上線、退回與淘汰由網站負責人操作；你可以按「初審通過」或「退回修改」"}, 403)
        try:
            body = self._body()
            m_raw = re.match(r"^/api/articles/([A-Za-z0-9\-]+)/raw$", path)
            if m_raw:
                if "raw" not in body:
                    return self._json({"error": "沒有 raw"}, 400)
                res = save_raw(m_raw.group(1), body["raw"], body.get("base_hash", ""), self.who)
                if res.get("ok") and not res.get("unchanged"):
                    b = build_site()
                    res["build_ok"] = b["ok"]
                return self._json(res, 409 if res.get("conflict") else 200)

            m = re.match(r"^/api/review/([A-Za-z0-9\-]+)/(claim|release|check|stage|comment)$", path)
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
            m = re.match(r"^/api/verify/([A-Za-z0-9][A-Za-z0-9_\-\.]*)$", path)
            if m:
                return self._json(run([PY, "scrapers/literature/verify_citation.py", m.group(1)], 600))
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
        except Exception as e:  # noqa: BLE001
            return self._json({"error": str(e)}, 500)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--lan", action="store_true", help="開給同區網的小幫手審稿（要通行碼；commit／push／部署只限本機）")
    ap.add_argument("--port", type=int, default=8010)
    args = ap.parse_args()
    ACCESS["hosts"] = {f"127.0.0.1:{args.port}", f"localhost:{args.port}"}
    # 本機：http，只綁 127.0.0.1
    srv = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"貓健康站 工作檯 → http://127.0.0.1:{args.port}/   (Ctrl+C 停止)")
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
        lan = ThreadingHTTPServer((ip, args.port), Handler)
        lan.socket = ctx.wrap_socket(lan.socket, server_side=True)
        servers.append(lan)
        ACCESS["token"] = secrets.token_urlsafe(12)
        ACCESS["hosts"].add(f"{ip}:{args.port}")
        print(f" 區網審稿網址（給小幫手，含通行碼，每次啟動都會換）：https://{ip}:{args.port}/?t={ACCESS['token']}")
        print(f" 憑證指紋 SHA-256：{fp}")
        print(" 第一次開會出現「連線不是私人連線」：先在瀏覽器的憑證資訊比對上面的指紋，一樣再按「繼續前往」。")
        print(" 小幫手可以審文章、核對文獻、重建預覽；commit、push、部署只能在這台電腦操作。")
        print(" 只在自己的辦公室網路開；Windows 防火牆只允許「私人網路」。用完 Ctrl+C 關掉。")
    for s in servers[1:]:
        threading.Thread(target=s.serve_forever, daemon=True).start()
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
