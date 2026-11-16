"""پیش‌نویسِ شخصیتِ «چغر»: شخصیتِ گفتار فقط از ``docs/chagher/brand-facts-fa.md`` + یک شخصیتِ مربی با رنگ‌های برندِ چغر؛ و برگهٔ تماسِ همهٔ سبک‌ها × ژست‌ها برای دیدنِ با چشم.

    python manage.py brandchar_chagher --store 34 --out /tmp/chagher            # فقط می‌سازد و می‌نویسد؛ چیزی در دیتابیس نمی‌ماند
    python manage.py brandchar_chagher --store 34 --apply                       # پیش‌نویسِ گفتار را ذخیره و یک شخصیتِ مربی می‌سازد (قفل نمی‌کند)

هیچ‌چیز منتشر نمی‌شود؛ ``--apply`` فقط پیش‌نویس می‌سازد و مالک در پنل ویرایش و تأیید می‌کند.
"""
from __future__ import annotations

import os

from django.core.management.base import BaseCommand, CommandError
from PIL import Image

from apps.brandchar import persona as P
from apps.brandchar import persona_store, services as S
from apps.brandchar.engine import doc as D
from apps.brandchar.engine import render as R
from apps.brandchar.engine import sheet as SH
from apps.mascot.engine import compose, poses
from apps.stores.models import Store

CONTACT_POSES = ("stand", "wave", "thumbs_up", "point_up", "think", "cheer", "curl", "run_a", "squat", "stop")


class Command(BaseCommand):
    help = "پیش‌نویسِ شخصیتِ چغر (گفتار از سندِ واقعیت‌ها + شخصیتِ مربی) و برگهٔ تماس"

    def add_arguments(self, parser):
        parser.add_argument("--store", type=int, default=34)
        parser.add_argument("--out", default="")
        parser.add_argument("--apply", action="store_true")

    def handle(self, *args, **o):
        store = Store.objects.filter(pk=o["store"]).first()
        if store is None:
            raise CommandError(f"فروشگاه {o['store']} نیست")
        out = o["out"]
        if out:
            os.makedirs(out, exist_ok=True)
        draft = P.draft(store)
        p = draft["persona"]
        self.stdout.write(f"فروشگاه: {store.name} · منبع: {draft['origin']} · کهن‌الگو: {P.ARCHETYPES[p['archetype']]['fa']} · کامل‌بودن: {P.filled_score(p)['done']}/{P.filled_score(p)['total']}")
        for s in draft["sources"]:
            self.stdout.write(f"  واقعیت: {s['fact']}  [{s['source']}]")
        for n in draft["notes"]:
            self.stdout.write(f"  یادداشت: {n}")
        brand = S.brand_colours(store) or P.CHAGHER["colours"]
        logo = S.store_logo(store)
        docs = {st: S.new_doc("coach", brand, "مربیِ چغر", style=st, logo=logo is not None) for st in D.STYLES}
        if o["apply"]:
            row = persona_store.save(store, None, p, source="facts" if draft["origin"] == "facts" else "rule")
            self.stdout.write(f"شخصیتِ گفتار ذخیره شد (نسخهٔ {row.version}، قفل نیست)")
            if not S.primary(store):
                c = S.create(store, None, role="coach", name="مربیِ چغر", style="flat", use_logo=True, brand=brand)
                self.stdout.write(f"شخصیتِ مربی ساخته شد: #{c.pk} (قفل نیست)")
        if out:
            W, H = 230, 350
            sheet = Image.new("RGB", (W * len(CONTACT_POSES), H * len(D.STYLES)), "#e9eef5")
            for r, st in enumerate(D.STYLES):
                for c_, pz in enumerate(CONTACT_POSES):
                    shot = compose.figure_layer({"spec": R.actor_spec(docs[st]), "pose": pz, "expression": "happy", "x": 0.5, "y": 0.96, "height": 0.93}, W, H, logo=R.logo_for(docs[st], logo))
                    bg = Image.new("RGBA", (W, H), (233, 238, 245, 255))
                    bg.alpha_composite(shot.layer)
                    sheet.paste(bg.convert("RGB"), (c_ * W, r * H))
            sheet.save(os.path.join(out, "chagher-contact.png"))
            SH.model_sheet(docs["flat"], title="مربیِ چغر", store_name=store.name, logo=logo, persona=p).save(os.path.join(out, "chagher-sheet.jpg"), quality=88)
            for i, tid in enumerate(("tip", "greet", "slogan")):
                from apps.brandchar import templates as T

                opts = T.options_for(type("C", (), {"role": "coach"})(), tid, p)
                img, _ = R.still(docs["flat"], S.clean_options(opts), brand, logo)
                img.save(os.path.join(out, f"chagher-post-{tid}.jpg"), quality=88)
            self.stdout.write(f"نوشته شد: {out}/chagher-contact.png، chagher-sheet.jpg، chagher-post-*.jpg")
        self.stdout.write(f"ژست‌ها: {len(poses.POSES)} · سبک‌ها: {len(D.STYLES)} · اندازه‌ها: {len(compose.SIZES)}")
