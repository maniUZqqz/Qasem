"""Multi-track timeline and proxy editing. §23.4

The EDL in `edl.py` describes one operation applied to one source. That is the
right shape for «کوتاهش کن، روشنش کن» and the wrong shape the moment a shop
wants two clips side by side, a logo in the corner for the last five seconds,
and music under all of it. This is that second shape.

**A timeline is tracks, and a track is clips on a clock.** Nothing here renders:
it produces an ffmpeg filtergraph, and `edl.render` still does the work. Keeping
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
"""
from __future__ import annotations

import logging
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

    @property
    def source_length(self) -> float:
        return (self.end - self.start) if self.end is not None else 0.0

    @property
    def ends_at(self) -> float:
        return self.at + self.source_length

    def validate(self, index: int) -> None:
        where = self.label or f"قطعه‌ی {index + 1}"
        if self.at < 0:
            raise TimelineError(f"{where}: زمان شروع منفی است.")
        if self.end is not None and self.end <= self.start:
            raise TimelineError(
                f"{where}: پایان ({self.end:g}) قبل از شروع ({self.start:g}) است."
            )
        if not 0 <= self.opacity <= 1:
            raise TimelineError(f"{where}: شفافیت باید بین ۰ و ۱ باشد.")
        for name, value in (("x", self.x), ("y", self.y)):
            if not 0 <= value <= 1:
                raise TimelineError(f"{where}: {name} باید بین ۰ و ۱ باشد.")
        if not 0 < self.width <= 1 or not 0 < self.height <= 1:
            raise TimelineError(f"{where}: اندازه باید بین ۰ و ۱ باشد.")
        if self.x + self.width > 1.001 or self.y + self.height > 1.001:
            raise TimelineError(f"{where}: از لبه‌ی کادر بیرون می‌زند.")


@dataclass
class Track:
    """Clips that share a layer. Higher index draws on top."""

    kind: str = "video"          # "video" or "audio"
    name: str = ""
    clips: list[Clip] = field(default_factory=list)
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
        return {
            "tracks": [
                {
                    "kind": t.kind, "name": t.name, "muted": t.muted,
                    "clips": [
                        {
                            "source": c.source, "at": round(c.at, 2),
                            "start": round(c.start, 2),
                            "end": round(c.end, 2) if c.end is not None else None,
                            "opacity": c.opacity, "label": c.label,
                            "x": c.x, "y": c.y,
                            "width": c.width, "height": c.height,
                        }
                        for t2 in [t] for c in t2.clips
                    ],
                }
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


def build_filtergraph(timeline: Timeline) -> tuple[list[str], str]:
    """A timeline → (input files, filter_complex).

    Returned rather than executed, so the panel can show the shop the
    arrangement before anything is encoded.
    """
    timeline.validate()

    inputs: list[str] = []
    parts: list[str] = []
    index_of: dict[int, int] = {}

    for track in timeline.tracks:
        for clip in track.clips:
            index_of[id(clip)] = len(inputs)
            inputs.append(clip.source)

    # The canvas. Every video clip is composited onto it, which means a gap in
    # the base track is black rather than whatever the renderer felt like.
    parts.append(
        f"color=c=black:s={timeline.width}x{timeline.height}"
        f":r={timeline.fps}:d={timeline.length:.3f}[base]"
    )

    current = "base"
    step = 0
    for track in timeline.tracks:
        if track.kind != "video":
            continue
        for clip in track.clips:
            source = index_of[id(clip)]
            label = f"v{step}"
            trimmed = f"t{step}"
            end = clip.end if clip.end is not None else clip.start
            # `setpts` moves the clip so that its first frame carries the
            # timestamp `at` — the same shift `adelay` gives the audio below.
            # Without it the clip's own clock starts at 0, and by the time the
            # overlay window opens at `at` the input has already played past
            # (a two-second clip placed at 3 s never appeared at all).
            parts.append(
                f"[{source}:v]trim={clip.start:.3f}:{end:.3f},"
                f"setpts=PTS-STARTPTS+{clip.at:.3f}/TB,"
                f"scale={int(timeline.width * clip.width)}:"
                f"{int(timeline.height * clip.height)}"
                + (f",format=yuva420p,colorchannelmixer=aa={clip.opacity:.3f}"
                   if clip.opacity < 1 else "")
                + f"[{trimmed}]"
            )
            parts.append(
                f"[{current}][{trimmed}]overlay="
                f"x={int(timeline.width * clip.x)}:"
                f"y={int(timeline.height * clip.y)}:"
                f"enable='between(t,{clip.at:.3f},{clip.ends_at:.3f})':"
                f"eof_action=pass[{label}]"
            )
            current = label
            step += 1

    audio_labels = []
    step = 0
    for track in timeline.tracks:
        if track.kind != "audio" or track.muted:
            continue
        for clip in track.clips:
            source = index_of[id(clip)]
            label = f"a{step}"
            end = clip.end if clip.end is not None else clip.start
            parts.append(
                f"[{source}:a]atrim={clip.start:.3f}:{end:.3f},"
                f"asetpts=PTS-STARTPTS,"
                f"adelay={int(clip.at * 1000)}|{int(clip.at * 1000)}"
                + (f",volume={clip.opacity:.3f}" if clip.opacity < 1 else "")
                + f"[{label}]"
            )
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
    return inputs, ";".join(parts)


def render(timeline: Timeline, out_path) -> Path:
    """Encode the arrangement."""
    from services.video.ffmpeg import FFMPEG, VideoProcessingError, _run

    inputs, graph = build_filtergraph(timeline)
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    from services.video.ffmpeg import AUDIO_DELIVERY, VIDEO_DELIVERY

    command = [FFMPEG, "-y"]
    for source in inputs:
        command += ["-i", str(source)]
    command += ["-filter_complex", graph, "-map", "[vout]"]
    if "[aout]" in graph:
        command += ["-map", "[aout]", *AUDIO_DELIVERY]
    command += [*VIDEO_DELIVERY, str(out)]
    _run(command)
    if not out.exists() or out.stat().st_size == 0:
        raise VideoProcessingError("تایم‌لاین رندر نشد")
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


def make_proxy(source, out_path) -> Path:
    """A small stand-in for editing decisions.

    **The frame rate is deliberately not changed.** A proxy at a different
    timebase makes a cut at 12.40 seconds land on a different frame in the
    proxy than in the original — so the shop approves one video and exports a
    subtly different one, and the difference only appears on the final render.
    Resolution is the only thing given up.
    """
    from services.video.ffmpeg import FFMPEG, VideoProcessingError, _run

    worth_it, why = needs_proxy(source)
    if not worth_it:
        raise TimelineError(why)

    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    _run([
        FFMPEG, "-y", "-i", str(source),
        # -2 keeps the width even (h264 requires it) and preserves the aspect.
        "-vf", f"scale=-2:{PROXY_HEIGHT}",
        "-c:v", "libx264", "-preset", PROXY_PRESET, "-crf", str(PROXY_CRF),
        "-c:a", "aac", "-b:a", "96k",
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
