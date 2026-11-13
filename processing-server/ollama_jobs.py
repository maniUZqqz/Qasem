#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ollama.chat / ollama.generate on the node, streamed (agent 2.11). Python 3.8+ standard library only.

The log the owner pasted (2026-11-11): `job ... (ollama.generate) failed: RuntimeError: ollama service is not reachable at
http://127.0.0.1:11434: timed out`. Ollama WAS running: a long generation sent no byte for longer than the single socket
timeout, and the error text said "not reachable". This module fixes the cause, not the text:

  * the request is always sent with stream=true; the NDJSON stream is read line by line and folded into exactly the JSON a
    non-streaming call returns (so the site reads `ollama.json` as before), and the site is told the progress (tokens so far)
    every few seconds, which also keeps the job's lease alive - a long answer never meets a read timeout;
  * connecting and reading have separate budgets. Connect failure (refused / unreachable / connect timeout) = "not reachable";
    a read that stays silent for `first_byte_s` before the first byte = "the model is still loading" (waits - loading a 30B model
    from disk takes minutes and is NOT a failure; the clock is the job's own timeout), and later `idle_s` of silence = "stalled";
  * num_ctx is chosen for the card (gpu.num_ctx_for) unless the job states one, keep_alive defaults to ten minutes, and when the
    job ends /api/ps says how much of the model really sits in VRAM -> meta.device (cuda / mixed / cpu + the reason).
"""
import http.client
import json
import queue
import socket
import threading
import time
import urllib.parse

import gpu

VERSION = "1.0"
CONNECT_S = 8.0
FIRST_BYTE_S = 1500.0           # waiting for the first token includes loading the model from disk
IDLE_S = 180.0                  # silence between two tokens of a running answer
PROGRESS_EVERY_S = 8.0
DEFAULT_KEEP_ALIVE = "10m"


class OllamaConnectError(Exception):
    """Nothing listens / the connection could not be made."""


class OllamaReadTimeout(Exception):
    """Connected, but the server went silent for too long (`phase`: first-byte = loading, idle = mid-answer)."""

    def __init__(self, message, phase="idle", waited=0.0):
        super().__init__(message)
        self.phase = phase
        self.waited = waited


class OllamaHTTPError(Exception):
    def __init__(self, status, body):
        super().__init__("HTTP %s %s" % (status, body[:400]))
        self.status = status
        self.body = body


def _split(base_url):
    u = urllib.parse.urlparse(base_url)
    return u.hostname or "127.0.0.1", u.port or 80


def _reader(conn, data, q):
    """Runs in a thread: sends the request, waits for the answer (blocking - the model may be loading for minutes) and puts every
    NDJSON line on the queue. The main loop never blocks on the socket, so cancel / progress / silence limits always work."""
    try:
        conn.request("POST", q.path, body=data, headers={"Content-Type": "application/json; charset=utf-8",
                                                         "Accept": "application/x-ndjson"})
        resp = conn.getresponse()
        q.put(("head", resp.status))
        if resp.status >= 400:
            q.put(("err_http", (resp.status, resp.read().decode("utf-8", "replace"))))
            return
        while True:
            line = resp.readline()
            if not line:
                break
            q.put(("line", line))
        q.put(("eof", None))
    except Exception as e:  # noqa: BLE001 - closed by the main loop, reset by the peer ...
        q.put(("err", e))


class _Q(queue.Queue):
    path = "/"


def stream_request(base_url, path, body, connect_s=CONNECT_S, first_byte_s=FIRST_BYTE_S, idle_s=IDLE_S, total_s=1800,
                   on_line=None, cancelled=None, tick=None):
    """POST `body` (stream=true) and collect every NDJSON object; on_line(obj) is called for each as it arrives.

    Raises OllamaConnectError (could not connect / the connection broke), OllamaReadTimeout (connected but silent: phase
    first-byte = still loading, idle = stalled, limit = the job's own time ran out), OllamaHTTPError, InterruptedError (cancelled)."""
    host, port = _split(base_url)
    data = json.dumps(dict(body, stream=True), ensure_ascii=False).encode("utf-8")
    conn = http.client.HTTPConnection(host, port, timeout=connect_s)
    try:
        conn.connect()
    except (OSError, socket.timeout) as e:                       # refused, unreachable, connect timeout
        raise OllamaConnectError("cannot connect to ollama at %s: %s" % (base_url, e))
    conn.sock.settimeout(None)                                   # reads are watched by the loop below, not by the socket
    q = _Q()
    q.path = path
    threading.Thread(target=_reader, args=(conn, data, q), daemon=True, name="ollama-stream").start()
    deadline = time.time() + total_s
    objs, first, silent = [], True, 0.0
    try:
        while True:
            if cancelled and cancelled():
                raise InterruptedError("cancelled")
            if time.time() > deadline:
                raise OllamaReadTimeout("the job's time limit ran out while the answer was still coming", "limit", silent)
            try:
                kind, val = q.get(timeout=1.0)
            except queue.Empty:
                silent += 1.0
                if tick:
                    tick(silent)
                if time.time() > deadline:
                    raise OllamaReadTimeout("the job's time limit ran out while the answer was still coming", "limit", silent)
                limit = first_byte_s if first else idle_s
                if silent >= limit:
                    raise OllamaReadTimeout("ollama is running but sent nothing for %d s (%s)" % (
                        int(silent), "the model is still loading" if first else "the answer stalled"),
                        "first-byte" if first else "idle", silent)
                continue
            silent = 0.0
            if kind == "head":
                continue
            if kind == "err_http":
                raise OllamaHTTPError(val[0], val[1])
            if kind == "err":
                raise OllamaConnectError("connection to ollama broke: %s" % val)
            if kind == "eof":
                break
            first = False
            line = val.strip()
            if not line:
                continue
            try:
                obj = json.loads(line.decode("utf-8"))
            except ValueError:
                continue
            if isinstance(obj, dict) and obj.get("error"):
                raise OllamaHTTPError(500, str(obj["error"]))
            objs.append(obj)
            if on_line:
                on_line(obj)
            if isinstance(obj, dict) and obj.get("done"):
                break
        return objs
    finally:
        _abort(conn)


def _abort(conn):
    """Close the connection even while the reader thread is blocked in recv: shutdown() wakes it, a plain close() would wait for it."""
    try:
        if conn.sock is not None:
            conn.sock.shutdown(socket.SHUT_RDWR)
    except OSError:
        pass
    try:
        conn.close()
    except Exception:  # noqa: BLE001
        pass


def fold(objs, is_chat):
    """The NDJSON objects -> the single JSON object a non-streaming call would have returned."""
    text, think, calls = [], [], []
    final = {}
    for o in objs:
        if not isinstance(o, dict):
            continue
        if is_chat:
            m = o.get("message") or {}
            if m.get("content"):
                text.append(m["content"])
            if m.get("thinking"):
                think.append(m["thinking"])
            if m.get("tool_calls"):
                calls.extend(m["tool_calls"])
        else:
            if o.get("response"):
                text.append(o["response"])
            if o.get("thinking"):
                think.append(o["thinking"])
        if o.get("done") or not final:
            final = {k: v for k, v in o.items()}
    final = dict(final)
    if is_chat:
        msg = {"role": "assistant", "content": "".join(text)}
        if think:
            msg["thinking"] = "".join(think)
        if calls:
            msg["tool_calls"] = calls
        final["message"] = msg
    else:
        final["response"] = "".join(text)
        if think:
            final["thinking"] = "".join(think)
    final["done"] = True
    return final


def tokens_in(obj):
    return 1 if isinstance(obj, dict) and (obj.get("response") or (obj.get("message") or {}).get("content")
                                          or (obj.get("message") or {}).get("thinking") or obj.get("thinking")) else 0


def friendly_http(status, body, model):
    low = (body or "").lower()
    if status == 404 or "not found" in low:
        return ("model '%s' is not installed on this node (ollama said: %s). Install it from the panel (AI priority > download model)"
                % (model, body[:160]))
    if "requires more system memory" in low or "out of memory" in low or "cuda error" in low:
        return "ollama ran out of memory loading '%s': %s" % (model, body[:200])
    return "ollama answered HTTP %s: %s" % (status, body[:300])


def prepare_body(payload, base_url, vram_total_mb=None, http_get=None):
    """Job payload -> (path, body, info): num_ctx / keep_alive defaults for the card, images left as they are (the caller
    already turned input names into base64)."""
    p = dict(payload)
    path = p.pop("path", None) or ("/api/chat" if "messages" in p else "/api/generate")
    info = {}
    opts = dict(p.get("options") or {})
    model = str(p.get("model") or "")
    if "num_ctx" not in opts and http_get is not None and model:
        try:
            tags = http_get(base_url + "/api/tags") or {}
            size = next((m.get("size") for m in tags.get("models", []) if m.get("name") == model or m.get("model") == model), None)
            chars = len(json.dumps(p.get("messages") or p.get("prompt") or "", ensure_ascii=False))
            ctx, fits = gpu.num_ctx_for(size, vram_total_mb, chars, int(opts.get("num_predict") or 1024))
            if size or vram_total_mb:
                opts["num_ctx"] = ctx
                info["num_ctx"] = ctx
                info["model_mb"] = round((size or 0) / 1e6)
                if fits is False:
                    info["too_big"] = True
        except Exception:  # noqa: BLE001 - a missing tags answer must not block the job
            pass
    if opts:
        p["options"] = opts
    p.setdefault("keep_alive", DEFAULT_KEEP_ALIVE)
    return path, p, info


def run(job, agent):
    """The handler of ollama.chat / ollama.generate / ollama.vision (registered by agent.py)."""
    import base64
    import os

    payload = dict(job.payload)

    def fix_images(obj):
        if isinstance(obj, dict):
            if isinstance(obj.get("images"), list):
                obj["images"] = [base64.b64encode(job.input_bytes(x)).decode() if job.input_path(x) else x for x in obj["images"]]
            for v in obj.values():
                fix_images(v)
        elif isinstance(obj, list):
            for v in obj:
                fix_images(v)

    fix_images(payload)
    base = agent.service_url("ollama")
    _used, vtotal = agent.vram_mb()

    def http_get(url):
        return agent.http("GET", url, timeout=6)

    path, body, info = prepare_body(payload, base, vtotal, http_get)
    model = str(body.get("model") or "?")
    is_chat = path.rstrip("/").endswith("/chat")
    num_predict = int((body.get("options") or {}).get("num_predict") or 0)
    state = {"tokens": 0, "last": 0.0, "t0": time.time()}
    if info.get("too_big"):
        agent.warn("ollama: '%s' (%d MB) is larger than the free VRAM; part of it will run on the CPU - num_ctx kept at %s"
                   % (model, info.get("model_mb", 0), info.get("num_ctx")))

    def say(msg, frac=None):
        job.progress(frac if frac is not None else min(0.95, 0.1 + 0.8 * (state["tokens"] / float(num_predict or 2000))), msg)

    def on_line(obj):
        state["tokens"] += tokens_in(obj)
        if time.time() - state["last"] >= PROGRESS_EVERY_S:
            state["last"] = time.time()
            say("ollama %s: %d tokens, %ds" % (model, state["tokens"], int(time.time() - state["t0"])))

    def tick(waited):
        if int(waited) % 20 == 0:
            say("ollama %s: loading the model ... %ds" % (model, int(waited)), 0.08)

    try:
        objs = stream_request(base, path, body, first_byte_s=FIRST_BYTE_S, idle_s=IDLE_S, total_s=max(60, job.timeout_s - 20),
                              on_line=on_line, cancelled=lambda: job.cancelled, tick=tick)
    except InterruptedError:
        raise agent.Cancelled()
    except OllamaConnectError as e:
        raise agent.JobError("ollama service is not reachable at %s: %s" % (base, e))
    except OllamaReadTimeout as e:
        raise agent.JobError("ollama is running but did not finish in time (%s; waited %ds). The model may be too large for this GPU "
                             "or stuck - see logs\\service-ollama.log" % (e, int(e.waited)))
    except OllamaHTTPError as e:
        raise agent.JobError(friendly_http(e.status, e.body, model), retryable=e.status >= 500)
    obj = fold(objs, is_chat)
    with open(job.out("ollama.json"), "w", encoding="utf-8") as fh:
        json.dump(obj, fh, ensure_ascii=False, indent=2)
    meta = {"primary": "ollama.json", "engine": "ollama", "model": model, "tokens": obj.get("eval_count") or state["tokens"],
            "seconds_total": round(time.time() - state["t0"], 1), "streamed": True}
    if obj.get("load_duration"):
        meta["load_s"] = round(obj["load_duration"] / 1e9, 1)
    if info.get("num_ctx"):
        meta["num_ctx"] = info["num_ctx"]
    try:                                            # how much of the model really sits on the card
        device, note = gpu.ollama_device(agent.http("GET", base + "/api/ps", timeout=6))
        meta["device"], meta["device_note"] = device, note
    except Exception:  # noqa: BLE001
        pass
    return meta
