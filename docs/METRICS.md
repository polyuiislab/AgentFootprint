# Metrics & Measurement Methodology

## Attribution boundary
Footprint = all bytes attributable to a run and absent before it: workspace
files, session/checkpoint databases, conversation and action logs, context
snapshots, debug traces — wherever the framework writes them (HOME/XDG are
redirected into the sandbox, so hidden state is captured). Shared environment
artifacts (model weights, tokenizer caches, pip caches) are excluded but
reported separately (`excluded_bytes`).

## The six metrics
- **S_total** — attributable bytes after the run; split into `S_workspace`
  (agent-produced artifacts) and `S_home` (framework residue).
- **Composition** — operationally, S_total split by store channel
  (state/checkpoints, debug/event logs, conversation/actions) via audited
  path rules, plus content-level duplication from CDC fingerprints. The
  decisions / observations / derivations / duplicates taxonomy is the
  interpretive lens; per-byte semantic classification is not automated.
- **D (duplication factor)** — logical bytes / unique bytes, where unique is
  FastCDC content-defined chunking (SHA-256) over *logical streams*.
- **α (growth exponent)** — fit of log S_total ~ α · log T on the
  long-horizon suite (T ∈ {25, 50, 100, 200}, constant per-round content).
  Report the full-range fit AND piecewise local slopes.
- **C (compressibility)** — S_total / zstd-19-long-window size.
- **R (replayability, 0–3)** — 0: nothing retained; 1: bytes but no per-call
  structure; 2: per-call structure but no complete copy of observations;
  3: at least one channel reconstructs the model's exact step-k input.
  Scored automatically with line-level probes; evidence emitted for audit.

## Why logical streams (the two serialization traps)
Byte-level chunking over raw files reports D=1.01 for a store that zstd
compresses 142x — a contradiction. Two mechanisms mask duplication:
1. **SQLite paging**: large values are fragmented across 4KB pages with
   interleaved headers, so chunk boundaries never align between copies.
2. **JSON escaping**: embedded content is byte-rewritten (\n, \uXXXX), so
   trajectory copies no longer match source bytes.
The meter extracts logical streams first — every SQLite cell and every JSONL
line is chunked as its own stream. Same store: D=12.1.

Cross-representation copies (raw file vs. escaped copy in a log) still evade
chunk matching, so the meter additionally plants **content probes** — fixed
substrings and whole lines from every input file — and searches all logical
streams under raw / JSON-escaped / double-escaped encodings. The mean
occurrence count (`echo_copies`) estimates how many times input content is
stored; the same probes power R's completeness check. Probes are generated
from the task workspace baseline only — framework-owned template files in
the sandbox HOME are excluded, so a framework is never scored against its
own configuration text.
