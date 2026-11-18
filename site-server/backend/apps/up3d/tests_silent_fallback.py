"""رندرِ خودکارِ سه‌بعدی (برنامهٔ بازاریابی): اگر سرویسِ صدای آنلاین جواب ندهد (مثلاً اعتبارِ متیس تمام شده، ۴۰۲) رندر بی‌صدا ادامه می‌دهد؛
بدونِ پرچمِ «silent_fallback» رفتارِ قبلی (شکستن با پیامِ خطا) دست‌نخورده می‌ماند."""
from unittest import mock

from django.contrib.auth.models import User
from django.test import TestCase
from up3d.tts import TTSError

from . import services as U


class SilentFallbackTests(TestCase):
    def _job(self, params):
        user = User.objects.create_user("u3d-fallback", password="x")
        project, plan_job = U.create_project(user, {"product_name": "نمونه", "brand": "نمونه"}, mode="template", template="showcase", title="نمونه")
        U.process_plan(plan_job)
        return U.request_job(project, "render", "preview", params)

    @staticmethod
    def _info():
        return {"frames": 12, "frame_step": 1, "resolution": (640, 360)}

    def test_a_voice_service_error_without_the_flag_still_fails_as_before(self):
        job = self._job({})
        with mock.patch.object(U.pipeline, "prepare", side_effect=TTSError("Error code: 402 - Payment Required")):
            with self.assertRaises(TTSError):
                U.process_prepare(job)

    def test_with_the_flag_the_render_continues_silently_and_says_so(self):
        job = self._job({"silent_fallback": True})
        calls = []

        def prepare(doc, job_dir, profile, tts_settings=None, **kw):
            calls.append(tts_settings)
            if len(calls) == 1:
                raise TTSError("Error code: 402 - Payment Required")
            return self._info()

        with mock.patch.object(U.pipeline, "prepare", side_effect=prepare):
            U.process_prepare(job)
        job.refresh_from_db()
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[1], {"api_key": ""})                 # بی‌صدا: «provider» ِ openai به silent برمی‌گردد
        self.assertIn("بی‌صدا", job.log)
        self.assertIn("402", job.report["silent_fallback"])
        self.assertEqual(job.owner, "worker")                       # آمادهٔ برداشتنِ کارگر؛ نشکسته
        self.assertNotEqual(job.state, "FAILED")

    def test_another_kind_of_error_is_never_swallowed_by_the_flag(self):
        job = self._job({"silent_fallback": True})
        with mock.patch.object(U.pipeline, "prepare", side_effect=RuntimeError("blender missing")):
            with self.assertRaises(RuntimeError):
                U.process_prepare(job)
