"""增长实验重复聚合：每 (fw, T) 的 S_total mean±SD（3 reps）+ 逐 seed α 拟合。

用法: python3 src/aggregate_growth.py
reps: 原始（无后缀）+ s2 + s3；α = log-log 全区间最小二乘斜率。
"""

from __future__ import annotations

import json
import math
import statistics as st
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RUNS = ROOT / "experiments" / "longhorizon_runs"
FWS = ["langgraph", "autogen", "llamaindex"]
TS = [25, 50, 100, 200]
SEEDS = ["", "__s2", "__s3"]


def fit_alpha(pts):
    xs = [math.log(t) for t, _ in pts]
    ys = [math.log(s) for _, s in pts]
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    return (sum((x - mx) * (y - my) for x, y in zip(xs, ys)) /
            sum((x - mx) ** 2 for x in xs))


def main() -> None:
    for fw in FWS:
        print(f"\n=== {fw} ===")
        alphas = []
        per_t = {}
        for seed in SEEDS:
            pts = []
            for t in TS:
                m = RUNS / fw / f"lh_T{t:03d}{seed}" / "measurement.json"
                if not m.exists():
                    continue
                d = json.loads(m.read_text())
                mb = d["S_total"] / 1048576
                pts.append((t, mb))
                per_t.setdefault(t, []).append(mb)
            if len(pts) == len(TS):
                alphas.append(fit_alpha(pts))
        for t in TS:
            v = per_t.get(t, [])
            m = st.mean(v)
            sd = st.stdev(v) if len(v) > 1 else 0.0
            print(f"  T={t:<4d} n={len(v)}  {m:8.1f} ± {sd:5.1f} MB")
        am = st.mean(alphas)
        asd = st.stdev(alphas) if len(alphas) > 1 else 0.0
        print(f"  alpha per-seed: {[f'{a:.2f}' for a in alphas]}"
              f"  ->  {am:.2f} ± {asd:.2f}  (n={len(alphas)} seeds)")


if __name__ == "__main__":
    main()
