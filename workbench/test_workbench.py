"""工作檯自動測試：python workbench/test_workbench.py

不碰真的 repo：先把 repo clone 到暫存資料夾（含還沒 commit 的程式改動），
另建一個 bare repo 當假遠端，工作檯就在那份複製上跑，測完整份刪掉。

一、單元：身分判斷、審稿流程規則、建議套用、存檔衝突與 lint 把關
二、API（本機擁有者，http）：註解、套用建議、兩段式審核、核准把關、build 排隊
三、API（區網審稿者，https）：通行碼、權限、Host 檢查、http 連不上
四、git：commit、遠端領先時 rebase、衝突時停下、push、部署（假 gh）
"""
from __future__ import annotations

import concurrent.futures as cf
import http.cookiejar
import importlib.util
import json
import os
import re
import shutil
import socket
import ssl
import stat
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

REAL_ROOT = Path(__file__).resolve().parent.parent
TMP = Path(tempfile.mkdtemp(prefix="wbtest-"))
REPO = TMP / "repo"
REMOTE = TMP / "remote.git"
# 跑工作檯與 build 用的 Python；e2e 從另一個 venv 呼叫時用 WB_PYTHON 指回裝有 cryptography 的那個
PY = os.environ.get("WB_PYTHON") or sys.executable
ENV = dict(os.environ, PYTHONIOENCODING="utf-8", GIT_TERMINAL_PROMPT="0")


def sh(cmd, cwd=None, check=True):
    p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace", env=ENV)
    if check and p.returncode != 0:
        raise RuntimeError(f"{cmd} 失敗：{p.stderr or p.stdout}")
    return p


def free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def setup_repo():
    """clone 一份到暫存區，蓋上工作樹裡還沒 commit 的改動，建假遠端，先 build 一次。"""
    sh(["git", "clone", "--quiet", "--no-hardlinks", str(REAL_ROOT), str(REPO)])
    changed = sh(["git", "ls-files", "-m", "-o", "--exclude-standard"], cwd=REAL_ROOT).stdout.split("\n")
    for rel in filter(None, changed):
        src = REAL_ROOT / rel
        if src.is_file():
            (REPO / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, REPO / rel)
    sh(["git", "add", "-A"], cwd=REPO)
    sh(["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-m", "test snapshot", "--allow-empty"], cwd=REPO)
    sh(["git", "clone", "--quiet", "--bare", str(REPO), str(REMOTE)])
    sh(["git", "remote", "set-url", "origin", str(REMOTE)], cwd=REPO)
    sh(["git", "fetch", "-q"], cwd=REPO)
    sh(["git", "branch", "-q", "--set-upstream-to=origin/main", "main"], cwd=REPO)
    sh(["git", "config", "user.email", "t@t"], cwd=REPO)
    sh(["git", "config", "user.name", "tester"], cwd=REPO)
    sh([PY, "build.py"], cwd=REPO)


