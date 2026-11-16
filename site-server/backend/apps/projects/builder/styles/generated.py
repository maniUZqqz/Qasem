# -*- coding: utf-8 -*-
"""سبک‌های طراحیِ «خودکار» از کلِ دادهٔ ui-ux-pro-max (MIT): برای هر سبکِ آن مخزن که سبکِ دست‌سازی ندارد یک سبکِ کامل می‌سازیم.

ردیفِ دادهٔ ui-ux-pro-max (نام، نوع، کلیدواژه، ``rtl_level``، وضعیت) + یک پالتِ واقعیِ ``colors.csv`` (رنگِ اصلی، تأکید، زمینه، متن) + یک جفتِ قلمِ ``typography.csv``
که به قلمِ فارسیِ مجوزدار نگاشته شده (``fonts_fa``) + یک «الگوی» ظاهری (``gen_archetypes``) ⇒ سبکی با همان ساختارِ ۱۴ سبکِ دست‌ساز.
متنِ فارسیِ نام و توضیح را خودمان نوشته‌ایم (جدولِ ``TABLE``)؛ انگلیسیِ اصلی در ``en`` می‌ماند.

آزمون (tests_styles_full.py): هر ردیفِ دادهٔ ui-ux-pro-max یا سبکِ دست‌ساز دارد یا این‌جا؛ هر سبک تباینِ WCAG، قلمِ فارسی‌پذیر، CSSِ راست‌به‌چپ (بی‌left/right) و
بی‌فاصلهٔ حروف دارد؛ همه در مرورگر هم باز می‌شوند.
"""
from . import fonts_fa, gen_archetypes
from .gen_core import contrast, ensure, h2r, lum, make_palette, mix
from . import uiux

GROUPS_FA = {'General': 'عمومی', 'Mobile': 'اپ و موبایل', 'BI/Analytics': 'داشبورد و تحلیل', 'Landing Page': 'الگوی صفحهٔ فرود (قدیمی)',
             'Platform/System': 'سیستم‌های طراحی', 'Platform/Material': 'سیستم‌های طراحی'}
#: قلم‌های نسخ/نستعلیق‌مانند که نقطه‌ها و کشیده‌هایشان با ارتفاعِ خطِ کوتاه در هم می‌رود (همان قاعدهٔ «امیری» ِ سبک‌های دست‌ساز)
TALL_MARK_FONTS = ('amiri', 'scheherazade', 'lateef', 'mirza', 'naskh', 'aref', 'katibeh', 'markazi')
TALL_MARK_CSS = ('.nb-hero-title{line-height:1.4}.nb-hero.nbv-start h1.nb-hero-title{line-height:1.4}.nb-title,.nb-h,.nb-plan-name,.nb-feature-title{line-height:1.4}')

GROUP_ORDER = ['عمومی', 'اپ و موبایل', 'داشبورد و تحلیل', 'سیستم‌های طراحی', 'الگوی صفحهٔ فرود (قدیمی)']

