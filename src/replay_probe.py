"""R 可重放/审计分（0–3）自动打分器（rubric 见 docs/01 §2 指标 6）。

问题："仅凭留存物能否重建第 k 步模型确切看到了什么？"
自动证据 + 规则打分（正式版仍需人工抽查复核，脚本输出证据便于复核）：

  E1 per-call 结构：留存物中有无逐 LLM 调用的记录（llm_debug 行 / checkpoint 行 /
     事件日志行 / 状态快照文件数）
  E2 指令覆盖：所有用户问题文本能否在留存物中找到
  E3 观测完整性：**行级探针**——从被读文件抽整行（>80 字符），在每个 per-call
     结构文件里以 原始/JSON转义/双重转义 三种形态查找；任一 per-call 文件
     覆盖率 ≥90% 即认定存在完整拷贝（截断/重排/行号包装都不影响行级匹配）

  R=0 无任务归因留存物
  R=1 有留存但无 per-call 结构（只能大致知道发生过什么）
  R=2 有 per-call 结构但无任何完整观测拷贝（逻辑可重建，非精确）
  R=3 per-call 结构 + 至少一个通道观测完整（可精确重建第 k 步输入）

用法: python3 replay_probe.py <run_sandbox> [...]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from meter import inventory, is_excluded, is_sqlite, sqlite_streams  # noqa: E402

PER_CALL_HINTS = {
    "llm_debug.jsonl": "per-call debug jsonl",
    "checkpoints": "checkpoint rows",
    "agent_state_q": "per-turn state snapshot",
    "autogen_events": "event log",
    "_actions.json": "action log",
    "raw_io.jsonl": "raw io trace",
    "ctx_q": "per-turn context snapshot",
    "agents_sessions": "session message store",
    "agno_sessions": "session store",
}


def retained(sandbox: Path) -> list[Path]:
    base = json.loads((sandbox / "baseline.json").read_text(encoding="utf-8"))
    out = []
    for layer in ("workspace", "home"):
        root = sandbox / layer
        if not root.exists():
            continue
        before = base[layer]
        for rel, size in inventory(root).items():
            if rel in before and before[rel] == size:
                continue
            if is_excluded(rel):
                continue
            out.append(root / rel)
    return out


def score(sandbox: Path) -> dict:
    files = retained(sandbox)
    meas = json.loads((sandbox / "measurement.json").read_text(encoding="utf-8"))
    task = meas["task"]
    suite = "longhorizon" if task.startswith("lh_") else "file_intensive"
    qfile = sandbox.parents[2].parent / "tasks" / suite / task / "questions.json"
    questions = json.loads(qfile.read_text(encoding="utf-8"))

    if not files:
        return {"framework": meas["framework"], "task": task, "R": 0,
                "evidence": "no task-attributable artifacts retained"}

    # 行级探针：从问题指向的语料文件抽整行
    import random
    import re
    targets = sorted({m for q in questions
                      for m in re.findall(r"records_\w+\.txt|status\.txt",
                                          q["question"])})
    probe_lines: list[str] = []
    rng = random.Random(20260708)
    for t in targets:
        src = qfile.parent / "corpus" / t
        if src.exists():
            lines = [ln for ln in src.read_text(encoding="utf-8").splitlines()
                     if len(ln) > 80]
            probe_lines += rng.sample(lines, min(6, len(lines)))

    def variants(s: str) -> list[bytes]:
        esc = json.dumps(s, ensure_ascii=True)[1:-1]
        esc2 = json.dumps(esc, ensure_ascii=True)[1:-1]
        return [s.encode(), esc.encode(), esc2.encode()]

    def jsonl_structured(data: bytes) -> bool:
        """.jsonl 提示文件的结构门槛：≥3 行可解析为 JSON 对象（防文件名冒充）。"""
        ok = 0
        for ln in data.split(b"\n")[:200]:
            ln = ln.strip()
            if not ln:
                continue
            try:
                if isinstance(json.loads(ln), dict):
                    ok += 1
                    if ok >= 3:
                        return True
            except Exception:
                continue
        return False

    percall: dict[str, float] = {}   # 文件 -> 行探针覆盖率
    allb_parts: list[bytes] = []
    for f in files:
        name = f.name
        is_pc = any(h in name for h in PER_CALL_HINTS) or (
            is_sqlite(f) and ("checkpoint" in name or "sqlite" in name))
        try:
            data = (b"\n".join(sqlite_streams(f)) if is_sqlite(f)
                    else f.read_bytes())
        except OSError:
            continue
        if is_pc and f.suffix in (".jsonl", ".ndjson") and not is_sqlite(f):
            is_pc = jsonl_structured(data)
        allb_parts.append(data)
        if is_pc and probe_lines:
            found = sum(1 for ln in probe_lines
                        if any(v in data for v in variants(ln)))
            percall[name] = round(found / len(probe_lines), 2)
        elif is_pc:
            percall[name] = 0.0
    allb = b"\n".join(allb_parts)

    q_found = sum(1 for q in questions
                  if q["question"][:60].encode() in allb
                  or json.dumps(q["question"][:60], ensure_ascii=True)[1:-1].encode() in allb)
    full = [n for n, cov in percall.items() if cov >= 0.9]

    if not percall:
        r = 1
    elif full:
        r = 3
    else:
        r = 2
    return {
        "framework": meas["framework"], "task": task, "R": r,
        "per_call_coverage": dict(sorted(percall.items(),
                                         key=lambda kv: -kv[1])[:6]),
        "full_copy_channels": full[:3],
        "questions_found": f"{q_found}/{len(questions)}",
    }


def main() -> None:
    out = [score(Path(p).resolve()) for p in sys.argv[1:]]
    print(json.dumps(out, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
