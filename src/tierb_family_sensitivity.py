"""Tier-B independence sensitivity: submissions are not i.i.d. systems.

The 108 usable submissions include multiple dated versions from the same
team/framework family (e.g., several OpenHands or SWE-agent submissions).
Plain permutation tests treat them as exchangeable units, which can bias
significance. Two sensitivity analyses:

  1. latest-per-family: keep only the newest submission of each family,
     recompute tau_b + permutation p on the deduplicated set;
  2. family-mean aggregation: collapse each family to its mean resolve rate
     and mean per-instance bytes, then run a standard permutation test on
     the family-level points.

Family extraction: strip the leading YYYYMMDD_ date prefix, then normalize
the remaining name by removing model-name tokens and version suffixes; the
mapping is printed for manual audit and saved alongside the stats.
"""

from __future__ import annotations

import json
import random
import re
from collections import defaultdict
from itertools import combinations
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TB = ROOT / "experiments" / "tierb"

MODEL_TOKENS = re.compile(
    r"(gpt[-_]?4[o0]?(mini)?|gpt5|claude[-_]?(3|4|opus|sonnet|haiku)[-.\w]*|"
    r"gemini[-\w.]*|deepseek[-\w.]*|qwen[-\w.]*|o1|o3|v\d+(\.\d+)*|"
    r"\d{2,}b)", re.I)


def family_of(submission: str) -> str:
    name = re.sub(r"^\d{8}_", "", submission).lower()
    parts = [p for p in re.split(r"[_+]", name) if p]
    kept = []
    for p in parts:
        if MODEL_TOKENS.fullmatch(p) or MODEL_TOKENS.match(p):
            continue
        kept.append(p)
    fam = kept[0] if kept else parts[0]
    # 常见别名归并
    alias = {"sweagent": "swe-agent", "swe-agent": "swe-agent"}
    return alias.get(fam, fam)


def tau_b(x: list, y: list) -> float:
    n = len(x)
    c = d = tx = ty = 0
    for i, j in combinations(range(n), 2):
        a, b = x[i] - x[j], y[i] - y[j]
        if a == 0 and b == 0:
            tx += 1; ty += 1
        elif a == 0:
            tx += 1
        elif b == 0:
            ty += 1
        elif a * b > 0:
            c += 1
        else:
            d += 1
    n0 = n * (n - 1) / 2
    denom = ((n0 - tx) * (n0 - ty)) ** 0.5
    return (c - d) / denom if denom else 0.0


def perm_p(x, y, obs, n_perm=20000, seed=11, clusters=None) -> float:
    rng = random.Random(seed)
    cnt = 0
    if clusters is None:
        yy = list(y)
        for _ in range(n_perm):
            rng.shuffle(yy)
            if abs(tau_b(x, yy)) >= abs(obs) - 1e-12:
                cnt += 1
    else:
        # 聚类置换：按 family 整体重排 y 值块
        fam_groups = defaultdict(list)
        for idx, f in enumerate(clusters):
            fam_groups[f].append(idx)
        blocks = list(fam_groups.values())
        for _ in range(n_perm):
            order = list(range(len(blocks)))
            rng.shuffle(order)
            yy = [0.0] * len(y)
            src_vals = [[y[i] for i in blocks[b]] for b in range(len(blocks))]
            pos = 0
            flat_targets = [i for b in order for i in blocks[b]]
            flat_vals = [v for b in order for v in src_vals[b]]
            for t, v in zip(flat_targets, flat_vals):
                yy[t] = v
            if abs(tau_b(x, yy)) >= abs(obs) - 1e-12:
                cnt += 1
    return cnt / n_perm


def main() -> None:
    rows = json.loads((TB / "verified_traj_sizes.json").read_text(encoding="utf-8"))
    ok = [r for r in rows if r.get("normalization_status") == "usable"
          and r.get("resolve_rate") is not None and r.get("mean_bytes")]
    fams = defaultdict(list)
    for r in ok:
        fams[family_of(r["submission"])].append(r)

    print(f"usable={len(ok)}, families={len(fams)}")
    multi = {f: [r['submission'] for r in v] for f, v in fams.items() if len(v) > 1}
    print(f"families with >1 submission: {len(multi)}")

    rr = [r["resolve_rate"] for r in ok]
    mb = [r["mean_bytes"] / 1e6 for r in ok]
    full_tau = tau_b(rr, mb)

    # 敏感性 1：latest per family（提交名前缀日期最大者）
    latest = [max(v, key=lambda r: r["submission"][:8]) for v in fams.values()]
    lrr = [r["resolve_rate"] for r in latest]
    lmb = [r["mean_bytes"] / 1e6 for r in latest]
    tau_latest = tau_b(lrr, lmb)
    p_latest = perm_p(lrr, lmb, tau_latest)

    # 敏感性 2：家族级聚合（每家族取均值后做标准置换——避免不等块置换的实现陷阱）
    frr = [sum(r["resolve_rate"] for r in v) / len(v) for v in fams.values()]
    fmb = [sum(r["mean_bytes"] for r in v) / len(v) / 1e6 for v in fams.values()]
    tau_fam = tau_b(frr, fmb)
    p_fam = perm_p(frr, fmb, tau_fam)

    out = {
        "n_usable": len(ok),
        "n_families": len(fams),
        "families_with_multiple": {k: v for k, v in sorted(multi.items())},
        "direct_tau_b_full": round(full_tau, 4),
        "latest_per_family": {
            "n": len(latest),
            "direct_tau_b": round(tau_latest, 4),
            "permutation_p": round(p_latest, 4),
        },
        "family_mean_aggregation": {
            "n": len(fams),
            "direct_tau_b": round(tau_fam, 4),
            "permutation_p": round(p_fam, 4),
        },
    }
    (TB / "family_sensitivity.json").write_text(json.dumps(out, indent=1),
                                                encoding="utf-8")
    print(json.dumps({k: v for k, v in out.items()
                      if k != "families_with_multiple"}, indent=1))


if __name__ == "__main__":
    main()
