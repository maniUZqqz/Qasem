"""Turning a chosen HTML form into the list of fields that would be submitted, and filling them truthfully.

Every value comes from one of three places: the sender identity (Growth Settings), the template (subject /
message), or the page itself (hidden inputs, pre-selected options, pre-filled values). A required field that
none of them can fill is reported as a problem and the form is skipped: nothing is ever invented.

Pure functions (no network, no Django models). The data classes live in ``form_analysis``; this module
returns plain dicts and tuples so there is no import cycle.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from bs4 import BeautifulSoup
from bs4.element import Tag

from . import form_antibot as ab
from .form_reasons import text_for

# --------------------------------------------------------------------------- vocabulary (Persian + English)

_USERNAME = ab.words("username", "user name", "user id", "userid", "نام کاربری", "login", "نام کاربر")
_ID_LIKE = ab.words(
    "کد ملی", "کدملی", "شماره ملی", "national code", "national id", "ssn", "شماره سفارش", "order number", "order id", "order no",
    "کد رهگیری", "شماره پیگیری", "کد پیگیری", "tracking", "شماره فاکتور", "invoice", "کد پستی", "postal code", "zip", "شماره شناسنامه",
    "شماره حساب", "iban", "شبا", "شماره کارت", "card number",
)
_FAX = ab.words("fax", "فکس")
_EMAIL = ab.words("email", "e mail", "mail", "ایمیل", "پست الکترونیک", "پست الکترونیکی", "نشانی ایمیل", "آدرس ایمیل")
_PHONE = ab.words(
    "phone", "mobile", "tel", "telephone", "cell", "cellphone", "whatsapp", "تلفن", "موبایل", "همراه", "شماره تماس", "شماره موبایل",
    "شماره همراه", "شماره تلفن", "تلفن همراه", "شماره واتساپ",
)
_WEBSITE = ab.words(
    "website", "web site", "url", "homepage", "site", "وب سایت", "وبسایت", "وب‌سایت", "سایت", "آدرس سایت", "لینک سایت", "آدرس وب",
)
_COMPANY = ab.words(
    "company", "organization", "organisation", "org", "business", "firm", "شرکت", "سازمان", "کسب و کار", "کسب‌و‌کار", "کسبوکار",
    "نام فروشگاه", "فروشگاه", "برند", "brand",
)
_SUBJECT = ab.words("subject", "topic", "title", "موضوع", "عنوان")
_FULLNAME = ab.words("نام و نام خانوادگی", "نام ونام خانوادگی", "نام و نام‌خانوادگی", "full name", "fullname", "your name", "نام کامل", "name and surname", "نام شما", "نام و فامیل")
_FIRST = ab.words("first name", "firstname", "fname", "given name", "نام کوچک")
_LAST = ab.words("last name", "lastname", "lname", "surname", "family name", "family", "نام خانوادگی", "فامیل", "فامیلی")
_NAME = ab.words("name", "نام", "اسم")
_MESSAGE = ab.words(
    "message", "msg", "comment", "comments", "enquiry", "inquiry", "details", "description", "body", "content", "text", "request",
    "how can we help", "پیام", "متن", "توضیحات", "شرح", "درخواست", "نظر", "سوال", "پرسش", "مشکل",
)
_REQUIRED_HINT = re.compile(r"\*|\(?\s*(الزامی|ضروری)\s*\)?|\(\s*required\s*\)|\brequired\b", re.I)
_TEXT_LIKE_SKIP = {"submit", "button", "reset", "image", "file", "checkbox", "radio", "hidden", "password"}


@dataclass
class Identity:
    name: str = ""
    company: str = ""
    phone: str = ""
    email: str = ""
    website: str = ""


@dataclass
class Built:
    fields: list[dict] = field(default_factory=list)
    problems: list[tuple[str, str]] = field(default_factory=list)  # (reason code, Persian text)
    honeypots: list[str] = field(default_factory=list)
    captcha_fields: list[str] = field(default_factory=list)
    otp_fields: list[str] = field(default_factory=list)
    has_file_input: bool = False
    has_message_field: bool = False
    has_password: bool = False

    def problem(self, code: str, label: str = "") -> None:
        item = (code, text_for(code, label))
        if item not in self.problems:
            self.problems.append(item)


# --------------------------------------------------------------------------- labels


def _clean_label(text: str) -> str:
    text = re.sub(r"\s+", " ", (text or "").replace("*", " ")).strip(" :：؛-–—")
    return text[:80]


def _label_text(node: Tag, exclude: Tag | None = None) -> str:
    parts = []
    for string in node.find_all(string=True):
        parent_names = {p.name for p in string.parents if isinstance(p, Tag)}
        if parent_names & {"script", "style", "select", "textarea", "option", "noscript"}:
            continue
        if exclude is not None and exclude in string.parents:
            continue
        parts.append(str(string))
    return re.sub(r"\s+", " ", " ".join(parts)).strip()


def label_for(el: Tag, labels_by_for: dict[str, str]) -> str:
    """The visible label of a control (raw, may still contain «*»), by the most reliable source first."""
    ident = el.get("id")
    if ident and ident in labels_by_for:
        return labels_by_for[ident]
    wrapper = el.find_parent("label")
    if wrapper is not None:
        text = _label_text(wrapper, exclude=el)
        if text:
            return text
    aria = ab._attr(el, "aria-label")
    if aria:
        return aria
    labelled_by = ab._attr(el, "aria-labelledby")
    if labelled_by:
        root = el.find_parent(["form", "body"]) or el
        texts = []
        for token in labelled_by.split():
            target = root.find(id=token)
            if target is not None:
                texts.append(_label_text(target))
        if any(texts):
            return " ".join(t for t in texts if t)
    title = ab._attr(el, "title")
    if title:
        return title
    # table / div layouts: the text just before the control inside its wrapper
    previous = el.find_previous_sibling(["label", "span", "div", "p", "b", "strong", "th", "td"])
    if previous is not None and el.parent is not None and previous.parent is el.parent:
        text = _label_text(previous)
        if text and len(text) <= 80:
            return text
    parent = el.parent
    if isinstance(parent, Tag) and parent.name in ("td", "div", "p", "li", "span"):
        own = " ".join(str(s) for s in parent.find_all(string=True, recursive=False)).strip()
        if own and len(own) <= 80:
            return re.sub(r"\s+", " ", own)
        row = el.find_parent("tr")
        if row is not None:
            first = row.find(["th", "td"])
            if first is not None and not first.find(["input", "select", "textarea"]):
                text = _label_text(first)
                if text and len(text) <= 80:
                    return text
    return ab._attr(el, "placeholder")


def _group_label(el: Tag) -> str:
    fieldset = el.find_parent("fieldset")
    if fieldset is not None:
        legend = fieldset.find("legend")
        if legend is not None:
            return _label_text(legend)
    return ""


# --------------------------------------------------------------------------- required / classification


def is_required(el: Tag, label_raw: str) -> bool:
    if el.has_attr("required") or ab._attr(el, "aria-required").lower() == "true" or ab._attr(el, "data-required").lower() in ("true", "1", "required"):
        return True
    if re.search(r"(^|\s)(required|wpcf7-validates-as-required|is-required|wpforms-field-required)(\s|$)", ab._attr(el, "class")):
        return True
    return bool(_REQUIRED_HINT.search(label_raw or "") or _REQUIRED_HINT.search(ab._attr(el, "placeholder")))


def classify(type_: str, tag: str, text_hay: str) -> str:
    """email | phone | website | company | subject | name | first_name | last_name | message | other"""
    if _USERNAME.search(text_hay) or _ID_LIKE.search(text_hay) or _FAX.search(text_hay):
        return "other"
    if type_ == "email" or _EMAIL.search(text_hay):
        return "email"
    if type_ == "tel" or _PHONE.search(text_hay):
        return "phone"
    if type_ == "url" or _WEBSITE.search(text_hay):
        return "website"
    if _COMPANY.search(text_hay):
        return "company"
    if _SUBJECT.search(text_hay):
        return "subject"
    if _FULLNAME.search(text_hay):
        return "name"
    if _FIRST.search(text_hay):
        return "first_name"
    if _LAST.search(text_hay):
        return "last_name"
    if _NAME.search(text_hay):
        return "name"
    if tag == "textarea" or _MESSAGE.search(text_hay):
        return "message"
    return "other"


def _split_name(full: str) -> tuple[str, str]:
    parts = full.split()
    if len(parts) <= 1:
        return full, ""
    return parts[0], " ".join(parts[1:])


# --------------------------------------------------------------------------- the builder


def build_fields(
    form: Tag,
    soup: BeautifulSoup,
    identity: Identity,
    subject: str,
    message: str,
    hidden_classes: set[str],
    hidden_ids: set[str],
) -> Built:
    out = Built()
    labels_by_for = {}
    for lab in soup.find_all("label", attrs={"for": True}):
        labels_by_for.setdefault(ab._attr(lab, "for"), _label_text(lab))
    has_send_button = ab.form_has_send_code_button(form)
    controls = [c for c in form.find_all(["input", "select", "textarea", "button"]) if not c.has_attr("disabled")]

    def type_of(el: Tag) -> str:
        if el.name == "input":
            return (ab._attr(el, "type") or "text").lower()
        if el.name == "button":
            return (ab._attr(el, "type") or "submit").lower()
        return el.name

    def is_trap(el: Tag, label_raw: str) -> bool:
        return ab.is_honeypot(el, form, label_raw, hidden_classes, hidden_ids)

    # the message goes into exactly ONE field: the first message-like visible textarea, else the first visible
    # textarea, else a text input that is clearly the message
    message_el: Tag | None = None
    textareas = [c for c in controls if c.name == "textarea" and not is_trap(c, label_for(c, labels_by_for))]
    for ta in textareas:
        if _MESSAGE.search(ab.hay(ab._attr(ta, "name"), ab._attr(ta, "id"), ab._attr(ta, "placeholder"), label_for(ta, labels_by_for))):
            message_el = ta
            break
    if message_el is None and textareas:
        message_el = textareas[0]
    if message_el is None:
        for c in controls:
            if c.name == "input" and type_of(c) in ("text", "search") and not is_trap(c, label_for(c, labels_by_for)):
                h = ab.hay(ab._attr(c, "name"), ab._attr(c, "id"), label_for(c, labels_by_for))
                if re.search(r"(^| )(message|msg|پیام|متن پیام|comment)( |$)", h):
                    message_el = c
                    break
    out.has_message_field = message_el is not None

    submit_done = False
    radio_seen: set[str] = set()

    def add(name, type_, label, source, value, required=False, hidden=False):
        out.fields.append(
            {"name": name, "type": type_, "label": _clean_label(label) or name, "source": source, "value": value, "required": required, "hidden": hidden}
        )

    for el in controls:
        type_ = type_of(el)
        name = ab._attr(el, "name")
        label_raw = label_for(el, labels_by_for)
        label = _clean_label(label_raw) or _clean_label(ab._attr(el, "placeholder")) or name
        required = is_required(el, label_raw)
        text_hay = ab.hay(name, ab._attr(el, "id"), ab._attr(el, "placeholder"), ab._attr(el, "aria-label"), label_raw, ab._attr(el, "autocomplete"))

        if type_ == "password":
            out.has_password = True
            if name:
                add(name, "password", label, "empty", "", required)
            continue
        if type_ == "hidden":
            if name:
                add(name, "hidden", name, "hidden", ab._attr(el, "value"), False, True)
            continue
        if type_ in ("submit", "button", "reset", "image"):
            if type_ == "submit" and name and not submit_done:
                value = ab._attr(el, "value") if el.name == "input" else (ab._attr(el, "value") if el.has_attr("value") else "")
                add(name, "submit", ab._attr(el, "value") or el.get_text(" ", strip=True) or name, "default", value)
                submit_done = True
            continue
        if type_ == "file":
            out.has_file_input = True
            if required:
                out.problem("file_upload_required")
            continue
        if not name:
            continue

        # anti-bot controls are reported, never filled
        if is_trap(el, label_raw):
            out.honeypots.append(name)
            add(name, type_, label, "empty", "", False)
            continue
        if ab.is_captcha_field(text_hay):
            out.captcha_fields.append(name)
            add(name, type_, label, "empty", "", required)
            continue
        if ab.is_otp_field(text_hay, ab.hay(name, ab._attr(el, "id")), has_send_button):
            out.otp_fields.append(name)
            add(name, type_, label, "empty", "", required)
            continue

        if type_ == "checkbox":
            if el.has_attr("checked"):
                add(name, "checkbox", label, "default", ab._attr(el, "value") or "on", required)
            elif required:
                out.problem("required_checkbox", label)
            continue

        if type_ == "radio":
            if name in radio_seen:
                continue
            radio_seen.add(name)
            group = [r for r in controls if r.name == "input" and type_of(r) == "radio" and ab._attr(r, "name") == name]
            checked = next((r for r in group if r.has_attr("checked")), None)
            group_required = any(is_required(r, label_for(r, labels_by_for)) for r in group)
            group_label = _clean_label(_group_label(el)) or label
            if checked is not None:
                add(name, "radio", group_label, "default", ab._attr(checked, "value") or "on", group_required)
            elif group_required:
                out.problem("required_field_unfillable", group_label)
            continue

        if el.name == "select":
            options = [o for o in el.find_all("option")]
            usable = [o for o in options if not o.has_attr("disabled")]
            selected = [o for o in usable if o.has_attr("selected")]

            def value_of(option: Tag) -> str:
                return option.get("value") if option.has_attr("value") else option.get_text(strip=True)

            if el.has_attr("multiple"):
                for option in selected:
                    add(name, "select", label, "default", value_of(option), required)
                if not selected and required:
                    out.problem("required_field_unfillable", label)
                continue
            if selected:
                chosen = selected[-1]
            elif required:
                out.problem("required_field_unfillable", label)
                continue
            else:
                chosen = usable[0] if usable else None  # what a browser submits for an optional select
            add(name, "select", label, "default", value_of(chosen) if chosen is not None else "", required)
            if required and chosen is not None and not value_of(chosen):
                out.problem("required_field_unfillable", label)
            continue

        # ---- text-like controls and textareas
        kind = "message" if el is message_el else classify(type_, el.name, text_hay)
        if kind == "message" and el is not message_el:
            kind = "other"  # a second textarea never receives the message
        if kind == "message" and el is message_el:
            value, source = message, "message"
        elif kind == "email":
            value, source = identity.email, "identity_email"
        elif kind == "phone":
            value, source = identity.phone, "identity_phone"
        elif kind == "website":
            value, source = identity.website, "identity_website"
        elif kind == "company":
            value, source = identity.company, "identity_company"
        elif kind == "subject":
            value, source = subject, "subject"
        elif kind == "name":
            value, source = identity.name, "identity_name"
        elif kind == "first_name":
            value, source = _split_name(identity.name)[0], "identity_name"
        elif kind == "last_name":
            value, source = _split_name(identity.name)[1], "identity_name"
        else:
            value, source = "", "empty"

        if source == "empty":
            prefilled = ab._attr(el, "value") if el.name == "input" else (el.get_text() or "").strip()
            if prefilled.strip():
                add(name, type_, label, "default", prefilled, required)
            else:
                add(name, type_, label, "empty", "", required)
                if required:
                    out.problem("required_field_unfillable", label)
            continue
        if not value:
            add(name, type_, label, "empty", "", required)
            if required:
                out.problem("required_field_unfillable", label)
            continue
        limit = ab._attr(el, "maxlength")
        if limit.isdigit() and len(value) > int(limit):
            # cutting the text short would change what we say: a person decides
            out.problem("required_field_unfillable", f"{label} (حداکثر {limit} نویسه)")
        add(name, type_, label, source, value, required)
    return out
