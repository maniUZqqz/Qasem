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
        self.cpu = Worker.objects.create(name='server-cpu', last_seen=timezone.now(),
                                         capabilities={'gpu': None, 'cpu_count': 2, 'version': '1.1.0'})
        self.gpu_off = Worker.objects.create(name='gpu-1', last_seen=timezone.now() - timedelta(hours=1),
                                             capabilities={'gpu': ['OPTIX:RTX'], 'version': '1.1.0'})

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


# ───────────────────────── بسته‌های دارایی (۱۴۰۵/۰۷/۲۹)

import io  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import shutil  # noqa: E402
import tempfile  # noqa: E402
import zipfile  # noqa: E402
from unittest import mock  # noqa: E402

from django.core.files.uploadedfile import SimpleUploadedFile  # noqa: E402

from up3d import packs as PK  # noqa: E402
from up3d import paths as UP  # noqa: E402
from up3d.assets import registry  # noqa: E402

BVH = """HIERARCHY
ROOT Hips
{
	OFFSET 0 0 0
	CHANNELS 6 Xposition Yposition Zposition Zrotation Xrotation Yrotation
	End Site
	{
		OFFSET 0 10 0
	}
}
MOTION
Frames: 48
Frame Time: 0.041667
""" + "0 0 0 0 0 0\n" * 48


def _zip(files):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as zf:
        for name, data in files.items():
            zf.writestr(name, data if isinstance(data, (bytes, str)) else json.dumps(data, ensure_ascii=False))
    return buf.getvalue()


def _pack_files():
    return {
        'pack.json': {'id': 'shop_pack', 'name': 'بستهٔ فروشگاه'},
        'my_room/manifest.json': {'kind': 'environment', 'id': 'my_room', 'name': {'fa': 'اتاقِ من'}, 'file': 'room.glb',
                                  'license': 'CC0'},
        'my_room/room.glb': b'glTF-test',
        'animations/hello_clip/manifest.json': {'name': 'سلام', 'source': {'type': 'clip', 'file': 'hello.bvh'},
                                                'license': 'CC0'},
        'animations/hello_clip/hello.bvh': BVH,
        'people/ali/manifest.json': {'name': 'علی', 'provider': 'file', 'path': 'ali.fbx', 'rigmap': 'mixamo',
                                     'gender': 'male', 'license': 'CC0'},
        'people/ali/ali.fbx': b'fbx',
    }


