/**
 * Marketing copy, in both languages.
 *
 * Everything the site *claims* lives here; everything it *prices* comes from
 * the live API (lib/plans.ts). That split matters: a price shown on the site
 * and a price enforced by the backend must never be two separate edits.
 *
 * The English is written, not translated. Where a Persian line only works as
 * Persian, the English says the same thing the way an English speaker would.
 *
 * Both halves are required by the types, so a half-finished translation fails
 * the build instead of quietly shipping a page in the wrong language.
 */
import type { Locale, Localized } from "./i18n";

const PANEL_URL = process.env.NEXT_PUBLIC_PANEL_URL || "http://127.0.0.1:5173";

type Site = {
  name: string;
  nameEn: string;
  tagline: string;
  oneLiner: string;
  panelUrl: string;
  email: string;
  instagram: string;
  keywords: string[];
};

const site: Localized<Site> = {
  fa: {
    name: "NMarketing",
    nameEn: "NMarketing",
    tagline: "کارمند فروش و مارکتینگ هوش مصنوعی برای فروشگاه‌های آنلاین",
    oneLiner:
      "اطلاعات محصولت را بده — پوستر، ویدیو، کپشن و پشتیبانی فروشش را تحویل بگیر.",
    panelUrl: PANEL_URL,
    email: "hello@upmarket.ir",
    instagram: "https://instagram.com/upmarket.ir",
    keywords: [
      "بازاریابی هوش مصنوعی",
      "تولید محتوا با هوش مصنوعی",
      "پوستر تبلیغاتی",
      "ویدیو تبلیغاتی",
      "کپشن اینستاگرام",
      "فروشگاه آنلاین",
      "تحلیل رقبا",
      "SaaS ایرانی",
      "دستیار فروش",
    ],
  },
  en: {
    name: "NMarketing",
    nameEn: "NMarketing",
    tagline: "An AI sales and marketing employee for online shops",
    oneLiner:
      "Add your product — get the poster, the video, the caption and the sales replies.",
    panelUrl: PANEL_URL,
    email: "hello@upmarket.ir",
    instagram: "https://instagram.com/upmarket.ir",
    keywords: [
      "AI marketing",
      "AI content generation",
      "ad poster generator",
      "promotional video AI",
      "Instagram captions",
      "online shop marketing",
      "competitor analysis",
      "AI sales assistant",
    ],
  },
};

export function siteFor(locale: Locale): Site {
  return site[locale];
}

/** Kept for modules that genuinely have no locale in hand (build scripts). */
export const siteBase = site.fa;

// --------------------------------------------------------------------------
// Pages a sitemap must list, regardless of what the header happens to show.
// Keeping this separate from navigation stops a nav tweak from silently
// dropping pages out of Google.
// --------------------------------------------------------------------------
export const sitemapPages = [
  "/features",
  "/solutions",
  "/use-cases",
  "/how-it-works",
  "/showcase",
  "/pricing",
  "/blog",
  "/about",
  "/faq",
  "/contact",
  "/tools",
  "/compare",
];

export const TEAM_COST = 40_000_000;

// --------------------------------------------------------------------------

type Role = { icon: string; role: string; task: string };
type Step = { n: string; icon: string; title: string; desc: string; detail: string };
type Feature = { id: string; icon: string; title: string; lead: string; bullets: string[] };
type IconCard = { icon: string; title: string; desc: string };
type Faq = { q: string; a: string };
type Capability = { value: string; label: string; hint: string };
type Audience = { icon: string; label: string; proven?: boolean };
type Objection = { icon: string; q: string; a: string };

type Content = {
  roles: Role[];
  steps: Step[];
  features: Feature[];
  trust: IconCard[];
  faq: Faq[];
  about: {
    mission: string;
    story: { title: string; text: string }[];
    values: IconCard[];
  };
  capabilities: Capability[];
  audiences: Audience[];
  alternatives: { left: { title: string; items: string[] }; right: { title: string; items: string[] } };
  objections: Objection[];
};

