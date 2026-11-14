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


# ───────────────────────── ویرایشگرِ آزادِ صحنه (پنل ⇐ «ویرایشگرِ آزاد»)

def _editor_doc():
    """سندی با همهٔ قابلیت‌های ویرایشگر: جای آزاد، کلید، شیء، نور، دوربینِ آزاد."""
    doc = _valid_doc()
    doc['actors'][0]['transform'] = {'pos': [0.4, 0.2, 0], 'rot': [0, 0, 20], 'scale': [1, 1, 1]}
    doc['actors'][0]['keys'] = [{'t': 0, 'pos': [0.4, 0.2, 0], 'rot': [0, 0, 20]},
                                {'t': 2, 'pos': [0.9, 0.2, 0], 'rot': [0, 0, 0], 'ease': 'linear'}]
    doc['products'][0]['transform'] = {'pos': [0.1, -0.5, 0.86], 'rot': [0, 0, 30], 'scale': [1.5, 1.5, 1.5]}
    doc['props'] = [{'asset': 'box_package', 'transform': {'pos': [-0.6, -0.4, 0], 'rot': [0, 0, 0], 'scale': [3, 3, 3]},
                     'keys': [{'t': 0, 'pos': [-0.6, -0.4, 0]}, {'t': 1, 'pos': [-0.6, -0.4, 0.5]}]}]
    doc['lights'] = [{'type': 'spot', 'color': '#ffd0a0', 'power': 400, 'transform': {'pos': [1, -2, 2.5], 'rot': [50, 0, 20]}}]
    doc['cameras'] = [{'id': 'cam1', 'lens': 40, 'keys': [
        {'t': 0, 'pos': [0, -3, 1.6], 'target': [0, 0, 1.2], 'lens': 40},
        {'t': 1.5, 'pos': [1, -2.5, 1.4], 'target': [0, 0, 1.1], 'ease': 'auto'},
        {'t': 3, 'pos': [1.5, -1.5, 1.5], 'target': [0.1, -0.4, 0.95]}]}]
    doc['shots'] = [{'camera': 'cam1', 'start': 0, 'duration': doc['output']['duration']}]
    return doc


class SceneEditorTests(TestCase):
    def test_editor_doc_is_valid_and_compiles_free_placement(self):
        from up3d import keys as K
        from up3d.validate import validate
        r = SV.reg()
        doc = _editor_doc()
        rep = validate(doc, r)
        self.assertTrue(rep.ok, [i['message'] for i in rep.errors])
        env = r.get('environment', doc['environment']['id'])
        before = dict(env['surfaces'])
        comp = compiler.compile_scene(doc, r, 'animatic')
        self.assertEqual(dict(env['surfaces']), before, 'سطح‌های دفترِ دارایی نباید عوض شود')
        a = comp['actors'][0]
        self.assertEqual(a['mark']['pos'], [0.4, 0.2, 0.0])
        self.assertEqual(a['mark']['facing'], 20.0)
        self.assertEqual([k['f'] for k in a['keys']], [1.0, 1 + 2 * comp['fps']])
        p = comp['products'][0]
        self.assertEqual(p['surface_id'], '@' + doc['products'][0]['id'])
        self.assertEqual(p['surface']['rot'], [0.0, 0.0, 30.0])
        self.assertEqual(p['scale'], [1.5, 1.5, 1.5])
        self.assertEqual(len(comp['props']), 1)
        self.assertEqual(comp['props'][0]['builder'], 'box_package')
        self.assertEqual(comp['lights'][0]['type'], 'spot')
        sh = comp['shots'][0]
        self.assertTrue(sh['free'])
        self.assertEqual(sh['f1'], comp['frame_end'])
        self.assertEqual(len(sh['keys']), 3)
        # ریاضیِ مشترکِ کلید: دو سرِ بازه همان کلیدها، «پله‌ای» تا کلیدِ بعد ثابت
        self.assertEqual(K.sample(doc['cameras'][0]['keys'], 0, 'pos'), [0, -3, 1.6])
        mid = K.sample(doc['actors'][0]['keys'], 1.0, 'pos')
        self.assertAlmostEqual(mid[0], 0.65, 3)
        self.assertEqual(K.sample([{'t': 0, 'pos': [0, 0, 0], 'ease': 'step'}, {'t': 1, 'pos': [1, 1, 1]}], 0.9, 'pos'), [0, 0, 0])
        self.assertAlmostEqual(K.ease('smooth', 0.5), 0.5)

    def test_free_shot_without_keys_is_error_and_repair_falls_back(self):
        from up3d.validate import repair, validate
        r = SV.reg()
        doc = _editor_doc()
        doc['cameras'][0]['keys'] = []
        rep = validate(doc, r)
        self.assertIn('E_CAMERA_KEYS', [i['code'] for i in rep.errors])
        fixed, changes, rep2 = repair(doc, r)
        self.assertTrue(rep2.ok, [i['message'] for i in rep2.errors])
        self.assertFalse(fixed['shots'][0].get('camera'))
        self.assertTrue(fixed['shots'][0].get('shot'))

    def test_free_actor_skips_mark_checks_and_survives_repair(self):
        from up3d.validate import repair
        r = SV.reg()
        doc = _editor_doc()
        doc['actors'][0]['mark'] = 'nowhere'
        fixed, changes, rep = repair(doc, r)
        self.assertTrue(rep.ok)
        self.assertEqual(fixed['actors'][0]['transform']['pos'], [0.4, 0.2, 0.0])
        self.assertEqual(fixed['props'][0]['id'], 'prop1')
        comp = compiler.compile_scene(fixed, r, 'animatic')
        self.assertEqual(comp['actors'][0]['mark']['pos'], [0.4, 0.2, 0.0])

    def test_editor_jobs_only_go_to_new_workers(self):
        now = timezone.now()
        old = Worker.objects.create(name='old-cpu', last_seen=now, capabilities={'gpu': None, 'version': '1.1.0'})
        new = Worker.objects.create(name='new-cpu', last_seen=now, capabilities={'gpu': None, 'version': '1.2.0'})
        project = Project.objects.create(title='editor', brief={})
        v = SV.new_version(project, _editor_doc(), 'scene-editor', 'x')
        self.assertTrue(v.valid, v.report)
        j = Job.objects.create(project=project, version=v, kind='render', profile='animatic', owner='worker',
                               state='SCENE_BUILDING')
        self.assertTrue(SV.needs_editor(j))
        self.assertIsNone(SV.claim(old), 'کارگرِ ۱.۱ فیلدهای ویرایشگر را نمی‌فهمد')
        self.assertEqual(SV.claim(new)['id'], j.pk)

    def test_asset_preview_queue_and_cache(self):
        import os
        st = SV.preview_status('product', 'can_drink')
        if st['state'] == 'ready':
            os.remove(SV.preview_path('product', 'can_drink', SV.preview_key(SV.reg().get('product', 'can_drink'))))
        self.assertEqual(SV.preview_status('product', 'can_drink')['state'], 'none')
        out = SV.request_preview('product', 'can_drink')
        self.assertEqual(out['state'], 'building')
        self.assertEqual(SV.request_preview('product', 'can_drink')['job'], out['job'], 'یک کار برای هر دارایی')
        j = Job.objects.get(pk=out['job'])
        self.assertEqual(j.params['format'], 'preview_glb')
        self.assertEqual(SV.engine_mode(j), ('export', ['--format', 'preview_glb']))
        # کارگر GLB را فرستاد ⇐ کش
        d = SV.job_dir(j)
        with open(os.path.join(d, 'scene.glb'), 'wb') as fh:
            fh.write(b'glTF-test')
        j.files = {'scene.glb': os.path.join(j.dir_rel(), 'scene.glb')}
        j.state = 'QUALITY_CHECK'
        j.save()
        SV.process_finish(j)
        st = SV.preview_status('product', 'can_drink')
        self.assertEqual(st['state'], 'ready')
        self.assertEqual(SV.preview_file('product', 'can_drink'),
                         SV.preview_path('product', 'can_drink', SV.preview_key(SV.reg().get('product', 'can_drink'))))
        os.remove(SV.preview_file('product', 'can_drink'))
        import shutil
        shutil.rmtree(d, ignore_errors=True)
        self.assertEqual(SV.preview_status('character', 'nope')['state'], 'unsupported')
