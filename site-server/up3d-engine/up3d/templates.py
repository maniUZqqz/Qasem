"""قالب‌های قاعده‌محور: از «خلاصهٔ کار» (brief) بی‌نیاز به هوشِ مصنوعی یک سندِ صحنهٔ معتبر می‌سازند.
کارگردانِ AI هم وقتی مدل در دسترس نیست یا خروجی‌اش رد شد، به همین‌ها برمی‌گردد.

هر قالب «ضرب‌ها» (beats) را پشتِ سرِ هم می‌چیند؛ طولِ هر ضرب = بیشینهٔ (حرکت‌ها، گفتار)،
پس متنِ بلندتر خودبه‌خود جای بیشتری می‌گیرد و هم‌پوشانی پیش نمی‌آید.
"""
import re

from . import scene as S
from .assets import registry

TEMPLATES = {
    'showcase': {'fa': 'معرفیِ کاملِ محصول (برداشتن، نشان‌دادن، گذاشتن)', 'en': 'Full product showcase'},
    'quick': {'fa': 'تبلیغِ کوتاه (اشاره به محصول روی میز)', 'en': 'Quick promo'},
    'testimonial': {'fa': 'توصیهٔ صمیمی (دست روی سینه)', 'en': 'Testimonial'},
    'ritual': {'fa': 'آیینِ استفاده (برداشتن، استفاده، نشان‌دادن)', 'en': 'Usage ritual'},
    'product_only': {'fa': 'فقط محصول با صدای راوی', 'en': 'Product only, voice-over'},
}


def _sentences(text):
    parts = [p.strip() for p in re.split(r'[.!؟?\n]+', text or '') if len(p.strip()) > 3]
    return parts


def _brief_defaults(brief, reg):
    b = dict(brief or {})
    b.setdefault('product_name', b.get('name') or 'محصولِ ما')
    b.setdefault('product_asset', reg.default('product').id)
    b.setdefault('environment', reg.default('environment').id)
    b.setdefault('character', reg.default('character').id)
    ch = reg.get('character', b['character'])
    gender = (ch or {}).get('gender', 'female')
    if not b.get('voice'):
        b['voice'] = 'fa_female_nova' if gender == 'female' else 'fa_male_onyx'
    b.setdefault('aspect', '9:16')
    b.setdefault('cta', 'همین حالا از آپ‌مارکت سفارش بدید!')
    benefits = b.get('benefits') or []
    if isinstance(benefits, str):
        benefits = _sentences(benefits)
    if not benefits:
        benefits = _sentences(b.get('description', ''))[:2]
    if not benefits:
        benefits = ['کیفیتی که از اولین لحظه حسش می‌کنید', 'انتخابی مطمئن برای هر روزِ شما']
    b['benefits'] = benefits
    return b


class _Beats:
    def __init__(self, doc, reg, actor, pid, voice):
        self.doc, self.reg, self.actor, self.pid, self.voice = doc, reg, actor, pid, voice
        self.t = 0.25

    def beat(self, motions=(), text=None, shot=None, subject=None, move=None, min_len=0.0, text_delay=0.15):
        t0 = self.t
        mt = t0
        for m in motions:
            mid, params = (m, {}) if isinstance(m, str) else m
            ma = self.reg.get('motion', mid)
            d = ma['duration']['default'] if ma else 1.5
            if mid in ('talk', 'idle') and text:
                d = max(ma['duration']['min'], S.estimate_speech_seconds(text) - (mt - t0) + 0.2)
                d = min(d, ma['duration']['max'])
            self.doc['actions'].append({'actor': self.actor, 'motion': mid, 'start': round(mt, 3), 'duration': round(d, 3),
                                        'params': params})
            if not (ma and ma.get('layer')):
                mt += d + 0.05
        st = 0.0
        if text:
            sp = {'actor': self.actor, 'text': text, 'start': round(t0 + text_delay, 3), 'voice': self.voice}
            self.doc['speech'].append(sp)
            st = text_delay + S.estimate_speech_seconds(text) + 0.25
        end = max(mt, t0 + st, t0 + min_len)
        if shot:
            self.doc['shots'].append({'shot': shot, 'start': round(t0 if self.doc['shots'] else 0.0, 3),
                                      'subject': subject or self.actor or self.pid, 'move': move or 'static', 'params': {}})
        self.t = end
        return t0, end


