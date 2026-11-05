"""بخش‌های هوش مصنوعیِ طراحِ خودکار: برنامه‌ریز (planner) و منتقد (critic).

اصل: مدل **مختصات و اندازهٔ دقیق نمی‌دهد**. او فقط الگو، متن‌ها، حال‌وهوا و اصلاحِ رنگ را پیشنهاد می‌دهد و در صورتِ لزوم
چند مرحلهٔ اضافه از «کاتالوگِ ابزارها» (toolspec). چیدمان، اندازه‌ها و رنگ‌ها را لایهٔ قطعی (recipes/build/qa) می‌سازد؛ مدلِ
۱۲ میلیاردی هم بدونِ مهارتِ گرافیکی نتیجهٔ حرفه‌ای می‌دهد و مدلِ بزرگ‌تر فقط بهتر می‌شود.

هر جواب سخت‌گیرانه وارسی می‌شود (کلیدِ ناشناخته دور، مقدار در بازه). اگر هوشِ مصنوعی در دسترس نبود ``AIUnavailable`` با دلیلِ
فارسی برمی‌خیزد و فراخواننده بدونِ آن ادامه می‌دهد (و به کاربر می‌گوید کدام بخش به هوش مصنوعی نیاز داشت).
"""
from __future__ import annotations

import base64
import io
import json
import logging
import re

from .. import smart
from . import colorx, grid, recipes, toolspec

logger = logging.getLogger(__name__)

PLAN_TIMEOUT = 150
CRITIC_TIMEOUT = 150
IMAGE_SIDE = 768
MAX_EXTRA = 6
MAX_FIXES = 6
CRITERIA = ("hierarchy", "legibility", "contrast", "margins", "balance", "color", "typography", "prompt_fit")
CRITERIA_FA = {"hierarchy": "سلسله‌مراتب", "legibility": "خوانایی", "contrast": "کنتراست", "margins": "حاشیه و حاشیهٔ امن",
               "balance": "تعادل", "color": "هماهنگیِ رنگ", "typography": "تایپوگرافیِ فارسی", "prompt_fit": "هم‌خوانی با دستور"}


class AIUnavailable(RuntimeError):
    """هوشِ مصنوعیِ بینا جواب نداد؛ متنِ فارسی برای کاربر."""


def clean_reason(text) -> str:
    """دلیلِ شکستِ هوش مصنوعی برای صاحبِ فروشگاه: تکه‌های فنی (JSON ِ خطای سرویس، timestamp، نشانیِ API) برداشته و کوتاه می‌شود."""
    t = re.sub(r"\{.*?\}", "", str(text or ""), flags=re.S)
    t = re.sub(r"\(\s*timestamp[^)]*\)?", "", t)
    t = re.sub(r"https?://\S+", "", t)
    t = re.sub(r"\s+", " ", t).strip(" :؛;—-،,")
    return t[:220] or "هوش مصنوعی در دسترس نبود"


def _b64(img) -> str:
    im = img.convert("RGB")
    im.thumbnail((IMAGE_SIDE, IMAGE_SIDE))
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=84)
    return base64.b64encode(buf.getvalue()).decode("ascii")


def _ask(store, prompt: str, image, timeout: int) -> tuple[dict, dict]:
    """⇒ (JSON ِ جواب، {via, model, label, fell_back, reason}). هر شکستی ⇒ AIUnavailable(دلیلِ فارسی)."""
    try:
        provider = smart._vision(store)
        model = smart._model_for(provider)
        got = provider.generate_json(model, prompt, images=[_b64(image)], timeout=timeout)
        parsed = got[0] if isinstance(got, tuple) else got
    except Exception as exc:  # noqa: BLE001 — لوکال/متیس/سیاست/پیکربندی، هر چه بود
        raise AIUnavailable(clean_reason(smart._why(exc))) from exc
    if not isinstance(parsed, dict):
        raise AIUnavailable("هوشِ مصنوعی جوابِ قابل‌استفاده نداد.")
    return parsed, smart._describe(provider, model)


# ───────────────────────────── برنامه‌ریز

