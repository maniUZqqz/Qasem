"""«دانلودِ خودکارِ مدل‌ها»: مدل‌هایی که قابلیتِ روشنِ پنل لازم دارد خودشان روی سرورِ پردازش می‌آیند.

مالک (۱۴۰۵/۰۸/۲۳): وقتی سرورِ پردازش را روشن می‌کنم همه‌چیز باید خودش کار کند — بی نصبِ دستی و بی کلیک.

* هر بسته در `processing/downloads/*.json` می‌تواند `auto: true` و `features: [...]` داشته باشد؛ هر «قابلیت» (FEATURES در
  `model_packages.py`) یک سوئیچ دارد. بستهٔ خودکار وقتی دانلود می‌شود که یکی از قابلیت‌های سوئیچ‌دارش روشن باشد؛
* فقط بسته‌های **باز** (`license_class: open`) خودکار می‌شوند؛ «غیرتجاری» و «با شرط» هرگز (حتی اگر در manifest اشتباهاً auto باشند)؛
* سایت می‌گوید **چه چیزی** (فهرستِ مرتب‌شده در بلوکِ `models_auto` ِ هر heartbeat)؛ سرور (`processing/model_auto.py`) تصمیم می‌گیرد
  **کِی و جا می‌شود یا نه**: دیسکِ آزاد منهای ذخیره (پیش‌فرض ۲۵ گیگابایت)؛ بسته‌های کوچک بلافاصله، بزرگ (بیش از ۱٫۵ گیگابایت) در
  بازهٔ شبانه؛ ادامه‌پذیر و با sha256؛
* تنظیمات در یک فایلِ کوچکِ JSON کنارِ داده‌ها (`<NM_DATA_DIR>/model-auto.json`) نگه داشته می‌شود — جدولِ تازه و migration لازم نیست.
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
from pathlib import Path

from . import model_packages as MP
from .services import data_root

logger = logging.getLogger(__name__)

FILE = "model-auto.json"
DEFAULT_RESERVE_GB = 25
BIG_MB = 1536


class AutoError(ValueError):
    """ورودیِ نادرست؛ متنِ فارسیِ آماده برای نمایش."""


def _path() -> Path:
    return data_root() / FILE


def defaults() -> dict:
    return {"enabled": True, "reserve_gb": DEFAULT_RESERVE_GB,
            "features": {k: bool(v[2]) for k, v in MP.FEATURES.items() if v[1]}}


def load() -> dict:
    """تنظیمِ ذخیره‌شده روی پیش‌فرض‌ها؛ فایلِ خراب/نبود ⇒ پیش‌فرض (هرگز خطا نمی‌دهد)."""
    cfg = defaults()
    try:
        raw = json.loads(_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return cfg
    if not isinstance(raw, dict):
        return cfg
    if isinstance(raw.get("enabled"), bool):
        cfg["enabled"] = raw["enabled"]
    try:
        cfg["reserve_gb"] = max(5, min(500, int(raw.get("reserve_gb", DEFAULT_RESERVE_GB))))
    except (TypeError, ValueError):
        pass
    if isinstance(raw.get("features"), dict):
        for k, v in raw["features"].items():
            if k in cfg["features"] and isinstance(v, bool):
                cfg["features"][k] = v
    return cfg


def save(patch: dict) -> dict:
    """{enabled?, reserve_gb?, features?: {کلید: bool}} را روی تنظیمِ فعلی می‌نشاند؛ نادرست ⇒ AutoError."""
    if not isinstance(patch, dict):
        raise AutoError("درخواست درست نیست.")
    cfg = load()
    if "enabled" in patch:
        if not isinstance(patch["enabled"], bool):
            raise AutoError("«دانلودِ خودکار» باید روشن یا خاموش باشد.")
        cfg["enabled"] = patch["enabled"]
    if "reserve_gb" in patch:
        try:
            gb = int(patch["reserve_gb"])
        except (TypeError, ValueError):
            raise AutoError("فضای نگه‌داشته‌شده را با یک عدد (گیگابایت) بنویسید.")
        if not 5 <= gb <= 500:
            raise AutoError("فضای نگه‌داشته‌شده باید بین ۵ و ۵۰۰ گیگابایت باشد.")
        cfg["reserve_gb"] = gb
    if "features" in patch:
        if not isinstance(patch["features"], dict):
            raise AutoError("فهرستِ قابلیت‌ها درست نیست.")
        for k, v in patch["features"].items():
            if k not in cfg["features"]:
                raise AutoError("قابلیتِ «%s» شناخته نیست." % str(k)[:40])
            if not isinstance(v, bool):
                raise AutoError("هر قابلیت باید روشن یا خاموش باشد.")
            cfg["features"][k] = v
    folder = _path().parent
    folder.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".model-auto-", dir=str(folder))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(cfg, fh, ensure_ascii=False)
        os.replace(tmp, _path())
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    return cfg


def wanted(cfg: dict | None = None) -> list[str]:
    """بسته‌های خودکار: بازِ سوئیچ‌دار که یکی از قابلیت‌هایشان روشن است، مرتب بر اساسِ اولویت."""
    cfg = cfg or load()
    if not cfg["enabled"]:
        return []
    on = {k for k, v in cfg["features"].items() if v}
    cat = MP.catalog()
    rows = [(row.get("priority", 50), pk) for pk, row in cat.items()
            if row.get("auto") and row.get("license_class") == "open" and on & set(row.get("features") or [])]
    return [pk for _p, pk in sorted(rows)]


def control_block(cfg: dict | None = None) -> dict:
    """آنچه با هر heartbeat به گره می‌رود (عاملِ قدیمی کلیدِ ناشناخته را نادیده می‌گیرد)."""
    cfg = cfg or load()
    return {"enabled": cfg["enabled"], "packages": wanted(cfg), "reserve_gb": cfg["reserve_gb"], "big_mb": BIG_MB}


def view() -> dict:
    """برای صفحهٔ «دانلودِ مدل‌ها»: سوئیچِ کلی، ذخیرهٔ دیسک و هر قابلیت با بسته‌هایش."""
    cfg = load()
    cat = MP.catalog()
    feats = []
    for key, (label, switch, _default) in MP.FEATURES.items():
        if not switch:
            continue
        pk = sorted((p for p, r in cat.items() if r.get("auto") and r.get("license_class") == "open" and key in (r.get("features") or [])),
                    key=lambda p: (cat[p].get("priority", 50), p))
        every: list = []
        for p in pk:
            every += [q for q in MP._closure(cat, [p]) if q not in every]
        size = sum(cat[q]["size_mb"] for q in every if q in cat)          # هر بستهٔ مشترک یک بار شمرده می‌شود
        feats.append({"key": key, "label": label, "on": bool(cfg["features"].get(key)),
                      "packages": [{"key": p, "title": MP.LABELS.get(p, ("", ""))[0] or cat[p].get("title_fa") or p} for p in pk],
                      "size_mb": size})
    return {"enabled": cfg["enabled"], "reserve_gb": cfg["reserve_gb"], "big_mb": BIG_MB, "features": feats,
            "wanted": wanted(cfg)}
