"""Subtitles. §8 — «زیرنویس خودکار، با زمان‌بندی هر کلمه».

**For our own videos, subtitles are free, and that is the whole trick here.**

The usual way to subtitle a video is speech-to-text: run a model over the audio,
get words back, hope it heard «نایکی» and not «نای کی». But for a video *we*
made, we already know exactly what was said — it is the narration we wrote and
handed to the voice engine. There is nothing to recognise. Running ASR over our
own narration to recover text we have in a database column would be paying a
model to tell us something we told it.

So this module does the one part that is genuinely unknown: **where** each line
falls in time. And it gets that from the waveform rather than guessing:

* Split the narration into readable lines at the places Persian punctuation
  already marks.
* Find the real pauses inside the spoken audio — the same envelope the audio QC
  module measures.
* Snap the line boundaries to those pauses.

When the audio cannot be read, it falls back to splitting the scene's duration
in proportion to line length — and **says in the result that it did**, because a
proportional guess presented as measured timing is a subtitle that drifts and
nobody knows why.

**Word-level timing comes from Whisper, and only the timing.** When the model
is installed, `cues_from_transcript` runs it over our own narration audio and
then *throws the transcript away*: our text is already correct, and a
mis-recognised «نایکی» that still lands at the right second is worth more than
a transcript we would have to correct. See `services.audio.transcribe.align`.

**Uploaded customer video needs the transcript itself.** There we genuinely do
not know what was said — that path is `from_transcript`, and every uncertain
line is marked rather than presented in the same typeface as a fact.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

def word_level_available() -> bool:
    """Whether per-word timing is possible right now.

    True once Whisper is installed. Asked rather than hard-coded because the
    honest answer changes with the environment, and a panel that promises
    karaoke timing on a box without the model is lying to the shop.
    """
    from services.audio import transcribe

    return transcribe.available()[0]

#: Longer than this and a line stops being readable in the two seconds it is on
#: screen. The number is on the low side for Persian, where the script is dense.
MAX_LINE = 42

#: Two lines is the ceiling every subtitle guideline agrees on. Three covers the
#: frame and people stop watching the video to read.
MAX_LINES = 2

#: A cue shorter than this flashes. One longer than that outstays a short scene.
MIN_CUE = 0.8
MAX_CUE = 7.0

#: Persian sentence and clause enders. The comma matters as much as the full
#: stop — Persian narration is written in long sentences with clause breaks, and
#: splitting only on «.» gives lines nobody can read.
_BREAKS = re.compile(r"(?<=[.!?؟…؛:،])\s+")


@dataclass
class Cue:
    index: int
    start: float
    end: float
    text: str

    @property
    def seconds(self) -> float:
        return max(0.0, self.end - self.start)


def _stamp(seconds: float) -> str:
    seconds = max(0.0, seconds)
    hours, rest = divmod(int(seconds), 3600)
    minutes, secs = divmod(rest, 60)
    millis = int(round((seconds - int(seconds)) * 1000))
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def wrap(text: str, width: int = MAX_LINE) -> str:
    """Break one cue across at most two lines, on a space.

    Never mid-word: Persian joins letters, and a word split across two subtitle
    lines is unreadable in a way an English one is not.
    """
    words = text.split()
    lines, current = [], ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if len(candidate) <= width or not current:
            current = candidate
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)

    if len(lines) <= MAX_LINES:
        return "\n".join(lines)
    # Too long for two lines: split near the middle instead of truncating.
    # Losing half a sentence is worse than a slightly wide line.
    middle = len(words) // 2
    return "\n".join([" ".join(words[:middle]), " ".join(words[middle:])])


def phrases(text: str) -> list[str]:
    """Narration → the lines that will appear, in order."""
    cleaned = " ".join((text or "").split())
    if not cleaned:
        return []

    parts = [p.strip() for p in _BREAKS.split(cleaned) if p.strip()]
    out: list[str] = []
    for part in parts:
        # A clause that is still far too long gets split on spaces rather than
        # shown as a wall of text nobody can read in two seconds.
        while len(part) > MAX_LINE * MAX_LINES:
            head, _, tail = part[: MAX_LINE * MAX_LINES].rpartition(" ")
            if not head:
                break
            out.append(head)
            part = tail + part[MAX_LINE * MAX_LINES :]
        if part.strip():
            out.append(part.strip())
    return out


# ------------------------------------------------------------------ timing


def pauses_in(audio_path, work_dir, *, want: int) -> list[float]:
    """The `want` longest silences inside speech, as seconds from the start.

    Reuses the audio QC envelope on purpose: its silence threshold is relative
    to the clip's own speech level, so a quietly recorded narration does not
    come back as one long pause.
    """
    if want <= 0:
        return []
    from services.audio import qc

    try:
        samples, rate = qc.decode(audio_path, work_dir)
    except Exception as exc:  # noqa: BLE001 — a missing ffmpeg is not a crash
        logger.info("Could not read %s for timing: %s", audio_path, exc)
        return []
    if not samples:
        return []

    levels = qc._windows(samples, rate)
    if not levels:
        return []
    floor = qc.silence_floor(levels)
    window = qc.WINDOW_MS / 1000

    runs = qc._runs_of_silence(levels, floor)
    if not runs:
        return []

    # Longest first, because the longest pause inside a narration is almost
    # always the boundary the writer intended.
    longest = sorted(runs, key=lambda run: run[1], reverse=True)[:want]
    # The middle of the gap, so a cue neither clips the word before nor waits
    # through the whole pause before the word after.
    return sorted((start + length / 2) * window for start, length in longest)


def _proportional(lines: list[str], start: float, end: float) -> list[float]:
    """Boundaries split by line length. The fallback, and it is honest about it."""
    total = sum(len(line) for line in lines) or 1
    span = max(0.0, end - start)
    marks, running = [], 0
    for line in lines[:-1]:
        running += len(line)
        marks.append(start + span * running / total)
    return marks


def cues_for(
    text: str,
    start: float,
    end: float,
    *,
    audio_path=None,
    work_dir=None,
    first_index: int = 1,
) -> tuple[list[Cue], bool]:
    """Lines → timed cues. Returns (cues, measured).

    `measured` is False when the boundaries came from line length rather than
    from the audio. The caller reports it: a proportional guess presented as
    measured timing produces subtitles that drift and nobody knows why.
    """
    lines = phrases(text)
    if not lines:
        return [], True
    if len(lines) == 1:
        return [Cue(first_index, start, end, wrap(lines[0]))], True

    marks: list[float] = []
    measured = False
    if audio_path is not None and work_dir is not None:
        found = pauses_in(audio_path, work_dir, want=len(lines) - 1)
        if len(found) == len(lines) - 1:
            marks = [start + offset for offset in found]
            measured = True
    if not marks:
        marks = _proportional(lines, start, end)

    edges = [start, *marks, end]
    # Monotonic and inside the scene, whatever the pause detection returned. A
    # cue that starts before the one before it ended makes a player show both.
    for i in range(1, len(edges)):
        edges[i] = min(max(edges[i], edges[i - 1] + 0.05), end)

    cues = []
    for i, line in enumerate(lines):
        cues.append(Cue(first_index + i, edges[i], edges[i + 1], wrap(line)))
    return cues, measured


def _join(first: Cue, second: Cue) -> Cue:
    first.end = second.end
    first.text = wrap(f"{first.text} {second.text}".replace("\n", " "))
    return first


def tidy(cues: list[Cue]) -> list[Cue]:
    """Merge cues too short to read, and cap ones that outstay their welcome.

    A short cue joins whichever neighbour it can: backwards normally, forwards
    when it is the first one. The forward case is the one that is easy to miss —
    a 0.3-second flash at the very start has no predecessor to merge into, and
    an implementation that only looks backwards leaves it on screen exactly as
    long as it was.
    """
    if not cues:
        return []

    merged: list[Cue] = []
    pending: Cue | None = None

    for cue in cues:
        if pending is not None:
            cue = _join(pending, cue)
            pending = None

        if cue.seconds < MIN_CUE:
            if merged and merged[-1].seconds < MAX_CUE:
                _join(merged[-1], cue)
                continue
            # Nothing behind it to join, so it waits for the next line.
            pending = cue
            continue
        merged.append(cue)

    if pending is not None:
        # A short final cue with nothing after it: stretch rather than flash,
        # since there is no neighbour left to carry it.
        pending.end = max(pending.end, pending.start + MIN_CUE)
        merged.append(pending)

    for cue in merged:
        if cue.seconds > MAX_CUE:
            cue.end = cue.start + MAX_CUE

    for position, cue in enumerate(merged, start=1):
        cue.index = position
    return merged


# ------------------------------------------------------------------ output


def to_srt(cues: list[Cue]) -> str:
    """SRT, because ffmpeg's `subtitles` filter and every platform read it."""
    blocks = []
    for cue in cues:
        blocks.append(
            f"{cue.index}\n"
            f"{_stamp(cue.start)} --> {_stamp(cue.end)}\n"
            f"{cue.text}\n"
        )
    return "\n".join(blocks)


