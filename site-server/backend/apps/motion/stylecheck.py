"""کنترلِ کیفیتِ «سبکِ تازه» پیش از ذخیره.

سه لایه، هر کدام بدونِ مدلِ زبانی:
  ۱) اعتبارسنجیِ توکن‌ها (custom.sanitize) — نوع‌ها و بازه‌ها؛
  ۲) نگهبانِ کنتراستِ پالت (custom.contrast_report) — متنِ اصلی ≥ ۴٫۵ روی زمینه، تأکید ≥ ۳ و …؛
  ۳) رندرِ واقعیِ فریم‌ها با «همان متنِ فروشگاه» در ۹:۱۶ و ۱۶:۹ (همان مرورگرِ بی‌سر و همان موتورِ ویدیو) و سنجشِ هندسه/کنتراستِ پیکسلی (qa.geometry_findings):
     بیرون‌زدنِ متن، روی‌هم‌افتادن، کنتراستِ زیرِ حد روی پیکسل‌های واقعی. یک «خطا» = سبک ذخیره نمی‌شود؛ «هشدار» نشان داده می‌شود.

نتیجه روی `MotionStyleCheck` می‌ماند؛ ذخیرهٔ سبک فقط با یک check ِ «قبول» با همان امضای محتوا ممکن است (views_custom).
ابزارِ رندر روی سایت نبود ⇒ لایه‌های ۱ و ۲ اجرا می‌شود و گزارش صریح می‌گوید «بررسیِ تصویری انجام نشد» (`geometry: false`).
"""
from __future__ import annotations

import logging
import re
import shutil
import tempfile
from pathlib import Path

from django.conf import settings
from django.utils import timezone

from . import assets, catalog, custom, qa, qa_browser, runner, specs, timeline
from .models import MotionStyleCheck

logger = logging.getLogger(__name__)

#: کدِ یافته‌هایی که یک سبکِ بد می‌سازد و ذخیره را می‌بندند (اگر severity ِ «error» باشند)
BLOCKING = ("overflow", "low_contrast", "overlap", "small_text")
ASPECTS = (("9:16", 2), ("16:9", 1))
STALE_S = 900


def sample_scenes(store) -> list:
    """متنِ همین فروشگاه (نام، توضیح، نامِ محصول‌ها) در پنج صحنه؛ یکی از صحنه‌ها عمداً بلند است تا جاشوی متن هم سنجیده شود."""
    name = (getattr(store, "name", "") or "فروشگاهِ من").strip()[:40]
    desc = re.split(r"[.!؟?\n]", (getattr(store, "description", "") or "").strip())[0].strip()[:90]
    items: list = []
    try:
        items = [str(p.name).strip()[:60] for p in store.products.all()[:3] if getattr(p, "name", "")]
    except Exception:  # noqa: BLE001 — فروشگاهِ بدونِ محصول یا ماژولِ محصول
        items = []
    for fill in ("کیفیتِ مطمئن", "ارسالِ سریع", "پشتیبانیِ همیشگی"):
        if len(items) < 3:
            items.append(fill)
    return [
        {"type": "title", "duration": 4, "kicker": "معرفی", "title": name, "subtitle": desc or "نمونهٔ سبکِ شما با متنِ فروشگاهتان"},
        {"type": "list", "duration": 6, "title": "چرا " + name[:24] + "؟", "items": items[:3], "numbered": True},
        {"type": "stat", "duration": 4, "kicker": "در یک نگاه", "value": "1200", "suffix": "+", "label": "مشتریِ راضی در سراسرِ کشور"},
        {"type": "quote", "duration": 6, "text": "بهترین سبک آن است که پیام را زودتر از شکلش به مخاطب برساند و خواندنش حتی روی صفحهٔ کوچکِ گوشی هم راحت باشد.", "author": name},
        {"type": "cta", "duration": 4, "title": "همین حالا شروع کنید", "button": "ثبت‌نام", "note": "نمونهٔ دکمه و توضیح"},
    ]


def sample_spec(store, style_id: str, aspect: str) -> dict:
    d = assets.store_defaults(store)
    brand = {"use_brand_colors": False, "show_logo": False, "name": d["name"]}      # کنترلِ سبک: با پالتِ خودِ سبک، نه رنگِ برند (رنگِ برند را تأکیدِ هر صحنه اصلاح می‌کند)
    return specs.normalize_spec({"version": 2, "style": style_id, "aspect": aspect, "fps": 30, "lang": "fa", "digits": "auto", "brand": brand, "scenes": sample_scenes(store)})


def preview_spec(store, style_id: str, aspect: str = "4:5", *, scenes: int = 2) -> dict:
    """طرحِ پیش‌نمایشِ زندهٔ ویرایشگر: همان متنِ فروشگاه، چند صحنهٔ اول."""
    spec = sample_spec(store, style_id, aspect)
    spec["scenes"] = spec["scenes"][: max(1, scenes)]
    return spec


