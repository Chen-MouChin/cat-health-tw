"""小幫手離線審稿：審稿包、寄回結果、版本快照與逐段合併。

流程：
  負責人「產生審稿包」→ zip（開始審稿.exe ＋ 審稿資料/）→ LINE 或 Email 傳給小幫手
  小幫手在自己電腦審 →「寄回結果」→ 審稿結果-名字-日期.zip → 傳回來
  負責人「匯入審稿結果」→ 文章沒被改過就直接套用；兩邊都改過就逐段選版本

審稿包只放下面 SNAPSHOT 列的檔案，不放 .git、research/ 的其他東西、憑證或 sandbox/。
"""
from __future__ import annotations

import datetime as dt
import difflib
import hashlib
import io
import json
import os
import re
import secrets
import shutil
import zipfile
from pathlib import Path

SLUG_RE = re.compile(r"^[A-Za-z0-9\-]+$")
FM_RE = re.compile(r"^(---\r?\n)(.*?)(\r?\n---\r?\n)(.*)$", re.S)
# 這幾行是審核狀態，不算文章內容：比對版本時不看，套用別人的版本時保留現在的值
STATUS_KEYS = ("quality", "last_reviewed", "review_notes")
STATUS_LINE = re.compile(r"^(quality|last_reviewed|review_notes):")

PACK_KIND = "cat-health-review-pack"
RESULT_KIND = "cat-health-review-result"
DATA_DIR = "審稿資料"
EXE_NAME = "開始審稿.exe"

# 審稿包裡的檔案（相對 repo 根目錄）；目錄會整個帶
SNAPSHOT_FILES = [
    "build.py", "scripts/lint_articles.py", "scripts/sync_cited_by.py",
    "content/references/citations.json", "content/references/glossary.json", "content/references/terms.json",
    "data/breeds/breeds.json", "data/breeds_en.json",
    "data/vets/all_vets.json", "data/vets/taipei_newtaipei_vets.json",
]
SNAPSHOT_GLOBS = ["content/articles/*.md", "build/drafts/articles/*.html"]
SNAPSHOT_DIRS = ["frontend"]
# 小幫手的工作資料夾裡，換新審稿包時要整個換掉的部分（審稿紀錄 research/ 保留）
REPLACED = ["build.py", "scripts", "content", "data", "frontend", "build"]

MANUAL = Path(__file__).resolve().parent / "helper" / "使用手冊.txt"   # 放進審稿包，{owner} 換成負責人的名字


def manual_text(owner: str) -> bytes:
    """給 Windows 記事本開的純文字：UTF-8 加 BOM、CRLF 換行。"""
    return MANUAL.read_text(encoding="utf-8").replace("{owner}", owner).replace("\r\n", "\n").replace("\n", "\r\n").encode("utf-8-sig")


def now() -> str:
    return dt.datetime.now().isoformat(timespec="seconds")


# ---------------------------------------------------------------------------
# 版本
# ---------------------------------------------------------------------------

def norm(text: str) -> str:
    """拿掉 frontmatter 裡的審核狀態行，只留文章內容。"""
    m = FM_RE.match(text)
    if not m:
        return text
    head, fm, sep, body = m.groups()
    keep = [l for l in fm.split("\n") if not STATUS_LINE.match(l)]
    return head + "\n".join(keep) + sep + body


def content_hash(text: str) -> str:
    return hashlib.sha256(norm(text).encode("utf-8")).hexdigest()[:16]


def keep_status(new: str, cur: str) -> str:
    """new 的內容，配上 cur 的審核狀態行。撤銷、還原、套用小幫手的版本都不會改到上線狀態。"""
    mn, mc = FM_RE.match(new), FM_RE.match(cur)
    if not mn or not mc:
        return new
    cur_lines = {STATUS_LINE.match(l).group(1): l for l in mc.group(2).split("\n") if STATUS_LINE.match(l)}
    out, done = [], set()
    for l in mn.group(2).split("\n"):
        m = STATUS_LINE.match(l)
        if not m:
            out.append(l)
        elif m.group(1) in cur_lines and m.group(1) not in done:
            out.append(cur_lines[m.group(1)])
            done.add(m.group(1))
    out += [l for k, l in cur_lines.items() if k not in done]
    return mn.group(1) + "\n".join(out) + mn.group(3) + mn.group(4)


