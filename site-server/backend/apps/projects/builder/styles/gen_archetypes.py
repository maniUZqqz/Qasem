# -*- coding: utf-8 -*-
"""«الگو»های ظاهریِ سبک‌های خودکار: هر الگو از یک پالت ``Pal`` توکن‌های ``--st-*`` و چند قاعدهٔ CSSِ ویژه می‌سازد.

هر تابع ``(P, o) ⇒ {tokens, extra, sections, radius, button, width}``؛ ``o`` گزینه‌های ردیفِ سبک است (مثلاً acc2). فقط ویژگی‌های منطقیِ CSS (start/end)،
بی‌letter-spacing، بی‌url()، بی‌@import؛ ``sections`` فقط چیدمان‌هایی که با متنِ هیرو روی هر زمینه‌ای خوانا می‌مانند (بی‌«aurora»ی هیرو).
"""
from .gen_core import Pal, contrast, ensure, fill, hero_pair, mix, on_color, rgba, shade, stop_for, tint

SEC = dict(hero='', features='', pricing='', testimonials='', faq='', cta='', site_header='')


def _sec(**kw):
    s = dict(SEC)
    s.update(kw)
    return s


def _base(P: Pal, solid=False, a=None, b=None, **kw):
    """توکن‌های پایه: تیترِ بی‌فاصلهٔ حروف + هیرو/دعوتِ خوانا؛ kw بازنویسی می‌کند."""
    bg, fg, bb, bf = hero_pair(P, a=a, b=b, solid=solid)
    t = {'head_w': '800', 'head_ls': '0', 'head_tt': 'none', 'hero_bg': bg, 'hero_fg': fg, 'hero_btn_bg': bb, 'hero_btn_fg': bf,
         'cta_bg': bg, 'cta_fg': fg}
    t.update(kw)
    return t


def _mesh(P: Pal, a=0.30, b=0.26, c=0.20):
    c3 = mix(P.primary, P.acc2, .5)
    return ('radial-gradient(60%% 50%% at 12%% 6%%,%s 0,transparent 62%%),radial-gradient(50%% 45%% at 92%% 12%%,%s 0,transparent 62%%),'
            'radial-gradient(55%% 50%% at 75%% 96%%,%s 0,transparent 62%%),%s' % (rgba(P.primary, a), rgba(P.acc2, b), rgba(c3, c), P.bg))


# ───────────────────────────── الگوها

def flat(P, o):
    return dict(radius=10, button='soft', width=1140, sections=_sec(pricing='flat', faq='plain'),
                tokens=_base(P, solid=True, card_sh='none', hov='translateY(-2px)', hov_sh='0 10px 24px -18px rgba(0,0,0,.35)', btn_sh='none', btn_hov='none',
                             ic_r='10px', ic_bg='color-mix(in srgb,var(--brand) 14%,transparent)', cta_r='14px'), extra='')


def soft(P, o):
    return dict(radius=24, button='round', width=1140, sections=_sec(testimonials='marked', faq='boxed', site_header='floating'),
                tokens=_base(P, card_sh='0 18px 40px -26px %s' % rgba(P.primary, .55), hov='translateY(-4px)', hov_sh='0 24px 48px -26px %s' % rgba(P.primary, .6),
                             btn_sh='0 12px 26px -12px %s' % rgba(P.primary, .65), ic_r='50%', gap='24px', cta_r='32px'), extra='')


def glass(P, o):
    d = P.dark
    card = 'rgba(255,255,255,.06)' if d else 'rgba(255,255,255,.55)'
    edge = 'rgba(255,255,255,.14)' if d else 'rgba(255,255,255,.75)'
    return dict(radius=22, button='round', width=1140, sections=_sec(pricing='glow', faq='boxed', site_header='floating'),
                tokens=_base(P, page_bg=_mesh(P, .38 if d else .30, .30 if d else .26, .24 if d else .20), card_bg=card, card_bd='1px solid ' + edge,
                             card_sh='0 14px 44px -18px %s' % rgba(P.primary, .45), bf='blur(18px) saturate(1.4)', hov_sh='0 20px 50px -18px %s' % rgba(P.primary, .55),
                             btn_sh='0 12px 28px -10px %s' % rgba(P.primary, .6), hd_bg=card, hd_bf='blur(18px) saturate(1.4)', hd_bd='1px solid ' + edge,
                             in_bg='rgba(255,255,255,.08)' if d else 'rgba(255,255,255,.7)', in_bd='1px solid ' + edge, eb_bg=card),
                extra='.nb-btn.is-outline{-webkit-backdrop-filter:blur(8px);backdrop-filter:blur(8px)}')


