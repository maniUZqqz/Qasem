"""Shared by every step: settings from the environment, the two exceptions, small text helpers."""
import os
from pathlib import Path

BASE = os.environ.get("IGS_BASE", "https://www.instagram.com").rstrip("/")
DATA = Path(os.environ.get("IGS_DATA") or Path(__file__).parent / "data")
HEADLESS = os.environ.get("IGS_HEADLESS") == "1"
# NMarketing node (2026-11): the browser Playwright drives. IGS_BROWSER_EXE = a Chromium/Chrome/Edge program to use as it is;
# IGS_BROWSER_CHANNEL = a browser that is installed on the computer ("msedge" is on every Windows 11) instead of Playwright's own
# Chromium download (which is blocked from Iran). Both empty = Playwright's own Chromium, exactly as before.
BROWSER_EXE = os.environ.get("IGS_BROWSER_EXE", "").strip()
BROWSER_CHANNEL = os.environ.get("IGS_BROWSER_CHANNEL", "").strip()


def browser_opts():
    """The launch options that choose the browser (empty = Playwright's default Chromium)."""
    if BROWSER_EXE:
        return {"executable_path": BROWSER_EXE}
    if BROWSER_CHANNEL:
        return {"channel": BROWSER_CHANNEL}
    return {}
# Instagram holds the account until a person passes its check ("confirm you're human", a code): every page goes there.
CHALLENGE_MSG = "اینستاگرام این حساب را تا «تأیید انسان بودن» نگه داشته؛ در «تنظیمات ← حساب و نشست» «بررسی نشست» را بزن و در پنجره خودت تأیید کن"


class Busy(Exception):
    pass


class Fail(Exception):
    """An attempt that ended without what it came for; kind is what the UI explains."""

    def __init__(self, kind, msg="", ig_message=None, detail=None):
        super().__init__(msg)
        self.kind, self.msg, self.ig_message, self.detail = kind, msg, ig_message, detail


def first_line(e):
    text = str(e).strip()
    return text.splitlines()[0][:300] if text else e.__class__.__name__


LRI, PDI = chr(0x2066), chr(0x2069)
FA_DIGITS = str.maketrans("0123456789", "".join(chr(0x06F0 + i) for i in range(10)))


def ltr(text):
    """Isolate English text inside a Persian line so its punctuation stays where it belongs."""
    return LRI + str(text) + PDI


def fa(n):
    """Digits as Persian numerals, for sentences the server writes."""
    return str(n).translate(FA_DIGITS)


def age_text(seconds):
    """A rough Persian 'how long ago', for log lines."""
    s = int(seconds)
    if s < 60:
        return "چند ثانیه"
    if s < 3600:
        return fa(s // 60) + " دقیقه"
    if s < 86400:
        return fa(s // 3600) + " ساعت"
    return fa(s // 86400) + " روز"
