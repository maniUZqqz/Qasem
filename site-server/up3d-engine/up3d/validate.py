"""وارسیِ سندِ صحنه + گرافِ حرکت + ترمیمِ خودکار.

اصل: «هیچ برنامه‌ای بی‌وارسی رندر نمی‌شود». هر ایراد = {level, code, path, message}.
level: error (رندر ممنوع) | warning (رندر مجاز، کیفیت در خطر) | info.

گرافِ حرکت: برای هر بازیگر، حالتِ دست‌ها و برای هر محصول، جایش (روی سطح / در دستِ کی)
در طولِ زمان شبیه‌سازی می‌شود. هر حرکت «نیاز» (requires) و «اثر» (effect) دارد.
"""
import copy

from . import scene as S

MAX_DURATION = 60.0
MIN_DURATION = 3.0
GAP = 0.05


def _issue(level, code, path, message):
    return {'level': level, 'code': code, 'path': path, 'message': message}


class Report:
    def __init__(self, issues=None, timeline=None):
        self.issues = issues or []
        self.timeline = timeline or []   # وضعیتِ محصول/دست بعد از هر حرکت (برای پنل و آزمون)

    @property
    def errors(self):
        return [i for i in self.issues if i['level'] == 'error']

    @property
    def warnings(self):
        return [i for i in self.issues if i['level'] == 'warning']

    @property
    def ok(self):
        return not self.errors

    def to_dict(self):
        return {'ok': self.ok, 'errors': len(self.errors), 'warnings': len(self.warnings),
                'issues': self.issues, 'timeline': self.timeline}


# ───────────────────────── کمک‌ها

def _motion_hand(motion, params, held_by_hand, explicit=None):
    """دستی که این حرکت به کار می‌برد. held_by_hand: {'R': product|None, 'L': ...}
    explicit: پارامترهایی که کاربر/AI صریح داده (پیش‌فرضِ manifest دستِ پر را تحمیل نمی‌کند)."""
    hands = motion.get('hands') or {}
    uses = hands.get('uses', 'none')
    explicit = params if explicit is None else explicit
    if hands.get('param') and explicit.get(hands['param']) in ('R', 'L'):
        return explicit[hands['param']]
    if uses in ('R', 'L', 'both', 'none'):
        return uses
    if uses == 'free':
        for h in ('R', 'L'):
            if not held_by_hand.get(h):
                return h
        return None
    if uses == 'holding':   # دستی که محصولِ موردِ نظر را دارد
        prod = params.get((motion.get('product') or {}).get('param', 'product'))
        for h in ('R', 'L'):
            if held_by_hand.get(h) == prod:
                return h
        return None
    return uses


def simulate(doc, reg):
    """شبیه‌سازیِ گرافِ حرکت. خروجی: (issues, timeline)."""
    issues, timeline = [], []
    products = {p['id']: {'state': 'surface', 'surface': p.get('surface')} for p in doc['products']}
    hands = {a['id']: {'R': None, 'L': None} for a in doc['actors']}
    for idx, act in enumerate(doc['actions']):
        path = 'actions[%d]' % idx
        m = reg.get('motion', act.get('motion'))
        if not m or act.get('actor') not in hands:
            continue
        params, _ = reg.resolve_params(m, act.get('params'))
        pinfo = m.get('product') or {}
        prod_id = params.get(pinfo.get('param', 'product')) if pinfo else None
        req, eff = pinfo.get('requires'), pinfo.get('effect')
        actor_hands = hands[act['actor']]
        hand = _motion_hand(m, params, actor_hands, act.get('params') or {})
        label = '«%s» در %.1fث' % (m.label(), act['start'])
        if (req or eff) and not prod_id:
            issues.append(_issue('error', 'E_GRAPH_NO_PRODUCT', path, '%s محصول لازم دارد' % label))
            continue
        if prod_id and prod_id not in products:
            issues.append(_issue('error', 'E_REF', path, '%s: محصولِ «%s» در صحنه نیست' % (label, prod_id)))
            continue
        st = products.get(prod_id)
        if req == 'on_surface' and st and st['state'] != 'surface':
            issues.append(_issue('error', 'E_GRAPH_HELD', path,
                                 '%s: محصول روی میز نیست (در دستِ %s است)؛ اول باید گذاشته شود' % (label, st.get('actor'))))
        if req == 'in_hand' and st and not (st['state'] == 'held' and st['actor'] == act['actor']):
            issues.append(_issue('error', 'E_GRAPH_NOT_HELD', path,
                                 '%s: محصول در دستِ بازیگر نیست؛ اول باید «برداشتن» بیاید' % label))
        if (m.get('hands') or {}).get('uses') in ('free',) and hand is None:
            issues.append(_issue('error', 'E_GRAPH_HANDS_BUSY', path, '%s: هر دو دست پر است' % label))
        if (m.get('hands') or {}).get('requires_free') and hand in ('R', 'L') and actor_hands.get(hand) and actor_hands[hand] != prod_id:
            issues.append(_issue('error', 'E_GRAPH_HAND_BUSY', path,
                                 '%s: دستِ %s چیزِ دیگری در دست دارد' % (label, 'راست' if hand == 'R' else 'چپ')))
        # اثر
        if eff == 'in_hand' and st is not None and hand in ('R', 'L'):
            products[prod_id] = {'state': 'held', 'actor': act['actor'], 'hand': hand}
            actor_hands[hand] = prod_id
        elif eff == 'on_surface' and st is not None:
            for h in ('R', 'L'):
                if actor_hands.get(h) == prod_id:
                    actor_hands[h] = None
            products[prod_id] = {'state': 'surface', 'surface': params.get('surface') or st.get('surface')}
        timeline.append({'action': act.get('id'), 'time': S.end_of(act),
                         'products': copy.deepcopy(products), 'hands': copy.deepcopy(hands)})
    return issues, timeline


