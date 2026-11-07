"""Multi-track timeline and proxy editing. §23.4

The EDL in `edl.py` describes one operation applied to one source. That is the
right shape for «کوتاهش کن، روشنش کن» and the wrong shape the moment a shop
wants two clips side by side, a logo in the corner for the last five seconds,
and music under all of it. This is that second shape.

**A timeline is tracks, and a track is clips on a clock.** This module is the
DATA (what the panel's JSON becomes, validated and clamped); `compose.py` turns
it into one ffmpeg filtergraph and `export.py` runs it. Keeping the description
separate from the execution is what lets the panel show a shop what will
happen before a single frame is encoded — the same reason `plan` and `apply`
are separate endpoints.

**Proxy editing exists because of what a shop's phone produces.** A three-minute
4K clip is gigabytes, and every preview render of it costs minutes the shop
spends watching a spinner. So: build a small proxy once, do all the deciding
against that, and apply the finished decisions to the original at export.

The trap in proxy workflows is that the proxy and the original disagree about
time. If the proxy is a different frame rate, a cut at 12.40 seconds lands on a
different frame in each — and the exported video is subtly wrong in a way that
only shows up on the final render, after the shop approved something else.
`PROXY_FPS` is therefore **not** set: the proxy keeps the source's timebase and
only loses resolution.

**What the panel's «دستی» workspace adds on top (Premiere/CapCut-style):** a clip can carry its own sound
(`has_audio`, `volume`, fades, EQ, pan), a speed (or a keyframed speed ramp, reverse, freeze), a fit, picture effects
and a Lumetri-style colour block, keyframed position/scale/rotation/opacity/crop/volume, chroma key, blend mode, a
mask, a transition into it (xfade library), and a track can hold titles/captions (`TextClip`, rendered by libass).
Stills are clips too (`kind="image"`); so are shapes and stickers (a drawn PNG, `shapes.py`). A clip can carry a 3D LUT,
a free-form mask (`masks.py`), a background-removal matte (`matte`), and can be a whole **nested sequence**
(`ref="seq:<id>"`, built recursively here and inlined into the parent's graph by `compose.py`). `from_project` turns the panel's JSON into a Timeline, resolving every `ref`
through a callback — the browser never names a file path.
"""
from __future__ import annotations

import copy
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

from . import color as color_module
from . import keyframes, luts, masks, shapes
from .errors import TimelineError

logger = logging.getLogger(__name__)

__all__ = ["TimelineError"]

#: Small enough to render in seconds, large enough to judge framing and read
#: any text burnt into the picture.
PROXY_HEIGHT = 480

#: Proxies are disposable; this is about not spending minutes making one.
PROXY_CRF = 30
PROXY_PRESET = "veryfast"

#: More than this and the filtergraph takes longer to assemble than the render
#: it describes, and nobody is hand-building a 40-track edit in this panel.
MAX_TRACKS = 12
MAX_CLIPS = 120
#: sequences inside sequences (a nested clip's own timeline may hold nested clips, up to this deep)
MAX_NEST = 3

FITS = ("stretch", "cover", "contain")
TRACK_KINDS = ("video", "audio", "text")
ROLES = ("", "speech", "music", "sfx")
TEXT_POSITIONS = ("top", "middle", "bottom")
BLENDS = ("normal", "multiply", "screen", "overlay", "add", "softlight", "lighten", "darken", "difference")
EQ_PRESETS = ("flat", "voice", "bright", "warm", "phone", "bass_cut", "bass_boost", "deess")
MASK_SHAPES = ("none", "rect", "ellipse", "bezier")

#: Legacy transition kinds ("fade" = dip to black, "crossfade" = dissolve) + the xfade library.
LEGACY_TRANSITIONS = ("fade", "crossfade")

#: Picture tools that make sense on ONE clip (the rest — cut, trim_silence, zoom, fade, transition, stabilize,
#: crop_format, denoise_audio, normalize_audio, subtitle, speed, watermark — act on the whole program or are native
#: clip properties; see `PROGRAM_TOOLS`).
CLIP_EFFECT_TOOLS = ("brightness", "contrast", "saturation", "white_balance", "deflicker", "sharpen", "vignette",
                     "blur_region", "rotate")

#: keyframe channels → (min, max)
KF_CHANNELS = {
    "px": (-2.0, 2.0), "py": (-2.0, 2.0), "scale": (0.05, 8.0), "rot": (-720.0, 720.0), "opacity": (0.0, 1.0),
    "volume": (0.0, 3.0), "crop_l": (0.0, 0.95), "crop_r": (0.0, 0.95), "crop_t": (0.0, 0.95), "crop_b": (0.0, 0.95),
}

#: a speed ramp is played as this many constant-speed steps (the browser mirrors it, so lengths agree to the frame)
RAMP_STEPS = 16

_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")


def transitions_all() -> tuple[str, ...]:
    from . import transitions

    return LEGACY_TRANSITIONS + tuple(transitions.XFADE)


# ----------------------------------------------------------------- speed ramp


def ramp_speeds(ramp: list[dict]) -> list[float]:
    """The speed of each of the RAMP_STEPS equal slices of the used source range (linear between keys, clamped)."""
    keys = sorted(({"p": float(k["p"]), "v": float(k["v"])} for k in ramp), key=lambda k: k["p"])
    out = []
    for i in range(RAMP_STEPS):
        p = (i + 0.5) / RAMP_STEPS
        if p <= keys[0]["p"]:
            v = keys[0]["v"]
        elif p >= keys[-1]["p"]:
            v = keys[-1]["v"]
        else:
            v = keys[-1]["v"]
            for a, b in zip(keys, keys[1:]):
                if a["p"] <= p <= b["p"]:
                    u = (p - a["p"]) / max(1e-9, b["p"] - a["p"])
                    v = a["v"] + (b["v"] - a["v"]) * u
                    break
        out.append(max(0.1, min(8.0, v)))
    return out


def cut_segments(segs: list[tuple[float, float, float]], x0: float, x1: float) -> list[tuple[float, float, float]]:
    """The part of a (source-order) segment list that plays between timeline seconds x0 and x1 (of the un-reversed run)."""
    out, cum = [], 0.0
    for a, b, v in segs:
        dur = (b - a) / v
        lo, hi = max(x0, cum), min(x1, cum + dur)
        if hi - lo > 1e-4:
            out.append((a + (lo - cum) * v, a + (hi - cum) * v, v))
        cum += dur
    return out


