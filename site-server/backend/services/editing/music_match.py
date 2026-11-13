"""Choosing the background music by what the video IS — mood, tempo, energy — instead of "the newest track in the library".

The same words an editor uses: a calm talking video wants a quiet instrumental that stays out of the way; a fast sale reel wants an
up-tempo energetic track whose beats the cuts can land on; a luxury product film wants slow and dramatic.  The target comes from facts the
director already has (the brief's pace and look, how much of the footage is speech, how long the shots are), each library track is described
by what we can measure cheaply (tempo from its beats, loudness, onset density) and read from its title/description (mood words, in Persian
and English), and `rank` scores the match with a stated reason in Persian.

Pure functions; the caller supplies candidates (`describe_track`) and gets them back ordered.  Nothing is downloaded or invented: if the
library has no track that fits at all, `rank` says so and the plan keeps going without music.
"""
from __future__ import annotations

import math

#: mood → (words that signal it in a title / description, bpm band, energy 0..1)
MOODS: dict[str, dict] = {
    "calm": {"title": "آرام و ملایم", "words": ("آرام", "ملایم", "آرامش", "calm", "soft", "ambient", "relax", "peaceful", "lofi", "lo-fi", "piano", "acoustic", "گیتار", "پیانو"),
             "bpm": (60, 95), "energy": 0.28},
    "warm": {"title": "گرم و صمیمی", "words": ("گرم", "صمیمی", "warm", "cozy", "friendly", "gentle", "کافه", "cafe", "jazz", "جاز"),
             "bpm": (80, 110), "energy": 0.42},
    "happy": {"title": "شاد و پرانرژی", "words": ("شاد", "happy", "fun", "upbeat", "joy", "cheerful", "summer", "ukulele", "pop"),
             "bpm": (100, 130), "energy": 0.62},
    "energetic": {"title": "پرانرژی و تند", "words": ("پرانرژی", "تند", "انرژی", "energetic", "energy", "dance", "fast", "workout", "sport", "gym", "edm", "electro", "beat", "trap", "hip"),
                  "bpm": (115, 150), "energy": 0.85},
    "inspiring": {"title": "الهام‌بخش", "words": ("الهام", "انگیزه", "inspiring", "motivational", "uplifting", "hope", "corporate", "epic"),
                  "bpm": (90, 125), "energy": 0.6},
    "dramatic": {"title": "سینمایی و دراماتیک", "words": ("سینمایی", "دراماتیک", "cinematic", "dramatic", "trailer", "dark", "tension", "orchestral", "luxury", "لوکس"),
                 "bpm": (60, 100), "energy": 0.55},
}
DEFAULT_MOOD = "warm"
SPEECH_ENERGY_CAP = 0.45     # music under a talking person stays below this energy: it must not compete with the voice


def mood_scores(text: str) -> dict[str, float]:
    """How strongly a title/description signals each mood (0..1): the share of that mood's words found."""
    low = (text or "").lower()
    out: dict[str, float] = {}
    for key, m in MOODS.items():
        hits = sum(1 for w in m["words"] if w.lower() in low)
        if hits:
            out[key] = min(1.0, 0.5 + 0.25 * hits)
    return out


def target_for(*, pace: str = "normal", look: str = "", speech_share: float = 0.0, avg_shot: float | None = None, recipe: str = "",
               mood: str = "") -> dict:
    """What the music should be like for this video.  `speech_share` = the fraction of the footage where somebody talks (0..1)."""
    chosen = mood if mood in MOODS else ""
    why = []
    if not chosen:
        if recipe in ("sale",) or pace == "fast":
            chosen = "energetic"
            why.append("ریتمِ تند")
        elif look in ("cinematic", "bw") or pace == "slow":
            chosen = "dramatic" if look == "cinematic" else "calm"
            why.append("حال‌وهوای آرام/سینمایی")
        elif look in ("golden_hour",):
            chosen = "warm"
            why.append("رنگ‌های گرم")
        elif speech_share >= 0.5:
            chosen = "calm"
            why.append("ویدیو بیشترش گفتار است")
        else:
            chosen = DEFAULT_MOOD
    m = MOODS[chosen]
    lo, hi = m["bpm"]
    energy = m["energy"]
    if speech_share >= 0.4:
        energy = min(energy, SPEECH_ENERGY_CAP)                # a voice carries the video: the bed stays down
        why.append("زیرِ صدای گوینده می‌نشیند")
    if avg_shot and avg_shot < 1.8:                            # very short shots want a driving tempo to cut on
        lo, hi = max(lo, 105), max(hi, 135)
        energy = max(energy, 0.6) if speech_share < 0.4 else energy
        why.append("برش‌های کوتاه ریتمِ سریع‌تر می‌خواهد")
    return {"mood": chosen, "title": m["title"], "bpm": (lo, hi), "energy": round(energy, 2), "instrumental": speech_share >= 0.25, "why": why}


