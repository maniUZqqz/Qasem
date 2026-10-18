"""`python manage.py aisetup` — ask once which engines this machine runs.

The launcher used to have a single all-or-nothing switch: either everything
local, or everything through an API. That is the wrong shape for the real
situation, which is usually mixed — a machine with a GPU good enough for images
but not for forty-minute video renders, or a laptop that wants text from an API
while ComfyUI runs on the desktop next door.

So this asks three separate questions (text, image, video) and writes the
answers into `backend/.env`. `start.bat` then launches **only what is still
needed**: Ollama only if text or vision stayed local, ComfyUI only if image or
video did.

Why the asking lives here and not in the batch file: the launcher has already
been bitten twice by `cmd.exe` — a `findstr` regex that ate a caret, and a
Python-written path where `\\node_modules` became a real newline. Batch is a bad
place for logic and a worse place for Persian text. It calls this instead.
"""
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand

from services.ai import providers

ENV_PATH = Path(settings.BASE_DIR) / ".env"

QUESTIONS = [
    {
        "key": "AI_MODE_TEXT",
        "title": "متن، تحلیل و ایجنت فروش",
        "local": "روی همین سیستم با Ollama",
        "api": "با API سازگار با OpenAI",
        "needs": ["AI_API_BASE_URL", "AI_API_KEY"],
        "engine": "Ollama",
    },
    {
        "key": "AI_MODE_IMAGE",
        "title": "تولید تصویر و پوستر",
        "local": "روی همین سیستم با ComfyUI (FLUX)",
        "api": "با API تصویر",
        "needs": ["MEDIA_API_TOKEN"],
        "engine": "ComfyUI",
    },
    {
        "key": "AI_MODE_VIDEO",
        "title": "تولید ویدیو",
        "local": "روی همین سیستم با ComfyUI (Wan 2.2)",
        "api": "با API ویدیو",
        "needs": ["MEDIA_API_TOKEN"],
        "engine": "ComfyUI",
    },
]


def read_env() -> dict:
    values = {}
    if not ENV_PATH.exists():
        return values
    for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip()
    return values


def write_env(updates: dict) -> None:
    """Update keys in place, appending any that are new.

    Rewritten line by line rather than regenerated, so comments the operator
    wrote and keys this command knows nothing about survive.
    """
    lines = ENV_PATH.read_text(encoding="utf-8").splitlines() if ENV_PATH.exists() else []
    seen = set()
    out = []
    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            key = stripped.split("=", 1)[0].strip()
            if key in updates:
                out.append(f"{key}={updates[key]}")
                seen.add(key)
                continue
        out.append(line)

    missing = {k: v for k, v in updates.items() if k not in seen}
    if missing:
        out.append("")
        out.append("# ---- انتخاب موتور هوش مصنوعی (از manage.py aisetup) ----")
        out.extend(f"{k}={v}" for k, v in missing.items())

    ENV_PATH.parent.mkdir(parents=True, exist_ok=True)
    ENV_PATH.write_text("\n".join(out) + "\n", encoding="utf-8")