def vision(P, o):
    g = glass(P, o)
    g['tokens'].update(bf='blur(30px) saturate(1.7)', hd_bf='blur(30px) saturate(1.7)', card_bd='1px solid rgba(255,255,255,.28)',
                       card_sh='0 30px 70px -30px rgba(0,0,0,.45)', card_r='34px')
    g.update(radius=32)
    return g


def neu(P, o):
    d = shade(P.bg, .20) if not P.dark else shade(P.bg, .45)
    l = tint(P.bg, .75) if not P.dark else tint(P.bg, .09)
    return dict(radius=22, button='soft', width=1100, sections=_sec(hero='minimal', pricing='flat', faq='boxed', site_header='minimal'),
                tokens=_base(P, solid=True, card_bg=P.bg, card_bd='0 solid transparent', card_sh='10px 10px 22px %s,-10px -10px 22px %s' % (d, l), hov='translateY(-2px)',
                             hov_sh='12px 12px 26px %s,-12px -12px 26px %s' % (d, l), btn_bw='0', btn_sh='7px 7px 16px %s,-7px -7px 16px %s' % (d, l),
                             in_bg=P.bg, in_bd='0 solid transparent', in_sh='inset 6px 6px 12px %s,inset -6px -6px 12px %s' % (d, l), ic_bg=P.bg, ic_r='50%',
                             hd_bg=P.bg, hd_bd='0 solid transparent', eb_bg=P.bg, cta_r='28px'),
                extra='.nb-btn:active{box-shadow:inset 5px 5px 10px %s,inset -5px -5px 10px %s;transform:none}.nb-feature-icon{box-shadow:inset 4px 4px 8px %s,inset -4px -4px 8px %s}'
                      % (d, l, d, l))


def clay(P, o):
    edge = P.surface if not P.dark else tint(P.bg, .14)
    return dict(radius=28, button='round', width=1140, sections=_sec(hero='framed', testimonials='marked', faq='boxed', site_header='floating'),
                tokens=_base(P, card_bd='3px solid ' + edge, card_sh='inset -6px -6px 14px %s,inset 6px 6px 14px %s,10px 14px 28px -8px %s' % (rgba(P.primary, .12), rgba('#ffffff', .75 if not P.dark else .08), rgba(P.primary, .35)),
                             hov='translateY(-6px) rotate(-.4deg)', mo='transform .3s cubic-bezier(.34,1.56,.64,1),box-shadow .3s ease', btn_bw='0',
                             btn_sh='inset -3px -4px 8px rgba(0,0,0,.14),inset 3px 3px 8px rgba(255,255,255,.4),6px 8px 16px -4px %s' % rgba(P.primary, .6),
                             btn_hov='translateY(-3px) scale(1.03)', ic_r='50%', gap='26px', in_bd='3px solid ' + edge, cta_r='36px'), extra='')


def tactile(P, o):
    c = clay(P, o)
    c['tokens'].update(card_bg='linear-gradient(160deg,%s,%s)' % (tint(P.surface, .0) if not P.dark else tint(P.surface, .04), mix(P.surface, P.primary, .08)),
                       btn_sh='inset 0 -8px 14px rgba(0,0,0,.18),inset 0 8px 14px rgba(255,255,255,.16),0 12px 22px -8px %s' % rgba(P.primary, .7), hov='translateY(-4px) scale(1.01)')
    c['extra'] = '.nb-feature-icon{box-shadow:inset 0 -4px 8px rgba(0,0,0,.14),inset 0 4px 8px rgba(255,255,255,.55)}'
    return c


def brut(P, o):
    ink = P.text
    a2 = o.get('acc2') or '#ffd23f'
    bg, fg, bb, bf = hero_pair(P, a=a2, solid=True)
    return dict(radius=0, button='square', width=1180, sections=_sec(pricing='bold', testimonials='plain', faq='boxed'),
                tokens=dict(head_w='900', head_ls='0', head_tt='none', card_bd='3px solid ' + ink, card_sh='6px 6px 0 ' + ink, card_r='0', hov='translate(-3px,-3px)',
                            hov_sh='9px 9px 0 ' + ink, mo='transform .12s ease,box-shadow .12s ease', btn_bw='3px', btn_sh='5px 5px 0 ' + ink, btn_bc=ink,
                            btn_hov='translate(-2px,-2px)', btn_mo='transform .1s,box-shadow .1s', in_bd='3px solid ' + ink, in_r='0', ic_bg=a2, ic_fg=on_color(a2), ic_r='0',
                            eb_bg=a2, eb_r='0', hd_bd='3px solid ' + ink, hl_bd='3px solid ' + ink, hl_sh='8px 8px 0 ' + ink, hero_bg=bg, hero_fg=fg, hero_btn_bg=bb,
                            hero_btn_fg=bf, cta_bg=P.primary, cta_fg=P.on_primary, cta_bd='3px solid ' + ink, cta_sh='8px 8px 0 ' + ink, cta_r='0',
                            sec_py='clamp(44px,6vw,76px)'),
                extra='.nb-btn:hover{box-shadow:7px 7px 0 %s}.nb-btn:active{transform:translate(3px,3px);box-shadow:0 0 0 %s}.nb-hero .nb-sub{opacity:1}' % (ink, ink)
                      + '.nb-feature:nth-child(3n+2){background:%s}.nb-feature:nth-child(3n+3){background:%s}' % (stop_for(mix(P.surface, o.get('acc3') or '#7be0b0', .45), P.text2, 5.6), stop_for(mix(P.surface, P.acc2, .3), P.text2, 5.6)))


