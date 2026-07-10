"""生成合成长程任务（任务层 3，docs/01 §3）：测增长指数 α。

monitor 型：T 轮，每轮读同一个 status.txt（固定 2KB，循环体内容长度恒定），
报告其中的 COUNTER 码。留存增长只来自框架的轨迹/状态持久化行为，
不混入内容增长 → log S_total ~ α·log T 可比。

T ∈ {25, 50, 100, 200}，每个 T 一个独立任务目录（独立沙箱冷启动）。
"""

from __future__ import annotations

import json
import random
import string
from pathlib import Path

HERE = Path(__file__).resolve().parent
TASKS_DIR = HERE.parent / "tasks" / "longhorizon"

T_VALUES = [25, 50, 100, 200]
STATUS_KB = 2


def main() -> None:
    rng = random.Random(20260709)
    code = "QX-" + "".join(rng.choices(string.digits, k=5)) + "-" \
        + "".join(rng.choices(string.ascii_uppercase, k=2))
    filler_words = ("monitor heartbeat uptime latency queue backlog watermark "
                    "rotation checkpoint lease").split()
    body = []
    while sum(len(x) for x in body) < STATUS_KB * 1024:
        body.append(" ".join(rng.choice(filler_words) for _ in range(12)) + ".")
    body.insert(len(body) // 2, f"COUNTER: {code}")
    status = "\n".join(body)

    for T in T_VALUES:
        tdir = TASKS_DIR / f"lh_T{T:03d}"
        (tdir / "corpus").mkdir(parents=True, exist_ok=True)
        (tdir / "corpus" / "status.txt").write_text(status, encoding="utf-8")
        questions = [{
            "qid": k,
            "question": (f"Monitoring round {k + 1} of {T}: read the file status.txt "
                         f"(you MUST re-read it now) and report the exact value of "
                         f"COUNTER. Answer with the code only."),
            "answer": code,
        } for k in range(T)]
        (tdir / "questions.json").write_text(
            json.dumps(questions, indent=2), encoding="utf-8")
        print(f"lh_T{T:03d}: status.txt {len(status)}B, {T} rounds")


if __name__ == "__main__":
    main()
