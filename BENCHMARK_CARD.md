# AgentFootprint Benchmark Card (v1.0)

## Intended use
Measure the **post-run persistent storage footprint** of LLM agent
frameworks under their documented durable-session configurations, and
what those bytes buy (history-exact replayability, session resume).
Six metrics per run: `S_total`, store-channel composition, duplication
factor `D` (logical streams), growth exponent `alpha`, compressibility
`C`, replayability `R` (0–3).

## Protocol track
v1.0 is a **system-track** benchmark: documented default configurations
measured end-to-end, so results include agent-policy effects (prompts,
tool budgets, retries), not storage encoding alone. A **fixed-trace**
companion protocol (replaying one recorded trajectory through each
persistence backend) is planned; proxy-recorded trajectories that seed
it ship in the artifact.

## Non-goals
- Not a ranking of framework quality or reasoning ability.
- Not a capability-normalized efficiency comparison: equal-`R`
  configurations may differ in workflow-state recovery, event
  provenance, and crash semantics (see the capability matrix in the
  paper appendix).
- Not a peak-disk / bytes-written / write-amplification benchmark:
  the object is post-run retention.

## Measurement boundary
Fresh sandbox per run; workspace + redirected `HOME`/XDG inventoried
with per-file size **and SHA-256** (meter v3) before and after.
Pre-existing files count only growth (`S_total_delta`); the published
legacy accounting is audited against this on all 501 runs (≤0.0022%
difference). **Out of scope in v1.0:** system temp directories, remote
telemetry. Framework setup-time staging is excluded from `S_total`
and reported separately.

## Replayability scoring
The automated scorer yields a *candidate* grade (probe completeness +
per-call structure with a JSON-record gate). Framework-level `R=3`
additionally requires the adapter's serialization contract to pass
field-by-field conversation reconstruction against a logging proxy;
a process-boundary resume probe checks session continuation. New
adapters need a reconstruction extractor to obtain a verified grade.

## Adding a framework
See `TEMPLATE.py` and `docs/`: implement `setup`/`run` phases, read
`FOOTPRINT_MODEL` / `OPENROUTER_API_KEY` from the environment, write
`answers.json`. Never reuse a task identity after a failed run.

## Versioning & results
v1.0 at submission; adapters pin exact package versions
(`envlocks/*.txt`); results are grouped by benchmark and backend-model
version, new framework versions enter as new rows. Result schema =
`measurement.json` per run (keys documented in `src/meter.py`).

## Cost
Full main study ≈ 501 sandboxed runs on a budget model
(DeepSeek-V4-Flash via OpenRouter), API cost on the order of a few USD;
the meter and analysis run offline.

## Licensing & data
MIT. Synthetic corpora contain no personal data. SWE-bench-derived
size tables inherit the leaderboard's public-data terms; no raw user
data is redistributed.
