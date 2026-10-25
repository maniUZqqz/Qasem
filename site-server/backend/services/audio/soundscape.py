"""Everything in a video that is not somebody talking.

A product video with a voice and nothing else sounds like a slideshow. Real
footage has a place in it: rain on the window behind the coat, the street
outside the café, the click of the lamp switch, heels on a wooden floor. This
module gives a generated video that layer — chosen per scene, placed in time,
and mixed well under the voice.

**Real recordings first.** The sounds come from a local library of real
field recordings (`SoundClip`), filled once from Freesound's CC0 catalogue by
`manage.py audio_setup --library` and then fully offline. CC0 means no
attribution and no licence risk on the shop's published ad; the source and
creator are still kept on every clip. Where the library has nothing for a
category, the next engine in the admin's order takes over: sounds made with
code (only the noise-like ones code can make well — room tone, rain, wind,
waves, a whoosh), a live Openverse search that is imported into the library
so it is offline next time, or ElevenLabs' sound-effect generator.

**Which sound goes where** is decided per scene: the script model names an
ambience and any effects when it writes the scene; when it did not, the
scene's own words are matched against each category's keywords. Two scenes
in a row with the same ambience share one continuous bed — rain does not
restart at every cut.

**Loudness is a hierarchy, not a set of gains.** Every layer is brought to
its own loudness target from the admin (`AudioMix`): the voice on top, the
effects under it, the ambience under those, the shop's own background lowest.
The beds then duck under the voice while it speaks. The sounds should be felt
more than heard; a listener who notices the rain has been handed too much.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from services.video.ffmpeg import FFMPEG, VideoProcessingError, _run, probe_duration

from . import engines as engine_registry

logger = logging.getLogger(__name__)

#: Every library clip is normalised to this at import, so a clip's gain at mix
#: time is simply (target − REFERENCE_LUFS).
REFERENCE_LUFS = -23.0

BED = "bed"
SPOT = "spot"


@dataclass(frozen=True)
class SoundKind:
    key: str
    label: str
    kind: str
    #: English search phrases for Freesound/Openverse and ElevenLabs prompts.
    queries: tuple[str, ...]
    #: English words in a scene's prompt that call for this sound.
    keywords: tuple[str, ...]
    #: Longest a spot effect plays. Beds loop for as long as needed.
    max_seconds: float = 4.0
    procedural: str = ""


CATALOGUE: dict[str, SoundKind] = {k.key: k for k in (
    # ---- ambience beds ------------------------------------------------
    SoundKind("room_tone", "اتاق آرام", BED, ("room tone quiet interior", "quiet room ambience"),
              ("room", "interior", "indoor", "studio", "home", "living room", "bedroom", "shelf",
               "table", "desk", "minimalist"), procedural="room_tone"),
    SoundKind("rain", "باران", BED, ("rain ambience", "light rain", "rain on window"),
              ("rain", "rainy", "raindrop", "storm", "umbrella", "wet", "drizzle"), procedural="rain"),
    SoundKind("wind", "باد", BED, ("gentle wind ambience", "wind blowing"),
              ("wind", "windy", "breeze", "desert", "mountain", "field", "hill"), procedural="wind"),
    SoundKind("ocean", "دریا و موج", BED, ("ocean waves beach", "sea waves"),
              ("beach", "sea", "ocean", "wave", "shore", "coast", "seaside", "sand"), procedural="ocean"),
    SoundKind("forest", "طبیعت و پرنده", BED, ("forest birds ambience", "birdsong morning"),
              ("forest", "tree", "garden", "park", "nature", "bird", "spring", "grass", "flower",
               "outdoor", "leaves")),
    SoundKind("city", "خیابان شهر", BED, ("city street ambience", "urban traffic ambience"),
              ("city", "street", "road", "urban", "traffic", "sidewalk", "downtown", "car")),
    SoundKind("cafe", "کافه", BED, ("cafe ambience", "coffee shop ambience"),
              ("cafe", "coffee shop", "restaurant", "bistro", "barista", "diner")),
    SoundKind("kitchen", "آشپزخانه", BED, ("kitchen ambience cooking", "cooking sizzle"),
              ("kitchen", "cooking", "chef", "pan", "stove", "bake", "oven")),
    SoundKind("shop", "فروشگاه", BED, ("shopping mall ambience", "store ambience"),
              ("shop", "store", "boutique", "mall", "retail", "market", "showroom")),
    SoundKind("office", "دفتر کار", BED, ("office ambience",),
              ("office", "workspace", "meeting", "coworking")),
    SoundKind("night", "شب", BED, ("night ambience crickets",),
              ("night", "evening", "moon", "crickets", "starry", "dusk")),
    SoundKind("fireplace", "شومینه", BED, ("fireplace crackling", "fire crackling", "campfire crackling"),
              ("fireplace", "campfire", "fire", "cozy", "cabin", "winter")),
    SoundKind("water", "آب روان", BED, ("stream water flowing", "river ambience"),
              ("river", "stream", "waterfall", "fountain", "creek")),
    # ---- spot effects ------------------------------------------------
    # Keywords are ACTIONS, not nouns. A scene that shows a lamp is not a scene
    # where somebody switches it on, and a shoe product shot is not a runway
    # walk; noun keywords put a click or a clatter on nearly every scene.
    SoundKind("footsteps", "قدم زدن", SPOT, ("footsteps walking", "footsteps on floor"),
              ("walks", "walking", "strolls", "strolling", "walks in", "walks toward"), 4.0),
    SoundKind("heels", "قدم با کفش پاشنه‌دار", SPOT, ("high heels footsteps",),
              ("runway", "catwalk", "walks in heels", "struts"), 4.0),
    SoundKind("door", "در", SPOT, ("door open close",),
              ("opens the door", "door opens", "door closes", "closes the door", "doors open", "doors close"), 2.0),
    SoundKind("whoosh", "ووش (گذار)", SPOT, ("whoosh transition swoosh",),
              ("whoosh", "swipe", "whip pan", "spins", "sweeps"), 1.2, procedural="whoosh"),
    SoundKind("camera", "شاتر دوربین", SPOT, ("camera shutter click",),
              ("photographer", "photo shoot", "takes a photo", "takes a picture", "shutter"), 1.0),
    SoundKind("cloth", "خش‌خش پارچه", SPOT, ("cloth fabric rustle",),
              ("folds", "unfolds", "drapes", "rustles", "shakes out", "puts on the"), 2.0),
    SoundKind("zipper", "زیپ", SPOT, ("zipper",), ("unzips", "zips up", "unzip", "zipping", "zips the", "zipped up"), 1.5),
    SoundKind("pour", "ریختن نوشیدنی", SPOT, ("pouring drink glass", "pour coffee cup"),
              ("pour", "pours", "pouring"), 3.0),
    SoundKind("clink", "برخورد لیوان", SPOT, ("glass clink",), ("cheers", "toast", "clink"), 1.5),
    SoundKind("keyboard", "تایپ", SPOT, ("keyboard typing",), ("typing", "types on", "types"), 3.0),
    SoundKind("paper", "کاغذ و جعبه", SPOT, ("paper rustle unboxing", "cardboard box open"),
              ("unbox", "unboxing", "opens the box", "box opens", "unwraps", "lid opens"), 2.5),
    SoundKind("spray", "اسپری عطر", SPOT, ("perfume spray",),
              ("sprays", "spraying", "sprayed", "spritz", "mists"), 1.5),
    SoundKind("switch", "کلید برق", SPOT, ("light switch click",),
              ("switches on", "switch on", "turns on the", "lamp turns on", "light turns on",
               "flicks the switch", "lights up"), 0.8),
)}

BEDS = [k for k, v in CATALOGUE.items() if v.kind == BED]
SPOTS = [k for k, v in CATALOGUE.items() if v.kind == SPOT]


class SoundError(Exception):
    pass


# ------------------------------------------------------------ measuring


def measure_lufs(path) -> float | None:
    """Integrated loudness of a file, from ffmpeg's own EBU R128 meter."""
    try:
        result = _run([FFMPEG, "-hide_banner", "-nostats", "-i", str(path),
                       "-af", "loudnorm=print_format=json", "-f", "null", "-"])
    except VideoProcessingError:
        return None
    text = result.stderr or ""
    start = text.rfind("{")
    end = text.rfind("}")
    if start < 0 or end < start:
        return None
    try:
        value = float(json.loads(text[start:end + 1]).get("input_i"))
    except (ValueError, TypeError):
        return None
    return value if value > -70 else None


