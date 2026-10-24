"""Letting someone who forgot their password back in.

This was missing entirely — no "forgot password" anywhere, in the site or the
panel. Until the first paying customer that costs nothing; from the first day
of sales it means every lost password becomes a personal message to the
founders, at whatever hour it happens.

Four decisions, each protecting against a specific thing:

**The token is not stored.** Django's `default_token_generator` derives it from
the user's password hash, their last login and a timestamp. So it needs no
table, needs no cleanup, and — the part that matters — becomes invalid the
moment the password changes. A stored-token table has to be swept, and a
forgotten row is a spare key to someone's shop.

**The request never says whether the email exists.** Same response, same
status, whether or not anyone matches. An endpoint that answers differently is
a way to test which of your customers' addresses are registered, and that list
is worth money to the wrong people.

**The email is sent, then the response returns.** If the mail server is down,
the caller is told the truth rather than "we sent you a link" — a customer who
believes a link is coming waits instead of asking for help.

**Confirming logs nobody in.** A successful reset returns nothing but success;
the user then signs in normally. Handing back a session would mean a leaked
link is a full account takeover rather than a password change the owner can see
happened.
"""
from __future__ import annotations

import logging

from django.conf import settings
from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password
from django.contrib.auth.tokens import default_token_generator
from django.core.exceptions import ValidationError
from django.core.mail import send_mail
from django.utils.encoding import force_bytes, force_str
from django.utils.http import urlsafe_base64_decode, urlsafe_base64_encode

logger = logging.getLogger(__name__)

#: What the caller is told either way. Deliberately vague about existence and
#: deliberately specific about what to do next.
GENERIC_REPLY = (
    "اگر حسابی با این ایمیل ثبت شده باشد، لینک بازیابی رمز برایش فرستاده شد. "
    "چند دقیقه صبر کنید و پوشه‌ی اسپم را هم نگاه کنید."
)

SUBJECT = "بازیابی رمز آپ‌مارکت"


class ResetFailed(Exception):
    """The link is not usable. Carries a message meant for the person reading it."""


def _panel_url() -> str:
    """Where the panel is served from.

    `PANEL_URL` lives in `UPMARKET_PAYMENT` because the gateway callback needed
    it first — not an obvious home for it, and reading the wrong dict here
    produced a relative link in the email, which a customer cannot click.
    """
    return str(settings.UPMARKET_PAYMENT.get("PANEL_URL", "")).rstrip("/")


def reset_link(user: User) -> str:
    """The URL the email points at.

    Lives in the panel, not the public site: the page needs to talk to the API
    and the panel is already authenticated against it.
    """
    uid = urlsafe_base64_encode(force_bytes(user.pk))
    token = default_token_generator.make_token(user)
    return f"{_panel_url()}/reset-password?uid={uid}&token={token}"


def _body(user: User, link: str) -> str:
    hours = max(1, settings.PASSWORD_RESET_TIMEOUT // 3600)
    name = user.first_name or user.username
    return (
        f"سلام {name}،\n\n"
        "برای حساب شما در آپ‌مارکت درخواست بازیابی رمز ثبت شد.\n"
        "برای گذاشتن رمز جدید روی این لینک بزنید:\n\n"
        f"{link}\n\n"
        f"این لینک {hours} ساعت اعتبار دارد و بعد از یک‌بار استفاده باطل می‌شود.\n\n"
        "اگر این درخواست از طرف شما نبود، این ایمیل را نادیده بگیرید — "
        "رمز فعلی‌تان تغییر نکرده و کسی به حساب شما دسترسی پیدا نکرده است.\n\n"
        "آپ‌مارکت"
    )


def request_reset(email: str) -> dict:
    """Send a reset link if this email belongs to someone.

    Returns the same shape regardless. `sent` is included for tests and logs,
    never for the HTTP response — putting it in the response would undo the
    whole point of the generic reply.
    """
    email = (email or "").strip()
    if not email:
        return {"detail": GENERIC_REPLY, "sent": 0}

    # `iexact` because people type their own address with different casing than
    # they registered it, and being told "no such account" over a capital
    # letter is the kind of thing that loses a customer.
    people = list(User.objects.filter(email__iexact=email, is_active=True))

    sent = 0
    for user in people:
        link = reset_link(user)
        # fail_silently=False on purpose — see the module docstring. The view
        # turns a failure into an honest error rather than a false promise.
        send_mail(
            subject=SUBJECT,
            message=_body(user, link),
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[user.email],
            fail_silently=False,
        )
        sent += 1

    if not people:
        # Logged, not returned. Useful when a customer swears they registered.
        logger.info("Password reset requested for an address with no account")

    return {"detail": GENERIC_REPLY, "sent": sent}


def _user_from_uid(uid: str) -> User | None:
    try:
        pk = force_str(urlsafe_base64_decode(uid))
        return User.objects.get(pk=pk, is_active=True)
    except (TypeError, ValueError, OverflowError, User.DoesNotExist):
        return None


def check_token(uid: str, token: str) -> User:
    """The user this link belongs to, or raise with a readable reason."""
    user = _user_from_uid(uid or "")
    # One message for both "no such user" and "bad token": distinguishing them
    # tells a stranger holding a guessed link which half they got right.
    if user is None or not default_token_generator.check_token(user, token or ""):
        raise ResetFailed(
            "این لینک معتبر نیست یا منقضی شده است. "
            "از صفحه‌ی «رمزم را فراموش کردم» یک لینک تازه بگیرید."
        )
    return user


def confirm_reset(uid: str, token: str, new_password: str) -> User:
    """Set the new password. The link stops working immediately after."""
    user = check_token(uid, token)

    try:
        validate_password(new_password, user=user)
    except ValidationError as exc:
        raise ResetFailed(" ".join(exc.messages)) from exc

    user.set_password(new_password)
    user.save(update_fields=["password"])
    # Nothing else to invalidate: the token was derived from the old password
    # hash, so changing the password is what expires the link.
    logger.info("Password reset completed for user %s", user.pk)
    return user