def raw(P, o):
    """بروتالیسمِ خام: تقریباً بی‌طراحی؛ حاشیهٔ نازک، سایهٔ سخت نه، قلمِ ساده."""
    return dict(radius=0, button='square', width=1100, sections=_sec(hero='start', pricing='flat', testimonials='plain', faq='plain', site_header='minimal'),
                tokens=_base(P, solid=True, card_bd='2px solid ' + P.text, card_sh='none', card_r='0', hov='none', hov_sh='none', btn_bw='2px', btn_sh='none', btn_hov='none',
                             btn_bc=P.text, in_bd='2px solid ' + P.text, in_r='0', ic_bg='transparent', ic_r='0', eb_r='0', hd_bd='2px solid ' + P.text, hl_bd='4px double ' + P.text,
                             hl_sh='none', cta_r='0', head_w='900', sec_py='clamp(36px,5vw,64px)'),
                extra='.nb-text a,.nb-nav a{text-decoration:underline}.nb-feature-icon{display:none}')


def dark(P, o):
    return dict(radius=18, button='round', width=1140, sections=_sec(pricing='glow', faq='boxed'),
                tokens=_base(P, page_bg='radial-gradient(60%% 45%% at 50%% 0,%s 0,transparent 70%%),%s' % (rgba(P.primary, .22), P.bg),
                             card_bg='rgba(255,255,255,.04)', card_bd='1px solid rgba(255,255,255,.10)', card_sh='0 18px 50px -26px rgba(0,0,0,.9)',
                             hov_sh='0 22px 60px -22px %s' % rgba(P.primary, .5), btn_sh='0 10px 30px -10px %s' % rgba(P.primary, .8), hd_bg=rgba(P.bg, .7),
                             hd_bf='blur(12px)', hd_bd='1px solid rgba(255,255,255,.08)', in_bg='rgba(255,255,255,.06)', in_bd='1px solid rgba(255,255,255,.14)',
                             ic_bg=rgba(P.primary, .18), eb_bg='rgba(255,255,255,.08)'), extra='')


def neon(P, o):
    a = P.primary
    glow = '0 0 0 1px %s,0 0 26px -6px %s' % (rgba(a, .35), rgba(a, .65))
    return dict(radius=8, button='soft', width=1140, sections=_sec(pricing='glow', faq='boxed'),
                tokens=_base(P, page_bg='repeating-linear-gradient(0deg,%s 0 1px,transparent 1px 4px),radial-gradient(60%% 40%% at 20%% 0,%s 0,transparent 70%%),%s'
                             % (rgba(a, .035), rgba(P.acc2, .20), P.bg), card_bg=rgba(P.surface, .75), card_bd='1px solid ' + rgba(a, .55), card_sh=glow,
                             hov_sh='0 0 0 1px %s,0 0 36px -4px %s' % (rgba(a, .6), rgba(a, .8)), btn_sh='0 0 22px -2px ' + rgba(a, .7), btn_bw='1px',
                             in_bg=rgba(P.surface, .8), in_bd='1px solid ' + rgba(a, .5), ic_bg=rgba(a, .14), hd_bg=rgba(P.bg, .8), hd_bd='1px solid ' + rgba(a, .35),
                             hl_bd='1px solid ' + a, hl_sh='0 0 0 1px %s,0 0 40px -4px %s' % (rgba(a, .5), rgba(a, .8)), cta_bd='1px solid ' + a, eb_bg=rgba(a, .12), eb_r='6px'),
                extra='.nb-hero-title,.nb-title{text-shadow:0 0 22px %s}' % rgba(a, .5))


