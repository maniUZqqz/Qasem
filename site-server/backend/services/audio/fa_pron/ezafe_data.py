"""Word lists behind the conservative ezafe rules (``ezafe.py``).

Every list is plain text, words separated by spaces or line breaks, written with their normal half-spaces. ``ezafe.py`` compares
them with the half-spaces taken out, so «تازه‌کار» and «تازهکار» are the same word.

The lists are deliberately short and curated: an automatic ezafe is added only between a word we know to be a noun and a
word we know to be an adjective, a possessive pronoun, or a noun that normally takes a genitive. Anything outside the lists
gets NO ezafe (a missing ezafe sounds natural, a wrong one sounds like a mistake). To extend the coverage, add words here -
and add a sentence with its hand-checked reading to ``ezafe_gold.py`` so the check keeps both numbers honest.
"""

#: Classifying / relational adjectives: they are only ever attributive («برنامهٔ ورزشی», «رژیمِ غذایی»), so the ezafe in front of
#: them is safe wherever they stand (a copula after them still blocks it: «برنامه ورزشی است»).
ATTR = """
ورزشی غذایی تمرینی روزانه هفتگی ماهانه سالانه شبانه ساعتی شخصی اختصاصی آموزشی علمی عملی کاربردی دیجیتال آنلاین آفلاین
رایگان اصلی فرعی کلی جزئی عمومی خصوصی ملی بین‌المللی ایرانی خارجی فارسی انگلیسی عربی ترکی پزشکی بدنی ذهنی روانی عضلانی
قلبی تنفسی گوارشی پوستی گیاهی حیوانی طبیعی مصنوعی صنعتی سنتی مدرن امروزی قدیمی بعدی قبلی بالایی پایینی داخلی
مجازی حضوری کتبی شفاهی رسمی ویژه پایه مبتدی پیشرفته حرفه‌ای نیمه‌حرفه‌ای رژیمی قدرتی استقامتی اضافه اضافی نهایی
اول دوم سوم چهارم پنجم ششم هفتم هشتم نهم دهم یازدهم دوازدهم اولین دومین سومین چهارمین آخرین
مالی اقتصادی اجتماعی فرهنگی سیاسی تجاری اداری فنی تخصصی دانشگاهی تغذیه‌ای مشاوره‌ای
تلفنی پستی بانکی اینترنتی موبایلی همگانی خانگی باشگاهی گروهی انفرادی سنی جنسی عاطفی ژنتیکی هورمونی
ماهیانه سالیانه صبحگاهی شامگاهی عادی معمولی واقعی قانونی میلادی قمری شمسی هجری مرجوعی
""".split()

#: Qualitative adjectives: «غذای سالم», «وزنهٔ سنگین». They can also be what is SAID about the noun («بچه‌ها سالم رسیدند»), so the ezafe in
#: front of them is added only when what follows them cannot be a verb (a boundary, «و», a preposition, «را», a noun ...).
QUAL = """
سالم سنگین سبک تازه جدید نو نوین بزرگ کوچک مناسب مقوی خوشمزه عالی قوی ضعیف سخت آسان ساده کامل مهم ضروری مفید مضر
پرانرژی ارزان گران باکیفیت زیبا قشنگ خوشگل معتبر موثر مؤثر پایدار منظم هدفمند متنوع متعادل کم‌چرب پرچرب کم‌کالری پرپروتئین
تمیز شیک خنک گرم سرد داغ تلخ شیرین ترش سفید سیاه قرمز آبی سبز زرد صورتی شاد غمگین ناراحت خسته بیمار مریض امن پاک
بلند کوتاه عمیق وسیع نرم سفت لاغر چاق قدرتمند حساس جذاب کارآمد آماده مشخص معین دلخواه پیشنهادی مطمئن ایمن عزیز گرامی
محترم ارجمند مهربان صمیمی حرفه‌ای باهوش هوشمند خلاق مستقل رضایت‌بخش لذیذ پخته خام کافی لازم ممکن مختلف گوناگون
عجیب جالب ارزشمند باارزش مختصر دقیق‌تر قوی‌تر سالم‌تر سبک‌تر بهتر بدتر بزرگ‌تر کوچک‌تر تازه‌کار باتجربه کم‌تجربه
پرمصرف پرطرفدار محبوب معروف مشهور فعال پیر جوان نوجوان خوش‌اندام متناسب قابل‌اعتماد قابل‌اطمینان پرکار
""".split()

