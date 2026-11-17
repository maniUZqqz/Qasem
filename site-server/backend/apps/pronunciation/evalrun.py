"""«صدا ← تشخیصِ گفتار ← نرخِ خطای واژه»: سنجشِ این‌که لایهٔ تلفظ صدا را واقعاً روشن‌تر کرده.

هر جمله دو بار گفته می‌شود: «پیش» (متنِ خام، همان‌طور که تا امروز به موتور می‌رفت) و «پس» (خروجیِ لایهٔ تلفظ). یک تشخیصِ گفتار (Whisper روی
کارتِ سرورِ پردازش) هر دو را گوش می‌دهد و سایت نرخِ خطای واژه را با ``fa_pron.quality`` حساب می‌کند.

* **Piper و MOSS**: کارِ ماندگارِ ``voice.pron_eval`` روی سرورِ پردازش (دسته‌های ۱۶ جمله‌ای). گره خاموش باشد کار در صف می‌ماند و با روشن شدنش
  خودکار انجام می‌شود (نصبِ Piper و مدلِ Whisper را خودِ گره می‌کند، ``processing/requirements.d/pron.json``).
* **Edge**: صدا روی سایت ساخته می‌شود (ابری؛ متنِ آزمون عمومی است) و فایل‌ها برای گوش‌دادن به کارِ ``voice.pron_asr`` می‌روند.

همه‌چیز در پایگاه‌داده است؛ ``advance()`` هر ۵ دقیقه (beat) و هر بار که پنل نتیجه را می‌خواهد یک گام جلو می‌رود، پس با ری‌استارت چیزی گم نمی‌شود.
"""
from __future__ import annotations

import logging
import shutil
import threading
from pathlib import Path

from django.conf import settings
from django.utils import timezone

from apps.compute import services as compute
from apps.compute.models import ComputeJob
from services.audio import fa_pron
from services.audio.fa_pron import eval_set, quality

from . import services as svc
from .models import EvalRun, ProblemWord

logger = logging.getLogger(__name__)

CHUNK = 16                     # جمله در هر کارِ گره (۳۲ فایل صوتی)
DEFAULT_VOICE = {"piper": "fa_IR-amir-medium", "edge": "fa-IR-DilaraNeural", "moss": ""}
SAMPLES = {"quick": 2, "full": 0}      # quick = ۲ جمله از هر دسته (۳۲ جمله)
STALE_THREAD_S = 20 * 60
_THREADS: dict[int, threading.Thread] = {}


class EvalError(RuntimeError):
    pass


def sentences(sample: str) -> list[tuple[int, str, str]]:
    """[(stable id, tag, text)]. The id is the sentence's position in the fixed set."""
    rows = [(i, tag, text) for i, (tag, text) in enumerate(eval_set.SENTENCES)]
    per = SAMPLES.get(sample, 0)
    if not per:
        return rows
    seen: dict[str, int] = {}
    out = []
    for r in rows:
        if seen.get(r[1], 0) < per:
            seen[r[1]] = seen.get(r[1], 0) + 1
            out.append(r)
    return out


def _after_for(engine: str, text: str, dictionary, ezafe: bool, depth: str):
    """What the layer hands this engine for ``text`` (pure; used by the run and by the node self-test)."""
    prep = fa_pron.prepare(text, depth=depth, dictionary=dictionary, ezafe=ezafe)
    if depth == "normalize":
        if engine == "piper":
            # only the text changes (the voice reads it as it always did) - except a spelled-out acronym, whose letter names go in as phonemes
            rend = fa_pron.render_prepared(prep, "piper", native_ipa=lambda w: "{{%s}}" % w)
            if rend.ipa_sentences:
                return {"ipa": rend.ipa_sentences}, rend.ipa
        return {"text": prep.normalized}, prep.normalized
    if engine == "piper":
        rend = fa_pron.render_prepared(prep, "piper", native_ipa=lambda w: "{{%s}}" % w if depth != "full" else "")
        return {"ipa": rend.ipa_sentences}, rend.ipa
    rend = fa_pron.render_prepared(prep, "plain")
    return {"text": rend.text}, rend.text


def build_items(engine: str, rows: list[tuple[int, str, str]], store=None, depth: str = "") -> tuple[list[dict], dict]:
    s = svc.settings_for(store)
    dic = svc.dictionary_for(store)
    depth = depth or s["depth"].get(engine) or svc.effective_default(engine)
    items, shown = [], {}
    for iid, _tag, text in rows:
        items.append({"id": iid, "variant": "before", "text": text})
        payload, display = _after_for(engine, text, dic, s["ezafe"], depth)
        items.append({"id": iid, "variant": "after", **payload})
        shown[iid] = display
    return items, shown