def hud(P, o):
    n = neon(P, o)
    a = P.primary
    n['tokens'].update(card_r='3px', card_sh='inset 0 0 24px %s' % rgba(a, .10), btn_hov='none', ic_r='3px', in_r='3px', cta_r='3px')
    n['extra'] = ('.nb-feature,.nb-plan,.nb-quote{clip-path:polygon(0 0,calc(100%% - 14px) 0,100%% 14px,100%% 100%%,14px 100%%,0 calc(100%% - 14px))}'
                  '.nb-eyebrow{border:1px solid %s}' % rgba(a, .5))
    n['radius'] = 3
    return n


def glitch(P, o):
    n = neon(P, o)
    n['extra'] = ('.nb-hero-title,.nb-title{text-shadow:2px 0 %s,-2px 0 %s}.nb-btn.is-filled{text-shadow:1px 0 rgba(255,0,60,.5),-1px 0 rgba(0,240,255,.5)}'
                  % (rgba(o.get('acc2') or '#ff2a6d', .65), rgba('#05d9e8', .65)))
    return n


def gradient(P, o):
    return dict(radius=22, button='round', width=1140, sections=_sec(pricing='glow', faq='boxed', site_header='floating'),
                tokens=_base(P, a=P.primary, b=P.acc2, page_bg=_mesh(P, .34, .30, .24),
                             card_bg=rgba(P.surface, .66 if not P.dark else .5), card_bd='1px solid ' + rgba(P.line, .9), card_sh='0 18px 50px -26px %s' % rgba(P.primary, .5),
                             bf='blur(10px)', btn_sh='0 12px 28px -10px %s' % rgba(P.primary, .6), hd_bg=rgba(P.surface, .7), hd_bf='blur(12px)'), extra='')


def vapor(P, o):
    g = gradient(P, o)
    g['tokens']['page_bg'] = 'linear-gradient(180deg,%s 0,%s 60%%,%s 140%%)' % (P.bg, mix(P.bg, P.primary, .25), mix(P.bg, P.acc2, .55))
    g['tokens']['card_bg'] = rgba(P.surface, .6)
    return g


def editorial(P, o):
    return dict(radius=2, button='square', width=1100, sections=_sec(hero='start', features='numbered', pricing='flat', testimonials='big', faq='plain', cta='outline', site_header='centered'),
                tokens=_base(P, solid=True, head_w='700', card_bg='transparent', card_bd='0 solid transparent', card_sh='none', card_r='0', hov='none', hov_sh='none',
                             btn_sh='none', btn_hov='none', ic_bg='transparent', ic_fg=P.primary, ic_r='0', eb_bg='transparent', eb_r='0', cta_r='0', sec_py='clamp(56px,8vw,112px)',
                             hd_bd='0 solid transparent', in_r='0'),
                extra='.nb-feature,.nb-plan,.nb-quote{border-block-start:2px solid var(--ink);padding-block-start:18px;border-radius:0}.nb-plan.is-featured{transform:none}'
                      '.nb-eyebrow{padding:0;font-weight:600}.nb-header{border-bottom:2px solid var(--ink)}')


def swiss(P, o):
    return dict(radius=0, button='square', width=1160, sections=_sec(hero='start', features='numbered', pricing='flat', testimonials='plain', faq='plain', cta='bar', site_header='minimal'),
                tokens=_base(P, solid=True, card_bg='transparent', card_bd='1px solid ' + P.text, card_sh='none', card_r='0', hov='none', hov_sh='none', btn_sh='none',
                             btn_hov='none', ic_bg='transparent', ic_r='0', eb_bg='transparent', eb_r='0', cta_r='0', in_r='0', hd_bd='1px solid ' + P.text, head_w='800'),
                extra='.nb-eyebrow{padding:0}.nb-btn{border-radius:0}')


def exmin(P, o):
    s = swiss(P, o)
    s['tokens'].update(card_bd='0 solid transparent', sec_py='clamp(72px,11vw,150px)', head_w='900', hd_bd='0 solid transparent')
    s['extra'] = '.nb-hero-title{font-size:clamp(2.8rem,9vw,7rem);line-height:1.05}.nb-title{font-size:clamp(2rem,5vw,3.6rem)}.nb-eyebrow{padding:0}'
    return s


def kinetic(P, o):
    f = flat(P, o)
    f['tokens'].update(head_w='900', hov='none', hov_sh='none')
    f['extra'] = ('.nb-hero-title{font-size:clamp(2.8rem,9.5vw,7.6rem);line-height:1.04}.nb-title{font-size:clamp(2rem,6vw,4.4rem);line-height:1.1}'
                  '@media (prefers-reduced-motion:no-preference){.nb-hero-title{animation:nbk-rise .9s cubic-bezier(.2,.8,.2,1) both}@keyframes nbk-rise{from{opacity:0;transform:translateY(24px)}to{opacity:1;transform:none}}}')
    f['sections'] = _sec(hero='start', features='plain', pricing='bold', testimonials='big', cta='bar')
    return f


