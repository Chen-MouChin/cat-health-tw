#!/usr/bin/env python3
"""
獸醫院資料清理（Phase 1D）
========================
- 用地址 regex 補 district 缺失
- 同電話重複偵測（分院 vs 實質重登）
- 各都覆蓋率合理性檢查

輸出：
- data/vets/all_vets.json（覆蓋）
- data/vets/cleanup-report.md（人工審核清單）
"""
from __future__ import annotations
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).parent.parent
VETS = ROOT / "data" / "vets" / "all_vets.json"
REPORT = ROOT / "data" / "vets" / "cleanup-report.md"

# 六都行政區對照（主要）
DISTRICTS = {
    "台北市": ["中正區", "大同區", "中山區", "松山區", "大安區", "萬華區", "信義區", "士林區", "北投區", "內湖區", "南港區", "文山區"],
    "新北市": ["板橋區", "三重區", "中和區", "永和區", "新莊區", "新店區", "土城區", "蘆洲區", "樹林區", "汐止區", "鶯歌區", "三峽區", "淡水區", "瑞芳區", "五股區", "泰山區", "林口區", "深坑區", "石碇區", "坪林區", "三芝區", "石門區", "八里區", "平溪區", "雙溪區", "貢寮區", "金山區", "萬里區", "烏來區"],
    "桃園市": ["桃園區", "中壢區", "平鎮區", "八德區", "楊梅區", "蘆竹區", "大溪區", "龍潭區", "龜山區", "大園區", "觀音區", "新屋區", "復興區"],
    "台中市": ["中區", "東區", "西區", "南區", "北區", "北屯區", "西屯區", "南屯區", "太平區", "大里區", "霧峰區", "烏日區", "豐原區", "后里區", "石岡區", "東勢區", "和平區", "新社區", "潭子區", "大雅區", "神岡區", "大肚區", "沙鹿區", "龍井區", "梧棲區", "清水區", "大甲區", "外埔區", "大安區"],
    "台南市": ["中西區", "東區", "南區", "北區", "安平區", "安南區", "永康區", "歸仁區", "新化區", "左鎮區", "玉井區", "楠西區", "南化區", "仁德區", "關廟區", "龍崎區", "官田區", "麻豆區", "佳里區", "西港區", "七股區", "將軍區", "學甲區", "北門區", "新營區", "後壁區", "白河區", "東山區", "六甲區", "下營區", "柳營區", "鹽水區", "善化區", "大內區", "山上區", "新市區", "安定區"],
    "高雄市": ["新興區", "前金區", "苓雅區", "鹽埕區", "鼓山區", "旗津區", "前鎮區", "三民區", "楠梓區", "小港區", "左營區", "仁武區", "大社區", "岡山區", "路竹區", "阿蓮區", "田寮區", "燕巢區", "橋頭區", "梓官區", "彌陀區", "永安區", "湖內區", "鳳山區", "大寮區", "林園區", "鳥松區", "大樹區", "旗山區", "美濃區", "六龜區", "內門區", "杉林區", "甲仙區", "桃源區", "那瑪夏區", "茂林區", "茄萣區"],
}


def fill_district(vet):
    """從 address 欄位 regex 提取 district"""
    if vet.get("district"):
        return None
    addr = vet.get("address") or ""
    city = vet.get("city") or ""
    candidates = DISTRICTS.get(city, [])
    for d in candidates:
        if d in addr:
            return d
    return None


def normalize_phone(s):
    return re.sub(r"\D", "", str(s or ""))


def is_branch_name(names):
    """判斷同電話的 2 筆是否為分院關係（名字互含或一方含「分院」）"""
    if len(names) != 2:
        return None  # 複雜情況，人工判
    a, b = sorted(names, key=len)
    if a in b:
        return True  # b 是 a 的擴展（如「逗號」vs「逗號南崁分院」）
    if "分院" in b or "分店" in b:
        return True
    return False


def main():
    data = json.loads(VETS.read_text(encoding="utf-8"))
    print(f"[Load] {len(data)} vets")

    # 1. 補 district
    before_no_dist = sum(1 for v in data if not v.get("district"))
    filled = 0
    still_missing = []
    for v in data:
        new_dist = fill_district(v)
        if new_dist:
            v["district"] = new_dist
            filled += 1
        elif not v.get("district"):
            still_missing.append(v)
    print(f"[District] 原本缺 {before_no_dist}，補 {filled}，仍缺 {len(still_missing)}")

    # 2. 同電話偵測
    phone_groups = defaultdict(list)
    for v in data:
        ph = normalize_phone(v.get("tel", ""))
        if ph:
            phone_groups[ph].append(v)
    dupe_groups = {ph: vs for ph, vs in phone_groups.items() if len(vs) > 1}

    auto_branch = 0
    need_human = []
    for ph, vs in dupe_groups.items():
        names = [v.get("name", "") for v in vs]
        verdict = is_branch_name(names)
        if verdict is True:
            # 自動標分院
            for v in vs:
                v["branch_of_phone"] = ph
            auto_branch += 1
        else:
            need_human.append((ph, vs))
    print(f"[Dupes] 同電話組 {len(dupe_groups)} 組，其中 {auto_branch} 組自動標為分院；{len(need_human)} 組需人工審")

    # 3. 覆蓋率
    by_city = Counter(v.get("city", "?") for v in data)
    print(f"[Coverage]")
    for c, n in by_city.most_common():
        status = "✅" if n >= 80 else "⚠️"
        print(f"  {c}: {n} {status}")

    # 存回
    VETS.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[Save] {VETS}")

    # 寫人工審核報告
    lines = [
        "# 獸醫院清理報告",
        "",
        f"## 摘要",
        f"- 總數：{len(data)}",
        f"- district 補完：{filled} / 仍缺 {len(still_missing)}",
        f"- 同電話重複組：{len(dupe_groups)}（自動分院 {auto_branch} / 需人工 {len(need_human)}）",
        "",
        "## 仍缺 district 的清單（可能地址未含區名或特殊格式）",
        "",
    ]
    for v in still_missing[:30]:
        lines.append(f"- **{v.get('name', '?')}** | {v.get('city', '?')} | {v.get('address', '?')[:60]}")
    if len(still_missing) > 30:
        lines.append(f"\n（還有 {len(still_missing) - 30} 筆未列）")

    lines += ["", "## 需人工審核的重複組（同電話但名字無明顯分院關係）", ""]
    for ph, vs in need_human:
        lines.append(f"### 電話 {ph}")
        for v in vs:
            lines.append(f"- {v.get('name', '?')} | {v.get('city', '?')} · {v.get('district', '?')} | {v.get('address', '?')[:50]}")
        lines.append("")

    REPORT.write_text("\n".join(lines), encoding="utf-8")
    print(f"[Report] {REPORT}")


if __name__ == "__main__":
    main()
