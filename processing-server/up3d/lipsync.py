"""هماهنگیِ لب برای فارسی.

متن ⇐ دنبالهٔ «ویسم» (۱۵ شکلِ استانداردِ دهانِ Meta/ARKit: sil PP FF TH DD kk CH SS nn RR aa E I O U)
⇐ چیدن روی بخش‌های «صدادارِ» فایلِ صوتی (از روی انرژیِ صدا) ⇐ وزن با بلندیِ صدا.

مصوت‌های کوتاهِ فارسی معمولاً نوشته نمی‌شوند؛ بینِ دو صامتِ پشتِ‌سرِهم یک مصوتِ کوتاه گذاشته می‌شود.
فراهم‌کنندهٔ دقیق‌تر (هم‌ترازیِ واجی، مثلاً Rhubarb یا مدلِ گفتار) می‌تواند جایگزینِ align_to_audio شود
و همین خروجی را بدهد: [(ثانیه، ویسم، وزن), ...]
"""
import math
import os
import re
import struct
import subprocess

VISEMES = ('sil', 'PP', 'FF', 'TH', 'DD', 'kk', 'CH', 'SS', 'nn', 'RR', 'aa', 'E', 'I', 'O', 'U')
VOWELS = {'aa', 'E', 'I', 'O', 'U'}

FA = {
    'ب': 'PP', 'پ': 'PP', 'م': 'PP',
    'ف': 'FF',
    'ت': 'DD', 'ط': 'DD', 'د': 'DD',
    'ث': 'SS', 'س': 'SS', 'ص': 'SS', 'ز': 'SS', 'ذ': 'SS', 'ض': 'SS', 'ظ': 'SS',
    'ش': 'CH', 'ج': 'CH', 'چ': 'CH', 'ژ': 'CH',
    'ک': 'kk', 'ك': 'kk', 'گ': 'kk', 'ق': 'kk', 'غ': 'kk', 'خ': 'kk', 'ح': 'kk', 'ع': 'kk', 'ء': 'kk',
    'ئ': 'I', 'أ': 'aa', 'إ': 'E', 'ؤ': 'O',
    'ن': 'nn', 'ل': 'nn',
    'ر': 'RR',
}
LATIN = {
    'a': 'aa', 'e': 'E', 'i': 'I', 'o': 'O', 'u': 'U', 'y': 'I',
    'b': 'PP', 'p': 'PP', 'm': 'PP', 'f': 'FF', 'v': 'FF', 'w': 'U',
    't': 'DD', 'd': 'DD', 'n': 'nn', 'l': 'nn', 's': 'SS', 'z': 'SS', 'c': 'kk', 'k': 'kk', 'q': 'kk',
    'g': 'kk', 'h': 'kk', 'x': 'kk', 'j': 'CH', 'r': 'RR',
}
DIACRITIC = {'َ': 'aa', 'ِ': 'E', 'ُ': 'O'}
SHORT_CYCLE = ('aa', 'E', 'aa', 'O', 'E')
DUR = {'aa': 1.35, 'I': 1.25, 'U': 1.25, 'O': 1.0, 'E': 0.9, 'PP': 0.8, 'FF': 0.8, 'SS': 0.9, 'CH': 0.9,
       'kk': 0.7, 'DD': 0.65, 'nn': 0.7, 'RR': 0.6, 'TH': 0.7, 'sil': 0.0}
WEIGHT = {'aa': 1.0, 'O': 0.9, 'U': 0.85, 'E': 0.8, 'I': 0.8, 'PP': 0.95, 'FF': 0.8, 'SS': 0.6, 'CH': 0.75,
          'kk': 0.45, 'DD': 0.5, 'nn': 0.45, 'RR': 0.5, 'TH': 0.6, 'sil': 0.0}
PAUSE = re.compile(r'[.!?؟،,;:\n…]')


def _word_tokens(word, salt):
    """یک واژه ⇐ ویسم‌ها، با مصوتِ کوتاهِ ضمنی."""
    out = []
    chars = list(word)
    n = len(chars)
    for i, ch in enumerate(chars):
        if ch in DIACRITIC:
            if out and out[-1] in VOWELS:
                out[-1] = DIACRITIC[ch]
            else:
                out.append(DIACRITIC[ch])
            continue
        if ch in ('ّ', 'ْ', '‌', 'ـ'):   # تشدید، سکون، نیم‌فاصله، کشیده
            if ch == 'ّ' and out:
                out.append(out[-1])
            continue
        if ch in 'اآ':
            out.append('aa')
            continue
        if ch == 'و':
            if n == 1:
                out.append('O')
            elif i == 0 or (i + 1 < n and chars[i + 1] in 'اآیو'):
                out.append('FF')        # «و» صامت (v)
            else:
                out.append('U')
            continue
        if ch in 'یي':
            out.append('I')
            continue
        if ch in 'هة':
            out.append('E' if i == n - 1 and n > 1 else 'kk')
            continue
        if ch.isdigit() or ch in '۰۱۲۳۴۵۶۷۸۹':
            out += ['E', 'kk', 'aa']
            continue
        lo = ch.lower()
        if lo in LATIN:
            out.append(LATIN[lo])
            continue
        v = FA.get(ch)
        if v:
            out.append(v)
    # مصوتِ کوتاهِ ضمنی: بعد از صامتی که صامتِ دیگری پس از آن است (و آغازِ واژه)
    res = []
    k = salt
    for i, v in enumerate(out):
        res.append(v)
        nxt = out[i + 1] if i + 1 < len(out) else None
        if v not in VOWELS and nxt is not None and nxt not in VOWELS and (i == 0 or out[i - 1] in VOWELS or i % 2 == 0):
            res.append(SHORT_CYCLE[k % len(SHORT_CYCLE)])
            k += 1
    return res