#: Adjectives that are also adverbs («سریع جواب داد», «خوب کار می‌کند»): the ezafe goes in front of them only at the end of the
#: phrase («منبع خوب.», «ارسال سریع و ...»), where nobody can take them for adverbs.
AMBIG = """
خوب بد زیاد کم سریع آرام آهسته دقیق راحت جدی درست غلط مستقیم محکم تند کند زود دیر بیشتر کمتر بیش بالا پایین
""".split()

#: Pronouns that can be a possessor («کتابِ من», «برنامهٔ شما»).
POSSESSOR = """من تو او ما شما ایشان آنها آن‌ها اینها این‌ها""".split()
#: «کارِ خود را» - a reflexive after a noun is always the possessor.
REFLEXIVE = """خود خودم خودت خودش خودمان خودتان خودشان""".split()

#: Nouns that nearly always take a genitive noun after them («کاهشِ وزن», «قیمتِ محصول», «ساعتِ تمرین»). Only these may link
#: two nouns automatically; any other pair of nouns («علی کتاب ...», «شنا حرکت‌ها ...») is left alone.
HEADS = """
کاهش افزایش کنترل مدیریت سلامت کیفیت قیمت هزینه ساعت روش نحوه شیوه هدف نتیجه نتایج تاثیر تأثیر اثر فواید فایده مزایا معایب
مشکل مشکلات اهمیت نیاز ادامه شروع پایان آغاز انتخاب تعیین محاسبه تولید ساخت طراحی دسترسی امکانات خدمات مجموعه انواع نوع
تعداد مقدار میزان سطح بخش قسمت لیست فهرست گزارش جلسه دوره زمان مدت وقت لحظه روز نام شماره آدرس رمز کد پیام نظر
عکس ویدیو فیلم صدا تصویر متن فایل پرونده کتابخانه محیط عضله بدن پوست قلب تعریف توضیح توضیحات اطلاعات ثبت ارسال پرداخت
سفارش تحویل خرید فروش مصرف استفاده شرایط قوانین قانون حریم برنامه مربی‌گری بررسی آموزش مشاوره پشتیبانی تغذیه ریکاوری
شهر کشور استان روستا خیابان کوچه رودخانه دریا کوه پاسخ جواب
""".split()

#: Nouns that take the ezafe in front of a brand name («اپِ چغر», «پنلِ چغر», «تیمِ چغر»).
PRODUCT_HEADS = """
اپ اپلیکیشن برنامه پنل سایت وب‌سایت نسخه محصول تیم حساب دستیار پلتفرم سرویس کانال صفحه پروفایل اشتراک
""".split()

#: Prepositional nouns: «کنارِ شما», «رویِ من». They take the ezafe only in front of a pronoun.
PREP_NOUNS = """کنار روی زیر بالای جلوی پشت بین میان پیش مقابل برابر""".split()

#: «شهرِ تهران», «کشورِ ایران»: the place word takes the ezafe in front of the name of the place (a name or a word nobody lists).
PLACE_HEADS = """شهر کشور استان روستا خیابان کوچه رودخانه دریاچه""".split()

#: Brand, product and platform names: never linked to what follows by the layer («با چغر برنامه بساز» is not «چغرِ برنامه»). The writer
#: can still write the mark («چغرِ عزیز»).
BRANDS = """
چغر چغراپ چغر‌اپ ان‌ام‌مارکتینگ ان‌ام اینستاگرام تلگرام واتساپ یوتیوب گوگل اپل سامسونگ اندروید آیفون چت‌جی‌پی‌تی اوپن‌ای‌آی
ایکس لینکدین دیجی‌کالا
""".split()