# ───────────────────────── وارسی

def validate(doc, reg):
    doc = S.normalize(doc)
    issues = []
    out = doc['output']
    dur = out['duration']
    if not (MIN_DURATION <= dur <= MAX_DURATION):
        issues.append(_issue('error', 'E_OUTPUT', 'output.duration', 'مدت باید بینِ %d و %d ثانیه باشد' % (MIN_DURATION, MAX_DURATION)))
    if not (12 <= out['fps'] <= 60):
        issues.append(_issue('error', 'E_OUTPUT', 'output.fps', 'fps باید بینِ ۱۲ و ۶۰ باشد'))

    env = reg.get('environment', doc['environment'].get('id'))
    if not env:
        issues.append(_issue('error', 'E_ASSET', 'environment', 'محیطِ «%s» در کتابخانه نیست' % doc['environment'].get('id')))
    if doc['lighting'].get('id') and not reg.get('lighting', doc['lighting']['id']):
        issues.append(_issue('error', 'E_ASSET', 'lighting', 'نورپردازیِ «%s» نیست' % doc['lighting']['id']))
    if not doc['actors'] and not doc['products']:
        issues.append(_issue('error', 'E_EMPTY', 'actors', 'صحنه نه بازیگر دارد نه محصول'))

    ids = {}
    for kind in ('actors', 'products'):
        for i, it in enumerate(doc[kind]):
            if it['id'] in ids:
                issues.append(_issue('error', 'E_DUP', '%s[%d]' % (kind, i), 'شناسهٔ تکراری «%s»' % it['id']))
            ids[it['id']] = kind
    used_marks = {}
    for i, a in enumerate(doc['actors']):
        if not reg.get('character', a.get('character')):
            issues.append(_issue('error', 'E_ASSET', 'actors[%d]' % i, 'کاراکترِ «%s» نیست' % a.get('character')))
        if env and a.get('mark') not in env['marks']:
            issues.append(_issue('error', 'E_MARK', 'actors[%d]' % i, 'جایگاهِ «%s» در محیطِ %s نیست (مجاز: %s)' % (
                a.get('mark'), env.id, ', '.join(env['marks']))))
        if a.get('mark') in used_marks:
            issues.append(_issue('error', 'E_MARK', 'actors[%d]' % i, 'دو بازیگر روی یک جایگاه'))
        used_marks[a.get('mark')] = a['id']
    used_surf = {}
    for i, p in enumerate(doc['products']):
        pa = reg.get('product', p.get('asset'))
        if not pa:
            issues.append(_issue('error', 'E_ASSET', 'products[%d]' % i, 'محصولِ «%s» نیست' % p.get('asset')))
        if env:
            if not p.get('surface'):
                issues.append(_issue('warning', 'W_SURFACE', 'products[%d]' % i, 'جای محصول مشخص نیست؛ اولین سطح استفاده می‌شود'))
            elif p['surface'] not in env['surfaces']:
                issues.append(_issue('error', 'E_SURFACE', 'products[%d]' % i, 'سطحِ «%s» در محیط نیست (مجاز: %s)' % (
                    p['surface'], ', '.join(env['surfaces']))))
            elif p['surface'] in used_surf:
                issues.append(_issue('warning', 'W_SURFACE', 'products[%d]' % i, 'دو محصول روی یک نقطه'))
            used_surf[p.get('surface')] = p['id']

    # حرکت‌ها
    last_end = {}
    for i, act in enumerate(doc['actions']):
        path = 'actions[%d]' % i
        m = reg.get('motion', act.get('motion'))
        if act.get('actor') not in [a['id'] for a in doc['actors']]:
            issues.append(_issue('error', 'E_REF', path, 'بازیگرِ «%s» نیست' % act.get('actor')))
        if not m:
            issues.append(_issue('error', 'E_ASSET', path, 'حرکتِ «%s» در کتابخانه نیست' % act.get('motion')))
            continue
        d = m['duration']
        if act['duration'] < d['min'] - 1e-6 or act['duration'] > d['max'] + 1e-6:
            issues.append(_issue('warning', 'W_DURATION', path, '«%s» باید %.1f تا %.1f ثانیه باشد (الان %.2f)' % (
                m.label(), d['min'], d['max'], act['duration'])))
        if S.end_of(act) > dur + 1e-6:
            issues.append(_issue('error', 'E_RANGE', path, '«%s» بعد از پایانِ ویدئو تمام می‌شود' % m.label()))
        _, pissues = reg.resolve_params(m, act.get('params'))
        for msg in pissues:
            issues.append(_issue('warning', 'W_PARAM', path, '%s: %s' % (m.label(), msg)))
        for key, spec in (m.get('params') or {}).items():
            if spec.get('type') == 'product_ref':
                pid = (act.get('params') or {}).get(key) or spec.get('default')
                if pid and ids.get(pid) != 'products':
                    issues.append(_issue('error', 'E_REF', path, '%s: محصولِ «%s» نیست' % (m.label(), pid)))
            if spec.get('type') == 'surface_ref' and env:
                sid = (act.get('params') or {}).get(key)
                if sid and sid not in env['surfaces']:
                    issues.append(_issue('error', 'E_SURFACE', path, '%s: سطحِ «%s» نیست' % (m.label(), sid)))
        if not m.get('layer'):
            prev = last_end.get(act.get('actor'))
            if prev and act['start'] < prev[0] - 1e-6:
                issues.append(_issue('error', 'E_OVERLAP', path, '«%s» با حرکتِ قبلی (%s) هم‌پوشانی دارد' % (m.label(), prev[1])))
            last_end[act.get('actor')] = (S.end_of(act), act.get('id'))

    gissues, timeline = simulate(doc, reg)
    issues += gissues

    # گفتار
    sp_end = {}
    for i, sp in enumerate(doc['speech']):
        path = 'speech[%d]' % i
        if not (sp.get('text') or '').strip():
            issues.append(_issue('error', 'E_SPEECH', path, 'متنِ گفتار خالی است'))
        if sp.get('actor') and sp['actor'] not in [a['id'] for a in doc['actors']]:
            issues.append(_issue('error', 'E_REF', path, 'گویندهٔ «%s» نیست' % sp['actor']))
        if sp.get('voice') and not reg.get('voice', sp['voice']):
            issues.append(_issue('error', 'E_ASSET', path, 'صدای «%s» نیست' % sp['voice']))
        est = S.estimate_speech_seconds(sp.get('text', ''))
        if sp['start'] + est > dur + 0.3:
            issues.append(_issue('error', 'E_SPEECH_LONG', path, 'این جمله (~%.1fث) تا پایانِ ویدئو جا نمی‌شود' % est))
        key = sp.get('actor') or '_vo'
        if key in sp_end and sp['start'] < sp_end[key] - 1e-6:
            issues.append(_issue('error', 'E_OVERLAP', path, 'دو جملهٔ هم‌زمان از یک گوینده'))
        sp_end[key] = sp['start'] + max(est, sp.get('duration') or 0)

    # دوربین
    if not doc['shots']:
        issues.append(_issue('error', 'E_SHOTS', 'shots', 'هیچ شاتِ دوربینی نیست'))
    t = 0.0
    for i, sh in enumerate(doc['shots']):
        path = 'shots[%d]' % i
        sa = reg.get('shot', sh.get('shot'))
        if not sa:
            issues.append(_issue('error', 'E_ASSET', path, 'نمای دوربینِ «%s» نیست' % sh.get('shot')))
        kind = S.subject_kind(doc, sh.get('subject'))
        if not kind:
            issues.append(_issue('error', 'E_REF', path, 'سوژهٔ شات «%s» نیست' % sh.get('subject')))
        elif sa and sa.get('subject', 'any') not in ('any', kind):
            issues.append(_issue('error', 'E_SHOT_SUBJECT', path, 'نمای «%s» برای %s است، نه %s' % (
                sa.label(), sa.get('subject'), kind)))
        if sa and sh.get('move') and sh['move'] not in sa.get('moves', []):
            issues.append(_issue('warning', 'W_MOVE', path, 'حرکتِ دوربینِ «%s» برای این نما تعریف نشده' % sh['move']))
        if sh['start'] > t + 0.02:
            issues.append(_issue('warning', 'W_SHOT_GAP', path, 'فاصلهٔ بی‌دوربین از %.2f تا %.2f' % (t, sh['start'])))
        if sh['start'] < t - 0.02:
            issues.append(_issue('error', 'E_SHOT_OVERLAP', path, 'شات با قبلی هم‌پوشانی دارد'))
        if sh['duration'] < 0.6:
            issues.append(_issue('warning', 'W_SHOT_SHORT', path, 'شاتِ کوتاه‌تر از ۰٫۶ ثانیه پرش‌دار دیده می‌شود'))
        t = max(t, S.end_of(sh))
    if doc['shots'] and t < dur - 0.02:
        issues.append(_issue('warning', 'W_SHOT_GAP', 'shots', 'دوربین از %.2f تا پایان پوشش ندارد' % t))

    for i, g in enumerate(doc['gaze']):
        tgt = g.get('target', 'camera')
        if tgt not in ('camera', 'forward') and not (
                ':' in tgt and tgt.split(':', 1)[0] in ('product', 'actor') and S.subject_kind(doc, tgt.split(':', 1)[1])):
            issues.append(_issue('error', 'E_REF', 'gaze[%d]' % i, 'هدفِ نگاهِ «%s» نامعتبر است' % tgt))
    for i, e in enumerate(doc['expressions']):
        if e.get('expression') not in S.EXPRESSIONS:
            issues.append(_issue('warning', 'W_EXPR', 'expressions[%d]' % i, 'حالتِ چهرهٔ «%s» شناخته نیست' % e.get('expression')))
    for i, o in enumerate(doc['overlays']):
        if o.get('type') not in S.OVERLAY_TYPES:
            issues.append(_issue('warning', 'W_OVERLAY', 'overlays[%d]' % i, 'نوعِ نوشتهٔ «%s» شناخته نیست' % o.get('type')))
        if len(o.get('text', '')) > 60:
            issues.append(_issue('warning', 'W_OVERLAY', 'overlays[%d]' % i, 'نوشته بلند است (بیش از ۶۰ نویسه)'))
        if S.end_of(o) > dur + 0.05:
            issues.append(_issue('warning', 'W_RANGE', 'overlays[%d]' % i, 'نوشته بعد از پایانِ ویدئو'))
    return Report(issues, timeline)


