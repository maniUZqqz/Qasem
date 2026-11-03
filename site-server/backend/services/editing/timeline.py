"""Multi-track timeline and proxy editing. §23.4

The EDL in `edl.py` describes one operation applied to one source. That is the
right shape for «کوتاهش کن، روشنش کن» and the wrong shape the moment a shop
wants two clips side by side, a logo in the corner for the last five seconds,
and music under all of it. This is that second shape.

**A timeline is tracks, and a track is clips on a clock.** Nothing here renders:
it produces an ffmpeg filtergraph, and `render` still does the work. Keeping
the description separate from the execution is what lets the panel show a shop
what will happen before a single frame is encoded — the same reason `plan` and
`apply` are separate endpoints.

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

**What the panel's «دستی» workspace adds on top (Premiere-style):** a clip can carry its own sound
(`has_audio`, `volume`, fades), a speed, a fit (`cover`/`contain`/`stretch`), a handful of picture effects
(`effects`, the same toolbox as `tools.py`), a transition into it from the previous clip, and a track can hold
text (`TextClip`). Stills are clips too (`kind="image"`). `from_project` turns the panel's JSON into a Timeline,
resolving every `ref` through a callback — the browser never names a file path.
"""
from __future__ import annotations

import logging
import re
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

#: Small enough to render in seconds, large enough to judge framing and read
#: any text burnt into the picture.
PROXY_HEIGHT = 480

#: Proxies are disposable; this is about not spending minutes making one.
PROXY_CRF = 30
PROXY_PRESET = "veryfast"

#: More than this and the filtergraph takes longer to assemble than the render
#: it describes, and nobody is hand-building a 40-track edit in this panel.
MAX_TRACKS = 8
MAX_CLIPS = 120

FITS = ("stretch", "cover", "contain")
TRACK_KINDS = ("video", "audio", "text")
TRANSITIONS = ("fade", "crossfade")
TEXT_POSITIONS = ("top", "middle", "bottom")

#: Picture tools that make sense on ONE clip (the rest — cut, trim_silence, zoom, fade, transition, stabilize,
#: crop_format, denoise_audio, normalize_audio, subtitle, speed, watermark — act on the whole program or are native
#: clip properties; see `PROGRAM_TOOLS`).
CLIP_EFFECT_TOOLS = ("brightness", "contrast", "saturation", "white_balance", "deflicker", "sharpen", "vignette",
                     "blur_region", "rotate")

_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")


class TimelineError(Exception):
    """Something about the arrangement cannot be rendered, said in Persian."""


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
    #: How this clip comes in from the previous one on its track: {"kind": "fade"|"crossfade", "duration": s}.
    transition: dict | None = None
    #: Seconds the previous clip is held on its last frame under a crossfade (set by `_resolve_transitions`).
    hold: float = 0.0

    @property
    def source_length(self) -> float:
        return (self.end - self.start) if self.end is not None else 0.0

    @property
    def length(self) -> float:
        return self.source_length / (self.speed or 1.0)

    @property
    def ends_at(self) -> float:
        return self.at + self.length

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
        if not 0 <= self.opacity <= 1:
            raise TimelineError(f"{where}: شفافیت باید بین ۰ و ۱ باشد.")
        for name, value in (("x", self.x), ("y", self.y)):
            if not 0 <= value <= 1:
                raise TimelineError(f"{where}: {name} باید بین ۰ و ۱ باشد.")
        if not 0 < self.width <= 1 or not 0 < self.height <= 1:
            raise TimelineError(f"{where}: اندازه باید بین ۰ و ۱ باشد.")
        if self.x + self.width > 1.001 or self.y + self.height > 1.001:
            raise TimelineError(f"{where}: از لبه‌ی کادر بیرون می‌زند.")
        if not 0.25 <= self.speed <= 4:
            raise TimelineError(f"{where}: سرعت باید بین ۰٫۲۵ و ۴ برابر باشد.")
        if not 0 <= self.volume <= 3:
            raise TimelineError(f"{where}: بلندی صدا باید بین ۰ و ۳ برابر باشد.")
        if self.fit not in FITS:
            raise TimelineError(f"{where}: روش جا دادن باید یکی از {'، '.join(FITS)} باشد.")
        if self.fade_in < 0 or self.fade_out < 0 or self.fade_in + self.fade_out > max(self.length, 0.01) + 0.001:
            raise TimelineError(f"{where}: محو شدنِ ابتدا و انتها از طولِ قطعه بیشتر است.")


