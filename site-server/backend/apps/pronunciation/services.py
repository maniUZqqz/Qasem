"""منطقِ صفحهٔ «تلفظ»: واژه‌نامهٔ فروشگاه، پیش‌نمایشِ پیش/پس، فهرستِ مشکل‌دار.

لایهٔ اصلی در ``services/audio/fa_pron`` است (پایتونِ خالص). این‌جا فقط پایگاه‌داده و قیدهای فروشگاه (سیاستِ «فقط لوکال»، روشن/خاموش) است.
"""
from __future__ import annotations

import logging
import threading
from pathlib import Path

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
DEPTH_LABELS = {"normalize": "فقط نرمال‌سازیِ متن", "lexicon": "نرمال‌سازی + واژه‌های شناخته‌شده", "full": "همه‌چیز (حتی واژه‌های ناشناخته)"}
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


def save_settings(store, *, enabled=None, ezafe=None, depth=None) -> dict:
    row, _ = PronSettings.objects.get_or_create(store=store)
    if enabled is not None:
        row.enabled = bool(enabled)
    if ezafe is not None:
        row.ezafe = bool(ezafe)
    if isinstance(depth, dict):
        clean = {k: v for k, v in depth.items() if k in ENGINES and v in fa_pron.DEPTHS}
        row.depth = clean
    row.save()
    return settings_for(store)


# ------------------------------------------------------------------ lexicon

class PronError(ValueError):
    pass


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
    return {"pn": pn, "respelling": P.to_respelling(toks), "ipa": P.to_ssml_ipa(toks), "syllables": P.syllable_count(toks)}


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
            "scope": "store" if e.store_id else "global", "heard_as": P.to_respelling(toks) if toks else "",
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

def preview(store, text: str, engines=None) -> dict:
    """What each engine would be given, with the changes explained word by word."""
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
    out["words"] = [{"text": t.text, "pn": t.pn or "", "source": t.source, "ezafe": t.ezafe, "applied": t.apply,
                     "heard_as": respell_token(t) if t.pn else ""}
                    for t in base.tokens if t.kind == "word"]
    out["unknown"] = base.unknown
    out["latin_guesses"] = list(dict.fromkeys(base.notes.latin_guesses))
    for eng in engines or ENGINES:
        if eng not in ENGINES:
            continue
        depth = s["depth"].get(eng) or effective_default(eng)
        prep = fa_pron.prepare(text, depth=depth, dictionary=dic, ezafe=s["ezafe"])
        if eng == "piper" and depth != "normalize":
            r = fa_pron.render_prepared(prep, "piper")
            out["engines"][eng] = {"depth": depth, "ipa": r.ipa, "text": prep.normalized}
        else:
            r = fa_pron.render_prepared(prep, "plain")
            out["engines"][eng] = {"depth": depth, "text": r.text}
    return out


# ------------------------------------------------------------------ the shipped baseline measurement

BASELINE_FILE = Path(__file__).resolve().parents[3] / "docs" / "pronunciation" / "baseline-results.json"


def seed_baseline() -> int:
    """Put the measurement that shipped with this version into the table (once)."""
    if EvalRun.objects.filter(baseline=True).exists() or not BASELINE_FILE.is_file():
        return 0
    import json

    try:
        data = json.loads(BASELINE_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return 0
    n = 0
    for run in data.get("runs", []):
        EvalRun.objects.create(
            store=None, engine=run["engine"], voice=run.get("voice", ""), sample=run.get("sample", "full"),
            depth=run.get("depth", ""), state=EvalRun.State.DONE, baseline=True, asr=run.get("asr", ""),
            where=run.get("where", ""), n_sentences=run.get("n", 0), summary=run.get("summary", {}),
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
