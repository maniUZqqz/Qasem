"""Reading a contact / ticket page: is there a plain HTML form we may submit, and exactly what would be posted?

Pure functions over an HTML string (no network, no Django). ``analyze_page`` returns a ``FormPlan``;
the plan is stored on the outreach item (dry run), re-created right before a send, and its
``fingerprint_material`` is what an approval is bound to.

THE DATA CLASSES BELOW ARE THE FIXED INTERFACE used by the rest of the outreach module (see DESIGN-EXT.md
section 3 for every skip rule). Detection of anti-bot measures lives in ``form_antibot`` (detection only - nothing is
ever solved or bypassed), the field mapping in ``form_mapping``, the Persian reason texts in ``form_reasons``.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from urllib.parse import urldefrag, urljoin

from bs4 import BeautifulSoup

from . import form_antibot as ab
from . import form_mapping as mapping
from .form_reasons import REASON_CODES, REASON_TEXTS, text_for  # noqa: F401  (re-exported for the rest of outreach)

#: where a field's value comes from
SOURCES = (
    "identity_name", "identity_company", "identity_email", "identity_phone", "identity_website",
    "subject", "message", "hidden", "default", "empty",
)


@dataclass(frozen=True)
class SenderIdentity:
    """Who we truthfully are (from Growth Settings)."""

    name: str = ""
    company: str = ""
    phone: str = ""
    email: str = ""
    website: str = ""


@dataclass
class Reason:
    code: str
    text: str


@dataclass
class PlanField:
    name: str
    type: str  # text | email | tel | textarea | hidden | select | checkbox | radio | url | number | ...
    label: str
    source: str  # one of SOURCES
    value: str
    required: bool = False
    hidden: bool = False  # type=hidden: kept as the page gave it, shown redacted in the UI


@dataclass
class FormPlan:
    page_url: str = ""
    action_url: str = ""
    method: str = "POST"
    enctype: str = "urlencoded"  # urlencoded | multipart
    verdict: str = "skip"  # eligible | skip
    reasons: list[Reason] = field(default_factory=list)
    fields: list[PlanField] = field(default_factory=list)
    detected: dict = field(default_factory=dict)  # {"forms_found": n, "captcha": bool, "honeypot": bool, ...}

    @property
    def eligible(self) -> bool:
        return self.verdict == "eligible"

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "FormPlan":
        return cls(
            page_url=data.get("page_url", ""), action_url=data.get("action_url", ""), method=data.get("method", "POST"),
            enctype=data.get("enctype", "urlencoded"), verdict=data.get("verdict", "skip"),
            reasons=[Reason(**r) for r in data.get("reasons", [])], fields=[PlanField(**f) for f in data.get("fields", [])],
            detected=dict(data.get("detected", {})),
        )

    def payload_pairs(self) -> list[tuple[str, str]]:
        """What would be POSTed, in form order: every submitted field with its value (hidden ones included)."""
        return [(f.name, f.value) for f in self.fields if f.name]

    def fingerprint_material(self) -> dict:
        """What an approval is bound to. Hidden VALUES are left out (tokens change per page load); their NAMES are in."""
        return {
            "action_url": self.action_url,
            "method": self.method,
            "enctype": self.enctype,
            "visible": sorted((f.name, f.value) for f in self.fields if not f.hidden and f.name),
            "hidden_names": sorted(f.name for f in self.fields if f.hidden and f.name),
        }

# --------------------------------------------------------------------------- choosing the contact form

_CONTACT_STRONG = ab.words(
    "contact", "contact us", "contactus", "ticket", "tickets", "support", "helpdesk", "help desk", "enquiry", "inquiry", "feedback",
    "wpcf7", "cf7", "wpforms", "ninja forms", "gform", "formidable", "تماس", "تیکت", "پشتیبانی", "ارتباط", "ثبت درخواست", "ارسال پیام", "پیام به ما",
)
_CONTACT_WEAK = ab.words("message", "send", "submit", "پیام", "ارسال", "درخواست")
_SEARCH = ab.words("search", "searchform", "جستجو", "جست و جو", "جستوجو")
_NEWSLETTER = ab.words("newsletter", "subscribe", "subscription", "mailchimp", "sendinblue", "mc4wp", "خبرنامه", "عضویت در خبرنامه", "اشتراک")
_LOGINISH = ab.words("login", "log in", "signin", "sign in", "signup", "sign up", "register", "registration", "lostpassword", "ورود", "ثبت نام", "فراموشی رمز")
_COMMENT = ab.words("commentform", "comment form", "wp comments post", "comments post", "ارسال دیدگاه")
_CART = ab.words("cart", "checkout", "add to cart", "basket", "woocommerce", "coupon", "سبد خرید", "تسویه حساب", "کد تخفیف")
_SEARCH_NAMES = {"q", "s", "search", "query", "keyword", "keywords", "k", "term", "searchterm"}
_TEXTISH = {"text", "search", "number", "tel", "email", "url", "date", "time", "datetime-local", "month", "week", "range", "color"}
MIN_FORM_SCORE = 3


def _form_attr_hay(form, heading: str) -> str:
    buttons = " ".join(
        (ab._attr(b, "value") if b.name == "input" else b.get_text(" "))
        for b in form.find_all(["button", "input"])
        if b.name == "button" or ab._attr(b, "type").lower() in ("submit", "button")
    )
    return ab.hay(
        ab._attr(form, "action"), ab._attr(form, "id"), ab._attr(form, "class"), ab._attr(form, "name"), ab._attr(form, "role"),
        ab._attr(form, "aria-label"), heading, buttons,
    )


def _heading_for(form) -> str:
    inner = form.find(["h1", "h2", "h3", "h4", "legend"])
    before = form.find_previous(["h1", "h2", "h3", "h4", "legend"])
    texts = [ab.visible_text(n)[:100] for n in (inner, before) if n is not None]
    return " ".join(texts)


def _score_form(form, heading: str, labels_by_for: dict[str, str], hidden_classes: set[str], hidden_ids: set[str]) -> int:
    controls = form.find_all(["input", "select", "textarea"])
    visible = []
    for c in controls:
        type_ = (ab._attr(c, "type") or "text").lower() if c.name == "input" else c.name
        if type_ in ("hidden", "submit", "button", "image", "reset"):
            continue
        if ab.hidden_from_people(c, form, hidden_classes, hidden_ids):
            continue
        visible.append((c, type_))
    has_textarea = any(t == "textarea" for _, t in visible)
    score = 0
    if has_textarea:
        score += 4
    kinds = set()
    for c, type_ in visible:
        label = mapping.label_for(c, labels_by_for)
        text_hay = ab.hay(ab._attr(c, "name"), ab._attr(c, "id"), ab._attr(c, "placeholder"), ab._attr(c, "aria-label"), label, ab._attr(c, "autocomplete"))
        kinds.add(mapping.classify(type_, c.name, text_hay) if c.name != "textarea" else "message")
    score += 2 if "email" in kinds else 0
    score += 1 if "phone" in kinds else 0
    score += 1 if kinds & {"name", "first_name", "last_name"} else 0
    score += 1 if "subject" in kinds else 0
    attrs = _form_attr_hay(form, heading)
    if _CONTACT_STRONG.search(attrs):
        score += 3
    elif _CONTACT_WEAK.search(attrs):
        score += 1
    # things that are not a contact form
    if ab.form_has_password(form):
        score -= 10
    elif _LOGINISH.search(ab.hay(ab._attr(form, "action"), ab._attr(form, "id"), ab._attr(form, "class"), ab._attr(form, "name"))):
        score -= 6
    text_inputs = [(c, t) for c, t in visible if t in _TEXTISH]
    only_search_input = len(text_inputs) <= 1 and not has_textarea and bool(text_inputs) and (
        (ab._attr(text_inputs[0][0], "name").lower() in _SEARCH_NAMES) or text_inputs[0][1] == "search"
    )
    if ab._attr(form, "role").lower() == "search" or only_search_input or (not has_textarea and _SEARCH.search(attrs)):
        score -= 10
    if not has_textarea:
        if _NEWSLETTER.search(attrs):
            score -= 8
        elif "email" in kinds and len(text_inputs) <= 2 and not (kinds & {"message", "phone"}):
            score -= 6
    if _COMMENT.search(ab.hay(ab._attr(form, "action"), ab._attr(form, "id"), ab._attr(form, "class"))):
        score -= 6
    if _CART.search(ab.hay(ab._attr(form, "action"), ab._attr(form, "id"), ab._attr(form, "class"))) or form.find("input", attrs={"name": re.compile(r"quantity", re.I)}):
        score -= 8
    return score


def _strip_fragment(url: str) -> str:
    return urldefrag(url)[0]


def _resolve_action(form, base_url: str) -> str:
    action = ab._attr(form, "action").strip()
    if not action or action == "#":
        return _strip_fragment(base_url)
    if action.lower().startswith("javascript:"):
        return action
    return _strip_fragment(urljoin(base_url, action))


# --------------------------------------------------------------------------- the entry point


def analyze_page(
    html: str,
    page_url: str,
    *,
    fetch_status: int = 200,
    fetch_final_url: str = "",
    sender: SenderIdentity,
    message: str,
    subject: str = "",
) -> FormPlan:
    """Pick the contact form on ``html`` and decide whether it may be submitted. See DESIGN-EXT.md section 3.

    ``fetch_status`` / ``fetch_final_url`` come from the fetch of the page (a redirect to a login page, a 401/403 or a
    Cloudflare challenge are page-level reasons). The returned plan is ``eligible`` only when NO reason was found.
    """
    plan = FormPlan(page_url=page_url, action_url="", method="POST", enctype="urlencoded", verdict="skip")
    det = plan.detected
    det.update(
        forms_found=0, chosen_form_index=None, form_score=None, captcha=False, captcha_kinds=[], honeypot=False, honeypot_fields=[],
        login=False, otp=False, js_only=False, challenge=False, has_file_input=False, spa_shell=False, get_forms=0,
    )
    found: list[tuple[str, str]] = []

    def add(code: str, label: str = "") -> None:
        item = (code, text_for(code, label))
        if item not in found:
            found.append(item)

    def finish() -> FormPlan:
        plan.reasons = [Reason(code, text) for code, text in found]
        plan.verdict = "eligible" if not found else "skip"
        return plan

    html = html or ""
    # ---- page-level: things that mean there is no real page to submit to
    if ab.looks_like_challenge(html, fetch_status):
        det["challenge"] = True
        add("challenge_page")
        return finish()
    if fetch_status in (401, 403):
        det["login"] = True
        add("login_required")
        return finish()
    if not fetch_status or fetch_status >= 400:
        add("fetch_failed")
        return finish()
    if ab.login_redirect(page_url, fetch_final_url):
        det["login"] = True
        add("login_required")
        return finish()

    soup = BeautifulSoup(html, "html.parser")
    base_url = fetch_final_url or page_url
    base_tag = soup.find("base", href=True)
    if base_tag is not None:
        base_url = urljoin(base_url, ab._attr(base_tag, "href"))
    forms = soup.find_all("form")
    det["forms_found"] = len(forms)
    hidden_classes, hidden_ids = ab.style_hidden_selectors(soup)
    labels_by_for = {}
    for lab in soup.find_all("label", attrs={"for": True}):
        labels_by_for.setdefault(ab._attr(lab, "for"), mapping._label_text(lab))
    page_text = ab.visible_text(soup)
    login_text = ab.login_text_present(page_text)

    # ---- which form is the contact form?
    best = None
    for index, form in enumerate(forms):
        method = (ab._attr(form, "method") or "get").strip().lower()
        action_url = _resolve_action(form, base_url)
        postable = action_url.lower().startswith(("http://", "https://")) or action_url.lower().startswith("javascript:")
        if method != "post":
            det["get_forms"] += 1
            continue
        if not postable:
            continue  # mailto:, tel: ... cannot be posted
        score = _score_form(form, _heading_for(form), labels_by_for, hidden_classes, hidden_ids)
        if score >= MIN_FORM_SCORE and (best is None or score > best[0]):
            best = (score, index, form, action_url)

    if best is None:
        if any(ab.form_has_password(f) for f in forms) or login_text:
            det["login"] = True
            add("login_required")
        if ab.looks_like_spa_shell(soup):
            det["spa_shell"] = det["js_only"] = True
            add("js_only")
        add("no_form_found")
        return finish()

    score, index, form, action_url = best
    det["chosen_form_index"], det["form_score"] = index, score
    plan.action_url = action_url
    plan.method = "POST"
    plan.enctype = "multipart" if "multipart/form-data" in ab._attr(form, "enctype").lower() else "urlencoded"

    built = mapping.build_fields(
        form, soup, mapping.Identity(sender.name, sender.company, sender.phone, sender.email, sender.website), subject, message,
        hidden_classes, hidden_ids,
    )
    plan.fields = [PlanField(**f) for f in built.fields]
    det["has_file_input"] = built.has_file_input

    # ---- every eligibility check, over the whole page and the chosen form
    if ab.form_is_js_only(form):
        det["js_only"] = True
        add("js_only")
    if built.has_password or login_text:
        det["login"] = True
        add("login_required")
    kinds = ab.captcha_kinds_on_page(soup) | ab.captcha_kinds_in_form(form)
    if built.captcha_fields:
        kinds.add("field")
    if kinds:
        det["captcha"] = True
        det["captcha_kinds"] = sorted(kinds)
        add("captcha")
    if built.honeypots:
        det["honeypot"] = True
        det["honeypot_fields"] = built.honeypots
        add("honeypot")
    if built.otp_fields:
        det["otp"] = True
        add("otp_required")
    for code, text in built.problems:
        if (code, text) not in found:
            found.append((code, text))
    if not built.has_message_field:
        add("no_message_field")
    return finish()
