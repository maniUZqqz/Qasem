"""منطقِ صفحهٔ «تلفظ»: واژه‌نامهٔ فروشگاه، پیش‌نمایشِ پیش/پس، فهرستِ مشکل‌دار.

لایهٔ اصلی در ``services/audio/fa_pron`` است (پایتونِ خالص). این‌جا فقط پایگاه‌داده و قیدهای فروشگاه (سیاستِ «فقط لوکال»، روشن/خاموش) است.
"""
from __future__ import annotations

import logging
import re
import shutil
import threading
from pathlib import Path

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import Count, Max

from services.audio import fa_pron
from services.audio.fa_pron import dictionary as D
from services.audio.fa_pron import g2p
from services.audio.fa_pron import phones as P
from services.audio.fa_pron.render import respell_token

from .models import EvalRun, LexiconEntry, ProblemWord, PronSettings

logger = logging.getLogger(__name__)

ENGINES = {
    "piper": {"label": "Piper (روی همین سرور، آفلاین)", "local": True,
              "native": "ورودیِ واجی (IPA) — همان الفبایی که صدا با آن آموزش دیده"},
    "edge": {"label": "Edge (مایکروسافت، آنلاین)", "local": False,
             "native": "فقط متن؛ برچسبِ SSML پذیرفته نمی‌شود، پس واژه‌ها با نشانهٔ کوتاه‌صدا بازنویسی می‌شوند"},
    "moss": {"label": "MOSS-TTS (کارتِ گرافیکِ سرورِ پردازش)", "local": True,
             "native": "متنِ بازنویسی‌شده با نشانهٔ کوتاه‌صدا"},
}
#: short enough for a select box at phone width; the long explanation is DEPTH_HELP (shown under the settings and as a tooltip)
DEPTH_LABELS = {"normalize": "فقط نرمال‌سازی", "lexicon": "نرمال‌سازی + واژه‌نامه", "full": "همه‌چیز"}
DEPTH_HELP = {
    "normalize": "فقط متن را آماده می‌کند: عدد، تاریخ، ساعت، قیمت، شماره‌تلفن و واژه‌های لاتین به واژهٔ فارسی، سرواژه‌ها (PDF، GPS) حرف‌به‌حرف، و واژه‌هایی که خودِ فروشگاه در واژه‌نامه‌اش نوشته. بقیهٔ واژه‌ها را خودِ صدا می‌خواند.",
    "lexicon": "علاوه بر آن، واژه‌هایی را که صدا اشتباه می‌خواند با آوای درست می‌دهد: ع و ء، «ه» و «ی» و «و/او» پایانی و میانی، تشدید، اضافه (برنامهٔ تمرینی، ورزش‌های سنگین)، هم‌نویسه‌ها (کشتی، مرد، کرم). این عمق برای شکایتِ تلفظ است.",
    "full": "علاوه بر آن، حتی واژه‌های ناشناخته را با قاعده‌های حرف‌به‌حرف آوانویسی می‌کند (برای موتورهایی که هیچ پیش‌پردازشِ فارسی ندارند).",
}
MAX_WORD = 80

# ------------------------------------------------------------------ runtime (used by every provider)

_CACHE: dict[int | None, tuple[tuple, fa_pron.Dictionary]] = {}
_LOCK = threading.Lock()


def _stamp(store_id) -> tuple:
    mine = LexiconEntry.objects.filter(store_id=store_id, enabled=True).aggregate(n=Count("id"), t=Max("updated_at"))
    glob = LexiconEntry.objects.filter(store__isnull=True, enabled=True).aggregate(n=Count("id"), t=Max("updated_at"))
    return (mine["n"], mine["t"], glob["n"], glob["t"])


