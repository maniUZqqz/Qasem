"""زمان‌بندیِ دانلودها: «همین الان»، «در ساعتِ ۰۳:۳۰» یا «در بازهٔ شبانه» (همه به وقتِ تهران).

هر جایی که دانلودی شروع می‌شود (دانلودِ مدلِ هوش مصنوعی، دانلودِ مدل‌های صدا و ویدیو) یک `when` می‌گیرد:

    {"mode": "default"}                 طبقِ «زمانِ دانلودها» در تنظیماتِ سرورهای پردازش (now | window)
    {"mode": "now"}                     همین الان، هر چه تنظیمِ کلی باشد
    {"mode": "at", "time": "03:30"}     نخستین «۰۳:۳۰» ِ آینده (به وقتِ تهران)
    {"mode": "window"}                  فقط در بازهٔ شبانهٔ تنظیمات (یا {"window": "01:00-05:00"} برای بازهٔ دیگر)

`schedule_from_when` آن را به دو ستونِ صفِ پردازش ترجمه می‌کند: `not_before` (پیش از این لحظه هیچ گره‌ای کار را نمی‌گیرد)
و `window` (فقط داخلِ بازه گرفته می‌شود) — services.claim هر دو را رعایت می‌کند. عاملِ سرورِ پردازش (۲٫۶ به بعد) همان
`window` را در بدنهٔ کار هم می‌بیند تا دانلودی که خودش در پس‌زمینه شروع می‌کند هم از بازه بیرون نزند.
"""
from __future__ import annotations

from datetime import timezone as dt_timezone

from django.utils import timezone
from rest_framework.exceptions import ValidationError

from . import services as SV

MODES = ("default", "now", "at", "window")
CATEGORY = "download"                       # دستهٔ ComputeJob برای فهرستِ «دانلودها» در صف
DEFAULT_WINDOW = "02:00-07:00"
TEHRAN_OFFSET_MIN = 210                     # UTC+3:30؛ ایران ساعتِ تابستانی ندارد

_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
_FA = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")


class ScheduleError(ValidationError):
    """ورودیِ نامعتبرِ زمان؛ `.message` متنِ فارسیِ آماده برای نمایش به کاربر است."""

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


def fa(value) -> str:
    return str(value).translate(_FA)


def _ascii(text) -> str:
    return str(text or "").translate(_DIGITS).strip()


def _config(cfg):
    if cfg is not None:
        return cfg
    from .models import ComputeSettings
    return ComputeSettings.get()


def _read(when) -> tuple[str, str, str]:
    """`when` در هر شکلی ⇒ (mode, time, window). خالی ⇒ default."""
    if when is None or when == "":
        return "default", "", ""
    if isinstance(when, str):
        text = _ascii(when).lower()
        if ":" in text and text[:1].isdigit():          # «03:30» تنها یعنی «در ساعتِ ۰۳:۳۰»
            return "at", text, ""
        return text, "", ""
    if isinstance(when, dict):
        mode = _ascii(when.get("mode") or "default").lower()
        return mode, _ascii(when.get("time")), _ascii(when.get("window"))
    raise ScheduleError("زمانِ دانلود را درست انتخاب کنید («الان»، «در ساعتِ …» یا «در بازهٔ شبانه»).")


