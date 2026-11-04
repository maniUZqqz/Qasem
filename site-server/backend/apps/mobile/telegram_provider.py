"""Telegram caller lookup through the OFFICIAL MTProto API (Telethon), with the owner's OWN Telegram account.

The owner links his account himself from the NM panel (phone -> code -> 2FA password if set). The login session and the
api_id/api_hash live in `<NM_DATA_DIR>/mobile/telegram/` (mode 600), never in a repository and never in logs.
A number is resolved with `contacts.resolvePhone`, which respects the other person's own privacy settings: if they do not
allow being found by number Telegram answers «not found», exactly as it would to any user.

Telethon is imported lazily; tests inject a fake backend through `BACKEND_FACTORY`, so no real Telegram call is ever made
by the test-suite.
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import time
from pathlib import Path

from . import calls as calls_service
from . import phone as phonelib

logger = logging.getLogger(__name__)

AVATAR_MAX = 300 * 1024


class ProviderError(Exception):
    def __init__(self, message, code="telegram_error", refund=False):
        super().__init__(message)
        self.code, self.refund = code, refund


def _dir() -> Path:
    d = calls_service.data_dir() / "telegram"
    d.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(d, 0o700)
    except OSError:
        pass
    return d


def _read(name, default=None):
    p = _dir() / name
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _write(name, data):
    p = _dir() / name
    p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    try:
        os.chmod(p, 0o600)
    except OSError:
        pass


def _remove(*names):
    for n in names:
        try:
            (_dir() / n).unlink()
        except OSError:
            pass


def session_path() -> str:
    return str(_dir() / "owner")


def installed() -> bool:
    try:
        import telethon  # noqa: F401
        return True
    except Exception:  # noqa: BLE001
        return BACKEND_FACTORY is not None


# ------------------------------------------------------------------ real backend

class TelethonBackend:
    """Thin async wrapper; every call connects, does one thing and disconnects (the session file keeps the login)."""

    def __init__(self, api_id: int, api_hash: str, session: str):
        self.api_id, self.api_hash, self.session = api_id, api_hash, session

    def _client(self):
        from telethon import TelegramClient

        return TelegramClient(self.session, self.api_id, self.api_hash)

    async def send_code(self, phone: str) -> str:
        c = self._client()
        await c.connect()
        try:
            sent = await c.send_code_request(phone)
            return sent.phone_code_hash
        finally:
            await c.disconnect()

    async def sign_in(self, phone: str, code: str, code_hash: str):
        from telethon import errors

        c = self._client()
        await c.connect()
        try:
            try:
                await c.sign_in(phone=phone, code=code, phone_code_hash=code_hash)
            except errors.SessionPasswordNeededError:
                return "password_needed"
            return await self._me(c)
        finally:
            await c.disconnect()

    async def sign_in_password(self, password: str):
        c = self._client()
        await c.connect()
        try:
            await c.sign_in(password=password)
            return await self._me(c)
        finally:
            await c.disconnect()

    async def _me(self, c):
        me = await c.get_me()
        name = " ".join(x for x in [getattr(me, "first_name", ""), getattr(me, "last_name", "")] if x)
        return {"id": me.id, "name": name, "username": getattr(me, "username", "") or ""}

    async def is_authorized(self) -> bool:
        c = self._client()
        await c.connect()
        try:
            return bool(await c.is_user_authorized())
        finally:
            await c.disconnect()

    async def logout(self):
        c = self._client()
        await c.connect()
        try:
            if await c.is_user_authorized():
                await c.log_out()
        finally:
            await c.disconnect()

    async def resolve_phone(self, digits: str):
        from telethon import errors, functions

        c = self._client()
        await c.connect()
        try:
            if not await c.is_user_authorized():
                raise ProviderError("نشستِ تلگرام منقضی شده؛ دوباره وصلش کنید.", "platform_not_ready", refund=True)
            try:
                res = await c(functions.contacts.ResolvePhoneRequest(phone=digits))
            except errors.PhoneNotOccupiedError:
                return None
            except errors.FloodWaitError as exc:
                raise _flood(exc.seconds) from exc
            users = list(getattr(res, "users", []) or [])
            if not users:
                return None
            user = users[0]
            about = ""
            try:
                full = await c(functions.users.GetFullUserRequest(user))
                about = getattr(full.full_user, "about", "") or ""
            except errors.FloodWaitError as exc:
                raise _flood(exc.seconds) from exc
            except Exception:  # noqa: BLE001 - bio is optional
                about = ""
            photo = None
            try:
                photo = await c.download_profile_photo(user, file=bytes)
            except Exception:  # noqa: BLE001 - photo is optional
                photo = None
            return {"id": user.id, "first_name": getattr(user, "first_name", "") or "", "last_name": getattr(user, "last_name", "") or "",
                    "username": getattr(user, "username", "") or "", "about": about, "photo": photo,
                    "premium": bool(getattr(user, "premium", False)), "verified": bool(getattr(user, "verified", False)),
                    "bot": bool(getattr(user, "bot", False))}
        finally:
            await c.disconnect()


def _flood(seconds) -> ProviderError:
    until = time.time() + int(seconds)
    _write("cooldown.json", {"until": until})
    return ProviderError(f"تلگرام برای حفاظت از حساب {int(seconds)} ثانیه جستجو را متوقف کرده؛ بعداً دوباره.", "flood_wait", refund=True)


#: tests set this to a callable returning a fake backend
BACKEND_FACTORY = None


def _backend() -> TelethonBackend:
    if BACKEND_FACTORY is not None:
        return BACKEND_FACTORY()
    api = _read("api.json")
    if not api:
        raise ProviderError("api_id و api_hash تلگرام هنوز وارد نشده است.", "platform_not_ready")
    try:
        import telethon  # noqa: F401
    except Exception as exc:  # noqa: BLE001
        raise ProviderError("کتابخانهٔ Telethon روی سرور نصب نیست.", "platform_not_ready") from exc
    return TelethonBackend(int(api["api_id"]), str(api["api_hash"]), session_path())


def _run(coro):
    return asyncio.run(coro)


# ------------------------------------------------------------------ linking (panel)

def status() -> dict:
    account = _read("account.json")
    pending = _read("pending.json")
    api = _read("api.json")
    return {
        "installed": installed(), "api_configured": bool(api), "api_id": (api or {}).get("api_id"),
        "linked": bool(account), "account": account,
        "pending": (pending or {}).get("stage"), "pending_phone": _mask((pending or {}).get("phone", "")),
    }


def _mask(p: str) -> str:
    return (p[:4] + "****" + p[-3:]) if len(p) > 8 else ""


def is_ready() -> bool:
    return bool(_read("account.json"))


def save_api(api_id, api_hash):
    try:
        api_id = int(str(api_id).strip())
    except (TypeError, ValueError) as exc:
        raise ProviderError("api_id باید عدد باشد.", "bad_input") from exc
    api_hash = str(api_hash or "").strip()
    if len(api_hash) < 16 or not all(ch in "0123456789abcdefABCDEF" for ch in api_hash):
        raise ProviderError("api_hash باید یک رشتهٔ ۳۲ نویسه‌ای (۰-۹ و a-f) باشد.", "bad_input")
    _write("api.json", {"api_id": api_id, "api_hash": api_hash})


def start(phone_input: str):
    norm = phonelib.normalize(phone_input)
    if not phonelib.is_valid(norm):
        raise ProviderError("شماره درست نیست؛ با کد کشور بنویسید، مثل 989121234567.", "bad_input")
    phone = "+" + norm
    be = _backend()
    try:
        code_hash = _run(be.send_code(phone))
    except ProviderError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise ProviderError(_nice(exc), "telegram_error") from exc
    _write("pending.json", {"phone": phone, "phone_code_hash": code_hash, "stage": "code", "at": time.time()})


def confirm_code(code: str):
    pending = _read("pending.json")
    if not pending:
        raise ProviderError("اول شماره را بفرستید تا کد بیاید.", "bad_input")
    be = _backend()
    try:
        result = _run(be.sign_in(pending["phone"], str(code).strip(), pending["phone_code_hash"]))
    except Exception as exc:  # noqa: BLE001
        raise ProviderError(_nice(exc), "telegram_error") from exc
    if result == "password_needed":
        pending["stage"] = "password"
        _write("pending.json", pending)
        return {"stage": "password"}
    _finish(result)
    return {"stage": "linked", "account": result}


def confirm_password(password: str):
    pending = _read("pending.json")
    if not pending or pending.get("stage") != "password":
        raise ProviderError("رمزِ دومرحله‌ای الان لازم نیست.", "bad_input")
    be = _backend()
    try:
        result = _run(be.sign_in_password(str(password)))
    except Exception as exc:  # noqa: BLE001
        raise ProviderError(_nice(exc), "telegram_error") from exc
    _finish(result)
    return {"stage": "linked", "account": result}


def _finish(account: dict):
    _write("account.json", {"id": account.get("id"), "name": account.get("name", ""), "username": account.get("username", ""),
                            "linked_at": time.strftime("%Y-%m-%dT%H:%M:%S%z")})
    _remove("pending.json", "cooldown.json")


def unlink():
    try:
        _run(_backend().logout())
    except Exception:  # noqa: BLE001 - even if Telegram refuses, forget the local session
        logger.info("telegram logout failed (ignored)")
    _remove("account.json", "pending.json", "cooldown.json", "owner.session", "owner.session-journal")


def _nice(exc: Exception) -> str:
    name = type(exc).__name__
    table = {
        "PhoneCodeInvalidError": "کد اشتباه است.", "PhoneCodeExpiredError": "کد منقضی شده؛ دوباره شماره را بفرستید.",
        "PasswordHashInvalidError": "رمزِ دومرحله‌ای اشتباه است.", "PhoneNumberInvalidError": "شماره درست نیست.",
        "ApiIdInvalidError": "api_id / api_hash درست نیست.", "FloodWaitError": "تلگرام موقتاً درخواست را نپذیرفت؛ کمی بعد.",
        "PhoneNumberBannedError": "این شماره در تلگرام مسدود است.",
    }
    return table.get(name, f"خطای تلگرام ({name}).")


# ------------------------------------------------------------------ lookup

def lookup(number_norm: str) -> dict:
    """number_norm like 989121234567 -> result dict for lookups._record (never raises for «not found»)."""
    cool = _read("cooldown.json")
    if cool and cool.get("until", 0) > time.time():
        left = int(cool["until"] - time.time())
        raise ProviderError(f"تلگرام تا {left} ثانیهٔ دیگر جستجو را نمی‌پذیرد.", "flood_wait", refund=True)
    if not is_ready():
        raise ProviderError("حسابِ تلگرام وصل نیست.", "platform_not_ready", refund=True)
    be = _backend()
    try:
        info = _run(be.resolve_phone(number_norm))
    except ProviderError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise ProviderError(_nice(exc), "telegram_error", refund=True) from exc
    if info is None:
        return {"status": "not_found", "on_platform": False,
                "extra": {"note": "یا حساب ندارد یا اجازهٔ پیدا شدن با شماره را نداده"}}
    name = " ".join(x for x in [info.get("first_name"), info.get("last_name")] if x)
    photo = info.get("photo")
    sources = {"display_name": "تلگرام: نامِ نمایشی", "on_platform": "تلگرام: وجودِ حساب"}
    if info.get("username"):
        sources["username"] = "تلگرام: نام‌کاربری"
    if info.get("about"):
        sources["bio"] = "تلگرام: درباره"
    avatar = None
    if photo and len(photo) <= AVATAR_MAX:
        avatar = base64.b64encode(photo).decode("ascii")
        sources["avatar"] = "تلگرام: عکس پروفایل"
    return {"status": "found", "on_platform": True, "display_name": name, "username": info.get("username") or "",
            "bio": info.get("about") or "", "deep_link_id": str(info.get("id") or ""), "avatar_b64": avatar,
            "extra": {"premium": info.get("premium", False), "verified": info.get("verified", False), "bot": info.get("bot", False)},
            "field_sources": sources}
