# -*- coding: utf-8 -*-
"""اتصال به سرویسِ هوشِ مصنوعی — با کتابخانهٔ رسمیِ `openai`.

نشانیِ پایه (Base URL)، کلید (توکن) و نامِ مدل از جدولِ AiSettings می‌آیند
که در جنگو ادمین ویرایش می‌شود؛ پس OpenAI، Metis، OpenRouter یا هر سرویسِ
سازگارِ دیگری فقط با عوض‌کردنِ همان سه مقدار کار می‌کند.

هر Provider فقط یک کار می‌کند: `complete(system, user) -> str`.
همه‌چیزِ دیگر (Context، اعتبارسنجی، Diff، اعمال) بیرون از این فایل است.

پیامِ کاربر همیشه یک JSON است (services آن را می‌سازد) تا هم مدل‌های واقعی
ساختار را دقیق بگیرند و هم Providerِ آزمایشی بتواند آن را بخواند.
"""
import json
import re


class AiError(Exception):
    pass


def extract_json(text):
    """JSON را از پاسخِ مدل بیرون می‌کشد — حتی اگر لای ```json … ``` یا متن باشد."""
    if not text:
        raise AiError('پاسخِ خالی از مدل.')
    t = text.strip()
    m = re.search(r'```(?:json)?\s*(.*?)```', t, re.S)
    if m:
        t = m.group(1).strip()
    try:
        return json.loads(t)
    except ValueError:
        pass
    a, b = t.find('{'), t.rfind('}')
    if a >= 0 and b > a:
        try:
            return json.loads(t[a:b + 1])
        except ValueError as exc:
            raise AiError('پاسخِ مدل JSONِ معتبر نبود: %s' % exc)
    raise AiError('در پاسخِ مدل JSON پیدا نشد.')


class BaseProvider:
    name = 'base'

    def __init__(self, cfg):
        self.cfg = cfg

    def complete(self, system, user, json_mode=True):
        raise NotImplementedError

    def ping(self):
        return self.complete('پاسخِ خیلی کوتاه بده.', 'فقط بنویس: OK', json_mode=False)

    def list_models(self, limit=30):
        return []


def _short(exc, n=300):
    msg = getattr(exc, 'message', None) or str(exc)
    body = getattr(exc, 'body', None)
    if isinstance(body, dict):
        err = body.get('error') if isinstance(body.get('error'), dict) else body
        msg = err.get('message') or msg
    return str(msg)[:n]


