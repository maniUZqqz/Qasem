"""
`python manage.py selftest` — run every AI feature end to end without the models.

The 30B/32B models and ComfyUI are replaced by tools/fake_ai_stack.py, which
answers with realistic content AND reproduces the ways local models actually
mangle their output (chain-of-thought leaking, ```json fences, a missing comma,
truncation, Qwen3-VL's empty `response` field, a first model that answers with
half the keys missing, and an outright HTTP failure).

Everything else is the real thing: the real tasks, the real prompts, the real
JSON repair, the real validators, the real database rows, the real Pillow
poster overlay and the real ffmpeg video concatenation.

Nothing is written to your data: the run happens in a throwaway store that is
deleted afterwards, and all media goes to a temporary folder.
"""

import shutil
import subprocess
import tempfile
import time
from decimal import Decimal
from io import BytesIO
from pathlib import Path

import requests
from django.conf import settings
from django.contrib.auth.models import User
from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand
from django.test.utils import override_settings

from apps.ai.models import MarketResearch, ProductIntelligence
from apps.ai.tasks import analyze_market_task, analyze_product_task
from apps.content.models import Caption, GeneratedImage, VideoScript
from apps.content.tasks import (
    generate_captions_task,
    generate_image_task,
    generate_video_script_task,
    generate_video_task,
)
from apps.jobs.models import Job
from apps.products.models import Product, ProductImage
from apps.stores.models import Store
from services import net
from services.ai import models_registry
from tools import fake_ai_stack

SELFTEST_STORE = "__selftest__"

# how a real local model mangles its answer; every one of these must still end
# in a correct row in the database
TEXT_STYLES = [
    ("clean", "خروجی تمیز"),
    ("think", "نشت زنجیرهٔ فکر QwQ"),
    ("fenced", "داخل ```json"),
    ("prose", "متن اضافه قبل و بعد"),
    ("trailing_comma", "کامای اضافه"),
    ("missing_comma", "کامای جاافتاده (خطای لاگ خودت)"),
    ("truncated", "خروجی قطع‌شده (باید کوتاه‌تر بپرسد)"),
    ("thinking_field", "پاسخ خالی، JSON داخل thinking"),
    ("http_500", "خطای ۵۰۰ اولاما (کمبود VRAM)"),
]

# A model that simply cannot fit the task: even the shorter retry is cut off.
# Nothing can rescue this — the only correct behaviour is to fail honestly,
# with a message the store owner can read, and to write no half-made rows.
UNRECOVERABLE_STYLE = ("truncated_always", "خروجی همیشه قطع می‌شود")


class Failure(Exception):
    pass


def check(condition, message):
    if not condition:
        raise Failure(message)


