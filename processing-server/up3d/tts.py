"""متن ⇐ گفتار. فراهم‌کننده‌ها قابلِ تعویض‌اند و خروجیِ همه یک فایلِ WAV است.

  openai   هر سرویسِ سازگار با OpenAI (Metis، OpenAI، …) با کتابخانهٔ رسمیِ openai
  piper    موتورِ آفلاینِ Piper (اگر نصب باشد)
  silent   سکوت به اندازهٔ تخمینی (آزمون، یا وقتی کلید نیست)

تنظیم (base_url، کلید، مدل) از پنل (جنگو ادمین) یا متغیرهای محیطی می‌آید، نه از کد.
"""
import hashlib
import json
import os
import shutil
import subprocess

from . import paths
from . import scene as S


class TTSError(Exception):
    pass


def _ffmpeg():
    return paths.ffmpeg_binary() or 'ffmpeg'


def _to_wav(src, dst, rate=48000):
    subprocess.run([_ffmpeg(), '-v', 'error', '-y', '-i', src, '-ac', '1', '-ar', str(rate), dst], check=True)


def settings_from_env():
    return {
        'base_url': os.environ.get('UP3D_TTS_BASE_URL') or os.environ.get('OPENAI_BASE_URL') or '',
        'api_key': os.environ.get('UP3D_TTS_API_KEY') or os.environ.get('OPENAI_API_KEY') or '',
        'model': os.environ.get('UP3D_TTS_MODEL', 'tts-1'),
    }


def synthesize(text, voice_asset, settings=None, out_dir=None, style=None):
    """خروجی: {'file': wav, 'duration': s, 'provider': ..., 'cached': bool}"""
    settings = settings or settings_from_env()
    voice = dict(voice_asset or {})
    provider = voice.get('provider', 'silent')
    if provider == 'openai' and not settings.get('api_key'):
        provider = 'silent'
    key = hashlib.sha256(json.dumps([provider, voice.get('voice'), voice.get('model') or settings.get('model'),
                                     settings.get('base_url'), text, style, voice.get('speed', 1.0)],
                                    ensure_ascii=False).encode('utf-8')).hexdigest()[:24]
    cache = paths.cache_dir('tts')
    wav = os.path.join(cache, key + '.wav')
    cached = os.path.isfile(wav) and os.path.getsize(wav) > 1000
    if not cached:
        if provider == 'openai':
            _openai(text, voice, settings, wav, style)
        elif provider == 'piper':
            _piper(text, voice, wav)
        else:
            _silent(text, wav)
    from .lipsync import wav_duration
    dur = wav_duration(wav, _ffmpeg()) or S.estimate_speech_seconds(text)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
        dst = os.path.join(out_dir, key + '.wav')
        shutil.copyfile(wav, dst)
        wav = dst
    return {'file': wav, 'duration': round(dur, 3), 'provider': provider, 'cached': cached}


def _openai(text, voice, settings, wav, style):
    try:
        from openai import OpenAI
    except ImportError as e:
        raise TTSError('کتابخانهٔ openai نصب نیست') from e
    client = OpenAI(api_key=settings['api_key'], base_url=settings.get('base_url') or None, timeout=90, max_retries=1)
    model = voice.get('model') or settings.get('model') or 'tts-1'
    kwargs = {'model': model, 'voice': voice.get('voice', 'nova'), 'input': text}
    if voice.get('speed'):
        kwargs['speed'] = float(voice['speed'])
    if 'gpt-4o' in model and (style or voice.get('instructions')):
        kwargs['instructions'] = (voice.get('instructions') or '') + (' Tone: %s.' % style if style else '')
    try:
        resp = client.audio.speech.create(**kwargs)
    except TypeError:
        kwargs.pop('instructions', None)
        resp = client.audio.speech.create(**kwargs)
    except Exception as e:
        raise TTSError('سرویسِ صدا خطا داد: %s' % str(e)[:300]) from e
    tmp = wav + '.mp3'
    with open(tmp, 'wb') as fh:
        fh.write(resp.read())
    _to_wav(tmp, wav)
    os.remove(tmp)


def _piper(text, voice, wav):
    exe = voice.get('binary') or shutil.which('piper')
    model = voice.get('model_path')
    if not exe or not model or not os.path.isfile(model):
        raise TTSError('Piper یا مدلِ صدایش نصب نیست')
    tmp = wav + '.raw.wav'
    subprocess.run([exe, '--model', model, '--output_file', tmp], input=text.encode('utf-8'), check=True,
                   capture_output=True)
    _to_wav(tmp, wav)
    os.remove(tmp)


def _silent(text, wav):
    secs = S.estimate_speech_seconds(text)
    subprocess.run([_ffmpeg(), '-v', 'error', '-y', '-f', 'lavfi', '-i', 'anullsrc=r=48000:cl=mono', '-t',
                    '%.2f' % secs, wav], check=True)
