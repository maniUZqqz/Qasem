"""Edit RECIPES: the deterministic layer that gives the director a professional floor **without any AI**.

A recipe turns a *brief* (what the owner wants), the *assets* and the *analysis* into a plan — a list of catalogue tool
calls (`tools.TOOLS`), so the result is an ordinary editable project. Six recipes: product showcase, unboxing, before/after,
sale, testimonial, photo slideshow. Each can come in three *variants* (different pace, caption look, transitions) so the
owner can pick; the variant knobs are plain data (`VARIANTS`).

Craft rules baked in (they are what a pro editor does by habit):
* the strongest moment opens the video (a hook in the first 2–3 s) and a title sits on it;
* cuts land on the music beats when a track with beats is there; otherwise on a steady rhythm for the platform;
* silences go, words are never cut in half (`analyze.snap_to_speech`), captions stay out of the platform's UI bands;
* speech sits clearly above music (ducking + auto-mix), the final mix is normalised for social platforms;
* the video ends on a call-to-action card.
"""
from __future__ import annotations

from . import analyze
from .brief import PLATFORMS, RECIPES

#: key → knobs. `pace` overrides the brief's only when the brief did not ask for one explicitly.
VARIANTS: dict[str, dict] = {
    "a": {"title": "تند و ضرب‌دار", "pace": "fast", "captions": "pop", "transition": "", "zoom": "punch", "beats": True, "title_template": "title_big"},
    "b": {"title": "آرام و حرفه‌ای", "pace": "slow", "captions": "clean", "transition": "crossfade", "zoom": "push", "beats": False, "title_template": "lower_bar"},
    "c": {"title": "پرتأکید و جذاب", "pace": "normal", "captions": "karaoke", "transition": "slideleft", "zoom": "push", "beats": True, "title_template": "sticker"},
}
BODY_TAIL = 2.5          # the end card


def step(tool: str, params: dict | None = None, why: str = "", sid: str | None = None) -> dict:
    out = {"tool": tool, "params": dict(params or {}), "why": why}
    if sid:
        out["id"] = sid
    return out


def variant_keys(brief: dict) -> list[str]:
    return ["a", "b", "c"]


def _visual_refs(assets: list[dict]) -> list[str]:
    return [a["ref"] for a in assets if a.get("kind") in ("video", "image")]


def build_plan(brief: dict, assets: list[dict], an: dict, *, variant: str = "a", music_ref: str = "") -> list[dict]:
    """The plan of one variant. `music_ref` = a track to use (an audio asset the owner picked, or one found in the library);
    empty = no music step (the plan then says so instead of failing)."""
    v = VARIANTS.get(variant, VARIANTS["a"])
    recipe = brief["recipe"]
    fn = {"product_showcase": _showcase, "unboxing": _unboxing, "before_after": _before_after, "sale": _sale,
          "testimonial": _testimonial, "slideshow": _slideshow, "polish": _polish}[recipe]
    pace = brief["pace"] if brief.get("pace_explicit") else v["pace"] if recipe in ("product_showcase", "sale") else brief["pace"]
    ctx = {"brief": brief, "assets": assets, "an": an, "v": v, "pace": pace, "music": music_ref, "plat": PLATFORMS[brief["platform"]]}
    steps = [step("set_format", {"preset": ctx["plat"]["preset"]}, f"قاب برای {ctx['plat']['title']}")]
    steps += fn(ctx)
    return steps


# ----------------------------------------------------------------------------- shared blocks


def _body_target(ctx: dict) -> float:
    return max(5.0, float(ctx["brief"]["duration"]) - BODY_TAIL)


def _clip_steps(segs: list[dict], ctx: dict, *, why: str = "") -> list[dict]:
    out = []
    for i, s in enumerate(segs):
        params = {"ref": s["ref"], "track": "main", "at": "end", "id": f"n{i + 1}"}
        if "duration" in s:
            params["duration"] = s["duration"]
        else:
            params["start"], params["end"] = s["start"], s["end"]
        out.append(step("add_clip", params, why if i == 0 else "", f"add{i + 1}"))
    return out


def _quiet_ambient(ctx: dict, segs: list[dict]) -> list[dict]:
    """Product footage with its own noise but no speech: turn its sound down so the music is the sound of the video."""
    if not ctx["music"]:
        return []
    out = []
    for i, s in enumerate(segs):
        row = ctx["an"]["by_ref"].get(s["ref"], {})
        if row.get("kind") == "video" and row.get("has_audio") and sum(e - b for b, e in row.get("spans", [])) < 2.0:
            out.append(step("clip_volume", {"clip": f"n{i + 1}", "db": -30}, "صدای محیطِ فیلم کم شد تا موسیقی دیده شود" if not out else ""))
    return out


