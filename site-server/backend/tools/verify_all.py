# -*- coding: utf-8 -*-
"""Run every check there is, and leave a report that explains itself.

This is what `verify-all.bat` runs. The batch file is only a launcher, on
purpose: the first version of all this WAS a batch file, and its own test run
showed the two things batch cannot do —

  * it cannot give a step a time limit, so one hung step hangs the whole run
    forever (it did: the queued end-to-end test, on a machine short of RAM);
  * a redirected Python buffers its output, so at the moment it hung the log
    was EMPTY — the one time the log mattered.

So every step here runs with a timeout, its whole process tree is killed when
the timeout passes, and children run unbuffered so the log is current to the
second. A hang becomes a FAIL with the last lines of what it was doing.

Output, all under logs/verify/ (tracked by git, so push.bat carries it back):
    SUMMARY.txt     one PASS/FAIL/NOTE line per step, with how long it took
    ERRORS.txt      for every failure: what broke, the lines that say why,
                    and — for the real-stack step — what to do about it
    NN-*.log        the full log of each step
    artifacts/      the image and clip the real models produced
"""
import argparse
import os
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BACKEND = Path(__file__).resolve().parent.parent
ROOT = BACKEND.parent
FRONTEND = ROOT / "frontend"
WEBSITE = ROOT / "website"
OUT = ROOT / "logs" / "verify"

sys.path.insert(0, str(Path(__file__).resolve().parent))
import verify_tail  # noqa: E402  (same folder)

MIN = 60
FAILS = []
STARTED_REDIS = None


# ===================================================================== plumbing
def say(text=""):
    print(text, flush=True)


def summary(line):
    with open(OUT / "SUMMARY.txt", "a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def errors(text):
    with open(OUT / "ERRORS.txt", "a", encoding="utf-8") as fh:
        fh.write(text + "\n")


def port_open(port, host="127.0.0.1"):
    try:
        with socket.create_connection((host, port), timeout=1):
            return True
    except OSError:
        return False


def child_env():
    env = dict(os.environ)
    env["PYTHONUNBUFFERED"] = "1"          # the log must be current when a step hangs
    env["PYTHONIOENCODING"] = "utf-8"
    local_ffmpeg = ROOT / "ffmpeg" / "bin"
    if (local_ffmpeg / "ffmpeg.exe").exists():
        env["PATH"] = str(local_ffmpeg) + os.pathsep + env.get("PATH", "")
    return env


def kill_tree(pid):
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True)
    else:
        try:
            os.killpg(os.getpgid(pid), 9)
        except Exception:  # noqa: BLE001
            pass


def npm(*args):
    """npm and npx are .cmd shims on Windows; cmd /c is the one way to run them
    that works whether or not the path has spaces and brackets in it."""
    return (["cmd", "/c"] if os.name == "nt" else []) + list(args)


