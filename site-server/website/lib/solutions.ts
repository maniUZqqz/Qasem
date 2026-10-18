/**
 * Industry solution pages.
 *
 * These exist to answer one search intent each: "I sell X — does this work for
 * me?" So every entry carries the *industry's* real problem in its own words,
 * not a template with the business name swapped. A page whose only difference
 * from its neighbour is a noun is SEO spam; we do not ship those.
 *
 * Adding one: only when there is a real audience, a real workflow difference,
 * and something specific to say. Otherwise leave it out.
 */

import type { Locale } from "./i18n";

export type Solution = {
  slug: string;
  name: string;
  /** Shown on cards and in the hero. */
  tagline: string;
  icon: string;
  /** What this industry actually struggles with, stated plainly. */
  problem: string[];
  /** How the product answers each of those, in the same order where possible. */
  answer: { title: string; desc: string }[];
  /** Which built features matter most here — order is the reading order. */
  features: string[];
  /** A concrete before/after the buyer can picture. */
  example: { before: string; after: string };
  /** Realistic monthly output for a shop this size. */
  workflow: string[];
};

const fa: Solution[] = [
  {
    slug: "instagram-sellers",
    name: "فروشندگان اینستاگرام",
    tagline: "پیج فعال، بدون تیم محتوا",
    icon: "📱",
    problem: [
      "اینستاگرام روزی چند پست می‌خواهد و تولیدش وقت می‌برد.",
      "دایرکت‌ها بی‌جواب می‌مانند و مشتری می‌رود.",
      "عکس محصول با موبایل گرفته شده و حرفه‌ای به نظر نمی‌رسد.",
    ],
    answer: [
      {
        title: "محتوای هر روز، در چند دقیقه",
        desc: "از همان عکس محصول، پوستر و کپشن آماده‌ی انتشار می‌سازد.",
      },
      {
        title: "دایرکت بی‌جواب نمی‌ماند",
        desc: "ایجنت فروش قیمت و موجودی را از کاتالوگ خودتان می‌گوید و سفارش می‌گیرد.",
      },
      {
        title: "عکس موبایلی، خروجی حرفه‌ای",
        desc: "نور و پس‌زمینه اصلاح می‌شود ولی خود محصول دست‌نخورده می‌ماند.",
      },
    ],
    features: ["استودیوی تصویر", "موتور کپشن", "ایجنت فروش", "انتشار خودکار"],
    example: {
      before: "عکس کفش روی موکت، با نور زرد لامپ اتاق.",
      after: "همان کفش، روی پس‌زمینه‌ی تمیز با نور استودیویی و کپشن آماده‌ی پست.",
    },
    workflow: [
      "محصولات را یک بار وارد می‌کنید",
      "برای هرکدام پوستر و کپشن می‌گیرید",
      "تأیید می‌کنید و منتشر می‌شود",
      "ایجنت جواب دایرکت‌ها را می‌دهد",
    ],
  },
  {
    slug: "online-shops",
    name: "فروشگاه‌های اینترنتی",
    tagline: "کاتالوگ بزرگ، محتوای کم",
    icon: "🛒",
    problem: [
      "صدها محصول دارید و برای اکثرشان هیچ محتوایی تولید نشده.",
      "نمی‌دانید کدام محصول واقعاً سود می‌دهد، فقط می‌دانید کدام زیاد می‌فروشد.",
      "رقبا قیمت را عوض می‌کنند و شما دیر می‌فهمید.",
    ],
    answer: [
      {
        title: "محتوا برای هر محصول، نه فقط ده تای اول",
        desc: "تولید دسته‌ای از روی همان کاتالوگی که دارید.",
      },
      {
        title: "قیمت رقبا از وب واقعی",
        desc: "از دیجی‌کالا و ترب خوانده می‌شود، با منبع و تاریخ — نه حدس مدل.",
      },
      {
        title: "تحلیل محصول قبل از تبلیغ",
        desc: "نقاط فروش، مخاطب هدف و اعتراض‌های محتمل، قبل از خرج تبلیغات.",
      },
    ],
    features: ["هوش محصول", "تحلیل رقبا", "استودیوی تصویر", "کمپین"],
    example: {
      before: "۳۰۰ محصول در سایت، ۱۲ تایشان عکس درست دارند.",
      after: "هر محصول پوستر، کپشن سه‌پلتفرمی و پرونده‌ی بازاریابی دارد.",
    },
    workflow: [
      "کاتالوگ را وارد می‌کنید",
      "تحلیل محصول و رقبا اجرا می‌شود",
      "برای محصولات اولویت‌دار محتوا می‌سازید",
      "در کمپین گروه‌بندی و منتشر می‌کنید",
    ],
  },
  {
    slug: "clothing-businesses",
    name: "پوشاک",
    tagline: "لباس را باید تن آدم دید",
    icon: "👗",
    problem: [
      "عکس لباس روی چوب‌لباسی نمی‌فروشد؛ مشتری می‌خواهد تنِ کسی ببیند.",
      "عکاسی با مدل برای هر فصل گران است.",
      "مدل‌های AI معمولاً خودِ لباس را عوض می‌کنند.",
    ],
    answer: [
      {
        title: "لباس شما، نه لباس شبیه آن",
        desc: "بینایی ماشین رنگ، شکل و جزئیات را با عکس اصلی مقایسه می‌کند و تغییر را رد می‌کند.",
      },
      {
        title: "صحنه عوض می‌شود، محصول نه",
        desc: "مدل، محیط و نور تغییر می‌کنند؛ خود لباس دست‌نخورده می‌ماند.",
      },
      {
        title: "ویدیوی کوتاه برای ریلز",
        desc: "قطعات پیوسته با صداگذاری، از همان عکس محصول.",
      },
    ],
    features: ["نمایش محصول", "کنترل کیفیت تصویر", "استودیوی ویدیو", "موتور کپشن"],
    example: {
      before: "کت روی چوب‌لباسی، جلوی دیوار سفید.",
      after: "همان کت — همان رنگ و همان دکمه‌ها — در یک صحنه‌ی پاییزی.",
    },
    workflow: [
      "عکس محصول را آپلود می‌کنید",
      "صحنه و مدل را انتخاب می‌کنید",
      "خروجی با عکس اصلی مقایسه می‌شود",
      "تأیید و انتشار",
    ],
  },
  {
    slug: "home-decor",
    name: "دکوراسیون و لوازم خانه",
    tagline: "محصول را باید در فضا دید",
    icon: "🛋️",
    problem: [
      "مشتری نمی‌تواند تصور کند این محصول در خانه‌اش چطور می‌شود.",
      "عکس تکی محصول روی پس‌زمینه‌ی سفید، حس فضا نمی‌دهد.",
      "چیدمان و عکاسی صحنه برای هر محصول شدنی نیست.",
    ],
    answer: [
      {
        title: "محصول در صحنه، نه روی زمینه‌ی سفید",
        desc: "همان محصول در یک اتاق واقعی‌نما، با نور و سبک دلخواه.",
      },
      {
        title: "چند فضا از یک عکس",
        desc: "یک آباژور در اتاق نشیمن مدرن، اتاق خواب گرم، یا فضای مینیمال.",
      },
      {
        title: "ویدیوی معرفی کوتاه",
        desc: "حرکت آرام دوربین دور محصول، با نریشن فارسی.",
      },
    ],
    features: ["نمایش محصول", "استودیوی ویدیو", "موتور کپشن", "کمپین"],
    example: {
      before: "آباژور روی میز، عکس با فلاش موبایل.",
      after: "همان آباژور کنار مبل، در نور غروب — و یک ویدیوی ده ثانیه‌ای.",
    },
    workflow: [
      "عکس محصول را وارد می‌کنید",
      "سبک فضا را انتخاب می‌کنید",
      "چند صحنه‌ی مختلف می‌گیرید",
      "بهترین را تأیید و منتشر می‌کنید",
    ],
  },
];

