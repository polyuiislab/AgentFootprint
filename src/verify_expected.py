"""CI 回归校验：从归档数据重生成关键数字并与论文发布值比对。

覆盖：主表 file-QA 每框架 S_total 均值（±0.5%）、异质族严格联合成功计数、
meter 校准精确场景 D 值。任何一项漂移即失败——保证公开数据与论文表格一致。
依赖：仓库内 experiments/ 摘要与产物 + tasks/（无需任何 API）。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from statistics import mean

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

EXPECTED_S_MB = {  # 论文 Table 1（file-QA 主研究，30 run 均值）
    "langgraph": 5.10, "autogen": 2.49, "infiagent": 2.12, "agno": 1.15,
    "llamaindex": 0.93, "openai_agents": 0.33, "crewai": 0.32,
    "smolagents": 0.0,
}
EXPECTED_JOINT = {  # 论文附录 het 表（严格口径）
    "edit_tasks": {"langgraph": 5, "autogen": 0, "infiagent": 0, "crewai": 5,
                   "smolagents": 4, "openai_agents": 5, "llamaindex": 5,
                   "agno": 5},
    "data_tasks": {"langgraph": 5, "autogen": 0, "infiagent": 0, "crewai": 5,
                   "smolagents": 1, "openai_agents": 5, "llamaindex": 5,
                   "agno": 5},
}


def check_main_table() -> None:
    rows = json.loads((ROOT / "experiments/pilot_runs/summary.json")
                      .read_text(encoding="utf-8"))
    main = [r for r in rows if r.get("seed", "s1") in ("s1", "s2", "s3")
            and "gpt-4o-mini" not in r.get("model", "")
            and "-" not in r["framework"]]
    for fw, exp in EXPECTED_S_MB.items():
        vals = [r["S_total"] for r in main if r["framework"] == fw]
        assert len(vals) == 30, f"{fw}: expected 30 main runs, got {len(vals)}"
        got = mean(vals) / 1048576
        assert abs(got - exp) <= max(0.005 * max(exp, 0.01), 0.005), \
            f"{fw}: S_total mean {got:.3f}MB != published {exp}MB"
    print(f"main table OK ({len(EXPECTED_S_MB)} frameworks, 240 runs)")


def check_het_joint() -> None:
    from strict_graders import data_strict, edit_strict
    fns = {"edit_tasks": edit_strict, "data_tasks": data_strict}
    for suite, exp in EXPECTED_JOINT.items():
        rows = json.loads((ROOT / "experiments" / f"{suite}_runs/summary.json")
                          .read_text(encoding="utf-8"))
        for fw, e in exp.items():
            rs = [r for r in rows if r["framework"] == fw]
            joint = sum(1 for r in rs if fns[suite](r["task"], fw)
                        and r["n_correct"] == r["n_questions"])
            assert joint == e, f"{suite}/{fw}: joint {joint} != published {e}"
    print("heterogeneous strict-joint OK (16 cells)")


def check_calibration() -> None:
    import meter_calibration as mc
    for name, build, d_true, _ in mc.SCENES:
        if name in ("single-esc", "sqlite-exact", "small-lines"):
            rep = mc.measure_scene(name, build)
            assert abs(rep["D"] - d_true) < 0.05, \
                f"calibration {name}: D {rep['D']} != {d_true}"
    print("meter calibration exact scenes OK")


if __name__ == "__main__":
    check_main_table()
    check_het_joint()
    check_calibration()
    print("ALL VERIFICATIONS PASSED")