@dataclass
class TextClip:
    """A line of text on the picture for a while. Lives on a track of kind "text"."""

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

    def validate(self, index: int) -> None:
        where = self.label or f"متن {index + 1}"
        if self.at < 0 or self.duration <= 0:
            raise TimelineError(f"{where}: زمان یا مدتِ متن درست نیست.")
        if not self.text.strip():
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

    @property
    def length(self) -> float:
        return max((t.length for t in self.tracks), default=0.0)

    @property
    def clip_count(self) -> int:
        return sum(len(t.clips) for t in self.tracks)

    def validate(self) -> None:
        if not self.tracks:
            raise TimelineError("تایم‌لاین خالی است.")
        if len(self.tracks) > MAX_TRACKS:
            raise TimelineError(f"حداکثر {MAX_TRACKS} ترک.")
        if self.clip_count > MAX_CLIPS:
            raise TimelineError(f"حداکثر {MAX_CLIPS} قطعه در کل تایم‌لاین.")

        video_tracks = [t for t in self.tracks if t.kind == "video"]
        if not video_tracks:
            raise TimelineError("حداقل یک ترک تصویر لازم است.")
        if not video_tracks[0].clips:
            raise TimelineError("ترک اصلی تصویر هیچ قطعه‌ای ندارد.")

        for track in self.tracks:
            for index, clip in enumerate(track.clips):
                clip.validate(index)
            clashes = track.overlaps()
            if clashes:
                first, second = clashes[0]
                raise TimelineError(
                    f"در ترک «{track.name or track.kind}» دو قطعه هم‌زمان‌اند "
                    f"({first.label or 'قطعه'} تا {first.ends_at:.1f} و "
                    f"{second.label or 'قطعه'} از {second.at:.1f}). "
                    "یکی را جابه‌جا کنید یا ترک تازه بسازید."
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


# -------------------------------------------------------------- filtergraph

#: Substituted by `render` with the path of a text file per text clip (drawtext's own escaping rejects '%', quotes
#: and commas; `expansion=none` + a textfile carries any string untouched — the same trick the watermark uses).
TEXTFILE_TOKEN = "__TEXTFILE_{n}__"


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
    """drawtext does not wrap: a long line runs off both edges. Break it at spaces so each line fits ~88 % of the
    frame width (Vazirmatn averages about half an em per character)."""
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


def _resolve_transitions(timeline: Timeline) -> None:
    """A crossfade holds the previous clip's last frame under the incoming fade; a «fade» dips both to black."""
    for track in timeline.tracks:
        if track.kind != "video":
            continue
        ordered = sorted(track.clips, key=lambda c: c.at)
        for clip in ordered:
            clip.hold = 0.0
        for earlier, later in zip(ordered, ordered[1:]):
            tr = later.transition
            if not tr or abs(later.at - earlier.ends_at) > 0.15:
                continue
            d = max(0.1, min(float(tr.get("duration", 0.5)), 2.0, later.length, 3.0))
            if tr.get("kind") == "crossfade":
                earlier.hold = max(earlier.hold, d)
            else:
                earlier.fade_out = max(earlier.fade_out, min(d / 2, earlier.length))


@dataclass
class Graph:
    inputs: list[str]
    input_args: list[list[str]]
    graph: str
    texts: dict[str, str]
    has_audio: bool


def build_graph(timeline: Timeline) -> Graph:
    """The whole filtergraph plus what `render` needs to run it."""
    timeline.validate()
    _resolve_transitions(timeline)

    inputs: list[str] = []
    input_args: list[list[str]] = []
    parts: list[str] = []
    index_of: dict[int, int] = {}
    texts: dict[str, str] = {}

    for track in timeline.tracks:
        if track.kind == "text":
            continue
        for clip in track.clips:
            index_of[id(clip)] = len(inputs)
            inputs.append(clip.source)
            if clip.kind == "image":
                input_args.append(["-loop", "1", "-framerate", str(timeline.fps), "-t", f"{clip.source_length + clip.hold + 0.5:.3f}"])
            else:
                input_args.append([])

    W, H = timeline.width, timeline.height
    # The canvas. Every video clip is composited onto it, which means a gap in
    # the base track is black rather than whatever the renderer felt like.
    parts.append(f"color=c=black:s={W}x{H}:r={timeline.fps}:d={timeline.length:.3f}[base]")

    current = "base"
    step = 0
    for track in timeline.tracks:
        if track.kind == "video":
            for clip in track.clips:
                source = index_of[id(clip)]
                label = f"v{step}"
                trimmed = f"t{step}"
                end = clip.end if clip.end is not None else clip.start
                chain = [
                    f"trim={clip.start:.3f}:{end:.3f}",
                    # `setpts` moves the clip so that its first frame carries the timestamp `at` — the same shift
                    # `adelay` gives the audio below. Without it the clip's own clock starts at 0, and by the time
                    # the overlay window opens at `at` the input has already played past (a two-second clip placed
                    # at 3 s never appeared at all).
                    (f"setpts=(PTS-STARTPTS)/{_f(clip.speed)}+{clip.at:.3f}/TB" if clip.speed != 1.0
                     else f"setpts=PTS-STARTPTS+{clip.at:.3f}/TB"),
                ]
                for effect in clip.effects:
                    if effect.get("tool") == "rotate":
                        chain.append(_effect_fragment(effect))
                bw, bh = int(W * clip.width) // 2 * 2, int(H * clip.height) // 2 * 2
                if clip.fit == "cover":
                    chain.append(f"scale={bw}:{bh}:force_original_aspect_ratio=increase,crop={bw}:{bh}")
                elif clip.fit == "contain":
                    chain.append(f"scale={bw}:{bh}:force_original_aspect_ratio=decrease,"
                                 f"pad={bw}:{bh}:(ow-iw)/2:(oh-ih)/2:color=black")
                else:
                    chain.append(f"scale={int(W * clip.width)}:{int(H * clip.height)}")
                chain.append("setsar=1")
                for effect in clip.effects:
                    if effect.get("tool") != "rotate":
                        chain.append(_effect_fragment(effect))
                if clip.hold > 0:
                    chain.append(f"tpad=stop_mode=clone:stop_duration={clip.hold:.3f}")
                fades = []
                fin = clip.fade_in
                if clip.transition and clip.transition.get("kind") in TRANSITIONS:
                    fin = max(fin, min(float(clip.transition.get("duration", 0.5)) / (1 if clip.transition["kind"] == "crossfade" else 2), clip.length))
                if fin > 0:
                    fades.append(f"fade=t=in:st={clip.at:.3f}:d={fin:.3f}:alpha=1")
                if clip.fade_out > 0:
                    fades.append(f"fade=t=out:st={clip.ends_at - clip.fade_out:.3f}:d={clip.fade_out:.3f}:alpha=1")
                if fades:
                    chain.append("format=yuva420p")
                    chain += fades
                if clip.opacity < 1:
                    chain.append(f"format=yuva420p,colorchannelmixer=aa={clip.opacity:.3f}")
                parts.append(f"[{source}:v]" + ",".join(chain) + f"[{trimmed}]")
                parts.append(
                    f"[{current}][{trimmed}]overlay="
                    f"x={int(W * clip.x)}:"
                    f"y={int(H * clip.y)}:"
                    f"enable='between(t,{clip.at:.3f},{clip.ends_at + clip.hold:.3f})':"
                    f"eof_action=pass[{label}]"
                )
                current = label
                step += 1
        elif track.kind == "text":
            from .tools import FONT_FILE
            from services.video.ffmpeg import filter_path

            for clip in track.clips:
                label = f"v{step}"
                token = TEXTFILE_TOKEN.format(n=len(texts))
                texts[token] = wrap_text(clip.text, W, H, clip.size)
                y = {"top": "h*0.08", "middle": "(h-text_h)/2", "bottom": "h-text_h-h*0.08"}[clip.position]
                size = _f(max(1.0, min(20.0, clip.size)) / 100)
                box = ":box=1:boxcolor=black@0.45:boxborderw='h*0.012'" if clip.box else ""
                colour = clip.color.lstrip("#")
                parts.append(
                    f"[{current}]drawtext=fontfile={filter_path(FONT_FILE)}:expansion=none:textfile={token}"
                    f":x=(w-text_w)/2:y={y}:text_align=center:fontsize='h*{size}':fontcolor=0x{colour}@{_f(clip.opacity)}{box}"
                    f":enable='between(t,{clip.at:.3f},{clip.ends_at:.3f})'[{label}]"
                )
                current = label
                step += 1

    audio_labels = []
    step = 0
    for track in timeline.tracks:
        if track.kind == "text" or track.muted:
            continue
        for clip in track.clips:
            carries = (track.kind == "audio") or (track.kind == "video" and clip.kind == "video" and clip.has_audio)
            if not carries:
                continue
            source = index_of[id(clip)]
            label = f"a{step}"
            end = clip.end if clip.end is not None else clip.start
            chain = [f"atrim={clip.start:.3f}:{end:.3f}", "asetpts=PTS-STARTPTS"]
            if clip.speed != 1.0:
                chain.append(_atempo(clip.speed))
            if clip.fade_in > 0:
                chain.append(f"afade=t=in:st=0:d={clip.fade_in:.3f}")
            if clip.fade_out > 0:
                chain.append(f"afade=t=out:st={max(0.0, clip.length - clip.fade_out):.3f}:d={clip.fade_out:.3f}")
            # An audio clip's `opacity` is its level (the original, pre-panel meaning); `volume` multiplies it.
            level = clip.volume * (clip.opacity if track.kind == "audio" else 1.0)
            if abs(level - 1.0) > 1e-6:
                chain.append(f"volume={level:.3f}")
            ms = int(clip.at * 1000)
            chain.append(f"adelay={ms}|{ms}")
            parts.append(f"[{source}:a]" + ",".join(chain) + f"[{label}]")
            audio_labels.append(f"[{label}]")
            step += 1

    if audio_labels:
        parts.append(
            f"{''.join(audio_labels)}amix=inputs={len(audio_labels)}"
            # normalize=0: amix otherwise divides by the input count, so a
            # six-clip timeline came back quieter than any one of its clips.
            f":duration=longest:dropout_transition=0:normalize=0,"
            "alimiter=limit=0.95[aout]"
        )

    parts.append(f"[{current}]null[vout]")
    return Graph(inputs, input_args, ";".join(parts), texts, bool(audio_labels))


def build_filtergraph(timeline: Timeline) -> tuple[list[str], str]:
    """A timeline → (input files, filter_complex).

    Returned rather than executed, so the panel can show the shop the
    arrangement before anything is encoded.
    """
    built = build_graph(timeline)
    return built.inputs, built.graph


#: Draft = look at it fast; final = the delivery settings every other render here uses.
DRAFT_VIDEO = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "27", "-pix_fmt", "yuv420p", "-movflags", "+faststart"]