# ───────────────────────── موتورِ ۱٫۳ (بازبینی‌شده روی سرور با Blender واقعی در /root/t3d؛ این‌جا فقط منطقِ بی‌Blender)

import json as _json
import os as _os
import tempfile as _tempfile
import zipfile as _zipfile

NEW_LIGHTING = ('studio_softbox', 'three_point', 'hdri_studio', 'hdri_loft', 'hdri_sunset', 'hdri_daylight', 'golden_hour', 'neon_night')
NEW_ENVS = ('stage', 'neon_stage', 'open_air')
NEW_PRODUCTS = ('phone_showcase', 'text_3d', 'logo_3d', 'material_object')
NEW_SHOTS = ('stage_hero', 'stage_low', 'stage_wide', 'stage_macro', 'phone_front', 'phone_angle', 'logo_front')
NEW_MOVES = ('turntable', 'orbit_full', 'arc_left', 'arc_right', 'reveal_pull', 'hero_orbit', 'dolly_zoom', 'drift')
AD_TEMPLATES = ('turntable', 'hero_reveal', 'app_showcase', 'logo_reveal', 'neon_launch', 'golden_hour', 'material_trio')
CHAGHER = {'product_name': 'چغر', 'brand': 'چغر', 'tagline': 'با چغر چغر تر شو', 'cta': 'همین حالا امتحان کنید',
           'benefits': ['پیش‌نویسِ برنامهٔ ورزشی و غذایی', 'دستورالعملِ شخصیِ مربی', 'خروجیِ PDF برندشده و قابل‌چاپ'],
           'brand_color': '#126F85', 'brand_color_2': '#163F75'}


