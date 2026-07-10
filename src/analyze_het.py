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


def _content_ok(suite: str, q: dict, art: Path) -> bool:
    try:
        text = art.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return False
    if suite == "edit_tasks":
        return q["answer"] in text
    # data: summary.csv 某一行同时含 product 与 total（容忍逗号/空格分隔）
    prod, tot = q["answer"].split()
    return any(prod in ln and tot in ln for ln in text.splitlines())


def artifact_ok(suite: str, fw: str, task: str) -> tuple[bool, bool]:
    """返回 (workspace 内合格, home 内合格——写错位置)。"""
    tdir = ROOT / "tasks" / suite / task
    q = json.loads((tdir / "questions.json").read_text(encoding="utf-8"))[0]
    sandbox = ROOT / "experiments" / f"{suite}_runs" / fw / task
    ws_art = sandbox / "workspace" / q["artifact"]
    if ws_art.exists() and _content_ok(suite, q, ws_art):
        return True, False
    for cand in (sandbox / "home").rglob(q["artifact"]):
        if _content_ok(suite, q, cand):
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
