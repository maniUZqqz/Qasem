"""ویدیوی سه‌بعدی — چیزهایی که پنل به آن‌ها تکیه می‌کند و با دست بدِ آزمودن‌اند:
تنظیمِ دستیِ کیفیت (بازه و ضریبِ تخمین)، «چرا کار منتظر است» و اجازهٔ CPU، شمارشِ فریم با گامِ دستی."""
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from up3d import compiler, templates

from . import services as SV
from .models import Job, Project, SceneVersion, Worker


def _valid_doc():
    return templates.build('quick', {'product_name': 'آزمون', 'benefits': ['خوب']}, SV.reg())


class QualityOverrideTests(TestCase):
    def test_clean_quality_keeps_only_known_keys_in_range(self):
        q = compiler.clean_quality({'resolution': '1280', 'samples': 32, 'frame_step': '2', 'denoise': 'false',
                                    'motion_blur': True, 'bogus': 1, 'bounces': {'total': 99}})
        self.assertEqual(q, {'resolution': 1280, 'samples': 32, 'frame_step': 2, 'denoise': False, 'motion_blur': True})
        self.assertEqual(compiler.clean_quality({'resolution': '', 'samples': None}), {})
        self.assertEqual(compiler.clean_quality(None), {})

    def test_clean_quality_rejects_out_of_range(self):
        with self.assertRaises(ValueError):
            compiler.clean_quality({'resolution': 100})
        with self.assertRaises(ValueError):
            compiler.clean_quality({'frame_step': 9})
        with self.assertRaises(ValueError):
            compiler.clean_quality({'samples': 'abc'})

    def test_overrides_reach_compiled_profile_and_resolution(self):
        reg = SV.reg()
        doc = _valid_doc()
        base = compiler.compile_scene(doc, reg, 'preview')
        over = compiler.compile_scene(doc, reg, 'preview', profile_overrides={'resolution': 1280, 'samples': 40,
                                                                              'frame_step': 1, 'denoise': False})
        self.assertEqual(base['profile']['id'], over['profile']['id'])
        self.assertEqual(max(over['resolution']), 1280)
        self.assertEqual(over['profile']['samples'], 40)
        self.assertEqual(over['profile']['frame_step'], 1)
        self.assertFalse(over['profile']['denoise'])
        self.assertEqual(over['profile']['folder'], base['profile']['folder'], 'پوشهٔ دارایی باید بماند')

    def test_quality_scale_and_frames(self):
        prof = SV.reg().get('render_profile', 'preview')   # 640px, 14 spp, step 2
        self.assertAlmostEqual(compiler.quality_scale(prof, None), 1.0)
        self.assertAlmostEqual(compiler.quality_scale(prof, {'resolution': 1280}), 4.0)
        self.assertAlmostEqual(compiler.quality_scale(prof, {'samples': 28}), 2.0)
        doc = _valid_doc()
        total = int(round(doc['output']['duration'] * doc['output']['fps']))
        self.assertEqual(SV.frames_of(doc, 'preview', {'frame_step': 1}), total)
        self.assertEqual(SV.frames_of(doc, 'preview'), total // 2, 'پیش‌نمایش با گامِ ۲ رندر می‌شود')
        self.assertEqual(SV.frames_of(doc, 'preview', {'frame_step': 4}), total // 4)


class WaitingForWorkerTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.staff = User.objects.create_user(username='staff3d', password='x', is_staff=True)
        self.client = APIClient()
        self.client.force_authenticate(user=self.staff)
        self.project = Project.objects.create(title='پروژهٔ آزمون', brief={}, owner=self.staff)
        self.version = SV.new_version(self.project, _valid_doc(), 'test', 'آزمون')
        self.assertTrue(self.version.valid)
        self.cpu = Worker.objects.create(name='server-cpu', last_seen=timezone.now(), capabilities={'gpu': None, 'cpu_count': 2})
        self.gpu_off = Worker.objects.create(name='gpu-1', last_seen=timezone.now() - timedelta(hours=1),
                                             capabilities={'gpu': ['OPTIX:RTX']})

    def test_request_job_records_quality_and_frame_count(self):
        base = SV.request_job(self.project, 'render', 'preview')
        tuned = SV.request_job(self.project, 'render', 'preview', {'quality': {'frame_step': '1', 'resolution': 960}})
        self.assertEqual(tuned.params['quality'], {'frame_step': 1, 'resolution': 960})
        self.assertGreater(tuned.frames_total, base.frames_total)
        self.assertGreater(tuned.estimate_seconds, base.estimate_seconds)
        with self.assertRaises(ValueError):
            SV.request_job(self.project, 'render', 'preview', {'quality': {'resolution': 10}})

    def test_api_render_accepts_quality_and_rejects_bad(self):
        r = self.client.post('/api/v1/up3d/video-projects/%d/preview/' % self.project.pk,
                             {'profile': 'preview', 'quality': {'samples': 8, 'frame_step': 2}}, format='json')
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(r.json()['quality'], {'samples': 8, 'frame_step': 2})
        r = self.client.post('/api/v1/up3d/video-projects/%d/preview/' % self.project.pk,
                             {'profile': 'preview', 'quality': {'samples': 99999}}, format='json')
        self.assertEqual(r.status_code, 400)
        self.assertIn('samples', r.json()['error'])

    def test_waiting_info_explains_gpu_need_and_allow_cpu_unblocks(self):
        job = SV.request_job(self.project, 'render', 'high')
        job.owner = 'worker'
        job.state = 'SCENE_BUILDING'
        job.save()
        w = SV.waiting_info(job)
        self.assertTrue(w['needs_gpu'])
        self.assertFalse(w['allow_cpu'])
        self.assertEqual(w['online'], ['server-cpu'])
        self.assertEqual(w['eligible'], [], 'کارگرِ CPU نباید high را بگیرد')
        self.assertIsNone(SV.claim(self.cpu))
        r = self.client.get('/api/v1/up3d/jobs/%d/' % job.pk)
        self.assertEqual(r.json()['waiting']['eligible'], [])
        r = self.client.post('/api/v1/up3d/jobs/%d/allow-cpu/' % job.pk)
        self.assertEqual(r.status_code, 200, r.content)
        self.assertTrue(r.json()['waiting']['allow_cpu'])
        self.assertEqual(r.json()['waiting']['eligible'], ['server-cpu'])
        claimed = SV.claim(self.cpu)
        self.assertIsNotNone(claimed)
        self.assertEqual(claimed['id'], job.pk)
        r = self.client.post('/api/v1/up3d/jobs/%d/allow-cpu/' % job.pk)
        self.assertEqual(r.status_code, 400, 'کارِ گرفته‌شده دیگر تغییر نمی‌کند')

    def test_waiting_is_null_when_worker_took_the_job(self):
        job = SV.request_job(self.project, 'render', 'animatic')
        job.owner = 'worker'
        job.state = 'SCENE_BUILDING'
        job.save()
        self.assertEqual(SV.waiting_info(job)['eligible'], ['server-cpu'])
        self.assertEqual(SV.claim(self.cpu)['id'], job.pk)
        r = self.client.get('/api/v1/up3d/jobs/%d/' % job.pk)
        self.assertIsNone(r.json()['waiting'])
        self.assertEqual(r.json()['worker'], 'server-cpu')

    def test_estimate_endpoint_scales_with_quality(self):
        base = self.client.get('/api/v1/up3d/estimate/', {'profile': 'preview', 'project': self.project.pk}).json()
        tuned = self.client.get('/api/v1/up3d/estimate/', {'profile': 'preview', 'project': self.project.pk,
                                                             'resolution': 1280}).json()
        self.assertTrue(base['available'])
        self.assertEqual(base['worker'], 'server-cpu')
        self.assertGreater(tuned['seconds'], base['seconds'] * 3)
        bad = self.client.get('/api/v1/up3d/estimate/', {'profile': 'preview', 'resolution': 5})
        self.assertEqual(bad.status_code, 400)
