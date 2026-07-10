"""四张主图（AAAI/KDD 版式，pdf+png）。

固定实体→颜色/标记映射（全文一致，CVD 校验通过的 5 色 + 形状二次编码）：
  langgraph #0072B2 o | autogen #E69F00 s | infiagent #009E73 ^ |
  crewai #D55E00 D | smolagents #CC79A7 v

fig1 构成堆叠条  fig2 log-log 增长+α  fig3 Pareto(acc vs S_total)+CAS 箭头
fig4 Tier B 洗牌散点（实例归一化系统）
"""

from __future__ import annotations

import json
import math
from collections import defaultdict
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
FIGS = ROOT / "experiments" / "figures"
FIGS.mkdir(parents=True, exist_ok=True)

FW = ["langgraph", "autogen", "infiagent", "crewai", "smolagents",
      "openai_agents", "llamaindex", "agno"]
COLOR = {"langgraph": "#0072B2", "autogen": "#E69F00", "infiagent": "#009E73",
         "crewai": "#D55E00", "smolagents": "#CC79A7",
         "openai_agents": "#56B4E9", "llamaindex": "#7570B3", "agno": "#A0522D"}
MARKER = {"langgraph": "o", "autogen": "s", "infiagent": "^",
          "crewai": "D", "smolagents": "v",
          "openai_agents": "P", "llamaindex": "X", "agno": "*"}


def is_main_row(row: dict) -> bool:
    """Select only the main DeepSeek repetitions, not ablations/variants/GPT."""
    return (row.get("framework") in FW
            and row.get("seed") != "m2"
            and "gpt-4o-mini" not in row.get("model", ""))

plt.rcParams.update({
    "font.size": 9, "axes.titlesize": 10, "axes.labelsize": 9,
    "axes.spines.top": False, "axes.spines.right": False,
    "grid.color": "#e6e6e6", "grid.linewidth": 0.6,
    "figure.dpi": 120, "savefig.dpi": 300,
})


def load(path: str):
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def savefig(fig, name: str) -> None:
    for ext in ("pdf", "png"):
        fig.savefig(FIGS / f"{name}.{ext}", bbox_inches="tight")
    plt.close(fig)
    print(f"  {name}.pdf/.png")


# ---------- fig1 构成 ----------

def classify(path: str) -> str:
    p = path.lower()
    if any(k in p for k in ("llm_debug", "raw_io", "events.log", "/debug/")):
        return "Debug / event logs"
    if any(k in p for k in ("checkpoint", "agent_state", "sqlite", ".db", "ctx_q")):
        return "State / checkpoints"
    if any(k in p for k in ("actions", "share_context", "stack", "conversation")):
        return "Conversation / actions"
    return "Other"


CATS = ["State / checkpoints", "Debug / event logs",
        "Conversation / actions", "Other"]
CAT_COLOR = {"State / checkpoints": "#33526e", "Debug / event logs": "#5b7d9e",
             "Conversation / actions": "#8fabc4", "Other": "#c6d4e1"}


def fig1() -> None:
    rows = [r for r in load("experiments/pilot_runs/summary.json")
            if is_main_row(r)]
    agg: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    n_runs: dict[str, int] = defaultdict(int)   # 按运行数平均（含 seeds），与主表口径一致
    for r in rows:
        n_runs[r["framework"]] += 1
        for f in r["files_top"]:
            agg[r["framework"]][classify(f["path"])] += f["bytes"]
    fws = [f for f in FW if agg.get(f) or f == "smolagents"]
    fws.sort(key=lambda f: -sum(agg[f].values()))
    fig, ax = plt.subplots(figsize=(4.8, 2.6))
    x = np.arange(len(fws))
    bottom = np.zeros(len(fws))
    for cat in CATS:
        vals = np.array([agg[f][cat] / max(1, n_runs[f]) / 1048576
                         for f in fws])
        ax.bar(x, vals, 0.62, bottom=bottom, label=cat,
               color=CAT_COLOR[cat], edgecolor="white", linewidth=1.2)
        bottom += vals
    ax.set_ylim(0, max(bottom) * 1.18)
    for i, f in enumerate(fws):
        ax.text(i, bottom[i] + max(bottom) * 0.02, f"{bottom[i]:.1f}",
                ha="center", fontsize=8)
    ax.set_xticks(x, [f.replace("openai_agents", "openai-ag.")
                      .replace("smolagents", "smolag.") for f in fws],
                  rotation=28, ha="right", fontsize=7.5)
    ax.set_ylabel("Retained bytes per task (MB)")
    ax.set_title("Storage composition (file-QA suite, mean per run)")
    ax.legend(fontsize=7, frameon=False, loc="upper right")
    ax.grid(axis="y")
    ax.set_axisbelow(True)
    savefig(fig, "fig1_composition")


