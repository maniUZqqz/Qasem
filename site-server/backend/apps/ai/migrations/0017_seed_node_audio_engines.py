"""MOSS on the processing node in the admin's engine table.

* VOICE  NODE_MOSS  priority 5: before Edge (10) and Piper (20) — the commercially usable Persian voice. While no
  node with the models is on, readiness skips it in no time and Edge/Piper read as before.
* SOUND  NODE_SFX   priority 15: after the real-recording library (10), before the code-made sounds (20); what it
  makes joins the shared library, so each sound is generated once.

Rows an operator already made are left alone (matched by kind).
"""
from django.db import migrations

NOTE_MOSS = ("MOSS-TTS-Realtime + LoRA فارسی (Apache-2.0)؛ روی سرورِ پردازش با Download-Models.bat نصب می‌شود. "
             "صدای مرد/زن: شناسه‌ی صدای مرجع از کیتِ صدا (arash، kaveh، amir، reza، bahram، mana) یا lora.")
NOTE_SFX = "MOSS-SoundEffect v2.0 (Apache-2.0)؛ روی سرورِ پردازش. هر صدا یک بار ساخته و به کتابخانه اضافه می‌شود."


def forwards(apps, schema_editor):
    AudioEngine = apps.get_model("ai", "AudioEngine")
    if not AudioEngine.objects.filter(kind="NODE_MOSS").exists():
        AudioEngine.objects.create(role="VOICE", kind="NODE_MOSS", name="MOSS-TTS فارسی (سرورِ پردازش)", priority=5,
                                   is_active=True, voice_fa="arash", voice_fa_female="mana", timeout_s=900,
                                   notes=NOTE_MOSS)
    if not AudioEngine.objects.filter(kind="NODE_SFX").exists():
        AudioEngine.objects.create(role="SOUND", kind="NODE_SFX", name="MOSS-SoundEffect (سرورِ پردازش)", priority=15,
                                   is_active=True, timeout_s=900, notes=NOTE_SFX)


def backwards(apps, schema_editor):
    AudioEngine = apps.get_model("ai", "AudioEngine")
    AudioEngine.objects.filter(kind__in=["NODE_MOSS", "NODE_SFX"]).delete()


class Migration(migrations.Migration):
    dependencies = [("ai", "0016_audio_library")]
    operations = [migrations.RunPython(forwards, backwards)]