class OpenAIProvider(BaseProvider):
    """کتابخانهٔ رسمیِ openai — برای OpenAI و هر سرویسِ سازگار با آن."""
    name = 'openai'

    def _client(self):
        try:
            from openai import OpenAI
        except ImportError:
            raise AiError('کتابخانهٔ openai نصب نیست (venv/bin/pip install openai).')
        if not (self.cfg.api_key or '').strip():
            raise AiError('کلید (توکن) API تنظیم نشده — در جنگو ادمین ⇐ «تنظیماتِ هوشِ مصنوعی» بگذار.')
        return OpenAI(api_key=self.cfg.api_key.strip(),
                      base_url=(self.cfg.base_url or '').strip() or None,
                      timeout=float(self.cfg.timeout_s or 120), max_retries=1)

    def complete(self, system, user, json_mode=True):
        import openai
        client = self._client()
        params = {
            'model': (self.cfg.model or '').strip() or 'gpt-4o-mini',
            'messages': [{'role': 'system', 'content': system}, {'role': 'user', 'content': user}],
            'temperature': self.cfg.temperature,
            'max_tokens': self.cfg.max_tokens,
        }
        if json_mode:
            params['response_format'] = {'type': 'json_object'}
        resp = None
        # مدل‌ها و سرویس‌ها همه یک پارامترها را نمی‌پذیرند؛ اگر یکی را رد کردند، بی‌آن دوباره بفرست
        for _ in range(4):
            try:
                resp = client.chat.completions.create(**params)
                break
            except openai.BadRequestError as exc:
                msg = _short(exc, 800).lower()
                if 'max_tokens' in params and ('max_tokens' in msg or 'max_completion_tokens' in msg):
                    params['max_completion_tokens'] = params.pop('max_tokens')
                    continue
                if 'temperature' in params and 'temperature' in msg:
                    params.pop('temperature')
                    continue
                if 'response_format' in params and ('response_format' in msg or 'json' in msg):
                    params.pop('response_format')
                    continue
                raise AiError('سرویس درخواست را نپذیرفت (400): %s' % _short(exc))
            except openai.AuthenticationError:
                raise AiError('کلید (توکن) پذیرفته نشد (401) — در جنگو ادمین کلید را وارسی کن.')
            except openai.PermissionDeniedError as exc:
                raise AiError('دسترسی رد شد (403): %s' % _short(exc))
            except openai.NotFoundError as exc:
                raise AiError('مدلِ «%s» یا نشانیِ «%s» پیدا نشد (404): %s'
                              % (params['model'], self.cfg.base_url or 'api.openai.com', _short(exc)))
            except openai.RateLimitError as exc:
                raise AiError('سقفِ درخواست یا اعتبارِ حساب تمام شده (429): %s' % _short(exc))
            except openai.APITimeoutError:
                raise AiError('سرویس در %s ثانیه جواب نداد (مهلت را در جنگو ادمین بیشتر کن).' % self.cfg.timeout_s)
            except openai.APIConnectionError as exc:
                raise AiError('اتصال به سرویس برقرار نشد (%s): %s' % (self.cfg.base_url or 'api.openai.com', _short(exc)))
            except openai.APIStatusError as exc:
                raise AiError('سرویس خطای %s برگرداند: %s' % (getattr(exc, 'status_code', '?'), _short(exc)))
        if resp is None:
            raise AiError('سرویس هیچ ترکیبی از پارامترها را نپذیرفت.')
        try:
            choice = resp.choices[0]
            content = choice.message.content
        except (AttributeError, IndexError, TypeError):
            raise AiError('ساختارِ پاسخِ سرویس ناشناخته بود.')
        if not content:
            raise AiError('مدل پاسخِ خالی داد (finish_reason=%s).' % getattr(choice, 'finish_reason', '?'))
        return content

    def list_models(self, limit=30):
        """نامِ مدل‌هایی که سرویس اعلام می‌کند (اگر پشتیبانی کند)."""
        try:
            ids = [m.id for m in self._client().models.list()]
        except Exception:  # noqa — بعضی سرویس‌ها /models ندارند
            return []
        # مدل‌های چت اول؛ مدل‌های fine-tune ِ حساب‌های دیگر و جاسازی/صدا/تصویر کنار
        skip = ('ft:', 'embedding', 'whisper', 'tts', 'dall-e', 'davinci', 'babbage', 'moderation', 'image', 'audio')
        chat = [i for i in ids if not any(s in i.lower() for s in skip)]
        pref = ('gpt-', 'o1', 'o3', 'o4', 'claude', 'gemini', 'deepseek', 'llama', 'qwen', 'mistral', 'grok')
        chat.sort(key=lambda i: (not i.lower().startswith(pref), i))
        return chat[:limit]


