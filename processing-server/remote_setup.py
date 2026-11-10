"""Setup-Remote.bat - let the site reach this computer like a server (once, as Administrator). 2026-11-10.

What it does (nothing is opened to the internet or to the local network):
  1. installs the Windows OpenSSH server if it is missing (Windows' own optional feature, else the copy mirrored on the
     site) and makes it listen ONLY on 127.0.0.1 of this computer, keys only (no passwords);
  2. makes a key pair for the tunnel and registers it with the site (with this node's token from node.json);
  3. puts the site's administrator key in C:\\ProgramData\\ssh\\administrators_authorized_keys;
  4. a scheduled task "\\NMarketing\\Remote tunnel" (SYSTEM, at start-up, restarted if it stops) keeps a reverse SSH tunnel
     open to the site: the site reaches this computer's sshd through it - even when the node program is closed;
  5. a task "\\NMarketing\\Processing node" (on demand, in the signed-in user's desktop) lets the site start START.bat;
  6. C:\\ProgramData\\NMarketing\\remote\\nm-control.cmd runs nm_control.py (status / stop / start / restart / update /
     build / logs) from whichever code folder the node runs (the agent keeps home.txt up to date).
It asks the site to log in through the tunnel and says whether that worked.
  Setup-Remote.bat remove   - undo everything (tasks, keys, the tunnel; sshd is stopped and set to manual).
Console text is ASCII on purpose (the Windows console garbles Persian).
"""
import ctypes
import getpass
import hashlib
import json
import ntpath
import os
import platform
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

PROGRAMDATA = os.environ.get("ProgramData") or r"C:\ProgramData"
REMOTE = os.path.join(PROGRAMDATA, "NMarketing", "remote")
SSH_DATA = os.path.join(PROGRAMDATA, "ssh")
SSHD_CONFIG = os.path.join(SSH_DATA, "sshd_config")
ADMIN_KEYS = os.path.join(SSH_DATA, "administrators_authorized_keys")
OPENSSH_DIR = os.path.join(os.environ.get("ProgramFiles") or r"C:\Program Files", "OpenSSH")
SYSTEM32 = os.path.join(os.environ.get("SystemRoot") or r"C:\Windows", "System32")
POWERSHELL = os.path.join(SYSTEM32, "WindowsPowerShell", "v1.0", "powershell.exe")
ZIP_NAME = "OpenSSH-Win64-v9.8.3.0p2.zip"
ZIP_SHA256 = "0ca131f3a78f404dc819a6336606caec0db1663a692ccc3af1e90232706ada54"
TUNNEL_TASK = r"\NMarketing\Remote tunnel"
NODE_TASK = r"\NMarketing\Processing node"
SID_ADMINS = "*S-1-5-32-544"
SID_SYSTEM = "*S-1-5-18"
BLOCK_BEGIN = "# >>> NMarketing remote access (Setup-Remote.bat): only through the tunnel to the site"
BLOCK_END = "# <<< NMarketing"
KEY_MARK = "nm-vps-admin"


def say(msg=""):
    print(msg, flush=True)


def run(cmd, timeout=600, check=False, quiet=False):
    """subprocess.run with text output (errors replaced); returns (code, output)."""
    try:
        p = subprocess.run(cmd, capture_output=True, timeout=timeout, stdin=subprocess.DEVNULL)
    except FileNotFoundError as e:
        return 127, str(e)
    except subprocess.TimeoutExpired:
        return 124, "timed out after %d s" % timeout
    out = (p.stdout or b"").decode("utf-8", "replace") + (p.stderr or b"").decode("utf-8", "replace")
    if check and p.returncode != 0:
        raise SetupError("%s failed (%s): %s" % (cmd[0] if isinstance(cmd, list) else cmd, p.returncode, out.strip()[-600:]))
    if not quiet and p.returncode != 0:
        say("    (%s -> exit %s) %s" % (os.path.basename(cmd[0]) if isinstance(cmd, list) else cmd, p.returncode, out.strip()[-300:]))
    return p.returncode, out


