"""Which Whisper model should this machine use? Measure it, do not guess.

The honest answer is "it depends on your GPU and your audio", and that is not
something I can work out from here — the box this was written on has no GPU and
no Persian speech to try. So instead of shipping a default chosen by vibes, this
runs the candidates against a clip you actually care about and prints what each
one costs and produces.

**Read the transcripts, not just the times.** A model twice as fast that turns
«نایکی» into «نای کی» is not faster at the job; it is fast at a different job.
The times are here because they bound how many videos an hour the box can do,
and the text is here because it decides whether any of them are worth doing.

    python manage.py whisperbench path/to/clip.mp3
    python manage.py whisperbench clip.mp3 --models small,medium
    python manage.py whisperbench clip.mp3 --expect "کفش نایکی اصل"
"""
import time

from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Compare Whisper models on a real clip, on this machine."

    def add_arguments(self, parser):
        parser.add_argument("audio", help="An audio or video file with Persian speech in it")
        parser.add_argument(
            "--models", default="tiny,base,small",
            help="Comma-separated. `medium` and `large-v3` are slow but much better.",
        )
        parser.add_argument("--language", default="fa")
        parser.add_argument(
            "--expect", default="",
            help="What was actually said. Turns the comparison into a score instead of a reading exercise.",
        )

    def handle(self, *args, **options):
        from pathlib import Path

        from services.audio import transcribe

        ok, why = transcribe.available()
        if not ok:
            raise CommandError(why)

        audio = Path(options["audio"])
        if not audio.exists():
            raise CommandError(f"فایل پیدا نشد: {audio}")

        wanted = [m.strip() for m in options["models"].split(",") if m.strip()]
        unknown = [m for m in wanted if m not in transcribe.MODELS]
        if unknown:
            raise CommandError(
                f"مدل‌های ناشناخته: {'، '.join(unknown)}. "
                f"موجود: {'، '.join(transcribe.MODELS)}"
            )

        device = transcribe._device()
        self.stdout.write(f"\nدستگاه: {device}")
        if device == "cpu":
            self.stdout.write(self.style.WARNING(
                "روی CPU اجرا می‌شود و کند است. اگر کارت گرافیک دارید، "
                "WHISPER_DEVICE=cuda را در .env بگذارید."
            ))
        self.stdout.write(f"فایل: {audio.name}\n")

        expected = options["expect"].strip()
        rows = []

        for model in wanted:
            self.stdout.write(f"  … {model}")
            started = time.monotonic()
            try:
                result = transcribe.transcribe(
                    audio, language=options["language"], model=model,
                )
            except Exception as exc:  # noqa: BLE001 — one model failing is data
                self.stdout.write(self.style.ERROR(f"     شکست: {exc}"))
                continue
            took = time.monotonic() - started

            # Seconds of audio per second of compute. The number that decides
            # how many videos an hour this box can subtitle — wall-clock alone
            # says nothing without the clip's length.
            speed = (result.seconds / took) if took else 0
            rows.append({
                "model": model,
                "seconds": took,
                "speed": speed,
                "words": len(result.words),
                "uncertain": result.uncertain_count,
                "text": result.text,
                "score": _similarity(expected, result.text) if expected else None,
            })

        if not rows:
            raise CommandError("هیچ مدلی اجرا نشد.")

        self.stdout.write("\n" + "─" * 72)
        header = f"{'مدل':<10} {'ثانیه':>8} {'سرعت':>8} {'کلمه':>6} {'نامطمئن':>8}"
        if expected:
            header += f" {'دقت':>7}"
        self.stdout.write(header)
        self.stdout.write("─" * 72)

        for row in rows:
            line = (
                f"{row['model']:<10} {row['seconds']:>8.1f} "
                f"{row['speed']:>7.1f}x {row['words']:>6} {row['uncertain']:>8}"
            )
            if expected:
                line += f" {row['score'] * 100:>6.0f}%"
            self.stdout.write(line)

        self.stdout.write("\n" + "─" * 72)
        for row in rows:
            self.stdout.write(f"\n[{row['model']}]")
            self.stdout.write(f"  {row['text'][:400]}")

        self.stdout.write("\n" + "─" * 72)
        if expected:
            best = max(rows, key=lambda r: r["score"])
            self.stdout.write(self.style.SUCCESS(
                f"دقیق‌ترین: {best['model']} ({best['score'] * 100:.0f}٪)"
            ))
            # Named separately from "best", because the fastest model that is
            # accurate enough is usually the right answer and the most accurate
            # one is usually not.
            good = [r for r in rows if r["score"] >= best["score"] - 0.05]
            fastest = min(good, key=lambda r: r["seconds"])
            if fastest["model"] != best["model"]:
                self.stdout.write(self.style.SUCCESS(
                    f"سریع‌ترینِ به‌اندازه‌ی کافی دقیق: {fastest['model']} "
                    f"({fastest['score'] * 100:.0f}٪، {fastest['seconds']:.1f} ثانیه)"
                ))
        else:
            self.stdout.write(
                "متن‌ها را بخوانید و ببینید کدام اسم برندها و اعداد را درست "
                "شنیده. برای نمره‌ی عددی، --expect را با متن واقعی بدهید."
            )

        self.stdout.write(
            "\nانتخابتان را اینجا بگذارید:  WHISPER_MODEL=<مدل>  در backend/.env\n"
        )


def _similarity(expected: str, heard: str) -> float:
    """How much of what was said came back, word by word.

    Word-level rather than character-level: a model that hears every word and
    spells one differently has done the job, and a character diff would punish
    it the same as one that missed a sentence.
    """
    import difflib
    import re

    token = re.compile(r"[\w؀-ۿ‌]+")
    a = [w.lower() for w in token.findall(expected)]
    b = [w.lower() for w in token.findall(heard)]
    if not a:
        return 0.0
    return difflib.SequenceMatcher(None, a, b, autojunk=False).ratio()
