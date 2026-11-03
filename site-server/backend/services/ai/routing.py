# -*- coding: utf-8 -*-
"""مسیریابیِ هوش مصنوعی: لوکال (Ollama روی سرورِ پردازش) و متیس (API)، با اولویتِ قابلِ تنظیم.

تصمیمِ مالک (۱۴۰۵/۰۸/۱۲): «توی همه کارها باید دو تاش باشه و باید توی تنظیمات تعیین شود: متیس / لوکال — یکی نبود اون یکی».
تنظیم در `apps.ai.AiPriority` است (جنگو ادمین + پنل «موتورهای AI»)؛ منطقِ تصمیم این‌جاست:

  · ترتیب = اولویتِ کلی یا اولویتِ همان نوعِ کار (متن/کد/بینایی) — `priority.config().order(kind)`
  · مسیرِ اول جواب نداد ⇒ همان لحظه مسیرِ دوم. «جواب نداد» یعنی: گره خاموش یا مدل نصب نیست، گره کار را برنداشت،
    مهلت، قطعِ گره وسطِ کار، HTTP ۴۰۲ / ۴۰۱ / ۴۰۳ / ۴۲۹ / ۵xx، قطعِ اتصال، تنظیم‌نبودنِ کلید.
  · شکستِ تازه چند دقیقه یادش می‌ماند (کلیدِ مدار: priority.trip/open_failure)؛ تا آن موقع مسیرِ خراب آخرِ صف می‌رود،
    پس هر درخواست منتظرِ مهلتِ سرویسِ مرده نمی‌ماند. اگر هر دو مسیر خراب‌اند، باز هر دو امتحان می‌شوند.
  · هر دو شکست خورد ⇒ `AllProvidersFailed` با جملهٔ فارسی که دلیلِ هر دو را می‌گوید.
  · کدام مسیر و مدل جواب داد روی خودِ provider می‌ماند (answered_by / answered_via / fell_back / fallback_reason /
    answered_label) و `recorded_json_call` آن را در AIRequest می‌نویسد.

گرهٔ مالک اغلب خاموش و کند است (مدلِ ۳۲ میلیاردی ~۱۹۰ ثانیه برای یک چت)، پس:

  · گرهٔ خاموش هیچ‌وقت کار نمی‌گیرد: اگر الان آنلاین نیست، بی‌هیچ انتظاری می‌رود سراغِ مسیرِ دیگر.
  · اگر گره آنلاین است ولی کار را تا AI_NODE_CLAIM_TIMEOUT (۴۵ ثانیه) برنداشت (مثلاً سرگرمِ رندر است) ⇐ مسیرِ دیگر.
  · اگر بعد از برداشتن تا AI_NODE_RUN_TIMEOUT (۷ دقیقه) تمام نشد ⇐ مسیرِ دیگر.
  · اگر وسطِ کار گره قطع شد (heartbeat رفت) ⇐ همان لحظه مسیرِ دیگر، نه بعد از پایانِ مهلت.
  · بعد از اولین شکست، بقیهٔ همان کارِ چندمرحله‌ای مستقیم به مسیرِ دیگر می‌رود تا هر مرحله ۷ دقیقه هدر نرود.

سیاستِ دادهٔ فروشگاه همان است: پیامِ مشتری که اجازهٔ رفتن به سرویسِ بیرونی ندارد به متیس نمی‌رود و فقط لوکال می‌ماند.

نام‌های قدیمی (RoutedTextProvider, StudioRouted, node_state, coder_model, wants_node, mode, node_provider, NodeFailed) ماندند:
ویرایشگرِ ویدیو، عکس، استودیو و آزمون‌ها صدایشان می‌زنند.
"""
from __future__ import annotations

import logging
import time

from django.conf import settings

from . import priority
from .ollama import OllamaUnavailable
from .priority import CODE, LOCAL, METIS, TEXT, VISION, Failure  # noqa: F401 — re-exported for callers

logger = logging.getLogger(__name__)

# نام‌های قدیمیِ «حالت» — حالا فقط نمایی از اولویت‌اند (metis_only ≈ اول متیس)
MODE_QWEN = 'qwen_first'
MODE_METIS = 'metis_only'
MODES = (MODE_QWEN, MODE_METIS)
LABEL_NODE = 'لوکال (Ollama روی سرورِ پردازش)'


