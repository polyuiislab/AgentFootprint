"""SmolAgents 适配器：官方 quickstart 形态（ToolCallingAgent + LiteLLMModel）。

默认不落盘持久化（内存态 memory）——这本身是重要数据点：足迹≈0 但 R=0
（任务结束什么都不可审计/不可恢复）。reset=False 保持跨问题会话记忆。
"""

from __future__ import annotations

import argparse
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
        print("smolagents setup done (no-op)")
        return

    ws = Path(a.workspace).resolve()

    from smolagents import LiteLLMModel, ToolCallingAgent, tool

    @tool
    def list_files() -> str:
        """List the files available in the workspace.

        Returns:
            Newline-separated file names.
        """
        return "\n".join(sorted(p.name for p in ws.iterdir() if p.is_file()))

    @tool
    def read_file(filename: str) -> str:
        """Read a file from the workspace and return its full content.

        Args:
            filename: Name of the file in the workspace.
        """
        p = (ws / filename).resolve()
        if not str(p).startswith(str(ws)):
            return "ERROR: path outside workspace"
        if not p.exists():
            return f"ERROR: no such file {filename}"
        return p.read_text(encoding="utf-8", errors="replace")

    @tool
    def write_file(filename: str, content: str) -> str:
        """Write content to a file in the workspace.

        Args:
            filename: Name of the file to write.
            content: Text content to write.
        """
        p = (ws / filename).resolve()
        if not str(p).startswith(str(ws)):
            return "ERROR: path outside workspace"
        p.write_text(content, encoding="utf-8")
        return f"wrote {filename} ({len(content)} chars)"

    tools = [list_files, read_file]
    if os.environ.get("FOOTPRINT_TOOLSET") == "rw":
        tools.append(write_file)
    # FOOTPRINT_OR_IGNORE: OpenRouter 供应商黑名单（如 Phala 返回损坏 JSON）
    _ig = os.environ.get("FOOTPRINT_OR_IGNORE")
    _extra = ({"extra_body": {"provider": {"ignore": _ig.split(",")}}}
              if _ig else {})
    model = LiteLLMModel(model_id=os.environ["FOOTPRINT_MODEL"],
                         api_key=os.environ["OPENROUTER_API_KEY"],
                         temperature=0, **_extra)
    agent = ToolCallingAgent(tools=tools, model=model,
                             max_steps=12)

    questions = json.loads(
        (Path(a.task_dir) / "questions.json").read_text(encoding="utf-8"))
    answers = {}
    for i, q in enumerate(questions):
        try:
            r = agent.run(q["question"], reset=(i == 0))
            answers[str(q["qid"])] = str(r)
        except Exception as e:
            answers[str(q["qid"])] = f"ADAPTER_ERROR: {e}"
    Path(a.out).write_text(json.dumps(answers, ensure_ascii=False, indent=2),
                           encoding="utf-8")
    print("smolagents adapter done")


if __name__ == "__main__":
    main()
