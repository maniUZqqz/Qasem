"""آزمونِ «دستورها»: بعد از دستورِ به‌روزرسانی عامل با نسخهٔ تازه برمی‌گردد (نسخهٔ پیش و پس ثبت می‌شود).

دو حالت:
  * اجرای «پس از نسخهٔ تازه» (version): همین حالا عامل به‌روز شده؛ آخرین دستورِ update (خودکار یا دستی) را می‌خوانیم و ثبت می‌کنیم که
    کدِ گره با بستهٔ سایت یکی است ⇒ قبول (دوباره خاموش/روشن نمی‌کنیم).
  * اجراهای دیگر (شبانه/دستی): گره بی‌کار باشد ⇒ اگر بستهٔ تازه‌تر هست «به‌روزرسانی» وگرنه «راه‌اندازیِ دوباره» فرستاده می‌شود و
    باید عامل (با زمانِ شروعِ تازه) و با کدِ درست برگردد. اگر گره مشغول است تا نیم ساعت صبر می‌کنیم؛ بعد «ردشده».
آخرین آزمون است (final): بقیه تمام شده‌اند و ریستارت کاری را نمی‌شکند."""
from datetime import timedelta

from django.utils import timezone
from django.utils.dateparse import parse_datetime

from .. import commands as C
from .. import updates as U
from ..models import ComputeJob
from . import SelfTest, Verdict, register

BACK_WITHIN_S = 15 * 60
IDLE_WAIT_S = 30 * 60


def _code(caps) -> str:
    c = caps.get("code") if isinstance(caps.get("code"), dict) else {}
    return str(c.get("id") or "")[:16]


def _label(caps) -> str:
    return "v%s (%s)" % (caps.get("agent") or "?", _code(caps) or "بی‌شناسه")


def _idle(node) -> bool:
    return not ComputeJob.objects.filter(node=node, state__in=[ComputeJob.State.CLAIMED, ComputeJob.State.RUNNING]).exclude(
        kind__in=("ollama.pull", "node.models")).exists()


def _supports(node, action) -> bool:
    caps = node.capabilities or {}
    return C.supported(node) and action in (caps.get("commands") or [])


def virtual(ctx):
    node, res = ctx.node, ctx.result
    caps = node.capabilities or {}
    extra = dict(res.extra or {})
    latest = U.latest()
    waiting = U.update_state(caps, latest).get("update_waiting")
    now = timezone.now()
    state = C.state(node)
    last = state.get("last") or {}

    # ── جریانِ در حالِ انجام (فرستاده‌ایم و منتظرِ برگشت‌ایم)
    if extra.get("cmd_id"):
        sent = parse_datetime(extra["sent_at"])
        if last.get("id") == extra["cmd_id"] and last.get("state") == "done" and last.get("ok") is False:
            return Verdict.failed("دستورِ «%s» روی گره شکست خورد: %s" % (extra.get("action"), (last.get("output") or "")[-200:]), extra=extra)
        done = last.get("id") == extra["cmd_id"] and last.get("state") == "done" and last.get("ok")
        started = float(caps.get("started_at") or 0)
        back = node.online and started > sent.timestamp()
        if done and back:
            after = {"agent": caps.get("agent"), "code": _code(caps)}
            ok_code = extra["action"] != "update" or not U.update_state(caps, latest).get("update_waiting")
            extra["after"] = after
            if not ok_code:
                return Verdict.failed("گره برگشت ولی هنوز کدِ قدیمی دارد: %s (بستهٔ سایت %s)" % (_label(caps), latest.get("version")), extra=extra)
            return Verdict.passed("«%s» انجام شد و عامل برگشت: %s ⇒ %s (در %d ثانیه)" % (
                "به‌روزرسانی" if extra["action"] == "update" else "راه‌اندازیِ دوباره", extra["before"]["label"], _label(caps),
                (now - sent).total_seconds()), extra=extra)
        if (now - sent).total_seconds() > BACK_WITHIN_S:
            return Verdict.failed("عامل پس از دستورِ «%s» تا %d دقیقه برنگشت (خاموش شد؟ START.bat بسته شد؟)" % (extra.get("action"), BACK_WITHIN_S // 60),
                                  extra=extra)
        return Verdict.waiting("منتظرِ برگشتِ عامل پس از «%s» ..." % extra.get("action"), extra=extra)

    # ── اجرای «پس از نسخهٔ تازه»: ثبتِ آخرین به‌روزرسانی
    if ctx.run.trigger == "version":
        finished = parse_datetime(last.get("finished_at") or "") if last.get("finished_at") else None
        recent = finished and (now - finished) < timedelta(hours=2)
        if last.get("action") == "update" and last.get("state") == "done" and last.get("ok") and recent and not waiting:
            return Verdict.passed("به‌روزرسانیِ %s از پنل/خودکار انجام شد و عامل با کدِ تازه برگشت: %s" % (last.get("by") or "خودکار", _label(caps)),
                                  extra={"after": {"agent": caps.get("agent"), "code": _code(caps)}, "command": last.get("id")})
        if not waiting:
            return Verdict.passed("عامل %s با بستهٔ سایت یکی است (به‌روزرسانیِ دیگری لازم نیست)" % _label(caps),
                                  extra={"after": {"agent": caps.get("agent"), "code": _code(caps)}})

    # ── اجراهای دیگر: خودمان دستور می‌فرستیم
    action = "update" if waiting else "restart"
    if not _supports(node, action):
        return Verdict.failed("عاملِ این سرور (%s) دستورِ «%s» را نمی‌شناسد؛ با START.bat یک بار به‌روز شود." % (caps.get("agent"), action))
    if not node.online:
        return Verdict.waiting("سرور آنلاین نیست")
    first = parse_datetime(extra["first_check"]) if extra.get("first_check") else now
    extra["first_check"] = first.isoformat()
    if not _idle(node) or state.get("busy"):
        if (now - first).total_seconds() > IDLE_WAIT_S:
            return Verdict.skipped("گره تا نیم ساعت مشغولِ کارِ دیگر بود؛ برای اینکه کاری نشکند «راه‌اندازیِ دوباره» انجام نشد.")
        return Verdict.waiting("منتظرِ بی‌کار شدنِ گره برای دستورِ «%s» ..." % action, extra=extra)
    try:
        cmd = C.request(node, action, "آزمونِ خودکار")
    except C.CommandError as exc:
        return Verdict.waiting("دستور هنوز نرفت: %s" % exc, extra=extra)
    extra.update(cmd_id=cmd["id"], action=action, sent_at=now.isoformat(), before={"agent": caps.get("agent"), "code": _code(caps), "label": _label(caps)})
    return Verdict.waiting("دستورِ «%s» فرستاده شد ..." % action, extra=extra)


register(SelfTest(key="update_flow", label="دستورِ از راه دور: به‌روزرسانی/راه‌اندازیِ دوباره و برگشتِ عامل", group="system", virtual=virtual,
                  final=True, order=200, wait_install_s=BACK_WITHIN_S + IDLE_WAIT_S,
                  describe="بدونِ رفتن پای آن سیستم؛ نسخهٔ پیش و پس ثبت می‌شود"))
