"""Pilot 编排器：每 (framework, task) 一个干净沙箱 -> 跑适配器 -> meter 测量 -> 判分。

沙箱布局：experiments/pilot_runs/<fw>/<task>/{workspace,home}
  workspace  任务语料（agent 工具的根）
  home       HOME/XDG 全部指过来，框架的持久化都落这里
baseline.json / measurement.json / answers.json / 适配器日志放沙箱根（不计入测量）。

用法:
  python3 runner.py --frameworks langgraph --tasks task_00            # 冒烟
  python3 runner.py --frameworks langgraph,autogen,infiagent --tasks task_00..task_09
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
TASKS = ROOT / "tasks" / "file_intensive"   # 由 --suite 重定向
RUNS = ROOT / "experiments" / "pilot_runs"

sys.path.insert(0, str(HERE))
import meter  # noqa: E402

PY_BY_FW = {
    "langgraph": ROOT / ".venvs" / "langgraph" / "bin" / "python",
    "autogen": ROOT / ".venvs" / "autogen" / "bin" / "python",
    "infiagent": Path("/opt/anaconda3/bin/python3"),
    "crewai": ROOT / ".venvs" / "crewai" / "bin" / "python",
    "smolagents": ROOT / ".venvs" / "smolagents" / "bin" / "python",
    "openai_agents": ROOT / ".venvs" / "openai_agents" / "bin" / "python",
    "llamaindex": ROOT / ".venvs" / "llamaindex" / "bin" / "python",
    "agno": ROOT / ".venvs" / "agno" / "bin" / "python",
}
MODEL_BY_FW = {  # 同一后端模型；litellm 系（infiagent/crewai/smolagents）带 openrouter/ 前缀
    "langgraph": "deepseek/deepseek-v4-flash",
    "autogen": "deepseek/deepseek-v4-flash",
    "infiagent": "openrouter/deepseek/deepseek-v4-flash",
    "crewai": "openrouter/deepseek/deepseek-v4-flash",
    "smolagents": "openrouter/deepseek/deepseek-v4-flash",
    "openai_agents": "deepseek/deepseek-v4-flash",   # 直连 openrouter client
    "llamaindex": "deepseek/deepseek-v4-flash",      # OpenAILike api_base
    "agno": "deepseek/deepseek-v4-flash",            # OpenRouter model id
}


def api_key() -> str:
    env = os.environ.get("OPENROUTER_API_KEY")   # 显式环境变量优先（多 key 并行）
    if env:
        return env
    try:
        for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
            if line.startswith("OPENROUTER_API_KEY="):
                return line.split("=", 1)[1].strip()
    except OSError:
        pass
    if os.environ.get("FOOTPRINT_BASE_URL"):   # mock/fixed-trace 场景无需真 key
        return "sk-mock"
    raise SystemExit("OPENROUTER_API_KEY not found in .env or environment")


EXTRA_ENV: dict = {}


def py_for(fw: str) -> Path:
    """解释器解析：FOOTPRINT_PY_<FW> 环境覆盖 > 本地 venv > 当前解释器。"""
    env = os.environ.get(f"FOOTPRINT_PY_{fw.upper()}")
    if env:
        return Path(env)
    p = PY_BY_FW.get(fw)
    if p and Path(p).exists():
        return Path(p)
    return Path(sys.executable)


def run_one(fw: str, task_name: str, timeout: int = 1200,
            ablation: bool = False, seed: str = "") -> dict:
    label = f"{fw}-abl" if ablation else fw
    if EXTRA_ENV.get("FOOTPRINT_SAVE_MODE") == "final":
        label = f"{fw}-finalsave"
    sandbox = RUNS / label / (task_name + (f"__{seed}" if seed else ""))
    if sandbox.exists():
        shutil.rmtree(sandbox)
    ws, home = sandbox / "workspace", sandbox / "home"
    ws.mkdir(parents=True)
    home.mkdir()
    tdir = TASKS / task_name
    for f in sorted((tdir / "corpus").iterdir()):
        shutil.copy2(f, ws / f.name)

    key = api_key()
    env = os.environ.copy()
    env.update({
        "HOME": str(home),
        "XDG_CACHE_HOME": str(home / ".cache"),
        "XDG_DATA_HOME": str(home / ".local" / "share"),
        "OPENROUTER_API_KEY": key,
        "OPENAI_API_KEY": key,
        "FOOTPRINT_MODEL": MODEL_BY_FW[fw],
        "FOOTPRINT_WORKSPACE": str(ws),
    })
    if ablation:
        env["FOOTPRINT_ABLATION"] = "1"
    if TASKS.name in ("write_tasks", "edit_tasks", "data_tasks"):  # rw 工具集套件
        env["FOOTPRINT_TOOLSET"] = "rw"
    env.update(EXTRA_ENV)
    adapter = [str(py_for(fw)), str(HERE / "adapters" / f"run_{fw}.py")]
    common = ["--task-dir", str(tdir), "--workspace", str(ws),
              "--home", str(home), "--out", str(sandbox / "answers.json")]

    # setup（框架侧准备，计入 baseline）→ snapshot → run（只测 agent 行为）
    setup_proc = subprocess.run(adapter + ["setup"] + common, env=env,
                                cwd=str(ws), capture_output=True, text=True, timeout=120)
    if setup_proc.returncode != 0:
        raise RuntimeError(f"setup failed: {setup_proc.stderr[-2000:]}")
    meter.snapshot(sandbox, sandbox / "baseline.json")

    t0 = time.time()
    try:
        proc = subprocess.run(adapter + ["run"] + common, env=env, cwd=str(ws),
                              capture_output=True, text=True, timeout=timeout)
        rc, out, err = proc.returncode, proc.stdout, proc.stderr
    except subprocess.TimeoutExpired as e:
        rc, out, err = -9, str(e.stdout or ""), f"TIMEOUT after {timeout}s\n{e.stderr or ''}"
    wall = round(time.time() - t0, 1)
    (sandbox / "adapter_stdout.log").write_text((out or "")[-40000:], encoding="utf-8")
    (sandbox / "adapter_stderr.log").write_text((err or "")[-40000:], encoding="utf-8")

    rep = meter.measure(sandbox, sandbox / "baseline.json")

    qs = json.loads((tdir / "questions.json").read_text(encoding="utf-8"))
    try:
        answers = json.loads((sandbox / "answers.json").read_text(encoding="utf-8"))
    except Exception:
        answers = {}
    n_correct = sum(1 for q in qs if q["answer"] in str(answers.get(str(q["qid"]), "")))

    import platform
    rep.update({"framework": label, "task": task_name, "model": MODEL_BY_FW[fw],
                "seed": seed or "s1", "wall_sec": wall, "returncode": rc,
                "n_correct": n_correct, "n_questions": len(qs),
                "benchmark_version": "v1.0.1",
                "platform": platform.platform(),
                "python": sys.version.split()[0]})
    (sandbox / "measurement.json").write_text(json.dumps(rep, indent=2), encoding="utf-8")
    return rep


def expand_tasks(spec: str) -> list[str]:
    if ".." in spec:
        a, b = spec.split("..")
        i, j = int(a.split("_")[1]), int(b.split("_")[1])
        return [f"task_{k:02d}" for k in range(i, j + 1)]
    return spec.split(",")


def fmt_bytes(n) -> str:
    if n is None:
        return "-"
    for u in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f}{u}"
        n /= 1024
    return f"{n:.1f}TB"


def main() -> None:
    global TASKS, RUNS
    ap = argparse.ArgumentParser()
    ap.add_argument("--frameworks", required=True)
    ap.add_argument("--tasks", required=True)
    ap.add_argument("--timeout", type=int, default=1200)
    ap.add_argument("--suite", default="file_intensive",
                    help="任务套件目录名（tasks/<suite>），结果写 experiments/<suite>_runs")
    ap.add_argument("--ablation", action="store_true",
                    help="消融模式：关掉框架的持久化/调试通道（FOOTPRINT_ABLATION=1）")
    ap.add_argument("--seed", default="",
                    help="复跑标签（如 s2/s3）：沙箱与结果行加后缀，不覆盖 s1")
    ap.add_argument("--extra-env", default="",
                    help="KEY=VAL[,KEY=VAL] 传给适配器（如配置敏感性变体）")
    ap.add_argument("--model-override", default="",
                    help="第二后端复现：如 openai/gpt-4o-mini（litellm 系自动加 openrouter/ 前缀），seed 标签自动带 -m2")
    a = ap.parse_args()
    if a.model_override:
        for fw in MODEL_BY_FW:
            MODEL_BY_FW[fw] = (
                "openrouter/" + a.model_override
                if MODEL_BY_FW[fw].startswith("openrouter/") else a.model_override)
        if not a.seed:
            a.seed = "m2"
    if a.extra_env:
        for kv in a.extra_env.split(","):
            k, v = kv.split("=", 1)
            EXTRA_ENV[k] = v
    TASKS = ROOT / "tasks" / a.suite
    RUNS = ROOT / "experiments" / (
        "pilot_runs" if a.suite == "file_intensive" else f"{a.suite}_runs")
    fws = a.frameworks.split(",")
    tasks = expand_tasks(a.tasks)

    rows = []
    for fw in fws:
        for t in tasks:
            print(f"=== {fw} / {t} ...", flush=True)
            try:
                rep = run_one(fw, t, a.timeout, ablation=a.ablation, seed=a.seed)
            except Exception as e:
                print(f"    RUN FAILED: {e}")
                continue
            rows.append(rep)
            print(f"    S_total={fmt_bytes(rep['S_total'])} D={rep['D']} "
                  f"C={rep['C']} echo×{rep['echo_copies']} "
                  f"correct={rep['n_correct']}/{rep['n_questions']} "
                  f"rc={rep['returncode']} {rep['wall_sec']}s", flush=True)

    if rows:
        out = RUNS / "summary.json"
        existing = []
        if out.exists():
            existing = json.loads(out.read_text(encoding="utf-8"))
            keys = {(r["framework"], r["task"], r.get("seed", "s1")) for r in rows}
            existing = [r for r in existing
                        if (r["framework"], r["task"], r.get("seed", "s1")) not in keys]
        out.write_text(json.dumps(existing + rows, indent=2), encoding="utf-8")
        print(f"\nsummary -> {out} ({len(existing) + len(rows)} rows)")


if __name__ == "__main__":
    main()