# -------------------------------------------------------- the library


def _library_dir() -> Path:
    from django.conf import settings

    return Path(settings.MEDIA_ROOT) / "sound_library"


#: How much of a bed's head is folded onto its tail to hide the loop point.
LOOP_OVERLAP = 1.5


def prepare_file(source, category: str, out: Path, *, skip: float = 0.0) -> tuple[float, float]:
    """Trim, resample, cut and normalise one recording. Returns (seconds, LUFS).

    The single path every library sound takes — downloaded, generated or
    uploaded by an operator in the admin — so a clip's loudness is always
    REFERENCE_LUFS and its mix gain is arithmetic. `skip` drops that many
    seconds from the start first (used when re-preparing an older file).
    """
    kind = CATALOGUE.get(category)
    if kind is None:
        raise SoundError(f"دسته‌ی صدای «{category}» شناخته نشد")
    trim = (
        "silenceremove=start_periods=1:start_threshold=-50dB:start_silence=0.05,"
        "areverse,silenceremove=start_periods=1:start_threshold=-50dB:start_silence=0.05,areverse"
    )
    chain = [trim, "aresample=48000", "aformat=channel_layouts=stereo"]
    if skip > 0:
        chain.insert(0, f"atrim=start={skip:.3f},asetpts=PTS-STARTPTS")
    loudnorm = f"loudnorm=I={REFERENCE_LUFS}:TP=-2:LRA=15"
    out.parent.mkdir(parents=True, exist_ok=True)
    if kind.kind == SPOT:
        length = kind.max_seconds
        chain.append(f"atrim=0:{length:.2f},afade=t=out:st={max(0.0, length - 0.35):.2f}:d=0.35")
        chain.append(loudnorm)
        _run([FFMPEG, "-y", "-i", str(source), "-vn", "-af", ",".join(chain),
              "-c:a", "aac", "-b:a", "192k", "-ar", "48000", str(out)])
    else:
        # Beds are looped under scenes longer than the recording, and capped
        # at three minutes so the library stays small. No fade is baked in —
        # the mix fades each bed where it starts; a fade in the file would
        # dip the level at every loop.
        chain.append("atrim=0:180")
        staged = out.with_name(out.stem + "_staged.wav")
        _run([FFMPEG, "-y", "-i", str(source), "-vn", "-af", ",".join(chain),
              "-c:a", "pcm_s16le", "-ar", "48000", str(staged)])
        try:
            _loopable(staged, out, loudnorm)
        finally:
            staged.unlink(missing_ok=True)
    duration = probe_duration(out)
    if duration < (0.3 if kind.kind == SPOT else 4.0):
        out.unlink(missing_ok=True)
        raise SoundError(f"این فایل برای «{kind.label}» کوتاه است ({duration:.1f} ثانیه)")
    loudness = measure_lufs(out)
    if loudness is None:
        out.unlink(missing_ok=True)
        raise SoundError("این فایل عملاً ساکت است")
    return round(duration, 2), round(loudness, 1)


