"""OpenAI Agents SDK 适配器：官方 Sessions quickstart 形态。

持久化 = SQLiteSession（官方会话持久化教程的标准接法，落沙箱 home）。
tracing 显式关闭（否则会往 OpenAI 平台上传，且不属于本地留存）。
消融（FOOTPRINT_ABLATION=1）：不用 Session，手动传历史 → 无落盘。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("phase", choices=["setup", "run"])
    ap.add_argument("--task-dir", required=True)
    ap.add_argument("--workspace", required=True)
    ap.add_argument("--home", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    if a.phase == "setup":
        print("openai_agents setup done (no-op)")
        return

    ws = Path(a.workspace).resolve()
    home = Path(a.home).resolve()
    ablation = os.environ.get("FOOTPRINT_ABLATION") == "1"

    from agents import (Agent, Runner, SQLiteSession, function_tool,
                        set_tracing_disabled)
    from agents.models.openai_chatcompletions import OpenAIChatCompletionsModel
    from openai import AsyncOpenAI

    set_tracing_disabled(True)

    @function_tool
    def list_files() -> str:
        """List the files available in the workspace."""
        return "\n".join(sorted(p.name for p in ws.iterdir() if p.is_file()))

    @function_tool
    def read_file(filename: str) -> str:
        """Read a file from the workspace and return its full content."""
        p = (ws / filename).resolve()
        if not str(p).startswith(str(ws)):
            return "ERROR: path outside workspace"
        if not p.exists():
            return f"ERROR: no such file {filename}"
        return p.read_text(encoding="utf-8", errors="replace")

    @function_tool
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

    client = AsyncOpenAI(base_url=os.environ.get("FOOTPRINT_BASE_URL", "https://openrouter.ai/api/v1"),
                         api_key=os.environ["OPENROUTER_API_KEY"])
    agent = Agent(
        name="assistant",
        instructions=("You are a document QA assistant. Verify answers by "
                      "reading workspace files with the tools before answering. "
                      "Answer with the exact requested value only."),
        model=OpenAIChatCompletionsModel(
            model=os.environ["FOOTPRINT_MODEL"], openai_client=client),
        tools=tools,
    )

    questions = json.loads(
        (Path(a.task_dir) / "questions.json").read_text(encoding="utf-8"))
    answers = {}

    async def go() -> None:
        session = None if ablation else SQLiteSession(
            "session-1", str(home / "agents_sessions.sqlite"))
        for q in questions:
            try:
                r = await Runner.run(agent, q["question"], session=session,
                                     max_turns=15)
                answers[str(q["qid"])] = str(r.final_output)
            except Exception as e:
                answers[str(q["qid"])] = f"ADAPTER_ERROR: {e}"

    asyncio.run(go())
    Path(a.out).write_text(json.dumps(answers, ensure_ascii=False, indent=2),
                           encoding="utf-8")
    print("openai_agents adapter done")


if __name__ == "__main__":
    main()
