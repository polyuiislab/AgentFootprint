"""Meter 实现审计（审稿 round-4 W1）：在全部已存沙箱上量化 size-only 基线的实际影响。

问题：v2 基线只存 st_size——(a) 同尺寸原地改写会被漏计；(b) 变更基线文件按
运行后全尺寸计入 S_total 而非增量。本脚本对每个已存沙箱实证：

  A. 基线 home 文件数/字节——若快照时 home 为空，(a)(b) 在 home 侧无从发生；
  B. 基线 workspace 文件 vs 发布语料逐字节比对——捕获包括同尺寸改写在内的
     任何原地修改（runner 每次从 tasks/<suite>/<task>/corpus 全量新拷）；
  C. 尺寸变化的基线文件：S_total 中含其运行前字节 → 全尺寸-增量差
     （S_total_delta 修正量）；
  D. 尺寸相同的基线 home 文件：事后无法哈希验证的盲区规模。
"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SUITES = {  # runs 目录 -> tasks 目录
    "pilot_runs": "file_intensive",
    "longhorizon_runs": "longhorizon",
    "natural_runs": "natural",
    "write_tasks_runs": "write_tasks",
    "edit_tasks_runs": "edit_tasks",
    "data_tasks_runs": "data_tasks",
    "docker_runs": "file_intensive",
}


def sha(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        while True:
            b = f.read(1 << 20)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def base_size(v) -> int:
    return v if isinstance(v, int) else v.get("size", 0)


def main() -> None:
    agg = defaultdict(lambda: {"runs": 0, "S_total": 0, "pre_bytes_in_changed": 0,
                               "ws_modified_files": 0, "home_base_files": 0,
                               "home_base_bytes": 0, "same_size_home_files": 0,
                               "same_size_home_bytes": 0})
    worst = []
    n_runs = 0
    for suite_dir, tasks_name in SUITES.items():
        sroot = ROOT / "experiments" / suite_dir
        if not sroot.is_dir():
            continue
        for meas in sroot.rglob("measurement.json"):
            sandbox = meas.parent
            basef = sandbox / "baseline.json"
            if not basef.exists():
                continue
            try:
                rep = json.loads(meas.read_text(encoding="utf-8"))
                base = json.loads(basef.read_text(encoding="utf-8"))
            except Exception:
                continue
            n_runs += 1
            fw = rep.get("framework", sandbox.parent.name)
            key = (suite_dir, fw)
            a = agg[key]
            a["runs"] += 1
            a["S_total"] += rep.get("S_total", 0) or 0

            task = sandbox.name.split("__")[0]
            corpus = ROOT / "tasks" / tasks_name / task / "corpus"

            pre_in_changed = 0
            for layer in ("workspace", "home"):
                before = base.get(layer, {})
                if not isinstance(before, dict):
                    continue
                root = sandbox / layer
                if layer == "home":
                    a["home_base_files"] += len(before)
                    a["home_base_bytes"] += sum(base_size(v) for v in before.values())
                for rel, v in before.items():
                    bs = base_size(v)
                    cur = root / rel
                    if not cur.exists():
                        continue
                    try:
                        cs = cur.stat().st_size
                    except OSError:
                        continue
                    if cs != bs:            # 已被计全尺寸的变更基线文件
                        pre_in_changed += min(bs, cs)
                    elif layer == "home":   # 同尺寸 home 基线文件：事后盲区
                        a["same_size_home_files"] += 1
                        a["same_size_home_bytes"] += bs
                    elif layer == "workspace" and corpus.is_dir():
                        src = corpus / rel
                        if src.is_file() and src.stat().st_size == cs:
                            try:
                                if sha(src) != sha(cur):   # 同尺寸原地改写！
                                    a["ws_modified_files"] += 1
                            except OSError:
                                pass
            a["pre_bytes_in_changed"] += pre_in_changed
            st = rep.get("S_total", 0) or 0
            if st and pre_in_changed:
                worst.append((pre_in_changed / st, suite_dir, fw,
                              sandbox.name, pre_in_changed, st))

    print(f"audited sandboxes: {n_runs}\n")
    print("| suite | framework | runs | ΣS_total MB | Σpre-in-changed B | "
          "ws同尺寸改写 | home基线文件 | home同尺寸盲区 B |")
    print("|---|---|---|---|---|---|---|---|")
    tot_pre = tot_s = tot_wsmod = tot_blind = 0
    for (sd, fw), a in sorted(agg.items()):
        tot_pre += a["pre_bytes_in_changed"]
        tot_s += a["S_total"]
        tot_wsmod += a["ws_modified_files"]
        tot_blind += a["same_size_home_bytes"]
        if (a["pre_bytes_in_changed"] or a["ws_modified_files"]
                or a["home_base_files"]):
            print(f"| {sd} | {fw} | {a['runs']} | {a['S_total']/1048576:.2f} | "
                  f"{a['pre_bytes_in_changed']} | {a['ws_modified_files']} | "
                  f"{a['home_base_files']} | {a['same_size_home_bytes']} |")
    print(f"\nTOTALS: S_total={tot_s/1048576:.1f}MB  "
          f"pre-bytes-in-changed={tot_pre}B "
          f"({100*tot_pre/max(tot_s,1):.4f}% of S_total)  "
          f"ws-same-size-rewrites={tot_wsmod}  "
          f"home-same-size-unverifiable={tot_blind}B")
    worst.sort(reverse=True)
    for w in worst[:5]:
        print("  worst:", w)
    out = ROOT / "experiments" / "meter_audit_report.json"
    out.write_text(json.dumps(
        {f"{k[0]}/{k[1]}": v for k, v in agg.items()}, indent=2),
        encoding="utf-8")
    print(f"\nreport -> {out}")


if __name__ == "__main__":
    main()