def dictionary_for(store) -> fa_pron.Dictionary:
    """Shared lexicon + global additions + this store's entries (store wins)."""
    sid = getattr(store, "pk", None)
    try:
        stamp = _stamp(sid)
    except Exception:  # noqa: BLE001 - no table yet (before migrate)
        return fa_pron.Dictionary()
    with _LOCK:
        hit = _CACHE.get(sid)
        if hit and hit[0] == stamp:
            return hit[1]
    own = {e.word: e.pn for e in LexiconEntry.objects.filter(store_id=sid, enabled=True)} if sid else {}
    glob = {e.word: e.pn for e in LexiconEntry.objects.filter(store__isnull=True, enabled=True)}
    dic = fa_pron.Dictionary(store=own, extra=glob)
    with _LOCK:
        _CACHE[sid] = (stamp, dic)
    return dic


def settings_for(store) -> dict:
    row = PronSettings.objects.filter(store=store).first() if store is not None else None
    return {"enabled": True if row is None else row.enabled, "ezafe": True if row is None else row.ezafe,
            "depth": dict(row.depth) if row and isinstance(row.depth, dict) else {}}


def measured_depths() -> dict[str, str]:
    """engine -> the depth that measured best on the node (only where BOTH depths were measured on the full set).

    The node self-test queues a full run per engine and depth; when both are in, the one with the lower word error rate after
    the layer becomes the platform default for that engine (a store's own choice still wins). A difference under one point
    is noise (Vosk and Whisper both wobble about that much): then the built-in default stays.
    """
    stamp = EvalRun.objects.filter(state=EvalRun.State.DONE, baseline=False, sample="full", store__isnull=True).aggregate(
        n=Count("id"), t=Max("updated_at"))
    stamp = (stamp["n"], stamp["t"])
    with _LOCK:
        if _MEASURED.get("stamp") == stamp:
            return dict(_MEASURED["value"])
    out = _measured_depths_uncached()
    with _LOCK:
        _MEASURED.update(stamp=stamp, value=dict(out))
    return out


_MEASURED: dict = {}


def _measured_depths_uncached() -> dict[str, str]:
    out: dict[str, str] = {}
    for engine in ENGINES:
        best: dict[str, float] = {}
        for r in EvalRun.objects.filter(engine=engine, state=EvalRun.State.DONE, baseline=False, sample="full",
                                        store__isnull=True).order_by("-created_at"):
            after = ((r.summary or {}).get("overall") or {}).get("after")
            if r.depth and r.depth not in best and after is not None:
                best[r.depth] = after
        if len(best) >= 2:
            ranked = sorted(best.items(), key=lambda kv: kv[1])
            base = fa_pron.DEFAULT_DEPTH[engine]
            winner = ranked[0][0]
            if winner != base and base in best and best[base] - best[winner] < 0.01:
                winner = base
            out[engine] = winner
    return out


def effective_default(engine: str) -> str:
    try:
        return measured_depths().get(engine) or fa_pron.DEFAULT_DEPTH[engine]
    except Exception:  # noqa: BLE001 - no table yet
        return fa_pron.DEFAULT_DEPTH[engine]


def runtime_for(store):
    """(enabled, ezafe, depth overrides, Dictionary) - the cheap call made on every narration."""
    s = settings_for(store)
    try:
        auto = measured_depths()
    except Exception:  # noqa: BLE001
        auto = {}
    return s["enabled"], s["ezafe"], {**auto, **s["depth"]}, dictionary_for(store)


class PronError(ValueError):
    pass


def clean_depth(depth) -> dict:
    """The per-engine depth map from the panel. A wrong engine or depth is an error, not something to drop silently
    (dropping it used to reset the owner's whole map)."""
    if not isinstance(depth, dict):
        raise PronError("عمق باید یک نگاشتِ «موتور ← عمق» باشد.")
    bad = [f"{k}={v}" for k, v in depth.items() if k not in ENGINES or v not in fa_pron.DEPTHS]
    if bad:
        raise PronError("موتور یا عمقِ نامعتبر: " + "، ".join(bad[:4]) + " (موتورها: " + " ".join(ENGINES) +
                        "؛ عمق‌ها: " + " ".join(fa_pron.DEPTHS) + ").")
    return {k: v for k, v in depth.items()}