def write_srt(cues: list[Cue], out_path) -> Path:
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    # UTF-8 with a BOM: some players still guess the encoding of a subtitle
    # file, and a Persian subtitle guessed as cp1256 is unreadable mojibake.
    out.write_text(to_srt(cues), encoding="utf-8-sig")
    return out


# --------------------------------------------------------------- the whole


def build_for_scenes(scenes, work_dir, *, clip_for=None, duration_for=None) -> dict:
    """Subtitles for a whole video we made ourselves.

    `scenes` is anything with `.index`, `.narration` and `.duration`.
    `clip_for(scene)` gives that scene's narration audio (for real timing) and
    `duration_for(scene)` its real length; both optional.
    """
    work = Path(work_dir)
    work.mkdir(parents=True, exist_ok=True)

    cues: list[Cue] = []
    at = 0.0
    measured_all = True
    silent = 0

    for scene in scenes:
        length = float(duration_for(scene) if duration_for else scene.duration)
        text = (scene.narration or "").strip()
        if not text:
            # A scene with no narration gets no subtitle. Captioning silence
            # with the visual prompt would put our own stage directions on the
            # customer's video.
            silent += 1
            at += length
            continue

        clip = clip_for(scene) if clip_for else None
        scene_cues, measured = cues_for(
            text, at, at + length,
            audio_path=clip, work_dir=work, first_index=len(cues) + 1,
        )
        cues += scene_cues
        measured_all = measured_all and measured
        at += length

    cues = tidy(cues)
    return {
        "cues": cues,
        "count": len(cues),
        "seconds": round(at, 2),
        "silent_scenes": silent,
        # The honest label. False means the boundaries came from line length,
        # not from listening.
        "measured": measured_all and bool(cues),
        "word_level": word_level_available(),
        "note": (
            "" if measured_all or not cues else
            "زمان‌بندی خطوط از روی طول متن تخمین زده شد، نه از روی خود صدا — "
            "چون صدا خوانده نشد. ممکن است کمی جلو یا عقب باشد."
        ),
    }


