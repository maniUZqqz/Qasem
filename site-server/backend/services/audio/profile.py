"""Voice Profile — the parts of it that are real for Persian. §22

The roadmap asked for gender, age, accent, pitch and emotion. Before building a
form with five dropdowns, I asked the voice engine what it actually has, and the
answer changes the feature:

    fa-IR-DilaraNeural   Female   Friendly, Positive
    fa-IR-FaridNeural    Male     Friendly, Positive

**Two Persian voices exist. That is the whole catalogue.** Both are adults, both
are Tehran-standard, both are tagged with one personality. So:

* **Gender** — real. Two voices, and picking between them is the single biggest
  change a shop can make to how their video sounds.
* **Pitch, speed, loudness** — real. SSML prosody, measured working: `-25%` rate
  took a 3.43-second line to 4.54 seconds, and `+15Hz` moved the energy above
  200 Hz up by 0.8 dB.
* **Age** — not possible. There is no Persian child or elderly voice to select.
* **Accent** — not possible. There is one Persian locale, `fa-IR`.
* **Emotion** — not possible *for Persian*. Style tags (`cheerful`, `sad`) exist
  in Azure's catalogue for some English voices and neither Persian voice carries
  them; `edge_tts.Communicate` has no style parameter at all.

The three that are not possible are **named and explained in the panel** rather
than shipped as dropdowns that quietly do nothing. A shop that sets "emotion:
excited" and hears no difference has learned that our settings are decorative,
and that is a worse outcome than the setting not existing.

**Pitch and speed are bounded on purpose.** Past roughly ±20% the neural voice
stops sounding like a person and starts sounding like a tape running wrong,
which is exactly the "AI slop" impression the whole product is trying to avoid.
"""
from __future__ import annotations

from dataclasses import dataclass

#: Persian voices, as edge-tts reports them. Not a guess — listed from the live
#: catalogue and confirmed to synthesise.
PERSIAN_VOICES = {
    "male": {
        "id": "fa-IR-FaridNeural",
        "label": "فرید — مردانه",
        "note": "صدای پیش‌فرض. گرم و خنثی.",
    },
    "female": {
        "id": "fa-IR-DilaraNeural",
        "label": "دلارا — زنانه",
        "note": "کمی روشن‌تر و سبک‌تر.",
    },
}

ENGLISH_VOICES = {
    "male": {"id": "en-US-AndrewNeural", "label": "Andrew", "note": ""},
    "female": {"id": "en-US-AvaNeural", "label": "Ava", "note": ""},
}

#: Past this the voice stops sounding like a person. The point of the product is
#: output a shop is willing to put their name on, and a chipmunk is not that.
MAX_RATE = 20        # percent
MAX_PITCH = 20       # Hz
MAX_VOLUME = 30      # percent

#: What each slider is for, in a sentence, because "سرعت: ۰" means nothing on
#: its own and a shop should know which way to move it and why.
GUIDANCE = {
    "rate": "کندتر برای توضیح فنی، تندتر برای تیزر کوتاه و پرانرژی.",
    "pitch": "پایین‌تر جدی‌تر و آرام‌تر، بالاتر جوان‌تر و سبک‌تر.",
    "volume": "معمولاً دست نزنید — بلندی نهایی خودش یکسان می‌شود.",
}

#: The three the roadmap asked for that do not exist for Persian. Shown, with
#: the reason. A dropdown that does nothing teaches a shop that our settings are
#: decorative, which costs more than the missing feature.
UNAVAILABLE = [
    {
        "key": "age",
        "label": "سن صدا",
        "why": (
            "هیچ صدای فارسیِ کودک یا سالمند وجود ندارد — کل کاتالوگ فارسی دو "
            "صدای بزرگسال است. «زیروبمی» نزدیک‌ترین چیزی است که داریم."
        ),
    },
    {
        "key": "accent",
        "label": "لهجه",
        "why": "فقط یک گویش فارسی (fa-IR) وجود دارد؛ لهجه‌ی منطقه‌ای نداریم.",
    },
    {
        "key": "emotion",
        "label": "احساس",
        "why": (
            "برچسب احساس (شاد، غمگین، هیجان‌زده) برای بعضی صداهای انگلیسی هست "
            "و برای هیچ‌کدام از دو صدای فارسی نیست. به‌جایش با **زیروبمی و "
            "سرعت** می‌شود لحن را عوض کرد."
        ),
    },
]


class ProfileError(Exception):
    """A setting outside what the engine can actually do."""