class Versions:
    """文章的版本快照，用內容雜湊當檔名。在 research/reviews/versions/（不進 git）。"""

    def __init__(self, root: Path):
        self.dir = root / "research" / "reviews" / "versions"

    def put(self, slug: str, text: str) -> str:
        if not SLUG_RE.match(slug):
            raise ValueError("slug 格式不對")
        h = content_hash(text)
        p = self.dir / slug / f"{h}.md"
        if not p.exists():
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text, encoding="utf-8")
        return h

    def get(self, slug: str, h: str) -> str | None:
        if not SLUG_RE.match(slug) or not re.match(r"^[0-9a-f]{16}$", h or ""):
            return None
        p = self.dir / slug / f"{h}.md"
        return p.read_text(encoding="utf-8") if p.exists() else None


# ---------------------------------------------------------------------------
# 逐段合併
# ---------------------------------------------------------------------------

def split_cells(text: str) -> list[str]:
    """和工作檯前端的 parseCells 同一套規則：空行分段，frontmatter、``` 程式碼、<!-- --> 裡的空行不切。"""
    lines = text.replace("\r\n", "\n").split("\n")
    cells, i, n = [], 0, len(lines)
    while i < n and not lines[i].strip():
        i += 1
    while i < n:
        start = i
        if not cells and lines[i].strip() == "---":
            i += 1
            while i < n and lines[i].strip() != "---":
                i += 1
            i += 1
        else:
            fence = note = False
            while i < n:
                l = lines[i]
                if not fence and not note and not l.strip():
                    break
                if not note and l.lstrip().startswith("```"):
                    fence = not fence
                elif not fence:
                    if note:
                        if "-->" in l:
                            note = False
                    elif "<!--" in l and "-->" not in l[l.index("<!--"):]:
                        note = True
                i += 1
        cells.append("\n".join(lines[start:min(i, n)]))
        while i < n and not lines[i].strip():
            i += 1
    return cells


def join_cells(cells: list[str]) -> str:
    return "\n\n".join(c for c in cells if c.strip()) + "\n"


def _hunks(base: list[str], side: list[str], who: str) -> list[tuple]:
    """這一邊相對共同祖先改了哪些地方：(祖先起, 祖先迄, 這邊起, 這邊迄, who)。"""
    sm = difflib.SequenceMatcher(None, base, side, autojunk=False)
    return [(i1, i2, j1, j2, who) for op, i1, i2, j1, j2 in sm.get_opcodes() if op != "equal"]


def _touch(a: tuple, b: tuple) -> bool:
    if a[0] < b[1] and b[0] < a[1]:
        return True
    # 插入（祖先範圍是空的）碰到另一邊的修改，也算同一處
    return (a[0] == a[1] or b[0] == b[1]) and a[0] <= b[1] and b[0] <= a[1]


def merge3(base: list[str], mine: list[str], theirs: list[str]) -> list[dict]:
    """三方合併（以段為單位，diff3 的作法）。回傳 [{"t":"same","cells":[...]} | {"t":"conflict","mine":[...],"theirs":[...]}]。
    只有一邊改的地方直接用改過的；兩邊改到同一處而且改得不一樣，才是 conflict。"""
    hunks = sorted(_hunks(base, mine, "mine") + _hunks(base, theirs, "theirs"), key=lambda h: (h[0], h[1]))
    groups: list[list[tuple]] = []
    for h in hunks:
        if groups and any(_touch(h, g) for g in groups[-1]):
            groups[-1].append(h)
        else:
            groups.append([h])
    out: list[dict] = []

    def same(cells):
        if not cells:
            return
        if out and out[-1]["t"] == "same":
            out[-1]["cells"] += cells
        else:
            out.append({"t": "same", "cells": list(cells)})

    def side_text(group, who, cells, lo, hi):
        res, pos = [], lo
        for i1, i2, j1, j2, w in group:
            if w != who:
                continue
            res += base[pos:i1] + cells[j1:j2]
            pos = i2
        return res + base[pos:hi]

    pos = 0
    for g in groups:
        lo, hi = min(h[0] for h in g), max(h[1] for h in g)
        same(base[pos:lo])
        M = side_text(g, "mine", mine, lo, hi)
        T = side_text(g, "theirs", theirs, lo, hi)
        if {h[4] for h in g} == {"theirs"}:
            same(T)
        elif {h[4] for h in g} == {"mine"} or M == T:
            same(M)
        else:
            out.append({"t": "conflict", "mine": M, "theirs": T})
        pos = hi
    same(base[pos:])
    return out


