"""平板（瀏覽器）版審稿：在 Pyodide 裡直接呼叫工作檯的 Handler，不開網路 socket。

瀏覽器那邊（workbench/web/）把 /api/*、/site/* 的請求轉給 handle()，拿回 (狀態碼, 標頭, 內容)。
Handler 的邏輯完全沿用 server.py，平板和 Windows 審稿程式跑的是同一套程式。

用法（Pyodide 內）：
    import web_bridge
    web_bridge.start("/work")                 # 工作資料夾，裝過審稿包之後才有文章
    status, headers, body = web_bridge.handle("GET", "/api/articles", {}, b"")
"""
from __future__ import annotations

import contextlib
import io
import os
import runpy
import sys
from email.message import Message
from pathlib import Path

WB = Path(__file__).resolve().parent
server = None
HOST = "tablet"


def _bytes(x) -> bytes:
    """瀏覽器傳進來的 Uint8Array 是 JsProxy，轉成真正的 bytes。"""
    if x is None:
        return b""
    if hasattr(x, "to_py"):
        x = x.to_py()
    return bytes(x)


def _run_in_process(cmd: list[str], timeout: int = 600) -> dict:
    """瀏覽器裡不能開子行程：build.py、sync_cited_by.py 這類腳本改在同一個 Python 裡跑。"""
    script = next((c for c in cmd if str(c).endswith(".py")), "")
    if not script:
        return {"code": 127, "stdout": "", "stderr": f"平板版不能執行：{' '.join(map(str, cmd))}"}
    root = server.ROOT
    p = Path(script) if Path(script).is_absolute() else root / script
    args = [str(c) for c in cmd[cmd.index(script) + 1:]]
    out, err = io.StringIO(), io.StringIO()
    old_argv, old_cwd, old_path = sys.argv, os.getcwd(), list(sys.path)
    code = 0
    try:
        os.chdir(root)
        sys.argv = [str(p), *args]
        sys.path.insert(0, str(p.parent))
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                runpy.run_path(str(p), run_name="__main__")
            except SystemExit as e:
                code = e.code if isinstance(e.code, int) else (0 if e.code is None else 1)
    except Exception as e:  # 腳本自己出錯，照子行程失敗回報
        err.write(f"{type(e).__name__}: {e}")
        code = 1
    finally:
        sys.argv, sys.path[:] = old_argv, old_path
        os.chdir(old_cwd)
    return {"code": code, "stdout": out.getvalue(), "stderr": err.getvalue()}


def has_pack(work: str) -> bool:
    return (Path(work) / "pack.json").exists()


def install(work: str, zip_bytes: bytes) -> dict:
    """第一次使用：把審稿包（zip）裝進工作資料夾。server.py 載入時要讀工作資料夾裡的 scripts/，所以要先裝。
    之後換審稿包改走 /api/helper/load-pack，和 Windows 版一樣會保留審稿紀錄。"""
    if str(WB) not in sys.path:
        sys.path.insert(0, str(WB))
    import pack
    import reviews
    meta = pack.install_pack(Path(work), _bytes(zip_bytes), lambda local, inc: reviews.merge_record(local, inc, remote=True))
    return {"ok": True, "focus": len(meta.get("focus", [])), "created_at": meta.get("created_at", "")}


def start(work: str) -> None:
    """載入 server.py（小幫手模式），把子行程換成同行程執行。"""
    global server
    os.environ["WB_HELPER_ROOT"] = work
    os.environ.setdefault("WB_DOWNLOADS", str(Path(work) / "_exports"))
    Path(os.environ["WB_DOWNLOADS"]).mkdir(parents=True, exist_ok=True)
    if str(WB) not in sys.path:
        sys.path.insert(0, str(WB))
    import server as srv
    server = srv
    srv.run = _run_in_process
    srv.ACCESS["hosts"] = {HOST}
    srv.ACCESS["token"] = ""


def handle(method: str, path: str, headers: dict, body: bytes) -> tuple[int, list, bytes]:
    body = _bytes(body)
    if hasattr(headers, "to_py"):
        headers = headers.to_py()
    cls = type("WebHandler", (server.Handler,), {"__init__": lambda self: None})
    h = cls()
    h.command, h.path, h.request_version = method, path, "HTTP/1.1"
    h.requestline = f"{method} {path} HTTP/1.1"
    h.close_connection = True
    h.client_address = ("127.0.0.1", 0)
    h.server = None
    h.directory = str(server.ROOT / "frontend")
    msg = Message()
    for k, v in (headers or {}).items():
        msg[k] = v
    msg["Host"] = HOST
    if body:
        msg["Content-Length"] = str(len(body))
    h.headers = msg
    h.rfile = io.BytesIO(body or b"")
    h.wfile = io.BytesIO()
    try:
        (h.do_POST if method == "POST" else h.do_GET)()
    except Exception as e:  # 和 server 一樣回 500，畫面才不會卡住
        return 500, [("Content-Type", "text/plain; charset=utf-8")], f"{type(e).__name__}: {e}".encode()
    raw = h.wfile.getvalue()
    head, _, payload = raw.partition(b"\r\n\r\n")
    lines = head.decode("latin-1").split("\r\n")
    status = int(lines[0].split(" ")[1]) if lines and lines[0].startswith("HTTP/") else 200
    hdrs = []
    for l in lines[1:]:
        if ":" in l:
            k, v = l.split(":", 1)
            hdrs.append((k.strip(), v.strip()))
    return status, hdrs, payload
