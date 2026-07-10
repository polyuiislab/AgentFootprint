"""存储足迹测量核心 v2：物理字节 + 逻辑内容双层分析。

物理层（你为之付费的字节）：
  S_total   任务归因总字节（运行后新增/变更文件，workspace + home）
  C         zstd -19 长窗口可压缩率

逻辑层（这些字节里装了什么——修正序列化伪装）：
  - sqlite 文件按 cell 提取（blob 被分页存储，裸字节 CDC 对不齐块边界）
  - .jsonl 按行、其余文件整体作为逻辑流
  D         重复因子 = 逻辑流总字节 / CDC 去重后唯一字节
  echo      内容探针：从任务 workspace 输入文件抽定长子串，在留存物中数出现次数
            （同时匹配原始形态与 JSON 转义形态），均值 = 输入内容平均被存几遍

口径（docs/01 §2）：只算任务归因字节；模型权重/分词器缓存/pip 缓存排除，
被排除字节单独报告（excluded_bytes）。
"""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import sqlite3
from pathlib import Path

import zstandard
from fastcdc import fastcdc

CDC_MIN, CDC_AVG, CDC_MAX = 1024, 4096, 32768
PROBE_LEN = 72          # 探针长度（字符）
PROBES_PER_FILE = 12    # 每个输入文件的探针数

DEFAULT_EXCLUDES = [
    "*/tiktoken*", "*tiktoken_cache*",
    "*/.cache/huggingface/*", "*/huggingface/hub/*",
    "*/.cache/pip/*", "*/pip/cache/*",
    "*/__pycache__/*", "*.pyc",
    "*/.cache/uv/*",
]


def is_excluded(rel: str) -> bool:
    r = "/" + rel
    return any(fnmatch.fnmatch(r, pat) or fnmatch.fnmatch(rel, pat) for pat in DEFAULT_EXCLUDES)


def inventory(root: Path) -> dict:
    inv = {}
    if not root.exists():
        return inv
    for p in root.rglob("*"):
        try:
            if p.is_file() and not p.is_symlink():
                inv[str(p.relative_to(root))] = p.stat().st_size
        except OSError:
            continue
    return inv


def file_sha(path: Path) -> str:
    h = hashlib.sha256()
    try:
        with open(path, "rb") as f:
            while True:
                buf = f.read(1 << 20)
                if not buf:
                    break
                h.update(buf)
    except OSError:
        return ""
    return h.hexdigest()


def inventory_hashed(root: Path) -> dict:
    """v3 基线：rel -> {size, sha}。哈希判变更（尺寸相同的原地改写也能捕获）。"""
    inv = {}
    if not root.exists():
        return inv
    for p in root.rglob("*"):
        try:
            if p.is_file() and not p.is_symlink():
                inv[str(p.relative_to(root))] = {
                    "size": p.stat().st_size, "sha": file_sha(p)}
        except OSError:
            continue
    return inv


def _base_entry(v):
    """兼容 v2 基线（rel->size 整数）与 v3 基线（rel->{size,sha}）。"""
    if isinstance(v, dict):
        return v.get("size", 0), v.get("sha", "")
    return v, ""


# ---------- 逻辑流提取 ----------

def is_sqlite(path: Path) -> bool:
    try:
        with open(path, "rb") as f:
            return f.read(16).startswith(b"SQLite format 3")
    except OSError:
        return False


def sqlite_streams(path: Path, min_len: int = 64) -> list[bytes]:
    """每个表格 cell（bytes/str 且 >min_len）作为一个逻辑流。"""
    out: list[bytes] = []
    try:
        con = sqlite3.connect(f"file:{path}?mode=ro&immutable=1", uri=True)
        con.text_factory = bytes
        tables = [r[0] for r in con.execute(
            "select name from sqlite_master where type='table'")]
        for t in tables:
            try:
                for row in con.execute(f'select * from "{t.decode() if isinstance(t, bytes) else t}"'):
                    for v in row:
                        if isinstance(v, (bytes, memoryview)):
                            b = bytes(v)
                        elif isinstance(v, str):
                            b = v.encode("utf-8", "replace")
                        else:
                            continue
                        if len(b) > min_len:
                            out.append(b)
            except sqlite3.Error:
                continue
        con.close()
    except sqlite3.Error:
        return [path.read_bytes()]
    return out or [path.read_bytes()]