def merged_text(chunks: list[dict], choices: list[str]) -> str:
    cells, k = [], 0
    for ch in chunks:
        if ch["t"] == "same":
            cells += ch["cells"]
            continue
        pick = choices[k] if k < len(choices) else ""
        k += 1
        if pick == "theirs":
            cells += ch["theirs"]
        elif pick == "both":
            cells += ch["mine"] + ch["theirs"]
        elif pick == "mine":
            cells += ch["mine"]
        else:
            raise ValueError(f"第 {k} 處還沒選")
    return join_cells(cells)


def changed_cells(a: str, b: str) -> int:
    """兩個版本有幾段不一樣（給「改了幾處」用）。"""
    sm = difflib.SequenceMatcher(None, split_cells(norm(a)), split_cells(norm(b)), autojunk=False)
    return sum(max(i2 - i1, j2 - j1) for op, i1, i2, j1, j2 in sm.get_opcodes() if op != "equal")


def conflict_view(chunks: list[dict]) -> list[dict]:
    """給畫面用：每處衝突附上它所在的章節。"""
    where, out = "", []
    for ch in chunks:
        if ch["t"] == "same":
            for c in ch["cells"]:
                m = re.match(r"^#{1,4}\s+(.+)", c)
                if m:
                    where = m.group(1).strip()
            continue
        out.append({"where": where or "開頭", "mine": "\n\n".join(ch["mine"]), "theirs": "\n\n".join(ch["theirs"])})
    return out


# ---------------------------------------------------------------------------
# 審稿包（負責人）
# ---------------------------------------------------------------------------

def snapshot_paths(root: Path) -> list[Path]:
    files: list[Path] = []
    for f in SNAPSHOT_FILES:
        if (root / f).is_file():
            files.append(root / f)
    for g in SNAPSHOT_GLOBS:
        files += sorted((root).glob(g))
    for d in SNAPSHOT_DIRS:
        files += sorted(p for p in (root / d).rglob("*") if p.is_file())
    return [p for p in files if p.name != "README.md" or "content" not in p.parts]


def clean_record(rec: dict) -> dict:
    """給小幫手的審稿紀錄：拿掉認領狀態與只對這台電腦有意義的欄位。"""
    rec = json.loads(json.dumps(rec))
    if rec.get("stage") == "claimed":
        rec["stage"] = rec.get("stage_before_claim") or "todo"
    rec["claimed_by"] = ""
    for f in ("claimed_at", "stage_before_claim", "original_hash", "original_at", "incoming"):
        rec.pop(f, None)
    return rec


def downloads_dir() -> Path:
    """Windows 的「下載」資料夾（使用者可能搬過位置）。測試用 WB_DOWNLOADS 指到暫存區。"""
    if os.environ.get("WB_DOWNLOADS"):
        return Path(os.environ["WB_DOWNLOADS"])
    if os.name == "nt":
        try:
            import ctypes
            from ctypes import wintypes
            guid = ctypes.c_byte * 16
            fid = guid(*bytes.fromhex("90e24d373f126545916439c4925e467b"))   # FOLDERID_Downloads
            out = ctypes.c_wchar_p()
            if ctypes.windll.shell32.SHGetKnownFolderPath(ctypes.byref(fid), 0, None, ctypes.byref(out)) == 0:
                p = Path(out.value)
                ctypes.windll.ole32.CoTaskMemFree(out)
                if p.is_dir():
                    return p
        except (OSError, AttributeError, ValueError):
            pass
    p = Path.home() / "Downloads"
    p.mkdir(exist_ok=True)
    return p


def unique_path(folder: Path, stem: str, ext: str = ".zip") -> Path:
    p = folder / f"{stem}{ext}"
    k = 2
    while p.exists():
        p = folder / f"{stem}-{k}{ext}"
        k += 1
    return p


def safe_name(s: str) -> str:
    return re.sub(r'[\\/:*?"<>|\x00-\x1f]', "", s).strip()[:20] or "小幫手"