class Command(BaseCommand):
    help = "پرسیدن اینکه متن/تصویر/ویدیو روی این سیستم اجرا شوند یا با API"

    def add_arguments(self, parser):
        parser.add_argument(
            "--show", action="store_true",
            help="فقط وضعیت فعلی را نشان بده و چیزی نپرس",
        )
        parser.add_argument(
            "--if-unset", action="store_true",
            help="فقط وقتی بپرس که هنوز انتخابی ثبت نشده (برای start.bat)",
        )

    # ------------------------------------------------------------------

    def handle(self, *args, **options):
        current = read_env()

        if options["show"]:
            self._show(current)
            return

        already = all(current.get(q["key"]) for q in QUESTIONS)
        if options["if_unset"] and already:
            self._show(current)
            return

        if not self._interactive():
            self.stdout.write(self.style.WARNING(
                "ورودی تعاملی در دسترس نیست؛ چیزی عوض نشد.\n"
                "برای تنظیم دستی، AI_MODE_TEXT / AI_MODE_IMAGE / AI_MODE_VIDEO را "
                "در backend/.env روی local یا api بگذارید."
            ))
            return

        self._ask(current)

    # ------------------------------------------------------------------

    def _interactive(self) -> bool:
        """Is there a person to ask?

        `isatty()` is the best signal available and it is not conclusive — a
        console can exist with no readable stdin. So the question loop also
        survives EOF; this check only avoids printing a menu nobody will see.
        """
        import sys

        try:
            return sys.stdin is not None and sys.stdin.isatty()
        except Exception:  # noqa: BLE001
            return False

    def _ask(self, current: dict) -> None:
        self.stdout.write("")
        self.stdout.write(self.style.MIGRATE_HEADING(
            "هر بخش را کجا اجرا کنیم؟"
        ))
        self.stdout.write(
            "  می‌توانی هرکدام را جدا انتخاب کنی. هر چیزی که API بشود، موتور\n"
            "  محلی‌اش هم دیگر بالا نمی‌آید.\n"
        )

        updates = {}
        for question in QUESTIONS:
            existing = current.get(question["key"], "")
            default = existing if existing in ("local", "api") else "local"

            self.stdout.write("")
            self.stdout.write(self.style.SUCCESS(f"  {question['title']}"))
            self.stdout.write(f"    1) {question['local']}")
            self.stdout.write(f"    2) {question['api']}")
            try:
                answer = input(f"    انتخاب [{'1' if default == 'local' else '2'}]: ").strip()
            except (EOFError, KeyboardInterrupt):
                # No console after all — a scheduled task, a piped run, or the
                # user pressing Ctrl+C. Keep the default and stop asking rather
                # than taking the whole launcher down with a traceback.
                self.stdout.write("")
                self.stdout.write(self.style.WARNING(
                    "    ورودی در دسترس نبود؛ همان مقدار پیش‌فرض ماند."
                ))
                answer = ""
                updates[question["key"]] = default
                for remaining in QUESTIONS[QUESTIONS.index(question) + 1:]:
                    existing_other = current.get(remaining["key"], "")
                    updates[remaining["key"]] = (
                        existing_other if existing_other in ("local", "api") else "local"
                    )
                break

            if answer == "2":
                choice = "api"
            elif answer == "1":
                choice = "local"
            else:
                choice = default
            updates[question["key"]] = choice

            if choice == "api":
                missing = [k for k in question["needs"] if not current.get(k)]
                if missing:
                    self.stdout.write(self.style.WARNING(
                        f"    ⚠ برای API به {'، '.join(missing)} نیاز است. "
                        "تا وقتی پر نشود، همان موتور محلی استفاده می‌شود."
                    ))

        write_env(updates)
        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("ذخیره شد در backend/.env"))
        self.stdout.write("")
        # Re-read through Django so what is shown is what the product will do,
        # not what was just typed.
        self._show(read_env(), reloaded=True)

    def _show(self, current: dict, reloaded: bool = False) -> None:
        if reloaded:
            for question in QUESTIONS:
                settings.UPMARKET_AI[question["key"]] = current.get(question["key"], "")

        rows = [
            ("متن و تحلیل", providers.TEXT),
            ("تحلیل تصویر", providers.VISION),
            ("تولید تصویر", providers.IMAGE),
            ("تولید ویدیو", providers.VIDEO),
        ]
        self.stdout.write(self.style.MIGRATE_HEADING("الان چه چیزی کجا اجرا می‌شود"))
        for label, capability in rows:
            local = providers.uses_own_gpu(capability)
            where = "🖥️  این سیستم" if local else "☁️  API"
            self.stdout.write(f"  {label:<14} {where}")

        needed = providers.local_services_needed()
        self.stdout.write("")
        self.stdout.write(self.style.MIGRATE_HEADING("موتورهایی که باید بالا بیایند"))
        if needed:
            for service in sorted(needed):
                self.stdout.write(f"  • {service}")
        else:
            self.stdout.write("  هیچ‌کدام — این سیستم به کارت گرافیک نیاز ندارد.")
