"""工作檯的審稿流程資料：階段、認領、檢查清單、註解、修改紀錄。

每篇一個 JSON，存在 research/reviews/{slug}.json。research/ 不進 git，
所以小幫手的名字與註解不會出現在公開 repo。文章的 quality 仍由 frontmatter 決定，
只有擁有者「核准上線」時才寫回 frontmatter。

階段：
  todo     待審
  claimed  審稿中（有人認領，CLAIM_HOURS 小時沒動作就自動釋出）
  changes  退回修改
  passed   初審通過，等擁有者核准
  approved 已核准上線（frontmatter quality = reviewed / featured）
"""
from __future__ import annotations

import datetime as dt
import difflib
import json
import re
import secrets
import threading
import time
from pathlib import Path

LOCK = threading.RLock()
CLAIM_HOURS = 2

STAGES = {
    "todo": "待審",
    "claimed": "審稿中",
    "changes": "退回修改",
    "passed": "初審通過",
    "approved": "已上線",
}

# 初審要逐項確認的清單；每項都勾了（或標不適用）才能按「初審通過」
CHECKLIST = [
    ("cites", "每個數字都有註腳，且和右欄的文獻摘要對得上"),
    ("tone", "語氣是建議，沒有渲染急迫（立刻、馬上、不要等）"),
    ("brand", "沒有品牌名、價格或購買通路"),
    ("flow", "讀得懂，段落順序合理，前後沒有矛盾"),
    ("links", "站內連結點得開，相關文章選得合理"),
]

SLUG_RE = re.compile(r"^[A-Za-z0-9\-]+$")


def replace_retry(tmp: Path, dest: Path, tries: int = 20) -> None:
    """Windows 上別的程式或執行緒剛好在讀 dest 時 replace 會被拒（WinError 5），稍等再試。"""
    for i in range(tries):
        try:
            tmp.replace(dest)
            return
        except PermissionError:
            if i == tries - 1:
                raise
            time.sleep(0.02 * (i + 1))


def now() -> str:
    return dt.datetime.now().isoformat(timespec="seconds")


