# -*- coding: utf-8 -*-
"""دسترسیِ راه‌دور به سرورهای پردازش (۱۴۰۵/۰۸/۱۹).

خواستهٔ مالک: «سرورِ پردازش مثلِ VPS باشد»: هم دسترسیِ کامل (فایل‌ها، دستور)، هم یک دستور برای
توقف ⇐ Update ⇐ راه‌اندازیِ دوباره، بی آن‌که کسی پشتِ آن کامپیوتر باشد.

ساختار (گره IP ندارد؛ پس اتصال از خودِ گره شروع می‌شود):
  · روی گره، Setup-Remote.bat (یک بار، با اجازهٔ Administrator) سرویسِ OpenSSH را فقط روی 127.0.0.1 ِ همان کامپیوتر
    روشن می‌کند و یک کارِ زمان‌بندی‌شدهٔ SYSTEM یک «تونلِ معکوس» به همین سرور باز نگه می‌دارد:
        ssh -N -R 127.0.0.1:<پورت>:127.0.0.1:22 nmtunnel@<این سرور>
  · کاربرِ nmtunnel روی این سرور شل ندارد و کلیدِ هر گره فقط اجازهٔ همان یک پورت را روی 127.0.0.1 دارد
    (restrict,port-forwarding,permitlisten) — یعنی از اینترنت هیچ دری باز نمی‌شود.
  · ورود به گره فقط با کلیدِ /root/.ssh/nm_node_admin ِ همین سرور است (رمز خاموش است).
  · پنل فقط دستورهای ثابت را می‌فرستد (ACTIONS ⇐ nm_control.py روی گره)؛ دستورِ دلخواه فقط از خطِ فرمانِ سرور
    (`nm-node <name> run '...'`، کاربرِ root).

چیزی از این‌ها در مخزن نیست: کلیدها روی سرور و روی گره ساخته می‌شوند (مخزن عمومی است).
"""
from __future__ import annotations

import json
import os
import re
import socket
import subprocess
import tempfile
from pathlib import Path

from django.conf import settings
from django.utils import timezone

from . import services as SV
from .models import ComputeNode, ComputeNodeLog

TUNNEL_USER = getattr(settings, "NM_REMOTE_TUNNEL_USER", "nmtunnel")
AUTH_KEYS = Path(getattr(settings, "NM_REMOTE_AUTHORIZED_KEYS", "/var/lib/nmtunnel/.ssh/authorized_keys"))
ADMIN_KEY = Path(getattr(settings, "NM_REMOTE_ADMIN_KEY", "/root/.ssh/nm_node_admin"))
KNOWN_HOSTS = Path(getattr(settings, "NM_REMOTE_KNOWN_HOSTS", "/root/.ssh/nm_nodes_known_hosts"))
HOST_KEY_PUB = Path(getattr(settings, "NM_REMOTE_HOST_KEY", "/etc/ssh/ssh_host_ed25519_key.pub"))
PUBLIC_HOST = getattr(settings, "NM_REMOTE_PUBLIC_HOST", "87.107.160.17")
SSH_PORT = int(getattr(settings, "NM_REMOTE_SSH_PORT", 22))
PORT_BASE = int(getattr(settings, "NM_REMOTE_PORT_BASE", 22200))

#: دستورهای ثابتِ پنل ⇒ nm_control.py روی گره
ACTIONS = ("status", "stop", "start", "restart", "update", "build", "logs")
ACTION_LABEL = {
    "status": "وضعیت", "stop": "توقف", "start": "روشن کردن", "restart": "راه‌اندازیِ دوباره",
    "update": "به‌روزرسانی و راه‌اندازیِ دوباره", "build": "ساختِ ویرایشگرها", "logs": "لاگ‌ها",
}
#: سقفِ زمانِ هر دستور (ثانیه)
ACTION_TIMEOUT = {"status": 120, "logs": 120, "stop": 180, "start": 240, "restart": 420, "update": 1800, "build": 3600}
#: «در حالِ اجرا» ای که بیش از این مانده (کارگر مرد) دیگر جلوی دستورِ تازه را نمی‌گیرد
STALE_RUNNING_S = 2 * 3600
#: روی گره: لانچرِ ثابت که Setup-Remote.bat می‌نویسد (پوشهٔ کد و پایتون را از home.txt / python.txt می‌خواند)
CONTROL = r"& 'C:\ProgramData\NMarketing\remote\nm-control.cmd'"

PUBKEY_RE = re.compile(r"^(ssh-ed25519) ([A-Za-z0-9+/]{60,100}={0,2})(?: [^\r\n]{0,120})?$")
#: نامِ کاربرِ ویندوز (بدونِ دامنه): بی فاصله و نویسه‌هایی که در خطِ فرمان معنی دارند
USER_RE = re.compile(r"^[^\s\"'@/\\:;|&<>`$*?%]{1,40}$")


class RemoteError(Exception):
    pass


def safe_name(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]", "_", name or "")[:60] or "node"