@dataclass
class Clip:
    """One piece of source material, and where it sits on the timeline."""

    source: str
    #: Where it lands in the finished video.
    at: float
    #: Which part of the SOURCE file is used — in-point and out-point, not
    #: positions on the timeline. A clip placed `at=10` using `start=0,end=13`
    #: of its source therefore ends at 23 seconds, not 13. Every NLE works this
    #: way and everybody gets it wrong once; the test named after it says so.
    start: float = 0.0
    end: float | None = None
    #: 0 = fully transparent, 1 = opaque. Only meaningful above the base track.
    opacity: float = 1.0
    #: Fractions of the frame. The default covers it.
    x: float = 0.0
    y: float = 0.0
    width: float = 1.0
    height: float = 1.0
    label: str = ""
    #: "video" | "image" (a still, looped for `end - start` seconds) | "audio"
    kind: str = "video"
    #: The source has a sound track and this clip should play it (video clips; audio clips always do).
    has_audio: bool = False
    #: Loudness multiplier of this clip's own sound.
    volume: float = 1.0
    #: Playback rate; the clip's length on the timeline is `source_length / speed`.
    speed: float = 1.0
    fit: str = "stretch"
    fade_in: float = 0.0
    fade_out: float = 0.0
    #: Validated picture effects (tools.Operation-style dicts: {"tool", "params"}).
    effects: list = field(default_factory=list)
    #: How this clip comes in from the previous one on its track: {"kind": …, "duration": s}.
    transition: dict | None = None
    #: Seconds the previous clip is held on its last frame under a crossfade (legacy; the xfade path uses handles).
    hold: float = 0.0
    # ---- the "pro" fields (all optional; the defaults are a plain clip)
    rot: float = 0.0
    scale: float = 1.0
    px: float = 0.0
    py: float = 0.0
    flip_h: bool = False
    flip_v: bool = False
    blend: str = "normal"
    crop: dict = field(default_factory=dict)
    mask: dict = field(default_factory=dict)
    kf: dict = field(default_factory=dict)
    chroma: dict = field(default_factory=dict)
    color: dict = field(default_factory=dict)
    ramp: list = field(default_factory=list)
    reverse: bool = False
    freeze: bool = False
    link: str = ""
    audio: dict = field(default_factory=dict)
    #: «بازتنظیمِ قاب»: a window INSIDE the source picture, cut before the fit step (quality comes from the original file):
    #: {"w","h"} = its size, {"cx","cy"} = its centre (fractions of the source), optional {"kx","ky"} keyframes of the centre.
    reframe: dict = field(default_factory=dict)
    #: Explicit (source_a, source_b, speed) list — set by `window()` when a ramp clip is cut; wins over `ramp`.
    segs: list | None = None
    #: Length of the whole source file (0 = unknown) — how much footage exists beyond the in/out points (handles).
    src_len: float = 0.0
    #: Pixel size of the source picture (0 = unknown) — a matte video is scaled to it.
    src_w: int = 0
    src_h: int = 0
    #: A (possibly blended) .cube handed to `lut3d`, after the colour block.
    lut_file: str = ""
    #: The grey PNG of a free-form mask, and the matte (background removal) video + the source second it starts at.
    mask_file: str = ""
    matte_file: str = ""
    matte_s0: float = 0.0
    #: A nested sequence: this clip's picture and sound are that timeline's (its time = the nested timeline's time).
    nested: object = None
    #: «لایهٔ تنظیم»: no picture of its own — its colour/effects apply to everything BELOW it on the other video tracks, for its duration.
    adjust: bool = False
    #: «کلیدِ روشنایی»: {on, mode: dark|bright, tolerance, softness} → `lumakey`.   «اصلاحِ لنز»: {k1, k2} → `lenscorrection`.
    luma: dict = field(default_factory=dict)
    #: «نقطهٔ لنگر»: {x, y} = the pivot of rotation and scale, as a fraction of the clip's box measured from its centre (0, 0 = the centre).
    anchor: dict = field(default_factory=dict)
    #: «Track matte»: this clip is seen only through the clip that overlaps it on the NEXT video track up (that clip is not shown itself).
    #: {mode: luma|alpha, invert}. luma = brightness of the upper clip is the opacity of this one; alpha = its transparency is.
    track_matte: dict = field(default_factory=dict)
    lens: dict = field(default_factory=dict)

    @property
    def source_length(self) -> float:
        return (self.end - self.start) if self.end is not None else 0.0

    def segments(self) -> list[tuple[float, float, float]]:
        """Source-order (a, b, speed) pieces that make up the clip (one piece unless it is ramped)."""
        if self.end is None:
            return []
        if self.segs:
            return [tuple(s) for s in self.segs]
        if self.ramp and len(self.ramp) >= 2 and self.kind != "image" and not self.freeze:
            speeds = ramp_speeds(self.ramp)
            n = len(speeds)
            span = (self.end - self.start) / n
            return [(self.start + i * span, self.start + (i + 1) * span, v) for i, v in enumerate(speeds)]
        return [(self.start, self.end, self.speed or 1.0)]

    @property
    def length(self) -> float:
        if self.freeze or self.kind == "image":
            return max(0.0, self.source_length)
        if self.segs or self.ramp:
            return sum((b - a) / v for a, b, v in self.segments())
        return self.source_length / (self.speed or 1.0)

    @property
    def ends_at(self) -> float:
        return self.at + self.length

    @property
    def animated(self) -> bool:
        return any(self.kf.get(k) for k in ("px", "py", "scale", "rot"))

    def validate(self, index: int) -> None:
        where = self.label or f"قطعه‌ی {index + 1}"
        if self.at < 0:
            raise TimelineError(f"{where}: زمان شروع منفی است.")
        if self.end is not None and self.end <= self.start:
            raise TimelineError(
                f"{where}: پایان ({self.end:g}) قبل از شروع ({self.start:g}) است."
            )
        if self.kind == "image" and self.end is None:
            raise TimelineError(f"{where}: برای عکس باید مدتِ نمایش مشخص باشد.")
        if self.nested is not None and self.end is None:
            raise TimelineError(f"{where}: توالیِ تودرتو مدت ندارد (خالی است).")
        if not 0 <= self.opacity <= 1:
            raise TimelineError(f"{where}: شفافیت باید بین ۰ و ۱ باشد.")
        for name, value in (("x", self.x), ("y", self.y)):
            if not 0 <= value <= 1:
                raise TimelineError(f"{where}: {name} باید بین ۰ و ۱ باشد.")
        if not 0 < self.width <= 1 or not 0 < self.height <= 1:
            raise TimelineError(f"{where}: اندازه باید بین ۰ و ۱ باشد.")
        if self.x + self.width > 1.001 or self.y + self.height > 1.001:
            raise TimelineError(f"{where}: از لبه‌ی کادر بیرون می‌زند.")
        if not self.segs and not self.ramp and not 0.25 <= self.speed <= 4:
            raise TimelineError(f"{where}: سرعت باید بین ۰٫۲۵ و ۴ برابر باشد.")
        if not 0 <= self.volume <= 3:
            raise TimelineError(f"{where}: بلندی صدا باید بین ۰ و ۳ برابر باشد.")
        if self.fit not in FITS:
            raise TimelineError(f"{where}: روش جا دادن باید یکی از {'، '.join(FITS)} باشد.")
        if self.blend not in BLENDS:
            raise TimelineError(f"{where}: حالتِ ترکیب نامعتبر است.")
        if self.fade_in < 0 or self.fade_out < 0 or self.fade_in + self.fade_out > max(self.length, 0.01) + 0.001:
            raise TimelineError(f"{where}: محو شدنِ ابتدا و انتها از طولِ قطعه بیشتر است.")