class MockProvider(BaseProvider):
    """بدونِ اینترنت: پاسخ‌های ثابت ولی معنی‌دار — تا کلِ چرخه (پیشنهاد⇒Diff⇒اعمال⇒بازگردانی) قابلِ تست باشد."""
    name = 'mock'

    def complete(self, system, user, json_mode=True):
        if not json_mode:
            return 'OK'
        try:
            req = json.loads(user)
        except ValueError:
            req = {}
        task = req.get('task', '')
        instr = (req.get('instruction') or '')[:80]
        mark = '\n<!-- mock edit: %s -->' % instr

        if task == 'shell':
            return json.dumps({
                'summary': '[آزمایشی] هدر و فوترِ ساده با منو و سبد',
                'header': '<header class="site-header"><div class="wrap"><a class="brand" href="/">{{ SITE_TITLE }}</a>'
                          '<nav class="main-nav">{% for title, href in MENU %}<a href="{{ href }}">{{ title }}</a>{% endfor %}</nav>'
                          '<a class="cart-link" href="/cart/">سبد{% if cart|length %}<span class="badge">{{ cart|length }}</span>{% endif %}</a></div></header>',
                'footer': '<footer class="site-footer"><div class="wrap"><p class="copy">© {{ SITE_TITLE }} — ساخته با استودیو (آزمایشی)</p></div></footer>',
                'theme_css': ':root { --brand: #7c3aed; }\n.site-header { border-bottom: 3px solid var(--brand); } /* mock theme */',
            }, ensure_ascii=False)
        if task == 'page':
            slug = req.get('slug') or ''
            return json.dumps({
                'summary': '[آزمایشی] بدنهٔ تازه برای /%s' % slug,
                'body_html': '<section class="section"><div class="wrap"><h1>{{ SITE_TITLE }} — %s</h1>'
                             '<p class="muted">این بدنه را Providerِ آزمایشی ساخته است.</p></div></section>' % (slug or 'خانه'),
                'css': '/* mock */',
            }, ensure_ascii=False)
        if task in ('edit_page', 'edit_view'):
            return json.dumps({'summary': '[آزمایشی] «%s» اعمال شد' % instr,
                               'body_html': (req.get('current_body') or '').rstrip() + mark,
                               'css': None}, ensure_ascii=False)
        if task == 'edit_file':
            return json.dumps({'summary': '[آزمایشی] «%s»' % instr,
                               'content': (req.get('current') or '').rstrip() + mark}, ensure_ascii=False)
        if task == 'samples':
            return json.dumps({'summary': '[آزمایشی] دادهٔ نمونه', 'categories': [
                {'name': 'دستهٔ یک', 'slug': 'cat-one'}, {'name': 'دستهٔ دو', 'slug': 'cat-two'}],
                'products': [{'name': 'محصولِ نمونه %d' % i, 'slug': 'sample-%d' % i, 'description': 'توضیحِ نمونه.',
                              'price': 100000 * i, 'stock': 5, 'category': 'cat-one' if i % 2 else 'cat-two'}
                             for i in range(1, 5)]}, ensure_ascii=False)
        if task == 'edit_shared':
            cur = req.get('current') or ''
            if req.get('kind') == 'base_css':
                return json.dumps({'summary': '[آزمایشی] «%s»' % instr,
                                   'css': '/* mock edit: %s */\n.site-footer { padding-top: 40px; }' % instr}, ensure_ascii=False)
            return json.dumps({'summary': '[آزمایشی] «%s»' % instr, 'content': cur.rstrip() + mark}, ensure_ascii=False)
        if task == 'suggest_models':
            return json.dumps({
                'summary': '[آزمایشی] یک اپِ نظرات با مدلِ Review',
                'apps': [{'name': 'reviews', 'verbose': 'نظرات', 'models': [{
                    'name': 'Review', 'verbose': 'نظر', 'verbose_plural': 'نظرها',
                    'fields': [
                        {'name': 'author', 'verbose': 'نویسنده', 'type': 'CharField', 'max_length': 80},
                        {'name': 'text', 'verbose': 'متن', 'type': 'TextField'},
                        {'name': 'rating', 'verbose': 'امتیاز', 'type': 'PositiveIntegerField', 'default': '5'},
                        {'name': 'created_at', 'verbose': 'تاریخ', 'type': 'DateTimeField', 'auto_now_add': True},
                    ]}]}]}, ensure_ascii=False)
        return json.dumps({'summary': 'mock', 'result': 'ok'}, ensure_ascii=False)


class RoutedProvider(BaseProvider):
    """اول Qwen Coder روی سرورِ پردازش، بعد همان سرویسِ تنظیم‌شده (Metis). services/ai/routing.py"""
    name = 'routed'

    def __init__(self, cfg):
        super().__init__(cfg)
        from services.ai.routing import StudioRouted
        self.direct = OpenAIProvider(cfg)
        self.router = StudioRouted(self.direct)

    def complete(self, system, user, json_mode=True):
        return self.router.complete(system, user, json_mode=json_mode, max_tokens=self.cfg.max_tokens, temperature=self.cfg.temperature)

    @property
    def answered_by(self):
        return self.router.answered_by

    @property
    def fell_back(self):
        return self.router.fell_back

    @property
    def fallback_reason(self):
        return self.router.fallback_reason

    def list_models(self, limit=30):
        return self.direct.list_models(limit)


def get_provider(cfg=None, direct=False):
    """direct=True: همان سرویسِ تنظیم‌شده بی‌مسیریابی (دکمهٔ «آزمونِ اتصال» نباید چند دقیقه منتظرِ گره بماند)."""
    from services.ai import routing
    from .models import AiSettings
    cfg = cfg or AiSettings.get()
    if cfg.provider == 'mock':
        return MockProvider(cfg)
    if not direct and routing.wants_node():
        return RoutedProvider(cfg)
    return OpenAIProvider(cfg)
