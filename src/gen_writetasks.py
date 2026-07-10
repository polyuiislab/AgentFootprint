"""生成写任务层（任务层 4）：合法产物 vs 框架残留的分界演示。

每任务：读 2 个部门档案 → 用 write_file 产出 summary.txt（含两个编码）→ 回答编码。
判分：答案含两码 + workspace 出现 summary.txt。
分析口径：S_workspace（合法产物）与 S_home（框架残留）分开报。
"""

from __future__ import annotations

import json
import random
import string
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from gen_tasks import DEPTS, build_file  # noqa: E402

HERE = Path(__file__).resolve().parent
TASKS_DIR = HERE.parent / "tasks" / "write_tasks"
N_TASKS = 5


def main() -> None:
    for t in range(N_TASKS):
        rng = random.Random(20260710 + t)
        tdir = TASKS_DIR / f"wtask_{t:02d}"
        (tdir / "corpus").mkdir(parents=True, exist_ok=True)
        depts = rng.sample(DEPTS, 4)
        codes = {}
        for dept in depts:
            text, facts = build_file(rng, dept)
            (tdir / "corpus" / f"records_{dept}.txt").write_text(text, encoding="utf-8")
            codes[dept] = facts["procurement-code"]
        d1, d2 = depts[0], depts[1]
        q = {
            "qid": 0,
            "question": (
                f"Read records_{d1}.txt and records_{d2}.txt. Then use the "
                f"write_file tool to create a file named summary.txt in the "
                f"workspace containing one line per department in the format "
                f"'<dept>: <procurement-code>' for {d1} and {d2}. Finally answer "
                f"with the two procurement codes separated by a space."),
            "answer": codes[d1],          # 判分主码
            "answer2": codes[d2],
            "artifact": "summary.txt",
        }
        (tdir / "questions.json").write_text(json.dumps([q], indent=2),
                                             encoding="utf-8")
        total = sum(f.stat().st_size for f in (tdir / "corpus").iterdir())
        print(f"wtask_{t:02d}: corpus {total/1024:.0f}KB")


if __name__ == "__main__":
    main()
