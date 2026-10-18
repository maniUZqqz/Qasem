"""کارگردانِ هوشِ مصنوعی.

مدلِ زبانی فقط «سندِ صحنه» می‌نویسد (JSON) و فقط از دارایی‌های دفتر (catalog). بعد:
  نرمال‌سازی ⇐ ترمیمِ خودکار ⇐ اگر هنوز خطا هست، خطاها به مدل برمی‌گردد (یک بارِ دیگر) ⇐ اگر نشد، قالبِ قاعده‌محور.
پس خروجیِ این ماژول همیشه یک سندِ معتبر است، با گزارشِ این‌که از کجا آمد.

اتصال با کتابخانهٔ رسمیِ openai به هر سرویسِ سازگار (Metis، OpenAI، …)؛ base_url/کلید/مدل از تنظیماتِ پنل.
"""
import json
import re
import time

from . import scene as S
from . import templates
from .assets import registry
from .validate import repair, validate

SYSTEM = """You are the film director of "UpMarket 3D", an engine that renders realistic 3D advertising videos
(Blender) for an Iranian e-commerce marketplace. You do NOT animate; you write a SCENE DOCUMENT (JSON) that the
engine validates and executes. Use ONLY the asset ids in the catalog. All spoken lines and on-screen texts are
in natural, warm, persuasive PERSIAN (Farsi), short (max ~12 words per spoken line), no English.

SCENE DOCUMENT FORMAT (times in seconds):
{
 "format": "up3d.scene/1",
 "meta": {"title": "<short Persian title>"},
 "output": {"aspect": "9:16"|"16:9"|"1:1"|"4:5", "fps": 24, "duration": <seconds>},
 "environment": {"id": <environment id>, "params": {}},
 "lighting": {"id": <lighting id>, "params": {}},
 "actors": [{"id": "host", "character": <character id>, "mark": <one of the environment marks>}],
 "products": [{"id": "p1", "asset": <product id>, "name": "<product name>", "surface": <one of the environment surfaces>,
               "params": {"brand": "...", "tagline": "...", "liquid_color": "#rrggbb", ...}}],
 "actions": [{"actor": "host", "motion": <motion id>, "start": s, "duration": s, "params": {"product": "p1"}}],
 "speech": [{"actor": "host", "text": "<Persian line>", "start": s, "voice": <voice id>}],
 "expressions": [{"actor": "host", "expression": "smile|big_smile|warm|surprised|thinking|confident|wink|neutral", "start": s, "duration": s, "intensity": 0.7}],
 "gaze": [{"actor": "host", "target": "camera|forward|product:p1", "start": s, "duration": s}],
 "shots": [{"shot": <shot id>, "start": s, "duration": s, "subject": "host"|"p1", "move": <one of the shot's moves>}],
 "overlays": [{"type": "title|cta|price|badge", "text": "<Persian>", "start": s, "duration": s}],
 "audio": {"subtitles": true}
}

HARD RULES (the validator rejects violations):
- Body motions of one actor must not overlap in time (LAYER motions like nod/look_at may overlap).
- Durations must be within each motion's min/max.
- A product must be picked up (pick_up) before present / rotate_show / spray / put_down, and put down only if held.
- Shots must cover 0..duration with no gaps/overlaps; product shots (subject product id) only use shots whose subject is product.
- Spoken lines of one actor must not overlap; Persian TTS speaks ~13 characters per second; leave time.
- Everything must end before output.duration. Typical ad: 10-15 seconds, 3-5 shots, 3-4 short spoken lines.
GOOD DIRECTION:
- Open with a greeting (wave_hello) in a medium shot, then pick_up + present in medium_close, cut to product_macro on the product
  while it is held (rotate_show), end with put_down/point_at/thumbs_up and a call to action. Put "talk" under spoken lines
  when hands are free. Use expressions for emotion. Cut on actions. Match voice gender to the character.
Return ONLY the JSON object."""


class DirectorError(Exception):
    pass


