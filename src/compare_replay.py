"""Field-by-field replay-reconstruction verification.

Ground truth: experiments/replay_recon/<fw>_requests.jsonl — every request
body the model actually received (recorded by an independent logging proxy).
Reconstruction: <fw>_reconstructed.json — conversation rebuilt from retained
bytes only.

For each recorded call k we normalize its `messages` array and test:
  input_exact    every message (including system) matches the reconstruction
                 prefix field-by-field (role, content, tool_calls id/name/
                 arguments, tool_call_id);
  history_exact  same, after dropping system messages from both sides
                 (system prompts are adapter config; whether they are retained
                 is reported separately per framework).

A framework supports exact replay of call k iff the recorded input can be
regenerated from its store. Output: replay_verification.json + console table.
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RP = ROOT / "experiments" / "replay_recon"
FWS = ["langgraph", "autogen", "openai_agents", "llamaindex", "agno",
       "infiagent"]


def norm_msg(m: dict) -> dict:
    out = {"role": m.get("role"), "content": m.get("content")}
    if out["content"] == "":
        out["content"] = None
    tcs = m.get("tool_calls")
    if tcs:
        ntc = []
        for t in tcs:
            f = t.get("function", t)
            args = f.get("arguments")
            try:  # 参数 JSON 语义相等（空白/键序差异不算失配）
                args = json.dumps(json.loads(args), sort_keys=True)
            except Exception:
                pass
            ntc.append({"id": t.get("id"), "name": f.get("name"),
                        "arguments": args})
        out["tool_calls"] = ntc
    if m.get("tool_call_id"):
        out["tool_call_id"] = m["tool_call_id"]
    return out


def msgs_equal(a: list, b: list) -> bool:
    if len(a) != len(b):
        return False
    return all(norm_msg(x) == norm_msg(y) for x, y in zip(a, b))


def drop_system(ms: list) -> list:
    return [m for m in ms if m.get("role") != "system"]


def verify(fw: str) -> dict:
    reqs = [json.loads(ln) for ln in
            (RP / f"{fw}_requests.jsonl").read_text(encoding="utf-8").splitlines()]
    recon = json.loads((RP / f"{fw}_reconstructed.json").read_text(encoding="utf-8"))
    rmsgs = recon["messages"]

    res = {"framework": fw, "n_calls": len(reqs), "input_exact": 0,
           "history_exact": 0, "mismatches": [], "notes": recon.get("notes", [])}
    for r in reqs:
        gt = r["request"].get("messages") or []
        k = r["call_index"]
        if fw == "infiagent":  # per-call full-payload records
            hit_full = any(msgs_equal(gt, cand) for cand in rmsgs)
            hit_hist = hit_full or any(
                msgs_equal(drop_system(gt), drop_system(cand)) for cand in rmsgs)
        else:
            # Unified contract: the call's history must appear as a contiguous
            # subsequence of the reconstructed history (prefix is the special
            # case; windowed-history frameworks match mid-sequence). The system
            # message, if any, must additionally be present in the store.
            gt_h = drop_system(gt)
            rh = drop_system(rmsgs)
            hit_hist = any(msgs_equal(gt_h, rh[i:i + len(gt_h)])
                           for i in range(len(rh) - len(gt_h) + 1))
            gt_sys = gt[0] if gt and gt[0].get("role") == "system" else None
            if gt_sys is None:
                hit_full = hit_hist
            else:
                sys_in_store = any(m.get("role") == "system" and
                                   msgs_equal([m], [gt_sys]) for m in rmsgs)
                hit_full = hit_hist and sys_in_store
        res["input_exact"] += hit_full
        res["history_exact"] += hit_hist
        if not hit_hist and len(res["mismatches"]) < 3:
            gt_h = drop_system(gt)
            rec_h = (drop_system(rmsgs)[:len(gt_h)]
                     if fw != "infiagent" else None)
            diff = None
            if rec_h is not None:
                for i, (x, y) in enumerate(zip(gt_h, rec_h)):
                    if norm_msg(x) != norm_msg(y):
                        diff = {"pos": i, "gt": norm_msg(x), "rec": norm_msg(y)}
                        break
                if diff is None:
                    diff = {"len_gt": len(gt_h), "len_rec": len(rec_h)}
            res["mismatches"].append({"call": k, "first_diff": diff})
    return res


def main() -> None:
    results = [verify(fw) for fw in FWS]
    (RP / "replay_verification.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{'framework':<14} {'calls':>5} {'input-exact':>12} {'history-exact':>14}")
    for r in results:
        print(f"{r['framework']:<14} {r['n_calls']:>5} "
              f"{r['input_exact']:>7}/{r['n_calls']:<4} "
              f"{r['history_exact']:>9}/{r['n_calls']:<4}")


if __name__ == "__main__":
    main()
