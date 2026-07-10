# AgentFootprint

**A benchmark that makes storage footprint a first-class metric for LLM agent
evaluation.** It measures what an agent framework *leaves on disk* — logs,
checkpoints, context snapshots, session databases — under identical models,
tools, and tasks, and turns the bytes into six comparable metrics.

| Metric | Meaning |
|---|---|
| `S_total` | task-attributable bytes retained (workspace artifacts vs. framework residue) |
| composition | operational store-channel split of S_total (state / debug / conversation), audited by path rules; the decisions / observations / derivations / duplicates taxonomy is the interpretive framework |
| `D` | duplication factor over *logical content streams* (SQLite cells, JSONL records) |
| `α` | growth exponent of retention vs. task horizon |
| `C` | zstd long-range compressibility (the "syntactic free lunch" baseline) |
| `R` | replayability 0–3: can retained bytes reconstruct exactly what the model saw at step *k*? |

Naive byte-level measurement is blinded by SQLite paging and JSON escaping
(it reports D = 1.01 for a store that logically holds the same content 12×);
the meter therefore fingerprints logical streams and searches content probes
under raw / escaped / double-escaped encodings. See `docs/METRICS.md`.

## Quickstart

```bash
# 0) deps for the harness itself (meter, runner, analysis)
python3 -m pip install -r requirements.txt

# 1) one venv per framework you want to measure, e.g.:
python3 -m venv .venvs/langgraph
.venvs/langgraph/bin/pip install langgraph langgraph-checkpoint-sqlite langchain-openai

# 2) generate the task suites (deterministic, seeded)
python3 src/gen_tasks.py && python3 src/gen_longhorizon.py && python3 src/gen_writetasks.py

# 3) API key (any OpenAI-compatible provider; default model in frameworks.yaml)
echo 'OPENROUTER_API_KEY=sk-or-...' > .env

# 4) smoke run: one framework, one task
python3 src/runner.py --frameworks langgraph --tasks task_00

# 5) full suites, seeds, ablations, growth
python3 src/runner.py --frameworks langgraph,autogen --tasks task_00..task_09 --seed s2
python3 src/runner.py --suite longhorizon --frameworks langgraph --tasks lh_T025,lh_T050,lh_T100,lh_T200
python3 src/runner.py --frameworks langgraph --tasks task_00..task_04 --ablation

# 6) aggregate / score / compact
python3 src/analyze.py
python3 src/replay_probe.py experiments/pilot_runs/langgraph/task_0?
python3 src/cas_compactor.py experiments/pilot_runs/langgraph/task_00
```

## Bring your own agent (3 steps, ~50 lines)

1. `cp src/adapters/TEMPLATE.py src/adapters/run_myagent.py` and fill the two
   marked spots (build your agent; answer the questions). The contract is in
   `docs/ADAPTER_CONTRACT.md` — the harness owns sandboxing, measurement,
   grading, replay scoring, and compaction; your adapter only runs the agent.
2. Register it in `frameworks.yaml`:
   ```yaml
   myagent:
     python: .venvs/myagent/bin/python
     model: deepseek/deepseek-v4-flash
     percall_hints: [my_session_store]   # filename substrings of your per-call logs
   ```
3. `python3 src/runner.py --frameworks myagent --tasks task_00`

Rules of the game: configure your framework in its **canonical persistence
form** (what its own documentation teaches for durable sessions), don't tune
for storage, and keep one continuous session per task.

## Repository layout

```
frameworks.yaml       framework registry (add yours here)
tasks/                generated task suites (file-QA, long-horizon, write-task)
src/
  runner.py           sandbox orchestration (setup → snapshot → run → measure)
  meter.py            serialization-aware measurement (logical streams + probes)
  replay_probe.py     replayability scoring R∈{0..3} with evidence output
  cas_compactor.py    content-addressed reference store (lossless, verified)
  analyze.py          aggregate tables + rank statistics
  gen_*.py            deterministic task generators
  adapters/           one adapter per framework + TEMPLATE.py
  docker_check/       per-run container cross-validation of the sandbox
experiments/          raw measurements — gitignored except experiments/tierb/ caches
```

## Tier-B: public-leaderboard analysis

`src/tierb_harvest.py` maps SWE-bench Verified submissions' public S3 objects
to the 500 canonical instance ids (an S3 object is NOT an instance — some
submissions store several objects per instance or aggregate archives), keeps
only submissions with >=90% instance coverage and mapped-byte fraction, and
`src/tierb_stats.py` computes tie-corrected Kendall tau-b with permutation
tests. Cached tables from our run live in `experiments/tierb/`.

## Notes

- **Isolation.** The default sandbox is process-level (fresh workspace +
  redirected HOME/XDG per run); `src/docker_check/` re-runs a subset in
  per-run containers and agreed within 0–8.5% in our measurements.
- **InfiAgent adapter** requires its SDK on the configured interpreter; all
  other bundled adapters install from public PyPI.
- **Cost.** With a small OpenRouter-class model, the full 8-framework study
  (240 file-QA runs + growth/ablation/write suites) costs on the order of
  tens of dollars.

## License

MIT — see `LICENSE`.
