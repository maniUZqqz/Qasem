"""قالب‌های تبلیغاتیِ آماده (موتورِ ۱٫۳): بی‌مجری، بی‌صدای راوی، با استیجِ محصول، نورِ حرفه‌ای و دوربینِ سینمایی.

هر قالب از «خلاصهٔ کار» (brief) یک سندِ صحنهٔ معتبر می‌سازد؛ فقط از چیزهایی که در brief آمده نوشته می‌گذارد (نام، شعار، دعوت به خرید).
هیچ قیمت، آمار یا ادعایی از خودش نمی‌نویسد.

  turntable      چرخ‌میزِ محصول: محصول روی پایه ۳۶۰ درجه می‌چرخد، نورِ سافت‌باکس، نمای نزدیک در پایان
  hero_reveal    آشکارسازیِ قهرمان: از زاویهٔ پایین و نزدیک شروع، با محو از تاریکی عقب می‌کشد و دورِ محصول می‌چرخد
  app_showcase   نمایشِ اپلیکیشن: گوشی با اسکرین‌شاتِ اپ (یا صفحه‌های نمونهٔ برند)، حرکتِ کمانی، برشِ خودکارِ صفحه‌ها
  logo_reveal    آشکارسازیِ لوگو یا نامِ برندِ سه‌بعدی (فارسی/لاتین) با جنسِ دلخواه
  neon_launch    معرفیِ نئونیِ شبانه: استیجِ تاریک، لولهٔ نئون، بازتابِ رنگی روی کفِ آینه‌ای
  golden_hour    قهرمانِ ساعتِ طلایی: آسمانِ فیزیکیِ غروب، نورِ زرین از پشتِ محصول
  material_trio  سه متریالِ واقعی (طلا، کروم، شیشه…) کنارِ هم برای معرفیِ جنس/رنگ‌بندی
"""
import copy

from . import scene as S

AD_TEMPLATES = {
    'turntable': {'fa': 'چرخ‌میزِ محصول (چرخشِ ۳۶۰ درجه)', 'en': 'Product turntable',
                  'hint': 'محصول روی پایه می‌چرخد؛ نورِ استودیویی و یک نمای نزدیک. محصول، نام و شعار را از خلاصه می‌گیرد.'},
    'hero_reveal': {'fa': 'آشکارسازیِ قهرمانِ محصول', 'en': 'Hero reveal',
                    'hint': 'شروعِ نزدیک و کم‌عمق، عقب‌کشیدن از تاریکی تا نمای قهرمان و چرخشِ آرامِ دوربین.'},
    'app_showcase': {'fa': 'نمایشِ اپلیکیشن روی گوشی', 'en': 'App showcase', 'asset': 'phone_showcase', 'inputs': ['screens', 'brand_colors'],
                     'hint': 'گوشی با اسکرین‌شاتِ اپ؛ تا چهار تصویر بدهید. اگر ندادید، صفحه‌های نمونه با رنگ و نوشتهٔ برندِ شما ساخته می‌شود.'},
    'logo_reveal': {'fa': 'آشکارسازیِ لوگو / نامِ برندِ سه‌بعدی', 'en': '3D logo reveal', 'asset': 'logo_3d', 'inputs': ['logo', 'brand_colors'],
                    'hint': 'لوگو (PNG/JPG) یا نامِ برند به‌صورتِ سه‌بعدی؛ فارسی با حروفِ چسبیده درست نوشته می‌شود.'},
    'neon_launch': {'fa': 'معرفیِ نئونیِ شبانه', 'en': 'Neon launch',
                    'hint': 'استیجِ تاریک با لولهٔ نئون و بازتابِ رنگی؛ برای محصولِ جوان‌پسند.'},
    'golden_hour': {'fa': 'قهرمانِ ساعتِ طلایی', 'en': 'Golden hour hero',
                    'hint': 'محصول زیرِ آسمانِ غروب با نورِ گرمِ پشتی؛ حسِ برندِ لوکس و طبیعی.'},
    'material_trio': {'fa': 'سه متریالِ واقعی (طلا، کروم، شیشه)', 'en': 'Material trio', 'asset': 'material_object',
                      'hint': 'سه جسمِ نمایشیِ PBR کنارِ هم؛ برای نشان‌دادنِ جنس و رنگ‌بندی.'},
}

#: فریمِ عمودیِ ۹:۱۶ و … ⇒ نسبتِ پهنا به ارتفاع
ASPECT_WH = {'9:16': 9 / 16, '16:9': 16 / 9, '1:1': 1.0, '4:5': 4 / 5}