def start(user, store, engine: str, *, voice: str = "", sample: str = "quick", depth: str = "") -> EvalRun:
    if engine not in svc.ENGINES:
        raise EvalError("موتورِ نامعتبر.")
    if sample not in SAMPLES:
        raise EvalError("نمونهٔ نامعتبر (quick یا full).")
    if depth and depth not in fa_pron.DEPTHS:
        raise EvalError("عمقِ نامعتبر.")
    if engine == "edge":
        # Edge sends text to Microsoft: a store whose data policy is «فقط لوکال» never starts such a run (even though only
        # the fixed public test sentences would leave); the panel says the same, so the two must agree
        from services.audio import engines as engine_registry

        if engine_registry.local_only(store) or engine_registry.local_only(None):
            raise EvalError("سیاستِ دادهٔ این فروشگاه «فقط لوکال» است؛ سنجشِ Edge متن را به مایکروسافت می‌فرستد و انجام نمی‌شود.")
    s = svc.settings_for(store)
    depth = depth or s["depth"].get(engine) or svc.effective_default(engine)
    if EvalRun.objects.filter(engine=engine, depth=depth, state__in=[EvalRun.State.WAITING, EvalRun.State.RUNNING],
                              baseline=False).exists():
        raise EvalError("یک سنجشِ همین موتور و همین عمق هم‌اکنون در جریان است.")
    voice = voice or DEFAULT_VOICE[engine]
    rows = sentences(sample)
    run = EvalRun.objects.create(store=store, created_by=user, engine=engine, voice=voice, sample=sample, depth=depth,
                                 n_sentences=len(rows), state=EvalRun.State.WAITING,
                                 rows=[{"id": i, "tag": t, "ref": x, "before": None, "after": None} for i, t, x in rows])
    try:
        if engine == "edge":
            _start_edge(run, rows, store, depth)
        else:
            _enqueue_node(run, engine, voice, rows, store, depth)
    except Exception as exc:  # noqa: BLE001
        run.state, run.message = EvalRun.State.FAILED, str(exc)[:300]
        run.save(update_fields=["state", "message", "updated_at"])
    return run


def _enqueue_node(run: EvalRun, engine: str, voice: str, rows, store, depth: str = "") -> None:
    items, shown = build_items(engine, rows, store, depth)
    for r in run.rows:
        r["after_input"] = shown.get(r["id"], "")
    uids = []
    for i in range(0, len(rows), CHUNK):
        ids = {r[0] for r in rows[i:i + CHUNK]}
        part = [it for it in items if it["id"] in ids]
        job = compute.enqueue_durable("voice.pron_eval", {"engine": engine, "voice": voice, "language": "fa", "items": part},
                                      store=None, origin="pron_eval", priority=70, timeout_s=2400)
        uids.append(str(job.uid))
    run.jobs = uids
    run.message = "کارها در صفِ ماندگارِ سرورِ پردازش‌اند؛ با روشن شدنِ آن خودکار انجام می‌شوند."
    run.save()


# ------------------------------------------------------------------ Edge (cloud voice; sentences are public test text)

def _edge_dir(run: EvalRun) -> Path:
    return Path(settings.MEDIA_ROOT) / "pronunciation" / "runs" / str(run.pk)


def _start_edge(run: EvalRun, rows, store, depth: str = "") -> None:
    from services.audio import engines as engine_registry

    if engine_registry.local_only(store) or engine_registry.local_only(None):
        raise EvalError("سیاستِ دادهٔ «فقط لوکال» است؛ سنجشِ Edge متن را به مایکروسافت می‌فرستد.")
    items, shown = build_items("edge", rows, store, depth)
    for r in run.rows:
        r["after_input"] = shown.get(r["id"], "")
    run.state = EvalRun.State.RUNNING
    run.meta = {"stage": "synth", "done": 0, "total": len(items), "dir": str(_edge_dir(run))}
    run.message = "ساختِ صدا با Edge ..."
    run.save()
    _spawn(run.pk, items)


def _thread_main(run_id: int, items: list[dict]) -> None:
    from django.db import connection

    try:
        _edge_synth(run_id, items)
    finally:
        connection.close()          # this thread's own connection


