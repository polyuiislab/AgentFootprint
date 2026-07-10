"""Gate 1 汇总：summary.json -> 每框架均值表 + 判定。"""

from __future__ import annotations

import json
import math
from collections import defaultdict
from itertools import permutations
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SUMMARY = ROOT / "experiments" / "pilot_runs" / "summary.json"
MAIN_FRAMEWORKS = (
    "langgraph", "autogen", "infiagent", "agno", "llamaindex",
    "openai_agents", "crewai", "smolagents",
)


def is_main_run(row: dict) -> bool:
    """Main DeepSeek study only; exclude ablations, variants, and GPT replication."""
    return (row.get("framework") in MAIN_FRAMEWORKS
            and row.get("seed", "s1") in ("s1", "s2", "s3")
            and "gpt-4o-mini" not in row.get("model", ""))


def kendall_tau_b(x: list[float], y: list[float]) -> float:
    """Kendall tau-b with explicit tie correction and no SciPy dependency."""
    concordant = discordant = tie_x = tie_y = 0
    for i in range(len(x)):
        for j in range(i + 1, len(x)):
            dx, dy = x[i] - x[j], y[i] - y[j]
            if dx == 0 and dy == 0:
                continue
            if dx == 0:
                tie_x += 1
            elif dy == 0:
                tie_y += 1
            elif dx * dy > 0:
                concordant += 1
            else:
                discordant += 1
    denom = math.sqrt((concordant + discordant + tie_x) *
                      (concordant + discordant + tie_y))
    return (concordant - discordant) / denom if denom else 0.0


def fmt_mb(n: float) -> str:
    return f"{n / 1024 / 1024:.2f}MB"


def main() -> None:
    all_rows = json.loads(SUMMARY.read_text(encoding="utf-8"))
    rows = [r for r in all_rows if is_main_run(r)]
    by_fw: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_fw[r["framework"]].append(r)

    print(f"{'framework':<14} {'n':>3} {'S_total(avg±sd)':>18} {'D(avg)':>7} "
          f"{'C(avg)':>7} {'echo(avg)':>9} {'acc':>6} {'wall(avg)':>9}")
    stats = {}
    for fw in MAIN_FRAMEWORKS:
        rs = by_fw.get(fw, [])
        if not rs:
            continue
        n = len(rs)
        ss = [r["S_total"] for r in rs]
        s = sum(ss) / n
        sd = (sum((x - s) ** 2 for x in ss) / n) ** 0.5
        d = sum(r["D"] or 0 for r in rs) / n
        c = sum(r["C"] or 0 for r in rs) / n
        e = sum(r["echo_copies"] or 0 for r in rs) / n
        acc = sum(r["n_correct"] for r in rs) / max(1, sum(r["n_questions"] for r in rs))
        w = sum(r["wall_sec"] for r in rs) / n
        stats[fw] = {"S": s, "D": d, "acc": acc}
        print(f"{fw:<14} {n:>3} {fmt_mb(s):>11}±{sd/1048576:>5.2f} {d:>7.2f} {c:>7.1f} "
              f"{e:>9.2f} {acc:>6.1%} {w:>8.0f}s")

    # Tier A: Kendall tau-b handles the many accuracy ties explicitly.
    pers = {fw: v for fw, v in stats.items() if v["S"] > 0}
    if len(pers) >= 4:
        fws = list(pers)
        acc_r = [pers[f]["acc"] for f in fws]
        eff_r = [pers[f]["acc"] / (pers[f]["S"] / 1048576) for f in fws]
        tau = kendall_tau_b(acc_r, eff_r)
        null = [kendall_tau_b(acc_r, list(p)) for p in permutations(eff_r)]
        p_exact = sum(abs(x) >= abs(tau) - 1e-12 for x in null) / len(null)
        print(f"\nTier A Kendall tau-b (accuracy vs accuracy/MB, "
              f"n={len(fws)}): {tau:.2f}, exact permutation p={p_exact:.2f}")

    # Gate 判定只看主结果（排除 -abl 消融行）；差距在有持久化的框架间算，
    # 零足迹框架（smolagents）单独作为极端点报告
    main_stats = stats
    persisting = {fw: v for fw, v in main_stats.items() if v["S"] > 0}
    if len(persisting) >= 2:
        ss = [v["S"] for v in persisting.values()]
        spread = max(ss) / min(ss)
        d_ge2 = [fw for fw, v in main_stats.items() if v["D"] >= 2]
        zero_fw = [fw for fw, v in main_stats.items() if v["S"] == 0]
        if zero_fw:
            print(f"\n零足迹极端点：{zero_fw}（差距对其发散，不计入 spread）")
        print(f"\nGate 1 判定：")
        print(f"  ① 跨框架 S_total 差距 = {spread:.1f}×  ({'PASS' if spread >= 3 else 'MISS'}, 需 ≥3×)")
        print(f"  ② D≥2 的框架 = {d_ge2 or '无'}  ({'PASS' if d_ge2 else 'MISS'})")
        print(f"  ③ harness 全自动 = PASS（本表即产物）")
        n_pass = (spread >= 3) + bool(d_ge2) + 1
        print(f"  => {n_pass}/3 {'→ 继续 Plan A' if n_pass >= 2 else '→ 转 Plan B'}")


if __name__ == "__main__":
    main()
