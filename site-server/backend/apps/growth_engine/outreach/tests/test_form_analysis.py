"""Form analysis: choosing the contact form, mapping fields truthfully, and skipping everything that needs a person.

Pure functions over saved HTML fixtures (``fixtures/forms/*.html``): no network, no database.
"""
import json
from pathlib import Path

from django.test import SimpleTestCase

from apps.growth_engine.outreach.services import form_antibot as ab
from apps.growth_engine.outreach.services import form_mapping as mapping
from apps.growth_engine.outreach.services.form_analysis import FormPlan, PlanField, SenderIdentity, analyze_page
from apps.growth_engine.outreach.services.form_reasons import REASON_CODES, REASON_TEXTS, text_for

FIXTURES = Path(__file__).parent / "fixtures" / "forms"
SENDER = SenderIdentity(name="علی رضایی", company="آپ‌مارکت", phone="09121234567", email="ali@upmarket.ir", website="https://upmarket.ir")
MESSAGE = "سلام،\nاین یک پیام آزمایشی است.\n\nعلی رضایی"
SUBJECT = "معرفی آپ‌مارکت"
URL = "https://shop.example.ir/contact"

#: every reason code of the design table (DESIGN-EXT.md section 3)
TABLE_CODES = {
    "captcha", "honeypot", "login_required", "otp_required", "js_only", "challenge_page", "file_upload_required",
    "required_field_unfillable", "required_checkbox", "no_message_field", "no_form_found", "no_target_url", "robots_blocked",
    "robots_unavailable", "fetch_failed",
}


def html(name: str) -> str:
    return (FIXTURES / f"{name}.html").read_text(encoding="utf-8")


def run(source: str, **kwargs) -> FormPlan:
    """Analyse a fixture name (or raw html when it contains «<»)."""
    page = source if "<" in source else html(source)
    kwargs.setdefault("sender", SENDER)
    kwargs.setdefault("message", MESSAGE)
    kwargs.setdefault("subject", SUBJECT)
    return analyze_page(page, kwargs.pop("url", URL), **kwargs)


def codes(plan: FormPlan) -> list[str]:
    return [r.code for r in plan.reasons]


def field(plan: FormPlan, name: str) -> PlanField:
    matches = [f for f in plan.fields if f.name == name]
    assert matches, f"no field {name!r} in {[f.name for f in plan.fields]}"
    return matches[0]


def swap(source: str, old: str, new: str) -> str:
    text = html(source)
    assert old in text, old
    return text.replace(old, new, 1)


# =============================================================================================== eligible forms


class PlainFormTests(SimpleTestCase):
    def test_a_plain_php_form_is_eligible(self):
        plan = run("plain_php")
        self.assertEqual((plan.verdict, plan.reasons), ("eligible", []))
        self.assertTrue(plan.eligible)

    def test_action_method_and_encoding(self):
        plan = run("plain_php")
        self.assertEqual((plan.action_url, plan.method, plan.enctype, plan.page_url), ("https://shop.example.ir/send.php", "POST", "urlencoded", URL))

    def test_the_exact_payload(self):
        self.assertEqual(
            run("plain_php").payload_pairs(),
            [("fullname", "علی رضایی"), ("email", "ali@upmarket.ir"), ("mobile", "09121234567"), ("subject", SUBJECT), ("message", MESSAGE), ("send", "1")],
        )

    def test_sources_of_every_value(self):
        plan = run("plain_php")
        sources = {f.name: f.source for f in plan.fields}
        self.assertEqual(
            sources,
            {"fullname": "identity_name", "email": "identity_email", "mobile": "identity_phone", "subject": "subject", "message": "message", "send": "default"},
        )

    def test_labels_are_clean_and_required_flags_are_read(self):
        plan = run("plain_php")
        self.assertEqual(field(plan, "fullname").label, "نام و نام خانوادگی")
        self.assertTrue(field(plan, "fullname").required)
        self.assertFalse(field(plan, "mobile").required)
        self.assertTrue(field(plan, "message").required)

    def test_field_types(self):
        plan = run("plain_php")
        self.assertEqual({f.name: f.type for f in plan.fields}, {"fullname": "text", "email": "email", "mobile": "tel", "subject": "text", "message": "textarea", "send": "submit"})

    def test_detected_summary_for_the_ui(self):
        det = run("plain_php").detected
        self.assertEqual((det["forms_found"], det["chosen_form_index"]), (1, 0))
        for key in ("captcha", "honeypot", "login", "otp", "js_only", "challenge", "has_file_input"):
            self.assertFalse(det[key], key)
        self.assertGreaterEqual(det["form_score"], 3)


class ContactForm7Tests(SimpleTestCase):
    def test_eligible_and_the_fragment_is_not_posted(self):
        plan = run("cf7")
        self.assertEqual((plan.verdict, plan.reasons), ("eligible", []))
        self.assertEqual(plan.action_url, "https://shop.example.ir/contact/")

    def test_hidden_inputs_keep_the_pages_values(self):
        plan = run("cf7")
        hidden = [f for f in plan.fields if f.hidden]
        self.assertEqual([f.name for f in hidden], ["_wpcf7", "_wpcf7_version", "_wpcf7_locale", "_wpcf7_unit_tag", "_wpcf7_container_post", "_wpcf7_posted_data_hash"])
        self.assertTrue(all(f.source == "hidden" and f.type == "hidden" for f in hidden))
        self.assertEqual(field(plan, "_wpcf7_unit_tag").value, "wpcf7-f123-p45-o1")

    def test_english_labels_map_to_the_identity(self):
        plan = run("cf7")
        self.assertEqual(field(plan, "your-name").source, "identity_name")
        self.assertEqual(field(plan, "your-email").source, "identity_email")
        self.assertEqual(field(plan, "your-subject").value, SUBJECT)
        self.assertEqual(field(plan, "your-message").value, MESSAGE)

    def test_aria_required_marks_required_fields(self):
        plan = run("cf7")
        self.assertTrue(field(plan, "your-name").required)
        self.assertFalse(field(plan, "your-subject").required)

    def test_the_submit_without_a_name_adds_nothing(self):
        self.assertNotIn("submit", [f.type for f in run("cf7").fields])

    def test_an_empty_subject_is_fine_when_the_field_is_optional(self):
        plan = run("cf7", subject="")
        self.assertEqual(plan.verdict, "eligible")
        self.assertEqual((field(plan, "your-subject").value, field(plan, "your-subject").source), ("", "empty"))


