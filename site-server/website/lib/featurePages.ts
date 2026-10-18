/**
 * Dedicated pages for the features that carry their own search intent.
 *
 * The `/features` overview answers "what does this product do". These answer
 * "does it do *this* thing, and how" — a different question, from someone
 * already looking for that one capability.
 *
 * Note the image and video studio is one feature in the product but two pages
 * here: "AI poster generator" and "AI video generator" are separate searches
 * with separate expectations, and one page cannot rank honestly for both.
 *
 * Every claim must be something the code does today. Where a capability is
 * planned, it goes in `planned` and is labelled as such on the page — never
 * mixed into the working list.
 */
import type { Locale } from "./i18n";

export type FeaturePage = {
  slug: string;
  icon: string;
  title: string;
  /** One line, used on cards and as the meta description seed. */
  lead: string;
  /** The reader's problem, in their words. */
  problem: string;
  /** What the product does about it. */
  does: string[];
  /** How, concretely — this is where trust is won or lost. */
  how: { title: string; desc: string }[];
  /** A before/after the reader can picture. */
  example: { before: string; after: string };
  /** Why it matters commercially. */
  benefit: string;
  /** Honest about what is not built yet. */
  planned?: string[];
  /** Related pages, by slug. */
  related: string[];
};

const fa: FeaturePage[] = [
  {
    slug: "product-analysis",
    icon: "🧠",
    title: "تحلیل محصول با هوش مصنوعی",
    lead: "از عکس و مشخصات محصول، یک پرونده‌ی بازاریابی کامل.",
    problem:
      "شما محصول را می‌شناسید، ولی نوشتن اینکه «چرا کسی باید این را بخرد» کار دیگری است. بیشتر فروشگاه‌ها مستقیم سراغ تبلیغ می‌روند بدون اینکه بدانند نقطه‌ی فروششان چیست.",
    does: [
      "خلاصه‌ی محصول و مخاطب هدف",
      "نقاط فروش و نقاط ضعف",
      "اعتراض‌هایی که مشتری احتمالاً می‌آورد",
      "زاویه‌های تبلیغاتی و جایگاه‌یابی",
      "لحن پیشنهادی و ایده‌های محتوا",
      "برای هر عکس: چه دیده می‌شود، کیفیت، نور، آماده‌ی اینستاگرام هست یا نه",
    ],
    how: [
      {
        title: "مدل بینایی عکس را می‌خواند",
        desc: "هر عکس محصول جداگانه بررسی می‌شود — جنس، رنگ، کیفیت تصویر، پس‌زمینه و نورپردازی.",
      },
      {
        title: "مدل استدلال استراتژی می‌سازد",
        desc: "از مجموع آنچه در عکس‌ها دیده شده به‌علاوه‌ی مشخصاتی که وارد کرده‌اید.",
      },
      {
        title: "خروجی ساختاریافته است، نه متن آزاد",
        desc: "هر بخش جدا ذخیره می‌شود تا بقیه‌ی سیستم بتواند از آن استفاده کند — کپشن و سناریوی ویدیو روی همین سوار می‌شوند.",
      },
    ],
    example: {
      before: "یک کت کرم، با قیمت و سایزبندی. همین.",
      after:
        "مخاطب هدف، سه زاویه‌ی تبلیغاتی، دو اعتراض محتمل مشتری، و لحنی که به برند شما می‌خورد.",
    },
    benefit:
      "قبل از اینکه یک ریال خرج تبلیغات کنید، می‌دانید چه چیزی را به چه کسی و با چه زاویه‌ای بگویید.",
    related: ["competitor-analysis", "caption-generation"],
  },
  {
    slug: "competitor-analysis",
    icon: "📊",
    title: "تحلیل رقبا از وب واقعی",
    lead: "قیمت و موضع رقبا، با منبع و تاریخ — نه حدس مدل.",
    problem:
      "بیشتر ابزارها از مدل می‌پرسند «رقبای این محصول کی‌اند» و مدل اسم و قیمت از خودش درمی‌آورد. آن داده برای تصمیم‌گیری بی‌ارزش است و بدتر، گمراه‌کننده.",
    does: [
      "کارت هر رقیب: نام، برند، قیمت، کجا و چطور می‌فروشد",
      "مقایسه‌ی مستقیم با محصول شما",
      "پیام‌های مشترک بازار و الگوهای محتوایی",
      "شکاف‌های محتوایی و فرصت‌های تمایز",
      "درجه‌ی اطمینان هر نتیجه‌گیری",
    ],
    how: [
      {
        title: "جستجوی واقعی، نه حافظه‌ی مدل",
        desc: "دیجی‌کالا و ترب برای قیمت، و جستجوی وب برای پیدا کردن سایت رقبا.",
      },
      {
        title: "مشاهده از نتیجه‌گیری جدا می‌ماند",
        desc: "هر عددی که نشان داده می‌شود لینک منبع و زمان دریافت دارد. آنچه برداشت ماست، صریح به‌عنوان برداشت علامت می‌خورد.",
      },
      {
        title: "شما چیزی وارد نمی‌کنید",
        desc: "لازم نیست بدانید رقیبتان کیست — سیستم خودش می‌گردد.",
      },
    ],
    example: {
      before: "«فکر می‌کنم حدود دو میلیون می‌فروشند.»",
      after:
        "چهار رقیب با قیمت واقعی، لینک صفحه‌ی هرکدام، و تاریخ خواندن — به‌علاوه‌ی اینکه شما کجای این طیف ایستاده‌اید.",
    },
    benefit:
      "قیمت‌گذاری و پیام‌تان را روی داده‌ی واقعی می‌بندید، نه روی حدس.",
    related: ["product-analysis", "campaigns-publishing"],
  },
  {
    slug: "ai-image-generation",
    icon: "🎨",
    title: "ساخت پوستر و عکس محصول",
    lead: "از عکس واقعی محصول شما، با متن فارسی درست روی تصویر.",
    problem:
      "دو مشکل همیشگی تولید تصویر با هوش مصنوعی: مدل محصول را عوض می‌کند، و متن فارسی روی تصویر به‌هم می‌ریزد — حروف جدا می‌شوند یا برعکس می‌آیند.",
    does: [
      "پوستر تبلیغاتی با متن فارسی درست",
      "عکس آماده‌ی اینستاگرام از همان محصول",
      "بهبود عکس موجود — نور و پس‌زمینه، بدون دست زدن به محصول",
      "کپشن مخصوص همان تصویر",
    ],
    how: [
      {
        title: "پوستر از عکس واقعی ساخته می‌شود",
        desc: "نه از صفر. مدل صحنه و نور را می‌سازد، روی همان عکسی که آپلود کرده‌اید.",
      },
      {
        title: "متن را کد می‌نشاند، نه مدل",
        desc: "حروف فارسی با کد روی تصویر نوشته می‌شوند — فونت، رنگ و جای دقیق دست خودمان است. به مدل هم صریح گفته می‌شود حق ندارد متن بگذارد.",
      },
      {
        title: "سه حالت با آزادی متفاوت",
        desc: "«بهبود عکس» کمترین تغییر را اجازه می‌دهد؛ «پوستر» بیشترین.",
      },
    ],
    example: {
      before: "عکس آباژور روی میز، با فلاش موبایل.",
      after: "همان آباژور کنار مبل در نور غروب، با عنوان کمپین درست روی تصویر.",
    },
    benefit:
      "محتوای بصری حرفه‌ای بدون عکاس و بدون گرافیست — و مشتری همان چیزی را می‌بیند که می‌خرد.",
    related: ["ai-video-generation", "caption-generation"],
  },
  {
    slug: "ai-video-generation",
    icon: "🎬",
    title: "ساخت ویدیوی تبلیغاتی",
    lead: "ویدیوی پیوسته با صداگذاری — نه چند کلیپ جدا.",
    problem:
      "مدل‌های ویدیو بیشتر از چند ثانیه یک‌جا نمی‌سازند. اگر قطعه‌ها را جدا بسازی و به هم بچسبانی، نتیجه چند ویدیوی بی‌ربط است: شخصیت عوض می‌شود، رنگ می‌پرد، محصول تغییر می‌کند.",
    does: [
      "سناریو و صحنه‌بندی از روی همان محصول",
      "قطعات ۵ ثانیه‌ای که به هم می‌چسبند",
      "صداگذاری فارسی یا انگلیسی، هماهنگ با طول هر صحنه",
      "اتصال نهایی و میکس صدا",
    ],
    how: [
      {
        title: "فریم آخر، ورودی قطعه‌ی بعدی",
        desc: "هر قطعه از جایی شروع می‌شود که قطعه‌ی قبلی تمام شده — مثل ادامه دادن یک فیلم، نه شروع دوباره.",
      },
      {
        title: "صدا با طول واقعی صحنه جور می‌شود",
        desc: "نریشن وسط جمله قطع نمی‌شود؛ صحنه‌های بی‌حرف سکوت می‌گیرند نه صدای الکی.",
      },
      {
        title: "خطای یک قطعه کل کار را دور نمی‌ریزد",
        desc: "اگر قطعه‌ای شکست بخورد فقط همان دوباره ساخته می‌شود و سهمیه‌اش برمی‌گردد.",
      },
    ],
    example: {
      before: "یک عکس ثابت از محصول.",
      after: "ده ثانیه ویدیوی پیوسته با حرکت آرام دوربین و نریشن فارسی.",
    },
    benefit:
      "ویدیو گران‌ترین قالب محتواست — این کار را از هفته‌ها به یک صف رندر تبدیل می‌کند.",
    planned: [
      "کنترل کیفیت خودکار هر قطعه با بینایی ماشین",
      "تعمیر خودکار نقص‌های کوچک با کد، پیش از رندر دوباره",
      "نمایش قطعه‌به‌قطعه و تأیید در حین ساخت",
    ],
    related: ["ai-image-generation", "caption-generation"],
  },
  {
    slug: "caption-generation",
    icon: "✍️",
    title: "تولید کپشن و متن فروش",
    lead: "متنی که برای فروش نوشته شده، وصل به همان تصویری که درباره‌اش است.",
    problem:
      "کپشن عمومی که به هیچ عکسی وصل نیست، جای خالی را پر می‌کند ولی نمی‌فروشد. و لحن اینستاگرام با لینکدین یکی نیست.",
    does: [
      "اینستاگرام، تلگرام و لینکدین — هرکدام با لحن خودش",
      "سه طول: کوتاه، متوسط، بلند",
      "هشتگ و فراخوان به اقدام",
      "وصل به تصویر یا ویدیوی مشخص",
    ],
    how: [
      {
        title: "کپشن به محتوا وصل است",
        desc: "موقع ساخت، مشخص می‌کنید درباره‌ی کدام تصویر یا ویدیو است — پس متن به همان اشاره می‌کند، نه به محصول به‌طور کلی.",
      },
      {
        title: "لحن برند شما",
        desc: "از پروفایل برندی که یک‌بار ثبت کرده‌اید خوانده می‌شود.",
      },
      {
        title: "سه طول، چون جای‌ها فرق دارند",
        desc: "کپشن استوری با کپشن پست یکی نیست؛ هر سه ساخته می‌شود تا انتخاب کنید.",
      },
    ],
    example: {
      before: "«کت اورسایز کرم، سایز ۳۶ تا ۴۴، ارسال رایگان.»",
      after:
        "سه نسخه با لحن برند شما، هرکدام با هشتگ و دعوت به اقدام مناسب همان پلتفرم.",
    },
    benefit: "نوشتن متن از گلوگاه روزانه به یک کلیک تبدیل می‌شود.",
    related: ["ai-image-generation", "product-analysis"],
  },
  {
    slug: "sales-assistant",
    icon: "🤝",
    title: "پشتیبان فروش هوش مصنوعی",
    lead: "جواب می‌دهد، پیشنهاد می‌دهد و سفارش ثبت می‌کند — بدون ساختن عدد.",
    problem:
      "مشتری که جواب نگیرد می‌رود. ولی جواب دادن یعنی کسی باید تمام روز آنلاین باشد و قیمت و موجودی همه‌ی محصولات را بداند.",
    does: [
      "تشخیص قصد پیام و پاسخ بر پایه‌ی کاتالوگ شما",
      "مدیریت اعتراض و پیشنهاد محصول جایگزین",
      "ثبت سفارش و دریافت رسید پرداخت",
      "ارجاع موارد حساس به شما",
      "ساخت تیکت پشتیبانی برای شکایت",
    ],
    how: [
      {
        title: "قیمت و موجودی از دیتابیس، نه از مدل",
        desc: "مدل جمله می‌سازد، عدد نمی‌سازد. اگر موجودی صفر است نمی‌تواند بگوید «داریم».",
      },
      {
        title: "تأیید پرداخت همیشه با انسان",
        desc: "مشتری رسید می‌فرستد، سفارش «در انتظار تأیید» می‌شود و شما تصمیم می‌گیرید. این قابل تغییر نیست.",
      },
      {
        title: "بلد است کجا عقب بکشد",
        desc: "وقتی از پسش برنمی‌آید یا موضوع حساس است، به پنل شما اعلان می‌دهد.",
      },
    ],
    example: {
      before: "دایرکت ساعت ۲ بامداد: «این سایز ۴۰ موجوده؟»",
      after:
        "جواب فوری از روی موجودی واقعی، پیشنهاد سایز نزدیک اگر نبود، و ثبت سفارش اگر بود.",
    },
    benefit: "فروشی که به‌خاطر دیر جواب دادن از دست می‌رفت، از دست نمی‌رود.",
    planned: [
      "تنظیم لحن و قوانین فروش برای هر فروشگاه",
      "صندوق واحد برای دایرکت، واتساپ، تلگرام و پیامک",
    ],
    related: ["product-analysis", "campaigns-publishing"],
  },
  {
    slug: "campaigns-publishing",
    icon: "🚀",
    title: "کمپین و انتشار خودکار",
    lead: "از تولید تا انتشار، با تأیید انسانی در وسط.",
    problem:
      "محتوا ساختن نصف کار است. نصف دیگر این است که کجا، کی و با چه ترتیبی منتشر شود — و اینکه چیزی بدون اجازه بیرون نرود.",
    does: [
      "گروه‌بندی پوستر، ویدیو و کپشن در یک کمپین",
      "چرخه‌ی تأیید: پیش‌نویس ← تأیید ← انتشار",
      "انتشار مستقیم در اینستاگرام",
      "گزارش وضعیت تحویل هر پلتفرم",
    ],
    how: [
      {
        title: "کمپین محتوای هم‌محصول را جمع می‌کند",
        desc: "سیستم بررسی می‌کند همه‌ی اقلام یک کمپین به یک محصول مربوط باشند.",
      },
      {
        title: "انتشار فقط بعد از تأیید",
        desc: "هیچ مسیری وجود ندارد که محتوا بدون تأیید شما منتشر شود.",
      },
      {
        title: "وضعیت هر پلتفرم جدا ثبت می‌شود",
        desc: "اگر یکی شکست بخورد، بقیه دوباره پست نمی‌شوند.",
      },
    ],
    example: {
      before: "پوستر در یک پوشه، کپشن در یادداشت‌ها، ویدیو در گالری.",
      after: "یک کمپین با همه‌ی اقلام، یک دکمه‌ی تأیید، و انتشار خودکار.",
    },
    benefit: "کنترل کامل روی چیزی که بیرون می‌رود، بدون کار دستی.",
    related: ["caption-generation", "sales-assistant"],
  },
];

