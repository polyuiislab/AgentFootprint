"""固定轨迹 mock LLM 服务器（fixed-trace 协议核心，零 API）。

OpenAI chat-completions 兼容端点。响应由**请求内容的状态机**决定而非计数器，
因此对反思轮/重试/不同调用节奏的框架都稳健：

  已完成的 read 次数 = 请求 messages 里 role=="tool" 的结果数（排除 final_output 回执）
  < len(READS)  -> 发下一个 read 工具调用（工具名/参数名自适应请求的 tools schema）
  >= len(READS) -> 终局：若 tools 含 final_output 则调用之（InfiAgent 契约），
                   否则输出纯文本答案

所有框架收到相同的逻辑轨迹：相同的读取目标序列、相同的观测字节、相同答案；
仅传输层（工具 schema/终止契约）按各框架适配。支持 stream=true（SSE 单块）。
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

READS: list[str] = []      # 由驱动器注入：固定读取目标序列
ANSWER = ""                # 固定答案


def _pick_read_tool(tools: list) -> tuple[str, str]:
    """从请求的 tools schema 里找 read 类工具及其文件参数名。"""
    for t in tools or []:
        fn = t.get("function", t)
        name = fn.get("name", "")
        if "read" in name.lower():
            props = (fn.get("parameters") or {}).get("properties") or {}
            for cand in ("filename", "file_path", "path", "file"):
                if cand in props:
                    return name, cand
            if props:
                return name, next(iter(props))
    return "read_file", "filename"


def _find_tool(tools: list, key: str) -> str | None:
    for t in tools or []:
        fn = t.get("function", t)
        if key in fn.get("name", "").lower():
            return fn["name"]
    return None


def _n_reads_done(messages: list) -> int:
    n = 0
    for m in messages:
        if m.get("role") == "tool":
            c = m.get("content") or ""
            if isinstance(c, list):
                c = " ".join(str(x.get("text", x)) for x in c)
            if "final_output" not in str(c)[:200].lower() or len(str(c)) > 200:
                n += 1
    return n


def build_response(body: dict) -> dict:
    messages = body.get("messages", [])
    tools = body.get("tools", [])
    done = _n_reads_done(messages)
    if done < len(READS):
        # 批量发出剩余读取：反思型执行器一次拿全；顺序执行器自然降级为逐个
        name, param = _pick_read_tool(tools)
        calls = [{"id": f"call_{done + i}", "type": "function",
                  "function": {"name": name,
                               "arguments": json.dumps({param: t})}}
                 for i, t in enumerate(READS[done:])]
        msg = {"role": "assistant", "content": None, "tool_calls": calls}
        finish = "tool_calls"
    else:
        fo = _find_tool(tools, "final_output")
        already_final = any(m.get("role") == "assistant" and m.get("tool_calls")
                            and "final" in str(m["tool_calls"])[:400]
                            for m in messages)
        if fo and not already_final:
            props = {}
            for t in tools:
                fn = t.get("function", t)
                if fn.get("name") == fo:
                    props = (fn.get("parameters") or {}).get("properties") or {}
            key = next((k for k in ("output", "answer", "content", "result")
                        if k in props), (next(iter(props)) if props else "output"))
            msg = {"role": "assistant", "content": None, "tool_calls": [{
                "id": "call_final", "type": "function",
                "function": {"name": fo,
                             "arguments": json.dumps({key: f"The registry code is {ANSWER}."})}}]}
            finish = "tool_calls"
        else:
            msg = {"role": "assistant",
                   "content": f"The registry code is {ANSWER}."}
            finish = "stop"
    return {
        "id": "chatcmpl-fixedtrace", "object": "chat.completion",
        "created": 1780000000, "model": body.get("model", "fixed-trace"),
        "choices": [{"index": 0, "message": msg, "finish_reason": finish}],
        "usage": {"prompt_tokens": 100, "completion_tokens": 20,
                  "total_tokens": 120},
    }


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):  # 静默
        pass

    def do_GET(self):
        data = json.dumps({"object": "list", "data": [
            {"id": "fixed-trace", "object": "model"}]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        try:
            body = json.loads(self.rfile.read(n) or b"{}")
        except Exception:
            body = {}
        resp = build_response(body)
        if body.get("stream"):
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            ch = {"id": resp["id"], "object": "chat.completion.chunk",
                  "created": resp["created"], "model": resp["model"],
                  "choices": [{"index": 0,
                               "delta": resp["choices"][0]["message"],
                               "finish_reason": resp["choices"][0]["finish_reason"]}]}
            self.wfile.write(f"data: {json.dumps(ch)}\n\n".encode())
            self.wfile.write(b"data: [DONE]\n\n")
        else:
            data = json.dumps(resp).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)


def serve(port: int, reads: list[str], answer: str) -> ThreadingHTTPServer:
    global READS, ANSWER
    READS, ANSWER = reads, answer
    srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


if __name__ == "__main__":
    import sys
    import time
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8781
    reads = sys.argv[2].split(",") if len(sys.argv) > 2 else []
    answer = sys.argv[3] if len(sys.argv) > 3 else "TEST"
    serve(port, reads, answer)
    print(f"mock llm on :{port} reads={reads} answer={answer}", flush=True)
    while True:
        time.sleep(60)
