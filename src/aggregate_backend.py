"""聚合第二/第三后端复制结果 -> 论文表格行。

用法: python3 src/aggregate_backend.py 27b [7b ...]
按 (framework) 聚合 task_*__<label>[123] 的 measurement.json：
S_total mean±SD(MB)、D、echo、C、accuracy、n_runs；同时打印
与 DeepSeek 主表的 S_total 比值与 Spearman 排序一致性。
"""

from __future__ import annotations

import glob
import json
import statistics as st
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FWS = ["langgraph", "autogen", "infiagent", "agno", "llamaindex",
       "openai_agents", "crewai", "smolagents"]
MAIN = {  # DeepSeek 主表 S_total (MB)，排序一致性参照
    "langgraph": 5.10, "autogen": 2.49, "infiagent": 2.12, "agno": 1.15,
    "llamaindex": 0.93, "openai_agents": 0.33, "crewai": 0.32,
    "smolagents": 0.0,
}


def agg(label: str) -> None:
    print(f"\n=== backend[{label}] ===")
    print(f"{'framework':<14}{'n':>3} {'S_total MB':>16} {'D':>6} "
          f"{'echo':>6} {'C':>6} {'acc':>7}  vs-main")
    order_main, order_bk = [], []
    for fw in FWS:
        ms = sorted(glob.glob(
            str(ROOT / f"experiments/pilot_runs/{fw}/task_*__{label}[123]"
                       "/measurement.json")))
        if not ms:
            print(f"{fw:<14}  0  (N/A)")
            continue
        rows = [json.load(open(m)) for m in ms]
        S = [r["S_total"] / 1048576 for r in rows]
        D = [r["D"] for r in rows if r["D"] is not None]
        E = [r["echo_copies"] for r in rows if r["echo_copies"] is not None]
        C = [r["C"] for r in rows if r["C"] is not None]
        acc = sum(r["n_correct"] for r in rows) / sum(r["n_questions"]
                                                      for r in rows)
        mS = st.mean(S)
        sd = st.stdev(S) if len(S) > 1 else 0.0
        ratio = f"{mS / MAIN[fw]:.2f}x" if MAIN[fw] else "--"
        print(f"{fw:<14}{len(rows):>3} {mS:>8.2f}±{sd:<6.2f} "
              f"{st.mean(D) if D else 0:>6.1f} {st.mean(E) if E else 0:>6.1f} "
              f"{st.mean(C) if C else 0:>6.0f} {acc:>6.1%}  {ratio}")
        if MAIN[fw] > 0:
            order_main.append(MAIN[fw])
            order_bk.append(mS)
    # Spearman via rank correlation（手算，避免依赖 scipy）
    def ranks(v):
        s = sorted(range(len(v)), key=lambda i: v[i])
        r = [0] * len(v)
        for k, i in enumerate(s):
            r[i] = k
        return r
    ra, rb = ranks(order_main), ranks(order_bk)
    n = len(ra)
    rho = 1 - 6 * sum((a - b) ** 2 for a, b in zip(ra, rb)) / (n * (n * n - 1))
    print(f"S_total 排序一致性 vs DeepSeek 主表 (persisting {n} fw): "
          f"Spearman rho = {rho:.3f}")
    spread = max(order_bk) / min(order_bk)
    print(f"等后端 spread (persisting): {spread:.1f}x")


if __name__ == "__main__":
    for lb in (sys.argv[1:] or ["27b"]):
        agg(lb)