@dataclass
class TextClip:
    """A title / caption for a while. Lives on a track of kind "text"; rendered by libass (`titles.py`)."""

    text: str
    at: float
    duration: float
    position: str = "bottom"
    #: Percent of the frame height.
    size: float = 6.0
    color: str = "#ffffff"
    box: bool = True
    opacity: float = 1.0
    label: str = ""
    kind: str = "text"
    source: str = ""
    start: float = 0.0
    #: The cleaned `titles.clean` dict (None ⇒ built from the fields above on demand).
    spec: dict | None = None

    @property
    def end(self) -> float:
        return self.duration

    @property
    def source_length(self) -> float:
        return self.duration

    @property
    def length(self) -> float:
        return self.duration

    @property
    def ends_at(self) -> float:
        return self.at + self.duration

    def style(self) -> dict:
        """The cleaned titles dict for this clip, with the CURRENT at/duration."""
        from . import titles

        if self.spec is not None:
            return {**self.spec, "at": self.at, "duration": self.duration}
        return titles.clean({
            "text": self.text, "at": self.at, "duration": self.duration, "position": self.position, "size": self.size,
            "color": self.color, "box": self.box, "opacity": self.opacity, "label": self.label,
        })

    def validate(self, index: int) -> None:
        where = self.label or f"متن {index + 1}"
        if self.at < 0 or self.duration <= 0:
            raise TimelineError(f"{where}: زمان یا مدتِ متن درست نیست.")
        if not (self.text or "").strip() and not ((self.spec or {}).get("text2") or "").strip():
            raise TimelineError(f"{where}: متن خالی است.")
        if self.position not in TEXT_POSITIONS:
            raise TimelineError(f"{where}: جای متن باید یکی از {'، '.join(TEXT_POSITIONS)} باشد.")
        if not _HEX.match(self.color):
            raise TimelineError(f"{where}: رنگِ متن باید مثل #ffffff باشد.")


@dataclass
class Track:
    """Clips that share a layer. Higher index draws on top."""

    kind: str = "video"          # "video", "audio" or "text"
    name: str = ""
    clips: list = field(default_factory=list)
    muted: bool = False
    hidden: bool = False
    solo: bool = False
    gain_db: float = 0.0
    pan: float = 0.0
    role: str = ""
    caption: bool = False

    @property
    def length(self) -> float:
        return max((c.ends_at for c in self.clips), default=0.0)

    def overlaps(self) -> list[tuple[Clip, Clip]]:
        """Clips on one track that occupy the same moment.

        A track is a single layer, so two clips at once is not a rich edit —
        it is an arrangement with no defined answer, and rendering it silently
        picks one.
        """
        found = []
        ordered = sorted(self.clips, key=lambda c: c.at)
        for earlier, later in zip(ordered, ordered[1:]):
            if later.at < earlier.ends_at - 0.001:
                found.append((earlier, later))
        return found


@dataclass
class Timeline:
    tracks: list[Track] = field(default_factory=list)
    width: int = 1080
    height: int = 1920
    fps: int = 30
    markers: list = field(default_factory=list)
    inout: dict | None = None
    master: dict = field(default_factory=lambda: {"gain_db": 0.0, "limiter": True})
    ducking: dict = field(default_factory=lambda: {"on": False, "amount_db": 12.0, "threshold": 0.04,
                                                    "attack_ms": 40.0, "release_ms": 500.0})
    export: dict = field(default_factory=dict)

    @property
    def length(self) -> float:
        return max((t.length for t in self.tracks), default=0.0)

    @property
    def clip_count(self) -> int:
        n = 0
        for t in self.tracks:
            for c in t.clips:
                n += 1 + (getattr(c, "nested", None).clip_count if getattr(c, "nested", None) is not None else 0)
        return n

    def validate(self, *, need_base: bool = True) -> None:
        if not self.tracks:
            raise TimelineError("تایم‌لاین خالی است.")
        if len(self.tracks) > MAX_TRACKS:
            raise TimelineError(f"حداکثر {MAX_TRACKS} ترک.")
        if self.clip_count > MAX_CLIPS:
            raise TimelineError(f"حداکثر {MAX_CLIPS} قطعه در کل تایم‌لاین.")

        video_tracks = [t for t in self.tracks if t.kind == "video"]
        if not video_tracks:
            raise TimelineError("حداقل یک ترک تصویر لازم است.")
        if need_base and not video_tracks[0].clips:
            raise TimelineError("ترک اصلی تصویر هیچ قطعه‌ای ندارد.")

        for track in self.tracks:
            for index, clip in enumerate(track.clips):
                clip.validate(index)
                if getattr(clip, "nested", None) is not None:
                    clip.nested.validate(need_base=False)
            clashes = track.overlaps()
            if clashes:
                first, second = clashes[0]
                raise TimelineError(
                    f"در ترک «{track.name or track.kind}» دو قطعه هم‌زمان‌اند "
                    f"({first.label or 'قطعه'} تا {first.ends_at:.1f} و "
                    f"{second.label or 'قطعه'} از {second.at:.1f}). "
                    "یکی را جابه‌جا کنید یا ترک تازه بسازید."
                )
        self._check_reverse()

    def _check_reverse(self) -> None:
        """`reverse` buffers every frame in memory: bound it by what a 3 GB server can hold."""
        budget = 600e6
        for track in self.tracks:
            for clip in track.clips:
                if getattr(clip, "reverse", False) and clip.kind == "video":
                    bw, bh = max(2, int(self.width * clip.width)), max(2, int(self.height * clip.height))
                    frames = clip.length * self.fps
                    if frames * bw * bh * 1.5 > budget:
                        most = budget / (bw * bh * 1.5 * self.fps)
                        raise TimelineError(
                            f"«{clip.label or 'قطعه'}»: برای وارونه‌کردن در این اندازه‌ی قاب حداکثر "
                            f"{most:.0f} ثانیه جا دارد؛ قطعه را کوتاه‌تر کنید."
                        )

    def gaps(self) -> list[tuple[float, float]]:
        """Moments the base video track shows nothing.

        Reported rather than filled: black is a legitimate choice and so is
        holding the last frame, and guessing which one the shop meant produces
        a video they did not ask for.
        """
        base = next((t for t in self.tracks if t.kind == "video"), None)
        if base is None or not base.clips:
            return []
        holes, cursor = [], 0.0
        for clip in sorted(base.clips, key=lambda c: c.at):
            if clip.at > cursor + 0.04:      # about one frame at 25fps
                holes.append((cursor, clip.at))
            cursor = max(cursor, clip.ends_at)
        return holes

    def as_dict(self) -> dict:
        def one(c):
            if c.kind == "text":
                return {"text": c.text, "at": round(c.at, 2), "duration": round(c.duration, 2), "label": c.label,
                        "kind": "text"}
            return {
                "source": c.source, "at": round(c.at, 2),
                "start": round(c.start, 2),
                "end": round(c.end, 2) if c.end is not None else None,
                "opacity": c.opacity, "label": c.label,
                "x": c.x, "y": c.y,
                "width": c.width, "height": c.height,
                "kind": c.kind, "speed": c.speed, "volume": c.volume,
            }

        return {
            "tracks": [
                {"kind": t.kind, "name": t.name, "muted": t.muted, "clips": [one(c) for c in t.clips]}
                for t in self.tracks
            ],
            "length": round(self.length, 2),
            "clips": self.clip_count,
            "size": f"{self.width}x{self.height}",
            "fps": self.fps,
            "gaps": [
                {"start": round(a, 2), "end": round(b, 2)} for a, b in self.gaps()
            ],
        }


