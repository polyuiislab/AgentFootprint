# Adapter Contract

An adapter is one Python file, `src/adapters/run_<name>.py`, executed by the
interpreter you register in `frameworks.yaml`. It is the ONLY code you write
to put a new agent on the benchmark.

## CLI

```
python run_<name>.py  <phase>  --task-dir D --workspace W --home H --out F
```

| Arg | Meaning |
|---|---|
| `phase` | `setup` or `run` |
| `--task-dir D` | read-only task definition; `D/questions.json` holds the questions |
| `--workspace W` | the agent's file area; harness pre-copies the task corpus here |
| `--home H` | sandbox HOME; your framework's persistence should land here (or in W) |
| `--out F` | where `run` writes the answers JSON |

### `setup` phase

Prepare anything your framework needs *inside the sandbox* (e.g. copy a
config template, initialize a user directory). Everything that exists when
`setup` exits is recorded as **baseline** and never counted as footprint.
Most adapters do nothing here.

### `run` phase

Answer every question in `D/questions.json`
(`[{"qid": 0, "question": "...", "answer": "<ground truth>"}, ...]`) with
**one continuous agent session** per task, and write
`{"0": "answer text", ...}` to `F`. Grading is substring match against the
ground-truth code — return the exact value, not a summary.

Per-question failures must not abort the task: catch, record
`"ADAPTER_ERROR: <e>"`, continue. If your framework leaves stale session
state after a failure, start a FRESH session/task id for the remaining
questions rather than reusing the poisoned one.

## Environment (provided by the harness)

| Var | Meaning |
|---|---|
| `FOOTPRINT_MODEL` | backend model string from `frameworks.yaml` |
| `OPENROUTER_API_KEY` / `OPENAI_API_KEY` | credentials |
| `FOOTPRINT_WORKSPACE` | absolute path of W, for your file tools |
| `FOOTPRINT_ABLATION` | `"1"` → run with persistence disabled (support if possible) |
| `FOOTPRINT_TOOLSET` | `"rw"` → additionally expose `write_file` (write-task suite) |
| `HOME`, `XDG_CACHE_HOME`, `XDG_DATA_HOME` | redirected into the sandbox |

## Tools

Give the agent exactly these tools (copy the implementations from
`TEMPLATE.py` so behavior is identical across frameworks):

- `list_files()` — names of files in W
- `read_file(filename)` — full text content
- `write_file(filename, content)` — only when `FOOTPRINT_TOOLSET=rw`

## Fairness rules

1. **Canonical persistence form**: configure the persistence mechanism your
   framework's documentation teaches for durable sessions (checkpointer,
   session store, state saving...). Not "everything on", not "everything
   off" — what a documented user gets.
2. No storage tuning, no compression flags, no custom compaction.
3. `temperature=0`; the model comes from the registry.
4. One continuous session across a task's questions (context accumulates).

## Registry entry (`frameworks.yaml`)

```yaml
myagent:
  python: .venvs/myagent/bin/python   # or absolute path
  model: deepseek/deepseek-v4-flash   # passed as FOOTPRINT_MODEL
  litellm: true                        # only if your adapter takes litellm-style names
  percall_hints: [my_session, my_trace] # filename substrings of per-LLM-call stores;
                                        # replay_probe uses these to score R fairly
```

`percall_hints` matters: if your framework's per-call store has a filename
the prober doesn't recognize, its replayability will be under-scored as
R=1 even when the content is complete.