class NodeFailed(Exception):
    """سرورِ پردازش جواب نداد؛ متن برای نشان دادن به مالک است."""


class AllProvidersFailed(OllamaUnavailable):
    """هر دو مسیر (لوکال و متیس) جواب ندادند. پیام دلیلِ هر دو را می‌گوید؛ `failures` = {مسیر: Failure}.

    زیرکلاسِ OllamaUnavailable است تا همه‌جا مثلِ «هوش مصنوعی در دسترس نیست» دیده شود (recorded_json_call دیگر مدلِ بعدی را
    امتحان نمی‌کند، نماهای مشتری ۵۰۳ می‌دهند) و قراردادِ قدیمی نشکند."""

    status_hint = None

    def __init__(self, message, failures=None):
        super().__init__(message)
        self.failures = failures or {}
        kinds = {f.kind for f in self.failures.values() if f is not None}
        if kinds == {'timeout'}:
            self.status_hint = 'TIMEOUT'


def _conf(name, default):
    return getattr(settings, name, default)


def claim_timeout():
    return int(_conf('AI_NODE_CLAIM_TIMEOUT', 45))


def run_timeout():
    return int(_conf('AI_NODE_RUN_TIMEOUT', 420))


def coder_model():
    """مدلِ لوکالِ کار‌های «کد» (سایت‌ساز): انتخابِ مالک در تنظیم، وگرنه MODEL_CODER."""
    return priority.local_model(CODE)


def enabled():
    """زیرِ آزمون‌های قدیمی خاموش است تا رفتارِ آن‌ها عوض نشود؛ آزمون‌های خودش با AI_ROUTE_FORCE روشنش می‌کنند."""
    return not getattr(settings, 'IS_TEST', False) or getattr(settings, 'AI_ROUTE_FORCE', False)


def mode():
    """نمای قدیمیِ تنظیم: qwen_first (اول لوکال) یا metis_only (اول متیس). منبعِ حقیقت: apps.ai.AiPriority."""
    return MODE_METIS if priority.config().first_for(CODE) == METIS else MODE_QWEN


def wants_node():
    """آیا مسیریابیِ دوگانه روشن است؟ (دیگر «فقط متیس» نداریم؛ ترتیب را اولویت می‌گوید و لوکال همیشه پشتیبان است)."""
    return enabled()


def _same_model(a, b):
    from . import models_registry
    return models_registry._same_model(a, b)


def node_state(kind=CODE):
    """وضعِ الانِ سرورهای پردازش برای مدلِ لوکالِ این نوعِ کار. ⇒ dict برای تصمیم و برای پنل."""
    wanted = priority.local_model(kind)
    out = {'model': wanted, 'kind': kind, 'online': False, 'ready': False, 'has_model': None, 'node': '', 'nodes': [], 'known_models': [], 'reason': ''}
    try:
        from apps.compute.models import ComputeNode
        nodes = list(ComputeNode.objects.filter(enabled=True))
    except Exception as exc:  # noqa: BLE001 — جدول هنوز نیست
        out['reason'] = 'سرورهای پردازش در دسترس نیستند.'
        logger.info('compute unavailable: %s', exc)
        return out
    registered = [n for n in nodes if n.has('ollama')]
    live = [n for n in registered if n.online]
    out['nodes'] = [{'name': n.name, 'online': n.online, 'models': list((n.capabilities or {}).get('ollama_models') or [])} for n in registered or nodes]
    if not live:
        out['reason'] = 'سرورِ پردازش خاموش است.' if nodes else 'هیچ سرورِ پردازشی ثبت نشده.'
        # آخرین فهرستِ مدل‌ها (از آخرین باری که گره روشن بود) فقط برای نمایش
        names = []
        for n in registered or nodes:
            names += [m for m in (n.capabilities or {}).get('ollama_models') or [] if m not in names]
        out['known_models'] = names
        if names:
            out['has_model'] = any(_same_model(wanted, m) for m in names)
        return out
    out['online'] = True
    unknown = None
    for n in live:
        names = (n.capabilities or {}).get('ollama_models')
        for m in names or []:
            if m not in out['known_models']:
                out['known_models'].append(m)
        if names and any(_same_model(wanted, m) for m in names):
            out.update({'ready': True, 'has_model': True, 'node': n.name})
            return out
        if not names and unknown is None:
            unknown = n
    if unknown is not None:
        # Ollama الان خاموش است و عاملِ گره می‌تواند روشنش کند؛ فهرستِ مدل‌ها را تا آن موقع نمی‌دانیم.
        # اگر مدل نبود، خودِ Ollama خطا می‌دهد و همان لحظه می‌رویم سراغِ مسیرِ دیگر.
        out.update({'ready': True, 'has_model': None, 'node': unknown.name})
        return out
    out['has_model'] = False
    out['reason'] = 'مدلِ %s روی سرورِ پردازش نصب نیست.' % wanted
    return out


