"""Resume 探针（审稿 Q1 轻量版）：进程边界会话续跑。

阶段 A：适配器进程按 canonical 配置运行——被告知一个 registry code 并持久化，
进程正常退出（崩溃点在轮间）。
阶段 B：全新进程，同一 home、同一 canonical 会话标识，仅凭留存字节回答
"刚才告诉你的 code 是什么"。语料文件不含 code，只有会话库能提供答案。

阶段 B 路径：
  langgraph / openai_agents / agno / crewai / infiagent：重跑适配器
  （固定 session-1 / db 路径 / task_id=任务目录，天然接续）。
  autogen / llamaindex：probes/ 下官方恢复 API 小脚本
  （load_state / Context.from_dict——适配器只保存不加载）。
  smolagents：零留存，按构造不可恢复（L0），不跑。

不测轮中工具态/工作流图恢复——那是更强的能力层级，论文如实声明。
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
import runner  # noqa: E402  (PY_BY_FW / MODEL_BY_FW / api_key)

CODE = "KRX-4471-BM"
OUT = ROOT / "experiments" / "resume_probe"
QA = [{"qid": 0, "question": (
    f"For this session, remember that the registry code is {CODE}. "
    "Do not use any tools. Reply with exactly: OK"), "answer": "OK"}]
QB = [{"qid": 0, "question": (
    "Earlier in this session you were told a registry code. "
    "Answer with exactly that code and nothing else."), "answer": CODE}]
FWS = ["langgraph", "autogen", "openai_agents", "llamaindex", "agno",
       "crewai", "infiagent"]


def mktask(d: Path, qs: list) -> None:
    (d / "corpus").mkdir(parents=True, exist_ok=True)
    (d / "corpus" / "note.txt").write_text(
        "Project workspace. No registry data in the files.\n" * 3,
        encoding="utf-8")
    (d / "questions.json").write_text(json.dumps(qs), encoding="utf-8")


def env_for(fw: str, ws: Path, home: Path) -> dict:
    key = runner.api_key()
    env = os.environ.copy()
    env.update({
        "HOME": str(home),
        "XDG_CACHE_HOME": str(home / ".cache"),
        "XDG_DATA_HOME": str(home / ".local" / "share"),
        "OPENROUTER_API_KEY": key,
        "OPENAI_API_KEY": key,
        "FOOTPRINT_MODEL": runner.MODEL_BY_FW[fw],
        "FOOTPRINT_WORKSPACE": str(ws),
    })
    return env


def run_adapter(fw: str, task_dir: Path, ws: Path, home: Path, out: Path):
    py, ad = runner.PY_BY_FW[fw], HERE / "adapters" / f"run_{fw}.py"
    common = ["--task-dir", str(task_dir), "--workspace", str(ws),
              "--home", str(home), "--out", str(out)]
    env = env_for(fw, ws, home)
    subprocess.run([str(py), str(ad), "setup"] + common, env=env, cwd=str(ws),
                   capture_output=True, text=True, timeout=120)
    return subprocess.run([str(py), str(ad), "run"] + common, env=env,
                          cwd=str(ws), capture_output=True, text=True,
                          timeout=420)


def run_mini(fw: str, script: str, ws: Path, home: Path, out: Path):
    return subprocess.run(
        [str(runner.PY_BY_FW[fw]), str(HERE / "probes" / script),
         "--workspace", str(ws), "--home", str(home), "--out", str(out),
         "--question", QB[0]["question"]],
        env=env_for(fw, ws, home), cwd=str(ws),
        capture_output=True, text=True, timeout=420)


def answer_of(path: Path, proc) -> str:
    try:
        return str(json.loads(path.read_text(encoding="utf-8")).get("0", ""))
    except Exception:
        return f"(no answers file) rc={proc.returncode} err={proc.stderr[-300:]}"


def main() -> None:
    ta, tb = OUT / "_taskA", OUT / "_taskB"
    mktask(ta, QA)
    mktask(tb, QB)
    results = {}
    for fw in FWS:
        sb = OUT / fw
        if sb.exists():
            shutil.rmtree(sb)
        ws, home = sb / "workspace", sb / "home"
        ws.mkdir(parents=True)
        home.mkdir()
        for f in (ta / "corpus").iterdir():
            shutil.copy2(f, ws / f.name)
        print(f"=== {fw} phase A ...", flush=True)
        pa = run_adapter(fw, ta, ws, home, sb / "answers_a.json")
        aa = answer_of(sb / "answers_a.json", pa)
        print(f"=== {fw} phase B (fresh process) ...", flush=True)
        if fw == "autogen":
            pb = run_mini(fw, "resume_autogen_b.py", ws, home, sb / "answers_b.json")
        elif fw == "llamaindex":
            pb = run_mini(fw, "resume_llamaindex_b.py", ws, home, sb / "answers_b.json")
        else:
            pb = run_adapter(fw, tb, ws, home, sb / "answers_b.json")
        ab = answer_of(sb / "answers_b.json", pb)
        ok = CODE in ab
        results[fw] = {"phaseA": aa[:150], "phaseB": ab[:250], "resume_ok": ok}
        print(f"    A={aa[:50]!r}  resume_ok={ok}  B={ab[:80]!r}", flush=True)
    (OUT / "report.json").write_text(
        json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    print("\nRESUME_PROBE_DONE")
    for fw, r in results.items():
        print(f"{fw:15s} resume_ok={r['resume_ok']}")


if __name__ == "__main__":
    main()