#: Titles and first names / surnames: a name is not followed by an ezafe («علی کتاب می‌خواند», «دکتر علی رضایی»). The lexicon's own
#: name list (category «نام‌ها») is added at run time; these are the ones it lacks.
TITLES = """دکتر مهندس آقای خانم استاد جناب سرکار حاج حاجی سید سیده شیخ سرهنگ سروان سرگرد کاپیتان مرحوم مرحومه""".split()
NAMES = """
علی محمد حسین حسن رضا مهدی امیر سارا نگار نرگس سمیه فاطمه زهرا مریم محمدرضا علیرضا امیرعلی امیرحسین پوریا آرش آرمان کیارش
آرین نیلوفر مهناز مهسا ندا الهام الناز مینا لیلا پریسا شیما ساناز ماهان کامران کیوان بهرام بهزاد پرویز فرهاد شهرام داریوش
فرزاد سجاد وحید عباس کاظم جعفر اصغر اکبر احمد محسن مصطفی ناصر نادر مجید حمید سعید ابراهیم اسماعیل یوسف موسی عیسی
رضایی محمدی احمدی کریمی حسینی موسوی جعفری اکبری یوسفی صادقی قاسمی کاظمی رحیمی عباسی نوری حیدری ملکی کاشانی
هادی حامد مسعود امین ایمان یاسر یاسین مرتضی میلاد سینا آریا آروین ارش پارسا پدرام بابک سهراب سام کوروش آیدا آزاده
آزیتا آناهیتا بنفشه پگاه ترانه ثریا دنیا رها روشنک ستاره سحر سپیده شادی شبنم شهلا شیدا غزل فرشته کیمیا گلناز لادن مژگان
مرجان ملیکا ملینا نازنین نسترن هستی هانیه یاسمن یلدا
""".split()

#: Common nouns the shared lexicon does not list. They count as nouns for the first word of a pair (the lexicon's own nouns
#: with tag N count too).
COMMON_NOUNS = """
کفش لباس شلوار کیف ماشین شهر کشور روستا استان خیابان کوچه خانواده فرزند پسر دختر همسر همکار همکاران شهروندان دانشجو
دانش‌آموز شاگرد پزشک پرستار آشپز راننده فروشنده خریدار دفتر قلم میز تخت فرش چای آب نان برنج مرغ ماهی سبزی ماست پنیر
تخم‌مرغ شکلات شکر نمک روغن سالاد سوپ فصل بهار تابستان پاییز زمستان انرژی روغن زبان مقاله وب‌سایت گوشی سفر مسیر برنامه
هدیه تجربه گارانتی تخفیف پیشنهاد بسته مدیر معلم دوست دوستان همراه مادر پدر رنگ ماست آدرس شماره ایمیل موبایل
زندگی درگاه عبور کارت قلب مغز استخوان مفصل ریه کبد معده روده پوست مو چشم دست پا سر صورت گردن شانه سینه کمر شکم ران ساق زانو مچ آرنج
تصمیم تصمیمات ایده فکر نکته پرسش پاسخ سوال جواب مطلب خبر گزارش تحلیل کتاب سریال بازی ورزش
جلسات کلاس آزمون امتحان درس دانشگاه شرکت کارخانه کارگاه بازار مغازه
رفتار انگیزه اراده توان قدرت سرعت استقامت تعادل انعطاف تمرکز آرامش استرس خواب بیداری
وزنه دمبل هالتر طناب کش توپ تشک دستگاه تردمیل دوچرخه پیست استخر سالن زمین
صبحانه ناهار شام میان‌وعده وعده خوراک نوشیدنی شیرینی دسر حبوبات غلات
پروتئین کربوهیدرات چربی ویتامین مکمل املاح کالری دوغ
تلفن رایانه لپ‌تاپ تبلت اینترنت شبکه گذرواژه
بدنسازی تناسب اندام لاغری چاقی رژیم سلامتی بهداشت درمان دارو بیماری درد آسیب
مصرف‌کننده مخاطب بینندگان شنوندگان
""".split()

#: A verb form (the clause-end test for qualitative adjectives): the common 3rd person past forms and imperatives that do not
#: look like verbs. Everything with «می‌», a personal ending or «ب» + stem is recognised by ``ezafe._is_verbish``.
VERB_FORMS = """
رفت آمد گفت دید شنید خرید فروخت داد گرفت کرد شد رسید ماند افتاد ایستاد نشست خوابید خورد نوشت خواند پخت ساخت برد آورد
گذاشت بود نبود نکرد نشد بگو بیا برو بده بگیر بساز بخور بنویس بخوان ببین بخر بفروش بزن بشین بمان بدو بپر بپوش بردار بنوش
""".split()

