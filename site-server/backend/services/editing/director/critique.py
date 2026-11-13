"""The editing RUBRIC: a deterministic critique of a finished project, with fixes the director can apply by itself.

Eight things a pro editor checks, each as an item `{"key","title","ok","severity": info|warn|bad,"detail","fix": [steps]|None}`:

hook (a picture at 0 s and text in the first 3 s) · pacing (average shot length for the platform) · beats (cuts on the music's
beats) · word cuts (no cut in the middle of a spoken word) · captions (readable, inside the platform's safe zone) · audio
levels (speech above music, final loudness) · brand/CTA (the product is used, the video ends on a call to action) · length
(platform limit and the requested length) — plus black gaps. `fix` steps are catalogue tool calls, so applying them is just
another plan run. A model-based visual critique (`loop.vision_critique`) is added on top when a vision model is available.
"""
from __future__ import annotations

from .. import safezones
from . import projectops as ops
from .brief import PLATFORMS

SEVERITY_COST = {"bad": 22, "warn": 10, "info": 3}


def _item(key: str, title: str, ok: bool, severity: str, detail: str, fix: list | None = None) -> dict:
    return {"key": key, "title": title, "ok": ok, "severity": "info" if ok else severity, "detail": detail, "fix": fix if not ok else None}


def _main_clips(project: dict) -> list[dict]:
    t = ops.main_track(project)
    return sorted([c for c in t["clips"] if c.get("type") == "media" and not (c.get("ref") == "shape" and c.get("label") == "کارتِ پایانی")], key=lambda c: float(c["at"]))


def _fa(x) -> str:
    from .tools import fa

    return fa(x)