# -------------------------------------------------------------------- helpers

def _f(value) -> str:
    return f"{float(value):.4f}".rstrip("0").rstrip(".") or "0"


def _atempo(factor: float) -> str:
    """atempo takes 0.5–2 per instance; chain for anything outside."""
    parts, f = [], float(factor)
    while f > 2.0 + 1e-9:
        parts.append("atempo=2")
        f /= 2.0
    while f < 0.5 - 1e-9:
        parts.append("atempo=0.5")
        f /= 0.5
    parts.append(f"atempo={_f(f)}")
    return ",".join(parts)


def wrap_text(text: str, frame_width: int, frame_height: int, size_pct: float) -> str:
    """Kept for callers of the old drawtext path: break a long line at spaces so each fits ~88 % of the frame width.
    (Titles are laid out by libass now; this is no longer used by the renderer.)"""
    font_px = max(8.0, frame_height * max(1.0, min(20.0, size_pct)) / 100)
    limit = max(6, int(frame_width * 0.88 / (font_px * 0.5)))
    out: list[str] = []
    for paragraph in str(text).replace("\r", "").split("\n"):
        line = ""
        for word in paragraph.split():
            trial = (line + " " + word).strip()
            if line and len(trial) > limit:
                out.append(line)
                line = word
            else:
                line = trial
        out.append(line)
    return "\n".join(out[:6])


def _effect_fragment(effect: dict) -> str:
    from . import tools as tools_module

    key = str(effect.get("tool"))
    if key not in CLIP_EFFECT_TOOLS:
        raise TimelineError(f"«{key}» روی یک قطعه اعمال نمی‌شود؛ از «افکتِ کلِ ویدیو» استفاده کنید.")
    tool = tools_module.TOOLS[key]
    return tool.build(dict(effect.get("params") or {}))


def build_graph(timeline: Timeline, **kwargs):
    """The whole filtergraph plus what `render` needs to run it (see compose.py)."""
    from . import compose

    return compose.build_graph(timeline, **kwargs)


def build_filtergraph(timeline: Timeline) -> tuple[list[str], str]:
    """A timeline → (input files, filter_complex).

    Returned rather than executed, so the panel can show the shop the
    arrangement before anything is encoded.
    """
    built = build_graph(timeline)
    return built.inputs, built.graph


def render(timeline: Timeline, out_path, *, quality: str = "final", **kwargs) -> Path:
    """Encode the arrangement (see export.py for presets, progress, cancel and range previews)."""
    from . import export

    return export.render(timeline, out_path, quality=quality, **kwargs)


# ------------------------------------------------------------ the panel's JSON

#: Tools that act on the whole finished program (stage two of a render, through the single-source EDL pipeline).
PROGRAM_TOOLS = ("cut", "trim_silence", "brightness", "contrast", "saturation", "white_balance", "deflicker",
                 "stabilize", "zoom", "speed", "crop_format", "denoise_audio", "normalize_audio", "fade", "rotate",
                 "watermark", "blur_region", "sharpen", "vignette", "transition")


def _num(value, lo, hi, default):
    try:
        x = float(value)
    except (TypeError, ValueError):
        return default
    if x != x:
        return default
    return max(lo, min(hi, x))


def _bool(value, default=False) -> bool:
    return default if value is None else bool(value)


def _hex(value, default):
    return str(value) if _HEX.match(str(value or "")) else default


def _clean_extras(rc: dict) -> dict:
    """The "pro" fields of a media clip, clamped. Never raises: a bad value falls back to the neutral one."""
    out: dict = {}
    out["rot"] = _num(rc.get("rot"), -360, 360, 0.0)
    out["scale"] = _num(rc.get("scale"), 0.05, 8, 1.0)
    out["px"] = _num(rc.get("px"), -2, 2, 0.0)
    out["py"] = _num(rc.get("py"), -2, 2, 0.0)
    out["flip_h"] = _bool(rc.get("flip_h"))
    out["flip_v"] = _bool(rc.get("flip_v"))
    blend = str(rc.get("blend") or "normal")
    out["blend"] = blend if blend in BLENDS else "normal"

    crop_in = rc.get("crop") if isinstance(rc.get("crop"), dict) else {}
    crop = {k: _num(crop_in.get(k), 0, 0.95, 0.0) for k in ("l", "r", "t", "b")}
    for a, b in (("l", "r"), ("t", "b")):
        if crop[a] + crop[b] > 0.98:
            k = 0.98 / (crop[a] + crop[b])
            crop[a], crop[b] = crop[a] * k, crop[b] * k
    out["crop"] = {k: round(v, 4) for k, v in crop.items() if v > 0}

    mask_in = rc.get("mask") if isinstance(rc.get("mask"), dict) else {}
    shape = str(mask_in.get("shape") or "none")
    if shape in MASK_SHAPES and shape != "none":
        out["mask"] = {"shape": shape, "cx": _num(mask_in.get("cx"), 0, 1, 0.5), "cy": _num(mask_in.get("cy"), 0, 1, 0.5),
                       "w": _num(mask_in.get("w"), 0.02, 1, 0.6), "h": _num(mask_in.get("h"), 0.02, 1, 0.6),
                       "feather": _num(mask_in.get("feather"), 0, 0.5, 0.05), "invert": _bool(mask_in.get("invert"))}
        if shape == "bezier":
            pts = masks.clean_points(mask_in.get("points"))
            if pts:
                out["mask"]["points"] = pts
            else:
                out["mask"] = {}
        # a motion track moves the mask: the displacement of its centre (fractions of the clip's box) over the clip's time
        if out["mask"]:
            for axis in ("kx", "ky"):
                keys = keyframes.clean_keys(mask_in.get(axis), -2.0, 2.0)
                if keys:
                    out["mask"][axis] = keys
    else:
        out["mask"] = {}

    kf_in = rc.get("kf") if isinstance(rc.get("kf"), dict) else {}
    kf = {}
    for channel, (lo, hi) in KF_CHANNELS.items():
        keys = keyframes.clean_keys(kf_in.get(channel), lo, hi)
        if keys:
            kf[channel] = keys
    out["kf"] = kf

    ch = rc.get("chroma") if isinstance(rc.get("chroma"), dict) else {}
    out["chroma"] = ({"on": True, "color": _hex(ch.get("color"), "#00ff00"), "similarity": _num(ch.get("similarity"), 0.01, 0.8, 0.18),
                      "blend": _num(ch.get("blend"), 0, 0.5, 0.08), "spill": _num(ch.get("spill"), 0, 1, 0.5)}
                     if ch.get("on") else {})

    col = color_module.clean(rc.get("color")) if isinstance(rc.get("color"), dict) else None
    out["color"] = col if col is not None and not color_module.is_neutral(col) else {}

    ramp = []
    for item in (rc.get("ramp") if isinstance(rc.get("ramp"), list) else [])[:12]:
        if isinstance(item, dict):
            ramp.append({"p": _num(item.get("p"), 0, 1, 0.0), "v": _num(item.get("v"), 0.1, 8, 1.0)})
    ramp.sort(key=lambda k: k["p"])
    out["ramp"] = ramp if len(ramp) >= 2 else []
    rf_in = rc.get("reframe") if isinstance(rc.get("reframe"), dict) else {}
    reframe: dict = {}
    if rf_in:
        rw, rh = _num(rf_in.get("w"), 0.05, 1, 1.0), _num(rf_in.get("h"), 0.05, 1, 1.0)
        reframe = {"w": round(rw, 4), "h": round(rh, 4), "cx": round(_num(rf_in.get("cx"), 0, 1, 0.5), 4),
                   "cy": round(_num(rf_in.get("cy"), 0, 1, 0.5), 4)}
        for axis in ("kx", "ky"):
            keys = keyframes.clean_keys(rf_in.get(axis), 0.0, 1.0)
            if keys:
                reframe[axis] = keys
        if rw >= 0.999 and rh >= 0.999 and not (reframe.get("kx") or reframe.get("ky")):
            reframe = {}
    out["reframe"] = reframe
    out["reverse"] = _bool(rc.get("reverse"))
    out["freeze"] = _bool(rc.get("freeze"))
    out["link"] = str(rc.get("link") or "")[:24]

    au = rc.get("audio") if isinstance(rc.get("audio"), dict) else {}
    eq = str(au.get("eq") or "flat")
    out["audio"] = {k: v for k, v in {
        "pan": _num(au.get("pan"), -1, 1, 0.0), "eq": eq if eq in EQ_PRESETS else "flat",
        "comp": _num(au.get("comp"), 0, 1, 0.0), "enhance": _bool(au.get("enhance")),
        "denoise": _bool(au.get("denoise")), "normalize": _bool(au.get("normalize")), "denoise_ai": _bool(au.get("denoise_ai")),
    }.items() if v not in (0.0, "flat", False)}
    out["audio"].update(_clean_audio_pro(au))
    out.update(_clean_fx_r5(rc))
    return out