def remote_dir() -> Path:
    d = SV.data_root() / "remote"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _info_path(node: ComputeNode) -> Path:
    return remote_dir() / ("%s.json" % safe_name(node.name))


def _last_path(node: ComputeNode) -> Path:
    return remote_dir() / ("%s-last.json" % safe_name(node.name))


def _read(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _write(path: Path, obj: dict, mode: int = 0o600) -> None:
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".tmp-")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, ensure_ascii=False, indent=1)
    os.chmod(tmp, mode)
    os.replace(tmp, path)


def load(node: ComputeNode) -> dict:
    return _read(_info_path(node))


def listen_port(node: ComputeNode) -> int:
    return PORT_BASE + int(node.pk)


# ───────────────────────────── ثبتِ گره (از Setup-Remote.bat)

def _key_line(node: ComputeNode, algo: str, body: str) -> str:
    return 'restrict,port-forwarding,permitlisten="127.0.0.1:%d" %s %s nm-node:%s' % (
        listen_port(node), algo, body, safe_name(node.name))


def _write_authorized_key(node: ComputeNode, line: str) -> None:
    marker = " nm-node:%s" % safe_name(node.name)
    try:
        old = AUTH_KEYS.read_text(encoding="utf-8").splitlines()
    except OSError:
        old = []
    keep = [ln for ln in old if ln.strip() and not ln.rstrip().endswith(marker)]
    AUTH_KEYS.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(AUTH_KEYS.parent), prefix=".tmp-")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write("\n".join(keep + [line]) + "\n")
    os.chmod(tmp, 0o600)
    try:
        import pwd

        pw = pwd.getpwnam(TUNNEL_USER)
        os.chown(tmp, pw.pw_uid, pw.pw_gid)
    except (KeyError, ImportError, PermissionError):
        pass                              # آزمون‌ها / سروری که کاربرِ تونل ندارد
    os.replace(tmp, AUTH_KEYS)


def _forget_host_key(port: int) -> None:
    """گرهٔ دوباره‌ثبت‌شده ممکن است کلیدِ میزبانِ تازه داشته باشد (sshd دوباره نصب شد)."""
    if KNOWN_HOSTS.exists():
        subprocess.run(["ssh-keygen", "-R", "[127.0.0.1]:%d" % port, "-f", str(KNOWN_HOSTS)],
                       capture_output=True, timeout=20)


def _known_hosts_line() -> str:
    try:
        parts = HOST_KEY_PUB.read_text(encoding="utf-8").split()
    except OSError as exc:
        raise RemoteError("کلیدِ میزبانِ SSH ِ این سرور خوانده نشد (%s)" % exc) from exc
    host = PUBLIC_HOST if SSH_PORT == 22 else "[%s]:%d" % (PUBLIC_HOST, SSH_PORT)
    return "%s %s %s" % (host, parts[0], parts[1])


def _admin_pubkey() -> str:
    try:
        return Path(str(ADMIN_KEY) + ".pub").read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise RemoteError("کلیدِ مدیرِ گره‌ها روی سرور نیست (deploy/nm/remote-access-setup.sh اجرا نشده): %s" % exc) from exc


def enroll(node: ComputeNode, pubkey: str, user: str, home: str = "", python: str = "", windows: str = "") -> dict:
    pubkey = (pubkey or "").strip()
    m = PUBKEY_RE.match(pubkey)
    if not m:
        raise RemoteError("کلیدِ تونل باید ssh-ed25519 باشد")
    user = (user or "").strip()
    if not USER_RE.match(user):
        raise RemoteError("نامِ کاربرِ ویندوز درست نیست")
    admin = _admin_pubkey()
    known = _known_hosts_line()
    port = listen_port(node)
    _write_authorized_key(node, _key_line(node, m.group(1), m.group(2)))
    _forget_host_key(port)
    info = {
        "node": node.name, "node_id": node.pk, "listen_port": port, "user": user,
        "home": str(home or "")[:300], "python": str(python or "")[:300], "windows": str(windows or "")[:120],
        "pubkey": "%s %s" % (m.group(1), m.group(2)), "enrolled_at": timezone.now().isoformat(),
    }
    _write(_info_path(node), info)
    return {
        "host": PUBLIC_HOST, "ssh_port": SSH_PORT, "user": TUNNEL_USER, "listen_port": port, "local_port": 22,
        "known_hosts": known, "admin_pubkey": admin,
    }


# ───────────────────────────── وضعیت و دستورها

def tunnel_banner(port: int, timeout: float = 3.0) -> str:
    """سرِ تونل روی همین سرور: اگر وصل باشد sshd ِ ویندوز همان لحظه «SSH-2.0-OpenSSH_for_Windows…» می‌گوید."""
    try:
        with socket.create_connection(("127.0.0.1", int(port)), timeout=timeout) as s:
            s.settimeout(timeout)
            data = s.recv(80)
    except OSError:
        return ""
    return data.decode("ascii", "replace").strip() if data.startswith(b"SSH-") else ""


