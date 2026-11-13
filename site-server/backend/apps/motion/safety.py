"""اسکنرِ امنیتیِ کدِ کاربر (حالتِ «کد»).

کدِ کاربر در مرورگرِ بی‌سر (Chromium) اجرا می‌شود و فقط به همان صفحهٔ بسته‌بندی‌شده دسترسی دارد. چند لایه:

  ۱) این اسکنر (پیش از هر پیش‌نمایش/رندر): فقط importِ مجاز، بدونِ شبکه/ذخیره‌سازی/eval/DOMِ والد، اندازهٔ محدود.
  ۲) در صفحه (motion/remotion/src/user.tsx): `require` فقط ماژول‌های مجاز را می‌دهد؛ fetch/XHR/WebSocket/Worker بسته می‌شوند.
  ۳) در رندر: Content-Security-Policy (connect/img/font فقط خودِ صفحه و data:) + `--host-resolver-rules` (هیچ نشانیِ بیرونی) +
     فرایندِ جدا با سقفِ زمان و حافظه (apps.motion.runner).

اسکنر عمداً سخت‌گیر است؛ وقتی کلمه‌ای رد می‌شود پیامِ فارسیِ دقیق می‌گوید کدام.
"""
from __future__ import annotations

import re

MAX_CODE_BYTES = 200_000
MAX_LINES = 4000

ALLOWED_IMPORTS = ("react", "react/jsx-runtime", "remotion", "@remotion/shapes", "@remotion/paths", "@remotion/noise", "nm-motion")

#: شناسه‌هایی که در کدِ کاربر (بیرون از رشته/توضیح) رد می‌شوند ⇒ دلیلِ فارسی
BANNED_IDENTIFIERS = {
    "fetch": "دسترسی به شبکه (fetch)", "XMLHttpRequest": "دسترسی به شبکه", "WebSocket": "دسترسی به شبکه", "EventSource": "دسترسی به شبکه",
    "Worker": "Worker", "SharedWorker": "Worker", "ServiceWorker": "Worker", "importScripts": "importScripts",
    "sendBeacon": "ارسال به بیرون", "localStorage": "ذخیره‌سازی", "sessionStorage": "ذخیره‌سازی", "indexedDB": "ذخیره‌سازی",
    "caches": "ذخیره‌سازی", "eval": "eval", "require": "require", "process": "process", "globalThis": "globalThis",
    "window": "window", "parent": "parent", "top": "top", "opener": "opener", "frames": "frames", "self": "self",
    "location": "location", "history": "history", "navigator": "navigator", "Reflect": "Reflect", "Proxy": "Proxy",
    "constructor": "constructor", "__proto__": "__proto__", "importmeta": "import.meta", "XMLSerializer": "XMLSerializer",
    "RTCPeerConnection": "دسترسی به شبکه", "WebAssembly": "WebAssembly", "Atomics": "Atomics", "SharedArrayBuffer": "SharedArrayBuffer",
}
BANNED_DOCUMENT = ("cookie", "domain", "write", "writeln", "location", "referrer", "open")
BANNED_TAGS = ("script", "iframe", "object", "embed", "link", "meta", "base", "form", "frame", "frameset", "applet")


class UnsafeCode(Exception):
    """کد رد شد؛ str(exc) جملهٔ فارسی برای نمایش به کاربر است."""

    def __init__(self, message: str, line: int | None = None):
        super().__init__(message)
        self.line = line


def _scan(src: str, i: int, in_expr: bool) -> tuple[str, list[str], int]:
    out: list[str] = []
    strings: list[str] = []
    depth = 0
    n = len(src)
    while i < n:
        c = src[i]
        nxt = src[i + 1] if i + 1 < n else ""
        if c == "/" and nxt == "/":
            j = src.find("\n", i)
            i = n if j < 0 else j
            continue
        if c == "/" and nxt == "*":
            j = src.find("*/", i + 2)
            out.append("\n" * src[i:(n if j < 0 else j)].count("\n"))
            i = n if j < 0 else j + 2
            continue
        if c in "'\"":
            j = i + 1
            buf = []
            while j < n and src[j] != c:
                if src[j] == "\\":
                    buf.append(src[j:j + 2])
                    j += 2
                    continue
                if src[j] == "\n":
                    break
                buf.append(src[j])
                j += 1
            strings.append("".join(buf))
            out.append('""')
            i = j + 1
            continue
        if c == "`":
            i += 1
            buf = []
            while i < n and src[i] != "`":
                if src[i] == "\\":
                    buf.append(src[i:i + 2])
                    i += 2
                    continue
                if src[i] == "$" and src[i + 1:i + 2] == "{":
                    strings.append("".join(buf))
                    buf = []
                    sub_out, sub_strings, i = _scan(src, i + 2, True)
                    out.append("(" + sub_out + ")")
                    strings.extend(sub_strings)
                    continue
                buf.append(src[i])
                i += 1
            strings.append("".join(buf))
            out.append('""')
            i += 1
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            if in_expr and depth == 0:
                return "".join(out), strings, i + 1
            depth -= 1
        out.append(c)
        i += 1
    return "".join(out), strings, i


def strip_code(src: str) -> tuple[str, list[str]]:
    """(کد بدونِ رشته‌ها و توضیح‌ها، محتوای رشته‌ها). عبارت‌های `${…}` ِ داخلِ قالب‌ها کد حساب می‌شوند."""
    out, strings, _ = _scan(src, 0, False)
    return out, strings