def schedule_from_when(when=None, cfg=None, now=None) -> dict:
    """⇒ {"not_before": datetime | None, "window": "02:00-07:00" | ""}؛ نامعتبر ⇒ ScheduleError (ValidationError با متنِ فارسی)."""
    now = now or timezone.now()
    mode, hhmm, win = _read(when)
    if mode not in MODES:
        raise ScheduleError("زمانِ دانلود را درست انتخاب کنید («الان»، «در ساعتِ …» یا «در بازهٔ شبانه»).")
    if mode == "default":
        cfg = _config(cfg)
        if getattr(cfg, "download_mode", "now") != "window":
            return {"not_before": None, "window": ""}
        # تنظیمِ کلیِ خراب هرگز دانلود را متوقف نمی‌کند: به بازهٔ پیش‌فرض برمی‌گردیم
        return {"not_before": None, "window": cfg.download_window if SV.parse_window(cfg.download_window) else DEFAULT_WINDOW}
    if mode == "now":
        return {"not_before": None, "window": ""}
    if mode == "at":
        if not hhmm:
            raise ScheduleError("ساعتِ شروع را بنویسید، مثلاً ۰۳:۳۰ (به وقتِ تهران).")
        moment = SV.next_clock_time(hhmm, now)
        if moment is None:
            raise ScheduleError("ساعت را مثل ۰۳:۳۰ بنویسید (ساعت ۰ تا ۲۳، دقیقه ۰ تا ۵۹).")
        return {"not_before": moment, "window": ""}
    # mode == "window"
    if win:
        if not SV.parse_window(win):
            raise ScheduleError("بازه را مثل ۰۲:۰۰-۰۷:۰۰ بنویسید (ساعتِ شروع و پایان فرق داشته باشد).")
        return {"not_before": None, "window": win}
    cfg = _config(cfg)
    return {"not_before": None, "window": cfg.download_window if SV.parse_window(cfg.download_window) else DEFAULT_WINDOW}


def clock_text(moment, now=None) -> str:
    """«امروز ۰۲:۰۰» / «فردا ۰۲:۰۰» / «۳ روزِ دیگر، ۰۲:۰۰» به وقتِ تهران."""
    now = now or timezone.now()
    t = SV.tehran_now(moment)
    day = (t.date() - SV.tehran_now(now).date()).days
    hhmm = fa(f"{t.hour:02d}:{t.minute:02d}")
    if day <= 0:
        return f"امروز {hhmm}"
    if day == 1:
        return f"فردا {hhmm}"
    return f"{fa(day)} روزِ دیگر، {hhmm}"


def start_moment(not_before, window, now=None):
    """کی کار می‌تواند شروع شود؟ None = همین حالا (زمانی تعیین نشده یا بازه الان باز است)."""
    now = now or timezone.now()
    moment = not_before if (not_before and not_before > now) else None
    if window and not SV.in_window(window, now):
        opens = SV.next_window_start(window, now)
        moment = max(moment, opens) if moment else opens
    return moment


def schedule_text(not_before, window, now=None) -> str:
    """«زمان‌بندی‌شده — شروع امروز ۰۲:۰۰ (وقتِ تهران)» یا «» وقتی کار می‌تواند همین حالا شروع شود."""
    now = now or timezone.now()
    moment = start_moment(not_before, window, now)
    if moment is None:
        return ""
    return f"زمان‌بندی‌شده — شروع {clock_text(moment, now)} (وقتِ تهران)"


def payload_fields(sched: dict) -> dict:
    """کلیدهای payload که عاملِ گره می‌خواند: `window` همیشه هست (خالی = بی‌محدودیت، حتی اگر تنظیمِ کلی «بازه» باشد)."""
    nb = sched.get("not_before")
    return {"window": sched.get("window") or "", "not_before": nb.isoformat() if nb else ""}


def control_block(cfg=None, now=None) -> dict:
    """تنظیمِ کلیِ دانلودها برای عامل (heartbeat و claim): حالت، بازه، اختلافِ ساعتِ تهران و ساعتِ سرور."""
    cfg = _config(cfg)
    now = now or timezone.now()
    return {"mode": cfg.download_mode, "window": cfg.download_window, "tz_offset_min": TEHRAN_OFFSET_MIN,
            "server_time": now.astimezone(dt_timezone.utc).isoformat()}


__all__ = ["schedule_from_when", "schedule_text", "start_moment", "clock_text", "payload_fields", "control_block",
           "ScheduleError", "CATEGORY", "MODES"]