# کلید: Style ID در styles.csv ⇒ مشخصاتِ ساخت. فیلدها: arch (الگو)، pal (ردیفِ پالت در colors.csv)، pair (جفتِ قلم در typography.csv)،
# mode (dark)، acc / acc2 / bg (در صورتِ نیاز رنگِ دقیق)، label/mood/desc/tags (فارسی)
TABLE = {
    'brutalism': dict(arch='raw', pal='Knowledge Base/Documentation', pair='Brutalist Raw', acc='#1a0dab', bg='#f2f2ee', label='بروتالیسمِ خام', mood='خام، بی‌پیرایه و صریح',
                      desc='تقریباً بی‌طراحی؛ حاشیهٔ ساده، پیوندِ آبیِ کلاسیک و ساختارِ بی‌پرده. برای پرتفولیو و پروژهٔ هنریِ ضدِ ظاهرِ براق.', tags='بروتالیسم خام ساده هنری'),
    '3d-and-hyperrealism': dict(arch='dark', pal='Luxury/Premium Brand', pair='Classic Elegant', mode='dark', acc='#d4af37', acc2='#8b1a2b', label='سه‌بعدی و واقع‌نما',
                                mood='عمیق، براق و سینمایی', desc='سایه‌های چندلایه و رنگ‌های سرمه‌ای، شرابی و طلایی برای حسِ عمقِ واقعی؛ مناسبِ محصولِ سه‌بعدی و برندِ گران.',
                                tags='سه‌بعدی واقع‌گرا تیره طلایی'),
    'vibrant-and-block-based': dict(arch='blocks', pal='Marketplace (P2P)', pair='Bold Statement', label='بلوکی و پرانرژی', mood='شاد و رنگیِ پُرکنتراست',
                                    desc='بلوک‌های بزرگِ رنگی کنارِ هم با حاشیهٔ پررنگ؛ برای برندِ جوان، رویداد و محصولِ شاد.', tags='بلوکی رنگی پرانرژی جوان'),
    'accessible-and-ethical': dict(arch='access', pal='Government/Public Service', pair='Accessibility First', acc='#0b57d0', bg='#ffffff', label='دسترس‌پذیر و اخلاقی',
                                   mood='روشن، پُرکنتراست و قابل‌اعتماد', desc='تباینِ بالا، حاشیهٔ پررنگ، نوشتهٔ درشت و حلقهٔ فوکوسِ واضح؛ برای خدماتِ عمومی و هر جایی که همه باید بتوانند بخوانند.',
                                   tags='دسترس‌پذیری پرکنتراست عمومی'),
    'retro-futurism': dict(arch='neon', pal='Gaming', pair='Crypto/Web3', mode='dark', acc='#2bb3ff', acc2='#ff2d95', label='رترو-فیوچریسم', mood='نئونیِ دههٔ ۸۰',
                           desc='زمینهٔ تیره با خطوطِ شبکه‌ای و درخششِ نئونیِ آبی و صورتی؛ برای بازی، موسیقی و فناوری.', tags='رترو نئون آینده‌نگر بازی'),
    'skeuomorphism': dict(arch='skeuo', pal='Bakery/Cafe', pair='Retro Vintage', bg='#e9dcc3', surface='#fffaf0', label='شبیه‌واقعی', mood='گرم، لمسی و کاغذی',
                          desc='سطح‌هایی شبیهِ چرم و کاغذ با سایهٔ داخلی و گرادیانِ ملایم؛ حسِ شیءِ واقعی.', tags='اسکیومورفیسم لمسی گرم'),
    'liquid-glass': dict(arch='vision', pal='Travel/Tourism Agency', pair='Spatial Clear', label='شیشهٔ مایع', mood='شفاف، روان و سیستم‌عاملی',
                         desc='شیشهٔ بسیار مات‌شده با لبهٔ روشن و گوشه‌های خیلی گرد؛ حسِ سیستم‌عاملِ امروزی.', tags='شیشه مایع شفاف'),
    'motion-driven': dict(arch='kinetic', pal='Creative Agency', pair='Kinetic Motion', label='حرکت‌محور', mood='پویا و پرانرژی',
                          desc='تیترهای بسیار درشت و ورودِ نرمِ عنصرها (با «کاهشِ حرکت» در دستگاه خودکار خاموش می‌شود)؛ برای آژانس و ارائهٔ برند.', tags='حرکت پویا تیتر درشت'),
    'micro-interactions': dict(arch='soft', pal='Productivity Tool', pair='Friendly SaaS', label='ریزتعامل‌ها', mood='نرم، پاسخگو و ظریف',
                               desc='سایه‌های ملایم، جابه‌جاییِ کوچک روی هاور و دکمه‌های گرد؛ همه‌چیز به لمس جواب می‌دهد.', tags='ریزتعامل نرم اپ'),
    'inclusive-design': dict(arch='access', pal='Healthcare App', pair='Accessibility First', acc='#00677f', label='طراحیِ فراگیر', mood='شفاف، آرام و بی‌مانع',
                             desc='تباینِ بالا و حاشیهٔ پررنگ با رنگ‌های آرام؛ برای سلامت، آموزش و خدماتِ همگانی.', tags='فراگیر دسترس‌پذیر سلامت'),
    'zero-interface': dict(arch='paper', pal='Yoga & Stretching Guide', pair='Minimal Swiss', bg='#f7f7f4', label='بی‌رابط', mood='آرام، خالی و کم‌حرف',
                           desc='تقریباً فقط متن و فضای خالی؛ بدونِ کارت و تزیین، رابط در پس‌زمینه می‌ماند.', tags='مینیمال بی‌رابط کم‌حرف'),
    'hero-centric-design': dict(arch='corporate', pal='SaaS (General)', pair='Modern Professional', label='هیرو‌محور (الگوی قدیمی)', mood='بزرگ، روشن و مستقیم',
                                desc='همه‌چیز دورِ یک سربرگِ بزرگ و یک دعوت به اقدام می‌چرخد. در دادهٔ ui-ux-pro-max این ردیف «الگوی صفحه» و منسوخ است؛ برای کامل‌بودن آمده.',
                                tags='هیرو الگو قدیمی'),
    'conversion-optimized': dict(arch='corporate', pal='E-commerce', pair='Modern Professional', label='تبدیل‌محور (قدیمی)', mood='متمرکز و فروشنده',
                                 desc='رنگِ دکمهٔ اصلی پررنگ و بقیه آرام تا چشم همیشه به اقدامِ اصلی برود. ردیفِ منسوخِ دادهٔ مرجع.', tags='تبدیل فروش دکمه قدیمی'),
    'feature-rich-showcase': dict(arch='soft', pal='Design System/Component Library', pair='Friendly SaaS', label='ویترینِ پُرامکانات (قدیمی)', mood='رنگارنگ و منظم',
                                  desc='کارت‌های گردِ امکانات با نمادهای رنگی برای معرفیِ محصولِ پُرقابلیت. ردیفِ منسوخِ دادهٔ مرجع.', tags='امکانات ویترین قدیمی'),
    'minimal-and-direct': dict(arch='flat', pal='Portfolio/Personal', pair='Minimal Swiss', acc='#111111', label='ساده و مستقیم (قدیمی)', mood='سفید، یک‌رنگ و بی‌حاشیه',
                               desc='یک رنگِ اصلی روی زمینهٔ سفید و یک دکمه، بی‌پرده. ردیفِ منسوخِ دادهٔ مرجع.', tags='ساده مستقیم قدیمی'),
    'social-proof-focused': dict(arch='corporate', pal='Membership/Community', pair='Corporate Trust', label='اعتمادسازی با نظرها (قدیمی)', mood='مطمئن و انسانی',
                                 desc='نظرها و نشان‌های اعتماد جلوی صحنه‌اند؛ رنگ‌های آرام و رسمی. ردیفِ منسوخِ دادهٔ مرجع.', tags='نظر اعتماد قدیمی'),
    'interactive-product-demo': dict(arch='dark', pal='AI/Chatbot Platform', pair='Tech Startup', mode='dark', acc='#a78bfa', label='نمایشِ تعاملیِ محصول (قدیمی)', mood='تیره و فنی',
                                     desc='زمینهٔ تیره و درخششِ رنگیِ ملایم برای نشان‌دادنِ رابطِ محصول. ردیفِ منسوخِ دادهٔ مرجع.', tags='دمو محصول تیره قدیمی'),
    'trust-and-authority': dict(arch='corporate', pal='Legal Services', pair='Legal Professional', label='اعتماد و اقتدار (قدیمی)', mood='رسمی، سرمه‌ای و باوقار',
                                desc='سرمه‌ای و طلایی با نشان‌های مجوز؛ برای حقوقی، مالی و درمانی. ردیفِ منسوخِ دادهٔ مرجع.', tags='اعتماد رسمی سرمه‌ای قدیمی'),
    'storytelling-driven': dict(arch='story', pal='Wedding/Event Planning', pair='Magazine Style', label='روایت‌محور (قدیمی)', mood='رنگیِ نرم و داستانی',
                                desc='بخش‌هایی با پس‌زمینه‌های گرادیانیِ متفاوت و ترتیبِ شماره‌دار؛ داستانِ برند را قدم‌به‌قدم می‌گوید. ردیفِ منسوخِ دادهٔ مرجع.', tags='روایت داستان قدیمی'),
    'data-dense-dashboard': dict(arch='dash', pal='Analytics Dashboard', pair='Dashboard Data', label='داشبوردِ پرداده', mood='فشرده، دقیق و خوانا',
                                 desc='فاصله‌های کم، کارت‌های کوچک و حاشیهٔ نازک؛ برای صفحه‌های تحلیلی و پنلِ مدیریت.', tags='داشبورد داده تحلیل'),
    'heat-map-and-heatmap-style': dict(arch='dash', pal='Weather App', pair='Dashboard Data', label='نقشهٔ حرارتی', mood='فشرده با رنگِ سرد و گرم',
                                       desc='داشبوردی با پالتِ آبیِ سرد تا نارنجیِ گرم برای نمایشِ شدت‌ها و تراکم.', tags='نقشه حرارتی شدت داده'),
    'executive-dashboard': dict(arch='dash', pal='Banking/Traditional Finance', pair='Financial Trust', acc='#1e293b', acc2='#a16207', label='داشبوردِ مدیریتی', mood='رسمی و خلاصه',
                                desc='سرمه‌ای و طلایی؛ شاخص‌های کلیدیِ بزرگ و بقیه کم‌حرف.', tags='مدیریتی شاخص رسمی'),
    'real-time-monitoring': dict(arch='dash', pal='Smart Home/IoT Dashboard', pair='Dashboard Data', mode='dark', acc='#22c55e', acc2='#f59e0b', label='پایشِ زنده', mood='تیره و هشداردهنده',
                                 desc='زمینهٔ تیره با سبزِ «عادی» و زردِ «هشدار» برای وضعیتِ سامانه‌ها.', tags='پایش زنده تیره هشدار'),
    'drill-down-analytics': dict(arch='dash', pal='CRM & Client Management', pair='Dashboard Data', label='تحلیلِ لایه‌به‌لایه', mood='آبی و منظم',
                                 desc='سلسله‌مراتبِ واضح با رنگِ آبیِ اصلی؛ از کلیات به جزئیات.', tags='تحلیل جزئیات آبی'),
    'comparative-analysis-dashboard': dict(arch='dash', pal='Micro SaaS', pair='Dashboard Data', label='داشبوردِ مقایسه‌ای', mood='بنفش و سبز',
                                           desc='دو رنگِ مقایسه کنارِ هم؛ برای قبل/بعد، رقابت و آزمونِ A/B.', tags='مقایسه تحلیل بنفش'),
    'predictive-analytics': dict(arch='dash', pal='Fintech/Crypto', pair='Dashboard Data', mode='dark', acc='#a78bfa', acc2='#f59e0b', label='تحلیلِ پیش‌بینی', mood='تیره و بنفش',
                                 desc='زمینهٔ تیره با بنفشِ ملایم برای نمودارِ پیش‌بینی و بازهٔ اطمینان.', tags='پیش‌بینی تیره بنفش'),
    'user-behavior-analytics': dict(arch='dash', pal='Online Course/E-learning', pair='Dashboard Data', label='تحلیلِ رفتارِ کاربر', mood='فیروزه‌ای و روشن',
                                    desc='قیف‌ها و مسیرها با رنگِ فیروزه‌ای؛ برای محصولات و آموزش.', tags='رفتار کاربر قیف فیروزه‌ای'),
    'financial-dashboard': dict(arch='dash', pal='Financial Dashboard', pair='Financial Trust', mode='dark', acc='#22c55e', acc2='#ef4444', label='داشبوردِ مالی', mood='تیره، سودِ سبز و زیانِ قرمز',
                                desc='زمینهٔ تیرهٔ مالی؛ سود سبز و زیان قرمز.', tags='مالی تیره سود'),
    'sales-intelligence-dashboard': dict(arch='dash', pal='Logistics/Delivery', pair='Dashboard Data', label='داشبوردِ فروش', mood='آبی و نارنجی',
                                         desc='رنگِ آبیِ اصلی با تأکیدِ نارنجی برای فرصت‌ها و پیگیری‌ها.', tags='فروش آبی نارنجی'),
    'cyberpunk-ui': dict(arch='neon', pal='Cybersecurity Platform', pair='Tech/HUD Mono', mode='dark', acc='#00ff9c', acc2='#ff00aa', label='سایبرپانک', mood='نئونیِ تیره',
                         desc='سبزِ ماتریکس و سرخابیِ نئونی روی سیاه؛ برای امنیت، بازی و فناوری.', tags='سایبرپانک نئون تیره امنیت'),
    'ai-native-ui': dict(arch='ainative', pal='AI/Chatbot Platform', pair='Tech Startup', label='رابطِ هوشِ مصنوعی', mood='تمیز با درخششِ بنفش',
                         desc='زمینهٔ روشن و یک بنفشِ هوشمند؛ کارتِ ویژه با هالهٔ ملایم.', tags='هوش‌مصنوعی بنفش تمیز'),
    'memphis-design': dict(arch='memphis', pal='Kids Learning (ABC & Math)', pair='Playful Creative', acc2='#ffb703', label='ممفیس', mood='رنگارنگ و بازیگوش',
                           desc='نقطه‌ها و شکل‌های پراکنده با حاشیهٔ ضخیم؛ برای کودک و خلاقیت.', tags='ممفیس رنگارنگ بازیگوش'),
    'vaporwave': dict(arch='vapor', pal='NFT/Web3 Platform', pair='Crypto/Web3', mode='dark', acc='#ff71ce', acc2='#01cdfe', label='ویپورویو', mood='بنفش و صورتی',
                      desc='گرادیانِ بنفش به صورتی با فیروزه‌ای؛ نوستالژیِ دههٔ ۸۰ و ۹۰.', tags='ویپورویو صورتی بنفش'),
    'dimensional-layering': dict(arch='layers', pal='Design System/Component Library', pair='Geometric Modern', label='لایه‌های بُعدی', mood='شناور و منظم',
                                 desc='سایه‌های چندلایه و چیدمانِ بنتو؛ هر کارت از زمینه جدا شناور است.', tags='لایه سایه شناور بنتو'),
    'exaggerated-minimalism': dict(arch='exmin', pal='Portfolio/Personal', pair='Minimalist Portfolio', acc='#111111', label='مینیمالِ اغراق‌شده', mood='سفید با تیترِ غول‌پیکر',
                                   desc='تیترِ بسیار بزرگ و فضای خالیِ زیاد؛ فقط یک رنگ.', tags='مینیمال تیتر درشت'),
    'kinetic-typography': dict(arch='kinetic', pal='Marketing Agency', pair='Fashion Forward', label='تایپوگرافیِ پویا', mood='درشت و زنده',
                               desc='حروفِ غول‌پیکر که با ورود جان می‌گیرند (در صورتِ «کاهشِ حرکت» ساکن می‌مانند).', tags='تایپوگرافی پویا درشت'),
    'parallax-storytelling': dict(arch='story', pal='Travel/Tourism Agency', pair='News Editorial', label='روایتِ لایه‌ای', mood='رنگیِ نرم و سینمایی',
                                  desc='بخش‌های پشتِ‌سرِ هم با گرادیان و شماره؛ بدونِ اسکرولِ پیچیده (پارالاکسِ واقعی نیازِ جاوااسکریپت دارد و در سایت‌ساز نیست).', tags='روایت لایه‌ای سینمایی'),
    'hud-sci-fi-fui': dict(arch='hud', pal='Space Tech / Aerospace', pair='Tech/HUD Mono', mode='dark', acc='#38e8ff', acc2='#ff4d6d', label='رابطِ علمی-تخیلی', mood='تیره و خط‌خطیِ فیروزه‌ای',
                           desc='خطوطِ نازکِ فیروزه‌ای، گوشه‌های بریده و شبکهٔ ریز؛ حسِ نمایشگرِ فضاپیما.', tags='علمی‌تخیلی HUD فیروزه‌ای'),
    'pixel-art': dict(arch='pixel', pal='Arcade & Retro Game', pair='Pixel Retro', bg='#fdf6e3', acc='#c1121f', acc2='#22c55e', label='پیکسلی', mood='رترو و شطرنجی',
                      desc='حاشیهٔ ضخیم و سایهٔ پله‌ای با زمینهٔ شطرنجیِ محو؛ شبیهِ بازی‌های قدیمی.', tags='پیکسل رترو بازی'),
    'bento-grids': dict(arch='layers', pal='SaaS (General)', pair='Friendly SaaS', label='بنتوی قدیمی', mood='سفید و ماژولار',
                        desc='نسخهٔ قدیمیِ شبکهٔ بنتو (در دادهٔ مرجع منسوخ است)؛ کاشی‌های سفید با سایهٔ نرم.', tags='بنتو قدیمی ماژولار'),
    'spatial-ui-visionos': dict(arch='vision', pal='Spatial Computing OS / App', pair='Spatial Clear', mode='dark', acc='#8ab4ff', acc2='#c4a5ff', label='رابطِ فضایی', mood='شیشه‌ای و تیره',
                                desc='شیشهٔ نیمه‌شفاف روی زمینهٔ تیره و گوشه‌های خیلی گرد؛ حسِ عینکِ واقعیت‌افزوده.', tags='فضایی شیشه تیره'),
    'e-ink-paper': dict(arch='paper', pal='Notes & Writing App', pair='Academic/Archival', bg='#f4f1e8', acc='#2b2b2b', label='کاغذِ الکترونیکی', mood='خاکستریِ کاغذی',
                        desc='زمینهٔ کاغذی و خطِ نازکِ مشکی؛ مثلِ کتاب‌خوان.', tags='کاغذ کتاب‌خوان مینیمال'),
    'gen-z-chaos-maximalism': dict(arch='maximal', pal='Meme & Sticker Maker', pair='Gen Z Brutal', acc2='#d6ff00', label='هرج‌ومرجِ نسلِ Z', mood='شلوغ، رنگی و پرسروصدا',
                                   desc='رنگ‌های متضاد، سایهٔ سخت و چرخشِ کوچک؛ برای برندِ اینترنتی و میم.', tags='نسل‌زد شلوغ رنگی'),
    'biomimetic-organic-2-0': dict(arch='dark', pal='Sustainable Energy / Climate Tech', pair='Wellness Calm', mode='dark', acc='#34d399', acc2='#a3e635', label='زیست‌الهامِ ۲', mood='تیره، سبزِ زنده',
                                   desc='زمینهٔ تیره با درخششِ سبزِ زیستی و گوشه‌های گرد.', tags='زیستی سبز تیره'),
    'anti-polish-raw-aesthetic': dict(arch='sketch', pal='Diary & Journal App', pair='Handwritten Charm', bg='#faf8f1', acc2='#ffd166', label='خام و دست‌ساز', mood='کاغذی و ناصاف',
                                      desc='حاشیه‌های دست‌کشیده و سایهٔ کج؛ حسِ طراحیِ دستی و صمیمی.', tags='دست‌ساز خام صمیمی'),
    'tactile-digital-deformable-ui': dict(arch='tactile', pal='Casual Puzzle Game', pair='Playful Creative', acc='#c2185b', label='دیجیتالِ لمسی', mood='ژله‌ای و براق',
                                          desc='دکمه‌ها و کارت‌های ژله‌ایِ برجسته با درخشش.', tags='لمسی ژله‌ای براق'),
    'nature-distilled': dict(arch='earth', pal='Home Decoration & Interior Design', pair='Wellness Calm', acc='#a8431f', acc2='#c9a66b', bg='#f4ece0', label='طبیعتِ تقطیرشده', mood='خاکی و گرم',
                             desc='رنگ‌های سفال و شن؛ آرام، گرم و خاکی.', tags='طبیعت خاکی سفال'),
    'interactive-cursor-design': dict(arch='flat', pal='Generative Art Platform', pair='Minimalist Portfolio', acc='#18181b', acc2='#ec4899', label='طراحیِ اشاره‌گرمحور', mood='تمیز و مینیمال',
                                      desc='رنگِ تأکیدِ واضح و فاصلهٔ زیاد (افکتِ اشاره‌گر نیازِ جاوااسکریپت دارد؛ این‌جا فقط ظاهرِ آرامش).', tags='اشاره‌گر مینیمال تمیز'),
    'voice-first-multimodal': dict(arch='calm', pal='Meditation & Mindfulness', pair='Soft Rounded', label='صوت‌محور', mood='آرام و درشت',
                                   desc='کارت‌های گردِ بزرگ و رنگ‌های آرام؛ مناسبِ دستیارِ صوتی.', tags='صوت آرام درشت'),
    '3d-product-preview': dict(arch='studio', pal='E-commerce Luxury', pair='Luxury Minimalist', bg='#e9e9ec', acc='#1c1917', acc2='#a16207', label='ویترینِ سه‌بعدیِ محصول', mood='صحنهٔ استودیویی',
                               desc='زمینهٔ خاکستریِ روشن با نورِ بالا؛ محصول مثلِ روی سکو.', tags='محصول استودیو سه‌بعدی'),
    'gradient-mesh-aurora-evolved': dict(arch='gradient', pal='Creator Economy Platform', pair='Fashion Forward', label='گرادیانِ مشِ تکامل‌یافته', mood='رنگیِ نرم و شناور',
                                         desc='لکه‌های رنگیِ نرم پشتِ کارت‌های نیمه‌شفاف.', tags='گرادیان مش رنگی'),
    'chromatic-aberration-rgb-split': dict(arch='glitch', pal='Video Streaming/OTT', pair='Kinetic Motion', mode='dark', acc='#ff2a6d', acc2='#05d9e8', label='شکافِ رنگیِ RGB', mood='تیره و گلیچی',
                                           desc='تیترهایی با سایهٔ قرمز-آبیِ جدا؛ حسِ تصویرِ خراب.', tags='گلیچ RGB تیره'),
    'vintage-analog-retro-film': dict(arch='film', pal='Brewery/Winery', pair='Retro Vintage', bg='#f3e8d2', acc='#7c2d12', acc2='#a16207', label='فیلمِ آنالوگِ قدیمی', mood='سپیا و گرم',
                                      desc='رنگ‌های کم‌رنگ‌شده و سایهٔ گوشه‌ها؛ حسِ عکسِ قدیمی.', tags='فیلم قدیمی سپیا'),
    'bauhaus': dict(arch='brut', pal='Sports Team/Club', pair='Bauhaus Geometric', acc='#d02020', acc2='#f0c020', bg='#f4f1ea', label='باهاوس', mood='هندسی و رنگ‌های اصلی',
                    desc='قرمز، آبی و زرد با حاشیهٔ ضخیم و شکل‌های هندسی.', tags='باهاوس هندسی رنگ‌اصلی'),
    'minimalist-monochrome': dict(arch='swiss', pal='Museum/Gallery', pair='Minimalist Portfolio', acc='#111111', label='مینیمالِ تک‌رنگ', mood='سیاه و سفید',
                                  desc='فقط سیاه و سفید و فضای خالی.', tags='تک‌رنگ سیاه‌سفید مینیمال'),
    'modern-dark-cinema-mobile': dict(arch='dark', pal='Video Streaming/OTT', pair='Modern Dark Cinema (Inter System)', mode='dark', acc='#7c86ff', label='تیرهٔ سینمایی', mood='تیره و دقیق',
                                      desc='زمینهٔ تقریباً سیاه با یک رنگِ نیلی؛ دقیق و گران.', tags='تیره سینمایی نیلی'),
    'saas-mobile-high-tech-boutique': dict(arch='soft', pal='SaaS (General)', pair='SaaS Mobile Boutique (Calistoga + Inter)', acc='#0052ff', label='بوتیکِ فناوری', mood='آبیِ الکتریکی',
                                           desc='آبیِ پررنگ و سایهٔ رنگی؛ برای SaaSِ مدرن.', tags='فناوری آبی بوتیک'),
    'terminal-cli-mobile': dict(arch='neon', pal='Coding Bootcamp', pair='Terminal CLI Monospace', mode='dark', acc='#33ff00', acc2='#00d5ff', label='ترمینال', mood='سبز روی سیاه',
                                desc='حسِ خطِ فرمان با سبزِ نئونی.', tags='ترمینال خطفرمان سبز'),
    'kinetic-brutalism-mobile': dict(arch='brut', pal='Fitness/Gym App', pair='Kinetic Brutalism (Space Grotesk)', mode='dark', acc='#dfe104', acc2='#dfe104', bg='#0b0b0d', label='بروتالیسمِ پویا',
                                     mood='زردِ اسیدی روی سیاه', desc='حاشیه و سایهٔ سخت با زردِ تند روی زمینهٔ تقریباً سیاه.', tags='بروتالیسم زرد سیاه'),
    'flat-design-mobile-touch-first': dict(arch='flat', pal='Chat & Messaging App', pair='Flat Design Mobile (System Bold)', label='تختِ لمس‌محور', mood='ساده و درشت',
                                           desc='دکمه‌های بزرگ و رنگ‌های تخت برای انگشت.', tags='تخت لمس درشت'),
    'material-you-md3-mobile': dict(arch='material', pal='Mental Health App', pair='Material You MD3 (Roboto System)', acc='#6750a4', bg='#fef7ff', label='متریال ۳', mood='رنگیِ تونال',
                                    desc='سطح‌های تونال و گوشه‌های گرد؛ شبیهِ اندرویدِ جدید.', tags='متریال تونال اندروید'),
    'neo-brutalism-mobile': dict(arch='brut', pal='Social Media App', pair='Neo Brutalism Mobile (Space Grotesk Bold)', acc='#c1121f', acc2='#ffd93d', bg='#fffdf5', label='نئوبروتالیسمِ موبایل',
                                 mood='زرد و قرمز، سایهٔ سخت', desc='کرِم، قرمز و زرد با حاشیهٔ سیاه.', tags='نئوبروتالیسم زرد قرمز'),
    'bold-typography-mobile-poster': dict(arch='exmin', pal='Magazine/Blog', pair='Bold Typography Mobile (Inter Poster)', acc='#0a0a0a', label='پوستریِ تایپوگرافیک', mood='سیاه‌وسفیدِ درشت',
                                          desc='تیترِ پوستریِ بزرگ و فضای زیاد.', tags='پوستر تایپوگرافی درشت'),
    'academia-scholarly-mobile': dict(arch='luxury', pal='Museum/Gallery', pair='Academia Mobile (Cormorant + Crimson + Cinzel)', mode='dark', acc='#c9a66b', bg='#1c1714', label='آکادمیک',
                                      mood='چوبی و ارجمند', desc='زمینهٔ تیرهٔ ماهون و برنجی؛ حسِ کتابخانه.', tags='آکادمیک کتابخانه ماهون'),
    'cyberpunk-mobile-hud': dict(arch='hud', pal='Cybersecurity Platform', pair='Cyberpunk Mobile (Orbitron + JetBrains Mono)', mode='dark', acc='#00e5ff', acc2='#ff2e88', bg='#0a0a0f',
                                 label='سایبرپانکِ HUD', mood='تیره و نئونی', desc='فیروزه‌ای و سرخابی با خطوطِ HUD.', tags='سایبرپانک HUD نئون'),
    'bitcoin-defi-mobile': dict(arch='dark', pal='Fintech/Crypto', pair='Web3 Bitcoin DeFi (Space Grotesk + Inter + Mono)', mode='dark', acc='#f7931a', acc2='#ffd600', label='دیفایِ بیت‌کوین',
                                mood='تیره و طلاییِ دیجیتال', desc='زمینهٔ تیره با نارنجی-طلایی؛ مالی و رمزارز.', tags='رمزارز دیفای طلایی'),
    'claymorphism-mobile': dict(arch='clay', pal='Marketplace (P2P)', pair='Claymorphism Mobile (Nunito + DM Sans)', acc='#7c3aed', acc2='#db2777', bg='#f6f0ff', label='خمیریِ موبایل', mood='بنفش و صورتی، تپل',
                                desc='همان خمیری با بنفش و صورتیِ شاد.', tags='خمیری بنفش صورتی'),
    'enterprise-saas-mobile': dict(arch='corporate', pal='Micro SaaS', pair='Enterprise SaaS Mobile (Plus Jakarta Sans)', acc='#4f46e5', acc2='#7c3aed', label='SaaSِ سازمانی', mood='نیلی و تمیز',
                                   desc='نیلیِ رسمی و سایه‌های ملایم برای نرم‌افزارِ سازمانی.', tags='سازمانی نیلی تمیز'),
    'sketch-hand-drawn-mobile': dict(arch='sketch', pal='Notes & Writing App', pair='Sketch Hand-Drawn Mobile (Kalam + Patrick Hand)', acc='#c0392b', acc2='#ffd166', bg='#fffdf7', label='طرحِ دست‌کشیده',
                                     mood='مدادی و صمیمی', desc='حاشیه‌های دست‌کشیده و ماژیکِ قرمز.', tags='طرح دست‌کشیده مداد'),
    'neumorphism-mobile': dict(arch='neu', pal='Productivity Tool', pair='Neumorphism Mobile (Plus Jakarta Sans + System)', acc='#5b52e8', bg='#e0e5ec', label='نرم‌برجستهٔ موبایل',
                               mood='خاکستریِ سرد', desc='همان نرم‌برجسته با بنفشِ ملایم.', tags='نرم‌برجسته خاکستری'),
    'fluent-2': dict(arch='material', pal='Government Portal / Civic Services', pair='Modern Professional', acc='#0f6cbd', bg='#f5f5f5', label='فلوئنت ۲', mood='آبیِ سیستمی و مرتب',
                     desc='سطح‌های تونال و گوشه‌های ملایم با آبیِ فلوئنت.', tags='سیستم‌طراحی آبی'),
    'shopify-polaris': dict(arch='material', pal='Grocery & Shopping List', pair='Friendly SaaS', acc='#008060', bg='#f1f2f4', label='پولاریس (فروشگاه‌ساز)', mood='سبزِ فروشگاهی',
                            desc='سبزِ ملایم و سطح‌های تمیزِ مدیریتی.', tags='سیستم‌طراحی سبز فروشگاه'),
    'spectrum-design-system': dict(arch='material', pal='Design System/Component Library', pair='Minimal Swiss', acc='#1473e6', bg='#f8f8f8', label='اسپکتروم', mood='آبیِ سیستمی',
                                   desc='آبیِ سیستمی و سطح‌های ساده.', tags='سیستم‌طراحی آبی ساده'),
    'spectrum-2': dict(arch='material', pal='Design System/Component Library', pair='Minimal Swiss', acc='#4b75ff', bg='#f6f7fb', label='اسپکتروم ۲', mood='آبیِ سیستمیِ نو',
                       desc='نسخهٔ تازه‌ترِ اسپکتروم با آبیِ روشن‌تر.', tags='سیستم‌طراحی آبی نو'),
    'apple-native-experience': dict(arch='calm', pal='Chat & Messaging App', pair='Spatial Clear', acc='#007aff', bg='#f2f2f7', label='تجربهٔ بومیِ اپل', mood='روشن و سیستم‌عاملی',
                                    desc='زمینهٔ سیستمیِ روشن با آبیِ سیستم و لبه‌های گرد.', tags='سیستم‌عامل روشن آبی'),
}