def build(template, brief, reg=None):
    reg = reg or registry()
    b = _brief_defaults(brief, reg)
    doc = S.new_scene(title=b['product_name'], duration=30, aspect=b['aspect'])
    doc['meta'].update({'source': 'template:' + template, 'brief': brief or {}})
    env = reg.get('environment', b['environment'])
    doc['environment'] = {'id': env.id, 'params': b.get('environment_params', {})}
    doc['lighting'] = {'id': b.get('lighting') or env.get('default_lighting') or reg.default('lighting').id, 'params': {}}
    surfaces = list(env['surfaces'])
    pid = 'p1'
    prod_params = {k: b[k] for k in ('brand', 'tagline', 'label_image', 'label_color', 'liquid_color', 'cap_color',
                                     'box_color', 'can_color', 'model_path') if b.get(k)}
    prod_params.update(b.get('product_params') or {})
    doc['products'].append({'id': pid, 'asset': b['product_asset'], 'name': b['product_name'],
                            'surface': b.get('surface') or surfaces[0], 'params': prod_params})
    name = b['product_name']
    ben = b['benefits']
    actor = None
    if template != 'product_only':
        actor = 'host'
        doc['actors'].append({'id': actor, 'character': b['character'], 'mark': 'center',
                              'params': b.get('character_params', {})})
    bt = _Beats(doc, reg, actor, pid, b['voice'])
    P = {'product': pid}
    if template == 'showcase':
        bt.beat(['wave_hello'], 'سلام! با %s آشنا بشید.' % name, 'medium', move='push_in')
        bt.beat([('pick_up', P), ('present', P)], ben[0] + '.', 'medium_close', move='static')
        bt.beat([('rotate_show', P)], (ben[1] + '.') if len(ben) > 1 else None, 'product_macro', subject=pid, move='orbit_left',
                min_len=2.2)
        bt.beat([('put_down', P), ('point_at', {'target': 'product'})], b['cta'], 'medium', move='pull_out')
        bt.beat(['thumbs_up'], None, None, min_len=1.2)
    elif template == 'quick':
        bt.beat(['talk'], 'این %s رو از دست ندید!' % name, 'medium', move='push_in')
        bt.beat([('point_at', {'target': 'product'})], ben[0] + '.', 'product_hero', subject=pid, move='push_in', min_len=2.0)
        bt.beat(['talk', 'thumbs_up'], b['cta'], 'medium_close', move='static')
    elif template == 'testimonial':
        bt.beat(['hand_on_chest'], 'من خودم %s رو امتحان کردم.' % name, 'medium_close', move='push_in')
        bt.beat([('pick_up', P), ('present', P)], ben[0] + '.', 'medium', move='static')
        bt.beat(['talk'], (ben[1] + '.') if len(ben) > 1 else 'واقعاً راضی‌ام.', 'product_macro', subject=pid, move='orbit_right')
        bt.beat([('put_down', P), 'thumbs_up'], b['cta'], 'medium', move='pull_out')
    elif template == 'ritual':
        bt.beat([('pick_up', P)], 'هر روز صبح با %s.' % name, 'medium', move='push_in')
        use = 'spray' if b['product_asset'] == 'perfume_bottle' else 'rotate_show'
        bt.beat([(use, P)], ben[0] + '.', 'medium_close', move='static')
        bt.beat([('present', P)], (ben[1] + '.') if len(ben) > 1 else None, 'product_macro', subject=pid, move='push_in', min_len=2.0)
        bt.beat([('put_down', P), 'thumbs_up'], b['cta'], 'medium', move='pull_out')
    else:   # product_only
        bt.beat([], '%s.' % name, 'product_hero', subject=pid, move='push_in', min_len=2.5)
        bt.beat([], ben[0] + '.', 'product_macro', subject=pid, move='orbit_left', min_len=2.5)
        bt.beat([], b['cta'], 'product_hero', subject=pid, move='crane_down', min_len=2.5)
    dur = round(bt.t + 0.6, 2)
    doc['output']['duration'] = dur
    doc['overlays'].append({'type': 'title', 'text': name, 'start': 0.4, 'duration': min(3.0, dur / 3), 'position': 'top'})
    if b.get('price'):
        doc['overlays'].append({'type': 'price', 'text': str(b['price']), 'start': round(dur * 0.45, 2), 'duration': 2.5})
    doc['overlays'].append({'type': 'cta', 'text': b.get('cta_short') or 'سفارش در آپ‌مارکت', 'start': round(max(0, dur - 3.0), 2),
                            'duration': 2.9})
    if b.get('music'):
        doc['audio']['music'] = b['music']
    from .validate import repair
    doc, changes, rep = repair(doc, reg)
    doc['meta']['repairs'] = changes
    return doc
