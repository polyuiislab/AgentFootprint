"""Tier B: instance-normalized SWE-bench Verified trajectory volume.

The public S3 prefixes are heterogeneous: some submissions store one object per
benchmark instance, others store several objects under an instance directory,
and still others publish a handful of aggregate JSONL archives.  An S3 object is
therefore *not* an instance.  We list object keys and sizes, map keys to the 500
canonical SWE-bench Verified instance ids, and report per-instance volume only
for submissions with sufficient mappable coverage.

Output ``experiments/tierb/verified_traj_sizes.json`` contains both the raw
object-level totals and the instance-normalized fields.  Aggregate archives that
cannot be assigned to individual instances remain in the file with
``normalization_status=ungroupable`` and are excluded from cross-system plots.
"""

from __future__ import annotations

import json
import re
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "experiments" / "tierb"
GH_RAW = "https://raw.githubusercontent.com/SWE-bench/experiments/main"
GH_API = "https://api.github.com/repos/SWE-bench/experiments/contents/evaluation/verified"
S3 = "https://swe-bench-submissions.s3.amazonaws.com/"
NS = "{http://s3.amazonaws.com/doc/2006-03-01/}"
N_VERIFIED = 500
HF_ROWS = "https://datasets-server.huggingface.co/rows"
INSTANCE_IDS_CACHE = OUT_DIR / "swebench_verified_instance_ids.json"
MIN_INSTANCE_COVERAGE = 0.90
MIN_MAPPED_BYTE_FRACTION = 0.90


def http_get(url: str, retries: int = 3) -> bytes | None:
    for i in range(retries):
        try:
            with urllib.request.urlopen(url, timeout=60) as r:
                return r.read()
        except Exception:
            time.sleep(2 * (i + 1))
    return None


def s3_list_objects(prefix: str) -> list[tuple[str, int]]:
    """Return every ``(key, size)`` below an S3 prefix."""
    objects: list[tuple[str, int]] = []
    token = None
    while True:
        q = {"list-type": "2", "prefix": prefix, "max-keys": "1000"}
        if token:
            q["continuation-token"] = token
        data = http_get(S3 + "?" + urllib.parse.urlencode(q))
        if data is None:
            return objects
        tree = ET.fromstring(data)
        for c in tree.findall(f"{NS}Contents"):
            objects.append((c.find(f"{NS}Key").text,
                            int(c.find(f"{NS}Size").text)))
        if (tree.find(f"{NS}IsTruncated") is not None
                and tree.find(f"{NS}IsTruncated").text == "true"):
            token = tree.find(f"{NS}NextContinuationToken").text
        else:
            return objects


def load_verified_instance_ids() -> list[str]:
    """Load the canonical 500 instance ids, caching the public HF response."""
    if INSTANCE_IDS_CACHE.exists():
        ids = json.loads(INSTANCE_IDS_CACHE.read_text(encoding="utf-8"))
        if len(ids) == N_VERIFIED and len(set(ids)) == N_VERIFIED:
            return ids

    ids: list[str] = []
    for offset in range(0, N_VERIFIED, 100):
        url = HF_ROWS + "?" + urllib.parse.urlencode({
            "dataset": "princeton-nlp/SWE-bench_Verified",
            "config": "default", "split": "test",
            "offset": offset, "length": 100,
        })
        data = http_get(url)
        if data is None:
            raise RuntimeError("failed to fetch SWE-bench Verified instance ids")
        page = json.loads(data.decode())
        ids.extend(r["row"]["instance_id"] for r in page["rows"])
    if len(ids) != N_VERIFIED or len(set(ids)) != N_VERIFIED:
        raise RuntimeError(f"expected 500 unique instance ids, found {len(set(ids))}")
    INSTANCE_IDS_CACHE.write_text(json.dumps(ids, indent=1), encoding="utf-8")
    return ids