#: بیشینهٔ نسبتِ پهنا به ارتفاعِ نوشتهٔ سه‌بعدی در هر قاب؛ نوشتهٔ پهن‌تر خودکار چندخطی می‌شود (در قابِ عمودی یک خطِ بلند ریز و کفِ قاب می‌افتاد)
TEXT_WRAP_RATIO = {'9:16': 2.6, '4:5': 3.2, '1:1': 3.8, '16:9': 6.0}

LOOKS = {
    'turntable': {'exposure': -0.55, 'look': 'agx', 'bloom': 0.25, 'vignette': 0.12, 'fade_in': 0.5, 'fade_out': 0.6, 'motion_blur': True, 'shutter': 0.4},
    'hero_reveal': {'exposure': -0.55, 'look': 'agx_contrast', 'bloom': 0.35, 'vignette': 0.22, 'fade_in': 1.0, 'fade_out': 0.6, 'motion_blur': True,
                    'shutter': 0.45, 'dof_strength': 1.25},
    'app_showcase': {'exposure': -0.55, 'look': 'agx', 'bloom': 0.3, 'vignette': 0.1, 'fade_in': 0.4, 'fade_out': 0.6, 'motion_blur': True, 'shutter': 0.4},
    'logo_reveal': {'exposure': -0.55, 'look': 'agx_contrast', 'bloom': 0.3, 'vignette': 0.2, 'fade_in': 0.8, 'fade_out': 0.6, 'motion_blur': True, 'shutter': 0.4},
    'neon_launch': {'look': 'agx_punchy', 'bloom': 1.0, 'vignette': 0.3, 'fade_in': 0.6, 'fade_out': 0.6, 'motion_blur': True, 'shutter': 0.5,
                    'handheld': 0.12},
    'golden_hour': {'look': 'agx_golden', 'bloom': 0.45, 'vignette': 0.18, 'fade_in': 0.8, 'fade_out': 0.8, 'motion_blur': True, 'shutter': 0.4},
    'material_trio': {'exposure': -0.55, 'look': 'agx', 'bloom': 0.2, 'vignette': 0.12, 'fade_in': 0.5, 'fade_out': 0.5, 'motion_blur': True, 'shutter': 0.4},
}


def _s(v):
    return str(v).strip() if v is not None else ''


def _brief(brief, template, reg):
    b = dict(brief or {})
    b['product_name'] = _s(b.get('product_name') or b.get('name') or b.get('brand')) or 'محصولِ ما'
    b.setdefault('aspect', '9:16')
    b['brand'] = _s(b.get('brand'))
    b['tagline'] = _s(b.get('tagline'))
    b['cta'] = _s(b.get('cta_short') or b.get('cta'))
    ben = b.get('benefits') or []
    if isinstance(ben, str):
        ben = [x.strip() for x in ben.replace('\r', '').split('\n') if x.strip()]
    b['benefits'] = [x for x in (_s(x) for x in ben) if x]
    return b


def _dur(shots):
    return round(sum(s[2] for s in shots), 3)


class _Doc:
    def __init__(self, reg, b, template, env, env_params, lighting, light_params=None, look_extra=None):
        self.reg, self.b = reg, b
        self.doc = S.new_scene(title=b['product_name'], duration=10, aspect=b['aspect'])
        self.doc['meta'].update({'source': 'template:' + template, 'brief': {k: v for k, v in b.items() if k not in ('screens',)}})
        self.doc['environment'] = {'id': env, 'params': dict(env_params or {})}
        self.doc['lighting'] = {'id': lighting, 'params': dict(light_params or {})}
        look = dict(LOOKS[template])
        if b.get('look'):
            look['look'] = b['look']
        look.update(look_extra or {})
        self.doc['render'] = look
        self.t = 0.0

    def product(self, asset, params=None, surface='platform', name=None, pid=None):
        pid = pid or 'p%d' % (len(self.doc['products']) + 1)
        self.doc['products'].append({'id': pid, 'asset': asset, 'name': name if name is not None else self.b['product_name'],
                                     'surface': surface, 'params': dict(params or {})})
        return pid

    def hscale(self, asset, base=0.13):
        a = self.reg.get('product', asset)
        h = (a.get('dimensions') or [0, 0, base])[2] if a else base
        return min(3.0, max(0.85, h / base))

    def shot(self, shot_id, dur, subject, move='static', scale=None, **params):
        sa = self.reg.get('shot', shot_id)
        if scale and scale != 1.0 and 'height' not in params and sa:
            params['height'] = round(sa['framing']['height'] * scale, 3)
        self.doc['shots'].append({'shot': shot_id, 'start': round(self.t, 3), 'duration': round(dur, 3), 'subject': subject, 'move': move,
                                  'params': params})
        self.t += dur

    def finish(self, title=True, tagline=True, cta=True):
        dur = round(self.t, 2)
        self.doc['output']['duration'] = dur
        ov = self.doc['overlays']
        b = self.b
        if title:
            ov.append({'type': 'title', 'text': b['brand'] or b['product_name'], 'start': 0.5, 'duration': min(3.2, dur * 0.34), 'position': 'top'})
        if tagline and b['tagline']:
            ov.append({'type': 'subtitle', 'text': b['tagline'], 'start': round(min(dur - 3.4, dur * 0.35), 2), 'duration': min(3.0, dur * 0.3)})
        if cta and b['cta']:
            ov.append({'type': 'cta', 'text': b['cta'], 'start': round(max(0.0, dur - 3.0), 2), 'duration': 2.9})
        if b.get('price'):
            ov.append({'type': 'price', 'text': _s(b['price']), 'start': round(dur * 0.55, 2), 'duration': 2.4})
        if b.get('music'):
            self.doc['audio']['music'] = b['music']
        self.doc['audio']['subtitles'] = False
        return self.doc


