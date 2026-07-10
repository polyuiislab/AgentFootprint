"""infiagent 适配器（脚手架规范版，见 deploy/infiagent_dev_scaffold）。

- 内置工具 file_read/dir_list/final_output，不自造轮子
- 语料拷入 task 目录（file_read 相对 task 根解析）
- setup / run 两阶段：setup 铺好 user_root+语料（计入 baseline），run 只跑 agent
- 某轮失败后续轮换全新 task_id（历史残留会污染重试），语料重新拷贝
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
from pathlib import Path

TEMPLATE = Path(__file__).resolve().parent / "infiagent_user_root"


def task_dir_for(user_root: Path, attempt: int) -> Path:
    d = user_root / "tasks" / f"qa_run_a{attempt}"
    d.mkdir(parents=True, exist_ok=True)
    return d


def copy_corpus(ws: Path, task_dir: Path) -> None:
    for f in sorted(ws.iterdir()):
        if f.is_file():
            shutil.copy2(f, task_dir / f.name)


def setup(a) -> None:
    home = Path(a.home).resolve()
    ws = Path(a.workspace).resolve()
    user_root = home / "user_root"
    shutil.copytree(TEMPLATE, user_root)
    for d in ("skills", "resources", "knowledge", "logs", "runtime",
              "conversations", "tasks", "tools_library"):
        (user_root / d).mkdir(exist_ok=True)
    llm_cfg = user_root / "config" / "llm_config.yaml"
    cfg_text = llm_cfg.read_text(encoding="utf-8").replace(
        "__OPENROUTER_KEY__", os.environ["OPENROUTER_API_KEY"])
    if os.environ.get("FOOTPRINT_BASE_URL"):
        cfg_text = cfg_text.replace("https://openrouter.ai/api/v1",
                                    os.environ["FOOTPRINT_BASE_URL"])
    llm_cfg.write_text(cfg_text, encoding="utf-8")
    copy_corpus(ws, task_dir_for(user_root, 0))
    print("infiagent setup done")


def extract_reply(result, agent, task_id: str) -> str:
    hits: list[str] = []

    def walk(o):
        if isinstance(o, dict):
            for k, v in o.items():
                if k in ("last_final_output", "final_output", "output") \
                        and isinstance(v, str) and v.strip():
                    hits.append(v)
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)

    walk(result)
    if hits:
        return hits[-1]
    try:
        snap = agent.task_snapshot(task_id=task_id)
        return str(snap.get("last_final_output") or "")
    except Exception:
        return ""


def run(a) -> None:
    home = Path(a.home).resolve()
    ws = Path(a.workspace).resolve()
    user_root = home / "user_root"

    from infiagent import infiagent  # noqa: PLC0415

    agent = infiagent(
        user_data_root=str(user_root),
        default_agent_system="footprint",
        default_agent_name="file_qa_agent",
        agent_library_dir=str(user_root),
        skills_dir=str(user_root / "skills"),
        tools_dir=str(user_root / "tools_library"),
        llm_config_path=str(user_root / "config" / "llm_config.yaml"),
        seed_builtin_resources=False,
        direct_tools=True,
        max_turns=60,
    )
    system_add_path = str((user_root / "system-add" / "footprint").resolve())

    questions = json.loads(
        (Path(a.task_dir) / "questions.json").read_text(encoding="utf-8"))
    answers = {}
    attempt = 0
    fresh = True  # 当前 task_id 上是否还没跑过第一轮
    task_id = str(task_dir_for(user_root, attempt).resolve())
    for q in questions:
        try:
            result = agent.run(
                q["question"],
                task_id=task_id,
                force_new=fresh,
                system_add_path=system_add_path,
                collect_events=False,
                stream_llm_tokens=False,
                include_trace=False,
                auto_resume_attempts=1,
                auto_resume_delay_sec=2,
            )
            if isinstance(result, dict) and result.get("status") == "busy":
                raise RuntimeError("run() returned busy")
            answers[str(q["qid"])] = extract_reply(result, agent, task_id)
            fresh = False
        except Exception as e:
            answers[str(q["qid"])] = f"ADAPTER_ERROR: {e}"
            # 失败后不复用 task_id：换全新任务目录重铺语料，继续后面的问题
            attempt += 1
            new_dir = task_dir_for(user_root, attempt)
            copy_corpus(ws, new_dir)
            task_id = str(new_dir.resolve())
            fresh = True
    Path(a.out).write_text(json.dumps(answers, ensure_ascii=False, indent=2),
                           encoding="utf-8")
    print(f"infiagent adapter done (attempts used: {attempt + 1})")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("phase", choices=["setup", "run"])
    ap.add_argument("--task-dir", required=True)
    ap.add_argument("--workspace", required=True)
    ap.add_argument("--home", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    if a.phase == "setup":
        setup(a)
    else:
        run(a)


if __name__ == "__main__":
    main()