class LaravelFormTests(SimpleTestCase):
    def test_eligible_with_the_token_kept(self):
        plan = run("laravel_token")
        self.assertEqual(plan.verdict, "eligible")
        self.assertEqual(plan.action_url, "https://shop.example.ir/contact")
        token = field(plan, "_token")
        self.assertEqual((token.value, token.hidden, token.source), ("TOKEN_A", True, "hidden"))

    def test_optional_phone_is_filled_with_the_real_phone(self):
        plan = run("laravel_token")
        self.assertEqual((field(plan, "phone").value, field(plan, "phone").required), ("09121234567", False))

    def test_payload_order_is_document_order(self):
        self.assertEqual([n for n, _ in run("laravel_token").payload_pairs()], ["_token", "name", "email", "phone", "message"])


class MultipartTests(SimpleTestCase):
    def test_multipart_form_with_an_optional_file_is_eligible_and_the_file_is_left_out(self):
        plan = run("multipart_optional_file")
        self.assertEqual(plan.verdict, "eligible")
        self.assertEqual(plan.enctype, "multipart")
        self.assertNotIn("attachment", [f.name for f in plan.fields])
        self.assertTrue(plan.detected["has_file_input"])


class FieldMappingTests(SimpleTestCase):
    def test_english_form_with_unlabelled_names(self):
        plan = run("english_support")
        self.assertEqual(
            {f.name: f.source for f in plan.fields},
            {"f1": "identity_name", "f2": "identity_email", "f3": "identity_phone", "f4": "identity_company", "f5": "identity_website", "f6": "subject", "f7": "message"},
        )
        self.assertEqual(plan.verdict, "eligible")

    def test_persian_labels_full_name_company_website_phone(self):
        plan = run("persian_fullname_company")
        self.assertEqual(
            {f.name: (f.source, f.value) for f in plan.fields},
            {
                "x1": ("identity_name", "علی رضایی"), "x2": ("identity_company", "آپ‌مارکت"), "x3": ("identity_website", "https://upmarket.ir"),
                "x4": ("identity_phone", "09121234567"), "x5": ("identity_email", "ali@upmarket.ir"), "x6": ("message", MESSAGE),
            },
        )

    def test_a_company_field_never_receives_the_person_name(self):
        plan = run("persian_fullname_company")
        self.assertNotEqual(field(plan, "x2").value, SENDER.name)

    def test_first_and_last_name_fields_split_the_real_name(self):
        plan = run("first_last_name")
        self.assertEqual((field(plan, "first_name").value, field(plan, "last_name").value), ("علی", "رضایی"))
        self.assertEqual(plan.verdict, "eligible")

    def test_a_one_word_name_cannot_fill_a_required_last_name(self):
        plan = run("first_last_name", sender=SenderIdentity(name="علی", company="x", phone="09121234567", email="a@b.ir"))
        self.assertEqual(codes(plan), ["required_field_unfillable"])
        self.assertIn("نام خانوادگی", plan.reasons[0].text)

    def test_placeholders_only(self):
        plan = run("placeholder_only")
        self.assertEqual({f.name: f.source for f in plan.fields if f.type != "submit"}, {"a": "identity_name", "b": "identity_email", "c": "identity_phone", "d": "message"})
        self.assertEqual(plan.verdict, "eligible")

    def test_optional_unknown_fields_are_submitted_as_a_browser_would(self):
        plan = run("unknown_optional_fields")
        self.assertEqual(plan.verdict, "eligible")
        self.assertEqual(
            plan.payload_pairs(),
            [
                ("form_id", "42"), ("name", "علی رضایی"), ("email", "ali@upmarket.ir"), ("city", ""), ("source", "گوگل"), ("dept", "general"),
                ("newsletter", "yes"), ("message", MESSAGE), ("action", "send"),
            ],
        )
        self.assertEqual(field(plan, "city").source, "empty")
        self.assertEqual(field(plan, "source").source, "default")
        self.assertEqual(field(plan, "dept").source, "default")
        self.assertNotIn("callback", [f.name for f in plan.fields])

    def test_a_required_select_with_a_preselected_option_keeps_it(self):
        plan = run("select_default")
        self.assertEqual(plan.verdict, "eligible")
        self.assertEqual((field(plan, "department").value, field(plan, "department").source), ("support", "default"))

    def test_a_required_radio_with_a_checked_option_keeps_it(self):
        plan = run("radio_default")
        self.assertEqual(plan.verdict, "eligible")
        self.assertEqual([f.value for f in plan.fields if f.name == "kind"], ["support"])

    def test_the_message_goes_into_the_first_textarea_only(self):
        plan = run("two_textareas_optional")
        self.assertEqual(plan.verdict, "eligible")
        self.assertEqual((field(plan, "message").value, field(plan, "address").value, field(plan, "address").source), (MESSAGE, "", "empty"))

    def test_an_unticked_optional_checkbox_is_not_sent(self):
        plan = run("terms_checkbox_optional")
        self.assertEqual(plan.verdict, "eligible")
        self.assertNotIn("terms", [f.name for f in plan.fields])

    def test_required_website_and_subject_are_filled_from_the_identity_and_template(self):
        plan = run("website_required")
        self.assertEqual(plan.verdict, "eligible")
        self.assertEqual((field(plan, "website").value, field(plan, "subject").value), ("https://upmarket.ir", SUBJECT))

    def test_a_required_website_with_no_identity_website_is_unfillable(self):
        plan = run("website_required", sender=SenderIdentity(name="علی رضایی", company="x", phone="0912", email="a@b.ir", website=""))
        self.assertEqual(codes(plan), ["required_field_unfillable"])
        self.assertIn("وب‌سایت", plan.reasons[0].text)

    def test_a_required_subject_with_no_template_subject_is_unfillable(self):
        plan = run("website_required", subject="")
        self.assertEqual(codes(plan), ["required_field_unfillable"])
        self.assertIn("موضوع", plan.reasons[0].text)

    def test_a_required_phone_with_an_empty_identity_phone_is_unfillable(self):
        page = '<form action="/c" method="post" class="contact"><input type="tel" name="p" required placeholder="موبایل"><input type="email" name="e" required><textarea name="m"></textarea></form>'
        plan = run(page, sender=SenderIdentity(name="n", company="c", phone="", email="a@b.ir"))
        self.assertEqual(codes(plan), ["required_field_unfillable"])

    def test_disabled_controls_are_not_submitted_and_not_required(self):
        plan = run("disabled_field")
        self.assertEqual(plan.verdict, "eligible")
        self.assertNotIn("locked", [f.name for f in plan.fields])

    def test_a_value_longer_than_maxlength_is_never_cut_short(self):
        plan = run("maxlength_message")
        self.assertEqual(codes(plan), ["required_field_unfillable"])
        self.assertIn("20", plan.reasons[0].text)

    def test_an_empty_action_posts_to_the_page_itself(self):
        plan = run("empty_action")
        self.assertEqual((plan.verdict, plan.action_url), ("eligible", URL))

    def test_the_final_url_after_redirects_is_the_base_of_a_relative_action(self):
        plan = run("empty_action", fetch_final_url="https://www.shop.example.ir/fa/contact")
        self.assertEqual(plan.action_url, "https://www.shop.example.ir/fa/contact")

    def test_a_base_tag_changes_where_a_relative_action_points(self):
        self.assertEqual(run("base_href").action_url, "https://cdn.example.ir/app/send")


