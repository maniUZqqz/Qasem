"""Timeline → one ffmpeg filtergraph. The picture half lives here, the sound half in `audiofx.py`.

**Every video clip is a layer**: input (fast-seeked to its in-point) → time remap (speed / ramp / reverse / freeze) →
fit → colour → chroma key → alpha (opacity, fades, crop, mask — one `geq` mask video when it is animated) → rotate →
scale → `overlay` at the layer's CENTRE (so scale and rotation animate around it). A property that animates is an
ffmpeg expression of time built by `keyframes.expr`, never a baked frame sequence.

**A transition is a window on the cut**: `[cut - d/2, cut + d/2]`. Both clips are rendered into that window on a black
canvas (their handles, or a held frame when the source has no more footage), `xfade` blends them, and the result is
laid over the track for exactly that window; the two clips themselves only show outside it.

**Time is explicit**: the base is a `color` source of the project length, every layer carries timeline timestamps
(`setpts=PTS+at/TB`) and an `enable='between(t,…)'` window, titles come from libass (`titles.build_ass`).

**Nested sequences are inlined**: a clip whose `nested` is a Timeline gets a sub-`Builder` that shares this one's parts,
inputs and label counter and returns the nested picture (and sound) as a stream label; the parent clip then trims / speeds /
fits that stream exactly like a file input. A **matte** (background removal) is a grey video merged into the clip's alpha
right at the source; a **free-form mask** is a grey PNG multiplied into the layer's alpha mask (moved by an `overlay`
expression when a motion track is attached); a **LUT** is one `lut3d` after the colour block.

**Portable graphs** (`portable=True`, for a render on the processing node): paths of files that sit INSIDE a filter option
(the ASS documents, the fonts folder, LUTs) become tokens (`__FILE_n__`, `__FONTSDIR__`, `__ASSET_n__`) that the other
computer substitutes with its own copies; everything else is the ordinary `-i` list.
"""
from __future__ import annotations

import functools
import logging
from dataclasses import dataclass, field

from . import color as color_module
from . import keyframes, transitions
from .errors import TimelineError
from .timeline import Clip, TextClip, Timeline, Track, _atempo, _effect_fragment, _f, cut_segments

logger = logging.getLogger(__name__)

#: Substituted by `export.render` with the path of a temp file per ASS document.
FILE_TOKEN = "__FILE_{n}__"
TEXTFILE_TOKEN = FILE_TOKEN  # name kept for callers of the old drawtext path
ASSET_TOKEN = "__ASSET_{n}__"

#: how a blend mode is done: the neutral canvas the layer is composited on first (so the area outside it changes
#: nothing), and ffmpeg's blend mode
_BLEND = {
    "multiply": ("white", "multiply"), "screen": ("black", "screen"), "add": ("black", "addition"),
    "overlay": ("0x808080", "overlay"), "softlight": ("0x808080", "softlight"), "lighten": ("black", "lighten"),
    "darken": ("white", "darken"), "difference": ("black", "difference"),
}

MASK_MAX = 640


@dataclass
class Graph:
    inputs: list[str]
    input_args: list[list[str]]
    graph: str
    #: token → text of a temp file (the ASS documents) that `export.render` writes and substitutes
    texts: dict[str, str]
    has_audio: bool
    length: float = 0.0
    notes: list[str] = field(default_factory=list)
    #: token → path of a file referenced INSIDE a filter option (portable graphs only; see the module doc)
    assets: dict[str, str] = field(default_factory=dict)


def _q(x: float) -> str:
    return f"{x:.3f}"


