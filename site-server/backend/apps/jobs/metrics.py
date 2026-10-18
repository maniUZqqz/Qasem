"""Recording how long each render actually took.

Phase 0.5 is the gate the whole roadmap waits behind, and its DoD is "a
benchmark report with real numbers exists". Right now the capacity model rests
on two remembered runs — 15 minutes and 45 minutes for five seconds of video —
and the gap between those two numbers is the gap between a viable business and
one that cannot reach its own break-even.

The benchmark cannot be run here: this machine has no GPU. What can be built
here is the part that makes the benchmark a by-product of ordinary use instead
of a separate exercise someone has to remember to write down. Every render
records what it cost, `manage.py benchmark` reports the distribution, and the
numbers stop being remembered.

Two deliberate choices:

* **Nothing is averaged across machines.** A 3060 and a 4090 produce different
  numbers, and their mean describes neither. Rows carry a hardware
  fingerprint and the report groups by it.
* **Failures are recorded too.** A pipeline that succeeds in 4 minutes but
  fails a third of the time costs 6 minutes per usable output, and a table of
  successful renders would hide that completely.
"""
from __future__ import annotations

import logging
import time

from django.db import models

from apps.common.models import TimeStampedModel

logger = logging.getLogger(__name__)


class RenderMetric(TimeStampedModel):
    """One measured unit of generation work."""

    class Kind(models.TextChoices):
        VIDEO_SEGMENT = "VIDEO_SEGMENT", "قطعه ویدیو"
        IMAGE = "IMAGE", "تصویر"
        TEXT = "TEXT", "متن / تحلیل"
        VISION = "VISION", "تحلیل تصویر"
        MODEL_SWAP = "MODEL_SWAP", "جابه‌جایی مدل روی کارت"
        AUDIO = "AUDIO", "صداگذاری"

    kind = models.CharField(max_length=16, choices=Kind.choices)
    #: Workflow or model name, e.g. "wan22_i2v@v1" or "qwq:32b". The unit of
    #: comparison — a number without it answers no question worth asking.
    engine = models.CharField(max_length=120)
    #: Machine class these numbers came from. Never averaged across values.
    hardware = models.CharField(max_length=120)

    #: Wall-clock seconds. Wall clock, not CPU time: the customer waits on the
    #: wall clock, including model loads and queue waits inside the task.
    duration_s = models.FloatField()
    #: How much output this produced — seconds of video, or 1 for an image.
    #: The ratio of the two is the number the capacity model needs.
    output_units = models.FloatField(default=1)

    resolution = models.CharField(max_length=20, blank=True)
    vram_peak_mb = models.PositiveIntegerField(null=True, blank=True)
    #: Time spent getting the model onto the card before any real work. On a
    #: single-GPU machine that swaps between Ollama and ComfyUI this is not a
    #: rounding error; §8.5 wants it in the capacity formula explicitly.
    load_s = models.FloatField(null=True, blank=True)

    succeeded = models.BooleanField(default=True)
    error_kind = models.CharField(max_length=80, blank=True)
    retry_count = models.PositiveSmallIntegerField(default=0)

    job = models.ForeignKey(
        "jobs.Job", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="metrics",
    )
    store = models.ForeignKey(
        "stores.Store", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="render_metrics",
    )
    context = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["kind", "engine", "hardware"]),
            models.Index(fields=["-created_at"]),
        ]
        verbose_name = "اندازه‌گیری رندر"
        verbose_name_plural = "اندازه‌گیری‌های رندر"

    def __str__(self):
        return f"{self.kind} {self.engine} {self.duration_s:.1f}s"

    @property
    def minutes_per_unit(self) -> float | None:
        """Minutes of wall clock per unit of output — the capacity number.

        For a video segment that is minutes per second of finished video, which
        is exactly the figure `دیتا/0-منبع/data.json` currently guesses at.
        """
        if not self.output_units:
            return None
        return (self.duration_s / 60.0) / self.output_units


