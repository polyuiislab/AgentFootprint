"""infiagent 事后消融：从已有运行中剔除调试通道（llm_debug + training_traces +
runtime debug），重算 S_total/D/echo——等价于"关掉调试日志"（runtime 无开关，
这正是论文观点：调试残留默认开且用户关不掉）。

结果追加写 experiments/pilot_runs/summary.json，framework 记为 infiagent-abl。

用法: python3 ablate_infiagent_posthoc.py <run_sandbox> [...]
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import meter  # noqa: E402

DEBUG_PATTERNS = ("llm_debug", "training_traces", "raw_io", "/debug/")


def main() -> None:
    rows = []
    for arg in sys.argv[1:]:
        src = Path(arg).resolve()
        dst = src.parent.parent / (src.parent.name + "-abl") / src.name
        if dst.exists():
            shutil.rmtree(dst)
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(src, dst, ignore=shutil.ignore_patterns(
            "cas_compacted", "adapter_*.log"))
        removed = 0
        for p in list(dst.rglob("*")):
            if p.is_file() and any(pat in str(p) for pat in DEBUG_PATTERNS):
                removed += p.stat().st_size
                p.unlink()
        rep = meter.measure(dst, dst / "baseline.json")
        old = json.loads((src / "measurement.json").read_text(encoding="utf-8"))
        rep.update({"framework": old["framework"] + "-abl", "task": old["task"],
                    "model": old["model"], "wall_sec": old["wall_sec"],
                    "returncode": old["returncode"],
                    "n_correct": old["n_correct"],
                    "n_questions": old["n_questions"],
                    "debug_bytes_removed": removed})
        (dst / "measurement.json").write_text(json.dumps(rep, indent=2),
                                              encoding="utf-8")
        rows.append(rep)
        print(f"{old['task']}: S {old['S_total']} -> {rep['S_total']} "
              f"(removed {removed}B debug), D {old['D']} -> {rep['D']}")

    summary = src.parents[1] / "summary.json"
    existing = json.loads(summary.read_text(encoding="utf-8"))
    keys = {(r["framework"], r["task"]) for r in rows}
    existing = [r for r in existing if (r["framework"], r["task"]) not in keys]
    summary.write_text(json.dumps(existing + rows, indent=2), encoding="utf-8")
    print(f"summary updated: {summary}")


if __name__ == "__main__":
    main()