def ps(script, timeout=600, check=False, quiet=False):
    return run([POWERSHELL, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command",
                "[Console]::OutputEncoding=[Text.Encoding]::UTF8; " + script], timeout=timeout, check=check, quiet=quiet)


class SetupError(Exception):
    pass


def is_admin():
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:  # noqa: BLE001
        return False


# ───────────────────────────── node identity (node.json written by START.bat the first time)

def node_config():
    import nm_data

    data = nm_data.data_root(HERE)
    cfg = {}
    for path in (os.path.join(data, "node.json"), os.path.join(HERE, "site.json")):
        try:
            with open(path, encoding="utf-8") as fh:
                for k, v in json.load(fh).items():
                    cfg.setdefault(k, v)
        except (OSError, ValueError):
            pass
    if not cfg.get("token") or not cfg.get("site"):
        raise SetupError("this computer is not registered yet - run START.bat once (it asks for the enrollment key), then run this again")
    cfg["site"] = str(cfg["site"]).rstrip("/")
    cfg["data"] = data
    return cfg


def site_call(cfg, method, path, body=None, timeout=60):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(cfg["site"] + path, data=data, method=method, headers={
        "Authorization": "Node " + cfg["token"], "Content-Type": "application/json", "User-Agent": "nm-remote-setup/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as e:
        detail = e.read()[:600].decode("utf-8", "replace")
        raise SetupError("the site said HTTP %s for %s: %s" % (e.code, path, detail))
    except (urllib.error.URLError, OSError) as e:
        raise SetupError("cannot reach the site %s: %s" % (cfg["site"], e))


# ───────────────────────────── OpenSSH server

def find_tool(name):
    for d in (os.path.join(SYSTEM32, "OpenSSH"), OPENSSH_DIR):
        p = os.path.join(d, name)
        if os.path.isfile(p):
            return p
    return shutil.which(name)


def sshd_installed():
    code, _ = run(["sc.exe", "query", "sshd"], quiet=True)
    return code == 0


def install_from_zip(cfg):
    url = "%s/3d/files/downloads/%s" % (cfg["site"], ZIP_NAME)
    tmp = os.path.join(REMOTE, ZIP_NAME)
    for attempt in range(1, 6):
        try:
            say("    downloading %s (attempt %d) ..." % (url, attempt))
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "nm-remote-setup/1.0"}), timeout=60) as r, \
                    open(tmp, "wb") as fh:
                shutil.copyfileobj(r, fh)
            with open(tmp, "rb") as fh:
                if hashlib.sha256(fh.read()).hexdigest() == ZIP_SHA256:
                    break
            say("    the download is damaged (sha256 differs) - again")
        except (urllib.error.URLError, OSError) as e:
            say("    download failed: %s" % e)
        time.sleep(5 * attempt)
    else:
        raise SetupError("could not download OpenSSH from the site")
    os.makedirs(OPENSSH_DIR, exist_ok=True)
    with zipfile.ZipFile(tmp) as z:
        for m in z.infolist():
            rel = m.filename.split("/", 1)[1] if "/" in m.filename else ""
            if not rel or m.is_dir():
                continue
            dest = os.path.join(OPENSSH_DIR, *rel.split("/"))
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            with z.open(m) as src, open(dest, "wb") as out:
                shutil.copyfileobj(src, out)
    os.remove(tmp)
    run([POWERSHELL, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", os.path.join(OPENSSH_DIR, "install-sshd.ps1")],
        timeout=300, check=True)


def ensure_sshd(cfg):
    if sshd_installed():
        say("[1/6] OpenSSH server: already installed")
    else:
        say("[1/6] OpenSSH server: installing Windows' own optional feature (may take a few minutes) ...")
        ps("Add-WindowsCapability -Online -Name OpenSSH.Server~~~~0.0.1.0 | Out-String", timeout=1200)
        if not sshd_installed():
            say("    Windows could not add it (often: no access to Windows Update) - using the copy on the site")
            install_from_zip(cfg)
        if not sshd_installed():
            raise SetupError("the OpenSSH server could not be installed")
    run(["sc.exe", "config", "sshd", "start=", "auto"], check=True)
    ps("Start-Service sshd", timeout=120)                    # the first start writes sshd_config and the host keys
    for _ in range(30):
        if os.path.isfile(SSHD_CONFIG):
            break
        time.sleep(1)
    if not os.path.isfile(SSHD_CONFIG):
        raise SetupError("sshd did not write %s" % SSHD_CONFIG)


def configured_sshd_text(text):
    """Our block at the very top (sshd takes the FIRST value of a keyword); any other active ListenAddress is
    commented out (ListenAddress adds up). The default 'Match Group administrators' block stays."""
    out = []
    skip = False
    for ln in text.splitlines():
        if ln.strip() == BLOCK_BEGIN:
            skip = True
            continue
        if skip:
            if ln.strip() == BLOCK_END:
                skip = False
            continue
        if ln.strip().lower().startswith("listenaddress "):
            ln = "#NM# " + ln
        out.append(ln)
    block = [BLOCK_BEGIN, "ListenAddress 127.0.0.1", "PasswordAuthentication no", "PubkeyAuthentication yes",
             "PermitEmptyPasswords no", BLOCK_END]
    return "\n".join(block + out).rstrip("\n") + "\n"


def configure_sshd():
    say("[2/6] OpenSSH server: only on 127.0.0.1 of this computer, keys only")
    with open(SSHD_CONFIG, encoding="utf-8", errors="replace") as fh:
        text = fh.read()
    new = configured_sshd_text(text)
    if new != text:
        shutil.copyfile(SSHD_CONFIG, SSHD_CONFIG + ".before-nmarketing") if not os.path.exists(
            SSHD_CONFIG + ".before-nmarketing") else None
        with open(SSHD_CONFIG, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(new)
    sshd = find_tool("sshd.exe")
    if sshd:
        code, out = run([sshd, "-t", "-f", SSHD_CONFIG], quiet=True)
        if code != 0:
            raise SetupError("sshd_config check failed: %s" % out.strip()[-400:])
    run(["reg", "add", r"HKLM\SOFTWARE\OpenSSH", "/v", "DefaultShell", "/t", "REG_SZ", "/d", POWERSHELL, "/f"], check=True)
    # nothing listens outside this computer, so the inbound rule Windows adds is not needed
    ps("Get-NetFirewallRule -Name 'OpenSSH-Server-In-TCP' -ErrorAction SilentlyContinue | Disable-NetFirewallRule", quiet=True)
    ps("Restart-Service sshd -Force", timeout=120, check=True)


def lock_down(path, extra_user=None, modify=False):
    """Only Administrators + SYSTEM (ssh refuses keys others can read); optionally one user may change a file."""
    run(["icacls", path, "/inheritance:r", "/grant:r", "%s:(OI)(CI)F" % SID_ADMINS if os.path.isdir(path) else "%s:F" % SID_ADMINS,
         "/grant:r", "%s:(OI)(CI)F" % SID_SYSTEM if os.path.isdir(path) else "%s:F" % SID_SYSTEM], check=True, quiet=True)
    if extra_user:
        run(["icacls", path, "/grant", "%s:%s" % (extra_user, "M" if modify else "RX")], quiet=True)


# ───────────────────────────── keys, tunnel, tasks

def tunnel_key():
    say("[3/6] tunnel key")
    os.makedirs(REMOTE, exist_ok=True)
    lock_down(REMOTE)
    key = os.path.join(REMOTE, "tunnel_key")
    if not (os.path.isfile(key) and os.path.isfile(key + ".pub")):
        for p in (key, key + ".pub"):
            if os.path.exists(p):
                os.remove(p)
        keygen = find_tool("ssh-keygen.exe")
        if not keygen:
            raise SetupError("ssh-keygen.exe not found")
        run([keygen, "-q", "-t", "ed25519", "-N", "", "-C", "nm-tunnel@%s" % platform.node(), "-f", key], check=True)
    lock_down(key)
    with open(key + ".pub", encoding="utf-8") as fh:
        return key, fh.read().strip()


def merge_admin_key(text, admin_pubkey):
    lines = [ln for ln in (text or "").splitlines() if ln.strip() and KEY_MARK not in ln]
    parts = admin_pubkey.split()
    return "\n".join(lines + ["%s %s %s" % (parts[0], parts[1], KEY_MARK)]) + "\n"


def install_admin_key(admin_pubkey):
    say("[4/6] the site's administrator key")
    try:
        with open(ADMIN_KEYS, encoding="utf-8") as fh:
            text = fh.read()
    except OSError:
        text = ""
    with open(ADMIN_KEYS, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(merge_admin_key(text, admin_pubkey))
    lock_down(ADMIN_KEYS)


def tunnel_cmd(ssh_exe, info):
    """The loop the SYSTEM task runs. `ping` instead of `timeout` (timeout needs a console; the task has none)."""
    return "\r\n".join([
        "@echo off",
        "rem NMarketing remote tunnel - written by Setup-Remote.bat; run by the task \\NMarketing\\Remote tunnel (SYSTEM)",
        "setlocal",
        'set "D=%~dp0"',
        ":loop",
        'if exist "%D%tunnel.log" for %%A in ("%D%tunnel.log") do if %%~zA GTR 1000000 move /y "%D%tunnel.log" "%D%tunnel.prev.log" >nul',
        'echo [%date% %time%] connecting to {host}>>"%D%tunnel.log"'.format(**info),
        ('"{ssh}" -N -T -o ExitOnForwardFailure=yes -o ServerAliveInterval=30 -o ServerAliveCountMax=3 -o ConnectTimeout=20 '
         '-o BatchMode=yes -o StrictHostKeyChecking=yes -o "UserKnownHostsFile=%D%known_hosts" -i "%D%tunnel_key" '
         '-p {ssh_port} -R 127.0.0.1:{listen_port}:127.0.0.1:{local_port} {user}@{host} >>"%D%tunnel.log" 2>&1').format(ssh=ssh_exe, **info),
        "ping -n 16 127.0.0.1 >nul",
        "goto loop",
        "",
    ])


def control_cmd():
    return "\r\n".join([
        "@echo off",
        "rem NMarketing - the site's fixed commands for this node (written by Setup-Remote.bat)",
        "setlocal",
        'set "D=%~dp0"',
        'set /p NMHOME=<"%D%home.txt"',
        'set /p NMPY=<"%D%python.txt"',
        'set "PYTHONIOENCODING=utf-8"',
        'set "PYTHONUNBUFFERED=1"',
        '"%NMPY%" "%NMHOME%\\nm_control.py" %*',
        "",
    ])


def task_xml(description, command, arguments, principal_xml, triggers_xml="", workdir=""):
    wd = "<WorkingDirectory>%s</WorkingDirectory>" % _x(workdir) if workdir else ""
    return """<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo><Description>%s</Description></RegistrationInfo>
  <Triggers>%s</Triggers>
  <Principals>%s</Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <AllowHardTerminate>true</AllowHardTerminate>
    <StartWhenAvailable>true</StartWhenAvailable>
    <RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable>
    <IdleSettings><StopOnIdleEnd>false</StopOnIdleEnd><RestartOnIdle>false</RestartOnIdle></IdleSettings>
    <AllowStartOnDemand>true</AllowStartOnDemand>
    <Enabled>true</Enabled>
    <Hidden>false</Hidden>
    <RunOnlyIfIdle>false</RunOnlyIfIdle>
    <WakeToRun>false</WakeToRun>
    <ExecutionTimeLimit>PT0S</ExecutionTimeLimit>
    <Priority>7</Priority>
    <RestartOnFailure><Interval>PT1M</Interval><Count>999</Count></RestartOnFailure>
  </Settings>
  <Actions Context="Author"><Exec><Command>%s</Command><Arguments>%s</Arguments>%s</Exec></Actions>
</Task>
""" % (_x(description), triggers_xml, principal_xml, _x(command), _x(arguments), wd)


def _x(s):
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def tunnel_task_xml():
    return task_xml(
        "NMarketing: keeps the tunnel to the site open so the site can reach this computer (Setup-Remote.bat)",
        os.path.join(SYSTEM32, "cmd.exe"), '/d /c "%s"' % os.path.join(REMOTE, "tunnel.cmd"),
        '<Principal id="Author"><UserId>S-1-5-18</UserId><RunLevel>HighestAvailable</RunLevel></Principal>',
        "<BootTrigger><Enabled>true</Enabled></BootTrigger>"
        "<TimeTrigger><Repetition><Interval>PT5M</Interval><StopAtDurationEnd>false</StopAtDurationEnd></Repetition>"
        "<StartBoundary>2026-01-01T00:00:00</StartBoundary><Enabled>true</Enabled></TimeTrigger>")


def node_task_xml(user, home):
    """On demand only (no trigger): the site's «start» runs START.bat in the signed-in user's desktop, like a double-click."""
    return task_xml(
        "NMarketing: the processing node (START.bat) - started by the site's remote «start» (Setup-Remote.bat)",
        os.path.join(SYSTEM32, "cmd.exe"), '/d /c "%s"' % ntpath.join(home, "START.bat"),
        '<Principal id="Author"><UserId>%s</UserId><LogonType>InteractiveToken</LogonType><RunLevel>LeastPrivilege</RunLevel></Principal>' % _x(user),
        "", workdir=home)


def create_task(name, xml, fallback):
    path = os.path.join(REMOTE, "task-%s.xml" % name.rsplit("\\", 1)[-1].replace(" ", "-").lower())
    with open(path, "w", encoding="utf-16") as fh:
        fh.write(xml)
    code, out = run(["schtasks", "/create", "/tn", name, "/xml", path, "/f"], quiet=True)
    if code != 0:
        say("    the full task definition was refused (%s) - using the simple form" % out.strip()[-200:])
        run(["schtasks", "/create", "/tn", name, "/f"] + fallback, check=True)


def write_text(path, text, encoding="utf-8"):
    with open(path, "w", encoding=encoding, newline="") as fh:
        fh.write(text)


def full_user():
    dom = os.environ.get("USERDOMAIN") or platform.node()
    return "%s\\%s" % (dom, getpass.getuser())


def setup():
    cfg = node_config()
    say("This computer: node '%s' of %s" % (cfg.get("name", "?"), cfg["site"]))
    os.makedirs(REMOTE, exist_ok=True)
    ensure_sshd(cfg)
    configure_sshd()
    key, pub = tunnel_key()
    say("[5/6] registering with the site")
    reply = site_call(cfg, "POST", "/api/v1/compute/remote/enroll/", {
        "pubkey": pub, "user": getpass.getuser(), "home": HERE, "python": sys.executable,
        "windows": "%s %s" % (platform.system(), platform.version())})
    install_admin_key(reply["admin_pubkey"])
    write_text(os.path.join(REMOTE, "known_hosts"), reply["known_hosts"] + "\n")
    ssh_exe = find_tool("ssh.exe")
    if not ssh_exe:
        raise SetupError("ssh.exe not found")
    write_text(os.path.join(REMOTE, "tunnel.cmd"), tunnel_cmd(ssh_exe, reply))
    write_text(os.path.join(REMOTE, "nm-control.cmd"), control_cmd())
    write_text(os.path.join(REMOTE, "home.txt"), HERE)
    write_text(os.path.join(REMOTE, "python.txt"), sys.executable)
    for name in ("known_hosts", "tunnel.cmd", "nm-control.cmd", "python.txt"):
        lock_down(os.path.join(REMOTE, name))
    lock_down(os.path.join(REMOTE, "home.txt"), extra_user=full_user(), modify=True)   # the agent (not elevated) keeps it current
    say("[6/6] scheduled tasks")
    run(["schtasks", "/end", "/tn", TUNNEL_TASK], quiet=True)
    create_task(TUNNEL_TASK, tunnel_task_xml(),
                ["/sc", "onstart", "/ru", "SYSTEM", "/rl", "HIGHEST", "/tr", 'cmd.exe /d /c "%s"' % os.path.join(REMOTE, "tunnel.cmd")])
    create_task(NODE_TASK, node_task_xml(full_user(), HERE),
                ["/sc", "once", "/st", "23:59", "/it", "/tr", '"%s"' % os.path.join(HERE, "START.bat")])
    run(["schtasks", "/run", "/tn", TUNNEL_TASK], check=True)
    say("")
    say("Checking that the site can log in through the tunnel ...")
    for i in range(12):
        time.sleep(5)
        try:
            st = site_call(cfg, "GET", "/api/v1/compute/remote/check/", timeout=90)
        except SetupError as e:
            st = {"message": str(e)}
        if st.get("login_ok"):
            say("OK - the site reaches this computer (%s)." % st.get("banner", ""))
            say("From now on the panel can stop / start / update this node, and the site's admin can work on it remotely.")
            say("Undo at any time:  Setup-Remote.bat remove")
            return 0
        if i in (3, 7):
            say("  still waiting: %s" % (st.get("message") or "")[:300])
    say("[!] The tunnel did not come up yet. Its log: %s" % os.path.join(REMOTE, "tunnel.log"))
    try:
        with open(os.path.join(REMOTE, "tunnel.log"), encoding="utf-8", errors="replace") as fh:
            for ln in fh.read().splitlines()[-8:]:
                say("    " + ln)
    except OSError:
        pass
    return 2


def remove():
    say("Removing NMarketing remote access ...")
    for t in (TUNNEL_TASK, NODE_TASK):
        run(["schtasks", "/end", "/tn", t], quiet=True)
        run(["schtasks", "/delete", "/tn", t, "/f"], quiet=True)
    run(["taskkill", "/F", "/FI", "IMAGENAME eq ssh.exe", "/FI", "USERNAME eq SYSTEM"], quiet=True)
    try:
        with open(ADMIN_KEYS, encoding="utf-8") as fh:
            text = fh.read()
        rest = [ln for ln in text.splitlines() if ln.strip() and KEY_MARK not in ln]
        with open(ADMIN_KEYS, "w", encoding="utf-8", newline="\n") as fh:
            fh.write("\n".join(rest) + ("\n" if rest else ""))
    except OSError:
        pass
    ps("Stop-Service sshd -Force -ErrorAction SilentlyContinue; Set-Service sshd -StartupType Manual -ErrorAction SilentlyContinue",
       quiet=True)
    shutil.rmtree(REMOTE, ignore_errors=True)
    say("Done: the tunnel, the tasks and the site's key are gone; the OpenSSH server is stopped (startup: manual).")
    return 0


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if not sys.platform.startswith("win"):
        say("This is for the Windows processing node.")
        return 1
    if not is_admin():
        say("[!] Run Setup-Remote.bat (it asks Windows for Administrator rights).")
        return 1
    try:
        return remove() if argv[:1] == ["remove"] else setup()
    except SetupError as e:
        say("")
        say("[!] %s" % e)
        return 1


if __name__ == "__main__":
    sys.exit(main())