class measured:
    """Context manager that records one unit of work.

    Records on the way out whether or not the body succeeded, because a render
    that fails still consumed the card:

        with measured(RenderMetric.Kind.VIDEO_SEGMENT, "wan22_i2v@v1",
                      output_units=5, job=job, store=store):
            ...render...

    Never raises on its own account. A measurement that breaks a render would
    be worse than no measurement, so every failure here is logged and dropped.
    """

    def __init__(
        self,
        kind: str,
        engine: str,
        *,
        output_units: float = 1,
        job=None,
        store=None,
        resolution: str = "",
        context: dict | None = None,
    ):
        self.kind = kind
        self.engine = engine
        self.output_units = output_units
        self.job = job
        self.store = store
        self.resolution = resolution
        self.context = context or {}
        self.started = 0.0
        self.load_s: float | None = None
        self._vram_before: int | None = None
        self.row: RenderMetric | None = None

    def mark_loaded(self) -> None:
        """Call once the model is on the card and real work begins."""
        self.load_s = time.monotonic() - self.started

    def __enter__(self) -> "measured":
        self.started = time.monotonic()
        try:
            from services import hardware

            self._vram_before = hardware.vram_used_mb()
        except Exception as exc:  # noqa: BLE001
            logger.debug("VRAM probe before work failed: %s", exc)
        return self

    def __exit__(self, exc_type, exc, tb):
        duration = time.monotonic() - self.started
        try:
            from services import hardware

            peak = hardware.vram_used_mb()
            self.row = RenderMetric.objects.create(
                kind=self.kind,
                engine=self.engine,
                hardware=hardware.fingerprint(),
                duration_s=round(duration, 3),
                output_units=self.output_units,
                resolution=self.resolution,
                vram_peak_mb=peak,
                load_s=round(self.load_s, 3) if self.load_s is not None else None,
                succeeded=exc_type is None,
                error_kind="" if exc_type is None else exc_type.__name__[:80],
                job=self.job,
                store=self.store,
                context={**self.context, "vram_before_mb": self._vram_before},
            )
        except Exception as record_exc:  # noqa: BLE001
            # A broken measurement must never break a render.
            logger.warning("Could not record render metric: %s", record_exc)
        return False  # never swallow the real exception


def summarise(kind: str | None = None, hardware: str | None = None) -> list[dict]:
    """Per engine: how long it takes, how often it works.

    Median rather than mean. Render times have a long right tail (a model
    reload, a thermal throttle), and a mean dragged up by one 45-minute outlier
    describes a machine nobody has.
    """
    from statistics import median

    rows = RenderMetric.objects.all()
    if kind:
        rows = rows.filter(kind=kind)
    if hardware:
        rows = rows.filter(hardware=hardware)

    grouped: dict[tuple[str, str, str], list[RenderMetric]] = {}
    for row in rows:
        grouped.setdefault((row.hardware, row.kind, row.engine), []).append(row)

    out = []
    for (hw, row_kind, engine), items in sorted(grouped.items()):
        good = [i for i in items if i.succeeded]
        per_unit = [i.minutes_per_unit for i in good if i.minutes_per_unit is not None]
        loads = [i.load_s for i in items if i.load_s is not None]
        entry = {
            "hardware": hw,
            "kind": row_kind,
            "engine": engine,
            "runs": len(items),
            "succeeded": len(good),
            "success_rate": round(len(good) / len(items), 3) if items else None,
            "minutes_per_unit_min": round(min(per_unit), 2) if per_unit else None,
            "minutes_per_unit_median": round(median(per_unit), 2) if per_unit else None,
            "minutes_per_unit_max": round(max(per_unit), 2) if per_unit else None,
            "load_s_median": round(median(loads), 2) if loads else None,
        }
        # What a usable output really costs, failures included. This is the
        # number capacity planning needs; the success-only median is the one
        # that flatters the pipeline.
        if per_unit and entry["success_rate"]:
            entry["effective_minutes_per_unit"] = round(
                entry["minutes_per_unit_median"] / entry["success_rate"], 2
            )
        else:
            entry["effective_minutes_per_unit"] = None
        out.append(entry)
    return out
