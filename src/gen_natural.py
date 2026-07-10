"""Natural-workload suite (external-validity check).

Differences from the file-QA stress suite, by design:
  - questions do NOT name the file that contains the answer (the agent must
    explore via list_files);
  - no "you MUST re-read" instruction anywhere;
  - the three questions of a task target three DIFFERENT files (no forced
    revisits);
  - documents read like project notes/specs/minutes rather than registries.

Facts keep the REGISTRY-ENTRY marker inside otherwise natural prose so that
grading stays exact-substring and framework prompts stay unchanged.
5 tasks x 6 files (~40KB each) x 3 questions.
"""

from __future__ import annotations

import json
import random
import string
from pathlib import Path

HERE = Path(__file__).resolve().parent
TASKS_DIR = HERE.parent / "tasks" / "natural"

TOPICS = ["kickoff-minutes", "product-spec", "risk-register",
          "vendor-review", "budget-memo", "retro-notes"]
WORDS = ("roadmap milestone stakeholder deliverable dependency onboarding "
         "backlog sprint retro action item procurement vendor budget "
         "headcount review launch readiness risk mitigation escalation "
         "timeline scope tradeoff alignment sync followup").split()
ASPECTS = {
    "kickoff-minutes": ("the budget code approved at the project kickoff",
                        "budget code"),
    "product-spec": ("the tracking id assigned to the storage requirement",
                     "tracking id"),
    "risk-register": ("the mitigation ticket opened for the top schedule risk",
                      "mitigation ticket"),
    "vendor-review": ("the contract reference chosen for the selected vendor",
                      "contract reference"),
    "budget-memo": ("the cost-center code the memo allocates the overrun to",
                    "cost-center code"),
    "retro-notes": ("the action-item id raised for documentation debt",
                    "action-item id"),
}
FILE_KB = 40
N_TASKS = 5


def para(rng: random.Random, n: int) -> str:
    return " ".join(rng.choice(WORDS) for _ in range(n)).capitalize() + "."


def code(rng: random.Random) -> str:
    return ("QX-" + "".join(rng.choices(string.digits, k=5)) + "-"
            + "".join(rng.choices(string.ascii_uppercase, k=2)))


def main() -> None:
    for t in range(N_TASKS):
        rng = random.Random(20260711 + t)
        tdir = TASKS_DIR / f"ntask_{t:02d}"
        (tdir / "corpus").mkdir(parents=True, exist_ok=True)
        facts = {}
        for topic in TOPICS:
            c = code(rng)
            facts[topic] = c
            blocks = [f"# Project Aurora — {topic.replace('-', ' ')}\n"]
            while sum(len(b) for b in blocks) < FILE_KB * 1024:
                blocks.append(para(rng, 80) + "\n")
            pos = rng.randint(len(blocks) // 3, 2 * len(blocks) // 3)
            blocks.insert(pos, f"REGISTRY-ENTRY {ASPECTS[topic][1]}: {c}\n")
            (tdir / "corpus" / f"aurora_{topic}.md").write_text(
                "\n".join(blocks), encoding="utf-8")

        # 3 个问题指向 3 个不同文件，不点名文件，不要求重读
        picked = rng.sample(TOPICS, 3)
        questions = [{
            "qid": qi,
            "question": (f"You are helping with Project Aurora. Looking through "
                         f"the project documents in the workspace, what is "
                         f"{ASPECTS[topic][0]}? Answer with the code only."),
            "answer": facts[topic],
        } for qi, topic in enumerate(picked)]
        (tdir / "questions.json").write_text(json.dumps(questions, indent=2),
                                             encoding="utf-8")
        total = sum(f.stat().st_size for f in (tdir / "corpus").iterdir())
        print(f"ntask_{t:02d}: corpus {total/1024:.0f}KB, 3 questions, "
              f"targets={picked}")


if __name__ == "__main__":
    main()
