"""LlamaIndex 阶段 B：全新进程，仅凭留存 ctx_q0.json（官方 state persistence
教程的 Context.from_dict 路径）恢复上下文并回答 recall 问题。"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workspace", required=True)
    ap.add_argument("--home", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--question", required=True)
    a = ap.parse_args()
    ws = Path(a.workspace).resolve()
    home = Path(a.home).resolve()

    from llama_index.core.agent.workflow import FunctionAgent
    from llama_index.core.workflow import Context, JsonSerializer
    from llama_index.llms.openai_like import OpenAILike

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

    llm = OpenAILike(model=os.environ["FOOTPRINT_MODEL"],
                     api_base=os.environ.get("FOOTPRINT_BASE_URL", "https://openrouter.ai/api/v1"),
                     api_key=os.environ["OPENROUTER_API_KEY"],
                     is_chat_model=True, is_function_calling_model=True,
                     temperature=0, timeout=180)
    agent = FunctionAgent(
        tools=[list_files, read_file], llm=llm,
        system_prompt=("You are a document QA assistant. Verify answers by "
                       "reading workspace files with the tools before answering. "
                       "Answer with the exact requested value only."))

    d = json.loads((home / "ctx_q0.json").read_text(encoding="utf-8"))

    async def go() -> str:
        ctx = Context.from_dict(agent, d, serializer=JsonSerializer())
        r = await agent.run(a.question, ctx=ctx)
        return str(r)

    ans = asyncio.run(go())
    Path(a.out).write_text(json.dumps({"0": ans}, ensure_ascii=False),
                           encoding="utf-8")
    print("llamaindex resume-B done")


if __name__ == "__main__":
    main()