def _loopable(staged: Path, out: Path, finish: str) -> None:
    """Make the end of a bed flow into its start.

    The recording's first X seconds are cross-faded (equal power, since two
    stretches of rain are uncorrelated) over its last X seconds, and the
    body starts at X. The file then ends on exactly the sample it starts
    with, so `aloop` repeats it without the click — or the sudden change of
    room — that a plain cut makes every loop.
    """
    seconds = probe_duration(staged)
    overlap = min(LOOP_OVERLAP, seconds * 0.15)
    if overlap < 0.2:
        _run([FFMPEG, "-y", "-i", str(staged), "-af", finish,
              "-c:a", "aac", "-b:a", "192k", "-ar", "48000", str(out)])
        return
    graph = (
        f"[0:a]asplit[a][b];"
        f"[a]atrim=0:{overlap:.3f},asetpts=PTS-STARTPTS[head];"
        f"[b]atrim=start={overlap:.3f},asetpts=PTS-STARTPTS[body];"
        f"[body][head]acrossfade=d={overlap:.3f}:c1=qsin:c2=qsin,{finish}[out]"
    )
    _run([FFMPEG, "-y", "-i", str(staged), "-filter_complex", graph, "-map", "[out]",
          "-c:a", "aac", "-b:a", "192k", "-ar", "48000", str(out)])


def import_clip(source, category: str, *, title: str = "", origin: str = "UPLOAD",
                licence: str = "", creator: str = "", source_url: str = "",
                attribution: str = "", work_dir=None):
    """Bring a recording into the library, ready to mix.

    Every clip goes through the same door, whatever its origin:
      * leading and trailing silence trimmed,
      * 48 kHz stereo,
      * loudness normalised to REFERENCE_LUFS, so its mix gain is arithmetic,
      * spots cut to their category's longest useful length, with a fade.
    A clip that comes out silent or too short for its purpose is refused.
    """
    from django.core.files import File

    from apps.ai.models import SoundClip

    kind = CATALOGUE.get(category)
    if kind is None:
        raise SoundError(f"دسته‌ی صدای «{category}» شناخته نشد")
    work = Path(work_dir) if work_dir else _library_dir() / "_work"
    work.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha1(f"{source_url or source}:{category}".encode()).hexdigest()[:10]
    out = work / f"{category}_{digest}.m4a"
    duration, loudness = prepare_file(source, category, out)

    clip = SoundClip(
        category=category, title=(title or kind.label)[:200], duration=round(duration, 2),
        loudness_lufs=round(loudness, 1), origin=origin, licence=licence[:40],
        creator=creator[:200], source_url=source_url[:500], attribution=attribution[:400],
    )
    with out.open("rb") as handle:
        clip.file.save(f"{category}/{category}_{digest}.m4a", File(handle), save=False)
    clip.save()  # also writes the sidecar JSON `audio_setup --reindex` reads
    out.unlink(missing_ok=True)
    return clip


# -------------------------------------------------------- engines


@dataclass
class Picked:
    """One sound chosen for the video."""

    key: str
    path: Path
    engine: str
    title: str = ""
    licence: str = ""
    creator: str = ""
    source_url: str = ""
    attribution: str = ""
    loudness: float | None = REFERENCE_LUFS

    def credit(self) -> dict:
        return {
            "sound": CATALOGUE[self.key].label, "title": self.title, "engine": self.engine,
            "licence": self.licence, "creator": self.creator, "source_url": self.source_url,
            "attribution": self.attribution,
        }


def _seeded_choice(rows, seed: str):
    """Different videos get different recordings of the same rain, but the
    same video always gets the same one — a re-render must not change it."""
    if not rows:
        return None
    index = int(hashlib.sha1(seed.encode()).hexdigest(), 16) % len(rows)
    return rows[index]


def _local_file(field, work: Path | None) -> Path | None:
    """A path ffmpeg can open for a library file, wherever storage keeps it.

    On local storage, the file itself. On shared storage (S3), a copy made in
    the job's work folder — `media.reading` deletes its temporary file when
    its block ends, so the path it yields cannot be handed to a mix that runs
    later.
    """
    from services.media import files as media

    if not media.is_shared():
        try:
            path = Path(field.path)
        except Exception:  # noqa: BLE001
            return None
        return path if path.exists() else None
    folder = Path(work) if work is not None else Path(tempfile.mkdtemp(prefix="sound_"))
    folder.mkdir(parents=True, exist_ok=True)
    copy = folder / f"lib_{Path(field.name).name}"
    if not copy.exists():
        with media.reading(field) as local:
            shutil.copyfile(local, copy)
    return copy


def _from_library(key: str, seed: str, work: Path | None = None) -> Picked | None:
    from apps.ai.models import SoundClip

    rows = list(SoundClip.objects.filter(category=key, is_active=True).order_by("id"))
    clip = _seeded_choice(rows, seed)
    if clip is None:
        return None
    path = _local_file(clip.file, work)
    if path is None:
        return None
    return Picked(
        key=key, path=path, engine="کتابخانه‌ی صدای واقعی", title=clip.title,
        licence=clip.licence, creator=clip.creator, source_url=clip.source_url,
        attribution=clip.attribution, loudness=clip.loudness_lufs,
    )