# =============================================================================================== choosing the form


class ChoosingTheFormTests(SimpleTestCase):
    def test_the_contact_form_is_chosen_over_a_newsletter_form(self):
        plan = run("newsletter_and_contact")
        self.assertEqual(plan.verdict, "eligible")
        self.assertEqual((plan.detected["forms_found"], plan.detected["chosen_form_index"]), (2, 1))
        self.assertEqual(plan.action_url, "https://shop.example.ir/contact/send")

    def test_search_forms_are_not_contact_forms(self):
        plan = run("search_only")
        self.assertEqual(codes(plan), ["no_form_found"])
        self.assertEqual(plan.detected["forms_found"], 2)

    def test_a_comment_form_is_not_a_contact_form(self):
        self.assertEqual(codes(run("comment_form")), ["no_form_found"])

    def test_a_cart_form_is_not_a_contact_form(self):
        self.assertEqual(codes(run("cart_form")), ["no_form_found"])

    def test_a_form_that_would_be_sent_with_get_is_not_posted(self):
        plan = run("get_form")
        self.assertEqual(codes(plan), ["no_form_found"])
        self.assertEqual(plan.detected["get_forms"], 1)

    def test_a_mailto_form_cannot_be_posted(self):
        self.assertEqual(codes(run("mailto_form")), ["no_form_found"])

    def test_a_page_without_any_form(self):
        plan = run("no_form")
        self.assertEqual((codes(plan), plan.detected["forms_found"], plan.fields), (["no_form_found"], 0, []))

    def test_empty_html(self):
        self.assertEqual(codes(analyze_page("", URL, sender=SENDER, message=MESSAGE)), ["no_form_found"])

    def test_two_contact_forms_choose_the_better_scored_one(self):
        small = '<form action="/a" method="post" class="contact"><input name="e" type="email"><textarea name="m"></textarea></form>'
        big = '<form action="/b" method="post" class="contact"><input name="n" placeholder="نام"><input name="e" type="email"><input type="tel" name="p"><textarea name="m"></textarea></form>'
        plan = run(small + big)
        self.assertEqual(plan.action_url, "https://shop.example.ir/b")


# =============================================================================================== skip reasons


class LoginTests(SimpleTestCase):
    def test_a_ticket_system_that_needs_login(self):
        plan = run("ticket_login")
        self.assertEqual(codes(plan), ["login_required", "no_form_found"])
        self.assertTrue(plan.detected["login"])
        self.assertEqual(plan.verdict, "skip")

    def test_a_password_field_in_the_ticket_form(self):
        self.assertEqual(codes(run("password_in_ticket_form")), ["login_required", "no_form_found"])

    def test_redirected_to_a_login_page(self):
        plan = run("plain_php", fetch_final_url="https://shop.example.ir/login?next=/contact")
        self.assertEqual(codes(plan), ["login_required"])

    def test_a_redirect_that_is_not_a_login_is_fine(self):
        self.assertEqual(run("plain_php", fetch_final_url="https://shop.example.ir/fa/contact-us").verdict, "eligible")

    def test_landing_on_the_page_that_was_asked_for_is_not_a_redirect(self):
        self.assertEqual(run("plain_php", fetch_final_url=URL).verdict, "eligible")

    def test_http_401_and_a_plain_403_mean_login(self):
        for status in (401, 403):
            with self.subTest(status=status):
                self.assertEqual(codes(run("plain_php", fetch_status=status)), ["login_required"])

    def test_a_sentence_saying_login_is_needed_to_submit(self):
        text = swap("plain_php", "<h1>تماس با ما</h1>", "<h1>تماس با ما</h1><p>برای ارسال پیام باید وارد حساب کاربری شوید.</p>")
        self.assertIn("login_required", codes(run(text)))

    def test_the_login_link_in_the_menu_alone_is_not_a_reason(self):
        self.assertIn("ورود", html("plain_php"))
        self.assertEqual(run("plain_php").verdict, "eligible")