def load_module():
    """把暫存複製的 server.py 載進來（ROOT 會指到暫存區）。"""
    real_wb = str(REAL_ROOT / "workbench")
    sys.path[:] = [p for p in sys.path if Path(p).resolve() != Path(real_wb).resolve()]
    sys.path.insert(0, str(REPO / "workbench"))
    for m in ("reviews", "lint_articles"):
        sys.modules.pop(m, None)
    spec = importlib.util.spec_from_file_location("wb_server_tmp", REPO / "workbench" / "server.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class Client:
    """簡單的 HTTP 用戶端：記 cookie、帶 X-Workbench 與 X-Reviewer、4xx 不丟例外。"""

    def __init__(self, base, name="", cafile=None, host=None):
        self.base, self.name, self.host = base, name, host
        self.jar = http.cookiejar.CookieJar()
        handlers = [urllib.request.HTTPCookieProcessor(self.jar)]
        if cafile:
            # 只信任工作檯產生的那張自簽憑證，照常驗證憑證與 IP
            ctx = ssl.create_default_context(cafile=str(cafile))
            handlers.append(urllib.request.HTTPSHandler(context=ctx))
        self.opener = urllib.request.build_opener(*handlers)

    def req(self, method, path, body=None, wb_header=True):
        h = {}
        if self.name:
            h["X-Reviewer"] = urllib.parse.quote(self.name)
        if method == "POST":
            h["Content-Type"] = "application/json"
            if wb_header:
                h["X-Workbench"] = "1"
        if self.host:
            h["Host"] = self.host
        data = json.dumps(body or {}).encode() if method == "POST" else None
        r = urllib.request.Request(self.base + path, data=data, headers=h, method=method)
        try:
            with self.opener.open(r, timeout=120) as resp:
                raw, code = resp.read(), resp.status
        except urllib.error.HTTPError as e:
            raw, code = e.read(), e.code
        try:
            return code, json.loads(raw.decode("utf-8"))
        except ValueError:
            return code, raw.decode("utf-8", "replace")

    def get(self, path):
        return self.req("GET", path)

    def post(self, path, body=None, **kw):
        return self.req("POST", path, body, **kw)


SERVER = {}


def start_server():
    port = free_port()
    p = subprocess.Popen([PY, "-u", str(REPO / "workbench" / "server.py"), "--lan", "--port", str(port)],
                         cwd=REPO, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", env=ENV)
    lines, url = [], ""
    deadline = time.time() + 30
    while time.time() < deadline:
        line = p.stdout.readline()
        if not line:
            break
        lines.append(line)
        m = re.search(r"(https://[0-9.]+:\d+/\?t=[\w-]+)", line)
        if m:
            url = m.group(1)
        if "用完 Ctrl+C" in line or "沒有開" in line:
            break

    # 之後持續讀掉伺服器輸出；不讀的話管線塞滿，伺服器的 print 會卡住所有請求
    def drain():
        for line in p.stdout:
            lines.append(line)
            del lines[:-500]
    threading.Thread(target=drain, daemon=True).start()
    SERVER.update(proc=p, port=port, lan_url=url, log=lines)
    for _ in range(50):
        try:
            socket.create_connection(("127.0.0.1", port), timeout=0.5).close()
            break
        except OSError:
            time.sleep(0.2)


def stop_server():
    p = SERVER.get("proc")
    if p:
        p.terminate()
        try:
            p.wait(timeout=10)
        except subprocess.TimeoutExpired:
            p.kill()


def pick_slug(owner: Client) -> str:
    """挑一篇草稿、lint 沒有 FAIL、有註腳的文章來測。"""
    _, arts = owner.get("/api/articles")
    for a in arts:
        if a["quality"] == "draft" and a["fails"] == 0 and a["footnotes"] > 0:
            return a["slug"]
    raise RuntimeError("找不到可測的草稿")


def article_path(slug: str) -> Path:
    for p in (REPO / "content" / "articles").glob("*.md"):
        if re.search(rf"^slug:\s*{re.escape(slug)}\s*$", p.read_text(encoding="utf-8"), re.M) or p.stem.endswith(slug):
            return p
    raise FileNotFoundError(slug)


# ===========================================================================
# 一、單元
# ===========================================================================

class T1Unit(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.S = load_module()
        cls.R = sys.modules["reviews"]

    def test_client_role(self):
        S = self.S
        S.ACCESS["token"] = "secret-token"
        cases = [
            (("127.0.0.1", "", ""), "owner"),
            (("::1", "", ""), "owner"),
            (("::ffff:127.0.0.1", "", ""), "owner"),
            (("192.168.1.5", "", ""), ""),
            (("192.168.1.5", "", "wrong"), ""),
            (("192.168.1.5", "", "secret-token"), "reviewer"),
            (("10.0.0.8", "wb_token=secret-token", ""), "reviewer"),
            (("172.20.1.1", "wb_token=nope", ""), ""),
            (("8.8.8.8", "", "secret-token"), ""),
            (("169.254.1.1", "", "secret-token"), ""),
            (("not-an-ip", "", "secret-token"), ""),
        ]
        for (ip, cookie, q), want in cases:
            with self.subTest(ip=ip, cookie=cookie, q=q):
                self.assertEqual(S.client_role(ip, cookie, q), want)
        S.ACCESS["token"] = ""
        self.assertEqual(S.client_role("192.168.1.5", "", "secret-token"), "", "沒開 --lan 時區網一律拒絕")

    def test_claim_and_expiry(self):
        st = self.R.Store(TMP / "unit-store")
        self.assertTrue(st.claim("a-b", "小美")["ok"])
        r = st.claim("a-b", "阿明")
        self.assertFalse(r["ok"])
        self.assertIn("小美", r["error"])
        rec = st.load("a-b")
        rec["claimed_at"] = "2000-01-01T00:00:00"
        st.save(rec)
        self.assertEqual(st.summary(st.load("a-b"), "draft")["stage"], "todo", "認領過期要回到待審")
        self.assertTrue(st.claim("a-b", "阿明")["ok"])

    def test_stage_rules(self):
        st = self.R.Store(TMP / "unit-store")
        r = st.set_stage("c-d", "小美", "passed")
        self.assertFalse(r["ok"])
        self.assertTrue(r["missing"], "清單沒勾不能初審通過")
        for k, _ in self.R.CHECKLIST:
            st.set_check("c-d", "小美", k, "ok")
        c = st.add_comment("c-d", "小美", "某句", "這裡怪", "")["comment"]
        self.assertIn("註解", st.set_stage("c-d", "小美", "passed")["error"], "有未解決註解不能初審通過")
        st.resolve("c-d", "小美", c["id"], True)
        self.assertTrue(st.set_stage("c-d", "小美", "passed")["ok"])
        self.assertEqual(st.load("c-d")["stage"], "passed")
        self.assertFalse(st.set_stage("e-f", "小美", "changes")["ok"], "退回修改要有原因或註解")
        self.assertTrue(st.set_stage("e-f", "小美", "changes", "數字對不上")["ok"])
        with self.assertRaises(ValueError):
            st.set_stage("e-f", "小美", "approved")
        with self.assertRaises(ValueError):
            st.load("../etc")

    def test_comment_permissions(self):
        st = self.R.Store(TMP / "unit-store")
        c = st.add_comment("g-h", "小美", "", "整篇太長", "")["comment"]
        self.assertFalse(st.delete_comment("g-h", "阿明", c["id"], is_owner=False)["ok"])
        self.assertTrue(st.delete_comment("g-h", "老闆", c["id"], is_owner=True)["ok"])
        with self.assertRaises(ValueError):
            st.add_comment("g-h", "小美", "x", "", "")

    def test_apply_suggestion(self):
        f = self.R.apply_suggestion
        self.assertEqual(f("甲乙丙", "乙", "丁"), ("甲丁丙", ""))
        self.assertIsNone(f("甲乙乙", "乙", "丁")[0])
        self.assertIsNone(f("甲乙丙", "戊", "丁")[0])
        self.assertIsNone(f("甲乙丙", "", "丁")[0])

    def test_save_raw_conflict_and_lint_gate(self):
        S = self.S
        p = next(q for q in (REPO / "content" / "articles").glob("*.md"))
        slug = (S.parse_fm(p.read_text(encoding="utf-8"))[0].get("slug") or p.stem)
        orig = p.read_text(encoding="utf-8")
        h = S.text_hash(orig)
        bad = orig + "\n\n我們不是獸醫，不假裝是。\n"
        r = S.save_raw(slug, bad, h, "測試")
        self.assertFalse(r["ok"])
        self.assertEqual(p.read_text(encoding="utf-8"), orig, "lint FAIL 時原檔不能被改")
        r = S.save_raw(slug, orig + "\n", "0" * 16, "測試")
        self.assertTrue(r.get("conflict"), "版本不符要回 conflict")
        self.assertEqual(p.read_text(encoding="utf-8"), orig)


# ===========================================================================
# 二、API：本機擁有者
# ===========================================================================

class T2OwnerAPI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.o = Client(f"http://127.0.0.1:{SERVER['port']}")
        cls.slug = pick_slug(cls.o)

    def test_01_overview_and_detail(self):
        code, ov = self.o.get("/api/overview")
        self.assertEqual(code, 200)
        self.assertEqual(ov["role"], "owner")
        self.assertEqual(ov["who"], "Chen-MouChin")
        code, d = self.o.get(f"/api/articles/{self.slug}")
        self.assertEqual(code, 200)
        for k in ("review", "gate", "raw_hash", "checklist_def"):
            self.assertIn(k, d)

    def test_02_post_needs_header(self):
        code, _ = self.o.post("/api/build", wb_header=False)
        self.assertEqual(code, 403)

    def test_03_comment_reply_resolve(self):
        code, r = self.o.post(f"/api/review/{self.slug}/comment", {"quote": "", "text": "整篇註解"})
        self.assertTrue(r["ok"])
        cid = r["comment"]["id"]
        self.assertTrue(self.o.post(f"/api/review/{self.slug}/comment/{cid}/reply", {"text": "收到"})[1]["ok"])
        self.assertTrue(self.o.post(f"/api/review/{self.slug}/comment/{cid}/resolve", {"resolved": True})[1]["ok"])
        _, d = self.o.get(f"/api/articles/{self.slug}")
        c = next(x for x in d["review"]["comments"] if x["id"] == cid)
        self.assertTrue(c["resolved"])
        self.assertEqual(c["replies"][0]["text"], "收到")

    def test_04_apply_suggestion(self):
        p = article_path(self.slug)
        body = p.read_text(encoding="utf-8").split("---", 2)[2]
        # 找一個在原文只出現一次、不含 Markdown 記號的片段
        quote = next(s for s in re.findall(r"[一-鿿，]{8,20}", body) if body.count(s) == 1 and p.read_text(encoding="utf-8").count(s) == 1)
        _, r = self.o.post(f"/api/review/{self.slug}/comment", {"quote": quote, "text": "改一下", "suggestion": quote + "（已改）"})
        cid = r["comment"]["id"]
        code, r = self.o.post(f"/api/review/{self.slug}/comment/{cid}/apply")
        self.assertTrue(r["ok"], r)
        self.assertIn(quote + "（已改）", p.read_text(encoding="utf-8"))
        _, d = self.o.get(f"/api/articles/{self.slug}")
        self.assertTrue(any(e["action"] == "套用建議" and e.get("diff") for e in d["review"]["log"]), "套用要記進修改紀錄並附 diff")

    def test_05_edit_conflict(self):
        _, a = self.o.get(f"/api/articles/{self.slug}/raw")
        base = a["raw_hash"]
        code, r1 = self.o.post(f"/api/articles/{self.slug}/raw", {"raw": a["raw"] + "\n", "base_hash": base})
        self.assertTrue(r1["ok"], r1)
        code, r2 = self.o.post(f"/api/articles/{self.slug}/raw", {"raw": a["raw"] + "\n\n", "base_hash": base})
        self.assertEqual(code, 409, "第二個人用舊版本存檔要被擋")
        self.assertTrue(r2["conflict"])

    def test_06_two_stage_and_gate(self):
        s = self.slug
        for k, _ in [("cites", 0), ("tone", 0), ("brand", 0), ("flow", 0), ("links", 0)]:
            self.o.post(f"/api/review/{s}/check", {"key": k, "value": "ok"})
        _, d = self.o.get(f"/api/articles/{s}")
        for c in d["review"]["comments"]:
            if not c["resolved"]:
                self.o.post(f"/api/review/{s}/comment/{c['id']}/resolve", {"resolved": True})
        _, r = self.o.post(f"/api/review/{s}/stage", {"stage": "passed"})
        self.assertTrue(r["ok"], r)
        _, ov = self.o.get("/api/overview")
        self.assertIn(s, [w["slug"] for w in ov["review"]["waiting"]], "初審通過要出現在等你核准")
        _, d = self.o.get(f"/api/articles/{s}")
        _, r = self.o.post(f"/api/articles/{s}/quality", {"quality": "reviewed"})
        if d["gate"]["unapproved_cites"]:
            self.assertFalse(r["ok"])
            self.assertTrue(r["need_confirm"], "引用文獻未核准要先確認")
            _, r = self.o.post(f"/api/articles/{s}/quality", {"quality": "reviewed", "confirm_unapproved": True})
        self.assertTrue(r["ok"], r)
        self.assertTrue(r["build_ok"])
        text = article_path(s).read_text(encoding="utf-8")
        self.assertRegex(text, r"(?m)^quality: reviewed$")
        self.assertNotRegex(text, r"(?m)^review_notes:", "審稿備註不寫進 frontmatter")
        self.assertTrue((REPO / "frontend" / "articles" / f"{s}.html").exists(), "核准後要產出上線頁")
        _, d = self.o.get(f"/api/articles/{s}")
        self.assertEqual(d["review"]["stage"], "approved")
        # 下架
        _, r = self.o.post(f"/api/articles/{s}/quality", {"quality": "draft", "note": "測試下架"})
        self.assertTrue(r["ok"])
        self.assertFalse((REPO / "frontend" / "articles" / f"{s}.html").exists(), "下架後上線頁要消失")

    def test_07_gate_blocks_fail(self):
        _, arts = self.o.get("/api/articles")
        other = next(a["slug"] for a in arts if a["quality"] == "draft" and a["slug"] != self.slug)
        p = article_path(other)
        orig = p.read_text(encoding="utf-8")
        p.write_text(orig + "\n\n我們不是獸醫。\n", encoding="utf-8")
        try:
            _, r = self.o.post(f"/api/articles/{other}/quality", {"quality": "reviewed", "confirm_unapproved": True})
            self.assertFalse(r["ok"])
            self.assertIn("FAIL", r["error"])
        finally:
            p.write_text(orig, encoding="utf-8")

    def test_08_build_queue(self):
        with cf.ThreadPoolExecutor(3) as ex:
            res = list(ex.map(lambda _: self.o.post("/api/build")[1], range(3)))
        self.assertTrue(all(r["ok"] for r in res), [r.get("error") for r in res])

    def test_10_concurrent_reads_and_writes(self):
        """兩個人同時用：讀清單、讀文章、加註解、勾清單交錯，不能有錯誤，也不能少存或多存。"""
        _, arts = self.o.get("/api/articles")
        s = next(a["slug"] for a in arts if a["quality"] == "draft" and a["slug"] != self.slug)
        _, d = self.o.get(f"/api/articles/{s}")
        before = len(d["review"]["comments"])
        jobs = []
        for i in range(30):
            jobs += [("GET", "/api/overview", None), ("GET", "/api/articles", None), ("GET", f"/api/articles/{s}", None),
                     ("POST", f"/api/review/{s}/comment", {"text": f"併發 {i}"}),
                     ("POST", f"/api/review/{s}/check", {"key": "tone", "value": "ok" if i % 2 else ""})]
        with cf.ThreadPoolExecutor(12) as ex:
            res = list(ex.map(lambda j: self.o.req(*j), jobs))
        bad = [(c, b) for c, b in res if c != 200]
        self.assertFalse(bad, bad[:3])
        _, d = self.o.get(f"/api/articles/{s}")
        self.assertEqual(len(d["review"]["comments"]) - before, 30)

    def test_09_activity(self):
        code, act = self.o.get("/api/activity")
        self.assertEqual(code, 200)
        self.assertTrue(act and "diff" not in act[0], "動態列表不帶 diff 本文")


# ===========================================================================
# 三、API：區網審稿者
# ===========================================================================

class T3ReviewerAPI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not SERVER.get("lan_url"):
            raise unittest.SkipTest("找不到區網 IP，略過區網測試")
        u = urllib.parse.urlsplit(SERVER["lan_url"])
        cls.base = f"https://{u.netloc}"
        cls.token = urllib.parse.parse_qs(u.query)["t"][0]
        cls.ip = u.hostname
        cls.ca = REPO / "build" / "workbench-cert" / "cert.pem"
        cls.r = Client(cls.base, name="小美", cafile=cls.ca)
        cls.o = Client(f"http://127.0.0.1:{SERVER['port']}")

    def test_01_no_token(self):
        c = Client(self.base, cafile=self.ca)
        self.assertEqual(c.get("/api/articles")[0], 403)
        self.assertEqual(c.get("/?t=wrong")[0], 403)

    def test_02_token_to_cookie(self):
        code, _ = self.r.get(f"/?t={self.token}")
        self.assertEqual(code, 200)   # 303 之後跟到 /
        cookie = next(c for c in self.r.jar if c.name == "wb_token")
        self.assertTrue(cookie.secure, "通行碼 cookie 要有 Secure")
        _, ov = self.r.get("/api/overview")
        self.assertEqual(ov["role"], "reviewer")
        self.assertEqual(ov["who"], "小美")

    def test_03_reviewer_permissions(self):
        self.r.get(f"/?t={self.token}")
        slug = pick_slug(self.o)
        for path in ("/api/git/commit", "/api/git/push", "/api/deploy", f"/api/articles/{slug}/quality"):
            with self.subTest(path=path):
                self.assertEqual(self.r.post(path, {"quality": "reviewed", "message": "x"})[0], 403)
        _, cites = self.o.get("/api/citations")
        key = next(c["key"] for c in cites if c["status"] != "approved")
        self.assertEqual(self.r.post(f"/api/citations/{key}", {"status": "approved", "url_verified": True})[0], 403)
        # 可以做的事
        _, res = self.r.post(f"/api/review/{slug}/comment", {"text": "小美的註解"})
        self.assertTrue(res["ok"])
        self.assertEqual(res["comment"]["who"], "小美")
        self.assertTrue(self.r.post(f"/api/review/{slug}/claim")[1]["ok"])
        _, res = self.o.post(f"/api/review/{slug}/claim")
        self.assertFalse(res["ok"], "別人認領中，擁有者不加 force 也要被提醒")
        self.assertTrue(self.o.post(f"/api/review/{slug}/claim", {"force": True})[1]["ok"])
        self.assertEqual(self.r.post("/api/lint")[0], 200)

    def test_04_bad_host(self):
        c = Client(f"http://127.0.0.1:{SERVER['port']}", host="evil.example")
        self.assertEqual(c.get("/api/overview")[0], 403)

    def test_05_plain_http_to_lan_fails(self):
        with self.assertRaises(Exception):
            urllib.request.urlopen(f"http://{self.ip}:{SERVER['port']}/api/overview", timeout=5).read()

    def test_06_lan_not_on_wildcard(self):
        out = sh(["netstat", "-ano"]).stdout if os.name == "nt" else ""
        if out:
            self.assertNotIn(f"0.0.0.0:{SERVER['port']} ", out, "不能綁 0.0.0.0")


# ===========================================================================
# 四、git 與部署
# ===========================================================================

class T4Git(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        stop_server()   # 避免和伺服器同時寫檔
        cls.S = load_module()
        sh(["git", "add", "-A"], cwd=REPO)
        sh(["git", "commit", "-q", "-m", "before git tests", "--allow-empty"], cwd=REPO)
        sh(["git", "push", "-q", "origin", "main"], cwd=REPO)
        cls.other = TMP / "other"
        sh(["git", "clone", "-q", str(REMOTE), str(cls.other)])
        sh(["git", "config", "user.email", "o@o"], cwd=cls.other)
        sh(["git", "config", "user.name", "other"], cwd=cls.other)

    def _other_push(self, rel, text):
        (self.other / rel).write_text(text, encoding="utf-8")
        sh(["git", "add", "-A"], cwd=self.other)
        sh(["git", "commit", "-q", "-m", f"other {rel}"], cwd=self.other)
        sh(["git", "pull", "-q", "--rebase"], cwd=self.other)
        sh(["git", "push", "-q"], cwd=self.other)

    def test_1_commit_and_push(self):
        (REPO / "wbtest-a.txt").write_text("a\n", encoding="utf-8")
        r = self.S.git_commit("test: a")
        self.assertTrue(r["ok"], r)
        self.assertIn("Co-Authored-By: Claude", sh(["git", "log", "-1", "--format=%B"], cwd=REPO).stdout)
        self.assertEqual(self.S.run(["git", "push"])["code"], 0)

    def test_2_rebase_when_behind(self):
        self._other_push("wbtest-b.txt", "b\n")
        (REPO / "wbtest-c.txt").write_text("c\n", encoding="utf-8")
        r = self.S.git_commit("test: c")
        self.assertTrue(r["ok"], r)
        self.assertTrue((REPO / "wbtest-b.txt").exists(), "落後時要 rebase 到遠端")

    def test_3_conflict_stops(self):
        sh(["git", "pull", "-q", "--rebase"], cwd=self.other)
        self._other_push("wbtest-a.txt", "remote\n")
        (REPO / "wbtest-a.txt").write_text("local\n", encoding="utf-8")
        r = self.S.git_commit("test: conflict")
        self.assertFalse(r["ok"])
        self.assertIn("衝突", r["error"])
        self.assertFalse((REPO / ".git" / "rebase-merge").exists() or (REPO / ".git" / "rebase-apply").exists(), "衝突後要中止 rebase，不留半套狀態")
        self.assertEqual((REPO / "wbtest-a.txt").read_text(encoding="utf-8"), "local\n", "本機的修改不能不見")

    def test_4_deploy_with_fake_gh(self):
        calls = []
        S = self.S
        orig_gh, orig_run = S.gh_exe, S.run
        S.gh_exe = lambda: "fake-gh"
        S.run = lambda cmd, timeout=600: calls.append(cmd) or {"code": 0, "stdout": "ok", "stderr": ""}
        try:
            r = S.deploy()
        finally:
            S.gh_exe, S.run = orig_gh, orig_run
        self.assertEqual(r["code"], 0)
        self.assertEqual(calls[0][:3], ["fake-gh", "workflow", "run"])
        self.assertIn("--ref", calls[0])


def rm_tree(path: Path):
    def onerr(func, p, _):
        os.chmod(p, stat.S_IWRITE)
        func(p)
    shutil.rmtree(path, onerror=onerr)


def main() -> int:
    print(f"暫存區：{TMP}")
    t0 = time.time()
    try:
        setup_repo()
        start_server()
        if not SERVER.get("lan_url"):
            print("（找不到區網 IP，區網測試會略過）")
        suite = unittest.TestSuite()
        loader = unittest.TestLoader()
        for cls in (T1Unit, T2OwnerAPI, T3ReviewerAPI, T4Git):
            suite.addTests(loader.loadTestsFromTestCase(cls))
        res = unittest.TextTestRunner(verbosity=2).run(suite)
    finally:
        stop_server()
        try:
            rm_tree(TMP)
        except OSError as e:
            print(f"暫存區沒刪乾淨：{e}")
    n = res.testsRun
    bad = len(res.failures) + len(res.errors)
    print(f"\n工作檯測試：{n - bad - len(res.skipped)} 通過 / {bad} 失敗 / {len(res.skipped)} 略過，{time.time() - t0:.0f} 秒")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