def transcribe_needed(upload) -> str:
    """Why an uploaded video cannot be subtitled the cheap way.

    Stated as a sentence rather than an empty result, because the reason is the
    useful part: a shop can record narration in the panel instead, and get
    perfect subtitles without any of this.
    """
    return (
        "این ویدیو را خودتان گرفته‌اید، پس ما نمی‌دانیم در آن چه گفته شده و "
        "برای زیرنویسش به تبدیل گفتار به متن نیاز است که هنوز نداریم. "
        "برای ویدیوهایی که خودمان می‌سازیم زیرنویس رایگان است، چون متنش را "
        "از اول خودمان نوشته‌ایم."
    )


# ------------------------------------------------------- word-level timing


def cues_from_transcript(known_text: str, transcript, *, start: float = 0.0,
                         first_index: int = 1) -> list[Cue]:
    """Our own text, on Whisper's clock. The best timing we can produce.

    The transcript is used and discarded: we wrote the narration, so the words
    are not in question — only when each one was said. `align` carries our
    spelling across onto the model's timings, which is why a brand name Whisper
    mangles still ends up in the right place with the right letters.
    """
    from services.audio import transcribe as asr

    words = asr.align(known_text, transcript)
    if not words:
        return []

    cues = []
    for offset, (begin, end, text) in enumerate(
        asr.cues_from_words(words, max_chars=MAX_LINE * MAX_LINES,
                            max_seconds=MAX_CUE)
    ):
        cues.append(Cue(first_index + offset, start + begin, start + end, wrap(text)))
    return cues


def from_transcript(transcript, *, first_index: int = 1) -> dict:
    """Subtitles for video we did not write — the shop filmed it themselves.

    Here the words *are* in question, so uncertain segments are carried through
    rather than smoothed over. A shop can fix a word we got wrong; they cannot
    fix a line we quietly deleted.
    """
    cues: list[Cue] = []
    uncertain: list[int] = []

    for segment in transcript.segments:
        text = (segment.text or "").strip()
        if not text:
            continue
        if segment.words:
            from services.audio import transcribe as asr

            pieces = asr.cues_from_words(
                segment.words, max_chars=MAX_LINE * MAX_LINES, max_seconds=MAX_CUE,
            )
        else:
            pieces = [(segment.start, segment.end, text)]

        for begin, end, line in pieces:
            cues.append(Cue(first_index + len(cues), begin, end, wrap(line)))
            if segment.uncertain:
                uncertain.append(cues[-1].index)

    cues = tidy(cues)
    return {
        "cues": cues,
        "count": len(cues),
        "seconds": round(cues[-1].end if cues else 0.0, 2),
        "silent_scenes": 0,
        # Heard, not written. The most reliable timing there is for this kind
        # of video, because it came from the audio itself.
        "measured": True,
        "word_level": any(s.words for s in transcript.segments),
        "uncertain_lines": uncertain,
        "note": (
            f"{len(uncertain)} خط با اطمینان پایین شنیده شد و علامت خورده — "
            "قبل از انتشار نگاهشان کنید."
            if uncertain else ""
        ),
    }