class Engine13AssetTests(TestCase):
    def test_every_new_asset_is_in_the_registry_without_problems(self):
        r = SV.reg()
        self.assertEqual(r.problems, [])
        for kind, ids in (('lighting', NEW_LIGHTING), ('environment', NEW_ENVS), ('product', NEW_PRODUCTS), ('shot', NEW_SHOTS)):
            for i in ids:
                a = r.get(kind, i)
                self.assertIsNotNone(a, '%s/%s' % (kind, i))
                self.assertEqual(a.get('min_engine'), '1.3.0', '%s/%s must gate old workers' % (kind, i))
                self.assertTrue(a.label(), i)

    def test_hdri_environments_are_mirrored_cc0_files(self):
        root = _os.path.join(str(SV.settings.UP3D_ROOT), 'assets', 'hdri')
        names = {SV.reg().get('lighting', i)['world'].get('hdri') for i in NEW_LIGHTING}
        for n in {x for x in names if x}:
            self.assertTrue(_os.path.isfile(_os.path.join(root, n + '.hdr')), 'missing HDRI file for ' + n)
        sources = open(_os.path.join(root, 'SOURCES.md'), encoding='utf-8').read()
        self.assertIn('CC0', sources)
        for n in ('studio_small_09', 'photo_studio_loft_hall', 'venice_sunset', 'kloofendal_48d_partly_cloudy_puresky'):
            self.assertIn(n, sources)

    def test_all_new_camera_moves_are_offered_by_the_shots_that_use_them(self):
        r = SV.reg()
        for sid in ('stage_hero', 'stage_low', 'stage_wide', 'stage_macro', 'product_hero', 'product_macro'):
            for mv in NEW_MOVES:
                self.assertIn(mv, r.get('shot', sid)['moves'], '%s lacks %s' % (sid, mv))
        for sid in ('medium', 'close_up', 'wide'):
            self.assertIn('arc_left', r.get('shot', sid)['moves'])

    def test_every_ad_template_builds_a_valid_scene_that_needs_the_new_engine(self):
        from up3d.validate import needs_v13, validate
        from up3d.templates import TEMPLATES
        r = SV.reg()
        for t in AD_TEMPLATES:
            self.assertEqual(TEMPLATES[t]['group'], 'ad')
            doc = templates.build(t, dict(CHAGHER), r)
            rep = validate(doc, r)
            self.assertTrue(rep.ok, '%s: %s' % (t, [i['message'] for i in rep.errors]))
            self.assertEqual([i for i in rep.issues if i['code'] == 'W_MOVE'], [], t)
            self.assertFalse(doc['actors'], t)
            self.assertTrue(needs_v13(doc, r), t)
            self.assertGreaterEqual(doc['output']['duration'], 8.0)
            comp = compiler.compile_scene(doc, r, 'preview')
            self.assertEqual(comp['render'], doc['render'])
            self.assertIn(doc['render']['look'], ('agx', 'agx_soft', 'agx_contrast', 'agx_punchy', 'agx_golden', 'agx_bw'))

    def test_presenter_templates_are_untouched_and_still_valid_for_old_workers(self):
        from up3d.validate import needs_v13
        r = SV.reg()
        for t in ('showcase', 'quick', 'testimonial', 'ritual', 'product_only'):
            doc = templates.build(t, {'product_name': 'x', 'benefits': ['y']}, r)
            self.assertFalse(needs_v13(doc, r), t)
            self.assertEqual(templates.TEMPLATES[t]['group'], 'presenter')

    def test_template_listing_carries_group_hint_and_inputs(self):
        c = APIClient()
        u = get_user_model().objects.create_user('staff1', password='x', is_staff=True)
        c.force_authenticate(u)
        rows = {x['id']: x for x in c.get('/api/v1/up3d/templates/').json()}
        for t in AD_TEMPLATES:
            self.assertEqual(rows[t]['group'], 'ad')
            self.assertTrue(rows[t]['fa'])
        self.assertIn('screens', rows['app_showcase']['inputs'])
        self.assertIn('logo', rows['logo_reveal']['inputs'])
        self.assertEqual(rows['showcase']['group'], 'presenter')

    def test_turntable_template_turns_the_product_and_chagher_text_is_persian(self):
        r = SV.reg()
        doc = templates.build('turntable', dict(CHAGHER), r)
        spin = [s for s in doc['shots'] if s['move'] == 'turntable'][0]
        self.assertEqual(spin['params']['turn_deg'], 360)
        self.assertEqual(spin['shot'], 'stage_hero')
        logo = templates.build('logo_reveal', dict(CHAGHER), r)
        p = logo['products'][0]
        self.assertEqual(p['asset'], 'text_3d')
        self.assertEqual(p['params']['text'], 'چغر')
        self.assertTrue(p['params']['use_color'])
        self.assertEqual(p['params']['color'], '#126F85')

    def test_render_block_is_normalised_and_clamped(self):
        from up3d import scene as S
        out = S.norm_render({'look': 'agx_golden', 'ease': 'expo', 'exposure': 9, 'fstop': 0.1, 'handheld': 5, 'dof': 'off', 'motion_blur': '1',
                             'bloom': -1, 'bogus': 1, 'fade_in': 'x'})
        self.assertEqual(out['look'], 'agx_golden')
        self.assertEqual(out['ease'], 'expo')
        self.assertEqual(out['exposure'], 3.0)
        self.assertEqual(out['fstop'], 0.7)
        self.assertEqual(out['handheld'], 1.0)
        self.assertIs(out['dof'], False)
        self.assertIs(out['motion_blur'], True)
        self.assertEqual(out['bloom'], 0.0)
        self.assertNotIn('bogus', out)
        self.assertNotIn('fade_in', out)
        self.assertEqual(S.norm_render({'look': 'unknown'}), {})
        doc = S.normalize({**_valid_doc(), 'render': {'look': 'nope'}})
        self.assertNotIn('render', doc)

    def test_ai_director_does_not_see_the_special_builders(self):
        cat = SV.reg().catalog_for_ai()
        for hidden in ('text_3d', 'logo_3d', 'phone_showcase', 'material_object'):
            self.assertNotIn('- %s:' % hidden, cat)
        for hidden in ('stage_hero', 'phone_front', 'neon_night', 'golden_hour', 'stage', 'open_air'):
            self.assertNotIn('- %s:' % hidden, cat, 'product-stage assets are placed by the ad templates, not by the presenter director')
        self.assertIn('- soft_beauty:', cat)
        self.assertIn('- studio_warm:', cat)

    def test_brand_screens_are_made_from_the_brief_only(self):
        from PIL import Image
        from up3d import screens
        with _tempfile.TemporaryDirectory() as d:
            files = screens.make_screens('چغر', 'با چغر چغر تر شو', ['یک', 'دو', 'سه'], '#126F85', '#163F75', count=3, size=(390, 844), out_dir=d)
            self.assertEqual(len(files), 3)
            self.assertEqual(len(set(files)), 3)
            for f in files:
                self.assertEqual(Image.open(f).size, (390, 844))
            self.assertEqual(files, screens.make_screens('چغر', 'با چغر چغر تر شو', ['یک', 'دو', 'سه'], '#126F85', '#163F75', count=3,
                                                         size=(390, 844), out_dir=d))        # cached: same names

    def test_3d_persian_text_and_pbr_object_dimensions_travel_in_the_compiled_scene(self):
        try:
            import cv2  # noqa: F401
        except ImportError:
            self.skipTest('OpenCV is not installed here')
        from up3d import pipeline
        from up3d.assets import registry
        reg = registry()
        doc = templates.build('logo_reveal', dict(CHAGHER), reg)
        with _tempfile.TemporaryDirectory() as d:
            info = pipeline.prepare(doc, d, 'animatic', None, log=lambda m: None, reg=reg)
            comp = _json.load(open(info['compiled'], encoding='utf-8')) if 'compiled' in info else _json.load(open(_os.path.join(d, 'compiled.json'), encoding='utf-8'))
            p = comp['products'][0]
            self.assertEqual(p['builder'], 'text3d')
            self.assertTrue(p['outline'] and p['outline']['polys'], 'the Persian letters must be traced to polygons')
            self.assertTrue(any(pl['hole'] for pl in p['outline']['polys']), 'ج / چ / غ / ر have counters (holes)')
            self.assertAlmostEqual(p['dimensions'][0], 0.46, places=2)
        trio = templates.build('material_trio', dict(CHAGHER), reg)
        with _tempfile.TemporaryDirectory() as d:
            pipeline.prepare(trio, d, 'animatic', None, log=lambda m: None, reg=reg)
            comp = _json.load(open(_os.path.join(d, 'compiled.json'), encoding='utf-8'))
            self.assertEqual([p['builder'] for p in comp['products']], ['primitive'] * 3)
            self.assertEqual(comp['products'][0]['dimensions'], [0.1, 0.1, 0.1])

    def test_phone_screens_travel_with_the_job_as_relative_paths(self):
        from up3d import pipeline
        from up3d.assets import registry
        reg = registry()
        doc = templates.build('app_showcase', dict(CHAGHER), reg)
        with _tempfile.TemporaryDirectory() as d:
            pipeline.prepare(doc, d, 'animatic', None, log=lambda m: None, reg=reg)
            comp = _json.load(open(_os.path.join(d, 'compiled.json'), encoding='utf-8'))
            prm = comp['products'][0]['params']
            for k in ('screen_image', 'screen_image_2', 'screen_image_3'):
                self.assertTrue(prm[k].startswith('inputs/'), prm[k])
                self.assertTrue(_os.path.isfile(_os.path.join(d, prm[k])))

    def test_old_workers_never_get_a_1_3_scene(self):
        project = Project.objects.create(title='v13', brief={})
        v = SV.new_version(project, templates.build('app_showcase', dict(CHAGHER), SV.reg()), 'test', 'x')
        j = Job.objects.create(project=project, version=v, kind='render', profile='high', owner='worker', state='SCENE_BUILDING')
        now = timezone.now()
        old = Worker.objects.create(name='old-gpu', last_seen=now, capabilities={'gpu': ['OPTIX:RTX'], 'version': '1.2.0', 'mpfb': True})
        new = Worker.objects.create(name='new-gpu', last_seen=now, capabilities={'gpu': ['OPTIX:RTX'], 'version': '1.3.0', 'mpfb': True})
        self.assertTrue(SV.needs_v13_job(j))
        self.assertFalse(SV.capable(old, j))
        self.assertTrue(SV.capable(new, j))
        self.assertIsNone(SV.claim(old))
        self.assertEqual(SV.claim(new)['id'], j.pk)

    def test_up3d_package_and_pack_validation_know_the_new_builders_and_moves(self):
        from up3d import packs
        for b in ('stage', 'open_air'):
            self.assertIn(b, packs.ENV_BUILDERS)
        for b in ('phone', 'text3d', 'logo3d', 'primitive'):
            self.assertIn(b, packs.PRODUCT_BUILDERS)
        for m in NEW_MOVES:
            self.assertIn(m, packs.CAMERA_MOVES)