def normalize_objects(prefix: str, objects: list[tuple[str, int]],
                      instance_ids: list[str]) -> dict:
    """Map heterogeneous S3 objects to canonical benchmark instances.

    Matching is deliberately conservative: an id must occur as a path/filename
    token, not merely as an arbitrary substring.  Aggregate archives with no
    instance token are counted as unmapped and cannot produce ``mean_bytes``.
    """
    ordered = sorted(instance_ids, key=len, reverse=True)
    # All current ids use this shape; the boundaries avoid issue 12 matching 123.
    patterns = [(iid, re.compile(r"(?:^|[/_.-])" + re.escape(iid) +
                                 r"(?:$|[/_.-])")) for iid in ordered]
    per_instance: dict[str, int] = {}
    unmapped_bytes = 0
    unmapped_objects = 0
    for key, size in objects:
        rel = key[len(prefix):] if key.startswith(prefix) else key
        iid = next((candidate for candidate, pat in patterns if pat.search(rel)), None)
        if iid is None:
            unmapped_bytes += size
            unmapped_objects += 1
        else:
            per_instance[iid] = per_instance.get(iid, 0) + size

    total = sum(size for _, size in objects)
    mapped = sum(per_instance.values())
    n_instances = len(per_instance)
    coverage = n_instances / N_VERIFIED
    mapped_fraction = mapped / total if total else 0.0
    usable = (coverage >= MIN_INSTANCE_COVERAGE and
              mapped_fraction >= MIN_MAPPED_BYTE_FRACTION)
    vals = sorted(per_instance.values())
    result = {
        "n_traj_objects": len(objects),
        "traj_bytes": total,
        "n_traj_instances": n_instances,
        "instance_coverage": round(coverage, 4),
        "mapped_traj_bytes": mapped,
        "mapped_byte_fraction": round(mapped_fraction, 4),
        "unmapped_objects": unmapped_objects,
        "unmapped_bytes": unmapped_bytes,
        "normalization_status": "usable" if usable else "ungroupable",
    }
    if usable and vals:
        result.update({
            "mean_bytes": mapped // n_instances,
            "median_bytes": vals[len(vals) // 2],
            "min_bytes": vals[0],
            "max_bytes": vals[-1],
        })
    return result


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    instance_ids = load_verified_instance_ids()
    subs = json.loads(http_get(GH_API + "?per_page=100").decode())
    # GitHub contents API 单页 1000 上限内一次给全；防翻页问题再拉一次 page=2
    names = [x["name"] for x in subs if x["type"] == "dir"]
    page2 = http_get(GH_API + "?per_page=100&page=2")
    if page2:
        try:
            names += [x["name"] for x in json.loads(page2.decode())
                      if x["type"] == "dir" and x["name"] not in names]
        except Exception:
            pass
    print(f"{len(names)} submissions")

    rows = []
    for i, name in enumerate(sorted(names)):
        row = {"submission": name}
        res = http_get(f"{GH_RAW}/evaluation/verified/{name}/results/results.json")
        if res:
            try:
                rj = json.loads(res.decode())
                resolved = rj.get("resolved")
                n_res = len(resolved) if isinstance(resolved, list) else (
                    int(resolved) if resolved is not None else None)
                row["resolved"] = n_res
                row["resolve_rate"] = round(n_res / N_VERIFIED, 4) if n_res is not None else None
            except Exception:
                pass
        meta = http_get(f"{GH_RAW}/evaluation/verified/{name}/metadata.yaml")
        s3_prefix = None
        if meta:
            for ln in meta.decode(errors="replace").splitlines():
                ln = ln.strip()
                if ln.startswith("trajs:") and "s3://swe-bench-submissions/" in ln:
                    s3_prefix = ln.split("s3://swe-bench-submissions/", 1)[1].strip()
        if s3_prefix:
            prefix = s3_prefix.rstrip("/") + "/"
            objects = s3_list_objects(prefix)
            row.update({"traj_source": "s3", "traj_prefix": prefix})
            row.update(normalize_objects(prefix, objects, instance_ids))
        else:
            # 老提交轨迹在 repo 内：用 git trees API 会触发限流，标记后续处理
            row["traj_source"] = "in_repo_or_missing"
        rows.append(row)
        if (i + 1) % 10 == 0:
            print(f"  {i + 1}/{len(names)} done", flush=True)
            (OUT_DIR / "verified_traj_sizes.json").write_text(
                json.dumps(rows, indent=1), encoding="utf-8")
    (OUT_DIR / "verified_traj_sizes.json").write_text(
        json.dumps(rows, indent=1), encoding="utf-8")
    with_s3 = [r for r in rows if r.get("traj_bytes")]
    usable = [r for r in rows if r.get("normalization_status") == "usable"]
    print(f"done: {len(rows)} submissions, {len(with_s3)} with S3 objects, "
          f"{len(usable)} instance-normalized")


if __name__ == "__main__":
    main()
