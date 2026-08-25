#!/usr/bin/env python3
"""Local caller for the res agent and its demo screen."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
ROLE = (ROOT / ".claude/agents/res.md").read_text(encoding="utf-8")


def load_key():
    for path in (ROOT / ".env", ROOT / "backend/.env"):
        if path.exists():
            for line in path.read_text(encoding="utf-8").splitlines():
                if line.startswith("ANTHROPIC_API_KEY="):
                    return line.split("=", 1)[1].strip()
    return os.environ.get("ANTHROPIC_API_KEY", "")


def call_agent(text):
    key = load_key()
    if not key:
        raise RuntimeError("ANTHROPIC_API_KEY를 찾을 수 없습니다")
    payload = json.dumps({
        "model": "claude-haiku-4-5-20251001",
        "max_tokens": 700,
        "system": ROLE,
        "messages": [{"role": "user", "content": text}],
    }).encode()
    request = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=payload,
        headers={
            "content-type": "application/json",
            "x-api-key": key,
            "anthropic-version": "2023-06-01",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        body = json.loads(response.read())
    return "".join(block.get("text", "") for block in body.get("content", []))


class Handler(BaseHTTPRequestHandler):
    def send_json(self, status, value):
        data = json.dumps(value, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("content-type", "application/json; charset=utf-8")
        self.send_header("content-length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path != "/":
            self.send_error(404)
            return
        data = (ROOT / "res/screen.html").read_bytes()
        self.send_response(200)
        self.send_header("content-type", "text/html; charset=utf-8")
        self.send_header("content-length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        if self.path != "/call-agent":
            self.send_error(404)
            return
        try:
            length = int(self.headers.get("content-length", "0"))
            text = json.loads(self.rfile.read(length)).get("text", "").strip()
            if not text:
                self.send_json(400, {"error": "넣을 글이 없습니다"})
                return
            self.send_json(200, {"result": call_agent(text)})
        except Exception as error:
            self.send_json(500, {"error": str(error)})

    def log_message(self, *_):
        pass


if __name__ == "__main__":
    ThreadingHTTPServer(("127.0.0.1", 8787), Handler).serve_forever()
