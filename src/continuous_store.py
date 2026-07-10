"""长期共享库协议（R7-Q4）：同一持久化后端连续执行 N 个任务的边际存储成本。

与主协议（每任务全新沙箱）互补：一个沙箱、同一 documented session 身份，
连续 N=10 个固定轨迹任务（mock 端点，零 API），每任务后测量 home 累计字节，
报告 S(k) 与边际 ΔS(k)=S(k)-S(k-1)。回答"真实部署里共享库的每任务边际
成本是否保持主协议的排序/形态"。

预期形态（各框架 documented 配置的真实语义，如实报告）：
  langgraph  同 thread 历史累积 -> 边际递增（超线性累计）
  openai/agno/infiagent  会话追加/有界 -> 边际近常数
  autogen/llamaindex  快照文件名按 qid 固定 -> 跨任务覆写，边际近零增长
"""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
import mock_llm  # noqa: E402
import runner  # noqa: E402
from meter import inventory  # noqa: E402

SRC_TASK = ROOT / "tasks" / "file_intensive" / "task_00"
READS = ["records_algol.txt", "records_briar.txt", "records_algol.txt"]
N_TASKS = 10
FWS = ["langgraph", "autogen", "openai_agents", "llamaindex", "agno",
       "infiagent"]
OUT = ROOT / "experiments" / "continuous_store"


def free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def home_bytes(home: Path) -> int:
    return sum(inventory(home).values())


def main() -> None:
    q0 = json.loads((SRC_TASK / "questions.json").read_text(encoding="utf-8"))[0]
    answer = q0["answer"]
    tdir = OUT / "_task"
    if tdir.exists():
        shutil.rmtree(tdir)
    (tdir / "corpus").mkdir(parents=True)
    for f in sorted((SRC_TASK / "corpus").iterdir()):
        shutil.copy2(f, tdir / "corpus" / f.name)
    (tdir / "questions.json").write_text(json.dumps([{
        "qid": 0,
        "question": ("Inspect the workspace records with your tools and "
                     "report the registry code for entry ALGOL-7."),
        "answer": answer}]), encoding="utf-8")

    port = free_port()
    srv = mock_llm.serve(port, READS, answer)
    base = f"http://127.0.0.1:{port}/v1"
    key = runner.api_key()
    results = {}
    for fw in FWS:
        sb = OUT / fw
        if sb.exists():
            shutil.rmtree(sb)
        ws, home = sb / "workspace", sb / "home"
        ws.mkdir(parents=True)
        home.mkdir()
        for f in (tdir / "corpus").iterdir():
            shutil.copy2(f, ws / f.name)
        env = os.environ.copy()
        env.update({
            "HOME": str(home), "XDG_CACHE_HOME": str(home / ".cache"),
            "XDG_DATA_HOME": str(home / ".local" / "share"),
            "OPENROUTER_API_KEY": key, "OPENAI_API_KEY": key,
            "FOOTPRINT_MODEL": runner.MODEL_BY_FW[fw],
            "FOOTPRINT_WORKSPACE": str(ws),
            "FOOTPRINT_BASE_URL": base, "OPENROUTER_API_BASE": base,
        })
        py = runner.py_for(fw)
        ad = HERE / "adapters" / f"run_{fw}.py"
        common = ["--task-dir", str(tdir), "--workspace", str(ws),
                  "--home", str(home), "--out", str(sb / "answers.json")]
        subprocess.run([str(py), str(ad), "setup"] + common, env=env,
                       cwd=str(ws), capture_output=True, text=True, timeout=120)
        base_bytes = home_bytes(home)   # setup 暂存不计入任务边际
        series = []
        ok = 0
        for k in range(1, N_TASKS + 1):
            pr = subprocess.run([str(py), str(ad), "run"] + common, env=env,
                                cwd=str(ws), capture_output=True, text=True,
                                timeout=300)
            try:
                a = json.loads((sb / "answers.json").read_text())["0"]
                ok += answer in str(a)
            except Exception:
                pass
            series.append(home_bytes(home) - base_bytes)
        marg = [series[0]] + [series[i] - series[i - 1]
                              for i in range(1, len(series))]
        results[fw] = {"S_k_bytes": series, "marginal_bytes": marg,
                       "answers_ok": ok, "n_tasks": N_TASKS}
        print(f"{fw:15s} ok={ok}/{N_TASKS} S(1)={series[0]/1024:.0f}KB "
              f"S(10)={series[-1]/1024:.0f}KB  marg1={marg[0]/1024:.0f}KB "
              f"marg10={marg[-1]/1024:.0f}KB "
              f"trend={'rising' if marg[-1] > 1.5*max(marg[0],1) else ('flat' if marg[-1] > 0.5*marg[0] else 'collapsing')}",
              flush=True)
    srv.shutdown()
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "report.json").write_text(json.dumps(results, indent=2),
                                     encoding="utf-8")
    print(f"\nreport -> {OUT/'report.json'}")


if __name__ == "__main__":
    main()
