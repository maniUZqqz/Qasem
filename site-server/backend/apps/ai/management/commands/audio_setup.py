"""One command that makes every offline sound engine ready on this machine.

    python manage.py audio_setup                 # everything, then a status table
    python manage.py audio_setup --voices        # Piper voices (≈63 MB each)
    python manage.py audio_setup --denoise       # DeepFilterNet (≈27 MB)
    python manage.py audio_setup --library       # real recordings from Freesound (CC0)
    python manage.py audio_setup --library --per-category 3
    python manage.py audio_setup --reindex       # rebuild library rows from media/sound_library
    python manage.py audio_setup --status        # just the table
    python manage.py audio_setup --check         # exit 1 + one line per missing piece
    python manage.py audio_setup --english       # English output (for start.bat)

Downloads happen once; after that every engine it prepared works without the
internet. Voices and DeepFilterNet go to `Code/UpMarket/models/` (ignored by
git, like ffmpeg — they are re-downloadable binaries). The sound library goes
to `media/sound_library/`, which IS tracked, so a `git pull` on the main system
brings the recordings with it.

Idempotent: anything already present is skipped.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import requests
from django.core.management.base import BaseCommand

#: Voice file → path inside the Piper voices repository. The Persian ones are
#: every Persian voice Piper has; gyro and ganji are the two the admin seeds.
VOICES = {
    "fa_IR-gyro-medium": "fa/fa_IR/gyro/medium",
    "fa_IR-ganji-medium": "fa/fa_IR/ganji/medium",
    "fa_IR-amir-medium": "fa/fa_IR/amir/medium",
    "fa_IR-reza_ibrahim-medium": "fa/fa_IR/reza_ibrahim/medium",
    "en_US-hfc_male-medium": "en/en_US/hfc_male/medium",
    "en_US-hfc_female-medium": "en/en_US/hfc_female/medium",
    # Not in the rhasspy repository: its own repository, files at the root.
    # The only female Persian Piper voice (MIT; CC-0 ManaTTS corpus).
    "fa_IR-mana-medium": "repo:MahtaFetrat/Mana-Persian-Piper",
}
DEFAULT_VOICES = ["fa_IR-gyro-medium", "fa_IR-ganji-medium", "fa_IR-mana-medium",
                  "en_US-hfc_male-medium", "en_US-hfc_female-medium"]


def _voice_urls(name: str, suffix: str) -> list[str]:
    """Where `name` + suffix can be downloaded from, in order."""
    where = VOICES[name]
    if where.startswith("repo:"):
        repo = where[len("repo:"):]
        return [f"{b}/{repo}/resolve/main/{name}{suffix}" for b in _hf_bases()]
    return [f"{b}/rhasspy/piper-voices/resolve/main/{where}/{name}{suffix}" for b in _hf_bases()]

DEEPFILTER_URL = (
    "https://github.com/Rikorose/DeepFilterNet/releases/download/v0.5.6/"
    "deep-filter-0.5.6-x86_64-pc-windows-msvc.exe"
)
DEEPFILTER_LINUX_URL = (
    "https://github.com/Rikorose/DeepFilterNet/releases/download/v0.5.6/"
    "deep-filter-0.5.6-x86_64-unknown-linux-musl"
)


#: Where Piper voices can be fetched from, tried in order. Hugging Face first;
#: its public mirror when HF refuses the connection (it does for some
#: networks, including some in Iran). HF_ENDPOINT, the variable the HF tools
#: themselves read, goes in front when set.
def _hf_bases() -> list[str]:
    import os

    bases = ["https://huggingface.co", "https://hf-mirror.com"]
    custom = (os.environ.get("HF_ENDPOINT") or "").strip().rstrip("/")
    if custom and custom not in bases:
        bases.insert(0, custom)
    return bases


def _looks_complete(target: Path) -> bool:
    """Present AND plausibly whole — an error page saved as a model is neither."""
    if not target.exists():
        return False
    size = target.stat().st_size
    if target.suffix == ".json":
        try:
            json.loads(target.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            return False
        return size > 100
    return size > 1_000_000


def _download(urls, target: Path, *, label: str, say) -> bool:
    """Fetch `target` from the first URL that works. Returns True when present."""
    if _looks_complete(target):
        say(f"  ✓ {label} — از قبل هست", f"  [OK] {label} - already here")
        return True
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_suffix(target.suffix + ".part")
    errors = []
    for url in ([urls] if isinstance(urls, str) else urls):
        started = time.monotonic()
        try:
            with requests.get(url, stream=True, timeout=60, headers={"User-Agent": "UpMarket/1.0"}) as r:
                r.raise_for_status()
                with partial.open("wb") as handle:
                    for chunk in r.iter_content(1 << 20):
                        handle.write(chunk)
            partial.replace(target)
            if not _looks_complete(target):
                target.unlink(missing_ok=True)
                raise ValueError("the file that arrived is not a complete model")
        except Exception as exc:  # noqa: BLE001 — try the next source
            errors.append(f"{url.split('/')[2]}: {exc}")
            continue
        finally:
            # Also on Ctrl+C: half a model left behind looks like a model.
            partial.unlink(missing_ok=True)
        size = target.stat().st_size / (1 << 20)
        seconds = time.monotonic() - started
        say(f"  ✓ {label} — {size:.0f} MB در {seconds:.0f} ثانیه",
            f"  [OK] {label} - {size:.0f} MB in {seconds:.0f} s")
        return True
    detail = " | ".join(errors)[:300]
    say(f"  ✗ {label} — {detail}", f"  [FAILED] {label} - {detail}")
    return False


def _whisper_ready(name: str) -> bool:
    """Is the Whisper model already on this machine (no network)?"""
    try:
        from faster_whisper.utils import download_model

        download_model(name, local_files_only=True)
        return True
    except Exception:  # noqa: BLE001 — not installed, or not downloaded
        return False


def wanted_voices() -> list[str]:
    """Every Piper voice this install should have on disk.

    The defaults, plus any voice an admin typed into a Piper row — active or
    not, since switching a row on in the admin must not be the moment someone
    discovers its voice was never downloaded. Only names we know how to
    fetch are returned; an unknown name is reported by `check`.
    """
    names = list(DEFAULT_VOICES)
    try:
        from apps.ai.models import AudioEngine

        for row in AudioEngine.objects.filter(kind="PIPER"):
            for value in (row.model_name, row.voice_fa, row.voice_fa_female,
                          row.voice_en, row.voice_en_female):
                name = (value or "").strip().removesuffix(".onnx")
                if name and name not in names:
                    names.append(name)
    except Exception:  # noqa: BLE001 — before migrations
        pass
    return names


class Command(BaseCommand):
    help = "مدل‌های صدای آفلاین، نویزگیر و کتابخانه‌ی صدای واقعی را روی همین سیستم آماده می‌کند"

    def add_arguments(self, parser):
        parser.add_argument("--voices", nargs="*", help="صداهای Piper (خالی = همه‌ی صداهای لازم)")
        parser.add_argument("--denoise", action="store_true", help="DeepFilterNet")
        parser.add_argument("--library", action="store_true", help="صداهای محیط و افکت از Freesound")
        parser.add_argument("--per-category", type=int, default=2)
        parser.add_argument("--categories", nargs="*", help="فقط این دسته‌ها")
        parser.add_argument("--reindex", action="store_true", help="بازسازی ردیف‌ها از فایل‌ها")
        parser.add_argument("--status", action="store_true", help="فقط وضعیت")
        parser.add_argument(
            "--check", action="store_true",
            help="برای start.bat: اگر چیزی کم است، کد خروج ۱ و یک خط توضیح برای هرکدام",
        )
        parser.add_argument(
            "--english", action="store_true",
            help="پیام‌ها به انگلیسی — کنسول start.bat فارسی را درست نشان نمی‌دهد",
        )

    def say(self, persian: str, english: str) -> None:
        self.stdout.write(english if self.english else persian)

    def handle(self, *args, **options):
        self.english = bool(options["english"])
        if options["check"]:
            return self.check_offline()
        everything = not any([
            options["voices"] is not None, options["denoise"], options["library"],
            options["reindex"], options["status"],
        ])
        if options["voices"] is not None or everything:
            self.voices(options["voices"] or wanted_voices())
        if options["denoise"] or everything:
            self.deepfilter()
        if everything:
            self.whisper()
        if options["reindex"] or everything:
            # Before downloading: a fresh clone already has the library files
            # (they are tracked in git) and only lacks the rows. Without this
            # step the download would fetch 50 sounds the disk already has.
            self.reindex()
        if options["library"] or everything:
            self.library(options["per_category"], options["categories"])
        if self.english:
            missing = self.missing()
            for line in missing:
                self.stdout.write(line)
            if not missing:
                self.stdout.write("[OK] Offline voice, noise removal and sound library are ready.")
        else:
            self.status()

    # ------------------------------------------------------------ voices

    def voices(self, names):
        from services.audio import engines

        self.say("\nصداهای Piper (آفلاین):", "Offline voices (Piper):")
        folder = engines.models_dir() / "piper"
        for name in names:
            name = name.removesuffix(".onnx")
            base = VOICES.get(name)
            if base is None:
                self.say(f"  ✗ {name} — شناخته نشد؛ یکی از: {', '.join(VOICES)}",
                         f"  [SKIP] {name} - unknown voice; known: {', '.join(VOICES)}")
                continue
            # The config first: it is small, and a voice whose config cannot be
            # fetched is not worth 63 MB of model.
            ok = _download(_voice_urls(name, ".onnx.json"),
                           folder / f"{name}.onnx.json", label=f"{name} (config)", say=self.say)
            if ok:
                _download(_voice_urls(name, ".onnx"), folder / f"{name}.onnx", label=name, say=self.say)

    # ------------------------------------------------------------ whisper

    def whisper(self):
        """The speech-recognition model: word timings for narration sync and
        subtitles of the shop's own videos. faster-whisper would fetch it on
        first use, in the middle of a job; this fetches it now, with the
        Hugging Face mirror when HF itself refuses."""
        import os

        from django.conf import settings

        name = settings.UPMARKET_AI.get("WHISPER_MODEL", "small")
        self.say(f"\nمدل تشخیص گفتار Whisper «{name}»:", f"Speech recognition model (Whisper {name}):")
        if _whisper_ready(name):
            self.say("  ✓ از قبل هست", "  [OK] already here")
            return
        try:
            from faster_whisper.utils import download_model
        except ImportError:
            self.say("  ✗ faster-whisper نصب نیست", "  [FAILED] faster-whisper is not installed")
            return
        previous = os.environ.get("HF_ENDPOINT")
        for base in _hf_bases():
            os.environ["HF_ENDPOINT"] = base
            try:
                download_model(name)
                self.say(f"  ✓ دانلود شد ({base})", f"  [OK] downloaded ({base})")
                break
            except Exception as exc:  # noqa: BLE001 — try the next source
                self.say(f"  · {base}: {exc}"[:160], f"  [--] {base}: {exc}"[:160])
        if previous is None:
            os.environ.pop("HF_ENDPOINT", None)
        else:
            os.environ["HF_ENDPOINT"] = previous

    # ------------------------------------------------------------ denoise

    def deepfilter(self):
        import os
        import stat

        from services.audio import engines

        self.say("\nنویزگیر DeepFilterNet (آفلاین):", "Noise remover (DeepFilterNet):")
        windows = os.name == "nt"
        target = engines.models_dir() / "deepfilter" / ("deep-filter.exe" if windows else "deep-filter")
        if _download(DEEPFILTER_URL if windows else DEEPFILTER_LINUX_URL, target,
                     label="deep-filter", say=self.say) and not windows:
            target.chmod(target.stat().st_mode | stat.S_IEXEC)

    # ------------------------------------------------------------ library

    def library(self, per_category: int, only):
        from apps.ai.models import SoundClip
        from services.audio import soundscape

        self.say("\nکتابخانه‌ی صدای واقعی (Freesound، فقط CC0):",
                 "Sound library (real recordings, Freesound CC0):")
        for key, kind in soundscape.CATALOGUE.items():
            if only and key not in only:
                continue
            have = SoundClip.objects.filter(category=key, is_active=True).count()
            if have >= per_category:
                self.say(f"  ✓ {kind.label} — {have} صدا از قبل هست",
                         f"  [OK] {key} - {have} already here")
                continue
            try:
                got = soundscape.fetch_openverse(key, limit=per_category - have)
            except Exception as exc:  # noqa: BLE001
                self.say(f"  ✗ {kind.label} — {exc}", f"  [FAILED] {key} - {exc}"[:200])
                continue
            names = "، ".join(c.title[:30] for c in got) or "چیزی پیدا نشد"
            self.say(f"  {'✓' if got else '·'} {kind.label} — {len(got)} صدای تازه: {names}",
                     f"  [{'OK' if got else '--'}] {key} - {len(got)} new")

    def _unindexed(self) -> list[Path]:
        """Library files on disk that have no row — what a fresh clone looks like."""
        from django.conf import settings

        from apps.ai.models import SoundClip

        root = Path(settings.MEDIA_ROOT) / "sound_library"
        known = set(SoundClip.objects.values_list("file", flat=True))
        out = []
        for sidecar in root.glob("*/*.json"):
            audio = sidecar.with_suffix(".m4a")
            if audio.exists() and f"sound_library/{audio.parent.name}/{audio.name}" not in known:
                out.append(audio)
        return out

    def reindex(self):
        from apps.ai.models import SoundClip
        from services.audio import soundscape

        added = 0
        for audio in self._unindexed():
            sidecar = audio.with_suffix(".json")
            meta = json.loads(sidecar.read_text(encoding="utf-8"))
            clip = SoundClip(
                category=meta.get("category") or audio.parent.name, title=meta.get("title", ""),
                origin=meta.get("origin", "UPLOAD"), licence=meta.get("licence", ""),
                creator=meta.get("creator", ""), source_url=meta.get("source_url", ""),
                attribution=meta.get("attribution", ""),
                is_active=bool(meta.get("is_active", True)),
                quality_note=meta.get("quality_note", ""),
                duration=0, loudness_lufs=soundscape.measure_lufs(audio),
            )
            clip.file.name = f"sound_library/{audio.parent.name}/{audio.name}"
            try:
                from services.video.ffmpeg import probe_duration

                clip.duration = round(probe_duration(audio), 2)
            except Exception:  # noqa: BLE001
                pass
            clip.save()
            added += 1
        self.say(f"\n{added} ردیف از روی فایل‌های کتابخانه ساخته شد.",
                 f"Sound library: {added} recordings indexed from disk.")

    # ------------------------------------------------------------ check

    def missing(self) -> list[str]:
        """One English line per offline piece that is not in place.

        English because the console start.bat runs in does not render Persian.
        The online engines are not checked: they need nothing on this machine.
        """
        from apps.ai.models import SoundClip
        from services.audio import engines, soundscape

        lines = []
        for module, package in (("piper", "piper-tts"), ("noisereduce", "noisereduce"),
                                ("soundfile", "soundfile")):
            try:
                __import__(module)
            except ImportError:
                lines.append(f"[MISSING] Python package {package} - pip install {package}")

        folder = engines.models_dir() / "piper"
        for name in wanted_voices():
            if name not in VOICES:
                lines.append(f"[UNKNOWN] voice {name} named in the admin - no download source for it")
                continue
            model = folder / f"{name}.onnx"
            if not (_looks_complete(model) and _looks_complete(model.with_suffix(".onnx.json"))):
                lines.append(f"[MISSING] offline voice {name}")

        if engines.deepfilter_binary() is None:
            lines.append("[MISSING] DeepFilterNet - noise removal falls back to the lighter RNNoise")

        from django.conf import settings

        whisper_name = settings.UPMARKET_AI.get("WHISPER_MODEL", "small")
        if not _whisper_ready(whisper_name):
            lines.append(f"[MISSING] Whisper {whisper_name} - narration timing and subtitles of filmed videos")

        unindexed = len(self._unindexed())
        if unindexed:
            lines.append(f"[MISSING] {unindexed} sound library recordings are on disk but not indexed")
        covered = set(SoundClip.objects.filter(is_active=True).values_list("category", flat=True))
        # Code can make the noise-like sounds well; everything else needs a
        # real recording or it is simply absent from the video.
        empty = [k for k, kind in soundscape.CATALOGUE.items()
                 if k not in covered and not kind.procedural]
        if empty and not unindexed:
            lines.append(f"[MISSING] no recording yet for: {', '.join(empty)}")
        return lines

    def check_offline(self):
        """What the launcher asks. Exit 1 with the missing lines, or exit 0.

        Not called `check`: that name is BaseCommand's system-check hook, which
        Django runs before `handle()` on EVERY invocation. Overriding it meant
        that on a machine with anything missing, the download command printed
        the list and exited before downloading a byte.
        """
        import sys

        missing = self.missing()
        for line in missing:
            self.stdout.write(line)
        if missing:
            sys.exit(1)

    # ------------------------------------------------------------ status

    def status(self):
        from apps.ai.models import SoundClip
        from services.audio import engines

        self.stdout.write("\nوضعیت موتورهای صدا (همان که ادمین نشان می‌دهد):")
        role_names = {"VOICE": "گوینده", "SOUND": "صدای محیط", "DENOISE": "حذف نویز"}
        for row in engines.status():
            mark = "✓" if row["ready"] else "✗"
            where = "آفلاین" if row["local"] else "آنلاین"
            reason = "" if row["ready"] else f" — {row['reason']}"
            self.stdout.write(
                f"  {mark} {role_names[row['role']]:10s} [{row['priority']:>3}] {row['name']} ({where}){reason}"
            )
        self.stdout.write(f"\nکتابخانه‌ی صدا: {SoundClip.objects.filter(is_active=True).count()} صدای فعال")
