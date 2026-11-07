"""رشتهٔ کارِ «طراحِ خودکار»: تحلیل ⇒ برنامه (هوش مصنوعی + الگو) ⇒ ساخت ⇒ وارسی/اصلاحِ قطعی ⇒ پیش‌نمایش ⇒ نقدِ هوش مصنوعی ⇒
اصلاح (حداکثر N دور) ⇒ ۲ تا ۳ پیشنهاد. نتیجه همیشه لایه‌ها و تنظیم‌های قابل‌ویرایشِ ادیتورِ دستی است.

بدونِ هوشِ مصنوعی هم همهٔ مراحلِ قطعی انجام می‌شود؛ ``design.ai`` می‌گوید کدام بخش به آن نیاز داشت و چرا اجرا نشد.
"""
from __future__ import annotations

import logging
import time

from django.utils import timezone

from .. import brand as brand_mod, matting, services
from ..models import PhotoAsset, PhotoDesign
from . import ai as ai_mod
from . import analyze, build as build_mod, colorx, grid, qa, recipes, render, toolspec

logger = logging.getLogger(__name__)

QUALITY_ROUNDS = {"fast": 0, "normal": 1, "best": 2}
AI_BUDGET_S = 540           # بعد از این مدت از شروع، دیگر از هوش مصنوعی نمی‌پرسیم (طراحی با قاعده‌ها تمام می‌شود)
MAX_ACTIVE = 2
COPY_KEYS = ("headline", "subline", "price", "old_price", "discount", "cta", "badge")
VARIANT_NAMES = ("سبکِ ۱", "سبکِ ۲", "سبکِ ۳")


class DesignError(Exception):
    """خطایی که متنش برای کاربر است."""


# ───────────────────────────── ساخت و ورودی

def clean_input(data: dict) -> dict:
    prompt = str((data or {}).get("prompt") or "").strip()[:600]
    recipe = data.get("recipe") if data.get("recipe") in recipes.RECIPES else ""
    fmt = data.get("format") if data.get("format") in grid.FORMAT_KEYS else ""
    mood = data.get("mood") if data.get("mood") in colorx.MOODS else "auto"
    quality = data.get("quality") if data.get("quality") in QUALITY_ROUNDS else "normal"
    copy_in = data.get("copy") if isinstance(data.get("copy"), dict) else {}
    copy = {}
    for k in COPY_KEYS:
        v = copy_in.get(k)
        if isinstance(v, (str, int, float)) and not isinstance(v, bool):
            t = str(v).strip()[:120]
            if t:
                copy[k] = t
    try:
        n = max(1, min(3, int(data.get("variants") or 3)))
    except (TypeError, ValueError):
        n = 3
    opts = {"variants": n, "use_ai": data.get("use_ai") is not False, "use_brand": data.get("use_brand") is not False}
    if "use_ai" not in data:
        opts.pop("use_ai")          # نیامده ⇒ create() از «پیش‌فرضِ کمکِ هوش مصنوعی» ِ فروشگاه می‌خواند
    if isinstance(data.get("brand"), dict) and data["brand"]:
        ov = brand_mod.clean(data["brand"])
        opts["brand"] = {k: ov[k] for k in ("colors", "heading_font", "body_font", "tone", "logo") if k in data["brand"]}
    return {"prompt": prompt, "recipe": recipe, "fmt": fmt, "mood": mood, "quality": quality, "copy": copy, "options": opts}


def create(store, user, asset: PhotoAsset, data: dict) -> PhotoDesign:
    inp = clean_input(data)
    if not inp["prompt"] and not inp["recipe"]:
        raise DesignError("یا دستور بنویسید یا یکی از الگوها را انتخاب کنید.")
    active = PhotoDesign.objects.filter(store=store, state__in=PhotoDesign.ACTIVE).count()
    if active >= MAX_ACTIVE:
        raise DesignError("دو طراحی هم‌زمان در حالِ انجام است؛ چند لحظه صبر کنید.")
    fmt = inp["fmt"] or (recipes.RECIPES[inp["recipe"]]["format"] if inp["recipe"] else "square")
    inp["options"].setdefault("use_ai", brand_mod.ai_default(store))
    return PhotoDesign.objects.create(store=store, asset=asset, created_by=user, prompt=inp["prompt"], recipe=inp["recipe"], fmt=fmt,
                                      mood=inp["mood"], quality=inp["quality"], copy=inp["copy"], options=inp["options"],
                                      message="در صف")


