"""LangGraph 适配器：官方 persistence quickstart 形态。

create_react_agent + SqliteSaver checkpointer（LangGraph 持久化教程的标准接法），
同一 thread_id 连续多问 —— 每个 superstep checkpoint 全量状态，这正是被测行为。
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
from pathlib import Path

from langchain_core.tools import tool
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.prebuilt import create_react_agent


def text_of(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):  # 新版 content blocks
        return " ".join(b.get("text", "") if isinstance(b, dict) else str(b) for b in content)
    return str(content)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("phase", choices=["setup", "run"])
    ap.add_argument("--task-dir", required=True)
    ap.add_argument("--workspace", required=True)
    ap.add_argument("--home", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    if a.phase == "setup":  # 语料由 runner 铺进 workspace，无框架侧准备
        print("langgraph setup done (no-op)")
        return
    ws = Path(a.workspace).resolve()
    home = Path(a.home).resolve()

    @tool
    def list_files() -> str:
        """List the files available in the workspace."""
        return "\n".join(sorted(p.name for p in ws.iterdir() if p.is_file()))

    @tool
    def read_file(filename: str) -> str:
        """Read a file from the workspace and return its full content."""
        p = (ws / filename).resolve()
        if not str(p).startswith(str(ws)):
            return "ERROR: path outside workspace"
        if not p.exists():
            return f"ERROR: no such file {filename}"
        return p.read_text(encoding="utf-8", errors="replace")

    model = ChatOpenAI(
        model=os.environ["FOOTPRINT_MODEL"],
        api_key=os.environ["OPENROUTER_API_KEY"],
        base_url=os.environ.get("FOOTPRINT_BASE_URL", "https://openrouter.ai/api/v1"),
        temperature=0,
        timeout=180,
        max_retries=3,
    )
    @tool
    def write_file(filename: str, content: str) -> str:
        """Write content to a file in the workspace."""
        p = (ws / filename).resolve()
        if not str(p).startswith(str(ws)):
            return "ERROR: path outside workspace"
        p.write_text(content, encoding="utf-8")
        return f"wrote {filename} ({len(content)} chars)"

    tools = [list_files, read_file]
    if os.environ.get("FOOTPRINT_TOOLSET") == "rw":
        tools.append(write_file)

    ablation = os.environ.get("FOOTPRINT_ABLATION") == "1"
    if ablation:  # 消融：关持久化（quickstart 无 checkpointer 形态）
        conn = None
        agent = create_react_agent(model, tools)
    else:
        conn = sqlite3.connect(str(home / "langgraph_checkpoints.sqlite"),
                               check_same_thread=False)
        agent = create_react_agent(model, tools,
                                   checkpointer=SqliteSaver(conn))

    questions = json.loads((Path(a.task_dir) / "questions.json").read_text(encoding="utf-8"))
    cfg = {"configurable": {"thread_id": "session-1"}, "recursion_limit": 50}
    answers = {}
    history = {"messages": []}  # 消融模式下手动维护多轮上下文
    for q in questions:
        try:
            if ablation:
                history["messages"].append(("user", q["question"]))
                r = agent.invoke(history, {"recursion_limit": 50})
                history = r
            else:
                r = agent.invoke({"messages": [("user", q["question"])]}, cfg)
            answers[str(q["qid"])] = text_of(r["messages"][-1].content)
        except Exception as e:  # 单题失败不拖垮整个任务
            answers[str(q["qid"])] = f"ADAPTER_ERROR: {e}"
    if conn is not None:
        conn.commit()
        conn.close()
    Path(a.out).write_text(json.dumps(answers, ensure_ascii=False, indent=2), encoding="utf-8")
    print("langgraph adapter done")


if __name__ == "__main__":
    main()