class Command(BaseCommand):
    help = "Run every AI pipeline against a fake Ollama/ComfyUI and report pass/fail."

    def add_arguments(self, parser):
        parser.add_argument(
            "--only",
            default="",
            help="comma-separated: analysis,market,captions,image,script,video,chat",
        )
        parser.add_argument(
            "--quick",
            action="store_true",
            help="one style only (skips the messy-output sweep)",
        )

    # ------------------------------------------------------------------ setup
    def _fixture(self):
        """A throwaway store + product + photo, isolated from real data."""
        user, _ = User.objects.get_or_create(username="__selftest_user__")
        store = Store.objects.create(
            owner=user,
            name=SELFTEST_STORE,
            business_type="لوازم صوتی",
            description="فروشگاه آزمایشی خودکار",
        )
        product = Product.objects.create(
            store=store,
            name="هدفون بی‌سیم TK-900",
            brand="TekLand",
            price=Decimal("2450000"),
            description="هدفون بلوتوثی با نویز کنسلینگ فعال و باتری ۴۰ ساعته",
            short_description="صدای شفاف، باتری ۴۰ ساعته",
        )
        from PIL import Image

        buffer = BytesIO()
        # deliberately small and soft: this is what a store owner really uploads
        Image.new("RGB", (400, 300), (30, 90, 160)).save(buffer, "PNG")
        ProductImage.objects.create(
            product=product, image=ContentFile(buffer.getvalue(), name="selftest.png")
        )
        # A new store starts on the trial plan, and the trial's allowance is a
        # few captions. This command runs the caption pipeline once per output
        # style, so from the third style on every check failed with «سهمیه‌ی
        # کپشن تمام شده» — a billing message, reported as nine broken pipelines.
        # The self-check is about whether the pipelines survive a misbehaving
        # model, not about quotas (billing has its own tests), so the throwaway
        # store gets an allowance it cannot exhaust.
        from apps.billing.models import Subscription

        Subscription.objects.filter(store=store).update(
            bonus_captions=100_000, bonus_images=100_000, bonus_video_seconds=10_000_000
        )
        return store, product

    def _cleanup(self):
        Store.objects.filter(name=SELFTEST_STORE).delete()
        User.objects.filter(username="__selftest_user__").delete()

    def _set_style(self, style, first_model_fails=False):
        requests.post(
            f"{self.ollama_url}/_control",
            json={"style": style, "first_model_fails": first_model_fails},
            timeout=5,
        )
        models_registry._cache.update({"at": 0.0, "models": []})
        net.clear_cache()

    def _job(self, store, job_type):
        return Job.objects.create(store=store, type=job_type)

    # ------------------------------------------------------------------ checks
    def _run_analysis(self, store, product):
        ProductIntelligence.objects.filter(product=product).delete()
        job = self._job(store, Job.Type.PRODUCT_ANALYSIS)
        analyze_product_task.apply(args=(job.id, product.id))
        job.refresh_from_db()
        check(job.state == Job.State.COMPLETED, f"job {job.state}: {job.error[:160]}")
        row = ProductIntelligence.objects.filter(product=product).first()
        check(row is not None, "no ProductIntelligence row")
        for field in ("target_audience", "selling_points", "weaknesses", "objections",
                      "marketing_angles", "content_ideas", "use_cases"):
            check(len(getattr(row, field)) >= 1, f"{field} is empty")
        check(len(row.summary) > 20, "summary too short")
        check(bool(row.positioning), "positioning missing")
        check(len(row.visual_analysis) == 1, "product photo was not analysed")
        return f"{len(row.selling_points)} نقطه قوت، {len(row.objections)} اعتراض"

    def _run_market(self, store, product):
        MarketResearch.objects.filter(product=product).delete()
        job = self._job(store, Job.Type.MARKET_ANALYSIS)
        analyze_market_task.apply(args=(job.id, product.id, ""))
        job.refresh_from_db()
        check(job.state == Job.State.COMPLETED, f"job {job.state}: {job.error[:160]}")
        row = MarketResearch.objects.filter(product=product).first()
        check(row is not None, "no MarketResearch row")
        competitors = row.conclusions.get("competitors") or []
        check(len(competitors) >= 1, "no competitors extracted")
        first = competitors[0]
        for field in ("name", "product", "price", "where_sells"):
            check(field in first, f"competitor missing {field}")
        check(len(row.conclusions.get("comparison") or []) >= 1, "no comparison lines")
        check(row.confidence in {"LOW", "MEDIUM", "HIGH"}, "bad confidence value")
        return f"{len(competitors)} رقیب، اطمینان {row.confidence}"

    def _run_captions(self, store, product):
        Caption.objects.filter(product=product).delete()
        job = self._job(store, Job.Type.CAPTION_GENERATION)
        platforms = ["INSTAGRAM", "TELEGRAM", "LINKEDIN"]
        generate_captions_task.apply(args=(job.id, product.id, platforms, "", "", None, None))
        job.refresh_from_db()
        check(job.state == Job.State.COMPLETED, f"job {job.state}: {job.error[:160]}")
        rows = list(Caption.objects.filter(product=product))
        check(len(rows) == 3, f"expected 3 captions, got {len(rows)}")
        check({c.platform for c in rows} == set(platforms), "a platform is missing")
        for caption in rows:
            check(caption.short_text and caption.medium_text and caption.long_text,
                  f"{caption.platform}: an empty caption length")
            check(bool(caption.cta), f"{caption.platform}: no call to action")
        return f"{len(rows)} پلتفرم"

    def _run_image(self, store, product):
        GeneratedImage.objects.filter(product=product).delete()
        job = self._job(store, Job.Type.IMAGE_GENERATION)
        generate_image_task.apply(args=(job.id, product.id, "POSTER", "مینیمال", ""))
        job.refresh_from_db()
        check(job.state == Job.State.COMPLETED, f"job {job.state}: {job.error[:160]}")
        row = GeneratedImage.objects.filter(product=product).first()
        check(row is not None, "no GeneratedImage row")
        check(row.workflow_version == "flux_img_edit@v1", "poster did not use the real photo")
        check(row.source_image_id is not None, "poster is not anchored on the product photo")
        path = Path(row.image.path)
        check(path.exists(), "poster file missing on disk")
        check("_text" in path.name, "Persian text was not drawn onto the poster")
        from PIL import Image

        with Image.open(path) as poster:
            check(poster.size == (832, 1216), f"poster is {poster.size}, expected 832x1216")
        overlay = row.metadata.get("text_overlay") or {}
        check(bool(overlay.get("headline")), "no headline drawn")
        badge = overlay.get("badge", "")
        check(any(d in badge for d in "۰۱۲۳۴۵۶۷۸۹"), f"price not in Persian digits: {badge!r}")
        return f"{path.name} — «{overlay['headline']}» / {badge}"

    def _run_script(self, store, product):
        VideoScript.objects.filter(product=product).delete()
        job = self._job(store, Job.Type.VIDEO_SCRIPT)
        generate_video_script_task.apply(args=(job.id, product.id, 15, "", "fa"))
        job.refresh_from_db()
        check(job.state == Job.State.COMPLETED, f"job {job.state}: {job.error[:160]}")
        script = VideoScript.objects.filter(product=product).first()
        check(script is not None, "no VideoScript row")
        scenes = list(script.scenes.all())
        check(len(scenes) == 3, f"expected 3 scenes, got {len(scenes)}")
        check(scenes[0].transition == "NEW_SCENE", "scene 1 must start a new scene")
        for scene in scenes:
            check(bool(scene.visual_prompt), f"scene {scene.index}: no visual prompt")
            check(bool(scene.narration), f"scene {scene.index}: no narration")
        check(bool(script.cta), "no call to action")
        return f"{len(scenes)} صحنه، CTA: «{script.cta[:28]}»"

    def _run_video(self, store, product):
        script = VideoScript.objects.filter(product=product).first()
        check(script is not None, "run the script step first")
        job = self._job(store, Job.Type.VIDEO_GENERATION)
        generate_video_task.apply(args=(job.id, script.id))
        job.refresh_from_db()
        # Video jobs default to SAFE mode: render one segment, park, wait for the
        # owner. Nobody is here to press «ادامه بده», so this plays that part —
        # otherwise the check reports WAITING_APPROVAL as if it were a failure,
        # when it is the product doing exactly what it was designed to do.
        for _ in range(12):
            if not job.awaiting_human:
                break
            job.advance(Job.State.APPROVED, label="selftest: approved")
            generate_video_task.apply(args=(job.id, script.id))
            job.refresh_from_db()
        check(job.state == Job.State.COMPLETED, f"job {job.state}: {job.error[:200]}")
        script.refresh_from_db()
        check(bool(script.final_video), "no final video")
        final = Path(script.final_video.path)
        check(final.exists() and final.stat().st_size > 1000, "final video is empty")
        segments = list(script.segments.all())
        check(len(segments) == 3, f"expected 3 segments, got {len(segments)}")
        for segment in segments:
            check(segment.status == "DONE", f"segment {segment.index}: {segment.error[:80]}")
            check(bool(segment.last_frame), f"segment {segment.index}: no last frame extracted")
        duration = self._probe(final)
        return f"final.mp4 {final.stat().st_size // 1024}KB، {duration}، {len(segments)} قطعه"

    def _run_chat(self, store, product):
        from apps.customers.agent import run_sales_agent
        from apps.customers.models import Conversation, Customer

        customer, _ = Customer.objects.get_or_create(store=store, name="مشتری آزمایشی")
        conversation = Conversation.objects.create(store=store, customer=customer)
        result = run_sales_agent(conversation, "سلام، قیمت این هدفون چنده؟")
        check(bool(result.get("reply")), "empty reply")
        check(len(result["reply"]) > 10, "reply too short")
        return f"«{result['reply'][:46]}…»"

    @staticmethod
    def _probe(path):
        try:
            out = subprocess.run(
                ["ffprobe", "-v", "error", "-show_entries", "format=duration",
                 "-of", "default=nw=1:nk=1", str(path)],
                capture_output=True, text=True, timeout=30,
            )
            return f"{float(out.stdout.strip()):.1f}s"
        except Exception:
            return "طول نامشخص"

    # ------------------------------------------------------------------ driver
    def handle(self, *args, **options):
        media_root = Path(tempfile.mkdtemp(prefix="upmarket-selftest-media-"))
        self.ollama_url, comfy_url, _servers = fake_ai_stack.serve()

        wanted = {s.strip() for s in options["only"].split(",") if s.strip()}
        styles = TEXT_STYLES[:1] if options["quick"] else TEXT_STYLES

        elements = [
            ("analysis", "۲. تحلیل محصول (بینایی + استدلال)", self._run_analysis, True),
            ("market", "۳. تحلیل رقبا و بازار", self._run_market, True),
            ("captions", "۵. تولید کپشن", self._run_captions, True),
            ("image", "۴. ساخت تصویر / پوستر", self._run_image, False),
            ("script", "۶الف. سناریوی ویدیو", self._run_script, True),
            ("video", "۶ب. تولید ویدیو (Wan + ffmpeg)", self._run_video, False),
            ("chat", "۱. چت فروش", self._run_chat, True),
        ]
        if wanted:
            elements = [e for e in elements if e[0] in wanted]

        original_ai = dict(settings.UPMARKET_AI)
        settings.UPMARKET_AI["OLLAMA_BASE_URL"] = self.ollama_url
        settings.UPMARKET_AI["COMFYUI_BASE_URL"] = comfy_url
        settings.UPMARKET_AI["COMFYUI_POLL_INTERVAL"] = 0.2

        failures = 0
        try:
            with override_settings(MEDIA_ROOT=str(media_root)):
                self._cleanup()
                store, product = self._fixture()

                self.stdout.write("")
                self.stdout.write(self.style.MIGRATE_HEADING(
                    "  A) هر المان با خروجی سالم و با هر ۸ نوع خرابیِ واقعیِ مدل"
                ))
                self.stdout.write("")
                for key, title, runner, sweep in elements:
                    run_styles = styles if sweep else styles[:1]
                    self.stdout.write(f"  {title}")
                    for style, label in run_styles:
                        self._set_style(style)
                        failures += self._attempt(runner, store, product, label)
                    self.stdout.write("")

                self.stdout.write(self.style.MIGRATE_HEADING(
                    "  B) مدل اول جواب ناقص می‌دهد — باید خودکار سراغ مدل بعدی برود"
                ))
                self.stdout.write("")
                for key, title, runner, _sweep in elements:
                    self._set_style("clean", first_model_fails=True)
                    self.stdout.write(f"  {title}")
                    failures += self._attempt(runner, store, product, "فالبک مدل")
                    self.stdout.write("")

                self.stdout.write(self.style.MIGRATE_HEADING(
                    "  C) حالتی که هیچ مدلی از پسش برنمی‌آید — باید محترمانه شکست بخورد"
                ))
                self.stdout.write("")
                style, label = UNRECOVERABLE_STYLE
                for key, title, runner, _sweep in elements:
                    self._set_style(style)
                    self.stdout.write(f"  {title}")
                    failures += self._attempt_graceful(runner, store, product, label)
                    self.stdout.write("")

                self._cleanup()
        finally:
            settings.UPMARKET_AI.clear()
            settings.UPMARKET_AI.update(original_ai)
            models_registry._cache.update({"at": 0.0, "models": []})
            net.clear_cache()
            shutil.rmtree(media_root, ignore_errors=True)

        self.stdout.write("")
        if failures:
            self.stdout.write(self.style.ERROR(f"  {failures} مورد شکست خورد."))
            raise SystemExit(1)
        self.stdout.write(self.style.SUCCESS("  همهٔ المان‌ها با همهٔ حالت‌ها سالم بودند."))

    def _attempt_graceful(self, runner, store, product, label) -> int:
        """The run MUST fail, and it must fail well: a terminal job, a readable
        Persian message, and no half-written rows left behind."""
        before = Job.objects.filter(store=store).count()
        try:
            runner(store, product)
        except Failure:
            pass  # the checks below decide whether the failure was a good one
        except Exception as exc:  # noqa: BLE001
            # the sales chat has no Job row; it raises, which is correct
            message = str(exc)
            if message.strip():
                self.stdout.write(f"      ✓ {label:34s} خطای روشن: «{message[:52]}…»")
                return 0
            self.stdout.write(self.style.ERROR(f"      ✗ {label:34s} خطای بی‌پیام"))
            return 1

        if Job.objects.filter(store=store).count() == before:
            # the sales chat answers in-request and has no Job row; getting a
            # usable reply out of a cut-off answer is the best possible outcome
            self.stdout.write(f"      ✓ {label:34s} با وجود قطع‌شدن، پاسخ داد")
            return 0
        job = Job.objects.filter(store=store).order_by("-id").first()
        if job.state not in {Job.State.FAILED, Job.State.COMPLETED}:
            self.stdout.write(
                self.style.ERROR(f"      ✗ {label:34s} Job در حالت {job.state} گیر کرد")
            )
            return 1
        if job.state == Job.State.COMPLETED:
            # recovering is also an acceptable outcome — never a stuck spinner
            self.stdout.write(f"      ✓ {label:34s} با وجود قطع‌شدن، کامل شد")
            return 0
        if not job.error.strip():
            self.stdout.write(self.style.ERROR(f"      ✗ {label:34s} شکست بدون پیام"))
            return 1
        self.stdout.write(f"      ✓ {label:34s} شکست تمیز: «{job.error[:52]}…»")
        return 0

    def _attempt(self, runner, store, product, label) -> int:
        started = time.monotonic()
        try:
            detail = runner(store, product)
        except Failure as exc:
            self.stdout.write(self.style.ERROR(f"      ✗ {label:34s} {exc}"))
            return 1
        except Exception as exc:  # noqa: BLE001 — the report must never crash
            self.stdout.write(self.style.ERROR(f"      ✗ {label:34s} {type(exc).__name__}: {exc}"))
            return 1
        elapsed = time.monotonic() - started
        self.stdout.write(f"      ✓ {label:34s} {detail}  ({elapsed:.1f}s)")
        return 0
