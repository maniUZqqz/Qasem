# -*- coding: utf-8 -*-
"""خزشِ 21st.dev روی سرورِ گرافیکی (کارِ ``crawl21.run``) — راهِ جایگزین وقتی سرورِ سایت نمی‌تواند (مسدود شد، یا صفحه نیازِ مرورگرِ واقعی دارد).

گرهٔ GPU با Playwright (Edge/Chrome که روی ویندوز هست؛ نصبِ خودکار با ``requirements.d/crawl21.json``) همان صفحه‌های **عمومی** را مثلِ یک مرورگر باز می‌کند:
نخست ``robots.txt`` (هر نشانیِ ممنوع، حتی درخواست‌های داخلیِ صفحه، قطع می‌شود)، بعد برای هر قطعه ``.md`` و صفحهٔ HTML ⇒ ``results.json`` برمی‌گردد
{id, ok, md, page: {title, demo: {file, code}, text}}. این‌جا همان تجزیه‌گرهای سرور (``c21st.parse_component_md``، ``c21_source.parse_demo``) روی آن اجرا می‌شود؛
پس منطقِ تجزیه یکی است و گره فقط «چشم» است.

* ``enqueue_batch`` — یک کارِ ماندگار (گرهٔ خاموش ⇒ در صف می‌ماند) برای ≤ ۲۵ قطعه؛ خودکار از تسکِ خزش وقتی سرور ۴۰۳ می‌خورد.
* ``collect`` — کارهای تمام‌شده را می‌خواند و می‌ریزد توی کاتالوگ (تسکِ Celery هر چند دقیقه صدایش می‌زند).
* دستی روی گره: ``python crawl21_jobs.py --run ids.txt out.json`` (docs/c21-crawler.md).
"""
from __future__ import annotations

import json
import logging
import re
import time
from pathlib import Path

from . import c21_crawl, c21_source as SRC, c21st

logger = logging.getLogger(__name__)

KIND = "crawl21.run"
BATCH = 25
MAX_PENDING = 4


def state_path() -> Path:
    return c21st.root() / "node_jobs.json"


def state() -> dict:
    try:
        return json.loads(state_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"pending": [], "ingested": 0, "jobs": 0}


def _save(st: dict) -> None:
    c21st._atomic(state_path(), json.dumps(st, ensure_ascii=False))


def demos_dir() -> Path:
    d = c21st.root() / "demos"
    d.mkdir(parents=True, exist_ok=True)
    return d


def save_demo(cid: str, demo: dict) -> None:
    c21st._atomic(demos_dir() / (c21st.safe_name(cid) + ".json"), json.dumps(demo, ensure_ascii=False))