def make_pack(root: Path, out_dir: Path, *, focus: list[str], slugs: dict[str, Path], records: dict[str, dict],
              versions: Versions, owner: str, exe: Path | None) -> dict:
    """產生審稿包 zip。slugs 是全部文章 {slug: 檔案}；focus 是這次請小幫手先看的。"""
    pack_id = dt.datetime.now().strftime("%Y%m%d-%H%M%S-") + secrets.token_hex(3)
    base = {}
    for slug, p in slugs.items():
        base[slug] = versions.put(slug, p.read_text(encoding="utf-8"))   # 匯入時三方合併要用
    meta = {"kind": PACK_KIND, "version": 1, "id": pack_id, "created_at": now(), "owner": owner,
            "focus": [s for s in focus if s in slugs], "base": base}
    out_dir.mkdir(parents=True, exist_ok=True)
    out = unique_path(out_dir, "貓健康站審稿包-" + dt.date.today().strftime("%m%d"))
    tmp = out.with_suffix(".tmp")
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        if exe:
            z.write(exe, EXE_NAME)
        z.writestr("使用手冊.txt", manual_text(owner))
        z.writestr(f"{DATA_DIR}/pack.json", json.dumps(meta, ensure_ascii=False, indent=1))
        for p in snapshot_paths(root):
            z.write(p, f"{DATA_DIR}/files/" + p.relative_to(root).as_posix())
        for slug, rec in records.items():
            if slug in slugs:
                z.writestr(f"{DATA_DIR}/reviews/{slug}.json", json.dumps(clean_record(rec), ensure_ascii=False, indent=1))
    tmp.replace(out)
    return {"id": pack_id, "file": out, "size": out.stat().st_size, "meta": meta}


# ---------------------------------------------------------------------------
# 讀 zip（兩邊共用）：只收預期的檔名，限制大小
# ---------------------------------------------------------------------------

RESULT_NAMES = re.compile(r"^(manifest\.json|articles/[A-Za-z0-9\-]+\.md|reviews/[A-Za-z0-9\-]+\.json)$")


def read_result(data: bytes) -> tuple[dict, dict[str, str], dict[str, dict]]:
    """解開小幫手寄回的檔案。回傳 (manifest, {slug: 文章原文}, {slug: 審稿紀錄})。"""
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        raise ValueError("這不是審稿結果的檔案（不是 zip）")
    total = 0
    arts, recs, manifest = {}, {}, None
    for info in z.infolist():
        if info.is_dir():
            continue
        if not RESULT_NAMES.match(info.filename):
            raise ValueError(f"檔案裡有不認得的內容：{info.filename}")
        total += info.file_size
        if info.file_size > 3_000_000 or total > 40_000_000:
            raise ValueError("檔案太大，不像審稿結果")
        raw = z.read(info).decode("utf-8")
        if info.filename == "manifest.json":
            manifest = json.loads(raw)
        elif info.filename.startswith("articles/"):
            arts[info.filename[9:-3]] = raw
        else:
            rec = json.loads(raw)
            if isinstance(rec, dict):
                recs[info.filename[8:-5]] = rec
    if not manifest or manifest.get("kind") != RESULT_KIND:
        raise ValueError("這不是審稿結果的檔案。要匯入的是小幫手寄回的「審稿結果-名字-日期.zip」")
    return manifest, arts, recs


def pack_members(z: zipfile.ZipFile) -> tuple[dict, str]:
    """找出審稿包裡的 pack.json，回傳 (meta, 資料夾前綴)。"""
    for name in z.namelist():
        if name.endswith(f"{DATA_DIR}/pack.json") or name == "pack.json":
            meta = json.loads(z.read(name).decode("utf-8"))
            if meta.get("kind") == PACK_KIND:
                return meta, name[: -len("pack.json")]
    raise ValueError("這不是審稿包。要打開的是「貓健康站審稿包-日期.zip」")


# ---------------------------------------------------------------------------
# 小幫手的電腦
# ---------------------------------------------------------------------------