def node_models():
    """مدل‌هایی که سرورهای پردازش گزارش کرده‌اند (برای لیستِ کشویی در تنظیم). آنلاین‌ها اول، بعد آخرین گزارشِ بقیه."""
    names = []
    try:
        from apps.compute.models import ComputeNode
        nodes = [n for n in ComputeNode.objects.filter(enabled=True) if n.has('ollama')]
        nodes.sort(key=lambda n: (not n.online, n.name))
        for n in nodes:
            for m in (n.capabilities or {}).get('ollama_models') or []:
                if isinstance(m, str) and m and m not in names:
                    names.append(m)
    except Exception as exc:  # noqa: BLE001
        logger.info('node models unavailable: %s', exc)
    return names


def log_route(task, model, via, fell_back=False, reason='', seconds=0.0):
    try:
        from apps.ai_engine.models import AiRouteLog
        AiRouteLog.objects.create(task=(task or '')[:60], model=(model or '')[:120], via=via, fell_back=bool(fell_back),
                                  reason=(reason or '')[:400], seconds=round(float(seconds or 0), 1))
        old = list(AiRouteLog.objects.order_by('-id').values_list('pk', flat=True)[200:])
        if old:
            AiRouteLog.objects.filter(pk__in=old).delete()
    except Exception as exc:  # noqa: BLE001 — گزارش نباید کار را بخواباند
        logger.info('route log: %s', exc)


def _watch(state):
    """بازرسِ هر ۲ ثانیهٔ کار: برنداشته، قطع‌شده. compute.wait خودش مهلتِ اجرا را می‌سنجد."""
    def tick(job):
        from apps.compute import services as compute
        if not job.claimed_at:
            if time.monotonic() > state['claim_deadline']:
                compute.cancel(job)
                raise NodeFailed('سرورِ پردازش کار را در %d ثانیه برنداشت (احتمالاً سرگرمِ کارِ دیگری است).' % state['claim_s'])
            return
        node = getattr(job, 'node', None)
        if node is not None:
            node.refresh_from_db(fields=['last_seen'])
            if not node.online:
                compute.cancel(job)
                raise NodeFailed('سرورِ پردازش وسطِ کار قطع شد.')
    return tick


def node_provider(node_name, kind=CODE, claim_s=None, run_s=None):
    """OllamaProvider ِ معمولی روی صفِ کارها، با بازرسِ بالا؛ پس تعمیرِ JSON و بقیهٔ منطق همان است."""
    from .ollama import OllamaProvider
    claim_s = int(claim_s if claim_s is not None else claim_timeout())
    run_s = int(run_s if run_s is not None else run_timeout())
    prov = OllamaProvider(base_url='agent://%s' % node_name if node_name else 'agent://any', timeout=run_s, model=priority.local_model(kind))
    prov.num_ctx = int(_conf('AI_NODE_NUM_CTX', 16384))
    state = {'claim_deadline': time.monotonic() + claim_s, 'claim_s': claim_s}
    prov.on_tick = _watch(state)
    prov.watch_state = state
    return prov


# ───────────────────────────── موتورِ مشترکِ مسیریابی