def render(timeline: Timeline, out_path, *, quality: str = "final") -> Path:
    """Encode the arrangement."""
    from services.video.ffmpeg import AUDIO_DELIVERY, FFMPEG, VIDEO_DELIVERY, VideoProcessingError, _run, filter_path

    built = build_graph(timeline)
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    graph = built.graph
    handles: list[Path] = []
    try:
        for token, text in built.texts.items():
            handle = tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8")
            handle.write(text[:300])
            handle.close()
            handles.append(Path(handle.name))
            graph = graph.replace(token, filter_path(handle.name))

        command = [FFMPEG, "-y"]
        for source, args in zip(built.inputs, built.input_args):
            command += [*args, "-i", str(source)]
        command += ["-filter_complex", graph, "-map", "[vout]"]
        if built.has_audio:
            command += ["-map", "[aout]", *AUDIO_DELIVERY]
        command += [*(DRAFT_VIDEO if quality == "draft" else VIDEO_DELIVERY), str(out)]
        _run(command)
    finally:
        for path in handles:
            try:
                path.unlink()
            except OSError:
                pass
    if not out.exists() or out.stat().st_size == 0:
        raise VideoProcessingError("تایم‌لاین رندر نشد")
    return out


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


def from_project(data: dict, resolve) -> Timeline:
    """The panel's project JSON → a validated Timeline.

    `resolve(ref)` returns ``{"path", "kind", "has_audio", "duration"}`` or raises TimelineError. Everything the browser
    sends is clamped here; unknown keys are dropped, unknown tools refused.
    """
    from . import tools as tools_module

    if not isinstance(data, dict):
        raise TimelineError("پروژه درست ذخیره نشده است.")
    fmt = data.get("format") if isinstance(data.get("format"), dict) else {}
    width = int(_num(fmt.get("width"), 240, 3840, 1080)) // 2 * 2
    height = int(_num(fmt.get("height"), 240, 3840, 1920)) // 2 * 2
    fps = int(_num(fmt.get("fps"), 12, 60, 30))
    timeline = Timeline(width=width, height=height, fps=fps)

    raw_tracks = data.get("tracks")
    if not isinstance(raw_tracks, list) or not raw_tracks:
        raise TimelineError("تایم‌لاین خالی است.")
    for ti, rt in enumerate(raw_tracks[: MAX_TRACKS + 1]):
        if not isinstance(rt, dict):
            raise TimelineError("ترک نامعتبر است.")
        kind = str(rt.get("kind") or "video")
        if kind not in TRACK_KINDS:
            raise TimelineError(f"نوعِ ترک باید یکی از {'، '.join(TRACK_KINDS)} باشد.")
        track = Track(kind=kind, name=str(rt.get("name") or "")[:40], muted=bool(rt.get("muted")))
        for ci, rc in enumerate((rt.get("clips") or [])[: MAX_CLIPS + 1]):
            if not isinstance(rc, dict):
                raise TimelineError("قطعهٔ نامعتبر.")
            label = str(rc.get("label") or "")[:60]
            if kind == "text":
                track.clips.append(TextClip(
                    text=str(rc.get("text") or "")[:200], at=_num(rc.get("at"), 0, 86400, 0),
                    duration=_num(rc.get("duration"), 0.1, 3600, 2.0),
                    position=str(rc.get("position") or "bottom") if str(rc.get("position") or "bottom") in TEXT_POSITIONS else "bottom",
                    size=_num(rc.get("size"), 1, 20, 6.0),
                    color=str(rc.get("color")) if _HEX.match(str(rc.get("color") or "")) else "#ffffff",
                    box=bool(rc.get("box", True)), opacity=_num(rc.get("opacity"), 0.05, 1, 1.0), label=label,
                ))
                continue
            ref = str(rc.get("ref") or "")
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
            if isinstance(tr, dict) and tr.get("kind") in TRANSITIONS:
                transition = {"kind": tr["kind"], "duration": _num(tr.get("duration"), 0.1, 2.0, 0.5)}
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
                effects=effects, transition=transition,
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