def _motion(ctx: dict, n: int, *, images: bool = False) -> list[dict]:
    v = ctx["v"]
    out = []
    if v["zoom"] == "punch" and n >= 3:
        out.append(step("punch_in", {"every": 2, "scale": 1.1}, "جامپ‌کاتِ کوچک برای انرژی"))
    elif v["zoom"] == "push" and n >= 1:
        out.append(step("zoom", {"clip": "main:odd", "from_scale": 1.0, "to_scale": 1.12}, "زومِ آرامِ حرکتی (نزدیک‌شدن)"))
        if n >= 2:
            out.append(step("zoom", {"clip": "main:even", "from_scale": 1.12, "to_scale": 1.0}, "زومِ آرامِ حرکتی (دورشدن)"))
    return out


def _transitions(ctx: dict) -> list[dict]:
    kind = ctx["v"]["transition"]
    return [step("transition", {"clip": "all", "kind": kind, "duration": 0.35}, "گذارِ نرم میانِ نماها")] if kind else []


def _look(ctx: dict) -> list[dict]:
    look = ctx["brief"].get("look")
    return [step("color_look", {"clip": "all", "look": look, "amount": 55}, "حال‌وهوای رنگیِ یکدست")] if look else []


def _hook(ctx: dict, *, text: str | None = None, template: str | None = None, at: float = 0.25, dur: float = 2.4) -> list[dict]:
    b = ctx["brief"]
    t = text or b["title"]
    if not t:
        return []
    params = {"text": t, "at": at, "duration": dur, "template": template or ctx["v"]["title_template"]}
    if b.get("subtitle"):
        params["text2"] = b["subtitle"]
    return [step("add_title", params, "تیتر روی ثانیه‌های اول (قلاب)")]


def _speech_block(ctx: dict, *, silence: bool = True) -> list[dict]:
    an, b = ctx["an"], ctx["brief"]
    out = []
    if not an["has_speech"]:
        return out
    if silence:
        out.append(step("remove_silence", {"clip": "all", "min_silence": 0.55, "keep": 0.12}, "مکث‌های بلند حذف شد"))
        if an.get("has_words"):
            out.append(step("remove_fillers", {"clip": "all"}, "صداهای «اِم و اوم» حذف شد"))
    if b.get("captions") is not False:
        out.append(step("add_captions", {"clip": "all", "style": ctx["v"]["captions"]}, "زیرنویس با کلمهٔ هایلایت"))
    out.append(step("clean_voice", {"clip": "all", "level": "light"}, "نویزِ صدا گرفته شد"))
    return out


def _end_and_mix(ctx: dict, *, beats_ref: str = "") -> list[dict]:
    b = ctx["brief"]
    out = [step("end_card", {"text": b["cta"], "text2": f"{b['discount']}٪ تخفیف" if b.get("discount") else "", "duration": BODY_TAIL}, "پایان با دعوت به خرید")]
    if ctx["music"] and b.get("music") is not False:
        out.append(step("add_music", {"ref": ctx["music"], "volume_db": -17 if ctx["an"]["has_speech"] else -12, "duck": True, "fade_out": 2}, "موسیقیِ پس‌زمینه زیرِ گفتار کم می‌شود"))
    out.append(step("auto_mix", {}, "بلندیِ گفتار و موسیقی متعادل شد"))
    out.append(step("set_loudness", {"on": True, "target": -14, "tp": -1}, "بلندیِ نهایی برای اینستاگرام/تیک‌تاک"))
    return out


def _beat_cut(ctx: dict) -> list[dict]:
    row = ctx["an"]["by_ref"].get(ctx["music"]) if ctx["music"] else None
    if ctx["v"]["beats"] and row and len(row.get("beats", [])) >= 8 and ctx["brief"].get("music") is not False:
        every = 2 if ctx["pace"] == "fast" else 4
        return [step("cut_to_beats", {"music": ctx["music"], "every": every}, "برش‌ها روی ضربِ موسیقی نشست")]
    return []


# ----------------------------------------------------------------------------- recipes