# ---------- fig2 增长 ----------

def fig2() -> None:
    rows = [json.loads(p.read_text(encoding="utf-8"))
            for p in (ROOT / "experiments" / "longhorizon_runs").glob(
                "*/lh_T*/measurement.json")]
    by = defaultdict(list)
    for r in rows:
        if r["framework"].endswith(("-abl", "-finalsave")):
            continue
        if r.get("seed", "s1") not in ("", "s1"):  # 排除 m2 第二后端复现行
            continue
        T = int(r["task"].split("T")[1])
        if r["S_total"] > 0:
            by[r["framework"]].append((T, r["S_total"]))
    fig, ax = plt.subplots(figsize=(3.6, 2.8))
    for fw in FW:
        pts = sorted(by.get(fw, []))
        if len(pts) < 2:
            continue
        T = np.array([p[0] for p in pts], float)
        S = np.array([p[1] for p in pts], float) / 1048576
        alpha = np.polyfit(np.log(T), np.log(S), 1)[0]
        ax.loglog(T, S, marker=MARKER[fw], color=COLOR[fw], lw=1.6, ms=4.5,
                  label=f"{fw} (α={alpha:.2f})")
    # 参考斜率
    Tref = np.array([25, 200], float)
    for a, lbl in ((1, "∝T"), (2, "∝T²")):
        ax.loglog(Tref, 0.02 * (Tref / 25) ** a, "--", color="#bbbbbb", lw=0.9)
        ax.annotate(lbl, (Tref[-1], 0.02 * (Tref[-1] / 25) ** a),
                    fontsize=7, color="#999999",
                    textcoords="offset points", xytext=(2, 0))
    ax.set_xlabel("Rounds T")
    ax.set_ylabel("Retained bytes (MB)")
    ax.set_title("Repeated-observation stress task")
    ax.set_xticks([25, 50, 100, 200])
    ax.xaxis.set_major_formatter(matplotlib.ticker.ScalarFormatter())
    ax.xaxis.set_minor_locator(matplotlib.ticker.NullLocator())
    ax.set_xlim(21, 300)
    ax.grid(True, which="both")
    ax.set_axisbelow(True)
    ax.legend(fontsize=6.5, ncol=2, loc="upper center",
              bbox_to_anchor=(0.5, -0.22), frameon=False,
              columnspacing=1.2, handlelength=1.6)
    savefig(fig, "fig2_growth")


# ---------- fig3 Pareto ----------