def load_demo(cid: str) -> dict:
    try:
        return json.loads((demos_dir() / (c21st.safe_name(cid) + ".json")).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def pick_ids(limit: int = BATCH) -> list[str]:
    """اول قطعه‌هایی که جزئیاتشان هنوز نیست (سرور مسدود بود یا نرسید)، بعد قطعه‌های قابلِ تبدیل که نمونهٔ استفاده‌شان هنوز نیست:
    مجوزِ آزاد + کتابخانه‌ای با مخزنِ عمومی (بی‌مخزن هرگز تبدیل نمی‌شود، پس نمونه‌اش بی‌فایده است) + نه «مجوزِ مخزن آزاد نیست» و نه «در مخزن نبود»."""
    rows = c21st.load()
    libs = c21_crawl.load_libs()
    first = [r["id"] for r in rows if not r.get("detail") and len(r["id"].split("/")) == 2]
    second = [r["id"] for r in rows if r.get("usable") and r.get("detail") and len(r["id"].split("/")) == 2
              and (libs.get(r.get("library_id") or "") or {}).get("github") and (r.get("conv") or {}).get("state") not in ("ok", "license", "no-source")
              and not load_demo(r["id"])]
    seen, out = set(), []
    for cid in first + second:
        if cid not in seen:
            seen.add(cid)
            out.append(cid)
        if len(out) >= limit:
            break
    return out


def build_payload(ids: list[str], robots_text: str = "") -> dict:
    return {"ids": ids, "urls": ["%s/@%s/components/%s" % (c21st.BASE, i.split("/")[0], i.split("/")[1]) for i in ids if len(i.split("/")) == 2], "want": "md,page",
            "delay_s": 1.5, "robots": (robots_text or "")[:20000], "ua": c21_crawl.UA_TOKEN}


def enqueue_batch(limit: int = BATCH, *, ids: list[str] | None = None, robots_text: str = ""):
    """⇒ ComputeJob یا None (چیزی برای کار نیست / سرورِ پردازشی ثبت نیست / صفِ پیشین هنوز تمام نشده)."""
    from apps.compute import services as SV

    st = state()
    st["pending"] = [p for p in st.get("pending", []) if p.get("uid")]
    if len(st["pending"]) >= MAX_PENDING:
        return None
    taken = {i for p in st["pending"] for i in p.get("ids", [])}      # دسته‌های در انتظار دوباره گرفته نمی‌شوند؛ هر کارِ تازه ۲۵ قطعهٔ بعدی را می‌برد (تا MAX_PENDING کارِ هم‌زمان)
    ids = ids or [i for i in pick_ids(limit + len(taken)) if i not in taken][:limit]
    if not ids:
        return None
    try:
        job = SV.enqueue_durable(KIND, build_payload(ids, robots_text), origin="c21", priority=120, dedupe=False, timeout_s=3600)
    except SV.ComputeUnavailable:
        return None
    st["pending"].append({"uid": str(job.uid), "ids": ids, "at": time.time()})
    st["jobs"] = st.get("jobs", 0) + 1
    _save(st)
    return job


def ingest_results(results: list[dict]) -> dict:
    """نتیجهٔ گره ⇒ کاتالوگ. هر ردیف مستقل است؛ ردیفِ خراب فقط خودش را از دست می‌دهد."""
    rows = {r["id"]: r for r in c21st.load()}
    out = {"rows": 0, "details": 0, "demos": 0, "failed": 0}
    for res in results or []:
        cid = str(res.get("id") or "")
        if not re.fullmatch(r"[A-Za-z0-9._-]{1,60}/[A-Za-z0-9._-]{1,120}", cid):
            continue
        out["rows"] += 1
        if not res.get("ok"):
            out["failed"] += 1
            continue
        r = rows.setdefault(cid, {"id": cid, "title": c21_crawl.title_from_slug(cid), "author_name": "", "cats": [], "detail": False})
        md = str(res.get("md") or "")
        if md.startswith("#"):
            d = c21st.parse_component_md(md)
            r.update({k: v for k, v in d.items() if v}, detail=True, detail_at=c21st._now())
            r["library_id"] = c21_crawl.library_id_of(c21st._field(md, "Library")) or r.get("library_id", "")
            r["usable"] = c21st.is_permissive(r.get("license", ""))
            a, s = cid.split("/")
            r["url"] = "%s/@%s/components/%s" % (c21st.BASE, a, s)
            r["cats"] = c21_crawl.infer_cats(r)
            out["details"] += 1
        page = res.get("page") or {}
        demo = page.get("demo") or {}
        if isinstance(demo, dict) and demo.get("code"):
            code = str(demo["code"])[:SRC.MAX_FILE]
            save_demo(cid, {"file": str(demo.get("file") or "Usage.tsx")[:80], "code": code, "imports": SRC.imports_of(code), "via": "node"})
            out["demos"] += 1
    c21st.save(sorted(rows.values(), key=lambda x: x["id"]))
    return out


def collect() -> dict:
    """کارهای تمام‌شدهٔ گره را می‌خواند و می‌ریزد توی کاتالوگ. ⇒ {jobs, rows, details, demos}"""
    from apps.compute import services as SV
    from apps.compute.models import ComputeJob

    st = state()
    keep, total = [], {"jobs": 0, "rows": 0, "details": 0, "demos": 0, "failed": 0}
    for p in st.get("pending", []):
        job = ComputeJob.objects.filter(uid=p.get("uid")).first()
        if job is None or job.state in (ComputeJob.State.FAILED, ComputeJob.State.CANCELLED):
            continue
        if job.state != ComputeJob.State.COMPLETED:
            keep.append(p)
            continue
        try:
            data = json.loads(SV.output_path(job, "results.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        got = ingest_results(data.get("results") if isinstance(data, dict) else data)
        total["jobs"] += 1
        for k in ("rows", "details", "demos", "failed"):
            total[k] += got[k]
    st["pending"] = keep
    st["ingested"] = st.get("ingested", 0) + total["rows"]
    _save(st)
    return total