def _showcase(ctx: dict) -> list[dict]:
    an, b, plat = ctx["an"], ctx["brief"], ctx["plat"]
    refs = _visual_refs(ctx["assets"])
    segs = analyze.pick_segments(an, refs, _body_target(ctx), plat["shot"], ctx["pace"])
    steps = _clip_steps(segs, ctx, why="قوی‌ترین لحظه اول آمد و بقیه نماها پشتِ سرِ هم چیده شد")
    steps += _quiet_ambient(ctx, segs)
    steps += _beat_cut(ctx)
    steps += _motion(ctx, len(segs))
    steps += _transitions(ctx)
    steps += _look(ctx)
    steps += _speech_block(ctx, silence=False)
    steps += _hook(ctx)
    steps += _end_and_mix(ctx)
    return steps


def _unboxing(ctx: dict) -> list[dict]:
    an, plat = ctx["an"], ctx["plat"]
    refs = _visual_refs(ctx["assets"])
    segs = analyze.pick_segments(an, refs, max(_body_target(ctx), 12.0), plat["shot"], "normal", chronological=True)
    steps = _clip_steps(segs, ctx, why="ترتیبِ فیلمِ شما حفظ شد")
    steps += _speech_block(ctx, silence=True)
    steps += _motion({**ctx, "v": {**ctx["v"], "zoom": "punch"}}, len(segs))
    steps += _transitions(ctx)
    steps += _look(ctx)
    steps += _hook(ctx)
    steps += _end_and_mix(ctx)
    return steps


def _before_after(ctx: dict) -> list[dict]:
    an = ctx["an"]
    refs = _visual_refs(ctx["assets"])[:2]
    if len(refs) == 1:
        # one video: first half is «قبل», second half «بعد»
        row = an["by_ref"][refs[0]]
        dur = row["duration"] or 6.0
        half = min(4.0, dur / 2)
        segs = [{"ref": refs[0], "start": 0.0, "end": round(half, 2)}, {"ref": refs[0], "start": round(max(half, dur - half), 2), "end": round(dur, 2)}]
        if row["kind"] == "image":
            segs = [{"ref": refs[0], "duration": 3.0}, {"ref": refs[0], "duration": 3.0}]
    else:
        segs = []
        for ref in refs:
            row = an["by_ref"][ref]
            if row["kind"] == "image":
                segs.append({"ref": ref, "duration": 3.2})
            else:
                w = analyze.best_windows(row["moments"], 3.6, 1, total=row["duration"] or 3.6, spans=row["spans"]) if row["moments"] else [{"s": 0.0, "e": round(min(3.6, row["duration"] or 3.6), 2)}]
                segs.append({"ref": ref, "start": w[0]["s"], "end": w[0]["e"]})
    steps = _clip_steps(segs, ctx, why="دو نما: قبل و بعد")
    steps.append(step("transition", {"clip": "n2", "kind": "wipeleft", "duration": 0.6}, "پاک‌کردنِ نرم از «قبل» به «بعد»"))
    steps.append(step("add_title", {"text": "قبل", "at": 0.2, "duration": 2.4, "template": "sticker", "position": "top"}, "برچسبِ «قبل»"))
    first_len = (segs[0].get("duration") or (segs[0]["end"] - segs[0]["start"]))
    steps.append(step("add_title", {"text": "بعد", "at": round(first_len + 0.3, 2), "duration": 2.4, "template": "sticker", "position": "top"}, "برچسبِ «بعد»"))
    steps += _look(ctx)
    steps += _hook(ctx, text=None, template="lower_bar", at=0.2, dur=2.2) if ctx["brief"].get("title") not in ("قبل و بعد", "") else []
    steps += _end_and_mix(ctx)
    return steps


def _sale(ctx: dict) -> list[dict]:
    an, b, plat = ctx["an"], ctx["brief"], ctx["plat"]
    refs = _visual_refs(ctx["assets"])
    segs = analyze.pick_segments(an, refs, _body_target(ctx), plat["shot"], "fast")
    steps = _clip_steps(segs, ctx, why="برش‌های تند برای حس فروش")
    steps += _quiet_ambient(ctx, segs)
    steps += _beat_cut(ctx)
    steps += _motion({**ctx, "v": {**ctx["v"], "zoom": "punch"}}, len(segs))
    steps += _look({**ctx, "brief": {**b, "look": b.get("look") or "vivid"}})
    steps += _speech_block(ctx, silence=False)
    if b.get("discount"):
        steps.append(step("sticker", {"key": "sale", "at": 0.3, "duration": 3.2, "x": 0.6, "y": 0.14, "width": 0.3}, "برچسبِ «تخفیف» در بالاترین نقطهٔ امن"))
        steps.append(step("add_title", {"text": f"{b['discount']}٪ تخفیف", "at": 0.4, "duration": 3.0, "template": "title_big"}, "درصدِ تخفیف درشت و واضح"))
    else:
        steps.append(step("sticker", {"key": "sale", "at": 0.3, "duration": 3.2, "x": 0.6, "y": 0.14, "width": 0.3}, "برچسبِ «تخفیف»"))
        steps += _hook(ctx, template="sticker")
    steps += _end_and_mix(ctx)
    return steps


