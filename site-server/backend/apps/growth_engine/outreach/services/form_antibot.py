"""Detection of everything that makes a form NOT eligible for automated submission.

DETECTION ONLY. Nothing here solves, bypasses or works around a CAPTCHA, a honeypot, a login, an OTP or a
challenge page: when any of them is seen the form is skipped and a person handles it.

Pure functions over BeautifulSoup elements and strings (no network, no Django models).
"""
from __future__ import annotations

import re
from urllib.parse import urlsplit

from bs4 import BeautifulSoup
from bs4.element import Tag

from apps.growth_engine.core import normalization as nz

# --------------------------------------------------------------------------- text helpers

_CAMEL = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")
_SEPARATORS = re.compile(r"[\[\]_\-.:/()*|]+")
_NOT_TEXT_PARENTS = {"script", "style", "noscript", "template", "select", "textarea", "option", "head", "title"}


def hay(*parts) -> str:
    """A normalised search string (lower case, ASCII digits, Persian letters, separators -> spaces)."""
    raw = " ".join(str(p) for p in parts if p)
    raw = _CAMEL.sub(" ", raw)
    raw = nz.to_ascii_digits(nz.normalize_text(raw)).lower()
    raw = _SEPARATORS.sub(" ", raw)
    return " " + re.sub(r"\s+", " ", raw).strip() + " "


def words(*items: str) -> re.Pattern:
    """One regex for a list of words: Latin words need word boundaries, short Persian words too,
    longer Persian words only a leading boundary (so «ایمیل» also matches «ایمیلتان»)."""
    alts = []
    for word in items:
        word = word.lower()
        if word.isascii():
            alts.append(rf"(?<![a-z0-9]){re.escape(word)}(?![a-z0-9])")
        elif len(word) <= 3:
            alts.append(rf"(?<![؀-ۿ]){re.escape(word)}(?![؀-ۿ])")
        else:
            alts.append(rf"(?<![؀-ۿ]){re.escape(word)}")
    return re.compile("|".join(alts))


def visible_text(node) -> str:
    """The text a person reads: no scripts, styles, option lists or textarea content."""
    parts = []
    for string in node.find_all(string=True):
        if string.parent is not None and string.parent.name in _NOT_TEXT_PARENTS:
            continue
        if any(p.name in _NOT_TEXT_PARENTS for p in string.parents if isinstance(p, Tag)):
            continue
        text = str(string).strip()
        if text and not text.startswith("<!--"):
            parts.append(text)
    return re.sub(r"\s+", " ", " ".join(parts)).strip()


def _attr(el: Tag, name: str) -> str:
    value = el.get(name, "")
    if isinstance(value, list):
        value = " ".join(value)
    return str(value or "")


# --------------------------------------------------------------------------- page level: challenge, login, SPA

_CHALLENGE_TITLES = words(
    "just a moment", "attention required", "checking your browser", "checking if the site connection is secure",
    "ddos protection", "در حال بررسی مرورگر", "در حال بررسی امنیت", "لطفا صبر کنید",
)
_CHALLENGE_MARKERS = (
    "__cf_chl", "_cf_chl_opt", "cf-browser-verification", "cf-challenge-running", 'id="challenge-form"', "id='challenge-form'",
    "chl_page", "orchestrate/chl", "sucuri.net/privacy", "enable javascript and cookies to continue", "ddos-guard.net",
)
_CLOUDFLAREISH = ("cloudflare", "cf-ray", "ray id", "ddos", "sucuri", "incapsula", "akamai")


def looks_like_challenge(html: str, status: int = 200) -> bool:
    """Cloudflare-style interstitial: there is no real page behind it, so there is nothing to submit to."""
    low = (html or "").lower()
    title = re.search(r"<title[^>]*>(.*?)</title>", low, re.S)
    if title and _CHALLENGE_TITLES.search(hay(title.group(1))):
        return True
    if any(marker in low for marker in _CHALLENGE_MARKERS):
        return True
    return status in (403, 503) and any(m in low for m in _CLOUDFLAREISH)


_LOGIN_PATH = re.compile(
    r"(^|/)(log-?in|sign-?in|wp-login\.php|login\.(php|aspx?)|authenticate|auth|ورود|account/login|accounts/login|user/login|users/sign_in)(/|$)"
)


def login_redirect(page_url: str, final_url: str) -> bool:
    """The fetch ended on a login URL although another page was asked for."""
    if not final_url or final_url == page_url:
        return False
    asked, landed = urlsplit(page_url), urlsplit(final_url)
    if asked.path == landed.path and asked.netloc == landed.netloc:
        return False
    return bool(_LOGIN_PATH.search(landed.path.lower()))


