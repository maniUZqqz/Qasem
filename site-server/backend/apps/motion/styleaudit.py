"""«ممیزیِ سبک‌ها»: هر سبکِ کاتالوگ × {۹:۱۶، ۱۶:۹} با یک طرحِ واقعی، در همان مرورگرِ بی‌سر و همان موتورِ رندرِ تولید، رندر و سنجیده می‌شود
(همان `qa_browser.make_measure` + `qa.geometry_findings` ِ کنترلِ کیفیت)؛ بعد برگه‌های تماس (contact sheet) برای نگاهِ انسانی ساخته می‌شود.

چرا: «همهٔ سبک‌ها بیاد و درست باشه» را فقط دیدنِ هر سبک روی متنِ واقعی ثابت می‌کند؛ آزمونِ کاتالوگ فقط ساختار را می‌سنجد، نه اینکه تیترِ استیم‌پانک روی زمینهٔ قهوه‌ای گم شده.
اجرا:  manage.py motion_style_audit --store <id> [--styles a,b|all] [--aspects 9:16,16:9] [--plan chagher|store] [--frames 1|2] [--out DIR] [--resume] [--sheets-only]
(فرمانِ سنگین است: روی سرورِ مشترک زیرِ `flock /root/nm-heavy.lock` اجرا کنید.)

طرحِ «چغر» فقط جمله‌های تأییدشدهٔ docs/chagher/brand-facts-fa.md را دارد (هیچ قیمت یا آماری نمی‌سازد)."""
from __future__ import annotations

import json
import shutil
import tempfile
import time
from pathlib import Path

from . import assets, catalog, custom, qa, qa_browser, runner, specs, stylecheck

#: سه رنگِ برندِ چغر (docs/chagher/brand-facts-fa.md) — فقط وقتی فروشگاه خودش رنگی ندارد
CHAGHER_COLORS = ["#126F85", "#163F75", "#DBE6FF"]


def chagher_scenes() -> list:
    """چهار صحنه (عنوان، فهرست، عدد، دعوت) با جمله‌های تأییدشدهٔ چغر؛ «۱٬۳۰۰ حرکت» از دیتابیسِ خودِ چغر است (brand-facts بند ۸)."""
    return [
        {"type": "title", "duration": 4, "kicker": "دستیار هوش مصنوعیِ مربی‌ها", "title": "چغر", "subtitle": "با چغر چغر تر شو"},
        {"type": "list", "duration": 7, "title": "چهار قدم تا برنامه", "items": ["ثبت‌نام در کمتر از یک دقیقه", "خریدِ توکن", "واردکردنِ اطلاعاتِ مجموعه", "تولیدِ برنامه"], "numbered": True},
        {"type": "stat", "duration": 4, "kicker": "کتابخانهٔ حرکت‌ها", "value": "1300", "suffix": "+", "label": "حرکتِ آموزشی با نامِ فارسی"},
        {"type": "cta", "duration": 4, "title": "پیش‌نویسِ برنامه در کمتر از یک دقیقه", "button": "شروع رایگان", "note": "panel.chagher.ir"},
    ]


def audit_spec(store, style_id: str, aspect: str, *, plan: str = "store", brand: bool = True) -> dict:
    d = assets.store_defaults(store)
    colors = d["colors"] or (CHAGHER_COLORS if plan == "chagher" else [])
    b = {"use_brand_colors": bool(brand and colors), "show_logo": bool(d["logo"]), "colors": colors, "name": d["name"]}
    if d["logo"]:
        b["logo"] = d["logo"]
    scenes = chagher_scenes() if plan == "chagher" else stylecheck.sample_scenes(store)
    return specs.normalize_spec({"version": 2, "style": style_id, "aspect": aspect, "fps": 30, "lang": "fa", "digits": "auto", "brand": b, "scenes": scenes})


def _tag(style_id: str, aspect: str) -> str:
    return f"{style_id}__{aspect.replace(':', 'x')}"


def _slim(findings: list) -> list:
    return [{k: f.get(k) for k in ("code", "severity", "scene", "message", "ratio")} for f in findings]