@dataclass
class VoiceProfile:
    """How a shop wants their narration to sound."""

    gender: str = "male"
    #: Percent, relative to the voice's natural speed.
    rate: int = 0
    #: Hertz, relative to the voice's natural pitch.
    pitch: int = 0
    #: Percent.
    volume: int = 0
    language: str = "fa"
    #: A ClonedVoice id (this store's): Persian narration in that voice instead of Farid/Dilara.
    #: Rate/pitch do not apply to it; English narration keeps the gender voice.
    cloned_voice: int | None = None
    cloned_voice_name: str = ""
    #: A MOSS default voice id (services.audio.node_audio.presets) — used when MOSS on the processing node
    #: narrates; empty = the admin's default for the gender.
    preset: str = ""

    def voice_id(self) -> str:
        catalogue = PERSIAN_VOICES if self.language == "fa" else ENGLISH_VOICES
        chosen = catalogue.get(self.gender)
        if chosen is None:
            raise ProfileError(
                f"«{self.gender}» شناخته نشد — یکی از: {'، '.join(catalogue)}"
            )
        return chosen["id"]

    def validate(self) -> None:
        for name, value, cap, unit in (
            ("سرعت", self.rate, MAX_RATE, "درصد"),
            ("زیروبمی", self.pitch, MAX_PITCH, "هرتز"),
            ("بلندی", self.volume, MAX_VOLUME, "درصد"),
        ):
            if abs(int(value)) > cap:
                raise ProfileError(
                    f"{name} باید بین {-cap} و {cap} {unit} باشد. بیشتر از این، "
                    "صدا دیگر شبیه آدم نیست — و ویدیویی که صدایش مصنوعی به نظر "
                    "برسد، همان تصوری را می‌سازد که می‌خواهیم از آن فرار کنیم."
                )
        self.voice_id()

    def as_kwargs(self) -> dict:
        """What `edge_tts.Communicate` takes.

        Zero values are left out rather than sent as "+0%": edge-tts accepts
        both, and omitting them keeps the request identical to an unmodified
        one, which makes a profile with nothing set genuinely free.
        """
        self.validate()
        out = {}
        if self.rate:
            out["rate"] = f"{self.rate:+d}%"
        if self.pitch:
            out["pitch"] = f"{self.pitch:+d}Hz"
        if self.volume:
            out["volume"] = f"{self.volume:+d}%"
        return out

    @property
    def is_default(self) -> bool:
        return not (self.rate or self.pitch or self.volume)

    def describe(self) -> str:
        """One line a shop can read back, in words rather than numbers."""
        if self.cloned_voice and self.language == "fa":
            return f"صدای کلون‌شدهٔ «{self.cloned_voice_name or self.cloned_voice}» (ساختهٔ ماشین)"
        catalogue = PERSIAN_VOICES if self.language == "fa" else ENGLISH_VOICES
        parts = [catalogue[self.gender]["label"]]
        if self.rate:
            parts.append("کندتر" if self.rate < 0 else "تندتر")
        if self.pitch:
            parts.append("بم‌تر" if self.pitch < 0 else "زیرتر")
        if self.volume:
            parts.append("آرام‌تر" if self.volume < 0 else "بلندتر")
        return "، ".join(parts)

    def as_dict(self) -> dict:
        return {
            "gender": self.gender,
            "rate": self.rate,
            "pitch": self.pitch,
            "volume": self.volume,
            "language": self.language,
            "cloned_voice": self.cloned_voice,
            "preset": self.preset,
            "voice_id": self.voice_id(),
            "description": self.describe(),
        }

    @classmethod
    def from_store(cls, store, language: str = "fa") -> "VoiceProfile":
        """The shop's saved profile, or the default if they have not set one."""
        try:
            saved = store.profile.voice_profile or {}
        except Exception:  # noqa: BLE001 — no profile row yet
            saved = {}
        cloned, cloned_name = saved.get("cloned_voice"), ""
        if cloned:
            # a voice deleted since is not a choice any more (deleting also clears it; this is the backstop)
            try:
                from apps.ai.models import ClonedVoice

                row = ClonedVoice.objects.filter(pk=int(cloned), store=store).only("pk", "name").first()
            except Exception:  # noqa: BLE001 — no database (engine-level tests) or a bad value
                row = None
            cloned, cloned_name = (row.pk, row.name) if row is not None else (None, "")
        return cls(
            gender=str(saved.get("gender", "male")),
            rate=int(saved.get("rate", 0) or 0),
            pitch=int(saved.get("pitch", 0) or 0),
            volume=int(saved.get("volume", 0) or 0),
            language=language,
            cloned_voice=cloned,
            cloned_voice_name=cloned_name,
            preset=str(saved.get("preset") or "")[:40],
        )


def options(language: str = "fa") -> dict:
    """Everything the panel needs to draw the form — including the refusals."""
    catalogue = PERSIAN_VOICES if language == "fa" else ENGLISH_VOICES
    return {
        "voices": [
            {"key": key, **value} for key, value in catalogue.items()
        ],
        "sliders": [
            {"key": "rate", "label": "سرعت", "min": -MAX_RATE, "max": MAX_RATE,
             "unit": "٪", "hint": GUIDANCE["rate"]},
            {"key": "pitch", "label": "زیروبمی", "min": -MAX_PITCH, "max": MAX_PITCH,
             "unit": "Hz", "hint": GUIDANCE["pitch"]},
            {"key": "volume", "label": "بلندی", "min": -MAX_VOLUME, "max": MAX_VOLUME,
             "unit": "٪", "hint": GUIDANCE["volume"]},
        ],
        "unavailable": UNAVAILABLE,
        "note": (
            "کاتالوگ صدای فارسی دو صدا دارد — همین. آنچه در این صفحه نیست، "
            "به این دلیل نیست که نساخته‌ایم؛ موتور صدا ندارد."
        ),
    }
