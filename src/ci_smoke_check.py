"""CI 冒烟断言：fixed-trace 单框架结果健壮性检查。"""

import json
import sys
from pathlib import Path

rows = json.loads(Path("experiments/fixed_trace_runs/summary.json").read_text())
fw = sys.argv[1] if len(sys.argv) > 1 else "openai_agents"
r = [x for x in rows if x["framework"] == fw][0]
assert r["n_correct"] == 1, f"fixed-trace answer failed: {r}"
assert r["S_total"] > 100_000, f"retention implausible: {r['S_total']}"
print(f"fixed-trace smoke OK: {fw} retained {r['S_total']} bytes")
