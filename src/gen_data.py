"""Heterogeneous task family 2: structured data analysis.

Different from file-QA in data type (CSV), required computation (grouped
aggregation across files), and output form (a derived summary artifact).
No file named as "the answer"; no re-read instruction.

Each task: two quarterly sales CSVs (per-region rows). The agent must
aggregate total units per product across both files, write summary.csv
(product,total sorted descending), and answer "<PRODUCT> <TOTAL>" for the
top product — a deterministic, unique string.
"""

from __future__ import annotations

import json
import random
from pathlib import Path

HERE = Path(__file__).resolve().parent
TASKS_DIR = HERE.parent / "tasks" / "data_tasks"

PRODUCTS = ["P-KESTREL", "P-MERLIN", "P-OSPREY", "P-HARRIER", "P-KITE",
            "P-SHRIKE"]
REGIONS = ["north", "south", "east", "west", "central"]
N_TASKS = 5


def main() -> None:
    for t in range(N_TASKS):
        rng = random.Random(20260713 + t)
        tdir = TASKS_DIR / f"dtask_{t:02d}"
        (tdir / "corpus").mkdir(parents=True, exist_ok=True)
        totals = {p: 0 for p in PRODUCTS}
        for qi, fname in enumerate(("sales_q1.csv", "sales_q2.csv")):
            rows = ["product,region,units"]
            for p in PRODUCTS:
                for rgn in REGIONS:
                    u = rng.randint(10, 999)
                    totals[p] += u
                    rows.append(f"{p},{rgn},{u}")
            rng.shuffle(rows[1:])
            (tdir / "corpus" / fname).write_text("\n".join(rows) + "\n",
                                                 encoding="utf-8")
        # 干扰文件
        (tdir / "corpus" / "readme.md").write_text(
            "Quarterly unit sales exports. See CSV files.", encoding="utf-8")
        # 确保唯一最大值
        ranked = sorted(totals.items(), key=lambda kv: -kv[1])
        if ranked[0][1] == ranked[1][1]:
            totals[ranked[0][0]] += 7  # 打破并列（写回 q2 文件尾行）
            with open(tdir / "corpus" / "sales_q2.csv", "a", encoding="utf-8") as f:
                f.write(f"{ranked[0][0]},north,7\n")
            ranked = sorted(totals.items(), key=lambda kv: -kv[1])
        top, tot = ranked[0]
        q = {
            "qid": 0,
            "question": (
                "The workspace contains quarterly sales CSV exports. Compute "
                "the total units per product across all quarters, write a "
                "file summary.csv with header 'product,total' sorted by total "
                "descending, and answer with the top product and its total in "
                "the exact form 'PRODUCT TOTAL' (single space separated)."),
            "answer": f"{top} {tot}",
            "artifact": "summary.csv",
        }
        (tdir / "questions.json").write_text(json.dumps([q], indent=2),
                                             encoding="utf-8")
        print(f"dtask_{t:02d}: top={top} {tot}")


if __name__ == "__main__":
    main()