def story(P, o):
    g = gradient(P, o)
    g['sections'] = _sec(hero='start', features='numbered', testimonials='big', cta='split', site_header='floating')
    g['extra'] = '.nb-section:nth-child(even){background:%s}' % rgba(P.primary, .05)
    return g


def luxury(P, o):
    gold = P.primary
    return dict(radius=4, button='square', width=1120, sections=_sec(hero='minimal', features='plain', pricing='flat', testimonials='big', faq='plain', cta='outline', site_header='centered'),
                tokens=_base(P, a=P.bg, b=mix(P.bg, gold, .22), page_bg='radial-gradient(70%% 50%% at 50%% 0,%s 0,transparent 70%%),%s' % (rgba(gold, .12), P.bg),
                             card_bg='rgba(255,255,255,.03)', card_bd='1px solid ' + rgba(gold, .32), card_sh='0 20px 50px -30px rgba(0,0,0,.9)', card_r='4px', btn_sh='none',
                             hov_sh='0 20px 50px -26px ' + rgba(gold, .4), hero_btn_bg=gold, hero_btn_fg=P.on_primary, ic_bg='transparent', ic_fg=gold, ic_r='0', eb_bg='transparent',
                             eb_r='0', hd_bg=rgba(P.bg, .85), hd_bd='1px solid ' + rgba(gold, .25), in_r='2px', cta_r='4px', cta_bd='1px solid ' + rgba(gold, .4), sec_py='clamp(56px,8vw,116px)',
                             head_w='700'),
                extra='.nb-eyebrow{padding:0;color:%s}' % gold)


def organic(P, o):
    return dict(radius=26, button='round', width=1140, sections=_sec(hero='framed', features='', testimonials='marked', faq='boxed', site_header='floating'),
                tokens=_base(P, card_bd='1px solid var(--line)', card_sh='0 16px 36px -26px %s' % rgba(shade(P.primary, .3), .55), hov='translateY(-3px)', ic_r='50%',
                             ic_bg=rgba(P.primary, .13), gap='24px', cta_r='40px'),
                extra='.nb-feature:nth-child(even){border-start-start-radius:34px;border-start-end-radius:12px;border-end-end-radius:34px;border-end-start-radius:12px}'
                      '.nb-plan,.nb-quote{border-start-start-radius:12px;border-start-end-radius:34px;border-end-end-radius:12px;border-end-start-radius:34px}')


def earth(P, o):
    return organic(P, o)


def memphis(P, o):
    a2 = o.get('acc2') or P.acc2
    dots = 'radial-gradient(%s 2px,transparent 2.4px) 0 0/26px 26px' % rgba(P.text, .10)
    shapes = 'radial-gradient(circle at 12%% 18%%,%s 0 22px,transparent 23px),radial-gradient(circle at 88%% 72%%,%s 0 30px,transparent 31px)' % (rgba(a2, .55), rgba(P.primary, .28))
    return dict(radius=14, button='round', width=1140, sections=_sec(hero='band', features='', pricing='bold', testimonials='marked', faq='boxed', site_header='floating'),
                tokens=_base(P, a=P.primary, b=a2, page_bg='%s,%s,%s' % (shapes, dots, P.bg), card_bd='3px solid ' + P.text, card_sh='6px 6px 0 ' + a2,
                             hov='translate(-2px,-2px)', hov_sh='8px 8px 0 ' + a2, btn_bw='3px', btn_bc=P.text, btn_sh='4px 4px 0 ' + P.text, ic_bg=a2, ic_fg=on_color(a2), ic_r='50%',
                             eb_bg=a2, in_bd='2px solid ' + P.text),
                extra='.nb-feature:nth-child(3n+2){transform:rotate(-1deg)}.nb-feature:nth-child(3n+3){transform:rotate(1deg)}')


def pixel(P, o):
    ink = P.text
    return dict(radius=0, button='square', width=1100, sections=_sec(hero='band', pricing='bold', testimonials='plain', faq='boxed'),
                tokens=_base(P, solid=True, card_bd='4px solid ' + ink, card_sh='4px 4px 0 ' + ink, card_r='0', hov='translate(-2px,-2px)', hov_sh='6px 6px 0 ' + ink, btn_bw='4px',
                             btn_bc=ink, btn_sh='4px 4px 0 ' + ink, btn_hov='translate(-2px,-2px)', in_bd='4px solid ' + ink, in_r='0', ic_bg=P.acc2, ic_fg=on_color(P.acc2), ic_r='0',
                             eb_r='0', hd_bd='4px solid ' + ink, hl_bd='4px solid ' + ink, hl_sh='6px 6px 0 ' + ink, cta_bd='4px solid ' + ink, cta_sh='6px 6px 0 ' + ink, cta_r='0',
                             page_bg='linear-gradient(%s 1px,transparent 1px) 0 0/16px 16px,linear-gradient(90deg,%s 1px,transparent 1px) 0 0/16px 16px,%s' % (rgba(ink, .05), rgba(ink, .05), P.bg)),
                extra='.nb-btn:active{transform:translate(4px,4px);box-shadow:none}')


