"""ADAPTER TEMPLATE — copy to run_<yourname>.py and fill the two marked spots.

The harness contract (see docs/ADAPTER_CONTRACT.md):

  python run_<name>.py  setup|run  --task-dir D --workspace W --home H --out F

  setup   prepare anything your framework needs INSIDE the sandbox
          (most frameworks: nothing — the harness already copied the task
          corpus into W). Whatever exists after setup counts as BASELINE,
          not as footprint.
  run     answer every question in D/questions.json using your agent,
          write {"<qid>": "<answer text>", ...} to F.

  Environment provided by the harness:
    FOOTPRINT_MODEL      backend model string (from frameworks.yaml)
    OPENROUTER_API_KEY / OPENAI_API_KEY
    FOOTPRINT_WORKSPACE  absolute path of W (for your file tools)
    FOOTPRINT_ABLATION   "1" => run with persistence DISABLED (optional)
    FOOTPRINT_TOOLSET    "rw" => also expose write_file (write-task suite)
    HOME / XDG_*         redirected into the sandbox — write state anywhere
                         your framework normally would; the meter sees it.

  Rules:
    - Use your framework's CANONICAL persistence configuration (what its
      docs teach for durable sessions). Do not tune for storage.
    - Keep one continuous session across the questions of a task.
    - Catch per-question exceptions; write "ADAPTER_ERROR: ..." as the
      answer and continue.
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
        print("setup done (no-op)")
        return

    ws = Path(a.workspace).resolve()

    # ---- tool implementations shared by all adapters -----------------
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
    ablation = os.environ.get("FOOTPRINT_ABLATION") == "1"

    # ---- (1) BUILD YOUR AGENT here ------------------------------------
    # model = os.environ["FOOTPRINT_MODEL"]
    # api_key = os.environ["OPENROUTER_API_KEY"]
    # agent = YourFramework(model=model, tools=tools,
    #                       persistence=None if ablation else CANONICAL_STORE)
    raise NotImplementedError("(1) build your agent")

    # ---- (2) ANSWER THE QUESTIONS with one continuous session ---------
    questions = json.loads(
        (Path(a.task_dir) / "questions.json").read_text(encoding="utf-8"))
    answers = {}
    for q in questions:
        try:
            # answers[str(q["qid"])] = str(agent.run(q["question"]))
            raise NotImplementedError("(2) run your agent")
        except Exception as e:
            answers[str(q["qid"])] = f"ADAPTER_ERROR: {e}"
    Path(a.out).write_text(json.dumps(answers, ensure_ascii=False, indent=2),
                           encoding="utf-8")
    print("adapter done")


if __name__ == "__main__":
    main()