# ───────────────────────── ترمیم

def repair(doc, reg, max_rounds=4):
    """ایرادهای قابلِ ترمیم را درست می‌کند. خروجی: (doc, changes[], report)."""
    doc = S.normalize(doc)
    changes = []
    for _ in range(max_rounds):
        rep = validate(doc, reg)
        if not rep.issues:
            break
        before = len(changes)
        _repair_round(doc, reg, rep, changes)
        doc = S.normalize(doc)
        if len(changes) == before:
            break
    return doc, changes, validate(doc, reg)


def _default_id(reg, kind):
    a = reg.default(kind)
    return a.id if a else None


def _repair_round(doc, reg, rep, changes):
    out = doc['output']
    if out['duration'] < MIN_DURATION or out['duration'] > MAX_DURATION:
        out['duration'] = min(MAX_DURATION, max(MIN_DURATION, out['duration']))
        changes.append('مدت به %.1f ثانیه محدود شد' % out['duration'])
    out['fps'] = min(60, max(12, out['fps']))
    if not reg.get('environment', doc['environment'].get('id')):
        doc['environment'] = {'id': _default_id(reg, 'environment'), 'params': {}}
        changes.append('محیطِ پیش‌فرض «%s» گذاشته شد' % doc['environment']['id'])
    if not reg.get('lighting', doc['lighting'].get('id')):
        env = reg.get('environment', doc['environment']['id'])
        doc['lighting'] = {'id': (env or {}).get('default_lighting') or _default_id(reg, 'lighting'), 'params': {}}
        changes.append('نورِ «%s» گذاشته شد' % doc['lighting']['id'])
    env = reg.get('environment', doc['environment']['id'])
    marks = list(env['marks']) if env else []
    surfs = list(env['surfaces']) if env else []
    taken = set()
    for a in doc['actors']:
        if not reg.get('character', a.get('character')):
            a['character'] = _default_id(reg, 'character')
            changes.append('کاراکترِ «%s» به‌جای کاراکترِ ناموجود' % a['character'])
        if a.get('mark') not in marks or a.get('mark') in taken:
            free = [m for m in marks if m not in taken]
            if free:
                a['mark'] = free[0]
                changes.append('بازیگرِ %s روی جایگاهِ «%s»' % (a['id'], a['mark']))
        taken.add(a.get('mark'))
    stake = set()
    for p in doc['products']:
        if not reg.get('product', p.get('asset')):
            p['asset'] = _default_id(reg, 'product')
            changes.append('شکلِ محصول «%s» شد' % p['asset'])
        if p.get('surface') not in surfs or p.get('surface') in stake:
            free = [s for s in surfs if s not in stake]
            if free:
                p['surface'] = free[0]
                changes.append('محصولِ %s روی «%s»' % (p['id'], p['surface']))
        stake.add(p.get('surface'))

    actors = [a['id'] for a in doc['actors']]
    prods = [p['id'] for p in doc['products']]
    keep = []
    for act in doc['actions']:
        m = reg.get('motion', act.get('motion'))
        if not m or act.get('actor') not in actors:
            changes.append('حرکتِ نامعتبرِ «%s» حذف شد' % act.get('motion'))
            continue
        d = m['duration']
        if act['duration'] < d['min'] or act['duration'] > d['max']:
            act['duration'] = min(d['max'], max(d['min'], act['duration']))
            changes.append('مدتِ «%s» به %.2f ثانیه رسید' % (m.label(), act['duration']))
        for key, spec in (m.get('params') or {}).items():
            if spec.get('type') == 'product_ref':
                pid = (act.get('params') or {}).get(key)
                if pid not in prods and prods:
                    act.setdefault('params', {})[key] = prods[0]
                    changes.append('«%s» به محصولِ %s وصل شد' % (m.label(), prods[0]))
            if spec.get('type') == 'surface_ref' and env:
                sid = (act.get('params') or {}).get(key)
                if sid and sid not in surfs:
                    act['params'].pop(key, None)
                    changes.append('سطحِ نامعتبر از «%s» برداشته شد' % m.label())
        keep.append(act)
    doc['actions'] = keep

    # هم‌پوشانیِ حرکت‌های بدن: هل دادن به بعد
    for aid in actors:
        t = 0.0
        for act in [x for x in doc['actions'] if x['actor'] == aid and not reg.get('motion', x['motion']).get('layer')]:
            if act['start'] < t - 1e-6:
                act['start'] = round(t + GAP, 3)
                changes.append('«%s» به %.2f ثانیه جابه‌جا شد تا هم‌پوشانی نداشته باشد' % (act['motion'], act['start']))
            t = S.end_of(act)

    # گرافِ حرکت: افزودنِ «برداشتن» پیش از حرکتی که محصول در دست می‌خواهد
    codes = {i['code'] for i in rep.issues}
    if codes & {'E_GRAPH_NOT_HELD', 'E_GRAPH_HELD'}:
        _repair_graph(doc, reg, changes)
    if codes & {'E_GRAPH_HAND_BUSY', 'E_GRAPH_HANDS_BUSY'}:
        _repair_hands(doc, reg, changes)

    # گفتار
    dur = doc['output']['duration']
    t_need = 0.0
    last = {}
    for sp in doc['speech']:
        est = S.estimate_speech_seconds(sp.get('text', ''))
        key = sp.get('actor') or '_vo'
        if key in last and sp['start'] < last[key]:
            sp['start'] = round(last[key] + 0.15, 3)
            changes.append('جملهٔ «%s…» بعد از جملهٔ قبلی گذاشته شد' % sp.get('text', '')[:20])
        last[key] = sp['start'] + est
        sp['duration'] = round(est, 2)
        t_need = max(t_need, sp['start'] + est + 0.4)
        if sp.get('voice') and not reg.get('voice', sp['voice']):
            sp['voice'] = _default_id(reg, 'voice')
            changes.append('صدای پیش‌فرض گذاشته شد')
    t_need = max([t_need] + [S.end_of(a) + 0.3 for a in doc['actions']])
    if t_need > dur:
        doc['output']['duration'] = dur = round(min(MAX_DURATION, t_need), 2)
        changes.append('مدتِ ویدئو به %.1f ثانیه رسید تا گفتار و حرکت جا شوند' % dur)
    doc['actions'] = [a for a in doc['actions'] if a['start'] < dur - 0.2]
    for a in doc['actions']:
        if S.end_of(a) > dur:
            a['duration'] = round(dur - a['start'], 3)

    # دوربین: پوششِ کامل و بی‌هم‌پوشانی
    subj_default = actors[0] if actors else (prods[0] if prods else None)
    if not doc['shots']:
        doc['shots'] = [{'shot': _shot_for(reg, 'actor' if actors else 'product'), 'start': 0.0, 'duration': dur,
                         'subject': subj_default, 'move': 'push_in', 'params': {}}]
        changes.append('یک شاتِ پیش‌فرض برای کلِ ویدئو ساخته شد')
    shots = []
    for sh in doc['shots']:
        kind = S.subject_kind(doc, sh.get('subject'))
        if not kind:
            sh['subject'] = subj_default
            kind = S.subject_kind(doc, subj_default)
            changes.append('سوژهٔ شاتِ %s درست شد' % sh.get('id'))
        sa = reg.get('shot', sh.get('shot'))
        if not sa or sa.get('subject', 'any') not in ('any', kind):
            sh['shot'] = _shot_for(reg, kind)
            sa = reg.get('shot', sh['shot'])
            changes.append('نمای شاتِ %s به «%s» تغییر کرد' % (sh.get('id'), sh['shot']))
        if sh.get('move') and sa and sh['move'] not in sa.get('moves', []):
            sh['move'] = (sa.get('moves') or ['static'])[0]
        if sh['start'] < dur - 0.3:
            shots.append(sh)
    shots.sort(key=lambda s: s['start'])
    if shots:
        shots[0]['start'] = 0.0
        for a, b in zip(shots, shots[1:]):
            a['duration'] = round(max(0.3, b['start'] - a['start']), 3)
        shots[-1]['duration'] = round(dur - shots[-1]['start'], 3)
    doc['shots'] = shots

    for track in ('gaze', 'expressions', 'overlays'):
        lst = []
        for it in doc[track]:
            if it['start'] >= dur - 0.1:
                continue
            if S.end_of(it) > dur:
                it['duration'] = round(dur - it['start'], 3)
            lst.append(it)
        doc[track] = lst
    doc['gaze'] = [g for g in doc['gaze'] if g.get('target', 'camera') in ('camera', 'forward') or (
        ':' in g.get('target', '') and S.subject_kind(doc, g['target'].split(':', 1)[1]))]
    doc['expressions'] = [e for e in doc['expressions'] if e.get('expression') in S.EXPRESSIONS]