class PackManifestTests(TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def _f(self, name, data=b'x'):
        with open(os.path.join(self.dir, name), 'wb') as fh:
            fh.write(data if isinstance(data, bytes) else data.encode())

    def test_environment_file_gets_defaults_and_checks_file(self):
        self._f('room.glb')
        m, err, warn = PK.validate_manifest({'id': 'room_a', 'file': 'room.glb'}, 'scene', self.dir, SV.reg())
        self.assertEqual(err, [])
        self.assertEqual(m['builder'], 'model_file')
        self.assertIn('center', m['marks'])
        self.assertTrue(m['surfaces'] and m['add_table'], 'بی‌سطح ⇐ میز و سه سطح')
        self.assertTrue(any('surfaces' in w for w in warn))
        _, err, _ = PK.validate_manifest({'id': 'room_b', 'file': 'nope.glb'}, 'environment', self.dir)
        self.assertTrue(any('در پوشه نیست' in e for e in err))
        self._f('room.txt')
        _, err, _ = PK.validate_manifest({'id': 'room_c', 'file': 'room.txt'}, 'environment', self.dir)
        self.assertTrue(any('پسوند' in e for e in err))
        _, err, _ = PK.validate_manifest({'id': 'room_d', 'file': '../room.glb'}, 'environment', self.dir)
        self.assertTrue(any('نسبی' in e for e in err))

    def test_character_rigmap_and_mpfb_defaults(self):
        self._f('a.fbx')
        m, err, _ = PK.validate_manifest({'id': 'p1x', 'provider': 'file', 'path': 'a.fbx', 'rigmap': 'mixamo', 'gender': 'male'},
                                         'person', self.dir)
        self.assertEqual(err, [])
        self.assertEqual(m['rigmap'], 'mixamo')
        _, err, _ = PK.validate_manifest({'id': 'p2x', 'path': 'a.fbx', 'rigmap': 'unknown_rig'}, 'character', self.dir)
        self.assertTrue(any('rigmap' in e for e in err))
        _, err, _ = PK.validate_manifest({'id': 'p3x', 'path': 'a.fbx', 'rigmap': {'roles': {'hips': 'Hips'}}}, 'character', self.dir)
        self.assertTrue(any('نقش' in e for e in err))
        m, err, _ = PK.validate_manifest({'id': 'p4x', 'provider': 'mpfb', 'gender': 'female',
                                          'macro': {'gender': 0.0, 'age': 0.3}}, 'character', None, SV.reg())
        self.assertEqual(err, [])
        self.assertTrue(m.get('skin'), 'پوست از شخصِ پیش‌فرضِ کتابخانه')

    def test_motion_clip_duration_from_bvh_and_channels(self):
        self._f('c.bvh', BVH)
        m, err, _ = PK.validate_manifest({'id': 'clip_a', 'source': {'type': 'clip', 'file': 'c.bvh'}}, 'animation', self.dir)
        self.assertEqual(err, [])
        self.assertAlmostEqual(m['duration']['default'], 2.0, places=2)
        self.assertEqual(m['source']['rig'], 'auto')
        self.assertEqual(m['source']['channels'], ['spine', 'neck', 'arms', 'fingers'])
        _, err, _ = PK.validate_manifest({'id': 'clip_b', 'source': {'file': 'c.bvh', 'channels': ['tail']}}, 'motion', self.dir)
        self.assertTrue(any('channels' in e for e in err))
        _, err, _ = PK.validate_manifest({'id': 'clip_c', 'source': {'type': 'procedural', 'fn': 'moonwalk'}}, 'motion', self.dir)
        self.assertTrue(err)

    def test_product_lighting_shot_and_id(self):
        _, err, _ = PK.validate_manifest({'id': 'bottle_x', 'builder': 'perfume_bottle'}, 'product', self.dir)
        self.assertTrue(any('dimensions' in e for e in err))
        m, err, _ = PK.validate_manifest({'id': 'bottle_y', 'builder': 'perfume_bottle', 'dimensions': [0.06, 0.04, 0.14]},
                                         'product', self.dir)
        self.assertEqual(err, [])
        self.assertIn('height', m['grasp'])
        _, err, _ = PK.validate_manifest({'id': 'l1', 'rig': []}, 'light', self.dir)
        self.assertTrue(err, 'نورِ بی‌نور و بی‌HDRI')
        m, err, _ = PK.validate_manifest({'id': 'l2', 'world': {'hdri': 'sunset'}}, 'lighting', self.dir)
        self.assertEqual(err, [])
        _, err, _ = PK.validate_manifest({'id': 'cam1', 'framing': {'lens': 50}}, 'camera', self.dir)
        self.assertTrue(err)
        m, err, _ = PK.validate_manifest({'id': 'cam2', 'framing': {'height': 0.5, 'lens': 85}, 'moves': ['push_in', 'fly']},
                                         'camera', self.dir)
        self.assertTrue(any('fly' in e for e in err))
        _, err, _ = PK.validate_manifest({'id': 'Bad Id!', 'framing': {'height': 1}}, 'shot', self.dir)
        self.assertTrue(any('شناسه' in e for e in err))
        _, err, _ = PK.validate_manifest({'id': 'x_ok'}, 'weather', self.dir)
        self.assertTrue(err)


class PackInstallTests(TestCase):
    def setUp(self):
        self.data = tempfile.mkdtemp()
        self.p = mock.patch.object(UP, 'DATA', self.data)
        self.p.start()
        self.zip = os.path.join(self.data, 'in.zip')
        with open(self.zip, 'wb') as fh:
            fh.write(_zip(_pack_files()))
        User = get_user_model()
        self.staff = User.objects.create_user(username='packadmin', password='x', is_staff=True)
        self.client = APIClient()
        self.client.force_authenticate(user=self.staff)

    def tearDown(self):
        self.p.stop()
        shutil.rmtree(self.data, ignore_errors=True)
        registry()

    def test_install_toggle_delete_updates_registry(self):
        rep = PK.install_zip(self.zip, reg=registry(), source_name='shop.zip')
        self.assertTrue(rep['ok'], rep)
        self.assertEqual(rep['pack'], 'shop_pack')
        self.assertEqual(sorted((a['kind'], a['id']) for a in rep['assets']),
                         [('character', 'ali'), ('environment', 'my_room'), ('motion', 'hello_clip')])
        base = os.path.join(self.data, 'asset-packs', 'shop_pack')
        self.assertTrue(os.path.isfile(os.path.join(base, 'environments', 'my_room', 'room.glb')))
        self.assertTrue(os.path.isfile(os.path.join(base, 'motions', 'hello_clip', 'manifest.json')))
        r = registry()
        self.assertIsNotNone(r.get('environment', 'my_room'))
        self.assertEqual(r.get('motion', 'hello_clip')['_pack'], 'shop_pack')
        self.assertEqual(r.get('environment', 'my_room')['builder'], 'model_file')
        self.assertEqual([p['id'] for p in PK.list_packs(r)], ['shop_pack'])
        PK.set_enabled('shop_pack', False)
        self.assertIsNone(registry().get('environment', 'my_room'), 'بستهٔ خاموش در دفتر نیست')
        PK.set_enabled('shop_pack', True)
        self.assertIsNotNone(registry().get('environment', 'my_room'))
        with self.assertRaises(PK.PackError):
            PK.install_zip(self.zip, reg=registry())          # تکراری بی «جایگزین کن»
        self.assertTrue(PK.install_zip(self.zip, reg=registry(), replace=True)['ok'])
        PK.delete('shop_pack')
        self.assertFalse(os.path.exists(base))
        self.assertIsNone(registry().get('motion', 'hello_clip'))

    def test_dry_run_and_rejections(self):
        rep = PK.install_zip(self.zip, reg=registry(), dry_run=True)
        self.assertTrue(rep['ok'] and rep['dry_run'])
        self.assertFalse(os.path.exists(os.path.join(self.data, 'asset-packs', 'shop_pack')))
        for files, why in (({'../evil/manifest.json': {'id': 'x'}}, 'خطرناک'),
                           ({'a/manifest.json': {'kind': 'shot', 'id': 'aa', 'framing': {'height': 1}}, 'a/run.py': 'print(1)'}, 'پذیرفته نیست'),
                           ({'readme.txt': 'hi'}, 'manifest'),
                           ({'a/manifest.json': '{bad json'}, 'JSON')):
            z = os.path.join(self.data, 'bad.zip')
            with open(z, 'wb') as fh:
                fh.write(_zip(files))
            with self.assertRaises(PK.PackError) as cm:
                PK.install_zip(z, reg=registry())
            self.assertTrue(any(why in e for e in cm.exception.report['errors']), (why, cm.exception.report['errors']))
        self.assertEqual([n for n in os.listdir(os.path.join(self.data, 'asset-packs')) if not n.startswith('.stamp')], [])

    def test_api_upload_list_toggle_delete(self):
        up = SimpleUploadedFile('shop.zip', _zip(_pack_files()), content_type='application/zip')
        r = self.client.post('/api/v1/up3d/asset-packs/', {'file': up}, format='multipart')
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(r.json()['pack'], 'shop_pack')
        r = self.client.get('/api/v1/up3d/asset-packs/')
        self.assertEqual([p['id'] for p in r.json()['packs']], ['shop_pack'])
        self.assertTrue(all(a['active'] for a in r.json()['packs'][0]['assets']))
        cat = self.client.get('/api/v1/up3d/catalog/').json()
        self.assertIn('my_room', [e['id'] for e in cat['environment']])
        self.assertEqual(next(e for e in cat['environment'] if e['id'] == 'my_room')['pack'], 'shop_pack')
        r = self.client.post('/api/v1/up3d/asset-packs/shop_pack/toggle/', {'enabled': False}, format='json')
        self.assertFalse(r.json()['pack']['enabled'])
        self.assertNotIn('my_room', [e['id'] for e in self.client.get('/api/v1/up3d/catalog/').json()['environment']])
        bad = SimpleUploadedFile('x.zip', _zip({'a/manifest.json': {'kind': 'product', 'id': 'pp'}}), content_type='application/zip')
        r = self.client.post('/api/v1/up3d/asset-packs/', {'file': bad}, format='multipart')
        self.assertEqual(r.status_code, 400)
        self.assertTrue(r.json()['report']['errors'])
        self.assertEqual(self.client.delete('/api/v1/up3d/asset-packs/shop_pack/').status_code, 200)
        self.assertEqual(self.client.get('/api/v1/up3d/asset-packs/').json()['packs'], [])
        anon = APIClient()
        self.assertIn(anon.get('/api/v1/up3d/asset-packs/').status_code, (401, 403))

    def test_pack_assets_ship_with_the_job(self):
        PK.install_zip(self.zip, reg=registry())
        doc = _valid_doc()
        doc['environment'] = {'id': 'my_room', 'params': {}}
        doc['actions'] = [{'actor': doc['actors'][0]['id'], 'motion': 'hello_clip', 'start': 0.2, 'duration': 2.0, 'params': {}}]
        doc['speech'] = []
        from up3d import pipeline
        jd = os.path.join(self.data, 'job')
        info = pipeline.prepare(doc, jd, 'animatic', None, log=lambda m: None, reg=registry())
        with open(info['compiled'], encoding='utf-8') as fh:
            comp = json.load(fh)
        self.assertEqual(comp['environment']['pack_rel'], 'inputs/packs/environments/my_room')
        self.assertTrue(os.path.isfile(os.path.join(jd, 'inputs', 'packs', 'environments', 'my_room', 'room.glb')))
        clip = next(a for a in comp['actions'] if a['motion'] == 'hello_clip')
        self.assertEqual(clip['pack_rel'], 'inputs/packs/motions/hello_clip')
        self.assertTrue(os.path.isfile(os.path.join(jd, 'inputs', 'packs', 'motions', 'hello_clip', 'hello.bvh')))


class GpuFirstRoutingTests(TestCase):
    def setUp(self):
        now = timezone.now()
        self.cpu = Worker.objects.create(name='server-cpu', last_seen=now, capabilities={'gpu': None, 'version': '1.1.0'})
        self.gpu = Worker.objects.create(name='DESKTOP-GPU', last_seen=now,
                                         capabilities={'gpu': ['OPTIX:RTX 3060'], 'version': '1.1.0', 'mpfb': True})

    def test_legacy_or_mpfb_less_workers_get_no_jobs(self):
        self.gpu.capabilities = {'gpu': ['OPTIX:RTX 3060'], 'version': '1.0.0'}
        self.gpu.save()
        j = self._job('preview')
        self.assertFalse(SV.capable(self.gpu))
        self.assertIsNone(SV.claim(self.gpu), 'کارگرِ قدیمی کار نمی‌گیرد')
        self.assertEqual(SV.claim(self.cpu)['id'], j.pk, 'GPU ِ قدیمی «GPU ِ آنلاین» حساب نمی‌شود')
        self.gpu.capabilities = {'gpu': ['OPTIX:RTX 3060'], 'version': '1.1.0', 'mpfb': False}
        self.gpu.save()
        Job.objects.all().delete()
        project = Project.objects.create(title='mpfb', brief={})
        doc = _valid_doc()
        v = SV.new_version(project, doc, 'test', 'x')
        j2 = Job.objects.create(project=project, version=v, kind='render', profile='preview', owner='worker', state='SCENE_BUILDING')
        self.assertTrue(SV.needs_mpfb(j2))
        self.assertIsNone(SV.claim(self.gpu), 'بی‌دادهٔ MPFB ⇐ کارِ با مجریِ MPFB نه')

    def _job(self, profile, **kw):
        return Job.objects.create(kind='render', profile=profile, owner='worker', state='SCENE_BUILDING', params=kw)

    def test_cpu_leaves_jobs_for_an_idle_gpu(self):
        j = self._job('preview')
        self.assertIsNone(SV.claim(self.cpu), 'GPU ِ بیکار آنلاین است')
        self.assertEqual(SV.claim(self.gpu)['id'], j.pk)
        self.gpu.last_seen = timezone.now() - timedelta(hours=1)
        self.gpu.save()
        j2 = self._job('animatic')
        self.assertEqual(SV.claim(self.cpu)['id'], j2.pk, 'GPU آفلاین ⇐ سرور خودش می‌سازد')

    def test_busy_gpu_cpu_takes_light_jobs_first_and_not_gpu_class(self):
        busy = self._job('high')
        SV.claim(self.gpu)
        self.assertEqual(Job.objects.get(pk=busy.pk).worker, self.gpu)
        heavy = self._job('high', allow_cpu=True)
        light = self._job('animatic')
        got = SV.claim(self.cpu)
        self.assertEqual(got['id'], light.pk, 'اول کارِ سبک')
        Job.objects.filter(pk=light.pk).update(state='COMPLETED', owner='panel')
        self.assertIsNone(SV.claim(self.cpu), 'کارِ GPU-کلاس منتظرِ GPU ِ آنلاین می‌ماند')
        self.assertIsNone(Job.objects.get(pk=heavy.pk).worker)

    def test_long_cpu_render_is_handed_to_gpu_or_yields(self):
        self.gpu.last_seen = timezone.now() - timedelta(hours=1)
        self.gpu.save()
        heavy = self._job('high', allow_cpu=True)
        self.assertEqual(SV.claim(self.cpu)['id'], heavy.pk)
        heavy.refresh_from_db()
        self.assertEqual(SV.worker_progress(heavy, {'state': 'RENDERING'}, self.cpu), {'cancel': False})
        light = self._job('preview')
        heavy.refresh_from_db()
        r = SV.worker_progress(heavy, {'state': 'RENDERING'}, self.cpu)
        self.assertEqual(r['release'], 'yield')
        heavy.refresh_from_db()
        self.assertIsNone(heavy.worker)
        self.assertEqual(SV.claim(self.cpu)['id'], light.pk, 'کارِ کوتاه اول')
        Job.objects.filter(pk=light.pk).update(state='COMPLETED', owner='panel')
        self.assertEqual(SV.claim(self.cpu)['id'], heavy.pk, 'بعد همان کارِ بلند ادامه می‌یابد')
        self.gpu.last_seen = timezone.now()
        self.gpu.save()
        heavy.refresh_from_db()
        r = SV.worker_progress(heavy, {'state': 'RENDERING'}, self.cpu)
        self.assertEqual(r, {'cancel': True, 'release': 'handoff'})
        self.assertEqual(SV.claim(self.gpu)['id'], heavy.pk)

    def test_restarted_worker_gets_its_unfinished_job_back(self):
        j = self._job('animatic')
        self.gpu.last_seen = timezone.now() - timedelta(hours=1)
        self.gpu.save()
        self.assertEqual(SV.claim(self.cpu)['id'], j.pk)
        self._job('animatic')
        self.assertEqual(SV.claim(self.cpu)['id'], j.pk, 'فرایندِ تازهٔ همان کارگر اول کارِ نیمه‌تمامِ خودش را می‌گیرد')
        Job.objects.filter(pk=j.pk).update(state='QUALITY_CHECK', owner='panel')
        self.assertNotEqual(SV.claim(self.cpu)['id'], j.pk)

    def test_node_is_asked_to_start_its_3d_worker_while_jobs_wait(self):
        from apps.compute.models import ComputeNode
        node = ComputeNode.objects.create(name='DESKTOP-GPU', capabilities={'gpu': 'RTX 3060', 'startable': {'worker3d': True}})
        self.assertFalse(SV.wants_gpu_worker(node))
        self._job('high')
        self.assertTrue(SV.wants_gpu_worker(node))
        c = APIClient()
        r = c.post('/api/v1/compute/heartbeat/', {'gpu': 'RTX 3060', 'startable': {'worker3d': True}}, format='json',
                   HTTP_AUTHORIZATION='Node %s' % node.token)
        self.assertEqual(r.status_code, 200, r.content)
        self.assertTrue(r.json()['desired'].get('worker3d'))
        node.desired = {'worker3d': False}
        node.save()
        r = c.post('/api/v1/compute/heartbeat/', {'gpu': 'RTX 3060', 'startable': {'worker3d': True}}, format='json',
                   HTTP_AUTHORIZATION='Node %s' % node.token)
        self.assertFalse(r.json()['desired']['worker3d'], 'تصمیمِ صریحِ پنل دست نمی‌خورد')
        nodes = SV.gpu_nodes()
        self.assertEqual(nodes[0]['name'], 'DESKTOP-GPU')
        self.assertTrue(nodes[0]['startable'])

    def test_package_contains_nested_pack_inputs(self):
        data = tempfile.mkdtemp()
        try:
            with mock.patch.object(SV, 'DATA', data):
                j = self._job('preview')
                d = SV.job_dir(j)
                os.makedirs(os.path.join(d, 'inputs', 'packs', 'motions', 'm1'))
                for rel in ('compiled.json', 'inputs/label-p1.png', 'inputs/packs/motions/m1/a.bvh'):
                    with open(os.path.join(d, *rel.split('/')), 'w') as fh:
                        fh.write('x')
                with zipfile.ZipFile(SV.package(j)) as zf:
                    names = set(zf.namelist())
            self.assertIn('inputs/packs/motions/m1/a.bvh', names)
            self.assertIn('inputs/label-p1.png', names)
        finally:
            shutil.rmtree(data, ignore_errors=True)