def dash(P, o):
    return dict(radius=8, button='soft', width=1240, sections=_sec(hero='start', features='', pricing='flat', testimonials='plain', faq='plain', cta='bar', site_header='minimal'),
                tokens=_base(P, solid=True, head_w='700', sec_py='clamp(28px,4vw,52px)', gap='14px', card_r='8px', card_bd='1px solid var(--line)',
                             card_sh='0 1px 2px rgba(15,23,42,.06)', hov='none', hov_sh='0 6px 18px -10px rgba(15,23,42,.3)', btn_sh='none', btn_hov='none', ic_r='8px',
                             ic_bg=rgba(P.primary, .13), eb_r='6px', cta_r='10px', in_r='6px'),
                extra='.nb-feature,.nb-plan,.nb-quote{padding:18px}.nb-feature-title{font-size:1rem}.nb-eyebrow{font-size:.78rem}')


def paper(P, o):
    return dict(radius=2, button='square', width=1060, sections=_sec(hero='minimal', features='list', pricing='flat', testimonials='plain', faq='plain', cta='outline', site_header='minimal'),
                tokens=_base(P, solid=True, card_bg='transparent', card_bd='1px solid ' + P.text, card_sh='none', card_r='2px', hov='none', hov_sh='none', btn_sh='none', btn_hov='none',
                             btn_bw='1px', btn_bc=P.text, ic_bg='transparent', ic_r='0', eb_bg='transparent', eb_r='0', cta_r='2px', in_r='0', hd_bd='1px solid ' + P.text, head_w='700',
                             sec_py='clamp(52px,8vw,104px)'),
                extra='.nb-eyebrow{padding:0}.nb-text a{text-underline-offset:4px}')


def sketch(P, o):
    ink = P.text
    return dict(radius=14, button='soft', width=1100, sections=_sec(hero='start', features='', pricing='flat', testimonials='marked', faq='boxed', site_header='minimal'),
                tokens=_base(P, solid=True, card_bg=P.surface, card_bd='2.5px solid ' + ink, card_r='255px 18px 225px 18px/18px 225px 18px 255px',
                             card_sh='3px 4px 0 ' + rgba(ink, .35), hov='rotate(-.6deg)', hov_sh='4px 6px 0 ' + rgba(ink, .35), btn_bw='2.5px', btn_bc=ink, btn_sh='3px 3px 0 ' + rgba(ink, .4),
                             btn_hov='rotate(-1deg)', in_bd='2.5px solid ' + ink, ic_r='50%', ic_bg=rgba(P.acc2, .5), ic_fg=ink, eb_bg=rgba(P.acc2, .5), eb_r='255px 12px 225px 12px/12px 225px 12px 255px',
                             cta_r='30px', hl_bd='3px solid ' + ink),
                extra='.nb-btn{border-radius:255px 14px 225px 14px/14px 225px 14px 255px}.nb-feature:nth-child(even){transform:rotate(.5deg)}')


def corporate(P, o):
    return dict(radius=8, button='soft', width=1160, sections=_sec(hero='', features='', pricing='flat', testimonials='', faq='columns', cta='split', site_header=''),
                tokens=_base(P, card_sh='0 1px 3px rgba(16,24,40,.08),0 10px 26px -18px rgba(16,24,40,.25)', hov='translateY(-2px)', hov_sh='0 14px 34px -18px rgba(16,24,40,.35)',
                             btn_sh='0 1px 2px rgba(16,24,40,.12)', btn_hov='none', ic_r='10px', ic_bg=rgba(P.primary, .12), cta_r='16px', head_w='700'), extra='')


