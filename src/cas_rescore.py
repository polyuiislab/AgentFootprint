"""Measure (not argue) that the CAS store preserves replayability.

For each persisting framework's task_00 run: restore every compacted file
from cas_compacted/ (skeleton + objects) into a temporary sandbox whose
workspace/baseline are those of the original run, then re-run the R prober
on the restored retention. Expectation: R identical to the original score.

Output: experiments/pilot_runs/cas_rescore.json
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from cas_compactor import CAS, restore_json, restore_sqlite_rows, is_sqlite  # noqa: E402
import sqlite3  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
FWS = ["langgraph", "autogen", "infiagent", "agno", "llamaindex",
       "openai_agents", "crewai"]


def restore_file(src_skel: Path, dst: Path, cas: CAS) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    if is_sqlite(src_skel):
        # 重建 sqlite：按 skeleton 的 schema+行，还原 cas:// 引用
        rows = restore_sqlite_rows(src_skel, cas)
        con_in = sqlite3.connect(f"file:{src_skel}?mode=ro&immutable=1", uri=True)
        out = sqlite3.connect(dst)
        for (sql,) in con_in.execute(
                "select sql from sqlite_master where sql is not null"):
            try:
                out.execute(sql)
            except sqlite3.Error:
                pass
        for t, rws in rows.items():
            if not rws:
                continue
            ph = ",".join("?" * len(rws[0]))
            out.executemany(f'insert into "{t}" values ({ph})', rws)
        out.commit()
        out.close()
        con_in.close()
    elif src_skel.suffix in (".json",):
        obj = json.loads(src_skel.read_text(encoding="utf-8"))
        dst.write_text(json.dumps(restore_json(obj, cas), ensure_ascii=False),
                       encoding="utf-8")
    elif src_skel.suffix in (".jsonl", ".ndjson"):
        lines = []
        for ln in src_skel.read_text(encoding="utf-8").splitlines():
            if not ln.strip():
                lines.append(ln)
                continue
            lines.append(json.dumps(restore_json(json.loads(ln), cas),
                                    ensure_ascii=False, separators=(",", ":")))
        dst.write_text("\n".join(lines), encoding="utf-8")
    elif src_skel.suffix in (".log", ".txt"):
        lines = []
        for ln in src_skel.read_text(encoding="utf-8",
                                     errors="replace").splitlines():
            i = ln.find("{")
            obj = None
            if i >= 0:
                try:
                    obj = json.loads(ln[i:])
                except json.JSONDecodeError:
                    obj = None
            if obj is None:
                lines.append(ln)
            else:
                lines.append(ln[:i] + json.dumps(restore_json(obj, cas),
                                                 ensure_ascii=False,
                                                 separators=(",", ":")))
        dst.write_text("\n".join(lines), encoding="utf-8")
    else:
        shutil.copy2(src_skel, dst)


def main() -> None:
    import replay_probe
    results = []
    for fw in FWS:
        run = ROOT / "experiments" / "pilot_runs" / fw / "task_00"
        casdir = run / "cas_compacted"
        if not casdir.exists():
            continue
        tmp = ROOT / "experiments" / "pilot_runs" / fw / "task_00_casrestored"
        if tmp.exists():
            shutil.rmtree(tmp)
        tmp.mkdir()
        # workspace/baseline/measurement 原样；home 由 CAS 还原
        shutil.copytree(run / "workspace", tmp / "workspace")
        shutil.copy2(run / "baseline.json", tmp / "baseline.json")
        shutil.copy2(run / "measurement.json", tmp / "measurement.json")
        cas = CAS(casdir / "objects")
        cas.stored = {p.stem for p in (casdir / "objects").rglob("*.zst")}
        skel_root = casdir / "skeleton"
        for f in skel_root.rglob("*"):
            if f.is_file():
                rel = f.relative_to(skel_root)
                restore_file(f, tmp / rel, cas)
        orig = replay_probe.score(run)
        rest = replay_probe.score(tmp)
        results.append({"framework": fw, "R_original": orig["R"],
                        "R_after_cas_restore": rest["R"],
                        "match": orig["R"] == rest["R"]})
        print(f"{fw:<14} R {orig['R']} -> {rest['R']}  "
              f"{'OK' if orig['R'] == rest['R'] else 'MISMATCH'}")
        shutil.rmtree(tmp)
    (ROOT / "experiments" / "pilot_runs" / "cas_rescore.json").write_text(
        json.dumps(results, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