def streams_of(path: Path, min_len: int = 64) -> list[bytes]:
    """文件 -> 逻辑流列表。sqlite 按 cell；jsonl 按行；其余整文件。"""
    try:
        if is_sqlite(path):
            return sqlite_streams(path, min_len)
        data = path.read_bytes()
    except OSError:
        return []
    if path.suffix in (".jsonl", ".ndjson") and b"\n" in data:
        return [ln for ln in data.split(b"\n") if len(ln) > min_len] or [data]
    return [data] if data else []


def chunk_stream(data: bytes) -> list[tuple[str, int]]:
    if len(data) <= CDC_MIN:
        return [(hashlib.sha256(data).hexdigest(), len(data))] if data else []
    try:
        return [(c.hash, c.length)
                for c in fastcdc(data, CDC_MIN, CDC_AVG, CDC_MAX, fat=False, hf=hashlib.sha256)]
    except Exception:
        return [(hashlib.sha256(data).hexdigest(), len(data))]


def chunk_file(path: Path) -> tuple[list[tuple[str, int]], int]:
    """(chunks, 逻辑字节总数)。"""
    chunks: list[tuple[str, int]] = []
    total = 0
    for s in streams_of(path):
        total += len(s)
        chunks.extend(chunk_stream(s))
    return chunks, total


# ---------- 探针 ----------

def make_probes(path: Path, rel: str) -> list[dict]:
    """从输入文件确定性抽取 PROBES_PER_FILE 个 PROBE_LEN 字符子串。"""
    try:
        text = path.read_text(encoding="utf-8", errors="strict")
    except (OSError, UnicodeDecodeError):
        return []
    if len(text) < PROBE_LEN * 4:
        return []
    probes = []
    for i in range(PROBES_PER_FILE):
        # 均匀分布 + 按文件名哈希偏移，确定性且避开文件间同位置
        off = (hash_int(rel) + i * (len(text) - PROBE_LEN)) // PROBES_PER_FILE
        off = max(0, min(len(text) - PROBE_LEN, off % (len(text) - PROBE_LEN)))
        probes.append({"file": rel, "text": text[off:off + PROBE_LEN]})
    return probes


def hash_int(s: str) -> int:
    return int(hashlib.sha256(s.encode()).hexdigest()[:12], 16)


def probe_variants(text: str) -> list[bytes]:
    raw = text.encode("utf-8")
    esc = json.dumps(text, ensure_ascii=False)[1:-1].encode("utf-8")   # JSON 转义形态
    esc_ascii = json.dumps(text, ensure_ascii=True)[1:-1].encode("utf-8")
    variants = [raw]
    for v in (esc, esc_ascii):
        if v not in variants:
            variants.append(v)
    return variants


# ---------- zstd ----------

def zstd_size(files: list[Path]) -> int:
    try:
        params = zstandard.ZstdCompressionParameters.from_level(
            19, window_log=27, enable_ldm=True)
        cctx = zstandard.ZstdCompressor(compression_params=params)
    except Exception:
        cctx = zstandard.ZstdCompressor(level=19)

    class _Counter:
        n = 0
        def write(self, b):
            self.n += len(b)
            return len(b)

    counter = _Counter()
    with cctx.stream_writer(counter, closefd=False) as w:
        for f in files:
            try:
                with open(f, "rb") as fh:
                    while True:
                        buf = fh.read(1 << 20)
                        if not buf:
                            break
                        w.write(buf)
            except OSError:
                continue
    return counter.n


# ---------- snapshot / measure ----------

def snapshot(sandbox: Path, out: Path) -> None:
    """运行前基线（v3）：文件清单含 sha256；探针只从任务 workspace 抽取。"""
    base: dict = {}
    probes: list[dict] = []
    input_bytes = 0
    input_bytes_by_layer: dict[str, int] = {}
    for layer in ("workspace", "home"):
        root = sandbox / layer
        base[layer] = inventory_hashed(root)
        layer_bytes = sum(v["size"] for v in base[layer].values())
        input_bytes_by_layer[layer] = layer_bytes
        input_bytes += layer_bytes
        for rel in base[layer]:
            if layer == "workspace":
                probes.extend(make_probes(root / rel, f"{layer}/{rel}"))
    base["probes"] = probes
    base["baseline_version"] = 3
    base["input_bytes"] = input_bytes
    base["input_bytes_by_layer"] = input_bytes_by_layer
    out.write_text(json.dumps(base, ensure_ascii=False), encoding="utf-8")


