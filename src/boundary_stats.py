"""Round-5 边界统计（可复现脚本化）：
  1) InfiAgent setup 暂存字节与 total-operational 口径（附录 L）
  2) LlamaIndex latest-only 增长指数（附录 E）
  3) Table 1 SD 分解：任务间 vs 任务内重复（附录 C）
"""

from __future__ import annotations

import json
from pathlib import Path
from statistics import mean, pstdev

import numpy as np

ROOT = Path(__file__).resolve().parent.parent


def staging() -> None:
    runs = sorted((ROOT / "experiments/pilot_runs/infiagent").glob("task_*"))
    stag, stot = [], []
    for sb in runs:
        b = json.loads((sb / "baseline.json").read_text(encoding="utf-8"))
        m = json.loads((sb / "measurement.json").read_text(encoding="utf-8"))
        if m.get("seed", "s1") not in ("s1", "s2", "s3") or "gpt" in m.get("model", ""):
            continue
        stag.append(sum((v if isinstance(v, int) else v["size"])
                        for v in b["home"].values()))
        stot.append(m["S_total"])
    print(f"InfiAgent file-QA n={len(stag)}: staging={mean(stag)/1048576:.2f}MB "
          f"S_total={mean(stot)/1048576:.2f}MB "
          f"total-operational={(mean(stag)+mean(stot))/1048576:.2f}MB")


def latest_only() -> None:
    pts = []
    for sb in sorted((ROOT / "experiments/longhorizon_runs/llamaindex").glob("*")):
        m = json.loads((sb / "measurement.json").read_text(encoding="utf-8"))
        if "gpt" in m.get("model", ""):
            continue
        T = int(m["task"].split("_T")[1])
        ctxs = sorted((sb / "home").glob("ctx_q*.json"),
                      key=lambda p: int(p.stem.split("ctx_q")[1]))
        if ctxs:
            pts.append((T, ctxs[-1].stat().st_size))
    pts.sort()
    a = np.polyfit(np.log([t for t, _ in pts]), np.log([s for _, s in pts]), 1)[0]
    sizes = ", ".join(f"{s/1024:.0f}KB@T{t}" for t, s in pts)
    print(f"LlamaIndex latest-only: {sizes}  alpha={a:.2f} (append-all=1.95)")


def sd_decomposition() -> None:
    rows = json.loads((ROOT / "experiments/pilot_runs/summary.json")
                      .read_text(encoding="utf-8"))
    main = [r for r in rows if r.get("seed", "s1") in ("s1", "s2", "s3")
            and "gpt-4o-mini" not in r.get("model", "")
            and "-" not in r["framework"]]
    for fw in ("langgraph", "autogen", "infiagent", "agno", "llamaindex",
               "openai_agents", "crewai"):
        per: dict = {}
        for r in main:
            if r["framework"] == fw:
                per.setdefault(r["task"], []).append(r["S_total"])
        tmeans = [mean(v) for v in per.values()]
        within = [pstdev(v) for v in per.values() if len(v) > 1]
        print(f"{fw:15s} between-task SD={pstdev(tmeans)/1048576:.2f}MB "
              f"mean within-task SD={mean(within)/1048576:.3f}MB")


if __name__ == "__main__":
    staging()
    latest_only()
    sd_decomposition()