class CaptchaTests(SimpleTestCase):
    def assert_captcha(self, name, kind):
        plan = run(name)
        self.assertEqual(plan.verdict, "skip")
        self.assertIn("captcha", codes(plan))
        self.assertTrue(plan.detected["captcha"])
        self.assertIn(kind, plan.detected["captcha_kinds"])
        return plan

    def test_recaptcha_v2_widget(self):
        self.assert_captcha("recaptcha_v2", "recaptcha")

    def test_recaptcha_v3_script_without_any_widget(self):
        self.assert_captcha("recaptcha_v3", "recaptcha")

    def test_hcaptcha(self):
        self.assert_captcha("hcaptcha", "hcaptcha")

    def test_turnstile_widget_is_a_captcha_not_a_challenge_page(self):
        plan = self.assert_captcha("turnstile", "turnstile")
        self.assertFalse(plan.detected["challenge"])
        self.assertNotIn("challenge_page", codes(plan))

    def test_arcaptcha(self):
        self.assert_captcha("arcaptcha", "arcaptcha")

    def test_image_captcha(self):
        self.assert_captcha("captcha_image", "image")

    def test_maths_question(self):
        plan = self.assert_captcha("captcha_math", "math")
        self.assertEqual([f.value for f in plan.fields if f.name == "answer"], [""], "the answer is never guessed")

    def test_persian_security_code_label(self):
        self.assert_captcha("captcha_persian_label", "field")

    def test_the_captcha_text_is_persian_and_says_a_person_does_it(self):
        text = run("recaptcha_v2").reasons[0].text
        self.assertIn("کپچا", text)
        self.assertIn("دستی", text)

    def test_a_plain_form_has_no_captcha_kinds(self):
        self.assertEqual(run("plain_php").detected["captcha_kinds"], [])


class HoneypotTests(SimpleTestCase):
    def assert_honeypot(self, name, field_name):
        plan = run(name)
        self.assertEqual(plan.verdict, "skip")
        self.assertIn("honeypot", codes(plan))
        self.assertIn(field_name, plan.detected["honeypot_fields"])
        self.assertEqual(field(plan, field_name).value, "", "a honeypot is never filled")
        return plan

    def test_inline_style_display_none_wrapper(self):
        self.assert_honeypot("honeypot_inline", "website_url")

    def test_class_hidden_by_a_style_block(self):
        self.assert_honeypot("honeypot_css_class", "company_url")

    def test_netlify_bot_field(self):
        self.assert_honeypot("honeypot_netlify", "bot-field")

    def test_wpforms_hp_field(self):
        self.assert_honeypot("honeypot_wpforms", "wpforms[hp]")

    def test_only_the_honeypot_is_the_reason(self):
        self.assertEqual(codes(run("honeypot_inline")), ["honeypot"])

    def test_cf7_hidden_inputs_in_a_hidden_wrapper_are_not_honeypots(self):
        self.assertEqual(run("cf7").detected["honeypot_fields"], [])

    def test_screen_reader_only_text_is_not_hiding(self):
        page = '<form action="/c" method="post" class="contact"><input class="sr-only" type="text" name="nick" aria-label="نام مستعار"><input name="e" type="email"><textarea name="m"></textarea></form>'
        self.assertEqual(run(page).detected["honeypot_fields"], [])

    def test_hidden_attribute_and_aria_hidden(self):
        for attr in ('hidden', 'aria-hidden="true"'):
            with self.subTest(attr=attr):
                page = f'<form action="/c" method="post" class="contact"><input {attr} type="text" name="x"><input name="e" type="email"><textarea name="m"></textarea></form>'
                self.assertIn("honeypot", codes(run(page)))

    def test_tabindex_minus_one_with_autocomplete_off_and_no_label(self):
        page = '<form action="/c" method="post" class="contact"><input type="text" name="zz" tabindex="-1" autocomplete="off"><input name="e" type="email"><textarea name="m"></textarea></form>'
        self.assertIn("honeypot", codes(run(page)))


class OtpTests(SimpleTestCase):
    def test_a_form_asking_for_an_sms_code(self):
        plan = run("otp_form")
        self.assertIn("otp_required", codes(plan))
        self.assertTrue(plan.detected["otp"])
        self.assertEqual(field(plan, "code").value, "")

    def test_a_field_named_otp_is_enough(self):
        page = '<form action="/c" method="post" class="contact"><input name="otp" type="text"><input name="e" type="email"><textarea name="m"></textarea></form>'
        self.assertIn("otp_required", codes(run(page)))

    def test_a_confirmation_label_without_a_send_code_button_is_not_called_an_otp(self):
        page = '<form action="/c" method="post" class="contact"><input name="x" type="text" placeholder="کد تأیید"><input name="e" type="email"><textarea name="m"></textarea></form>'
        self.assertNotIn("otp_required", codes(run(page)))