def run(store, ids, aspects, out: Path, *, plan: str = "store", frames: int = 1, brand: bool = True, as_draft: bool = False, resume: bool = False, say=print) -> list:
    """⇒ فهرستِ ردیف‌ها {style, aspect, frames, errors, warnings}؛ برای هر سبک/اندازه یک `<out>/<style>__<aspect>.json` و فریم‌ها در `<out>/img/`."""
    out = Path(out)
    (out / "img").mkdir(parents=True, exist_ok=True)
    ok, why = qa_browser.available()
    if not ok:
        raise RuntimeError("ابزارِ رندرِ سایت آماده نیست: " + why)
    rows: list = []
    work = Path(tempfile.mkdtemp(prefix="nm-style-audit-"))
    lock = runner.SiteLock()
    lock.acquire()
    try:
        for sid in ids:
            st = catalog.get(sid)
            if not st:
                say(f"سبکِ ناشناخته: {sid}")
                continue
            for asp in aspects:
                tag = _tag(sid, asp)
                jf = out / f"{tag}.json"
                if resume and jf.exists():
                    continue
                draft_id = f"u{store.pk}-audit"
                ctx = None
                use_id = sid
                if as_draft:
                    # the style rides along with the plan (style_def): an edit of catalog.py shows up without rebuilding the render bundle
                    sdef = custom.to_styledef(draft_id, {k: v for k, v in st.items() if k not in ("id", "custom", "scope", "group_label", "fits")}, scope="store")
                    ctx, use_id = custom.draft(draft_id, sdef), draft_id
                try:
                    if ctx is not None:
                        ctx.__enter__()
                    spec = audit_spec(store, use_id, asp, plan=plan, brand=brand)
                    measure = qa_browser.make_measure(store, workdir=work / tag, media_dir=None, prefix="a", per_scene=max(1, min(2, frames)))
                    shots = measure(spec)
                    findings = qa.geometry_findings(spec, shots)
                    kept = []
                    for s in shots:
                        dest = out / "img" / f"{tag}__s{s['scene']}__{s['kind']}.jpg"
                        if s.get("_image") is not None:
                            s["_image"].convert("RGB").save(dest, quality=86)
                        kept.append({"scene": s["scene"], "kind": s["kind"], "frame": s["frame"], "image": dest.name})
                    slim = _slim(findings)
                    jf.write_text(json.dumps({"style": sid, "aspect": asp, "findings": slim, "shots": kept}, ensure_ascii=False), encoding="utf-8")
                    row = {"style": sid, "aspect": asp, "frames": len(shots), "errors": sum(1 for f in slim if f["severity"] == "error"), "warnings": sum(1 for f in slim if f["severity"] == "warn")}
                except Exception as exc:  # noqa: BLE001 — a style that cannot render is itself a finding
                    row = {"style": sid, "aspect": asp, "frames": 0, "errors": 1, "warnings": 0, "failure": str(exc)[:300]}
                finally:
                    if ctx is not None:
                        ctx.__exit__(None, None, None)
                rows.append(row)
                say(json.dumps(row, ensure_ascii=False))
    finally:
        lock.release()
        shutil.rmtree(work, ignore_errors=True)
    return rows


def load_rows(out: Path, ids) -> list:
    rows = []
    for sid in ids:
        for asp in ("9:16", "16:9"):
            p = Path(out) / f"{_tag(sid, asp)}.json"
            if not p.exists():
                continue
            d = json.loads(p.read_text(encoding="utf-8"))
            errs = [f for f in d["findings"] if f["severity"] == "error"]
            warns = [f for f in d["findings"] if f["severity"] == "warn"]
            rows.append({"style": sid, "aspect": asp, "errors": len(errs), "warnings": len(warns), "messages": [f["message"] for f in errs + warns][:5], "shots": d["shots"]})
    return rows


def sheets(out: Path, ids, *, kind: str = "enter", per9: int = 8, per16: int = 16) -> dict:
    """برگه‌های تماس + findings.txt ⇒ {«9:16»: n، «16:9»: n}. هر سبک یک ردیف از چهار فریم (یک فریم برای هر صحنه) با برچسبِ خطا/هشدار."""
    from PIL import Image, ImageDraw, ImageFont

    out = Path(out)
    rows = load_rows(out, ids)
    with open(out / "findings.txt", "w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(f"{r['style']:28} {r['aspect']:6} err={r['errors']} warn={r['warnings']}  " + " | ".join(m[:100] for m in r["messages"]) + "\n")
    font = ImageFont.load_default()
    for cand in (Path(__file__).resolve().parents[2] / "services" / "imaging" / "fonts" / "Vazirmatn-Regular.ttf",):
        try:
            font = ImageFont.truetype(str(cand), 20)
            break
        except OSError:
            continue
    made = {}
    for asp, per, (fw, fh_) in (("9:16", per9, (200, 356)), ("16:9", per16, (232, 131))):
        have = [r for r in rows if r["aspect"] == asp]
        by = {r["style"]: r for r in have}
        order = [s for s in ids if s in by]
        n = 0
        cols = 2
        for k in range(0, len(order), per):
            chunk = order[k:k + per]
            height = ((len(chunk) + cols - 1) // cols) * (fh_ + 26)
            sheet = Image.new("RGB", (cols * 4 * fw + (cols - 1) * 8, height), (28, 28, 28))
            dr = ImageDraw.Draw(sheet)
            for i, sid in enumerate(chunk):
                r = by[sid]
                cx, cy = (i % cols) * (4 * fw + 8), (i // cols) * (fh_ + 26)
                dr.text((cx + 4, cy + 1), f"{ids.index(sid) + 1}. {sid}  e{r['errors']} w{r['warnings']}", fill=(255, 120, 120) if r["errors"] else (255, 235, 120), font=font)
                for c in range(4):
                    pth = out / "img" / f"{_tag(sid, asp)}__s{c}__{kind}.jpg"
                    if not pth.exists():
                        pth = out / "img" / f"{_tag(sid, asp)}__s{c}__enter.jpg"
                    if pth.exists():
                        sheet.paste(Image.open(pth).convert("RGB").resize((fw, fh_), Image.LANCZOS), (cx + c * fw, cy + 26))
            n += 1
            sheet.save(out / f"sheet-{asp.replace(':', 'x')}-{n:02d}.jpg", quality=84)
        made[asp] = n
    return made


def default_out() -> Path:
    from django.conf import settings

    return Path(settings.MEDIA_ROOT) / "generated" / "motion" / "style-audit" / time.strftime("%Y%m%d-%H%M%S")
