"""nm_control.py - the site's fixed commands for this processing node (2026-11-10).

    status    what runs: the agent and its version, START.bat windows, the services' ports, GPU, disk, the tunnel
    stop      closes START.bat and the agent (the services the agent started go with it; an Ollama you run yourself stays)
    start     starts START.bat in the signed-in user's desktop (task \\NMarketing\\Processing node), like a double-click
    restart   stop + start
    update    stop + update.py (the same as Update.bat) + start
    build     Build-Editors.bat (the photo / video / voice editors)
    logs [N]  the last N lines of the agent's log and of each service log

The site runs it through the remote tunnel (C:\\ProgramData\\NMarketing\\remote\\nm-control.cmd <command>, written by
Setup-Remote.bat); it can also be run by hand:  python nm_control.py status
Exit code 0 = done. Console text is ASCII on purpose (the Windows console garbles Persian).
"""
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

PROGRAMDATA = os.environ.get("ProgramData") or r"C:\ProgramData"
REMOTE = os.path.join(PROGRAMDATA, "NMarketing", "remote")
NODE_TASK = r"\NMarketing\Processing node"
SYSTEM32 = os.path.join(os.environ.get("SystemRoot") or r"C:\Windows", "System32")
POWERSHELL = os.path.join(SYSTEM32, "WindowsPowerShell", "v1.0", "powershell.exe")
PORTS = (("ollama", 11434), ("comfyui", 8188), ("voice", 5600), ("photo", 5670), ("video", 5680),
         ("moss", 5640), ("sfx", 5641), ("music", 5642))      # the agent's SERVICES defaults


def say(msg=""):
    print(msg, flush=True)


def data_dir():
    try:
        import nm_data

        return nm_data.data_root(HERE)
    except Exception:  # noqa: BLE001
        return os.path.join(os.path.expanduser("~"), "NMarketing-data")


def run(cmd, timeout=300, cwd=None):
    try:
        p = subprocess.run(cmd, capture_output=True, timeout=timeout, stdin=subprocess.DEVNULL, cwd=cwd)
    except FileNotFoundError as e:
        return 127, str(e)
    except subprocess.TimeoutExpired as e:
        return 124, ((e.stdout or b"") + (e.stderr or b"")).decode("utf-8", "replace") + "\n(timed out after %d s)" % timeout
    return p.returncode, ((p.stdout or b"") + (p.stderr or b"")).decode("utf-8", "replace")


# ───────────────────────────── processes

def processes():
    """[{pid, ppid, name, cmd}] from Win32_Process (wmic is gone from new Windows)."""
    code, out = run([POWERSHELL, "-NoProfile", "-NonInteractive", "-Command",
                     "[Console]::OutputEncoding=[Text.Encoding]::UTF8; Get-CimInstance Win32_Process | "
                     "Select-Object ProcessId,ParentProcessId,Name,CommandLine | ConvertTo-Json -Compress"], timeout=90)
    if code != 0:
        return []
    return parse_processes(out)


def parse_processes(text):
    try:
        rows = json.loads(text.strip() or "[]")
    except ValueError:
        return []
    if isinstance(rows, dict):
        rows = [rows]
    return [{"pid": r.get("ProcessId"), "ppid": r.get("ParentProcessId"), "name": (r.get("Name") or "").lower(),
             "cmd": r.get("CommandLine") or ""} for r in rows if isinstance(r, dict)]


_SCRIPT = re.compile(r'"?([A-Za-z]:\\[^"]*?\\)(agent\.py|START\.bat)"?', re.I)


def node_folder(cmdline, script):
    """The code folder of a node process (it has nm_data.py next to agent.py), else ''."""
    for m in _SCRIPT.finditer(cmdline or ""):
        if m.group(2).lower() == script.lower():
            folder = m.group(1).rstrip("\\")
            if os.path.isfile(os.path.join(folder, "nm_data.py")) or not sys.platform.startswith("win"):
                return folder
    return ""


def node_processes(rows=None):
    """(START.bat windows, agents) of any NMarketing node folder on this computer."""
    rows = processes() if rows is None else rows
    starts = [r for r in rows if r["name"] == "cmd.exe" and node_folder(r["cmd"], "START.bat")]
    agents = [r for r in rows if r["name"].startswith("python") and node_folder(r["cmd"], "agent.py")
              and "--version" not in r["cmd"] and "--prepare" not in r["cmd"]]
    return starts, agents


def version_of(folder):
    try:
        with open(os.path.join(folder, "agent.py"), encoding="utf-8", errors="replace") as fh:
            m = re.search(r'^VERSION = "([^"]+)"', fh.read(), re.M)
        return m.group(1) if m else "?"
    except OSError:
        return "?"


def listening(port, timeout=0.5):
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=timeout):
            return True
    except OSError:
        return False


# ───────────────────────────── commands

def status():
    starts, agents = node_processes()
    say("code folder : %s (agent v%s)" % (HERE, version_of(HERE)))
    say("data folder : %s" % data_dir())
    if agents:
        for a in agents:
            folder = node_folder(a["cmd"], "agent.py")
            say("agent       : RUNNING pid %s from %s (v%s)" % (a["pid"], folder, version_of(folder)))
    else:
        say("agent       : not running")
    say("START.bat   : %s" % (", ".join("pid %s" % s["pid"] for s in starts) or "no window"))
    say("services    : %s" % ", ".join("%s %s" % (k, "up" if listening(p) else "-") for k, p in PORTS))
    code, out = run(["nvidia-smi", "--query-gpu=name,memory.used,memory.total,utilization.gpu,temperature.gpu",
                     "--format=csv,noheader"], timeout=30)
    say("gpu         : %s" % (out.strip().replace("\n", " | ") if code == 0 else "nvidia-smi not available"))
    try:
        free = shutil.disk_usage(data_dir()).free / 1e9
        say("disk free   : %.1f GB (data drive)" % free)
    except OSError:
        pass
    rows = processes()
    signed_in = any(r["name"] == "explorer.exe" for r in rows)
    say("signed in   : %s" % ("yes (a desktop is open)" if signed_in else "NO - nobody is signed in; 'start' needs a signed-in user"))
    tail = tail_lines(os.path.join(REMOTE, "tunnel.log"), 2)
    if tail:
        say("tunnel log  : %s" % " | ".join(tail))
    return 0


