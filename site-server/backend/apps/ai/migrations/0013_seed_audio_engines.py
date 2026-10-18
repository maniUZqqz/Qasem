"""Every audio engine, pre-filled in the admin, so switching is a tick box.

Order out of the box (lowest priority number is tried first):

* VOICE — Edge TTS first (measured the clearest Persian: 11.7 % character
  error through Whisper, against 17.2 % for the best offline voice), Piper
  "gyro" right behind it as the offline fallback, and the paid APIs present
  but switched off until someone pastes a key.
* SOUND — the local library of real recordings, then sounds made with code,
  then a live Freesound (CC0) search that imports what it finds.
* DENOISE — DeepFilterNet, then RNNoise, then the plain FFT filter.

Only fills a role that has no rows yet, so re-running it never overwrites an
operator's choices.
"""
from django.db import migrations

# Only the pause between sentences. Speed and variation are left to each
# voice's own tuned config (the English voices differ from the Persian
# ones); an admin who wants to override them adds the keys here.
PIPER_OPTIONS = {"sentence_silence": 0.25}

ENGINES = [
    # ---- voice ----------------------------------------------------------
    dict(role="VOICE", kind="EDGE", name="Edge TTS (مایکروسافت، آنلاین)", priority=10, is_active=True,
         voice_fa="fa-IR-FaridNeural", voice_fa_female="fa-IR-DilaraNeural",
         voice_en="en-US-AndrewNeural", voice_en_female="en-US-AvaNeural",
         notes="واضح‌ترین صدای فارسی رایگان. متن نریشن به سرور مایکروسافت می‌رود."),
    dict(role="VOICE", kind="PIPER", name="Piper — صدای gyro (آفلاین)", priority=20, is_active=True,
         model_name="fa_IR-gyro-medium", voice_fa="fa_IR-gyro-medium",
         voice_fa_female="fa_IR-mana-medium",
         voice_en="en_US-hfc_male-medium", voice_en_female="en_US-hfc_female-medium",
         options=PIPER_OPTIONS,
         notes="روی همین سیستم، بدون اینترنت. مدل MIT (gyroing)، ساخته‌شده روی مدل OpenRAIL — "
               "استفاده‌ی تجاری مجاز. " + "صدای زن فارسی: mana (مدل MIT روی دیتاست ManaTTS با مجوز CC-0 — استفاده‌ی تجاری مجاز). اندازه‌گیری‌شده: ۲۴.۶٪ خطای Whisper در برابر ۱۲.۵٪ دیلارای آنلاین، پس پشتیبانِ آفلاین است نه اولویت اول."),
    dict(role="VOICE", kind="PIPER", name="Piper — صدای ganji (آفلاین)", priority=25, is_active=False,
         model_name="fa_IR-ganji-medium", voice_fa="fa_IR-ganji-medium",
         voice_en="en_US-hfc_male-medium", voice_en_female="en_US-hfc_female-medium",
         options=PIPER_OPTIONS,
         notes="صدای مرد دیگر، دیتاست CC0. کمی کمتر از gyro واضح است (۱۸.۹٪ در برابر ۱۷.۲٪ خطا)."),
    dict(role="VOICE", kind="AZURE", name="Azure Speech (پولی)", priority=40, is_active=False,
         base_url="westeurope", voice_fa="fa-IR-FaridNeural", voice_fa_female="fa-IR-DilaraNeural",
         voice_en="en-US-AndrewNeural", voice_en_female="en-US-AvaNeural", timeout_s=60,
         notes="همان صداهای Edge، با قرارداد و کلید رسمی."),
    dict(role="VOICE", kind="OPENAI_TTS", name="OpenAI / API سازگار (پولی)", priority=50, is_active=False,
         base_url="https://api.openai.com/v1", model_name="gpt-4o-mini-tts",
         voice_fa="onyx", voice_fa_female="nova", voice_en="onyx", voice_en_female="nova",
         options={"instructions": "گرم، طبیعی و صمیمی؛ مثل فروشنده‌ای که محصولش را دوست دارد، بدون اغراق."},
         notes="هر سرویسی که /v1/audio/speech دارد — OpenAI یا درگاه‌های ایرانی سازگار با آن."),
    dict(role="VOICE", kind="ELEVENLABS", name="ElevenLabs (پولی)", priority=60, is_active=False,
         model_name="eleven_v3", options={"stability": 0.5, "similarity_boost": 0.75},
         notes="شناسه‌ی صدا را از پنل ElevenLabs در «صدای فارسی» بگذارید."),
    dict(role="VOICE", kind="GTTS", name="Google Translate TTS (فقط انگلیسی)", priority=90, is_active=False,
         voice_en="en"),
    # ---- ambience & effects --------------------------------------------
    dict(role="SOUND", kind="SOUND_LIBRARY", name="کتابخانه‌ی صدای واقعی (آفلاین)", priority=10, is_active=True,
         notes="ضبط‌های واقعی CC0 از Freesound که یک بار دانلود شده‌اند. python manage.py audio_setup --library"),
    dict(role="SOUND", kind="PROCEDURAL", name="ساخت با کد (آفلاین)", priority=20, is_active=True,
         notes="فقط صداهایی که ذاتاً نویزند: سکوت اتاق، باران، باد، موج، ووش."),
    dict(role="SOUND", kind="OPENVERSE", name="جست‌وجوی Freesound (CC0، آنلاین)", priority=30, is_active=True,
         notes="وقتی کتابخانه برای یک صدا چیزی ندارد؛ آنچه پیدا شود به کتابخانه اضافه می‌شود."),
    dict(role="SOUND", kind="ELEVENLABS_SFX", name="ElevenLabs Sound Effects (پولی)", priority=60, is_active=False,
         options={"prompt_influence": 0.4}),
    # ---- noise removal --------------------------------------------------
    dict(role="DENOISE", kind="DEEPFILTER", name="DeepFilterNet (آفلاین، بهترین)", priority=10, is_active=True,
         options={"atten_lim_db": 30}, timeout_s=600,
         notes="python manage.py audio_setup --denoise · MIT/Apache"),
    dict(role="DENOISE", kind="RNNOISE", name="RNNoise (آفلاین، سریع)", priority=20, is_active=True,
         model_name="sh", options={"mix": 0.9}, notes="مدل همراه پروژه است."),
    dict(role="DENOISE", kind="SPECTRAL", name="noisereduce (آفلاین)", priority=30, is_active=False,
         options={"stationary": False, "prop_decrease": 0.85}),
    dict(role="DENOISE", kind="AFFTDN", name="فیلتر FFT ساده (آفلاین)", priority=40, is_active=True,
         options={"nr": 12}),
]


def seed(apps, schema_editor):
    AudioEngine = apps.get_model("ai", "AudioEngine")
    AudioMix = apps.get_model("ai", "AudioMix")
    for role in ("VOICE", "SOUND", "DENOISE"):
        if AudioEngine.objects.filter(role=role).exists():
            continue
        for row in ENGINES:
            if row["role"] == role:
                AudioEngine.objects.create(**row)
    if not AudioMix.objects.exists():
        AudioMix.objects.create()


def unseed(apps, schema_editor):
    """Nothing: removing rows an operator may have edited is not a rollback."""


class Migration(migrations.Migration):
    dependencies = [("ai", "0012_audioengine_audiomix_soundclip")]
    operations = [migrations.RunPython(seed, unseed)]