const fa: Content = {
  roles: [
    { icon: "🎨", role: "گرافیست", task: "طراحی پست و پوستر" },
    { icon: "🎬", role: "تدوینگر", task: "تولید ویدیو" },
    { icon: "✍️", role: "کپی‌رایتر", task: "متن تبلیغاتی" },
    { icon: "📱", role: "ادمین", task: "پاسخ به مشتری" },
    { icon: "🧠", role: "استراتژیست", task: "استراتژی محتوا" },
    { icon: "💰", role: "هزینه‌بر", task: "استخدام و مدیریت" },
  ],

  steps: [
    {
      n: "۱",
      icon: "🏪",
      title: "فروشگاه و محصول را ثبت کنید",
      desc: "نام برند، لحن، سیاست‌های ارسال و مرجوعی، و محصولات با عکس واقعی.",
      detail:
        "همین اطلاعات بعداً پایه‌ی هر جمله‌ای است که سیستم به مشتری شما می‌گوید.",
    },
    {
      n: "۲",
      icon: "📊",
      title: "تحلیل محصول و رقبا",
      desc: "عکس محصول خوانده می‌شود و قیمت رقبا از وب درمی‌آید.",
      detail:
        "دیجی‌کالا، ترب و جستجوی وب — منبع و زمان هر داده ذخیره می‌شود تا قابل بازبینی باشد.",
    },
    {
      n: "۳",
      icon: "🎨",
      title: "پوستر و تصاویر",
      desc: "از عکس واقعی محصول شما، با متن فارسی روی تصویر.",
      detail: "سه حالت: پوستر تبلیغاتی، عکس اینستاگرامی، و بهبود عکس موجود.",
    },
    {
      n: "۴",
      icon: "🎬",
      title: "ویدیوی تبلیغاتی",
      desc: "سناریو، صحنه‌بندی، و ویدیوی پیوسته با صداگذاری فارسی.",
      detail:
        "قطعات ۵ ثانیه‌ای که از فریم آخر یکدیگر ادامه پیدا می‌کنند — نه چند کلیپ جدا.",
    },
    {
      n: "۵",
      icon: "✍️",
      title: "کپشن و متن فروش",
      desc: "برای اینستاگرام، تلگرام و لینکدین — هرکدام با لحن خودش.",
      detail:
        "سه طول مختلف، هشتگ و فراخوان به اقدام، وصل به همان محتوایی که درباره‌اش است.",
    },
    {
      n: "۶",
      icon: "🚀",
      title: "تأیید و انتشار",
      desc: "هرچه پسندیدید مستقیم در اینستاگرام منتشر می‌شود.",
      detail: "هیچ چیز بدون تأیید شما منتشر نمی‌شود.",
    },
  ],

  features: [
    {
      id: "intelligence",
      icon: "🧠",
      title: "هوش محصول",
      lead: "از عکس و مشخصات، یک پرونده‌ی بازاریابی کامل می‌سازد.",
      bullets: [
        "خلاصه محصول و مخاطب هدف",
        "نقاط فروش و نقاط ضعف",
        "اعتراض‌هایی که مشتری احتمالاً می‌آورد",
        "زاویه‌های تبلیغاتی و جایگاه‌یابی",
        "لحن پیشنهادی و ایده‌های محتوا",
      ],
    },
    {
      id: "market",
      icon: "📊",
      title: "تحلیل بازار و رقبا",
      lead: "خودش از وب درمی‌آورد؛ شما چیزی وارد نمی‌کنید.",
      bullets: [
        "کارت هر رقیب: قیمت، کجا و چطور می‌فروشد، قوت و ضعف",
        "مقایسه‌ی مستقیم با محصول شما",
        "پیام‌های مشترک بازار و الگوهای محتوایی",
        "شکاف‌های محتوایی و فرصت‌های تمایز",
        "تفکیک «مشاهده» از «نتیجه‌گیری» — هیچ داده‌ای ساخته نمی‌شود",
      ],
    },
    {
      id: "studio",
      icon: "🎨",
      title: "استودیوی تصویر و ویدیو",
      lead: "خروجی آماده‌ی انتشار، از عکس واقعی محصول شما.",
      bullets: [
        "پوستر تبلیغاتی با متن فارسی",
        "عکس اینستاگرامی و بهبود عکس موجود",
        "ویدیوی پیوسته با صداگذاری فارسی یا انگلیسی",
        "اگر قطعه‌ای خراب شد فقط همان دوباره ساخته می‌شود",
      ],
    },
    {
      id: "captions",
      icon: "✍️",
      title: "موتور کپشن",
      lead: "متنی که برای فروش نوشته شده، نه برای پر کردن جای خالی.",
      bullets: [
        "اینستاگرام، تلگرام و لینکدین",
        "سه طول: کوتاه، متوسط، بلند",
        "هشتگ و فراخوان به اقدام",
        "وصل به همان تصویر یا ویدیویی که درباره‌اش است",
      ],
    },
    {
      id: "agent",
      icon: "🤝",
      title: "پشتیبان فروش ۲۴ ساعته",
      lead: "به مشتری پاسخ می‌دهد، پیشنهاد می‌دهد و سفارش ثبت می‌کند.",
      bullets: [
        "قیمت و موجودی فقط از روی اطلاعات خودتان",
        "مدیریت اعتراض و پیشنهاد محصول جایگزین",
        "ثبت سفارش و دریافت رسید پرداخت",
        "تأیید پرداخت همیشه با شماست، نه با هوش مصنوعی",
        "مسائل حساس به شما ارجاع داده می‌شود",
      ],
    },
    {
      id: "campaigns",
      icon: "🚀",
      title: "کمپین و انتشار",
      lead: "از تولید تا انتشار، در یک جریان.",
      bullets: [
        "گروه‌بندی پوستر، ویدیو و کپشن در یک کمپین",
        "تأیید انسانی قبل از هر انتشار",
        "انتشار مستقیم در اینستاگرام",
        "گزارش وضعیت تحویل هر پلتفرم",
      ],
    },
  ],

  trust: [
    {
      icon: "🎁",
      title: "دو هفته رایگان",
      desc: "قبل از هر پرداختی، خروجی واقعی برای محصولات خودتان می‌گیرید.",
    },
    {
      icon: "🛡️",
      title: "بدون ریسک",
      desc: "اگر در دو هفته نتیجه نگرفتید، هیچ هزینه‌ای نمی‌پردازید.",
    },
    {
      // Was "داده‌ی شما پیش ما می‌ماند — نه سرویس خارجی". The code says
      // otherwise: narration goes to Microsoft's TTS and competitor research
      // reads Digikala/Torob. Claiming a blanket "nothing leaves" would be a
      // promise the product cannot keep.
      icon: "🔒",
      title: "پردازش روی سرور خودمان",
      desc: "تولید تصویر و ویدیو روی سخت‌افزار خودمان است. دو مورد بیرون می‌رود و شفاف می‌گوییم: صداگذاری، و جستجوی قیمت رقبا.",
    },
    {
      icon: "👤",
      title: "تأیید نهایی با شماست",
      desc: "هیچ محتوایی بدون تأیید شما منتشر نمی‌شود.",
    },
  ],

  faq: [
    {
      q: "باید بلد باشم با هوش مصنوعی کار کنم؟",
      a: "نه. اطلاعات محصول و عکسش را وارد می‌کنید؛ بقیه‌اش خودکار است. پرامپت‌نویسی لازم نیست.",
    },
    {
      q: "عکس محصول خودم استفاده می‌شود یا تصویر ساختگی؟",
      a: "عکس واقعی خودتان. پوستر از روی همان عکس ساخته می‌شود تا مشتری دقیقاً همان چیزی را ببیند که می‌خرد.",
    },
    {
      q: "قیمت و موجودی را چطور به مشتری می‌گوید؟",
      a: "فقط از روی اطلاعاتی که خودتان ثبت کرده‌اید. سیستم عدد نمی‌سازد و اگر چیزی را نداند می‌گوید نمی‌داند.",
    },
    {
      q: "محتوا به چه زبانی است؟",
      a: "فارسی، با لحن برند خودتان. نریشن ویدیو هم فارسی یا انگلیسی، به انتخاب شما.",
    },
    {
      // The old answer said "a full content pack in a few minutes". Our own
      // render figures put a pro-package video at hours of GPU time, so that
      // was a promise we would break on the first order.
      q: "چقدر طول می‌کشد؟",
      a: "کپشن و متن در چند دقیقه آماده است. پوستر و ویدیو رندر می‌خواهند و در صف قرار می‌گیرند — پیشرفتشان را زنده می‌بینید. در هر حال روزها و هفته‌های یک تیم انسانی نیست.",
    },
    {
      q: "اگر خروجی را نپسندم؟",
      a: "دوباره تولید می‌کنید. تا وقتی تأیید نکنید چیزی منتشر نمی‌شود.",
    },
    {
      q: "سهمیه‌ی ماهانه یعنی چه؟",
      a: "هر پلن مقدار مشخصی ثانیه ویدیو، تصویر و کپشن در ماه دارد. مصرف را در پنل زنده می‌بینید و اگر رندری خطا بدهد سهمیه‌اش برمی‌گردد.",
    },
    {
      q: "پرداخت چطور است؟",
      a: "ماهانه. دوره‌ی آزمایشی دو هفته‌ای بدون کارت بانکی شروع می‌شود و خودکار تمدید نمی‌شود.",
    },
    {
      q: "به اینستاگرام من وصل می‌شود؟",
      a: "بله. با اتصال حساب، محتوای تأییدشده مستقیم منتشر می‌شود. اگر ترجیح بدهید می‌توانید خودتان دستی منتشر کنید.",
    },
    {
      q: "اطلاعات فروشگاه من امن است؟",
      a: "هر فروشگاه کاملاً جدا است و فقط صاحبش به داده‌هایش دسترسی دارد. تولید تصویر و ویدیو روی سرور خودمان انجام می‌شود؛ صداگذاری و جستجوی قیمت رقبا به سرویس بیرونی وصل می‌شوند و این را در سیاست حریم خصوصی نوشته‌ایم.",
    },
  ],

  about: {
    mission:
      "بازاریابی حرفه‌ای نباید امتیاز کسب‌وکارهای بزرگ باشد. NMarketing همان کاری را " +
      "که یک تیم پنج‌نفره‌ی بازاریابی انجام می‌دهد، برای یک فروشگاه کوچک و با " +
      "کسری از هزینه انجام می‌دهد.",
    story: [
      {
        title: "مشکل را از نزدیک دیدیم",
        text:
          "کسب‌وکارهای کوچک محصول خوب دارند اما نمی‌توانند خوب نشانش دهند. " +
          "استخدام تیم گران است و آژانس‌ها شفاف نیستند.",
      },
      {
        title: "به‌جای ابزار، جریان ساختیم",
        text:
          "ابزارهای موجود هرکدام یک تکه را حل می‌کنند و کاربر باید خودش وصل‌شان کند. " +
          "ما کل مسیر از ثبت محصول تا انتشار را یکجا ساختیم.",
      },
      {
        title: "روی سخت‌افزار خودمان",
        text:
          "تولید تصویر و ویدیو روی کارت‌های گرافیک خودمان انجام می‌شود — یعنی " +
          "قیمت به نرخ ارز گره نخورده و ظرفیت دست خودمان است.",
      },
    ],
    values: [
      { icon: "🎯", title: "هدف فروش است", desc: "نه تولید محتوای زیبا، که فروش بیشتر." },
      { icon: "🔍", title: "شفافیت عددی", desc: "قیمت و موجودی هرگز ساخته نمی‌شود." },
      { icon: "👤", title: "انسان تصمیم می‌گیرد", desc: "تأیید انتشار و پرداخت همیشه با شماست." },
      { icon: "🇮🇷", title: "ساخته‌شده برای ایران", desc: "زبان، فرهنگ و بازار محلی." },
    ],
  },

  capabilities: [
    { value: "۴", label: "نوع خروجی", hint: "پوستر · ویدیو · کپشن · پاسخ فروش" },
    { value: "۳", label: "پلتفرم کپشن", hint: "اینستاگرام · تلگرام · لینکدین" },
    { value: "۱۰", label: "خروجی تحلیل محصول", hint: "از مخاطب هدف تا لحن پیشنهادی" },
    { value: "۱۱", label: "خروجی تحلیل رقبا", hint: "با منبع و تاریخ هر داده" },
  ],

  audiences: [
    { icon: "👕", label: "پوشاک", proven: true },
    { icon: "💎", label: "اکسسوری و زیورآلات", proven: true },
    { icon: "🛋️", label: "دکوراسیون و هوم‌دکور", proven: true },
    { icon: "🧴", label: "آرایشی و بهداشتی" },
    { icon: "🍯", label: "مواد غذایی و صنایع‌دستی" },
    { icon: "👟", label: "کفش و کیف" },
    { icon: "📱", label: "لوازم جانبی دیجیتال" },
    { icon: "🌿", label: "گیاه و باغبانی" },
  ],

  alternatives: {
    left: {
      title: "بدون NMarketing",
      items: [
        "یا تیم پنج‌نفره استخدام می‌کنید",
        "یا به آژانس با هزینه‌ی نامشخص می‌سپارید",
        "یا خودتان شب‌ها محتوا می‌سازید",
        "یا — که رایج‌ترین است — هیچ‌کدام",
        "خروجی نامنظم و بی‌کیفیت",
        "دایرکت‌ها بی‌جواب می‌مانند",
      ],
    },
    right: {
      title: "با NMarketing",
      items: [
        "یک‌بار محصول را ثبت می‌کنید",
        "بسته‌ی محتوا در چند دقیقه آماده است",
        "هزینه از پیش مشخص و ثابت",
        "تأیید نهایی همیشه با شماست",
        "خروجی یکدست، ماه به ماه",
        "پاسخ به مشتری ۲۴ ساعته",
      ],
    },
  },

  objections: [
    {
      icon: "🤖",
      q: "نکند خروجی مصنوعی به نظر برسد؟",
      a: "پوستر از عکس واقعی خودتان ساخته می‌شود، نه از صفر. متن فارسی هم با کد روی تصویر می‌نشیند تا حروف به‌هم نریزد.",
    },
    {
      icon: "🎛️",
      q: "کنترل از دستم خارج می‌شود؟",
      a: "هیچ چیزی بدون تأیید شما منتشر نمی‌شود. هر خروجی را می‌توانید دوباره بسازید تا راضی شوید.",
    },
    {
      icon: "💸",
      q: "بعداً هزینه‌ی پنهان دارد؟",
      a: "سهمیه‌ی هر پلن از قبل مشخص است و مصرفتان را زنده می‌بینید. اگر رندری خطا بدهد، سهمیه‌اش برمی‌گردد.",
    },
    {
      icon: "🔌",
      q: "اگر خواستم قطع کنم چه؟",
      a: "دوره‌ی آزمایشی خودکار تمدید نمی‌شود و محتوایی که ساخته‌اید مال خودتان است.",
    },
  ],
};