def install_pack(work: Path, src, merge) -> dict:
    """把審稿包放進小幫手的工作資料夾。src 是解壓後的「審稿資料」資料夾，或 zip 的 bytes。
    文章與網站檔案整個換新；審稿紀錄（註解、勾選、判斷）保留，再把審稿包帶來的紀錄併進去。
    merge(local_rec, pack_rec) 由呼叫端提供（reviews.merge_record）。"""
    if isinstance(src, (bytes, bytearray)):
        z = zipfile.ZipFile(io.BytesIO(src))
        meta, prefix = pack_members(z)
        members = {}
        for info in z.infolist():
            if info.is_dir() or not info.filename.startswith(prefix):
                continue
            rel = info.filename[len(prefix):]
            members[rel] = info
        read = lambda rel: z.read(members[rel])  # noqa: E731
        names = list(members)
    else:
        src = Path(src)
        meta = json.loads((src / "pack.json").read_text(encoding="utf-8"))
        if meta.get("kind") != PACK_KIND:
            raise ValueError("這不是審稿包")
        names = [p.relative_to(src).as_posix() for p in src.rglob("*") if p.is_file()]
        read = lambda rel: (src / rel).read_bytes()  # noqa: E731
    for rel in names:
        parts = rel.split("/")
        if ".." in parts or rel.startswith("/") or ":" in rel:
            raise ValueError("審稿包裡有不安全的路徑")
    work.mkdir(parents=True, exist_ok=True)
    stage = work.parent / (work.name + ".new")
    if stage.exists():
        shutil.rmtree(stage)
    stage.mkdir(parents=True)
    for rel in names:
        if rel.startswith("files/"):
            dest = stage / rel[6:]
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(read(rel))
    for name in REPLACED:
        p = work / name
        if p.is_dir():
            shutil.rmtree(p)
        elif p.exists():
            p.unlink()
    for p in stage.iterdir():
        p.replace(work / p.name)
    shutil.rmtree(stage, ignore_errors=True)
    rdir = work / "research" / "reviews"
    rdir.mkdir(parents=True, exist_ok=True)
    merged = 0
    for rel in names:
        m = re.match(r"^reviews/([A-Za-z0-9\-]+)\.json$", rel)
        if not m:
            continue
        p = rdir / f"{m.group(1)}.json"
        local = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {"slug": m.group(1)}
        for f, v in (("stage", "todo"), ("claimed_by", ""), ("checklist", {}), ("comments", []), ("log", [])):
            local.setdefault(f, v)
        merge(local, json.loads(read(rel).decode("utf-8")))
        local.pop("original_hash", None)       # 文章換新了，「初稿」改成這次審稿包的版本
        local.pop("original_at", None)
        p.write_text(json.dumps(local, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        merged += 1
    for p in rdir.glob("*.json"):              # 審稿包沒帶紀錄的文章，也重設初稿
        rec = json.loads(p.read_text(encoding="utf-8"))
        if rec.pop("original_hash", None):
            rec.pop("original_at", None)
            p.write_text(json.dumps(rec, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    meta["installed_at"] = now()
    (work / "pack.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    return meta


def helper_state(work: Path) -> dict:
    p = work / "helper.json"
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_helper_state(work: Path, **kv) -> dict:
    st = {**helper_state(work), **kv}
    (work / "helper.json").write_text(json.dumps(st, ensure_ascii=False, indent=1), encoding="utf-8")
    return st


def make_result(work: Path, records: dict[str, dict], name: str, articles: dict[str, Path]) -> tuple[bytes, dict]:
    """小幫手的「寄回結果」：改過的文章原文＋審稿紀錄。每次都包含到目前為止的全部進度。"""
    meta = json.loads((work / "pack.json").read_text(encoding="utf-8"))
    base = meta.get("base", {})
    since = meta.get("installed_at", "")
    manifest = {"kind": RESULT_KIND, "version": 1, "pack_id": meta.get("id"), "reviewer": name,
                "exported_at": now(), "articles": {}}
    counts = {"passed": 0, "changes": 0, "comments": 0, "edits": 0, "articles": 0}
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for slug, p in articles.items():
            text = p.read_text(encoding="utf-8")
            if base.get(slug) and content_hash(text) != base[slug]:
                z.writestr(f"articles/{slug}.md", text)
                manifest["articles"][slug] = {"base": base[slug], "changed": True}
        for slug, rec in records.items():
            mine = [e for e in rec.get("log", []) if not e.get("remote") and e.get("at", "") >= since]
            if not mine and slug not in manifest["articles"]:
                continue
            z.writestr(f"reviews/{slug}.json", json.dumps(clean_record(rec), ensure_ascii=False, indent=1))
            manifest["articles"].setdefault(slug, {"base": base.get(slug, ""), "changed": False})
            counts["articles"] += 1
            if rec.get("stage") in ("passed", "changes") and any(e["action"] in ("通過", "需修改") for e in mine):
                counts[rec["stage"]] += 1
            counts["comments"] += sum(1 for c in rec.get("comments", []) if c.get("who") == name and c.get("at", "") >= since)
            counts["edits"] += sum(1 for e in mine if e["action"] in ("修改內文", "套用建議"))
        z.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=1))
    return buf.getvalue(), counts
