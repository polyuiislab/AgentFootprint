"""D 的流长度阈值敏感性（审稿 round-4 W2a）。

在 file-QA 首重复子集（8 框架 × task_00..04）上，用 min_len ∈ {0,16,32,64,128}
重算 D = S_logical / S_unique，检验 64B 阈值是否驱动结论。数值/NULL 单元
不属于内容字节，任何阈值下都不进入分子分母（正文如实声明）。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from statistics import mean

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
import meter  # noqa: E402

FWS = ["langgraph", "autogen", "infiagent", "agno", "llamaindex",
       "openai_agents", "crewai"]
THRESHOLDS = [0, 16, 32, 64, 128]
TASKS = [f"task_{i:02d}" for i in range(5)]


def retained_files(sb: Path) -> list[Path]:
    base = json.loads((sb / "baseline.json").read_text(encoding="utf-8"))
    out = []
    for layer in ("workspace", "home"):
        before = base.get(layer, {})
        root = sb / layer
        for rel, size in meter.inventory(root).items():
            bv = before.get(rel)
            bs = bv if isinstance(bv, int) else (bv or {}).get("size")
            if bs == size:
                continue
            if meter.is_excluded(rel):
                continue
            out.append(root / rel)
    return out


def d_at(files: list[Path], min_len: int):
    uniq: dict[str, int] = {}
    logical = 0
    for f in files:
        for s in meter.streams_of(f, min_len):
            logical += len(s)
            for h, ln in meter.chunk_stream(s):
                uniq.setdefault(h, ln)
    u = sum(uniq.values())
    return (logical / u) if u else None


def main() -> None:
    print("| framework | " + " | ".join(f"D@{t}" for t in THRESHOLDS) + " |")
    print("|---" * (len(THRESHOLDS) + 1) + "|")
    report = {}
    for fw in FWS:
        rows = {t: [] for t in THRESHOLDS}
        for task in TASKS:
            sb = ROOT / "experiments" / "pilot_runs" / fw / task
            if not sb.exists():
                continue
            files = retained_files(sb)
            for t in THRESHOLDS:
                d = d_at(files, t)
                if d:
                    rows[t].append(d)
        vals = [f"{mean(rows[t]):.1f}" if rows[t] else "--" for t in THRESHOLDS]
        report[fw] = {t: (round(mean(rows[t]), 2) if rows[t] else None)
                      for t in THRESHOLDS}
        print(f"| {fw} | " + " | ".join(vals) + " |")
    out = ROOT / "experiments" / "threshold_sensitivity.json"
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"\nreport -> {out}")


if __name__ == "__main__":
    main()