def _client(settings):
    try:
        from openai import OpenAI
    except ImportError as e:
        raise DirectorError('کتابخانهٔ openai نصب نیست') from e
    if not settings.get('api_key'):
        raise DirectorError('کلیدِ API تنظیم نشده')
    return OpenAI(api_key=settings['api_key'], base_url=settings.get('base_url') or None,
                  timeout=float(settings.get('timeout', 120)), max_retries=1)


def _chat(settings, messages):
    client = _client(settings)
    kw = {'model': settings.get('model') or 'gpt-4o-mini', 'messages': messages}
    temp = settings.get('temperature', 0.7)
    attempts = [dict(kw, response_format={'type': 'json_object'}, temperature=temp), dict(kw, temperature=temp), kw]
    last = None
    for a in attempts:
        try:
            r = client.chat.completions.create(**a)
            return r.choices[0].message.content or '', getattr(r, 'usage', None)
        except Exception as e:   # بعضی مدل‌ها response_format یا temperature را نمی‌پذیرند
            last = e
            msg = str(e).lower()
            if 'auth' in msg or '401' in msg or 'quota' in msg:
                break
    raise DirectorError('مدل پاسخ نداد: %s' % str(last)[:300])


def _extract_json(text):
    text = text.strip()
    m = re.search(r'```(?:json)?\s*(\{.*\})\s*```', text, re.S)
    if m:
        text = m.group(1)
    i, j = text.find('{'), text.rfind('}')
    if i < 0 or j < 0:
        raise DirectorError('خروجیِ مدل JSON نبود')
    return json.loads(text[i:j + 1])


def _brief_text(brief):
    b = dict(brief or {})
    lines = []
    for k, label in (('request', 'Request'), ('product_name', 'Product name'), ('product_asset', 'Product shape asset'),
                     ('description', 'Product description'), ('benefits', 'Key benefits'), ('price', 'Price'),
                     ('cta', 'Call to action'), ('brand', 'Brand'), ('tone', 'Tone'), ('audience', 'Audience'),
                     ('duration', 'Target duration (s)'), ('aspect', 'Aspect'), ('character', 'Preferred character'),
                     ('environment', 'Preferred environment'), ('voice', 'Preferred voice')):
        if b.get(k):
            v = b[k]
            lines.append('%s: %s' % (label, ', '.join(v) if isinstance(v, list) else v))
    return '\n'.join(lines) or 'Make a 12 second ad.'


def plan(brief, settings, reg=None, log=print):
    """خلاصهٔ کار ⇐ سندِ صحنهٔ معتبر. خروجی: (doc, info)"""
    reg = reg or registry()
    info = {'source': 'ai', 'model': settings.get('model'), 'attempts': [], 'repairs': []}
    example = templates.build('showcase', {'product_name': 'نمونه'}, reg)
    for k in ('meta',):
        example.pop(k, None)
    messages = [
        {'role': 'system', 'content': SYSTEM},
        {'role': 'user', 'content': 'CATALOG:\n%s\n\nEXAMPLE (valid, adapt it — do not copy texts):\n%s\n\nBRIEF:\n%s' % (
            reg.catalog_for_ai(), json.dumps(example, ensure_ascii=False), _brief_text(brief))},
    ]
    t0 = time.time()
    for attempt in range(2):
        try:
            raw, usage = _chat(settings, messages)
        except DirectorError as e:
            info['attempts'].append({'error': str(e)})
            break
        try:
            doc = _extract_json(raw)
        except (ValueError, DirectorError) as e:
            info['attempts'].append({'error': 'JSON نامعتبر: %s' % e})
            messages += [{'role': 'assistant', 'content': raw[:4000]},
                         {'role': 'user', 'content': 'That was not valid JSON. Return ONLY the JSON object.'}]
            continue
        doc = _apply_brief(S.normalize(doc), brief, reg)
        doc, changes, rep = repair(doc, reg)
        info['attempts'].append({'errors_after_repair': len(rep.errors), 'repairs': len(changes),
                                 'tokens': getattr(usage, 'total_tokens', None)})
        info['repairs'] = changes
        if rep.ok:
            doc['meta'].update({'source': 'ai', 'model': settings.get('model'), 'brief': brief or {},
                                'repairs': changes, 'seconds': round(time.time() - t0, 1)})
            info['seconds'] = round(time.time() - t0, 1)
            return doc, info
        errs = '\n'.join('- %s: %s' % (i['path'], i['message']) for i in rep.errors[:12])
        messages += [{'role': 'assistant', 'content': raw[:6000]},
                     {'role': 'user', 'content': 'The validator found these errors, fix them and return the full JSON again:\n' + errs}]
        log('کارگردان: %d خطا ماند؛ دوباره از مدل' % len(rep.errors))
    info['source'] = 'template'
    info['fallback_reason'] = (info['attempts'][-1] if info['attempts'] else {}).get('error', 'خطای وارسی')
    doc = templates.build(brief.get('template', 'showcase') if brief else 'showcase', brief, reg)
    doc['meta']['ai_fallback'] = info['fallback_reason']
    return doc, info