class JavaScriptOnlyTests(SimpleTestCase):
    def test_action_hash_with_a_cancelling_onsubmit(self):
        plan = run("js_only_form")
        self.assertEqual(codes(plan), ["js_only"])
        self.assertTrue(plan.detected["js_only"])

    def test_framework_submit_handler_without_an_action(self):
        self.assertEqual(codes(run("js_only_framework")), ["js_only"])

    def test_javascript_action(self):
        self.assertEqual(codes(run("js_action_form")), ["js_only"])

    def test_an_empty_app_shell(self):
        plan = run("spa_shell")
        self.assertEqual(codes(plan), ["js_only", "no_form_found"])
        self.assertTrue(plan.detected["spa_shell"])

    def test_a_missing_action_alone_is_a_normal_form(self):
        self.assertEqual(run("empty_action").verdict, "eligible")

    def test_a_real_action_with_onsubmit_validation_is_a_normal_form(self):
        page = '<form action="/send" method="post" onsubmit="return validate();" class="contact"><input name="e" type="email"><textarea name="m"></textarea></form>'
        self.assertEqual(run(page).verdict, "eligible")


class ChallengePageTests(SimpleTestCase):
    def test_a_cloudflare_interstitial_even_with_status_200(self):
        plan = run("cloudflare_challenge")
        self.assertEqual(codes(plan), ["challenge_page"])
        self.assertTrue(plan.detected["challenge"])
        self.assertEqual(plan.fields, [])

    def test_403_with_cloudflare_markers(self):
        page = "<html><head><title>Attention</title></head><body>Cloudflare Ray ID: 1a2b3c4d</body></html>"
        self.assertEqual(codes(run(page, fetch_status=403)), ["challenge_page"])

    def test_503_with_ddos_protection_markers(self):
        page = "<html><body>DDoS protection by Cloudflare - cf-ray 123</body></html>"
        self.assertEqual(codes(run(page, fetch_status=503)), ["challenge_page"])

    def test_a_normal_page_behind_cloudflare_is_not_a_challenge(self):
        page = swap("plain_php", "</body>", '<script src="/cdn-cgi/challenge-platform/scripts/jsd/main.js"></script></body>')
        self.assertEqual(run(page).verdict, "eligible")

    def test_title_markers(self):
        for title in ("Just a moment...", "Attention Required! | Cloudflare", "Checking your browser before accessing"):
            with self.subTest(title=title):
                self.assertEqual(codes(run(f"<html><head><title>{title}</title></head><body></body></html>")), ["challenge_page"])


class FetchStatusTests(SimpleTestCase):
    def test_not_found_and_server_errors_are_fetch_failures(self):
        for status in (404, 410, 500, 502, 503):
            with self.subTest(status=status):
                self.assertEqual(codes(run("plain_php", fetch_status=status)), ["fetch_failed"])

    def test_no_status_at_all(self):
        self.assertEqual(codes(run("plain_php", fetch_status=0)), ["fetch_failed"])

    def test_redirect_status_codes_are_not_analysed_here(self):
        self.assertEqual(run("plain_php", fetch_status=200).verdict, "eligible")


class RequiredFieldTests(SimpleTestCase):
    def test_a_required_terms_checkbox_needs_a_person(self):
        plan = run("terms_checkbox_required")
        self.assertEqual(codes(plan), ["required_checkbox"])
        self.assertIn("با قوانین و مقررات سایت موافقم", plan.reasons[0].text)
        self.assertNotIn("terms", [f.name for f in plan.fields])

    def test_a_pre_ticked_required_checkbox_is_submitted_as_the_page_gave_it(self):
        text = swap("terms_checkbox_required", 'name="terms" value="1" required', 'name="terms" value="1" required checked')
        plan = run(text)
        self.assertEqual(plan.verdict, "eligible")
        self.assertEqual(field(plan, "terms").source, "default")

    def test_a_required_national_code(self):
        plan = run("national_code_required")
        self.assertEqual(codes(plan), ["required_field_unfillable"])
        self.assertIn("کد ملی", plan.reasons[0].text)

    def test_a_required_select_without_a_default(self):
        plan = run("select_no_default")
        self.assertEqual(codes(plan), ["required_field_unfillable"])
        self.assertIn("بخش", plan.reasons[0].text)
        self.assertNotIn("department", [f.name for f in plan.fields])

    def test_an_optional_select_submits_the_browser_default(self):
        text = swap("select_no_default", 'name="department" required', 'name="department"').replace("بخش *", "بخش")  # no attribute and no «*»
        plan = run(text)
        self.assertEqual(plan.verdict, "eligible")
        self.assertEqual(field(plan, "department").value, "")  # the first option is the empty placeholder

    def test_a_required_radio_group_without_a_choice(self):
        plan = run("radio_required")
        self.assertEqual(codes(plan), ["required_field_unfillable"])
        self.assertIn("نوع درخواست", plan.reasons[0].text)

    def test_a_second_required_textarea_cannot_be_filled(self):
        plan = run("two_textareas_required")
        self.assertEqual(codes(plan), ["required_field_unfillable"])
        self.assertIn("شرح محصول", plan.reasons[0].text)

    def test_a_required_file_upload(self):
        plan = run("file_required")
        self.assertEqual(codes(plan), ["file_upload_required"])
        self.assertEqual(plan.enctype, "multipart")
        self.assertNotIn("cv", [f.name for f in plan.fields])

    def test_no_place_for_a_message(self):
        plan = run("no_textarea")
        self.assertEqual(codes(plan), ["no_message_field"])

    def test_several_problems_are_all_reported(self):
        text = swap("national_code_required", "</form>", '<label><input type="checkbox" name="t" required> قوانین</label><input type="file" name="f" required></form>')
        self.assertEqual(sorted(codes(run(text))), sorted(["file_upload_required", "required_field_unfillable", "required_checkbox"]))