def save_settings(store, *, enabled=None, ezafe=None, depth=None) -> dict:
    new_depth = clean_depth(depth) if depth is not None else None     # validate BEFORE anything is written
    row, _ = PronSettings.objects.get_or_create(store=store)
    if enabled is not None:
        row.enabled = bool(enabled)
    if ezafe is not None:
        row.ezafe = bool(ezafe)
    if new_depth is not None:
        row.depth = new_depth
    row.save()
    return settings_for(store)


# ------------------------------------------------------------------ lexicon

def convert(respelling: str) -> dict:
    """What the owner typed -> PN + how it will be read (shown live in the panel)."""
    text = (respelling or "").strip()
    if not text:
        raise PronError("بازنویسی را بنویسید؛ مثلاً «چِغِر» یا «مَعنی».")
    if len(text) > 160:
        raise PronError("بازنویسی خیلی بلند است.")
    try:
        pn = g2p.respelling_to_pn(text)
    except ValueError as exc:
        raise PronError(str(exc)) from exc
    if not pn or not P.is_valid(pn):
        raise PronError("این بازنویسی را نتوانستم به آوا تبدیل کنم. حرف‌های فارسی (با ـَ ـِ ـُ برای کوتاه‌صداها) یا حروفِ لاتینِ ساده بنویسید.")
    toks = P.parse(pn)
    # «چغر» must come back as «چغر», not «چقر»: the letter the owner wrote for the one sound «q» is kept
    return {"pn": pn, "respelling": P.to_respelling(toks, q_letter=P.q_letter_for(text)), "ipa": P.to_ssml_ipa(toks),
            "syllables": P.syllable_count(toks)}


def _clean_word(word: str) -> str:
    w = D.canon(fa_pron_normalize(word)).strip()
    if not w or len(w) > MAX_WORD:
        raise PronError("واژه خالی یا خیلی بلند است.")
    return w


def fa_pron_normalize(word: str) -> str:
    from services.audio.fa_pron.normalize import unify_letters

    return unify_letters(word or "").strip()


def save_entry(store, word: str, respelling: str, *, note: str = "", user=None, pk: int | None = None) -> LexiconEntry:
    """Create or update (``store=None`` = a global addition, staff only - the view checks)."""
    key = _clean_word(word)
    conv = convert(respelling)
    try:
        with transaction.atomic():
            if pk:
                row = LexiconEntry.objects.get(pk=pk, store=store)
                row.word, row.respelling, row.pn, row.note = key, respelling.strip(), conv["pn"], note[:200]
                row.save()
            else:
                row, created = LexiconEntry.objects.update_or_create(
                    store=store, word=key,
                    defaults={"respelling": respelling.strip(), "pn": conv["pn"], "note": note[:200], "enabled": True,
                              "created_by": user})
                _ = created
    except LexiconEntry.DoesNotExist as exc:
        raise PronError("پیدا نشد.") from exc
    except IntegrityError as exc:
        raise PronError("این واژه از قبل در فهرست هست.") from exc
    # a word in the list is no longer a problem
    ProblemWord.objects.filter(store=store, word=key).exclude(status=ProblemWord.Status.FIXED).update(status=ProblemWord.Status.FIXED)
    return row


def entry_dict(e: LexiconEntry) -> dict:
    toks = P.parse(e.pn) if P.is_valid(e.pn) else []
    return {"id": e.pk, "word": e.word, "respelling": e.respelling, "pn": e.pn, "note": e.note, "enabled": e.enabled,
            "scope": "store" if e.store_id else "global",
            "heard_as": P.to_respelling(toks, q_letter=P.q_letter_for(e.word, e.respelling)) if toks else "",
            "ipa": P.to_ssml_ipa(toks) if toks else "", "updated_at": e.updated_at.isoformat()}