def edit(doc, instruction, settings, reg=None):
    """ویرایشِ صحنه با زبانِ طبیعی («شاتِ دوم نزدیک‌تر باشد و لبخند بزند»). خروجی: (doc, info)"""
    reg = reg or registry()
    messages = [
        {'role': 'system', 'content': SYSTEM + '\nYou are EDITING an existing scene. Keep everything the user did not ask to change.'},
        {'role': 'user', 'content': 'CATALOG:\n%s\n\nCURRENT SCENE:\n%s\n\nCHANGE REQUEST (Persian):\n%s' % (
            reg.catalog_for_ai(), json.dumps(doc, ensure_ascii=False), instruction)},
    ]
    raw, usage = _chat(settings, messages)
    new = S.normalize(_extract_json(raw))
    new['meta'] = {**doc.get('meta', {}), **(new.get('meta') or {}), 'source': 'ai-edit'}
    new, changes, rep = repair(new, reg)
    if not rep.ok:
        raise DirectorError('ویرایش معتبر نشد: ' + '؛ '.join(i['message'] for i in rep.errors[:4]))
    return new, {'repairs': changes, 'diff': diff(doc, new), 'tokens': getattr(usage, 'total_tokens', None)}


def _apply_brief(doc, brief, reg):
    """چیزهایی که کاربر صریح خواسته بر حدسِ مدل برتری دارد (نامِ محصول، شکل، عکس، برند)."""
    b = brief or {}
    if doc.get('products'):
        p = doc['products'][0]
        if b.get('product_name'):
            p['name'] = b['product_name']
        if b.get('product_asset') and reg.get('product', b['product_asset']):
            p['asset'] = b['product_asset']
        for k in ('label_image', 'brand', 'model_path'):
            if b.get(k):
                p.setdefault('params', {})[k] = b[k]
        p['params'].update(b.get('product_params') or {})
    if b.get('aspect') in S.ASPECTS:
        doc['output']['aspect'] = b['aspect']
    if b.get('character') and doc.get('actors') and reg.get('character', b['character']):
        doc['actors'][0]['character'] = b['character']
    if b.get('environment') and reg.get('environment', b['environment']):
        doc['environment']['id'] = b['environment']
    if b.get('voice') and reg.get('voice', b['voice']):
        for sp in doc['speech']:
            sp['voice'] = b['voice']
    return doc


def diff(a, b):
    """خلاصهٔ تفاوتِ دو سند برای نمایش در پنل."""
    out = []
    for k in ('environment', 'lighting'):
        if (a.get(k) or {}).get('id') != (b.get(k) or {}).get('id'):
            out.append('%s: %s ⇐ %s' % (k, (a.get(k) or {}).get('id'), (b.get(k) or {}).get('id')))
    if a.get('output') != b.get('output'):
        out.append('خروجی: %s ⇐ %s' % (a.get('output'), b.get('output')))
    for t in S.TRACKS:
        x, y = a.get(t, []), b.get(t, [])
        if json.dumps(x, sort_keys=True, ensure_ascii=False) != json.dumps(y, sort_keys=True, ensure_ascii=False):
            out.append('%s: %d ⇐ %d مورد (تغییر کرد)' % (t, len(x), len(y)))
    return out