_LOGIN_TEXT = re.compile(
    "|".join(
        [
            r"(برای|جهت)[^.\n]{0,50}(ارسال|ثبت|ایجاد|باز کردن)[^.\n]{0,40}(تیکت|درخواست|پیام|نظر)[^.\n]{0,40}(وارد|ورود|لاگین)",
            r"(ابتدا|اول|لطفا|لطفاً)\s+[^.\n]{0,20}وارد[^.\n]{0,30}(شوید|شو)\b",
            r"باید\s+(ابتدا\s+)?(وارد|لاگین)\s+(حساب|سایت|شوید)",
            r"(please\s+)?(log ?in|sign ?in)\s+(first\s+)?to\s+(submit|send|create|open|post|contact|raise|add|reply)",
            r"you\s+(must|need to|have to)\s+be\s+(logged|signed)\s*in",
            r"login\s+required",
        ]
    ),
    re.I,
)


def login_text_present(text: str) -> bool:
    """A sentence like «برای ارسال تیکت وارد شوید» (a menu link «ورود / ثبت‌نام» alone does not count)."""
    return bool(_LOGIN_TEXT.search(nz.normalize_text(text)))


_APP_ROOT_IDS = {"root", "app", "__next", "__nuxt", "app-root", "q-app", "svelte"}
_NOSCRIPT_JS = words("enable javascript", "javascript is required", "javascript is disabled", "جاوا اسکریپت", "جاوااسکریپت", "javascript")


def looks_like_spa_shell(soup: BeautifulSoup) -> bool:
    """An empty app shell: no form, almost no text, a mount point and scripts. The page is built by JavaScript."""
    if soup.find("form"):
        return False
    if len(visible_text(soup)) >= 150:
        return False
    root = any(
        (soup.find(id=i) is not None) for i in _APP_ROOT_IDS
    ) or soup.find("app-root") is not None or soup.find(attrs={"ng-app": True}) is not None or soup.find(attrs={"data-reactroot": True}) is not None
    noscript_notice = any(_NOSCRIPT_JS.search(hay(n.get_text(" "))) for n in soup.find_all("noscript"))
    scripts = len(soup.find_all("script", src=True))
    return bool(root or noscript_notice) and (scripts >= 1 or noscript_notice)


# --------------------------------------------------------------------------- form level: JavaScript-only submission

_CANCEL_SUBMIT = re.compile(r"return\s+false|preventdefault|returnvalue\s*=\s*false", re.I)
_JS_FRAMEWORK_ATTRS = ("@submit", "v-on:submit", "x-on:submit", "ng-submit", "(ngsubmit)", "hx-post", "hx-put", "wire:submit", "onsubmit.prevent")


def form_is_js_only(form: Tag) -> bool:
    """The form cannot be sent as a plain HTTP form post: a ``javascript:`` action, or no real action plus
    a script that cancels the submit / a framework submit handler."""
    action = _attr(form, "action").strip().lower()
    if action.startswith("javascript:"):
        return True
    if action not in ("", "#"):
        return False
    onsubmit = _attr(form, "onsubmit")
    if onsubmit and _CANCEL_SUBMIT.search(onsubmit):
        return True
    attrs = {a.lower() for a in form.attrs}
    return any(marker in attrs or any(a.startswith(marker) for a in attrs) for marker in _JS_FRAMEWORK_ATTRS)


# --------------------------------------------------------------------------- CAPTCHA

_CAPTCHA_SCRIPT_KINDS = [
    ("recaptcha", re.compile(r"recaptcha|grecaptcha", re.I)),
    ("hcaptcha", re.compile(r"hcaptcha", re.I)),
    ("turnstile", re.compile(r"turnstile", re.I)),
    ("arcaptcha", re.compile(r"arcaptcha", re.I)),
    ("other", re.compile(r"captcha|geetest|mtcaptcha|procaptcha|altcha|keycaptcha|friendlycaptcha", re.I)),
]
_INLINE_CAPTCHA = re.compile(r"grecaptcha|hcaptcha\.|turnstile\.(render|execute)|arcaptcha|cf-turnstile|geetest|mtcaptcha", re.I)
_CAPTCHA_ATTR_KINDS = [
    ("recaptcha", re.compile(r"g-recaptcha|recaptcha", re.I)),
    ("hcaptcha", re.compile(r"h-captcha|hcaptcha", re.I)),
    ("turnstile", re.compile(r"cf-turnstile|turnstile", re.I)),
    ("arcaptcha", re.compile(r"arcaptcha", re.I)),
    ("other", re.compile(r"captcha", re.I)),
]
CAPTCHA_FIELD = words(
    "captcha", "recaptcha", "g recaptcha response", "h captcha response", "cf turnstile response", "arcaptcha", "securimage",
    "security code", "sec code", "seccode", "antispam", "anti spam", "human check", "are you human", "not a robot", "kaptcha",
    "کد امنیتی", "کپچا", "کد تصویر", "کد داخل تصویر", "کد مقابل", "تصویر امنیتی", "ربات نیستم", "من ربات", "کد درون تصویر",
)
_IMG_CAPTCHA = re.compile(r"captcha|securimage|kcaptcha|codeimage|verifyimage|verification[-_ ]?image|کد امنیتی|کپچا", re.I)
_MATH = re.compile(
    r"\d+\s*(\+|-|−|–|×|x|\*|÷|/|plus|minus|times)\s*\d+\s*(=|برابر|چند|چنده|\?|؟)"
    r"|حاصل\s*(جمع|ضرب|تفریق|عبارت)"
    r"|what is \d+\s*(\+|plus|minus|-|times|x)\s*\d+"
    r"|\d+\s*(\+|-|×)\s*\d+\s*=",
    re.I,
)