def last(node: ComputeNode) -> dict:
    row = _read(_last_path(node))
    if row.get("running") and row.get("started_at"):
        from django.utils.dateparse import parse_datetime

        started = parse_datetime(row["started_at"])
        if started and (timezone.now() - started).total_seconds() > STALE_RUNNING_S:
            row["running"] = False
            row["stale"] = True
    return row


def state(node: ComputeNode) -> dict:
    info = load(node)
    if not info:
        return {"enrolled": False, "actions": [{"key": k, "label": ACTION_LABEL[k]} for k in ACTIONS]}
    banner = tunnel_banner(info["listen_port"])
    return {
        "enrolled": True, "tunnel_up": bool(banner), "banner": banner, "listen_port": info["listen_port"],
        "user": info.get("user", ""), "home": info.get("home", ""), "windows": info.get("windows", ""),
        "enrolled_at": info.get("enrolled_at"), "last": last(node),
        "actions": [{"key": k, "label": ACTION_LABEL[k]} for k in ACTIONS],
    }


def ssh_command(info: dict, remote_command: str) -> list[str]:
    return ["ssh", "-p", str(int(info["listen_port"])), "-i", str(ADMIN_KEY),
            "-o", "BatchMode=yes", "-o", "ConnectTimeout=15", "-o", "StrictHostKeyChecking=accept-new",
            "-o", "UserKnownHostsFile=%s" % KNOWN_HOSTS, "-o", "ServerAliveInterval=30", "-o", "ServerAliveCountMax=4",
            "-l", info["user"], "127.0.0.1", remote_command]


def _decode(raw: bytes) -> str:
    return (raw or b"").decode("utf-8", "replace").replace("\r\n", "\n")


def run(info: dict, remote_command: str, timeout: int) -> tuple[int, str]:
    try:
        p = subprocess.run(ssh_command(info, remote_command), capture_output=True, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        return -1, _decode(exc.stdout or b"") + _decode(exc.stderr or b"") + "\n[timed out after %d s]" % timeout
    return p.returncode, _decode(p.stdout) + _decode(p.stderr)


def mark_started(node: ComputeNode, action: str, by: str = "") -> dict:
    if action not in ACTIONS:
        raise RemoteError("دستورِ ناشناخته: %s" % action)
    info = load(node)
    if not info:
        raise RemoteError("این سرور هنوز دسترسیِ راه‌دور ندارد: یک بار Setup-Remote.bat را روی خودش بزنید.")
    cur = last(node)
    if cur.get("running"):
        raise RemoteError("دستورِ «%s» هنوز در حالِ اجراست." % ACTION_LABEL.get(cur.get("action"), cur.get("action")))
    if not tunnel_banner(info["listen_port"]):
        raise RemoteError("تونل وصل نیست: آن کامپیوتر خاموش است یا اینترنتش قطع است.")
    row = {"action": action, "label": ACTION_LABEL[action], "running": True, "by": by,
           "started_at": timezone.now().isoformat(), "output": "", "exit_code": None}
    _write(_last_path(node), row)
    return row


def control(node: ComputeNode, action: str, by: str = "") -> dict:
    """اجرای یک دستورِ ثابت روی گره (از Celery). نتیجه در <data>/remote/<name>-last.json و لاگِ همان سرور."""
    info = load(node)
    row = _read(_last_path(node)) or {"action": action, "label": ACTION_LABEL.get(action, action), "by": by,
                                       "started_at": timezone.now().isoformat()}
    if not info:
        code, out = -1, "not enrolled"
    else:
        code, out = run(info, "%s %s" % (CONTROL, action), ACTION_TIMEOUT.get(action, 600))
    row.update({"running": False, "exit_code": code, "ok": code == 0, "output": out[-30000:],
                "finished_at": timezone.now().isoformat()})
    _write(_last_path(node), row)
    try:
        ComputeNodeLog.objects.create(
            node=node, level="INFO" if code == 0 else "ERROR", logged_at=timezone.now(),
            message=("remote %s%s -> %s\n%s" % (action, (" (%s)" % by) if by else "",
                                               "ok" if code == 0 else "exit %s" % code, out[-2500:]))[:4000])
    except Exception:  # noqa: BLE001 — لاگ نباید نتیجه را از بین ببرد
        pass
    return row


def check(node: ComputeNode) -> dict:
    """برای Setup-Remote.bat: «سایت از راهِ تونل به من می‌رسد؟» — هم تونل، هم ورود با کلیدِ مدیر."""
    info = load(node)
    if not info:
        return {"tunnel_up": False, "login_ok": False, "message": "not enrolled"}
    banner = tunnel_banner(info["listen_port"])
    if not banner:
        return {"tunnel_up": False, "login_ok": False, "message": "the tunnel is not up yet"}
    code, out = run(info, "Write-Output nm-remote-ok", 40)
    ok = code == 0 and "nm-remote-ok" in out
    return {"tunnel_up": True, "login_ok": ok, "banner": banner, "message": "" if ok else out[-600:]}