class Store:
    def __init__(self, root: Path):
        self.dir = root / "research" / "reviews"

    # -------- 讀寫 --------
    def _path(self, slug: str) -> Path:
        if not SLUG_RE.match(slug):
            raise ValueError("slug 格式不對")
        return self.dir / f"{slug}.json"

    def load(self, slug: str) -> dict:
        p = self._path(slug)
        with LOCK:   # 讀寫用同一把鎖，避免讀到一半被 replace
            rec = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
        rec.setdefault("slug", slug)
        rec.setdefault("stage", "todo")
        rec.setdefault("claimed_by", "")
        rec.setdefault("claimed_at", "")
        rec.setdefault("checklist", {})
        rec.setdefault("comments", [])
        rec.setdefault("log", [])
        return rec

    def save(self, rec: dict) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        p = self._path(rec["slug"])
        tmp = p.with_suffix(".json.tmp")
        with LOCK:
            tmp.write_text(json.dumps(rec, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
            replace_retry(tmp, p)

    def all(self) -> dict[str, dict]:
        out = {}
        if self.dir.exists():
            for p in self.dir.glob("*.json"):
                try:
                    out[p.stem] = self.load(p.stem)
                except (ValueError, json.JSONDecodeError):
                    continue
        return out

    # -------- 狀態 --------
    @staticmethod
    def claim_active(rec: dict) -> bool:
        if rec.get("stage") != "claimed" or not rec.get("claimed_at"):
            return False
        try:
            t = dt.datetime.fromisoformat(rec["claimed_at"])
        except ValueError:
            return False
        return dt.datetime.now() - t < dt.timedelta(hours=CLAIM_HOURS)

    def effective_stage(self, rec: dict, quality: str) -> str:
        """frontmatter 已上線就是 approved；認領過期視為待審（或退回修改，若之前是）。"""
        if quality in ("reviewed", "featured"):
            return "approved"
        st = rec.get("stage", "todo")
        if st == "approved":          # frontmatter 被改回 draft
            return "todo"
        if st == "claimed" and not self.claim_active(rec):
            return rec.get("stage_before_claim") or "todo"
        return st

    def summary(self, rec: dict, quality: str) -> dict:
        st = self.effective_stage(rec, quality)
        open_c = [c for c in rec["comments"] if not c.get("resolved")]
        last = rec["log"][-1] if rec["log"] else None
        return {
            "stage": st,
            "stage_label": STAGES[st],
            "claimed_by": rec["claimed_by"] if st == "claimed" else "",
            "open_comments": len(open_c),
            "comments": len(rec["comments"]),
            "last_activity": last["at"] if last else "",
            "last_by": last["who"] if last else "",
        }

    @staticmethod
    def log(rec: dict, who: str, action: str, detail: str = "", diff: str = "") -> None:
        e = {"at": now(), "who": who, "action": action}
        if detail:
            e["detail"] = detail
        if diff:
            e["diff"] = diff
        rec["log"].append(e)
        rec["log"] = rec["log"][-300:]

    # -------- 動作 --------
    def claim(self, slug: str, who: str, force: bool = False) -> dict:
        with LOCK:
            rec = self.load(slug)
            if self.claim_active(rec) and rec["claimed_by"] != who and not force:
                return {"ok": False, "error": f"{rec['claimed_by']} 正在審這篇", "claimed_by": rec["claimed_by"]}
            if rec["stage"] != "claimed":
                rec["stage_before_claim"] = rec["stage"]
            rec["stage"] = "claimed"
            rec["claimed_by"] = who
            rec["claimed_at"] = now()
            self.log(rec, who, "認領")
            self.save(rec)
            return {"ok": True}

    def touch(self, rec: dict, who: str) -> None:
        """認領中的人有動作就延長認領時間。"""
        if rec.get("stage") == "claimed" and rec.get("claimed_by") == who:
            rec["claimed_at"] = now()

    def release(self, slug: str, who: str) -> dict:
        with LOCK:
            rec = self.load(slug)
            if rec["stage"] == "claimed":
                rec["stage"] = rec.get("stage_before_claim") or "todo"
                rec["claimed_by"] = ""
                self.log(rec, who, "放下")
                self.save(rec)
            return {"ok": True}

    def set_check(self, slug: str, who: str, key: str, value: str) -> dict:
        if key not in dict(CHECKLIST):
            raise ValueError("沒有這個檢查項目")
        if value not in ("", "ok", "na"):
            raise ValueError("檢查結果只能是 ok、na 或空")
        with LOCK:
            rec = self.load(slug)
            if value:
                rec["checklist"][key] = {"value": value, "by": who, "at": now()}
            else:
                rec["checklist"].pop(key, None)
            self.touch(rec, who)
            self.save(rec)
            return {"ok": True}

    def set_stage(self, slug: str, who: str, stage: str, note: str = "") -> dict:
        """審稿者能設的階段：passed（初審通過）、changes（退回修改）。"""
        if stage not in ("passed", "changes", "todo"):
            raise ValueError("階段只能是 passed、changes 或 todo")
        with LOCK:
            rec = self.load(slug)
            if stage == "passed":
                missing = [label for k, label in CHECKLIST if k not in rec["checklist"]]
                if missing:
                    return {"ok": False, "error": "檢查清單還沒勾完", "missing": missing}
                open_c = [c for c in rec["comments"] if not c.get("resolved")]
                if open_c:
                    return {"ok": False, "error": f"還有 {len(open_c)} 則註解沒處理完；處理完或標成已解決，再按初審通過"}
            if stage == "changes" and not note.strip():
                open_c = [c for c in rec["comments"] if not c.get("resolved")]
                if not open_c:
                    return {"ok": False, "error": "退回修改要留一句原因，或先在文章上加註解"}
            rec["stage"] = stage
            rec["claimed_by"] = ""
            rec["stage_by"] = who
            rec["stage_at"] = now()
            if note.strip():
                self._add_comment(rec, who, "", note.strip(), "")
            self.log(rec, who, {"passed": "初審通過", "changes": "退回修改", "todo": "改回待審"}[stage], note.strip())
            self.save(rec)
            return {"ok": True}

    def mark_approved(self, slug: str, who: str, quality: str, direct: bool) -> None:
        with LOCK:
            rec = self.load(slug)
            rec["stage"] = "approved"
            rec["claimed_by"] = ""
            rec["approved_by"] = who
            rec["approved_at"] = now()
            self.log(rec, who, "核准上線" + ("（精選）" if quality == "featured" else ""),
                     "未經初審，直接核准" if direct else "")
            self.save(rec)

    def owner_reject(self, slug: str, who: str, note: str) -> None:
        with LOCK:
            rec = self.load(slug)
            rec["stage"] = "changes"
            rec["claimed_by"] = ""
            if note.strip():
                self._add_comment(rec, who, "", note.strip(), "")
            self.log(rec, who, "退回修改", note.strip())
            self.save(rec)

    def note_event(self, slug: str, who: str, action: str, detail: str = "", diff: str = "") -> None:
        with LOCK:
            rec = self.load(slug)
            self.touch(rec, who)
            self.log(rec, who, action, detail, diff)
            self.save(rec)

    # -------- 註解 --------
    @staticmethod
    def _add_comment(rec: dict, who: str, quote: str, text: str, suggestion: str) -> dict:
        c = {"id": secrets.token_hex(4), "who": who, "at": now(), "quote": quote[:500],
             "text": text[:2000], "suggestion": suggestion[:2000], "resolved": False, "replies": []}
        rec["comments"].append(c)
        return c

    def add_comment(self, slug: str, who: str, quote: str, text: str, suggestion: str) -> dict:
        quote, text, suggestion = (quote or "").strip(), (text or "").strip(), (suggestion or "").strip()
        if not text and not suggestion:
            raise ValueError("註解內容是空的")
        with LOCK:
            rec = self.load(slug)
            c = self._add_comment(rec, who, quote, text, suggestion)
            self.touch(rec, who)
            self.log(rec, who, "建議修改" if suggestion else "加註解", (quote[:40] + "：" if quote else "") + (text or suggestion)[:80])
            self.save(rec)
            return {"ok": True, "comment": c}

    def _find(self, rec: dict, cid: str) -> dict:
        for c in rec["comments"]:
            if c["id"] == cid:
                return c
        raise FileNotFoundError("找不到這則註解")

    def reply(self, slug: str, who: str, cid: str, text: str) -> dict:
        text = (text or "").strip()
        if not text:
            raise ValueError("回覆是空的")
        with LOCK:
            rec = self.load(slug)
            c = self._find(rec, cid)
            c["replies"].append({"who": who, "at": now(), "text": text[:2000]})
            self.touch(rec, who)
            self.log(rec, who, "回覆註解", text[:80])
            self.save(rec)
            return {"ok": True}

    def resolve(self, slug: str, who: str, cid: str, resolved: bool, how: str = "") -> dict:
        with LOCK:
            rec = self.load(slug)
            c = self._find(rec, cid)
            c["resolved"] = bool(resolved)
            c["resolved_by"] = who if resolved else ""
            c["resolved_at"] = now() if resolved else ""
            if how:
                c["resolved_how"] = how
            self.touch(rec, who)
            self.log(rec, who, ("已解決註解" if resolved else "重新打開註解") + (f"（{how}）" if how else ""), (c["quote"] or c["text"])[:60])
            self.save(rec)
            return {"ok": True}

    def delete_comment(self, slug: str, who: str, cid: str, is_owner: bool) -> dict:
        with LOCK:
            rec = self.load(slug)
            c = self._find(rec, cid)
            if c["who"] != who and not is_owner:
                return {"ok": False, "error": "只能刪自己的註解"}
            rec["comments"] = [x for x in rec["comments"] if x["id"] != cid]
            self.log(rec, who, "刪除註解", (c["quote"] or c["text"])[:60])
            self.save(rec)
            return {"ok": True}

    def activity(self, limit: int = 60) -> list[dict]:
        items = []
        for slug, rec in self.all().items():
            for e in rec["log"]:
                items.append({"slug": slug, **{k: v for k, v in e.items() if k != "diff"}, "has_diff": bool(e.get("diff"))})
        items.sort(key=lambda e: e["at"], reverse=True)
        return items[:limit]


def make_diff(before: str, after: str, max_lines: int = 400) -> str:
    lines = list(difflib.unified_diff(before.splitlines(), after.splitlines(), "修改前", "修改後", n=1, lineterm=""))
    if len(lines) > max_lines:
        lines = lines[:max_lines] + [f"…（另有 {len(lines) - max_lines} 行沒列出）"]
    return "\n".join(lines)


def apply_suggestion(raw: str, quote: str, suggestion: str) -> tuple[str | None, str]:
    """把建議套進 Markdown 原文。原文裡剛好出現一次才套，否則回傳原因。"""
    if not quote:
        return None, "這則建議沒有對應的原文片段，請手動修改"
    n = raw.count(quote)
    if n == 1:
        return raw.replace(quote, suggestion), ""
    if n == 0:
        return None, "原文找不到這段字（可能含粗體、註腳或已被改過），請用「編輯內文」手動修改"
    return None, f"這段字在原文出現 {n} 次，無法確定改哪一處，請手動修改"
