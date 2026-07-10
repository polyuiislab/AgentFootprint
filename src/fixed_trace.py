"""Fixed-trace 协议驱动器（六轮审稿 #1 共同诉求：相同轨迹下的纯存储编码对比）。

设计：本地 mock LLM（mock_llm.py）向所有框架回放同一固定脚本——
读 records_algol -> 读 records_briar -> 再读 records_algol -> 报告答案。
所有框架收到相同的逻辑轨迹（读取序列/观测字节/答案完全一致），
S_total 的差异即为各持久化机制对同一内容的编码放大。零 API 成本。

复用 runner.py 全链路（沙箱/meter/判分），仅通过 --extra-env 把
FOOTPRINT_BASE_URL / OPENROUTER_API_BASE 指向 mock。
SmolAgents 默认零留存（无编码可比），不在此协议内。
"""

from __future__ import annotations

import json
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
import mock_llm  # noqa: E402

SRC_TASK = ROOT / "tasks" / "file_intensive" / "task_00"
FT_TASK = ROOT / "tasks" / "fixed_trace" / "ftask_00"
READS = ["records_algol.txt", "records_briar.txt", "records_algol.txt"]
import os
FWS = (os.environ.get("FIXED_TRACE_FWS", "").split(",")
       if os.environ.get("FIXED_TRACE_FWS") else
       ["langgraph", "autogen", "openai_agents", "llamaindex", "agno",
        "crewai", "infiagent"])


def make_task() -> str:
    """固定轨迹任务：task_00 语料 + 单问题；答案取 task_00 q0 的真实 code。"""
    q0 = json.loads((SRC_TASK / "questions.json").read_text(encoding="utf-8"))[0]
    answer = q0["answer"]
    if FT_TASK.exists():
        shutil.rmtree(FT_TASK)
    (FT_TASK / "corpus").mkdir(parents=True)
    for f in sorted((SRC_TASK / "corpus").iterdir()):
        shutil.copy2(f, FT_TASK / "corpus" / f.name)
    (FT_TASK / "questions.json").write_text(json.dumps([{
        "qid": 0,
        "question": ("Follow your tools to inspect the workspace records and "
                     "report the registry code for entry ALGOL-7."),
        "answer": answer}]), encoding="utf-8")
    return answer


def free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def main() -> None:
    answer = make_task()
    port = free_port()
    srv = mock_llm.serve(port, READS, answer)
    base = f"http://127.0.0.1:{port}/v1"
    print(f"mock llm on {base}  answer={answer}", flush=True)
    extra = (f"FOOTPRINT_BASE_URL={base},OPENROUTER_API_BASE={base},"
             f"OR_SITE_URL={base}")
    for fw in FWS:
        print(f"=== fixed-trace {fw} ===", flush=True)
        p = subprocess.run(
            [sys.executable, str(HERE / "runner.py"), "--frameworks", fw,
             "--tasks", "ftask_00", "--suite", "fixed_trace",
             "--timeout", "240", "--extra-env", extra],
            capture_output=True, text=True, timeout=600)
        tail = "\n".join(p.stdout.strip().splitlines()[-2:])
        print(tail, flush=True)
        if p.returncode != 0:
            print(f"    runner rc={p.returncode} err={p.stderr[-300:]}", flush=True)
    srv.shutdown()

    out = ROOT / "experiments" / "fixed_trace_runs" / "summary.json"
    if out.exists():
        rows = json.loads(out.read_text(encoding="utf-8"))
        obs = sum((FT_TASK / "corpus" / n).stat().st_size for n in READS)
        print(f"\n== fixed-trace results (identical trajectory; "
              f"observation bytes={obs/1024:.1f}KB) ==")
        print("| framework | correct | S_total KB | KB per obs-KB | D | echo |")
        print("|---|---|---|---|---|---|")
        for r in sorted(rows, key=lambda x: -x["S_total"]):
            print(f"| {r['framework']} | {r['n_correct']}/{r['n_questions']} | "
                  f"{r['S_total']/1024:.1f} | {r['S_total']/obs:.2f} | "
                  f"{r['D']} | {r['echo_copies']} |")


if __name__ == "__main__":
    main()