def captcha_kinds_on_page(soup: BeautifulSoup) -> set[str]:
    """CAPTCHA scripts / iframes anywhere on the page (an invisible v3 script protects the form without any widget)."""
    kinds: set[str] = set()
    for tag in soup.find_all(["script", "iframe"]):
        src = _attr(tag, "src")
        if src:
            for kind, pattern in _CAPTCHA_SCRIPT_KINDS:
                if pattern.search(src):
                    kinds.add(kind)
                    break
        elif tag.name == "script" and _INLINE_CAPTCHA.search(tag.get_text() or ""):
            text = tag.get_text()
            for kind, pattern in _CAPTCHA_SCRIPT_KINDS[:4]:
                if pattern.search(text):
                    kinds.add(kind)
                    break
            else:
                kinds.add("other")
    return kinds


def captcha_kinds_in_form(form: Tag) -> set[str]:
    """CAPTCHA widgets, image captchas, maths questions and captcha-named fields INSIDE the form."""
    kinds: set[str] = set()
    for tag in form.find_all(True):
        probe = " ".join([_attr(tag, "class"), _attr(tag, "id"), _attr(tag, "data-sitekey"), _attr(tag, "data-site-key"), _attr(tag, "data-captcha")])
        if tag.has_attr("data-sitekey") or tag.has_attr("data-site-key"):
            kinds.add("sitekey")
        for kind, pattern in _CAPTCHA_ATTR_KINDS:
            if pattern.search(probe):
                kinds.add(kind)
                break
        if tag.name == "img" and _IMG_CAPTCHA.search(" ".join([_attr(tag, "src"), _attr(tag, "alt"), _attr(tag, "id"), _attr(tag, "class"), _attr(tag, "title")])):
            kinds.add("image")
        if tag.name in ("iframe", "script"):
            src = _attr(tag, "src")
            for kind, pattern in _CAPTCHA_SCRIPT_KINDS:
                if src and pattern.search(src):
                    kinds.add(kind)
                    break
    text = hay(visible_text(form))
    if CAPTCHA_FIELD.search(text):
        kinds.add("field")
    if _MATH.search(nz.to_ascii_digits(visible_text(form))):
        kinds.add("math")
    return kinds


def is_captcha_field(label_hay: str) -> bool:
    return bool(CAPTCHA_FIELD.search(label_hay)) or bool(_MATH.search(label_hay))


# --------------------------------------------------------------------------- honeypot

#: names that only a trap has (visible or not); ``hp`` is the WPForms / Akismet style
_HONEYPOT_STRONG_NAME = re.compile(r"(^| )(honey ?pot|honey|gotcha|bot ?field|bot ?check|ak ?hp|hpot|spam ?trap|trap|no ?spam|hp)( |$)")
#: names that are traps only when the field is also hidden from people
_HONEYPOT_WEAK_NAME = re.compile(r"(^| )(url ?2|website ?url|homepage|fax|address ?2)( |$)")
_HONEYPOT_HINT = re.compile(
    r"leave (this )?(field )?(empty|blank)|do not fill|don't fill|if you are human|این فیلد را خالی|اگر انسان هستید|پر نکنید", re.I
)
_HIDDEN_STYLE = re.compile(
    r"display\s*:\s*none|visibility\s*:\s*hidden|opacity\s*:\s*0(\.0+)?\s*(;|!|$)|(left|top|right|bottom|inset-inline-start)\s*:\s*-\d{3,}"
    r"|text-indent\s*:\s*-\d{3,}|(height|width)\s*:\s*0(px)?\s*(;|!|$)|font-size\s*:\s*0(px)?\s*(;|!|$)|clip\s*:\s*rect\(0",
    re.I,
)
_HIDDEN_CLASSES = {"hidden", "d-none", "hide", "invisible", "honeypot", "hp", "hpot", "u-hidden", "is-hidden"}
_STYLE_RULE = re.compile(r"([^{}]+)\{([^{}]*)\}")