def _plan_prompt(brief: dict, an_public: dict, store_name: str) -> str:
    recs = "\n".join(f"- {k}: {v['title']} — {v['help']}" for k, v in recipes.RECIPES.items())
    pal = ", ".join(f"{p['hex']} ({p['name']}, {int(p['share'] * 100)}%)" for p in an_public["palette"][:4])
    return (
        "You are a senior Persian social-media graphic designer working for a small online shop. Look at the attached product photo and the "
        "owner's request, then choose the best design template and write the Persian copy. You do NOT place things by pixels: a layout engine "
        "does that. You only decide: template, mood, copy, colour grade and (optionally) a few extra steps from the tool catalogue.\n\n"
        f"Shop name: {store_name or '-'}\n"
        f"Owner's request (Persian): «{brief.get('prompt') or '-'}»\n"
        f"Target format: {grid.FORMAT_FA.get(brief.get('format'), brief.get('format'))}\n"
        f"Owner already typed these texts (keep them exactly): {json.dumps({k: v for k, v in (brief.get('copy') or {}).items() if v}, ensure_ascii=False)}\n\n"
        "Measured facts about the photo (trust them): "
        f"{json.dumps({'orientation': an_public['orientation'], 'brightness': an_public['brightness'], 'background_plain': an_public['background']['plain'], 'subject': an_public['subject'], 'dominant_colour': an_public['dominant'], 'palette': pal}, ensure_ascii=False)}\n\n"
        f"Templates (key — meaning):\n{recs}\n\n"
        f"Moods: {', '.join(colorx.MOODS)}.\n"
        f"Tool catalogue for optional extra steps (use sparingly, max {MAX_EXTRA}; each is {{\"tool\", \"params\", \"title\", \"why\"}}):\n{toolspec.prompt_catalog()}\n\n"
        "Rules: copy is short natural Persian (headline ≤ 6 words, subline ≤ 10 words, cta ≤ 4 words); never invent prices, discounts or "
        "claims that are not in the request; if the request has none leave those fields empty; use Persian digits; no emoji. "
        "The 'grade' is optional Lightroom-like slider values {\"exposure\": -1..1, \"contrast\": -100..100, \"temperature\": -100..100, "
        "\"vibrance\": -100..100, ...} only if the photo/mood needs it.\n"
        'Reply with ONLY this JSON: {"recipe": "<template key>", "mood": "<mood>", "copy": {"headline": "", "subline": "", "price": "", '
        '"discount": "", "cta": "", "badge": ""}, "grade": {}, "text_zone": "auto|top|bottom", "extra_steps": [], '
        '"notes": "one Persian sentence explaining the design idea"}'
    )


def validate_plan_reply(parsed) -> dict | None:
    """جوابِ خامِ برنامه‌ریز ⇒ {recipe, mood, copy, grade, text_zone, extra_steps, notes} وارسی‌شده یا None."""
    if not isinstance(parsed, dict):
        return None
    recipe = parsed.get("recipe") if parsed.get("recipe") in recipes.RECIPES else None
    mood = parsed.get("mood") if parsed.get("mood") in colorx.MOODS else "auto"
    copy_in = parsed.get("copy") if isinstance(parsed.get("copy"), dict) else {}
    limits = {"headline": 60, "subline": 90, "price": 40, "discount": 3, "cta": 32, "badge": 14, "old_price": 40}
    copy = {}
    for k, n in limits.items():
        v = copy_in.get(k)
        if isinstance(v, (str, int, float)) and not isinstance(v, bool):
            t = re.sub(r"[\x00-\x1f\x7f]+", " ", str(v)).strip()[:n]
            if t:
                copy[k] = t
    grade = smart.clean_adjust(parsed.get("grade")) if isinstance(parsed.get("grade"), dict) else {}
    zone = parsed.get("text_zone") if parsed.get("text_zone") in ("auto", "top", "bottom") else "auto"
    extra = []
    for i, s in enumerate((parsed.get("extra_steps") if isinstance(parsed.get("extra_steps"), list) else [])[:MAX_EXTRA]):
        try:
            st = toolspec.clean_step(dict(s, ai=True, id=f"x{i + 1}"), 100 + i)
        except (toolspec.PlanError, TypeError):
            continue
        if st["tool"] in ("frame", "rotate", "crop", "export", "cutout", "backdrop", "shadow", "compare", "grade"):
            continue            # مراحلِ ساختاری را الگو می‌گذارد، نه مدل
        extra.append(st)
    notes = smart.clean_notes(parsed.get("notes"))
    if not (recipe or copy or grade or extra or notes):
        return None
    return {"recipe": recipe, "mood": mood, "copy": copy, "grade": grade, "text_zone": zone, "extra_steps": extra, "notes": notes}


