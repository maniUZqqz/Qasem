# -*- coding: utf-8 -*-
"""چهارده سبکِ طراحی. هر سبک = توکن‌های طراحی (رنگ، قلم، گردی، سایه، تاری، حاشیه، فاصله، حرکت) + چیدمانِ پیش‌فرضِ بخش‌ها.

· «theme»: همان چیزی که به پوستهٔ سایت (SiteTheme) می‌نشیند: رنگ‌ها، قلم‌های فارسی‌پذیر، شکلِ دکمه، گردی و پهنای صفحه.
· «tokens»: متغیرهای `--st-*` که لایهٔ CSSِ سبک (css.py) به کلاس‌های `nb-*` وصل می‌کند.
· «sections»: کدام «چیدمانِ بخش» (variants.py) برای هر بلوک با این سبک جور است؛ با «اعمالِ سبک روی صفحه» می‌نشیند.
· «extra»: چند قاعدهٔ CSS که فقط همین سبک دارد (مثلاً تاریِ پشتِ شیشه یا سایهٔ سخت).
· «uiux»: ردیف‌های مرجع در دادهٔ ui-ux-pro-max (MIT) — شناسهٔ سبک، نامِ جفتِ قلم و نوعِ پالت — تا معلوم باشد تعریف از کجا آمده.

همهٔ جفت‌رنگ‌ها در آزمون با نسبتِ تباینِ WCAG سنجیده می‌شوند (متن/زمینه ≥ ۴٫۵ و متنِ دکمه/رنگِ اصلی ≥ ۴٫۵).
قلم‌ها همه فارسی‌پذیرند (پ چ ژ گ ک ی و رقم‌های فارسی در فایلِ قلم هست؛ آزمونِ tests_styles این را با fontTools می‌سنجد).
"""

MESH_LIGHT = ('radial-gradient(60% 50% at 10% 6%,#cdbfff 0,transparent 62%),radial-gradient(50% 45% at 92% 10%,#a8e6ff 0,transparent 62%),'
              'radial-gradient(55% 50% at 78% 96%,#ffc6e6 0,transparent 62%),#e9edff')

