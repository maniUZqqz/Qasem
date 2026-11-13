"""اجرای رندر روی سرورِ سایت (و ساختنِ توضیحِ کارِ رندر برای گره).

یک اسکریپتِ Node (motion/tools/render.mjs) هم روی سایت و هم روی کامپیوترِ گرافیکی اجرا می‌شود؛ این‌جا فقط:
  · پیدا کردنِ Node، بسته (bundle)، مرورگرِ بی‌سر؛
  · ساختنِ job.json و اجرای امنِ فرایند (سقفِ زمان و حافظه، بدونِ رازِ محیطی، پیشرفت خط‌به‌خط)؛
  · کامپایلِ کدِ کاربر (sucrase) پس از اسکنِ امنیتی.

رندرِ نهایی به‌طورِ پیش‌فرض روی گره می‌رود؛ رندرِ سایت یک گزینهٔ محدود است: هم‌زمانیِ ۱، حداکثر ۱۰۸۰p و ۶۰ ثانیه، یک رندر در هر لحظه.
"""
from __future__ import annotations

import fcntl
import glob
import json
import logging
import math
import os
import shutil
import signal
import subprocess
import tempfile
import time
from pathlib import Path

from django.conf import settings

from . import safety

logger = logging.getLogger(__name__)

SITE_MAX_SECONDS = 60
SITE_MAX_SHORT_SIDE = 1080
SITE_TIMEOUT_S = 1500
SITE_MEMORY_MAX = "1700M"


class RenderError(RuntimeError):
    def __init__(self, message: str, code: str = "render"):
        super().__init__(message)
        self.code = code


# ───────────────────────────────────────────── where things are

def repo_motion_dir() -> Path:
    return Path(getattr(settings, "NM_MOTION_DIR", "") or Path(settings.BASE_DIR).parent / "motion")


def data_dir() -> Path:
    d = Path(getattr(settings, "NM_DATA_DIR", Path(settings.MEDIA_ROOT).parent)) / "motion"
    d.mkdir(parents=True, exist_ok=True)
    return d


def bundle_dir() -> Path:
    return data_dir() / "bundle"


def pack_dir() -> Path:
    return data_dir() / "pack"


def tools_dir() -> Path:
    return repo_motion_dir() / "tools"


def toolchain_dir() -> Path:
    return Path(getattr(settings, "NM_MOTION_TOOLCHAIN", "") or "/opt/nm-motion")


def node_bin() -> str | None:
    env = getattr(settings, "NM_MOTION_NODE", "") or os.environ.get("NM_MOTION_NODE", "")
    if env and Path(env).is_file():
        return env
    for cand in ("/opt/node/bin/node", "/usr/local/bin/node", "/usr/bin/node"):
        if Path(cand).is_file():
            return cand
    return shutil.which("node")


def browser_path() -> str | None:
    """Chrome headless shell برای رندر روی سایت."""
    env = getattr(settings, "NM_MOTION_BROWSER", "") or os.environ.get("NM_MOTION_BROWSER", "")
    if env and Path(env).is_file():
        return env
    pats = [str(data_dir() / "browser" / "*" / "chrome-headless-shell"),
            str(data_dir() / "browser" / "*" / "*" / "chrome-headless-shell"),       # motion_build --only browser: browser/linux64/chrome-headless-shell-linux64/
            "/opt/up3d-uitest/browsers/chromium_headless_shell-*/chrome-headless-shell-linux64/chrome-headless-shell"]
    for pat in pats:
        found = sorted(glob.glob(pat))
        if found:
            return found[-1]
    return None