def _procedural(key: str, seconds: float, work: Path) -> Picked | None:
    """Sounds code can make well, because they ARE shaped noise."""
    recipe = CATALOGUE[key].procedural
    if not recipe:
        return None
    seconds = max(2.0, seconds)
    out = work / f"proc_{key}_{int(seconds * 10)}.m4a"
    graphs = {
        # The noise of a quiet room: low-frequency air, nothing else.
        "room_tone": (
            f"anoisesrc=d={seconds:.2f}:c=brown:r=48000:a=0.5,lowpass=f=450,highpass=f=35,"
            "aformat=channel_layouts=stereo"
        ),
        # A steady wash plus sparse droplets: pink noise shaped to the band
        # where rain lives, and random clicks rung through a short band-pass.
        "rain": (
            f"anoisesrc=d={seconds:.2f}:c=pink:r=48000:a=0.5,highpass=f=400,lowpass=f=9000[wash];"
            f"aevalsrc='if(lt(random(0),0.0015),(random(1)-0.5)*1.6,0)':d={seconds:.2f}:s=48000,"
            "bandpass=f=3500:w=2500,aecho=0.6:0.3:7:0.25[drops];"
            "[wash][drops]amix=inputs=2:weights=1 0.7:normalize=0,aformat=channel_layouts=stereo"
        ),
        # Gusts: brown noise swelling on two slow, unrelated cycles.
        "wind": (
            f"anoisesrc=d={seconds:.2f}:c=brown:r=48000:a=0.6,lowpass=f=700,highpass=f=60,"
            "volume='0.45+0.35*sin(2*PI*t*0.11)+0.2*sin(2*PI*t*0.29+1)':eval=frame,"
            "aformat=channel_layouts=stereo"
        ),
        # Waves: a surge and a retreat roughly every seven seconds.
        "ocean": (
            f"anoisesrc=d={seconds:.2f}:c=brown:r=48000:a=0.6,lowpass=f=1400,highpass=f=50,"
            "volume='0.15+0.85*pow(sin(PI*t/7.3),4)':eval=frame,"
            "aformat=channel_layouts=stereo"
        ),
        # A whoosh: a noise burst that swells and falls in under a second.
        "whoosh": (
            "anoisesrc=d=1.2:c=pink:r=48000:a=0.7,highpass=f=300,lowpass=f=5000,"
            "volume='pow(sin(PI*min(t/1.1\\,1)),3)':eval=frame,"
            "aformat=channel_layouts=stereo"
        ),
    }
    graph = graphs.get(recipe)
    if graph is None:
        return None
    try:
        _run([FFMPEG, "-y", "-filter_complex",
              f"{graph},loudnorm=I={REFERENCE_LUFS}:TP=-2:LRA=15",
              "-c:a", "aac", "-b:a", "160k", "-ar", "48000", str(out)])
    except VideoProcessingError as exc:
        logger.info("Procedural %s failed: %s", key, exc)
        return None
    return Picked(key=key, path=out, engine="ساخته‌شده با کد", title=CATALOGUE[key].label,
                  licence="ساخت خودمان", loudness=measure_lufs(out) or REFERENCE_LUFS)


def _openverse(key: str, seed: str, work: Path) -> Picked | None:
    """Search Freesound's CC0 catalogue, import the best hit, use it.

    Imported into the library, so this network call happens once per sound —
    after that the same category is served offline.
    """
    for clip in fetch_openverse(key, limit=1, work=work):
        return _from_library(key, seed, work) or None
    return None


#: What a recording's title or tags must mention to be accepted for a
#: category — search engines return near-misses, and a near-miss in an ad is
#: "rain" that is actually a thunderstorm or "room tone" inside a microwave.
MUST_MENTION = {
    "room_tone": ("room tone", "roomtone", "room ambience", "room ambiance", "quiet room",
                  "empty room", "interior ambience", "interior ambiance", "silence"),
    "rain": ("rain",), "wind": ("wind", "breeze"), "ocean": ("wave", "ocean", "sea", "surf", "beach"),
    "forest": ("bird", "forest", "woods", "birdsong", "nature"),
    "city": ("city", "street", "traffic", "urban", "town"),
    "cafe": ("cafe", "café", "coffee", "restaurant", "bistro"),
    "kitchen": ("kitchen", "cooking", "sizzl", "frying"),
    "shop": ("mall", "shop", "store", "market", "supermarket"),
    "office": ("office",), "night": ("night", "cricket"), "fireplace": ("fire", "fireplace", "crackl"),
    "water": ("stream", "river", "creek", "brook", "water"),
    "footsteps": ("footstep", "steps", "walking", "walk"), "heels": ("heel",),
    "door": ("door",), "whoosh": ("whoosh", "swoosh", "swish", "woosh"),
    "camera": ("camera", "shutter"), "cloth": ("cloth", "fabric", "rustl", "clothes"),
    "zipper": ("zip",), "pour": ("pour",), "clink": ("clink", "glass"),
    "keyboard": ("keyboard", "typing"), "paper": ("paper", "cardboard", "box", "unbox", "package"),
    "spray": ("spray", "aerosol", "perfume"), "switch": ("switch", "click"),
}

#: Words that disqualify a recording for any category: things that would make
#: an ad sound wrong however well they match the search.
AVOID_ALWAYS = ("music", "song", "melody", "voice", "speech", "talking", "narrat", "scream",
                "siren", "alarm", "explosion", "gun", "horror", "scary", "distort")