def _clean_fx_r5(rc: dict) -> dict:
    """Adjustment layer flag, luma key and lens correction of a clip (clamped; neutral = not present)."""
    out: dict = {}
    if rc.get("adjust") is True:
        out["adjust"] = True
    lk = rc.get("luma")
    if isinstance(lk, dict) and lk.get("on"):
        out["luma"] = {"on": True, "mode": "bright" if lk.get("mode") == "bright" else "dark", "tolerance": round(_num(lk.get("tolerance"), 0.0, 1.0, 0.1), 3),
                       "softness": round(_num(lk.get("softness"), 0.0, 1.0, 0.05), 3)}
    tm = rc.get("track_matte")
    if isinstance(tm, dict) and tm.get("on", True) is not False:
        out["track_matte"] = {"mode": "alpha" if tm.get("mode") == "alpha" else "luma", "invert": tm.get("invert") is True}
    an = rc.get("anchor")
    if isinstance(an, dict):
        ax, ay = _num(an.get("x"), -1.0, 1.0, 0.0), _num(an.get("y"), -1.0, 1.0, 0.0)
        if abs(ax) > 0.002 or abs(ay) > 0.002:
            out["anchor"] = {"x": round(ax, 4), "y": round(ay, 4)}
    ln = rc.get("lens")
    if isinstance(ln, dict):
        k1, k2 = _num(ln.get("k1"), -1.0, 1.0, 0.0), _num(ln.get("k2"), -1.0, 1.0, 0.0)
        if abs(k1) > 0.005 or abs(k2) > 0.005:
            out["lens"] = {"k1": round(k1, 3), "k2": round(k2, 3)}
    return out


MAX_EQ_BANDS = 5


def _clean_audio_pro(au: dict) -> dict:
    """«EQ پارامتریک / کمپرسورِ دقیق / زیر و بمی / پژواک» of a clip: every number clamped, neutral settings dropped (so a project that never
    touched them serialises exactly as before)."""
    out: dict = {}
    bands = []
    for b in (au.get("bands") if isinstance(au.get("bands"), list) else [])[:3 * MAX_EQ_BANDS]:
        if isinstance(b, dict) and len(bands) < MAX_EQ_BANDS:
            g = _num(b.get("g"), -18, 18, 0.0)
            if abs(g) >= 0.1:
                bands.append({"f": round(_num(b.get("f"), 20, 20000, 1000.0), 1), "g": round(g, 1), "q": round(_num(b.get("q"), 0.2, 10, 1.0), 2)})
    if bands:
        out["bands"] = bands
    cd = au.get("cdetail")
    if isinstance(cd, dict) and cd.get("on"):
        out["cdetail"] = {"on": True, "thr": round(_num(cd.get("thr"), -40, 0, -18.0), 1), "ratio": round(_num(cd.get("ratio"), 1, 20, 3.0), 1),
                          "attack": round(_num(cd.get("attack"), 1, 200, 20.0)), "release": round(_num(cd.get("release"), 10, 2000, 250.0)),
                          "makeup": round(_num(cd.get("makeup"), 0, 24, 0.0), 1)}
    pitch = _num(au.get("pitch"), -12, 12, 0.0)
    if abs(pitch) >= 0.05:
        out["pitch"] = round(pitch, 2)
    ec = au.get("echo")
    if isinstance(ec, dict) and ec.get("on"):
        out["echo"] = {"on": True, "delay": round(_num(ec.get("delay"), 20, 1000, 250.0)), "decay": round(_num(ec.get("decay"), 0.05, 0.9, 0.4), 2)}
    return out


