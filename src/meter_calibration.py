"""Meter 校准：已知重复率的合成库 -> D / echo 检出核对（审稿 Q7）。

每个场景一个沙箱：workspace/source.txt（探针来源，40KB 确定性文本），
home/ 下放构造的持久化库。snapshot 在放库之前，measure 之后，
因此 retained = 构造库本身，ground truth 完全已知。

场景（10 个 4KB 块 = source 的连续切片）：
  jsonl-exact    每块 5 份 JSONL 行                 D_true=5   echo_exp≈5
  sqlite-exact   同上但入 SQLite 单元               D_true=5   echo_exp≈5（raw 天真 CDC 应 ≈1）
  esc-jsonl      json.dumps 单层转义嵌入            D_true=5   echo_exp≈5（转义探针形态）
  dbl-esc        双层 json.dumps                    D_true=5   echo_exp≈5（子串包含）
  near-dup       每份复制随机改 1% 字节             内容冗余 5×，精确匹配 D 预期≈1（已知边界）
  zlib-prefix    第 k 轮存 zlib(前 k 块拼接)        逻辑冗余 5.5×，压缩后不可见（已知边界）
  small-lines    400 字符切片 ×8 份 JSONL           D_true=8（验证 < CDC_MIN 整流哈希路径）
"""

from __future__ import annotations

import json
import random
import shutil
import sqlite3
import sys
import zlib
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import meter  # noqa: E402

ROOT = HERE.parent
CAL = ROOT / "experiments" / "calibration"

WORDS = ("ledger manifest carrier intake registry corridor lattice beacon "
         "harbor quorum salient vector plumage granite meridian osprey "
         "kestrel bastion cadence fulcrum").split()


def make_source() -> str:
    rng = random.Random(20260710)
    lines = []
    while sum(len(l) + 1 for l in lines) < 40960:
        lines.append(" ".join(rng.choice(WORDS) for _ in range(12)) + ".")
    return "\n".join(lines)[:40960]


def sandbox(name: str) -> Path:
    sb = CAL / name
    if sb.exists():
        shutil.rmtree(sb)
    (sb / "workspace").mkdir(parents=True)
    (sb / "home").mkdir()
    return sb


def measure_scene(name: str, build) -> dict:
    sb = sandbox(name)
    src = make_source()
    (sb / "workspace" / "source.txt").write_text(src, encoding="utf-8")
    meter.snapshot(sb, sb / "baseline.json")
    build(sb / "home", src)
    rep = meter.measure(sb, sb / "baseline.json")
    # 天真 raw-file CDC：把每个留存文件当单一字节流
    uniq: dict[str, int] = {}
    total = 0
    for f in sorted((sb / "home").rglob("*")):
        if f.is_file():
            data = f.read_bytes()
            total += len(data)
            for h, ln in meter.chunk_stream(data):
                uniq.setdefault(h, ln)
    rep["naive_D"] = round(total / sum(uniq.values()), 2) if uniq else None
    return rep


def blocks_of(src: str, n=10, size=4096) -> list[str]:
    return [src[i * size:(i + 1) * size] for i in range(n)]


def b_jsonl(home: Path, src: str) -> None:
    rows = [json.dumps({"content": b}, ensure_ascii=False)
            for b in blocks_of(src) for _ in range(5)]
    (home / "store.jsonl").write_text("\n".join(rows), encoding="utf-8")


def b_sqlite(home: Path, src: str) -> None:
    db = sqlite3.connect(home / "store.db")
    db.execute("create table msgs (id integer primary key, content text)")
    for b in blocks_of(src):
        for _ in range(5):
            db.execute("insert into msgs (content) values (?)", (b,))
    db.commit()
    db.close()


def b_esc(home: Path, src: str) -> None:
    rows = [json.dumps({"payload": json.dumps({"content": b})})
            for b in blocks_of(src) for _ in range(5)]
    (home / "store.jsonl").write_text("\n".join(rows), encoding="utf-8")


def b_dbl(home: Path, src: str) -> None:
    rows = []
    for b in blocks_of(src):
        inner = json.dumps({"content": b})
        outer = json.dumps({"wrapped": json.dumps({"payload": inner})})
        rows.extend([outer] * 5)
    (home / "store.jsonl").write_text("\n".join(rows), encoding="utf-8")


def b_neardup(home: Path, src: str) -> None:
    rng = random.Random(7)
    rows = []
    for b in blocks_of(src):
        for _ in range(5):
            chars = list(b)
            for _ in range(len(chars) // 100):          # 1% 字节改动
                chars[rng.randrange(len(chars))] = rng.choice("abcdefgh")
            rows.append(json.dumps({"content": "".join(chars)},
                                   ensure_ascii=False))
    (home / "store.jsonl").write_text("\n".join(rows), encoding="utf-8")


def b_zlib(home: Path, src: str) -> None:
    bl = blocks_of(src)
    db = sqlite3.connect(home / "store.db")
    db.execute("create table snaps (id integer primary key, blob blob)")
    for k in range(1, 11):                              # 增长前缀，逐轮压缩
        db.execute("insert into snaps (blob) values (?)",
                   (zlib.compress("".join(bl[:k]).encode()),))
    db.commit()
    db.close()


def b_small(home: Path, src: str) -> None:
    slices = [src[i * 400:(i + 1) * 400] for i in range(100)]
    rows = [json.dumps({"line": s}, ensure_ascii=False)
            for s in slices for _ in range(8)]
    (home / "store.jsonl").write_text("\n".join(rows), encoding="utf-8")


SCENES = [
    ("single-esc",   b_jsonl,   5.0, "5.0"),   # json.dumps 单层转义
    ("sqlite-exact", b_sqlite,  5.0, "5.0"),
    ("double-esc",   b_esc,     5.0, "part"),  # JSON-in-JSON
    ("triple-esc",   b_dbl,     5.0, "part"),
    ("near-dup",     b_neardup, 1.0, "--"),   # 内容冗余5×但非精确；D 期望≈1（边界）
    ("zlib-prefix",  b_zlib,    1.0, "0.0"),  # 逻辑冗余5.5×压缩隐藏；echo 期望 0（边界）
    ("small-lines",  b_small,   8.0, "--"),
]


def main() -> None:
    CAL.mkdir(parents=True, exist_ok=True)
    results = {}
    print("| scenario | D_true | D_meas | naive_D | echo_exp | echo_meas | C |")
    print("|---|---|---|---|---|---|---|")
    for name, build, d_true, echo_exp in SCENES:
        rep = measure_scene(name, build)
        results[name] = rep
        print(f"| {name} | {d_true} | {rep['D']} | {rep['naive_D']} | "
              f"{echo_exp} | {rep['echo_copies']} | {rep['C']} |")
    (CAL / "calibration_report.json").write_text(
        json.dumps(results, indent=2, default=str), encoding="utf-8")


if __name__ == "__main__":
    main()