class CombinedReasonTests(SimpleTestCase):
    def test_captcha_honeypot_and_js_only_together(self):
        text = swap("honeypot_inline", "<form action=\"/contact\"", "<script src=\"https://www.google.com/recaptcha/api.js\"></script><form action=\"#\" onsubmit=\"return false\"")
        plan = run(text)
        self.assertEqual(sorted(codes(plan)), ["captcha", "honeypot", "js_only"])
        self.assertEqual(plan.verdict, "skip")

    def test_a_form_with_any_reason_is_never_eligible(self):
        for name in ("recaptcha_v2", "honeypot_inline", "otp_form", "js_only_form", "no_textarea", "file_required", "terms_checkbox_required"):
            with self.subTest(name=name):
                plan = run(name)
                self.assertEqual((plan.verdict, bool(plan.reasons)), ("skip", True))

    def test_verdict_is_eligible_exactly_when_there_are_no_reasons_for_every_fixture(self):
        for path in sorted(FIXTURES.glob("*.html")):
            with self.subTest(fixture=path.name):
                plan = run(path.stem)
                self.assertEqual(plan.verdict == "eligible", not plan.reasons)
                self.assertEqual(plan.eligible, plan.verdict == "eligible")

    def test_every_reason_has_persian_text(self):
        for path in sorted(FIXTURES.glob("*.html")):
            for reason in run(path.stem).reasons:
                with self.subTest(fixture=path.name, code=reason.code):
                    self.assertRegex(reason.text, "[؀-ۿ]")
                    self.assertIn(reason.code, REASON_CODES)


# =============================================================================================== reasons, texts, plan data


class ReasonTextTests(SimpleTestCase):
    def test_every_code_of_the_design_table_exists_with_persian_text(self):
        self.assertTrue(TABLE_CODES <= set(REASON_TEXTS))
        for code in TABLE_CODES:
            with self.subTest(code=code):
                self.assertRegex(text_for(code, "برچسب"), "[؀-ۿ]")

    def test_label_is_filled_into_the_per_field_reasons(self):
        self.assertIn("کد ملی", text_for("required_field_unfillable", "کد ملی"))
        self.assertIn("شرایط", text_for("required_checkbox", "شرایط"))

    def test_other_texts_ignore_the_label(self):
        self.assertEqual(text_for("captcha", "x"), REASON_TEXTS["captcha"])

    def test_texts_say_a_person_has_to_do_it_by_hand(self):
        for code in ("captcha", "honeypot", "login_required", "otp_required", "js_only", "challenge_page", "file_upload_required", "no_message_field"):
            with self.subTest(code=code):
                self.assertIn("دستی", REASON_TEXTS[code])


class PlanDataTests(SimpleTestCase):
    def test_to_dict_from_dict_round_trip_for_an_eligible_plan(self):
        plan = run("plain_php")
        again = FormPlan.from_dict(plan.to_dict())
        self.assertEqual(again.to_dict(), plan.to_dict())
        self.assertEqual(again.payload_pairs(), plan.payload_pairs())

    def test_round_trip_for_a_skipped_plan_with_reasons(self):
        plan = run("honeypot_inline")
        again = FormPlan.from_dict(plan.to_dict())
        self.assertEqual([(r.code, r.text) for r in again.reasons], [(r.code, r.text) for r in plan.reasons])
        self.assertEqual(again.detected, plan.detected)

    def test_the_dict_is_json_serialisable(self):
        for name in ("plain_php", "cf7", "recaptcha_v2", "ticket_login"):
            with self.subTest(name=name):
                json.dumps(run(name).to_dict(), ensure_ascii=False)

    def test_from_dict_tolerates_missing_keys(self):
        plan = FormPlan.from_dict({})
        self.assertEqual((plan.verdict, plan.method, plan.fields), ("skip", "POST", []))

    def test_payload_pairs_skip_nameless_fields(self):
        plan = FormPlan(fields=[PlanField("", "text", "x", "empty", ""), PlanField("a", "text", "a", "empty", "1")])
        self.assertEqual(plan.payload_pairs(), [("a", "1")])


class FingerprintTests(SimpleTestCase):
    def test_two_loads_that_differ_only_by_a_token_have_the_same_fingerprint_material(self):
        a = run("laravel_token")
        b = run(swap("laravel_token", "TOKEN_A", "TOKEN_B"))
        self.assertNotEqual(a.payload_pairs(), b.payload_pairs())
        self.assertEqual(a.fingerprint_material(), b.fingerprint_material())

    def test_a_different_message_changes_it(self):
        self.assertNotEqual(run("plain_php").fingerprint_material(), run("plain_php", message=MESSAGE + " (ویرایش)").fingerprint_material())

    def test_a_different_subject_changes_it(self):
        self.assertNotEqual(run("plain_php").fingerprint_material(), run("plain_php", subject="موضوع دیگر").fingerprint_material())

    def test_a_different_sender_changes_it(self):
        other = SenderIdentity(name="نفر دیگر", company="آپ‌مارکت", phone="09121234567", email="ali@upmarket.ir")
        self.assertNotEqual(run("plain_php").fingerprint_material(), run("plain_php", sender=other).fingerprint_material())

    def test_a_different_action_changes_it(self):
        changed = swap("plain_php", 'action="send.php"', 'action="other.php"')
        self.assertNotEqual(run("plain_php").fingerprint_material(), run(changed).fingerprint_material())

    def test_a_new_visible_field_changes_it(self):
        changed = swap("plain_php", "<button", '<input type="text" name="extra" placeholder="x"><button')
        self.assertNotEqual(run("plain_php").fingerprint_material(), run(changed).fingerprint_material())

    def test_a_new_hidden_field_name_changes_it(self):
        changed = swap("laravel_token", '<input type="hidden" name="_token" value="TOKEN_A">', '<input type="hidden" name="_token" value="TOKEN_A"><input type="hidden" name="nonce" value="9">')
        self.assertNotEqual(run("laravel_token").fingerprint_material(), run(changed).fingerprint_material())

    def test_a_changed_method_or_encoding_changes_it(self):
        changed = swap("multipart_optional_file", 'enctype="multipart/form-data"', "")
        self.assertNotEqual(run("multipart_optional_file").fingerprint_material(), run(changed).fingerprint_material())

    def test_material_shape(self):
        material = run("laravel_token").fingerprint_material()
        self.assertEqual(set(material), {"action_url", "method", "enctype", "visible", "hidden_names"})
        self.assertEqual(material["hidden_names"], ["_token"])
        self.assertEqual(material["visible"], sorted(material["visible"]))
        self.assertNotIn("TOKEN_A", json.dumps(material))