def start(store, user, style: dict) -> MotionStyleCheck:
    """check ِ تازه (یا قبولِ موجودِ همان امضا) ⇒ ردیف؛ اجرای واقعی را `run()` (Celery) می‌کند."""
    h = custom.style_hash(style)
    ok = MotionStyleCheck.objects.filter(store=store, style_hash=h, state=MotionStyleCheck.State.PASS).order_by("-created_at").first()
    if ok:
        return ok
    live = MotionStyleCheck.objects.filter(store=store, style_hash=h, state=MotionStyleCheck.State.RUNNING).order_by("-created_at").first()
    if live and (timezone.now() - live.updated_at).total_seconds() < STALE_S:
        return live
    return MotionStyleCheck.objects.create(store=store, user=user, style_hash=h, style=style, state=MotionStyleCheck.State.RUNNING,
                                           report={"summary": "کنترلِ کیفیت شروع شد…", "progress": 0.02})


def passed(store, style: dict) -> MotionStyleCheck | None:
    return MotionStyleCheck.objects.filter(store=store, style_hash=custom.style_hash(style), state=MotionStyleCheck.State.PASS).order_by("-created_at").first()


def _thumb_dir(store) -> Path:
    return Path(settings.MEDIA_ROOT) / "generated" / "motion" / str(store.pk) / "styles"


def _finish(chk: MotionStyleCheck, state: str, report: dict, thumb: str = "") -> MotionStyleCheck:
    report = dict(report)
    report["at"] = timezone.now().isoformat()
    chk.state, chk.report, chk.thumb = state, report, thumb or chk.thumb
    chk.save(update_fields=["state", "report", "thumb", "updated_at"])
    return chk


def judge(findings: list) -> tuple[list, list]:
    """یافته‌های هندسه ⇒ (خطاهای مسدودکننده, هشدارها) با پیامِ فارسی."""
    errs, warns = [], []
    for f in findings:
        row = {"code": f["code"], "label": f.get("label", f["code"]), "scene": f.get("scene"), "message": f["message"], "aspect": f.get("aspect", "")}
        if f["severity"] == "error" and f["code"] in BLOCKING:
            errs.append(row)
        elif f["severity"] in ("error", "warn"):
            warns.append(row)
    return errs, warns


def run(check_id: int, *, measure_factory=None) -> MotionStyleCheck | None:
    """کنترلِ کیفیت را اجرا و نتیجه را روی ردیف می‌نویسد. `measure_factory(store, workdir, media_dir, prefix)` برای آزمون جایگزین می‌شود."""
    chk = MotionStyleCheck.objects.filter(pk=check_id).select_related("store").first()
    if chk is None or chk.state != MotionStyleCheck.State.RUNNING:
        return chk
    store = chk.store
    style = chk.style
    rep: dict = {"summary": "", "errors": [], "warnings": [], "geometry": False, "frames": 0, "shots": []}
    try:
        try:
            clean = custom.sanitize(style)
        except custom.StyleError as exc:
            rep.update(summary=f"سبک معتبر نیست: {exc}", errors=[{"code": "invalid", "label": "ساختار", "message": str(exc)}])
            return _finish(chk, MotionStyleCheck.State.FAIL, rep)
        guard = custom.contrast_report(clean)
        rep["contrast"] = guard
        if not guard["ok"]:
            rep.update(summary="نگهبانِ کنتراست: " + "؛ ".join(guard["errors"][:3]), errors=[{"code": "palette_contrast", "label": "کنتراستِ پالت", "message": m} for m in guard["errors"]],
                       warnings=[{"code": "palette_contrast", "label": "کنتراستِ پالت", "message": m} for m in guard["warnings"]])
            return _finish(chk, MotionStyleCheck.State.FAIL, rep)
        rep["warnings"] = [{"code": "palette_contrast", "label": "کنتراستِ پالت", "message": m} for m in guard["warnings"]]
        # the real render: the draft is visible to catalog.get() for this thread only, and rides along as `style_def` (services.attach_style)
        style_id = "u%d-check" % store.pk
        full = {**clean, "id": style_id}
        factory = measure_factory
        ok, why = (True, "") if factory else qa_browser.available()
        if not ok:
            rep.update(summary="رنگ‌ها و ساختار سالم‌اند؛ بررسیِ تصویریِ فریم‌ها انجام نشد (" + why + ").", geometry=False)
            return _finish(chk, MotionStyleCheck.State.PASS, rep)
        _sweep_old(store)
        work = Path(tempfile.mkdtemp(prefix="nm-style-check-"))
        lock = None
        try:
            if not measure_factory:
                lock = runner.SiteLock()
                lock.acquire()
            with custom.draft(style_id, custom.to_styledef(style_id, clean, scope="store")):
                result = _render_and_judge(chk, store, style_id, clean, work, factory, rep)
            return result
        finally:
            if lock:
                lock.release()
            shutil.rmtree(work, ignore_errors=True)
    except Exception as exc:  # noqa: BLE001 — هر شکستِ زیرساخت = «خطا»، نه «قبول»
        logger.exception("motion: style check %s failed", check_id)
        rep.update(summary=f"کنترلِ کیفیت اجرا نشد: {exc}"[:300])
        return _finish(chk, MotionStyleCheck.State.ERROR, rep)


