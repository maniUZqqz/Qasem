# -*- coding: utf-8 -*-
"""کارهای متن و کد: اول Qwen Coder روی سرورِ پردازش، اگر نبود یا جواب نداد خودکار Metis.

خواستهٔ مالک: این کارها ترجیحاً روی سرورِ پردازش (qwen3-coder:30b) انجام شود، ولی کار هرگز به‌خاطرِ خاموش بودنِ آن
نمی‌خوابد. گرهٔ او اغلب خاموش و کند است (مدلِ ۳۲ میلیاردی ~۱۹۰ ثانیه برای یک چت)، پس:

  · گرهٔ خاموش هیچ‌وقت کار نمی‌گیرد: اگر الان آنلاین نیست، بی‌هیچ انتظاری می‌رود سراغِ Metis.
  · اگر گره آنلاین است ولی کار را تا AI_NODE_CLAIM_TIMEOUT (۴۵ ثانیه) برنداشت (مثلاً سرگرمِ رندر است) ⇐ Metis.
  · اگر بعد از برداشتن تا AI_NODE_RUN_TIMEOUT (۷ دقیقه) تمام نشد ⇐ Metis.
  · اگر وسطِ کار گره قطع شد (heartbeat رفت) ⇐ همان لحظه Metis، نه بعد از پایانِ مهلت.
  · بعد از اولین شکست، بقیهٔ همان کارِ چندمرحله‌ای مستقیم با Metis می‌رود تا هر مرحله ۷ دقیقه هدر نرود.

سیاستِ دادهٔ فروشگاه همان است: پیامِ مشتری که اجازهٔ رفتن به سرویسِ بیرونی ندارد به Metis نمی‌رود و خطا می‌ماند.
بینایی (تصویر) دست نخورده است؛ qwen3-coder مدلِ بینایی نیست.
"""
from __future__ import annotations

import logging
import time

from django.conf import settings

logger = logging.getLogger(__name__)

MODE_QWEN = 'qwen_first'
MODE_METIS = 'metis_only'
MODES = (MODE_QWEN, MODE_METIS)
LABEL_NODE = 'Qwen Coder روی سرورِ پردازش'


class NodeFailed(Exception):
    """سرورِ پردازش جواب نداد؛ متن برای نشان دادن به مالک است."""


def _conf(name, default):
    return getattr(settings, name, default)


def claim_timeout():
    return int(_conf('AI_NODE_CLAIM_TIMEOUT', 45))


def run_timeout():
    return int(_conf('AI_NODE_RUN_TIMEOUT', 420))


def coder_model():
    return settings.UPMARKET_AI['MODEL_CODER']


def enabled():
    """زیرِ آزمون‌های قدیمی خاموش است تا رفتارِ آن‌ها عوض نشود؛ آزمون‌های خودش با AI_ROUTE_FORCE روشنش می‌کنند."""
    return not getattr(settings, 'IS_TEST', False) or getattr(settings, 'AI_ROUTE_FORCE', False)


def mode():
    try:
        from apps.ai_engine.models import AiSettings
        row = AiSettings.objects.filter(pk=1).values('route_mode').first()
    except Exception as exc:  # noqa: BLE001 — پیش از مهاجرت
        logger.info('route mode unavailable: %s', exc)
        return MODE_QWEN
    return (row or {}).get('route_mode') or MODE_QWEN


def wants_node():
    return enabled() and mode() == MODE_QWEN


def _same_model(a, b):
    from . import models_registry
    return models_registry._same_model(a, b)


def node_state():
    """وضعِ الانِ سرورهای پردازش برای این مدل. ⇒ dict برای تصمیم و برای پنل."""
    wanted = coder_model()
    out = {'model': wanted, 'online': False, 'ready': False, 'has_model': None, 'node': '', 'nodes': [], 'known_models': [], 'reason': ''}
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
        # اگر مدل نبود، خودِ Ollama خطا می‌دهد و همان لحظه می‌رویم سراغِ Metis.
        out.update({'ready': True, 'has_model': None, 'node': unknown.name})
        return out
    out['has_model'] = False
    out['reason'] = 'مدلِ %s روی سرورِ پردازش نصب نیست.' % wanted
    return out


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
                raise NodeFailed('سرورِ پردازش کار را در %d ثانیه برنداشت (احتمالاً سرگرمِ کارِ دیگری است).' % claim_timeout())
            return
        node = getattr(job, 'node', None)
        if node is not None:
            node.refresh_from_db(fields=['last_seen'])
            if not node.online:
                compute.cancel(job)
                raise NodeFailed('سرورِ پردازش وسطِ کار قطع شد.')
    return tick


def node_provider(node_name):
    """OllamaProvider ِ معمولی روی صفِ کارها، با بازرسِ بالا؛ پس تعمیرِ JSON و بقیهٔ منطق همان است."""
    from .ollama import OllamaProvider
    prov = OllamaProvider(base_url='agent://%s' % node_name if node_name else 'agent://any', timeout=run_timeout(), model=coder_model())
    prov.num_ctx = int(_conf('AI_NODE_NUM_CTX', 16384))
    state = {'claim_deadline': time.monotonic() + claim_timeout()}
    prov.on_tick = _watch(state)
    prov.watch_state = state
    return prov