class _Router:
    """منطقِ مشترک: ترتیب را اولویت می‌گوید، اولی که شد جواب می‌دهد، وگرنه دومی.

    زیرکلاس‌ها فقط می‌گویند «لوکال را چطور صدا بزنم» و «متیس را چطور» (دو callable) و `_metis_precheck()`."""

    DEFAULT_KIND = CODE

    def __init__(self, task='', kind=None):
        self.task = task
        self.kind = kind or self.DEFAULT_KIND
        self.node_broken = None           # اگر گره در همین کار شکست خورد، دلیلش (نامِ قدیمی؛ ویرایشگرِ ویدیو می‌خواند)
        self.metis_broken = None
        self.answered_by = ''             # مدلی که واقعاً جواب داد
        self.answered_via = ''            # 'local' | 'metis'
        self.fell_back = False
        self.fallback_reason = ''
        self.attempts = []                # [{'via','model','ok','reason'}] آخرین _route
        self._lifetime = {}               # مسیر -> Failure؛ تا پایانِ عمرِ این provider دیگر امتحان نمی‌شود

    # ---- نمایش
    @property
    def answered_label(self):
        return priority.answer_label(self.answered_via, self.answered_by, self.fell_back)

    def describe(self):
        return {'via': self.answered_via, 'model': self.answered_by, 'fell_back': self.fell_back,
                'fallback_reason': self.fallback_reason, 'label': self.answered_label}

    # ---- قلاب‌های زیرکلاس
    def _metis_precheck(self):
        """⇒ Failure اگر متیس اصلاً نباید امتحان شود (کلید/آدرس نیست یا سیاستِ داده اجازه نمی‌دهد)."""
        return None

    def _metis_model_hint(self, candidates=None):
        return priority.metis_model(self.kind)

    # ---- پیش‌بررسی‌ها (فوری، بی‌شبکه)
    def _node_reason(self):
        """چرا لوکال الان قابل‌استفاده نیست؛ None اگر هست."""
        if self.node_broken:
            return self.node_broken
        if not wants_node():
            return 'مسیریابی خاموش است.'
        state = node_state(self.kind)
        return None if state['ready'] else (state['reason'] or 'سرورِ پردازش آماده نیست.')

    def _precheck(self, provider):
        if provider == LOCAL:
            if not wants_node():
                return Failure('offline', 'مسیریابی خاموش است.', provider=LOCAL)
            state = node_state(self.kind)
            if state['ready']:
                return None
            reason = state['reason'] or 'سرورِ پردازش آماده نیست.'
            kind = 'no_model' if state.get('has_model') is False and state.get('online') else 'offline'
            return Failure(kind, reason, provider=LOCAL, model=state['model'])
        return self._metis_precheck()

    def _model_of(self, provider, cfg=None):
        return priority.local_model(self.kind, cfg) if provider == LOCAL else ''

    # ---- ترتیبِ عملی، بی‌اجرا (برای select_models)
    def _usable_order(self, cfg=None):
        cfg = cfg or priority.config()
        order = cfg.order(self.kind)
        usable = [p for p in order if self._lifetime.get(p) is None and self._precheck(p) is None]
        if len(usable) > 1:
            blocked = {p: priority.open_failure(p, self._model_of(p, cfg)) for p in usable}
            if any(blocked.values()) and not all(blocked.values()):
                usable.sort(key=lambda p: blocked[p] is not None)
        return usable

    def availability(self):
        """(آیا دست‌کم یک مسیر الان قابل‌استفاده است، چرا) — بی‌هیچ درخواستی به شبکه. برای ویژگی‌هایی که مدل «اختیاری» است
        (پژوهشِ رقبا/ترند): اگر هیچ‌کدام از دو مسیر نیست، بی‌صبر کردن از مدل صرف‌نظر می‌کنند."""
        cfg = priority.config()
        order = cfg.order(self.kind)
        reasons = {}
        usable = []
        for p in order:
            pre = self._lifetime.get(p) or self._precheck(p)
            if pre is not None:
                reasons[p] = pre.sentence()
            else:
                usable.append(p)
        good = []
        for p in usable:
            info = priority.open_failure(p, self._model_of(p, cfg))
            if info:
                reasons[p] = 'چند لحظه پیش خطا داد (%s)' % (info['message'] or 'بی‌پیام')
            else:
                good.append(p)
        if good:
            return True, ' / '.join(priority.PROVIDER_LABEL[p] for p in good)
        return False, '؛ '.join('%s: %s' % (priority.PROVIDER_LABEL[p], reasons.get(p, '—')) for p in order)

    # ---- اجرا
    def _call_local(self, local_call, cfg):
        state = node_state(self.kind)
        if not state['ready']:
            raise NodeFailed(state['reason'] or 'سرورِ پردازش آماده نیست.')
        model = priority.local_model(self.kind, cfg)
        prov = node_provider(state['node'], self.kind) if self.kind != CODE else node_provider(state['node'])
        return local_call(prov, model), model

    def _route(self, local_call, metis_call):
        """local_call(prov, model) ⇒ نتیجه؛ metis_call(has_alt) ⇒ (نتیجه، مدل). اولین مسیرِ موفق جواب می‌دهد."""
        cfg = priority.config()
        order = cfg.order(self.kind)
        first = order[0]
        started = time.monotonic()
        self.attempts = []
        self.answered_by, self.answered_via, self.fell_back, self.fallback_reason = '', '', False, ''
        failures = {}
        runnable = []
        for p in order:
            pre = self._lifetime.get(p) or self._precheck(p)
            if pre is not None:
                failures[p] = pre
                self.attempts.append({'via': p, 'model': pre.model, 'ok': False, 'reason': pre.message, 'tried': False})
            else:
                runnable.append(p)

        if len(runnable) > 1:
            blocked = {p: priority.open_failure(p, self._model_of(p, cfg)) for p in runnable}
            if any(blocked.values()) and not all(blocked.values()):
                runnable.sort(key=lambda p: blocked[p] is not None)
                for p, info in blocked.items():
                    if info:
                        left = priority.minutes_left(info['until'])
                        failures[p] = Failure(info['kind'] or 'error',
                                              'چند لحظه پیش خطا داد و %d دقیقه کنار گذاشته شده است (%s)' % (left, info['message'] or 'بی‌پیام'),
                                              provider=p, model=self._model_of(p, cfg))

        for index, p in enumerate(runnable):
            has_alt = index < len(runnable) - 1
            model = self._model_of(p, cfg)
            try:
                if p == LOCAL:
                    result, model = self._call_local(local_call, cfg)
                else:
                    result, model = metis_call(has_alt)
            except Exception as exc:  # noqa: BLE001 — هر شکستی ⇒ مسیرِ دیگر؛ علتش ثبت می‌شود
                failure = priority.classify(exc, p, model)
                if p == LOCAL and failure.kind == 'no_model':
                    failure.message = 'مدلِ %s روی سرورِ پردازش نصب نیست.' % (model or priority.local_model(self.kind, cfg))
                failures[p] = failure
                self.attempts.append({'via': p, 'model': model, 'ok': False, 'reason': failure.message, 'tried': True})
                self._lifetime[p] = failure
                if p == LOCAL:
                    self.node_broken = failure.message
                else:
                    self.metis_broken = failure.message
                priority.trip(p, failure, model, cfg.breaker_minutes)
                logger.warning('AI route [%s/%s]: %s failed (%s) — %s', self.task, self.kind, p, failure.kind,
                               'trying the other path' if has_alt else 'no path left')
                continue
            self.attempts.append({'via': p, 'model': model, 'ok': True, 'reason': '', 'tried': True})
            self._succeeded(p, model, first, failures, time.monotonic() - started)
            return result
        raise self._all_failed(order, failures)

    def _succeeded(self, provider, model, first, failures, seconds):
        self.answered_by = model or ''
        self.answered_via = provider
        self.fell_back = provider != first
        reason = ''
        if self.fell_back and failures.get(first) is not None:
            reason = failures[first].sentence()[:400]
        self.fallback_reason = reason
        priority.ok(provider, model)
        log_route(self.task, model, 'node' if provider == LOCAL else 'metis', self.fell_back, reason, seconds)

    def _all_failed(self, order, failures):
        parts = []
        for p in order:
            f = failures.get(p)
            parts.append('%s: %s' % (priority.PROVIDER_LABEL[p], f.sentence() if f is not None else 'امتحان نشد'))
        return AllProvidersFailed('هیچ‌کدام از دو مسیرِ هوش مصنوعی جواب ندادند — ' + '؛ '.join(parts), failures)


