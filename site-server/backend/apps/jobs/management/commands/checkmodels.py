"""
`python manage.py checkmodels` — do the models this project asks for actually
exist on THIS machine, under exactly these names?

This is the one class of failure the fake-model tests structurally cannot
catch. `tools/e2e_api_test.py` proves the pipeline is correct, but its fake
ComfyUI accepts any filename, and its fake Ollama reports whatever model list
we tell it to. On the real machine a single character in a filename
(`wan2.2_...` vs `wan_2.2_...`) makes every render fail with a node validation
error deep inside a job, minutes after the user pressed the button.

So: ask the real services what they have, compare it with what the workflow
templates and the .env actually request, and name the mismatch up front.
"""
import difflib
import json

import requests
from django.conf import settings
from django.core.management.base import BaseCommand

from services.comfyui.workflows import WORKFLOWS_DIR
from services.net import is_listening

TIMEOUT = 15

# ComfyUI loader class → (workflow input field, /object_info field holding the
# list of files ComfyUI can actually see)
LOADER_FIELDS = {
    "CheckpointLoaderSimple": "ckpt_name",
    "UNETLoader": "unet_name",
    "CLIPLoader": "clip_name",
    "VAELoader": "vae_name",
    "LoraLoaderModelOnly": "lora_name",
    "LoraLoader": "lora_name",
    "CLIPVisionLoader": "clip_name",
}


