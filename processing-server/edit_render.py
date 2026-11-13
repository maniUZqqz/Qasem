#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""edit.render - the final render of the video editor, done on this computer (agent 2.2).

The site builds the whole ffmpeg filtergraph (the same one it would run itself) and sends it as a job:

    payload = {graph, inputs: [{file, args}], texts: {token: ASS text}, assets: {token: file id}, fonts: [file ids],
               audio, audio_args, encode: {cpu, nvenc, codec}, files: {id: {name, size, sha256}}, selftest, out, length}

This module (1) downloads what it does not have yet - HTTP Range, resumes after every break, size + sha256 checked by
nm_fetch, kept in <data>/cache/edit-assets by sha256 so the next export of the same project downloads nothing;
(2) proves it lays Persian text out like the site does (a test line through libass with the shipped Vazirmatn, ink pixels
compared with the site's number); (3) runs ffmpeg - NVENC when this card can, else x264/x265 - reporting progress and
stopping when the site cancels; (4) uploads the result in resumable chunks (the site checks size + sha256).

Progress messages are short codes the site turns into Persian: download|i|n, selftest, prepare, render|NN%, upload|NN%.
Python 3.8+ standard library only (plus nm_fetch next to it). Console text is English on purpose.

`caps(agent)` is what the heartbeat reports under capabilities["edit"] (computed once in the background); the site only
sends a render to a node whose caps say render=true. Agent 2.5 adds: matte_engine ("rvm" | "birefnet" | "rvm-pending" | ""),
rvm {runtime, model, provider, ort} and cache (16-hex sha256 prefixes of the originals already on this node - the site sends a
quick draft here only when it will not have to upload them).
"""
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

import nm_fetch

VERSION = "1.0"
CHUNK = 8 << 20
STALL_S = int(os.environ.get("NM_STALL_S") or nm_fetch.STALL_DEFAULT)
CACHE_LIMIT = int(float(os.environ.get("NM_EDIT_CACHE_GB") or 8) * (1 << 30))

#: every filter the editor's graph may use; a node whose ffmpeg lacks one reports it in caps.edit.missing and gets no render
REQUIRED_FILTERS = (
    "ass", "xfade", "geq", "chromakey", "despill", "alphamerge", "lut3d", "overlay", "blend", "scale", "rotate", "trim", "tpad",
    "reverse", "areverse", "setpts", "fps", "format", "color", "split", "asplit", "concat", "null", "anull", "crop", "hflip", "vflip",
    "fade", "curves", "colorbalance", "huesaturation", "vibrance", "colorchannelmixer", "hqdn3d", "boxblur", "unsharp", "vignette",
    "noise", "negate", "amix", "alimiter", "afftdn", "loudnorm", "acompressor", "adelay", "atempo", "atrim", "asetpts", "afade",
    "pan", "volume", "aformat", "highpass", "lowpass", "equalizer",
)

_INFO = {}
_LOCK = threading.Lock()
_CAPS = {"state": None}


# ───────────────────────────────────────────── ffmpeg discovery

def ffmpeg_exe(agent=None, probe="cached"):
    """The best ffmpeg of this computer (agent 2.11, gpu.py): one with a working NVENC encoder first - the owner's NM_FFMPEG, the one
    the node installed itself, the video kit's, then PATH. probe="cached" never starts ffmpeg itself (the heartbeat calls this); the
    caps probe and the render job warm / use the full probe."""
    env = (os.environ.get("NM_FFMPEG") or "").strip().strip('"')
    if env and os.path.isfile(env):
        return env
    try:
        import gpu

        data = getattr(agent, "DATA", "") if agent is not None else ""
        best, _rep = gpu.best_ffmpeg(data, probe=probe)
        if best:
            return best
    except Exception:  # noqa: BLE001 - never worse than the plain lookup below
        pass
    found = shutil.which("ffmpeg")
    if found:
        return found
    if agent is not None:
        for name in ("ffmpeg.exe", "ffmpeg"):
            cand = agent.kit_dir("Video", "tools", "ffmpeg", "bin", name)
            if os.path.isfile(cand):
                return cand
    return None


def _run(cmd, timeout=60):
    return subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=subprocess.DEVNULL, timeout=timeout)


def ffmpeg_info(ff):
    """{version: (major, minor), filters: set, encoders: set} of this ffmpeg (cached by path + mtime)."""
    key = (ff, os.path.getmtime(ff))
    if key in _INFO:
        return _INFO[key]
    out = _run([ff, "-hide_banner", "-version"]).stdout.decode("utf-8", "replace")
    m = re.search(r"version\s+n?(\d+)\.(\d+)", out)
    version = (int(m.group(1)), int(m.group(2))) if m else ((99, 0) if "version N-" in out else (0, 0))
    filters = set(re.findall(r"^\s*[A-Z.]{2,3}\s+(\w+)\s+[A-Z|N]+->", _run([ff, "-hide_banner", "-filters"]).stdout.decode("utf-8", "replace"), re.M))
    encoders = set(re.findall(r"^\s*V[A-Z.]{5}\s+(\w+)\s", _run([ff, "-hide_banner", "-encoders"]).stdout.decode("utf-8", "replace"), re.M))
    _INFO[key] = {"version": version, "filters": filters, "encoders": encoders}
    return _INFO[key]


def nvenc_works(ff, codec="h264_nvenc"):
    """A real five-frame encode on the card (an encoder that is merely compiled in proves nothing)."""
    try:
        r = _run([ff, "-v", "error", "-f", "lavfi", "-i", "color=c=black:s=256x144:r=10:d=0.6", "-frames:v", "5", "-c:v", codec,
                  "-f", "null", "-"], timeout=40)
        return r.returncode == 0
    except Exception:  # noqa: BLE001
        return False


def _compute_caps(agent):
    ff = ffmpeg_exe(agent, probe=True)
    if not ff:
        return {"v": 1, "render": False, "why": "ffmpeg not found"}
    try:
        info = ffmpeg_info(ff)
    except Exception as e:  # noqa: BLE001
        return {"v": 1, "render": False, "why": "ffmpeg did not run: %s" % e}
    missing = [f for f in REQUIRED_FILTERS if f not in info["filters"]]
    nvenc = {}
    for label, enc in (("h264", "h264_nvenc"), ("h265", "hevc_nvenc")):
        nvenc[label] = enc in info["encoders"] and nvenc_works(ff, enc)
    have_cv = False
    try:
        import importlib.util

        have_cv = bool(importlib.util.find_spec("cv2")) and bool(importlib.util.find_spec("numpy"))
    except Exception:  # noqa: BLE001
        have_cv = False
    probe = {"runtime": False}
    if agent is not None:
        try:                                           # which Python of this computer can run RVM (asked once, cached)
            import edit_rvm

            st = edit_rvm.status(agent)
            probe = {"runtime": bool(st.get("runtime")), "provider": st.get("provider", ""), "ort": st.get("ort", "")}
        except Exception as e:  # noqa: BLE001
            probe = {"runtime": False, "why": str(e)[:120]}
    return {
        "v": 1, "render": not missing and "libx264" in info["encoders"], "ffmpeg": "%d.%d" % info["version"], "missing": missing,
        "nvenc": nvenc, "track": have_cv, "rvm_probe": probe,
    }


MATTE_MODEL_REL = ("Photo", "models", "background", "birefnet-lite.onnx")
#: how many cached originals the heartbeat names (16 hex characters of the sha256 each, most recently used first)
CACHE_REPORT = 300


def cache_listing(agent, limit=CACHE_REPORT):
    """The first 16 hex digits of the sha256 of every file in the asset cache - what the site reads to know which originals
    this node already holds (so it can send it a quick draft without a long upload)."""
    rows = []
    try:
        for e in os.scandir(cache_dir(agent)):
            if e.is_file() and not e.name.endswith(".part") and re.match(r"^[0-9a-f]{64}", e.name):
                rows.append((e.stat().st_atime, e.name[:16]))
    except OSError:
        return []
    rows.sort(reverse=True)
    return [name for _atime, name in rows[:limit]]


def _fresh(agent, base):
    """The parts of the report that change while the node runs (a few stats and one directory listing - no probing):
    which background-removal engine can work now, and which originals are cached."""
    birefnet = os.path.isfile(agent.kit_dir(*MATTE_MODEL_REL))
    probe = base.get("rvm_probe") or {}
    runtime = bool(probe.get("runtime"))
    model = False
    if runtime:
        try:
            import edit_rvm

            model = edit_rvm.have_model(agent.DATA)
        except Exception:  # noqa: BLE001
            model = False
    engine = "rvm" if runtime and model else "birefnet" if birefnet else "rvm-pending" if runtime else ""
    return {"matte": birefnet or runtime, "matte_engine": engine,
            "rvm": {"runtime": runtime, "model": model, "provider": probe.get("provider", ""), "ort": probe.get("ort", "")},
            "cache": cache_listing(agent)}


def caps(agent=None, wait=False):
    """What the heartbeat reports. The first call starts the probe in the background (NVENC test, filter list)."""
    with _LOCK:
        if _CAPS["state"] is None:
            _CAPS["state"] = {"v": 1, "render": False, "pending": True}

            def work():
                try:
                    result = _compute_caps(agent)
                except Exception as e:  # noqa: BLE001
                    result = {"v": 1, "render": False, "why": str(e)}
                with _LOCK:
                    _CAPS["state"] = result

            t = threading.Thread(target=work, daemon=True)
            t.start()
            _CAPS["thread"] = t
    if wait and _CAPS.get("thread") is not None:
        _CAPS["thread"].join(60)
    out = dict(_CAPS["state"])
    if agent is not None and "rvm_probe" in out:
        try:
            out.update(_fresh(agent, out))
            out.pop("rvm_probe", None)
        except Exception:  # noqa: BLE001 - never let this keep the heartbeat from going out
            pass
    return out


# ───────────────────────────────────────────── files

def cache_dir(agent):
    d = os.path.join(agent.DATA, "cache", "edit-assets")
    os.makedirs(d, exist_ok=True)
    return d


def prune_cache(folder, keep, limit=CACHE_LIMIT):
    """Drop the least recently used cached files until the folder fits `limit` (never the ones this job needs)."""
    rows = []
    for name in os.listdir(folder):
        p = os.path.join(folder, name)
        if os.path.isfile(p) and not name.endswith(".part") and p not in keep:
            st = os.stat(p)
            rows.append((st.st_atime, st.st_size, p))
    total = sum(os.path.getsize(os.path.join(folder, n)) for n in os.listdir(folder) if os.path.isfile(os.path.join(folder, n)))
    for _atime, size, p in sorted(rows):
        if total <= limit:
            break
        try:
            os.remove(p)
            total -= size
        except OSError:
            pass


def ensure_files(job, agent, files, say):
    """Download every file of the job that is not in the cache. → {fid: local path}"""
    base = agent.site_base()
    token = (agent.CONFIG or {}).get("token") or os.environ.get("NM_TOKEN") or ""
    folder = cache_dir(agent)
    local = {}
    n = len(files)
    keep = set()
    for i, (fid, meta) in enumerate(files.items(), 1):
        ext = os.path.splitext(meta.get("name") or "")[1].lower()[:8]
        dest = os.path.join(folder, meta["sha256"] + ext)
        keep.add(dest)
        local[fid] = dest
        if os.path.isfile(dest) and os.path.getsize(dest) == int(meta["size"]):
            os.utime(dest, None)
            continue
        say("download|%d|%d" % (i, n), 0.02 + 0.16 * (i - 1) / max(1, n))
        url = "%s/api/v1/compute/jobs/%s/files/%s/" % (base, job.uid, fid)
        last = [0.0]

        def out(msg, _i=i):
            if time.time() - last[0] > 8:
                last[0] = time.time()
                say("download|%d|%d" % (_i, n), 0.02 + 0.16 * (_i - 0.5) / max(1, n))

        try:
            nm_fetch.fetch_with_progress(url, dest, out=out, every=5.0, headers={"Authorization": "Node " + token},
                                         size=int(meta["size"]), sha256=meta["sha256"], stall=STALL_S, sleep=time.sleep)
        except nm_fetch.FetchError as e:
            raise RuntimeError("download of %s failed: %s" % (meta.get("name"), e))
    prune_cache(folder, keep)
    return local


# ───────────────────────────────────────────── ffmpeg runner

def filter_path(path):
    """A path the way an ffmpeg FILTER option wants it (same as the site's filter_path): / and \\: , single-quoted."""
    return "'%s'" % str(path).replace("\\", "/").replace(":", "\\:")


def count_ink(raw, w, h):
    xs0, xs1, ys0, ys1, n = w, -1, h, -1, 0
    for i, b in enumerate(raw[: w * h]):
        if b > 128:
            n += 1
            x, y = i % w, i // w
            xs0, xs1 = min(xs0, x), max(xs1, x)
            ys0, ys1 = min(ys0, y), max(ys1, y)
    return {"count": n, "x0": xs0, "x1": xs1, "y0": ys0, "y1": ys1}


def selftest(ff, test, fonts_dir, work):
    """Lay the site's test line out here and compare with the site's measurement. → None when alike, else a sentence."""
    w, h = int(test["w"]), int(test["h"])
    f = os.path.join(work, "selftest.ass")
    with open(f, "w", encoding="utf-8") as fh:
        fh.write(test["ass"])
    r = _run([ff, "-v", "error", "-f", "lavfi", "-i", "color=c=black:s=%dx%d:r=10:d=1" % (w, h), "-vf",
              "ass=filename=%s:fontsdir=%s,format=gray" % (filter_path(f), filter_path(fonts_dir)), "-ss", str(test.get("at", 0.3)),
              "-frames:v", "1", "-f", "rawvideo", "-"], timeout=60)
    if len(r.stdout) < w * h:
        return "libass could not draw the test line here: %s" % r.stderr.decode("utf-8", "replace")[-200:]
    got, want = count_ink(r.stdout, w, h), test["expect"]
    if want["count"] <= 0:
        return None
    dc = abs(got["count"] - want["count"]) / want["count"]
    ww, gw = want["x1"] - want["x0"], got["x1"] - got["x0"]
    dw = abs(gw - ww) / max(1, ww)
    if dc > float(test.get("count_tol", 0.12)) or dw > float(test.get("width_tol", 0.04)):
        return "titles would not look like the site's here (ink %d vs %d, width %d vs %d) - the font is not the shipped one" % (
            got["count"], want["count"], gw, ww)
    return None


VIDEO_EXT = (".mp4", ".mov", ".mkv", ".webm", ".m4v", ".avi", ".mpg", ".mpeg", ".ts")


def build_command(ff, payload, local, work, nvenc, hw=None):
    p = payload
    texts = {}
    for i, (token, text) in enumerate(sorted(p.get("texts", {}).items())):
        f = os.path.join(work, "t%d.ass" % i)
        with open(f, "w", encoding="utf-8") as fh:
            fh.write(text)
        texts[token] = f
    graph = p["graph"]
    for token, f in texts.items():
        graph = graph.replace(token, filter_path(f)[1:-1])
    for token, fid in p.get("assets", {}).items():
        graph = graph.replace(token, filter_path(local[fid])[1:-1])
    fonts_dir = os.path.join(work, "fonts")
    graph = graph.replace("__FONTSDIR__", filter_path(fonts_dir)[1:-1])
    gfile = os.path.join(work, "graph.ffgraph")
    with open(gfile, "w", encoding="utf-8") as fh:
        fh.write(graph)
    flag = "-/filter_complex" if ffmpeg_info(ff)["version"] >= (7, 0) else "-filter_complex_script"
    cmd = [ff, "-y", "-hide_banner", "-nostats", "-loglevel", "error", "-progress", "pipe:1"]
    for inp in p["inputs"]:
        use_hw = list(hw or []) if os.path.splitext(str(local[inp["file"]]))[1].lower() in VIDEO_EXT else []
        cmd += use_hw + list(inp.get("args") or []) + ["-i", local[inp["file"]]]
    cmd += [flag, gfile, "-map", "[vout]"]
    if p.get("audio"):
        cmd += ["-map", "[aout]"] + list(p.get("audio_args") or [])
    enc = p["encode"]
    cmd += list(enc["nvenc"] if nvenc else enc["cpu"])
    out = os.path.join(work, p.get("out") or "render.mp4")
    cmd.append(out)
    return cmd, out


def run_ffmpeg(cmd, total, report, stall=7200):
    """Run ffmpeg; report(fraction) every ~3 s (it may raise - the site cancelled: ffmpeg is stopped and it propagates)."""
    err = tempfile.TemporaryFile()
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=err, stdin=subprocess.DEVNULL, universal_newlines=True, encoding="utf-8", errors="replace")
    state = {"t": 0.0}

    def read():
        for line in proc.stdout:
            if line.startswith("out_time_us=") or line.startswith("out_time_ms="):
                try:
                    state["t"] = max(state["t"], int(line.split("=", 1)[1]) / 1e6)
                except ValueError:
                    pass

    threading.Thread(target=read, daemon=True).start()
    last = 0.0
    started = time.time()
    try:
        while proc.poll() is None:
            time.sleep(0.5)
            if time.time() - last >= 3.0:
                last = time.time()
                report(min(0.99, state["t"] / total) if total > 0 else 0.0)
            if time.time() - started > stall:
                proc.kill()
                raise RuntimeError("ffmpeg did not finish in %d s" % stall)
    except BaseException:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
        err.close()
        proc.stdout.close()
        raise
    err.seek(0)
    detail = err.read().decode("utf-8", "replace").strip()[-800:]
    err.close()
    proc.stdout.close()
    if proc.returncode != 0:
        raise RuntimeError("ffmpeg failed (exit %s): %s" % (proc.returncode, detail))
    return state["t"]


# ───────────────────────────────────────────── upload

def sha256_file(path):
    return nm_fetch.sha256_file(path, 1 << 20)


def _request(method, url, token, data=None, timeout=120):
    req = urllib.request.Request(url, data=data, method=method, headers={"Authorization": "Node " + token, "Content-Type": "application/octet-stream"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as e:
        try:
            body = json.loads(e.read().decode("utf-8") or "{}")
        except ValueError:
            body = {}
        return e.code, body


def upload_resumable(job, agent, path, name, say):
    """Send `path` as <name> in 8 MB chunks; after a break ask the site how much it has and continue from there."""
    base = agent.site_base()
    token = (agent.CONFIG or {}).get("token") or os.environ.get("NM_TOKEN") or ""
    url = "%s/api/v1/compute/jobs/%s/chunks/%s/" % (base, job.uid, urllib.parse.quote(name))
    total = os.path.getsize(path)
    sha = sha256_file(path)
    offset, quiet_since, wait = 0, time.time(), 3
    while True:
        try:
            code, body = _request("GET", url, token)
            if code != 200:
                raise OSError("state HTTP %s" % code)
            have = int(body.get("size") or 0)
            offset = have if have <= total else 0
            break
        except (OSError, urllib.error.URLError) as e:
            if time.time() - quiet_since > STALL_S:
                raise RuntimeError("upload: the site is unreachable (%s)" % e)
            time.sleep(wait)
            wait = min(60, wait * 2)
    with open(path, "rb") as fh:
        while True:
            fh.seek(offset)
            chunk = fh.read(CHUNK)
            q = urllib.parse.urlencode({"offset": offset, "total": total, "sha256": sha})
            try:
                code, body = _request("PUT", url + "?" + q, token, chunk, timeout=300)
            except (OSError, urllib.error.URLError) as e:
                if time.time() - quiet_since > STALL_S:
                    raise RuntimeError("upload: the site is unreachable (%s)" % e)
                time.sleep(wait)
                wait = min(60, wait * 2)
                try:
                    c2, b2 = _request("GET", url, token)
                    if c2 == 200:
                        offset = int(b2.get("size") or 0)
                except (OSError, urllib.error.URLError):
                    pass
                continue
            if code == 409:
                offset = int(body.get("size") or 0)
                continue
            if code == 422:
                offset = 0
                quiet_since = time.time()
                say("upload|0%", 0.9)
                continue
            if code != 200:
                if code in (400, 401, 403, 404):
                    raise RuntimeError("upload refused (HTTP %s %s)" % (code, body))
                if time.time() - quiet_since > STALL_S:
                    raise RuntimeError("upload failed (HTTP %s)" % code)
                time.sleep(wait)
                wait = min(60, wait * 2)
                continue
            quiet_since, wait = time.time(), 3
            offset = int(body.get("size") or offset + len(chunk))
            say("upload|%d%%" % int(100 * offset / max(1, total)), 0.9 + 0.09 * offset / max(1, total))
            if body.get("complete") or offset >= total:
                return {"bytes": total, "sha256": sha}


# ───────────────────────────────────────────── the job

def run(job, agent):
    """The handler of edit.render (agent.h_edit_render calls it). → meta dict for the site."""
    p = job.payload
    t0 = time.time()
    say_state = {"t": 0.0}

    def say(message, fraction):
        if time.time() - say_state["t"] >= 2.0 or fraction >= 0.99 or message.startswith(("selftest", "prepare")):
            say_state["t"] = time.time()
            job.progress(max(0.02, min(0.99, fraction)), message)

    work = os.path.join(job.dir, "render")
    shutil.rmtree(work, ignore_errors=True)
    os.makedirs(work)
    ff = ffmpeg_exe(agent)
    if not ff:
        raise agent.JobError("ffmpeg is not installed on this node (the video kit brings it: Setup-Services.bat)", retryable=False)
    info = ffmpeg_info(ff)
    missing = [f for f in REQUIRED_FILTERS if f not in info["filters"]]
    if missing:
        raise agent.JobError("this ffmpeg lacks filters the editor needs: %s" % ", ".join(missing), retryable=False)
    say("prepare", 0.02)
    local = ensure_files(job, agent, p["files"], say)

    fonts_dir = os.path.join(work, "fonts")
    os.makedirs(fonts_dir)
    for fid in p.get("fonts") or []:
        shutil.copy2(local[fid], os.path.join(fonts_dir, p["files"][fid]["name"]))
    if p.get("selftest"):
        say("selftest", 0.19)
        why = selftest(ff, p["selftest"], fonts_dir, work)
        if why:
            raise agent.JobError("SELFTEST: " + why, retryable=False)

    codec = (p["encode"].get("codec") or "h264")
    ff = ffmpeg_exe(agent, probe=True) or ff
    want_nvenc = (caps(agent, wait=True).get("nvenc") or {}).get("h265" if codec == "h265" else "h264", False)
    hw = []
    try:                                   # NVDEC: decode the sources on the card; the (software) filters still get normal frames
        import gpu

        hw = gpu.hwaccel_args(gpu.ffmpeg_report(ff))
    except Exception:  # noqa: BLE001
        hw = []
    total = float(p.get("length") or 0)
    used_nvenc = bool(want_nvenc)
    say("render|0%", 0.2)

    def report(frac):
        job.progress(0.2 + 0.7 * frac, "render|%d%%" % int(frac * 100))

    cmd, out = build_command(ff, p, local, work, used_nvenc, hw)
    r0 = time.time()
    try:
        run_ffmpeg(cmd, total, report)
    except RuntimeError as e:
        if hw and re.search(r"cuda|cuvid|hwaccel|hardware", str(e), re.I) and not re.search(r"nvenc|OpenEncodeSession", str(e), re.I):
            agent.warn("GPU decoding (NVDEC) failed (%s) - decoding on the CPU instead" % str(e)[:200])
            hw = []
            cmd, out = build_command(ff, p, local, work, used_nvenc, hw)
            run_ffmpeg(cmd, total, report)
        elif used_nvenc and re.search(r"nvenc|NVENC|OpenEncodeSession|No capable devices", str(e)):
            agent.warn("NVENC failed (%s) - encoding on the CPU instead" % str(e)[:200])
            used_nvenc = False
            cmd, out = build_command(ff, p, local, work, False, hw)
            run_ffmpeg(cmd, total, report)
        else:
            raise
    render_seconds = round(time.time() - r0, 1)
    if not os.path.isfile(out) or os.path.getsize(out) <= 0:
        raise RuntimeError("ffmpeg produced no file")
    say("upload|0%", 0.9)
    up = upload_resumable(job, agent, out, p.get("out") or "render.mp4", say)
    shutil.rmtree(work, ignore_errors=True)
    return {
        "engine": "edit.render", "encoder": ("NVENC " if used_nvenc else "") + ("H.265" if codec == "h265" else "H.264"),
        "decoder": "NVDEC" if hw else "CPU",
        "device_note": ("NVENC encode" if used_nvenc else "software encode (this ffmpeg / card has no NVENC for %s)" % codec)
                       + (", NVDEC decode" if hw else ", CPU decode"),
        "ffmpeg": "%d.%d" % info["version"], "bytes": up["bytes"], "sha256": up["sha256"], "render_seconds": render_seconds,
        "seconds_total": round(time.time() - t0, 1),
    }
