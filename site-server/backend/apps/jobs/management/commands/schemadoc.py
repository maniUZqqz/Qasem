"""`python manage.py schemadoc` — نقشه‌ی واقعی دیتابیس را از خود مدل‌ها می‌نویسد.

چرا تولیدشده و نه دستی: نسخه‌ی دستیِ `docs/DATABASE.md` یک **طرح** بود، نه
توصیف کد. یک مدل `Asset` را شرح می‌داد که هیچ‌وقت ساخته نشد، پنج اپ کامل
(billing، marketing، cms، api_platform، analytics) را اصلاً نمی‌شناخت، و
حالت‌های Job را ناقص می‌گفت. سندی که اشتباه باشد از سند نداشتن بدتر است —
چون کسی بر اساسش تصمیم می‌گیرد.

    python manage.py schemadoc            # چاپ
    python manage.py schemadoc --write    # نوشتن روی docs/DATABASE.md
"""
from __future__ import annotations

from pathlib import Path

from django.apps import apps as django_apps
from django.core.management.base import BaseCommand
from django.db import models

#: به ترتیب جریان محصول خوانده می‌شود، نه الفبا — کسی که اولین بار نگاه
#: می‌کند، از «فروشگاه» شروع می‌کند نه از «accounts».
ORDER = [
    "accounts", "stores", "products", "ai", "content", "customers",
    "campaigns", "billing", "marketing", "analytics", "api_platform",
    "cms", "jobs", "common",
]

SKIP_FIELDS = {"id", "created_at", "updated_at"}


def describe(field) -> str:
    """یک فیلد، در یک خط — نوع و آنچه واقعاً مهم است."""
    kind = field.get_internal_type().replace("Field", "")
    bits = []

    if isinstance(field, models.ForeignKey):
        kind = f"→ {field.related_model._meta.object_name}"
        if field.remote_field.on_delete.__name__ != "CASCADE":
            bits.append(field.remote_field.on_delete.__name__.lower())
    elif isinstance(field, models.OneToOneField):
        kind = f"1:1 {field.related_model._meta.object_name}"
    elif isinstance(field, models.ManyToManyField):
        kind = f"↔ {field.related_model._meta.object_name}"

    if getattr(field, "choices", None):
        values = " | ".join(str(c[0]) for c in field.choices)
        bits.append(values if len(values) <= 90 else values[:87] + "…")
    if getattr(field, "unique", False):
        bits.append("یکتا")
    if getattr(field, "null", False):
        bits.append("nullable")
    if getattr(field, "db_index", False) and not isinstance(field, models.ForeignKey):
        bits.append("ایندکس")

    return f"`{field.name}` {kind}" + (f" — {'، '.join(bits)}" if bits else "")


class Command(BaseCommand):
    help = "نقشه‌ی دیتابیس را از مدل‌های واقعی تولید می‌کند."

    def add_arguments(self, parser):
        parser.add_argument("--write", action="store_true",
                            help="روی docs/DATABASE.md بنویس")

    def handle(self, *args, **options):
        out = [
            "<!-- تولیدشده با `python manage.py schemadoc --write` — دستی ویرایش نکن. -->",
            "# نقشه‌ی دیتابیس",
            "",
            "این فایل از **خود مدل‌ها** خوانده می‌شود، پس نمی‌تواند از کد جلو یا",
            "عقب بیفتد. بعد از هر مهاجرت یک بار `python manage.py schemadoc --write`",
            "بزنید.",
            "",
            "موتور: **SQLite** در توسعه، **PostgreSQL** در production — همان تصمیم D2.",
            "مدل‌ها و مهاجرت‌ها موتور-ناوابسته‌اند، پس جابه‌جایی فقط `DATABASES` را",
            "لمس می‌کند.",
            "",
            "> `id`، `created_at` و `updated_at` در جدول‌ها نوشته نشده‌اند چون تقریباً",
            "> همه دارندشان؛ نبودشان استثناست نه بودنشان.",
            "",
        ]

        seen, total = set(), 0
        for label in ORDER:
            try:
                config = django_apps.get_app_config(label)
            except LookupError:
                continue
            model_list = list(config.get_models())
            if not model_list:
                continue
            seen.add(label)
            out.append(f"## {label}")
            out.append("")
            for model in model_list:
                total += 1
                meta = model._meta
                out.append(f"### {meta.object_name}")
                doc = (model.__doc__ or "").strip().split("\n")[0]
                # جنگو برای مدل بدون docstring خودش یکی می‌سازد؛ آن را ننویس
                if doc and not doc.endswith("(id, )") and "object (" not in doc:
                    out.append(f"{doc}")
                out.append("")
                for field in meta.get_fields():
                    if not getattr(field, "concrete", False):
                        continue
                    if field.name in SKIP_FIELDS:
                        continue
                    out.append(f"- {describe(field)}")
                if meta.unique_together:
                    for group in meta.unique_together:
                        out.append(f"- **یکتا با هم:** {'، '.join(group)}")
                for index in meta.indexes:
                    out.append(f"- **ایندکس:** {'، '.join(index.fields)}")
                out.append("")

        missing = [c.label for c in django_apps.get_app_configs()
                   if c.label not in seen and list(c.get_models())
                   and not c.name.startswith(("django.", "rest_framework"))]
        if missing:
            out += ["## اپ‌هایی که در ترتیب بالا نبودند", "",
                    "به `ORDER` در `schemadoc.py` اضافه‌شان کن:", ""]
            out += [f"- {m}" for m in missing] + [""]

        out += [
            "---",
            "",
            "## قواعدی که در شکل جدول‌ها دیده می‌شوند",
            "",
            "- **هر جدولِ متعلق به فروشگاه، کلید `store` دارد** و هر کوئری با آن",
            "  فیلتر می‌شود. ایزوله‌سازی مستأجر در لایه‌ی ORM و دسترسی است، نه در",
            "  فرانت.",
            "- **ستون‌های کسب‌وکاری رابطه‌ای‌اند، نه JSON.** JSON فقط برای فراداده‌ی",
            "  مدل و ورک‌فلو است — چیزی که هرگز با آن کوئری نمی‌زنیم.",
            "- **هیچ فایل تولیدشده‌ای بدون ردیف دیتابیس وجود ندارد**، و نام فایل‌ها",
            "  UUID است نه ورودی کاربر.",
            "- **قیمت و موجودی فقط از این جدول‌ها خوانده می‌شود.** مدل زبانی آن‌ها را",
            "  قالب‌بندی می‌کند؛ هرگز نمی‌سازدشان.",
            "",
            f"<sub>{total} مدل در {len(seen)} اپ.</sub>",
            "",
        ]

        text = "\n".join(out)
        if options["write"]:
            # apps/jobs/management/commands/schemadoc.py → بالا تا Code/UpMarket/
            target = Path(__file__).resolve().parents[5] / "docs" / "DATABASE.md"
            target.write_text(text, encoding="utf-8", newline="\n")
            self.stdout.write(self.style.SUCCESS(
                f"{total} مدل در {len(seen)} اپ نوشته شد → {target}"))
        else:
            self.stdout.write(text)