def _hex(row, key):
    v = (row or {}).get(key, '')
    return v.strip() if isinstance(v, str) and len(v.strip()) == 7 and v.strip().startswith('#') else ''


def _palette_for(spec: dict, crow: dict):
    dark = spec.get('mode') == 'dark'
    acc = spec.get('acc') or _hex(crow, 'primary') or ('#7c8cff' if dark else '#2563eb')
    acc2 = spec.get('acc2') or _hex(crow, 'accent') or None
    bg = spec.get('bg')
    if not bg:
        pbg = _hex(crow, 'background')
        if pbg and ((dark and lum(pbg) < 0.06) or (not dark and lum(pbg) > 0.80)):
            bg = pbg
    text = None
    pfg = _hex(crow, 'foreground')
    if pfg and ((not dark and lum(pfg) < 0.14) or (dark and lum(pfg) > 0.80)):
        text = pfg
    kw = {}
    if spec['arch'] == 'neu':
        bg = bg or ('#2a2e37' if dark else '#e4e8ef')
        kw['surface'] = bg
    elif spec.get('surface'):
        kw['surface'] = spec['surface']
    return make_palette(acc, dark=dark, bg=bg, text=text, acc2=acc2, **kw)


def build_all(hand: dict) -> dict:
    """⇒ {کلیدِ سبک: تعریف} برای هر ردیفِ دادهٔ ui-ux-pro-max که سبکِ دست‌ساز ندارد. hand = سبک‌های دست‌ساز (برای فهمیدنِ ردیف‌های پوشش‌داده‌شده)."""
    covered = {(st.get('uiux') or {}).get('style_id') for st in hand.values()}
    out = {}
    for srow in uiux.rows('styles'):
        sid = srow.get('id')
        if not sid or sid in covered or sid not in TABLE:
            continue
        spec = TABLE[sid]
        crow = uiux.by_id('colors', 'product', spec['pal']) or {}
        frow = uiux.by_id('fonts', 'name', spec['pair']) or {}
        P = _palette_for(spec, crow)
        built = gen_archetypes.build(spec['arch'], P, spec)
        head, body = fonts_fa.persian_pair(frow.get('heading', ''), frow.get('body', ''))
        grp = GROUPS_FA.get(srow.get('type', ''), 'عمومی')
        if head in TALL_MARK_FONTS:
            built['extra'] = (built['extra'] + TALL_MARK_CSS)
        tags = spec['tags'].split() + [w.strip() for w in (srow.get('keywords') or '').split(',')[:4] if w.strip()]
        out['ux-' + sid] = {
            'label': spec['label'], 'en': (srow.get('name') or sid).replace('Adobe ', ''), 'mood': spec['mood'], 'desc': spec['desc'], 'tags': tags,
            'theme': {'colors': P.colors(), 'font_head': head, 'font_body': body, 'button': built['button'], 'radius': built['radius'], 'width': built['width']},
            'tokens': built['tokens'], 'sections': built['sections'], 'extra': built['extra'],
            'uiux': {'style_id': sid, 'font_pairing': spec['pair'], 'palette': spec['pal']},
            'source': 'generated', 'group': grp, 'status': srow.get('status', 'active'), 'rtl': srow.get('rtl', ''), 'arch': spec['arch'],
        }
    return out