def style_hidden_selectors(soup: BeautifulSoup) -> tuple[set[str], set[str]]:
    """(classes, ids) that a ``<style>`` block hides - how class-based honeypots are usually done."""
    classes: set[str] = set()
    ids: set[str] = set()
    for style in soup.find_all("style"):
        for selectors, body in _STYLE_RULE.findall(style.get_text() or ""):
            if not _HIDDEN_STYLE.search(body):
                continue
            for sel in selectors.split(","):
                sel = sel.strip()
                for token in re.findall(r"\.([\w-]+)", sel):
                    classes.add(token)
                for token in re.findall(r"#([\w-]+)", sel):
                    ids.add(token)
    return classes, ids


def hidden_from_people(el: Tag, form: Tag, hidden_classes: set[str], hidden_ids: set[str]) -> bool:
    """The element (or a wrapper up to the form) is invisible to a person: inline style, ``hidden``,
    ``aria-hidden``, a hiding class or a hiding rule in a ``<style>`` block. ``sr-only`` is NOT hiding (screen readers read it)."""
    node: Tag | None = el
    while isinstance(node, Tag):
        if node.has_attr("hidden") or _attr(node, "aria-hidden").lower() == "true":
            return True
        if _HIDDEN_STYLE.search(_attr(node, "style")):
            return True
        classes = set(_attr(node, "class").split())
        if classes & (_HIDDEN_CLASSES | hidden_classes):
            return True
        if _attr(node, "id") in hidden_ids:
            return True
        if node is form:
            break
        node = node.parent
    return False


def is_honeypot(el: Tag, form: Tag, label_text: str, hidden_classes: set[str], hidden_ids: set[str]) -> bool:
    """A control that is not ``type=hidden`` yet cannot be seen by a person, or is named/labelled like a trap."""
    type_ = _attr(el, "type").lower() if el.name == "input" else el.name
    if type_ in ("hidden", "submit", "button", "image", "reset"):
        return False
    name_hay = hay(_attr(el, "name"), _attr(el, "id"))
    hidden = hidden_from_people(el, form, hidden_classes, hidden_ids)
    if _HONEYPOT_STRONG_NAME.search(name_hay):
        return True
    if _HONEYPOT_WEAK_NAME.search(name_hay) and hidden:
        return True
    if _HONEYPOT_HINT.search(label_text) or _HONEYPOT_HINT.search(_attr(el, "placeholder")):
        return True
    if hidden:
        return True
    if _attr(el, "tabindex") == "-1" and _attr(el, "autocomplete").lower() in ("off", "nope", "new-password") and not label_text.strip():
        return True
    return False


# --------------------------------------------------------------------------- OTP

OTP_STRONG = words(
    "otp", "one time", "one time password", "sms code", "verification code", "verify code", "mobile verification", "phone verification",
    "کد یکبار مصرف", "رمز یکبار مصرف", "کد یک بار مصرف", "کد پیامکی", "کد فعال سازی", "کد فعالسازی",
)
OTP_LABEL = words("کد تایید", "کد تأیید", "کد تاییدیه", "کد احراز", "کد ورود", "verification", "confirm code", "confirmation code")
_SEND_CODE = words("ارسال کد", "دریافت کد", "send code", "get code", "send otp", "request code", "resend", "ارسال مجدد", "کد را بفرست")


def is_otp_field(label_hay: str, name_hay: str, has_send_button: bool) -> bool:
    """An input for a one-time code: named like one, or labelled «کد تأیید» next to a «ارسال کد» button."""
    if OTP_STRONG.search(name_hay):
        return True
    return bool(has_send_button and (OTP_LABEL.search(label_hay) or OTP_STRONG.search(label_hay)))


def form_has_send_code_button(form: Tag) -> bool:
    """A «ارسال کد» / «send code» button or link in the form (or its immediate surroundings)."""
    for tag in form.find_all(["button", "a", "input", "span"]):
        if tag.name == "input" and _attr(tag, "type").lower() not in ("button", "submit"):
            continue
        text = hay(tag.get_text(" ") if tag.name != "input" else _attr(tag, "value"), _attr(tag, "id"), _attr(tag, "class"), _attr(tag, "name"))
        if _SEND_CODE.search(text):
            return True
    return False


# --------------------------------------------------------------------------- login inside a form


def form_has_password(form: Tag) -> bool:
    return form.find("input", attrs={"type": re.compile(r"^password$", re.I)}) is not None
