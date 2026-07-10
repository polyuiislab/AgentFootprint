"""R 自动打分器构念验证（审稿 round-4 W3 / Q3）。

用真实 task_00 语料构造 7 类合成留存物，检验自动 rubric 的判定边界：
哪些构念缺陷会被放过（FP）、哪些会被正确拦截。结论进论文附录——
自动分是"内容完整性筛查"（通道识别依赖逐框架人工审计的文件名先验），
顺序/参数/调用边界的确证由 65-call 重建与 resume 探针承担。
"""

from __future__ import annotations

import json
import random
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
import replay_probe  # noqa: E402

TASK = "task_00"
TDIR = ROOT / "tasks" / "file_intensive" / TASK
OUT = ROOT / "experiments" / "r_validation"


def corpus_texts() -> dict[str, str]:
    qs = json.loads((TDIR / "questions.json").read_text(encoding="utf-8"))
    import re
    names = sorted({m for q in qs
                    for m in re.findall(r"records_\w+\.txt", q["question"])})
    return {n: (TDIR / "corpus" / n).read_text(encoding="utf-8") for n in names}


def percall_lines(texts: dict[str, str], *, order_shuffle=False,
                  strip_args=False, truncate=None, summary_only=False) -> str:
    """模拟逐调用记录：每次'调用'一行 JSON（role/tool_call/observation）。"""
    calls = []
    for i, (name, text) in enumerate(sorted(texts.items())):
        obs = (f"summary of {name}: {len(text)} chars" if summary_only
               else (text[:truncate] if truncate else text))
        call = {"call": i, "role": "assistant",
                "tool_call": {"name": "read_file",
                              "arguments": None if strip_args
                              else {"filename": name}},
                "observation": obs}
        calls.append(json.dumps(call, ensure_ascii=False))
    if order_shuffle:
        random.Random(7).shuffle(calls)
    return "\n".join(calls)


CASES = [
    # (名字, 店文件名, 内容构造, 构念判断应为, 说明)
    ("true-percall", "llm_debug.jsonl",
     lambda t: percall_lines(t), 3, "真逐调用记录+完整观测"),
    ("aggregate-hintname", "llm_debug.jsonl",
     lambda t: "\n\n".join(t.values()), 1, "纯观测聚合、无逐调用结构，但文件名命中提示"),
    ("aggregate-neutral", "observations_dump.txt",
     lambda t: "\n\n".join(t.values()), 1, "同上但中性文件名"),
    ("shuffled-order", "llm_debug.jsonl",
     lambda t: percall_lines(t, order_shuffle=True), "3*", "逐调用但顺序打乱"),
    ("missing-args", "llm_debug.jsonl",
     lambda t: percall_lines(t, strip_args=True), "3*", "逐调用但工具参数缺失"),
    ("truncated-obs", "llm_debug.jsonl",
     lambda t: percall_lines(t, truncate=100), 2, "逐调用但观测截断"),
    ("summary-only", "llm_debug.jsonl",
     lambda t: percall_lines(t, summary_only=True), 2, "逐调用但只有摘要"),
]


def main() -> None:
    texts = corpus_texts()
    print("| case | intended | auto R | verdict | note |")
    print("|---|---|---|---|---|")
    rows = []
    for name, store, build, intended, note in CASES:
        sb = OUT / name / TASK
        if sb.parent.exists():
            shutil.rmtree(sb.parent)
        (sb / "workspace").mkdir(parents=True)
        (sb / "home").mkdir()
        (sb / "baseline.json").write_text(
            json.dumps({"workspace": {}, "home": {}, "probes": []}),
            encoding="utf-8")
        (sb / "measurement.json").write_text(
            json.dumps({"framework": name, "task": TASK}), encoding="utf-8")
        (sb / "home" / store).write_text(build(texts), encoding="utf-8")
        r = replay_probe.score(sb)["R"]
        exp = intended if isinstance(intended, int) else 3
        verdict = ("OK" if r == exp else
                   ("FP (over-grade)" if r > (2 if isinstance(intended, str)
                                              else intended) else "FN"))
        if isinstance(intended, str):   # 3*：内容在、构念弱——自动分放过属预期披露项
            verdict = "insensitive (disclosed)"
        rows.append((name, intended, r, verdict, note))
        print(f"| {name} | {intended} | {r} | {verdict} | {note} |")
    (OUT / "validation_report.json").write_text(
        json.dumps([{"case": c, "intended": i, "auto_R": r,
                     "verdict": v, "note": n} for c, i, r, v, n in rows],
                   indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nreport -> {OUT/'validation_report.json'}")


if __name__ == "__main__":
    main()