def tokenize(text):
    """متن ⇐ [(viseme, duration_weight)] با 'pause' برای نشانه‌های مکث."""
    tokens = []
    salt = 0
    for part in re.split(r'(\s+|[.!?؟،,;:\n…])', text or ''):
        if not part or part.isspace():
            continue
        if PAUSE.fullmatch(part):
            tokens.append(('pause', 2.2))
            continue
        for v in _word_tokens(part, salt):
            tokens.append((v, DUR.get(v, 0.8)))
        tokens.append(('gap', 0.25))
        salt += 1
    while tokens and tokens[-1][0] in ('gap', 'pause'):
        tokens.pop()
    return tokens


def visemes_from_text(text, seconds, lead=0.05):
    """بی‌صدا (انیمیک): ویسم‌ها روی مدتِ تخمینی پخش می‌شوند."""
    toks = tokenize(text)
    total = sum(w for _, w in toks) or 1.0
    usable = max(0.2, seconds - lead * 2)
    t = lead
    keys = []
    for v, w in toks:
        d = usable * w / total
        if v not in ('pause', 'gap'):
            keys.append((round(t + d / 2, 3), v, WEIGHT.get(v, 0.6)))
        t += d
    return _with_rests(keys)


def _with_rests(keys):
    """دهان در مکث‌های بلند بسته شود (sil)."""
    out = []
    for i, k in enumerate(keys):
        if out and k[0] - out[-1][0] > 0.35:
            out.append((round(out[-1][0] + 0.12, 3), 'sil', 0.0))
            out.append((round(k[0] - 0.12, 3), 'sil', 0.0))
        out.append(k)
    return out


# ───────────────────────── صدا

def decode_pcm(path, rate=16000, ffmpeg='ffmpeg'):
    raw = subprocess.run([ffmpeg, '-v', 'error', '-i', path, '-ac', '1', '-ar', str(rate), '-f', 's16le', '-'],
                         capture_output=True, check=True).stdout
    n = len(raw) // 2
    return struct.unpack('<%dh' % n, raw[:n * 2]), rate


def energy_envelope(samples, rate, hop=0.01):
    """RMS در پنجره‌های ۱۰ms، بهنجار به ۰..۱ (صدک ۹۵)."""
    step = max(1, int(rate * hop))
    env = []
    for i in range(0, len(samples) - step + 1, step):
        chunk = samples[i:i + step]
        env.append(math.sqrt(sum(s * s for s in chunk) / len(chunk)) / 32768.0)
    if not env:
        return [], 1.0 / hop
    srt = sorted(env)
    p95 = srt[int(len(srt) * 0.95)] or 1e-6
    # هموارسازیِ سبک
    sm = [(env[max(0, i - 1)] + 2 * env[i] + env[min(len(env) - 1, i + 1)]) / 4.0 for i in range(len(env))]
    return [min(1.0, x / p95) for x in sm], 1.0 / hop


def voiced_segments(env, rate, thresh=0.12, min_gap=0.12, min_len=0.06):
    segs = []
    start = None
    for i, x in enumerate(env):
        if x >= thresh and start is None:
            start = i
        elif x < thresh and start is not None:
            segs.append([start / rate, i / rate])
            start = None
    if start is not None:
        segs.append([start / rate, len(env) / rate])
    merged = []
    for s in segs:
        if merged and s[0] - merged[-1][1] < min_gap:
            merged[-1][1] = s[1]
        else:
            merged.append(s)
    return [s for s in merged if s[1] - s[0] >= min_len]


def align_to_audio(text, audio_path, ffmpeg='ffmpeg'):
    """ویسم‌ها روی بخش‌های صدادارِ فایل. خروجی: dict(visemes, energy, energy_rate, duration, segments)."""
    samples, rate = decode_pcm(audio_path, ffmpeg=ffmpeg)
    duration = len(samples) / float(rate)
    env, erate = energy_envelope(samples, rate)
    segs = voiced_segments(env, erate) or [[0.0, duration]]
    toks = [(v, w) for v, w in tokenize(text) if v != 'pause']
    total_w = sum(w for _, w in toks) or 1.0
    total_v = sum(b - a for a, b in segs)

    def voiced_to_real(x):
        acc = 0.0
        for a, b in segs:
            if x <= acc + (b - a):
                return a + (x - acc)
            acc += b - a
        return segs[-1][1]

    keys = []
    pos = 0.0
    for v, w in toks:
        d = total_v * w / total_w
        if v != 'gap':
            t = voiced_to_real(pos + d / 2)
            e = env[min(len(env) - 1, int(t * erate))] if env else 1.0
            wt = WEIGHT.get(v, 0.6) * (max(0.4, min(1.0, 0.35 + e)) if v in VOWELS else 1.0)
            keys.append((round(t, 3), v, round(wt, 3)))
        pos += d
    return {'visemes': _with_rests(keys), 'energy': [round(x, 3) for x in env], 'energy_rate': erate,
            'duration': round(duration, 3), 'segments': segs}


def wav_duration(path, ffmpeg='ffprobe'):
    from . import paths
    probe = paths.ffprobe_binary()
    try:
        out = subprocess.run([probe, '-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', path],
                             capture_output=True, text=True, check=True).stdout
        return float(out.strip())
    except Exception:
        return None