AVOID = {
    "room_tone": ("microwave", "oven", "fridge", "refrigerator", "machine", "engine", "factory",
                  "hvac", "server", "fan", "motor", "car", "vehicle", "train"),
    "rain": ("thunder", "heavy", "hail", "car", "tent", "tin roof"),
    "wind": ("howl", "storm", "hurricane", "microphone", "car park", "parking", "traffic"),
    # "Forest" is the daytime birdsong bed; a night forest is the night bed.
    "forest": ("night", "cricket", "rain", "thunder"),
    "ocean": ("storm", "ship", "boat", "underwater"),
    "city": ("horn", "construction", "drill", "protest"),
    "kitchen": ("blender", "grinder", "alarm"),
    "footsteps": ("run", "running", "snow", "mud", "stairs"),
    "heels": ("run", "running", "stairs"),
    "door": ("slam", "creak", "squeak", "knock"),
    "fireplace": ("house fire", "forest fire", "wildfire", "extinguish"),
}


def _relevant(key: str, row: dict) -> bool:
    title = (row.get("title") or "").lower()
    tags = " ".join(str(t.get("name", "")) for t in (row.get("tags") or []) if isinstance(t, dict)).lower()
    text = f"{title} {tags}"
    if any(word in text for word in AVOID_ALWAYS + AVOID.get(key, ())):
        return False
    wanted = MUST_MENTION.get(key)
    return not wanted or any(word in text for word in wanted)


def fetch_openverse(key: str, *, limit: int = 2, work: Path | None = None) -> list:
    """Download up to `limit` CC0 recordings for a category into the library."""
    import requests

    kind = CATALOGUE[key]
    imported = []
    seen_urls = set()
    work = work or _library_dir() / "_work"
    work.mkdir(parents=True, exist_ok=True)
    from apps.ai.models import SoundClip

    existing = set(SoundClip.objects.filter(category=key).values_list("source_url", flat=True))
    for query in kind.queries:
        if len(imported) >= limit:
            break
        try:
            response = requests.get(
                "https://api.openverse.org/v1/audio/",
                params={"q": query, "license": "cc0,pdm", "source": "freesound", "page_size": 20},
                headers={"User-Agent": "UpMarket/1.0 (sound library)"}, timeout=30,
            )
            response.raise_for_status()
            rows = response.json().get("results", [])
        except Exception as exc:  # noqa: BLE001
            logger.info("Openverse search failed for %s: %s", query, exc)
            continue
        # Relevance order is Openverse's; we only filter. Re-sorting by length
        # (the first version did) put "Room tone — inside a microwave oven"
        # ahead of a real room, because it happened to be three minutes long.
        for row in rows:
            if len(imported) >= limit:
                break
            url = row.get("url") or ""
            page = row.get("foreign_landing_url") or url
            if not url or url in seen_urls or page in existing:
                continue
            seconds = (row.get("duration") or 0) / 1000
            if kind.kind == BED and not (20 <= seconds <= 400):
                continue
            if kind.kind == SPOT and not (0.5 <= seconds <= 60):
                continue
            if not _relevant(key, row):
                continue
            seen_urls.add(url)
            target = work / f"dl_{hashlib.sha1(url.encode()).hexdigest()[:10]}{Path(url.split('?')[0]).suffix or '.mp3'}"
            try:
                data = requests.get(url, timeout=60, headers={"User-Agent": "UpMarket/1.0"})
                data.raise_for_status()
                target.write_bytes(data.content)
                clip = import_clip(
                    target, key, title=row.get("title") or kind.label, origin="OPENVERSE",
                    licence=(row.get("license") or "cc0").upper(), creator=row.get("creator") or "",
                    source_url=page, attribution=row.get("attribution") or "", work_dir=work,
                )
                imported.append(clip)
            except Exception as exc:  # noqa: BLE001 — one bad file is not the category
                logger.info("Could not import %s: %s", url, exc)
            finally:
                target.unlink(missing_ok=True)
    return imported


def _elevenlabs(engine, key: str, seconds: float, work: Path) -> Picked | None:
    import requests

    kind = CATALOGUE[key]
    duration = min(22.0, max(0.5, seconds if kind.kind == BED else kind.max_seconds))
    try:
        response = requests.post(
            (engine.base_url or "https://api.elevenlabs.io").rstrip("/") + "/v1/sound-generation",
            json={"text": kind.queries[0], "duration_seconds": duration,
                  "prompt_influence": float(engine.options.get("prompt_influence", 0.4))},
            headers={"xi-api-key": engine.api_key}, timeout=engine.timeout_s,
        )
    except Exception as exc:  # noqa: BLE001
        logger.info("ElevenLabs SFX unreachable: %s", exc)
        return None
    if response.status_code != 200:
        logger.info("ElevenLabs SFX %s: %s", response.status_code, response.text[:200])
        return None
    raw = work / f"el_{key}.mp3"
    raw.write_bytes(response.content)
    try:
        clip = import_clip(raw, key, title=f"ElevenLabs: {kind.queries[0]}", origin="ELEVENLABS",
                           licence="ElevenLabs", work_dir=work)
    except Exception as exc:  # noqa: BLE001
        logger.info("ElevenLabs SFX import failed: %s", exc)
        return None
    finally:
        raw.unlink(missing_ok=True)
    path = _local_file(clip.file, work)
    if path is None:
        return None
    return Picked(key=key, path=path, engine="ElevenLabs", title=clip.title,
                  licence=clip.licence, loudness=clip.loudness_lufs)