class NodeRenderQueueTests(TestCase):
    """agent 2.12: a 3D render is the compute job up3d.render (one heavy GPU job at a time); the 3D section keeps its protocol."""

    def setUp(self):
        from apps.compute.models import ComputeNode
        now = timezone.now()
        self.node = ComputeNode.objects.create(name='DESKTOP-GPU', last_seen=now, capabilities={
            'gpu': 'RTX 3060', 'kinds': ['echo', 'up3d.render'], 'blender': True, 'startable': {'worker3d': True}})
        self.worker = Worker.objects.create(name='DESKTOP-GPU', last_seen=now,
                                            capabilities={'gpu': ['OPTIX:RTX 3060'], 'version': '1.3.0', 'mpfb': False})
        self.cpu = Worker.objects.create(name='server-cpu', last_seen=now, capabilities={'gpu': None, 'version': '1.3.0', 'mpfb': True})

    def _job(self, profile, **kw):
        return Job.objects.create(kind='render', profile=profile, owner='worker', state='SCENE_BUILDING', params=kw)

    def _queue_rows(self):
        from apps.compute.models import ComputeJob
        return list(ComputeJob.objects.filter(kind='up3d.render').order_by('created_at'))

    def test_waiting_gpu_job_becomes_one_durable_queue_job(self):
        j = self._job('high')
        self.assertEqual(SV.dispatch_to_nodes(min_gap=0), 1)
        rows = self._queue_rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].payload['up3d_job'], j.pk)
        self.assertEqual(rows[0].origin, 'up3d')
        self.assertGreaterEqual(rows[0].timeout_s, 3600)
        self.assertEqual(SV.dispatch_to_nodes(min_gap=0), 0, 'one live queue job per 3D job')
        self.assertIn('صفِ سرورِ پردازش', Job.objects.get(pk=j.pk).log)

    def test_job_like_36_waits_while_the_node_is_off_and_runs_by_itself_when_it_returns(self):
        from apps.compute import services as CS
        from apps.compute.models import ComputeJob, ComputeNode
        j = self._job('high')
        ComputeNode.objects.filter(pk=self.node.pk).update(last_seen=timezone.now() - timedelta(days=20))
        Worker.objects.filter(pk=self.worker.pk).update(last_seen=timezone.now() - timedelta(days=20))
        self.node.refresh_from_db()
        self.assertFalse(self.node.online)
        self.assertEqual(SV.dispatch_to_nodes(min_gap=0), 1, 'a registered node that knows the kind is enough: the job is parked durably')
        row = self._queue_rows()[0]
        self.assertEqual(row.state, ComputeJob.State.QUEUED)
        self.assertEqual(row.attempts, 0)
        self.assertEqual(row.max_wait_s, 0, 'no waiting limit: it may wait for days')
        ComputeNode.objects.filter(pk=self.node.pk).update(last_seen=timezone.now())
        self.node.refresh_from_db()
        got = CS.claim(self.node)
        self.assertEqual(got.kind, 'up3d.render')
        self.assertEqual(got.payload['up3d_job'], j.pk)

    def test_agent_without_the_kind_gets_nothing_and_keeps_the_old_service_path(self):
        from apps.compute.models import ComputeNode
        ComputeNode.objects.filter(pk=self.node.pk).update(capabilities={'gpu': 'RTX 3060', 'startable': {'worker3d': True}})
        self._job('high')
        self.assertEqual(SV.dispatch_to_nodes(min_gap=0), 0)
        self.node.refresh_from_db()
        self.assertTrue(SV.wants_gpu_worker(self.node), 'old agents are still asked to start worker-3d.bat')

    def test_new_agent_is_not_asked_to_start_a_second_gpu_consumer(self):
        self._job('high')
        self.assertFalse(SV.wants_gpu_worker(self.node))
        info = SV.gpu_nodes()[0]
        self.assertTrue(info['via_queue'])

    def test_light_job_goes_to_the_node_only_when_its_card_is_idle(self):
        from apps.compute.models import ComputeJob
        light = self._job('animatic')
        self.assertEqual(SV.dispatch_to_nodes(min_gap=0), 1, 'idle GPU first')
        ComputeJob.objects.all().delete()
        heavy_other = ComputeJob.objects.create(kind='ollama.chat', payload={}, state=ComputeJob.State.RUNNING, node=self.node)
        self.assertTrue(SV.busy(self.worker), 'the node runs another heavy job')
        self.assertEqual(SV.dispatch_to_nodes(min_gap=0), 0, 'light job: the server CPU worker takes it instead')
        self.assertEqual(SV.claim(self.cpu)['id'], light.pk)
        high = self._job('high')
        self.assertEqual(SV.dispatch_to_nodes(min_gap=0), 1, 'a GPU-class job always queues for the node')
        heavy_other.delete()

    def test_claim_only_the_requested_job(self):
        a, b = self._job('high'), self._job('high')
        self.assertEqual(SV.claim(self.worker, only=b.pk)['id'], b.pk)
        self.assertIsNone(SV.claim(self.worker, only=b.pk + 99))
        Job.objects.filter(pk=a.pk).update(cancel_requested=True)
        self.assertIsNone(SV.claim(self.worker, only=a.pk), 'a cancelled job is not given')

    def test_worker_claim_api_accepts_only_job_and_keeps_capabilities_clean(self):
        j = self._job('high')
        self._job('high')
        c = APIClient()
        body = {'gpu': ['OPTIX:RTX 3060'], 'version': '1.3.0', 'mpfb': False, 'only_job': j.pk}
        r = c.post('/3d/api/worker/claim/', body, format='json', HTTP_AUTHORIZATION='Worker %s' % self.worker.token)
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()['job']['id'], j.pk)
        self.worker.refresh_from_db()
        self.assertNotIn('only_job', self.worker.capabilities)

    def test_node_token_gets_a_worker_row_and_heartbeat_marks_gpu(self):
        from apps.compute.models import ComputeNode
        other = ComputeNode.objects.create(name='LAB-PC', capabilities={'kinds': ['up3d.render']})
        c = APIClient()
        r = c.post('/3d/api/worker/heartbeat/', {'gpu': ['OPTIX:RTX 4070'], 'version': '1.3.0', 'features': ['node']}, format='json',
                   HTTP_AUTHORIZATION='Worker %s' % other.token)
        self.assertEqual(r.status_code, 200, r.content)
        w = Worker.objects.get(name='LAB-PC')
        self.assertTrue(w.has_gpu and w.online)

    def test_queue_job_waits_for_blender_install_then_runs(self):
        from apps.compute import services as CS
        from apps.compute.models import ComputeNode
        self._job('high')
        SV.dispatch_to_nodes(min_gap=0)
        caps = dict(self.node.capabilities)
        caps['bootstrap'] = {'features': {'blender-3d': {'state': 'installing', 'items': [{'id': 'blender', 'title': 'Blender', 'state': 'installing', 'detail': '40%'}]}},
                             'blocked_kinds': {'up3d.render': 'blender-3d'}}
        ComputeNode.objects.filter(pk=self.node.pk).update(capabilities=caps)
        self.node.refresh_from_db()
        self.assertIsNone(CS.claim(self.node), 'the install is still running: the job stays queued')
        st = SV.node_install_state(self.node)
        self.assertEqual(st['state'], 'installing')
        self.assertIn('Blender', st['text'])
        caps['bootstrap'] = {'features': {'blender-3d': {'state': 'ready', 'items': []}}, 'blocked_kinds': {}}
        ComputeNode.objects.filter(pk=self.node.pk).update(capabilities=caps)
        self.node.refresh_from_db()
        self.assertEqual(CS.claim(self.node).kind, 'up3d.render')

    def test_waiting_info_says_the_node_will_take_it(self):
        j = self._job('high')
        info = SV.waiting_info(j)
        self.assertEqual(info['node_queue'], ['DESKTOP-GPU'])
        self.assertTrue(info['gpu_nodes'][0]['via_queue'])

    def test_compute_queue_knows_the_kind_for_panel_text(self):
        from apps.compute import queue as Q
        self.assertTrue(Q.node_takes(self.node, 'up3d.render'))
        from apps.compute.models import ComputeNode
        self.assertFalse(Q.node_takes(ComputeNode(name='old', capabilities={'kinds': ['echo']}), 'up3d.render'))

    def test_selftests_are_registered_and_build_a_real_package(self):
        from apps.compute import selftests as ST
        ST.load_all(force=True)
        self.assertIn('up3d_stage', ST.REGISTRY)
        self.assertIn('up3d_phone', ST.REGISTRY)
        t = ST.REGISTRY['up3d_stage']
        self.assertTrue(t.gpu_required)
        self.assertEqual(t.kind, 'up3d.render')
        self.assertTrue(ST.REGISTRY['up3d_phone'].deep)
        ok, why = t.available(self.node)
        self.assertTrue(ok, why)
        ok, why = t.available(type('N', (), {'capabilities': {'kinds': ['echo']}})())
        self.assertFalse(ok)
        try:
            import cv2  # noqa: F401
        except ImportError:
            return
        spec = t.build(type('C', (), {'caps': {}, 'node': self.node})())
        self.assertEqual(spec.kind, 'up3d.render')
        self.assertEqual(spec.payload['mode'], 'contact')
        with _zipfile.ZipFile(__import__('io').BytesIO(spec.files['package.zip'])) as z:
            names = z.namelist()
            self.assertIn('compiled.json', names)
            comp = _json.loads(z.read('compiled.json'))
        self.assertEqual(comp['profile']['id'], 'standard')
        self.assertEqual(comp['resolution'][0] % 2, 0)
        self.assertEqual(comp['lighting']['id'], 'hdri_studio')
        self.assertTrue(comp['products'][0]['outline']['polys'])

    def test_dispatch_skips_what_the_node_cannot_take_and_does_not_loop(self):
        from apps.compute.models import ComputeJob
        project = Project.objects.create(title='presenter', brief={})
        v = SV.new_version(project, _valid_doc(), 'test', 'x')
        pj = Job.objects.create(project=project, version=v, kind='render', profile='high', owner='worker', state='SCENE_BUILDING')
        self.assertTrue(SV.needs_mpfb(pj))
        self.assertEqual(SV.dispatch_to_nodes(min_gap=0), 0, 'a presenter scene needs the MPFB data this node has not installed (yet)')
        Worker.objects.filter(pk=self.worker.pk).update(capabilities={'gpu': ['OPTIX:RTX 3060'], 'version': '1.3.0', 'mpfb': True})
        self.assertEqual(SV.dispatch_to_nodes(min_gap=0), 1)
        ComputeJob.objects.filter(kind='up3d.render').update(state=ComputeJob.State.COMPLETED, finished_at=timezone.now())
        self.assertEqual(SV.dispatch_to_nodes(min_gap=0), 0, 'it finished a moment ago and found nothing to claim: no loop of empty queue jobs')
        ComputeJob.objects.filter(kind='up3d.render').update(finished_at=timezone.now() - timedelta(minutes=10))
        self.assertEqual(SV.dispatch_to_nodes(min_gap=0), 1, 'later it is tried again')