def _shot_for(reg, kind):
    for a in reg.list('shot'):
        if a.get('subject', 'any') in ('any', kind) and a.get('default_for') == kind:
            return a.id
    for a in reg.list('shot'):
        if a.get('subject', 'any') in ('any', kind):
            return a.id
    return None


def _repair_hands(doc, reg, changes):
    """ژستی که دستِ پر را می‌خواهد: دستِ آزادِ دیگر؛ اگر هیچ دستی آزاد نیست، اول محصول گذاشته شود."""
    for _ in range(6):
        issues, _tl = simulate(doc, reg)
        bad = [i for i in issues if i['code'] in ('E_GRAPH_HAND_BUSY', 'E_GRAPH_HANDS_BUSY')]
        if not bad:
            return
        idx = int(bad[0]['path'].split('[')[1].rstrip(']'))
        act = doc['actions'][idx]
        m = reg.get('motion', act['motion'])
        param = (m.get('hands') or {}).get('param')
        held = _held_before(doc, reg, idx)
        free = [h for h in ('R', 'L') if not held.get(h)]
        if free and param:
            act.setdefault('params', {})[param] = free[0]
            changes.append('«%s» با دستِ %s (دستِ دیگر محصول دارد)' % (m.label(), 'راست' if free[0] == 'R' else 'چپ'))
            continue
        put = reg.get('motion', 'put_down')
        pid = held.get('R') or held.get('L')
        if not put or not pid:
            doc['actions'].pop(idx)
            changes.append('«%s» حذف شد (هیچ دستی آزاد نبود)' % m.label())
            continue
        d = put['duration']['default']
        new = {'actor': act['actor'], 'motion': 'put_down', 'start': round(max(0.0, act['start'] - d - GAP), 3),
               'duration': d, 'params': {'product': pid}}
        for later in doc['actions'][idx:]:
            if later['actor'] == act['actor']:
                later['start'] = round(later['start'] + d + GAP, 3)
        doc['actions'].insert(idx, new)
        doc['actions'].sort(key=lambda x: x['start'])
        changes.append('«گذاشتن» پیش از «%s» افزوده شد تا دست آزاد شود' % m.label())


