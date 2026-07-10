"""Logging reverse proxy for replay-reconstruction ground truth.

Forwards OpenAI-compatible POSTs to OpenRouter unchanged and appends every
request body (plus a monotonically increasing call index) to a JSONL file.
The recorded request is the independent ground truth of "what the model saw
at call k" for the replay-reconstruction experiment.

Usage:
  python3 logging_proxy.py --port 18923 --log /path/requests.jsonl
Then point adapters at http://127.0.0.1:18923/v1 via FOOTPRINT_BASE_URL.
"""

from __future__ import annotations

import argparse
import json
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

UPSTREAM = "https://openrouter.ai/api"
_lock = threading.Lock()
_counter = {"n": 0}


def make_handler(log_path: str):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):  # 静默访问日志
            pass

        def do_POST(self):
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length)
            with _lock:
                _counter["n"] += 1
                idx = _counter["n"]
            try:
                parsed = json.loads(body.decode("utf-8"))
            except Exception:
                parsed = {"_raw": body.decode("utf-8", "replace")}
            with _lock:
                with open(log_path, "a", encoding="utf-8") as f:
                    f.write(json.dumps({"call_index": idx,
                                        "ts": time.time(),
                                        "path": self.path,
                                        "request": parsed},
                                       ensure_ascii=False) + "\n")
            # 转发（去掉 /v1 前缀差异：upstream 是 /api/v1/...）
            path = self.path
            if not path.startswith("/v1"):
                path = "/v1" + path
            req = urllib.request.Request(UPSTREAM + path, data=body, method="POST")
            for h in ("Authorization", "Content-Type", "Accept"):
                if self.headers.get(h):
                    req.add_header(h, self.headers[h])
            try:
                with urllib.request.urlopen(req, timeout=300) as resp:
                    data = resp.read()
                    self.send_response(resp.status)
                    self.send_header("Content-Type",
                                     resp.headers.get("Content-Type",
                                                      "application/json"))
                    self.send_header("Content-Length", str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
            except urllib.error.HTTPError as e:
                data = e.read()
                self.send_response(e.code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

        def do_GET(self):  # 健康检查 / models 透传
            req = urllib.request.Request(UPSTREAM + ("/v1" + self.path
                                         if not self.path.startswith("/v1")
                                         else self.path))
            if self.headers.get("Authorization"):
                req.add_header("Authorization", self.headers["Authorization"])
            try:
                with urllib.request.urlopen(req, timeout=60) as resp:
                    data = resp.read()
                    self.send_response(resp.status)
                    self.send_header("Content-Length", str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
            except Exception:
                self.send_response(502)
                self.end_headers()

    return Handler


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=18923)
    ap.add_argument("--log", required=True)
    a = ap.parse_args()
    srv = ThreadingHTTPServer(("127.0.0.1", a.port), make_handler(a.log))
    print(f"proxy on 127.0.0.1:{a.port} -> {UPSTREAM}, logging to {a.log}",
          flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
