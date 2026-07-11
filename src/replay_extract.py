"""Extract the reconstructable conversation from a framework's retained store.

Output: experiments/replay_recon/<fw>_reconstructed.json
  {"messages": [OpenAI-chat-format dicts in order], "notes": [...]}

The reconstruction uses ONLY retained bytes (plus, for LangGraph, the
framework's own checkpoint reader, since its blobs are framework-serialized).
Run with:  <appropriate python> replay_extract.py --framework <fw>
(LangGraph requires its venv; all others parse plain JSON/SQLite with any
Python.)
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RP = ROOT / "experiments" / "replay_recon"


def sandbox_of(fw: str) -> Path:
    return ROOT / "experiments" / "pilot_runs" / fw / "task_00__rp"


def norm_tool_calls(tcs) -> list:
    out = []
    for t in tcs or []:
        f = t.get("function", t)
        out.append({"id": t.get("id"),
                    "name": f.get("name"),
                    "arguments": f.get("arguments")})
    return out


# ---------------- per-framework extractors ----------------

def extract_langgraph(home: Path):
    from langgraph.checkpoint.sqlite import SqliteSaver  # framework reader
    conn = sqlite3.connect(str(home / "langgraph_checkpoints.sqlite"))
    saver = SqliteSaver(conn)
    cfg = {"configurable": {"thread_id": "session-1"}}
    latest = saver.get(cfg)
    msgs = latest["channel_values"]["messages"]
    out = []
    for m in msgs:
        t = m.type
        if t == "human":
            out.append({"role": "user", "content": m.content})
        elif t == "ai":
            e = {"role": "assistant", "content": m.content or None}
            if m.tool_calls:
                e["tool_calls"] = [{"id": c["id"], "name": c["name"],
                                    "arguments": json.dumps(c["args"])}
                                   for c in m.tool_calls]
            out.append(e)
        elif t == "tool":
            out.append({"role": "tool", "tool_call_id": m.tool_call_id,
                        "content": m.content})
    return out, ["system prompt: none configured (create_react_agent default)"]


def extract_autogen(home: Path):
    states = sorted(home.glob("agent_state_q*.json"))
    st = json.loads(states[-1].read_text(encoding="utf-8"))
    msgs = st["llm_context"]["messages"]
    out, notes = [], []
    for m in msgs:
        t = m.get("type")
        if t == "UserMessage":
            out.append({"role": "user", "content": m["content"]})
        elif t == "AssistantMessage":
            c = m["content"]
            if isinstance(c, list):  # tool calls (text kept in `thought`)
                out.append({"role": "assistant",
                            "content": m.get("thought") or None,
                            "tool_calls": [{"id": x["id"], "name": x["name"],
                                            "arguments": x["arguments"]}
                                           for x in c]})
            else:
                out.append({"role": "assistant", "content": c})
        elif t == "FunctionExecutionResultMessage":
            for r in m["content"]:
                out.append({"role": "tool", "tool_call_id": r["call_id"],
                            "content": r["content"]})
        elif t == "SystemMessage":
            out.append({"role": "system", "content": m["content"]})
    if not any(m.get("role") == "system" for m in out):
        notes.append("system message not present in retained state (config-side)")
    return out, notes


def extract_openai_agents(home: Path):
    con = sqlite3.connect(str(home / "agents_sessions.sqlite"))
    rows = [json.loads(r[0]) for r in con.execute(
        "select message_data from agent_messages order by id")]
    out, notes = [], []
    for it in rows:
        t = it.get("type", "message" if "role" in it else None)
        if t == "function_call":
            tc = {"id": it["call_id"], "name": it["name"],
                  "arguments": it["arguments"]}
            if out and out[-1]["role"] == "assistant" and \
                    "tool_calls" not in out[-1]:
                out[-1].setdefault("tool_calls", []).append(tc)
            elif out and out[-1]["role"] == "assistant":
                out[-1]["tool_calls"].append(tc)
            else:
                out.append({"role": "assistant", "content": None,
                            "tool_calls": [tc]})
        elif t == "function_call_output":
            out.append({"role": "tool", "tool_call_id": it["call_id"],
                        "content": it["output"]})
        elif it.get("role") == "user":
            out.append({"role": "user", "content": it["content"]})
        elif it.get("role") == "assistant":
            c = it.get("content")
            if isinstance(c, list):
                c = "".join(x.get("text", "") for x in c)
            out.append({"role": "assistant", "content": c})
    notes.append("instructions (system) not stored in session db (config-side)")
    return out, notes


def extract_llamaindex(home: Path):
    ctxs = sorted(home.glob("ctx_q*.json"))
    d = json.loads(ctxs[-1].read_text(encoding="utf-8"))

    # Context 序列化里 memory 的 chat store：递归找 messages 列表
    found = []

    def walk(o):
        if isinstance(o, dict):
            if "role" in o and ("content" in o or "blocks" in o):
                found.append(o)
            for v in o.values():
                if isinstance(v, str) and v.strip()[:1] in "{[":
                    try:
                        walk(json.loads(v))
                        continue
                    except Exception:
                        pass
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)

    walk(d)
    out, notes = [], []
    for m in found:
        role = m["role"]
        content = m.get("content")
        if content is None and "blocks" in m:
            content = "".join(b.get("text", "") for b in m["blocks"]
                              if isinstance(b, dict))
        kw = m.get("additional_kwargs") or {}
        e = {"role": role, "content": content}
        if kw.get("tool_calls"):
            e["tool_calls"] = norm_tool_calls(kw["tool_calls"])
        if kw.get("tool_call_id"):
            e["tool_call_id"] = kw["tool_call_id"]
        out.append(e)
    return out, ["messages recovered via recursive scan of serialized Context"]


def extract_agno(home: Path):
    db = home / "agno_sessions.sqlite"
    con = sqlite3.connect(str(db))
    raw = con.execute("select runs from agno_sessions").fetchone()[0]
    runs = json.loads(raw)
    if isinstance(runs, str):  # agno double-encodes the runs column
        runs = json.loads(runs)
    out, notes = [], []
    system_added = False
    for run in runs:
        for m in run.get("messages") or []:
            role = m.get("role")
            if role == "system":
                if not system_added:
                    out.append({"role": "system", "content": m.get("content")})
                    system_added = True
                continue
            e = {"role": role, "content": m.get("content")}
            if m.get("tool_calls"):
                e["tool_calls"] = norm_tool_calls(m["tool_calls"])
            if m.get("tool_call_id"):
                e["tool_call_id"] = m["tool_call_id"]
            out.append(e)
    notes.append("per-run message arrays concatenated in run order; "
                 "single leading system message")
    return out, notes


def extract_infiagent(home: Path):
    traces = sorted((home / "user_root" / "training_traces").glob("*raw_io.jsonl"))
    reqs = []
    for tr in traces:
        for ln in tr.read_text(encoding="utf-8").splitlines():
            try:
                rec = json.loads(ln)
            except Exception:
                continue
            payload = rec.get("request") or rec.get("raw_request") or {}
            msgs = payload.get("messages") if isinstance(payload, dict) else None
            if msgs:
                reqs.append(msgs)
    return reqs, ["raw_io stores full request payloads; returning per-call message arrays"]


EXTRACTORS = {
    "langgraph": extract_langgraph,
    "autogen": extract_autogen,
    "openai_agents": extract_openai_agents,
    "llamaindex": extract_llamaindex,
    "agno": extract_agno,
    "infiagent": extract_infiagent,
}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--framework", required=True, choices=sorted(EXTRACTORS))
    ap.add_argument("--run-dir", default="",
                    help="sandbox run dir override "
                         "(default: experiments/pilot_runs/<fw>/task_00__rp)")
    a = ap.parse_args()
    run_dir = Path(a.run_dir) if a.run_dir else sandbox_of(a.framework)
    home = run_dir / "home"
    msgs, notes = EXTRACTORS[a.framework](home)
    out = {"framework": a.framework, "messages": msgs, "notes": notes}
    p = RP / f"{a.framework}_reconstructed.json"
    p.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    n = len(msgs)
    print(f"{a.framework}: reconstructed {n} "
          f"{'per-call arrays' if a.framework == 'infiagent' else 'messages'} -> {p.name}")


if __name__ == "__main__":
    main()
