#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A tiny stand-in for Ollama (deploy/node/sim): lists the owner's four models and answers /api/generate and /api/chat with a canned JSON object.

Only for the node simulation on a test machine: it lets the REAL agent code path (heartbeat -> caps['ollama'] -> claim ollama.generate -> stream
NDJSON -> finish) and the site's deferred-AI queue run end to end without a GPU. It never produces anything the owner could mistake for a model answer
(the persona it returns is labelled 'SIM').
usage: fake_ollama.py <port>
"""
import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

MODELS = ["qwen3:8b", "qwq:32b", "qwen3-vl:30b", "qwen3-coder:30b"]

PERSONA = {"archetype": "sage", "secondary": "everyman", "tone": {"humor": 30, "formality": 35, "energy": 70, "warmth": 85, "directness": 60},
           "values": ["صداقت", "پشتیبانی", "پیشرفتِ قدم‌به‌قدم"], "do_words": ["قدم‌به‌قدم", "با هم"], "dont_words": ["معجزه"],
           "summary": "SIM: پاسخِ آزمایشیِ شبیه‌ساز (مدلِ واقعی نیست)"}


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, obj, code=200):
        data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path.startswith("/api/tags"):
            return self._send({"models": [{"name": m, "size": 1} for m in MODELS]})
        if self.path.startswith("/api/ps"):
            return self._send({"models": []})
        if self.path.startswith("/api/version"):
            return self._send({"version": "0.0.0-sim"})
        return self._send({"error": "not found"}, 404)

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(n) or b"{}")
        text = json.dumps(PERSONA, ensure_ascii=False)
        model = body.get("model") or MODELS[0]
        if self.path.startswith("/api/chat"):
            obj = {"model": model, "message": {"role": "assistant", "content": text}, "done": True, "eval_count": 5, "prompt_eval_count": 5}
        elif self.path.startswith("/api/generate"):
            obj = {"model": model, "response": text, "done": True, "eval_count": 5, "prompt_eval_count": 5}
        else:
            return self._send({"error": "not found"}, 404)
        line = (json.dumps(obj, ensure_ascii=False) + "\n").encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson")
        self.send_header("Content-Length", str(len(line)))
        self.end_headers()
        self.wfile.write(line)


if __name__ == "__main__":
    ThreadingHTTPServer(("127.0.0.1", int(sys.argv[1])), H).serve_forever()