class RealRenderSmokeTests(TestCase):
    """A real Blender run (CPU, tiny): one ad template from brief to picture. Skipped where Blender is not installed."""

    def setUp(self):
        from up3d import paths
        if not paths.blender_binary():
            self.skipTest('Blender is not installed here')

    def _still(self, template, frame=60):
        from PIL import Image, ImageStat
        from up3d import pipeline
        from up3d.assets import registry
        reg = registry()
        doc = templates.build(template, dict(CHAGHER), reg)
        with _tempfile.TemporaryDirectory() as d:
            pipeline.prepare(doc, d, 'preview', None, log=lambda m: None, reg=reg, profile_overrides={'resolution': 240, 'samples': 4})
            pipeline.render(d, None, None, 5, 2, _os.path.join(d, 'engine.log'), mode='still', extra=['--frame', str(frame)])
            png = _os.path.join(d, 'still_%04d.png' % frame)
            self.assertTrue(_os.path.isfile(png), open(_os.path.join(d, 'engine.log'), encoding='utf-8', errors='replace').read()[-1500:])
            im = Image.open(png).convert('L')
            st = ImageStat.Stat(im)
            rep = _json.load(open(_os.path.join(d, 'engine_report.json'), encoding='utf-8'))
            return im.size, st.mean[0], st.stddev[0], rep

    def test_turntable_template_renders_with_agx_on_the_cpu(self):
        size, mean, std, rep = self._still('turntable')
        self.assertEqual(size[0] % 2, 0)
        self.assertGreater(mean, 25, 'not black')
        self.assertLess(mean, 240, 'not blown out')
        self.assertGreater(std, 8, 'not flat')
        self.assertEqual(rep['device']['type'], 'CPU')
        self.assertEqual(rep['look']['view'], 'AgX')
        self.assertIn('AgX - ', rep['look']['look'])
        self.assertEqual(rep['warnings'] if 'warnings' in rep else [], [])

    def test_persian_3d_logo_and_phone_templates_render(self):
        for t in ('logo_reveal', 'app_showcase'):
            size, mean, std, rep = self._still(t, 120)
            self.assertGreater(std, 8, t)
            self.assertFalse(rep.get('warnings'), (t, rep.get('warnings')))