def fig3() -> None:
    """哑铃图：每框架一行，实心=默认留存，空心=CAS 后；右缘标 R 与 acc。"""
    rows = [r for r in load("experiments/pilot_runs/summary.json")
            if is_main_row(r)]
    cas = load("experiments/pilot_runs/cas_summary.json")
    rscores = defaultdict(list)
    for r in load("experiments/pilot_runs/replay_scores.json"):
        rscores[r["framework"]].append(r["R"])
    cas_by = defaultdict(list)
    for c in cas:
        cas_by[c["framework"]].append(c)
    by = defaultdict(list)
    for r in rows:
        by[r["framework"]].append(r)

    data = []
    for fw in FW:
        rs = by[fw]
        S = sum(r["S_total"] for r in rs) / len(rs) / 1048576
        acc = sum(r["n_correct"] for r in rs) / sum(r["n_questions"] for r in rs)
        Sa = (sum(c["S_after"] for c in cas_by[fw]) / len(cas_by[fw]) / 1048576
              if cas_by.get(fw) else None)
        rmode = max(set(rscores[fw]), key=rscores[fw].count) if rscores.get(fw) else 0
        data.append((fw, S, Sa, acc, rmode))
    data.sort(key=lambda d: d[1])  # 小在下，大在上

    fig, ax = plt.subplots(figsize=(4.6, 2.7))
    eps = 0.012
    for i, (fw, S, Sa, acc, rmode) in enumerate(data):
        y = i
        if S > 0 and Sa:
            ax.plot([Sa, S], [y, y], color=COLOR[fw], lw=1.4, alpha=0.55,
                    zorder=2)
            ax.scatter(S, y, s=52, color=COLOR[fw], marker=MARKER[fw],
                       zorder=3)
            ax.scatter(Sa, y, s=46, facecolors="white",
                       edgecolors=COLOR[fw], linewidths=1.4,
                       marker=MARKER[fw], zorder=3)
        else:  # smolagents 0B
            ax.scatter(eps, y, s=52, color=COLOR[fw], marker=MARKER[fw],
                       zorder=3)
            ax.annotate("0 B", (eps, y), textcoords="offset points",
                        xytext=(7, -3), fontsize=7, color="#555555")
        ax.annotate(f"R={rmode}   {acc:.0%}", xy=(1.015, y),
                    xycoords=("axes fraction", "data"), fontsize=7,
                    va="center", color="#333333")
    ax.set_yticks(range(len(data)),
                  [d[0].replace("openai_agents", "openai-agents")
                   for d in data], fontsize=8)
    ax.set_xscale("log")
    ax.set_xlim(0.008, 12)
    ax.set_xlabel("Retained bytes per task (MB, log)")
    ax.set_title("Default retention (filled) vs. after CAS store (hollow)")
    ax.grid(axis="x", which="both")
    ax.set_axisbelow(True)
    fig.subplots_adjust(right=0.82)
    savefig(fig, "fig3_pareto")


# ---------- fig4 Tier B 洗牌 ----------

def fig4() -> None:
    rows = load("experiments/tierb/verified_traj_sizes.json")
    ok = [r for r in rows
          if r.get("normalization_status") == "usable"
          and r.get("mean_bytes")
          and r.get("resolve_rate") is not None]
    x = np.array([r["mean_bytes"] / 1e6 for r in ok])
    y = np.array([r["resolve_rate"] * 100 for r in ok])
    fig, ax = plt.subplots(figsize=(3.8, 2.8))
    in_band = (y >= 65) & (y <= 75)
    ax.axhspan(65, 75, color="#f0b429", alpha=0.12, zorder=1)
    ax.scatter(x[~in_band], y[~in_band], s=14, color="#9aa8b5", alpha=0.6,
               edgecolors="none", zorder=2)
    ax.scatter(x[in_band], y[in_band], s=20, color="#33526e", alpha=0.9,
               edgecolors="none", zorder=3)
    bx = sorted(x[in_band])
    ax.annotate("", (bx[0], 63), (bx[-1], 63),
                arrowprops=dict(arrowstyle="<->", color="#b7791f", lw=1.0))
    ax.annotate(f"same success band, {bx[-1]/bx[0]:.0f}$\\times$ the bytes",
                ((bx[0] * bx[-1]) ** 0.5, 61), ha="center", va="top",
                fontsize=7, color="#b7791f")
    top = sorted(ok, key=lambda r: -r["resolve_rate"])[0]
    hog = max(ok, key=lambda r: r["mean_bytes"])
    for r, lbl_dy in ((top, 5), (hog, -9)):
        ax.annotate(r["submission"].split("_", 1)[1][:22],
                    (r["mean_bytes"] / 1e6, r["resolve_rate"] * 100),
                    textcoords="offset points", xytext=(4, lbl_dy), fontsize=6.5,
                    color="#555555")
    ax.set_xscale("log")
    ax.set_xlabel("Trajectory bytes per instance (MB, log)")
    ax.set_ylabel("Resolve rate (%)")
    ax.set_title(f"SWE-bench Verified, n={len(ok)} normalized systems")
    ax.grid(True, which="both")
    ax.set_axisbelow(True)
    savefig(fig, "fig4_shuffle")


if __name__ == "__main__":
    print("figures ->", FIGS)
    fig1()
    fig2()
    fig3()
    fig4()