def _sweep_old(store, days: int = 2) -> None:
    """بندانگشتی‌ها و فریم‌های کنترلِ کیفیتِ قدیمی را پاک می‌کند (فقط پوشه‌های style-* ِ خودِ همین ویژگی)."""
    import time

    base = Path(settings.MEDIA_ROOT) / "generated" / "motion" / str(store.pk) / "qa"
    try:
        for d in base.glob("style-*"):
            if d.is_dir() and time.time() - d.stat().st_mtime > days * 86400:
                shutil.rmtree(d, ignore_errors=True)
    except OSError:
        pass


def _render_and_judge(chk, store, style_id: str, clean: dict, work: Path, factory, rep: dict) -> MotionStyleCheck:
    thumb_rel = ""
    findings_all: list = []
    shots_meta: list = []
    total_frames = 0
    for k, (aspect, per) in enumerate(ASPECTS):
        spec = sample_spec(store, style_id, aspect)
        media_dir = qa_browser.media_dir_for(store.pk, f"style-{chk.pk}-{aspect.replace(':', 'x')}")
        make = factory or (lambda st, wd, md, pf, per=per: qa_browser.make_measure(st, workdir=wd, media_dir=md, prefix=pf, per_scene=per))
        measure = make(store, work / f"a{k}", media_dir, f"c{chk.pk}{k}")
        shots = measure(spec)
        total_frames += len(shots)
        for f in qa.geometry_findings(spec, shots):
            f["aspect"] = aspect
            findings_all.append(f)
        shots_meta += [{"aspect": aspect, "scene": s.get("scene"), "kind": s.get("kind"), "image_rel": s.get("image_rel", "")} for s in shots]
        chk.report = {**rep, "progress": round((k + 1) / (len(ASPECTS) + 1), 2), "summary": f"فریم‌های {aspect} سنجیده شد…"}
        chk.save(update_fields=["report", "updated_at"])
    # the gallery thumbnail: the title scene in 4:5, the frame the catalogue thumbnails show
    tspec = sample_spec(store, style_id, "4:5")
    tspec["scenes"] = tspec["scenes"][:1]
    tdir = _thumb_dir(store)
    tdir.mkdir(parents=True, exist_ok=True)
    tmp = tdir / f"tmp-{chk.pk}"
    make = factory or (lambda st, wd, md, pf: qa_browser.make_measure(st, workdir=wd, media_dir=md, prefix=pf, per_scene=1,
                                                                      frames_fn=lambda s: [{"scene": 0, "kind": "enter", "frame": 52}]))
    tshots = make(store, work / "thumb", tmp, f"t{chk.pk}")(tspec)
    if tshots and tshots[0].get("image_rel"):
        src = Path(settings.MEDIA_ROOT) / tshots[0]["image_rel"]
        dest = tdir / f"{custom.style_hash(clean)}.jpg"
        if src.is_file():
            shutil.copyfile(src, dest)
            thumb_rel = qa_browser.rel_of(dest)
    shutil.rmtree(tmp, ignore_errors=True)
    errs, warns = judge(findings_all)
    rep.update(geometry=True, frames=total_frames, shots=shots_meta[:40], errors=errs, warnings=rep["warnings"] + warns[:12])
    if errs:
        rep["summary"] = f"{qa.fa(len(errs))} مشکلِ خوانایی در فریم‌های واقعی: " + "؛ ".join(e["message"] for e in errs[:2])
        return _finish(chk, MotionStyleCheck.State.FAIL, rep, thumb_rel)
    rep["summary"] = f"کنترلِ کیفیت قبول شد: {qa.fa(total_frames)} فریمِ واقعی (۹:۱۶ و ۱۶:۹) با متنِ فروشگاه سنجیده شد" + (f"؛ {qa.fa(len(warns))} هشدار" if warns else "؛ بدونِ مشکل") + "."
    return _finish(chk, MotionStyleCheck.State.PASS, rep, thumb_rel)


def dto(chk: MotionStyleCheck) -> dict:
    from django.conf import settings as dj

    r = chk.report or {}
    thumb = (dj.MEDIA_URL.rstrip("/") + "/" + chk.thumb.lstrip("/")) if chk.thumb else ""
    shots = []
    for s in r.get("shots", [])[:40]:
        s = dict(s)
        if s.get("image_rel"):
            s["image_url"] = dj.MEDIA_URL.rstrip("/") + "/" + s["image_rel"].lstrip("/")
        shots.append(s)
    return {"id": chk.pk, "state": chk.state, "hash": chk.style_hash, "summary": r.get("summary", ""), "progress": r.get("progress", 1.0 if chk.state != "running" else 0.05),
            "errors": r.get("errors", []), "warnings": r.get("warnings", []), "geometry": bool(r.get("geometry")), "frames": r.get("frames", 0), "contrast": r.get("contrast"),
            "shots": shots, "thumb_url": thumb, "at": r.get("at", "")}
