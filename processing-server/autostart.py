#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Start the node by itself when the computer is switched on (agent 2.11). Python 3.8+ standard library only.

On the first run the agent puts a shortcut to START.bat in the CURRENT USER's Startup folder
(%APPDATA%\\Microsoft\\Windows\\Start Menu\\Programs\\Startup): minimized, no administrator rights, nothing system-wide. When the owner
logs in, the node starts - and with it ComfyUI / Ollama / the managed services as always.

  * idempotent: if the shortcut is already there for THIS folder nothing happens; if the folder moved, the shortcut is rewritten;
  * switch it off: the panel (node setting «شروعِ خودکار») sends desired["autostart"] = false, or NM_AUTOSTART=0, or an empty file
    <data>/autostart.off - the shortcut is removed and not written again;
  * a PowerShell-made .lnk is used (WindowStyle 7 = minimized); if PowerShell cannot do it a small .cmd with `start /min` is written;
  * nothing happens on a system that is not Windows (tests pass a fake folder).
"""
import json
import os
import subprocess
import sys

VERSION = "1.0"
NAME = "NMarketing Node"


def is_windows():
    return sys.platform.startswith("win")


def startup_folder(env=None):
    env = env if env is not None else os.environ
    base = env.get("APPDATA") or ""
    if not base:
        return ""
    return os.path.join(base, "Microsoft", "Windows", "Start Menu", "Programs", "Startup")


def disabled(data, env=None):
    env = env if env is not None else os.environ
    if str(env.get("NM_AUTOSTART", "")).strip().lower() in ("0", "off", "false", "no"):
        return "NM_AUTOSTART=0"
    if os.path.isfile(os.path.join(data, "autostart.off")):
        return "autostart.off in the data folder"
    return ""


def _record_path(data):
    return os.path.join(data, "autostart.json")


def _read_record(data):
    try:
        with open(_record_path(data), encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def _ps_quote(s):
    return "'" + s.replace("'", "''") + "'"


def make_lnk(lnk, target, workdir, run=None):
    """Create the shortcut with PowerShell/WScript.Shell; True when the file exists afterwards."""
    ps = ("$s=(New-Object -ComObject WScript.Shell).CreateShortcut(%s);$s.TargetPath=%s;$s.WorkingDirectory=%s;"
          "$s.WindowStyle=7;$s.Description='NMarketing processing node (starts when you log in)';$s.Save()") % (
        _ps_quote(lnk), _ps_quote(target), _ps_quote(workdir))
    try:
        (run or subprocess.run)(["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", ps],
                                capture_output=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return False
    return os.path.isfile(lnk)


def make_cmd(path, target, workdir):
    try:
        with open(path, "w", encoding="utf-8", newline="\r\n") as fh:
            fh.write('@echo off\ncd /d "%s"\nstart "NMarketing node" /min "%s"\n' % (workdir, target))
        return True
    except OSError:
        return False


def status(here, data, env=None):
    folder = startup_folder(env)
    rec = _read_record(data)
    path = rec.get("path") or ""
    return {"supported": is_windows() or bool(folder) and os.path.isdir(folder), "folder": folder,
            "registered": bool(path and os.path.isfile(path) and rec.get("target") == os.path.join(here, "START.bat")),
            "path": path, "disabled": disabled(data, env)}


def ensure(here, data, enabled=True, env=None, run=None, plat_windows=None, force=False):
    """Make the Startup entry match `enabled`. `force` = the panel said «on» explicitly (it beats the autostart.off marker).
    Returns {"state": registered|removed|unchanged|disabled|unsupported|failed, ...}."""
    win = is_windows() if plat_windows is None else plat_windows
    folder = startup_folder(env)
    if not win or not folder:
        return {"state": "unsupported", "detail": "autostart is for Windows (no Startup folder)"}
    if enabled and force:
        try:
            os.remove(os.path.join(data, "autostart.off"))
        except OSError:
            pass
    reason = disabled(data, env)
    rec = _read_record(data)
    old = rec.get("path") or ""
    if not enabled or reason:
        removed = False
        for p in {old, os.path.join(folder, NAME + ".lnk"), os.path.join(folder, NAME + ".cmd")}:
            if p and os.path.isfile(p):
                try:
                    os.remove(p)
                    removed = True
                except OSError:
                    pass
        try:
            if os.path.isfile(_record_path(data)):
                os.remove(_record_path(data))
        except OSError:
            pass
        if not enabled and not reason:
            try:
                with open(os.path.join(data, "autostart.off"), "w", encoding="utf-8") as fh:
                    fh.write("switched off from the panel\n")
            except OSError:
                pass
        return {"state": "removed" if removed else "disabled", "detail": reason or "switched off in the panel"}
    target = os.path.join(here, "START.bat")
    if not os.path.isfile(target):
        return {"state": "failed", "detail": "START.bat was not found next to agent.py (%s)" % here}
    if old and os.path.isfile(old) and rec.get("target") == target:
        return {"state": "unchanged", "path": old}
    try:
        os.makedirs(folder, exist_ok=True)
        if os.path.isfile(os.path.join(data, "autostart.off")):
            os.remove(os.path.join(data, "autostart.off"))      # the panel switched it back on
    except OSError:
        pass
    lnk = os.path.join(folder, NAME + ".lnk")
    path = lnk if make_lnk(lnk, target, here, run) else ""
    if not path:
        cmd = os.path.join(folder, NAME + ".cmd")
        path = cmd if make_cmd(cmd, target, here) else ""
    if not path:
        return {"state": "failed", "detail": "could not write into %s" % folder}
    try:
        os.makedirs(data, exist_ok=True)
        with open(_record_path(data), "w", encoding="utf-8") as fh:
            json.dump({"path": path, "target": target, "kind": os.path.splitext(path)[1][1:]}, fh)
    except OSError:
        pass
    return {"state": "registered", "path": path}
