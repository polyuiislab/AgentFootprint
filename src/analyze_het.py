"""异质任务族（edit_tasks / data_tasks）逐族统计：acc / S_total / D / echo / artifact 完成率。

artifact 判定：
  edit  族：workspace/ledger_fixed.md 存在且包含答案 ISO 日期
  data  族：workspace/summary.csv   存在且同一行包含 top product 与 total
输出：markdown 表（贴 docs/04 T16）+ LaTeX 行（贴论文附录表）。
"""

from __future__ import annotations

import json
from pathlib import Path
from statistics import mean, pstdev

ROOT = Path(__file__).resolve().parent.parent
FWS = ["langgraph", "autogen", "infiagent", "crewai", "smolagents",
       "openai_agents", "llamaindex", "agno"]
NICE = {"langgraph": "LangGraph", "autogen": "AutoGen", "infiagent": "InfiAgent",
        "crewai": "CrewAI", "smolagents": "SmolAgents",
        "openai_agents": "OpenAI Agents", "llamaindex": "LlamaIndex",
        "agno": "Agno"}


def _content_ok(suite: str, q: dict, art: Path, task: str) -> bool:
    """规格级严格验证（round-6 起）：edit=全部 DATE 行 ISO 且集合与源一致；
    data=表头+全部产品合计精确+降序。弱口径（仅含答案/含 top 行）已废弃。"""
    import strict_graders as sg
    try:
        if suite == "edit_tasks":
            expected = sg.edit_truth(task)
            got, bad = [], 0
            for ln in art.read_text(encoding="utf-8", errors="replace").splitlines():
                if ln.strip().startswith("DATE:"):
                    v = ln.split("DATE:", 1)[1].strip()
                    import re
                    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", v):
                        got.append(v)
                    else:
                        bad += 1
            return bad == 0 and len(got) == len(expected) and set(got) == expected
        truth = sg.data_truth(task)
        lines = [l.strip() for l in art.read_text(encoding="utf-8",
                 errors="replace").splitlines() if l.strip()]
        if not lines or lines[0].lower().replace(" ", "") != "product,total":
            return False
        rows = []
        for l in lines[1:]:
            parts = [x.strip() for x in l.split(",")]
            if len(parts) != 2 or not parts[1].lstrip("-").isdigit():
                return False
            rows.append((parts[0], int(parts[1])))
        return (dict(rows) == truth and len(rows) == len(truth)
                and rows == sorted(rows, key=lambda r: -r[1]))
    except Exception:
        return False


def artifact_ok(suite: str, fw: str, task: str) -> tuple[bool, bool]:
    """返回 (workspace 内合格, home 内合格——写错位置)。"""
    tdir = ROOT / "tasks" / suite / task
    q = json.loads((tdir / "questions.json").read_text(encoding="utf-8"))[0]
    sandbox = ROOT / "experiments" / f"{suite}_runs" / fw / task
    ws_art = sandbox / "workspace" / q["artifact"]
    if ws_art.exists() and _content_ok(suite, q, ws_art, task):
        return True, False
    for cand in (sandbox / "home").rglob(q["artifact"]):
        if _content_ok(suite, q, cand, task):
            return False, True
    return False, False


def fmt_kb(b: float) -> str:
    return f"{b/1024:.0f}" if b >= 10240 else f"{b/1024:.1f}"


def main() -> None:
    for suite in ("edit_tasks", "data_tasks"):
        rows = json.loads((ROOT / "experiments" / f"{suite}_runs" / "summary.json")
                          .read_text(encoding="utf-8"))
        by_fw = {fw: [r for r in rows if r["framework"] == fw] for fw in FWS}
        print(f"\n## {suite}  (n runs = {len(rows)})\n")
        print("| Framework | acc | S_total KB (mean±sd) | D | echo | artifact |")
        print("|---|---|---|---|---|---|")
        latex = []
        for fw in FWS:
            rs = by_fw[fw]
            if not rs:
                continue
            acc = sum(r["n_correct"] for r in rs) / sum(r["n_questions"] for r in rs)
            st = [r["S_total"] for r in rs]
            dv = [r["D"] for r in rs if r["D"] is not None]
            ev = [r["echo_copies"] for r in rs if r["echo_copies"] is not None]
            d = f"{mean(dv):.1f}" if dv else "--"
            echo = f"{mean(ev):.1f}" if ev else "--"
            checks = [artifact_ok(suite, fw, r["task"]) for r in rs]
            arts = sum(ws for ws, _ in checks)
            misplaced = sum(hm for _, hm in checks)
            mis = f" (+{misplaced} in home)" if misplaced else ""
            # 联合成功 = 该 run 答案全对 AND workspace artifact 合格（论文口径）
            joint = sum(1 for r, (ws_ok, _) in zip(rs, checks)
                        if ws_ok and r["n_correct"] == r["n_questions"])
            print(f"| {NICE[fw]} | {acc*100:.0f}% | {fmt_kb(mean(st))}"
                  f"±{fmt_kb(pstdev(st))} | {d} | {echo} | {arts}/{len(rs)}{mis}"
                  f" | joint {joint}/{len(rs)} |")
            latex.append(f"{NICE[fw]} & {acc*100:.0f} & {fmt_kb(mean(st))} & "
                         f"{d} & {echo} & {arts}/{len(rs)}{mis} & "
                         f"{joint}/{len(rs)} \\\\")
        print("\nLaTeX rows:")
        print("\n".join(latex))
        # 失败运行明细（rc!=0 或 acc=0）
        bad = [r for r in rows if r["returncode"] != 0 or r["n_correct"] == 0]
        if bad:
            print("\nfailures/zero-acc:")
            for r in bad:
                print(f"  {r['framework']}/{r['task']} rc={r['returncode']} "
                      f"correct={r['n_correct']}")


if __name__ == "__main__":
    main()
