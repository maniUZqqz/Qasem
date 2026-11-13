"""The Instagram accounts that belong to him, one of them active at a time. Each account has its own browser folder and its
own session note, so switching is like switching users on a phone: nothing is typed again. The account he already uses keeps
its old folder (data/profile, data/session.json); new ones live in data/accounts/<username>/.
Switching only changes WHICH account the one engine uses. The limits, the pause after "wait" and the queue stay shared by the
whole app (ig_budget), so a second account never adds capacity, and nothing runs on two accounts at once.
No password is stored here: a new account is added by logging in on the login page, like the first one."""
import json
import shutil
import time

import ig_profile as pr
from ig_common import DATA

FILE = DATA / "accounts.json"
LEGACY_DIR, LEGACY_META = DATA / "profile", DATA / "session.json"


def now():
    return int(time.time())


def _read():
    data = pr.read_json(FILE, {}, backup=True)
    if not isinstance(data, dict):
        data = {}
    data.setdefault("accounts", [])
    data.setdefault("active", None)
    if not data["accounts"]:                      # the account used before this feature existed keeps its folder
        try:
            who = json.loads(LEGACY_META.read_text("utf-8")).get("username")
        except (OSError, ValueError, AttributeError):
            who = None
        if who:
            data["accounts"].append({"username": who.lower(), "user_id": None, "added_at": now(), "last_used": now(), "legacy": True})
            data["active"] = who.lower()
    return data


def _write(data):
    DATA.mkdir(parents=True, exist_ok=True)
    pr.write_atomic(FILE, json.dumps(data, ensure_ascii=False, indent=1).encode("utf-8"), backup=True)


def _find(data, username):
    return next((a for a in data["accounts"] if a["username"] == (username or "").lower()), None)


def _folder(acc):
    return DATA / "accounts" / acc.get("folder", acc["username"])     # fixed when added: a login can change the name, never the folder


def active():
    """The active account's entry, or None when there is none yet (nobody has logged in)."""
    data = _read()
    return _find(data, data["active"])


def _entry(name):
    """The entry of the named account, or the active one when no name is given."""
    if name is None:
        return active()
    return _find(_read(), name)


def profile_dir(name=None):
    """The browser folder of an account: the active one by default (the old shared folder until any account exists)."""
    acc = _entry(name)
    if acc is None and name is not None:
        raise KeyError(name)                 # never fall back to another account's folder
    return LEGACY_DIR if acc is None or acc.get("legacy") else _folder(acc) / "profile"


def meta_file(name=None):
    acc = _entry(name)
    if acc is None and name is not None:
        raise KeyError(name)
    return LEGACY_META if acc is None or acc.get("legacy") else _folder(acc) / "session.json"


def listing():
    data = _read()
    out = []
    for acc in data["accounts"]:
        meta = LEGACY_META if acc.get("legacy") else _folder(acc) / "session.json"
        try:
            logged = bool(json.loads(meta.read_text("utf-8")).get("username"))
        except (OSError, ValueError, AttributeError):
            logged = False
        out.append({"username": acc["username"], "user_id": acc.get("user_id"), "added_at": acc["added_at"], "last_used": acc.get("last_used"),
                    "active": acc["username"] == data["active"], "logged_in": logged})
    return {"active": data["active"], "items": out}


def add(username):
    """A new account, not logged in yet. The ACTIVE account stays what it was (and keeps running its queue): the new one is
    logged in on the login page while the first goes on, and becomes active only when he switches to it. With no account at
    all yet, the first one is active at once."""
    data = _read()
    name = username.lower()
    if _find(data, name):
        return None
    data["accounts"].append({"username": name, "folder": name, "user_id": None, "added_at": now(), "last_used": None})
    if not data["active"] or _find(data, data["active"]) is None:
        data["active"] = name
    _write(data)
    return name


def switch(username):
    data = _read()
    acc = _find(data, username)
    if acc is None:
        return None
    data["active"], acc["last_used"] = acc["username"], now()
    _write(data)
    return acc["username"]


def set_identity(username, user_id, account=None):
    """A login succeeded for `account` (the active one by default): the entry is that Instagram account (the typed name may
    have been an email or a phone). The active account is never changed here, except by the very first login."""
    data = _read()
    acc = _find(data, account or data["active"])
    name = (username or "").lower()
    if acc is None:                                      # the very first login
        acc = {"username": name, "user_id": user_id, "added_at": now(), "last_used": now(), "legacy": True}
        data["accounts"].append(acc)
    elif acc["username"] != name and not _find(data, name):
        acc["username"] = name                           # the typed name was an email, a phone or a different spelling
    acc["user_id"], acc["last_used"] = user_id or acc.get("user_id"), now()
    if not data["active"] or account is None:
        data["active"] = acc["username"]
    elif data["active"] == (account or "").lower() and acc["username"] != account.lower():
        data["active"] = acc["username"]                  # the active entry was renamed: the pointer follows it
    _write(data)
    return acc["username"]


def remove(username):
    """Forget an account that is not the active one: its entry and its browser folder go (his button, after a confirm)."""
    data = _read()
    acc = _find(data, username)
    if acc is None or acc["username"] == data["active"]:
        return False
    if not acc.get("legacy"):
        shutil.rmtree(_folder(acc), ignore_errors=True)
    else:
        shutil.rmtree(LEGACY_DIR, ignore_errors=True)
        LEGACY_META.unlink(missing_ok=True)
    data["accounts"] = [a for a in data["accounts"] if a is not acc]
    _write(data)
    return True
