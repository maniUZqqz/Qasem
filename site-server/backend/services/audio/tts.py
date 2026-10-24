"""The narrator: text in, a human voice out — from whichever engine the admin chose.

Six engines, one interface (`synthesize(text, out_path) -> Path`):

| engine      | where it runs         | Persian voices                       | cost        |
|-------------|-----------------------|--------------------------------------|-------------|
| Piper       | this machine, offline | gyro, ganji, amir, reza (male), mana (female) | free |
| Edge TTS    | Microsoft, online     | Farid (male), Dilara (female)        | free        |
| Azure       | Microsoft, API        | the same two, official SLA           | paid        |
| OpenAI-like | any /v1/audio/speech  | multilingual voices                  | paid / self |
| ElevenLabs  | API                   | multilingual voices (eleven_v3)      | paid        |
| gTTS        | Google, online        | none — English only                  | free        |

Which one speaks is decided in the admin (`AudioEngine`, role VOICE): the
active rows are tried in priority order and the next takes over when one
fails, so Piper behind Edge means a video still gets its narration the day
Microsoft is unreachable. `ChainTTSProvider.used` records who actually spoke.

**Where the text goes is part of each engine's contract** (`is_local`). A shop
on «فقط لوکال» only ever reaches Piper; before Piper existed that shop could
not narrate at all, and the privacy page would have been a lie the moment it
could.

Piper's Persian voices were measured, not assumed: four voices, all trained on
CC0 datasets (free for commercial use), synthesised on this 4-core CPU at a
real-time factor of about 0.07 — eight seconds of speech in half a second.
The Persian ones were all male until Mana (MahtaFetrat/Mana-Persian-Piper,
MIT, trained on the CC-0 ManaTTS corpus): measured median pitch 220 Hz — a
female voice — and 24.6 % Whisper character error on shop sentences, against
14.6 % for gyro and 12.5 % for Edge's Dilara. So Dilara stays first for a
female narrator and Mana is what speaks offline or under «فقط لوکال».
"""
from __future__ import annotations

import logging
import wave
from pathlib import Path

from django.conf import settings

from . import engines as engine_registry

logger = logging.getLogger(__name__)


class TTSError(Exception):
    pass


class BaseTTSProvider:
    name = "base"
    # Where the narration text goes. Every engine must answer this, because the
    # data policy layer asks it before the first byte is sent.
    is_local = False
    processor = "نامشخص"
    #: The voice id actually used — reported with the result.
    voice = ""

    def synthesize(self, text: str, out_path) -> Path:  # pragma: no cover - interface
        raise NotImplementedError

    def describe(self) -> dict:
        return {
            "engine": self.name, "voice": self.voice,
            "local": self.is_local, "processor": self.processor,
        }


SUPPORTED_LANGUAGES = ("fa", "en")


def voice_for_language(language: str) -> str:
    """Edge voice for a narration language ('fa' or 'en'), from settings."""
    conf = settings.UPMARKET_AI
    if language == "en":
        return conf.get("TTS_VOICE_EN", "en-US-ChristopherNeural")
    return conf.get("TTS_VOICE_FA", conf.get("TTS_VOICE", "fa-IR-FaridNeural"))


def _require_output(out: Path, engine: str) -> Path:
    if not out.exists() or out.stat().st_size == 0:
        raise TTSError(f"{engine} produced no audio")
    return out


# ------------------------------------------------------------------ Piper


#: Loaded voices, kept for the life of the worker. Loading reads a 63 MB ONNX
#: file and takes about two seconds; a six-scene video would otherwise pay that
#: six times.
_PIPER_CACHE: dict[str, object] = {}