def plan_with_ai(store, image, brief: dict, an_public: dict) -> tuple[dict, dict]:
    """⇒ (جوابِ وارسی‌شده، meta). ``AIUnavailable`` اگر نشد."""
    prompt = _plan_prompt(brief, an_public, getattr(store, "name", ""))
    parsed, meta = _ask(store, prompt, image, PLAN_TIMEOUT)
    out = validate_plan_reply(parsed)
    if out is None:
        raise AIUnavailable(f"{meta.get('label') or 'هوش مصنوعی'} جوابِ قابل‌استفاده نداد.")
    return out, meta


# ───────────────────────────── منتقد

def _rubric(fmt: str) -> str:
    safe = grid.safe_rect(fmt)
    zone = ("Story safe zones: keep important content out of the top 14% and bottom 20% (Instagram UI)."
            if fmt == "story" else f"Keep text inside a safe margin (~{int(safe[0] * 100)}% sides, ~{int(safe[1] * 100)}% top/bottom).")
    return (
        "Score each criterion 1-10 (10 = professional agency quality): "
        "hierarchy (one clear focal message, headline clearly bigger than the rest), "
        "legibility (text readable at phone size), contrast (text vs its background; WCAG-like), "
        f"margins ({zone}), balance (visual weight not lopsided; whitespace), "
        "color (palette harmonises with the product; not garish), "
        "typography (Persian: correct letter joining, natural line breaks at phrase boundaries, no orphan single word lines, consistent digits, "
        "max 2 typefaces), prompt_fit (does it match the owner's request)."
    )


def _critic_prompt(brief: dict, summary: dict, fmt: str) -> str:
    steps = "\n".join(f"- id={s['id']} tool={s['tool']} «{s['title']}» params={json.dumps({k: v for k, v in s['params'].items() if v not in ('', None, False, {}, [])}, ensure_ascii=False)}"
                      for s in summary["steps"] if s["on"])
    return (
        "You are an art director reviewing a finished Persian social-media design (the attached image) made from the steps below. "
        f"Owner's request: «{brief.get('prompt') or '-'}». Format: {grid.FORMAT_FA.get(fmt, fmt)}.\n"
        f"Automatic checks already measured: {json.dumps(summary.get('qa', {}), ensure_ascii=False)}\n\n"
        f"Steps (you may fix these only):\n{steps}\n\n{_rubric(fmt)}\n\n"
        "Then list up to 4 concrete problems you SEE, each with ONE fix from this patch language: "
        '{"op":"set","step":"<step id>","param":"<param key of that tool>","value":<new value>} (e.g. role, slot, align, color, scale, plate, weight, font, '
        'text, strength, size, opacity), {"op":"remove","step":"<id>"}, {"op":"grade","adjust":{"exposure":0.2}}, {"op":"mood","value":"<mood>"}. '
        "Only fix real problems; if the design is already good, return verdict ok with no fixes. Persian text for problems.\n"
        'Reply with ONLY: {"scores": {"hierarchy": 8, "legibility": 8, "contrast": 8, "margins": 8, "balance": 8, "color": 8, "typography": 8, '
        '"prompt_fit": 8}, "verdict": "ok|revise", "issues": [{"problem": "...", "fix": {...}}], "summary": "one Persian sentence"}'
    )