def _node_sfx(key: str, seconds: float, work: Path) -> Picked | None:
    """MOSS-SoundEffect on a processing node, from the category's English caption (no shop data goes in).
    The result joins the shared library, so the next video that needs this sound finds a real file at once."""
    from . import node_audio

    kind = CATALOGUE[key]
    duration = min(20.0, max(1.0, seconds if kind.kind == BED else kind.max_seconds))
    prompt = kind.queries[0] + (", seamless ambience, no music, no speech" if kind.kind == BED else ", no music")
    try:
        raw = node_audio.run_and_wait("sfx", "voice.sfx", {"prompt": prompt, "seconds": duration, "out": "sfx.wav"},
                                      purpose="sfx",
                                      origin="soundscape", wait_s=900)
    except node_audio.NodeAudioError as exc:
        logger.info("MOSS-SoundEffect unavailable for %s: %s", key, exc)
        return None
    try:
        clip = import_clip(raw, key, title=f"MOSS: {kind.queries[0]}", origin="MOSS", licence="Apache-2.0",
                           work_dir=work)
    except Exception as exc:  # noqa: BLE001
        logger.info("MOSS sound import failed: %s", exc)
        return None
    path = _local_file(clip.file, work)
    if path is None:
        return None
    return Picked(key=key, path=path, engine="MOSS-SoundEffect", title=clip.title, licence=clip.licence,
                  loudness=clip.loudness_lufs)


def pick(key: str, *, seconds: float, seed: str, work: Path, store=None) -> Picked | None:
    """A recording for this sound, from the admin's engines in order."""
    try:
        chain = engine_registry.require(engine_registry.SOUND, store)
    except engine_registry.NoEngine:
        chain = [e for e in engine_registry.configured(engine_registry.SOUND) if e.kind == "PROCEDURAL"]
    for engine in chain:
        try:
            if engine.kind == "SOUND_LIBRARY":
                found = _from_library(key, seed, work)
            elif engine.kind == "PROCEDURAL":
                found = _procedural(key, seconds, work)
            elif engine.kind == "OPENVERSE":
                found = _openverse(key, seed, work)
            elif engine.kind == "ELEVENLABS_SFX":
                found = _elevenlabs(engine, key, seconds, work)
            elif engine.kind == "NODE_SFX":
                found = _node_sfx(key, seconds, work)
            else:
                found = None
        except Exception as exc:  # noqa: BLE001 — the next engine may still have it
            logger.info("Sound engine %s failed for %s: %s", engine.name, key, exc)
            found = None
        if found is not None:
            return found
    return None


# ------------------------------------------------------ what each scene gets


_WORD = re.compile(r"[a-z]+(?: [a-z]+)?")


def _scene_text(scene) -> str:
    state = getattr(scene, "state", None) or {}
    parts = [
        getattr(scene, "visual_prompt", "") or "",
        getattr(scene, "motion_prompt", "") or "",
        str(state.get("location", "")), str(state.get("action", "")),
        " ".join(str(x) for x in state.get("objects", []) or []),
    ]
    return " ".join(parts).lower()


#: Words that describe a mood or a surface, not a place. They may tip a tie
#: but must not outvote a noun that names the place: "a cozy café" is a café,
#: not a fireplace, and "a fireplace in the living room, product on a table"
#: is a fireplace, not an empty room.
WEAK_WORDS = frozenset({
    "cozy", "winter", "minimalist", "room", "interior", "indoor", "home",
    "table", "shelf", "desk", "studio",
})


def _score(text: str, kind: SoundKind) -> float:
    score = 0.0
    for word in kind.keywords:
        # "sprayed", "doors", "pouring" — prompts are written in running
        # English, keywords in their base form.
        if re.search(rf"\b{re.escape(word)}(?:s|es|d|ed|ing)?\b", text):
            score += 2 if " " in word else (0.5 if word in WEAK_WORDS else 1)
    return score


def plan_scene(scene, *, ambience: bool = True, effects: bool = True) -> dict:
    """{"ambience": key|None, "effects": [{"key", "at"}]} for one scene.

    The script model's own choice wins when it made one (`scene.sound`); the
    scene's words decide otherwise. An indoor product shot with nothing else
    to say still gets room tone: true silence under a voice sounds like a
    recording booth, and a little air sounds like a place.
    """
    declared = getattr(scene, "sound", None) or {}
    text = _scene_text(scene)
    duration = float(getattr(scene, "duration", 5) or 5)
    out = {"ambience": None, "effects": []}

    if ambience:
        chosen = declared.get("ambience")
        if chosen in CATALOGUE and CATALOGUE[chosen].kind == BED:
            out["ambience"] = chosen
        elif chosen == "none":
            out["ambience"] = None
        else:
            # Room tone is the floor, not a contender: any bed that names an
            # actual place beats it, and it is what is left when none does.
            ranked = sorted(
                ((_score(text, CATALOGUE[k]), -order, k) for order, k in enumerate(BEDS)
                 if k != "room_tone"),
                reverse=True,
            )
            out["ambience"] = ranked[0][2] if ranked and ranked[0][0] >= 1 else "room_tone"

    if effects:
        wanted = declared.get("effects")
        # A list — even an empty one — is the script model's decision and is
        # final: "no effect in this scene" must not be overruled by keyword
        # matching. Only a scene that says nothing at all falls back to words.
        if isinstance(wanted, list):
            for item in wanted[:2]:
                key = item.get("key") if isinstance(item, dict) else item
                if key in CATALOGUE and CATALOGUE[key].kind == SPOT:
                    at = item.get("at") if isinstance(item, dict) else None
                    try:
                        at = float(at)
                    except (TypeError, ValueError):
                        at = min(1.0, duration / 3)
                    out["effects"].append({
                        "key": key, "at": max(0.0, min(duration - 0.3, at)),
                        # A time the script or a person chose: the sync step
                        # looks for the event nearest to it, not the biggest.
                        "explicit": True,
                    })
        else:
            ranked = sorted(((_score(text, CATALOGUE[k]), k) for k in SPOTS), reverse=True)
            for score, key in ranked[:1]:
                if score > 0:
                    out["effects"].append({"key": key, "at": min(0.8, duration / 4)})
    return out