def _tune_metis(prov, has_alt):
    """وقتی مسیرِ دیگری هست، متیس تکرارِ ۳ باره نکند: سریع شکست بخورد و نوبت به دیگری برسد."""
    try:
        from .openai_compat import OpenAICompatProvider, RETRIES
        if isinstance(prov, OpenAICompatProvider):
            prov.retries = 0 if has_alt else RETRIES
    except Exception:  # noqa: BLE001
        pass


class RoutedTextProvider(_Router):
    """همان رابطِ OllamaProvider / OpenAICompatProvider برای مسیرهای gateway (generate و generate_json).

    `fallback` = کلاینتِ مسیرِ متیس (OpenAICompatProvider) یا None اگر سیاستِ داده/تنظیم اجازه نمی‌دهد.
    `kind` = متن / کد / بینایی (مدلِ لوکال و اولویتِ همان نوع)؛ بی‌kind همان «کد» ِ قدیمی (qwen3-coder) است."""

    def __init__(self, fallback, task='', kind=None, no_fallback_reason=''):
        super().__init__(task, kind)
        self.fallback = fallback
        self.no_fallback_reason = no_fallback_reason

    # بیرونی‌ها (مثلاً برای شمارشِ GPU) این را می‌پرسند
    @property
    def is_remote(self):
        return True

    @property
    def model(self):
        return priority.local_model(self.kind)

    def _metis_precheck(self):
        if self.fallback is None:
            kind = 'policy' if 'سیاست' in (self.no_fallback_reason or '') else 'unconfigured'
            return Failure(kind, self.no_fallback_reason or 'متیس برای این کار در دسترس نیست (تنظیم نشده یا سیاستِ داده اجازه نمی‌دهد).',
                           provider=METIS)
        return None

    def select_models(self, candidates):
        usable = self._usable_order()
        if usable and usable[0] == LOCAL:
            return [priority.local_model(self.kind)]
        if self.fallback is not None:
            return self.fallback.select_models(candidates)
        return [m for m in (candidates or []) if m] or [priority.local_model(self.kind)]

    def last_model(self):
        return self.answered_by

    def _run(self, name, model, prompt, kw):
        def local(prov, m):
            return getattr(prov, name)(m, prompt, **_node_kw(name, kw))

        def metis(has_alt):
            prov = self.fallback
            _tune_metis(prov, has_alt)
            chosen = prov.select_models([model] if model else [])
            chosen_model = chosen[0] if chosen else model
            if name == 'generate':
                return prov.generate(prompt, model=chosen_model, **_api_kw(kw)), chosen_model
            return prov.generate_json(chosen_model, prompt, **_api_json_kw(kw)), chosen_model

        return self._route(local, metis)

    def generate(self, *args, model=None, **kw):
        """هر دو شکل را می‌پذیرد: generate(model, prompt) ِ Ollama و generate(prompt, model=…) ِ API."""
        if len(args) == 2:
            model, prompt = args
        else:
            prompt = args[0] if args else kw.pop('prompt')
        return self._run('generate', model, prompt, kw)

    def generate_json(self, model, prompt, **kw):
        return self._run('generate_json', model, prompt, kw)

    def health(self):
        state = node_state(self.kind)
        if state['ready']:
            return True, 'سرورِ پردازش آماده است (%s).' % state['model']
        if self.fallback is not None and hasattr(self.fallback, 'health'):
            return self.fallback.health()
        return False, state['reason']


