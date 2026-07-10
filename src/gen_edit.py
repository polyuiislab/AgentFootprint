"""Heterogeneous task family 1: file editing / transformation.

Different from file-QA in toolchain (read + write), output form (a corrected
workspace artifact), and objective (transformation, not retrieval). No file
is named as containing "the answer"; no re-read instruction.

Each task: a ledger file with N entries whose DATE: lines use messy formats
(e.g. "March 3, 2026", "03/17/2026", "2026.5.9"). The agent must write a
corrected copy with all dates in ISO YYYY-MM-DD and answer with the latest
(maximum) date in ISO form — a deterministic, unique string. Grading:
answer contains the ISO date; the corrected artifact is checked separately
in analysis (file exists and contains that date).
"""

from __future__ import annotations

import json
import random
from pathlib import Path

HERE = Path(__file__).resolve().parent
TASKS_DIR = HERE.parent / "tasks" / "edit_tasks"

MONTHS = ["January", "February", "March", "April", "May", "June", "July",
          "August", "September", "October", "November", "December"]
FILLER = ("shipment reconciled against manifest pending carrier confirmation "
          "warehouse intake logged supervisor approval attached invoice "
          "cross-checked ledger balance carried forward").split()
N_TASKS = 5


def messy(rng: random.Random, y: int, m: int, d: int) -> str:
    style = rng.randrange(3)
    if style == 0:
        return f"{MONTHS[m-1]} {d}, {y}"
    if style == 1:
        return f"{m:02d}/{d:02d}/{y}"
    return f"{y}.{m}.{d}"


def main() -> None:
    for t in range(N_TASKS):
        rng = random.Random(20260712 + t)
        tdir = TASKS_DIR / f"etask_{t:02d}"
        (tdir / "corpus").mkdir(parents=True, exist_ok=True)
        dates = set()
        while len(dates) < 12:
            dates.add((rng.randint(2024, 2026), rng.randint(1, 12),
                       rng.randint(1, 28)))
        dates = sorted(dates)
        latest = dates[-1]
        iso_latest = f"{latest[0]}-{latest[1]:02d}-{latest[2]:02d}"
        lines = [f"# Shipment ledger {t:02d}\n"]
        for i, (y, m, d) in enumerate(rng.sample(dates, len(dates))):
            lines.append(f"ENTRY {i:03d}")
            lines.append(f"DATE: {messy(rng, y, m, d)}")
            lines.append(" ".join(rng.choice(FILLER) for _ in range(30)) + ".")
            lines.append("")
        (tdir / "corpus" / "ledger.md").write_text("\n".join(lines),
                                                   encoding="utf-8")
        # 陪衬文件（让 agent 需要判断读什么）
        for name in ("notes.md", "contacts.md"):
            (tdir / "corpus" / name).write_text(
                "\n".join(" ".join(rng.choice(FILLER) for _ in range(25)) + "."
                          for _ in range(80)), encoding="utf-8")
        q = {
            "qid": 0,
            "question": (
                "One of the workspace files is a shipment ledger whose DATE: "
                "lines use inconsistent formats. Write a corrected copy named "
                "ledger_fixed.md in which every DATE: line uses ISO "
                "YYYY-MM-DD format, then answer with the latest (most recent) "
                "date in the ledger, in ISO format only."),
            "answer": iso_latest,
            "artifact": "ledger_fixed.md",
        }
        (tdir / "questions.json").write_text(json.dumps([q], indent=2),
                                             encoding="utf-8")
        print(f"etask_{t:02d}: 12 dates, latest={iso_latest}")


if __name__ == "__main__":
    main()
