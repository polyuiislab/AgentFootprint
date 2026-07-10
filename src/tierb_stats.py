"""Reproducible statistics for the instance-normalized SWE-bench study."""

from __future__ import annotations

import json
import math
import random
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "experiments" / "tierb" / "verified_traj_sizes.json"
OUT = ROOT / "experiments" / "tierb" / "stats.json"
N_PERM = 20_000
SEED = 20260710


def kendall_tau_b(x: list[float], y: list[float]) -> float:
    concordant = discordant = tie_x = tie_y = 0
    for i in range(len(x)):
        for j in range(i + 1, len(x)):
            dx, dy = x[i] - x[j], y[i] - y[j]
            if dx == 0 and dy == 0:
                continue
            if dx == 0:
                tie_x += 1
            elif dy == 0:
                tie_y += 1
            elif dx * dy > 0:
                concordant += 1
            else:
                discordant += 1
    denom = math.sqrt((concordant + discordant + tie_x) *
                      (concordant + discordant + tie_y))
    return (concordant - discordant) / denom if denom else 0.0


def permutation_p(x: list[float], y: list[float], observed: float,
                  rng: random.Random) -> float:
    exceed = 0
    perm = list(y)
    for _ in range(N_PERM):
        rng.shuffle(perm)
        exceed += abs(kendall_tau_b(x, perm)) >= abs(observed) - 1e-12
    return (exceed + 1) / (N_PERM + 1)


def main() -> None:
    rows = json.loads(DATA.read_text(encoding="utf-8"))
    usable = [r for r in rows
              if r.get("normalization_status") == "usable"
              and r.get("mean_bytes")
              and r.get("resolve_rate") is not None]
    success = [r["resolve_rate"] for r in usable]
    volume = [r["mean_bytes"] for r in usable]
    efficiency = [s / (b / 1_000_000) for s, b in zip(success, volume)]

    rng = random.Random(SEED)
    direct_tau = kendall_tau_b(success, volume)
    direct_p = permutation_p(success, volume, direct_tau, rng)
    ranking_tau = kendall_tau_b(success, efficiency)
    ranking_p = permutation_p(success, efficiency, ranking_tau, rng)

    band = [r for r in usable if 0.65 <= r["resolve_rate"] <= 0.75]
    band_sizes = [r["mean_bytes"] for r in band]
    all_sizes = sorted(volume)
    stats = {
        "normalization": {
            "all_submissions": len(rows),
            "with_s3_objects": sum(bool(r.get("traj_bytes")) for r in rows),
            "usable_submissions": len(usable),
            "min_required_instance_coverage": 0.90,
            "min_required_mapped_byte_fraction": 0.90,
        },
        "volume": {
            "min_mean_bytes": all_sizes[0],
            "median_mean_bytes": all_sizes[len(all_sizes) // 2],
            "max_mean_bytes": all_sizes[-1],
            "spread": all_sizes[-1] / all_sizes[0],
        },
        "success_vs_volume": {
            "kendall_tau_b": direct_tau,
            "permutation_p": direct_p,
            "n_permutations": N_PERM,
        },
        "success_ranking_vs_success_per_mb_ranking": {
            "kendall_tau_b": ranking_tau,
            "permutation_p": ranking_p,
            "n_permutations": N_PERM,
        },
        "success_band_65_75": {
            "n": len(band_sizes),
            "min_mean_bytes": min(band_sizes) if band_sizes else None,
            "max_mean_bytes": max(band_sizes) if band_sizes else None,
            "spread": (max(band_sizes) / min(band_sizes)) if band_sizes else None,
        },
        "submissions": [r["submission"] for r in usable],
    }
    OUT.write_text(json.dumps(stats, indent=2), encoding="utf-8")
    print(json.dumps(stats, indent=2))


if __name__ == "__main__":
    main()