def measure(sandbox: Path, baseline_path: Path) -> dict:
    base = json.loads(baseline_path.read_text(encoding="utf-8"))
    # Old baselines sampled framework setup files in HOME for InfiAgent only,
    # making echo incomparable.  Filter those probes at read time so existing
    # runs can be re-analysed without another model call.
    probes: list[dict] = [p for p in base.get("probes", [])
                          if p.get("file", "").startswith("workspace/")]
    by_layer = base.get("input_bytes_by_layer", {})
    if "workspace" in by_layer:
        input_bytes = by_layer["workspace"]
    else:  # backward compatibility with size-only v2 baselines
        input_bytes = sum(v if isinstance(v, int) else v.get("size", 0)
                          for v in base.get("workspace", {}).values())

    retained: list[tuple[str, Path, int]] = []
    excluded_bytes = 0
    modified_baseline_files = 0
    modified_baseline_pre_bytes = 0   # 变更基线文件中运行前已存在的字节（增量口径要扣掉）
    for layer in ("workspace", "home"):
        root = sandbox / layer
        before = base[layer]
        for rel, size in inventory(root).items():
            if rel in before:
                b_size, b_sha = _base_entry(before[rel])
                if b_sha:                      # v3 基线：哈希判变更（捕获同尺寸改写）
                    if size == b_size and file_sha(root / rel) == b_sha:
                        continue
                elif b_size == size:           # v2 基线：尺寸判等（历史行为，保持可复算）
                    continue
                modified_baseline_files += 1
                modified_baseline_pre_bytes += min(b_size, size)
            if is_excluded(rel):
                excluded_bytes += size
                continue
            retained.append((f"{layer}/{rel}", root / rel, size))

    # S_total 沿用发布口径（新文件 + 变更文件全尺寸）；S_total_delta 为纯增量口径
    s_total = sum(s for _, _, s in retained)
    s_total_delta = s_total - modified_baseline_pre_bytes

    uniq: dict[str, int] = {}
    s_logical = 0
    probe_hits = [0] * len(probes)
    variants = [probe_variants(p["text"]) for p in probes]
    per_file = []
    for rel, p, size in retained:
        f_logical = 0
        f_streams: list[bytes] = []
        for s in streams_of(p):
            f_logical += len(s)
            f_streams.append(s)
            for h, ln in chunk_stream(s):
                if h not in uniq:
                    uniq[h] = ln
        s_logical += f_logical
        f_hits = 0
        for i, vs in enumerate(variants):
            for s in f_streams:
                for v in vs:
                    n = s.count(v)
                    if n:
                        probe_hits[i] += n
                        f_hits += n
        per_file.append({"path": rel, "bytes": size,
                         "logical_bytes": f_logical, "probe_hits": f_hits})

    s_unique = sum(uniq.values())
    compressed = zstd_size([p for _, p, _ in retained]) if retained else 0
    echo_copies = (sum(probe_hits) / len(probe_hits)) if probe_hits else None

    per_file.sort(key=lambda x: -x["bytes"])
    s_ws = sum(s for rel, _, s in retained if rel.startswith("workspace/"))
    return {
        "S_total": s_total,
        "S_total_delta": s_total_delta,   # 增量口径（变更基线文件只计新增字节）
        "modified_baseline_files": modified_baseline_files,
        "modified_baseline_pre_bytes": modified_baseline_pre_bytes,
        "S_workspace": s_ws,          # agent 主动产物（file_write 等）
        "S_home": s_total - s_ws,     # 框架持久化残留
        "S_logical": s_logical,
        "S_unique": s_unique,
        "D": round(s_logical / s_unique, 3) if s_unique else None,
        "zstd_bytes": compressed,
        "C": round(s_total / compressed, 3) if compressed else None,
        "input_bytes": input_bytes,
        "echo_copies": round(echo_copies, 3) if echo_copies is not None else None,
        "echo_bytes_est": int(echo_copies * input_bytes) if echo_copies is not None else None,
        "n_probes": len(probes),
        "excluded_bytes": excluded_bytes,
        "n_files": len(retained),
        "files_top": per_file[:25],
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    s1 = sub.add_parser("snapshot")
    s1.add_argument("sandbox")
    s2 = sub.add_parser("measure")
    s2.add_argument("sandbox")
    a = ap.parse_args()
    sandbox = Path(a.sandbox)
    bl = sandbox / "baseline.json"
    if a.cmd == "snapshot":
        snapshot(sandbox, bl)
        print(f"baseline -> {bl}")
    else:
        rep = measure(sandbox, bl)
        (sandbox / "measurement.json").write_text(
            json.dumps(rep, indent=2), encoding="utf-8")
        print(json.dumps({k: rep[k] for k in
                          ("S_total", "D", "C", "echo_copies", "n_files")}, indent=2))


if __name__ == "__main__":
    main()