def _node_kw(name, kw):
    """پارامترها به زبانِ OllamaProvider. مهلتِ کوتاهِ سفارشی نگه داشته می‌شود؛ مهلتِ بلندتر از سقفِ ما نه."""
    out = {k: kw[k] for k in ('system', 'timeout') if kw.get(k) is not None}
    if kw.get('images'):
        out['images'] = kw['images']
    options = dict(kw.get('options') or {})
    if kw.get('temperature') is not None:
        options['temperature'] = kw['temperature']
    if kw.get('num_predict') is not None:
        options['num_predict'] = kw['num_predict']
    if options:
        out['options'] = options
    if name == 'generate' and (kw.get('format_json') or kw.get('json_mode')):
        out['format_json'] = True
    if name == 'generate_json' and kw.get('repair_attempts') is not None:
        out['repair_attempts'] = kw['repair_attempts']
    if out.get('timeout'):
        out['timeout'] = min(int(out['timeout']), run_timeout())
    return out


def _api_kw(kw):
    """پارامترها به زبانِ OpenAICompatProvider.generate."""
    out = {k: kw[k] for k in ('system', 'images', 'timeout', 'temperature', 'num_predict') if kw.get(k) is not None}
    options = kw.get('options') or {}
    for key in ('temperature', 'num_predict'):
        if key not in out and options.get(key) is not None:
            out[key] = options[key]
    if kw.get('format_json') or kw.get('json_mode'):
        out['json_mode'] = True
    return out