# ───────────────────────── دورِ اصلاح (۱۴۰۵/۰۸/۲۳): صف‌گذاری بی‌CPU، متنِ چندخطی، لبهٔ نرمِ لوگو، تصویرِ نور/نما، بی‌سقفِ تصویرها


class QueueWithoutCpuTests(TestCase):
    """Node off: a GPU-class render can be created from the panel without «اجرا روی CPU» and waits by itself."""

    def setUp(self):
        from apps.compute.models import ComputeNode
        User = get_user_model()
        self.staff = User.objects.create_user(username='staff-fix', password='x', is_staff=True)
        self.client = APIClient()
        self.client.force_authenticate(user=self.staff)
        self.project = Project.objects.create(title='پروژهٔ صف', brief={}, owner=self.staff)
        self.version = SV.new_version(self.project, _valid_doc(), 'test', 'آزمون')
        self.assertTrue(self.version.valid)
        now = timezone.now()
        Worker.objects.create(name='server-cpu', last_seen=now, capabilities={'gpu': None, 'cpu_count': 2, 'version': '1.3.0', 'mpfb': True})
        # the GPU computer ran an old agent (no up3d.render) and is off now
        self.node = ComputeNode.objects.create(name='DESKTOP-EAFBTGQ', last_seen=now - timedelta(hours=11),
                                               capabilities={'gpu': 'RTX 3060', 'agent': '2.10', 'kinds': ['echo']})

    def test_estimate_names_the_gpu_node_so_the_panel_can_say_what_it_waits_for(self):
        r = self.client.get('/api/v1/up3d/estimate/', {'profile': 'high', 'project': self.project.pk})
        self.assertEqual(r.status_code, 200)
        e = r.json()
        self.assertFalse(e['available'])
        self.assertTrue(e['cpu_seconds'], 'the CPU alternative is still offered')
        self.assertEqual([(n['name'], n['online'], n['via_queue']) for n in e['gpu_nodes']], [('DESKTOP-EAFBTGQ', False, False)])
        ok = self.client.get('/api/v1/up3d/estimate/', {'profile': 'preview', 'project': self.project.pk}).json()
        self.assertTrue(ok['available'])
        self.assertNotIn('gpu_nodes', ok, 'only sent when nobody is ready')

    def test_render_without_allow_cpu_creates_a_job_that_waits_for_the_node(self):
        r = self.client.post('/api/v1/up3d/video-projects/%d/render/' % self.project.pk, {'profile': 'standard'}, format='json')
        self.assertEqual(r.status_code, 201, r.content)
        job = Job.objects.get(pk=r.json()['id'])
        self.assertNotIn('allow_cpu', job.params)
        job.owner, job.state = 'worker', 'SCENE_BUILDING'      # what the orchestrator does after preparing the package
        job.save()
        w = self.client.get('/api/v1/up3d/jobs/%d/' % job.pk).json()['waiting']
        self.assertTrue(w['needs_gpu'])
        self.assertFalse(w['allow_cpu'])
        self.assertEqual(w['eligible'], [], 'the CPU worker must not take a GPU-class render')
        self.assertEqual([n['name'] for n in w['gpu_nodes']], ['DESKTOP-EAFBTGQ'])
        self.assertEqual(w['node_queue'], [], 'the old agent cannot take it yet; it updates itself first')

    def test_the_update_makes_the_node_take_it(self):
        r = self.client.post('/api/v1/up3d/video-projects/%d/render/' % self.project.pk, {'profile': 'high'}, format='json')
        job = Job.objects.get(pk=r.json()['id'])
        job.owner, job.state = 'worker', 'SCENE_BUILDING'
        job.save()
        self.node.capabilities = {'gpu': 'RTX 3060', 'agent': '2.18', 'kinds': ['echo', 'up3d.render']}
        self.node.last_seen = timezone.now()
        self.node.save()
        w = self.client.get('/api/v1/up3d/jobs/%d/' % job.pk).json()['waiting']
        self.assertEqual(w['node_queue'], ['DESKTOP-EAFBTGQ'])