# =============================================================================================== the helpers themselves


class ClassifyTests(SimpleTestCase):
    def kind(self, label, type_="text", tag="input"):
        return mapping.classify(type_, tag, ab.hay(label))

    def test_english_labels(self):
        cases = {
            "Your email": "email", "E-mail address": "email", "Phone number": "phone", "Mobile": "phone", "Company name": "company",
            "Organization": "company", "Website URL": "website", "Subject": "subject", "Full name": "name", "Your name": "name",
            "First name": "first_name", "Last name": "last_name", "Surname": "last_name",
        }
        for label, expected in cases.items():
            with self.subTest(label=label):
                self.assertEqual(self.kind(label), expected)

    def test_persian_labels(self):
        cases = {
            "ایمیل": "email", "پست الکترونیکی": "email", "شماره تماس": "phone", "تلفن همراه": "phone", "شماره موبایل": "phone", "نام شرکت": "company",
            "نام فروشگاه": "company", "وب‌سایت": "website", "آدرس سایت": "website", "موضوع": "subject", "نام و نام خانوادگی": "name", "نام": "name",
            "نام کوچک": "first_name", "نام خانوادگی": "last_name",
        }
        for label, expected in cases.items():
            with self.subTest(label=label):
                self.assertEqual(self.kind(label), expected)

    def test_types_decide_first(self):
        self.assertEqual(self.kind("something", "email"), "email")
        self.assertEqual(self.kind("something", "tel"), "phone")
        self.assertEqual(self.kind("something", "url"), "website")

    def test_things_that_must_not_be_mistaken_for_a_name_or_phone(self):
        for label in ("نام کاربری", "Username", "کد ملی", "شماره سفارش", "Order number", "شماره فکس", "Fax", "کد پستی", "Postal code"):
            with self.subTest(label=label):
                self.assertEqual(self.kind(label), "other")

    def test_a_textarea_is_a_message(self):
        self.assertEqual(self.kind("anything", "textarea", "textarea"), "message")

    def test_persian_short_words_need_boundaries(self):
        self.assertEqual(self.kind("نامه"), "other")
        self.assertEqual(self.kind("اسم شما"), "name")


class AntibotHelperTests(SimpleTestCase):
    def test_hay_normalises(self):
        self.assertEqual(ab.hay("Your-Email_Address", "كد ۱۲۳"), " your email address کد 123 ")
        self.assertEqual(ab.hay("wpforms[fields][0]"), " wpforms fields 0 ")

    def test_words_boundaries(self):
        pattern = ab.words("mail", "ایمیل")
        self.assertTrue(pattern.search(" your mail "))
        self.assertFalse(pattern.search(" mailing list "))
        self.assertTrue(pattern.search(" ایمیلتان "))

    def test_login_sentences(self):
        for text in ("برای ارسال تیکت وارد شوید", "ابتدا وارد حساب کاربری شوید", "Please log in to submit a request", "You must be logged in to post", "Login required"):
            with self.subTest(text=text):
                self.assertTrue(ab.login_text_present(text))
        for text in ("ورود / ثبت‌نام", "تماس با ما", "Login", "We reply within a day"):
            with self.subTest(text=text):
                self.assertFalse(ab.login_text_present(text))

    def test_login_redirect(self):
        self.assertTrue(ab.login_redirect("https://a.ir/contact", "https://a.ir/wp-login.php?redirect_to=x"))
        self.assertTrue(ab.login_redirect("https://a.ir/support", "https://a.ir/ورود"))
        self.assertFalse(ab.login_redirect("https://a.ir/contact", "https://a.ir/contact"))
        self.assertFalse(ab.login_redirect("https://a.ir/contact", ""))
        self.assertFalse(ab.login_redirect("https://a.ir/login", "https://a.ir/login?x=1"))

    def test_challenge_detection(self):
        self.assertTrue(ab.looks_like_challenge("<title>Just a moment...</title>"))
        self.assertTrue(ab.looks_like_challenge("<script>window._cf_chl_opt={}</script>"))
        self.assertTrue(ab.looks_like_challenge("<html>cloudflare</html>", 403))
        self.assertFalse(ab.looks_like_challenge("<html>cloudflare</html>", 200))
        self.assertFalse(ab.looks_like_challenge("<title>تماس با ما</title>"))

    def test_style_hidden_selectors(self):
        from bs4 import BeautifulSoup

        soup = BeautifulSoup("<style>.a,.b{display:none} #c{visibility:hidden} .d{color:red}</style>", "html.parser")
        classes, ids = ab.style_hidden_selectors(soup)
        self.assertEqual((classes, ids), ({"a", "b"}, {"c"}))

    def test_send_code_button_detection(self):
        from bs4 import BeautifulSoup

        yes = BeautifulSoup('<form><button type="button">ارسال کد</button></form>', "html.parser").form
        no = BeautifulSoup("<form><button>ارسال پیام</button></form>", "html.parser").form
        self.assertTrue(ab.form_has_send_code_button(yes))
        self.assertFalse(ab.form_has_send_code_button(no))