def _api_json_kw(kw):
    return {k: kw[k] for k in ('system', 'images', 'options', 'repair_attempts', 'timeout', 'schema_keys') if kw.get(k) is not None}


class StudioRouted(_Router):
    """برای سایت‌ساز: همان complete(system, user, json_mode) ِ ai_engine. نوعِ کار = کد (qwen3-coder)."""

    DEFAULT_KIND = CODE

    def __init__(self, fallback, task='site-builder'):
        super().__init__(task, CODE)
        self.fallback = fallback

    def _metis_precheck(self):
        cfg = getattr(self.fallback, 'cfg', None)
        if cfg is not None and not (getattr(cfg, 'api_key', '') or '').strip():
            return Failure('unconfigured', 'کلیدِ API ِ متیس در تنظیماتِ سایت‌ساز (یا .env) وارد نشده است.', provider=METIS)
        return None

    def complete(self, system, user, json_mode=True, max_tokens=None, temperature=None):
        options = {'temperature': temperature if temperature is not None else 0.3}
        if max_tokens:
            options['num_predict'] = int(max_tokens)

        def local(prov, model):
            text = prov.generate(model, user, system=system, format_json=json_mode, options=options)
            if not text:
                raise NodeFailed('سرورِ پردازش جوابِ خالی داد.')
            return text

        def metis(has_alt):
            if hasattr(self.fallback, 'fast_fail'):
                self.fallback.fast_fail = has_alt
            text = self.fallback.complete(system, user, json_mode=json_mode)
            model = getattr(getattr(self.fallback, 'cfg', None), 'model', '') or 'Metis'
            return text, model

        return self._route(local, metis)


def _flatten(messages):
    """پیام‌های چت (system/user/assistant) ⇒ (system, prompt) برای /api/generate ِ Ollama."""
    system = '\n\n'.join(str(m.get('content') or '') for m in messages if m.get('role') == 'system')
    rest = [m for m in messages if m.get('role') != 'system']
    if len(rest) == 1:
        return system, str(rest[0].get('content') or '')
    names = {'user': 'USER', 'assistant': 'ASSISTANT'}
    prompt = '\n\n'.join('%s:\n%s' % (names.get(m.get('role'), 'USER'), m.get('content') or '') for m in rest)
    return system, prompt + '\n\nASSISTANT:\n'


class ChatRouted(_Router):
    """برای هر برنامه‌ای که یک گفتگوی چندپیامی دارد (کارگردانِ ویدیوی سه‌بعدی).

    `metis_chat(messages, temperature)` ⇒ (متن، usage) را صاحبِ برنامه می‌دهد؛ `metis_model` فقط برای ثبت."""

    DEFAULT_KIND = TEXT

    def __init__(self, metis_chat, metis_model='', metis_ready=True, task='chat', kind=TEXT):
        super().__init__(task, kind)
        self.metis_chat = metis_chat
        self.metis_model = metis_model
        self.metis_ready = metis_ready

    def _metis_precheck(self):
        if not self.metis_ready:
            return Failure('unconfigured', 'کلیدِ API ِ متیس برای این بخش وارد نشده است.', provider=METIS)
        return None

    def chat(self, messages, temperature=0.7, json_mode=True):
        system, prompt = _flatten(messages)

        def local(prov, model):
            text = prov.generate(model, prompt, system=system or None, format_json=json_mode, options={'temperature': temperature})
            if not text:
                raise NodeFailed('سرورِ پردازش جوابِ خالی داد.')
            return text, None

        def metis(has_alt):
            return self.metis_chat(messages, temperature), self.metis_model

        return self._route(local, metis)