const en: Content = {
  roles: [
    { icon: "🎨", role: "Designer", task: "Posts and posters" },
    { icon: "🎬", role: "Video editor", task: "Promo videos" },
    { icon: "✍️", role: "Copywriter", task: "Ad copy" },
    { icon: "📱", role: "Community manager", task: "Replying to customers" },
    { icon: "🧠", role: "Strategist", task: "Content strategy" },
    { icon: "💰", role: "Overhead", task: "Hiring and managing them" },
  ],

  steps: [
    {
      n: "1",
      icon: "🏪",
      title: "Add your shop and products",
      desc: "Brand name, tone of voice, shipping and returns policy, and products with real photos.",
      detail:
        "Everything the system later says to your customers is built on exactly this.",
    },
    {
      n: "2",
      icon: "📊",
      title: "Product and competitor analysis",
      desc: "Your product photos get read, and competitor prices come off the open web.",
      detail:
        "Digikala, Torob and web search — the source and timestamp of every figure is stored so you can check it.",
    },
    {
      n: "3",
      icon: "🎨",
      title: "Posters and images",
      desc: "Built on your real product photo, with the text laid over it.",
      detail: "Three modes: ad poster, social-ready shot, and cleaning up a photo you already have.",
    },
    {
      n: "4",
      icon: "🎬",
      title: "Promotional video",
      desc: "Script, scene breakdown, and one continuous video with narration.",
      detail:
        "Five-second segments that each start from the last frame of the one before — one video, not a pile of clips.",
    },
    {
      n: "5",
      icon: "✍️",
      title: "Captions and sales copy",
      desc: "For Instagram, Telegram and LinkedIn — each in its own register.",
      detail:
        "Three lengths, hashtags and a call to action, tied to the exact image or video it describes.",
    },
    {
      n: "6",
      icon: "🚀",
      title: "Approve and publish",
      desc: "Whatever you approve goes straight to Instagram.",
      detail: "Nothing is ever published without your approval.",
    },
  ],

  features: [
    {
      id: "intelligence",
      icon: "🧠",
      title: "Product intelligence",
      lead: "Turns a photo and a spec sheet into a marketing brief.",
      bullets: [
        "Product summary and target audience",
        "Selling points and weak spots",
        "Objections a buyer is likely to raise",
        "Advertising angles and positioning",
        "Suggested tone and content ideas",
      ],
    },
    {
      id: "market",
      icon: "📊",
      title: "Market and competitor analysis",
      lead: "It goes and looks. You enter nothing.",
      bullets: [
        "A card per competitor: price, where and how they sell, strengths, weaknesses",
        "Direct comparison against your product",
        "Shared market messaging and content patterns",
        "Content gaps and room to differentiate",
        "Observation kept separate from conclusion — no figure is invented",
      ],
    },
    {
      id: "studio",
      icon: "🎨",
      title: "Image and video studio",
      lead: "Publish-ready output, built on your real product photo.",
      bullets: [
        "Ad posters with text rendered in code, not by the model",
        "Social-ready shots, and clean-up of existing photos",
        "Continuous video with Persian or English narration",
        "If one segment fails, only that segment is rebuilt",
      ],
    },
    {
      id: "captions",
      icon: "✍️",
      title: "Caption engine",
      lead: "Copy written to sell, not to fill the box.",
      bullets: [
        "Instagram, Telegram and LinkedIn",
        "Three lengths: short, medium, long",
        "Hashtags and a call to action",
        "Tied to the specific image or video it is about",
      ],
    },
    {
      id: "agent",
      icon: "🤝",
      title: "24-hour sales assistant",
      lead: "Answers customers, recommends products, takes orders.",
      bullets: [
        "Price and stock read only from your own catalogue",
        "Handles objections and suggests alternatives",
        "Takes the order and collects the payment receipt",
        "You confirm payment — the AI never does",
        "Anything sensitive is escalated to you",
      ],
    },
    {
      id: "campaigns",
      icon: "🚀",
      title: "Campaigns and publishing",
      lead: "From generation to publication, in one flow.",
      bullets: [
        "Group poster, video and caption into one campaign",
        "Human approval before anything goes out",
        "Publish straight to Instagram",
        "Per-platform delivery status",
      ],
    },
  ],

  trust: [
    {
      icon: "🎁",
      title: "Two weeks free",
      desc: "You see real output for your own products before paying anything.",
    },
    {
      icon: "🛡️",
      title: "No risk",
      desc: "If two weeks bring you nothing, you pay nothing.",
    },
    {
      icon: "🔒",
      title: "Processing on our own servers",
      desc: "Image and video generation runs on our own hardware. Two things do leave, and we say so plainly: voice-over, and competitor price lookups.",
    },
    {
      icon: "👤",
      title: "The final call is yours",
      desc: "Nothing is published without your approval.",
    },
  ],

  faq: [
    {
      q: "Do I need to know how to use AI?",
      a: "No. You enter the product and its photo; the rest is automatic. There is no prompt writing.",
    },
    {
      q: "Does it use my product photo, or an invented image?",
      a: "Your real photo. The poster is built on top of it, so the buyer sees exactly what they are buying.",
    },
    {
      q: "How does it tell customers price and stock?",
      a: "Only from what you entered. It never invents a number, and if it does not know something it says so.",
    },
    {
      q: "What language is the content in?",
      a: "Persian, in your brand's tone. Video narration can be Persian or English — your choice.",
    },
    {
      q: "How long does it take?",
      a: "Captions and copy are ready in minutes. Posters and video need rendering and go into a queue — you watch the progress live. Either way it is not the days and weeks a human team takes.",
    },
    {
      q: "What if I do not like the output?",
      a: "You generate it again. Nothing is published until you approve it.",
    },
    {
      q: "What does the monthly quota mean?",
      a: "Each plan includes a set number of video seconds, images and captions per month. You see usage live in the panel, and a failed render returns its quota.",
    },
    {
      q: "How does payment work?",
      a: "Monthly. The two-week trial starts without a card and does not auto-renew.",
    },
    {
      q: "Does it connect to my Instagram?",
      a: "Yes. Connect the account and approved content publishes directly. If you prefer, you can still publish manually.",
    },
    {
      q: "Is my shop's data safe?",
      a: "Each shop is fully isolated and only its owner can reach its data. Image and video generation runs on our own servers; voice-over and competitor price lookups use outside services, and our privacy policy says exactly which.",
    },
  ],

  about: {
    mission:
      "Professional marketing should not be a privilege of large companies. " +
      "NMarketing does the work of a five-person marketing team for a small shop, " +
      "at a fraction of the cost.",
    story: [
      {
        title: "We watched the problem up close",
        text:
          "Small businesses have good products and no way to show them well. " +
          "Hiring a team is expensive and agencies are rarely transparent.",
      },
      {
        title: "We built a flow, not another tool",
        text:
          "Existing tools each solve one piece and leave you to wire them together. " +
          "We built the whole path, from adding a product to publishing it.",
      },
      {
        title: "On our own hardware",
        text:
          "Image and video generation runs on GPUs we own — so pricing is not " +
          "tied to the exchange rate, and capacity is ours to grow.",
      },
    ],
    values: [
      { icon: "🎯", title: "Sales, not decoration", desc: "The goal is more sales, not prettier posts." },
      { icon: "🔍", title: "Honest numbers", desc: "Price and stock are never invented." },
      { icon: "👤", title: "People decide", desc: "Publishing and payment approval always stay with you." },
      { icon: "🇮🇷", title: "Built for Iran", desc: "The language, the culture, the local market." },
    ],
  },

  capabilities: [
    { value: "4", label: "output types", hint: "Poster · Video · Caption · Sales reply" },
    { value: "3", label: "caption platforms", hint: "Instagram · Telegram · LinkedIn" },
    { value: "10", label: "product-analysis outputs", hint: "From target audience to suggested tone" },
    { value: "11", label: "competitor-analysis outputs", hint: "Each with its source and date" },
  ],

  audiences: [
    { icon: "👕", label: "Clothing", proven: true },
    { icon: "💎", label: "Jewellery and accessories", proven: true },
    { icon: "🛋️", label: "Home decor", proven: true },
    { icon: "🧴", label: "Beauty and personal care" },
    { icon: "🍯", label: "Food and handmade goods" },
    { icon: "👟", label: "Shoes and bags" },
    { icon: "📱", label: "Phone and tech accessories" },
    { icon: "🌿", label: "Plants and gardening" },
  ],

  alternatives: {
    left: {
      title: "Without NMarketing",
      items: [
        "Hire a team of five",
        "Or hand it to an agency at an unclear cost",
        "Or make the content yourself, at night",
        "Or — most commonly — none of the above",
        "Output that is irregular and uneven",
        "Direct messages left unanswered",
      ],
    },
    right: {
      title: "With NMarketing",
      items: [
        "Add each product once",
        "A content pack ready in minutes",
        "A cost you know in advance",
        "The final approval always yours",
        "Consistent output, month after month",
        "Customers answered around the clock",
      ],
    },
  },

  objections: [
    {
      icon: "🤖",
      q: "Won't the output look artificial?",
      a: "The poster is built on your real photo, not generated from nothing. The text is placed in code so the letters never break.",
    },
    {
      icon: "🎛️",
      q: "Do I lose control?",
      a: "Nothing is published without your approval, and you can regenerate any output until you are happy with it.",
    },
    {
      icon: "💸",
      q: "Are there hidden costs later?",
      a: "Each plan's quota is known up front and you watch your usage live. A failed render gives its quota back.",
    },
    {
      icon: "🔌",
      q: "What if I want to stop?",
      a: "The trial does not auto-renew, and the content you made is yours to keep.",
    },
  ],
};

const CONTENT: Localized<Content> = { fa, en };

export function contentFor(locale: Locale): Content {
  return CONTENT[locale];
}