class _Router:
    """منطقِ مشترک: اول گره، بعد جایگزین. سیاستِ «بعد از اولین شکست دیگر سراغِ گره نرو» این‌جاست."""

    def __init__(self, task=''):
        self.task = task
        self.node_broken = None           # اگر گره در همین کار شکست خورد، دلیلش
        self.answered_by = ''             # مدلی که واقعاً جواب داد
        self.fell_back = False
        self.fallback_reason = ''

    def _node_reason(self):
        if self.node_broken:
            return self.node_broken
        if not wants_node():
            return 'تنظیم روی «فقط Metis» است.'
        state = node_state()
        return None if state['ready'] else (state['reason'] or 'سرورِ پردازش آماده نیست.')

    def _try_node(self, call):
        """⇒ (ok, نتیجه). شکست‌ها NodeFailed می‌شوند."""
        from .ollama import OllamaError
        state = node_state()
        if not state['ready']:
            raise NodeFailed(state['reason'] or 'سرورِ پردازش آماده نیست.')
        prov = node_provider(state['node'])
        started = time.monotonic()
        try:
            result = call(prov, coder_model())
        except NodeFailed:
            raise
        except OllamaError as exc:
            low = str(exc).lower()
            if 'not found' in low or '404' in low:
                raise NodeFailed('مدلِ %s روی سرورِ پردازش نصب نیست.' % coder_model()) from exc
            raise NodeFailed('سرورِ پردازش جواب نداد: %s' % str(exc)[:200]) from exc
        self.answered_by = coder_model()
        self.fell_back = False
        self.fallback_reason = ''
        log_route(self.task, coder_model(), 'node', False, '', time.monotonic() - started)
        return result

    def _mark_fallback(self, reason, model, started):
        self.answered_by = model
        self.fell_back = True
        self.fallback_reason = reason
        log_route(self.task, model, 'metis', True, reason, time.monotonic() - started)


class RoutedTextProvider(_Router):
    """همان رابطِ OllamaProvider / OpenAICompatProvider برای مسیرهای gateway (generate و generate_json)."""

    def __init__(self, fallback, task=''):
        super().__init__(task)
        self.fallback = fallback

    # بیرونی‌ها (مثلاً برای شمارشِ GPU) این را می‌پرسند
    @property
    def is_remote(self):
        return True

    @property
    def model(self):
        return coder_model()

    def select_models(self, candidates):
        reason = self._node_reason()
        if reason is None:
            return [coder_model()]
        if self.fallback is not None:
            return self.fallback.select_models(candidates)
        return [m for m in (candidates or []) if m] or [coder_model()]

    def last_model(self):
        return self.answered_by

    def _run(self, name, model, prompt, kw):
        started = time.monotonic()
        reason = self._node_reason()
        if reason is None:
            try:
                return self._try_node(lambda prov, m: getattr(prov, name)(m, prompt, **_node_kw(name, kw)))
            except NodeFailed as exc:
                reason = str(exc)
                self.node_broken = reason
                logger.warning('AI route: node failed (%s) — falling back', reason)
        if self.fallback is None:
            from .ollama import OllamaUnavailable
            raise OllamaUnavailable(reason)
        chosen = self.fallback.select_models([model] if model else [])
        chosen_model = chosen[0] if chosen else model
        if name == 'generate':
            result = self.fallback.generate(prompt, model=chosen_model, **_api_kw(kw))
        else:
            result = self.fallback.generate_json(chosen_model, prompt, **_api_json_kw(kw))
        self._mark_fallback(reason, chosen_model, started)
        return result

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
        state = node_state()
        if state['ready']:
            return True, 'سرورِ پردازش آماده است (%s).' % coder_model()
        if self.fallback is not None and hasattr(self.fallback, 'health'):
            return self.fallback.health()
        return False, state['reason']


def _node_kw(name, kw):
    """پارامترها به زبانِ OllamaProvider. مهلتِ کوتاهِ سفارشی نگه داشته می‌شود؛ مهلتِ بلندتر از سقفِ ما نه."""
    out = {k: kw[k] for k in ('system', 'timeout') if kw.get(k) is not None}
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
    """برای سایت‌ساز: همان complete(system, user, json_mode) ِ ai_engine."""

    def __init__(self, fallback, task='site-builder'):
        super().__init__(task)
        self.fallback = fallback

    def complete(self, system, user, json_mode=True, max_tokens=None, temperature=None):
        started = time.monotonic()
        reason = self._node_reason()
        if reason is None:
            options = {'temperature': temperature if temperature is not None else 0.3}
            if max_tokens:
                options['num_predict'] = int(max_tokens)

            def call(prov, model):
                return prov.generate(model, user, system=system, format_json=json_mode, options=options)
            try:
                text = self._try_node(call)
                if text:
                    return text
                raise NodeFailed('سرورِ پردازش جوابِ خالی داد.')
            except NodeFailed as exc:
                reason = str(exc)
                self.node_broken = reason
                logger.warning('AI route: node failed (%s) — falling back', reason)
        text = self.fallback.complete(system, user, json_mode=json_mode)
        model = getattr(getattr(self.fallback, 'cfg', None), 'model', '') or 'Metis'
        self._mark_fallback(reason, model, started)
        return text
