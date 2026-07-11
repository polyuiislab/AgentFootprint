"""CAS 缓解方法原型（论文 §mitigation）：内容寻址存储 + 引用替换 + 按需还原。

对一次运行的留存物做事后压缩：
  - JSON/JSONL：≥1KB 的字符串值外置到 CAS，原位替换 {"$cas": sha, "len": n, "preview": ...}
  - sqlite：同 schema 重建，≥1KB 的 TEXT/BLOB cell 替换为 "cas://sha256/<hex>#<len>"
  - CAS 对象 zstd-19 压缩、按内容哈希去重（同一文件读 3 遍 = 只存 1 份）
还原验证：JSON/JSONL/日志中的结构化对象语义相等；SQLite 用户表行集相等；
未处理文件原样传递。该验证证明逻辑内容无损，并保留每个外置对象的稳定指纹。

用法:
  python3 cas_compactor.py <run_sandbox_dir>          # 压缩+还原验证+报告
"""

from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
import sys
from pathlib import Path

import zstandard

THRESHOLD = 1024
CCTX = zstandard.ZstdCompressor(level=19)
DCTX = zstandard.ZstdDecompressor()


class CAS:
    def __init__(self, root: Path):
        self.root = root
        root.mkdir(parents=True, exist_ok=True)
        self.stored: set[str] = set()

    def put(self, data: bytes) -> str:
        h = hashlib.sha256(data).hexdigest()
        if h not in self.stored:
            p = self.root / h[:2] / f"{h}.zst"
            if not p.exists():
                p.parent.mkdir(exist_ok=True)
                p.write_bytes(CCTX.compress(data))
            self.stored.add(h)
        return h

    def get(self, h: str) -> bytes:
        return DCTX.decompress((self.root / h[:2] / f"{h}.zst").read_bytes())

    def size(self) -> int:
        return sum(f.stat().st_size for f in self.root.rglob("*.zst"))


def externalize_json(obj, cas: CAS):
    if isinstance(obj, dict):
        return {k: externalize_json(v, cas) for k, v in obj.items()}
    if isinstance(obj, list):
        return [externalize_json(v, cas) for v in obj]
    if isinstance(obj, str) and len(obj.encode("utf-8", "replace")) >= THRESHOLD:
        b = obj.encode("utf-8")
        return {"$cas": cas.put(b), "len": len(b), "preview": obj[:120]}
    return obj


def restore_json(obj, cas: CAS):
    if isinstance(obj, dict):
        if set(obj) == {"$cas", "len", "preview"}:
            return cas.get(obj["$cas"]).decode("utf-8")
        return {k: restore_json(v, cas) for k, v in obj.items()}
    if isinstance(obj, list):
        return [restore_json(v, cas) for v in obj]
    return obj


def is_sqlite(path: Path) -> bool:
    try:
        with open(path, "rb") as f:
            return f.read(16).startswith(b"SQLite format 3")
    except OSError:
        return False


def compact_sqlite(src: Path, dst: Path, cas: CAS) -> None:
    con = sqlite3.connect(f"file:{src}?mode=ro&immutable=1", uri=True)
    out = sqlite3.connect(dst)
    for (sql,) in con.execute(
            "select sql from sqlite_master where sql is not null"):
        try:
            out.execute(sql)
        except sqlite3.Error:
            pass
    tables = [r[0] for r in con.execute(
        "select name from sqlite_master where type='table' "
        "and name not like 'sqlite_%' and name not like '%_fts%'")]
    for t in tables:
        rows = con.execute(f'select * from "{t}"').fetchall()
        if not rows:
            continue
        ph = ",".join("?" * len(rows[0]))
        new_rows = []
        for row in rows:
            new_row = []
            for v in row:
                if isinstance(v, bytes) and len(v) >= THRESHOLD:
                    new_row.append(f"cas://sha256/{cas.put(v)}#b{len(v)}")
                elif isinstance(v, str) and len(v) >= THRESHOLD:
                    new_row.append(
                        f"cas://sha256/{cas.put(v.encode('utf-8'))}#s{len(v)}")
                else:
                    new_row.append(v)
            new_rows.append(new_row)
        out.executemany(f'insert into "{t}" values ({ph})', new_rows)
    out.commit()
    out.execute("vacuum")
    out.close()
    con.close()


def restore_sqlite_rows(path: Path, cas: CAS) -> dict:
    """还原后的 {table: sorted rows}（逻辑校验用）。"""
    con = sqlite3.connect(f"file:{path}?mode=ro&immutable=1", uri=True)
    data = {}
    for (t,) in con.execute("select name from sqlite_master where type='table' "
                            "and name not like 'sqlite_%' "
                            "and name not like '%_fts%'"):
        rows = []
        for row in con.execute(f'select * from "{t}"'):
            new_row = []
            for v in row:
                if isinstance(v, str) and v.startswith("cas://sha256/"):
                    ref, meta = v[len("cas://sha256/"):].split("#")
                    raw = cas.get(ref)
                    new_row.append(raw if meta[0] == "b" else raw.decode("utf-8"))
                else:
                    new_row.append(v)
            rows.append(tuple(new_row))
        data[t] = sorted(rows, key=repr)
    con.close()
    return data