def _clean_master(data: dict) -> tuple[dict, dict, dict, list, dict | None]:
    m = data.get("master") if isinstance(data.get("master"), dict) else {}
    master = {"gain_db": _num(m.get("gain_db"), -24, 12, 0.0), "limiter": _bool(m.get("limiter"), True)}
    loud = m.get("loudness") if isinstance(m.get("loudness"), dict) else {}
    if loud.get("on"):
        # «بلندیِ استاندارد برای شبکه‌ها»: EBU R128 loudnorm on the finished mix (social platforms play ≈ −14 LUFS)
        master["loudness"] = {"on": True, "target": round(_num(loud.get("target"), -24, -8, -14.0), 1),
                              "tp": round(_num(loud.get("tp"), -3, 0, -1.0), 1)}
    d = data.get("ducking") if isinstance(data.get("ducking"), dict) else {}
    ducking = {"on": _bool(d.get("on")), "amount_db": _num(d.get("amount_db"), 3, 30, 12.0),
               "threshold": _num(d.get("threshold"), 0.005, 0.5, 0.04),
               "attack_ms": _num(d.get("attack_ms"), 5, 500, 40.0), "release_ms": _num(d.get("release_ms"), 50, 3000, 500.0)}
    e = data.get("export") if isinstance(data.get("export"), dict) else {}
    export = {k: v for k, v in e.items() if k in ("preset", "codec", "fps", "height", "quality", "audio_kbps", "where", "target_mb", "format", "range", "frame_t", "replace")}
    if "replace" in export:                       # «رندر و جایگزینی»: only the in–out range is rendered and kept as a new media file
        export["replace"] = export["replace"] is True
    if export.get("where") not in (None, "auto", "server"):
        export.pop("where")
    # one-shot output kinds (GIF, one still, sound only, only the in–out range): anything else means the normal video
    if export.get("format") not in (None, "mp4", "gif", "frame", "audio"):
        export.pop("format")
    if export.get("range") not in (None, "all", "inout"):
        export.pop("range")
    if "frame_t" in export:
        export["frame_t"] = _num(export.get("frame_t"), 0, 86400, 0.0)
    markers = []
    for item in (data.get("markers") if isinstance(data.get("markers"), list) else [])[:400]:
        if isinstance(item, dict):
            markers.append({"id": str(item.get("id") or "")[:24], "t": _num(item.get("t"), 0, 86400, 0.0),
                            "label": str(item.get("label") or "")[:60], "color": _hex(item.get("color"), "#ffcc00"),
                            "kind": str(item.get("kind")) if item.get("kind") in ("marker", "beat", "chapter") else "marker"})
    io = data.get("inout") if isinstance(data.get("inout"), dict) else None
    inout = None
    if io and io.get("in") is not None and io.get("out") is not None:
        a, b = _num(io.get("in"), 0, 86400, 0.0), _num(io.get("out"), 0, 86400, 0.0)
        if b > a + 0.05:
            inout = {"in": a, "out": b}
    return master, ducking, export, markers, inout