def shared_rows(query: str = "", category: str = "", limit: int = 400, offset: int = 0) -> dict:
    rows = D.all_shared_rows()
    cats: dict[str, int] = {}
    for r in rows:
        cats[r["category"]] = cats.get(r["category"], 0) + 1
    q = D.canon(query).strip()
    if q:
        rows = [r for r in rows if q in D.canon(r["word"]) or q in r["respelling"]]
    if category:
        rows = [r for r in rows if r["category"] == category]
    total = len(rows)
    return {"total": total, "rows": rows[offset:offset + limit],
            "categories": [{"name": k, "count": v} for k, v in cats.items()]}


# ------------------------------------------------------------------ problems

def record_problems(store, words, *, source: str, engine: str = "", context: str = "", detail: str = "") -> int:
    n = 0
    for w in words:
        w = str(w).strip()
        if not w or len(w) > MAX_WORD:
            continue
        key = w.lower() if source == ProblemWord.Source.LATIN else D.canon(w)
        # already has an entry in the store lexicon: not a problem
        if LexiconEntry.objects.filter(store=store, word=key).exists():
            continue
        row, created = ProblemWord.objects.get_or_create(
            store=store, word=key, source=source,
            defaults={"context": context[:300], "engine": engine, "detail": detail[:300]})
        if not created:
            row.count += 1
            if row.status == ProblemWord.Status.FIXED:
                row.status = ProblemWord.Status.OPEN
            row.save(update_fields=["count", "status", "updated_at"])
        n += 1
    return n


def problem_dict(p: ProblemWord) -> dict:
    return {"id": p.pk, "word": p.word, "source": p.source, "source_label": p.get_source_display(), "status": p.status,
            "context": p.context, "engine": p.engine, "detail": p.detail, "count": p.count,
            "updated_at": p.updated_at.isoformat()}


# ------------------------------------------------------------------ preview (before / after)

def preview(store, text: str, engines=None, depth: str | None = None) -> dict:
    """What each engine would be given, with the changes explained word by word.

    ``depth`` (optional) tries one depth for every engine without touching the store's settings."""
    if depth is not None and depth not in fa_pron.DEPTHS:
        raise PronError("عمقِ نامعتبر.")
    text = (text or "").strip()
    if not text:
        raise PronError("متنی بنویسید.")
    if len(text) > 1500:
        raise PronError("متن خیلی بلند است (تا ۱۵۰۰ نویسه).")
    s = settings_for(store)
    dic = dictionary_for(store)
    out = {"text": text, "engines": {}, "settings": s}
    base = fa_pron.prepare(text, depth="lexicon", dictionary=dic, ezafe=s["ezafe"])
    out["normalized"] = base.normalized
    out["words"] = [{"text": t.text, "pn": t.pn or "", "source": t.source, "ezafe": t.ezafe or t.ezafe_inside, "applied": t.apply,
                     "heard_as": respell_token(t) if t.pn else ""}
                    for t in base.tokens if t.kind == "word"]
    out["unknown"] = base.unknown
    out["latin_guesses"] = list(dict.fromkeys(base.notes.latin_guesses))
    for eng in engines or ENGINES:
        if eng not in ENGINES:
            continue
        chosen = depth or s["depth"].get(eng) or effective_default(eng)
        prep = fa_pron.prepare(text, depth=chosen, dictionary=dic, ezafe=s["ezafe"])
        r = None
        if eng == "piper":
            # a word the layer has no opinion on is phonemised by the voice itself at synthesis time: show it as «‹word›»
            # (not as nothing, which made the box look truncated). At depth «normalize» there is phoneme input only when the text
            # has a spelled-out acronym (its letter names are ours); otherwise the voice reads the normalised text itself.
            r = fa_pron.render_prepared(prep, "piper", native_ipa=lambda w: "‹" + w + "›")
        if r is not None and r.ipa:
            out["engines"][eng] = {"depth": chosen, "ipa": r.ipa, "text": prep.normalized,
                                   "engine_words": int(r.notes.get("native_words", 0)),
                                   "letter_words": int(r.notes.get("letter_words", 0))}
        else:
            r = fa_pron.render_prepared(prep, "plain")
            out["engines"][eng] = {"depth": chosen, "text": r.text}
    return out