def _log(d: PhotoDesign, text: str, progress: float | None = None, message: str | None = None, **fields) -> None:
    d.log = (d.log or []) + [{"t": timezone.now().isoformat(timespec="seconds"), "text": text}]
    upd = ["log", "updated_at"]
    if progress is not None:
        d.progress = round(progress, 3)
        upd.append("progress")
    if message is not None:
        d.message = message[:300]
        upd.append("message")
    for k, v in fields.items():
        setattr(d, k, v)
        upd.append(k)
    d.save(update_fields=upd)


# ───────────────────────────── ساختِ یک پیشنهاد

def _composite(qa_score: float, ai_mean: float | None) -> float:
    return round(qa_score if ai_mean is None else 0.5 * qa_score + 0.5 * ai_mean * 10, 1)


def _save_preview(d: PhotoDesign, idx: int, img) -> str:
    rel = f"{d.dir_rel}/v{idx + 1}.jpg"
    from .. import ops

    ops.save_bytes(services.abs_path(rel), render.to_jpeg(img, 88, 1280))
    return rel


def make_variant(asset: PhotoAsset, d: PhotoDesign, idx: int, plan_raw: dict, user, src=None) -> tuple[dict, object]:
    """برنامهٔ خام ⇒ (پیشنهاد، تصویرِ پیش‌نمایش). وارسی، ساخت، اصلاحِ قطعی و رندر."""
    plan, plan_notes = toolspec.clean_plan(plan_raw)
    b = build_mod.build(asset, plan, user=user, tag=f"d{d.pk}", src=src, kit=brand_mod.effective(d.store, d.options))
    fixes = qa.autofix(asset, b)
    img, _frame, rnotes = render.render_state(asset, b["state"], frame=b["frame"])
    rel = _save_preview(d, idx, img)
    qa_res = b["qa"]
    variant = {
        "id": f"v{idx + 1}", "index": idx, "title": f"{plan.get('title') or 'طراحی'} — {VARIANT_NAMES[idx % 3]}", "recipe": plan["recipe"],
        "plan": plan, "state": b["state"], "preview_rel": rel, "canvas": b["canvas"], "palette": b["palette"],
        "qa": {"score": qa_res["score"], "issues": [i["text"] for i in qa_res["issues"]], "fixes": fixes, "metrics": qa_res["metrics"]},
        "report": b["report"], "notes": list(dict.fromkeys(plan_notes + b["notes"] + rnotes))[:8], "needs": b["needs"],
        "cutout": b.get("cutout"), "rounds": [], "ai_mean": None, "score": _composite(qa_res["score"], None),
    }
    return variant, img


def _ai_overlay(plan_raw: dict, ai_plan: dict | None, zone_pref: str) -> dict:
    """جوابِ برنامه‌ریز ⇒ روی برنامهٔ الگو: رنگِ پیشنهادی، مراحلِ اضافه، جایِ متن."""
    if not ai_plan:
        return plan_raw
    steps = plan_raw["steps"]
    if ai_plan.get("grade"):
        g = next((s for s in steps if s["tool"] == "grade"), None)
        if g is not None:
            merged = dict(g["params"].get("adjust") or {})
            for k, v in ai_plan["grade"].items():
                merged[k] = v
            g["params"]["adjust"] = merged
            g["ai"] = True
            g["why"] = (g.get("why") or "") + " (با پیشنهادِ هوش مصنوعی)"
    zone = ai_plan.get("text_zone")
    if zone in ("top", "bottom"):
        for s in steps:
            if s["tool"] == "text" and s["params"].get("slot") == "auto":
                s["params"]["slot"] = zone
    for s in ai_plan.get("extra_steps") or []:
        steps.append(dict(s))
    return plan_raw


def run(design_id: int) -> None:
    # فقط یک کارگر طراحی را برمی‌دارد (پنل کارِ مانده در صف را دوباره می‌فرستد؛ دو اجرای هم‌زمان فایل‌ها را به‌هم می‌ریخت)
    claimed = PhotoDesign.objects.filter(pk=design_id, state=PhotoDesign.State.QUEUED).update(
        state=PhotoDesign.State.RUNNING, message="شروع شد", updated_at=timezone.now())
    if not claimed:
        return
    d = PhotoDesign.objects.select_related("asset", "asset__store", "store", "created_by").filter(pk=design_id).first()
    if d is None:
        return
    began = time.monotonic()
    try:
        _run(d)
    except Exception as exc:  # noqa: BLE001
        logger.exception("photoedit.designer: design %s failed", d.pk)
        _log(d, f"خطای داخلی: {exc}", message="ناموفق", state=PhotoDesign.State.FAILED, error=str(exc)[:1500])
    else:
        logger.info("photoedit.designer: design %s done in %.1fs", d.pk, time.monotonic() - began)


