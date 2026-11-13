"""Who may use the site (his order 2026-11-05): a login with an AbaOne account — LoginApi, the same four steps as the AbaOne
site's own login page (/chk → /getCo → /getYear → /token), then /GetUserID names the account — and only the people he added.
Two roles: 'full' (everything) and 'json' (see the saved pages, download and upload their JSON). The admins come from
IGS_ADMINS (his AbaOne user id) and keep the list in «کاربران».

Our own session is a random key in an HttpOnly cookie; only its hash is kept (data/sessions.json). The AbaOne password and
token are never stored or logged, and nothing about an account is said before its password is verified."""
import hashlib
import json
import os
import re
import secrets
import time
from datetime import date

import httpx

from ig_common import DATA
from ig_profile import read_json, write_atomic

LOGIN_API = os.environ.get("IGS_LOGIN_API", "").rstrip("/")
ADMINS = {x.strip() for x in os.environ.get("IGS_ADMINS", "").split(",") if x.strip()}
ENABLED = os.environ.get("IGS_AUTH", "1") != "0"     # 0: no login at all (the mock-site tests)
COOKIE = "igs_session"
TTL = 24 * 3600                   # a login lasts a day
ROLES = ("full", "json")
TRIES, TRY_WINDOW = 8, 15 * 60    # wrong passwords from one address before it waits
NAME_RE = re.compile(r"^[^\s/\\<>\"'`]{1,60}$")
USERS, SESSIONS = DATA / "users.json", DATA / "sessions.json"

_cache = {}     # path -> (mtime, data): the site asks on every request
_fails = {}     # address -> [times of wrong passwords]


def _read(path):
    try:
        stamp = path.stat().st_mtime
    except OSError:
        return {}
    hit = _cache.get(path)
    if hit and hit[0] == stamp:
        return hit[1]
    data = read_json(path, {}, backup=path == USERS)   # a damaged users.json: its .bak, not "nobody may come in"
    if not isinstance(data, dict):
        data = {}
    _cache[path] = (stamp, data)
    return data


def _write(path, data):
    write_atomic(path, json.dumps(data, ensure_ascii=False, indent=1).encode("utf-8"), backup=path == USERS)
    _cache.pop(path, None)


def clean_name(raw):
    name = str(raw or "").strip().lower()
    return name if NAME_RE.match(name) else None


# ---- the people he added ----
def users():
    return dict(_read(USERS).get("users") or {})


def add_user(username, role, by):
    name = clean_name(username)
    if not name or role not in ROLES:
        return None
    data = {"users": users()}
    old = data["users"].get(name) or {}
    data["users"][name] = {**old, "username": name, "role": role, "added_by": old.get("added_by", by),
                           "added_at": old.get("added_at", int(time.time()))}
    _write(USERS, data)
    return data["users"][name]


def remove_user(username):
    name, data = clean_name(username), {"users": users()}
    if not name or data["users"].pop(name, None) is None:
        return False
    _write(USERS, data)
    sessions = {k: v for k, v in _read(SESSIONS).items() if v.get("username") != name}
    _write(SESSIONS, sessions)                    # his open logins end at once
    return True


def role_of(username, uid):
    """'full', 'json' or None for an AbaOne account that just proved its password."""
    if str(uid) in ADMINS:
        return "full"
    rec = users().get(clean_name(username) or "")
    if not rec or (rec.get("uid") and str(rec["uid"]) != str(uid)):
        return None
    return rec.get("role") if rec.get("role") in ROLES else None


# ---- AbaOne's own login (LoginApi) ----
def _jalali_year(today=None):
    d = today or date.today()
    return d.year - 621 if (d.month, d.day) >= (3, 21) else d.year - 622


