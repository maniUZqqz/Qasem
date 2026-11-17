"""The shared pronunciation lexicon: words a Persian voice gets wrong without help.

Format, one entry per line:   <word>  <PN>  [tag]
  * PN is the notation described in ``phones.py`` (a=æ  A=ā  S=ش  q=غ/ق  '=ع/ء ...)
  * «_» inside a word stands for a half-space (ZWNJ)
  * tag:  N noun/adjective (takes ezafe)   F function word / pronoun (never)
          V verb (never)   -  nothing special
  * a line «## name» starts a category (shown in the panel); «## name ~» marks a
    category whose words engines read right on their own - they are only substituted
    at depth «full» (a «!» in front of a word forces it back on)

This is the *curated* list: words where the plain letter rules (``g2p.py``) or the
voice's own front end are known or likely to be wrong - ع/ء words, final «ه» that is
/h/, «و»/«او» words, «ی» that is /ey/, numbers, ordinals, loan words from the
fitness / app domain of the owner's product, and everyday function words. A store
can add its own words in the panel; those win over this list.

Words that the rules already get right are deliberately NOT listed, except a few
whose correctness matters a lot to the owner (brand, product vocabulary).

Pronunciation targets standard Tehrani Persian as read by a careful newsreader,
with the colloquial reductions that a modern voice-over would use left to the
voice (e.g. «sizdah», not «sizde»).
"""