def stop(quiet=False):
    starts, agents = node_processes()
    if not starts and not agents:
        if not quiet:
            say("the node is not running")
        return 0
    for r in starts + agents:              # the START.bat windows first: their loop would start the agent again
        code, out = run(["taskkill", "/T", "/F", "/PID", str(r["pid"])], timeout=60)
        say("stopped %s pid %s%s" % ("START.bat" if r in starts else "agent", r["pid"], "" if code == 0 else " (%s)" % out.strip()[-120:]))
    for _ in range(30):
        s, a = node_processes()
        if not s and not a:
            say("the node is stopped")
            return 0
        time.sleep(1)
    say("[!] something is still running: %s" % ", ".join(str(r["pid"]) for r in s + a))
    return 1


def ensure_node_task():
    """The task points at THIS code folder (the owner may unzip a new copy elsewhere)."""
    try:
        import remote_setup as RS

        user = RS.full_user()
        xml = RS.node_task_xml(user, HERE)
        RS.create_task(NODE_TASK, xml, ["/sc", "once", "/st", "23:59", "/it", "/tr", '"%s"' % os.path.join(HERE, "START.bat")])
        return True
    except Exception as e:  # noqa: BLE001 - an existing task still works
        say("(could not refresh the start task: %s)" % e)
        return False


def start():
    starts, agents = node_processes()
    if agents or starts:
        say("the node is already running (%s)" % ", ".join("pid %s" % r["pid"] for r in starts + agents))
        return 0
    ensure_node_task()
    code, out = run(["schtasks", "/run", "/tn", NODE_TASK], timeout=60)
    if code != 0:
        say("[!] could not start the task: %s" % out.strip()[-300:])
        return 1
    for _ in range(90):                     # START.bat first checks its registration and the site for an update
        time.sleep(2)
        s, a = node_processes()
        if a:
            say("the node is running (agent pid %s, v%s)" % (a[0]["pid"], version_of(node_folder(a[0]["cmd"], "agent.py"))))
            return 0
    signed_in = any(r["name"] == "explorer.exe" for r in processes())
    say("[!] the agent did not appear within 3 minutes%s" % (
        "" if signed_in else " - nobody is signed in to Windows on this computer (START.bat needs a desktop)"))
    return 1


def restart():
    code = stop()
    return start() if code == 0 else code


def update():
    stop()
    say("")
    say("--- update.py ---")
    code, out = run([sys.executable, os.path.join(HERE, "update.py"), "--auto"], timeout=1500, cwd=HERE)
    say(out.strip()[-6000:] or "(no output)")
    say("--- update.py exit %s ---" % code)
    say("")
    started = start()
    return code or started


def build():
    code, out = run(["cmd.exe", "/d", "/c", os.path.join(HERE, "Build-Editors.bat")], timeout=3500, cwd=HERE)
    say(out.strip()[-12000:] or "(no output)")
    return code


def decode_log(raw):
    if raw[:2] in (b"\xff\xfe", b"\xfe\xff") or (len(raw) > 16 and raw.count(b"\x00") > len(raw) // 4):
        body = raw[2:] if raw[:2] in (b"\xff\xfe", b"\xfe\xff") else raw
        if body[0::2].count(b"\x00") > body[1::2].count(b"\x00"):
            body = body[1:]
        return body[: len(body) // 2 * 2].decode("utf-16-le", "replace")
    return raw.decode("utf-8", "replace")


def tail_lines(path, n):
    try:
        with open(path, "rb") as fh:
            fh.seek(0, 2)
            size = fh.tell()
            fh.seek(max(0, size - 64000))
            text = decode_log(fh.read())
    except OSError:
        return []
    return [ln.rstrip() for ln in text.splitlines() if ln.strip()][-n:]


def logs(n=60):
    folder = os.path.join(data_dir(), "logs")
    names = ["agent.log"] + sorted(f for f in (os.listdir(folder) if os.path.isdir(folder) else [])
                                   if f.startswith("service-") and f.endswith(".log") and not f.endswith(".prev.log"))
    for name in names:
        lines = tail_lines(os.path.join(folder, name), n)
        if lines:
            say("===== %s (last %d lines) =====" % (name, len(lines)))
            for ln in lines:
                say(ln)
    return 0


COMMANDS = {"status": status, "stop": stop, "start": start, "restart": restart, "update": update, "build": build}


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    cmd = (argv[:1] or ["status"])[0].lower()
    say("=== nm_control %s on %s at %s ===" % (cmd, os.environ.get("COMPUTERNAME", "?"), time.strftime("%Y-%m-%d %H:%M:%S")))
    if cmd == "logs":
        n = int(argv[1]) if len(argv) > 1 and argv[1].isdigit() else 60
        return logs(min(n, 500))
    fn = COMMANDS.get(cmd)
    if not fn:
        say("unknown command '%s' - one of: %s, logs" % (cmd, ", ".join(COMMANDS)))
        return 2
    return fn()


if __name__ == "__main__":
    sys.exit(main())
