"""CrewAI 适配器：官方 quickstart 形态（Agent + Task + Crew.kickoff）。

持久化按默认行为：CrewAI 的 storage（task outputs 等 sqlite）写到用户数据目录，
HOME 已被 runner 指进沙箱，全部被捕获。memory 参数不传（默认值），测默认行为。
5 个问题 = 一个 Crew 的 5 个顺序 Task（quickstart 的标准多任务形态）。
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
        print("crewai setup done (no-op)")
        return

    ws = Path(a.workspace).resolve()

    from crewai import Agent, Crew, LLM, Task
    from crewai.tools import tool

    @tool("list_files")
    def list_files() -> str:
        """List the files available in the workspace."""
        return "\n".join(sorted(p.name for p in ws.iterdir() if p.is_file()))

    @tool("read_file")
    def read_file(filename: str) -> str:
        """Read a file from the workspace and return its full content."""
        p = (ws / filename).resolve()
        if not str(p).startswith(str(ws)):
            return "ERROR: path outside workspace"
        if not p.exists():
            return f"ERROR: no such file {filename}"
        return p.read_text(encoding="utf-8", errors="replace")

    llm = LLM(model=os.environ["FOOTPRINT_MODEL"],
              api_key=os.environ["OPENROUTER_API_KEY"],
              temperature=0)

    @tool("write_file")
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
    agent = Agent(
        role="Document QA assistant",
        goal="Answer questions about files in the workspace with exact values.",
        backstory="You verify answers by reading the files with the provided tools.",
        tools=tools,
        llm=llm,
        verbose=False,
    )

    questions = json.loads(
        (Path(a.task_dir) / "questions.json").read_text(encoding="utf-8"))
    tasks = [Task(description=q["question"],
                  expected_output="The exact code only (format QX-#####-XX).",
                  agent=agent)
             for q in questions]
    crew = Crew(agents=[agent], tasks=tasks, verbose=False)

    answers = {}
    try:
        crew.kickoff()
        for q, t in zip(questions, tasks):
            answers[str(q["qid"])] = str(getattr(t.output, "raw", t.output))
    except Exception as e:
        for q in questions:
            answers.setdefault(str(q["qid"]), f"ADAPTER_ERROR: {e}")
    Path(a.out).write_text(json.dumps(answers, ensure_ascii=False, indent=2),
                           encoding="utf-8")
    print("crewai adapter done")


if __name__ == "__main__":
    main()