class PiperProvider(BaseTTSProvider):
    """Piper — a VITS voice in ONNX, on this machine's CPU. Offline, free.

    Tuning that matters for naturalness, all overridable per engine row in the
    admin (`options`):

    * `length_scale` — speed. >1 is slower. The shop's voice-profile rate
      scales it.
    * `noise_scale` / `noise_w` — how much the model varies pitch and timing.
      Too low sounds flat and robotic; too high wobbles. Left out, each
      voice uses the values it was tuned at (its own .onnx.json).
    * `sentence_silence` — a real pause between sentences. Piper reads a
      paragraph as one breathless run without it, which is the single most
      "synthetic" thing about it.
    """

    name = "piper"
    is_local = True
    processor = "Piper روی همین سیستم (آفلاین)"

    def __init__(self, model: str, *, options: dict | None = None, rate: int = 0):
        self.voice = (model or "fa_IR-gyro-medium").removesuffix(".onnx")
        self.options = dict(options or {})
        self.rate = int(rate or 0)

    def _load(self):
        path = engine_registry.piper_model_path(self.voice)
        if not path.exists() or not path.with_suffix(".onnx.json").exists():
            raise TTSError(
                f"مدل صدای Piper «{self.voice}» کامل دانلود نشده — python manage.py audio_setup --voices"
            )
        key = str(path)
        if key not in _PIPER_CACHE:
            try:
                from piper import PiperVoice

                _PIPER_CACHE[key] = PiperVoice.load(str(path))
            except ImportError as exc:
                raise TTSError("piper-tts نصب نیست — pip install piper-tts") from exc
            except Exception as exc:  # noqa: BLE001 — a corrupt or partial model file
                raise TTSError(f"مدل صدای Piper «{self.voice}» باز نشد: {exc}") from exc
        return _PIPER_CACHE[key]

    def _config(self, voice):
        """Synthesis settings: the voice's OWN tuning unless the admin overrode it.

        Each Piper voice ships with the length/noise values it was tuned at
        (the English hfc voices use 0.8 / 0.333; the Persian ones 1.0 / 0.667).
        Forcing one set on every voice made the English narrator 25 % slower
        and wobblier, so an option the admin left out is passed as None and
        Piper uses the voice's own. The shop's speed setting scales whatever
        the base is.
        """
        from piper import SynthesisConfig

        tuned = getattr(voice, "config", None)
        length = self.options.get("length_scale")
        if length is None:
            length = getattr(tuned, "length_scale", None)
        if self.rate:
            # A profile's "+10 %" means faster, i.e. shorter phonemes.
            base = float(length) if length is not None else 1.0
            length = max(0.6, min(1.6, base / (1 + self.rate / 100.0)))

        def option(name):
            value = self.options.get(name)
            return None if value is None else float(value)

        return SynthesisConfig(
            length_scale=None if length is None else float(length),
            noise_scale=option("noise_scale"),
            noise_w_scale=option("noise_w"),
        )

    def synthesize(self, text: str, out_path) -> Path:
        """Write the narration. Returns the path actually written.

        Asked for an .mp3, it writes a .wav next to it instead and returns
        that: Piper's output is PCM, and encoding it to MP3 only to decode it
        again for the polish step would be a lossy generation for nothing.
        """
        out = Path(out_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        wav = out.with_suffix(".wav")
        silence = float(self.options.get("sentence_silence", 0.25))
        try:
            voice = self._load()
            config = self._config(voice)
            with wave.open(str(wav), "wb") as handle:
                first = True
                last = None
                for chunk in voice.synthesize(_normalise_persian(text), syn_config=config):
                    if first:
                        handle.setframerate(chunk.sample_rate)
                        handle.setsampwidth(chunk.sample_width)
                        handle.setnchannels(chunk.sample_channels)
                        first = False
                    else:
                        # One pause per sentence boundary: Piper yields one chunk
                        # per sentence.
                        handle.writeframes(
                            b"\x00" * int(chunk.sample_rate * silence)
                            * chunk.sample_width * chunk.sample_channels
                        )
                    handle.writeframes(chunk.audio_int16_bytes)
                    last = chunk
                if last is None:
                    raise TTSError("Piper produced no audio")
                # A breath after the last word. Piper stops dead on the final
                # phoneme; a person does not, and without it the audio QC
                # (rightly) hears a sentence that was cut off, and the next
                # scene's first word arrives with no gap.
                handle.writeframes(
                    b"\x00" * int(last.sample_rate * max(0.3, silence))
                    * last.sample_width * last.sample_channels
                )
        except TTSError:
            raise
        except Exception as exc:  # noqa: BLE001 — anything else must still fall through the chain
            raise TTSError(f"Piper synthesis failed (voice={self.voice}): {exc}") from exc
        return _require_output(wav, "Piper")


def _normalise_persian(text: str) -> str:
    """Letters and punctuation the Persian phonemiser actually knows.

    Arabic kaf/yeh render the same but are different code points, and espeak's
    Persian dictionary is keyed on the Persian ones — "كتاب" with an Arabic
    kaf is spelled out instead of read. Persian digits are left alone; numbers
    were already turned into words by the lexicon before this runs.
    """
    table = str.maketrans({"ك": "ک", "ي": "ی", "ى": "ی", "ة": "ه", "ۀ": "ه‌ی"})
    return (text or "").translate(table)


# ------------------------------------------------------------------- Edge


class EdgeTTSProvider(BaseTTSProvider):
    """Microsoft Edge neural TTS (needs internet). Persian: FaridNeural / DilaraNeural."""

    name = "edge"
    is_local = False
    processor = "مایکروسافت (Edge TTS)"

    def __init__(self, voice=None, profile=None):
        #: A VoiceProfile overrides the voice, because the gender IS the voice —
        #: there are exactly two Persian voices and picking one is the setting.
        self.profile = profile
        if voice:
            self.voice = voice
        elif profile is not None:
            self.voice = profile.voice_id()
        else:
            self.voice = settings.UPMARKET_AI.get("TTS_VOICE", "fa-IR-FaridNeural")

    def synthesize(self, text: str, out_path) -> Path:
        try:
            import asyncio

            import edge_tts
        except ImportError as exc:
            raise TTSError("edge-tts is not installed — pip install edge-tts") from exc
        out = Path(out_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        # Prosody only when the shop actually changed something: an unset
        # profile sends the same request an unset provider would, so a default
        # profile costs nothing and cannot change the output.
        tuning = self.profile.as_kwargs() if self.profile is not None else {}
        try:
            communicate = edge_tts.Communicate(text, self.voice, **tuning)
            asyncio.run(communicate.save(str(out)))
        except Exception as exc:  # network / voice errors
            raise TTSError(f"edge-tts synthesis failed (voice={self.voice}): {exc}") from exc
        return _require_output(out, "edge-tts")


# ------------------------------------------------------------------ Azure


class AzureTTSProvider(BaseTTSProvider):
    """Azure Speech — the paid, contracted version of the Edge voices.

    Same Persian voices as Edge, but with a key, a region, an SLA and SSML
    prosody. `base_url` holds either the region ("westeurope") or a full
    endpoint URL.
    """

    name = "azure"
    is_local = False
    processor = "مایکروسافت (Azure Speech)"

    def __init__(self, engine: engine_registry.Engine, voice: str, profile=None):
        self.engine = engine
        self.voice = voice or "fa-IR-FaridNeural"
        self.profile = profile

    def _endpoint(self) -> str:
        base = self.engine.base_url.strip().rstrip("/")
        if base.startswith("http"):
            return base if base.endswith("/v1") else f"{base}/cognitiveservices/v1"
        return f"https://{base}.tts.speech.microsoft.com/cognitiveservices/v1"

    def synthesize(self, text: str, out_path) -> Path:
        import html

        import requests

        out = Path(out_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        lang = "-".join(self.voice.split("-")[:2]) or "fa-IR"
        prosody = self.profile.as_kwargs() if self.profile is not None else {}
        attrs = " ".join(f'{k}="{v}"' for k, v in prosody.items())
        body = html.escape(text)
        if attrs:
            body = f"<prosody {attrs}>{body}</prosody>"
        ssml = (
            f'<speak version="1.0" xml:lang="{lang}" xmlns="http://www.w3.org/2001/10/synthesis">'
            f'<voice name="{self.voice}">{body}</voice></speak>'
        )
        try:
            response = requests.post(
                self._endpoint(),
                data=ssml.encode("utf-8"),
                headers={
                    "Ocp-Apim-Subscription-Key": self.engine.api_key,
                    "Content-Type": "application/ssml+xml",
                    "X-Microsoft-OutputFormat": "audio-48khz-192kbitrate-mono-mp3",
                    "User-Agent": "UpMarket",
                },
                timeout=self.engine.timeout_s,
            )
        except Exception as exc:  # noqa: BLE001
            raise TTSError(f"Azure TTS unreachable: {exc}") from exc
        if response.status_code != 200:
            raise TTSError(f"Azure TTS {response.status_code}: {response.text[:200]}")
        out.write_bytes(response.content)
        return _require_output(out, "Azure TTS")


# ----------------------------------------------------------------- OpenAI


class OpenAITTSProvider(BaseTTSProvider):
    """Any server that speaks OpenAI's `/v1/audio/speech`.

    OpenAI itself (gpt-4o-mini-tts, which takes a free-text `instructions`
    field for tone), Iranian gateways that proxy it, and self-hosted servers
    that copy the API. The tone instruction lives in the engine's options, so
    "گرم و صمیمی، مثل فروشنده‌ای که محصول را دوست دارد" is an admin setting.
    """

    name = "openai_tts"
    is_local = False
    processor = "API گفتار سازگار با OpenAI"

    def __init__(self, engine: engine_registry.Engine, voice: str, rate: int = 0):
        self.engine = engine
        self.voice = voice or "onyx"
        self.rate = int(rate or 0)

    def synthesize(self, text: str, out_path) -> Path:
        import requests

        out = Path(out_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "model": self.engine.model_name or "gpt-4o-mini-tts",
            "input": text,
            "voice": self.voice,
            "response_format": "mp3",
        }
        instructions = self.engine.options.get("instructions")
        if instructions:
            payload["instructions"] = instructions
        if self.rate:
            payload["speed"] = round(1 + self.rate / 100.0, 2)
        url = self.engine.base_url.rstrip("/") + "/audio/speech"
        try:
            response = requests.post(
                url, json=payload, timeout=self.engine.timeout_s,
                headers={"Authorization": f"Bearer {self.engine.api_key}"},
            )
        except Exception as exc:  # noqa: BLE001
            raise TTSError(f"OpenAI-compatible TTS unreachable: {exc}") from exc
        if response.status_code != 200:
            raise TTSError(f"OpenAI-compatible TTS {response.status_code}: {response.text[:200]}")
        out.write_bytes(response.content)
        return _require_output(out, "OpenAI TTS")


# ------------------------------------------------------------- ElevenLabs


class ElevenLabsProvider(BaseTTSProvider):
    """ElevenLabs text-to-speech. The most expressive of the lot, and paid.

    Persian needs a multilingual model that covers it (eleven_v3 at the time
    of writing); the model is an admin setting so a newer one is a field edit.
    """

    name = "elevenlabs"
    is_local = False
    processor = "ElevenLabs"

    def __init__(self, engine: engine_registry.Engine, voice: str):
        self.engine = engine
        self.voice = voice

    def synthesize(self, text: str, out_path) -> Path:
        import requests

        if not self.voice:
            raise TTSError("شناسه‌ی صدای ElevenLabs در ادمین وارد نشده")
        out = Path(out_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        base = (self.engine.base_url or "https://api.elevenlabs.io").rstrip("/")
        options = self.engine.options
        payload = {
            "text": text,
            "model_id": self.engine.model_name or "eleven_v3",
            "voice_settings": {
                "stability": float(options.get("stability", 0.5)),
                "similarity_boost": float(options.get("similarity_boost", 0.75)),
                "style": float(options.get("style", 0.0)),
                "use_speaker_boost": bool(options.get("use_speaker_boost", True)),
            },
        }
        try:
            response = requests.post(
                f"{base}/v1/text-to-speech/{self.voice}?output_format=mp3_44100_128",
                json=payload, timeout=self.engine.timeout_s,
                headers={"xi-api-key": self.engine.api_key},
            )
        except Exception as exc:  # noqa: BLE001
            raise TTSError(f"ElevenLabs unreachable: {exc}") from exc
        if response.status_code != 200:
            raise TTSError(f"ElevenLabs {response.status_code}: {response.text[:200]}")
        out.write_bytes(response.content)
        return _require_output(out, "ElevenLabs")


# ------------------------------------------------------------------ gTTS


class GTTSProvider(BaseTTSProvider):
    """Google Translate TTS. NOTE: does not support Persian ('fa') — validated up front."""

    name = "gtts"
    is_local = False
    processor = "گوگل (Google Translate TTS)"

    def __init__(self, language=None):
        self.language = language or settings.UPMARKET_AI.get("TTS_LANGUAGE", "fa")
        self.voice = f"gtts-{self.language}"
        try:
            from gtts.lang import tts_langs
        except ImportError as exc:
            raise TTSError("gTTS is not installed — pip install gTTS") from exc
        supported = tts_langs()
        if self.language not in supported:
            raise TTSError(
                f"gTTS does not support language '{self.language}' (Persian is NOT supported). "
                f"Use TTS_PROVIDER=edge for Persian voices."
            )

    def synthesize(self, text: str, out_path) -> Path:
        from gtts import gTTS

        out = Path(out_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        try:
            gTTS(text=text, lang=self.language).save(str(out))
        except Exception as exc:
            raise TTSError(f"gTTS synthesis failed: {exc}") from exc
        return _require_output(out, "gTTS")


# ------------------------------------------------------------------ chain


class ChainTTSProvider(BaseTTSProvider):
    """Several engines, tried in the admin's order until one speaks.

    `used` is the provider that produced the last take. It matters because a
    video narrated by the fallback sounds different from one narrated by the
    primary, and the result must say so rather than let the shop wonder why
    today's voice is not yesterday's.
    """

    name = "chain"

    def __init__(self, providers: list[BaseTTSProvider]):
        if not providers:
            raise TTSError("هیچ موتور گوینده‌ای در دسترس نیست")
        self.providers = providers
        self.used: BaseTTSProvider | None = None
        self.failures: list[str] = []
        primary = providers[0]
        self.name = primary.name
        self.voice = primary.voice
        self.processor = primary.processor
        self.is_local = all(p.is_local for p in providers)

    def synthesize(self, text: str, out_path) -> Path:
        errors = []
        # Once one engine has spoken in this job, stay with it: a narration
        # that switches voice between scenes is worse than a slower engine.
        order = self.providers
        if self.used is not None:
            order = [self.used] + [p for p in self.providers if p is not self.used]
        for provider in order:
            try:
                result = provider.synthesize(text, out_path)
            except TTSError as exc:
                errors.append(f"{provider.name}: {exc}")
                logger.info("TTS engine %s failed, trying the next: %s", provider.name, exc)
                continue
            if self.used is not None and provider is not self.used:
                self.failures.append(
                    f"صدای «{self.used.name}» در دسترس نبود و «{provider.name}» جایش خواند"
                )
            self.used = provider
            self.voice = provider.voice
            self.processor = provider.processor
            return result
        raise TTSError(" | ".join(errors) or "هیچ موتوری صدا نساخت")

    def describe(self) -> dict:
        speaker = self.used or self.providers[0]
        out = speaker.describe()
        out["fallbacks"] = [p.name for p in self.providers[1:]]
        out["notes"] = list(self.failures)
        return out


# ------------------------------------------------------------------ build


def _profile(store, language: str):
    if store is None:
        return None
    from services.audio.profile import VoiceProfile

    try:
        profile = VoiceProfile.from_store(store, language or "fa")
        profile.validate()
        return profile
    except Exception:  # noqa: BLE001 — a bad saved profile is not a reason to refuse narration
        return None


def build_provider(engine: engine_registry.Engine, language: str, profile=None) -> BaseTTSProvider:
    """One configured engine → a provider for this language."""
    gender = getattr(profile, "gender", "male") or "male"
    rate = getattr(profile, "rate", 0) or 0
    kind = engine.kind
    if kind == "PIPER":
        model = engine.voice(language, gender) or engine.model_name
        if language == "fa" and model and not model.startswith("fa_"):
            model = engine.model_name or "fa_IR-gyro-medium"
        return PiperProvider(model, options=engine.options, rate=rate)
    if kind == "EDGE":
        voice = engine.voice(language, gender) or voice_for_language(language)
        return EdgeTTSProvider(voice=voice, profile=profile)
    if kind == "AZURE":
        return AzureTTSProvider(engine, engine.voice(language, gender), profile)
    if kind == "OPENAI_TTS":
        return OpenAITTSProvider(engine, engine.voice(language, gender), rate)
    if kind == "ELEVENLABS":
        return ElevenLabsProvider(engine, engine.voice(language, gender))
    if kind == "GTTS":
        return GTTSProvider(language=language)
    raise TTSError(f"Unknown voice engine '{kind}'")


def get_tts_provider(language: str | None = None, store=None, *, profile=None) -> BaseTTSProvider:
    """The narrator for a language, honouring the admin's order and the store's policy.

    Returns the single provider when only one engine is usable, and a chain
    otherwise. `store` is optional only so the engine-level tests can build a
    provider without a database; every real call site passes one. `profile`
    overrides the store's saved voice profile — the settings page previews a
    profile before the shop saves it.
    """
    if language is not None and language not in SUPPORTED_LANGUAGES:
        raise TTSError(f"Unsupported TTS language '{language}' — supported: {SUPPORTED_LANGUAGES}")
    language = language or "fa"
    if profile is None:
        profile = _profile(store, language)
    gender = getattr(profile, "gender", "male") or "male"

    # The shop's own cloned voice (Persian): spoken by a processing node and never swapped for
    # another voice — with no node on, narration stops and says why (services.audio.voice_clone).
    clone_id = getattr(profile, "cloned_voice", None)
    if clone_id and language == "fa":
        from . import voice_clone

        return voice_clone.provider_for(store, clone_id)

    resolution = engine_registry.resolve(engine_registry.VOICE, store)
    if not resolution.engines:
        if engine_registry.local_only(store):
            raise TTSError(
                "سیاست این فروشگاه «فقط لوکال» است و هیچ گوینده‌ی لوکالی آماده نیست "
                f"({resolution.explain()}). در ادمین «موتورهای صدا» Piper را فعال کنید و "
                "مدلش را با python manage.py audio_setup --voices دانلود کنید؛ یا سیاست را "
                "تغییر دهید."
            )
        raise TTSError(f"هیچ موتور گوینده‌ای آماده نیست: {resolution.explain()}")

    # Engines that actually have a voice for this language and gender go
    # first; the rest stay as a fallback rather than being dropped, because a
    # male voice is better than no narration.
    exact = [e for e in resolution.engines if e.has_voice(language, gender) or e.kind == "GTTS"]
    rest = [e for e in resolution.engines if e not in exact]
    providers = []
    for engine in exact + rest:
        if engine.kind == "GTTS" and language == "fa":
            continue
        if engine.kind == "PIPER" and not engine.voice(language, gender) and language == "en":
            continue
        try:
            built = build_provider(engine, language, profile)
        except TTSError as exc:
            logger.info("Voice engine %s unusable: %s", engine.name, exc)
            continue
        # Whether this engine has a voice of the chosen gender, or would read
        # with its other one — shown on the voice settings page.
        built.exact_voice = engine.kind == "GTTS" or engine.has_voice(language, gender)
        providers.append(built)
    if not providers:
        raise TTSError(f"هیچ موتوری برای زبان «{language}» صدا ندارد")
    provider = providers[0] if len(providers) == 1 else ChainTTSProvider(providers)
    _enforce_policy(provider, store)
    return provider


def speakers(language: str, store=None, *, profile=None) -> dict:
    """Who would read this shop's narration, in order — without saying a word.

    For the voice settings page: the first entry is the voice the shop will
    hear, the rest take over if it fails. `exact` is False for an engine that
    has no voice of the chosen gender (it would read with its other voice),
    which is how a shop learns that a female Persian voice needs the
    internet. Never raises; `error` explains an empty list.
    """
    try:
        provider = get_tts_provider(language, store, profile=profile)
    except TTSError as exc:
        return {"speakers": [], "error": str(exc)}
    chain = provider.providers if isinstance(provider, ChainTTSProvider) else [provider]
    gender = getattr(profile, "gender", None) or getattr(_profile(store, language), "gender", "male")
    female = gender == "female"
    rows = []
    for item in chain:
        # Set by get_tts_provider from the engine row: does it have a voice of
        # this gender, or would it read with its other one?
        exact = bool(getattr(item, "exact_voice", True)) if female else True
        rows.append({**item.describe(), "exact": exact})
    return {"speakers": rows, "error": ""}


def _enforce_policy(provider: BaseTTSProvider, store) -> None:
    """Refuse an external voice when the store said its data stays home.

    The engine resolution already filters external engines for such a store;
    this is the second lock on the same door, for providers built by hand.
    """
    if provider.is_local:
        return
    if not engine_registry.local_only(store):
        return
    raise TTSError(
        f"سیاست این فروشگاه «فقط لوکال» است، ولی صداگذاری از {provider.processor} "
        "استفاده می‌کند و متن نریشن به سرور بیرونی می‌رود. در ادمین «موتورهای صدا» "
        "گوینده‌ی لوکال (Piper) را فعال کنید یا سیاست را تغییر دهید."
    )