const en: FeaturePage[] = [
  {
    slug: "product-analysis",
    icon: "🧠",
    title: "AI product analysis",
    lead: "A full marketing brief, from a photo and a spec sheet.",
    problem:
      "You know your product, but writing down why anyone should buy it is a different job. Most shops go straight to advertising without knowing what their selling point actually is.",
    does: [
      "Product summary and target audience",
      "Selling points and weak spots",
      "Objections a buyer is likely to raise",
      "Advertising angles and positioning",
      "Suggested tone and content ideas",
      "Per photo: what is visible, its quality, the lighting, whether it is social-ready",
    ],
    how: [
      {
        title: "A vision model reads the photos",
        desc: "Each product photo is examined on its own — material, colour, image quality, background and lighting.",
      },
      {
        title: "A reasoning model builds the strategy",
        desc: "From everything seen across the photos, plus the specifications you entered.",
      },
      {
        title: "The output is structured, not prose",
        desc: "Each part is stored separately so the rest of the system can use it — captions and video scripts are built on top of this.",
      },
    ],
    example: {
      before: "A cream coat, with a price and a size range. That is all.",
      after:
        "Target audience, three advertising angles, two likely objections, and a tone that fits your brand.",
    },
    benefit:
      "Before you spend anything on ads, you know what to say, to whom, and from which angle.",
    related: ["competitor-analysis", "caption-generation"],
  },
  {
    slug: "competitor-analysis",
    icon: "📊",
    title: "Competitor analysis from the real web",
    lead: "Competitor prices and positioning, with a source and a date — not a guess.",
    problem:
      "Most tools ask a model who the competitors are, and the model invents names and prices. That data is worthless for a decision, and worse, misleading.",
    does: [
      "A card per competitor: name, brand, price, where and how they sell",
      "A direct comparison against your product",
      "Shared market messaging and content patterns",
      "Content gaps and room to differentiate",
      "A confidence level on each conclusion",
    ],
    how: [
      {
        title: "A real search, not the model's memory",
        desc: "Digikala and Torob for prices, and web search to find competitor sites.",
      },
      {
        title: "Observation stays separate from conclusion",
        desc: "Every figure shown carries its source link and the time it was read. What is our interpretation is labelled as interpretation.",
      },
      {
        title: "You enter nothing",
        desc: "You do not need to know who your competitors are — the system goes looking.",
      },
    ],
    example: {
      before: "“I think they sell at around two million.”",
      after:
        "Four competitors with real prices, a link to each page and the date it was read — plus where you sit on that spread.",
    },
    benefit: "You set your price and your message on real data, not on a hunch.",
    related: ["product-analysis", "campaigns-publishing"],
  },
  {
    slug: "ai-image-generation",
    icon: "🎨",
    title: "Poster and product image generation",
    lead: "Built on your real product photo, with the text placed correctly.",
    problem:
      "Two things always go wrong with AI image generation: the model changes the product, and text on the image breaks apart — letters separated or reversed.",
    does: [
      "Advertising posters with correctly rendered text",
      "Social-ready shots of the same product",
      "Clean-up of an existing photo — light and background, product untouched",
      "A caption written for that specific image",
    ],
    how: [
      {
        title: "The poster is built on the real photo",
        desc: "Not from nothing. The model builds the scene and the lighting on top of the photo you uploaded.",
      },
      {
        title: "Code places the text, not the model",
        desc: "Letters are rendered in code — font, colour and exact position are ours to control. The model is explicitly told it may not add text.",
      },
      {
        title: "Three modes with different freedom",
        desc: "“Clean-up” allows the least change; “poster” allows the most.",
      },
    ],
    example: {
      before: "A lamp on a table, shot with a phone flash.",
      after: "The same lamp beside a sofa in evening light, with the campaign headline on the image.",
    },
    benefit:
      "Professional visuals without a photographer or a designer — and the buyer sees what they are buying.",
    related: ["ai-video-generation", "caption-generation"],
  },
  {
    slug: "ai-video-generation",
    icon: "🎬",
    title: "Promotional video generation",
    lead: "One continuous video with narration — not a pile of clips.",
    problem:
      "Video models cannot produce more than a few seconds at a time. Generate the pieces separately and stitch them, and you get several unrelated videos: the character changes, colours shift, the product transforms.",
    does: [
      "A script and scene breakdown from your product",
      "Five-second segments that actually join",
      "Persian or English narration, fitted to each scene",
      "Final assembly and audio mix",
    ],
    how: [
      {
        title: "The last frame feeds the next segment",
        desc: "Each segment starts where the previous one ended — like continuing a film, not restarting it.",
      },
      {
        title: "Audio is fitted to the real scene length",
        desc: "Narration is never cut mid-sentence; wordless scenes get silence rather than filler.",
      },
      {
        title: "One failure does not throw away the job",
        desc: "If a segment fails, only that segment is rebuilt and its quota comes back.",
      },
    ],
    example: {
      before: "One still photo of the product.",
      after: "Ten seconds of continuous video with a slow camera move and narration.",
    },
    benefit:
      "Video is the most expensive format there is — this turns it from weeks into a render queue.",
    planned: [
      "Automatic per-segment quality control with machine vision",
      "Repairing small defects in code before paying for another render",
      "Segment-by-segment preview and approval while it builds",
    ],
    related: ["ai-image-generation", "caption-generation"],
  },
  {
    slug: "caption-generation",
    icon: "✍️",
    title: "Caption and sales copy generation",
    lead: "Copy written to sell, tied to the exact image it describes.",
    problem:
      "A generic caption attached to nothing fills the box but does not sell. And the register that works on Instagram is not the one that works on LinkedIn.",
    does: [
      "Instagram, Telegram and LinkedIn — each in its own register",
      "Three lengths: short, medium, long",
      "Hashtags and a call to action",
      "Tied to a specific image or video",
    ],
    how: [
      {
        title: "The caption is attached to the content",
        desc: "You say which image or video it is about, so the copy refers to that — not to the product in the abstract.",
      },
      {
        title: "In your brand's voice",
        desc: "Read from the brand profile you set up once.",
      },
      {
        title: "Three lengths, because placements differ",
        desc: "A story caption is not a post caption; all three are produced so you can pick.",
      },
    ],
    example: {
      before: "“Cream oversized coat, sizes 36 to 44, free shipping.”",
      after:
        "Three versions in your brand voice, each with hashtags and a call to action suited to that platform.",
    },
    benefit: "Writing copy goes from a daily bottleneck to one click.",
    related: ["ai-image-generation", "product-analysis"],
  },
  {
    slug: "sales-assistant",
    icon: "🤝",
    title: "AI sales assistant",
    lead: "Answers, recommends and records orders — without inventing a number.",
    problem:
      "A customer who gets no answer leaves. But answering means someone online all day who knows the price and stock of every product.",
    does: [
      "Reads the intent of a message and answers from your catalogue",
      "Handles objections and suggests alternatives",
      "Records the order and collects the payment receipt",
      "Escalates anything sensitive to you",
      "Opens a support ticket for complaints",
    ],
    how: [
      {
        title: "Price and stock from the database, not the model",
        desc: "The model writes sentences, not numbers. If stock is zero it cannot say “we have it”.",
      },
      {
        title: "Payment confirmation is always human",
        desc: "The customer sends a receipt, the order becomes “awaiting approval”, and you decide. That cannot be changed.",
      },
      {
        title: "It knows when to step back",
        desc: "When it cannot handle something, or the matter is sensitive, it notifies your panel.",
      },
    ],
    example: {
      before: "A message at 2am: “do you have this in a 40?”",
      after:
        "An immediate answer from real stock, a nearby size suggested if not, and the order recorded if so.",
    },
    benefit: "The sale you used to lose by answering late, you no longer lose.",
    planned: [
      "Per-shop tone and sales rules",
      "A single inbox for Instagram, WhatsApp, Telegram and SMS",
    ],
    related: ["product-analysis", "campaigns-publishing"],
  },
  {
    slug: "campaigns-publishing",
    icon: "🚀",
    title: "Campaigns and automatic publishing",
    lead: "From generation to publication, with human approval in the middle.",
    problem:
      "Making the content is half the job. The other half is where, when and in what order it goes out — and making sure nothing leaves without permission.",
    does: [
      "Group poster, video and caption into one campaign",
      "An approval cycle: draft to approved to published",
      "Publish straight to Instagram",
      "Per-platform delivery status",
    ],
    how: [
      {
        title: "A campaign groups content for one product",
        desc: "The system checks that every item in a campaign belongs to the same product.",
      },
      {
        title: "Publishing happens only after approval",
        desc: "There is no path by which content goes out without you approving it.",
      },
      {
        title: "Each platform's status is tracked separately",
        desc: "If one fails, the others are not posted again.",
      },
    ],
    example: {
      before: "The poster in a folder, the caption in notes, the video in the gallery.",
      after: "One campaign with everything in it, one approve button, and automatic publishing.",
    },
    benefit: "Full control over what goes out, without the manual work.",
    related: ["caption-generation", "sales-assistant"],
  },
];

const PAGES: Record<Locale, FeaturePage[]> = { fa, en };

export function featurePagesFor(locale: Locale): FeaturePage[] {
  return PAGES[locale];
}

export function getFeaturePage(slug: string, locale: Locale): FeaturePage | undefined {
  return PAGES[locale].find((f) => f.slug === slug);
}

/** Slugs are shared across locales, so static params only need one pass. */
export const featureSlugs = fa.map((f) => f.slug);
