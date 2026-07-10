"""AutoGen 阶段 B：全新进程，仅凭留存 agent_state_q0.json（官方 Managing State
教程的 load_state 路径）恢复会话并回答 recall 问题。"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path

from autogen_agentchat.agents import AssistantAgent
from autogen_ext.models.openai import OpenAIChatCompletionClient


async def go() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workspace", required=True)
    ap.add_argument("--home", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--question", required=True)
    a = ap.parse_args()
    ws = Path(a.workspace).resolve()
    home = Path(a.home).resolve()

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
    agent = AssistantAgent("assistant", model_client=client,
                           tools=[list_files, read_file],
                           reflect_on_tool_use=True)
    state = json.loads((home / "agent_state_q0.json").read_text(encoding="utf-8"))
    await agent.load_state(state)
    result = await agent.run(task=a.question)
    content = result.messages[-1].content
    await client.close()
    Path(a.out).write_text(json.dumps(
        {"0": content if isinstance(content, str) else str(content)},
        ensure_ascii=False), encoding="utf-8")
    print("autogen resume-B done")


if __name__ == "__main__":
    asyncio.run(go())