def run_step(name, cmd, cwd, log_name, timeout, informational=False, err_name=None):
    """Run one step. Returns True on success. Never raises, never hangs."""
    log_path = OUT / log_name
    say("[..] %s   (limit %d min)" % (name, timeout // MIN))
    t0 = time.time()
    rc, timed_out = 1, False
    try:
        with open(log_path, "wb") as out:
            err = open(OUT / err_name, "wb") if err_name else subprocess.STDOUT
            flags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
            p = subprocess.Popen(cmd, cwd=str(cwd), env=child_env(), stdin=subprocess.DEVNULL,
                                 stdout=out, stderr=err, creationflags=flags)
            last_beat = t0
            while True:
                try:
                    rc = p.wait(timeout=5)
                    break
                except subprocess.TimeoutExpired:
                    now = time.time()
                    if now - t0 > timeout:
                        timed_out = True
                        kill_tree(p.pid)
                        rc = 124
                        break
                    if now - last_beat >= 120:
                        say("     ... still running, %d min so far" % ((now - t0) // MIN))
                        last_beat = now
            if err_name:
                err.close()
    except FileNotFoundError as e:
        rc = 127
        log_path.write_text("could not start: %s\n" % e, encoding="utf-8")
    took = time.time() - t0
    stamp = "%4.1f min" % (took / MIN)

    if informational:
        summary("[NOTE] %-52s %s  (informational — see %s)" % (name, stamp, log_name))
        say("[NOTE] %s" % name)
        return True
    if rc == 0:
        summary("[PASS] %-52s %s" % (name, stamp))
        say("[PASS] %s   (%s)" % (name, stamp.strip()))
        return True

    why = "TIMED OUT after %d min — killed" % (timeout // MIN) if timed_out else "exit code %s" % rc
    summary("[FAIL] %-52s %s  (%s — see %s and ERRORS.txt)" % (name, stamp, why, err_name or log_name))
    say("[FAIL] %s   (%s)" % (name, why))
    FAILS.append(name)
    errors(verify_tail.explain(str(OUT / (err_name or log_name)), "%s  —  %s" % (name, why)))
    return False


def note(text):
    summary("[NOTE] " + text)
    say("[NOTE] " + text)


# ===================================================================== redis, for the run
def start_redis():
    """The project's bundled Redis on :6379, if nothing is there already —
    so 'does the broker the app is configured for actually run' is a real test."""
    global STARTED_REDIS
    if port_open(6379):
        return
    exe = ROOT / "redis" / "redis-server.exe"
    if not exe.exists():
        return
    log = open(OUT / "svc-redis.log", "wb")
    STARTED_REDIS = subprocess.Popen([str(exe)], cwd=str(exe.parent), stdin=subprocess.DEVNULL,
                                     stdout=log, stderr=subprocess.STDOUT,
                                     creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    for _ in range(15):
        if port_open(6379):
            say("     ... started the bundled Redis for the duration of the run")
            return
        time.sleep(1)


def stop_redis():
    if STARTED_REDIS is not None:
        kill_tree(STARTED_REDIS.pid)


# ===================================================================== environment snapshot
def environment():
    lines = []

    def grab(title, cmd):
        lines.append("=== %s ===" % title)
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)
            lines.append((r.stdout or "") + (r.stderr or ""))
        except Exception as e:  # noqa: BLE001
            lines.append("(%s)" % e)

    grab("python", [sys.executable, "--version"])
    grab("node", npm("node", "--version"))
    grab("npm", npm("npm", "--version"))
    grab("git commit", ["git", "-C", str(ROOT), "log", "-1", "--format=%h %ci %s"])
    grab("GPU", ["nvidia-smi"])
    if os.name == "nt":
        grab("memory (KB)", ["wmic", "OS", "get", "FreePhysicalMemory,TotalVisibleMemorySize", "/value"])
    grab("ollama list", ["ollama", "list"])
    lines.append("=== ports ===")
    for port, what in ((8000, "backend"), (5173, "dashboard"), (3001, "website"), (6379, "redis"),
                       (11434, "ollama"), (8188, "comfyui")):
        lines.append("%-10s :%-6d %s" % (what, port, "LISTENING" if port_open(port) else "free"))
    (OUT / "00-environment.log").write_text("\n".join(lines), encoding="utf-8")


# ===================================================================== the run
def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--quick", action="store_true", help="skip the full test suite and the builds")
    ap.add_argument("--fastai", action="store_true", help="real stack: only 'is it there', no generation")
    ap.add_argument("--fullvideo", action="store_true", help="real stack: render a production-length clip (81 frames)")
    ap.add_argument("--noreal", action="store_true", help="skip the real-stack step entirely (no GPU on this machine)")
    args = ap.parse_args()

    if OUT.exists():
        shutil.rmtree(OUT, ignore_errors=True)
    OUT.mkdir(parents=True, exist_ok=True)

    py = sys.executable
    started = time.time()
    summary("UpMarket verification report")
    summary("machine : %s" % os.environ.get("COMPUTERNAME", "?"))
    summary("started : %s" % time.strftime("%Y-%m-%d %H:%M:%S"))
    summary("mode    : quick=%s fastai=%s fullvideo=%s noreal=%s" % (args.quick, args.fastai, args.fullvideo, args.noreal))
    summary("-" * 78)

    say("")
    say(" ============================================")
    say("   UpMarket — verifying everything")
    say("   report : logs\\verify\\SUMMARY.txt")
    say("   errors : logs\\verify\\ERRORS.txt")
    say(" ============================================")
    say("")

    try:
        environment()
        start_redis()

        # ---- 1. django
        run_step("django: manage.py check", [py, "manage.py", "check"], BACKEND, "01-django-check.log", 5 * MIN)
        # A fresh pull brings migrations this database has not seen. start.bat
        # applies them on launch; do the same, or every run right after a pull
        # reports a failure that only means "you have not started the app yet".
        run_step("django: apply pending migrations", [py, "manage.py", "migrate", "--noinput"],
                 BACKEND, "02-migrate.log", 15 * MIN)
        run_step("django: no model change is missing a migration",
                 [py, "manage.py", "makemigrations", "--check", "--dry-run"], BACKEND, "03-migrations-missing.log", 5 * MIN)
        run_step("django: check --deploy", [py, "manage.py", "check", "--deploy"],
                 BACKEND, "04-deploy-check.log", 5 * MIN, informational=True)

        # ---- 2. the full suite. Django prints its verdict on stderr, so that
        # is the file that matters and the one ERRORS.txt is built from.
        if args.quick:
            note("backend: full test suite SKIPPED (--quick)")
        else:
            run_step("backend: full test suite (1400+ tests)", [py, "manage.py", "test", "--noinput"],
                     BACKEND, "05-tests.stdout.log", 120 * MIN, err_name="05-tests.log")
            try:
                for line in (OUT / "05-tests.log").read_text(encoding="utf-8", errors="replace").splitlines():
                    if line.startswith(("Ran ", "OK", "FAILED")):
                        summary("        " + line)
            except OSError:
                pass

        # ---- 3. simulated pipelines
        run_step("pipelines: selftest (simulated AI)", [py, "manage.py", "selftest"], BACKEND, "06-selftest.log", 45 * MIN)
        # --queue brings up its own Redis (on a free port) and its own Celery
        # workers; it only needs a redis-server binary to exist.
        can_queue = (ROOT / "redis" / "redis-server.exe").exists() or bool(shutil.which("redis-server"))
        run_step("pipelines: API end-to-end (%s)" % ("real Redis + Celery" if can_queue else "no queue"),
                 [py, "tools/e2e_api_test.py"] + (["--queue"] if can_queue else []),
                 BACKEND, "07-e2e.log", 60 * MIN)

        # ---- 4. the REAL stack: one model at a time. real_smoke.py has its own
        # per-stage timeouts (30 + 30 + 30 + 90 min worst case); this outer limit
        # only exists so that even a bug in that script cannot hang the run.
        if args.noreal:
            note("real stack SKIPPED (--noreal)")
        else:
            say("")
            say("     The next step loads the real models ONE AT A TIME and empties the GPU")
            say("     between them. On a 12 GB card it takes 20 to 60 minutes. That is normal.")
            flags = (["--fast"] if args.fastai else []) + (["--full-video"] if args.fullvideo else [])
            ok = run_step("real stack: models load, fit, and hand the GPU over",
                          [py, "tools/real_smoke.py", "--out", str(OUT)] + flags,
                          BACKEND, "08-real-stack.log", 240 * MIN)
            try:
                for line in (OUT / "08-real-stack.log").read_text(encoding="utf-8", errors="replace").splitlines():
                    if line.startswith(("[PASS]", "[FAIL]", "[WARN]", "[SKIP]", "       ...")):
                        summary("        " + line)
            except OSError:
                pass
            detail = OUT / "ERRORS-real-stack.txt"
            if detail.exists():
                errors(detail.read_text(encoding="utf-8", errors="replace"))
            del ok

        # ---- 5 + 6. the two frontends
        if args.quick:
            note("dashboard + website builds SKIPPED (--quick)")
        elif not shutil.which("npm"):
            summary("[FAIL] node/npm not found — dashboard and website not checked")
            FAILS.append("node/npm not found")
            errors("#" * 70 + "\nnode/npm در PATH نیست. Node.js LTS را از nodejs.org نصب کنید.\n")
        else:
            if not (FRONTEND / "node_modules" / ".bin" / "vite.cmd").exists():
                run_step("dashboard: npm install", npm("npm", "install", "--no-audit", "--no-fund"),
                         FRONTEND, "09-frontend-install.log", 30 * MIN)
            run_step("dashboard: tsc --noEmit + vite build", npm("npm", "run", "build"),
                     FRONTEND, "10-frontend-build.log", 30 * MIN)
            if not (WEBSITE / "node_modules" / ".bin" / "next.cmd").exists():
                run_step("website: npm install", npm("npm", "install", "--no-audit", "--no-fund"),
                         WEBSITE, "11-website-install.log", 30 * MIN)
            run_step("website: tsc --noEmit", npm("npx", "tsc", "--noEmit"), WEBSITE, "12-website-tsc.log", 20 * MIN)
            # `next build` rewrites .next, and start.bat serves the site FROM .next.
            # Building under a running site breaks it mid-request.
            if port_open(3001):
                note("website: next build SKIPPED — the site is running on :3001 and the build would pull .next out from under it")
            else:
                run_step("website: next build", npm("npm", "run", "build"), WEBSITE, "13-website-build.log", 45 * MIN)
    except KeyboardInterrupt:
        summary("[FAIL] interrupted by the user")
        FAILS.append("interrupted")
    finally:
        stop_redis()

    summary("-" * 78)
    summary("finished: %s   (%.0f min)" % (time.strftime("%Y-%m-%d %H:%M:%S"), (time.time() - started) / MIN))
    summary("failed steps: %d" % len(FAILS))

    say("")
    say(" ============================================")
    say("   Done. Failed steps: %d" % len(FAILS))
    say(" ============================================")
    say("")
    say((OUT / "SUMMARY.txt").read_text(encoding="utf-8"))
    if FAILS:
        say("  WHY each step failed, and what to do:  logs\\verify\\ERRORS.txt")
    else:
        say("  Everything passed.")
    say("  To send the report back: run push.bat in the repository root.")
    return len(FAILS)


if __name__ == "__main__":
    sys.exit(main())
