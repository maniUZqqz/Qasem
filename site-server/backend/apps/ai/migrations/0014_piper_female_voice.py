"""Give the offline Persian narrator a female voice: Mana.

Installs seeded before it existed have Piper rows with no female Persian
voice, so a shop that chose «زنانه» under «فقط لوکال» got the male one.
Only rows that have none are filled in — a voice an operator typed in the
admin is theirs.
"""
from django.db import migrations

MANA = "fa_IR-mana-medium"
NOTE = "صدای زن فارسی: mana (مدل MIT روی دیتاست ManaTTS با مجوز CC-0 — استفاده‌ی تجاری مجاز). اندازه‌گیری‌شده: ۲۴.۶٪ خطای Whisper در برابر ۱۲.۵٪ دیلارای آنلاین، پس پشتیبانِ آفلاین است نه اولویت اول."


def forwards(apps, schema_editor):
    AudioEngine = apps.get_model("ai", "AudioEngine")
    for row in AudioEngine.objects.filter(kind="PIPER", voice_fa_female=""):
        row.voice_fa_female = MANA
        notes = (row.notes or "").replace("فقط صدای مرد فارسی دارد.", "").strip()
        row.notes = (notes + " " + NOTE).strip()
        row.save(update_fields=["voice_fa_female", "notes"])


def backwards(apps, schema_editor):
    AudioEngine = apps.get_model("ai", "AudioEngine")
    AudioEngine.objects.filter(kind="PIPER", voice_fa_female=MANA).update(voice_fa_female="")


class Migration(migrations.Migration):
    dependencies = [("ai", "0013_seed_audio_engines")]
    operations = [migrations.RunPython(forwards, backwards)]