# ------------------------------------------------------------- building


@dataclass
class Soundscape:
    path: Path | None
    plan: list[dict] = field(default_factory=list)
    credits: list[dict] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {"plan": self.plan, "credits": self.credits, "missing": self.missing}


def _gain(picked: Picked, target_lufs: float) -> float:
    return target_lufs - (picked.loudness if picked.loudness is not None else REFERENCE_LUFS)


def build(scenes, durations: list[float], out_path, work_dir, *, store=None, seed: str = "",
          ambience: bool = True, effects: bool = True, transitions: bool = True,
          video=None) -> Soundscape:
    """The whole non-voice track for a video, as one stereo file.

    `durations` are the REAL lengths of the rendered segments, in scene order,
    so every sound lands where its scene actually is. `video` is the rendered
    video those durations describe; when given, each effect is moved onto the
    frame where its event happens (`sync.place`) instead of the time the
    script guessed before the video existed.
    """
    from . import sync
    from .polish import settings_mix

    mix = settings_mix()
    ambience = ambience and getattr(mix, "ambience_enabled", True)
    effects = effects and getattr(mix, "effects_enabled", True)
    work = Path(work_dir)
    work.mkdir(parents=True, exist_ok=True)
    total = sum(durations)
    result = Soundscape(path=None)
    if total <= 0 or not (ambience or effects):
        return result

    starts, cursor = [], 0.0
    for length in durations:
        starts.append(cursor)
        cursor += length

    plans = [plan_scene(scene, ambience=ambience, effects=effects) for scene in scenes]

    # A whoosh on a hard cut: the one transition ads nearly always mark.
    if effects and transitions:
        for index, scene in enumerate(scenes[1:], start=1):
            if getattr(scene, "transition", "") == "NEW_SCENE" and not plans[index]["effects"]:
                plans[index]["effects"].append({"key": "whoosh", "at": 0.0, "lead": 0.45})

    # Merge consecutive scenes with the same ambience into one continuous bed.
    spans: list[list] = []
    for index, plan in enumerate(plans):
        key = plan["ambience"]
        if key and spans and spans[-1][0] == key and spans[-1][2] == index - 1:
            spans[-1][2] = index
        elif key:
            spans.append([key, index, index])

    inputs: list[Path] = []
    graph: list[str] = []
    labels: list[str] = []
    fade = 0.8

    for number, (key, first, last) in enumerate(spans):
        start = starts[first]
        end = starts[last] + durations[last]
        length = end - start
        picked = pick(key, seconds=length, seed=f"{seed}:{key}", work=work, store=store)
        if picked is None:
            result.missing.append(CATALOGUE[key].label)
            continue
        result.credits.append(picked.credit())
        index = len(inputs)
        inputs.append(picked.path)
        # Overlap neighbouring beds by the fade length so a cut is a crossfade.
        lead = fade / 2 if first > 0 else 0.0
        tail = fade / 2 if last < len(scenes) - 1 else 0.0
        begin = max(0.0, start - lead)
        span = (end + tail) - begin
        delay = int(begin * 1000)
        graph.append(
            f"[{index}:a]aloop=loop=-1:size=2e9,atrim=0:{span:.3f},asetpts=N/SR/TB,"
            f"aformat=sample_rates=48000:channel_layouts=stereo,"
            f"afade=t=in:st=0:d={fade if first > 0 else 1.5:.2f},"
            f"afade=t=out:st={max(0.0, span - fade):.3f}:d={fade:.2f},"
            f"volume={_gain(picked, mix.ambience_lufs):.2f}dB,"
            f"adelay={delay}|{delay},asetpts=N/SR/TB[b{number}]"
        )
        labels.append(f"[b{number}]")
        for scene_index in range(first, last + 1):
            plans[scene_index]["ambience_title"] = picked.title

    spot_number = 0
    for index, plan in enumerate(plans):
        for effect in plan["effects"]:
            key = effect["key"]
            picked = pick(key, seconds=CATALOGUE[key].max_seconds,
                          seed=f"{seed}:{key}:{index}", work=work, store=store)
            if picked is None:
                result.missing.append(CATALOGUE[key].label)
                continue
            result.credits.append(picked.credit())
            input_index = len(inputs)
            inputs.append(picked.path)
            gain = _gain(picked, mix.effects_lufs)
            planned = float(effect.get("at", 0))
            placement = sync.Placement(at=planned)
            if video is not None and not effect.get("lead"):
                placement = sync.place(
                    video, starts[index], durations[index], key, planned, picked.path,
                    explicit=bool(effect.get("explicit")),
                )
            effect["planned_at"] = planned
            effect["at"] = placement.at
            effect["synced"] = placement.synced
            effect["steps"] = len(placement.hits)

            if placement.hits:
                # A rhythm: one slice of the recording per step in the picture.
                branches = [f"[h{spot_number}_{n}]" for n in range(len(placement.hits))]
                graph.append(f"[{input_index}:a]asplit={len(branches)}{''.join(branches)}")
                for n, (hit_at, clip_start, clip_end) in enumerate(placement.hits):
                    delay = int(max(0.0, starts[index] + hit_at) * 1000)
                    piece = max(0.06, clip_end - clip_start)
                    graph.append(
                        f"{branches[n]}atrim=start={clip_start:.3f}:end={clip_end:.3f},asetpts=N/SR/TB,"
                        f"aformat=sample_rates=48000:channel_layouts=stereo,"
                        f"afade=t=in:st=0:d=0.005,"
                        f"afade=t=out:st={max(0.0, piece - 0.04):.3f}:d=0.04,"
                        f"volume={gain:.2f}dB,"
                        f"adelay={delay}|{delay},asetpts=N/SR/TB[s{spot_number}]"
                    )
                    labels.append(f"[s{spot_number}]")
                    spot_number += 1
                continue

            at = max(0.0, starts[index] + placement.at - float(effect.get("lead", 0)))
            delay = int(at * 1000)
            length = CATALOGUE[key].max_seconds
            # `skip` drops the recording's lead-in, so its attack — not the
            # silence or creak before it — is what lands on the event frame.
            skip = placement.skip
            graph.append(
                f"[{input_index}:a]atrim=start={skip:.3f}:end={skip + length:.3f},asetpts=N/SR/TB,"
                f"aformat=sample_rates=48000:channel_layouts=stereo,"
                f"afade=t=out:st={max(0.0, length - 0.3):.2f}:d=0.3,"
                f"volume={gain:.2f}dB,"
                f"adelay={delay}|{delay},asetpts=N/SR/TB[s{spot_number}]"
            )
            labels.append(f"[s{spot_number}]")
            spot_number += 1

    result.plan = [
        {
            "scene": getattr(scene, "index", i + 1),
            "ambience": plans[i]["ambience"],
            "ambience_label": CATALOGUE[plans[i]["ambience"]].label if plans[i]["ambience"] else None,
            "effects": [
                {
                    "key": e["key"], "label": CATALOGUE[e["key"]].label,
                    "at": round(e.get("at", 0), 2),
                    # Where the script guessed, and whether the picture moved it:
                    # "event" (on the frame of the action), "rhythm" (one
                    # sound per step) or None (no clear event — kept as planned).
                    "planned_at": round(e.get("planned_at", e.get("at", 0)), 2),
                    "synced": e.get("synced"),
                    "steps": e.get("steps", 0),
                }
                for e in plans[i]["effects"]
            ],
        }
        for i, scene in enumerate(scenes)
    ]
    # Credits once per recording, not once per scene.
    unique, seen = [], set()
    for credit in result.credits:
        marker = (credit["title"], credit["source_url"], credit["engine"])
        if marker not in seen:
            seen.add(marker)
            unique.append(credit)
    result.credits = unique

    if not labels:
        return result

    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    # Every delayed branch above ends in asetpts=N/SR/TB. Without it, a mix
    # with a SINGLE input (ambience off, one effect) lost its delay in the
    # atrim below and played the effect at second 0 — measured: a door meant
    # for 2.26 s started at 0.00 s. With two or more inputs amix happened to
    # realign it, which is why it went unnoticed.
    graph.append(
        f"{''.join(labels)}amix=inputs={len(labels)}:duration=longest:dropout_transition=0:"
        f"normalize=0,atrim=0:{total:.3f},alimiter=limit=0.9[out]"
    )
    command = [FFMPEG, "-y"]
    for path in inputs:
        command += ["-i", str(path)]
    command += ["-filter_complex", ";".join(graph), "-map", "[out]",
                *_codec(out), "-ar", "48000", str(out)]
    try:
        _run(command)
    except VideoProcessingError as exc:
        raise SoundError(f"میکس صدای محیط ساخته نشد: {exc}") from exc
    result.path = out
    return result


