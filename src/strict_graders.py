"""规格级严格 grader（round-6 审稿修复）：验证器必须实现论文写明的完整成功标准。

edit 族（ledger_fixed.md）：
  - 每条 DATE: 行均为 ISO YYYY-MM-DD；
  - 日期集合与源 ledger.md（三种乱格式解析后）完全一致，条数不缺不增；
  - 最新日期（答案）在其中。
data 族（summary.csv）：
  - 表头 product,total（容忍大小写/空格）；
  - 全部产品合计与语料重算真值精确一致，无多行无缺行；
  - 按 total 降序。

输出：逐框架 weak（旧口径）vs strict（新口径）对照 + 严格联合成功。
"""

from __future__ import annotations

import csv
import json
import re
import sys
from pathlib import Path
from statistics import mean

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
from analyze_het import FWS, NICE, artifact_ok  # noqa: E402  弱口径复用

MONTHS = {m: i + 1 for i, m in enumerate(
    ["January", "February", "March", "April", "May", "June", "July",
     "August", "September", "October", "November", "December"])}


def parse_messy(s: str):
    s = s.strip()
    m = re.match(r"([A-Z][a-z]+) (\d{1,2}), (\d{4})$", s)
    if m:
        return int(m.group(3)), MONTHS[m.group(1)], int(m.group(2))
    m = re.match(r"(\d{2})/(\d{2})/(\d{4})$", s)
    if m:
        return int(m.group(3)), int(m.group(1)), int(m.group(2))
    m = re.match(r"(\d{4})\.(\d{1,2})\.(\d{1,2})$", s)
    if m:
        return int(m.group(1)), int(m.group(2)), int(m.group(3))
    return None


def edit_truth(task: str) -> set[str]:
    src = (ROOT / "tasks/edit_tasks" / task / "corpus/ledger.md").read_text(encoding="utf-8")
    out = set()
    for ln in src.splitlines():
        if ln.startswith("DATE:"):
            ymd = parse_messy(ln[5:])
            assert ymd, f"unparsed source date: {ln}"
            out.add(f"{ymd[0]}-{ymd[1]:02d}-{ymd[2]:02d}")
    return out


def edit_strict(task: str, fw: str) -> bool:
    art = ROOT / "experiments/edit_tasks_runs" / fw / task / "workspace/ledger_fixed.md"
    if not art.exists():
        return False
    expected = edit_truth(task)
    got, bad = [], 0
    for ln in art.read_text(encoding="utf-8", errors="replace").splitlines():
        if ln.strip().startswith("DATE:"):
            v = ln.split("DATE:", 1)[1].strip()
            if re.fullmatch(r"\d{4}-\d{2}-\d{2}", v):
                got.append(v)
            else:
                bad += 1
    return bad == 0 and len(got) == len(expected) and set(got) == expected


def data_truth(task: str) -> dict[str, int]:
    totals: dict[str, int] = {}
    for fn in ("sales_q1.csv", "sales_q2.csv"):
        with open(ROOT / "tasks/data_tasks" / task / "corpus" / fn) as f:
            for row in csv.DictReader(f):
                totals[row["product"]] = totals.get(row["product"], 0) + int(row["units"])
    return totals


def data_strict(task: str, fw: str) -> bool:
    art = ROOT / "experiments/data_tasks_runs" / fw / task / "workspace/summary.csv"
    if not art.exists():
        return False
    lines = [l.strip() for l in art.read_text(encoding="utf-8", errors="replace")
             .splitlines() if l.strip()]
    if not lines or lines[0].lower().replace(" ", "") != "product,total":
        return False
    rows = []
    for l in lines[1:]:
        parts = [p.strip() for p in l.split(",")]
        if len(parts) != 2 or not parts[1].lstrip("-").isdigit():
            return False
        rows.append((parts[0], int(parts[1])))
    truth = data_truth(task)
    return (dict(rows) == truth and len(rows) == len(truth)
            and rows == sorted(rows, key=lambda r: -r[1]))


def main() -> None:
    for suite, strict_fn, tasks in (
            ("edit_tasks", edit_strict, [f"etask_{i:02d}" for i in range(5)]),
            ("data_tasks", data_strict, [f"dtask_{i:02d}" for i in range(5)])):
        rows = json.loads((ROOT / "experiments" / f"{suite}_runs/summary.json")
                          .read_text(encoding="utf-8"))
        print(f"\n== {suite}: weak -> strict (artifact | joint) ==")
        fulls = {}
        for fw in FWS:
            rs = [r for r in rows if r["framework"] == fw]
            weak = sum(artifact_ok(suite, fw, r["task"])[0] for r in rs)
            strict = sum(strict_fn(r["task"], fw) for r in rs)
            joint = sum(1 for r in rs if strict_fn(r["task"], fw)
                        and r["n_correct"] == r["n_questions"])
            st = mean(r["S_total"] for r in rs) / 1024
            print(f"{NICE[fw]:15s} artifact {weak}/5 -> {strict}/5   "
                  f"strict-joint {joint}/5   S={st:.1f}KB")
            if joint == len(rs):
                fulls[fw] = st
        if fulls:
            ss = list(fulls.values())
            print(f"full strict-joint configs: {len(fulls)} "
                  f"({', '.join(NICE[f] for f in fulls)})  "
                  f"span = {max(ss):.1f}/{min(ss):.1f} = {max(ss)/min(ss):.1f}x")


if __name__ == "__main__":
    main()