SHARED_TEXT = r"""
## اعداد ~
یک yek N
دو do
سه se
چهار CahAr
پنج panj
شش SeS
هفت haft
هشت haSt
نُه noh
ده dah
یازده yAzdah
دوازده davAzdah
سیزده sizdah
چهارده CahArdah
پانزده pAnzdah
شانزده SAnzdah
هفده hefdah
هجده hejdah
نوزده nuzdah
بیست bist
سی si
چهل Cehel
پنجاه panjAh
شصت Sast
هفتاد haftAd
هشتاد haStAd
نود navad
صد sad
دویست devist
سیصد sisad
چهارصد CahArsad
پانصد pAnsad
ششصد SeSsad
هفتصد haftsad
هشتصد haStsad
نهصد nohsad
هزار hazAr
میلیون milyun
میلیارد milyArd
تریلیون tirilyun
کوادریلیون kuAdrilyun
صفر sefr
نیم nim N
منفی manfi
ممیز mamiz
دهم dahom
اول avval N
یکم yekom
دوم dovvom
سوم sevvom
چهارم CahArom
پنجم panjom
ششم SeSom
هفتم haftom
هشتم haStom
نهم nohom
بیستم bistom
سی_ام siyom
صدم sadom
هزارم hazArom
نصف nesf
دهم dahom
صدم sadom
تومان tumAn
ریال riyAl
درصد darsad
دلار dolAr
یورو yuro
سنت sent
## ع و ء
عالی 'Ali N
عادت 'Adat N
عادی 'Adi N
عاشق 'ASeq N
عالم 'Alam N
عامل 'Amel N
عبارت 'ebArat N
عدد 'adad N
عدم 'adam N
عرض 'arz N
عرضه 'arze N
عزیز 'aziz N
عصر 'asr N
عصبی 'asabi N
عضو 'ozv N
عضله 'azale N
عضلات 'azalAt N
عقل 'aql N
عقیده 'aqide N
علاقه 'alAqe N
علاقه_مند 'alAqemand N
علامت 'alAmat N
علت 'ellat N
علم 'elm N
علمی 'elmi N
علی 'ali N
علاوه 'alAve N
عمر 'omr N
عمل 'amal N
عملی 'amali N
عملکرد 'amalkard N
عمومی 'omumi N
عموما 'omuman F
عمیق 'amiq N
عنوان 'onvAn N
عکس 'aks N
عکاسی 'akkAsi N
عکاس 'akkAs N
عید 'id N
عیدی 'idi N
عجیب 'ajib N
عجله 'ajale N
عشق 'eSq N
عطر 'atr N
عقب 'aqab N
عمق 'omq N
عهد 'ahd N
عوض 'avaz N
عوامل 'avAmel N
عوارض 'avArez N
عرق 'araq N
عسل 'asal N
عظیم 'azim N
عاقل 'Aqel N
عاطفه 'Atefe N
عاطفی 'Atefi N
عیب 'eyb N
عین 'eyn N
عینک 'eynak N
عادلانه 'AdelAne N
عاشقانه 'ASeqAne N
عرب 'arab N
عربی 'arabi N
عراق 'erAq N
عمان 'omAn N
عطا 'atA N
عفو 'afv N
عفونت 'ofunat N
عمارت 'emArat N
عمده 'omde N
عمدتا 'omdatan F
عمودی 'amudi N
عنصر 'onsor N
عوام 'avAm N
عیاری 'ayyAri N
معنی ma'ni N
معنا ma'nA N
معنوی ma'navi N
معمولا ma'mulan F
معمولی ma'muli N
معتبر mo'tabar N
معلم mo'allem N
معلمی mo'allemi N
معرفی ma'rafi N
معروف ma'ruf N
معین mo'ayyan N
معیار me'yAr N
معضل mo'zel N
معده me'de N
معاون mo'Aven N
معامله mo'Amele N
معاینه mo'Ayene N
معذرت ma'zerat N
معجزه mo'jeze N
معاف mo'Af N
متعادل mo'tadel N
تعادل ta'Adol N
تعداد te'dAd N
تعریف ta'rif N
تعطیل ta'til N
تعطیلات ta'tilAt N
تعهد ta'ahhod N
تعویض ta'viz N
تعامل ta'Amol N
تعیین ta'yin N
تعلیم ta'lim N
تعمیر ta'mir N
تعجب ta'ajjob N
تعلق ta'alloq N
تعقیب ta'qib N
تاثیر ta'sir N
تاکید ta'kid N
تایید ta'yid N
تامین ta'min N
تاخیر ta'xir N
تاسیس ta'sis N
تاسف ta'assof N
مامور ma'mur N
ماموریت ma'muriyyat N
مسئول mas'ul N
مسئولیت mas'uliyyat N
مسوول mas'ul N
سوال so'Al N
سوالات so'AlAt N
جرات jor'at N
جرئت jor'at N
رییس ra'is N
رئیس ra'is N
موسسه mo'assese N
موثر mo'asser N
متاسفانه mota'assefAne F
مومن mo'men N
ملائکه malA'eke N
مبدا mabda' N
مبدأ mabda' N
منشا manSa' N
شعر Se'r N
شعار Se'Ar N
شعله So'le N
شعبه Sa'be N
شعور So'ur N
شروع Soru' N
مشروع maSru' N
اطلاع etelA' N
اطلاعات etelA'At N
اجتماع ejtemA' N
اجتماعی ejtemA'i N
دفاع defA' N
سریع sari' N
وسیع vasi' N
مجموع majmu' N
مجموعه majmu'e N
موضوع mowzu' N
منبع manba' N
منابع manAbe' N
نوع now' N
انواع anvA' N
جامع jAme' N
جامعه jAme'e N
طبیعی tabi'i N
طبیعت tabi'at N
صنعت san'at N
صنعتی san'ati N
قطع qat' N
قطعا qat'an F
واقعا vAqe'an F
واقعی vAqe'i N
واقع vAqe' N
ضعیف za'if N
ضعف za'f N
رفع raf' N
مرجع marja' N
مطمئن motma'en N
اطمینان etminAn N
مراجعه morAje'e N
مطالعه motAle'e N
مصرف masraf N
ممنوع mamnu' N
مشاهده moSAhede N
ساعت sA'at N
ساعات sA'At N
قاعده qA'ede N
قاعدتا qA'edatan F
جمعه jom'e N
جمعیت jam'iyyat N
جمع jam' N
مجمع majma' N
اعتماد e'temAd N
اعتبار e'tebAr N
اعلام e'lAm N
اعلان e'lAn N
اعداد a'dAd N
اعضا a'zA N
اعضای a'zAye N
اعمال a'mAl N
اعتراض e'terAz N
اعتیاد e'tiyAd N
اعتقاد e'teqAd N
اعصاب a'sAb N
انعطاف en'etAf N
انعکاس en'ekAs N
تشکیل taSkil N
بعد ba'd N
بعدا ba'dan F
بعضی ba'zi N
بعضا ba'zan F
بعدی ba'di N
نعمت ne'mat N
نعناع na'nA' N
نفع naf' N
منفعت manfa'at N
مضاعف moza'af N
متعدد mota'added N
متعهد mota'ahhed N
تبعیض tab'iz N
شجاعت SajA'at N
وسعت vos'at N
توسعه towse'e N
سرعت sor'at N
سرعتی sor'ati N
قدرت qodrat N
عشایر 'aSAyer N
رفاه refAh N
جزء joz' N
جزئی joz'i N
مبدا mabda' N
وقایع vaqAye' N
اتفاق ettefAq N
اتفاقا ettefAqan F
قرآن qor'An N
مرآت mer'At N
تأکید ta'kid N
## ه و پایانی
ده dah
مه meh N
نه na F
که ke F
چه Ce F
به be F
سه se
ته te N
شه Sah N
آه Ah
اله 'elAh N
گناه gonAh N
اشتباه eStebAh N
کوتاه kutAh N
آگاه AgAh N
سیاه siyAh N
راه rAh N
ماه mAh N
شاه SAh N
کوه kuh N
شکوه Sokuh N
گروه goruh N
انبوه anbuh N
نگاه negAh N
پناه panAh N
دوباره dobAre F
همه hame F
همه_چیز hameCiz F
بچه baCCe N
بچه_ها baCCehA N
خانه xAne N
نامه nAme N
برنامه barnAme N
برنامه_ها barnAmehA N
برنامه_ریزی barnAmeriz N
مدرسه madrase N
تغذیه taqziye N
تصفیه tasfiye N
قضیه qaziyye N
حاشیه hASiye N
سرمایه sarmAye N
همسایه hamsAye N
رویه raviye N
آیه Aye N
تسویه tasviye N
ماهیه mAhiye N
نتیجه natije N
نتیجه_گیری natijegiri N
میوه mive N
شیوه Sive N
جلوه jelve N
قهوه qahve N
نحوه nahve N
دوره dore N
دوره_ای dorei N
مجموعه majmu'e N
وعده va'de N
وعده_ها va'dehA N
وعده_غذایی va'deqazAyi N
توصیه towsiye N
توضیح towzih N
توضیحات towzihAt N
خواهر xAhar N
برادر barAdar N
مادر mAdar N
پدر pedar N
خوشحال xoSAl N
نحوه nahve N
فایده fAyede N
فایده_ها fAyedehA N
ایده ide N
نمونه nemune N
نکته nokte N
نکات nokAt N
رابطه rAbete N
مسئله mas'ale N
مساله mas'ale N
مسابقه mosAbeqe N
مصاحبه moSAhebe N
مطالعه motAle'e N
معاینه mo'Ayene N
مجله majalle N
مقاله maqAle N
منطقه mantaqe N
مجموعه majmu'e N
وسیله vasile N
وظیفه vazife N
ویژه vije N
ویژگی vijegi N
هزینه hazine N
هدیه hediye N
تخفیف taxfif N
کلمه kalame N
جمله jomle N
لحظه lahze N
لحظه_ای lahzei N
نسخه nosxe N
نسبت nesbat N
نظریه nazariye N
نقطه noqte N
نقشه naqSe N
چهره Cehre N
چهره_ها CehrehA N
خلاصه xolAse N
دقیقه daqiqe N
ثانیه sAniye N
هفته hafte N
هفته_ای haftei N
حوصله hosele N
حوصله_ام hoseleam N
انگیزه angize N
خاطره xAtere N
خاطرات xAterAt N
ارزش arzeS N
ارزشمند arzeSmand N
پروژه poroje N
پرونده parvande N
پروتئین porotein N
کلاس kelAs N
کلاس_ها kelAsehA N
## و و او
او u F
وی vey F
اوه ove
اوج owj N
اوقات owqAt N
اوضاع owzA' N
اورژانس orZAns N
اولین avvalin N
اول avval N
اونها unhA F
اینها inhA F
آنها AnhA F
شما SomA F
ما mA F
من man F
تو to F
نو now N
نوین nowin N
کو ku
رو ro
سو so N
هو hu
مو mu N
بو bu N
جو jow N
گو gu
لو low
خوب xub N
خوبی xubi N
خوب_تر xubtar N
خون xun N
خونه xune N
خوک xuk N
خود xod F
خودم xodam F
خودت xodat F
خودش xodaS F
خودمان xodemAn F
خودتان xodetAn F
خودشان xodeSAn F
خودکار xodkAr N
خودرو xodro N
خورد xord V
خوردن xordan N
خوراک xorAk N
خوراکی xorAki N
خورشید xorSid N
خوش xoS N
خوشمزه xoSmaze N
خوشگل xoSgel N
خوشبختانه xoSbaxtAne F
خواب xAb N
خواب_ها xAbhA N
خواست xAst V
خواستن xAstan N
خواسته xAste N
خواهش xAheS N
خواهر xAhar N
خواهم xAham V
خوانده xAnde N
خواندن xAndan N
خواننده xAnande N
خواهد xAhad V
دوست dust N
دوستان dustAn N
دوستی dusti N
دوست_داشتن dustdAStan N
دور dur N
دوری duri N
دوره dore N
دوباره dobAre F
دوچرخه doCarxe N
دوچرخه_سواری doCarxesavAri N
روز ruz N
روزانه ruzAne N
روزها ruzhA N
روزی ruzi N
امروز emruz F
دیروز diruz F
هر_روز harruz F
نوروز nowruz N
روش raveS N
روان ravAn N
روانی ravAni N
رویا royA N
رودخانه rudxAne N
کودک kudak N
کودکان kudakAn N
کوچک kuCak N
کوچکتر kuCaktar N
گوشت guSt N
گوش guS N
گوشی guSi N
موج mowj N
موجود mowjud N
موجودی mowjudi N
موش muS N
موتور motor N
موبایل mobAyl N
موز moz N
موسیقی musiqi N
مورد mored N
موقع mowqe' N
موقعیت mowqe'iyyat N
موافق movAfeq N
موافقت movAfeqat N
موفق movaffaq N
موفقیت movaffaqiyyat N
مواد mavAd N
موادغذایی mavAdeqazAyi N
مواظب movAzeb N
مواظبت movAzebat N
موضع mowze' N
مهندس mohandes N
مهم mohem N
مهمان mehmAn N
هوش huS N
هوشمند huSmand N
هوا havA N
هواپیما havApeymA N
هوس havas N
هورمون hormon N
توان tavAn N
توانایی tavAnAyi N
توانستن tavAnestan N
توانست tavAnest V
نوشتن neveStan N
نوشت neveSt V
نوشته neveSte N
نویسنده nevisande N
بنویس benevis V
بنویسید benevisid V
می_نویسم minevisam V
قوانین qavAnin N
قانون qAnun N
قانونی qAnuni N
قوه qovve N
قوی qavi N
قویتر qaviter N
قوت qovvat N
ثروت servat N
نوار navAr N
نوازش navAzeS N
هوادار havAdAr N
تولید towlid N
تولد tavallod N
تولدت tavalodet N
توصیف towsif N
توجه tavajjoh N
توقف tavaqqof N
تورم tavarrom N
توسط tavassot F
تحویل tahvil N
تقویت taqviyat N
تقویم taqvim N
تقویتی taqviyati N
ورزش varzeS N
ورزشکار varzeSkAr N
ورزشی varzeSi N
ورزش_ها varzeShA N
وزن vazn N
وزنه vazne N
وزنه_برداری vaznebardAri N
وزنی vazni N
وضعیت vaz'iyyat N
وضع vaz' N
وقت vaqt N
وقتی vaqti F
وجود vojud N
وارد vAred N
وای vAy
وسایل vasAyel N
وسط vasat N
ویدیو vidiyo N
ویدئو vidiyo N
ویتامین vitAmin N
ویتامین_ها vitAminhA N
ویرایش virAyeS N
ویروس virus N
وب veb N
وب_سایت vebsAyt N
وبلاگ vebelAg N
وصل vasl N
وقتی vaqti F
ورود vorud N
وام vAm N
واحد vAhed N
واکنش vAkoneS N
واکسن vAksan N
ولی vali F
ولو valow F
ولع valla N
و o F
## ی و ای ~
ای ey F
پی pey N
کی ki F
چی Ci F
می mi F
نمی nemi F
بی bi F
پیش piS N
پیدا peydA N
خیلی xeyli F
غیر qeyr N
غیره qeyre F
عین 'eyn N
شیخ Seyx N
خیر xeyr N
پیام payAm N
پیمان peymAn N
پیوند peyvand N
پیروز piruz N
پیراهن pirAhan N
پیر pir N
پیاده piyAde N
پیاده_روی piyAderavi N
پیشنهاد piSnahAd N
پیشرفت piSraft N
پیشگیری piSgiri N
پیگیری peygiri N
پیکر peykar N
بیمه bime N
بیمار bimAr N
بیماری bimAri N
بیمارستان bimArestAn N
بیان bayAn N
دین din N
دیدن didan N
دیگر digar F
دیر dir N
زیر zir N
زیبا zibA N
زیاد ziyAd N
زیست zist N
ایده ide N
ایمن imen N
ایمنی imeni N
ایمیل imeyl N
ایستگاه istgAh N
ایجاد ijAd N
ایشان iSAn F
این in F
اینترنت internet N
اینستاگرام instAgerAm N
ایمان imAn N
ایران irAn N
ایرانی irAni N
بیست bist
بیش biS N
بیشتر biStar N
کمتر kamtar N
بیرون birun N
بیدار bidAr N
بیکار bikAr N
نیاز niyAz N
نیازمند niyAzmand N
نیرو niru N
نیروی niruye N
نیمه nime N
نیست nist V
نیز niz F
نیکو nikow N
میز miz N
میدان meydAn N
میل meyl N
میان miyAn N
میانه miyAne N
میزان mizAn N
فیلم film N
فیلم_برداری filmbardAri N
کیف kif N
کیفیت kayfiyyat N
کیلو kilo N
کیلوگرم kilogerAm N
کیلومتر kilumetr N
کیک kik N
لیست list N
لیوان livAn N
لیمو limu N
تیم tim N
تیر tir N
تیز tiz N
ثبت sabt N
ثبت_نام sabtenAm N
جیب jib N
حیوان heyvAn N
حیاط hayAt N
حیات hayAt N
حیف heyf N
خیابان xiyAbAn N
خیال xiyAl N
خیس xis N
دیوار divAr N
دیو div N
ریسک risk N
سیب sib N
سیر sir N
سیاه siyAh N
سیستم sistem N
سیگار sigAr N
شیر Sir N
شیرین Sirin N
شیمی Simi N
طیف teyf N
غیبت qeybat N
فیزیک fizik N
قیمت qeymat N
قیام qiyAm N
گیاه giyAh N
گیاهی giyAhi N
گیر gir
مدیر modir N
مدیریت modiriyyat N
نیکی niki N
هیچ hiC F
هیجان heyajAn N
هیجان_انگیز heyajAnangiz N
هیکل heykal N
یخ yax N
یخچال yaxCAl N
یکی yeki F
یاد yAd N
یادگیری yAdgiri N
یادداشت yAddASt N
یادآوری yAdAvari N
یا yA F
یار yAr N
یوگا yogA N
## کلمه‌های ربط و قیدها ~
از az F
در dar F
با bA F
بر bar F
تا tA F
برای barAye F
مانند mAnand F
مثل mesl N
درباره darbAre F
درباره_ی darbAreye F
بدون bedun F
قبل qabl N
پس pas F
روی ruye N
کنار kenAr N
بالای bAlAye N
پایین pAyin N
پایین_تر pAyintar N
جلوی jeloye N
پشت poSt N
مقابل moqAbel N
بین beyn N
همراه hamrAh N
طی tey F
جز joz F
حتی hattA F
فقط faqat F
تنها tanhA F
اما ammA F
اگر agar F
چون Cun F
زیرا zirA F
هم ham F
هر har F
آن An F
اینجا injA F
آنجا AnjA F
اینکه inke F
آنکه Anke F
چرا CerA F
چطور Cetor F
چگونه Cegune F
کجا kojA F
کدام kodAm F
چند Cand F
چقدر Caqadr F
چنین Canin F
همچنین hamCenin F
همیشه hamiSe F
هرگز hargez F
هنوز hanuz F
بسیار besyAr F
کاملا kAmelan F
مثلا masalan F
ضمنا zemnan F
فعلا fe'lan F
لطفا lotfan F
احتمالا ehtemAlan F
تقریبا taqribAn F
مخصوصا maxsusan F
اصلا aslan F
حتما hatman F
قطعا qat'an F
دقیقا daqiqan F
حداقل haddeaqal F
حداکثر haddeakSar F
حدود hodud F
بالاخره bAlAxare F
نهایتا nahAyatan F
خصوصا xosusan F
همین hamin F
همان hamAn F
هیچوقت hiCvaqt F
هیچ_وقت hiCvaqt F
انشاالله inSAlA F
ان_شاءالله inSAlA F
ماشاالله mASAlA F
را rA F
## ورزش و تناسب اندام
باشگاه bASgAh N
باشگاه_ها bASgAhhA N
مربی morabbi N
مربیگری morabbigari N
مربی_گری morabbigari N
تمرین tamrin N
تمرینات tamrinAt N
تمرین_ها tamrinhA N
تناسب tanAsob N
اندام andAm N
لاغری lAqari N
چاقی CAqi N
چربی Carbi N
چربی_سوزی Carbisuzi N
عضله_سازی 'azalesAzi N
حجم hajm N
حجم_دهی hajmdehi N
رژیم reZim N
رژیمی reZimi N
غذا qazA N
غذایی qazAyi N
تغذیه taqziye N
کالری kAlori N
کربوهیدرات karbohidrAt N
مکمل mokammel N
مکمل_ها mokammelhA N
استراحت esterAhat N
ریکاوری rikAveri N
گرم_کردن garmkardan N
کشش keSeS N
حرکت harekat N
حرکات harakAt N
ست set N
تکرار tekrAr N
دمبل dambel N
هالتر hAlter N
دستگاه dastgAh N
تردمیل terdmil N
طناب tanAb N
شنا SenA N
دویدن davidan N
پلانک pelAnk N
اسکات eskAt N
بارفیکس bArfiks N
پرس pors N
ددلیفت dedlift N
کاردیو kArdiyo N
پیلاتس pilAtes N
کراس_فیت kerAsfit N
بدنسازی badansAzi N
بدن badan N
شانه SAne N
سینه sine N
کمر kamar N
شکم Sekam N
ران rAn N
ساق sAq N
ماهیچه mAhiCe N
مفصل mafsal N
آسیب Asib N
آسیب_دیدگی Asibdidegi N
گرفتگی gereftegi N
درد dard N
سلامت salAmat N
سلامتی salAmati N
سالم sAlem N
هدف hadaf N
اهداف ahdAf N
پیشرفت piSraft N
تغییر taqyir N
تحول tahavvol N
چالش CAleS N
روزانه ruzAne N
هفتگی haftegi N
ماهانه mAhAne N
قدرتی qodrati N
استقامت esteqAmat N
استقامتی esteqAmati N
انعطاف_پذیری en'etAfpaziri N
هماهنگی hamAhangi N
تعادل ta'Adol N
چغر Caqar N
چغر_اپ Caqar-ap N
## برنامه، اپ و فروش
اپلیکیشن eplikeySan N
اپ ap N
دانلود dAnlod N
آنلاین Anlayn N
آفلاین Aflayn N
پلن pelan N
پکیج pakij N
پروفایل porofAyl N
اکانت akAnt N
لایک lAyk N
کامنت koment N
فالو fAlo N
فالوور fAlower N
پست post N
استوری estori N
ریلز rilz N
کانال kAnAl N
تلگرام telegerAm N
واتساپ vAtsAp N
یوتیوب yutyub N
گوگل gugel N
اندروید Andoroyd N
آیفون Ayfon N
اپل apel N
سامسونگ sAmsung N
کد kod N
لینک link N
سایت sAyt N
ایمیل imeyl N
پسورد pasvord N
رمز ramz N
رمز_عبور ramzeoboor N
ورود vorud N
اشتراک eStarAk N
رایگان rAyegAn N
ارسال ersAl N
سفارش sefAreS N
پشتیبانی poStibAni N
مشاوره moSAvere N
مشاور moSAver N
نسخه nosxe N
آموزش AmuzeS N
آموزشی AmuzeSi N
مربی_گری morabbigari N
برنامه_غذایی barnAmeqazAyi N
برنامه_تمرینی barnAmetamrini N
تمرینی tamrini N
دسترسی dastrasi N
امکانات emkAnAt N
قابلیت qAbeliyyat N
قابلیت_ها qAbeliyyathA N
کاربر kArbar N
کاربران kArbarAn N
کاربری kArbari N
مشتری moStari N
مشتریان moStariyAn N
فروش foruS N
فروشگاه foruSgAh N
محصول mahsul N
محصولات mahsulAt N
کیفیت kayfiyyat N
ضمانت zamAnat N
گارانتی gArAnti N
مرجوعی marjuyi N
پرداخت pardAxt N
پرداخت_ها pardAxthA N
قیمت qeymat N
ارزان arzAn N
گران gerAn N
## هم‌نویسه‌ها و واژه‌های پرخطا
کار kAr N
کارها kArhA N
کاری kAri N
گفت goft V
گفتن goftan N
کرد kard V
کردن kardan N
شد Sod V
شده Sode N
شدن Sodan N
بود bud V
بودن budan N
هست hast V
است ast V
نیستم nistam V
هستم hastam V
هستیم hastim V
هستید hastid V
هستند hastand V
باشد bASad V
باشید bASid V
باید bAyad F
شاید SAyad F
نباید nabAyad F
می_توان mitavAn V
می_توانید mitavAnid V
می_خواهید mixAhid V
می_خواهم mixAham V
می_خواهی mixAhi V
می_کنید mikonid V
می_کنم mikonam V
می_کند mikonad V
می_شود miSavad V
می_شوید miSavid V
می_دهد midahad V
می_دهید midahid V
می_دانید midAnid V
می_دانم midAnam V
می_رود miravad V
می_روید miravid V
می_آید miyAyad V
می_آیید miyAyid V
می_گویند miguyand V
می_گوید miguyad V
می_بینید mibinid V
می_بینم mibinam V
بگیرید begirid V
بگیر begir V
بکنید bekonid V
بروید beravid V
بیایید biyAyid V
بیا biyA V
بیاورید biyAvarid V
ببینید bebinid V
ببین bebin V
بخورید bexorid V
بخور bexor V
بدهید bedehid V
بدهید bedehid V
بدانید bedAnid V
بخوانید bexAnid V
بنویسید benevisid V
شروع_کنید Soru'konid V
شروع_کن Soru'kon V
شروع_کردن Soru'kardan N
انجام anjAm N
انجام_دهید anjAmdehid V
انجام_بده anjAmbede V
انجام_شد anjAmSod V
استفاده estefAde N
استفاده_کنید estefAdekonid V
استفاده_کن estefAdekon V
استفاده_از estefAdeaz
دریافت dariyAft N
دریافت_کنید dariyAftkonid V
ثبت_کنید sabtkonid V
ثبت_نام_کنید sabtenAmkonid V
نصب nasb N
نصب_کنید nasbkonid V
مطمئن motma'en N
مطمئنا motma'ennan F
اطمینان etminAn N
صبح sobh N
ظهر zohr N
عصر 'asr N
شب Sab N
شبانه Sabane N
شبانه_روز SabAneruz N
فردا fardA F
پس_فردا pasfardA F
دیشب diSab F
امشب emSab F
حالا hAlA F
الان alAn F
الآن alAn F
اکنون akonun F
سپس sepas F
سپس sepas F
گاهی gAhi F
گاه gAh F
اغلب aqlab F
غالبا qAleban F
دائما dA'eman F
داشتن dASan N
دارد dArad V
دارید dArid V
دارم dAram V
داریم dArim V
دارند dArand V
ندارد nadArad V
ندارید nadArid V
اینجور injowr F
اونجور unjowr F
همینطور hamintowr F
همین_طور hamintowr F
همچین hamCin F
چنان Canan F
آری Ari F
خیر xeyr F
بله bale F
نخیر naxeyr F
باشه bASe F
اوکی oke F
ممنون mamnun N
متشکرم motaSakkeram F
سپاس sepAs N
سپاسگزارم sepAsgozAram F
خداحافظ xodAhAfez F
سلام salAm N
درود dorud N
عزیزم 'azizam N
عزیزان 'azizAn N
دوستان_عزیز dustAne'aziz N
مهربان mehrabAn N
مهربانی mehrabAni N
ببخشید bebaxSid V
لطف lotf N
لطفا lotfan F
خواهشا xAheSan F
خواهش_می_کنم xAheSmikonam F
## نام ماه‌ها و روزها ~
فروردین farvardin N
اردیبهشت ordibeheSt N
خرداد xordAd N
تیر tir N
مرداد mordAd N
شهریور Sahrivar N
مهر mehr N
آبان AbAn N
آذر Azar N
دی dey N
بهمن bahman N
اسفند esfand N
شنبه Sanbe N
یکشنبه yekSanbe N
یک_شنبه yekSanbe N
دوشنبه doSanbe N
دو_شنبه doSanbe N
سه_شنبه seSanbe N
سه‌شنبه seSanbe N
چهارشنبه CahArSanbe N
چهار_شنبه CahArSanbe N
پنجشنبه panjSanbe N
پنج_شنبه panjSanbe N
جمعه jom'e N
ژانویه ZAnviye N
فوریه fevriye N
مارس mArs N
آوریل Avril N
مه me N
ژوئن Zuan N
ژوئیه Zuiye N
اوت owt N
سپتامبر septAmbr N
اکتبر oktobr N
نوامبر novAmbr N
دسامبر desAmbr N
میلادی milAdi N
شمسی Samsi N
هجری_شمسی hejriSamsi N
قمری qamari N
## واحدها ~
کیلومتر kilumetr N
متر metr N
سانتی_متر sAntimetr N
میلی_متر milimetr N
گرم gerAm N
کیلوگرم kilogerAm N
لیتر litr N
میلی_لیتر mililitr N
درجه daraje N
سانتی_گراد sAntigerAd N
دقیقه daqiqe N
ثانیه sAniye N
ساعت sA'at N
روز ruz N
ماه mAh N
سال sAl N
بایت bAyt N
مگابایت megAbAyt N
گیگابایت gigAbAyt N
ترابایت terAbAyt N
مگاهرتز megAhertz N
کیلووات kilovAt N
ولت volt N
آمپر Ampr N
بار bAr N
## نام‌های پرکاربرد
محمد mohammad
فاطمه fAteme
حسین hoseyn
حسن hasan
زهرا zahrA
مریم maryam
رضا rezA
مهدی mahdi
امیر amir
سارا sArA
نگار negAr
نرگس narges
سمیه somayye
ابراهیم ebrAhim
اسماعیل esmA'il
یوسف yusef
موسی musA
عیسی 'isA
مجید majid
حمید hamid
سعید sa'id
احمد ahmad
محسن mohsen
مصطفی mostafA
ناصر nAser
نادر nAder
بهرام bahrAm
بهزاد behzAd
پرویز parviz
فرهاد farhAd
شهرام SahrAm
کامران kAmrAn
کیوان keyvAn
سپیده sepide
ندا nedA
نازنین nAzanin
الهام elhAm
الناز elnAz
مینا minA
لیلا leylA
پریسا parisA
مهسا mahsA
شیما SimA
ساناز sAnAz
ماهان mAhAn
آرش AraS
آرمان ArmAn
پوریا puryA
مرتضی mortezA
علیرضا 'alirezA
محمدرضا mohammadrezA
امیرعلی amir'ali
امیرحسین amirhosein
حسام hesAm
اکبر akbar
اصغر asqar
جعفر ja'far
کاظم kAzem
عباس 'abbAs
سجاد sajjAd
ایمان imAn
وحید vahid
فرزاد farzAd
داریوش dAriyuS
تهران tehrAn N
## فعل‌ها و واژه‌های پرکاربرد
شو So V
بشو beSo V
دیده dide N
مردند mordand V
مردن mordan N
مردم mardom N
گرفت gereft V
گرفتن gereftan N
گرفتم gereftam V
گرفتی gerefti V
گرفتند gereftand V
گرفته gerefte N
می_گیرد migirad V
می_گیرم migiram V
می_گیری migiri V
می_گیریم migirim V
می_گیرید migirid V
می_گیرند migirand V
نمی_گیرد nemigirad V
بگیرد begirad V
بگیرید begirid V
نگیر negir V
کشتی_گیر kuStigir N
کشتی_گیری kuStigiri N
کشتی_گیران kuStigirAn N
کتاب ketAb N
جلسه jalase N
بزرگ bozorg N
سنگین sangin N
## واژه‌های آمیخته‌ی حرف و واژه
چت_جی_پی_تی Catjipiti
اوپن_ای_آی owpeneyAy
ان_ام_مارکتینگ enemmArketing
"""

