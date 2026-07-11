"""能力档位视图（history-only）：从已有实验组装，零新运行。

各框架压到"仅保留可恢复对话历史的最小形态"后的 file-QA 留存：
  - LlamaIndex  末次 Context 快照（latest-only；适配器一行改动可达成）
  - LangGraph   最新 checkpoint 行（推导值：非文档开关，需剪枝支持）
  - OpenAI      原生 SQLiteSession（session 即 history-only）
  - AutoGen     State 通道（真实开关：不挂 event logger）
  - Agno        原生 session db
  - InfiAgent   conversation 通道（事后通道排除；其通道不可开关）
推导值按首重复 10 任务取均值；通道值引用 composition 分解（30 run 均值）。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from statistics import mean

ROOT = Path(__file__).resolve().parent.parent
TASKS = [f"task_{i:02d}" for i in range(10)]


def llamaindex_latest() -> float:
    vals = []
    for t in TASKS:
        home = ROOT / "experiments/pilot_runs/llamaindex" / t / "home"
        ctxs = sorted(home.glob("ctx_q*.json"),
                      key=lambda p: int(p.stem.split("ctx_q")[1]))
        if ctxs:
            vals.append(ctxs[-1].stat().st_size)
    return mean(vals) / 1048576


def langgraph_latest_checkpoint() -> float:
    vals = []
    for t in TASKS:
        db = (ROOT / "experiments/pilot_runs/langgraph" / t /
              "home/langgraph_checkpoints.sqlite")
        if not db.exists():
            continue
        con = sqlite3.connect(f"file:{db}?mode=ro&immutable=1", uri=True)
        row = con.execute(
            "select length(checkpoint)+coalesce(length(metadata),0) "
            "from checkpoints order by rowid desc limit 1").fetchone()
        con.close()
        if row and row[0]:
            vals.append(row[0])
    return mean(vals) / 1048576


COMPOSITION = {  # 30-run 均值（论文 composition 表）
    "OpenAI Agents (native session)": (0.33, "native"),
    "AutoGen (state channel, event log off)": (0.83, "real toggle"),
    "Agno (native session db)": (1.15, "native"),
    "InfiAgent (conversation channel)": (1.20, "post-hoc channel split"),
}


def main() -> None:
    rows = [("LlamaIndex (latest snapshot)", llamaindex_latest(),
             "one-line adapter change"),
            ("LangGraph (newest checkpoint)", langgraph_latest_checkpoint(),
             "derived: pruning not a documented toggle")]
    rows += [(k, v, src) for k, (v, src) in COMPOSITION.items()]
    rows.sort(key=lambda r: r[1])
    print("| configuration (history-only form) | MB | source |")
    print("|---|---|---|")
    for name, mb, src in rows:
        print(f"| {name} | {mb:.2f} | {src} |")
    lo, hi = rows[0][1], rows[-1][1]
    print(f"\nhistory-only spread = {hi:.2f}/{lo:.2f} = {hi/lo:.1f}x "
          f"(defaults: 15.7x; fixed-trace encoding: 6.7x)")


if __name__ == "__main__":
    main()
