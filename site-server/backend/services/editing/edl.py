"""The Edit Decision List: what will happen, before anything happens. §8–§9.

An EDL is the plan in one object — which pieces of the timeline survive, which
filters run over them, what gets laid on top. It exists so that three separate
things can all look at the same edit:

* the human in «حالت پیشنهادی», who has to approve it before a frame is touched;
* the executor, which turns it into exactly one ffmpeg pass;
* the agent loop, which compares the plan it made with what came back out.

**Cuts are expressed as what is kept, not as what is removed.** Removals compose
badly — the second removal's timestamps mean something different once the first
one has shifted the timeline, and that off-by-a-few-seconds bug is invisible
until a customer watches the result. A keep-list has no ordering problem: it is
intersected, never sequenced.

**One pass, not a chain of renders.** Every filter here is concatenated into a
single filtergraph. Re-encoding a video four times to apply four corrections
costs four times the CPU and loses quality at every step, and the customer waits
for all of it.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

from services.video.ffmpeg import FFMPEG, VideoProcessingError, _run, probe_duration

from . import tools as tools_module
from .tools import AUDIO_FILTER, CUT, OVERLAY, VIDEO_FILTER, Operation

logger = logging.getLogger(__name__)

#: Anything shorter than this is not a clip, it is a glitch. Cutting a video
#: down to nothing is a failure mode worth a hard floor rather than a warning.
MIN_RESULT_SECONDS = 1.0


@dataclass
class Span:
    start: float
    end: float

    @property
    def length(self) -> float:
        return max(0.0, self.end - self.start)


@dataclass
class EDL:
    """One edit, fully described."""

    source: Path
    duration: float
    keep: list[Span] = field(default_factory=list)
    video_filters: list[str] = field(default_factory=list)
    audio_filters: list[str] = field(default_factory=list)
    overlays: list[str] = field(default_factory=list)
    #: The push-in, kept apart from the other filters because it has to sit
    #: between them and the overlays: after the picture corrections (which are
    #: time-scoped in source seconds) and before a subtitle is burnt in, or the
    #: zoom would crop the caption off the bottom of the frame.
    zoom: str = ""
    #: Playback speed factor; applied LAST on both streams (see render()).
    speed: float = 1.0
    #: The vidstabtransform fragment, applied FIRST so its transforms line up
    #: with the frames the detect pass measured.
    stabilize: str = ""
    #: Text the watermark draws, written to a file at render time.
    watermark_text: str = ""
    #: Where the detect pass wrote its transforms, once it has run.
    stabilize_file: Path | None = None
    #: Noise-removal strength (1.0 = natural), or 0 for none. Run as a pre-pass
    #: on the audio with the admin's denoise engine; see render().
    denoise: float = 0.0
    #: What the denoise pre-pass reported (engine, SNR before/after).
    denoise_report: dict = field(default_factory=dict)
    #: The shop the edit is for. Only the denoise pre-pass reads it — its
    #: data policy decides whether an engine that is not on this machine may
    #: be used on the shop's own recording.
    store: object = field(default=None, repr=False, compare=False)
    operations: list[Operation] = field(default_factory=list)
    refusals: list[str] = field(default_factory=list)
    has_audio: bool = True

    @property
    def result_seconds(self) -> float:
        return sum(span.length for span in self.keep)

    @property
    def removed_seconds(self) -> float:
        return max(0.0, self.duration - self.result_seconds)

    @property
    def cuts_anything(self) -> bool:
        return self.removed_seconds > 0.05

    def as_dict(self) -> dict:
        return {
            "duration": round(self.duration, 2),
            "result_seconds": round(self.result_seconds, 2),
            "removed_seconds": round(self.removed_seconds, 2),
            "keep": [{"start": round(s.start, 2), "end": round(s.end, 2)} for s in self.keep],
            "video_filters": (
                ([self.stabilize] if self.stabilize else [])
                + self.video_filters + ([self.zoom] if self.zoom else [])
                + ([f"setpts=PTS/{self.speed:g}"] if self.speed != 1.0 else [])
            ),
            "audio_filters": (
                ([f"denoise(strength={self.denoise:.2f})"] if self.denoise else [])
                + self.audio_filters + ([f"atempo={self.speed:g}"] if self.speed != 1.0 else [])
            ),
            "denoise": self.denoise_report,
            "overlays": self.overlays,
            "operations": [o.as_dict() for o in self.operations],
            "refusals": self.refusals,
        }

    def summary(self) -> str:
        """One line a shop owner can read, which is the only description most
        of them will ever look at."""
        parts = []
        if self.cuts_anything:
            parts.append(
                f"{self.removed_seconds:.0f} ثانیه برداشته می‌شود "
                f"({self.duration:.0f} → {self.result_seconds:.0f} ثانیه)"
            )
        titles = [o.spec.title for o in self.operations if o.spec.kind != CUT]
        if titles:
            parts.append("، ".join(dict.fromkeys(titles)))
        return " · ".join(parts) or "تغییری اعمال نمی‌شود"


# --------------------------------------------------------------- building


def _invert(removals: list[Span], duration: float) -> list[Span]:
    """Removals → the spans that survive them."""
    ordered = sorted((s for s in removals if s.length > 0), key=lambda s: s.start)
    merged: list[Span] = []
    for span in ordered:
        if merged and span.start <= merged[-1].end + 0.01:
            merged[-1].end = max(merged[-1].end, span.end)
        else:
            merged.append(Span(span.start, min(span.end, duration)))

    keep, cursor = [], 0.0
    for span in merged:
        if span.start > cursor + 0.01:
            keep.append(Span(cursor, span.start))
        cursor = max(cursor, span.end)
    if cursor < duration - 0.01:
        keep.append(Span(cursor, duration))
    return keep


def _windowed(fragment: str, params: dict) -> str:
    """Limit a picture filter to one shot when the operation names a window.

    `from_s`/`to_s` are SOURCE seconds: in render() the picture filters run
    after the cut `select` (which keeps source timestamps) and before the
    timestamps are renumbered, so a window measured on the upload still lands
    on the same shot after silences are cut out.
    """
    start = float(params.get("from_s", -1) if params.get("from_s") is not None else -1)
    end = float(params.get("to_s", -1) if params.get("to_s") is not None else -1)
    if start < 0 or end <= start:
        return fragment
    enable = f":enable='between(t,{_f(start)},{_f(end)})'"
    return ",".join(part + enable for part in fragment.split(","))


def build(
    source,
    operations: list[Operation],
    *,
    duration: float | None = None,
    has_audio: bool = True,
    silences: list[Span] | None = None,
    refusals: list[str] | None = None,
    subtitle_file=None,
    face_boxes=None,
    shape: dict | None = None,
) -> EDL:
    """Validated operations → an EDL ready to execute or to show a human.

    `silences` is supplied by the analysis layer: `trim_silence` says *that*
    silence should go, and the measurement of *where* it is belongs to the eye,
    not to the model. `shape` is the source's width/height/fps (also from the
    analysis layer); the zoom needs it to scale back to the frame.
    """
    source = Path(source)
    total = duration if duration is not None else probe_duration(source)
    edl = EDL(
        source=source, duration=total, operations=list(operations),
        refusals=list(refusals or []), has_audio=has_audio,
    )

    removals: list[Span] = []
    zooms: list[dict] = []
    fades: list[dict] = []
    transitions: list[dict] = []
    for operation in operations:
        tool = operation.spec
        params = operation.params

        if tool.key == "cut":
            removals.append(Span(float(params["start"]), float(params["end"])))
        elif tool.key == "trim_silence":
            keep_pad = float(params["keep"])
            minimum = float(params["min_silence"])
            for span in silences or []:
                if span.length < minimum:
                    continue
                # Leave a breath at each end. Cutting silence flush makes speech
                # sound clipped together, which is a worse artefact than the
                # pause it removed.
                removals.append(Span(span.start + keep_pad / 2, span.end - keep_pad / 2))
        elif tool.key == "zoom":
            # Refused rather than silently cropping somebody's head off — the
            # shop asked for a zoom, not for a beheading.
            from services.video import faces as face_finder

            safe, why = face_finder.safe_to_zoom(face_boxes or [], float(params["scale"]))
            if not safe:
                edl.refusals.append(why)
                continue
            if not shape or not shape.get("width") or not shape.get("height"):
                edl.refusals.append(
                    "زوم آرام به ابعاد ویدیو نیاز دارد و اندازه‌ی این ویدیو خوانده نشد"
                )
                continue
            zooms.append(dict(params))
        elif tool.key == "crop_format":
            # The ratio maths lives in `repurpose`, which owns it for §10 as
            # well. Two implementations of "crop to 9:16" drift, and the one
            # that drifts produces videos Instagram rejects.
            from services.video import repurpose

            fmt = repurpose.FORMATS_BY_KEY[str(params["format"])]
            edl.video_filters.append(
                repurpose.crop_filter(fmt.ratio, repurpose.centre_from_boxes(face_boxes)),
            )
        elif tool.key == "subtitle":
            if subtitle_file:
                # Moved off anyone's face. A caption across a mouth is the one
                # placement everybody notices, and bottom-centre — the default —
                # is exactly where a person in frame usually is.
                from services.video import faces as face_finder

                placed = dict(params)
                placed["position"] = face_finder.best_caption_position(
                    face_boxes or [], default=str(params["position"]),
                )
                edl.overlays.append(_subtitle_filter(placed, subtitle_file))
        elif tool.key == "fade":
            fades.append(dict(params))
        elif tool.key == "transition":
            transitions.append(dict(params))
        elif tool.key == "speed":
            edl.speed = float(params["factor"])
        elif tool.key == "denoise_audio":
            if has_audio:
                edl.denoise = max(0.3, min(2.5, float(params["amount"]) / 12.0))
        elif tool.key == "stabilize":
            # First in the chain, before any cut, so the detect pass and the
            # transform pass see the same frame sequence; see render().
            edl.stabilize = tool.build(params)
        elif tool.key == "watermark":
            edl.watermark_text = str(params.get("text", ""))
            edl.video_filters.append(tool.build(params))
        elif tool.kind == VIDEO_FILTER and tool.build:
            edl.video_filters.append(_windowed(tool.build(params), params))
        elif tool.kind == AUDIO_FILTER and tool.build:
            if has_audio:
                edl.audio_filters.append(tool.build(params))
        elif tool.kind == OVERLAY:
            logger.debug("Overlay %s had nothing to overlay", tool.key)

    edl.keep = _invert(removals, total) if removals else [Span(0.0, total)]
    removed = _removed_spans(edl.keep, total)

    # Fades are resolved against the real timeline: a fade-out with no time
    # ends at the end of what is KEPT, a fade-in starts where the kept video
    # starts. Each is limited to its own window with `enable=` — a bare
    # fade=out blacks every frame after it ends, which the old default of
    # at=0 turned into a video black from 0.4 s onwards.
    for fade in fades:
        edl.video_filters.append(_fade_filter(fade, edl.keep, total))
    for transition in transitions:
        edl.video_filters += _transition_filters(transition, removed, edl.refusals)

    if zooms:
        edl.zoom = _zoom_filter(zooms, face_boxes, shape)
    return edl


def _removed_spans(keep: list[Span], total: float) -> list[Span]:
    """The gaps between kept spans, in source time."""
    out, cursor = [], 0.0
    for span in sorted(keep, key=lambda s: s.start):
        if span.start > cursor + 0.01:
            out.append(Span(cursor, span.start))
        cursor = max(cursor, span.end)
    if cursor < total - 0.01:
        out.append(Span(cursor, total))
    return out


def _fade_filter(params: dict, keep: list[Span], total: float) -> str:
    where = str(params["where"])
    length = float(params["duration"])
    at = float(params.get("at", -1))
    first, last = keep[0], keep[-1]
    if where == "in":
        start = first.start if at < 0 else max(first.start, at)
    else:
        start = (last.end - length) if at < 0 else at
        start = max(first.start, min(start, last.end - length))
    return (
        f"fade=t={where}:st={_f(start)}:d={_f(length)}"
        f":enable='between(t,{_f(start)},{_f(start + length)})'"
    )


def _transition_filters(params: dict, removed: list[Span], refusals: list[str]) -> list[str]:
    """A fade-out into a fade-in around each join, each confined to its window.

    A cross-fade needs two inputs; after a keep-list has been concatenated
    there is only one stream, so this is what "soften that cut" can mean in a
    single pass. Windowed with `enable=`, because a bare fade=in blacks every
    frame before it and a bare fade=out every frame after it — the two
    together, unwindowed, rendered the entire clip black.
    """
    if not removed:
        refusals.append("گذار بدون برش معنا ندارد — اول برشی در برنامه باشد")
        return []
    length = float(params["duration"])
    half = length / 2
    at = float(params.get("at", -1))
    joins = removed if at < 0 else [min(removed, key=lambda s: abs(s.start - at))]
    out = []
    for gap in joins:
        out_start = max(0.0, gap.start - half)
        out.append(
            f"fade=t=out:st={_f(out_start)}:d={_f(half)}"
            f":enable='between(t,{_f(out_start)},{_f(gap.start)})'"
        )
        out.append(
            f"fade=t=in:st={_f(gap.end)}:d={_f(half)}"
            f":enable='between(t,{_f(gap.end)},{_f(gap.end + half)})'"
        )
    return out


#: Share of a zoom window spent ramping in, and again ramping out. The push-in
#: a viewer reads as deliberate is one that eases; a jump to full scale on the
#: first frame of the window reads as a cut.
ZOOM_RAMP = 0.35


def _f(value: float) -> str:
    return f"{float(value):.4f}".rstrip("0").rstrip(".") or "0"


def _zoom_filter(windows, faces_boxes=None, shape: dict | None = None) -> str:
    """A slow push-in over each window, and nothing outside them.

    Built on `zoompan`, because it is the one ffmpeg filter that can change the
    crop **per frame**: `crop`'s width and height are evaluated once at start
    (and it does not accept `enable` at all — the previous version failed the
    whole render with "Timeline ('enable' option) not supported with filter
    'crop'" whenever a plan contained a zoom). The output is scaled back to
    the source's own size, so the frame never changes dimensions — a zoom that
    did would break concatenation with every other segment.

    Each window ramps from 1× to its scale over the first `ZOOM_RAMP` of its
    length, holds, and ramps back over the last. Windows are combined with
    `max`, so two zooms never stack. Time is `it`, the INPUT timestamp: the
    seconds the model saw when it chose the window, unchanged by any `select`
    that dropped frames before this filter ran.

    Anchored on a face when there is one. An un-anchored zoom crops from the
    centre, and a person standing slightly off-centre loses an ear.

    Verified against a Pillow reference render: mean absolute difference of
    2 (of 255) inside the window, 0.4 outside it.
    """
    from services.video import faces as face_finder

    if isinstance(windows, dict):
        windows = [windows]
    windows = list(windows)
    biggest = max(float(w["scale"]) for w in windows)
    centre_x, centre_y = face_finder.zoom_window(faces_boxes or [], biggest)

    terms = []
    for window in windows:
        start, end = float(window["start"]), float(window["end"])
        scale = float(window["scale"])
        length = max(0.001, end - start)
        ramp = max(0.05, min(0.5, ZOOM_RAMP)) * length
        # 0→1 while ramping in, 1 while holding, 1→0 while ramping out.
        progress = (
            f"min(clip((it-{_f(start)})/{_f(ramp)}\\,0\\,1)\\,"
            f"clip(({_f(end)}-it)/{_f(ramp)}\\,0\\,1))"
        )
        terms.append(f"{_f(scale - 1)}*{progress}")
    zoom_expr = terms[0] if len(terms) == 1 else "max(" + "\\,".join(terms) + ")"

    width = int((shape or {}).get("width") or 0)
    height = int((shape or {}).get("height") or 0)
    fps = str((shape or {}).get("fps_text") or (shape or {}).get("fps") or "25")
    return (
        f"zoompan=z='1+{zoom_expr}'"
        f":x='(iw-iw/zoom)*{_f(centre_x)}':y='(ih-ih/zoom)*{_f(centre_y)}'"
        f":d=1:s={width}x{height}:fps={fps}"
    )


def _subtitle_filter(params: dict, subtitle_file) -> str:
    """The same builder `subtitles.burn_in` uses — one place for the font, the
    alignment codes and the size unit, so the editor and the burn-in step
    cannot drift apart."""
    from services.video import subtitles

    return subtitles.style_filter(
        subtitle_file, position=str(params["position"]), size_pct=float(params["size"]),
    )


# -------------------------------------------------------------- executing


def _select_expression(keep: list[Span]) -> str:
    return "+".join(f"between(t,{s.start:.3f},{s.end:.3f})" for s in keep)


def render(edl: EDL, out_path) -> Path:
    """Apply the whole EDL in a single pass.

    Refuses to produce a video shorter than MIN_RESULT_SECONDS. An edit that
    removed everything is always a mistake somewhere upstream — usually a silent
    audio track making every second look like a pause — and writing the
    zero-length file lets that mistake reach the customer.
    """
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    if edl.result_seconds < MIN_RESULT_SECONDS:
        raise VideoProcessingError(
            f"این تدوین از ویدیو فقط {edl.result_seconds:.1f} ثانیه باقی می‌گذارد — "
            "احتمالاً صدای ویدیو خوانده نشده و همه‌جا سکوت تشخیص داده شده است."
        )

    from services.video.ffmpeg import AUDIO_DELIVERY, VIDEO_DELIVERY, filter_path

    video_chain, audio_chain = [], []

    # Order, and why each thing sits where it does:
    #   1. stabilise — on the SOURCE frame sequence, the one the detect pass
    #      measured; after a cut the transform file would be misaligned.
    #   2. select/aselect — the cuts. Timestamps still carry the gaps.
    #   3. picture corrections, fades, zoom, overlays — all planned in SOURCE
    #      seconds, so they run while timestamps are still source time. Zoom
    #      before overlays, or a subtitle drawn first is cropped off.
    #   4. setpts/asetpts — close the gaps.
    #   5. speed — last, on both streams, so the re-stamp cannot cancel it and
    #      the audio keeps up with the picture.
    if edl.stabilize:
        transforms = Path(edl.source).parent / "transforms.trf"
        video_chain.append(edl.stabilize.replace(
            tools_module.STABILIZE_INPUT, filter_path(edl.stabilize_file or transforms),
        ))
    if edl.cuts_anything:
        expression = _select_expression(edl.keep)
        video_chain.append(f"select='{expression}'")
        # Whole AAC frames are the unit `aselect` drops; cutting the audio into
        # 48-sample pieces first makes the cut land where the video's does.
        audio_chain.append("asetnsamples=n=48:p=0")
        audio_chain.append(f"aselect='{expression}'")

    video_chain += edl.video_filters
    if edl.zoom:
        video_chain.append(edl.zoom)
    video_chain += edl.overlays
    audio_chain += edl.audio_filters

    if edl.cuts_anything:
        # After select, timestamps still carry the gaps. Without these the
        # output plays the kept frames at their original times and the video
        # freezes for the length of everything that was removed. (zoompan
        # already restamps its output contiguously; the setpts is then a no-op
        # and harmless.)
        video_chain.append("setpts=N/FRAME_RATE/TB")
        audio_chain.append("asetpts=N/SR/TB")

    if edl.speed != 1.0:
        video_chain.append(f"setpts=PTS/{edl.speed:g}")
        audio_chain.append(f"atempo={edl.speed:g}")

    # The watermark text travels through a file: drawtext's option parser
    # rejected '%' and mangled quotes, and a shop's «۵۰٪ تخفیف» was failing
    # the whole edit.
    textfile = None
    if edl.watermark_text and any(tools_module.WATERMARK_TEXTFILE in f for f in video_chain):
        import tempfile

        handle = tempfile.NamedTemporaryFile(
            "w", suffix=".txt", delete=False, encoding="utf-8",
        )
        handle.write(edl.watermark_text[:80])
        handle.close()
        textfile = Path(handle.name)
        video_chain = [
            f.replace(tools_module.WATERMARK_TEXTFILE, filter_path(textfile)) for f in video_chain
        ]

    command = [FFMPEG, "-y", "-i", str(edl.source)]

    # Noise removal runs BEFORE the render, on the whole audio track, with the
    # admin's engine (DeepFilterNet, RNNoise, …) — those are separate programs,
    # not ffmpeg filters. The cleaned track then comes in as a second input and
    # goes through the same cuts and filters as the original would have, so
    # timing is untouched.
    audio_input = "0:a"
    if edl.denoise and edl.has_audio:
        from services.audio import denoise as denoiser

        try:
            cleaned = denoiser.clean(
                edl.source, out.parent / "denoised.wav", out.parent / "denoise_work",
                store=edl.store, strength=edl.denoise,
            )
            command += ["-i", str(cleaned.path)]
            audio_input = "1:a"
            edl.denoise_report = cleaned.as_dict()
        except denoiser.DenoiseError as exc:
            logger.info("Denoise pre-pass failed: %s", exc)
            edl.refusals.append(f"حذف نویز انجام نشد: {exc}"[:300])

    # Most filters are a plain comma chain, which `-vf` takes. One is not:
    # blurring a region has to split the stream, blur one copy and overlay it
    # back, and that needs named pads — which `-vf` cannot express at all. So
    # the whole graph moves to `-filter_complex` when any filter uses them,
    # rather than keeping a second rendering path for one tool.
    complex_graph = any("[" in f for f in video_chain)
    if complex_graph:
        graph = f"[0:v]{','.join(video_chain)}[vout]"
        if audio_chain and edl.has_audio:
            graph += f";[{audio_input}]{','.join(audio_chain)}[aout]"
        command += ["-filter_complex", graph, "-map", "[vout]"]
        if edl.has_audio:
            command += ["-map", "[aout]" if audio_chain else audio_input]
    else:
        if video_chain:
            command += ["-vf", ",".join(video_chain)]
        if audio_input != "0:a":
            command += ["-map", "0:v", "-map", audio_input]
        if audio_chain and edl.has_audio:
            command += ["-af", ",".join(audio_chain)]
    if not edl.has_audio:
        command += ["-an"]
    command += VIDEO_DELIVERY
    if edl.has_audio:
        command += AUDIO_DELIVERY
    command += [str(out)]

    try:
        _run(command)
    finally:
        if textfile is not None:
            try:
                textfile.unlink()
            except OSError:
                pass
    if not out.exists() or out.stat().st_size == 0:
        raise VideoProcessingError(f"تدوین خروجی نداد: {out}")
    return out


def needs_stabilization_pass(edl: EDL) -> bool:
    """vidstabtransform reads a file the detect pass writes."""
    return bool(edl.stabilize)


def detect_stabilization(source, work_dir, edl: EDL | None = None) -> Path:
    """First pass of stabilisation: measure the shake, write the transforms.

    The result path goes through `filter_path`: a Windows drive colon inside
    `result=C:/...` was being read as the option name `C`, so the detect pass
    failed on every video and the agent dropped stabilisation each time with a
    refusal — the tool had never once run here.
    """
    from services.video.ffmpeg import filter_path

    work = Path(work_dir)
    work.mkdir(parents=True, exist_ok=True)
    transforms = work / "transforms.trf"
    _run([
        FFMPEG, "-y", "-i", str(source),
        "-vf", f"vidstabdetect=shakiness=5:accuracy=15:result={filter_path(transforms)}",
        "-f", "null", "-",
    ])
    if edl is not None:
        edl.stabilize_file = transforms
    return transforms
