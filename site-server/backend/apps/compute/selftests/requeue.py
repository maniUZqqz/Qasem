"""پس از قبولیِ یک آزمون، کارهای قبلاً ناموفقِ همان قابلیت — که به‌خاطرِ سرور شکست خورده بودند — خودکار دوباره به صف می‌روند
(مثلاً هفت صدای MOSS ِ چغر، کارهای FLUX و Wan). فقط خطاهایی که از سرورِ پردازش بوده‌اند؛ خطای واقعیِ خودِ کار (متنِ خالی…)
و لغوِ کاربر دست نمی‌خورد. هر کار حداکثر دو بار از این راه برمی‌گردد تا حلقه نشود."""
from __future__ import annotations

import logging
import re
from datetime import timedelta

from django.utils import timezone

logger = logging.getLogger(__name__)

NODE_ERROR_RE = re.compile("|".join([
    r"not reachable", r"unreachable", r"timed out", r"\btimeout\b", r"winerror", r"connection (refused|reset|aborted)", r"\b1006[01]\b",
    r"does not know job kind", r"voice_setup", r"downloading:", r"is not installed", r"not installed", r"not on this node",
    r"did not start", r"did not come up", r"exited right after start", r"is not running", r"not running on this node",
    r"out of (gpu )?memory", r"cuda error", r"nvenc", r"openencodesession", r"no capable devices", r"auto-switch is off",
    r"site unreachable", r"ollama", r"comfyui (did not|is not)", r"did not become ready", r"could not load its model",
    # a service that IS running but did not answer in time (a read timeout - the load on the node, not a bad job)
    r"did not answer within", r"is running but did not",
    # «ComfyUI rejected the graph» is the job's own fault (prompt_no_outputs, a missing node ...) and is never re-run;
    # only the one rejection that means "the model file is not on this node (yet)" is a node reason
    r"rejected the graph[\s\S]{0,500}value[_ ]not[_ ]in[_ ]list",
    r"سرورِ پردازش", r"سرور پردازش", r"بی‌خبر", r"قطع شد", r"نصب نیست", r"در حالِ دانلود", r"خاموش", r"مهلتِ", r"مهلت",
]), re.I)
MAX_PER_JOB = 2
LOOKBACK_DAYS = 14
LIMIT = 100


def node_reason(job) -> bool:
    """این کار به‌خاطرِ سرورِ پردازش (نه خطای خودِ کار) ناموفق/لغو شد؟"""
    text = " ".join([job.error or "", job.message or ""]).strip()
    if job.state == "CANCELLED" and (job.error or "").startswith("کاربر"):
        return False                                   # لغوِ دستیِ کاربر
    if not text:
        return job.state == "CANCELLED"
    return bool(NODE_ERROR_RE.search(text))


def candidates(kinds, match=None, days: int = LOOKBACK_DAYS, limit: int = LIMIT):
    from ..models import ComputeJob, RequeueRecord

    since = timezone.now() - timedelta(days=days)
    qs = (ComputeJob.objects.filter(state__in=["FAILED", "CANCELLED"], kind__in=list(kinds), finished_at__gte=since)
          .exclude(origin="selftest").order_by("-finished_at")[: limit * 3])
    out = []
    for j in qs:
        if match is not None:
            try:
                if not match(j):
                    continue
            except Exception:  # noqa: BLE001
                continue
        if not node_reason(j):
            continue
        if RequeueRecord.objects.filter(job_uid=j.uid).count() >= MAX_PER_JOB:
            continue
        out.append(j)
        if len(out) >= limit:
            break
    return out


def requeue_after_pass(run, test) -> dict:
    """آزمونِ `test` قبول شد ⇒ کارهای ناموفقِ همان قابلیت دوباره به صف. {"retried": n, "skipped": n, "errors": [...]}"""
    from .. import queue as QV
    from ..models import RequeueRecord

    spec = test.requeue or {}
    kinds = spec.get("kinds") or ()
    out = {"retried": 0, "skipped": 0, "errors": [], "kinds": list(kinds)}
    if not kinds:
        return out
    seen_owner = set()
    for job in candidates(kinds, spec.get("match")):
        mode = QV.retry_mode(job)
        if not mode or (mode == "owner" and job.job_ref in seen_owner):
            out["skipped"] += 1
            continue
        if mode == "owner":
            seen_owner.add(job.job_ref)
        try:
            QV.retry_ex(job)
        except ValueError as exc:
            out["skipped"] += 1
            if len(out["errors"]) < 3:
                out["errors"].append(str(exc)[:120])
            continue
        except Exception as exc:  # noqa: BLE001
            out["skipped"] += 1
            logger.warning("selftest requeue of %s failed: %s", job.uid, exc)
            continue
        RequeueRecord.objects.create(job_uid=job.uid, run=run, key=test.key)
        out["retried"] += 1
    if out["retried"]:
        logger.info("selftest %s passed: %d earlier failed job(s) of %s went back to the queue", test.key, out["retried"], list(kinds))
    return out