def _run(d: PhotoDesign) -> None:
    asset, store, user = d.asset, d.store, d.created_by
    t0 = time.monotonic()
    n = int((d.options or {}).get("variants") or 3)
    use_ai = (d.options or {}).get("use_ai") is not False
    rounds_max = QUALITY_ROUNDS.get(d.quality, 1) if use_ai else 0
    _log(d, "عکس را می‌سنجم…", 0.03, "عکس را می‌سنجم…", state=PhotoDesign.State.RUNNING)
    src = render.source_image(asset)
    an0 = analyze.analyze(src, fmt="orig", facts=asset.facts, findings=asset.findings)
    an_pub = analyze.public(an0)
    desc = analyze.describe_fa(an0)
    ai_info = {"enabled": use_ai, "planner": {"used": False, "reason": ""}, "critic": {"used": False, "rounds": 0, "reason": ""}}
    _log(d, desc, 0.1, "تحلیل شد", analysis=dict(an_pub, description=desc))
    kit = brand_mod.effective(store, d.options)
    has_logo = (services._store_logo(store) is not None or brand_mod.logo_asset(store, kit) is not None) and ((kit or {}).get("logo") or {}).get("mode") != "none"
    brief = {"prompt": d.prompt, "format": d.fmt, "copy": d.copy, "mood": d.mood, "has_logo": has_logo, "an": an_pub,
             "brand_tone": (kit or {}).get("tone", "")}

    ai_plan = None
    if use_ai:
        _log(d, "از هوشِ مصنوعی می‌پرسم کدام الگو و چه متنی بهتر است…", 0.14, "هوش مصنوعی در حالِ برنامه‌ریزی…")
        try:
            ai_plan, meta = ai_mod.plan_with_ai(store, src, brief, an_pub)
            ai_info["planner"] = {"used": True, "label": meta.get("label", ""), "model": meta.get("model", ""), "fell_back": meta.get("fell_back", False),
                                  "notes": ai_plan.get("notes", ""), "reason": ""}
            _log(d, f"{meta.get('label') or 'هوش مصنوعی'}: {ai_plan.get('notes') or 'برنامه را نوشت'}", 0.22)
        except ai_mod.AIUnavailable as exc:
            ai_info["planner"] = {"used": False, "reason": str(exc)}
            _log(d, f"هوشِ مصنوعی در دسترس نبود ({exc}). الگو و متن‌ها را با قاعده‌های آماده می‌سازم.", 0.22)
    else:
        ai_info["planner"] = {"used": False, "reason": "خاموش بود (بدونِ هوش مصنوعی)"}

    parsed = recipes.parse_prompt(d.prompt)
    recipe = d.recipe or (ai_plan or {}).get("recipe") or parsed.get("recipe") or ("product_ad" if an_pub["background"]["plain"] else "caption")
    mood = d.mood if d.mood != "auto" else ((ai_plan or {}).get("mood") if (ai_plan or {}).get("mood") not in (None, "auto") else parsed.get("mood", "auto"))
    fmt = d.fmt or recipes.RECIPES[recipe]["format"]
    if recipe == "story":
        fmt = "story"
    brief.update({"format": fmt, "mood": mood, "ai_copy": (ai_plan or {}).get("copy") or {},
                  "can_cutout": recipe in recipes.CUTOUT_RECIPES and (an_pub["background"]["plain"] or an_pub["has_alpha"] or matting.available())})
    if recipe in recipes.CUTOUT_RECIPES and not brief["can_cutout"]:
        _log(d, "زمینهٔ عکس ساده نیست؛ محصول را جدا نمی‌کنم و طراحی را روی خودِ عکس می‌سازم (برای جداسازیِ دقیق «حذف پس‌زمینه» در حالتِ دستی را بزنید).")
    d.recipe, d.mood, d.fmt = recipe, mood, fmt
    d.save(update_fields=["recipe", "mood", "fmt"])

    variants: list[dict] = []
    images: list = []
    for i in range(n):
        _log(d, f"پیشنهادِ {i + 1} از {n} را می‌سازم…", 0.25 + 0.45 * i / n, f"ساختِ پیشنهادِ {i + 1} از {n}…")
        plan_raw = recipes.make_plan(recipe, dict(brief, variation=i))
        plan_raw = _ai_overlay(plan_raw, ai_plan, "auto")
        v, img = make_variant(asset, d, i, plan_raw, user, src=src)
        variants.append(v)
        images.append(img)
        d.variants = variants
        d.save(update_fields=["variants", "updated_at"])
    _log(d, f"{n} پیشنهادِ اولیه با بررسیِ خودکارِ کنتراست، حاشیه و خوانایی آماده شد.", 0.7, "بررسی و نقد…", variants=variants)

    # نقدِ هوش مصنوعی + اصلاح
    if rounds_max:
        crit_dead = ""
        used_rounds = 0
        label = ""
        for i, v in enumerate(variants):
            if crit_dead:
                break
            img = images[i]
            for r in range(rounds_max):
                if time.monotonic() - t0 > AI_BUDGET_S:
                    crit_dead = "وقتِ در نظر گرفته‌شده برای هوش مصنوعی تمام شد"
                    break
                _log(d, f"منتقدِ هوش مصنوعی پیشنهادِ {i + 1} را بررسی می‌کند (دورِ {r + 1})…", 0.7 + 0.25 * (i + (r / rounds_max)) / n,
                     f"نقدِ پیشنهادِ {i + 1}…")
                summary = {"steps": v["plan"]["steps"], "qa": {"score": v["qa"]["score"], "problems": v["qa"]["issues"][:5],
                                                              "min_contrast": v["qa"]["metrics"].get("min_contrast")}}
                try:
                    crit, meta = ai_mod.critique_with_ai(store, img, brief, summary, fmt)
                except ai_mod.AIUnavailable as exc:
                    crit_dead = str(exc)
                    break
                label = meta.get("label", label)
                used_rounds += 1
                v["ai_mean"] = crit["mean"]
                v["score"] = _composite(v["qa"]["score"], crit["mean"])
                rec = {"scores": crit["scores"], "mean": crit["mean"], "summary": crit["summary"], "issues": [x["problem"] for x in crit["issues"] if x["problem"]],
                       "applied": [], "accepted": False}
                v["rounds"].append(rec)
                if crit["verdict"] == "ok" or not crit["issues"]:
                    break
                new_plan, applied, _rej = ai_mod.apply_fixes(v["plan"], crit["issues"])
                if not applied:
                    break
                try:
                    nv, nimg = make_variant(asset, d, i, new_plan, user, src=src)
                except Exception:  # noqa: BLE001 — اصلاحِ خراب نباید پیشنهادِ سالم را بکشد
                    logger.exception("designer: revised plan failed to build")
                    break
                rec["applied"] = applied
                if nv["qa"]["score"] >= v["qa"]["score"] - 3:      # اصلاح نباید وارسیِ قطعی را خراب کند
                    nv["rounds"] = v["rounds"]
                    nv["ai_mean"] = v["ai_mean"]
                    nv["score"] = _composite(nv["qa"]["score"], nv["ai_mean"])
                    rec["accepted"] = True
                    variants[i] = v = nv
                    img = images[i] = nimg
                else:
                    _save_preview(d, i, img)                           # پیش‌نمایشِ قبلی را برگردان
                    rec["accepted"] = False
                    break
            d.variants = variants
            d.save(update_fields=["variants", "updated_at"])
        ai_info["critic"] = {"used": used_rounds > 0, "rounds": used_rounds, "label": label, "reason": crit_dead}
    elif use_ai:
        ai_info["critic"] = {"used": False, "rounds": 0, "reason": "دقتِ «سریع» نقدِ هوش مصنوعی ندارد"}
    else:
        ai_info["critic"] = {"used": False, "rounds": 0, "reason": "خاموش بود (بدونِ هوش مصنوعی)"}

    best = max(range(len(variants)), key=lambda k: variants[k]["score"])
    for k, v in enumerate(variants):
        v["best"] = k == best
    missing = []
    if not ai_info["planner"].get("used"):
        missing.append("انتخابِ هوشمندِ الگو و نوشتنِ متن")
    if not ai_info["critic"].get("used") and rounds_max:
        missing.append("نقدِ طرح و اصلاحِ آن")
    msg = f"{len(variants)} پیشنهاد آماده است" + (f" — بدونِ هوشِ مصنوعی برای: {'، '.join(missing)}" if missing and use_ai else "")
    _log(d, msg, 1.0, msg[:300], variants=variants, ai=ai_info, state=PhotoDesign.State.READY)


