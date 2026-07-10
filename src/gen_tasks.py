"""生成文件密集型任务（任务层 2，docs/01 §3）。

每个任务：10 个部门档案文件（各 ~60KB，确定性伪随机文本），5 个事实性问题。
问题按 [A,B,A,C,A] 模式指向文件——同一文件被要求反复核读，直接激发
"重复读取放大"（agent 被指示每次答题前必须重新读文件核实）。

全部内容由 seed 决定，可一键复现；答案是唯一随机码，判分 = 子串匹配。
"""

from __future__ import annotations

import json
import random
import string
from pathlib import Path

HERE = Path(__file__).resolve().parent
TASKS_DIR = HERE.parent / "tasks" / "file_intensive"

DEPTS = ["algol", "briar", "cobalt", "dorian", "ember",
         "fjord", "garnet", "harbor", "indigo", "juniper"]

WORDS = ("ledger audit fiscal quarter variance procurement vendor invoice "
         "compliance retention archive manifest liaison directive threshold "
         "allocation reconcile deferral amortize custodial oversight remit "
         "tranche escrow disbursement covenant subsidiary consolidated").split()

N_TASKS = 10
FILE_KB = 60
FACTS_PER_FILE = 3
# 每题指向的文件下标：A,B,A,C,A —— 文件 A 被读 3 次
Q_PATTERN = [0, 1, 0, 2, 0]


def para(rng: random.Random, n: int) -> str:
    return " ".join(rng.choice(WORDS) for _ in range(n)).capitalize() + "."


def code(rng: random.Random) -> str:
    return ("QX-" + "".join(rng.choices(string.digits, k=5)) + "-"
            + "".join(rng.choices(string.ascii_uppercase, k=2)))


def build_file(rng: random.Random, dept: str) -> tuple[str, dict[str, str]]:
    """生成一个部门档案；返回 (文本, {fact_key: code})。"""
    facts = {}
    blocks = []
    target = FILE_KB * 1024
    fact_keys = ["procurement-code", "audit-token", "escrow-id"][:FACTS_PER_FILE]
    size = 0
    i = 0
    while size < target:
        blocks.append(f"## Section {i}: {dept} operations memo\n" + para(rng, 90) + "\n")
        size = sum(len(b) for b in blocks)
        i += 1
    # 事实行插进中部的确定性位置
    for j, key in enumerate(fact_keys):
        c = code(rng)
        facts[key] = c
        pos = (j + 1) * len(blocks) // (len(fact_keys) + 1)
        blocks.insert(pos, f"REGISTRY-ENTRY {key}[{dept}]: {c}\n")
    return "\n".join(blocks), facts


def main() -> None:
    for t in range(N_TASKS):
        rng = random.Random(20260708 + t)
        tdir = TASKS_DIR / f"task_{t:02d}"
        (tdir / "corpus").mkdir(parents=True, exist_ok=True)
        all_facts = {}
        depts = DEPTS.copy()
        rng.shuffle(depts)
        for dept in depts:
            text, facts = build_file(rng, dept)
            (tdir / "corpus" / f"records_{dept}.txt").write_text(text, encoding="utf-8")
            all_facts[dept] = facts

        target_depts = [depts[i] for i in Q_PATTERN]
        keys = ["procurement-code", "audit-token", "escrow-id",
                "procurement-code", "audit-token"]
        questions = []
        for qi, (dept, key) in enumerate(zip(target_depts, keys)):
            questions.append({
                "qid": qi,
                "question": (f"Open and read the file records_{dept}.txt in the workspace "
                             f"(you MUST re-read the file now to verify, even if you have seen it "
                             f"before) and report the exact value of REGISTRY-ENTRY "
                             f"{key}[{dept}]. Answer with the code only."),
                "answer": all_facts[dept][key],
            })
        (tdir / "questions.json").write_text(
            json.dumps(questions, indent=2), encoding="utf-8")
        total = sum(f.stat().st_size for f in (tdir / "corpus").iterdir())
        print(f"task_{t:02d}: corpus {total/1024:.0f}KB, {len(questions)} questions")


if __name__ == "__main__":
    main()
