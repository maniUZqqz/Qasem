"""پیوندِ کارِ برنامه به چیزهای ساخته‌شده در بخش‌های دیگرِ NM، و خواندنِ وضعیتِ زندهٔ آن‌ها.

یک «پیوند» (ref) فقط یک اشاره است: ``{"type", "id", "label", "url"}``. وضعیت هیچ‌جا ذخیره نمی‌شود؛ ``state_of`` هر بار از خودِ ردیفِ مقصد می‌خواند
(همان اصلِ تختهٔ کمپین: دو ردیف برای یک کار کم‌کم با هم ناهمخوان می‌شوند).

وضعیت‌ها: ready (ساخته شد)، draft (پیش‌نویسِ متنی)، waiting (منتظرِ سرورِ پردازش)، running، failed، cancelled، missing (ردیفِ مقصد پاک شده)، done (مالک انجامش داد).
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

READY, DRAFT, WAITING, RUNNING, FAILED, CANCELLED, MISSING, DONE = (
    "ready", "draft", "waiting", "running", "failed", "cancelled", "missing", "done")


def make(type_: str, id_, label: str = "", url: str = "", **extra) -> dict:
    return {"type": type_, "id": id_, "label": str(label or "")[:160], "url": url, **extra}


def add(item, ref: dict) -> bool:
    """پیوند را اضافه می‌کند (بدونِ تکرار)؛ True اگر تازه بود."""
    refs = list(item.refs or [])
    for r in refs:
        if r.get("type") == ref["type"] and str(r.get("id")) == str(ref["id"]):
            if ref.get("label") and r.get("label") != ref["label"]:
                r["label"] = ref["label"]
                item.refs = refs
            return False
    refs.append(ref)
    item.refs = refs
    return True


def remove(item, type_: str, id_=None) -> None:
    item.refs = [r for r in (item.refs or []) if not (r.get("type") == type_ and (id_ is None or str(r.get("id")) == str(id_)))]


def of_type(item, type_: str) -> list[dict]:
    return [r for r in (item.refs or []) if r.get("type") == type_]


def linked_ids(plan, type_: str, *, exclude_item=None) -> set[str]:
    """شناسهٔ همهٔ ردیف‌هایی از این نوع که کاری از همین برنامه به آن‌ها وصل است (برای این‌که یک ردیف دو بار پذیرفته نشود)."""
    out: set[str] = set()
    for it in plan.items.all():
        if exclude_item is not None and it.pk == exclude_item.pk:
            continue
        for r in it.refs or []:
            if r.get("type") == type_:
                out.add(str(r.get("id")))
    return out


# ----------------------------------------------------------------- وضعیتِ زنده

_JOB = {"QUEUED": WAITING, "CLAIMED": RUNNING, "RUNNING": RUNNING, "COMPLETED": READY, "FAILED": FAILED, "CANCELLED": CANCELLED}


def _job_state(uid) -> tuple[str, str]:
    from apps.compute.models import ComputeJob

    job = ComputeJob.objects.filter(uid=uid).first() if uid else None
    if job is None:
        return MISSING, "کارِ صفِ پردازش پیدا نشد"
    st = _JOB.get(job.state, WAITING)
    note = (job.error or job.message or "")[:200]
    if st == WAITING:
        note = "در صفِ سرورِ پردازش" if node_online() else "منتظرِ روشن‌شدنِ سرورِ پردازش"
    return st, note


def node_online() -> bool:
    from apps.compute.models import ComputeNode

    return any(n.online for n in ComputeNode.objects.filter(enabled=True))


def _campaign_task(ref) -> tuple[str, str]:
    from apps.campaigns.tasks_board import CampaignTask

    t = CampaignTask.objects.filter(pk=ref["id"]).first()
    if t is None:
        return MISSING, "کارِ کمپین پاک شده"
    if t.effective_state == CampaignTask.State.DONE:
        return DONE, "در تختهٔ کمپین «انجام شد» است"
    if t.effective_state == CampaignTask.State.DROPPED:
        return CANCELLED, "در تختهٔ کمپین لغو شده"
    return DRAFT, "پیش‌نویس در تختهٔ کمپین"


def _motion(ref) -> tuple[str, str]:
    from apps.motion.models import MotionRender as M

    r = M.objects.filter(pk=ref["id"]).first()
    if r is None:
        return MISSING, "رندرِ موشن پاک شده"
    S = M.State
    if r.state == S.READY:
        return READY, "ویدیو آماده است"
    if r.state in (S.WAITING_NODE,):
        return WAITING, "منتظرِ روشن‌شدنِ سرورِ پردازش"
    if r.state in (S.QUEUED, S.PREPARING, S.RENDERING):
        return RUNNING, r.message or "در حالِ رندر"
    if r.state == S.CANCELLED:
        return CANCELLED, "لغو شد"
    return FAILED, (r.error or r.message or "رندر ناموفق بود")[:200]


def _thumbnail(ref) -> tuple[str, str]:
    from apps.thumbs.models import Thumbnail as T

    t = T.objects.filter(pk=ref["id"]).first()
    if t is None:
        return MISSING, "تامنیل پاک شده"
    if t.state == T.State.READY:
        return READY, "آماده"
    if t.state == T.State.WAITING_BG:
        return WAITING, t.message or "منتظرِ پس‌زمینهٔ هوش مصنوعی (سرورِ پردازش)"
    return FAILED, (t.message or "ساخته نشد")[:200]


def _audio(ref) -> tuple[str, str]:
    from apps.ai.models import AudioAsset as A

    a = A.objects.filter(pk=ref["id"]).first()
    if a is None:
        return MISSING, "صدا پاک شده"
    S = A.Status
    if a.status == S.READY:
        return READY, "صدا آماده است"
    if a.status == S.PENDING:
        return WAITING, "منتظرِ سرورِ پردازش"
    if a.status == S.RUNNING:
        return RUNNING, "در حالِ ساخت"
    return FAILED, (a.error or "ساخته نشد")[:200]


def _char_job(ref) -> tuple[str, str]:
    from apps.brandchar.models import CharacterAIJob as J

    j = J.objects.filter(pk=ref["id"]).first()
    if j is None:
        return MISSING, "کارِ شخصیت پاک شده"
    if j.state == J.State.DONE:
        return READY, "تصویر آماده است"
    if j.state == J.State.RUNNING:
        return RUNNING, "در حالِ ساخت"
    if j.state == J.State.QUEUED:
        return WAITING, "منتظرِ سرورِ پردازش"
    return FAILED, (getattr(j, "error", "") or j.message or "ساخته نشد")[:200]


def _design_doc(ref) -> tuple[str, str]:
    from apps.design_studio.models import DesignDoc

    return (READY, "پیش‌نویس در استودیوی طراحی") if DesignDoc.objects.filter(pk=ref["id"]).exists() else (MISSING, "سند پاک شده")


def _design_export(ref) -> tuple[str, str]:
    from apps.design_studio.models import DesignExport as E

    e = E.objects.filter(pk=ref["id"]).first()
    if e is None:
        return MISSING, "خروجی پاک شده"
    if e.state == E.State.READY:
        return READY, "آماده"
    job_uid = (e.info or {}).get("job")
    if job_uid and e.state in (E.State.RUNNING, E.State.QUEUED):
        st, note = _job_state(job_uid)             # ویدیو از ارائه یک کارِ صفِ پردازش است: وضعیتش را از همان بخوان
        if st != MISSING:
            return st, note
    if e.state == E.State.RUNNING:
        return RUNNING, e.message or "در حالِ ساخت"
    if e.state == E.State.QUEUED:
        return WAITING, e.message or "منتظرِ سرورِ پردازش"
    return FAILED, (e.error or e.message or "ساخته نشد")[:200]


def _mission(ref) -> tuple[str, str]:
    from apps.growth_engine.crawler.models import CrawlMission

    m = CrawlMission.objects.filter(pk=ref["id"]).first()
    if m is None:
        return MISSING, "مأموریت پاک شده"
    run = m.runs.order_by("-id").first()
    if run is None:
        return DRAFT, "مأموریت ساخته شده؛ هنوز اجرا نشده"
    if run.status in ("completed",):
        return READY, (run.message or "اجرا تمام شد")[:200]
    if run.status in ("running", "queued", "pending"):
        return RUNNING, (run.message or "در حالِ اجرا")[:200]
    return FAILED, (run.message or run.status)[:200]


def _broadcast(ref) -> tuple[str, str]:
    from apps.inbox.models import Broadcast

    b = Broadcast.objects.filter(pk=ref["id"]).first()
    if b is None:
        return MISSING, "پیش‌نویس پاک شده"
    if b.status == Broadcast.Status.DRAFT:
        return DRAFT, "پیش‌نویس؛ چیزی نرفته است"
    if b.status in (Broadcast.Status.SENT,):
        return DONE, "ارسال شد"
    return READY, b.get_status_display()


def _scan(ref) -> tuple[str, str]:
    from apps.igtrends.models import IgScanRun as R

    r = R.objects.filter(pk=ref["id"]).first()
    if r is None:
        return MISSING, "اجرای خواندن پاک شده"
    if r.state == R.State.OK:
        return READY, "خواندنِ ترندها تمام شد"
    if r.state == R.State.QUEUED:
        return WAITING, "منتظرِ سرورِ پردازش (آباگرام)"
    if r.state == R.State.RUNNING:
        return RUNNING, "در حالِ خواندن"
    if r.state == R.State.STOPPED:
        return READY, "زودتر متوقف شد؛ نتیجهٔ بخشی ثبت شد"
    return FAILED, "ناموفق"


def _up3d_job(ref) -> tuple[str, str]:
    from apps.up3d.models import Job

    j = Job.objects.filter(pk=ref["id"]).first()
    if j is None:
        return MISSING, "کار پاک شده"
    if j.state == "COMPLETED":
        return READY, "آماده"
    if j.state in ("FAILED",):
        return FAILED, (j.error or j.message or "ناموفق")[:200]
    if j.state == "CANCELLED":
        return CANCELLED, "لغو شد"
    if j.state in ("PENDING", "PLANNED"):
        return WAITING, j.message or "منتظرِ آماده‌سازی و سرورِ پردازش"
    if j.state == "SCENE_BUILDING" and j.owner == "worker" and j.worker_id is None:
        return WAITING, "منتظرِ سرورِ پردازش (کارتِ گرافیک)"            # آماده‌سازی تمام شده؛ کارِ رندر در صفِ ماندگار است و هنوز کسی برنداشته
    return RUNNING, j.message or "در حالِ ساخت"


def _exists(model_path: str, label: str, state: str = READY):
    def check(ref):
        mod, _, name = model_path.rpartition(".")
        model = getattr(__import__(mod, fromlist=[name]), name)
        return (state, label) if model.objects.filter(pk=ref["id"]).exists() else (MISSING, "پاک شده")

    return check


CHECKS = {
    "compute_job": lambda r: _job_state(r["id"]),
    "campaign_task": _campaign_task,
    "motion_render": _motion,
    "thumbnail": _thumbnail,
    "audio_asset": _audio,
    "character_job": _char_job,
    "design_doc": _design_doc,
    "design_export": _design_export,
    "mission": _mission,
    "broadcast": _broadcast,
    "scan": _scan,
    "up3d_job": _up3d_job,
    "idea": _exists("apps.ideabank.models.StoreIdea", "ایده در بانکِ ایده"),
    "idea_set": _exists("apps.thumbs.models.IdeaSet", "مجموعهٔ ایده"),
    "canned": _exists("apps.inbox.models.CannedReply", "پاسخِ آماده در صندوق", DRAFT),
    "video_project": _exists("apps.content.models.VideoProject", "پروژهٔ ویدیو", DRAFT),
    "caption": _exists("apps.content.models.Caption", "کپشن", DRAFT),
    "photo_design": _exists("apps.photoedit.models.PhotoDesign", "طرحِ آماده در ادیتورِ عکس", READY),
    "site_project": _exists("apps.projects.models.Project", "پیش‌نویسِ سایت در سایت‌ساز", DRAFT),
    "up3d_project": _exists("apps.up3d.models.Project", "پروژهٔ سه‌بعدی", DRAFT),
    "character": _exists("apps.brandchar.models.BrandCharacter", "شخصیتِ برند", READY),
    "note": lambda r: (DRAFT, ""),
}


def state_of(ref: dict) -> tuple[str, str]:
    check = CHECKS.get(ref.get("type"))
    if check is None:
        return DRAFT, ""
    try:
        return check(ref)
    except Exception as exc:  # noqa: BLE001 — خرابیِ یک خواندن نباید کلِ صفحه را بخواباند
        logger.warning("mktplan: state of %s failed: %s", ref, exc)
        return DRAFT, ""