def bundle_version() -> dict | None:
    try:
        return json.loads((bundle_dir() / "nm-motion-version.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def site_status() -> dict:
    """آیا این سایت می‌تواند همین الان رندر کند؟ (برای پنل و آزمون‌ها)"""
    node, browser = node_bin(), browser_path()
    bundle = bundle_version()
    tool = (tools_dir() / "render.mjs").is_file() and (repo_motion_dir() / "node_modules" / "@remotion" / "renderer").exists()
    reasons = []
    if not node:
        reasons.append("Node.js روی سایت نصب نیست")
    if not bundle:
        reasons.append("بستهٔ رندر ساخته نشده (manage.py motion_build)")
    if not browser:
        reasons.append("مرورگرِ بی‌سر پیدا نشد")
    if not tool:
        reasons.append("ابزارِ رندر (motion/node_modules) آماده نیست")
    return {"ready": not reasons, "reasons": reasons, "node": node, "browser": browser, "bundle": bundle}


# ───────────────────────────────────────────── user code

def compile_code(code: str, timeout: int = 20, scan: bool = True) -> dict:
    """{ok, js} یا {ok: False, error, line}. ابتدا اسکنِ امنیتی، بعد sucrase (scan=False فقط برای آزمونِ لایه‌های بعدیِ امنیت)."""
    if scan:
        try:
            safety.scan(code)
        except safety.UnsafeCode as exc:
            return {"ok": False, "error": str(exc), "line": exc.line, "kind": "unsafe"}
    node = node_bin()
    script = tools_dir() / "compile.mjs"
    if not node or not script.is_file() or not (repo_motion_dir() / "node_modules" / "sucrase").exists():
        return {"ok": False, "error": "کامپایلرِ کد روی سایت آماده نیست (manage.py motion_build).", "kind": "setup"}
    try:
        proc = subprocess.run([node, str(script)], input=code.encode("utf-8"), capture_output=True, timeout=timeout,
                              cwd=str(repo_motion_dir()), env=_clean_env())
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "کامپایل بیش از حد طول کشید.", "kind": "timeout"}
    try:
        res = json.loads(proc.stdout.decode("utf-8") or "{}")
    except ValueError:
        return {"ok": False, "error": (proc.stderr.decode("utf-8", "replace") or "کامپایل ناموفق")[:400], "kind": "compile"}
    if not res.get("ok"):
        res["kind"] = "syntax"
    return res


# ───────────────────────────────────────────── running a render on the site

def _clean_env() -> dict:
    """محیطِ فرایندِ رندر: هیچ رازی (کلیدِ API، دیتابیس) نمی‌رسد."""
    keep = {"PATH": "/usr/local/bin:/usr/bin:/bin", "LANG": "C.UTF-8", "HOME": tempfile.gettempdir(),
            "NODE_OPTIONS": "--max-old-space-size=768", "TMPDIR": tempfile.gettempdir()}
    return keep


def _tree_rss_mb(pid: int) -> float:
    """مجموعِ RSS ِ فرایند و فرزندانش (از /proc)."""
    total = 0.0
    try:
        kids: dict[int, list[int]] = {}
        for d in os.listdir("/proc"):
            if d.isdigit():
                try:
                    with open(f"/proc/{d}/stat") as fh:
                        parts = fh.read().rsplit(")", 1)[1].split()
                    kids.setdefault(int(parts[1]), []).append(int(d))
                except (OSError, IndexError, ValueError):
                    continue
        stack, seen = [pid], set()
        while stack:
            p = stack.pop()
            if p in seen:
                continue
            seen.add(p)
            stack.extend(kids.get(p, []))
            try:
                with open(f"/proc/{p}/statm") as fh:
                    total += int(fh.read().split()[1]) * os.sysconf("SC_PAGE_SIZE") / 1048576
            except (OSError, IndexError, ValueError):
                continue
    except OSError:
        return 0.0
    return total


def _kill_tree(proc: subprocess.Popen) -> None:
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except (ProcessLookupError, PermissionError, OSError):
        try:
            proc.kill()
        except OSError:
            pass


class SiteLock:
    """یک رندرِ سایت در هر لحظه (RAM ِ سایت کم است). منتظر می‌ماند و حالتِ انتظار را گزارش می‌دهد."""

    def __init__(self, wait_s: int = 1800):
        self.path = data_dir() / "site-render.lock"
        self.wait_s = wait_s
        self.fh = None

    def acquire(self, on_wait=None, cancelled=None) -> None:
        self.fh = open(self.path, "w")
        t0 = time.time()
        while True:
            try:
                fcntl.flock(self.fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
                return
            except OSError:
                if time.time() - t0 > self.wait_s:
                    raise RenderError("رندرِ دیگری روی سایت در حال اجراست و نوبتِ شما نرسید؛ کمی بعد دوباره امتحان کنید.", "busy")
                if cancelled and cancelled():
                    raise RenderError("لغو شد.", "cancelled")
                if on_wait:
                    on_wait(int(time.time() - t0))
                time.sleep(2)

    def release(self) -> None:
        try:
            if self.fh:
                fcntl.flock(self.fh, fcntl.LOCK_UN)
                self.fh.close()
        finally:
            self.fh = None


def run_render(job: dict, *, workdir: Path, on_progress=None, cancelled=None, timeout: int = SITE_TIMEOUT_S,
               site_caps: bool = True) -> dict:
    """job (render.mjs) را اجرا می‌کند ⇒ پیامِ done. خطا ⇒ RenderError با پیامِ فارسی."""
    st = site_status()
    if not st["ready"]:
        raise RenderError("رندر روی سایت الان ممکن نیست: " + "؛ ".join(st["reasons"]), "setup")
    workdir.mkdir(parents=True, exist_ok=True)
    job = dict(job)
    job.setdefault("serve", str(bundle_dir()))
    job.setdefault("browser", st["browser"])
    job.setdefault("gl", "swangle")
    job.setdefault("concurrency", 1)
    job.setdefault("offline", True)
    if site_caps:
        job["max_seconds"] = min(float(job.get("max_seconds") or SITE_MAX_SECONDS), SITE_MAX_SECONDS)
        job["concurrency"] = 1
    jf = workdir / "job.json"
    jf.write_text(json.dumps(job, ensure_ascii=False), encoding="utf-8")
    cmd = [st["node"], str(tools_dir() / "render.mjs"), str(jf)]
    if shutil.which("systemd-run") and os.geteuid() == 0 and not getattr(settings, "IS_TEST", False):
        cmd = ["systemd-run", "--scope", "--quiet", "--collect", "-p", f"MemoryMax={SITE_MEMORY_MAX}", "-p", "TasksMax=400", "-p", "CPUWeight=50", *cmd]
    cmd = ["nice", "-n", "10", *cmd]
    t0 = time.time()
    proc = subprocess.Popen(cmd, cwd=str(repo_motion_dir()), stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=_clean_env(),
                            start_new_session=True, text=True, bufsize=1, encoding="utf-8", errors="replace")
    done: dict | None = None
    err: dict | None = None
    stderr_tail: list[str] = []
    import queue
    import threading

    lines: "queue.Queue[str | None]" = queue.Queue()

    def read_out():
        for ln in proc.stdout:  # type: ignore[union-attr]
            lines.put(ln)
        lines.put(None)

    def drain():
        for ln in proc.stderr:  # type: ignore[union-attr]
            stderr_tail.append(ln)
            del stderr_tail[:-30]

    threads = [threading.Thread(target=read_out, daemon=True), threading.Thread(target=drain, daemon=True)]
    for t in threads:
        t.start()
    peak = 0.0
    last_mem = 0.0
    try:
        eof = False
        while not eof:
            try:
                ln = lines.get(timeout=1.0)
            except queue.Empty:
                ln = ""
            if ln is None:
                eof = True
            elif ln.strip().startswith("{"):
                try:
                    ev = json.loads(ln.strip())
                except ValueError:
                    ev = None
                if ev:
                    if ev.get("ev") == "progress" and on_progress:
                        on_progress(ev)
                    elif ev.get("ev") == "done":
                        done = ev
                    elif ev.get("ev") == "error":
                        err = ev
            now = time.time()
            if now - t0 > timeout:
                _kill_tree(proc)
                raise RenderError("رندر بیش از مهلت طول کشید و متوقف شد.", "timeout")
            if cancelled and cancelled():
                _kill_tree(proc)
                raise RenderError("لغو شد.", "cancelled")
            if now - last_mem > 2:
                last_mem = now
                peak = max(peak, _tree_rss_mb(proc.pid))
                if peak > 2400:
                    _kill_tree(proc)
                    raise RenderError("رندر بیش از حدِ مجازِ حافظه برد و متوقف شد.", "memory")
        proc.wait(timeout=30)
    finally:
        if proc.poll() is None:
            _kill_tree(proc)
        for t in threads:
            t.join(timeout=2)
    if err:
        raise RenderError(_fa_error(err.get("message", "")), err.get("code") or "render")
    if proc.returncode != 0 or not done:
        raise RenderError(_fa_error("".join(stderr_tail)[-400:] or f"کد خروج {proc.returncode}"), "render")
    done["peak_mb"] = round(peak)
    return done


def _fa_error(msg: str) -> str:
    m = (msg or "").strip()
    low = m.lower()
    if "too_long" in low or "longer than the allowed" in low:
        return "ویدیو از سقفِ مجازِ مدت بلندتر است."
    if "not allowed" in low and "module" in low:
        return "کد از ماژولِ غیرمجاز استفاده می‌کند: " + m[:200]
    if "delayrender" in low or "timeout" in low:
        return "یکی از فریم‌ها بیش از حد طول کشید (کدِ سنگین؟): " + m[:200]
    return ("رندر ناموفق بود: " + m[:400]) if m else "رندر ناموفق بود."


# ───────────────────────────────────────────── job descriptions

def scale_for(aspect_wh: tuple[int, int], quality: str, *, site: bool = False) -> float:
    from .specs import QUALITY

    k = QUALITY.get(quality, QUALITY["720"])
    if site:
        short = min(aspect_wh)
        k = min(k, SITE_MAX_SHORT_SIDE / short)
    return exact_scale(aspect_wh, k)


def exact_scale(dims: tuple[int, int], k: float) -> float:
    """Remotion refuses a render whose scaled size is not a whole number (`height` must be an integer: 1080 x 0.3333 = 359.964).
    k = 1/3 is not exact, so the float itself must be chosen so that width x scale and height x scale are exact integers in IEEE arithmetic
    (the node's JavaScript does the same multiplication): k itself when it works, else the nearest neighbouring double that does."""
    def ok(s: float) -> bool:
        return all(float(d * s).is_integer() for d in dims)

    if ok(k):
        return k
    up = down = k
    for _ in range(256):
        up, down = math.nextafter(up, 2.0), math.nextafter(down, 0.0)
        for s in (up, down):
            if ok(s):
                return s
    for s in (1.0, 0.5, 0.25):          # dyadic scales are always exact
        if s <= max(k, 0.25) and ok(s):
            return s
    return 1.0
