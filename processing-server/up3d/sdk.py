"""ساختِ صحنه با کد (SDK).

    from up3d.sdk import Scene
    s = (Scene('عطر رز', duration=12)
         .environment('studio_warm').lighting('soft_beauty')
         .actor('host', 'presenter_f_01')
         .product('p1', 'perfume_bottle', name='رز', surface='table_right', brand='UpMarket')
         .at(0.2).do('host', 'wave_hello').say('host', 'سلام! عطرِ تازهٔ رز را ببینید.')
         .at(2.0).do('host', 'pick_up', product='p1').do('host', 'present', product='p1')
         .shot('medium', 0, move='push_in').shot('product_macro', 4.2, subject='p1')
         .overlay('title', 'عطر رز', 0.5, 3))
    s.validate()          # ایرادها
    s.render('preview')   # (اگر سرور/کارگر در دسترس است) یا s.save('scene.json')

هر متد همان سندِ صحنه را می‌سازد که AI و ویرایشگرِ گرافیکی می‌سازند.
"""
import json

from . import scene as S
from .assets import registry


class Scene:
    def __init__(self, title='', duration=12.0, aspect='9:16', fps=24, doc=None):
        self.doc = S.normalize(doc) if doc else S.new_scene(title, duration, aspect, fps)
        self._t = 0.0
        self._cursor = {}

    @classmethod
    def load(cls, path):
        with open(path, encoding='utf-8') as fh:
            return cls(doc=json.load(fh))

    # ── تنظیمِ صحنه
    def environment(self, env_id, **params):
        self.doc['environment'] = {'id': env_id, 'params': params}
        return self

    def lighting(self, light_id, **params):
        self.doc['lighting'] = {'id': light_id, 'params': params}
        return self

    def actor(self, aid, character, mark='center', **params):
        self.doc['actors'].append({'id': aid, 'character': character, 'mark': mark, 'params': params})
        return self

    def product(self, pid, asset, name='', surface=None, **params):
        self.doc['products'].append({'id': pid, 'asset': asset, 'name': name, 'surface': surface, 'params': params})
        return self

    # ── خطِ زمان
    def at(self, t):
        """زمانِ جاری (ثانیه) برای فرمان‌های بعدی."""
        self._t = float(t)
        return self

    def do(self, actor, motion, start=None, duration=None, **params):
        reg = registry()
        m = reg.get('motion', motion)
        st = self._cursor.get(actor, self._t) if start is None else float(start)
        st = max(st, self._t) if start is None else st
        d = duration or (m['duration']['default'] if m else 1.5)
        self.doc['actions'].append({'actor': actor, 'motion': motion, 'start': round(st, 3), 'duration': d,
                                    'params': params})
        if not (m and m.get('layer')):
            self._cursor[actor] = st + d + 0.05
        return self

    def say(self, actor, text, start=None, voice=None, style=None):
        it = {'actor': actor, 'text': text, 'start': self._t if start is None else float(start)}
        if voice:
            it['voice'] = voice
        if style:
            it['style'] = style
        self.doc['speech'].append(it)
        return self

    def voiceover(self, text, start=None, voice=None):
        return self.say(None, text, start, voice)

    def look(self, actor, target, start, duration):
        self.doc['gaze'].append({'actor': actor, 'target': target, 'start': start, 'duration': duration})
        return self

    def expression(self, actor, name, start, duration, intensity=0.7):
        self.doc['expressions'].append({'actor': actor, 'expression': name, 'start': start, 'duration': duration,
                                        'intensity': intensity})
        return self

    def shot(self, shot_id, start, duration=None, subject=None, move=None, **params):
        if subject is None:
            subject = self.doc['actors'][0]['id'] if self.doc['actors'] else self.doc['products'][0]['id']
        it = {'shot': shot_id, 'start': float(start), 'subject': subject, 'params': params}
        if duration:
            it['duration'] = duration
        if move:
            it['move'] = move
        self.doc['shots'].append(it)
        return self

    def overlay(self, kind, text, start, duration, **kw):
        self.doc['overlays'].append({'type': kind, 'text': text, 'start': start, 'duration': duration, **kw})
        return self

    def music(self, music_id_or_path, volume=0.14):
        self.doc['audio'].update({'music': music_id_or_path, 'music_volume': volume})
        return self

    # ── خروجی
    def finalize(self):
        """طولِ شات‌ها را تا شاتِ بعدی پر می‌کند و سند را مرتب می‌کند."""
        shots = sorted(self.doc['shots'], key=lambda s: s['start'])
        for a, b in zip(shots, shots[1:]):
            a.setdefault('duration', round(b['start'] - a['start'], 3))
        if shots:
            shots[-1].setdefault('duration', round(self.doc['output']['duration'] - shots[-1]['start'], 3))
        self.doc['shots'] = shots
        self.doc = S.normalize(self.doc)
        return self

    def validate(self, repair=False):
        from .validate import repair as rp, validate
        self.finalize()
        if repair:
            self.doc, changes, rep = rp(self.doc, registry())
            return rep.to_dict() | {'changes': changes}
        return validate(self.doc, registry()).to_dict()

    def to_dict(self):
        self.finalize()
        return self.doc

    def save(self, path):
        with open(path, 'w', encoding='utf-8') as fh:
            json.dump(self.to_dict(), fh, ensure_ascii=False, indent=1)
        return path

    def render(self, profile='preview', server=None, token=None):
        """روی پنل (API) کارِ رندر می‌سازد. server مثل http://host:8030 ، token = توکنِ API."""
        from .client import ApiClient
        return ApiClient(server, token).render_scene(self.to_dict(), profile)
