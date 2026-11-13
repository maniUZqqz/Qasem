"""«thumbs_demo»: نمونهٔ سبک‌ها با رنگ و لوگوی واقعیِ یک فروشگاه، بدونِ نوشتن در دیتابیس."""
import shutil
import tempfile
from io import StringIO
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.management import CommandError, call_command
from django.test import TestCase
from PIL import Image

from apps.stores.models import Store

from .models import IdeaSet, Thumbnail

User = get_user_model()


class ThumbsDemoTests(TestCase):
    def setUp(self):
        self.out = Path(tempfile.mkdtemp(prefix="nmthumbs-demo-"))
        owner = User.objects.create_user("demo-owner", password="x")
        self.store = Store.objects.create(owner=owner, name="چغر", colors={"primary": "#126F85", "secondary": "#163F75"}, description="دستیارِ مربی‌ها")

    def tearDown(self):
        shutil.rmtree(self.out, ignore_errors=True)

    def test_writes_images_and_sheet_without_touching_the_db(self):
        out = StringIO()
        call_command("thumbs_demo", store=self.store.pk, out=str(self.out), formats="youtube,story", styles="face_text,neon", title="با چغر، *چغر‌تر* شو",
                     subtitle="پیش‌نویسِ برنامه", width=320, stdout=out)
        names = sorted(p.name for p in self.out.iterdir())
        self.assertEqual(names, ["contact-sheet.jpg", "face_text-story.jpg", "face_text-youtube.jpg", "neon-story.jpg", "neon-youtube.jpg"])
        self.assertEqual(Image.open(self.out / "face_text-youtube.jpg").size[0], 320)
        self.assertIn("#126f85", out.getvalue())
        self.assertEqual(Thumbnail.objects.count(), 0)
        self.assertEqual(IdeaSet.objects.count(), 0)

    def test_bad_arguments(self):
        with self.assertRaises(CommandError):
            call_command("thumbs_demo", store=99999, out=str(self.out))
        with self.assertRaises(CommandError):
            call_command("thumbs_demo", store=self.store.pk, out=str(self.out), formats="zzz")