def _held_before(doc, reg, idx):
    """دست‌های بازیگرِ این حرکت درست پیش از آن چه دارند."""
    act = doc['actions'][idx]
    sub = dict(doc)
    sub['actions'] = doc['actions'][:idx]
    _issues, tl = simulate(sub, reg)
    for step in reversed(tl):
        if act['actor'] in step['hands']:
            return step['hands'][act['actor']]
    return {'R': None, 'L': None}


def _repair_graph(doc, reg, changes):
    """وقتی حرکتی محصولِ در دست می‌خواهد و نیست، «برداشتن» پیش از آن؛ وقتی روی میز می‌خواهد و در دست است، «گذاشتن»."""
    pick = reg.get('motion', 'pick_up')
    put = reg.get('motion', 'put_down')
    for _ in range(6):
        issues, _tl = simulate(doc, reg)
        bad = [i for i in issues if i['code'] in ('E_GRAPH_NOT_HELD', 'E_GRAPH_HELD')]
        if not bad:
            return
        idx = int(bad[0]['path'].split('[')[1].rstrip(']'))
        act = doc['actions'][idx]
        m = reg.get('motion', act['motion'])
        params, _ = reg.resolve_params(m, act.get('params'))
        pid = params.get((m.get('product') or {}).get('param', 'product'))
        insert = pick if bad[0]['code'] == 'E_GRAPH_NOT_HELD' else put
        if not insert:
            return
        d = insert['duration']['default']
        start = max(0.0, act['start'] - d - GAP)
        new = {'actor': act['actor'], 'motion': insert.id, 'start': round(start, 3), 'duration': d,
               'params': {'product': pid}}
        # جا باز کن: این حرکت و بعدی‌ها اگر لازم است جلو بروند
        if act['start'] - start < d + GAP - 1e-6:
            shift = d + GAP - (act['start'] - start)
            for later in doc['actions'][idx:]:
                if later['actor'] == act['actor']:
                    later['start'] = round(later['start'] + shift, 3)
        # حرکتِ بدنیِ قبلیِ همین بازیگر که با «برداشتن» هم‌پوشان است کوتاه شود
        for prev in doc['actions'][:idx]:
            pm = reg.get('motion', prev['motion'])
            if prev['actor'] == act['actor'] and pm and not pm.get('layer') and S.end_of(prev) > start - GAP:
                prev['duration'] = round(max(pm['duration']['min'], start - GAP - prev['start']), 3)
        doc['actions'].insert(idx, new)
        doc['actions'].sort(key=lambda x: x['start'])
        changes.append('«%s» پیش از «%s» افزوده شد' % (insert.label(), m.label()))