# ---------------------------------------------------------------- switches


def subtitles_wanted(video, store) -> bool:
    """Does this video get subtitles?

    Three states, not two. `None` on the video means "whatever the shop
    decided", and that is what makes a per-video switch usable: a shop sets the
    default once and only touches the ones that differ. A two-state flag would
    force a decision on every single video, and people answer those by
    accepting whatever is in front of them.
    """
    own = getattr(video, "subtitles_enabled", None)
    if own is not None:
        return bool(own)
    try:
        return bool(store.profile.subtitles_by_default)
    except Exception:  # noqa: BLE001 — no profile row yet
        return True


def subtitles_burned(video, store) -> bool:
    """Burned into the picture, or a separate file?

    Burned-in survives every platform that strips subtitle tracks — which is
    most of them for short-form video. A file stays editable and can be turned
    off by the viewer. Neither is right for everyone, so it is a setting.
    """
    own = getattr(video, "subtitles_burned", None)
    if own is not None:
        return bool(own)
    try:
        return bool(store.profile.subtitles_burned_by_default)
    except Exception:  # noqa: BLE001
        return False


#: libass reads `force_style` Alignment in the legacy SSA numbering (measured
#: on the bundled build): 1/2/3 bottom left/centre/right, 9/10/11 middle,
#: 5/6/7 top. The old code used Alignment=2 for every position and moved the
#: text with MarginV — which put "top" LOWER than "bottom", so moving a caption
#: off somebody's face changed nothing.
_ALIGNMENT = {"bottom": 2, "middle": 10, "top": 6}

#: force_style FontSize is in libass's own 288-line coordinate space, so a
#: size given as a percentage of the frame height is 2.88 units per percent.
_LIBASS_LINES = 288.0

#: Default caption height as a share of the frame. Two lines at 5.5 % each
#: with the margin still leave four fifths of a reel visible.
DEFAULT_SIZE_PCT = 5.5


def style_filter(srt_path, *, position: str = "bottom", size_pct: float = DEFAULT_SIZE_PCT) -> str:
    """The one `subtitles=` filter string every burn-in path uses.

    Persian needs a font that has the glyphs: fontconfig on Windows has no
    configuration, and without `fontsdir` the fallback face draws boxes. The
    bundled Vazirmatn is the same face the poster text is set in.
    """
    from services.editing.tools import FONT_DIR
    from services.video.ffmpeg import filter_path

    size = max(6, int(round(float(size_pct) * _LIBASS_LINES / 100.0)))
    alignment = _ALIGNMENT.get(str(position), 2)
    style = (
        f"FontName=Vazirmatn,FontSize={size},Alignment={alignment},MarginV=40,"
        # An outline, not a box: Persian subtitles sit over footage of every
        # brightness, and white-on-white is unreadable in exactly the frames
        # that matter.
        "Outline=2,Shadow=0,BorderStyle=1,PrimaryColour=&H00FFFFFF"
    )
    return (
        f"subtitles={filter_path(srt_path)}:fontsdir={filter_path(FONT_DIR)}"
        f":force_style='{style}'"
    )


def burn_in(video_path, srt_path, out_path, *, position: str = "bottom",
            size: float = DEFAULT_SIZE_PCT, avoid: list | None = None):
    """Burn the subtitle into the picture.

    `avoid` is the boxes the text must not land on — faces and the product, from
    `services.video.faces`. A subtitle across someone's mouth is the one
    placement everybody notices, and it is also the default position, so this is
    worth the extra pass. `size` is a percentage of the frame height.
    """
    from pathlib import Path as _Path

    from services.video.ffmpeg import (
        AUDIO_DELIVERY, FFMPEG, VIDEO_DELIVERY, VideoProcessingError, _run,
    )

    out = _Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    if avoid:
        from services.video import faces

        position = faces.best_caption_position(avoid, default=position)

    # Sizes handed in from before the unit change were libass units (42);
    # anything above the percentage range is one of those.
    size_pct = float(size) / _LIBASS_LINES * 100.0 if float(size) > 20 else float(size)

    _run([
        FFMPEG, "-y", "-i", str(video_path),
        "-vf", style_filter(srt_path, position=position, size_pct=size_pct),
        *AUDIO_DELIVERY, *VIDEO_DELIVERY,
        str(out),
    ])
    if not out.exists() or out.stat().st_size == 0:
        raise VideoProcessingError("زیرنویس روی تصویر ننشست")
    return out