# ───────────────────────────── ویرایشِ یک پیشنهاد (بی هوشِ مصنوعی)

def rerender(d: PhotoDesign, idx: int, plan_raw: dict, user) -> dict:
    """مرحله‌های ویرایش‌شدهٔ کاربر ⇒ ساختِ دوباره (قطعی و سریع)؛ هوشِ مصنوعی صدا زده نمی‌شود."""
    if not (0 <= idx < len(d.variants or [])):
        raise DesignError("پیشنهاد پیدا نشد.")
    if not isinstance(plan_raw, dict):
        raise DesignError("برنامه نامعتبر است.")
    old = d.variants[idx]
    raw = dict(plan_raw)
    raw.setdefault("recipe", old["recipe"])
    raw.setdefault("format", old["plan"]["format"])
    raw.setdefault("variation", old["plan"].get("variation", 0))
    raw.setdefault("title", old["plan"].get("title", ""))
    raw.setdefault("mood", old["plan"].get("mood", "auto"))
    nv, _img = make_variant(d.asset, d, idx, raw, user)
    nv["edited"] = True
    nv["rounds"] = old.get("rounds", [])
    nv["ai_mean"] = old.get("ai_mean")
    nv["score"] = _composite(nv["qa"]["score"], None)
    nv["best"] = False
    variants = list(d.variants)
    variants[idx] = nv
    d.variants = variants
    d.save(update_fields=["variants", "updated_at"])
    return nv