def critique(project: dict, an: dict, brief: dict) -> dict:
    plat = PLATFORMS.get(brief.get("platform") or "reels", PLATFORMS["reels"])
    total = ops.project_length(project)
    main = _main_clips(project)
    texts = [c for t in project["tracks"] if t["kind"] == "text" for c in t["clips"]]
    items: list[dict] = []
    polish = brief.get("recipe") == "polish"          # a talk made professional is not re-cut, sold or shortened by the product rubric
    zone = safezones.margins(plat["zone"], (project.get("format") or {}).get("preset", "reel"))

    # 1 · hook ---------------------------------------------------------------
    opens = bool(main) and float(main[0]["at"]) <= 0.05
    hook_text = [c for c in texts if float(c["at"]) <= 3.0 and not c.get("caption")]
    if not opens:
        items.append(_item("hook", "قلاب در ثانیه‌های اول", False, "bad", "ثانیهٔ صفرِ ویدیو تصویر ندارد (سیاه شروع می‌شود).", [{"tool": "close_gaps", "params": {"track": "main"}, "why": "شروعِ سیاه برداشته شد"}]))
    elif not hook_text and not any(c.get("caption") and float(c["at"]) <= 3.0 for c in texts):
        title = (brief.get("title") or "").strip()
        fix = [{"tool": "add_title", "params": {"text": title, "at": 0.25, "duration": 2.4, "template": "title_big"}, "why": "تیتر روی ثانیه‌های اول"}] if title else None
        items.append(_item("hook", "قلاب در ثانیه‌های اول", False, "warn", "در ۳ ثانیهٔ اول هیچ تیتر یا نوشته‌ای نیست؛ بیننده دلیلی برای ماندن نمی‌بیند.", fix))
    else:
        items.append(_item("hook", "قلاب در ثانیه‌های اول", True, "info", "ویدیو از ثانیهٔ صفر تصویر و نوشته دارد."))

    # 2 · pacing -------------------------------------------------------------
    if main and not polish:
        lens = [ops.clip_length(c) for c in main]
        avg = sum(lens) / len(lens)
        lo, hi = plat["shot"]
        longest = max(lens)
        if avg > hi * 1.35 and len(main) >= 2:
            items.append(_item("pacing", "ریتمِ برش‌ها", False, "warn", f"میانگینِ هر نما {_fa(round(avg, 1))} ثانیه است؛ برای {plat['title']} کند است (حدود {_fa(lo)} تا {_fa(hi)} ثانیه بهتر است).", None))
        elif longest > max(6.5, hi * 2) and plat["preset"] == "reel":
            items.append(_item("pacing", "ریتمِ برش‌ها", False, "info", f"یک نما {_fa(round(longest, 1))} ثانیه بی‌برش مانده؛ در ریلز بهتر است کوتاه‌تر شود.", None))
        else:
            items.append(_item("pacing", "ریتمِ برش‌ها", True, "info", f"میانگینِ نماها {_fa(round(avg, 1))} ثانیه است."))

    # 3 · cuts on beats ------------------------------------------------------
    music = next((c for t in project["tracks"] if t["kind"] == "audio" and t.get("role") == "music" for c in t["clips"]), None)
    row = an["by_ref"].get(music["ref"]) if music else None
    if music and row and len(row.get("beats", [])) >= 8 and len(main) >= 4 and not polish:      # a talk's cuts follow its pauses, never the music (that would chop it into 99 shots)
        beats = [ops.source_to_timeline(music, b) for b in row["beats"] if float(music["start"]) <= b <= float(music["end"])]
        cuts = [float(c["at"]) for c in main[1:]]
        near = sum(1 for t in cuts if beats and min(abs(t - b) for b in beats) <= 0.12)
        frac = near / max(1, len(cuts))
        if frac < 0.5:
            fix = [{"tool": "cut_to_beats", "params": {"music": music["ref"], "every": 2}, "why": "برش‌ها روی ضرب نشست"}]
            items.append(_item("beats", "برش روی ضربِ موسیقی", False, "info", f"فقط {_fa(round(frac * 100))}٪ برش‌ها روی ضرب است.", fix))
        else:
            items.append(_item("beats", "برش روی ضربِ موسیقی", True, "info", f"{_fa(round(frac * 100))}٪ برش‌ها روی ضرب است."))

    # 4 · no cut in the middle of a word ------------------------------------
    bad_cuts = []
    for a, b in zip(main, main[1:]):
        if a.get("ref") != b.get("ref") or abs(ops.clip_end(a) - float(b["at"])) > 0.15:
            pass
        for cl, edge in ((a, float(a["end"])), (b, float(b["start"]))):
            w_row = an["by_ref"].get(cl.get("ref"))
            for w in (w_row or {}).get("words", []):
                if float(w["s"]) + 0.04 < edge < float(w["e"]) - 0.04:
                    bad_cuts.append((cl, edge, w))
    if bad_cuts:
        fix = []
        for cl, edge, w in bad_cuts[:6]:
            to_end = abs(edge - float(w["e"])) <= abs(edge - float(w["s"]))
            if cl["end"] == edge:
                fix.append({"tool": "trim_clip", "params": {"clip": cl["id"], "end": round(float(w["e"]) + 0.04 if to_end else float(w["s"]) - 0.04, 3)}, "why": "برش به مرزِ کلمه رفت"})
            else:
                fix.append({"tool": "trim_clip", "params": {"clip": cl["id"], "start": round(float(w["s"]) - 0.04 if not to_end else float(w["e"]) + 0.04, 3)}, "why": "برش به مرزِ کلمه رفت"})
        items.append(_item("words", "بریدنِ وسطِ کلمه", False, "warn", f"{_fa(len(bad_cuts))} برش وسطِ یک کلمه افتاده است.", fix))
    elif an.get("has_words"):
        items.append(_item("words", "بریدنِ وسطِ کلمه", True, "info", "هیچ برشی وسطِ کلمه نیست."))

    # 5 · captions -----------------------------------------------------------
    caps = [c for c in texts if c.get("caption")]
    if caps:
        probs = []
        ys = [float(c.get("y") if c.get("y") is not None else 0.86) for c in caps]
        if any(y > 1 - zone["bottom"] - 0.015 for y in ys):
            probs.append("زیرنویس روی ناحیهٔ دکمه‌ها و کپشنِ پلتفرم افتاده")
        if plat["preset"] == "reel" and any(float(c.get("size") or 6) < 5 for c in caps):
            probs.append("حروفِ زیرنویس برای موبایل ریز است")
        if any(len(str(c.get("text", ""))) > 42 for c in caps):
            probs.append("بعضی خط‌های زیرنویس خیلی بلند است")
        if probs:
            fix = [{"tool": "caption_style", "params": {"style": "pop"}, "why": "زیرنویس درشت و داخلِ ناحیهٔ امن آمد"}]
            items.append(_item("captions", "خوانایی و جای زیرنویس", False, "warn", "؛ ".join(probs) + ".", fix))
        else:
            items.append(_item("captions", "خوانایی و جای زیرنویس", True, "info", "زیرنویس‌ها خوانا و داخلِ ناحیهٔ امن‌اند."))
    elif an.get("has_speech") and brief.get("captions") is not False:
        items.append(_item("captions", "خوانایی و جای زیرنویس", False, "info", "ویدیو گفتار دارد ولی زیرنویس ندارد؛ بیشترِ بینندگان بی‌صدا تماشا می‌کنند.", [{"tool": "add_captions", "params": {"clip": "all", "style": "pop"}, "why": "زیرنویس اضافه شد"}]))

    # 6 · audio levels -------------------------------------------------------
    speech = any((t["kind"] == "audio" and t.get("role") == "speech" and t["clips"]) or (t["kind"] == "video" and any(c.get("has_audio") and c.get("audio_on", True) and c.get("kind") == "video" for c in t["clips"])) for t in project["tracks"])
    music_clips = [c for t in project["tracks"] if t["kind"] == "audio" and t.get("role") == "music" for c in t["clips"]]
    duck = (project.get("ducking") or {}).get("on")
    if speech and music_clips:
        loud = max(float(c.get("volume", 1)) for c in music_clips)
        db = 20 * __import__("math").log10(max(loud, 1e-4))
        if db > -12 and not duck:
            items.append(_item("levels", "گفتار بالاتر از موسیقی", False, "bad", f"موسیقی {_fa(round(db))} dB است و زیرِ گفتار کم نمی‌شود؛ صدا قاطی می‌شود.", [{"tool": "auto_mix", "params": {}, "why": "موسیقی پایین و کم‌شونده شد"}]))
        else:
            items.append(_item("levels", "گفتار بالاتر از موسیقی", True, "info", "موسیقی زیرِ گفتار نشسته است."))
    loud_on = ((project.get("master") or {}).get("loudness") or {}).get("on")
    if speech or music_clips:
        items.append(_item("loudness", "بلندیِ نهایی برای شبکه‌ها", bool(loud_on), "info", "بلندیِ خروجی استاندارد نشده؛ اینستاگرام خودش صدا را بالا/پایین می‌برد." if not loud_on else "روی حدود ‎−۱۴ LUFS تنظیم است.", [{"tool": "set_loudness", "params": {"on": True, "target": -14, "tp": -1}, "why": "بلندیِ استاندارد"}]))

    # 7 · brand + CTA --------------------------------------------------------
    used = {c.get("ref") for t in project["tracks"] for c in t["clips"] if c.get("type") == "media"}
    owned = [r for r in an["by_ref"] if str(r).startswith("pimg:")]
    if owned and not all(r in used for r in owned):
        items.append(_item("brand", "محصول/برند دیده شود", False, "info", "عکسِ محصولی که انتخاب کردید در ویدیو استفاده نشده است.", None))
    elif owned:
        items.append(_item("brand", "محصول/برند دیده شود", True, "info", "عکسِ محصول در ویدیو هست."))
    tail_start = max(0.0, total - 3.6)
    has_cta = any(float(c["at"]) >= tail_start - 0.2 and len(str(c.get("text", ""))) >= 4 for c in texts if not c.get("caption")) or any(c.get("label") == "کارتِ پایانی" for c in main + [x for t in project["tracks"] for x in t["clips"] if x.get("type") == "media"])
    if not polish:
      items.append(_item("cta", "دعوت به اقدام در پایان", has_cta, "warn", "ویدیو با یک دعوت به اقدام (سفارش، تماس، بازدید) تمام نمی‌شود." if not has_cta else "پایانِ ویدیو دعوت به اقدام دارد.",
                       [{"tool": "end_card", "params": {"text": brief.get("cta") or "همین حالا سفارش بده", "duration": 2.5}, "why": "کارتِ پایانی اضافه شد"}]))

    # 8 · length -------------------------------------------------------------
    if total > plat["max"] + 0.5:
        items.append(_item("length", "طولِ ویدیو برای پلتفرم", False, "warn" if polish else "bad", f"{_fa(round(total))} ثانیه است؛ {plat['title']} تا {_fa(plat['max'])} ثانیه را می‌پذیرد.", None if polish else [{"tool": "fit_length", "params": {"seconds": plat["max"] - 1, "mode": "trim"}, "why": "کوتاه شد تا در حدِ مجاز بماند"}]))
    elif brief.get("duration") and total > float(brief["duration"]) * 1.3 and (not polish or "مدت" in (brief.get("matched") or [])):      # a talk is shortened only when the owner asked for a length
        items.append(_item("length", "طولِ ویدیو برای پلتفرم", False, "warn", f"خواسته بودید حدود {_fa(brief['duration'])} ثانیه؛ ویدیو {_fa(round(total))} ثانیه شد.", [{"tool": "fit_length", "params": {"seconds": float(brief["duration"]), "mode": "trim"}, "why": "به مدتِ خواسته نزدیک شد"}]))
    else:
        items.append(_item("length", "طولِ ویدیو برای پلتفرم", True, "info", f"{_fa(round(total))} ثانیه — مناسبِ {plat['title']}."))

    # 9 · black gaps ---------------------------------------------------------
    gaps = 0
    cur = 0.0
    for c in main:
        if float(c["at"]) > cur + 0.12:
            gaps += 1
        cur = max(cur, ops.clip_end(c))
    if gaps:
        items.append(_item("gaps", "فاصلهٔ سیاه", False, "warn", f"{_fa(gaps)} فاصلهٔ خالی (سیاه) بین نماها هست.", [{"tool": "close_gaps", "params": {"track": "main"}, "why": "فاصله‌ها بسته شد"}]))

    score = 100 - sum(SEVERITY_COST[i["severity"]] for i in items if not i["ok"])
    bad = [i for i in items if not i["ok"]]
    return {"score": max(0, min(100, score)), "items": items,
            "summary": "همه‌چیز مرتب است." if not bad else "؛ ".join(i["title"] for i in bad[:4])}


def auto_fixes(report: dict, *, done: set[str] | None = None) -> list[dict]:
    """The fix steps of every failing warn/bad item that has one (each item's fix only once per run)."""
    done = done if done is not None else set()
    steps: list[dict] = []
    for item in report["items"]:
        if item["ok"] or not item.get("fix") or item["severity"] == "info" and item["key"] not in ("captions", "beats", "loudness"):
            continue
        if item["key"] in done:
            continue
        done.add(item["key"])
        steps += item["fix"]
    return steps