def _spawn(run_id: int, items: list[dict]) -> None:
    t = threading.Thread(target=_thread_main, args=(run_id, items), daemon=True, name=f"pron-edge-{run_id}")
    _THREADS[run_id] = t
    t.start()


def _edge_synth(run_id: int, items: list[dict]) -> None:
    import asyncio

    try:
        import edge_tts
    except ImportError:
        _fail(run_id, "edge-tts نصب نیست")
        return
    run = EvalRun.objects.get(pk=run_id)
    folder = _edge_dir(run)
    folder.mkdir(parents=True, exist_ok=True)

    async def one(sem, it):
        name = f"{it['id']}_{it['variant']}.mp3"
        text = it.get("text") or ""
        async with sem:
            for attempt in range(3):
                try:
                    await edge_tts.Communicate(text, run.voice).save(str(folder / name))
                    return name
                except Exception:  # noqa: BLE001
                    await asyncio.sleep(1.5 * (attempt + 1))
        return ""

    async def all_():
        sem = asyncio.Semaphore(4)
        return await asyncio.gather(*(one(sem, it) for it in items))

    try:
        # «پس»: متنِ لایه؛ «پیش»: متنِ خام
        names = asyncio.run(all_())
        files = [{"id": it["id"], "variant": it["variant"], "name": n} for it, n in zip(items, names) if n]
        run = EvalRun.objects.get(pk=run_id)
        run.meta = {**run.meta, "stage": "asr", "done": len(files), "files": files}
        uids = []
        for i in range(0, len(files), CHUNK * 2):
            part = files[i:i + CHUNK * 2]
            inputs = {f["name"]: str(folder / f["name"]) for f in part}
            job = compute.enqueue_durable("voice.pron_asr", {"engine": "edge", "voice": run.voice, "files": part}, inputs,
                                          origin="pron_eval", priority=70, timeout_s=2400)
            uids.append(str(job.uid))
        run.jobs = uids
        run.state = EvalRun.State.WAITING
        run.message = "صدا ساخته شد؛ گوش‌دادن در صفِ سرورِ پردازش است."
        run.save()
    except Exception as exc:  # noqa: BLE001
        _fail(run_id, f"ساختِ صدای Edge نشد: {exc}")
    finally:
        _THREADS.pop(run_id, None)


def _fail(run_id: int, message: str) -> None:
    EvalRun.objects.filter(pk=run_id).update(state=EvalRun.State.FAILED, message=message[:300], updated_at=timezone.now())


# ------------------------------------------------------------------ collecting

def _read_result(job: ComputeJob) -> dict | None:
    import json

    p = compute.output_path(job, "result.json")
    try:
        return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else None
    except (OSError, ValueError):
        return None


def advance_run(run: EvalRun) -> str:
    """One step for one run; returns what happened."""
    if run.state in (EvalRun.State.DONE, EvalRun.State.FAILED) or run.baseline:
        return "final"
    if run.engine == "edge" and run.meta.get("stage") == "synth":
        t = _THREADS.get(run.pk)
        age = (timezone.now() - run.updated_at).total_seconds()
        if (t is None or not t.is_alive()) and age > STALE_THREAD_S:
            _fail(run.pk, "ساختِ صدای Edge نیمه‌کاره ماند (سایت دوباره بالا آمده)؛ سنجش را دوباره شروع کنید.")
            return "stale"
        return "synth"
    jobs = list(ComputeJob.objects.filter(uid__in=run.jobs))
    if not jobs or len(jobs) < len(run.jobs):
        return "no-jobs"
    failed = [j for j in jobs if j.state in (ComputeJob.State.FAILED, ComputeJob.State.CANCELLED)]
    if failed:
        run.state = EvalRun.State.FAILED
        run.message = (failed[0].error or failed[0].message or "کارِ گره ناموفق بود")[:300]
        run.save(update_fields=["state", "message", "updated_at"])
        return "failed"
    done = [j for j in jobs if j.state == ComputeJob.State.COMPLETED]
    if len(done) < len(jobs):
        want = ComputeJob.State.RUNNING if any(j.state in (ComputeJob.State.CLAIMED, ComputeJob.State.RUNNING) for j in jobs) \
            else EvalRun.State.WAITING
        state = EvalRun.State.RUNNING if want == ComputeJob.State.RUNNING else EvalRun.State.WAITING
        msg = f"{len(done)} از {len(jobs)} دسته انجام شد" if done or state == EvalRun.State.RUNNING else \
            "منتظرِ روشن شدنِ سرورِ پردازش (کار در صفِ ماندگار است)"
        if (run.state, run.message) != (state, msg):
            run.state, run.message = state, msg
            run.save(update_fields=["state", "message", "updated_at"])
        return "waiting"
    return _collect(run, done)


