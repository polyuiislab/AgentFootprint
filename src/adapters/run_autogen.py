"""AutoGen (autogen-agentchat 0.7.x) 适配器：官方教程形态。

AssistantAgent + 工具；持久化按官方两条教程的标准接法：
  1) Managing State —— 每轮 save_state() 落盘（会话可恢复的官方做法）
  2) Observability —— EVENT_LOGGER 结构化事件写文件
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
from pathlib import Path

from autogen_agentchat.agents import AssistantAgent
from autogen_core import EVENT_LOGGER_NAME
from autogen_ext.models.openai import OpenAIChatCompletionClient


def text_of(content) -> str:
    if isinstance(content, str):
        return content
    return str(content)


async def run() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("phase", choices=["setup", "run"])
    ap.add_argument("--task-dir", required=True)
    ap.add_argument("--workspace", required=True)
    ap.add_argument("--home", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    if a.phase == "setup":  # 语料由 runner 铺进 workspace，无框架侧准备
        print("autogen setup done (no-op)")
        return
    ws = Path(a.workspace).resolve()
    home = Path(a.home).resolve()

    ablation = os.environ.get("FOOTPRINT_ABLATION") == "1"
    if not ablation:  # 消融：不落事件日志
        ev = logging.getLogger(EVENT_LOGGER_NAME)
        ev.setLevel(logging.INFO)
        ev.addHandler(logging.FileHandler(home / "autogen_events.log", encoding="utf-8"))

    def list_files() -> str:
        """List the files available in the workspace."""
        return "\n".join(sorted(p.name for p in ws.iterdir() if p.is_file()))

    def read_file(filename: str) -> str:
        """Read a file from the workspace and return its full content."""
        p = (ws / filename).resolve()
        if not str(p).startswith(str(ws)):
            return "ERROR: path outside workspace"
        if not p.exists():
            return f"ERROR: no such file {filename}"
        return p.read_text(encoding="utf-8", errors="replace")

    client = OpenAIChatCompletionClient(
        model=os.environ["FOOTPRINT_MODEL"],
        api_key=os.environ["OPENROUTER_API_KEY"],
        base_url=os.environ.get("FOOTPRINT_BASE_URL", "https://openrouter.ai/api/v1"),
        temperature=0,
        model_info={
            "vision": False, "function_calling": True, "json_output": False,
            "family": "unknown", "structured_output": False,
            "multiple_system_messages": True,
        },
    )
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
    agent = AssistantAgent("assistant", model_client=client,
                           tools=tools,
                           reflect_on_tool_use=True)

    questions = json.loads((Path(a.task_dir) / "questions.json").read_text(encoding="utf-8"))
    answers = {}
    for q in questions:
        try:
            result = await agent.run(task=q["question"])
            answers[str(q["qid"])] = text_of(result.messages[-1].content)
        except Exception as e:
            answers[str(q["qid"])] = f"ADAPTER_ERROR: {e}"
        # 官方 Managing State 教程做法：每轮保存会话状态（消融模式跳过）
        # FOOTPRINT_SAVE_MODE=final：配置敏感性变体——只在任务结束时保存一次
        save_final_only = os.environ.get("FOOTPRINT_SAVE_MODE") == "final"
        is_last = q is questions[-1]
        if not ablation and (not save_final_only or is_last):
            try:
                state = await agent.save_state()
                (home / f"agent_state_q{q['qid']}.json").write_text(
                    json.dumps(state, ensure_ascii=False), encoding="utf-8")
            except Exception as e:
                (home / f"agent_state_q{q['qid']}.err").write_text(str(e), encoding="utf-8")
    await client.close()
    Path(a.out).write_text(json.dumps(answers, ensure_ascii=False, indent=2), encoding="utf-8")
    print("autogen adapter done")


if __name__ == "__main__":
    asyncio.run(run())