# ------------------------------------------------------------------ the shipped baseline measurement

BASELINE_FILE = Path(__file__).resolve().parents[3] / "docs" / "pronunciation" / "baseline-results.json"


_SEED_LOCK = threading.Lock()


def seed_baseline() -> int:
    """Put the measurement that shipped with this version into the table.

    The table always mirrors the shipped file: a new version of the file (a fresh measurement) replaces the rows of the old one
    (each row carries the file's fingerprint in ``summary.baseline_sha``); the owner's own runs are never touched."""
    if not BASELINE_FILE.is_file():
        return 0
    import hashlib
    import json

    try:
        raw = BASELINE_FILE.read_bytes()
        data = json.loads(raw.decode("utf-8"))
    except (OSError, ValueError):
        return 0
    sha = hashlib.sha1(raw).hexdigest()[:12]
    with _SEED_LOCK:
        have = {(r.summary or {}).get("baseline_sha") for r in EvalRun.objects.filter(baseline=True)}
        if have == {sha}:
            return 0
        n = 0
        with transaction.atomic():
            EvalRun.objects.filter(baseline=True).delete()
            for run in data.get("runs", []):
                EvalRun.objects.create(
                    store=None, engine=run["engine"], voice=run.get("voice", ""), sample=run.get("sample", "full"),
                    depth=run.get("depth", ""), state=EvalRun.State.DONE, baseline=True, asr=run.get("asr", ""),
                    where=run.get("where", ""), n_sentences=run.get("n", 0), summary={**(run.get("summary") or {}), "baseline_sha": sha},
                    rows=run.get("rows", []), message=run.get("message", ""))
                n += 1
        return n


def run_dict(r: EvalRun, rows: bool = False) -> dict:
    d = {"id": r.pk, "engine": r.engine, "voice": r.voice, "sample": r.sample, "depth": r.depth, "state": r.state,
         "state_label": r.get_state_display(), "message": r.message, "asr": r.asr, "where": r.where,
         "baseline": r.baseline, "n": r.n_sentences, "summary": r.summary, "created_at": r.created_at.isoformat(),
         "finished_at": r.finished_at.isoformat() if r.finished_at else None}
    if rows:
        d["rows"] = r.rows
    return d


def site_piper_voices() -> list[str]:
    """Persian Piper voices that are really installed on THIS server (the figures of the measurement table are labelled with it)."""
    from services.audio import engines

    try:
        folder = engines.piper_model_path("fa_IR-gyro-medium").parent
        return sorted(p.name.removesuffix(".onnx") for p in folder.glob("fa_IR-*.onnx")
                      if p.with_suffix(".onnx.json").exists())
    except Exception:  # noqa: BLE001
        return []


PIPER_SITE_PREFERENCE = ("fa_IR-amir-medium", "fa_IR-gyro-medium", "fa_IR-mana-medium", "fa_IR-ganji-medium")


def site_piper_voice(preferred: str = "") -> str:
    """The Piper voice to use on THIS server. The processing node installs its own pair (amir + gyro), but the site only has what
    ``audio_setup --voices`` downloaded (gyro, mana, ganji ...): the asked voice if it is installed, else the first installed Persian one of the
    preference list, else the engine default (so the error that follows names a voice that can be installed)."""
    from services.audio import engines

    wanted = [str(preferred).removesuffix(".onnx")] if preferred else []
    for name in wanted + list(PIPER_SITE_PREFERENCE):
        path = engines.piper_model_path(name)
        if path.exists() and path.with_suffix(".onnx.json").exists():
            return name
    return wanted[0] if wanted else PIPER_SITE_PREFERENCE[1]


