"""Getting back in after a forgotten password.

This path did not exist at all until now. Most of what follows is not about the
happy case — that part is three lines — but about the ways a reset flow leaks
or lies:

* telling a stranger which of your customers' addresses are registered,
* saying "we sent you a link" when the mail server refused,
* leaving a used link working,
* handing back a session so a leaked link is a full takeover.
"""
from django.contrib.auth.models import User
from django.contrib.auth.tokens import default_token_generator
from django.core import mail
from django.test import TestCase, override_settings
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode

from . import password_reset

REQUEST_URL = "/api/v1/auth/password-reset/"
CHECK_URL = "/api/v1/auth/password-reset/check/"
CONFIRM_URL = "/api/v1/auth/password-reset/confirm/"


def uid_for(user):
    return urlsafe_base64_encode(force_bytes(user.pk))


class RequestTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            "shopkeeper", email="owner@shop.ir", password="OldPass!2024",
        )

    def test_a_link_is_emailed_to_a_real_account(self):
        response = self.client.post(
            REQUEST_URL, {"email": "owner@shop.ir"}, content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("reset-password", mail.outbox[0].body)
        self.assertEqual(mail.outbox[0].to, ["owner@shop.ir"])

    def test_an_unknown_address_gets_the_same_answer_and_no_email(self):
        """An endpoint that answers differently is a way to test which of your
        customers are registered."""
        known = self.client.post(
            REQUEST_URL, {"email": "owner@shop.ir"}, content_type="application/json",
        )
        mail.outbox.clear()
        unknown = self.client.post(
            REQUEST_URL, {"email": "nobody@nowhere.ir"}, content_type="application/json",
        )

        self.assertEqual(known.status_code, unknown.status_code)
        self.assertEqual(known.json(), unknown.json())
        self.assertEqual(len(mail.outbox), 0)

    def test_the_response_never_says_how_many_emails_went_out(self):
        response = self.client.post(
            REQUEST_URL, {"email": "owner@shop.ir"}, content_type="application/json",
        )
        self.assertNotIn("sent", response.json())

    def test_casing_does_not_matter(self):
        """Being told "no such account" over a capital letter loses a customer."""
        self.client.post(
            REQUEST_URL, {"email": "Owner@Shop.IR"}, content_type="application/json",
        )
        self.assertEqual(len(mail.outbox), 1)

    def test_an_empty_email_is_accepted_quietly_and_sends_nothing(self):
        response = self.client.post(
            REQUEST_URL, {"email": ""}, content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(mail.outbox), 0)

    def test_a_deactivated_account_gets_no_link(self):
        self.user.is_active = False
        self.user.save()
        self.client.post(
            REQUEST_URL, {"email": "owner@shop.ir"}, content_type="application/json",
        )
        self.assertEqual(len(mail.outbox), 0)

    def test_a_dead_mail_server_is_reported_not_hidden(self):
        """"We sent you a link" when nothing was sent leaves the customer
        waiting instead of asking for help."""
        with override_settings(
            EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend"
        ):
            from unittest.mock import patch

            with patch.object(
                password_reset, "send_mail", side_effect=OSError("smtp refused")
            ):
                response = self.client.post(
                    REQUEST_URL, {"email": "owner@shop.ir"},
                    content_type="application/json",
                )

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["error"]["code"], "email_failed")

    def test_the_email_says_what_to_do_if_it_was_not_you(self):
        self.client.post(
            REQUEST_URL, {"email": "owner@shop.ir"}, content_type="application/json",
        )
        body = mail.outbox[0].body
        self.assertIn("نادیده بگیرید", body)
        self.assertIn("تغییر نکرده", body)

    def test_the_link_is_absolute(self):
        """A relative link in an email is a link nobody can click.

        `PANEL_URL` lives in UPMARKET_PAYMENT because the gateway callback
        needed it first; reading the wrong settings dict here produced exactly
        that, and only a real run showed it.
        """
        self.client.post(
            REQUEST_URL, {"email": "owner@shop.ir"}, content_type="application/json",
        )
        link = [
            line.strip() for line in mail.outbox[0].body.splitlines()
            if "reset-password" in line
        ][0]
        self.assertTrue(
            link.startswith("http://") or link.startswith("https://"),
            f"لینک نسبی است و کلیک نمی‌شود: {link}",
        )

    def test_the_email_says_how_long_the_link_lasts(self):
        """Otherwise the reader cannot tell whether an old email is still good."""
        with override_settings(PASSWORD_RESET_TIMEOUT=60 * 60 * 24):
            body = password_reset._body(self.user, "https://example.ir/x")
        self.assertIn("24 ساعت", body)

        with override_settings(PASSWORD_RESET_TIMEOUT=60 * 60 * 2):
            body = password_reset._body(self.user, "https://example.ir/x")
        self.assertIn("2 ساعت", body)


class CheckTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            "shopkeeper", email="owner@shop.ir", password="OldPass!2024",
        )
        self.uid = uid_for(self.user)
        self.token = default_token_generator.make_token(self.user)

    def test_a_fresh_link_checks_out(self):
        response = self.client.get(f"{CHECK_URL}?uid={self.uid}&token={self.token}")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["valid"])
        self.assertEqual(response.json()["username"], "shopkeeper")

    def test_a_tampered_token_is_refused(self):
        response = self.client.get(f"{CHECK_URL}?uid={self.uid}&token=not-a-token")
        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.json()["valid"])

    def test_a_bad_uid_and_a_bad_token_give_the_same_message(self):
        """Distinguishing them tells a stranger holding a guessed link which
        half they got right."""
        bad_token = self.client.get(f"{CHECK_URL}?uid={self.uid}&token=wrong")
        bad_uid = self.client.get(f"{CHECK_URL}?uid=zzzz&token={self.token}")
        self.assertEqual(bad_token.json()["message"], bad_uid.json()["message"])

    def test_checking_happens_before_typing(self):
        """The page can say "expired" on load rather than after the user has
        typed a new password twice."""
        response = self.client.get(f"{CHECK_URL}?uid=&token=")
        self.assertEqual(response.status_code, 400)


class ConfirmTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            "shopkeeper", email="owner@shop.ir", password="OldPass!2024",
        )
        self.uid = uid_for(self.user)
        self.token = default_token_generator.make_token(self.user)

    def _confirm(self, password="BrandNew!2026", token=None):
        return self.client.post(
            CONFIRM_URL,
            {"uid": self.uid, "token": token or self.token, "password": password},
            content_type="application/json",
        )

    def test_the_new_password_works(self):
        self.assertEqual(self._confirm().status_code, 200)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("BrandNew!2026"))

    def test_the_old_password_stops_working(self):
        self._confirm()
        self.user.refresh_from_db()
        self.assertFalse(self.user.check_password("OldPass!2024"))

    def test_the_link_dies_after_one_use(self):
        """The token is derived from the password hash, so changing the
        password is what expires it. No table to sweep."""
        self.assertEqual(self._confirm().status_code, 200)
        second = self._confirm(password="Another!2026")
        self.assertEqual(second.status_code, 400)

    def test_no_session_is_handed_back(self):
        """A leaked link should mean a password change the owner can notice,
        not a silent session for whoever had it."""
        body = self._confirm().json()
        self.assertNotIn("access", body)
        self.assertNotIn("refresh", body)
        self.assertNotIn("token", body)

    # محصول بی‌قاعدهٔ رمز کار می‌کند (AUTH_PASSWORD_VALIDATORS خالی، به خواستِ مالک)؛ این آزمون فقط
    # گزارشِ درستِ خطا را می‌سنجد، پس همین‌جا قاعده‌ها را موقتاً برمی‌گرداند.
    @override_settings(AUTH_PASSWORD_VALIDATORS=[
        {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
        {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
    ])
    def test_a_weak_password_is_refused_with_the_real_reason(self):
        response = self._confirm(password="1234")
        self.assertEqual(response.status_code, 400)
        self.assertTrue(response.json()["error"]["message"])
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("OldPass!2024"))

    def test_a_forged_token_changes_nothing(self):
        response = self._confirm(token="forged")
        self.assertEqual(response.status_code, 400)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("OldPass!2024"))

    def test_another_users_token_does_not_work_on_this_uid(self):
        other = User.objects.create_user("other", email="o@x.ir", password="Pass!2024x")
        response = self._confirm(token=default_token_generator.make_token(other))
        self.assertEqual(response.status_code, 400)


class EndToEndTests(TestCase):
    def test_forgot_then_reset_then_log_in(self):
        """The whole path, through real HTTP."""
        User.objects.create_user("owner", email="e2e@shop.ir", password="OldPass!2024")

        self.client.post(
            REQUEST_URL, {"email": "e2e@shop.ir"}, content_type="application/json",
        )
        body = mail.outbox[0].body
        link = [line for line in body.splitlines() if "reset-password" in line][0]
        query = link.split("?", 1)[1]
        params = dict(pair.split("=", 1) for pair in query.split("&"))

        check = self.client.get(f"{CHECK_URL}?uid={params['uid']}&token={params['token']}")
        self.assertTrue(check.json()["valid"])

        confirm = self.client.post(
            CONFIRM_URL,
            {"uid": params["uid"], "token": params["token"], "password": "Fresh!2026pw"},
            content_type="application/json",
        )
        self.assertEqual(confirm.status_code, 200)

        login = self.client.post(
            "/api/v1/auth/login/",
            {"username": "owner", "password": "Fresh!2026pw"},
            content_type="application/json",
        )
        self.assertEqual(login.status_code, 200)
        self.assertIn("access", login.json())


class RegistrationEmailTests(TestCase):
    """The root cause: a person who signs up without an address can never
    reset a forgotten password."""

    URL = "/api/v1/auth/register/"

    def test_email_is_required(self):
        response = self.client.post(
            self.URL, {"username": "noemail", "password": "Str0ngPass!x"},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("بازیابی", str(response.json()))

    def test_a_blank_email_is_refused(self):
        response = self.client.post(
            self.URL, {"username": "blank", "email": "", "password": "Str0ngPass!x"},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)

    def test_a_duplicate_email_is_refused_with_advice(self):
        """Two accounts on one address make "send the reset link" ambiguous."""
        User.objects.create_user("first", email="taken@shop.ir", password="Pass!2024x")
        response = self.client.post(
            self.URL,
            {"username": "second", "email": "taken@shop.ir", "password": "Str0ngPass!x"},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("فراموش", str(response.json()))

    def test_a_duplicate_in_different_casing_is_still_a_duplicate(self):
        User.objects.create_user("first", email="taken@shop.ir", password="Pass!2024x")
        response = self.client.post(
            self.URL,
            {"username": "second", "email": "TAKEN@Shop.ir", "password": "Str0ngPass!x"},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)

    def test_a_normal_registration_still_works(self):
        response = self.client.post(
            self.URL,
            {"username": "fine", "email": "fine@shop.ir", "password": "Str0ngPass!x"},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 201)