def maximal(P, o):
    a2 = o.get('acc2') or P.acc2
    a3 = o.get('acc3') or mix(P.primary, '#00e5a0', .6)
    return dict(radius=18, button='round', width=1180, sections=_sec(hero='band', features='', pricing='bold', testimonials='marked', faq='boxed'),
                tokens=_base(P, a=P.primary, b=a2, card_bd='3px solid ' + P.text, card_sh='7px 7px 0 ' + P.primary, hov='translate(-3px,-3px) rotate(-.6deg)', hov_sh='10px 10px 0 ' + a2,
                             btn_bw='3px', btn_bc=P.text, btn_sh='5px 5px 0 ' + a2, ic_bg=a3, ic_fg=on_color(a3), ic_r='14px', eb_bg=a2, in_bd='3px solid ' + P.text,
                             page_bg='radial-gradient(circle at 10%% 10%%,%s 0 40px,transparent 41px),radial-gradient(circle at 92%% 40%%,%s 0 56px,transparent 57px),%s' % (rgba(a2, .5), rgba(a3, .45), P.bg)),
                extra='.nb-feature:nth-child(3n+1){background:%s}.nb-feature:nth-child(3n+2){background:%s}.nb-feature:nth-child(even){transform:rotate(-1deg)}'
                      % (mix(P.surface, a2, .35), mix(P.surface, a3, .35)))


def layers(P, o):
    sh = '0 1px 1px rgba(0,0,0,.07),0 4px 4px rgba(0,0,0,.05),0 12px 12px rgba(0,0,0,.05),0 28px 28px rgba(0,0,0,.04)'
    return dict(radius=16, button='soft', width=1160, sections=_sec(features='bento', pricing='flat', faq='columns'),
                tokens=_base(P, card_sh=sh, card_bd='1px solid ' + rgba(P.text, .06), hov='translateY(-6px)', hov_sh='0 2px 2px rgba(0,0,0,.08),0 8px 8px rgba(0,0,0,.06),0 24px 24px rgba(0,0,0,.06),0 48px 48px rgba(0,0,0,.05)',
                             btn_sh='0 1px 1px rgba(0,0,0,.12),0 6px 12px -4px %s' % rgba(P.primary, .6), mo='transform .25s ease,box-shadow .25s ease', ic_r='12px'), extra='')


def material(P, o):
    tonal = mix(P.surface, P.primary, .07 if not P.dark else .14)
    return dict(radius=20, button='round', width=1140, sections=_sec(features='bento', pricing='flat', faq='boxed', site_header='floating'),
                tokens=_base(P, card_bg=tonal, card_bd='0 solid transparent', card_sh='none', hov='translateY(-2px)', hov_sh='0 6px 18px -10px rgba(0,0,0,.3)', btn_sh='none', btn_hov='none',
                             ic_bg=mix(P.surface, P.primary, .2), ic_fg=P.primary, ic_r='16px', in_bg=tonal, in_bd='1px solid var(--line)', cta_r='28px', eb_bg=tonal), extra='')


def skeuo(P, o):
    return dict(radius=12, button='soft', width=1100, sections=_sec(hero='', features='plain', pricing='bold', testimonials='marked', faq='boxed'),
                tokens=_base(P, a=P.primary, b=shade(P.primary, .3), card_bg='linear-gradient(180deg,%s,%s)' % (tint(P.surface, .6), mix(P.surface, P.primary, .08)),
                             card_bd='1px solid ' + rgba(shade(P.primary, .5), .35), card_sh='inset 0 1px 0 rgba(255,255,255,.85),0 2px 4px rgba(60,40,10,.22),0 12px 22px -10px rgba(60,40,10,.4)',
                             hov='translateY(-2px)', btn_bw='1px', btn_bc=shade(P.primary, .35), btn_sh='inset 0 1px 0 rgba(255,255,255,.35),0 3px 6px rgba(60,40,10,.35)',
                             in_bg='linear-gradient(180deg,%s,%s)' % (shade(P.surface, .04), P.surface), in_sh='inset 0 2px 4px rgba(60,40,10,.25)', ic_r='50%',
                             ic_bg='linear-gradient(145deg,%s,%s)' % (tint(P.primary, .6), mix(P.primary, '#ffffff', .25)), ic_fg=shade(P.primary, .35), hd_bg='linear-gradient(180deg,%s,%s)' % (tint(P.surface, .5), P.surface)), extra='')


def blocks(P, o):
    a2 = o.get('acc2') or P.acc2
    return dict(radius=14, button='soft', width=1180, sections=_sec(hero='band', features='', pricing='bold', testimonials='marked', faq='boxed'),
                tokens=_base(P, solid=True, card_bg=mix(P.surface, P.primary, .08), card_bd='2px solid ' + P.primary, card_sh='none', hov='translateY(-4px)', hov_sh='none',
                             btn_sh='none', ic_bg=a2, ic_fg=on_color(a2), ic_r='12px', eb_bg=a2, cta_bd='0 solid transparent'),
                extra='.nb-feature:nth-child(3n+2){background:%s;border-color:%s}.nb-feature:nth-child(3n+3){background:%s}' % (mix(P.surface, a2, .22), shade(a2, .35), mix(P.surface, P.text, .06)))


