"""«تامنیل‌ساز» را با رنگ‌ها و لوگوی واقعیِ یک فروشگاه امتحان می‌کند (فقط می‌خواند؛ هیچ ردیفی در دیتابیس نمی‌سازد).

    python manage.py thumbs_demo --store 34 --out /tmp/thumbs-demo \
        --title "با چغر، *چغر‌تر* شو" --subtitle "پیش‌نویسِ برنامهٔ ورزشی و غذایی در کمتر از یک دقیقه"

برای هر سبک و هر قالبِ خواسته یک JPEG می‌نویسد (سوژهٔ نمونه = شخصِ کارتونیِ ساختگی، نه عکسِ واقعی) و یک ``contact-sheet.jpg``.
متن‌ها را شما می‌دهید؛ هیچ قیمت یا آماری ساخته نمی‌شود. رنگ‌ها و لوگو از «سبکِ برند»/پروفایلِ همان فروشگاه می‌آید.
"""
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from PIL import Image

from apps.stores.models import Store
from apps.thumbs import render as R
from apps.thumbs import services
from apps.thumbs import formats as F
from apps.thumbs.styles import STYLES


class Command(BaseCommand):
    help = "نمونهٔ همهٔ سبک‌های تامنیل‌ساز با رنگ و لوگوی واقعیِ یک فروشگاه (بدونِ نوشتن در دیتابیس)."

    def add_arguments(self, parser):
        parser.add_argument("--store", type=int, required=True)
        parser.add_argument("--out", default="/tmp/thumbs-demo")
        parser.add_argument("--formats", default="youtube,ig_portrait,story")
        parser.add_argument("--styles", default="all")
        parser.add_argument("--title", default="")
        parser.add_argument("--subtitle", default="")
        parser.add_argument("--kicker", default="")
        parser.add_argument("--width", type=int, default=640)

    def handle(self, *args, **o):
        store = Store.objects.filter(pk=o["store"]).first()
        if store is None:
            raise CommandError("فروشگاه پیدا نشد.")
        fmts = [f for f in o["formats"].split(",") if f in F.FORMATS]
        styles = list(STYLES) if o["styles"] == "all" else [s for s in o["styles"].split(",") if s in STYLES]
        if not fmts or not styles:
            raise CommandError("قالب یا سبکِ معتبری داده نشد.")
        out = Path(o["out"])
        out.mkdir(parents=True, exist_ok=True)
        kit = services.brand_kit(store)
        title = o["title"] or store.name
        content = {"title": title, "subtitle": o["subtitle"] or (store.description or "")[:60], "kicker": o["kicker"]}
        rows = []
        for st in styles:
            row = []
            for fk in fmts:
                base = dict(services.SAMPLE_CONTENT.get(st, {}))
                base.update({k: v for k, v in content.items() if v})
                spec = R.clean_spec({"format": fk, "style": st, "content": base}, STYLES)
                inp = services.sample_inputs(st, kit["colors"])
                inp.heading_font, inp.store_name = kit["heading_font"], store.name
                lp = services._logo_path(store, kit["kit"])
                if lp is not None:
                    from apps.photoedit import ops

                    inp.logo = ops.load(lp)
                fm = F.get(fk)
                res = R.render(spec, inp, scale=min(1.0, o["width"] / fm.w))
                path = out / f"{st}-{fk}.jpg"
                path.write_bytes(R.to_jpeg_bytes(res.image, 88))
                row.append(res.image)
            rows.append(row)
        cw = max(i.width for r in rows for i in r)
        ch = max(i.height for r in rows for i in r)
        sheet = Image.new("RGB", (len(fmts) * (cw + 10) + 10, len(rows) * (ch + 10) + 10), (24, 24, 28))
        for ri, r in enumerate(rows):
            for ci, im in enumerate(r):
                sheet.paste(im, (10 + ci * (cw + 10), 10 + ri * (ch + 10)))
        sheet.save(out / "contact-sheet.jpg", quality=86)
        self.stdout.write(f"{len(styles) * len(fmts)} تصویر در {out} نوشته شد؛ رنگ‌های برند: {', '.join(kit['colors']) or 'ثبت نشده'}.")