def describe_track(ref: str, title: str = "", text: str = "", *, bpm: float | None = None, energy: float | None = None, duration: float = 0.0,
                   license: str = "") -> dict:
    """A candidate: what we know about one library track."""
    moods = mood_scores(f"{title} {text}")
    if energy is None and moods:
        energy = max(MOODS[k]["energy"] * v for k, v in moods.items())
    return {"ref": ref, "title": title, "text": text, "bpm": bpm, "energy": energy, "duration": float(duration or 0.0), "moods": moods, "license": license}


def _band_fit(bpm: float | None, lo: float, hi: float) -> float:
    """1 inside the band, falling to 0 at ±40 % outside it; half-time / double-time of an in-band tempo counts as 0.7 (a 70 bpm track
    felt in 140)."""
    if not bpm:
        return 0.5
    best = 0.0
    for factor, weight in ((1.0, 1.0), (2.0, 0.7), (0.5, 0.7)):
        b = bpm * factor
        if lo <= b <= hi:
            best = max(best, weight)
        else:
            gap = (lo - b) / lo if b < lo else (b - hi) / hi
            best = max(best, weight * max(0.0, 1.0 - gap / 0.4))
    return best


def score(track: dict, target: dict, *, need_seconds: float = 0.0) -> tuple[float, list[str]]:
    """0..1 and the reasons (Persian) why this track suits the target."""
    why: list[str] = []
    mood = target["mood"]
    s_mood = track["moods"].get(mood, 0.0)
    if s_mood:
        why.append(f"حال‌وهوای «{MOODS[mood]['title']}»")
    elif track["moods"]:
        s_mood = 0.15
    else:
        s_mood = 0.35                                   # unlabelled: neither for nor against
    s_bpm = _band_fit(track.get("bpm"), *target["bpm"])
    if track.get("bpm") and s_bpm >= 0.7:
        why.append(f"ضرب‌آهنگ {round(track['bpm'])}")
    en = track.get("energy")
    s_en = 0.5 if en is None else max(0.0, 1.0 - abs(en - target["energy"]) / 0.6)
    if en is not None and s_en >= 0.7:
        why.append("انرژیِ هم‌خوان")
    s_len = 1.0
    if need_seconds and track.get("duration"):
        s_len = 1.0 if track["duration"] >= need_seconds * 0.9 else 0.6 + 0.4 * (track["duration"] / max(1.0, need_seconds))
        if track["duration"] >= need_seconds * 0.9:
            why.append("به‌اندازهٔ ویدیو طول دارد")
        else:
            why.append("کوتاه‌تر از ویدیو است و تکرار می‌شود")
    total = 0.40 * s_mood + 0.25 * s_bpm + 0.25 * s_en + 0.10 * s_len
    return round(total, 3), why


def rank(candidates: list[dict], target: dict, *, need_seconds: float = 0.0, min_score: float = 0.38) -> list[dict]:
    """Candidates best-first, each with `score` and `why`.  Tracks scoring under `min_score` are dropped: a bad fit is worse than silence."""
    out = []
    for c in candidates:
        sc, why = score(c, target, need_seconds=need_seconds)
        if sc >= min_score:
            out.append({**c, "score": sc, "why": why})
    out.sort(key=lambda r: (-r["score"], r["title"]))
    return out


def loop_plan(track_seconds: float, need_seconds: float, bpm: float | None) -> dict:
    """How to fill `need_seconds` from a track of `track_seconds`: the number of whole repeats and a loop length that is a whole number of
    bars when the tempo is known (so the repeat is not heard as a jump)."""
    if track_seconds <= 0:
        return {"loops": 0, "piece": 0.0}
    piece = track_seconds
    if bpm and bpm > 0:
        bar = 4 * 60.0 / bpm
        bars = max(1, int(track_seconds // bar))
        piece = round(bars * bar, 3)
    loops = max(1, int(math.ceil(need_seconds / max(0.5, piece))))
    return {"loops": min(loops, 12), "piece": piece}