def under_voice(voice_path, bed_path, out_path, *, duck_db: float | None = None) -> Path:
    """Voice on top, the soundscape under it, ducking while the voice speaks."""
    from .polish import settings_mix

    mix = settings_mix()
    duck = float(duck_db if duck_db is not None else getattr(mix, "duck_db", 9.0))
    # sidechaincompress ratio that gives roughly `duck` dB of reduction on a
    # bed well under the voice-driven threshold.
    ratio = max(2.0, min(20.0, 1.0 + duck / 3.0))
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    graph = (
        "[0:a]aresample=48000,aformat=channel_layouts=stereo,asplit=2[voice][key];"
        "[1:a]aresample=48000,aformat=channel_layouts=stereo[bed];"
        f"[bed][key]sidechaincompress=threshold=0.02:ratio={ratio:.1f}:attack=40:release=600[ducked];"
        "[voice][ducked]amix=inputs=2:duration=first:dropout_transition=0:normalize=0,"
        "alimiter=limit=0.95[a]"
    )
    _run([FFMPEG, "-y", "-i", str(voice_path), "-i", str(bed_path),
          "-filter_complex", graph, "-map", "[a]",
          *_codec(out), "-ar", "48000", str(out)])
    return out


def _codec(out: Path) -> list[str]:
    """PCM for a .wav intermediate, AAC otherwise.

    The soundscape and the ducked mix are only steps on the way to the final
    mux, which encodes once. Each extra AAC pass is a little more smeared high
    end — on a voice, exactly where «س» and «ش» live.
    """
    if out.suffix.lower() == ".wav":
        return ["-c:a", "pcm_s16le"]
    return ["-c:a", "aac", "-b:a", "192k"]


def catalogue() -> list[dict]:
    """For the admin and the panel: every sound we know how to place."""
    return [
        {"key": k.key, "label": k.label, "kind": k.kind, "procedural": bool(k.procedural)}
        for k in CATALOGUE.values()
    ]
