"""آزمونِ «دانلودِ مدل‌ها» (کاتالوگِ ComfyUI / Hugging Face + دانلودِ خودکار) روی سرورِ پردازش.

سه آزمون، همه خودکار (بدونِ کلیکِ کسی) و پس از هر نسخهٔ تازهٔ عامل و هر شب:

1. «model_catalog» (مجازی، بی کار): عاملِ سرور کاتالوگِ تازه را می‌شناسد؛ همهٔ بسته‌های هر هفت گروه در گزارشِ `capabilities.models`
   هستند و دیسکِ آزاد گزارش شده است. اگر عامل قدیمی است ⇒ «ردّ» با راهنمای «به‌روزرسانی».
2. «model_catalog_download» (یک کارِ واقعیِ کوچک): `node.models` با بستهٔ `frame-interp` (RIFE/FILM، حدودِ ۱۰۹ مگابایت) ⇒ سرور دانلود را
   در پس‌زمینه شروع می‌کند و `models.json` (با `result` و `status`) برمی‌گرداند.
3. «model_catalog_installed» (مجازی، پس از ۲): تا نصبِ کاملِ آن بسته (با sha256) صبر می‌کند؛ خطای دانلود ⇒ ردّ.
4. «model_catalog_auto» (مجازی): «دانلودِ خودکار» — بسته‌های خواستهٔ قابلیت‌های روشن یا نصب‌شده‌اند یا در وضعیتِ مجاز
   (در صف / در حالِ دانلود / منتظرِ بازهٔ شبانه / «جا نیست»)؛ هرگز ناموفق، و هیچ مدلِ «غیرتجاری» در فهرستِ خودکار نیست.

شرح و گام‌های دستی: docs/selftests/model-catalog.md
"""
from __future__ import annotations

from . import SelfTest, Spec, Verdict, register

DOWNLOAD_PKG = "frame-interp"
DOWNLOAD_TITLE = "RIFE / FILM (نرم‌کردنِ حرکتِ ویدیو)"
#: وضعیت‌های درستِ یک بستهٔ خودکار که هنوز نصب نشده است
AUTO_OK = {"pending", "active", "downloading", "queued", "waiting_window", "no_disk"}
AUTO_STATE_FA = {"pending": "آماده‌شروع", "active": "در جریان", "downloading": "در حال دانلود", "queued": "در صف",
                 "waiting_window": "منتظرِ بازهٔ شبانه", "no_disk": "جای دیسک کافی نیست", "failed": "ناموفق",
                 "blocked_license": "مجوزِ غیرتجاری", "unknown_package": "بسته را نمی‌شناسد"}


def _models(node) -> dict:
    m = (node.capabilities or {}).get("models")
    return m if isinstance(m, dict) else {}


def _packages(node) -> dict:
    p = _models(node).get("packages")
    return p if isinstance(p, dict) else {}


def _kinds_ok(node):
    kinds = (node.capabilities or {}).get("kinds")
    if isinstance(kinds, list) and "node.models" not in kinds:
        return False, "عاملِ این سرور دانلودِ مدل را نمی‌شناسد (نسخهٔ ۱٫۸ به بالا)"
    return True, ""


def catalog_keys() -> list[str]:
    """همهٔ بسته‌های کاتالوگِ تازه (آن‌ها که package_info دارند)، به ترتیبِ گروه."""
    from .. import model_packages as MP

    return sorted(k for k, c in MP.catalog().items() if c.get("display"))


# ───────────────────────────── ۱) عامل کاتالوگ را می‌شناسد