def validate_critic_reply(parsed) -> dict | None:
    if not isinstance(parsed, dict):
        return None
    sc_in = parsed.get("scores") if isinstance(parsed.get("scores"), dict) else {}
    scores = {}
    for k in CRITERIA:
        v = smart._num(sc_in.get(k))
        if v is not None:
            scores[k] = round(max(1.0, min(10.0, v)), 1)
    if not scores:
        return None
    issues = []
    for it in (parsed.get("issues") if isinstance(parsed.get("issues"), list) else [])[:MAX_FIXES]:
        if not isinstance(it, dict):
            continue
        fix = it.get("fix") if isinstance(it.get("fix"), dict) else None
        issues.append({"problem": smart.clean_notes(it.get("problem"))[:200], "fix": fix})
    verdict = "ok" if parsed.get("verdict") == "ok" or not issues else "revise"
    return {"scores": scores, "verdict": verdict, "issues": issues, "summary": smart.clean_notes(parsed.get("summary")),
            "mean": round(sum(scores.values()) / len(scores), 2)}


def critique_with_ai(store, image, brief: dict, summary: dict, fmt: str) -> tuple[dict, dict]:
    parsed, meta = _ask(store, _critic_prompt(brief, summary, fmt), image, CRITIC_TIMEOUT)
    out = validate_critic_reply(parsed)
    if out is None:
        raise AIUnavailable(f"{meta.get('label') or 'هوش مصنوعی'} نقدِ قابل‌استفاده نداد.")
    return out, meta


# ───────────────────────────── زبانِ وصله (patch)

def apply_fixes(plan: dict, issues: list[dict]) -> tuple[dict, list[str], int]:
    """اصلاح‌های پیشنهادیِ منتقد را روی برنامه می‌نشاند. ⇒ (برنامهٔ تازه، جمله‌های فارسیِ آنچه اعمال شد، تعدادِ ردشده).

    فقط مرحله‌هایی که هستند و پارامترهایی که در کاتالوگ هستند؛ مقدار به بازه می‌رود. مرحله‌های ساختاری (قاب، خروجی) قابل‌حذف نیستند."""
    new = json.loads(json.dumps(plan))
    applied: list[str] = []
    rejected = 0
    by_id = {s["id"]: s for s in new["steps"]}
    for it in issues[:MAX_FIXES]:
        fix = it.get("fix") if isinstance(it, dict) else None
        if not isinstance(fix, dict):
            rejected += 1
            continue
        op = fix.get("op")
        if op == "set":
            st = by_id.get(str(fix.get("step")))
            spec = toolspec.BY_KEY.get(st["tool"]) if st else None
            ps = next((p for p in (spec or {}).get("params", []) if p["key"] == fix.get("param")), None)
            if st is None or ps is None:
                rejected += 1
                continue
            before = st["params"].get(ps["key"])
            val = toolspec.clean_param(ps, fix.get("value"))
            if val == before:
                rejected += 1
                continue
            st["params"][ps["key"]] = val
            st["ai"] = True
            applied.append(f"«{st['title']}»: {ps['title']} ⇐ {val}")
        elif op == "remove":
            st = by_id.get(str(fix.get("step")))
            if st is None or st["tool"] in ("frame", "export", "cutout", "backdrop"):
                rejected += 1
                continue
            st["on"] = False
            applied.append(f"«{st['title']}» برداشته شد")
        elif op == "grade":
            adj = smart.clean_adjust(fix.get("adjust"))
            if not adj:
                rejected += 1
                continue
            g = next((s for s in new["steps"] if s["tool"] == "grade"), None)
            if g is None:
                g = toolspec.clean_step({"id": "g", "tool": "grade", "title": "نور و رنگ", "params": {"adjust": adj}, "ai": True})
                new["steps"].append(g)
            else:
                merged = dict(g["params"]["adjust"])
                for k, v in adj.items():
                    merged[k] = round(merged.get(k, 0) + v, 3)
                g["params"]["adjust"] = smart.clean_adjust(merged)
                g["ai"] = True
            applied.append("نور و رنگ اصلاح شد")
        elif op == "mood":
            if fix.get("value") in colorx.MOODS and fix["value"] != new.get("mood"):
                new["mood"] = fix["value"]
                applied.append(f"حال‌وهوا ⇐ {colorx.MOOD_FA.get(fix['value'], fix['value'])}")
            else:
                rejected += 1
        else:
            rejected += 1
    new, _notes = toolspec.clean_plan(new)
    return new, applied, rejected