def access(P, o):
    return dict(radius=8, button='soft', width=1100, sections=_sec(hero='start', features='plain', pricing='flat', testimonials='plain', faq='plain', cta='bar', site_header='minimal'),
                tokens=_base(P, solid=True, card_bd='2px solid ' + P.text, card_sh='none', hov='none', hov_sh='none', btn_bw='3px', btn_bc=P.text, btn_sh='none', btn_hov='none',
                             in_bd='2px solid ' + P.text, ic_bg='transparent', ic_fg=P.primary, hl_bd='4px solid ' + P.primary, hl_sh='none', cta_r='10px'),
                extra='*:focus-visible{outline:3px solid %s;outline-offset:3px}.nb-text,.nb-sub{font-size:1.08rem;line-height:1.95}.nb-btn{min-height:48px}' % P.primary)


def film(P, o):
    return dict(radius=6, button='soft', width=1100, sections=_sec(hero='minimal', features='plain', pricing='flat', testimonials='big', faq='plain', cta='outline', site_header='centered'),
                tokens=_base(P, a=shade(P.primary, .25), b=shade(P.primary, .55), page_bg='radial-gradient(120%% 80%% at 50%% 0,%s 0,transparent 70%%),%s' % (rgba('#fff3d1', .7), P.bg),
                             card_bg=tint(P.surface, .0), card_bd='1px solid var(--line)', card_sh='0 10px 28px -20px rgba(80,50,10,.5)', hov='none', btn_sh='none', ic_r='50%',
                             ic_bg=rgba(P.primary, .14), head_w='700'),
                extra='body{box-shadow:inset 0 0 160px rgba(80,50,10,.16)}.nb-hero{filter:sepia(.12)}')


def studio(P, o):
    return dict(radius=20, button='round', width=1160, sections=_sec(hero='minimal', features='bento', pricing='flat', faq='columns', site_header='minimal'),
                tokens=_base(P, page_bg='radial-gradient(70%% 55%% at 50%% 0,%s 0,transparent 72%%),%s' % ('#ffffff' if not P.dark else tint(P.bg, .12), P.bg), card_sh='0 30px 60px -34px rgba(0,0,0,.35)',
                             hov='translateY(-4px)', btn_sh='0 12px 24px -12px rgba(0,0,0,.45)', ic_r='16px', cta_r='28px'), extra='')


def calm(P, o):
    s = soft(P, o)
    s['radius'] = 30
    s['tokens'].update(card_sh='0 24px 56px -34px rgba(60,70,90,.4)', gap='26px', cta_r='40px', sec_py='clamp(56px,8vw,104px)', head_w='700')
    s['sections'] = _sec(hero='minimal', features='', testimonials='marked', faq='boxed', cta='split', site_header='floating')
    return s


def ainative(P, o):
    return dict(radius=14, button='soft', width=1160, sections=_sec(hero='minimal', features='', pricing='glow', faq='boxed', site_header='minimal'),
                tokens=_base(P, a=P.primary, b=P.acc2, card_bd='1px solid var(--line)', card_sh='0 1px 2px rgba(0,0,0,.04)', hov='translateY(-2px)', hov_sh='0 14px 36px -20px %s' % rgba(P.primary, .5),
                             btn_sh='0 8px 22px -10px %s' % rgba(P.primary, .7), hl_bd='1px solid ' + P.primary, hl_sh='0 0 0 5px %s,0 24px 50px -28px %s' % (rgba(P.primary, .14), rgba(P.primary, .6)),
                             ic_r='10px', ic_bg='linear-gradient(135deg,%s,%s)' % (rgba(P.primary, .2), rgba(P.acc2, .16))), extra='')


ARCH = {k: v for k, v in dict(flat=flat, soft=soft, glass=glass, vision=vision, neu=neu, clay=clay, tactile=tactile, brut=brut, raw=raw, dark=dark, neon=neon, hud=hud, glitch=glitch,
                              gradient=gradient, vapor=vapor, editorial=editorial, swiss=swiss, exmin=exmin, kinetic=kinetic, story=story, luxury=luxury, organic=organic,
                              earth=earth, memphis=memphis, pixel=pixel, dash=dash, paper=paper, sketch=sketch, corporate=corporate, maximal=maximal, layers=layers,
                              material=material, skeuo=skeuo, blocks=blocks, access=access, film=film, studio=studio, calm=calm, ainative=ainative).items()}


def build(arch: str, P: Pal, o: dict) -> dict:
    """⇒ {tokens, extra(پُرشده), sections, radius, button, width}"""
    out = ARCH[arch](P, o)
    out['extra'] = fill(out.get('extra', ''), P)
    return out