def _collect(run: EvalRun, jobs: list[ComputeJob]) -> str:
    by_key: dict[tuple[int, str], str] = {}
    asr_info, where = {}, ""
    for j in jobs:
        res = _read_result(j)
        if not res:
            run.state, run.message = EvalRun.State.FAILED, "خروجیِ کارِ گره (result.json) خوانده نشد."
            run.save(update_fields=["state", "message", "updated_at"])
            return "failed"
        asr_info = res.get("asr") or asr_info
        where = j.node.name if j.node_id else where
        for it in res.get("items", []):
            by_key[(int(it["id"]), it["variant"])] = it.get("hyp", "")
    rows = []
    for r in run.rows:
        rows.append({**r, "before": by_key.get((r["id"], "before")), "after": by_key.get((r["id"], "after"))})
    run.rows = rows
    run.summary = quality.summarise([r for r in rows if r["before"] is not None and r["after"] is not None])
    run.asr = " / ".join(x for x in (str(asr_info.get("model") or ""), str(asr_info.get("device") or "")) if x)
    run.where = where
    run.state = EvalRun.State.DONE
    run.message = (asr_info.get("note") or "")[:300]
    run.finished_at = timezone.now()
    run.save()
    _problems_from(run)
    if run.engine == "edge":
        shutil.rmtree(_edge_dir(run), ignore_errors=True)
    return "done"


def _problems_from(run: EvalRun, min_count: int = 2) -> None:
    """Words the recogniser missed both before and after, in several sentences -> the store's «مشکل‌دار» list."""
    if run.store_id is None:
        return
    counts: dict[str, int] = {}
    ctx: dict[str, str] = {}
    for r in run.rows:
        if r.get("after") is None:
            continue
        for w in quality.score(r["ref"], r["after"]).missed:
            counts[w] = counts.get(w, 0) + 1
            ctx.setdefault(w, r["ref"])
    words = [w for w, n in counts.items() if n >= min_count and len(w) > 1]
    for w in words:
        row, created = ProblemWord.objects.get_or_create(
            store=run.store, word=w, source=ProblemWord.Source.ASR,
            defaults={"context": ctx[w][:300], "engine": run.engine, "count": counts[w],
                      "detail": f"در {counts[w]} جمله شنیده نشد"})
        if not created:
            row.count = max(row.count, counts[w])
            row.save(update_fields=["count", "updated_at"])


def ensure_full_runs(days: int = 14) -> list[int]:
    """After the node self-test passed: queue the full run (every sentence) for each engine that can run, unless one
    started in the last ``days`` days. Platform-level (no store); safe to call as often as you like."""
    from datetime import timedelta

    since = timezone.now() - timedelta(days=days)
    made: list[int] = []
    engines = ["piper"]
    try:
        from services.audio import engines as engine_registry

        if not engine_registry.local_only(None):
            engines.append("edge")
    except Exception:  # noqa: BLE001
        pass
    try:
        from services.audio import node_audio

        if node_audio.moss_ready()[0]:
            engines.append("moss")
    except Exception:  # noqa: BLE001
        pass
    for engine in engines:
        # both the full layer and the text-only normaliser, so the platform can pick what measured best (services.measured_depths)
        for depth in ("lexicon", "normalize"):
            if EvalRun.objects.filter(engine=engine, depth=depth, sample="full", baseline=False, created_at__gte=since).exclude(
                    state=EvalRun.State.FAILED).exists():
                continue
            try:
                run = start(None, None, engine, sample="full", depth=depth)
                made.append(run.pk)
            except EvalError as exc:
                logger.info("pronunciation: full %s/%s run not started: %s", engine, depth, exc)
    return made


def advance(limit: int = 6) -> dict:
    out = {}
    for run in EvalRun.objects.filter(state__in=[EvalRun.State.WAITING, EvalRun.State.RUNNING], baseline=False)[:limit]:
        try:
            out[run.pk] = advance_run(run)
        except Exception as exc:  # noqa: BLE001
            logger.warning("pronunciation eval %s: %s", run.pk, exc)
            out[run.pk] = f"error: {exc}"
    return out