def _even(x: float) -> int:
    return max(2, int(x) // 2 * 2)


@functools.lru_cache(maxsize=128)
def _source_size(path: str) -> tuple[int, int]:
    """Displayed (width, height) of a video file — a phone clip with a rotation tag is shown turned, and so is its matte."""
    from services.video.ffmpeg import probe

    info = probe(path)
    for stream in info.get("streams", []):
        if stream.get("codec_type") == "video" and stream.get("width"):
            w, h = int(stream["width"]), int(stream["height"])
            rot = 0
            try:
                rot = int(float((stream.get("tags") or {}).get("rotate") or 0))
            except (TypeError, ValueError):
                rot = 0
            for side in stream.get("side_data_list") or []:
                if "rotation" in side:
                    try:
                        rot = int(float(side["rotation"]))
                    except (TypeError, ValueError):
                        pass
            return (h, w) if abs(rot) % 180 == 90 else (w, h)
    raise TimelineError("ابعادِ ویدیو خوانده نشد.")


class Builder:
    def __init__(self, timeline: Timeline, *, spans=None, portable: bool = False, parent: "Builder | None" = None, flow: bool = True, alpha: bool = False):
        self.tl = timeline
        self.W, self.H, self.fps = timeline.width, timeline.height, timeline.fps
        self.parent = parent
        self.root = parent.root if parent else self
        self.flow = parent.flow if parent else flow           # optical flow (minterpolate) is heavy: not in the site's quick draft
        self.alpha = parent.alpha if parent else alpha         # a transparent base (ProRes 4444 with alpha)
        if parent:                              # a nested sequence: one graph, one label space
            self.inputs, self.args, self.parts = parent.inputs, parent.args, parent.parts
            self.texts, self.notes, self.assets = parent.texts, parent.notes, parent.assets
            self.portable = parent.portable
        else:
            self.inputs, self.args, self.parts = [], [], []
            self.texts, self.notes, self.assets = {}, [], {}
            self.portable = portable
        self.n = 0
        self.main_input: dict[int, int] = {}
        self.seeks: dict[int, float] = {}
        self.spans = spans                      # callable(path) -> [[s, e], …] for ducking (None ⇒ media_cache)
        self.vis: dict[int, tuple[float, float]] = {}
        self.matte_of: dict[int, Clip] = {}         # id(clip with a track matte) -> the clip that is its matte
        self.matte_src: set[int] = set()
        self.matte_used: set[int] = set()
        self.audio_fade_in: dict[int, float] = {}
        self.audio_fade_out: dict[int, float] = {}

    # ------------------------------------------------------------ plumbing
    def lab(self, prefix: str = "x") -> str:
        self.root.n += 1
        return f"{prefix}{self.root.n}"

    def file_opt(self, path) -> str:
        """A file path for a filter option: the real quoted path, or (portable) a token the other computer fills in."""
        from services.video.ffmpeg import filter_path

        if not self.portable:
            return filter_path(path)
        token = ASSET_TOKEN.format(n=len(self.assets))
        self.assets[token] = str(path)
        return filter_path(token)

    def nested_video(self, clip: Clip) -> str:
        """The picture of a nested clip's sequence as a stream label (built again for every use: a label feeds one filter)."""
        sub = Builder(clip.nested, spans=self.spans, parent=self)
        return sub.build_video(final=self.lab("nv"))

    def nested_audio(self, clip: Clip) -> str | None:
        from . import audiofx

        sub = Builder(clip.nested, spans=self.spans, parent=self)
        out = self.lab("na")
        return out if audiofx.build_audio(sub, final=out) else None

    def add_input(self, source: str, args: list[str]) -> int:
        self.inputs.append(source)
        self.args.append(args)
        return len(self.inputs) - 1

    def input_args_for(self, clip: Clip, segs: list[tuple[float, float, float]] | None = None) -> tuple[list[str], float]:
        """ffmpeg input options for a clip and the source second its stream now starts at (fast seek to the in-point)."""
        if clip.kind == "image":
            return ["-loop", "1", "-framerate", str(self.fps), "-t", _q(max(0.1, clip.length) + 0.6)], 0.0
        segs = segs if segs is not None else clip.segments()
        if clip.freeze:
            seek = clip.start
            span = 1.0
        elif segs:
            seek = min(s[0] for s in segs)
            span = max(s[1] for s in segs) - seek + 0.1
        else:
            seek, span = clip.start, 1.0
        # a source that cannot be sought cheaply (very short seek) is simply trimmed
        args = (["-ss", _q(seek)] if seek > 0.001 else []) + ["-t", _q(span)]
        return args, seek if seek > 0.001 else 0.0

    def main_input_for(self, clip: Clip) -> tuple[int, float]:
        """The input of a clip's MAIN use (its video layer and its audio share it)."""
        if id(clip) not in self.main_input:
            args, seek = self.input_args_for(clip)
            self.main_input[id(clip)] = self.add_input(clip.source, args)
            self.seeks[id(clip)] = seek
        return self.main_input[id(clip)], self.seeks[id(clip)]

    # ------------------------------------------------------------- the video
    def build_video(self, final: str = "vout") -> str:
        tl = self.tl
        length = max(0.1, tl.length)
        base = self.lab("base")
        if self.alpha:
            self.parts.append(f"color=c=black@0:s={self.W}x{self.H}:r={self.fps}:d={length:.3f},format=yuva420p[{base}]")
        else:
            self.parts.append(f"color=c=black:s={self.W}x{self.H}:r={self.fps}:d={length:.3f}[{base}]")
        current = base
        self.plan_mattes()
        for track in tl.tracks:
            if track.kind == "video" and not track.hidden:
                current = self.video_track(track, current)
            elif track.kind == "text":
                current = self.text_track(track, current)
        if self.alpha:
            self.parts.append(f"[{current}]format=yuva444p10le[{final}]")
        else:
            self.parts.append(f"[{current}]null[{final}]")
        return final

    def plan_mattes(self) -> None:
        """Pair every clip that asks for a track matte with the clip that overlaps it most on the next video track up."""
        tracks = [t for t in self.tl.tracks if t.kind == "video" and not t.hidden]
        for lower, upper in zip(tracks, tracks[1:]):
            for a in lower.clips:
                if not a.track_matte or a.kind == "audio" or a.adjust:
                    continue
                best, over = None, 0.05
                for m in upper.clips:
                    if m.kind == "audio" or m.adjust or id(m) in self.matte_src:
                        continue
                    o = min(a.ends_at, m.ends_at) - max(a.at, m.at)
                    if o > over:
                        best, over = m, o
                if best is None:
                    self.notes.append("ماتِ ترک: روی ترکِ بالاتر قطعه‌ای هم‌زمان با «%s» نبود؛ مات نادیده گرفته شد." % (a.label or "قطعه"))
                    continue
                self.matte_of[id(a)] = best
                self.matte_src.add(id(best))

    def clip_layer(self, clip: Clip) -> str:
        if clip.nested is not None:
            return self.layer(clip, None, 0.0, clip.segments(), clip.reverse, at=clip.at, off_start=0.0, length=clip.length, src=self.nested_video(clip))
        idx, seek = self.main_input_for(clip)
        return self.layer(clip, idx, seek, clip.segments(), clip.reverse, at=clip.at, off_start=0.0, length=clip.length)

    def matte_place(self, current: str, a: Clip, m: Clip, vs: float, ve: float) -> str:
        """Clip `a` seen through clip `m`: both are laid on a full-frame canvas (a on a transparent one, m on black), the matte's brightness (or
        transparency) is multiplied into a's own alpha, and the result goes over what is below."""
        tm = a.track_matte
        length = max(0.1, self.tl.length)
        W, H, fps = self.W, self.H, self.fps
        ca, cm = self.lab("ma"), self.lab("mm")
        self.parts.append(f"color=c=black@0:s={W}x{H}:r={fps}:d={length:.3f},format=yuva420p[{ca}]")
        layer_a = self.clip_layer(a)
        full_a = self.place(ca, layer_a, a, vs, ve, at=a.at, off_start=0.0, fmt=":format=auto")
        layer_m = self.clip_layer(m)
        if tm["mode"] == "alpha":
            self.parts.append(f"color=c=black@0:s={W}x{H}:r={fps}:d={length:.3f},format=yuva420p[{cm}]")
        else:
            self.parts.append(f"color=c=black:s={W}x{H}:r={fps}:d={length:.3f},format=yuva420p[{cm}]")
        full_m = self.place(cm, layer_m, m, m.at, m.ends_at, at=m.at, off_start=0.0, fmt=":format=auto")
        gm = self.lab("mg")
        tail = ",negate" if tm["invert"] else ""
        if tm["mode"] == "alpha":
            self.parts.append(f"[{full_m}]alphaextract{tail}[{gm}]")
        else:
            self.parts.append(f"[{full_m}]format=gray{tail}[{gm}]")
        k1, k2, ka, m2, am, out = (self.lab(x) for x in ("mk", "mk", "mk", "mk", "mx", "mv"))
        self.parts.append(f"[{full_a}]split[{k1}][{k2}];[{k1}]alphaextract[{ka}];[{ka}][{gm}]blend=all_mode=multiply[{m2}];[{k2}][{m2}]alphamerge[{am}]")
        self.parts.append(f"[{current}][{am}]overlay=x=0:y=0:enable='between(t,{_q(vs)},{_q(ve)})':eof_action=pass[{out}]")
        self.matte_used.add(id(m))
        return out

    def plan_transitions(self, track: Track) -> list[tuple[Clip, Clip, float, str]]:
        """Pairs of neighbours that touch and have a transition into the second one."""
        found = []
        ordered = sorted(track.clips, key=lambda c: c.at)
        for earlier, later in zip(ordered, ordered[1:]):
            tr = later.transition
            if not tr or abs(later.at - earlier.ends_at) > 0.15:
                continue
            d = max(0.1, min(float(tr.get("duration", 0.5)), 2.0, 0.9 * min(earlier.length, later.length)))
            half = d / 2
            cut = later.at
            self.vis[id(earlier)] = (self.vis.get(id(earlier), (earlier.at, earlier.ends_at))[0], cut - half)
            self.vis[id(later)] = (cut + half, self.vis.get(id(later), (later.at, later.ends_at))[1])
            self.audio_fade_out[id(earlier)] = max(self.audio_fade_out.get(id(earlier), 0.0), half)
            self.audio_fade_in[id(later)] = max(self.audio_fade_in.get(id(later), 0.0), half)
            found.append((earlier, later, d, transitions.xfade_name(str(tr["kind"]))))
        return found

    def video_track(self, track: Track, current: str) -> str:
        pairs = self.plan_transitions(track)
        for clip in sorted(track.clips, key=lambda c: c.at):
            if clip.kind == "audio":
                continue
            vs, ve = self.vis.get(id(clip), (clip.at, clip.ends_at))
            if ve <= vs + 0.001:
                continue
            if clip.adjust:
                current = self.adjust_layer(current, clip, vs, ve)
                continue
            if id(clip) in self.matte_used:                      # this clip was used up as somebody's matte
                continue
            m = self.matte_of.get(id(clip))
            if m is not None and id(clip) not in self.vis and clip.kind in ("video", "image"):
                current = self.matte_place(current, clip, m, vs, ve)
                continue
            if clip.nested is not None:
                layer = self.layer(clip, None, 0.0, clip.segments(), clip.reverse, at=clip.at, off_start=0.0, length=clip.length,
                                   src=self.nested_video(clip))
            else:
                idx, seek = self.main_input_for(clip)
                layer = self.layer(clip, idx, seek, clip.segments(), clip.reverse, at=clip.at, off_start=0.0, length=clip.length)
            current = self.place(current, layer, clip, vs, ve, at=clip.at, off_start=0.0)
        for earlier, later, d, name in pairs:
            current = self.transition_window(earlier, later, d, name, current)
        return current

    def fps_filter(self, clip: Clip, segs) -> str:
        """`fps=N`, or — for a SLOWED clip that asked for it — frame blending / optical-flow interpolation (`minterpolate`)."""
        fps = self.fps
        slowed = any(v < 0.999 for _a, _b, v in (segs or [])) and not clip.freeze
        if clip.frames == "blend" and slowed:
            return f"minterpolate=fps={fps}:mi_mode=blend"
        if clip.frames == "flow" and slowed:
            if not self.flow:
                self.notes.append("اپتیکال‌فلو در پیش‌نویسِ سریعِ روی سایت اجرا نمی‌شود (سنگین است)؛ در خروجیِ نهایی روی سرورِ پردازش هست.")
                return f"fps={fps}"
            return f"minterpolate=fps={fps}:mi_mode=mci:mc_mode=aobmc:me_mode=bidir:vsbmc=1"
        return f"fps={fps}"

    # ------------------------------------------------------ adjustment layer
    def adjust_layer(self, current: str, clip: Clip, t_from: float, t_to: float) -> str:
        """A «لایهٔ تنظیم»: everything composed so far is split; one branch gets this layer's colour / LUT / effects; for the clip's duration the corrected
        branch replaces the original (at the layer's opacity)."""
        chain: list[str] = []
        if clip.color:
            chain += color_module.build_filters(clip.color)
        if clip.lut_file:
            chain.append(f"lut3d=file={self.file_opt(clip.lut_file)}:interp=tetrahedral")
        for effect in clip.effects:
            chain.append(_effect_fragment(effect))
        if not chain:
            return current
        keep, fx0, fx, out = self.lab("ak"), self.lab("af"), self.lab("ax"), self.lab("av")
        enable = f"enable='between(t,{_q(t_from)},{_q(t_to)})'"
        self.parts.append(f"[{current}]split=2[{keep}][{fx0}]")
        self.parts.append(f"[{fx0}]" + ",".join(chain) + f"[{fx}]")
        if clip.opacity >= 0.999:
            self.parts.append(f"[{keep}][{fx}]overlay=x=0:y=0:{enable}:eof_action=pass{':format=auto' if self.alpha else ''}[{out}]")
        else:
            a, b = self.lab("aa"), self.lab("ab")
            self.parts.append(f"[{keep}]format=gbrp[{a}];[{fx}]format=gbrp[{b}]")
            self.parts.append(f"[{a}][{b}]blend=all_mode=normal:all_opacity={clip.opacity:.3f}:{enable},format=yuv420p[{out}]")
        return out

    # ---------------------------------------------------------------- layer
    def apply_matte(self, clip: Clip, idx: int, seek: float) -> str:
        """Merge the clip's matte (grey video) into the alpha of its source stream, right at the source."""
        w, h = clip.src_w, clip.src_h
        if not (w and h):
            w, h = _source_size(clip.source)
        segs = clip.segments()
        span = (max(s[1] for s in segs) - seek) + 0.5 if segs else 1.0
        into = seek - clip.matte_s0                      # where, in the matte file, the source second `seek` is
        args = (["-ss", _q(into)] if into > 0.001 else []) + ["-t", _q(span)]
        midx = self.add_input(clip.matte_file, args)
        mk, out = self.lab("mk"), self.lab("mt")
        chain = ["format=gray"]
        if into < -0.001:
            chain.append(f"tpad=start_mode=clone:start_duration={_q(-into)}")
        chain += [f"scale={w}:{h}:flags=bilinear", "setsar=1"]
        self.parts.append(f"[{midx}:v]" + ",".join(chain) + f"[{mk}]")
        self.parts.append(f"[{idx}:v][{mk}]alphamerge[{out}]")
        return out

    def layer(self, clip: Clip, idx: int | None, seek: float, segs: list, reverse: bool, *, at: float, off_start: float,
              length: float, fades: bool = True, pad_head: float = 0.0, pad_tail: float = 0.0, src: str | None = None) -> str:
        """The finished layer stream of one clip (or one piece of it): all of the per-clip filters, positioned in time.
        `src` is a ready stream label (a nested sequence) instead of the input `idx`."""
        W, H, fps = self.W, self.H, self.fps
        cur = src if src is not None else f"{idx}:v"
        if clip.matte_file and src is None and clip.kind == "video":
            cur = self.apply_matte(clip, idx, seek)
        ch: list[str] = []

        def flush(out: str | None = None) -> None:
            nonlocal cur, ch
            if not ch:
                return
            out = out or self.lab("l")
            self.parts.append(f"[{cur}]" + ",".join(ch) + f"[{out}]")
            cur, ch = out, []

        # 1 · time remap -------------------------------------------------
        if clip.kind == "image":
            ch += [f"trim=0:{_q(length + pad_head + pad_tail)}", "setpts=PTS-STARTPTS"]
        elif clip.freeze:
            if src is not None:                               # a nested stream starts at 0, not at the clip's in-point
                ch += [f"trim=start={_q(clip.start)}", "setpts=PTS-STARTPTS"]
            ch += ["trim=start_frame=0:end_frame=1", "setpts=PTS-STARTPTS",
                   f"tpad=stop_mode=clone:stop_duration={_q(length + 0.1)}", f"trim=duration={_q(length)}", "setpts=PTS-STARTPTS"]
        elif len(segs) == 1:
            a, b, v = segs[0]
            ch += [f"trim={_q(a - seek)}:{_q(b - seek)}",
                   f"setpts=(PTS-STARTPTS)/{_f(v)}" if abs(v - 1) > 1e-6 else "setpts=PTS-STARTPTS"]
        else:
            n = len(segs)
            pads = [self.lab("s") for _ in range(n)]
            self.parts.append(f"[{cur}]split={n}" + "".join(f"[{p}]" for p in pads))
            outs = []
            for p, (a, b, v) in zip(pads, segs):
                o = self.lab("c")
                self.parts.append(f"[{p}]trim={_q(a - seek)}:{_q(b - seek)},setpts=(PTS-STARTPTS)/{_f(v)}[{o}]")
                outs.append(o)
            joined = self.lab("j")
            self.parts.append("".join(f"[{o}]" for o in outs) + f"concat=n={n}:v=1:a=0[{joined}]")
            cur = joined
            ch.append("setpts=PTS-STARTPTS")
        if pad_head > 0.001:
            ch.append(f"tpad=start_mode=clone:start_duration={_q(pad_head)}")
        if pad_tail > 0.001:
            ch.append(f"tpad=stop_mode=clone:stop_duration={_q(pad_tail)}")
        if clip.kind != "image":
            ch.append(self.fps_filter(clip, segs))

        # 2 · reframe window, orientation, fit -----------------------------
        if clip.interpret.get("deinterlace"):
            ch.append("yadif=mode=0")                          # خط‌های درهم (interlace) ⇒ فریمِ کامل
        if clip.interpret and abs(float(clip.interpret.get("par", 1.0)) - 1.0) > 0.005:
            ch.append(f"scale=trunc(iw*{_f(clip.interpret['par'])}/2)*2:ih")   # نسبتِ پیکسل (فیلمِ آنامورفیک) ⇒ پیکسلِ مربع
        if clip.reframe and clip.kind in ("video", "image") and src is None:
            ch.append(self.reframe_crop(clip, off_start - pad_head))
        for effect in clip.effects:
            if effect.get("tool") == "rotate":
                ch.append(_effect_fragment(effect))
        if clip.flip_h:
            ch.append("hflip")
        if clip.flip_v:
            ch.append("vflip")
        bw, bh = _even(W * clip.width), _even(H * clip.height)
        if clip.fit == "cover":
            ch.append(f"scale={bw}:{bh}:force_original_aspect_ratio=increase,crop={bw}:{bh}")
        elif clip.fit == "contain":
            ch.append(f"scale={bw}:{bh}:force_original_aspect_ratio=decrease,pad={bw}:{bh}:(ow-iw)/2:(oh-ih)/2:color=black")
        else:
            ch.append(f"scale={bw}:{bh}")
        ch.append("setsar=1")
        if reverse and clip.kind == "video":
            ch += ["reverse", "setpts=PTS-STARTPTS"]
        if clip.lens:                                          # اصلاحِ اعوجاجِ لنز (k1 < 0 = بشکه‌ای را صاف می‌کند، k1 > 0 = بالشتکی را)
            ch.append(f"lenscorrection=cx=0.5:cy=0.5:k1={_f(clip.lens['k1'])}:k2={_f(clip.lens['k2'])}")

        if clip.denoise:                                       # نویزگیرِ تصویر
            a = float(clip.denoise["amount"])
            if clip.denoise.get("mode") == "strong":
                ch.append(f"nlmeans=s={1 + 5 * a:.1f}:p=5:r=11")
            else:
                ch.append(f"hqdn3d={1.5 + 6 * a:.1f}:{1.2 + 5 * a:.1f}:{2 + 8 * a:.1f}:{1.5 + 6 * a:.1f}")

        # 3 · colour and picture effects ----------------------------------
        if clip.color:
            ch += color_module.build_filters(clip.color)
        if clip.lut_file:
            ch.append(f"lut3d=file={self.file_opt(clip.lut_file)}:interp=tetrahedral")
        for effect in clip.effects:
            if effect.get("tool") != "rotate":
                ch.append(_effect_fragment(effect))

        # 4 · chroma key / luma key ---------------------------------------
        luma_on = bool(clip.luma and clip.luma.get("on"))
        keyed = bool(clip.chroma and clip.chroma.get("on")) or luma_on
        if luma_on:
            lk = clip.luma
            ch += ["format=yuva420p", f"lumakey=threshold={1.0 if lk['mode'] == 'bright' else 0.0:g}:tolerance={_f(lk['tolerance'])}:softness={_f(lk['softness'])}"]
        if clip.chroma and clip.chroma.get("on"):
            c = clip.chroma
            hexcolor = "0x" + c["color"].lstrip("#")
            red, green, blue = (int(c["color"][i:i + 2], 16) for i in (1, 3, 5))
            ch += ["format=rgba", f"chromakey=color={hexcolor}:similarity={_f(c['similarity'])}:blend={_f(c['blend'])}"]
            if c.get("spill", 0) > 0.01:
                ch.append(f"despill=type={'green' if green >= blue else 'blue'}:mix={_f(c['spill'])}:expand=0.1")

        # 5 · alpha: opacity / fades / crop / mask --------------------------
        fi = clip.fade_in if fades else 0.0
        fo = clip.fade_out if fades else 0.0
        kf = clip.kf
        crop = clip.crop or {}
        need_mask = bool(kf.get("opacity") or any(kf.get(k) for k in ("crop_l", "crop_r", "crop_t", "crop_b"))
                         or crop or clip.mask)
        if need_mask:
            flush()
            cur = self.alpha_mask(clip, cur, bw, bh, off_start, length, fi, fo, keyed)
        else:
            if fi > 0 or fo > 0:
                ch.append("format=rgba" if keyed else "format=yuva420p")
                if fi > 0:
                    ch.append(f"fade=t=in:st=0:d={_q(fi)}:alpha=1")
                if fo > 0:
                    ch.append(f"fade=t=out:st={_q(max(0.0, length - fo))}:d={_q(fo)}:alpha=1")
            if clip.opacity < 1:
                ch.append(f"format={'rgba' if keyed else 'yuva420p'},colorchannelmixer=aa={clip.opacity:.3f}")

        # 6 · into time, then rotate / scale around the centre -------------------
        ch.append(f"setpts=PTS+{_q(at)}/TB")
        tvar = f"(t-{_q(at)}+{_q(off_start)})"
        smax = max(0.05, min(8.0, 3.0 * W / bw, 3.0 * H / bh))
        rot_keys, scale_keys = kf.get("rot"), kf.get("scale")
        if rot_keys or abs(clip.rot) > 1e-6:
            angle = (keyframes.expr(rot_keys, clip.rot, tvar) if rot_keys else _f(clip.rot))
            ch += ["format=rgba", f"rotate=a='({angle})*PI/180':ow='ceil(hypot(iw,ih)/2)*2':oh='ceil(hypot(iw,ih)/2)*2':c=black@0"]
        if scale_keys or abs(clip.scale - 1) > 1e-6:
            if scale_keys:
                clamped = [{**k, "v": min(smax, k["v"])} for k in scale_keys]
                s = keyframes.expr(clamped, min(smax, clip.scale), tvar)
                ch += ["format=rgba", f"scale=w='trunc(iw*({s})/2)*2':h='trunc(ih*({s})/2)*2':eval=frame"]
            else:
                s = _f(min(smax, clip.scale))
                ch += ["format=rgba", f"scale=w='max(2,trunc(iw*{s}/2)*2)':h='max(2,trunc(ih*{s}/2)*2)'"]
        flush()
        return cur

    # ------------------------------------------------------- reframe window
    def reframe_crop(self, clip: Clip, shift: float) -> str:
        """`crop` of the reframe window: constant size, centre = static or keyframed (x/y are evaluated per frame, `t` =
        the frame's time; `shift` turns it into the clip's own timeline time). The browser mirrors this in Compositor.ts."""
        rf = clip.reframe
        var = f"(t+{_q(shift)})"
        cx = keyframes.expr(rf.get("kx"), float(rf.get("cx", 0.5)), var)
        cy = keyframes.expr(rf.get("ky"), float(rf.get("cy", 0.5)), var)
        w, h = float(rf.get("w", 1.0)), float(rf.get("h", 1.0))
        return (f"crop=w='max(2,floor(iw*{_f(w)}/2)*2)':h='max(2,floor(ih*{_f(h)}/2)*2)'"
                f":x='clip(iw*({cx})-ow/2,0,iw-ow)':y='clip(ih*({cy})-oh/2,0,ih-oh)':exact=1")

    # ------------------------------------------------------------ the mask
    def alpha_mask(self, clip: Clip, cur: str, bw: int, bh: int, off_start: float, length: float, fi: float, fo: float,
                   keyed: bool) -> str:
        """Opacity (keyframed), fades, crop and a shape mask as ONE grey video merged into the layer's alpha."""
        kf, crop, mask = clip.kf, clip.crop or {}, clip.mask or {}
        var = f"(T+{_q(off_start)})"
        terms: list[str] = [keyframes.expr(kf.get("opacity"), clip.opacity, var)]
        if fi > 0:
            terms.append(f"clip({var}/{_f(fi)},0,1)")
        if fo > 0:
            terms.append(f"clip(({_q(length)}-{var})/{_f(fo)},0,1)")
        bezier = bool(mask and mask.get("shape") == "bezier" and clip.mask_file)
        shaped = mask if (mask and not bezier and mask.get("shape") != "bezier") else {}
        spatial = bool(crop or shaped or any(kf.get(k) for k in ("crop_l", "crop_r", "crop_t", "crop_b")))
        if spatial:
            sides = {}
            for side, key in (("l", "crop_l"), ("r", "crop_r"), ("t", "crop_t"), ("b", "crop_b")):
                sides[side] = keyframes.expr(kf.get(key), crop.get(side, 0.0), var)
            terms.append(f"gte(X/W,{sides['l']})*lte(X/W,1-({sides['r']}))*gte(Y/H,{sides['t']})*lte(Y/H,1-({sides['b']}))")
        if shaped:
            mask = shaped
            cx, cy, w, h, f = (_f(mask[k]) for k in ("cx", "cy", "w", "h", "feather"))
            if mask.get("kx"):                       # a motion track moves the cut-out: its displacement over time
                cx = f"({cx}+{keyframes.expr(mask['kx'], 0.0, var)})"
            if mask.get("ky"):
                cy = f"({cy}+{keyframes.expr(mask['ky'], 0.0, var)})"
            soft = max(0.001, float(mask["feather"]))
            if mask["shape"] == "ellipse":
                inside = f"clip((1-hypot((X/W-{cx})/({w}/2),(Y/H-{cy})/({h}/2)))/{_f(soft)},0,1)"
            else:
                inside = (f"min(clip(({w}/2-abs(X/W-{cx}))/({w}*{_f(soft)}),0,1),"
                          f"clip(({h}/2-abs(Y/H-{cy}))/({h}*{_f(soft)}),0,1))")
            terms.append(f"(1-{inside})" if mask.get("invert") else inside)
        if spatial:
            mw, mh = max(16, min(MASK_MAX, bw // 2)), max(16, min(MASK_MAX, bh // 2))
        else:
            mw, mh = 8, 8
        m = self.lab("m")
        self.parts.append(
            f"color=c=black:s={mw}x{mh}:r={self.fps}:d={_q(length + 0.2)},format=gray,"
            f"geq=lum='255*clip({'*'.join(terms)},0,1)',scale={bw}:{bh}:flags=bilinear[{m}]"
        )
        if bezier:
            m = self.bezier_mask(clip, m, bw, bh, off_start, length)
        out = self.lab("a")
        if keyed:
            k1, k2, ka, m2 = self.lab("k"), self.lab("k"), self.lab("k"), self.lab("k")
            self.parts.append(f"[{cur}]split[{k1}][{k2}];[{k1}]alphaextract[{ka}];[{ka}][{m}]blend=all_mode=multiply[{m2}];"
                              f"[{k2}][{m2}]alphamerge[{out}]")
        else:
            lay = self.lab("k")
            self.parts.append(f"[{cur}]format=yuva420p[{lay}];[{lay}][{m}]alphamerge[{out}]")
        return out

    def bezier_mask(self, clip: Clip, m: str, bw: int, bh: int, off_start: float, length: float) -> str:
        """Multiply the free-form mask (a grey PNG, moved by the motion track if there is one) into the alpha mask `m`."""
        mask = clip.mask
        idx = self.add_input(clip.mask_file, ["-loop", "1", "-framerate", str(self.fps), "-t", _q(length + 0.3)])
        mb, out = self.lab("mb"), self.lab("mm")
        kx, ky = mask.get("kx"), mask.get("ky")
        if kx or ky:
            var = f"(t+{_q(off_start)})"
            cv, mv = self.lab("cv"), self.lab("mv")
            self.parts.append(f"color=c=black:s={bw}x{bh}:r={self.fps}:d={_q(length + 0.3)},format=yuv420p[{cv}]")
            self.parts.append(f"[{idx}:v]scale={bw}:{bh}:flags=bilinear,format=yuv420p[{mv}]")
            xe = f"x='{bw}*({keyframes.expr(kx, 0.0, var)})'" if kx else "x=0"
            ye = f"y='{bh}*({keyframes.expr(ky, 0.0, var)})'" if ky else "y=0"
            tail = ",negate" if mask.get("invert") else ""
            self.parts.append(f"[{cv}][{mv}]overlay={xe}:{ye}:eof_action=pass,format=gray{tail}[{mb}]")
        else:
            self.parts.append(f"[{idx}:v]scale={bw}:{bh}:flags=bilinear,format=gray[{mb}]")
        self.parts.append(f"[{m}][{mb}]blend=all_mode=multiply[{out}]")
        return out

    # --------------------------------------------------------------- place
    def place(self, current: str, layer: str, clip: Clip, t_from: float, t_to: float, *, at: float, off_start: float, fmt: str = "") -> str:
        W, H = self.W, self.H
        kf = clip.kf
        turned = bool(kf.get("scale") or kf.get("rot") or abs(clip.rot) > 1e-6 or abs(clip.scale - 1) > 1e-6)
        moved = bool(kf.get("px") or kf.get("py") or turned or abs(clip.px) > 1e-6 or abs(clip.py) > 1e-6)
        if moved:
            tvar = f"(t-{_q(at)}+{_q(off_start)})"
            cx = clip.x + clip.width / 2
            cy = clip.y + clip.height / 2
            pxe = keyframes.expr(kf.get("px"), clip.px, tvar)
            pye = keyframes.expr(kf.get("py"), clip.py, tvar)
            xe = f"x='{W}*({_f(cx)}+{pxe})-w/2'"
            ye = f"y='{H}*({_f(cy)}+{pye})-h/2'"
            if clip.anchor and turned:
                # rotating / scaling about the anchor a (pixels from the box centre) = about the centre + moving the centre by  a − s·R(θ)·a
                ax, ay = clip.anchor["x"] * _even(W * clip.width), clip.anchor["y"] * _even(H * clip.height)
                ang = f"(({keyframes.expr(kf.get('rot'), clip.rot, tvar)})*PI/180)"
                sc = f"({keyframes.expr(kf.get('scale'), clip.scale, tvar)})"
                xe = f"x='{W}*({_f(cx)}+{pxe})-w/2+({_f(ax)})-{sc}*(({_f(ax)})*cos{ang}-({_f(ay)})*sin{ang})'"
                ye = f"y='{H}*({_f(cy)}+{pye})-h/2+({_f(ay)})-{sc}*(({_f(ax)})*sin{ang}+({_f(ay)})*cos{ang})'"
        else:
            xe, ye = f"x={int(W * clip.x)}", f"y={int(H * clip.y)}"
        enable = f"enable='between(t,{_q(t_from)},{_q(t_to)})'"
        out = self.lab("v")
        fmt = fmt or (":format=auto" if self.alpha else "")
        if clip.blend == "normal" or clip.blend not in _BLEND:
            self.parts.append(f"[{current}][{layer}]overlay={xe}:{ye}:{enable}:eof_action=pass{fmt}[{out}]")
            return out
        neutral, mode = _BLEND[clip.blend]
        canvas, full, a, b = self.lab("n"), self.lab("f"), self.lab("g"), self.lab("h")
        self.parts.append(f"color=c={neutral}:s={self.W}x{self.H}:r={self.fps}:d={max(0.1, self.tl.length):.3f}[{canvas}]")
        self.parts.append(f"[{canvas}][{layer}]overlay={xe}:{ye}:{enable}:eof_action=pass[{full}]")
        self.parts.append(f"[{current}]format=gbrp[{a}];[{full}]format=gbrp[{b}]")
        self.parts.append(f"[{a}][{b}]blend=all_mode={mode}:{enable},format=yuv420p[{out}]")
        return out

    # --------------------------------------------------------- transitions
    def transition_window(self, A: Clip, B: Clip, d: float, name: str, current: str) -> str:
        """Both clips into `[cut - d/2, cut + d/2]` on black, `xfade` them, lay the result over the track."""
        half, cut = d / 2, B.at
        W, H, fps = self.W, self.H, self.fps
        pieces = []
        for clip, side in ((A, "out"), (B, "in")):
            simple = clip.kind in ("video", "image") and not clip.freeze and not clip.ramp and not clip.segs and not clip.reverse
            v = clip.speed or 1.0
            if clip.kind == "image":
                segs, pad_head, pad_tail, off = [(0.0, d, 1.0)], 0.0, 0.0, 0.0
                piece_len = d
                off = (clip.length - half) if side == "out" else -half
            elif simple:
                have_after = max(0.0, clip.src_len - clip.end) if clip.src_len else 0.0
                have_before = max(0.0, clip.start)
                if side == "out":
                    a0, a1 = clip.end - half * v, clip.end + min(half * v, have_after)
                    got = (a1 - a0) / v
                    segs, pad_head, pad_tail = [(a0, a1, v)], 0.0, max(0.0, d - got)
                    off = clip.length - half
                else:
                    b0, b1 = clip.start - min(half * v, have_before), clip.start + half * v
                    got = (b1 - b0) / v
                    segs, pad_head, pad_tail = [(b0, b1, v)], max(0.0, d - got), 0.0
                    off = -half
                piece_len = d
            else:
                # ramped / reversed / frozen: only what the clip itself plays, the rest is held
                L = clip.length
                x0, x1 = (L - half, L) if side == "out" else (0.0, half)
                if clip.reverse:
                    x0, x1 = L - x1, L - x0
                segs = cut_segments(clip.segments(), x0, x1) or [(clip.start, clip.start + 0.04, 1.0)]
                got = half
                pad_head, pad_tail = (0.0, d - got) if side == "out" else (d - got, 0.0)
                off = (clip.length - half) if side == "out" else 0.0
                piece_len = half
            pieces.append((clip, segs, pad_head, pad_tail, off, piece_len))
        labels = []
        for clip, segs, pad_head, pad_tail, off, piece_len in pieces:
            nested_src = None
            if clip.nested is not None:
                idx, seek, nested_src = None, 0.0, self.nested_video(clip)
            elif clip.kind == "image":
                args = ["-loop", "1", "-framerate", str(fps), "-t", _q(d + 0.6)]
                idx = self.add_input(clip.source, args)
                seek = 0.0
            else:
                args, seek = self.input_args_for(clip, segs)
                idx = self.add_input(clip.source, args)
            piece = self.layer(clip, idx, seek, segs, clip.reverse, at=0.0, off_start=off, length=piece_len, fades=False,
                               pad_head=pad_head, pad_tail=pad_tail, src=nested_src)
            canvas, out = self.lab("w"), self.lab("o")
            self.parts.append(f"color=c=black:s={W}x{H}:r={fps}:d={_q(d + 0.1)}[{canvas}]")
            vs, ve = 0.0, d + 0.1
            placed = self.place(canvas, piece, clip, vs, ve, at=0.0, off_start=off)
            self.parts.append(f"[{placed}]trim=duration={_q(d)},setpts=PTS-STARTPTS,format=yuv420p[{out}]")
            labels.append(out)
        x, shifted, out = self.lab("x"), self.lab("y"), self.lab("v")
        if name == "morphcut" and self.flow:
            # an approximation of a morph cut: the first half of the window from the outgoing clip, the second half from the incoming one,
            # joined, thinned to a third of the frame rate and re-interpolated with optical flow — the frames around the join are then SYNTHESISED
            # (motion-compensated) instead of jumping
            h0, h1 = self.lab("m"), self.lab("m")
            low = max(6, int(fps // 3))
            self.parts.append(f"[{labels[0]}]trim=duration={_q(d / 2)},setpts=PTS-STARTPTS[{h0}]")
            self.parts.append(f"[{labels[1]}]trim=start={_q(d / 2)}:duration={_q(d / 2)},setpts=PTS-STARTPTS[{h1}]")
            self.parts.append(f"[{h0}][{h1}]concat=n=2:v=1:a=0,fps={low},minterpolate=fps={fps}:mi_mode=mci:mc_mode=aobmc:me_mode=bidir:vsbmc=1,format=yuv420p[{x}]")
        else:
            if name == "morphcut":
                name = "fade"
                self.notes.append("برشِ مورف در پیش‌نویسِ سریعِ روی سایت به محو تبدیل می‌شود؛ در خروجیِ نهایی هست.")
            self.parts.append(f"[{labels[0]}][{labels[1]}]xfade=transition={name}:duration={_q(d)}:offset=0[{x}]")
        self.parts.append(f"[{x}]setpts=PTS+{_q(cut - half)}/TB[{shifted}]")
        self.parts.append(f"[{current}][{shifted}]overlay=x=0:y=0:enable='between(t,{_q(cut - half)},{_q(cut + half)})':eof_action=pass[{out}]")
        return out

    # ---------------------------------------------------------------- text
    def text_track(self, track: Track, current: str) -> str:
        from . import titles

        items = [c.style() for c in sorted(track.clips, key=lambda c: c.at) if isinstance(c, TextClip)]
        if not items:
            return current
        token = FILE_TOKEN.format(n=len(self.texts))
        self.texts[token] = titles.build_ass(items, self.W, self.H)
        out = self.lab("v")
        self.parts.append(f"[{current}]{titles.ass_filter(token, portable=self.portable)}[{out}]")
        return out


def build_graph(timeline: Timeline, *, spans=None, need_base: bool = True, portable: bool = False, video: bool = True, audio: bool = True, flow: bool = True,
                alpha: bool = False) -> Graph:
    """The whole filtergraph plus what `export.render` needs to run it.
    `video=False` / `audio=False` build only the other half (used by the sliced render: the picture in time slices, the sound once)."""
    from . import audiofx

    timeline.validate(need_base=need_base)
    b = Builder(timeline, spans=spans, portable=portable, flow=flow, alpha=alpha)
    if video:
        b.build_video()
    else:
        for track in timeline.tracks:                  # the half-transition dips of the sound are decided while the picture is planned
            if track.kind == "video" and not track.hidden:
                b.plan_transitions(track)
    has_audio = audiofx.build_audio(b) if audio else False
    return Graph(b.inputs, b.args, ";".join(b.parts), b.texts, has_audio, timeline.length, b.notes, b.assets)