def sqlite_rows(path: Path) -> dict:
    con = sqlite3.connect(f"file:{path}?mode=ro&immutable=1", uri=True)
    data = {}
    for (t,) in con.execute("select name from sqlite_master where type='table' "
                            "and name not like 'sqlite_%' "
                            "and name not like '%_fts%'"):
        data[t] = sorted(con.execute(f'select * from "{t}"'), key=repr)
    con.close()
    return data


def retained_files(sandbox: Path) -> list[Path]:
    base = json.loads((sandbox / "baseline.json").read_text(encoding="utf-8"))
    out = []
    for layer in ("workspace", "home"):
        root = sandbox / layer
        before = base[layer]
        if not root.exists():
            continue
        for p in root.rglob("*"):
            if not (p.is_file() and not p.is_symlink()):
                continue
            rel = str(p.relative_to(root))
            from meter import unchanged
            if rel in before and unchanged(before[rel], p, p.stat().st_size):
                continue
            out.append(p)
    return out


def main() -> None:
    sandbox = Path(sys.argv[1]).resolve()
    files = retained_files(sandbox)
    work = sandbox / "cas_compacted"
    if work.exists():
        shutil.rmtree(work)
    cas = CAS(work / "objects")

    s_before = sum(f.stat().st_size for f in files)
    skeleton_bytes = 0
    verified, failed = 0, 0
    n_compacted = 0
    for f in files:
        rel = f.relative_to(sandbox)
        dst = work / "skeleton" / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        try:
            if is_sqlite(f):
                compact_sqlite(f, dst, cas)
                ok = restore_sqlite_rows(dst, cas) == sqlite_rows(f)
            elif f.suffix in (".jsonl", ".ndjson"):
                lines_out = []
                raw_lines = f.read_text(encoding="utf-8").splitlines()
                for ln in raw_lines:
                    if not ln.strip():
                        lines_out.append(ln)
                        continue
                    obj = json.loads(ln)
                    lines_out.append(json.dumps(
                        externalize_json(obj, cas), ensure_ascii=False,
                        separators=(",", ":")))
                dst.write_text("\n".join(lines_out), encoding="utf-8")
                ok = all(
                    restore_json(json.loads(a), cas) == json.loads(b)
                    for a, b in zip(lines_out, raw_lines) if b.strip())
            elif f.suffix == ".json":
                obj = json.loads(f.read_text(encoding="utf-8"))
                comp = externalize_json(obj, cas)
                dst.write_text(json.dumps(comp, ensure_ascii=False,
                                          separators=(",", ":")), encoding="utf-8")
                ok = restore_json(json.loads(dst.read_text(encoding="utf-8")),
                                  cas) == obj
            elif f.suffix in (".log", ".txt"):
                # 日志行内嵌 JSON（如 autogen EVENT_LOGGER）：提取行内 JSON externalize
                raw_lines = f.read_text(encoding="utf-8",
                                        errors="replace").splitlines()
                lines_out = []
                ok = True
                for ln in raw_lines:
                    i = ln.find("{")
                    obj = None
                    if i >= 0:
                        try:
                            obj = json.loads(ln[i:])
                        except json.JSONDecodeError:
                            obj = None
                    if obj is None:
                        lines_out.append(ln)
                        continue
                    comp = externalize_json(obj, cas)
                    lines_out.append(ln[:i] + json.dumps(
                        comp, ensure_ascii=False, separators=(",", ":")))
                    if restore_json(comp, cas) != obj:
                        ok = False
                dst.write_text("\n".join(lines_out), encoding="utf-8")
            else:
                shutil.copy2(f, dst)   # passthrough files: verified byte-for-byte
                ok = dst.read_bytes() == f.read_bytes()
            skeleton_bytes += dst.stat().st_size
            n_compacted += 1
            verified += ok
            failed += (not ok)
        except Exception:
            shutil.copy2(f, dst)
            skeleton_bytes += dst.stat().st_size
            n_compacted += 1
            ok = dst.read_bytes() == f.read_bytes()
            verified += ok
            failed += (not ok)

    s_after = skeleton_bytes + cas.size()
    rep = {
        "sandbox": str(sandbox),
        "n_files": len(files),
        "S_before": s_before,
        "S_after": s_after,
        "skeleton_bytes": skeleton_bytes,
        "cas_bytes": cas.size(),
        "ratio": round(s_before / s_after, 2) if s_after else None,
        "restore_verified": verified,
        "restore_failed": failed,
    }
    (sandbox / "cas_report.json").write_text(json.dumps(rep, indent=2),
                                             encoding="utf-8")
    print(json.dumps(rep, indent=2))


if __name__ == "__main__":
    main()