async def abaone_login(username, password, transport=None):
    """(uid, None) when the AbaOne account and its password are right, else (None, 'wrong' | 'down'). The session cookie of
    /chk has to reach /token (LoginApi refuses it otherwise): one client keeps it. The token is only used to learn the id."""
    jar = {}     # LoginApi's cookies, carried by hand (like otp-api): a Secure cookie over plain http is never sent by a jar

    async def call(c, method, path, **kw):
        r = await c.request(method, path, headers={**kw.pop("headers", {}), **({"Cookie": "; ".join(f"{k}={v}" for k, v in jar.items())} if jar else {})}, **kw)
        jar.update({k: v for k, v in r.cookies.items()})
        c.cookies.clear()
        return r

    try:
        async with httpx.AsyncClient(base_url=LOGIN_API, timeout=20, verify=False, transport=transport) as c:
            chk = await call(c, "POST", "/chk", json={"userName": username, "passWord": password, "yearID": 0, "coID": 0})
            if chk.status_code != 200:
                return None, "wrong" if chk.status_code < 500 else "down"
            co, year = 1, 0
            try:
                rows = (await call(c, "POST", "/getCo", json={"userName": username})).json()
                if isinstance(rows, list) and rows:
                    co = rows[0].get("coID") or rows[0].get("CoID") or 1
            except (httpx.HTTPError, ValueError, AttributeError):
                pass
            try:
                rows = (await call(c, "POST", "/getYear", json={"userName": username, "coID": co})).json()
                if isinstance(rows, list) and rows:
                    now = next((y for y in rows if str(y.get("yearN0")) == str(_jalali_year())), rows[-1])
                    year = now.get("yearID") or 0
            except (httpx.HTTPError, ValueError, AttributeError):
                pass
            tk = await call(c, "POST", "/token", json={"userName": username, "passWord": password, "yearID": year, "coID": co})
            token = tk.text.strip().strip('"')
            if tk.status_code != 200 or token.count(".") != 2:
                return None, "wrong" if tk.status_code < 500 else "down"
            who = await call(c, "GET", "/GetUserID", headers={"Authorization": f"Bearer {token}"})
            uid = str(who.text).strip().strip('"')
            if who.status_code != 200 or not uid.isdigit() or int(uid) <= 0:
                return None, "down"
            return uid, None
    except httpx.HTTPError:
        return None, "down"


def waiting(address, now=None):
    """Seconds this address must wait after too many wrong passwords (0: it may try)."""
    now = now or time.time()
    times = [t for t in _fails.get(address, []) if t > now - TRY_WINDOW]
    _fails[address] = times
    return int(times[0] + TRY_WINDOW - now) + 1 if len(times) >= TRIES else 0


def failed(address, now=None):
    _fails.setdefault(address, []).append(now or time.time())


# ---- our sessions ----
def _hash(key):
    return hashlib.sha256(str(key).encode()).hexdigest()


def start_session(username, uid, now=None):
    """A new login: its key (for the cookie). Old logins that ran out are dropped on the way."""
    now = int(now or time.time())
    key, name = secrets.token_urlsafe(32), clean_name(username)
    data = {k: v for k, v in _read(SESSIONS).items() if v.get("until", 0) > now}
    data[_hash(key)] = {"username": name, "uid": str(uid), "at": now, "until": now + TTL}
    _write(SESSIONS, data)
    if str(uid) not in ADMINS and name in users():           # the id is kept on his first login (a name never changes owner)
        all_users = {"users": users()}
        all_users["users"][name] = {**all_users["users"][name], "uid": str(uid), "last_login": now}
        _write(USERS, all_users)
    return key


def session(key, now=None):
    """{'username', 'uid', 'role', 'admin', 'until'} of a live login, else None. The role is read every time: a person he
    removed, or whose role he changed, has it at once."""
    if not key or len(key) > 200:
        return None
    rec = _read(SESSIONS).get(_hash(key))
    if not rec or rec.get("until", 0) <= (now or time.time()):
        return None
    role = role_of(rec.get("username"), rec.get("uid"))
    if not role:
        return None
    return {"username": rec["username"], "uid": rec["uid"], "role": role, "admin": rec["uid"] in ADMINS, "until": rec["until"]}


def end_session(key):
    data = dict(_read(SESSIONS))
    if data.pop(_hash(key or ""), None) is not None:
        _write(SESSIONS, data)


# ---- what the 'json' role may do: see the saved pages, download and upload their JSON; nothing that touches Instagram ----
JSON_ROLE = [("GET", re.compile(p)) for p in (
    r"^/api/auth/me$", r"^/api/exchange$", r"^/api/export/[^/]+$", r"^/api/profiles$", r"^/api/dossier/[^/]+$",
    r"^/api/people/[^/]+/(followers|following)$", r"^/api/avatar/[^/]+$", r"^/api/media/[^/]+/[^/]+$", r"^/api/img$",
    r"^/api/process$", r"^/api/process/[^/]+/(followers|following)(/export\.xlsx)?$")] + [
    ("POST", re.compile(p)) for p in (r"^/api/import$", r"^/api/auth/logout$")]


def json_may(method, path):
    return any(m == method and rx.match(path) for m, rx in JSON_ROLE)