def virtual_catalog(ctx) -> Verdict:
    from .. import model_packages as MP

    models = _models(ctx.node)
    pk = _packages(ctx.node)
    if not pk:
        kinds = (ctx.node.capabilities or {}).get("kinds")
        if isinstance(kinds, list) and "node.models" not in kinds:
            return Verdict.failed("عاملِ این سرور دانلودِ مدل را نمی‌شناسد — «به‌روزرسانی» را از «دستورها» بزنید.")
        return Verdict.waiting("گزارشِ بسته‌های مدل هنوز از سرور نرسیده (چند دقیقه پس از روشن‌شدن)")
    keys = catalog_keys()
    missing = [k for k in keys if k not in pk]
    if missing:
        return Verdict.failed("عاملِ این سرور %d بستهٔ تازه را نمی‌شناسد (%s ...) — «به‌روزرسانی» را از «دستورها» بزنید؛ "
                              "پس از آن خودش درست می‌شود." % (len(missing), "، ".join(missing[:4])),
                              extra={"missing": missing})
    disk = models.get("disk_mb") if isinstance(models.get("disk_mb"), dict) else {}
    if not any(isinstance(v, (int, float)) for v in disk.values()):
        return Verdict.failed("فضای آزادِ دیسک گزارش نشده (دانلودِ خودکار بی آن نمی‌تواند جا را بسنجد)")
    cat = MP.catalog()
    groups = {}
    for k in keys:
        groups.setdefault(MP._display_group(str(cat[k].get("group") or ""), k, str(cat[k].get("display") or "")), []).append(k)
    need = {"image", "video", "upscale", "control", "depth"}
    lacking = sorted(need - set(groups))
    if lacking:
        return Verdict.failed("گروه‌های کاتالوگ ناقص‌اند: " + "، ".join(lacking))
    done = sum(1 for k in keys if (pk.get(k) or {}).get("installed"))
    free = min(v for v in disk.values() if isinstance(v, (int, float)))
    return Verdict.passed("%d بسته در %d گروه شناخته شد (%d نصب‌شده) · دیسکِ آزاد %.1f گیگابایت" % (len(keys), len(groups), done, free / 1024),
                          extra={"packages": len(keys), "installed": done, "disk_free_mb": int(free)})


register(SelfTest(key="model_catalog", label="دانلودِ مدل‌ها: سرور کاتالوگِ تازه را می‌شناسد", group="system", virtual=virtual_catalog,
                  available=_kinds_ok, order=300, wait_install_s=1800,
                  describe="همهٔ بسته‌های تصویر، ویدیو، بزرگ‌کردن، کنترل و عمق در گزارشِ سرور هستند و دیسکِ آزاد گزارش می‌شود"))


# ───────────────────────────── ۲) یک دانلودِ واقعیِ کوچک

def build_download(ctx):
    return Spec("node.models", {"action": "download", "packages": [DOWNLOAD_PKG], "window": ""}, timeout_s=600, priority=20)


def check_download(ctx, job) -> Verdict:
    data = ctx.read_json(job, "models.json")
    if not isinstance(data, dict):
        return Verdict.failed("models.json خوانده نشد")
    lacking = [k for k in ("result", "status") if k not in data]
    if lacking:
        return Verdict.failed("در models.json این کلیدها نیست: " + "، ".join(lacking))
    status = data.get("status") if isinstance(data.get("status"), dict) else {}
    if str(status.get("error") or "").strip() and not status.get("running"):
        return Verdict.failed("دانلود خطا داد: %s" % str(status["error"])[:300])
    return Verdict.passed("دانلودِ «%s» به سرور رسید: %s" % (DOWNLOAD_TITLE, str(data.get("result"))[:120]))


register(SelfTest(key="model_catalog_download", label="دانلودِ مدل: " + DOWNLOAD_TITLE, group="system", kind="node.models",
                  build=build_download, check=check_download, available=_kinds_ok, order=301, gpu_required=False,
                  describe="بستهٔ کوچکِ RIFE/FILM (حدودِ ۱۰۹ مگابایت) با دانلودِ واقعی؛ فایل‌ها در ComfyUI\\models\\frame_interpolation می‌نشینند"))


# ───────────────────────────── ۳) نصبِ کاملِ آن بسته

