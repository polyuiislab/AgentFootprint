"""Agno 适配器：官方 storage quickstart 形态（Agent + SqliteStorage/Db + 会话历史）。

Agno 版本间 storage API 有漂移（storage= vs db=），运行时探测两种形态。
消融：不配 storage → 无落盘。
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
        print("agno setup done (no-op)")
        return

    ws = Path(a.workspace).resolve()
    home = Path(a.home).resolve()
    ablation = os.environ.get("FOOTPRINT_ABLATION") == "1"

    from agno.agent import Agent
    from agno.models.openrouter import OpenRouter

    def list_files() -> str:
        """List the files available in the workspace."""
        return "\n".join(sorted(p.name for p in ws.iterdir() if p.is_file()))

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

    kwargs = {}
    if not ablation:
        db_file = str(home / "agno_sessions.sqlite")
        try:  # 新形态（agno>=2）：db=SqliteDb
            from agno.db.sqlite import SqliteDb
            kwargs["db"] = SqliteDb(db_file=db_file)
            kwargs["add_history_to_context"] = True
        except ImportError:  # 旧形态：storage=SqliteStorage
            from agno.storage.sqlite import SqliteStorage
            kwargs["storage"] = SqliteStorage(table_name="sessions",
                                              db_file=db_file)
            kwargs["add_history_to_messages"] = True

    agent = Agent(
        model=OpenRouter(id=os.environ["FOOTPRINT_MODEL"],
                         base_url=os.environ.get("FOOTPRINT_BASE_URL", "https://openrouter.ai/api/v1"),
                         api_key=os.environ["OPENROUTER_API_KEY"],
                         temperature=0),
        tools=tools,
        instructions=("You are a document QA assistant. Verify answers by "
                      "reading workspace files with the tools before answering. "
                      "Answer with the exact requested value only."),
        session_id="session-1",
        markdown=False,
        **kwargs,
    )

    questions = json.loads(
        (Path(a.task_dir) / "questions.json").read_text(encoding="utf-8"))
    answers = {}
    for q in questions:
        try:
            r = agent.run(q["question"])
            answers[str(q["qid"])] = str(getattr(r, "content", r))
        except Exception as e:
            answers[str(q["qid"])] = f"ADAPTER_ERROR: {e}"
    Path(a.out).write_text(json.dumps(answers, ensure_ascii=False, indent=2),
                           encoding="utf-8")
    print("agno adapter done")


if __name__ == "__main__":
    main()