STYLES = {
    'glassmorphism': {
        'label': 'شیشه‌ای', 'en': 'Glassmorphism', 'mood': 'روشن، شفاف و لایه‌لایه',
        'desc': 'کارت‌های نیمه‌شفافِ مات‌شده روی پس‌زمینهٔ رنگیِ ملایم؛ حسِ عمق و سبکی. برای اپ، فناوری و خدماتِ امروزی.',
        'tags': ['شیشه', 'شفاف', 'روشن', 'اپ', 'فناوری', 'امروزی', 'glass'],
        'theme': {'colors': {'primary': '#5b4bdb', 'on_primary': '#ffffff', 'text': '#1b1b3a', 'text2': '#3d3d63', 'muted': '#5f5f86',
                             'line': '#d3d6f3', 'bg': '#e9edff', 'surface': '#ffffff'},
                  'font_head': 'cairo', 'font_body': 'vazirmatn', 'button': 'round', 'radius': 22, 'width': 1140},
        'tokens': {'page_bg': MESH_LIGHT, 'page_att': 'fixed', 'card_bg': 'rgba(255,255,255,.55)', 'card_bd': '1px solid rgba(255,255,255,.75)',
                   'card_sh': '0 14px 44px -16px rgba(60,50,160,.38)', 'bf': 'blur(18px) saturate(1.5)', 'hov_sh': '0 20px 50px -16px rgba(60,50,160,.5)',
                   'head_w': '800', 'btn_sh': '0 12px 28px -10px rgba(91,75,219,.65)', 'hd_bg': 'rgba(255,255,255,.55)',
                   'hd_bf': 'blur(18px) saturate(1.5)', 'hd_bd': '1px solid rgba(255,255,255,.7)', 'in_bg': 'rgba(255,255,255,.7)',
                   'in_bd': '1px solid rgba(255,255,255,.9)', 'ic_bg': 'linear-gradient(135deg,rgba(255,255,255,.9),rgba(205,191,255,.6))',
                   'eb_bg': 'rgba(255,255,255,.55)', 'hero_bg': 'linear-gradient(135deg,#5b4bdb,#3f8cff 60%,#27c4d9)'},
        'sections': {'hero': 'framed', 'features': '', 'pricing': 'glow', 'testimonials': '', 'faq': 'boxed', 'cta': 'split', 'site_header': 'floating'},
        'extra': '.nb-hero .nb-hero-copy.is-center{text-shadow:0 2px 24px rgba(0,0,0,.18)}'
                 '.nb-feature-icon{box-shadow:inset 0 1px 0 rgba(255,255,255,.9)}'
                 '.nb-btn.is-outline{background:rgba(255,255,255,.4);-webkit-backdrop-filter:blur(8px);backdrop-filter:blur(8px)}',
        'uiux': {'style_id': 'glassmorphism', 'font_pairing': 'Modern Professional', 'palette': 'SaaS (General)'},
    },
    'claymorphism': {
        'label': 'خمیری', 'en': 'Claymorphism', 'mood': 'نرم، سه‌بعدی و بازیگوش',
        'desc': 'اجزای تپل و بادکرده مثلِ خمیر؛ حاشیهٔ ضخیم، سایهٔ دوگانه و رنگ‌های پاستلی. برای کودک، آموزش، خدماتِ دوستانه.',
        'tags': ['خمیری', 'نرم', 'بازیگوش', 'کودک', 'آموزش', 'پاستلی', 'clay'],
        'theme': {'colors': {'primary': '#c34025', 'on_primary': '#ffffff', 'text': '#3b2a26', 'text2': '#5a443d', 'muted': '#7d6259',
                             'line': '#f3d6cb', 'bg': '#fff0e8', 'surface': '#ffffff'},
                  'font_head': 'baloo', 'font_body': 'vazirmatn', 'button': 'round', 'radius': 28, 'width': 1140},
        'tokens': {'card_bd': '3px solid #ffffff', 'card_bg': '#ffffff',
                   'card_sh': 'inset -6px -6px 14px rgba(195,90,62,.10),inset 6px 6px 14px rgba(255,255,255,.95),10px 14px 28px -8px rgba(195,90,62,.28)',
                   'hov': 'translateY(-6px) rotate(-.4deg)', 'mo': 'transform .3s cubic-bezier(.34,1.56,.64,1),box-shadow .3s ease',
                   'btn_sh': 'inset -3px -4px 8px rgba(0,0,0,.14),inset 3px 3px 8px rgba(255,255,255,.45),6px 8px 16px -4px rgba(195,64,37,.55)',
                   'btn_bw': '0', 'btn_mo': 'transform .25s cubic-bezier(.34,1.56,.64,1)', 'btn_hov': 'translateY(-3px) scale(1.03)', 'head_w': '800',
                   'ic_r': '50%', 'ic_bg': 'linear-gradient(145deg,#ffd9c9,#ffc0a5)', 'ic_fg': '#c34025', 'gap': '26px',
                   'in_bd': '3px solid #ffffff', 'in_bg': '#fff7f2', 'in_sh': 'inset 3px 3px 8px rgba(195,90,62,.14)',
                   'hero_bg': 'linear-gradient(135deg,#ff9a76,#ff6f61 55%,#c34025)', 'eb_bg': 'rgba(255,255,255,.35)'},
        'sections': {'hero': 'framed', 'features': '', 'pricing': '', 'testimonials': 'marked', 'faq': 'boxed', 'cta': '', 'site_header': 'floating'},
        'extra': '.nb-feature:nth-child(3n+2) .nb-feature-icon{background:linear-gradient(145deg,#d8f1ff,#aee0fb);color:#1d78a8}'
                 '.nb-feature:nth-child(3n+3) .nb-feature-icon{background:linear-gradient(145deg,#e4ffd9,#bff0a5);color:#3a8a1d}'
                 '.nb-eyebrow{border:2px solid #fff}',
        'uiux': {'style_id': 'claymorphism', 'font_pairing': 'Playful Creative', 'palette': 'Kids Learning (ABC & Math)'},
    },
    'neumorphism': {
        'label': 'نرم‌برجسته', 'en': 'Neumorphism', 'mood': 'تک‌رنگ، برجسته و آرام',
        'desc': 'عنصرها از خودِ زمینه بیرون زده یا فرو رفته‌اند؛ سایهٔ روشن و تیرهٔ هم‌زمان. برای داشبورد، ابزار و برندِ آرام.',
        'tags': ['برجسته', 'نرم', 'آرام', 'ابزار', 'neumorphism', 'تک‌رنگ'],
        'theme': {'colors': {'primary': '#3752c4', 'on_primary': '#ffffff', 'text': '#27304a', 'text2': '#444e6d', 'muted': '#5b6583',
                             'line': '#cfd5e1', 'bg': '#e4e8ef', 'surface': '#e4e8ef'},
                  'font_head': 'plex', 'font_body': 'plex', 'button': 'soft', 'radius': 22, 'width': 1100},
        'tokens': {'card_bg': '#e4e8ef', 'card_bd': '0 solid transparent', 'card_sh': '10px 10px 22px #c4c9d4,-10px -10px 22px #ffffff',
                   'hov': 'translateY(-2px)', 'hov_sh': '12px 12px 26px #c0c5d1,-12px -12px 26px #ffffff', 'btn_bw': '0',
                   'btn_sh': '7px 7px 16px #b7bdcc,-7px -7px 16px #ffffff', 'head_w': '700', 'head_ls': '0',
                   'in_bg': '#e4e8ef', 'in_bd': '0 solid transparent', 'in_sh': 'inset 6px 6px 12px #c4c9d4,inset -6px -6px 12px #ffffff',
                   'ic_bg': '#e4e8ef', 'ic_fg': '#3752c4', 'ic_r': '50%', 'hd_bg': '#e4e8ef', 'hd_bd': '0 solid transparent',
                   'hero_bg': '#e4e8ef', 'hero_fg': '#27304a', 'hero_btn_bg': '#3752c4', 'hero_btn_fg': '#ffffff', 'eb_bg': '#e4e8ef',
                   'cta_bg': '#e4e8ef', 'cta_fg': '#27304a', 'cta_sh': '12px 12px 28px #c0c5d1,-12px -12px 28px #ffffff', 'cta_bd': '0 solid transparent',
                   'hl_bd': '0 solid transparent', 'hl_sh': 'inset 8px 8px 16px #c4c9d4,inset -8px -8px 16px #ffffff'},
        'sections': {'hero': 'minimal', 'features': '', 'pricing': 'flat', 'testimonials': '', 'faq': 'boxed', 'cta': '', 'site_header': 'minimal'},
        'extra': '.nb-btn:active{box-shadow:inset 5px 5px 10px #b7bdcc,inset -5px -5px 10px #ffffff;transform:none}'
                 '.nb-feature-icon{box-shadow:inset 4px 4px 8px #c4c9d4,inset -4px -4px 8px #ffffff}'
                 '.nb-btn.is-outline{color:var(--brand);background:#e4e8ef}'
                 '.nb-faq-item{box-shadow:6px 6px 14px #c4c9d4,-6px -6px 14px #fff}'
                 '.nb-hero .nb-sub,.nb-hero .nb-eyebrow{color:#27304a}',
        'uiux': {'style_id': 'neumorphism', 'font_pairing': 'Financial Trust', 'palette': 'Productivity Tool'},
    },
    'neo-brutalism': {
        'label': 'نئوبروتالیسم', 'en': 'Neo-brutalism', 'mood': 'جسور، رنگی و بی‌پروا',
        'desc': 'حاشیهٔ سیاهِ ضخیم، سایهٔ سختِ ۴۵ درجه، رنگ‌های تخت و درخشان، نوشتهٔ درشت. برای برندِ جوان و کارِ خلاقانه.',
        'tags': ['جسور', 'نئوبروتالیسم', 'رنگی', 'جوان', 'خلاق', 'brutalism', 'استارتاپ'],
        'theme': {'colors': {'primary': '#c1121f', 'on_primary': '#ffffff', 'text': '#000000', 'text2': '#1a1a1a', 'muted': '#3f3f3f',
                             'line': '#000000', 'bg': '#fff4d6', 'surface': '#ffffff'},
                  'font_head': 'kufi', 'font_body': 'vazirmatn', 'button': 'square', 'radius': 0, 'width': 1180},
        'tokens': {'card_bd': '3px solid #000', 'card_sh': '6px 6px 0 #000', 'card_r': '0', 'hov': 'translate(-3px,-3px)',
                   'hov_sh': '9px 9px 0 #000', 'mo': 'transform .12s ease,box-shadow .12s ease', 'head_w': '900', 'head_ls': '0',
                   'btn_bw': '3px', 'btn_sh': '5px 5px 0 #000', 'btn_bc': '#000', 'btn_hov': 'translate(-2px,-2px)', 'btn_mo': 'transform .1s,box-shadow .1s',
                   'in_bd': '3px solid #000', 'in_r': '0', 'in_bg': '#fff', 'ic_bg': '#ffd23f', 'ic_fg': '#000', 'ic_r': '0',
                   'eb_bg': '#ffd23f', 'eb_r': '0', 'hd_bd': '3px solid #000', 'hd_bg': '#fff4d6', 'hl_bd': '3px solid #000', 'hl_sh': '8px 8px 0 #000',
                   'hero_bg': '#ffd23f', 'hero_fg': '#000', 'hero_btn_bg': '#ff5d5d', 'hero_btn_fg': '#000',
                   'cta_bg': '#4d9bff', 'cta_fg': '#000', 'cta_bd': '3px solid #000', 'cta_sh': '8px 8px 0 #000', 'cta_r': '0', 'sec_py': 'clamp(44px,6vw,76px)'},
        'sections': {'hero': 'band', 'features': '', 'pricing': 'bold', 'testimonials': 'plain', 'faq': 'boxed', 'cta': '', 'site_header': ''},
        'extra': '.nb-feature:nth-child(3n+1){background:#fff}.nb-feature:nth-child(3n+2){background:#b8f5d3}.nb-feature:nth-child(3n+3){background:#ffc2e0}'
                 '.nb-btn:hover{box-shadow:7px 7px 0 #000}.nb-btn:active{transform:translate(3px,3px);box-shadow:0 0 0 #000}'
                 '.nb-btn.is-outline{background:#fff;color:#000;border-color:#000}.nb-btn.is-ghost{border-color:#000;color:#000;background:#fff}'
                 '.nb-hero .nb-sub{opacity:1}.nb-eyebrow{border:3px solid #000;transform:rotate(-2deg)}'
                 '.nb-nav a:hover,.nb-nav a.on{background:#ffd23f;color:#000;outline:2px solid #000}',
        'uiux': {'style_id': 'neubrutalism', 'font_pairing': 'Neubrutalist Bold', 'palette': 'Creative Agency'},
    },
    'bento-grid': {
        'label': 'شبکهٔ بنتو', 'en': 'Bento grid', 'mood': 'ماژولار، تمیز و اپل‌مانند',
        'desc': 'کاشی‌های گرد با اندازه‌های متفاوت کنارِ هم، مثلِ جعبهٔ بنتو؛ فضای خالیِ سخاوتمندانه. برای معرفیِ امکاناتِ محصول.',
        'tags': ['بنتو', 'شبکه', 'کاشی', 'محصول', 'اپ', 'امکانات', 'bento', 'مدولار'],
        'theme': {'colors': {'primary': '#006cd9', 'on_primary': '#ffffff', 'text': '#111827', 'text2': '#374151', 'muted': '#5b6472',
                             'line': '#e3e5ea', 'bg': '#f3f4f6', 'surface': '#ffffff'},
                  'font_head': 'cairo', 'font_body': 'vazirmatn', 'button': 'round', 'radius': 26, 'width': 1180},
        'tokens': {'card_bd': '1px solid rgba(17,24,39,.06)', 'card_sh': '0 1px 2px rgba(17,24,39,.04),0 10px 30px -18px rgba(17,24,39,.22)',
                   'hov': 'translateY(-3px) scale(1.012)', 'gap': '16px', 'head_w': '800', 'head_ls': '-.02em', 'btn_sh': '0 8px 20px -10px rgba(0,108,217,.7)',
                   'ic_r': '16px', 'ic_bg': 'color-mix(in srgb,var(--brand) 12%,#fff)', 'sec_py': 'clamp(48px,7vw,92px)',
                   'hero_bg': 'linear-gradient(160deg,#0a1b3d,#0b4aa3 70%,#006cd9)', 'cta_bg': 'linear-gradient(135deg,#0a1b3d,#006cd9)'},
        'sections': {'hero': '', 'features': 'bento', 'pricing': '', 'testimonials': '', 'faq': 'columns', 'cta': 'split', 'site_header': ''},
        'extra': '.nb-hero{margin:14px;border-radius:32px}.nb-hero>.nb-wrap{padding-inline:26px}'
                 '.nb-feature{padding:28px 26px}.nb-features .nb-feature-title{font-size:1.2rem}'
                 '.nb-features.nbv-bento .nb-feature:nth-child(1){background:linear-gradient(160deg,color-mix(in srgb,var(--brand) 14%,#fff),#fff)}',
        'uiux': {'style_id': 'bento-box-grid', 'font_pairing': 'Friendly SaaS', 'palette': 'SaaS (General)'},
    },
    'minimalism': {
        'label': 'مینیمال', 'en': 'Minimalism', 'mood': 'ساده، سفید و خوانا',
        'desc': 'فضای خالیِ فراوان، یک رنگِ اصلی، بدونِ سایه و تزیین؛ فقط محتوا. برای پرتفولیو، مشاوره و کسب‌وکارِ شخصی.',
        'tags': ['مینیمال', 'ساده', 'سفید', 'پرتفولیو', 'مشاوره', 'minimal', 'خلوت'],
        'theme': {'colors': {'primary': '#111111', 'on_primary': '#ffffff', 'text': '#111111', 'text2': '#3a3a3a', 'muted': '#6b6b6b',
                             'line': '#e5e5e5', 'bg': '#ffffff', 'surface': '#fafafa'},
                  'font_head': 'plex', 'font_body': 'plex', 'button': 'soft', 'radius': 6, 'width': 1060},
        'tokens': {'card_bg': '#ffffff', 'card_bd': '1px solid #e5e5e5', 'card_sh': 'none', 'hov': 'none', 'hov_sh': 'none', 'head_w': '600', 'head_ls': '-.015em',
                   'btn_sh': 'none', 'btn_hov': 'none', 'btn_filter': 'none', 'sec_py': 'clamp(56px,9vw,120px)', 'gap': '28px',
                   'ic_bg': 'transparent', 'ic_fg': '#111', 'ic_r': '0', 'eb_bg': 'transparent', 'eb_r': '0', 'hd_bg': '#ffffff',
                   'hero_bg': '#ffffff', 'hero_fg': '#111111', 'hero_btn_bg': '#111111', 'hero_btn_fg': '#ffffff', 'cta_bg': '#111111', 'cta_fg': '#ffffff',
                   'cta_r': '8px', 'hl_bd': '1px solid #111', 'hl_sh': 'none'},
        'sections': {'hero': 'minimal', 'features': 'list', 'pricing': 'flat', 'testimonials': 'plain', 'faq': 'plain', 'cta': 'outline', 'site_header': 'minimal'},
        'extra': '.nb-feature-icon{width:auto;height:auto;margin-bottom:10px}.nb-eyebrow{padding:0;font-weight:500;opacity:.7}'
                 '.nb-text a,.nb-nav a:hover{text-underline-offset:4px}.nb-hero .nb-btn.is-ghost{color:#111}',
        'uiux': {'style_id': 'minimalism-and-swiss-style', 'font_pairing': 'Minimal Swiss', 'palette': 'Portfolio/Personal'},
    },
    'aurora': {
        'label': 'شفق (گرادیانِ مش)', 'en': 'Aurora / gradient mesh', 'mood': 'تیره، درخشان و رنگارنگ',
        'desc': 'پس‌زمینهٔ تیرهٔ آسمانی با لکه‌های گرادیانِ بنفش، فیروزه‌ای و صورتی؛ حسِ آینده و هوش مصنوعی.',
        'tags': ['شفق', 'گرادیان', 'تیره', 'هوش مصنوعی', 'فناوری', 'aurora', 'مش'],
        'theme': {'colors': {'primary': '#9d8cff', 'on_primary': '#0b1020', 'text': '#eef2ff', 'text2': '#c9d1f2', 'muted': '#9aa6d4',
                             'line': '#2a3358', 'bg': '#0b1020', 'surface': '#141a33'},
                  'font_head': 'cairo', 'font_body': 'vazirmatn', 'button': 'round', 'radius': 20, 'width': 1140},
        'tokens': {'page_bg': 'radial-gradient(55% 40% at 15% 0%,rgba(124,92,255,.35) 0,transparent 70%),radial-gradient(45% 40% at 90% 8%,rgba(36,200,216,.28) 0,transparent 70%),'
                              'radial-gradient(50% 45% at 70% 100%,rgba(255,92,170,.22) 0,transparent 70%),#0b1020', 'page_att': 'fixed',
                   'card_bg': 'rgba(255,255,255,.05)', 'card_bd': '1px solid rgba(255,255,255,.12)', 'card_sh': '0 18px 50px -24px rgba(0,0,0,.8)',
                   'bf': 'blur(14px)', 'hov_sh': '0 22px 60px -22px rgba(157,140,255,.45)', 'head_w': '800', 'btn_sh': '0 10px 30px -10px rgba(157,140,255,.8)',
                   'hd_bg': 'rgba(11,16,32,.6)', 'hd_bf': 'blur(14px)', 'hd_bd': '1px solid rgba(255,255,255,.08)',
                   'in_bg': 'rgba(255,255,255,.06)', 'in_bd': '1px solid rgba(255,255,255,.14)', 'ic_bg': 'linear-gradient(135deg,rgba(157,140,255,.35),rgba(36,200,216,.25))',
                   'ic_fg': '#ffffff', 'eb_bg': 'rgba(255,255,255,.08)',
                   'hero_bg': 'transparent', 'hero_fg': '#eef2ff', 'hero_btn_bg': '#9d8cff', 'hero_btn_fg': '#0b1020',
                   'cta_bg': 'linear-gradient(135deg,rgba(124,92,255,.55),rgba(36,200,216,.4))', 'cta_fg': '#ffffff', 'cta_bd': '1px solid rgba(255,255,255,.18)'},
        'sections': {'hero': 'aurora', 'features': 'bento', 'pricing': 'glow', 'testimonials': '', 'faq': 'boxed', 'cta': 'split', 'site_header': 'floating'},
        'extra': '.nb-hero-title{background:linear-gradient(100deg,#ffffff,#c9b8ff 45%,#7ee7f5);-webkit-background-clip:text;background-clip:text;color:transparent}'
                 '.nb-btn.is-ghost{color:#eef2ff}.nb-plan-price{color:#c9b8ff}',
        'uiux': {'style_id': 'aurora-ui', 'font_pairing': 'Tech Startup', 'palette': 'AI/Chatbot Platform'},
    },
    'dark-luxury': {
        'label': 'لوکسِ تیره', 'en': 'Dark luxury', 'mood': 'مشکی، طلایی و باوقار',
        'desc': 'زمینهٔ مشکیِ عمیق، حاشیه‌های نازکِ طلایی، قلمِ ادبی و فاصله‌های بلند. برای برندِ لوکس، جواهر، معماری و خدماتِ ویژه.',
        'tags': ['لوکس', 'تیره', 'طلایی', 'مشکی', 'برند', 'luxury', 'جواهر', 'پریمیوم'],
        'theme': {'colors': {'primary': '#d4af37', 'on_primary': '#0b0b0b', 'text': '#f4eee3', 'text2': '#d6cdbd', 'muted': '#a39a8c',
                             'line': '#2f2c26', 'bg': '#0b0b0b', 'surface': '#151515'},
                  'font_head': 'amiri', 'font_body': 'vazirmatn', 'button': 'square', 'radius': 3, 'width': 1160},
        'tokens': {'card_bg': '#151515', 'card_bd': '1px solid rgba(212,175,55,.28)', 'card_sh': '0 24px 60px -30px rgba(0,0,0,.9)', 'hov': 'translateY(-4px)',
                   'hov_sh': '0 28px 70px -28px rgba(212,175,55,.35)', 'head_w': '700', 'head_ls': '.01em', 'btn_bw': '1px',
                   'btn_sh': 'none', 'btn_bc': '#d4af37', 'sec_py': 'clamp(60px,9vw,120px)', 'ic_bg': 'transparent', 'ic_fg': '#d4af37',
                   'ic_r': '0', 'eb_bg': 'transparent', 'eb_r': '0', 'hd_bg': '#0b0b0b', 'hd_bd': '1px solid rgba(212,175,55,.25)',
                   'in_bg': '#0f0f0f', 'in_bd': '1px solid #2f2c26', 'in_r': '2px',
                   'hero_bg': 'radial-gradient(70% 90% at 80% 0%,rgba(212,175,55,.22) 0,transparent 65%),linear-gradient(180deg,#121212,#0b0b0b)',
                   'hero_fg': '#f4eee3', 'hero_btn_bg': '#d4af37', 'hero_btn_fg': '#0b0b0b',
                   'cta_bg': 'linear-gradient(135deg,#1b1608,#0b0b0b)', 'cta_fg': '#f4eee3', 'cta_bd': '1px solid rgba(212,175,55,.4)', 'cta_r': '3px',
                   'hl_bd': '1px solid #d4af37', 'hl_sh': '0 28px 70px -28px rgba(212,175,55,.4)'},
        'sections': {'hero': 'start', 'features': 'numbered', 'pricing': 'flat', 'testimonials': 'big', 'faq': 'plain', 'cta': 'outline', 'site_header': 'minimal'},
        'extra': '.nb-eyebrow{letter-spacing:.14em;font-size:.78rem;color:#d4af37}'
                 '.nb-hero-title{font-weight:700}.nb-btn.is-ghost{color:#f4eee3;border-color:rgba(244,238,227,.35)}'
                 '.nb-btn.is-outline{color:#d4af37;border-color:#d4af37}.nb-plan-price{color:#d4af37}',
        'uiux': {'style_id': 'dark-mode-oled', 'font_pairing': 'Luxury Serif', 'palette': 'Luxury/Premium Brand'},
    },
    'soft-pastel': {
        'label': 'پاستلیِ نرم', 'en': 'Soft pastel', 'mood': 'ملایم، دوستانه و گرد',
        'desc': 'رنگ‌های پاستلیِ هماهنگ، گوشه‌های بسیار گرد و سایه‌های رنگیِ ملایم. برای سلامت، زیبایی، کودک و خدماتِ مهربان.',
        'tags': ['پاستلی', 'نرم', 'ملایم', 'زیبایی', 'سلامت', 'soft', 'دوستانه'],
        'theme': {'colors': {'primary': '#6f55c4', 'on_primary': '#ffffff', 'text': '#3a2f4a', 'text2': '#594b70', 'muted': '#746887',
                             'line': '#eddcf0', 'bg': '#fdf3f8', 'surface': '#ffffff'},
                  'font_head': 'baloo', 'font_body': 'vazirmatn', 'button': 'round', 'radius': 26, 'width': 1120},
        'tokens': {'card_bd': '1px solid rgba(111,85,196,.08)', 'card_sh': '0 12px 34px -16px rgba(111,85,196,.30)', 'hov': 'translateY(-4px)',
                   'hov_sh': '0 20px 44px -16px rgba(111,85,196,.38)', 'head_w': '700', 'head_ls': '0', 'btn_sh': '0 10px 22px -10px rgba(111,85,196,.6)',
                   'ic_r': '50%', 'ic_bg': 'linear-gradient(145deg,#ffe3d8,#ffd0e4)', 'ic_fg': '#c24d86', 'gap': '24px',
                   'hero_bg': 'linear-gradient(135deg,#c9b8f6,#f7b6d6 55%,#ffd2b8)', 'hero_fg': '#3a2f4a', 'hero_btn_bg': '#6f55c4', 'hero_btn_fg': '#ffffff',
                   'cta_bg': 'linear-gradient(135deg,#c9b8f6,#f7b6d6)', 'cta_fg': '#3a2f4a', 'eb_bg': 'rgba(255,255,255,.55)',
                   'in_bd': '1px solid #eddcf0', 'in_r': '16px'},
        'sections': {'hero': 'framed', 'features': '', 'pricing': '', 'testimonials': 'marked', 'faq': 'boxed', 'cta': '', 'site_header': 'floating'},
        'extra': '.nb-feature:nth-child(3n+2) .nb-feature-icon{background:linear-gradient(145deg,#d9f4e6,#c2ecd9);color:#2e8a62}'
                 '.nb-feature:nth-child(3n+3) .nb-feature-icon{background:linear-gradient(145deg,#d9e8ff,#c4dcff);color:#3a6fd0}'
                 '.nb-hero .nb-btn.is-ghost{color:#3a2f4a;border-color:rgba(58,47,74,.35)}',
        'uiux': {'style_id': 'soft-ui-evolution', 'font_pairing': 'Soft Rounded', 'palette': 'Beauty/Spa/Wellness Service'},
    },
    'corporate-clean': {
        'label': 'رسمی و تمیز', 'en': 'Corporate clean', 'mood': 'مطمئن، منظم و حرفه‌ای',
        'desc': 'سرمه‌ای و سفید، شبکهٔ منظم، سایهٔ کم و تأکید بر اعتماد. برای شرکت، خدماتِ مالی، حقوقی و B2B.',
        'tags': ['رسمی', 'شرکتی', 'سازمانی', 'اعتماد', 'corporate', 'تمیز', 'B2B'],
        'theme': {'colors': {'primary': '#0b5cab', 'on_primary': '#ffffff', 'text': '#0f2742', 'text2': '#34495f', 'muted': '#5b6c82',
                             'line': '#d9e2ee', 'bg': '#f4f7fb', 'surface': '#ffffff'},
                  'font_head': 'plex', 'font_body': 'vazirmatn', 'button': 'soft', 'radius': 10, 'width': 1160},
        'tokens': {'card_bd': '1px solid #d9e2ee', 'card_sh': '0 1px 2px rgba(15,39,66,.05),0 8px 22px -16px rgba(15,39,66,.25)', 'hov': 'translateY(-2px)',
                   'hov_sh': '0 14px 30px -18px rgba(15,39,66,.35)', 'head_w': '700', 'head_ls': '0', 'btn_sh': '0 6px 14px -8px rgba(11,92,171,.7)',
                   'ic_r': '10px', 'ic_bg': 'color-mix(in srgb,var(--brand) 10%,#fff)', 'gap': '22px',
                   'hero_bg': 'linear-gradient(135deg,#0a2a52,#0b5cab)', 'cta_bg': 'linear-gradient(135deg,#0a2a52,#0b5cab)', 'cta_r': '14px',
                   'eb_bg': 'rgba(255,255,255,.14)', 'eb_r': '6px', 'hd_bg': '#ffffff', 'in_r': '8px'},
        'sections': {'hero': '', 'features': '', 'pricing': 'flat', 'testimonials': '', 'faq': 'boxed', 'cta': 'split', 'site_header': ''},
        'extra': '.nb-feature,.nb-plan,.nb-quote{border-top:3px solid var(--brand)}.nb-plan.is-featured{border-top-width:4px}'
                 '.nb-nav a{border-radius:6px}',
        'uiux': {'style_id': 'flat-design', 'font_pairing': 'Corporate Trust', 'palette': 'B2B Service'},
    },
    'editorial': {
        'label': 'مجله‌ای', 'en': 'Editorial / magazine', 'mood': 'ادبی، چاپی و تیترمحور',
        'desc': 'تیترهای درشتِ قلمِ ادبی، خطوطِ جداکنندهٔ نازک، رنگِ کاغذی و فاصله‌گذاریِ چاپی. برای نشریه، بلاگ، فرهنگ و روایت.',
        'tags': ['مجله', 'نشریه', 'ادبی', 'بلاگ', 'فرهنگ', 'editorial', 'کاغذی', 'روایت'],
        'theme': {'colors': {'primary': '#b3261e', 'on_primary': '#ffffff', 'text': '#1a1814', 'text2': '#3d3a33', 'muted': '#6a6558',
                             'line': '#cfc8b8', 'bg': '#faf6ee', 'surface': '#fffdf8'},
                  'font_head': 'amiri', 'font_body': 'vazirmatn', 'button': 'square', 'radius': 0, 'width': 1100},
        'tokens': {'card_bg': 'transparent', 'card_bd': '0 solid transparent', 'card_sh': 'none', 'card_r': '0', 'hov': 'none', 'hov_sh': 'none',
                   'head_w': '700', 'head_ls': '0', 'btn_bw': '1px', 'btn_sh': 'none', 'btn_hov': 'none', 'ic_bg': 'transparent', 'ic_fg': '#b3261e', 'ic_r': '0',
                   'eb_bg': 'transparent', 'eb_r': '0', 'hd_bg': '#faf6ee', 'hd_bd': '2px solid #1a1814', 'sec_py': 'clamp(52px,8vw,104px)', 'gap': '34px',
                   'hero_bg': '#faf6ee', 'hero_fg': '#1a1814', 'hero_btn_bg': '#1a1814', 'hero_btn_fg': '#faf6ee',
                   'cta_bg': '#1a1814', 'cta_fg': '#faf6ee', 'cta_r': '0', 'in_r': '0', 'in_bg': '#fffdf8', 'in_bd': '1px solid #1a1814',
                   'hl_bd': '2px solid #1a1814', 'hl_sh': 'none'},
        'sections': {'hero': 'start', 'features': 'numbered', 'pricing': 'flat', 'testimonials': 'big', 'faq': 'plain', 'cta': 'bar', 'site_header': 'centered'},
        'extra': '.nb-feature,.nb-quote,.nb-faq-item{border-top:2px solid #1a1814;padding-top:16px;padding-inline:0}'
                 '.nb-plan{border:1px solid #1a1814}.nb-eyebrow{text-transform:uppercase;letter-spacing:.12em;font-size:.78rem;color:#b3261e;font-weight:700;padding:0}'
                 '.nb-hero-title{font-size:clamp(2.4rem,7vw,4.6rem);line-height:1.12}.nb-hero .nb-btn.is-ghost{color:#1a1814;border-color:#1a1814}'
                 '.nb-title{border-bottom:2px solid #1a1814;padding-bottom:10px;display:inline-block}.nb-head{text-align:start;margin-inline:0}'
                 '.nb-text>p:first-child::first-letter{font-family:var(--nb-font-head);font-size:3.2em;float:inline-start;line-height:.9;padding-inline-end:.12em;color:#b3261e}',
        'uiux': {'style_id': 'editorial-grid-magazine', 'font_pairing': 'Editorial Classic', 'palette': 'Magazine/Blog'},
    },
    'retro-y2k': {
        'label': 'رترو و Y2K', 'en': 'Retro / Y2K', 'mood': 'براق، بنفش و صورتیِ دهه‌ی ۲۰۰۰',
        'desc': 'گرادیان‌های براقِ صورتی و بنفش، دکمه‌های کروم، حباب‌ها و حاشیهٔ ضخیم؛ نوستالژیِ آینده‌نگر. برای سرگرمی، موسیقی و مد.',
        'tags': ['رترو', 'y2k', 'براق', 'صورتی', 'بنفش', 'سرگرمی', 'موسیقی', 'مد', 'retro'],
        'theme': {'colors': {'primary': '#ca0077', 'on_primary': '#ffffff', 'text': '#2a0a4a', 'text2': '#47276e', 'muted': '#6d5890',
                             'line': '#c9aeef', 'bg': '#f3e8ff', 'surface': '#ffffff'},
                  'font_head': 'lalezar', 'font_body': 'cairo', 'button': 'round', 'radius': 24, 'width': 1140},
        'tokens': {'page_bg': 'radial-gradient(circle at 12% 8%,#ffd0f0 0,transparent 38%),radial-gradient(circle at 88% 14%,#bff4ff 0,transparent 36%),#f3e8ff',
                   'card_bd': '2px solid #2a0a4a', 'card_sh': '5px 5px 0 #2a0a4a', 'card_bg': '#ffffff', 'hov': 'translate(-2px,-3px) rotate(-.5deg)',
                   'hov_sh': '8px 8px 0 #ca0077', 'head_w': '400', 'head_ls': '0', 'btn_bw': '2px', 'btn_bc': '#2a0a4a',
                   'btn_sh': 'inset 0 -6px 10px rgba(0,0,0,.18),inset 0 4px 8px rgba(255,255,255,.65),3px 4px 0 #2a0a4a',
                   'ic_bg': 'radial-gradient(circle at 30% 25%,#ffffff 0,#ffc2e6 40%,#ca0077 100%)', 'ic_fg': '#2a0a4a', 'ic_r': '50%',
                   'eb_bg': '#bff4ff', 'eb_r': '999px', 'hd_bg': '#ffffff', 'hd_bd': '2px solid #2a0a4a',
                   'hero_bg': 'conic-gradient(from 210deg at 70% 30%,#ff7ac6,#8f5bff,#4fd3ff,#ff7ac6)', 'hero_fg': '#ffffff', 'hero_btn_bg': '#ffffff', 'hero_btn_fg': '#ca0077',
                   'cta_bg': 'linear-gradient(120deg,#ff7ac6,#8f5bff 55%,#4fd3ff)', 'cta_fg': '#ffffff', 'cta_bd': '2px solid #2a0a4a', 'cta_sh': '6px 6px 0 #2a0a4a',
                   'in_bd': '2px solid #2a0a4a', 'in_bg': '#ffffff', 'hl_bd': '2px solid #2a0a4a', 'hl_sh': '8px 8px 0 #ca0077'},
        'sections': {'hero': 'framed', 'features': '', 'pricing': 'bold', 'testimonials': 'marked', 'faq': 'boxed', 'cta': '', 'site_header': 'floating'},
        'extra': '.nb-btn.is-filled{background:linear-gradient(180deg,#ff8fd0 0,#ca0077 55%,#a8005f 100%);color:#fff;text-shadow:0 1px 0 rgba(0,0,0,.25)}'
                 '.nb-hero-title{text-shadow:3px 3px 0 #2a0a4a;-webkit-text-stroke:0}.nb-btn.is-ghost{color:#fff;border-color:#fff}'
                 '.nb-eyebrow{border:2px solid #2a0a4a;color:#2a0a4a}.nb-hero .nb-sub{text-shadow:1px 1px 0 rgba(42,10,74,.5)}'
                 '.nb-feature:nth-child(even) .nb-feature-icon{background:radial-gradient(circle at 30% 25%,#ffffff 0,#bff4ff 40%,#2fb4e0 100%)}',
        'uiux': {'style_id': 'y2k-aesthetic', 'font_pairing': 'Music/Entertainment', 'palette': 'Music Streaming'},
    },
    'swiss': {
        'label': 'سوئیسی (بین‌المللی)', 'en': 'Swiss / International', 'mood': 'شبکه‌ای، سیاه‌وسفید و منطقی',
        'desc': 'شبکهٔ دقیق، تیترهای بزرگِ تراز، خطوطِ سیاهِ ضخیم و فقط یک رنگِ تأکید. برای طراحی، معماری، مشاوره و استودیو.',
        'tags': ['سوئیسی', 'شبکه', 'سیاه‌وسفید', 'طراحی', 'معماری', 'swiss', 'استودیو', 'بین‌المللی'],
        'theme': {'colors': {'primary': '#e30613', 'on_primary': '#ffffff', 'text': '#000000', 'text2': '#222222', 'muted': '#595959',
                             'line': '#d6d6d6', 'bg': '#ffffff', 'surface': '#ffffff'},
                  'font_head': 'plex', 'font_body': 'plex', 'button': 'square', 'radius': 0, 'width': 1200},
        'tokens': {'card_bg': 'transparent', 'card_bd': '0 solid transparent', 'card_sh': 'none', 'card_r': '0', 'hov': 'none', 'hov_sh': 'none',
                   'head_w': '700', 'head_ls': '-.025em', 'btn_bw': '2px', 'btn_sh': 'none', 'btn_hov': 'none', 'btn_filter': 'none', 'btn_bc': '#000',
                   'ic_bg': 'transparent', 'ic_fg': '#e30613', 'ic_r': '0', 'eb_bg': 'transparent', 'eb_r': '0', 'gap': '24px',
                   'hd_bg': '#ffffff', 'hd_bd': '2px solid #000', 'sec_py': 'clamp(48px,7vw,96px)',
                   'hero_bg': '#ffffff', 'hero_fg': '#000000', 'hero_btn_bg': '#e30613', 'hero_btn_fg': '#ffffff',
                   'cta_bg': '#e30613', 'cta_fg': '#ffffff', 'cta_r': '0', 'in_r': '0', 'in_bg': '#fff', 'in_bd': '2px solid #000',
                   'hl_bd': '2px solid #e30613', 'hl_sh': 'none'},
        'sections': {'hero': 'start', 'features': 'numbered', 'pricing': 'flat', 'testimonials': 'plain', 'faq': 'plain', 'cta': 'bar', 'site_header': 'minimal'},
        'extra': '.nb-feature,.nb-quote{border-top:2px solid #000;padding:16px 0 0}.nb-plan{border:2px solid #000}'
                 '.nb-eyebrow{padding:0;font-weight:700;color:#e30613;letter-spacing:.04em}.nb-hero-title{font-size:clamp(2.6rem,8vw,5.4rem);line-height:1.05}'
                 '.nb-hero .nb-btn.is-ghost{color:#000;border-color:#000}.nb-head{text-align:start;margin-inline:0;border-top:2px solid #000;padding-top:14px}'
                 '.nb-title{font-size:clamp(1.8rem,4vw,2.8rem)}.nb-faq-item{border-top:2px solid #000;padding-inline:0}',
        'uiux': {'style_id': 'swiss-modernism-2-0', 'font_pairing': 'Minimal Swiss', 'palette': 'Architecture / Interior'},
    },
    'organic': {
        'label': 'ارگانیک', 'en': 'Organic / biophilic', 'mood': 'طبیعی، گرم و خاکی',
        'desc': 'سبزِ جنگلی و بژِ خاکی، گوشه‌های نامتقارنِ گرد مثلِ برگ و سنگ، سایه‌های طبیعی. برای محصولِ طبیعی، سلامت و گیاه.',
        'tags': ['ارگانیک', 'طبیعی', 'سبز', 'گیاه', 'سلامت', 'خاکی', 'organic', 'غذا'],
        'theme': {'colors': {'primary': '#2f6b3a', 'on_primary': '#ffffff', 'text': '#26352a', 'text2': '#44574a', 'muted': '#5d6e62',
                             'line': '#dcd5c0', 'bg': '#f3efe4', 'surface': '#fbf8f0'},
                  'font_head': 'naskh', 'font_body': 'vazirmatn', 'button': 'round', 'radius': 30, 'width': 1120},
        'tokens': {'card_bg': '#fbf8f0', 'card_bd': '1px solid rgba(47,107,58,.14)', 'card_sh': '0 14px 34px -20px rgba(70,60,30,.35)',
                   'card_r': '34px 12px 34px 12px', 'hov': 'translateY(-4px) rotate(-.3deg)', 'head_w': '700', 'head_ls': '0',
                   'btn_sh': '0 10px 22px -12px rgba(47,107,58,.7)', 'ic_r': '60% 40% 55% 45%/50% 55% 45% 50%', 'ic_bg': 'color-mix(in srgb,var(--brand) 14%,#fbf8f0)',
                   'hero_bg': 'radial-gradient(80% 90% at 15% 100%,rgba(160,103,58,.35) 0,transparent 60%),linear-gradient(135deg,#2f6b3a,#4d8a52 60%,#7da86a)',
                   'hero_fg': '#fbf8f0', 'hero_btn_bg': '#fbf8f0', 'hero_btn_fg': '#2f6b3a', 'cta_bg': 'linear-gradient(135deg,#2f6b3a,#6a9a58)', 'cta_r': '42px 14px 42px 14px',
                   'eb_bg': 'rgba(251,248,240,.2)', 'in_r': '18px', 'in_bg': '#fbf8f0', 'hd_bg': '#f3efe4'},
        'sections': {'hero': '', 'features': '', 'pricing': '', 'testimonials': 'marked', 'faq': 'boxed', 'cta': '', 'site_header': ''},
        'extra': '.nb-feature:nth-child(even){border-radius:12px 34px 12px 34px}.nb-plan,.nb-quote{border-radius:34px 12px 34px 12px}'
                 '.nb-hero{border-bottom-left-radius:48px 28px;border-bottom-right-radius:48px 28px}'
                 '.nb-feature:nth-child(3n+2) .nb-feature-icon{color:#a0673a;background:color-mix(in srgb,#a0673a 14%,#fbf8f0)}',
        'uiux': {'style_id': 'organic-biophilic', 'font_pairing': 'Wellness Calm', 'palette': 'Florist/Plant Shop'},
    },
}

ORDER = ['glassmorphism', 'claymorphism', 'neumorphism', 'neo-brutalism', 'bento-grid', 'minimalism', 'aurora', 'dark-luxury',
         'soft-pastel', 'corporate-clean', 'editorial', 'retro-y2k', 'swiss', 'organic']
assert list(STYLES) == ORDER or set(STYLES) == set(ORDER)