_IMPORT_RE = re.compile(r"""(?:^|[\s;])import\s+(?:[^'"()]*?\s+from\s+)?['"]([^'"]+)['"]""", re.M)
_EXPORT_FROM_RE = re.compile(r"""export\s+(?:\*|\{[^}]*\})\s+from\s+['"]([^'"]+)['"]""")
_URL_RE = re.compile(r"""(?i)(?:https?:|wss?:|ftp:|file:)?//[a-z0-9._-]+\.[a-z]{2,}|(?:https?|wss?|ftp|file):""")


def _line_of(src: str, needle_pos: int) -> int:
    return src.count("\n", 0, needle_pos) + 1


def scan(code: str) -> None:
    """کد را می‌سنجد؛ مشکل ⇒ UnsafeCode با پیامِ فارسی."""
    if not isinstance(code, str) or not code.strip():
        raise UnsafeCode("کد خالی است.")
    if len(code.encode("utf-8")) > MAX_CODE_BYTES:
        raise UnsafeCode(f"کد از {MAX_CODE_BYTES // 1000} کیلوبایت بزرگ‌تر است.")
    if code.count("\n") > MAX_LINES:
        raise UnsafeCode(f"کد بیش از {MAX_LINES} خط است.")
    if "\x00" in code:
        raise UnsafeCode("کد کاراکترِ نامعتبر دارد.")
    bare, strings = strip_code(code)

    # importها (روی کدِ اصلی، چون نامِ ماژول داخلِ رشته است)
    for m in list(_IMPORT_RE.finditer(code)) + list(_EXPORT_FROM_RE.finditer(code)):
        name = m.group(1)
        if name not in ALLOWED_IMPORTS:
            raise UnsafeCode(f"import از «{name}» مجاز نیست. فقط: {'، '.join(ALLOWED_IMPORTS)}", _line_of(code, m.start()))
    if re.search(r"\bimport\s*\(", bare):
        raise UnsafeCode("importِ پویا (import(...)) مجاز نیست.")
    if re.search(r"\bimport\s*\.\s*meta\b", bare):
        raise UnsafeCode("import.meta مجاز نیست.")

    for ident, why in BANNED_IDENTIFIERS.items():
        m = re.search(rf"(?<![\w$])(?:\.\s*)?{re.escape(ident)}(?![\w$])", bare)
        if m:
            # «top»/«self»/«parent»/«history» به‌عنوانِ نامِ ویژگی در شیءِ کاربر (مثلاً style.top) مجاز است
            pre = bare[max(0, m.start() - 1):m.start() + 1]
            is_member = bare[m.start()] == "." or bare[max(0, m.start() - 1)] == "."
            if ident in ("top", "self", "parent", "history", "location", "frames", "opener", "navigator", "window") and is_member:
                continue
            if ident == "top" and re.match(r"\s*:", bare[m.end():m.end() + 3]):   # { top: 10 }
                continue
            if ident in ("process", "location", "history", "parent", "top", "self", "frames", "opener", "navigator", "window", "caches"):
                # فقط وقتی به‌عنوانِ متغیرِ سراسری خوانده شود
                after = bare[m.end():m.end() + 2].strip()
                if after.startswith(":") or (pre.strip() in ("{", ",") and after.startswith(",")):
                    continue
            raise UnsafeCode(f"استفاده از «{ident}» مجاز نیست ({why}).", _line_of(bare, m.start()))
    m = re.search(r"\bnew\s+Function\b|\bFunction\s*\(", bare)
    if m:
        raise UnsafeCode("ساختنِ تابع از متن (Function) مجاز نیست.", _line_of(bare, m.start()))
    m = re.search(r"\bdocument\s*\.\s*(" + "|".join(BANNED_DOCUMENT) + r")\b", bare)
    if m:
        raise UnsafeCode(f"document.{m.group(1)} مجاز نیست.", _line_of(bare, m.start()))
    m = re.search(r"<\s*(" + "|".join(BANNED_TAGS) + r")[\s/>]", bare, re.I)
    if m:
        raise UnsafeCode(f"تگِ «{m.group(1)}» مجاز نیست.", _line_of(bare, m.start()))
    m = re.search(r"\bdangerouslySetInnerHTML\b|\.\s*innerHTML\b|\.\s*outerHTML\b|\binsertAdjacentHTML\b", bare)
    if m:
        raise UnsafeCode("درج HTML خام مجاز نیست.", _line_of(bare, m.start()))

    # نشانیِ شبکه داخلِ رشته‌ها (تصویر/فونت/ویدیو از اینترنت)
    for s in strings:
        if s.lstrip().lower().startswith("data:"):
            continue
        if _URL_RE.search(s):
            raise UnsafeCode("نشانیِ اینترنتی در کد مجاز نیست؛ تصویرها را از «دارایی‌ها» بگیرید یا داخلِ کد (data:) بگذارید.")
        if re.search(r"(?i)\burl\s*\(\s*['\"]?\s*(?!data:|#)", s):
            raise UnsafeCode("url(...) به فایل/نشانیِ بیرونی مجاز نیست (فقط data:).")
        if "@import" in s:
            raise UnsafeCode("@import در CSS مجاز نیست.")