def _product_params(b):
    out = {k: b[k] for k in ('brand', 'tagline', 'label_image', 'label_color', 'liquid_color', 'cap_color', 'box_color', 'can_color',
                             'model_path') if b.get(k)}
    out.update(b.get('product_params') or {})
    return out


def _default_asset(b, reg):
    return b.get('product_asset') or reg.default('product').id


def build_ad(template, brief, reg):
    b = _brief(brief, template, reg)
    fn = {'turntable': _turntable, 'hero_reveal': _hero_reveal, 'app_showcase': _app_showcase, 'logo_reveal': _logo_reveal,
          'neon_launch': _neon_launch, 'golden_hour': _golden_hour, 'material_trio': _material_trio}[template]
    doc = fn(b, reg)
    from .validate import repair
    doc, changes, rep = repair(doc, reg)
    doc['meta']['repairs'] = changes
    return doc


# ───────────────────────────────────────── the templates

def _turntable(b, reg):
    d = _Doc(reg, b, 'turntable', 'stage', {}, b.get('lighting') or 'studio_softbox')
    asset = _default_asset(b, reg)
    pid = d.product(asset, _product_params(b))
    k = d.hscale(asset)
    d.shot('stage_wide', 2.4, pid, 'reveal_pull', k, move_amount=0.6)
    d.shot('stage_hero', 6.6, pid, 'turntable', k, turn_deg=360, turn_dir='left', spin_ease='smooth')
    d.shot('stage_macro', 2.8, pid, 'drift', k)
    return d.finish()


def _hero_reveal(b, reg):
    d = _Doc(reg, b, 'hero_reveal', 'stage', {'floor_gloss': 0.6}, b.get('lighting') or 'three_point')
    asset = _default_asset(b, reg)
    pid = d.product(asset, _product_params(b))
    k = d.hscale(asset)
    d.shot('stage_low', 4.6, pid, 'reveal_pull', k)
    d.shot('stage_hero', 4.4, pid, 'hero_orbit', k)
    d.shot('stage_hero', 3.0, pid, 'dolly_zoom', k)
    return d.finish()


def _screens(b, reg):
    shots = [x for x in (b.get('screens') or []) if x][:4]
    if shots:
        return shots
    from . import screens as SC
    return SC.make_screens(b['brand'] or b['product_name'], b['tagline'], b['benefits'][:4], b.get('brand_color') or '#126F85',
                           b.get('brand_color_2') or '#163F75', b.get('logo_image'), count=3)


def _app_showcase(b, reg):
    d = _Doc(reg, b, 'app_showcase', 'stage', {'floor_gloss': 0.35, 'backdrop_color': b.get('backdrop_color') or '#a5afbd'},
             b.get('lighting') or 'studio_softbox')
    prm = {'screen_image' + ('' if i == 0 else '_%d' % (i + 1)): p for i, p in enumerate(_screens(b, reg))}
    prm['screen_interval'] = float(b.get('screen_interval') or 2.6)
    prm.update(b.get('product_params') or {})
    pid = d.product('phone_showcase', prm, name=b['product_name'])
    d.shot('phone_angle', 3.6, pid, 'arc_right', arc_deg=15)          # the default 30 degrees ended at 54: grazing glass reflections wash the screen out
    d.shot('phone_front', 4.4, pid, 'push_in')
    d.shot('phone_angle', 3.6, pid, 'hero_orbit', move_amount=0.6)
    return d.finish()


