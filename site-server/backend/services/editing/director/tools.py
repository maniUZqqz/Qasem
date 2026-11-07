"""The TOOL CATALOGUE of the director — the timeline operations the manual editor has, as JSON-callable tools.

Structure (add/trim/split/remove/move/reorder/speed/fit/beat-cut/transition) · text (titles, captions, end card) · visual
(look, crop, reframe, zoom, stickers, shapes, logo) · audio (music, ducking, loudness, clean voice, silence removal,
voice-over, mix). Each tool is `ToolSpec(name, Persian title, params, English `does`, Persian describe, fn)`; `fn(st, p)`
edits `st.project` in place and returns a Persian result sentence (or raises `StepError`).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from .. import captions, color, reframe as reframe_mod, titles
from .. import timeline as tl
from . import projectops as ops
from .spec import Ctx, Param, StepError, ToolSpec

TOOLS: dict[str, ToolSpec] = {}

PRESET_TITLES = {"reel": "ریلز / استوری ۹:۱۶", "feed": "پستِ عمودی ۴:۵", "square": "مربع ۱:۱", "wide": "افقی ۱۶:۹"}
RAMPS = {
    "montage": [{"p": 0, "v": 1}, {"p": 0.35, "v": 3.5}, {"p": 0.65, "v": 0.4}, {"p": 1, "v": 1}],
    "hero": [{"p": 0, "v": 1.6}, {"p": 0.4, "v": 0.3}, {"p": 0.7, "v": 0.3}, {"p": 1, "v": 1.8}],
    "flash_in": [{"p": 0, "v": 4}, {"p": 0.3, "v": 1}, {"p": 1, "v": 1}],
    "flash_out": [{"p": 0, "v": 1}, {"p": 0.7, "v": 1}, {"p": 1, "v": 4}],
    "bullet": [{"p": 0, "v": 0.5}, {"p": 0.5, "v": 3}, {"p": 1, "v": 0.5}],
}
#: Persian caption looks: size is a % of the frame height; `y` is overridden by the platform's safe zone.
CAPTION_STYLES: dict[str, dict] = {
    "pop": {"title": "درشت و پرانرژی", "style": {"font": "vazir_black", "bold": False, "size": 7.2, "color": "#ffffff", "stroke_color": "#000000",
                                              "stroke": 14.0, "box": False, "hl_color": "#ffd400", "hl_mode": "scale", "shadow": 10.0,
                                              "anim_in": "pop", "anim_dur": 0.18}},
    "box": {"title": "کادرِ تیره", "style": {"font": "vazir", "bold": True, "size": 5.6, "color": "#ffffff", "stroke": 0.0, "box": True,
                                            "box_color": "#000000", "box_opacity": 0.62, "box_pad": 22.0, "hl_color": "#ffd400", "hl_mode": "color"}},
    "karaoke": {"title": "کارائوکه (هایلایت)", "style": {"font": "vazir_black", "bold": False, "size": 6.6, "color": "#ffffff", "stroke_color": "#000000",
                                                       "stroke": 12.0, "box": False, "hl_color": "#111111", "hl_mode": "box", "shadow": 8.0}},
    "clean": {"title": "ساده و تمیز", "style": {"font": "vazir", "bold": True, "size": 5.2, "color": "#ffffff", "stroke": 6.0, "stroke_color": "#000000",
                                              "box": False, "shadow": 14.0, "hl_color": "#ffd400", "hl_mode": "color"}},
}


@dataclass
class State:
    """Everything a tool may touch: the project, the alias table (`id` of an earlier step → clip id) and the world."""

    project: dict
    ctx: Ctx = field(default_factory=Ctx)
    aliases: dict = field(default_factory=dict)
    safe: dict = field(default_factory=lambda: {"top": 0.05, "bottom": 0.05, "left": 0.05, "right": 0.05})

    @property
    def fmt(self) -> dict:
        return self.project["format"]

    @property
    def length(self) -> float:
        return ops.project_length(self.project)


def tool(name: str, title: str, group: str, does: str, params: tuple, describe):
    def deco(fn):
        TOOLS[name] = ToolSpec(name=name, title=title, group=group, params=params, does=does, describe=describe, fn=fn)
        return fn
    return deco


P = Param
fa_digits = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")


def fa(x) -> str:
    if isinstance(x, float):
        x = round(x, 1)
        x = int(x) if x == int(x) else x
    return str(x).translate(fa_digits).replace(".", "٫")


def _clips(st: State, token: str, *, media_only: bool = False, with_sound: bool = False, main_only: bool = False) -> list[dict]:
    """Resolve a clip token: an id, an alias of an earlier step, `all`, `main`, `first`, `last`, `last_added`."""
    tok = (token or "").strip()
    if tok in st.aliases:
        tok = st.aliases[tok]
    found = ops.find(st.project, tok)
    if found:
        got = [found[1]]
    else:
        main = ops.main_track(st.project)["clips"]
        ordered = sorted(main, key=lambda c: float(c["at"]))
        if tok.startswith("main:"):
            sel = tok[5:]
            if sel == "odd":
                got = ordered[0::2]
            elif sel == "even":
                got = ordered[1::2]
            elif sel.isdigit() and 1 <= int(sel) <= len(ordered):
                got = [ordered[int(sel) - 1]]
            else:
                got = []
        elif tok in ("main", "first", "last"):
            got = sorted(main, key=lambda c: float(c["at"]))
            got = got[:1] if tok == "first" else got[-1:] if tok == "last" else got
        elif tok in ("all", ""):
            got = [c for t in st.project["tracks"] for c in t["clips"]] if not main_only else list(main)
        else:
            raise StepError(f"قطعه‌ای با نشانیِ «{token}» پیدا نشد.")
    if media_only:
        got = [c for c in got if c.get("type") == "media"]
    if with_sound:
        tracks = {c["id"]: t for t in st.project["tracks"] for c in t["clips"]}
        got = [c for c in got if c.get("type") == "media" and ((tracks[c["id"]]["kind"] == "audio") or (c.get("has_audio") and c.get("audio_on", True) and c.get("kind") == "video"))]
    if not got:
        raise StepError("قطعه‌ای برای این کار پیدا نشد.")
    return got


def _track_of(st: State, c: dict) -> dict:
    return next(t for t in st.project["tracks"] if any(x["id"] == c["id"] for x in t["clips"]))


def _db_to_lin(db: float) -> float:
    return round(max(0.0, min(3.0, 10 ** (db / 20.0))), 4)


def _alias(st: State, p: dict, clip: dict) -> None:
    """The step's `id` names the clip for later steps. Taking it as the clip's real id (when free) keeps the name valid
    after the plan: the owner and a later one-click tool can still say «n3»."""
    a = p.get("id")
    if not a:
        return
    if a not in ops.ids_of(st.project):
        clip["id"] = a
    st.aliases[a] = clip["id"]


def _at(st: State, track: dict, raw) -> float:
    if raw in (None, "", "end"):
        return ops.end_of(track)
    try:
        return max(0.0, float(raw))
    except (TypeError, ValueError):
        raise StepError("زمانِ قرارگیری درست نیست.") from None


# =================================================================== structure


@tool("set_format", "قابِ پروژه", "structure", "Set the frame: reel 9:16, feed 4:5, square 1:1 or wide 16:9.",
      (P("preset", "قاب", "choice", "reel", choices=("reel", "feed", "square", "wide"), doc="reel=9:16 stories/reels"),
       P("fps", "فریم در ثانیه", "int", 30, 24, 60)),
      lambda p: f"قاب را روی «{PRESET_TITLES[p['preset']]}» بگذار")
def _set_format(st: State, p: dict):
    ops.set_format(st.project, p["preset"], p.get("fps"))
    return f"قابِ پروژه شد «{PRESET_TITLES[p['preset']]}»."


@tool("add_clip", "افزودنِ قطعه", "structure", "Put a video, photo or sound from the media bin on the timeline.",
      (P("ref", "منبع", "ref", required=True, doc="a ref from the asset list, e.g. video:12, pimg:3, audio:5"),
       P("track", "ترک", "choice", "main", choices=("main", "overlay", "speech", "music", "sfx")),
       P("at", "زمان", "text", "end", doc='timeline seconds, or "end"'),
       P("start", "از ثانیهٔ منبع", "num", 0, 0, 86400, unit="ث"),
       P("end", "تا ثانیهٔ منبع", "num", None, 0, 86400, unit="ث"),
       P("duration", "مدت (عکس)", "num", 3, 0.3, 60, unit="ث"),
       P("fit", "جا دادن", "choice", "cover", choices=("cover", "contain", "stretch")),
       P("label", "نام", "text", ""), P("id", "نشانی برای مراحلِ بعد", "text", "")),
      lambda p: f"قطعهٔ «{p['ref']}» را روی تایم‌لاین بگذار")
def _add_clip(st: State, p: dict):
    item = st.ctx.describe(p["ref"])
    if not item:
        raise StepError(f"منبعِ «{p['ref']}» پیدا نشد (شاید پاک شده).")
    kind = item.get("kind") or "video"
    where = p["track"]
    if kind == "audio" and where in ("main", "overlay"):
        where = "music" if (item.get("duration") or 0) > 40 else "sfx"
    if kind != "audio" and where in ("speech", "music", "sfx"):
        raise StepError("تصویر را روی ترکِ صدا نمی‌شود گذاشت.")
    track = ops.main_track(st.project) if where == "main" else ops.overlay_track(st.project) if where == "overlay" else ops.audio_track(st.project, where)
    at = _at(st, track, p.get("at"))
    if where in ("overlay", "speech", "music", "sfx") and p.get("at") in (None, "", "end"):
        at = ops.end_of(track)
    if kind == "image":
        clip = ops.media_clip(st.project, item, at, start=0, end=p["duration"], label=p.get("label"))
    else:
        clip = ops.media_clip(st.project, item, at, start=p.get("start", 0), end=p.get("end"), label=p.get("label"))
    clip["fit"] = p.get("fit", "cover")
    if where == "main":
        ops.place(track, clip)
    elif where == "overlay":
        ops.place_free(st.project, "video", clip)
    else:
        ops.place_free(st.project, "audio", clip, role=where)
    _alias(st, p, clip)
    return f"«{clip['label']}» در ثانیهٔ {fa(clip['at'])} روی تایم‌لاین نشست ({fa(round(ops.clip_length(clip), 1))} ثانیه)."


@tool("trim_clip", "کوتاه‌کردنِ قطعه", "structure", "Change a clip's source in/out (seconds of the source file).",
      (P("clip", "قطعه", "clip", required=True), P("start", "از ثانیهٔ منبع", "num", None, 0, 86400), P("end", "تا ثانیهٔ منبع", "num", None, 0, 86400)),
      lambda p: "ابتدا و انتهای قطعه را تنظیم کن")
def _trim(st: State, p: dict):
    n = 0
    for c in _clips(st, p["clip"], media_only=True):
        if ops.trim(st.project, c["id"], start=p.get("start"), end=p.get("end")):
            n += 1
    return f"{fa(n)} قطعه کوتاه شد."


@tool("split_clip", "برشِ قطعه", "structure", "Cut a clip in two at a timeline time (linked sound is cut too).",
      (P("clip", "قطعه", "clip", required=True), P("at", "زمان", "num", required=True, minimum=0, maximum=86400, unit="ث")),
      lambda p: f"قطعه را در ثانیهٔ {fa(p['at'])} ببر")
def _split(st: State, p: dict):
    ids = ops.linked_ids(st.project, [c["id"] for c in _clips(st, p["clip"])])
    made = ops.split_all(st.project, ids, p["at"])
    if not made:
        raise StepError("آن لحظه داخلِ قطعه نیست.")
    return "قطعه بریده شد."


@tool("remove_range", "برداشتنِ یک بازه", "structure", "Remove a time range from every track and close the gap (a cut).",
      (P("from", "از ثانیه", "num", required=True, minimum=0, maximum=86400, unit="ث"), P("to", "تا ثانیه", "num", required=True, minimum=0, maximum=86400, unit="ث"),
       P("ripple", "بستنِ فاصله", "bool", True)),
      lambda p: f"بازهٔ {fa(p['from'])} تا {fa(p['to'])} ثانیه را بردار")
def _remove_range(st: State, p: dict):
    n = ops.remove_range(st.project, p["from"], p["to"], p.get("ripple", True))
    return f"{fa(n)} تکه برداشته شد."


@tool("delete_clip", "حذفِ قطعه", "structure", "Delete clips (optionally closing the gap on their tracks).",
      (P("clip", "قطعه", "clip", required=True), P("ripple", "بستنِ فاصله", "bool", False)),
      lambda p: "قطعه را حذف کن")
def _delete(st: State, p: dict):
    n = ops.delete_clips(st.project, [c["id"] for c in _clips(st, p["clip"])], p.get("ripple", False))
    return f"{fa(n)} قطعه حذف شد."


@tool("move_clip", "جابه‌جاییِ قطعه", "structure", "Move a clip to a timeline time.",
      (P("clip", "قطعه", "clip", required=True), P("at", "زمان", "num", required=True, minimum=0, maximum=86400, unit="ث")),
      lambda p: f"قطعه را به ثانیهٔ {fa(p['at'])} ببر")
def _move(st: State, p: dict):
    c = _clips(st, p["clip"])[0]
    track = _track_of(st, c)
    c["at"] = round(ops.free_spot(track, p["at"], ops.clip_length(c), (c["id"],)), 3)
    ops.sort_track(track)
    return f"قطعه در ثانیهٔ {fa(c['at'])} قرار گرفت."


@tool("reorder_clips", "ترتیبِ قطعه‌ها", "structure", "Re-sequence listed clips of the main track back-to-back in the given order.",
      (P("order", "ترتیب", "list", required=True, doc="list of clip ids or aliases"),),
      lambda p: "ترتیبِ نماها را عوض کن")
def _reorder(st: State, p: dict):
    picked = []
    for tok in p["order"]:
        picked.append(_clips(st, str(tok), media_only=True)[0])
    if not picked:
        raise StepError("فهرستِ قطعه‌ها خالی است.")
    track = _track_of(st, picked[0])
    cur = min(float(c["at"]) for c in picked)
    for c in picked:
        c["at"] = round(cur, 3)
        cur = ops.clip_end(c)
    ops.sort_track(track)
    return f"{fa(len(picked))} قطعه پشتِ هم چیده شد."


@tool("set_speed", "سرعتِ قطعه", "structure", "Change playback speed of a clip (0.25-4x).",
      (P("clip", "قطعه", "clip", required=True), P("speed", "سرعت", "num", required=True, minimum=0.25, maximum=4, unit="×")),
      lambda p: f"سرعت را {fa(p['speed'])} برابر کن")
def _speed(st: State, p: dict):
    for c in _clips(st, p["clip"], media_only=True):
        if c.get("kind") == "image":
            continue
        ops.set_speed(c, p["speed"])
    _reflow_after_speed(st)
    return f"سرعت {fa(p['speed'])} برابر شد."


def _reflow_after_speed(st: State) -> None:
    """A slower clip got longer: push the next clips of the main track so nothing overlaps (what the editor's auto-ripple does)."""
    track = ops.main_track(st.project)
    ops.sort_track(track)
    cur = None
    for c in track["clips"]:
        if cur is not None and float(c["at"]) < cur - 0.001:
            c["at"] = round(cur, 3)
        cur = ops.clip_end(c)


@tool("speed_ramp", "منحنیِ سرعت", "structure", "Apply a speed-ramp preset (fast/slow/fast) to a clip.",
      (P("clip", "قطعه", "clip", required=True), P("preset", "الگو", "choice", "montage", choices=tuple(RAMPS))),
      lambda p: f"منحنیِ سرعتِ «{p['preset']}» را بگذار")
def _ramp(st: State, p: dict):
    for c in _clips(st, p["clip"], media_only=True):
        if c.get("kind") == "video":
            c["ramp"] = [dict(k) for k in RAMPS[p["preset"]]]
            c["speed"] = 1
    _reflow_after_speed(st)
    return "منحنیِ سرعت گذاشته شد."


@tool("close_gaps", "بستنِ فاصله‌ها", "structure", "Butt the clips of a track against each other (no black gaps).",
      (P("track", "ترک", "choice", "main", choices=("main", "overlay")),),
      lambda p: "فاصله‌های خالی را ببند")
def _close(st: State, p: dict):
    ops.close_gaps(ops.main_track(st.project) if p["track"] == "main" else ops.overlay_track(st.project))
    return "فاصله‌ها بسته شد."


@tool("fit_length", "جا دادن در مدتِ هدف", "structure", "Shorten the main track to a target length by trimming clip tails (or speeding up).",
      (P("seconds", "مدت", "num", required=True, minimum=3, maximum=600, unit="ث"), P("mode", "روش", "choice", "trim", choices=("trim", "speed"))),
      lambda p: f"کلِ ویدیو را در {fa(p['seconds'])} ثانیه جا بده")
def _fit(st: State, p: dict):
    track = ops.main_track(st.project)
    card = [c for c in track["clips"] if c.get("label") == "کارتِ پایانی"]
    clips = sorted([c for c in track["clips"] if c not in card], key=lambda c: float(c["at"]))
    total = sum(ops.clip_length(c) for c in clips)
    target = max(2.0, float(p["seconds"]) - sum(ops.clip_length(c) for c in card))      # the end card keeps its length
    if total <= target + 0.2 or not clips:
        return f"از قبل {fa(round(total + sum(ops.clip_length(c) for c in card), 1))} ثانیه است؛ چیزی تغییر نکرد."
    if p["mode"] == "speed":
        k = min(2.0, total / target)
        for c in clips:
            if c.get("kind") == "video":
                ops.set_speed(c, float(c.get("speed") or 1) * k)
    else:
        floor = 0.8
        for _ in range(3):
            total = sum(ops.clip_length(c) for c in clips)
            if total <= target + 0.05:
                break
            ratio = target / total
            for c in clips:
                length = ops.clip_length(c)
                want = max(floor, length * ratio)
                if want < length - 0.02:
                    if c.get("kind") == "image":
                        c["end"] = round(float(c["start"]) + want, 3)
                    else:
                        c["end"] = round(float(c["start"]) + want * float(c.get("speed") or 1), 3)
    ops.close_gaps(track)
    return f"مدت به {fa(round(ops.end_of(track), 1))} ثانیه رسید."


@tool("cut_to_beats", "برش روی ضرب", "structure", "Re-cut the main track so every cut lands on the music beats (beat-synced edit).",
      (P("music", "موسیقی (قطعه یا منبع)", "clip", required=True), P("every", "هر چند ضرب", "int", 2, 1, 8),
       P("clips", "نماهای مبدأ", "list", None, doc="optional list of clip ids to draw footage from")),
      lambda p: f"نماها را روی هر {fa(p['every'])} ضرب ببر")
def _cut_to_beats(st: State, p: dict):
    music = p["music"]
    mc = None
    try:
        mc = _clips(st, music, media_only=True)[0]
    except StepError:
        mc = None
    if mc is not None:
        ref, off_src, at0 = mc["ref"], float(mc["start"]), float(mc["at"])
        beats_src = list(st.ctx.beats(ref).get("beats") or [])
        beats = [at0 + ops.source_to_timeline(mc, b) - at0 for b in beats_src if float(mc["start"]) <= b <= float(mc["end"])]
    else:
        beats = list((st.ctx.beats(music) or {}).get("beats") or [])
    if len(beats) < 4:
        raise StepError("ضرب‌های موسیقی پیدا نشد یا کم بود؛ برش روی ضرب انجام نشد.")
    track = ops.main_track(st.project)
    pool_ids = [str(x) for x in (p.get("clips") or [])]
    pool = [c for c in sorted(track["clips"], key=lambda c: float(c["at"])) if c.get("type") == "media" and (not pool_ids or c["id"] in pool_ids or c["id"] in [st.aliases.get(x) for x in pool_ids])]
    pool = [c for c in pool if not str(c.get("ref", "")).startswith(("shape", "seq:"))]
    if not pool:
        raise StepError("نمایی برای چیدن روی ضرب پیدا نشد.")
    pool_end = max(ops.clip_end(c) for c in pool)             # the picture keeps its length; only WHERE it is cut changes (the end card is not picture)
    end_t = pool_end
    cuts = [0.0] + [b for i, b in enumerate(beats) if ((i + 1) % int(p["every"]) == 0) and 0.4 < b < end_t - 0.4]
    cuts = sorted({round(c, 3) for c in cuts})
    if cuts[-1] < end_t - 0.5:
        cuts.append(round(end_t, 3))
    keep_others = [c for c in track["clips"] if c not in pool]
    cursor = {c["id"]: float(c["start"]) for c in pool}
    made: list[dict] = []
    i = 0
    for a, b in zip(cuts, cuts[1:]):
        d = b - a
        if d < 0.25:
            continue
        src = None
        for _ in range(len(pool)):
            cand = pool[i % len(pool)]
            i += 1
            spd = float(cand.get("speed") or 1)
            avail = (float(cand["end"]) - cursor[cand["id"]]) / spd
            if cand.get("kind") == "image" or avail >= d - 0.05:
                src = cand
                break
        if src is None:                                     # everything is used up: start the pool over
            cursor = {c["id"]: float(c["start"]) for c in pool}
            src = pool[0]
        spd = float(src.get("speed") or 1)
        piece = {**src, "id": ops.uid(st.project), "at": round(a, 3), "transition": None, "fade_in": 0, "fade_out": 0, "kf": {}}
        piece.pop("link", None)
        if src.get("kind") == "image":
            piece["start"], piece["end"] = 0, round(d, 3)
        else:
            s0 = cursor[src["id"]]
            piece["start"], piece["end"] = round(s0, 3), round(min(float(src["end"]), s0 + d * spd), 3)
            cursor[src["id"]] = piece["end"]
        made.append(piece)
    if not made:
        raise StepError("ضرب‌ها برای چیدنِ نماها کافی نبود.")
    new_end = max(ops.clip_end(m) for m in made)
    shift = round(new_end - pool_end, 3)
    if abs(shift) > 0.001:                                    # whatever followed the picture (the end card) follows its new end
        for c in keep_others:
            if float(c["at"]) >= pool_end - 0.05:
                c["at"] = round(max(0.0, float(c["at"]) + shift), 3)
    track["clips"] = keep_others + made
    ops.sort_track(track)
    return f"{fa(len(made))} نما روی ضرب‌های موسیقی چیده شد."


@tool("transition", "گذار", "structure", "Set the transition that brings a clip in from the previous one (or all joins of the main track).",
      (P("clip", "قطعهٔ واردشونده", "clip", "all"), P("kind", "نوع", "text", "crossfade", max_len=24), P("duration", "مدت", "num", 0.4, 0.1, 2, unit="ث")),
      lambda p: f"گذارِ «{p['kind']}» ({fa(p['duration'])} ثانیه)")
def _transition(st: State, p: dict):
    kinds = tl.transitions_all()
    kind = p["kind"] if p["kind"] in kinds else "crossfade"
    track = ops.main_track(st.project)
    targets = _clips(st, p["clip"], media_only=True, main_only=True) if p["clip"] in ("all", "") else _clips(st, p["clip"], media_only=True)
    ordered = sorted([c for c in track["clips"] if c.get("type") == "media"], key=lambda c: float(c["at"]))
    n = 0
    for i, c in enumerate(ordered):
        if i == 0 or c not in targets:
            continue
        prev = ordered[i - 1]
        if abs(float(c["at"]) - ops.clip_end(prev)) > 0.15:
            continue
        c["transition"] = {"kind": kind, "duration": p["duration"]}
        n += 1
    return f"{fa(n)} گذار گذاشته شد."


# =================================================================== text


@tool("add_title", "عنوان / متن", "text", "Add a title or text overlay with a template (Persian-ready).",
      (P("text", "متن", "text", required=True, max_len=160), P("text2", "زیرعنوان", "text", "", max_len=120),
       P("at", "زمان", "num", 0, 0, 86400, unit="ث"), P("duration", "مدت", "num", 2.5, 0.5, 20, unit="ث"),
       P("template", "قالب", "choice", "title_center", choices=tuple(titles.TEMPLATES)),
       P("position", "جا", "choice", "", choices=("", "top", "middle", "bottom")), P("size", "اندازه", "num", None, 2, 20, unit="٪"),
       P("color", "رنگ", "text", "", max_len=9), P("id", "نشانی", "text", "")),
      lambda p: f"عنوانِ «{p['text'][:30]}» را در ثانیهٔ {fa(p['at'])} بگذار")
def _title(st: State, p: dict):
    extra = {"template": p["template"], "text2": p.get("text2") or None, "size": p.get("size"),
             "position": p.get("position") or None, "color": p.get("color") if str(p.get("color", "")).startswith("#") else None}
    if not p.get("position"):
        extra["y"] = _title_y(st, p["template"])
    c = ops.text_clip(st.project, p["text"], p["at"], p["duration"], **extra)
    ops.place_free(st.project, "text", c)
    _alias(st, p, c)
    return f"عنوان در ثانیهٔ {fa(c['at'])} ({fa(p['duration'])} ثانیه) گذاشته شد."


def _title_y(st: State, template: str) -> float | None:
    """Keep lower-thirds and sticker titles clear of the platform's UI (top/bottom bands)."""
    if template.startswith("lower_"):
        return round(min(0.80, 1 - st.safe["bottom"] - 0.07), 3)
    if template in ("title_center", "title_big", "quote"):
        return 0.5
    if template == "sticker":
        return round(max(0.30, st.safe["top"] + 0.12), 3)
    return None


@tool("add_captions", "زیرنویس", "text", "Auto-caption the speech of a clip (needs speech recognition) or place given lines.",
      (P("clip", "قطعه", "clip", "all"), P("style", "سبک", "choice", "pop", choices=tuple(CAPTION_STYLES)),
       P("lines", "خط‌ها (اختیاری)", "list", None, doc="[{text,start,end}] in timeline seconds, used when speech recognition is unavailable")),
      lambda p: f"زیرنویسِ «{CAPTION_STYLES[p['style']]['title']}» را روی گفتار بگذار")
def _captions(st: State, p: dict):
    style = dict(CAPTION_STYLES[p["style"]]["style"])
    style["y"] = round(min(0.78, 1 - st.safe["bottom"] - 0.04), 3)
    track = ops.text_track(st.project, caption=True)
    made: list[dict] = []
    why = ""
    if p.get("lines"):
        for ln in p["lines"][:60]:
            try:
                text, a, b = str(ln["text"]), float(ln["start"]), float(ln["end"])
            except (KeyError, TypeError, ValueError):
                continue
            if b > a + 0.2 and text.strip():
                made.append(titles.clean({**captions.DEFAULT_STYLE, **style, "text": text, "at": a, "duration": b - a, "caption": True, "label": text[:20]}))
    else:
        targets = [c for c in _clips(st, p["clip"], media_only=True) if c.get("kind") != "image"]
        sound = [c for c in targets if c.get("has_audio") or _track_of(st, c)["kind"] == "audio"]
        for c in sound:
            if _track_of(st, c).get("role") == "music" or _track_of(st, c).get("role") == "sfx":
                continue
            try:
                words = st.ctx.words(c["ref"], float(c["start"]), float(c["end"]))
            except Exception as exc:  # noqa: BLE001 — ASR unavailable is a normal, explainable state
                why = str(exc)
                words = []
            if not words:
                continue
            k = 1.0 / max(0.25, float(c.get("speed") or 1))
            scaled = [{"w": w["w"], "s": w["s"] * k, "e": w["e"] * k} for w in words]
            groups = captions.group_words(scaled)
            made += captions.caption_clips(groups, offset=float(c["at"]), style=style)
    if not made:
        raise StepError(why or "گفتاری برای زیرنویس پیدا نشد (یا تشخیصِ گفتار در دسترس نیست — سرورِ پردازش را روشن کنید).")
    made.sort(key=lambda c: float(c["at"]))
    for raw in made:
        raw = dict(raw)
        raw.update({"id": ops.uid(st.project, "x"), "type": "text"})
        prev = track["clips"][-1] if track["clips"] else None
        if prev is not None and float(raw["at"]) < ops.clip_end(prev) - 0.001:     # two takes of the same words: never overlap on one track
            gap = float(raw["at"]) - float(prev["at"]) - 0.02
            if gap < 0.25:
                continue
            prev["duration"] = round(gap, 3)
        track["clips"].append(raw)
    ops.sort_track(track)
    return f"{fa(len(track['clips']))} خط زیرنویس گذاشته شد."


@tool("caption_style", "سبکِ زیرنویس‌ها", "text", "Re-style every caption line at once (look and vertical position, kept clear of the platform UI).",
      (P("style", "سبک", "choice", "pop", choices=tuple(CAPTION_STYLES)), P("y", "جای عمودی", "num", None, 0.3, 0.95)),
      lambda p: f"سبکِ همهٔ زیرنویس‌ها را «{CAPTION_STYLES[p['style']]['title']}» کن")
def _caption_style(st: State, p: dict):
    style = CAPTION_STYLES[p["style"]]["style"]
    y = p.get("y") or round(min(0.78, 1 - st.safe["bottom"] - 0.04), 3)
    n = 0
    for t in st.project["tracks"]:
        if t["kind"] != "text":
            continue
        for c in t["clips"]:
            if c.get("caption"):
                c.update({k: v for k, v in style.items() if k != "y"})
                c["y"] = y
                n += 1
    if not n:
        raise StepError("زیرنویسی روی تایم‌لاین نیست.")
    return f"سبکِ {fa(n)} خط زیرنویس عوض شد."


@tool("end_card", "کارتِ پایانی", "text", "Close the video with a full-frame call-to-action card.",
      (P("text", "متنِ اصلی", "text", "همین حالا سفارش بده", max_len=80), P("text2", "زیرعنوان", "text", "", max_len=100),
       P("duration", "مدت", "num", 2.5, 1.5, 6, unit="ث"), P("bg", "رنگِ زمینه", "text", "#0f172a", max_len=9), P("accent", "رنگِ تأکید", "text", "#ffd400", max_len=9)),
      lambda p: f"کارتِ پایانی با «{p['text'][:30]}» بساز")
def _end_card(st: State, p: dict):
    main = ops.main_track(st.project)
    at = round(ops.end_of(main), 3)
    d = float(p["duration"])
    shape = {"shape": "rect", "fill": p["bg"] if str(p["bg"]).startswith("#") else "#0f172a"}
    card = {"id": ops.uid(st.project), "type": "media", "ref": "shape", "label": "کارتِ پایانی", "kind": "image", "at": at, "start": 0, "end": d,
            "src": 0, "opacity": 1, "x": 0, "y": 0, "width": 1, "height": 1, "volume": 1, "speed": 1, "fit": "stretch", "fade_in": 0.25, "fade_out": 0,
            "audio_on": False, "has_audio": False, "effects": [], "transition": None, "shape": shape}
    ops.place(main, card, exact=True)
    accent = p["accent"] if str(p["accent"]).startswith("#") else "#ffd400"
    ops.place_free(st.project, "text", ops.text_clip(st.project, p["text"], at + 0.15, d - 0.3, template="title_big", color=accent, y=0.46))
    if p.get("text2"):
        ops.place_free(st.project, "text", ops.text_clip(st.project, p["text2"], at + 0.45, d - 0.6, template="plain", size=5, y=0.60, box=False, color="#ffffff"))
    return f"کارتِ پایانی ({fa(d)} ثانیه) ساخته شد."


# =================================================================== visual


@tool("color_look", "رنگ و حال‌وهوا", "visual", "Apply a colour look (cinematic, vivid, warm…) to clips.",
      (P("clip", "قطعه", "clip", "all"), P("look", "حال‌وهوا", "choice", "vivid", choices=tuple(color.LOOKS)), P("amount", "شدت", "num", 60, 0, 100, unit="٪")),
      lambda p: f"حال‌وهوای «{color.LOOKS[p['look']]['title']}» را بگذار")
def _look(st: State, p: dict):
    n = 0
    for c in _clips(st, p["clip"], media_only=True):
        if c.get("kind") in ("video", "image") and not str(c.get("ref", "")).startswith("shape"):
            col = dict(c.get("color") or {})
            col.update({"look": p["look"], "look_amount": p["amount"]})
            c["color"] = col
            n += 1
    return f"{fa(n)} قطعه رنگ گرفت."


@tool("crop", "برشِ لبه‌ها", "visual", "Crop the edges of a clip (fractions 0-0.9 of each side; the edge becomes transparent).",
      (P("clip", "قطعه", "clip", required=True), P("l", "چپ", "num", 0, 0, 0.9), P("r", "راست", "num", 0, 0, 0.9), P("t", "بالا", "num", 0, 0, 0.9),
       P("b", "پایین", "num", 0, 0, 0.9)),
      lambda p: "لبه‌های تصویر را ببر")
def _crop(st: State, p: dict):
    for c in _clips(st, p["clip"], media_only=True):
        c["crop"] = {k: p[k] for k in ("l", "r", "t", "b") if p.get(k)}
    return "برش اعمال شد."


@tool("reframe", "بازتنظیمِ قاب (۹:۱۶ خودکار)", "visual", "Reframe a clip to an aspect, following the subject (faces/motion).",
      (P("clip", "قطعه", "clip", required=True), P("aspect", "نسبت", "text", "9:16", max_len=8), P("follow", "دنبالِ سوژه", "choice", "auto", choices=("auto", "center")),
       P("zoom", "زوم", "num", 1, 1, 2)),
      lambda p: f"قاب را روی {p['aspect']} بازتنظیم کن")
def _reframe(st: State, p: dict):
    done, engines = 0, set()
    for c in _clips(st, p["clip"], media_only=True):
        if c.get("kind") == "audio" or str(c.get("ref", "")).startswith(("shape", "seq:", "sticker:")):
            continue
        item = st.ctx.describe(c["ref"]) or {}
        size = (int(item.get("width") or 0), int(item.get("height") or 0))
        path = st.ctx.path_of(c["ref"])
        asp = reframe_mod.aspect_value(p["aspect"]) if p["aspect"] else st.fmt["width"] / st.fmt["height"]
        if not all(size):
            continue
        if path and p["follow"] == "auto":
            res = reframe_mod.plan(path, float(c["start"]), float(c["end"]), asp, follow="auto", zoom=p["zoom"], speed=float(c.get("speed") or 1), size=size)
            c["reframe"] = res["reframe"]
            engines.add(res["engine"])
        else:
            c["reframe"] = reframe_mod.centred(size[0], size[1], asp, p["zoom"])
            engines.add("center")
        c["fit"] = "cover"
        done += 1
    if not done:
        raise StepError("قطعه‌ای برای بازتنظیمِ قاب پیدا نشد.")
    names = {"face": "چهره", "motion": "حرکت", "center": "وسطِ قاب"}
    return f"قاب {fa(done)} قطعه بازتنظیم شد (سوژه: {'، '.join(names.get(e, e) for e in sorted(engines))})."


@tool("zoom", "زومِ آرام", "visual", "Slow push-in or pull-out on a clip (animated scale).",
      (P("clip", "قطعه", "clip", required=True), P("from_scale", "از اندازه", "num", 1, 0.5, 3), P("to_scale", "تا اندازه", "num", 1.12, 0.5, 3),
       P("easing", "نرمی", "choice", "ease_in_out", choices=("linear", "ease_in", "ease_out", "ease_in_out"))),
      lambda p: f"زومِ آرام از {fa(p['from_scale'])} تا {fa(p['to_scale'])}")
def _zoom(st: State, p: dict):
    n = 0
    for c in _clips(st, p["clip"], media_only=True):
        if c.get("kind") == "audio":
            continue
        L = ops.clip_length(c)
        ops.set_keys(c, "scale", [ops.key(0, p["from_scale"], p["easing"]), ops.key(L, p["to_scale"], "linear")])
        n += 1
    return f"زوم روی {fa(n)} قطعه گذاشته شد."


@tool("punch_in", "زومِ پرشی (جامپ‌کات)", "visual", "Jump-cut punch-in: every n-th clip of the main track is scaled up a little (hides cuts, adds energy).",
      (P("every", "هر چندمین قطعه", "int", 2, 2, 6), P("scale", "اندازه", "num", 1.12, 1.03, 1.5)),
      lambda p: f"هر {fa(p['every'])} قطعه را کمی بزرگ کن")
def _punch(st: State, p: dict):
    ordered = [c for c in sorted(ops.main_track(st.project)["clips"], key=lambda c: float(c["at"])) if c.get("type") == "media" and c.get("kind") != "audio"
               and not str(c.get("ref", "")).startswith("shape")]
    n = 0
    for i, c in enumerate(ordered):
        if i % int(p["every"]) == int(p["every"]) - 1:
            c["scale"] = p["scale"]
            n += 1
    if not n:
        raise StepError("قطعه‌ی کافی برای زومِ پرشی نیست.")
    return f"{fa(n)} قطعه کمی بزرگ شد."


@tool("sticker", "استیکر", "visual", "Place a built-in sticker (badge or emoji) over the picture.",
      (P("key", "استیکر", "text", required=True, max_len=40), P("at", "زمان", "num", 0.5, 0, 86400, unit="ث"), P("duration", "مدت", "num", 2, 0.5, 20, unit="ث"),
       P("x", "جای افقی", "num", 0.62, 0, 0.95), P("y", "جای عمودی", "num", 0.12, 0, 0.95), P("width", "پهنا", "num", 0.26, 0.05, 0.9)),
      lambda p: f"استیکرِ «{p['key']}» را بگذار")
def _sticker(st: State, p: dict):
    ref = p["key"] if p["key"].startswith("sticker:") else f"sticker:{p['key']}"
    item = st.ctx.describe(ref)
    if not item:
        raise StepError(f"استیکرِ «{p['key']}» پیدا نشد.")
    box_h = p["width"] * st.fmt["width"] / st.fmt["height"]
    x = min(p["x"], 1 - p["width"])
    y = min(max(p["y"], st.safe["top"]), max(0.0, 1 - box_h))
    clip = ops.media_clip(st.project, item, p["at"], start=0, end=p["duration"], kind="image")
    clip.update({"x": round(x, 3), "y": round(y, 3), "width": p["width"], "height": round(min(0.95, box_h), 3), "fit": "contain", "has_audio": False})
    ops.place_free(st.project, "video", clip)
    return "استیکر گذاشته شد."


@tool("shape", "شکل", "visual", "Draw a shape (badge background, burst, bar) over the picture.",
      (P("kind", "شکل", "choice", "rounded", choices=("rect", "rounded", "ellipse", "triangle", "star", "polygon", "heart", "arrow", "burst")),
       P("fill", "رنگ", "text", "#ef4444", max_len=9), P("at", "زمان", "num", 0, 0, 86400, unit="ث"), P("duration", "مدت", "num", 2, 0.3, 30, unit="ث"),
       P("x", "جای افقی", "num", 0.3, 0, 0.95), P("y", "جای عمودی", "num", 0.4, 0, 0.95), P("width", "پهنا", "num", 0.4, 0.05, 1), P("height", "ارتفاع", "num", 0.12, 0.03, 1),
       P("id", "نشانی", "text", "")),
      lambda p: f"شکلِ «{p['kind']}» را بگذار")
def _shape(st: State, p: dict):
    w, h = p["width"], p["height"]
    clip = {"id": ops.uid(st.project), "type": "media", "ref": "shape", "label": "شکل", "kind": "image", "at": round(p["at"], 3), "start": 0, "end": p["duration"], "src": 0,
            "opacity": 1, "x": min(p["x"], 1 - w), "y": min(p["y"], 1 - h), "width": w, "height": h, "volume": 1, "speed": 1, "fit": "stretch", "fade_in": 0, "fade_out": 0,
            "audio_on": False, "has_audio": False, "effects": [], "transition": None, "shape": {"shape": p["kind"], "fill": p["fill"] if p["fill"].startswith("#") else "#ef4444"}}
    ops.place_free(st.project, "video", clip)
    _alias(st, p, clip)
    return "شکل گذاشته شد."


@tool("overlay_image", "لوگو / عکسِ روی تصویر", "visual", "Pin a logo or product photo to a corner for a while (inside the platform safe zone).",
      (P("ref", "منبع", "ref", required=True), P("corner", "گوشه", "choice", "tr", choices=("tr", "tl", "br", "bl")), P("size", "اندازه", "num", 0.2, 0.08, 0.6),
       P("at", "زمان", "num", 0, 0, 86400, unit="ث"), P("duration", "مدت", "text", "all", doc='seconds or "all" (to the end)')),
      lambda p: "لوگو را در گوشه بگذار")
def _overlay_image(st: State, p: dict):
    item = st.ctx.describe(p["ref"])
    if not item or item.get("kind") != "image":
        raise StepError("عکسِ لوگو پیدا نشد.")
    total = max(1.0, st.length)
    at = float(p["at"])
    dur = total - at if str(p["duration"]) == "all" else max(0.5, float(p["duration"]))
    iw, ih = float(item.get("width") or 1), float(item.get("height") or 1)
    w = p["size"]
    h = min(0.6, w * st.fmt["width"] / st.fmt["height"] * (ih / iw))
    sz = st.safe
    x = sz["left"] + 0.01 if p["corner"] in ("tl", "bl") else 1 - sz["right"] - 0.01 - w
    y = sz["top"] + 0.01 if p["corner"] in ("tl", "tr") else 1 - sz["bottom"] - 0.01 - h
    clip = ops.media_clip(st.project, item, at, start=0, end=dur, kind="image")
    clip.update({"x": round(max(0, x), 3), "y": round(max(0, y), 3), "width": round(w, 3), "height": round(h, 3), "fit": "contain", "has_audio": False})
    ops.place_free(st.project, "video", clip)
    return "لوگو گذاشته شد."


# =================================================================== audio


def _has_speech(st: State) -> bool:
    for t in st.project["tracks"]:
        if t["kind"] == "audio" and t.get("role") == "speech" and t["clips"]:
            return True
        if t["kind"] == "video" and any(c.get("has_audio") and c.get("audio_on", True) and c.get("kind") == "video" for c in t["clips"]):
            return True
    return False


@tool("add_music", "موسیقیِ پس‌زمینه", "audio", "Put background music under the whole video (looped/trimmed, fade-out, ducked under speech).",
      (P("ref", "موسیقی", "ref", "", doc="audio:<id> of a track in the bin"), P("query", "جست‌وجو", "text", "", max_len=60),
       P("volume_db", "بلندی", "num", -18, -30, 0, unit="dB"), P("duck", "کم‌شدن زیرِ گفتار", "bool", True), P("fade_out", "محوِ پایان", "num", 2, 0, 6, unit="ث"),
       P("start", "از ثانیهٔ آهنگ", "num", 0, 0, 3600, unit="ث"), P("id", "نشانی", "text", "")),
      lambda p: f"موسیقیِ پس‌زمینه ({fa(p['volume_db'])} dB) را بگذار")
def _music(st: State, p: dict):
    ref = p.get("ref") or ""
    if not ref:
        ref = st.ctx.find_music(p.get("query", "")) or ""
    if not ref:
        raise StepError("موسیقی‌ای انتخاب نشده و در کتابخانه‌ات موسیقی‌ای نیست؛ از «ساخت موسیقی» یا کتابخانه‌ی موسیقی یکی را انتخاب کن.")
    item = st.ctx.describe(ref)
    if not item or item.get("kind") != "audio":
        raise StepError("آهنگِ انتخاب‌شده پیدا نشد.")
    total = max(3.0, st.length)
    track = ops.audio_track(st.project, "music")
    track["clips"] = [c for c in track["clips"] if c.get("label") != "موسیقیِ پس‌زمینه"]
    dur = float(item.get("duration") or 0)
    if dur <= 0.5:
        raise StepError("آهنگ خالی است.")
    s0 = min(float(p["start"]), max(0.0, dur - 3.0))
    at = 0.0
    first = None
    for i in range(8):
        if at >= total - 0.05:
            break
        piece = min(dur - s0, total - at)
        clip = ops.media_clip(st.project, item, at, start=s0, end=s0 + piece, label="موسیقیِ پس‌زمینه")
        clip["volume"] = _db_to_lin(p["volume_db"])
        clip["fade_in"] = 0.6 if i == 0 else 0.3
        track["clips"].append(clip)
        first = first or clip
        at += piece
        s0 = 0.0
    last = track["clips"][-1]
    last["fade_out"] = round(min(float(p["fade_out"]), ops.clip_length(last) / 2), 2)
    ops.sort_track(track)
    if first:
        _alias(st, p, first)
    msg = f"موسیقی روی کلِ ویدیو ({fa(round(total, 1))} ثانیه) گذاشته شد."
    if p.get("duck") and _has_speech(st):
        d = st.project.setdefault("ducking", {})
        d.update({"on": True, "amount_db": d.get("amount_db", 12), "attack_ms": d.get("attack_ms", 40), "release_ms": d.get("release_ms", 500), "threshold": d.get("threshold", 0.04)})
        msg += " زیرِ گفتار کم می‌شود."
    return msg


@tool("ducking", "کم‌شدنِ موسیقی زیرِ گفتار", "audio", "Turn music ducking under speech on/off.",
      (P("on", "روشن", "bool", True), P("amount_db", "مقدار", "num", 12, 3, 30, unit="dB")),
      lambda p: "کم‌شدنِ موسیقی زیرِ گفتار " + ("روشن" if p["on"] else "خاموش"))
def _ducking(st: State, p: dict):
    d = st.project.setdefault("ducking", {})
    d.update({"on": bool(p["on"]), "amount_db": p.get("amount_db", 12), "attack_ms": d.get("attack_ms", 40), "release_ms": d.get("release_ms", 500), "threshold": d.get("threshold", 0.04)})
    return "کم‌شدنِ موسیقی " + ("روشن شد." if p["on"] else "خاموش شد.")


@tool("set_loudness", "بلندیِ استانداردِ شبکه‌ها", "audio", "Normalise the final mix for social media (about -14 LUFS, true-peak -1 dB).",
      (P("on", "روشن", "bool", True), P("target", "هدف (LUFS)", "num", -14, -24, -8, unit="LUFS"), P("tp", "سقفِ اوج", "num", -1, -3, 0, unit="dB")),
      lambda p: f"بلندیِ نهایی را روی {fa(p['target'])} LUFS بگذار" if p["on"] else "یکسان‌سازیِ بلندیِ نهایی خاموش")
def _loudness(st: State, p: dict):
    m = st.project.setdefault("master", {"gain_db": 0, "limiter": True})
    if p["on"]:
        m["loudness"] = {"on": True, "target": p["target"], "tp": p["tp"]}
        return f"بلندیِ نهایی روی {fa(p['target'])} LUFS و سقفِ اوج {fa(p['tp'])} dB تنظیم شد (در خروجی اعمال می‌شود)."
    m["loudness"] = {"on": False, "target": p["target"], "tp": p["tp"]}
    return "یکسان‌سازیِ بلندیِ نهایی خاموش شد."


@tool("clean_voice", "صدای تمیز", "audio", "Denoise (RNNoise) and polish speech clips.",
      (P("clip", "قطعه", "clip", "all"), P("level", "شدت", "choice", "light", choices=("light", "strong"))),
      lambda p: "نویزِ صدا را بگیر")
def _clean(st: State, p: dict):
    n = 0
    for c in _clips(st, p["clip"], with_sound=True):
        if _track_of(st, c).get("role") in ("music", "sfx"):
            continue
        a = dict(c.get("audio") or {})
        a["denoise_ai"] = True
        a.pop("denoise", None)
        if p["level"] == "strong":
            a["enhance"] = True
        c["audio"] = a
        n += 1
    if not n:
        raise StepError("صدایی برای تمیزکردن پیدا نشد.")
    return f"صدای {fa(n)} قطعه تمیز شد (در خروجی و پیش‌نمایشِ دقیق شنیده می‌شود)."


@tool("remove_silence", "حذفِ سکوت‌ها", "audio", "Cut the silent pauses out of speech clips (ripple on their own tracks).",
      (P("clip", "قطعه", "clip", "all"), P("min_silence", "کمترین سکوت", "num", 0.6, 0.3, 3, unit="ث"), P("keep", "نگه‌داشتنِ مکث", "num", 0.15, 0, 0.5, unit="ث")),
      lambda p: f"سکوت‌های بلندتر از {fa(p['min_silence'])} ثانیه را بردار")
def _silence(st: State, p: dict):
    targets = [c for c in _clips(st, p["clip"], with_sound=True) if _track_of(st, c).get("role") not in ("music", "sfx") and c.get("kind") != "image"]
    if p["clip"] in ("all", ""):
        seen, uniq = set(), []                      # the sound of a linked pair is cut through its partner, once
        for c in sorted(targets, key=lambda c: (_track_of(st, c)["kind"] != "video", float(c["at"]))):
            key = c.get("link") or c["id"]
            if key in seen:
                continue
            seen.add(key)
            uniq.append(c)
        targets = uniq
    plans = []
    for c in targets:
        spans = st.ctx.spans(c["ref"]) or []
        if not spans:
            continue
        a0, b0 = float(c["start"]), float(c["end"])
        sp = sorted((max(a0, float(s)), min(b0, float(e))) for s, e in spans if float(e) > a0 and float(s) < b0)
        gaps, prev_end = [], a0
        for s, e in sp:
            if s - prev_end >= p["min_silence"]:
                gaps.append((prev_end + (p["keep"] if prev_end > a0 + 0.01 else 0.0), s - p["keep"]))
            prev_end = max(prev_end, e)
        if b0 - prev_end >= p["min_silence"]:
            gaps.append((prev_end + p["keep"], b0))
        gaps = [(g0, g1) for g0, g1 in gaps if g1 - g0 >= 0.15]
        if gaps:
            tracks = {_track_of(st, x)["id"] for x in ops.linked_ids_clips(st.project, [c["id"]])}
            plans.append((float(c["at"]), c, gaps, tracks))
    if not plans:
        raise StepError("سکوتِ قابل‌حذفی پیدا نشد (یا گفتارِ قطعه تشخیص داده نشد).")
    cut_total, touched = _apply_cuts(st, plans)
    return f"{fa(round(cut_total, 1))} ثانیه سکوت از {fa(touched)} قطعه برداشته شد."


def _apply_cuts(st: State, plans: list) -> tuple[float, int]:
    """plans = [(clip.at, clip, [(source_from, source_to)...], {track ids})] -> remove those source ranges on the clip's own tracks (ripple).
    Latest clip first and latest range first, so the times of what is still to be cut stay valid. Returns (seconds cut, clips touched)."""
    total_clips = sum(len(t["clips"]) for t in st.project["tracks"])
    cut_total, touched = 0.0, 0
    for _, c, gaps, tracks in sorted(plans, key=lambda x: -x[0]):
        if total_clips + 2 * len(gaps) > tl.MAX_CLIPS - 5:
            continue
        ranges = []
        for g0, g1 in gaps:
            t0, t1 = ops.source_to_timeline(c, g0), ops.source_to_timeline(c, g1)
            ranges.append((min(t0, t1), max(t0, t1)))
        for lo, hi in sorted(ranges, reverse=True):
            ops.remove_range(st.project, lo, hi, True, only_tracks=tracks)
            cut_total += hi - lo
        total_clips += 2 * len(gaps)
        touched += 1
    if not touched:
        raise StepError("پروژه برای این کار بیش از حد بزرگ است.")
    _fit_music_tail(st)
    return cut_total, touched


#: Hesitation sounds a speaker makes while thinking (after `_norm_word`): never real words. «هم» and «ای» are NOT here on purpose (they are words).
FILLERS_HARD = {"ا", "اا", "آ", "آآ", "اه", "آه", "ام", "امم", "اوم", "اووم", "همم", "um", "umm", "uh", "uhh", "hmm", "er", "eh", "ah"}
#: Discourse fillers that ARE words: only with `include_soft` (the owner's choice).
FILLERS_SOFT = {"خب", "خوب", "یعنی", "چیزه", "ببین", "راستش"}
_DIACRITICS = dict.fromkeys(list(range(0x064B, 0x0653)) + [0x0670, 0x0640, 0x200C, 0x200F, 0x200E], None)


def _norm_word(w: str) -> str:
    """Lower-case, no diacritics/ZWNJ/punctuation, Arabic ي ك -> ی ک, and letter runs squeezed to two (اممممم -> امم)."""
    s = str(w or "").translate(_DIACRITICS).replace("ي", "ی").replace("ك", "ک").lower()
    s = "".join(ch for ch in s if ch.isalnum())
    out: list[str] = []
    for ch in s:
        if len(out) >= 2 and out[-1] == ch and out[-2] == ch:
            continue
        out.append(ch)
    return "".join(out)


@tool("remove_fillers", "حذفِ «اِم و اوم»", "audio", "Cut hesitation sounds (um/uh/ام/اوم) out of speech using the transcript; soft fillers only on request.",
      (P("clip", "قطعه", "clip", "all"), P("include_soft", "«خب، یعنی، ببین» هم", "bool", False), P("min_len", "کمترین طولِ صدا", "num", 0.12, 0.05, 1, unit="ث")),
      lambda p: "صداهای مکث‌دار (اِم، اوم) را بردار" + (" و «خب/یعنی/ببین»" if p.get("include_soft") else ""))
def _fillers(st: State, p: dict):
    targets = [c for c in _clips(st, p["clip"], with_sound=True) if _track_of(st, c).get("role") not in ("music", "sfx") and c.get("kind") != "image"]
    if p["clip"] in ("all", ""):
        seen, uniq = set(), []
        for c in sorted(targets, key=lambda c: (_track_of(st, c)["kind"] != "video", float(c["at"]))):
            key = c.get("link") or c["id"]
            if key in seen:
                continue
            seen.add(key)
            uniq.append(c)
        targets = uniq
    bad = FILLERS_HARD | (FILLERS_SOFT if p.get("include_soft") else set())
    plans, heard_any = [], False
    for c in targets:
        try:
            words = st.ctx.words(c["ref"], float(c["start"]), float(c["end"]))
        except Exception as exc:  # noqa: BLE001 - speech recognition off: the owner needs to know WHY, not "nothing found"
            raise StepError(str(exc) or "تشخیصِ گفتار در دسترس نیست.") from exc
        if not words:
            continue
        heard_any = True
        gaps = []
        for w in words:
            if _norm_word(w["w"]) in bad and float(w["e"]) - float(w["s"]) >= p["min_len"]:
                g0, g1 = float(c["start"]) + float(w["s"]) - 0.03, float(c["start"]) + float(w["e"]) + 0.05
                if gaps and g0 <= gaps[-1][1] + 0.05:
                    gaps[-1] = (gaps[-1][0], max(gaps[-1][1], g1))
                else:
                    gaps.append((g0, g1))
        gaps = [(max(float(c["start"]), a), min(float(c["end"]), b)) for a, b in gaps if b - a >= 0.1]
        if gaps:
            tracks = {_track_of(st, x)["id"] for x in ops.linked_ids_clips(st.project, [c["id"]])}
            plans.append((float(c["at"]), c, gaps, tracks))
    if not heard_any:
        raise StepError("گفتاری برای بررسی پیدا نشد (یا تشخیصِ گفتار در دسترس نیست).")
    if not plans:
        return "صدای مکث‌داری (اِم، اوم) پیدا نشد؛ چیزی حذف نشد."
    cut_total, touched = _apply_cuts(st, plans)
    return f"{fa(round(cut_total, 1))} ثانیه صدای مکث‌دار از {fa(touched)} قطعه برداشته شد."


def _fit_music_tail(st: State) -> None:
    """After cuts the program is shorter: a music bed that outlives the picture is trimmed to it (with a fade)."""
    total = max(ops.end_of(ops.main_track(st.project)), 0.0)
    if total < 1:
        return
    for t in st.project["tracks"]:
        if t["kind"] == "audio" and t.get("role") == "music":
            for c in list(t["clips"]):
                if float(c["at"]) >= total - 0.1:
                    t["clips"].remove(c)
                elif ops.clip_end(c) > total + 0.05:
                    ops.trim(st.project, c["id"], end=float(c["start"]) + (total - float(c["at"])) * float(c.get("speed") or 1))
                    c["fade_out"] = max(float(c.get("fade_out") or 0), 1.5)


@tool("add_voiceover", "گویندگی", "audio", "Add a voice-over: an audio asset, or text turned into speech (needs a TTS engine).",
      (P("ref", "صدا", "ref", "", doc="audio:<id>"), P("text", "متن (برای ساختِ گفتار)", "text", "", max_len=600), P("voice", "صدای گوینده", "text", "", max_len=60),
       P("at", "زمان", "num", 0, 0, 86400, unit="ث")),
      lambda p: "گویندگی را بگذار")
def _voiceover(st: State, p: dict):
    ref = p.get("ref") or ""
    if not ref:
        if not p.get("text"):
            raise StepError("صدا یا متنِ گویندگی لازم است.")
        if st.ctx.make_speech is None:
            raise StepError("ساختنِ گفتار از متن اینجا در دسترس نیست.")
        ref = st.ctx.make_speech(p["text"], p.get("voice", ""))
    item = st.ctx.describe(ref)
    if not item or item.get("kind") != "audio":
        raise StepError("صدای گویندگی پیدا نشد.")
    clip = ops.media_clip(st.project, item, p["at"], label="گویندگی")
    ops.place_free(st.project, "audio", clip, role="speech")
    return f"گویندگی ({fa(round(ops.clip_length(clip), 1))} ثانیه) در ثانیهٔ {fa(clip['at'])} گذاشته شد."


@tool("add_sfx", "جلوهٔ صوتی", "audio", "Place a sound effect at a time.",
      (P("ref", "صدا", "ref", required=True), P("at", "زمان", "num", required=True, minimum=0, maximum=86400, unit="ث"), P("volume_db", "بلندی", "num", -10, -40, 6, unit="dB")),
      lambda p: f"جلوهٔ صوتی را در ثانیهٔ {fa(p['at'])} بگذار")
def _sfx(st: State, p: dict):
    item = st.ctx.describe(p["ref"])
    if not item or item.get("kind") != "audio":
        raise StepError("جلوهٔ صوتی پیدا نشد.")
    clip = ops.media_clip(st.project, item, p["at"], label=item.get("title") or "جلوه")
    clip["volume"] = _db_to_lin(p["volume_db"])
    ops.place_free(st.project, "audio", clip, role="sfx")
    return "جلوهٔ صوتی گذاشته شد."


@tool("clip_volume", "بلندیِ قطعه", "audio", "Set a clip's volume in dB (0 = unchanged, -60 = silent).",
      (P("clip", "قطعه", "clip", required=True), P("db", "بلندی", "num", required=True, minimum=-60, maximum=9.5, unit="dB")),
      lambda p: f"بلندیِ قطعه را {fa(p['db'])} dB بگذار")
def _clip_volume(st: State, p: dict):
    n = 0
    for c in _clips(st, p["clip"], media_only=True):
        c["volume"] = _db_to_lin(p["db"]) if p["db"] > -59.5 else 0.0
        n += 1
    return f"بلندیِ {fa(n)} قطعه تنظیم شد."


@tool("fade", "محو شدن", "audio", "Fade a clip in and/or out (seconds).",
      (P("clip", "قطعه", "clip", required=True), P("fade_in", "محوِ ابتدا", "num", 0, 0, 10, unit="ث"), P("fade_out", "محوِ انتها", "num", 0, 0, 10, unit="ث")),
      lambda p: "محوِ ابتدا/انتها را بگذار")
def _fade(st: State, p: dict):
    for c in _clips(st, p["clip"], media_only=True):
        half = ops.clip_length(c) / 2
        c["fade_in"], c["fade_out"] = round(min(p["fade_in"], half), 2), round(min(p["fade_out"], half), 2)
    return "محو گذاشته شد."


@tool("auto_mix", "تنظیمِ خودکارِ میکس", "audio", "Balance levels so speech is clearly above music; duck music; social loudness.",
      (), lambda p: "بلندیِ گفتار و موسیقی را خودکار تنظیم کن")
def _auto_mix(st: State, p: dict):
    changes = []
    music_clips = [c for t in st.project["tracks"] if t["kind"] == "audio" and t.get("role") == "music" for c in t["clips"]]
    sfx_clips = [c for t in st.project["tracks"] if t["kind"] == "audio" and t.get("role") == "sfx" for c in t["clips"]]
    speech = _has_speech(st)
    for t in st.project["tracks"]:
        if t["kind"] == "audio" and not t.get("role"):
            t["role"] = "speech" if t["clips"] and not music_clips and not speech else "music"
    for c in music_clips:
        target = _db_to_lin(-18 if speech else -10)
        if float(c.get("volume", 1)) > target * 1.12:
            c["volume"] = target
            changes.append("موسیقی")
    for c in sfx_clips:
        if float(c.get("volume", 1)) > _db_to_lin(-8):
            c["volume"] = _db_to_lin(-10)
            changes.append("جلوه‌ها")
    if speech and music_clips:
        d = st.project.setdefault("ducking", {})
        if not d.get("on"):
            d.update({"on": True, "amount_db": 12, "attack_ms": 40, "release_ms": 500, "threshold": 0.04})
            changes.append("کم‌شدنِ موسیقی زیرِ گفتار")
    m = st.project.setdefault("master", {"gain_db": 0, "limiter": True})
    if not (m.get("loudness") or {}).get("on"):
        m["loudness"] = {"on": True, "target": -14, "tp": -1}
        changes.append("بلندیِ استاندارد (−۱۴)")
    return ("میکس تنظیم شد: " + "، ".join(sorted(set(changes))) + ".") if changes else "میکس از قبل مناسب بود."


@tool("mark_beats", "نشانگرِ ضرب‌ها", "audio", "Drop beat markers for a music clip (or ref) on the timeline.",
      (P("music", "موسیقی (قطعه یا منبع)", "clip", required=True),),
      lambda p: "ضرب‌های موسیقی را نشانگذاری کن")
def _mark_beats(st: State, p: dict):
    try:
        mc = _clips(st, p["music"], media_only=True)[0]
        beats = [ops.source_to_timeline(mc, b) for b in (st.ctx.beats(mc["ref"]).get("beats") or []) if float(mc["start"]) <= b <= float(mc["end"])]
    except StepError:
        beats = list((st.ctx.beats(p["music"]) or {}).get("beats") or [])
    if not beats:
        raise StepError("ضربی پیدا نشد.")
    mk = [m for m in st.project.get("markers", []) if m.get("kind") != "beat"]
    for b in beats[:300]:
        mk.append({"id": ops.uid(st.project, "m"), "t": round(b, 3), "label": "", "color": "#38bdf8", "kind": "beat"})
    st.project["markers"] = sorted(mk, key=lambda m: m["t"])[:400]
    return f"{fa(min(len(beats), 300))} ضرب نشانه‌گذاری شد."


def catalogue_for_model(names: tuple[str, ...] | None = None) -> list[dict]:
    return [t.for_model() for k, t in TOOLS.items() if names is None or k in names]


def catalogue_for_ui() -> list[dict]:
    return [t.as_dict() for t in TOOLS.values()]