def virtual_installed(ctx) -> Verdict:
    models = _models(ctx.node)
    st = _packages(ctx.node).get(DOWNLOAD_PKG)
    if not isinstance(st, dict):
        return Verdict.failed("سرور بستهٔ «%s» را نمی‌شناسد" % DOWNLOAD_PKG)
    if st.get("installed"):
        return Verdict.passed("«%s» نصب است (%d مگابایت؛ فایل‌های ComfyUI از قبل: %s)" % (DOWNLOAD_TITLE, int(st.get("total_mb") or 0),
                                                                                       st.get("in_comfyui") or 0))
    err = str(models.get("error") or "").strip()
    if err and not models.get("running"):
        return Verdict.failed("دانلودِ «%s» ناموفق بود: %s" % (DOWNLOAD_TITLE, err[:300]))
    pr = models.get("progress") if isinstance(models.get("progress"), dict) else {}
    if pr.get("bytes_total"):
        pct = int(100 * float(pr.get("bytes_done") or 0) / max(1, float(pr["bytes_total"])))
        return Verdict.waiting("در حالِ دانلود: %d٪ (%s)" % (pct, pr.get("current") or ""))
    wait = models.get("waiting") if isinstance(models.get("waiting"), dict) else {}
    if wait:
        return Verdict.waiting("منتظرِ بازهٔ دانلودِ شبانه")
    return Verdict.waiting("دانلود هنوز شروع نشده؛ کمی بعد دوباره بررسی می‌شود")


register(SelfTest(key="model_catalog_installed", label="دانلودِ مدل: فایل‌ها کامل نصب شدند", group="system", virtual=virtual_installed,
                  after=("model_catalog_download",), available=_kinds_ok, order=302, wait_install_s=3 * 3600,
                  describe="بستهٔ دانلودشده کامل و با sha256 درست در ComfyUI نشسته است"))


# ───────────────────────────── ۴) دانلودِ خودکار

def virtual_auto(ctx) -> Verdict:
    from .. import auto_models, model_packages as MP

    cfg = auto_models.load()
    if not cfg["enabled"]:
        return Verdict.skipped("«دانلودِ خودکار» در پنل خاموش است")
    wanted = auto_models.wanted(cfg)
    if not wanted:
        return Verdict.skipped("هیچ قابلیتِ دانلودِ خودکار روشن نیست")
    models = _models(ctx.node)
    auto = models.get("auto") if isinstance(models.get("auto"), dict) else {}
    states = auto.get("states") if isinstance(auto.get("states"), dict) else {}
    if not states:
        return Verdict.waiting("سرور هنوز وضعیتِ دانلودِ خودکار را گزارش نکرده (چند دقیقه پس از روشن‌شدن یا به‌روزرسانی)")
    cat = MP.catalog()
    pk = _packages(ctx.node)
    big = auto_models.BIG_MB
    bad, waiting_small, ok = [], [], []
    for p in wanted:
        if (pk.get(p) or {}).get("installed") or states.get(p) == "installed":
            ok.append(p)
            continue
        st = states.get(p, "")
        if st in AUTO_OK:
            if st in ("pending", "active", "downloading", "queued") and int(cat[p].get("size_mb") or 0) <= big:
                waiting_small.append(p)
            continue
        why = (auto.get("why") or {}).get(p, "")
        bad.append("%s: %s%s" % (p, AUTO_STATE_FA.get(st, st or "بی‌وضعیت"), " (%s)" % why[:100] if why else ""))
    leaked = [p for p in states if (cat.get(p) or {}).get("license_class", "open") != "open" and p in wanted]
    if leaked:
        return Verdict.failed("مدلِ غیرتجاری در فهرستِ خودکار آمده است: " + "، ".join(leaked))
    if bad:
        return Verdict.failed("دانلودِ خودکارِ این بسته‌ها درست پیش نرفت: " + "؛ ".join(bad)[:600], extra={"bad": bad})
    if waiting_small:
        return Verdict.waiting("در حالِ دانلودِ خودکار: " + "، ".join(waiting_small))
    return Verdict.passed("%d بستهٔ خودکار: %d نصب‌شده، بقیه منتظرِ شب یا جا" % (len(wanted), len(ok)), extra={"installed": ok, "wanted": wanted})


register(SelfTest(key="model_catalog_auto", label="دانلودِ خودکارِ مدل‌های قابلیت‌های روشن", group="system", virtual=virtual_auto,
                  available=_kinds_ok, order=303, wait_install_s=3 * 3600,
                  describe="بسته‌های کوچکِ قابلیت‌های روشن خودشان می‌آیند، بزرگ‌ها شب؛ مدلِ غیرتجاری هرگز"))
