# AgentFootprint — Supplementary Artifact

Self-contained reproduction package. Version alignment: see
`MANIFEST.txt` (public-repo commit / paper-repo commit / build date);
full environments, container image, and CI: public repository, tag
**v1.0.1-kdd**.

## Environment
    python3 -m pip install -r requirements.txt   # pinned: zstandard, fastcdc, numpy
Python 3.11–3.12 recommended (fastcdc wheels; 3.13 may need build tools).
No model API access is needed for anything below.

## What recomputes from what
| Level | Entry point | Source |
|---|---|---|
| Fully recomputable | `src/verify_expected.py` (main table, het joint cells, calibration) | archived per-run records + tasks |
| Fully recomputable | `src/meter_calibration.py`, `src/r_scorer_validation.py` (incl. v3 zero-retention regression) | self-generating |
| Fully recomputable | `src/tierb_stats.py` | Tier-B cache |
| Sample-recomputable | `src/threshold_sensitivity.py`, CAS compact/restore, D/C re-measurement | `representative_stores/` (task_00 per framework) |
| Sample-recomputable | `src/boundary_stats.py` latest-only | `representative_stores/llamaindex_horizons/` |
| Cache-verified only | `src/meter_audit.py` full 509-sandbox audit | needs the full 1.4 GB sandbox trees (not shipped); cached report included |
| Offline end-to-end | `src/fixed_trace.py` (mock endpoint, zero API) | needs framework packages; set `FOOTPRINT_PY_<FW>` |

## Representative raw stores
`representative_stores/<framework>/` holds one complete first-repetition
file-QA sandbox (baseline, measurement, full retained home tree) per
persisting framework, e.g.:
    python3 src/cas_compactor.py representative_stores/langgraph
Six stores are byte-exact originals. **InfiAgent's store is sanitized**
(API-key material redacted at source): it is measurement-equivalent,
with the re-measured values in
`representative_stores/infiagent/measurement_sanitized.json`
(S_total 2,207,880 B vs. 2,222,085 B pre-sanitization).
Store payloads are framework outputs on synthetic corpora; embedded
filesystem paths reflect the original sandbox layout.

## Layout
    MANIFEST.txt            version alignment triplet
    src/                    meter, graders, probes, protocols, analysis
    tasks/                  all synthetic task corpora
    experiments/            per-run baseline/measurement records (509 runs),
                            Tier-B cache, audits, calibration, fixed-trace,
                            continuous shared-store report
    representative_stores/  byte-exact raw stores + llamaindex horizon snapshots
