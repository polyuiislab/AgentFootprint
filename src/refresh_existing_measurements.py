"""Re-run the meter over completed sandboxes without another model call.

This is useful when a measurement definition is corrected (for example, the
workspace-only echo probes) while the retained artifacts and pre-run baselines
are still available.  Execution metadata and task scores are preserved.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import meter

ROOT = Path(__file__).resolve().parent.parent
PRESERVE = {
    "framework", "task", "model", "seed", "wall_sec", "returncode",
    "n_correct", "n_questions",
}


def sandbox_for(runs: Path, row: dict) -> Path:
    seed = row.get("seed") or "s1"
    suffix = "" if seed == "s1" else f"__{seed}"
    return runs / row["framework"] / f"{row['task']}{suffix}"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("suite", choices=("pilot_runs", "longhorizon_runs",
                                      "write_tasks_runs"))
    ap.add_argument("--frameworks", default="",
                    help="optional comma-separated exact framework labels")
    args = ap.parse_args()

    runs = ROOT / "experiments" / args.suite
    summary_path = runs / "summary.json"
    rows = json.loads(summary_path.read_text(encoding="utf-8"))
    selected = set(args.frameworks.split(",")) if args.frameworks else None
    refreshed = 0
    for i, row in enumerate(rows):
        if selected is not None and row["framework"] not in selected:
            continue
        sandbox = sandbox_for(runs, row)
        baseline = sandbox / "baseline.json"
        if not baseline.exists():
            print(f"skip missing baseline: {sandbox}")
            continue
        new = meter.measure(sandbox, baseline)
        metadata = {k: row[k] for k in PRESERVE if k in row}
        new.update(metadata)
        (sandbox / "measurement.json").write_text(
            json.dumps(new, indent=2), encoding="utf-8")
        rows[i] = new
        refreshed += 1
    summary_path.write_text(json.dumps(rows, indent=2), encoding="utf-8")
    print(f"refreshed {refreshed} rows -> {summary_path}")


if __name__ == "__main__":
    main()
