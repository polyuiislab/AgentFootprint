"""Tier B 深读抽样：从体量谱系两端+中位抽 6 个提交 × 5 实例，下载轨迹算
轨迹内重复因子 D（逻辑流 CDC）与逐步累积模式（消息数 vs 累计字节的曲率）。

产出 experiments/tierb/sample_analysis.json
"""

from __future__ import annotations

import json
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from meter import chunk_stream  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
TB = ROOT / "experiments" / "tierb"
S3 = "https://swe-bench-submissions.s3.amazonaws.com/"
NS = "{http://s3.amazonaws.com/doc/2006-03-01/}"
N_INST = 5


def http_get(url: str) -> bytes | None:
    try:
        with urllib.request.urlopen(url, timeout=120) as r:
            return r.read()
    except Exception:
        return None


def list_keys(prefix: str, n: int) -> list[str]:
    q = urllib.parse.urlencode(
        {"list-type": "2", "prefix": prefix, "max-keys": str(n * 3)})
    data = http_get(S3 + "?" + q)
    if not data:
        return []
    tree = ET.fromstring(data)
    keys = [c.find(f"{NS}Key").text for c in tree.findall(f"{NS}Contents")]
    return keys[:n]


def analyze_traj(data: bytes) -> dict:
    """轨迹文件（json 或 jsonl）→ D + 累积模式。"""
    streams: list[bytes] = []
    txt = data.decode("utf-8", "replace")
    msgs = None
    try:
        obj = json.loads(txt)
        # 常见形态：{"messages"/"history"/"trajectory": [...]} 或列表
        for key in ("messages", "history", "trajectory", "traj", "steps"):
            if isinstance(obj, dict) and isinstance(obj.get(key), list):
                msgs = obj[key]
                break
        if msgs is None and isinstance(obj, list):
            msgs = obj
    except json.JSONDecodeError:
        lines = [ln for ln in txt.splitlines() if ln.strip()]
        try:
            msgs = [json.loads(ln) for ln in lines]
        except json.JSONDecodeError:
            msgs = None
    if msgs is not None:
        streams = [json.dumps(m, ensure_ascii=False).encode() for m in msgs]
    else:
        streams = [data]

    total = sum(len(s) for s in streams)
    uniq: dict[str, int] = {}
    for s in streams:
        for h, ln in chunk_stream(s):
            uniq.setdefault(h, ln)
    d = total / max(1, sum(uniq.values()))
    # 累积曲率：前半消息字节占比（0.25=严重后倾/超线性累积，0.5=均匀）
    front_share = None
    if msgs and len(msgs) >= 8:
        sizes = [len(json.dumps(m, ensure_ascii=False)) for m in msgs]
        half = len(sizes) // 2
        front_share = round(sum(sizes[:half]) / max(1, sum(sizes)), 3)
    return {"bytes": len(data), "n_units": len(streams),
            "D_intra": round(d, 3), "front_half_share": front_share}


def main() -> None:
    rows = json.loads((TB / "verified_traj_sizes.json").read_text())
    ok = sorted([r for r in rows if r.get("mean_bytes") and r.get("resolve_rate")],
                key=lambda r: r["mean_bytes"])
    picks = [ok[0], ok[len(ok) // 4], ok[len(ok) // 2],
             ok[3 * len(ok) // 4], ok[-2], ok[-1]]
    out = []
    for r in picks:
        sub = r["submission"]
        prefix = f"verified/{sub}/trajs/"
        keys = list_keys(prefix, N_INST)
        insts = []
        for k in keys:
            data = http_get(S3 + urllib.parse.quote(k))
            if data:
                a = analyze_traj(data)
                a["key"] = k.rsplit("/", 1)[-1]
                insts.append(a)
        if insts:
            out.append({
                "submission": sub, "resolve_rate": r["resolve_rate"],
                "mean_bytes": r["mean_bytes"], "instances": insts,
                "D_intra_mean": round(sum(i["D_intra"] for i in insts)
                                      / len(insts), 3),
            })
            print(f"{sub[:48]}: D_intra={out[-1]['D_intra_mean']} "
                  f"({len(insts)} insts)", flush=True)
    (TB / "sample_analysis.json").write_text(json.dumps(out, indent=1))
    print("-> sample_analysis.json")


if __name__ == "__main__":
    main()