def from_project(data: dict, resolve, *, _depth: int = 0, _chain: tuple = ()) -> Timeline:
    """The panel's project JSON → a validated Timeline.

    `resolve(ref)` returns ``{"path", "kind", "has_audio", "duration"}`` (plus ``width``/``height`` for videos) or raises
    TimelineError. Everything the browser sends is clamped here; unknown keys are dropped, unknown tools refused.
    Refs of the form ``seq:<id>`` are the project's own nested sequences (`data["sequences"]`), built recursively;
    ``lut:<key>`` and ``matte:<key>`` are the shop's imported LUTs and background-removal mattes.
    """
    from . import tools as tools_module
    from . import titles

    if not isinstance(data, dict):
        raise TimelineError("پروژه درست ذخیره نشده است.")
    fmt = data.get("format") if isinstance(data.get("format"), dict) else {}
    width = int(_num(fmt.get("width"), 240, 3840, 1080)) // 2 * 2
    height = int(_num(fmt.get("height"), 240, 3840, 1920)) // 2 * 2
    fps = int(_num(fmt.get("fps"), 12, 60, 30))
    timeline = Timeline(width=width, height=height, fps=fps)
    timeline.master, timeline.ducking, timeline.export, timeline.markers, timeline.inout = _clean_master(data)

    raw_tracks = data.get("tracks")
    if not isinstance(raw_tracks, list) or not raw_tracks:
        raise TimelineError("تایم‌لاین خالی است.")
    for ti, rt in enumerate(raw_tracks[: MAX_TRACKS + 1]):
        if not isinstance(rt, dict):
            raise TimelineError("ترک نامعتبر است.")
        kind = str(rt.get("kind") or "video")
        if kind not in TRACK_KINDS:
            raise TimelineError(f"نوعِ ترک باید یکی از {'، '.join(TRACK_KINDS)} باشد.")
        role = str(rt.get("role") or "")
        track = Track(kind=kind, name=str(rt.get("name") or "")[:40], muted=bool(rt.get("muted")),
                      hidden=bool(rt.get("hidden")), solo=bool(rt.get("solo")),
                      gain_db=_num(rt.get("gain_db"), -40, 12, 0.0), pan=_num(rt.get("pan"), -1, 1, 0.0),
                      role=role if role in ROLES else "", caption=bool(rt.get("caption")))
        for ci, rc in enumerate((rt.get("clips") or [])[: MAX_CLIPS + 1]):
            if not isinstance(rc, dict):
                raise TimelineError("قطعهٔ نامعتبر.")
            label = str(rc.get("label") or "")[:60]
            if kind == "text":
                spec = titles.clean(rc, ci)
                track.clips.append(TextClip(
                    text=spec["text"], at=spec["at"], duration=spec["duration"], position=spec["position"], size=spec["size"],
                    color=spec["color"], box=spec["box"], opacity=spec["opacity"], label=spec["label"], spec=spec,
                ))
                continue
            ref = str(rc.get("ref") or "")
            shape_in = rc.get("shape") if isinstance(rc.get("shape"), dict) else None
            nested_tl = None
            if rc.get("adjust") is True and kind == "video":
                info = {"path": "", "kind": "image", "has_audio": False, "duration": 0.0}          # a layer with no picture of its own
            elif shape_in is not None and kind == "video":
                # a shape is a drawn PNG used as a still: it carries every picture property (keyframes, masks, fades …)
                spec = shapes.clean(shape_in)
                box_w = max(8, int(_num(rc.get("width"), 0.02, 1, 1.0) * width))
                box_h = max(8, int(_num(rc.get("height"), 0.02, 1, 1.0) * height))
                info = {"path": str(shapes.render_cached(spec, box_w, box_h)), "kind": "image", "has_audio": False, "duration": 0.0}
            elif ref.startswith("seq:"):
                if kind != "video":
                    raise TimelineError(f"«{label or ref}»: توالیِ تودرتو را فقط روی ترکِ تصویر می‌شود گذاشت.")
                sid = ref[4:]
                seqs = data.get("sequences") if isinstance(data.get("sequences"), dict) else {}
                seq = seqs.get(sid)
                if not isinstance(seq, dict):
                    raise TimelineError(f"«{label or ref}»: توالیِ تودرتو پیدا نشد (شاید پاک شده).")
                if _depth >= MAX_NEST or sid in _chain:
                    raise TimelineError(f"«{label or ref}»: توالی‌های تودرتو بیش از {MAX_NEST} سطح یا حلقه‌ای‌اند.")
                sub_format = seq.get("format") if isinstance(seq.get("format"), dict) else {"width": width, "height": height, "fps": fps}
                nested_tl = from_project({"format": sub_format, "tracks": seq.get("tracks"), "sequences": seqs, "master": seq.get("master")},
                                         resolve, _depth=_depth + 1, _chain=_chain + (sid,))
                nested_tl.validate(need_base=False)
                from . import audiofx

                info = {"path": "", "kind": "video", "duration": nested_tl.length,
                        "has_audio": any(audiofx.carries(t, c) for t in nested_tl.tracks for c in t.clips)}
            else:
                info = resolve(ref)
            src_kind = info.get("kind", "video")
            if kind == "audio" and src_kind == "image":
                raise TimelineError(f"«{label or ref}»: عکس را روی ترکِ صدا نمی‌شود گذاشت.")
            if kind == "video" and src_kind == "audio":
                raise TimelineError(f"«{label or ref}»: فایلِ صدا را روی ترکِ تصویر نمی‌شود گذاشت.")
            start = _num(rc.get("start"), 0, 86400, 0)
            end = rc.get("end")
            end = _num(end, 0, 86400, None) if end is not None else None
            duration = float(info.get("duration") or 0)
            if end is None:
                end = duration or None
            if src_kind != "image" and duration and end is not None:
                end = min(end, duration + 0.05)
            effects = []
            for effect in (rc.get("effects") or [])[:8]:
                if not isinstance(effect, dict):
                    continue
                if str(effect.get("tool")) not in CLIP_EFFECT_TOOLS:
                    raise TimelineError(f"«{effect.get('tool')}» روی یک قطعه اعمال نمی‌شود؛ از «افکتِ کلِ ویدیو» استفاده کنید.")
                params = dict(effect.get("params") or {})
                params.pop("from_s", None)
                params.pop("to_s", None)
                try:
                    op = tools_module.validate_one({"tool": effect["tool"], "params": params})
                except tools_module.ToolError as exc:
                    raise TimelineError(f"«{label or ref}»: {exc}") from exc
                effects.append({"tool": op.tool, "params": op.params})
            transition = None
            tr = rc.get("transition")
            if isinstance(tr, dict) and tr.get("kind") in transitions_all():
                transition = {"kind": tr["kind"], "duration": _num(tr.get("duration"), 0.1, 2.0, 0.5)}
            extras = _clean_extras(rc)
            if rc.get("adjust") is True and kind == "video":
                transition = None                                  # a layer without a picture has nothing to dissolve
            if src_kind == "image":
                extras["ramp"], extras["reverse"] = [], False
            lut_file = ""
            lut_in = rc.get("lut") if isinstance(rc.get("lut"), dict) else None
            if lut_in and lut_in.get("key"):
                got = resolve("lut:" + str(lut_in["key"]))
                lut_file = str(luts.blended(got["path"], _num(lut_in.get("amount"), 0, 1, 1.0)))
            matte_file, matte_s0 = "", 0.0
            matte_in = rc.get("matte") if isinstance(rc.get("matte"), dict) else None
            if matte_in and matte_in.get("key") and src_kind == "video" and nested_tl is None:
                got = resolve("matte:" + str(matte_in["key"]))
                matte_file, matte_s0 = str(got["path"]), float(got.get("s0") or 0.0)
            mask_file = ""
            m = extras.get("mask") or {}
            if m.get("shape") == "bezier" and m.get("points"):
                moving = bool(m.get("kx") or m.get("ky"))
                cw = max(8, int(_num(rc.get("width"), 0.02, 1, 1.0) * width))
                ch = max(8, int(_num(rc.get("height"), 0.02, 1, 1.0) * height))
                # a moving mask is drawn plain and inverted AFTER it moves (the uncovered edge must stay «outside»)
                mask_file = str(masks.render_cached({**m, "invert": False} if moving else m, cw, ch))
            track.clips.append(Clip(
                source=str(info["path"]), at=_num(rc.get("at"), 0, 86400, 0), start=0.0 if src_kind == "image" else start,
                end=end, opacity=_num(rc.get("opacity"), 0, 1, 1.0),
                x=_num(rc.get("x"), 0, 1, 0.0), y=_num(rc.get("y"), 0, 1, 0.0),
                width=_num(rc.get("width"), 0.02, 1, 1.0), height=_num(rc.get("height"), 0.02, 1, 1.0),
                label=label, kind="audio" if kind == "audio" else src_kind,
                has_audio=bool(info.get("has_audio")) and bool(rc.get("audio_on", True)),
                volume=_num(rc.get("volume"), 0, 3, 1.0), speed=_num(rc.get("speed"), 0.25, 4, 1.0),
                fit=str(rc.get("fit")) if str(rc.get("fit")) in FITS else "cover",
                fade_in=_num(rc.get("fade_in"), 0, 30, 0.0), fade_out=_num(rc.get("fade_out"), 0, 30, 0.0),
                effects=effects, transition=transition, src_len=duration if src_kind != "image" else 0.0, **extras,
                src_w=int(info.get("width") or 0), src_h=int(info.get("height") or 0), lut_file=lut_file, mask_file=mask_file,
                matte_file=matte_file, matte_s0=matte_s0, nested=nested_tl,
            ))
        timeline.tracks.append(track)
    return timeline


def program_operations(data: dict) -> list[dict]:
    """The project's whole-program tools (stage two of a render): [{tool, params}], validated by the caller."""
    ops = data.get("global_ops") if isinstance(data, dict) else None
    out = []
    for op in (ops or [])[:30]:
        if isinstance(op, dict) and str(op.get("tool")) in PROGRAM_TOOLS:
            out.append({"tool": str(op["tool"]), "params": dict(op.get("params") or {})})
        elif isinstance(op, dict):
            raise TimelineError(f"«{op.get('tool')}» افکتِ کلِ ویدیو نیست.")
    return out


# ------------------------------------------------------------------ windowing


def window(timeline: Timeline, t0: float, t1: float) -> Timeline:
    """The part of a timeline between `t0` and `t1`, re-based to start at 0 — for the exact range preview.

    Every clip is cut to the window (its source range, keyframes, fades and text words follow); a ramp clip becomes
    an explicit segment list. Nothing outside the window is decoded afterwards.
    """
    t0, t1 = max(0.0, float(t0)), max(float(t0) + 0.1, float(t1))
    out = Timeline(width=timeline.width, height=timeline.height, fps=timeline.fps, master=dict(timeline.master),
                   ducking=dict(timeline.ducking), export=dict(timeline.export))
    for track in timeline.tracks:
        nt = Track(kind=track.kind, name=track.name, muted=track.muted, hidden=track.hidden, solo=track.solo,
                   gain_db=track.gain_db, pan=track.pan, role=track.role, caption=track.caption)
        for clip in sorted(track.clips, key=lambda c: c.at):
            if clip.ends_at <= t0 + 1e-6 or clip.at >= t1 - 1e-6:
                continue
            nt.clips.append(_cut_clip(clip, t0, t1))
        out.tracks.append(nt)
    return out


