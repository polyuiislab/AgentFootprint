"""LlamaIndex 适配器：FunctionAgent + Context 持久化（官方 state persistence 教程）。

每轮把 Context 序列化落盘（ctx_q<i>.json）——官方"跨会话保持状态"的标准做法。
消融：不落 Context 快照。
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
        print("llamaindex setup done (no-op)")
        return

    ws = Path(a.workspace).resolve()
    home = Path(a.home).resolve()
    ablation = os.environ.get("FOOTPRINT_ABLATION") == "1"

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

    llm = OpenAILike(model=os.environ["FOOTPRINT_MODEL"],
                     api_base=os.environ.get("FOOTPRINT_BASE_URL", "https://openrouter.ai/api/v1"),
                     api_key=os.environ["OPENROUTER_API_KEY"],
                     is_chat_model=True, is_function_calling_model=True,
                     temperature=0, timeout=180)
    agent = FunctionAgent(
        tools=tools, llm=llm,
        system_prompt=("You are a document QA assistant. Verify answers by "
                       "reading workspace files with the tools before answering. "
                       "Answer with the exact requested value only."))

    questions = json.loads(
        (Path(a.task_dir) / "questions.json").read_text(encoding="utf-8"))
    answers = {}

    async def go() -> None:
        ctx = Context(agent)
        for q in questions:
            try:
                r = await agent.run(q["question"], ctx=ctx)
                answers[str(q["qid"])] = str(r)
            except Exception as e:
                answers[str(q["qid"])] = f"ADAPTER_ERROR: {e}"
            if not ablation:
                try:  # 官方 state persistence 教程：Context -> dict -> json 落盘
                    d = ctx.to_dict(serializer=JsonSerializer())
                    (home / f"ctx_q{q['qid']}.json").write_text(
                        json.dumps(d, ensure_ascii=False), encoding="utf-8")
                except Exception as e:
                    (home / f"ctx_q{q['qid']}.err").write_text(str(e),
                                                               encoding="utf-8")

    asyncio.run(go())
    Path(a.out).write_text(json.dumps(answers, ensure_ascii=False, indent=2),
                           encoding="utf-8")
    print("llamaindex adapter done")


if __name__ == "__main__":
    main()
