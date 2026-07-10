"""Docker 隔离对照验证：langgraph × 3 任务在容器内重跑，对比进程级沙箱数字。

沙箱布局与 runner.py 一致（workspace/home + baseline + meter），容器只是执行层：
每 (framework, task) 一个全新容器，卷挂载 workspace/home/adapter/tasks。
产出 experiments/docker_check.json：两种隔离方式的 S_total/D/echo 并排。
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC = HERE.parent
ROOT = SRC.parent
TASKS = ROOT / "tasks" / "file_intensive"
RUNS = ROOT / "experiments" / "docker_runs"

sys.path.insert(0, str(SRC))
import meter  # noqa: E402

IMAGE = "footprint-langgraph:pinned"
CHECK_TASKS = ["task_00", "task_01", "task_02"]


def api_key() -> str:
    for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
        if line.startswith("OPENROUTER_API_KEY="):
            return line.split("=", 1)[1].strip()
    raise SystemExit("no key")


def run_one(task_name: str) -> dict:
    sandbox = RUNS / "langgraph" / task_name
    if sandbox.exists():
        shutil.rmtree(sandbox)
    ws, home = sandbox / "workspace", sandbox / "home"
    ws.mkdir(parents=True)
    home.mkdir()
    os.chmod(home, 0o777)
    os.chmod(ws, 0o777)
    tdir = TASKS / task_name
    for f in sorted((tdir / "corpus").iterdir()):
        shutil.copy2(f, ws / f.name)
    meter.snapshot(sandbox, sandbox / "baseline.json")

    t0 = time.time()
    proc = subprocess.run([
        "docker", "run", "--rm",
        "-v", f"{ws}:/sandbox/workspace",
        "-v", f"{home}:/sandbox/home",
        "-v", f"{SRC / 'adapters'}:/adapter:ro",
        "-v", f"{tdir}:/taskdef:ro",
        "-e", f"OPENROUTER_API_KEY={api_key()}",
        "-e", "OPENAI_API_KEY=dummy",
        "-e", "FOOTPRINT_MODEL=deepseek/deepseek-v4-flash",
        IMAGE, "run",
        "--task-dir", "/taskdef", "--workspace", "/sandbox/workspace",
        "--home", "/sandbox/home", "--out", "/sandbox/home/answers.json",
    ], capture_output=True, text=True, timeout=1200)
    wall = round(time.time() - t0, 1)
    (sandbox / "adapter_stderr.log").write_text(proc.stderr[-20000:] or "")

    # answers.json 写在 home 里（容器可写处）；测量前移出去避免计入
    ans_src = home / "answers.json"
    answers = {}
    if ans_src.exists():
        answers = json.loads(ans_src.read_text(encoding="utf-8"))
        ans_src.rename(sandbox / "answers.json")

    rep = meter.measure(sandbox, sandbox / "baseline.json")
    qs = json.loads((tdir / "questions.json").read_text(encoding="utf-8"))
    rep.update({
        "framework": "langgraph-docker", "task": task_name,
        "wall_sec": wall, "returncode": proc.returncode,
        "n_correct": sum(1 for q in qs
                         if q["answer"] in str(answers.get(str(q["qid"]), ""))),
        "n_questions": len(qs),
    })
    (sandbox / "measurement.json").write_text(json.dumps(rep, indent=2))
    return rep


def main() -> None:
    out = []
    for t in CHECK_TASKS:
        print(f"=== docker langgraph / {t}", flush=True)
        rep = run_one(t)
        proc_rep = json.loads((ROOT / "experiments" / "pilot_runs" / "langgraph"
                               / t / "measurement.json").read_text())
        row = {"task": t,
               "docker": {k: rep[k] for k in
                          ("S_total", "D", "echo_copies", "n_correct")},
               "process": {k: proc_rep[k] for k in
                           ("S_total", "D", "echo_copies", "n_correct")}}
        out.append(row)
        print(f"    docker S={rep['S_total']} vs process S={proc_rep['S_total']}"
              f"  ratio={rep['S_total']/max(1,proc_rep['S_total']):.3f}")
    (ROOT / "experiments" / "docker_check.json").write_text(
        json.dumps(out, indent=2))
    print("-> experiments/docker_check.json")


if __name__ == "__main__":
    main()