# ------------------------------------------------------------------ what the layer does today (for caches)

def lexicon_stamp(store) -> tuple:
    """Changes whenever the store's lexicon (or the global additions) is edited."""
    return _stamp(getattr(store, "pk", None))


def fingerprint(store, engine: str) -> str:
    """A short key for «what the layer would do to a text for this store and this engine, right now»: the layer's own version,
    its on/off switch, the ezafe switch, the depth for the engine and the lexicon stamp. A cache of finished audio (the studio
    re-uses an identical earlier take) must include it, otherwise «fix the word, listen again» plays the OLD recording."""
    import hashlib

    from services.audio import pronounce

    key = pronounce.ENGINE_OF.get(engine, engine)
    try:
        enabled, ezafe, depth, _dic = runtime_for(store)
        raw = "|".join(map(str, (fa_pron.VERSION, int(enabled), int(ezafe), depth.get(key) or fa_pron.DEFAULT_DEPTH.get(key, ""),
                                 lexicon_stamp(store))))
    except Exception:  # noqa: BLE001 - no table yet: only the version matters
        raw = fa_pron.VERSION
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]


# ------------------------------------------------------------------ generated files: retention

AUDIO_MAX_AGE_H = 24          # test-box recordings: a day is plenty to listen again
AUDIO_KEEP_PER_STORE = 30     # and never more than this many per store
_AUDIO_NAME = re.compile(r"^[0-9a-f]{12}\.(wav|mp3)$")


def media_dir() -> Path:
    return Path(settings.MEDIA_ROOT) / "pronunciation"


def cleanup_store_audio(store_id, *, max_age_h: float = AUDIO_MAX_AGE_H, keep: int = AUDIO_KEEP_PER_STORE, now: float | None = None) -> int:
    """Delete this store's old test-box recordings (every click makes a 0.3-1 MB file). Returns how many were removed."""
    import time

    folder = media_dir() / str(store_id)
    if not folder.is_dir():
        return 0
    now = now if now is not None else time.time()
    files = sorted((f for f in folder.iterdir() if f.is_file() and _AUDIO_NAME.match(f.name)),
                   key=lambda f: f.stat().st_mtime, reverse=True)
    removed = 0
    for idx, f in enumerate(files):
        if idx >= keep or now - f.stat().st_mtime > max_age_h * 3600:
            try:
                f.unlink()
                removed += 1
            except OSError:
                pass
    return removed


def remove_run_files(run_id) -> None:
    """The WAV/MP3 files of one eval run (Edge runs keep them while the node listens)."""
    shutil.rmtree(media_dir() / "runs" / str(run_id), ignore_errors=True)


def cleanup_media(*, now: float | None = None) -> dict:
    """Housekeeping for everything under media/pronunciation: old test recordings, and run folders whose run is gone,
    finished or failed (a failed Edge run used to leave its files forever)."""
    import time

    now = now if now is not None else time.time()
    out = {"audio": 0, "runs": 0}
    root = media_dir()
    if not root.is_dir():
        return out
    for d in root.iterdir():
        if d.is_dir() and d.name.isdigit():
            out["audio"] += cleanup_store_audio(int(d.name), now=now)
    runs = root / "runs"
    if runs.is_dir():
        for d in runs.iterdir():
            if not d.is_dir() or not d.name.isdigit():
                continue
            run = EvalRun.objects.filter(pk=int(d.name)).first()
            old = now - d.stat().st_mtime > 3600
            if run is None or (old and run.state in (EvalRun.State.DONE, EvalRun.State.FAILED)) or \
                    (old and now - run.updated_at.timestamp() > 3 * 86400):
                shutil.rmtree(d, ignore_errors=True)
                out["runs"] += 1
    return out