class AssetFileTests(TestCase):
    def test_images_are_not_rate_limited_and_are_cacheable(self):
        from . import api
        self.assertEqual(api.asset_file.cls.throttle_classes, [], 'an <img> has no token: the anonymous 30/min cap gave 429 to the editor')
        r = APIClient().get('/3d/asset-file/environment/stage/thumbnail.jpg')      # anonymous, like an <img>
        self.assertEqual(r.status_code, 200)
        self.assertIn('max-age', r['Cache-Control'])
        r.close()
        self.assertEqual(APIClient().get('/3d/asset-file/environment/nope/thumbnail.jpg').status_code, 404)


class LightingShotThumbnailTests(TestCase):
    def test_every_lighting_and_shot_has_a_picture_and_a_valid_thumbnail_scene(self):
        from up3d.validate import validate
        r = SV.reg()
        for kind in ('lighting', 'shot'):
            self.assertGreaterEqual(len(r.list(kind)), 12, kind)
            for a in r.list(kind):
                self.assertTrue(a.public()['has_thumbnail'], '%s/%s has no thumbnail.jpg' % (kind, a.id))
                doc = SV.thumbnail_doc(kind, a.id)
                rep = validate(doc, r)
                self.assertTrue(rep.ok, '%s/%s: %s' % (kind, a.id, [i['message'] for i in rep.errors]))
                if kind == 'lighting':
                    self.assertEqual(doc['lighting']['id'], a.id)
                else:
                    self.assertEqual(doc['shots'][0]['shot'], a.id)

    def test_the_thumbnail_api_accepts_both_kinds(self):
        User = get_user_model()
        c = APIClient()
        c.force_authenticate(user=User.objects.create_user(username='staff-th', password='x', is_staff=True))
        for kind in ('lighting', 'shot'):
            r = c.post('/api/v1/up3d/assets/thumbnails/', {'kind': kind, 'ids': [SV.reg().list(kind)[0].id]}, format='json')
            self.assertEqual(r.status_code, 200, r.content)
            self.assertEqual(r.json()['queued'], 1)
        self.assertEqual(c.post('/api/v1/up3d/assets/thumbnails/', {'kind': 'voice'}, format='json').status_code, 400)