const en: Solution[] = [
  {
    slug: "instagram-sellers",
    name: "Instagram sellers",
    tagline: "An active page without a content team",
    icon: "📱",
    problem: [
      "Instagram wants several posts a day, and making them takes time.",
      "Direct messages go unanswered and the buyer moves on.",
      "Product photos are shot on a phone and do not look professional.",
    ],
    answer: [
      {
        title: "Every day's content, in minutes",
        desc: "From the same product photo, a poster and a caption ready to post.",
      },
      {
        title: "No unanswered messages",
        desc: "The sales agent quotes price and stock from your own catalogue and takes the order.",
      },
      {
        title: "Phone photo in, professional shot out",
        desc: "Lighting and background are fixed; the product itself is left alone.",
      },
    ],
    features: ["Image studio", "Caption engine", "Sales agent", "Auto publishing"],
    example: {
      before: "A shoe on the carpet, lit by a yellow ceiling bulb.",
      after: "The same shoe on a clean background in studio light, with the caption written.",
    },
    workflow: [
      "Add your products once",
      "Generate a poster and caption for each",
      "Approve, and it publishes",
      "The agent handles the direct messages",
    ],
  },
  {
    slug: "online-shops",
    name: "Online shops",
    tagline: "A big catalogue and not enough content",
    icon: "🛒",
    problem: [
      "You have hundreds of products and content for almost none of them.",
      "You know which product sells the most, not which one actually makes money.",
      "Competitors change prices and you find out late.",
    ],
    answer: [
      {
        title: "Content for every product, not just the first ten",
        desc: "Batch generation straight from the catalogue you already have.",
      },
      {
        title: "Competitor prices from the real web",
        desc: "Read off Digikala and Torob with a source and a date — not a guess from a model.",
      },
      {
        title: "Analyse before you advertise",
        desc: "Selling points, target audience and likely objections, before the ad budget goes out.",
      },
    ],
    features: ["Product intelligence", "Competitor analysis", "Image studio", "Campaigns"],
    example: {
      before: "300 products on the site, 12 of them with a decent photo.",
      after: "Every product has a poster, captions for three platforms, and a marketing brief.",
    },
    workflow: [
      "Import the catalogue",
      "Product and competitor analysis runs",
      "Generate content for the priority products",
      "Group into a campaign and publish",
    ],
  },
  {
    slug: "clothing-businesses",
    name: "Clothing",
    tagline: "Clothes have to be seen on someone",
    icon: "👗",
    problem: [
      "A garment on a hanger does not sell; the buyer wants to see it worn.",
      "A model shoot every season is expensive.",
      "AI models usually change the garment itself.",
    ],
    answer: [
      {
        title: "Your garment, not one that resembles it",
        desc: "Machine vision compares colour, shape and detail against the original photo and rejects a changed one.",
      },
      {
        title: "The scene changes, the product does not",
        desc: "Model, setting and lighting change; the garment stays exactly as it is.",
      },
      {
        title: "Short video for reels",
        desc: "Continuous segments with narration, built from the same product photo.",
      },
    ],
    features: ["Product showcase", "Image quality control", "Video studio", "Caption engine"],
    example: {
      before: "A coat on a hanger against a white wall.",
      after: "The same coat — same colour, same buttons — in an autumn scene.",
    },
    workflow: [
      "Upload the product photo",
      "Pick the scene and the model",
      "The output is checked against the original",
      "Approve and publish",
    ],
  },
  {
    slug: "home-decor",
    name: "Home decor",
    tagline: "The product has to be seen in a room",
    icon: "🛋️",
    problem: [
      "Buyers cannot picture how the piece would look in their own home.",
      "A product shot on white gives no sense of space.",
      "Styling and shooting a set for every product is not realistic.",
    ],
    answer: [
      {
        title: "The product in a room, not on a white background",
        desc: "The same piece in a believable room, with the light and style you choose.",
      },
      {
        title: "Several settings from one photo",
        desc: "One lamp in a modern living room, a warm bedroom, or a minimal space.",
      },
      {
        title: "A short introduction video",
        desc: "A slow camera move around the product, with narration.",
      },
    ],
    features: ["Product showcase", "Video studio", "Caption engine", "Campaigns"],
    example: {
      before: "A lamp on a table, shot with a phone flash.",
      after: "The same lamp beside a sofa in evening light — and a ten-second video.",
    },
    workflow: [
      "Add the product photo",
      "Choose the style of the room",
      "Generate a few different scenes",
      "Approve the best one and publish",
    ],
  },
];

const SOLUTIONS: Record<Locale, Solution[]> = { fa, en };

export function solutionsFor(locale: Locale): Solution[] {
  return SOLUTIONS[locale];
}

export function getSolution(slug: string, locale: Locale): Solution | undefined {
  return SOLUTIONS[locale].find((s) => s.slug === slug);
}

/** Slugs are shared across locales, so static params only need one pass. */
export const solutionSlugs = fa.map((s) => s.slug);