def _cut_clip(clip, t0: float, t1: float):
    a, b = max(clip.at, t0), min(clip.ends_at, t1)
    lt0, lt1 = a - clip.at, b - clip.at
    whole_head, whole_tail = lt0 <= 1e-6, lt1 >= clip.length - 1e-6
    if clip.kind == "text":
        new = copy.deepcopy(clip)
        new.at, new.duration = a - t0, b - a
        if new.spec:
            words = [{**w, "s": round(w["s"] - lt0, 3), "e": round(w["e"] - lt0, 3)} for w in new.spec.get("words", [])
                     if w["e"] > lt0 and w["s"] < lt1]
            new.spec = {**new.spec, "words": [{**w, "s": max(0.0, w["s"]), "e": min(b - a, w["e"])} for w in words]}
            if new.spec.get("path"):
                from . import titles

                pts = new.spec["path"]
                e0, e1 = titles.path_at(pts, lt0), titles.path_at(pts, lt1)
                inner = [{"t": round(p["t"] - lt0, 3), "dx": p["dx"], "dy": p["dy"]} for p in pts if lt0 < p["t"] < lt1]
                path = [{"t": 0.0, "dx": e0[0], "dy": e0[1]}, *inner, {"t": round(lt1 - lt0, 3), "dx": e1[0], "dy": e1[1]}]
                new.spec = {**new.spec, "path": path[: titles.MAX_PATH]}
        return new
    new = copy.deepcopy(clip)
    new.at = a - t0
    new.transition = clip.transition if whole_head else None
    new.fade_in = clip.fade_in if whole_head else 0.0
    new.fade_out = clip.fade_out if whole_tail else 0.0
    for channel, keys in list(new.kf.items()):
        sliced = keyframes.sliced(keys, lt0, lt1)
        if sliced:
            new.kf[channel] = sliced
    if new.mask and (new.mask.get("kx") or new.mask.get("ky")):
        m = dict(new.mask)
        for axis in ("kx", "ky"):
            if m.get(axis):
                m[axis] = keyframes.sliced(m[axis], lt0, lt1) or m[axis]
        new.mask = m
    if new.reframe and (new.reframe.get("kx") or new.reframe.get("ky")):
        rf = dict(new.reframe)
        for axis in ("kx", "ky"):
            if rf.get(axis):
                rf[axis] = keyframes.sliced(rf[axis], lt0, lt1) or rf[axis]
        new.reframe = rf
    if new.freeze or new.kind == "image":
        new.end = new.start + (b - a)
        if new.kind == "image":
            new.start, new.end = 0.0, b - a
        return new
    L = clip.length
    x0, x1 = (L - lt1, L - lt0) if clip.reverse else (lt0, lt1)
    segs = cut_segments(clip.segments(), x0, x1)
    if not segs:
        segs = [(clip.start, clip.start + 0.04, clip.speed or 1.0)]
    new.start, new.end = min(s[0] for s in segs), max(s[1] for s in segs)
    if len(segs) == 1:
        new.speed = max(0.1, min(8.0, segs[0][2]))
        new.ramp, new.segs = [], None
    else:
        new.ramp, new.segs = [], [tuple(s) for s in segs]
    return new


# ------------------------------------------------------------------- proxy


def needs_proxy(source) -> tuple[bool, str]:
    """Whether a proxy would actually help.

    Measured, because it often does not: re-encoding a clip that is already
    small produces a *larger* file and costs a render to do it. A 640x360 test
    clip came back 1.4x bigger than the original.
    """
    from services.video.ffmpeg import probe

    try:
        info = probe(source)
    except Exception as exc:  # noqa: BLE001
        return False, f"ابعاد ویدیو خوانده نشد: {exc}"

    stream = next(
        (s for s in info.get("streams", []) if s.get("codec_type") == "video"),
        None,
    )
    if stream is None:
        return False, "این فایل تصویر ندارد."

    height = int(stream.get("height") or 0)
    if height <= PROXY_HEIGHT * 1.2:
        return False, (
            f"این ویدیو {height} پیکسل ارتفاع دارد — از نسخه‌ی پیش‌نمایش "
            "کوچک‌تر است. ساختن پیش‌نمایش برایش فقط یک رندر اضافه است و "
            "فایلش هم بزرگ‌تر درمی‌آید."
        )
    return True, ""


def make_proxy(source, out_path, *, force: bool = False) -> Path:
    """A small stand-in for editing decisions.

    **The frame rate is deliberately not changed.** A proxy at a different
    timebase makes a cut at 12.40 seconds land on a different frame in the
    proxy than in the original — so the shop approves one video and exports a
    subtly different one, and the difference only appears on the final render.
    Resolution is the only thing given up.

    `force` is for files a browser cannot play at all (MOV/MKV/AVI, HEVC): there the proxy is a conversion, not a
    shrink, so the size check does not apply.
    """
    from services.video.ffmpeg import FFMPEG, VideoProcessingError, _run

    if not force:
        worth_it, why = needs_proxy(source)
        if not worth_it:
            raise TimelineError(why)

    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    _run([
        FFMPEG, "-y", "-i", str(source),
        # -2 keeps the width even (h264 requires it) and preserves the aspect.
        "-vf", f"scale=-2:{PROXY_HEIGHT}" if not force else f"scale=-2:'min({PROXY_HEIGHT},ih)'",
        "-c:v", "libx264", "-preset", PROXY_PRESET, "-crf", str(PROXY_CRF), "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "96k", "-movflags", "+faststart",
        str(out),
    ])
    if not out.exists() or out.stat().st_size == 0:
        raise VideoProcessingError("نسخه‌ی پیش‌نمایش ساخته نشد")
    return out


def proxy_savings(source, proxy) -> dict:
    """What the proxy bought, in numbers a shop can see."""
    from services.video.ffmpeg import probe_duration

    source, proxy = Path(source), Path(proxy)
    original = source.stat().st_size if source.exists() else 0
    small = proxy.stat().st_size if proxy.exists() else 0
    return {
        "original_mb": round(original / (1 << 20), 1),
        "proxy_mb": round(small / (1 << 20), 1),
        "times_smaller": round(original / small, 1) if small else 0,
        "seconds": round(probe_duration(proxy), 2) if proxy.exists() else 0,
        "note": (
            "تصمیم‌ها روی این نسخه‌ی کوچک گرفته می‌شوند و آخر کار روی فایل "
            "اصلی اعمال می‌شوند. نرخ فریم عمداً دست‌نخورده است — وگرنه یک برش "
            "در ثانیه‌ی ۱۲.۴ روی دو فایل به دو فریم مختلف می‌افتد و تفاوتش "
            "فقط در رندر نهایی معلوم می‌شود."
        ),
    }


def relink(timeline: Timeline, mapping: dict) -> Timeline:
    """Point every clip from its proxy back at the original.

    Called at export. Timings are untouched by design — that is the whole
    reason `make_proxy` does not change the frame rate.
    """
    for track in timeline.tracks:
        for clip in track.clips:
            clip.source = mapping.get(clip.source, clip.source)
    return timeline
