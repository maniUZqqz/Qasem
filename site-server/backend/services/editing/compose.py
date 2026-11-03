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
"""
from __future__ import annotations

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


def _q(x: float) -> str:
    return f"{x:.3f}"


def _even(x: float) -> int:
    return max(2, int(x) // 2 * 2)


class Builder:
    def __init__(self, timeline: Timeline, *, spans=None):
        self.tl = timeline
        self.W, self.H, self.fps = timeline.width, timeline.height, timeline.fps
        self.inputs: list[str] = []
        self.args: list[list[str]] = []
        self.parts: list[str] = []
        self.n = 0
        self.texts: dict[str, str] = {}
        self.main_input: dict[int, int] = {}
        self.seeks: dict[int, float] = {}
        self.notes: list[str] = []
        self.spans = spans                      # callable(path) -> [[s, e], …] for ducking (None ⇒ media_cache)
        self.vis: dict[int, tuple[float, float]] = {}
        self.audio_fade_in: dict[int, float] = {}
        self.audio_fade_out: dict[int, float] = {}

    # ------------------------------------------------------------ plumbing
    def lab(self, prefix: str = "x") -> str:
        self.n += 1
        return f"{prefix}{self.n}"

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
    def build_video(self) -> str:
        tl = self.tl
        length = max(0.1, tl.length)
        self.parts.append(f"color=c=black:s={self.W}x{self.H}:r={self.fps}:d={length:.3f}[base]")
        current = "base"
        for track in tl.tracks:
            if track.kind == "video" and not track.hidden:
                current = self.video_track(track, current)
            elif track.kind == "text":
                current = self.text_track(track, current)
        self.parts.append(f"[{current}]null[vout]")
        return "vout"

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
            idx, seek = self.main_input_for(clip)
            layer = self.layer(clip, idx, seek, clip.segments(), clip.reverse, at=clip.at, off_start=0.0, length=clip.length)
            current = self.place(current, layer, clip, vs, ve, at=clip.at, off_start=0.0)
        for earlier, later, d, name in pairs:
            current = self.transition_window(earlier, later, d, name, current)
        return current

    # ---------------------------------------------------------------- layer
    def layer(self, clip: Clip, idx: int, seek: float, segs: list, reverse: bool, *, at: float, off_start: float,
              length: float, fades: bool = True, pad_head: float = 0.0, pad_tail: float = 0.0) -> str:
        """The finished layer stream of one clip (or one piece of it): all of the per-clip filters, positioned in time."""
        W, H, fps = self.W, self.H, self.fps
        cur = f"{idx}:v"
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
            ch.append(f"fps={fps}")

        # 2 · orientation, fit --------------------------------------------
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

        # 3 · colour and picture effects ----------------------------------
        if clip.color:
            ch += color_module.build_filters(clip.color)
        for effect in clip.effects:
            if effect.get("tool") != "rotate":
                ch.append(_effect_fragment(effect))

        # 4 · chroma key --------------------------------------------------
        keyed = bool(clip.chroma and clip.chroma.get("on"))
        if keyed:
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
        spatial = bool(crop or mask or any(kf.get(k) for k in ("crop_l", "crop_r", "crop_t", "crop_b")))
        if spatial:
            sides = {}
            for side, key in (("l", "crop_l"), ("r", "crop_r"), ("t", "crop_t"), ("b", "crop_b")):
                sides[side] = keyframes.expr(kf.get(key), crop.get(side, 0.0), var)
            terms.append(f"gte(X/W,{sides['l']})*lte(X/W,1-({sides['r']}))*gte(Y/H,{sides['t']})*lte(Y/H,1-({sides['b']}))")
        if mask:
            cx, cy, w, h, f = (_f(mask[k]) for k in ("cx", "cy", "w", "h", "feather"))
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
        out = self.lab("a")
        if keyed:
            k1, k2, ka, m2 = self.lab("k"), self.lab("k"), self.lab("k"), self.lab("k")
            self.parts.append(f"[{cur}]split[{k1}][{k2}];[{k1}]alphaextract[{ka}];[{ka}][{m}]blend=all_mode=multiply[{m2}];"
                              f"[{k2}][{m2}]alphamerge[{out}]")
        else:
            lay = self.lab("k")
            self.parts.append(f"[{cur}]format=yuva420p[{lay}];[{lay}][{m}]alphamerge[{out}]")
        return out

    # --------------------------------------------------------------- place
    def place(self, current: str, layer: str, clip: Clip, t_from: float, t_to: float, *, at: float, off_start: float) -> str:
        W, H = self.W, self.H
        kf = clip.kf
        moved = bool(kf.get("px") or kf.get("py") or kf.get("scale") or kf.get("rot") or abs(clip.px) > 1e-6
                     or abs(clip.py) > 1e-6 or abs(clip.rot) > 1e-6 or abs(clip.scale - 1) > 1e-6)
        if moved:
            tvar = f"(t-{_q(at)}+{_q(off_start)})"
            cx = clip.x + clip.width / 2
            cy = clip.y + clip.height / 2
            pxe = keyframes.expr(kf.get("px"), clip.px, tvar)
            pye = keyframes.expr(kf.get("py"), clip.py, tvar)
            xe = f"x='{W}*({_f(cx)}+{pxe})-w/2'"
            ye = f"y='{H}*({_f(cy)}+{pye})-h/2'"
        else:
            xe, ye = f"x={int(W * clip.x)}", f"y={int(H * clip.y)}"
        enable = f"enable='between(t,{_q(t_from)},{_q(t_to)})'"
        out = self.lab("v")
        if clip.blend == "normal" or clip.blend not in _BLEND:
            self.parts.append(f"[{current}][{layer}]overlay={xe}:{ye}:{enable}:eof_action=pass[{out}]")
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
            if clip.kind == "image":
                args = ["-loop", "1", "-framerate", str(fps), "-t", _q(d + 0.6)]
                idx = self.add_input(clip.source, args)
                seek = 0.0
            else:
                args, seek = self.input_args_for(clip, segs)
                idx = self.add_input(clip.source, args)
            piece = self.layer(clip, idx, seek, segs, clip.reverse, at=0.0, off_start=off, length=piece_len, fades=False,
                               pad_head=pad_head, pad_tail=pad_tail)
            canvas, out = self.lab("w"), self.lab("o")
            self.parts.append(f"color=c=black:s={W}x{H}:r={fps}:d={_q(d + 0.1)}[{canvas}]")
            vs, ve = 0.0, d + 0.1
            placed = self.place(canvas, piece, clip, vs, ve, at=0.0, off_start=off)
            self.parts.append(f"[{placed}]trim=duration={_q(d)},setpts=PTS-STARTPTS,format=yuv420p[{out}]")
            labels.append(out)
        x, shifted, out = self.lab("x"), self.lab("y"), self.lab("v")
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
        self.parts.append(f"[{current}]{titles.ass_filter(token)}[{out}]")
        return out


def build_graph(timeline: Timeline, *, spans=None, need_base: bool = True) -> Graph:
    """The whole filtergraph plus what `export.render` needs to run it."""
    from . import audiofx

    timeline.validate(need_base=need_base)
    b = Builder(timeline, spans=spans)
    b.build_video()
    has_audio = audiofx.build_audio(b)
    return Graph(b.inputs, b.args, ";".join(b.parts), b.texts, has_audio, timeline.length, b.notes)