def _testimonial(ctx: dict) -> list[dict]:
    an, b = ctx["an"], ctx["brief"]
    refs = [r for r in _visual_refs(ctx["assets"]) if an["by_ref"][r]["kind"] == "video"]
    if not refs:
        refs = _visual_refs(ctx["assets"])
    steps = []
    for i, ref in enumerate(refs[:3]):
        row = an["by_ref"][ref]
        end = min(row["duration"] or 30, 60.0)
        steps.append(step("add_clip", {"ref": ref, "track": "main", "at": "end", "start": 0, "end": round(end, 2), "id": f"n{i + 1}"}, "حرفِ مشتری" if i == 0 else ""))
    steps += _speech_block({**ctx, "v": {**ctx["v"], "captions": "pop" if ctx["v"]["captions"] == "karaoke" else ctx["v"]["captions"]}}, silence=True)
    steps.append(step("punch_in", {"every": 2, "scale": 1.1}, "زومِ کوچک روی هر برشِ دوم تا بریدن‌ها دیده نشود"))
    steps += _look(ctx)
    steps.append(step("add_title", {"text": b["title"], "text2": b.get("subtitle") or "", "at": 0.3, "duration": 3.0, "template": "lower_box"}, "نام/عنوانِ گوینده"))
    steps += _end_and_mix(ctx)
    return steps