class Text3dFixTests(TestCase):
    LONG = 'پژوهش گچ‌بری Chagher ۱۴۰۵'

    def test_a_long_one_line_name_wraps_to_balanced_lines_and_grows_taller(self):
        from up3d import text3d
        flat = text3d.text_outline({'text': self.LONG, 'width_m': 0.46, 'wrap_ratio': 0})
        wrapped = text3d.text_outline({'text': self.LONG, 'width_m': 0.46, 'wrap_ratio': 2.6})
        self.assertGreater(flat['w'] / flat['h'], 5, 'one very wide line: tiny letters in a 9:16 frame')
        self.assertLessEqual(wrapped['w'] / wrapped['h'], 3.4)
        self.assertGreater(wrapped['h'], flat['h'] * 2)
        self.assertAlmostEqual(wrapped['w'], 0.46, places=2)

    def test_wrap_keeps_word_order_and_leaves_short_or_explicit_texts_alone(self):
        from up3d import text3d
        out = text3d.wrap_text(self.LONG, 'Black', 2.6)
        self.assertIn('\n', out)
        self.assertEqual(out.split(), self.LONG.split(), 'the logical word order is kept (each line is shaped on its own)')
        self.assertLessEqual(len(out.split('\n')), text3d.MAX_WRAP_LINES)
        self.assertEqual(text3d.wrap_text('چغر', 'Black', 2.6), 'چغر', 'one word cannot wrap')
        two = 'اول\nدوم و سوم و چهارم و پنجم و ششم'
        self.assertEqual(text3d.wrap_text(two, 'Black', 1.0), two, 'explicit line breaks are the author\'s')
        self.assertEqual(text3d.wrap_text(self.LONG, 'Black', 0), self.LONG, 'wrap_ratio 0 switches it off')

    def test_logo_ad_template_asks_for_a_wrap_that_fits_the_frame(self):
        from up3d.templates_ad import TEXT_WRAP_RATIO
        r = SV.reg()
        for aspect, ratio in TEXT_WRAP_RATIO.items():
            doc = templates.build('logo_reveal', dict(CHAGHER, aspect=aspect, brand=self.LONG), r)
            self.assertEqual(doc['products'][0]['params']['wrap_ratio'], ratio, aspect)
        self.assertLess(TEXT_WRAP_RATIO['9:16'], TEXT_WRAP_RATIO['16:9'])

    def test_small_logo_contours_are_smooth_not_stair_stepped(self):
        import math
        from PIL import Image, ImageDraw
        from up3d import text3d
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, 'logo.png')
            im = Image.new('RGBA', (500, 500), (0, 0, 0, 0))
            ImageDraw.Draw(im).ellipse((60, 60, 140, 140), fill=(18, 111, 133, 255))      # a small round feature: R = 40 px of 500
            im.save(path)
            outline, face = text3d.logo_outline({'logo_image': path, 'width_m': 0.4}, d, 'x')
            self.assertTrue(face and os.path.isfile(face))
            pts = outline['polys'][0]['pts']
            worst, radii = 0.0, []
            cx, cz = 0.0, outline['h'] / 2.0
            for i, b in enumerate(pts):
                a, c = pts[i - 1], pts[(i + 1) % len(pts)]
                v1, v2 = (b[0] - a[0], b[1] - a[1]), (c[0] - b[0], c[1] - b[1])
                worst = max(worst, abs(math.atan2(v1[0] * v2[1] - v1[1] * v2[0], v1[0] * v2[0] + v1[1] * v2[1])))
                radii.append(math.hypot(b[0] - cx, b[1] - cz))
            self.assertLess(math.degrees(worst), 18, 'one 1 px stair-step per vertex made 24-45 degree turns on such a feature')
            self.assertLess((max(radii) - min(radii)) / (sum(radii) / len(radii)), 0.02, 'stays a round disc (the old 16-gon was off by ~3%)')
            self.assertGreaterEqual(len(pts), 24, 'a smooth curve, not a coarse 16-gon')
            self.assertGreaterEqual(Image.open(face).size[0], 120, 'the coloured front picture is enlarged too')


class DeviceTextTests(TestCase):
    def test_device_is_a_readable_persian_line_not_raw_json(self):
        from up3d.worker import device_text
        self.assertEqual(device_text({'type': 'CPU'}), 'پردازنده (CPU)')
        gpu = device_text({'type': 'OPTIX', 'devices': ['NVIDIA GeForce RTX 3060']})
        self.assertEqual(gpu, 'کارتِ گرافیک NVIDIA GeForce RTX 3060 (OptiX)')
        self.assertNotIn('{', gpu)
        self.assertIn('OPTIX', device_text({'type': 'CUDA', 'devices': ['RTX']}, 'OPTIX->CUDA'))
        self.assertIn('پردازنده', device_text({'type': 'CPU', 'note': 'GPU failed: x'}, 'GPU->CPU'))


class HdriSunsetTests(TestCase):
    def test_sunset_has_a_warm_front_key_and_the_sun_turned_towards_the_stage(self):
        lt = SV.reg().get('lighting', 'hdri_sunset')
        self.assertTrue(lt['rig'], 'only the HDRI lit the product from behind: cold blue-grey')
        self.assertLessEqual(min(l.get('kelvin', 5500) for l in lt['rig']), 4200, 'a warm key')
        self.assertEqual(lt['world']['hdri'], 'venice_sunset')
        self.assertIn('hdri_rotation', lt['params'])

    def test_the_sun_of_the_picture_ends_up_in_front_of_the_product(self):
        """Blender's environment texture: u = 0.5 - atan2(y, x) / 2pi, and the Mapping node turns the lookup by the rotation, so the sun
        (the brightest pixel) stands at azimuth (0.5 - u) * 360 - rotation in the world (x to y). The camera looks from -Y: the sun must be on
        the camera side (y < 0), otherwise only the blue sky lights the product from behind."""
        import math
        import cv2
        lt = SV.reg().get('lighting', 'hdri_sunset')
        path = _os.path.join(str(SV.settings.UP3D_ROOT), 'assets', 'hdri', lt['world']['hdri'] + '.hdr')
        im = cv2.imread(path, cv2.IMREAD_ANYDEPTH | cv2.IMREAD_COLOR)
        self.assertIsNotNone(im)
        lum = im[:, :, 0] * 0.0722 + im[:, :, 1] * 0.7152 + im[:, :, 2] * 0.2126
        _, x = divmod(int(lum.argmax()), lum.shape[1])
        u = x / float(lum.shape[1])
        azimuth = (0.5 - u) * 360.0 - float(lt['world']['hdri_rotation'])
        self.assertLess(math.sin(math.radians(azimuth)), -0.5, 'the sun is on the camera side (azimuth %.0f)' % azimuth)
        self.assertEqual(float(lt['params']['hdri_rotation']['default']), float(lt['world']['hdri_rotation']), 'the slider starts at the preset')
