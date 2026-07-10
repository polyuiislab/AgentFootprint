"""生产环境存储足迹采集器（在生产主机上运行；输出不含任何内容字节）。

用途：为论文补充真实生产 runtime footprint 证据（审稿 R1-2/R2-M7）
与工作负载画像（R2-M4 代表性）。

脱敏设计（白名单输出，先天无内容）：
  - 只输出：尺寸、文件数、扩展名、通道类别、粗化月份、行数/调用计数；
  - 任务目录名 -> 顺序化名 task_0001...（映射不落盘）；
  - 路径只保留通道分类结果，不保留原始路径/文件名；
  - 日志仅统计行数与角色/工具名计数（工具名是通用词如 file_read），
    绝不读取 content 字段的值；
  - 输出为单个 JSON，先自查（任何字符串值长度 <= 40）再写出，供人工过目。

用法（在生产机上，python3 即可，无第三方依赖）：
  python3 prod_collector.py --root /path/to/infiagent/user_root \
      --out prod_footprint.json
可多次运行于不同部署（juepei/chatbi 等），--label 区分。
"""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

CHANNEL_RULES = [  # (子串, 通道)
    ("raw_io", "raw_trace"),
    ("llm_debug", "debug_log"),
    ("conversation", "conversation"),
    ("training_traces", "trajectory"),
    ("agent_library", "config"),
    ("config", "config"),
    ("logs", "service_log"),
    ("tasks", "task_store"),
]
SAFE_TOOL_KEYS = ("tool", "tool_name", "role", "type", "event", "kind",
                  "debug_label", "direction", "method", "finish_reason")
NEVER_DESCEND = ("content", "arguments", "text", "prompt", "output",
                 "observation", "result", "data", "payload_text")


def channel_of(rel: str) -> str:
    low = rel.lower()
    for key, ch in CHANNEL_RULES:
        if key in low:
            return ch
    return "other"


def month_of(p: Path) -> str:
    try:
        return datetime.fromtimestamp(p.stat().st_mtime).strftime("%Y-%m")
    except OSError:
        return "unknown"


def _extract_safe(obj, out: Counter, depth: int = 0) -> None:
    """有界递归提取白名单键；内容类键（content/arguments/...）永不下潜。"""
    if depth > 4:
        return
    if isinstance(obj, dict):
        for k, v in obj.items():
            kl = str(k).lower()
            if kl in NEVER_DESCEND:
                continue
            if kl in SAFE_TOOL_KEYS and isinstance(v, str) and len(v) <= 40:
                out[f"{kl}:{v}"] += 1
            elif kl == "function" and isinstance(v, dict):
                name = v.get("name")
                if isinstance(name, str) and len(name) <= 40:
                    out[f"tool:{name}"] += 1
            elif isinstance(v, (dict, list)):
                _extract_safe(v, out, depth + 1)
    elif isinstance(obj, list):
        for v in obj[:50]:
            _extract_safe(v, out, depth + 1)


def jsonl_stats(p: Path, max_lines: int = 200000) -> dict:
    """只统计行数与白名单字段计数；从不读取内容字段的值。"""
    counts: Counter = Counter()
    n = 0
    try:
        with open(p, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                n += 1
                if n > max_lines:
                    break
                line = line.strip()
                if not line.startswith("{"):
                    continue
                try:
                    obj = json.loads(line)
                except Exception:
                    continue
                _extract_safe(obj, counts)
    except OSError:
        pass
    return {"lines": n, "field_counts": dict(counts.most_common(30))}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True, help="InfiAgent user_root 或数据根目录")
    ap.add_argument("--out", default="prod_footprint.json")
    ap.add_argument("--label", default="deployment-1", help="部署代号（自拟，勿含真实系统名）")
    a = ap.parse_args()
    root = Path(a.root).resolve()

    tasks: dict = {}
    task_ids: dict = {}
    global_logs: list = []
    global_channels = defaultdict(lambda: {"files": 0, "bytes": 0})
    months: Counter = Counter()

    for p in root.rglob("*"):
        if not p.is_file() or p.is_symlink():
            continue
        rel = str(p.relative_to(root))
        parts = rel.split("/")
        # 任务桶：tasks/<id>/... 归任务；其余归全局
        tkey = None
        if len(parts) >= 2 and parts[0] == "tasks":
            raw = parts[1]
            if raw not in task_ids:
                task_ids[raw] = f"task_{len(task_ids)+1:04d}"
            tkey = task_ids[raw]
        try:
            size = p.stat().st_size
        except OSError:
            continue
        ch = channel_of(rel)
        ext = (p.suffix or "(none)")[:12]
        months[month_of(p)] += 1
        global_channels[ch]["files"] += 1
        global_channels[ch]["bytes"] += size
        if tkey:
            t = tasks.setdefault(tkey, {"bytes": 0, "files": 0,
                                        "by_channel": defaultdict(int),
                                        "by_ext": defaultdict(int)})
            t["bytes"] += size
            t["files"] += 1
            t["by_channel"][ch] += size
            t["by_ext"][ext] += size
        # 日志画像（行数/白名单字段计数，无内容）
        if p.name.endswith((".jsonl", ".ndjson")) and size < 200 * 1024 * 1024:
            stats = {"channel": ch, **jsonl_stats(p)}
            if tkey:
                tasks[tkey].setdefault("log_stats", []).append(stats)
            else:
                global_logs.append(stats)

    sizes = sorted(t["bytes"] for k, t in tasks.items() if k.startswith("task_"))
    def pct(q):
        return sizes[min(len(sizes) - 1, int(q * len(sizes)))] if sizes else 0
    report = {
        "label": a.label,
        "collector_version": "1.1",
        "n_tasks": len([k for k in tasks if k.startswith("task_")]),
        "task_bytes_percentiles": {p_: pct(q) for p_, q in
                                   [("p10", .1), ("p50", .5), ("p90", .9),
                                    ("p99", .99)]},
        "task_bytes_total": sum(sizes),
        "global_channels": {k: dict(v) for k, v in global_channels.items()},
        "global_log_stats": global_logs[:50],
        "months_active": dict(months.most_common(24)),
        "tasks": {k: {"bytes": t["bytes"], "files": t["files"],
                      "by_channel": dict(t["by_channel"]),
                      "by_ext": dict(t["by_ext"]),
                      **({"log_stats": t["log_stats"]} if "log_stats" in t else {})}
                  for k, t in sorted(tasks.items())},
    }

    # 自查：白名单键之外不允许长字符串（防内容泄漏）
    def audit(o):
        if isinstance(o, dict):
            for k, v in o.items():
                assert len(str(k)) <= 60, f"long key: {k[:80]}"
                audit(v)
        elif isinstance(o, list):
            for v in o:
                audit(v)
        elif isinstance(o, str):
            assert len(o) <= 40, f"long string value: {o[:80]}"
    audit(report)

    Path(a.out).write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"tasks={report['n_tasks']} total={report['task_bytes_total']/1048576:.1f}MB "
          f"p50={report['task_bytes_percentiles']['p50']/1024:.0f}KB -> {a.out}")
    print("请人工检查输出 JSON 后再带出生产环境。")


if __name__ == "__main__":
    main()
