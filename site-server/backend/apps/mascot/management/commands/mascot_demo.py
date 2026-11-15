"""«ماسکوت» را با رنگ‌ها و لوگوی واقعیِ یک فروشگاه امتحان می‌کند (فقط می‌خواند؛ هیچ ردیفی در دیتابیس و هیچ عکسی در کتابخانه نمی‌سازد).

    python manage.py mascot_demo --store 34 --out /tmp/mascot-demo [--role coach] [--text "با چغر چغر تر شو"]

در پوشهٔ خروجی می‌نویسد:
    contact-sheet.jpg      ژست‌ها × اندازه‌ها در یک برگه (همان شخصیت، همان رنگ‌ها)
    poses.jpg              همهٔ ۲۹ ژست · sizes.jpg  یک ژست در چهار اندازه · model-sheet.png  برگهٔ مدل
    sticker.png · sticker-bust.png  استیکرِ شفافِ تمام‌قد و نیم‌تنه · thumbnail-with-mascot.jpg  تامنیلِ یوتیوب که استیکر را سوژه گرفته (بدونِ هیچ «حذفِ پس‌زمینه»ای)
    shots/<اندازه>.png     پست و استوریِ کامل با حباب
متنِ حباب را شما می‌دهید یا از جمله‌های بی‌ادعای پیشنهادی (برای چغر: شعار و جمله‌های تأییدشدهٔ docs/chagher/brand-facts-fa.md) برداشته می‌شود؛ قیمت یا آماری ساخته نمی‌شود.
"""
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from PIL import Image

from apps.mascot import selftest, services
from apps.mascot.engine import brand as B
from apps.mascot.engine import compose, copy_guard, poses
from apps.stores.models import Store


class Command(BaseCommand):
    help = "نمونهٔ ماسکوتِ یک فروشگاه با رنگ و لوگوی واقعیِ آن (بدونِ نوشتن در دیتابیس)."

    def add_arguments(self, parser):
        parser.add_argument("--store", type=int, required=True)
        parser.add_argument("--out", default="/tmp/mascot-demo")
        parser.add_argument("--role", default="coach")
        parser.add_argument("--text", default="")
        parser.add_argument("--no-logo", action="store_true")

    def handle(self, *args, **o):
        store = Store.objects.filter(pk=o["store"]).first()
        if store is None:
            raise CommandError("فروشگاه پیدا نشد.")
        if o["role"] not in B.ROLES:
            raise CommandError("نقشِ ناشناخته: " + ", ".join(B.ROLES))
        colours = services.brand_colours(store)
        logo = None if o["no_logo"] else services.store_logo(store)
        role = B.ROLES[o["role"]]
        spec = B.spec_from_brand(o["role"], colours, f"{role['fa']} {store.name}", logo=logo is not None)
        text = " ".join(str(o["text"] or "").split()) or copy_guard.suggested_lines(store.name)[0]["text"]
        found = [f for f in copy_guard.check_text(text) if f["code"] in copy_guard.BLOCKING]
        if found:
            raise CommandError(copy_guard.message_fa(found))
        out = Path(o["out"])
        (out / "shots").mkdir(parents=True, exist_ok=True)
        bg = role["background"]

        sizes_img = compose.contact_sizes(spec, pose=role["pose"], expression=role["expression"], brand=colours, background=bg, txt=text, logo=logo, height=520)
        sizes_img.save(out / "sizes.jpg", quality=88)
        poses_img = compose.contact_poses(spec, brand=colours, background=bg, logo=logo, cell=260, cols=8)
        poses_img.save(out / "poses.jpg", quality=86)
        sheet = Image.new("RGB", (max(sizes_img.width, poses_img.width), sizes_img.height + poses_img.height + 20), (244, 241, 234))
        sheet.paste(sizes_img, (0, 0))
        sheet.paste(poses_img, (0, sizes_img.height + 20))
        sheet.save(out / "contact-sheet.jpg", quality=86)
        compose.model_sheet(spec, title=spec["name"], store_name=store.name, version=None, logo=logo).save(out / "model-sheet.png")
        for key in compose.SIZES:
            img, _info = compose.compose_still({"size": key, "background": bg, "brand": colours, "actors": [{"spec": spec, "pose": role["pose"], "expression": role["expression"]}],
                                                "bubbles": [{"actor": 0, "text": text, "kind": "say"}]}, logo=logo)
            img.save(out / "shots" / f"{key}.png")
        full, _ = compose.sticker(spec, pose="thumbs_up", expression="happy", logo=logo)
        full.save(out / "sticker.png")
        bust, _ = compose.sticker(spec, pose="thumbs_up", expression="happy", logo=logo, crop="bust")
        bust.save(out / "sticker-bust.png")
        self._thumbnail(store, bust, text, colours, logo, out / "thumbnail-with-mascot.jpg")
        res = selftest.grid(spec, logo=logo)
        self.stdout.write(f"رنگ‌های برند: {', '.join(colours) or '—'} · لوگو: {'روی سینه' if logo is not None else 'ندارد'} · نقش: {role['fa']}")
        self.stdout.write(f"بررسیِ ثبات: {res['passed']} از {res['total']} تصویر ({res['poses']} ژست × {res['sizes']} اندازه) قبول شد؛ {res['seconds']} ثانیه")
        self.stdout.write(f"متنِ حباب: «{text}» · ژست‌ها: {len(poses.POSES)} · خروجی: {out}")
        if not res["ok"]:
            raise CommandError("بررسیِ ثبات رد شد: " + str(res["failed"][:3]))

    def _thumbnail(self, store, bust, text, colours, logo, path):
        """همان مسیرِ تامنیل‌ساز: استیکرِ شفاف سوژهٔ «چهرهٔ بزرگ» می‌شود؛ هیچ برشی انجام نمی‌شود."""
        from apps.thumbs import render as R
        from apps.thumbs import services as thumbs
        from apps.thumbs.styles import STYLES

        kit = thumbs.brand_kit(store)
        spec = R.clean_spec({"format": "youtube", "style": "face_text", "content": {"title": text, "subtitle": ""}, "colors": {"use_brand": True}, "subject": {"mode": "cutout"}}, STYLES)
        inp = R.Inputs(brand_colors=kit["colors"], store_name=store.name, heading_font=kit["heading_font"])
        inp.subject, inp.subject_is_cutout = bust, True
        if logo is not None:
            inp.logo = logo
        res = R.render(spec, inp, scale=0.75)
        path.write_bytes(R.to_jpeg_bytes(res.image, 88))