class SafetyTests(SimpleTestCase):
    """Detection only: the analysis never produces a value for an anti-bot field."""

    def test_no_anti_bot_field_ever_gets_a_value(self):
        for name, field_name in (("honeypot_inline", "website_url"), ("captcha_math", "answer"), ("captcha_persian_label", "cc"), ("otp_form", "code")):
            with self.subTest(name=name):
                self.assertEqual(field(run(name), field_name).value, "")

    def test_the_message_text_is_never_modified(self):
        for name in ("plain_php", "cf7", "laravel_token"):
            plan = run(name)
            self.assertIn(MESSAGE, [f.value for f in plan.fields])

    def test_the_identity_is_the_only_source_of_personal_values(self):
        plan = run("plain_php", sender=SenderIdentity(name="", company="", phone="", email="", website=""))
        self.assertEqual(codes(plan), ["required_field_unfillable", "required_field_unfillable"])  # name and email are required and empty
        self.assertEqual(field(plan, "mobile").value, "")


# =============================================================================================== robustness


class RobustnessTests(SimpleTestCase):
    def test_a_hidden_wrapper_around_the_whole_form_is_not_a_honeypot(self):
        page = '<div style="display:none" id="modal"><form action="/c" method="post" class="contact"><input name="n" placeholder="نام"><input name="e" type="email"><textarea name="m"></textarea></form></div>'
        self.assertEqual(run(page).verdict, "eligible")

    def test_table_layouts_are_labelled_by_the_first_cell_of_the_row(self):
        page = (
            '<form action="/c" method="post" class="contact"><table>'
            '<tr><td>ایمیل</td><td><input name="f1"></td></tr><tr><td>نام</td><td><input name="f2"></td></tr>'
            '<tr><td>پیام</td><td><textarea name="f3"></textarea></td></tr></table></form>'
        )
        plan = run(page)
        self.assertEqual({f.name: f.source for f in plan.fields}, {"f1": "identity_email", "f2": "identity_name", "f3": "message"})

    def test_an_asterisk_in_the_label_alone_makes_an_unknown_field_required(self):
        page = '<form action="/c" method="post" class="contact"><label for="x">شماره قرارداد *</label><input id="x" name="x"><input name="e" type="email"><textarea name="m"></textarea></form>'
        plan = run(page)
        self.assertEqual(codes(plan), ["required_field_unfillable"])
        self.assertIn("شماره قرارداد", plan.reasons[0].text)

    def test_a_prefilled_message_box_receives_our_message_not_the_pages_sample_text(self):
        page = '<form action="/c" method="post" class="contact"><input name="e" type="email"><textarea name="m">پیام خود را بنویسید...</textarea></form>'
        self.assertEqual(field(run(page), "m").value, MESSAGE)

    def test_only_the_first_named_submit_button_is_sent(self):
        page = '<form action="/c" method="post" class="contact"><input name="e" type="email"><textarea name="m"></textarea><button name="send" value="1">ارسال</button><button name="preview" value="1">پیش‌نمایش</button></form>'
        self.assertEqual([n for n, _ in run(page).payload_pairs()], ["e", "m", "send"])

    def test_checked_checkboxes_with_the_same_name_are_all_sent(self):
        page = '<form action="/c" method="post" class="contact"><input name="e" type="email"><textarea name="m"></textarea><input type="checkbox" name="topics[]" value="a" checked><input type="checkbox" name="topics[]" value="b" checked><input type="checkbox" name="topics[]" value="c"></form>'
        self.assertEqual([v for n, v in run(page).payload_pairs() if n == "topics[]"], ["a", "b"])

    def test_a_multiple_select_sends_every_selected_option(self):
        page = '<form action="/c" method="post" class="contact"><input name="e" type="email"><textarea name="m"></textarea><select name="t[]" multiple><option value="x" selected>x</option><option value="y" selected>y</option><option value="z">z</option></select></form>'
        self.assertEqual([v for n, v in run(page).payload_pairs() if n == "t[]"], ["x", "y"])

    def test_a_textarea_outside_any_form_is_no_form(self):
        self.assertEqual(codes(run("<html><body><textarea name='m'></textarea></body></html>")), ["no_form_found"])

    def test_the_input_type_decides_even_when_the_name_is_cryptic(self):
        page = '<form action="/c" method="post" class="contact"><input name="q7" type="email"><input name="q8" type="tel"><textarea name="m"></textarea></form>'
        plan = run(page)
        self.assertEqual((field(plan, "q7").source, field(plan, "q8").source), ("identity_email", "identity_phone"))

    def test_autocomplete_attributes_help_to_map_fields(self):
        page = '<form action="/c" method="post" class="contact"><input name="z1" autocomplete="name"><input name="z2" autocomplete="organization"><input name="z3" autocomplete="email"><textarea name="m"></textarea></form>'
        plan = run(page)
        self.assertEqual([field(plan, n).source for n in ("z1", "z2", "z3")], ["identity_name", "identity_company", "identity_email"])

    def test_analysis_never_raises_on_broken_html(self):
        for page in ("<form", "<form><input", "<<<>>>", "<form action='/c' method='post'><textarea></form>", "\x00\x01", "<html></html>"):
            with self.subTest(page=page):
                plan = analyze_page(page, URL, sender=SENDER, message=MESSAGE, subject=SUBJECT)
                self.assertIn(plan.verdict, ("eligible", "skip"))