def _polish(ctx: dict) -> list[dict]:
    """A talking video made professional WITHOUT re-cutting its story: the whole thing stays, in the owner's order.

    Order matters and each step is a thing a good editor does:  1. the whole footage on the timeline;  2. dead air and doubtful pauses
    (the doubtful ones are asked, never silently cut);  3. hesitation sounds (needs speech recognition);  4. the picture:  light and colour
    per shot, then a window that follows the face with room above the head;  5. the voice cleaned;  6. captions with the spoken word
    highlighted, out of the app's buttons;  7. music chosen by the video's mood, ducked under the voice;  8. a standard loudness.
    """
    an, b, plat = ctx["an"], ctx["brief"], ctx["plat"]
    refs = [r for r in _visual_refs(ctx["assets"]) if an["by_ref"][r]["kind"] == "video"][:1] or _visual_refs(ctx["assets"])[:1]
    steps = []
    for i, ref in enumerate(refs):
        row = an["by_ref"][ref]
        end = round(min(row["duration"] or 600.0, 600.0), 2)
        steps.append(step("add_clip", {"ref": ref, "track": "main", "at": "end", "start": 0, "end": end, "id": f"n{i + 1}"}, "همهٔ ویدیو به ترتیبِ خودتان" if i == 0 else ""))
    boxed = any((an["by_ref"].get(ref) or {}).get("box", {}).get("found") for ref in refs)
    if boxed:                                                   # a phone screen / a clip inside black bars: show the picture itself
        steps.append(step("crop_content", {"clip": "all"}, "نوارهای سیاهِ دورِ تصویر بریده شد؛ خودِ تصویر قاب را پر می‌کند"))
    steps.append(step("split_shots", {"clip": "main"}, "جاهایی که نما عوض می‌شود جدا شد تا نور و قاب برای هر نما درست تصمیم گرفته شود"))
    if an["has_speech"]:
        steps.append(step("smart_cuts", {"clip": "all"}, "سکوتِ بی‌دلیل کوتاه شد؛ مکثِ عمدی می‌ماند و مکثِ مبهم از شما پرسیده می‌شود"))
        if an.get("has_words") or an.get("asr_waiting"):        # the words are not here yet (server off): the steps are queued and filled in by themselves
            steps.append(step("remove_retakes", {"clip": "all"}, "جمله‌ای که گوینده دوباره گفته فقط یک بار می‌ماند (نسخهٔ آخر)"))
            steps.append(step("remove_fillers", {"clip": "all"}, "صداهای «اِم و اوم» حذف شد"))
    if b.get("background") in ("blur", "color"):
        steps.append(step("background", {"mode": b["background"], "clip": "main"}, "سوژه با پردازشِ گرافیکی جدا شد و پس‌زمینه " + ("محو شد" if b["background"] == "blur" else "ساده شد")))
    elif b.get("background") == "image":
        # the picture: the panel's choice, else an IMAGE among the picked media (a video edit with one photo picked = «این عکس پشتِ من باشد»)
        pic = str(b.get("background_ref") or "") or next((a["ref"] for a in ctx["assets"] if a.get("kind") == "image"), "")
        if pic:
            steps.append(step("background", {"mode": "image", "ref": pic, "clip": "main"}, "سوژه با پردازشِ گرافیکی جدا شد و پس‌زمینه با عکسِ انتخاب‌شده عوض شد"))
        else:
            b.setdefault("notes", []).append("برای عوض کردنِ پس‌زمینه با عکس، عکسی انتخاب نشد؛ پس‌زمینه همان ماند.")
    steps.append(step("auto_look", {"clip": "all"}, "نور و رنگ هر نما از روی اندازه‌گیری درست شد"))
    if plat["preset"] != "wide" and not boxed:
        steps.append(step("reframe", {"clip": "all", "aspect": "9:16" if plat["preset"] == "reel" else "4:5" if plat["preset"] == "feed" else "1:1", "follow": "auto",
                                      "compose": True}, "قاب دنبالِ چهره، چهره روی خطِ یک‌سوم و با فضای سر"))
    if an["has_speech"]:
        steps.append(step("clean_voice", {"clip": "all", "level": "light"}, "نویزِ صدا گرفته شد"))
        if b.get("captions") is not False:
            steps.append(step("add_captions", {"clip": "all", "style": "karaoke" if ctx["v"]["captions"] == "karaoke" else "pop"}, "زیرنویس با کلمهٔ هایلایت، بیرون از دکمه‌های شبکه"))
    if b.get("title"):
        steps.append(step("add_title", {"text": b["title"], "at": 0.3, "duration": 2.6, "template": ctx["v"]["title_template"]}, "تیتر روی ثانیه‌های اول"))
    if b.get("music") is not False:
        steps.append(step("pick_music", {"mood": "auto", "volume_db": -18, "duck": True}, "موسیقی از روی حال‌وهوای ویدیو انتخاب شد و زیرِ گفتار کم می‌شود"))
    steps.append(step("auto_mix", {}, "بلندیِ گفتار و موسیقی متعادل شد"))
    steps.append(step("set_loudness", {"on": True, "target": -14, "tp": -1}, "بلندیِ نهایی برای شبکه‌های اجتماعی"))
    return steps


def _slideshow(ctx: dict) -> list[dict]:
    an, plat = ctx["an"], ctx["plat"]
    refs = [r for r in _visual_refs(ctx["assets"]) if an["by_ref"][r]["kind"] == "image"] or _visual_refs(ctx["assets"])
    per = {"fast": 1.6, "normal": 2.4, "slow": 3.2}[ctx["pace"]]
    row = an["by_ref"].get(ctx["music"]) if ctx["music"] else None
    bpm = (row or {}).get("bpm")
    if bpm and 60 <= float(bpm) <= 190:
        beat = 60.0 / float(bpm)
        per = max(1.4, round(beat * max(1, round(per / beat)), 2))
    n = max(len(refs), int(round(_body_target(ctx) / per)))
    segs = []
    for i in range(min(n, 30)):
        ref = refs[i % len(refs)]
        row_i = an["by_ref"][ref]
        if row_i["kind"] == "image":
            segs.append({"ref": ref, "duration": round(per, 2)})
        else:
            segs.append({"ref": ref, "start": 0.0, "end": round(min(per, row_i["duration"] or per), 2)})
    ctx2 = {**ctx, "v": {**ctx["v"], "zoom": "push", "transition": ctx["v"]["transition"] or "crossfade"}}
    steps = _clip_steps(segs, ctx2, why="هر عکس با زمانِ ثابت و روی ضرب")
    steps += _motion(ctx2, len(segs), images=True)
    steps += _transitions(ctx2)
    steps += _look(ctx)
    steps += _hook(ctx)
    steps += _end_and_mix(ctx)
    return steps
