"""Caption translation (round 5): batching and order, validation, the job and its Persian failures. The model is always faked — no real credit."""
import json
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import SimpleTestCase, TestCase

from apps.jobs.models import Job
from apps.stores.models import Store
from services.editing import translate


def fake_ask(store, job, system, prompt, n):
    """A deterministic «model»: upper-cases every numbered line."""
    lines = [ln.split(". ", 1)[1] for ln in prompt.splitlines()[1:]]
    assert len(lines) == n
    return {"items": [f"EN:{ln}" for ln in lines]}


class CleanTests(SimpleTestCase):
    def test_clean_items_validates_and_drops_empty_lines(self):
        out = translate.clean_items([{"id": "a", "text": " سلام "}, {"id": "b", "text": "  "}, {"id": "c", "text": "x" * 900}])
        self.assertEqual([i["id"] for i in out], ["a", "c"])
        self.assertEqual(out[0]["text"], "سلام")
        self.assertEqual(len(out[1]["text"]), translate.MAX_CHARS)

    def test_clean_items_refuses_nonsense_in_persian(self):
        for bad in (None, [], "x", [1], [{"text": "x"}], [{"id": "a", "text": ""}]):
            with self.assertRaises(ValueError):
                translate.clean_items(bad)
        with self.assertRaises(ValueError) as cm:
            translate.clean_items([{"id": str(i), "text": "x"} for i in range(translate.MAX_ITEMS + 1)])
        self.assertIn("حداکثر", str(cm.exception))


class TranslateTests(SimpleTestCase):
    def test_order_ids_and_batches(self):
        items = [{"id": f"c{i}", "text": f"خط {i}"} for i in range(60)]
        calls, ticks = [], []

        def ask(store, job, system, prompt, n):
            calls.append(n)
            return fake_ask(store, job, system, prompt, n)
        out = translate.translate(items, "en", ask=ask, progress=lambda d, t: ticks.append((d, t)))
        self.assertEqual(calls, [25, 25, 10])
        self.assertEqual(ticks, [(1, 3), (2, 3), (3, 3)])
        self.assertEqual([o["id"] for o in out], [i["id"] for i in items])
        self.assertEqual(out[7]["text"], "EN:خط 7")

    def test_the_prompt_names_the_language_and_the_exact_count(self):
        seen = {}

        def ask(store, job, system, prompt, n):
            seen.update(system=system, prompt=prompt, n=n)
            return fake_ask(store, job, system, prompt, n)
        translate.translate([{"id": "a", "text": "سلام"}, {"id": "b", "text": "خداحافظ"}], "tr", ask=ask)
        self.assertIn("Turkish", seen["system"])
        self.assertIn("exactly 2 strings", seen["system"])
        self.assertIn("1. سلام", seen["prompt"])

    def test_a_wrong_count_or_non_text_answer_is_an_error_not_a_silent_shift(self):
        for answer in ({"items": ["only one"]}, {"items": [1, 2]}, {"nope": []}, None, ["x", "y"]):
            with self.assertRaises(translate.TranslateError):
                translate.translate([{"id": "a", "text": "الف"}, {"id": "b", "text": "ب"}], "en", ask=lambda *a, _r=answer: _r)

    def test_multi_line_captions_keep_their_line_break(self):
        out = translate.translate([{"id": "a", "text": "خط اول\nخط دوم"}], "en", ask=lambda s, j, sy, p, n: {"items": ["line one / line two"]})
        self.assertEqual(out[0]["text"], "line one\nline two")

    def test_unknown_language_is_refused(self):
        with self.assertRaises(ValueError):
            translate.translate([{"id": "a", "text": "x"}], "xx", ask=fake_ask)

    def test_every_listed_language_has_both_names(self):
        for key, (fa_name, en_name) in translate.LANGS.items():
            self.assertTrue(fa_name and en_name and len(key) == 2, key)


def run_inline(job, task, *args, **kwargs):
    task(*args, **kwargs)
    return None


class TranslateApiTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user("tr-owner", password="x")
        self.store = Store.objects.create(owner=self.owner, name="فروشگاه ترجمه")
        self.client.force_login(self.owner)
        self.url = f"/api/v1/stores/{self.store.pk}/editor/captions/translate/"

    def post(self, body):
        with patch("apps.content.views_editor_pro.dispatch_job", side_effect=run_inline):
            return self.client.post(self.url, json.dumps(body), content_type="application/json")

    def test_a_job_translates_the_lines_and_keeps_ids(self):
        with patch.object(translate, "_ask", fake_ask):
            r = self.post({"lang": "en", "clips": [{"id": "c1", "text": "سلام"}, {"id": "c2", "text": "دنیا"}]})
        self.assertEqual(r.status_code, 202, r.content)
        job = Job.objects.get(pk=r.json()["job_id"])
        self.assertEqual(job.state, Job.State.COMPLETED, job.error)
        self.assertEqual(job.result["lang"], "en")
        self.assertEqual(job.result["items"], [{"id": "c1", "text": "EN:سلام"}, {"id": "c2", "text": "EN:دنیا"}])

    def test_bad_language_and_bad_clips_are_400_with_a_reason(self):
        self.assertEqual(self.post({"lang": "xx", "clips": [{"id": "a", "text": "x"}]}).status_code, 400)
        r = self.post({"lang": "en", "clips": []})
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.json()["error"]["code"], "bad_clips")

    def test_when_no_ai_is_available_the_job_fails_with_the_reason_in_persian(self):
        def boom(*a, **k):
            raise RuntimeError("Metis 402 insufficient credit")
        with patch.object(translate, "_ask", boom):
            r = self.post({"lang": "en", "clips": [{"id": "c1", "text": "سلام"}]})
        job = Job.objects.get(pk=r.json()["job_id"])
        self.assertEqual(job.state, Job.State.FAILED)
        self.assertIn("اعتبار", job.error)

    def test_a_bad_model_answer_fails_the_job_with_a_clear_sentence(self):
        with patch.object(translate, "_ask", lambda *a, **k: {"items": []}):
            r = self.post({"lang": "en", "clips": [{"id": "c1", "text": "سلام"}]})
        job = Job.objects.get(pk=r.json()["job_id"])
        self.assertEqual(job.state, Job.State.FAILED)
        self.assertIn("هم‌تعداد", job.error)

    def test_other_shops_and_anonymous_users_cannot_use_it(self):
        other = User.objects.create_user("tr-other", password="x")
        self.client.force_login(other)
        with patch.object(translate, "_ask", fake_ask):
            r = self.post({"lang": "en", "clips": [{"id": "c1", "text": "سلام"}]})
        self.assertIn(r.status_code, (403, 404))
        self.client.logout()
        self.assertIn(self.post({"lang": "en", "clips": [{"id": "c1", "text": "x"}]}).status_code, (401, 403))