#: Light-verb stems («کرد/کن», «شد», «می‌شود») make an adjective a result («خانه تمیز کرد», «غذا آماده شد»): the ezafe in
#: front of an adjective is blocked when one of these follows. (Unlike «داد», «گرفت»: «مربی تمرین جدید داد» is an ordinary phrase.)
RESULT_VERBS = """
کرد کردن کردند کردم کردی کردیم کردید کن کنم کنی کند کنیم کنید کنند نکرد نکن نکنید می‌کند می‌کنم می‌کنی می‌کنیم می‌کنید می‌کنند
نمی‌کند نمی‌کنم نمی‌کنید نمی‌کنند شد شدن شدند شدم شدی شدیم شدید می‌شود می‌شوند می‌شوم می‌شوی می‌شویم می‌شوید نمی‌شود نمی‌شوند
نشد بشود بشوند بشو بشوید گشت گردید می‌گردد شو شوید شوم شویم شوند شوی نشو نشوید
""".split()

#: Person words: «مربی خودش ...» is the coach himself, not «مربیِ خودش».
PERSON = """
مربی ورزشکار مشتری کاربر مدیر معلم استاد دکتر پزشک پدر مادر دوست دوستان پسر دختر همسر برادر خواهر همکار همکاران شاگرد دانشجو
بچه‌ها بچه فرزند رئیس رییس مسئول مشاور فروشنده خریدار پرستار آشپز راننده مرد زن آدم انسان کسی نفر
""".split()

# ---------------------------------------------------------------------------------------------------------------- round 4
#: Quantifiers: «هر روز» (every day), «هیچ وقت» (never), «چند ساعت» (some hours), «همه روز», «تمام وقت». A time or counting word right after
#: one of these says WHEN or HOW MANY («هر روز آب بنوش»); it is not the head of a genitive («روزِ آب» is nonsense), so it takes no automatic ezafe.
QUANTIFIERS = """هر هیچ چند چندین همه بعضی برخی تمام کل هرگونه هریک""".split()

#: Demonstratives: «این روزها», «آن وقت», «همین ساعت». A TIME word after one is an adverb as well («آن روز تمرین را سبک گرفتم»); a counting word after
#: one is a normal head («این بخشِ برنامه») unless a time, counting or measure word follows it.
DEMONSTRATIVES = """این آن همین همان""".split()

#: Words that say WHEN: adverbials after a quantifier, a demonstrative or a number.
TIME_WORDS = """
روز وقت ساعت لحظه زمان مدت هفته ماه سال شب صبح ظهر عصر بامداد غروب دقیقه ثانیه دفعه بار نوبت فصل
""".split()

#: Words that say HOW MUCH / HOW MANY: after ANY determiner or number («همین مقدار آب بنوش», «این تعداد تکرار», «چند میزان») they measure what
#: follows, they do not own it.
AMOUNT_WORDS = """
تعداد مقدار میزان سطح عدد
""".split()

#: Words for a PART of something («بخش», «جلسه», «مرحله»): after a quantifier or a number they count («چند جلسه تمرین کن», «هر مرحله تمرین را ...»);
#: after a demonstrative they are ordinary heads («این بخشِ برنامه را بخوان»).
#: (A classifying adjective after them still takes the ezafe: «دو جلسهٔ رایگان», «هر جلسهٔ تمرینی».)
PART_WORDS = """
بخش قسمت مرحله جلسه دوره رده نوبت
""".split()

QUANTITY_WORDS = AMOUNT_WORDS + PART_WORDS

#: «مربی تغذیه», «مشاور ورزشی», «متخصص سلامت»: a role word + its field. The field belongs to the role; it is not the head of what follows it
#: («مربی تغذیه برنامهٔ غذایی می‌نویسد», not «تغذیهٔ برنامه»). A title is a role too («دکتر تغذیه برنامه می‌نویسد»).
ROLES = """مربی مشاور متخصص کارشناس پزشک معلم استاد مدرس دکتر روانشناس فیزیوتراپیست درمانگر""".split()
ROLE_FIELDS = """تغذیه ریکاوری مشاوره آموزش پشتیبانی سلامت بدنسازی مربی‌گری تناسب""".split()