def _width_for(aspect, W, fill=0.8):
    """ارتفاعِ قابِ دیدنی که نوشته‌ای به پهنای W متر در عرضِ قاب جا شود (fill = سهمِ عرض)."""
    return round(W / fill / ASPECT_WH.get(aspect, 9 / 16), 3)


def _logo_reveal(b, reg):
    W = float(b.get('logo_width_m') or 0.46)
    env_params = {'floor_gloss': 0.5, 'platform_radius': round(max(0.24, W * 0.78), 3)}
    d = _Doc(reg, b, 'logo_reveal', 'stage', env_params, b.get('lighting') or 'studio_softbox')
    color = b.get('brand_color')
    if b.get('logo_image'):
        asset = 'logo_3d'
        prm = {'logo_image': b['logo_image'], 'width_m': W, 'depth_m': 0.045, 'finish': b.get('finish') or 'white_gloss'}
    else:
        asset = 'text_3d'
        prm = {'text': b['brand'] or b['product_name'], 'width_m': W, 'depth_m': 0.05, 'finish': b.get('finish') or 'gold',
               'wrap_ratio': TEXT_WRAP_RATIO.get(b['aspect'], 4.5)}
        if b['tagline'] and b.get('tagline_3d'):
            prm['text'] += '\n' + b['tagline']
    if color and not b.get('finish_keep_default'):
        prm.update({'use_color': True, 'color': color})
    prm.update(b.get('product_params') or {})
    pid = d.product(asset, prm, name=b['brand'] or b['product_name'])
    H = _width_for(b['aspect'], W)
    d.shot('logo_front', 4.2, pid, 'reveal_pull', height=H)
    d.shot('logo_front', 4.4, pid, 'arc_left', height=H)
    d.shot('logo_front', 3.2, pid, 'dolly_zoom', height=H)
    return d.finish(title=False)


def _neon_launch(b, reg):
    d = _Doc(reg, b, 'neon_launch', 'neon_stage',
             {k: v for k, v in (('accent_color', b.get('accent_color')), ('accent_color_2', b.get('accent_color_2'))) if v},
             b.get('lighting') or 'neon_night')
    asset = _default_asset(b, reg)
    pid = d.product(asset, _product_params(b))
    k = d.hscale(asset)
    d.shot('stage_wide', 3.0, pid, 'drift', k)
    d.shot('stage_low', 3.6, pid, 'push_in', k)
    d.shot('stage_hero', 4.4, pid, 'turntable', k, turn_deg=360, turn_dir='right', spin_ease='smooth')
    d.shot('stage_macro', 2.6, pid, 'handheld', k)
    return d.finish()


def _golden_hour(b, reg):
    d = _Doc(reg, b, 'golden_hour', 'open_air', {}, b.get('lighting') or 'golden_hour')
    asset = _default_asset(b, reg)
    pid = d.product(asset, _product_params(b))
    k = d.hscale(asset)
    d.shot('stage_low', 4.0, pid, 'push_in', k)
    d.shot('stage_hero', 4.6, pid, 'hero_orbit', k)
    d.shot('stage_wide', 3.2, pid, 'pull_out', k)
    return d.finish()


def _material_trio(b, reg):
    d = _Doc(reg, b, 'material_trio', 'stage', {'floor_gloss': 0.75}, b.get('lighting') or 'studio_softbox')
    fin = list(b.get('finishes') or ['gold', 'chrome', 'glass'])[:3]
    while len(fin) < 3:
        fin.append(['gold', 'chrome', 'glass'][len(fin)])
    shape = b.get('shape') or 'sphere'
    ids = []
    for f, surf in zip(fin, ('platform_left', 'platform', 'platform_right')):
        ids.append(d.product('material_object', {'shape': shape, 'size_m': 0.1, 'finish': f}, surface=surf, name=f))
    d.shot('stage_wide', 3.2, ids[1], 'reveal_pull', height=0.5)
    d.shot('stage_hero', 3.8, ids[1], 'arc_left', height=0.46)
    d.shot('stage_macro', 3.0, ids[0], 'drift', height=0.18)
    d.shot('stage_macro', 3.0, ids[2], 'drift', height=0.18)
    return d.finish()