#: Multi-word expressions that are read differently from their parts.
PHRASES_TEXT = r"""
ان شاءالله inSAlA
ان شاء الله inSAlA
إن شاء الله inSAlA
ما شاءالله mASAlA
ماشاء الله mASAlA
بسم الله besmellAh
بسم الله الرحمن الرحیم besmellAhirrahmAnirrahim
الحمدلله alhamdolellAh
سبحان الله sobhAnallAh
به علاوه be'alAve
به‌علاوه be'alAve
به خاطر be xAter
به‌خاطر bexAter
در مورد dar mored
در واقع dar vAqe'
در حال dar hAl
در حالی که dar hAli ke
به طور be towr
به‌طور betowr
به طور کامل be towre kAmel
به عنوان be 'onvAn
به‌عنوان be'onvAn
به دلیل be dalil
از طریق az tariq
از جمله az jomle
از آنجا که az AnjA ke
با توجه به bA tavajjoh be
مثلا masalan
چند بار Cand bAr
هر چند har Cand
هر روز har ruz
هر هفته har hafte
هر ماه har mAh
هر سال har sAl
یک بار yek bAr
دو بار do bAr
سه بار se bAr
چه کسی Ce kasi
چه چیزی Ce Cizi
جی پی اس jipies
پی دی اف pidief
اچ دی eCdi
کیو آر kiyuAr
وی آی پی viAypi
بی ام آی biemAy
تی وی tivi
ویتامین دی vitAmin di
ویتامین سی vitAmin si
ویتامین بی vitAmin bi
ویتامین ای vitAmin i
"""