class Command(BaseCommand):
    help = "Check that every Ollama and ComfyUI model this project needs is installed."

    def add_arguments(self, parser):
        parser.add_argument(
            "--strict",
            action="store_true",
            help="exit non-zero when anything is missing (for scripts)",
        )

    # ------------------------------------------------------------------ output
    def ok(self, message):
        self.stdout.write(self.style.SUCCESS(f"  [OK]   {message}"))

    def bad(self, message):
        self.stdout.write(self.style.ERROR(f"  [MISS] {message}"))

    def warn(self, message):
        self.stdout.write(self.style.WARNING(f"  [WARN] {message}"))

    def hint(self, message):
        self.stdout.write(f"         {message}")

    def skipped(self, what):
        """Record that a service could not be reached, so the summary cannot
        claim everything is fine when nothing was actually compared."""
        self._unchecked.append(what)

    @staticmethod
    def _closest(name, pool):
        """The installed name most likely meant — filename typos are the point."""
        matches = difflib.get_close_matches(name, pool, n=1, cutoff=0.6)
        return matches[0] if matches else None

    # ------------------------------------------------------------------ ollama
    def check_ollama(self) -> int:
        conf = settings.UPMARKET_AI
        base = conf["OLLAMA_BASE_URL"].rstrip("/")
        self.stdout.write(self.style.MIGRATE_HEADING(f"\nOllama — {base}"))

        if not is_listening(base):
            self.warn("Ollama پاسخ نمی‌دهد؛ روشنش کن یا OLLAMA_BASE_URL را درست کن.")
            self.hint("بدون Ollama هیچ تحلیل/کپشن/سناریو/چتی کار نمی‌کند.")
            self.skipped("Ollama")
            return 0  # not a name mismatch — nothing to compare against

        try:
            response = requests.get(f"{base}/api/tags", timeout=TIMEOUT)
            response.raise_for_status()
            installed = [
                m.get("name") or m.get("model") or "" for m in response.json().get("models", [])
            ]
            installed = [name for name in installed if name]
        except (requests.RequestException, ValueError) as exc:
            self.warn(f"لیست مدل‌های Ollama خوانده نشد: {exc}")
            self.skipped("Ollama")
            return 0

        self.hint(f"نصب‌شده: {', '.join(installed) or '(هیچ)'}")

        wanted = [
            ("REASONING (تحلیل، سناریو، چت)", conf["MODEL_REASONING"], True),
            ("VISION (تحلیل عکس محصول)", conf["MODEL_VISION"], True),
            ("CODER", conf["MODEL_CODER"], False),
        ]
        if conf.get("EMBEDDINGS_ENABLED"):
            wanted.append(("EMBEDDING (جستجوی معنایی)", conf["MODEL_EMBEDDING"], True))

        # `qwq` and `qwq:32b` are the same model to us (services.ai.models_registry)
        from services.ai import models_registry

        missing = 0
        for label, name, important in wanted:
            resolved = models_registry.resolve_installed(name)
            if resolved:
                self.ok(f"{label}: {resolved}")
                continue
            suggestion = self._closest(name, installed)
            if important:
                missing += 1
                self.bad(f"{label}: «{name}» نصب نیست")
            else:
                self.warn(f"{label}: «{name}» نصب نیست")
            if suggestion:
                self.hint(f"نزدیک‌ترین چیزی که داری: «{suggestion}»")
            self.hint(f"نصب: ollama pull {name}")

        if missing:
            self.hint(
                "نکته: اگر مدلی نصب نباشد، برنامه خودکار سراغ مدل نصب‌شدهٔ بعدی می‌رود، "
                "ولی کیفیت خروجی همانی نیست که انتظار داری."
            )
        return missing

    # ------------------------------------------------------------------ comfyui
    def _comfy_available(self, base, class_type, field):
        """Filenames ComfyUI can actually see for one loader input."""
        try:
            response = requests.get(f"{base}/object_info/{class_type}", timeout=TIMEOUT)
            response.raise_for_status()
            info = response.json().get(class_type) or {}
            spec = (info.get("input") or {}).get("required", {}).get(field)
            # ComfyUI shape: [[ "a.safetensors", "b.safetensors" ], {...options}]
            if isinstance(spec, list) and spec and isinstance(spec[0], list):
                return [str(item) for item in spec[0]]
        except (requests.RequestException, ValueError, KeyError, IndexError):
            return None
        return None

    def check_comfyui(self) -> int:
        base = settings.UPMARKET_AI["COMFYUI_BASE_URL"].rstrip("/")
        self.stdout.write(self.style.MIGRATE_HEADING(f"\nComfyUI — {base}"))

        # what the workflow templates demand, grouped by loader class
        required = {}
        for path in sorted(WORKFLOWS_DIR.glob("*_v1.json")):
            try:
                graph = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                self.bad(f"ورک‌فلو {path.name} خوانده نشد: {exc}")
                return 1
            for node in graph.values():
                class_type = node.get("class_type")
                field = LOADER_FIELDS.get(class_type)
                if not field:
                    continue
                value = (node.get("inputs") or {}).get(field)
                if isinstance(value, str) and value:
                    required.setdefault((class_type, field), set()).add(value)

        if not required:
            self.warn("هیچ ورک‌فلویی مدل نمی‌خواهد — این عجیب است.")
            return 0

        if not is_listening(base):
            self.warn("ComfyUI پاسخ نمی‌دهد؛ نمی‌شود نام فایل‌ها را با آن مقایسه کرد.")
            self.hint("این ورک‌فلوها دقیقاً این فایل‌ها را می‌خواهند:")
            for (class_type, _field), names in sorted(required.items()):
                for name in sorted(names):
                    self.hint(f"  • {name}   ({class_type})")
            self.hint(
                "ComfyUI را روشن کن و دوباره این دستور را بزن تا مطابقت واقعاً چک شود."
            )
            self.skipped("ComfyUI")
            return 0

        missing = 0
        for (class_type, field), names in sorted(required.items()):
            available = self._comfy_available(base, class_type, field)
            if available is None:
                self.warn(f"{class_type}: لیست فایل‌ها از ComfyUI گرفته نشد")
                self.skipped(f"ComfyUI/{class_type}")
                continue
            for name in sorted(names):
                if name in available:
                    self.ok(f"{class_type}: {name}")
                    continue
                missing += 1
                self.bad(f"{class_type}: «{name}» در ComfyUI نیست")
                suggestion = self._closest(name, available)
                if suggestion:
                    self.hint(f"نزدیک‌ترین فایل موجود: «{suggestion}»")
                    self.hint(
                        "یا فایل را به همین نام تغییر بده، یا نام را در "
                        f"backend/services/comfyui/workflows/ اصلاح کن."
                    )
                elif available:
                    self.hint(f"موجود در این دسته: {', '.join(sorted(available)[:6])}")
                else:
                    self.hint("ComfyUI هیچ فایلی در این دسته نمی‌بیند — مسیر models را چک کن.")
        return missing

    # ------------------------------------------------------------------ driver
    def handle(self, *args, **options):
        self._unchecked = []
        self.stdout.write(
            self.style.MIGRATE_HEADING(
                "\n  آیا مدل‌هایی که این پروژه می‌خواهد، با همین نام‌ها روی این سیستم هستند؟"
            )
        )
        missing = self.check_ollama() + self.check_comfyui()

        self.stdout.write("")
        if missing:
            self.stdout.write(
                self.style.ERROR(
                    f"  {missing} مدل با نام درست پیدا نشد — تا این حل نشود، همان "
                    "بخش‌ها روی سیستم اصلی شکست می‌خورند."
                )
            )
            if options["strict"]:
                raise SystemExit(1)
        elif self._unchecked:
            # never claim success for something we could not look at
            self.stdout.write(
                self.style.WARNING(
                    "  چک نشد: " + "، ".join(dict.fromkeys(self._unchecked))
                    + " — این سرویس‌ها خاموش بودند، پس مطابقت نام مدل‌ها هنوز معلوم نیست."
                )
            )
            if options["strict"]:
                raise SystemExit(1)
        else:
            self.stdout.write(
                self.style.SUCCESS("  هر مدلی که پروژه می‌خواهد، با همان نام موجود است.")
            )
        self.stdout.write("")