# ───────────────────────────── اعمال

def apply(d: PhotoDesign, idx: int, user) -> tuple:
    """پیشنهاد ⇒ پروژهٔ قابل‌ویرایشِ ادیتورِ دستی + یک نسخهٔ ساخته‌شده. ⇒ (project, edit)."""
    if d.state != PhotoDesign.State.READY or not (0 <= idx < len(d.variants or [])):
        raise DesignError("این پیشنهاد آماده نیست.")
    v = d.variants[idx]
    store, asset = d.store, d.asset
    title = f"{v['title']}"[:190]
    project = services.create_project(store, asset, title, v["state"])
    plan = v["plan"]
    exp = toolspec.find(plan, "export")
    state = dict(v["state"])
    if exp:
        state["out"] = {"format": exp["params"]["format"], "quality": exp["params"]["quality"], "max_kb": exp["params"]["max_kb"],
                        "long_edge": exp["params"]["long_edge"]}
    ops_ = render.normalized(state, project.pk, "all", store)
    edits = services.create_edits(store, user, [asset.pk], "designer", ops_, order=2)
    d.chosen = idx
    d.project = project
    d.edit = edits[0]
    d.save(update_fields=["chosen", "project", "edit", "updated_at"])
    return project, edits[0]


# ───────────────────────────── نمایش

def variant_dict(v: dict, *, full: bool = True) -> dict:
    out = {k: v[k] for k in ("id", "index", "title", "recipe", "canvas", "palette", "qa", "notes", "needs", "rounds", "score", "ai_mean", "best",
                             "edited", "cutout") if k in v}
    out["preview"] = services.media_url(v.get("preview_rel"))
    if full:
        out["plan"] = v["plan"]
        out["report"] = v.get("report", {})
    return out


def design_dict(d: PhotoDesign, *, full: bool = True) -> dict:
    return {
        "id": d.pk, "asset": d.asset_id, "state": d.state, "state_label": d.get_state_display(), "active": d.active, "progress": d.progress,
        "message": d.message, "error": d.error, "prompt": d.prompt, "recipe": d.recipe, "format": d.fmt, "mood": d.mood, "quality": d.quality,
        "copy": d.copy, "analysis": d.analysis, "ai": d.ai, "log": (d.log or [])[-14:], "chosen": d.chosen, "project": d.project_id,
        "edit": d.edit_id, "created_at": d.created_at, "updated_at": d.updated_at,
        "variants": [variant_dict(v, full=full) for v in (d.variants or [])],
    }
