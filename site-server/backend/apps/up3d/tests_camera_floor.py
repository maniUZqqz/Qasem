"""The 3D engine's camera never goes below the floor (review of 2026-11-13: «آشکارسازیِ قهرمان» had ~3 s of empty dark frames).

`stage_low` looks up from −9° and `reveal_pull` lowers it by up to 9° more; at the product distance of that shot this put the camera UNDER the stage floor,
so the film showed the back of the floor instead of the product.  Blender itself is not available to the unit tests, so this checks the contract of
the code (the real render of the fix was judged on frames of the template on the server) and that the node's copy of the engine is the same file.
"""
import re
from pathlib import Path
from unittest import mock

from django.conf import settings
from django.test import SimpleTestCase, TestCase

ENGINE = Path(settings.UP3D_ROOT) / "engine" / "up3d_engine"
NODE = Path(settings.BASE_DIR).parent / "processing" / "engine" / "up3d_engine"


def src(path: Path) -> str:
    return path.read_text(encoding="utf-8")


class CameraFloorContractTests(SimpleTestCase):
    def test_the_camera_height_is_clamped_to_the_floor_plus_a_clearance(self):
        text = src(ENGINE / "camera.py")
        self.assertRegex(text, r"CAM_FLOOR_CLEARANCE\s*=\s*0\.0\d+")
        self.assertIn("floor_min = float(getattr(ctx, 'floor_z', 0.0) or 0.0) + CAM_FLOOR_CLEARANCE", text)
        # the clamp is applied to the final position (after the handheld offsets), just before the keys are stored
        clamp = text.index("if pos.z < floor_min:")
        self.assertLess(text.index("pos += dp", 0), clamp)
        self.assertLess(clamp, text.index("locs.append(pos[:])"))

    def test_the_floor_of_the_environment_reaches_the_camera(self):
        main = src(ENGINE / "main.py")
        self.assertRegex(main, r"ctx\.floor_z\s*=\s*float\(\(environments\.build\(ctx\) or \{\}\)\.get\('floor_z'\) or 0\.0\)")
        envs = src(ENGINE / "environments.py")
        self.assertGreaterEqual(len(re.findall(r"return \{'floor_z': 0\.0", envs)), 5)       # every environment reports its floor

    def test_the_clearance_is_a_few_centimetres_not_a_metre(self):
        m = re.search(r"CAM_FLOOR_CLEARANCE\s*=\s*(0\.\d+)", src(ENGINE / "camera.py"))
        self.assertTrue(0.02 <= float(m.group(1)) <= 0.12, m.group(1))                  # below the platform top (0.06 m) is fine, a metre is not


class NodeCopyTests(SimpleTestCase):
    def test_the_nodes_copy_of_the_engine_is_the_same_code(self):
        """The processing node runs the copy in processing/engine: a fix that is only in up3d-engine never reaches the GPU."""
        if not NODE.is_dir():
            self.skipTest("no node copy of the engine in this tree")
        for name in ("camera.py", "main.py"):
            self.assertEqual(src(ENGINE / name).replace("\r\n", "\n"), src(NODE / name).replace("\r\n", "\n"), name)


class DeleteProjectFilesTests(TestCase):
    """Deleting a 3D project also removes the folders of its jobs (review of 2026-11-13: 29 folders / ~33 MB stayed behind)."""

    def test_the_job_folders_go_with_the_project(self):
        import os
        import shutil
        import tempfile

        from . import services as SV
        from .models import Job, Project

        data = tempfile.mkdtemp(prefix="up3d-del-")
        self.addCleanup(shutil.rmtree, data, True)
        project = Project.objects.create(title="حذف", brief={})
        other = Project.objects.create(title="ماندنی", brief={})
        jobs = [Job.objects.create(project=project, kind="render", profile="preview", owner="worker", state="DONE") for _ in range(2)]
        keep = Job.objects.create(project=other, kind="render", profile="preview", owner="worker", state="DONE")
        with mock.patch.object(SV, "DATA", data):
            for j in jobs + [keep]:
                d = SV.job_dir(j)
                with open(os.path.join(d, "final.mp4"), "wb") as fh:
                    fh.write(b"x" * 10)
            self.assertEqual(SV.delete_project(project), 2)
            self.assertFalse(Project.objects.filter(pk=project.pk).exists())
            for j in jobs:
                self.assertFalse(os.path.exists(SV.data_abs(j.dir_rel())), "a job folder stayed on disk")
            self.assertTrue(os.path.isfile(os.path.join(SV.data_abs(keep.dir_rel()), "final.mp4")), "another project's files must stay")
