/**
 * Tool catalogue.
 *
 * Three tools, built properly, rather than the seven the spec sketches. Each
 * one has to produce output a person would actually post; a page that emits
 * filler is worse for the brand than not existing.
 *
 * `honesty` is required, not decorative. Every tool page states in plain words
 * that it runs in the browser with no AI, so nobody mistakes the free tool for
 * the paid product — and so the upsell is a real difference rather than a
 * crippled version of the same thing.
 */
import type { Locale } from "../i18n";

export type ToolMeta = {
  slug: string;
  icon: string;
  title: string;
  lead: string;
  /** Metadata description — written for the search result, not the page. */
  metaDesc: string;
  /** What it does, in one short paragraph. */
  intro: string;
  /** The plain statement about what this is and is not. */
  honesty: string;
  /** Why the paid product is different — must be a real difference. */
  upsell: string;
  /** Practical advice, so the page is worth reading even without using it. */
  tips: string[];
};

const fa: ToolMeta[] = [
  {
    slug: "instagram-caption-generator",
    icon: "✍️",
    title: "کپشن‌ساز اینستاگرام",
    lead: "سه طول کپشن، با هشتگ و دعوت به اقدام — رایگان و بدون ثبت‌نام.",
    metaDesc:
      "کپشن‌ساز رایگان اینستاگرام برای فروشگاه‌های آنلاین. سه طول، هشتگ و CTA. بدون ثبت‌نام.",
    intro:
      "محصول، مخاطب و مزیتش را بنویس؛ سه نسخه‌ی کوتاه، متوسط و بلند می‌گیری که می‌توانی مستقیم کپی کنی.",
    honesty:
      "این ابزار در مرورگر خودت اجرا می‌شود. هوش مصنوعی نیست و چیزی به سروری فرستاده نمی‌شود — ساختار و الگوهای جواب‌داده است، روی چیزی که خودت نوشتی.",
    upsell:
      "نسخه‌ی هوش مصنوعی، کپشن را از روی عکس واقعی محصولت و کاتالوگ خودت می‌نویسد و به همان تصویری وصلش می‌کند که برایش ساخته شده.",
    tips: [
      "خط اول مهم‌ترین خط است — اینستاگرام بقیه را جمع می‌کند.",
      "یک دعوت به اقدام، نه سه تا. «دایرکت بده» با «لینک بایو» و «کامنت بذار» با هم، یعنی هیچ‌کدام.",
      "هشتگ‌های خیلی عمومی رقابتشان زیاد است؛ ترکیب عمومی و خاص بهتر جواب می‌دهد.",
      "مزیت را بنویس نه ویژگی را: «سبک است» کمتر از «تمام روز اذیت نمی‌کند» می‌فروشد.",
    ],
  },
  {
    slug: "instagram-bio-generator",
    icon: "📇",
    title: "بایوساز اینستاگرام",
    lead: "سه نسخه بایو برای پیج فروشگاهت — کوتاه، روشن، قابل کپی.",
    metaDesc:
      "بایوساز رایگان اینستاگرام برای کسب‌وکارها. سه نسخه‌ی آماده با محل و دعوت به اقدام.",
    intro:
      "اسم کسب‌وکار، چه می‌فروشی و کجایی را بنویس؛ سه بایو می‌گیری که در ۱۵۰ کاراکتر جا می‌شود.",
    honesty:
      "در مرورگر خودت اجرا می‌شود. هوش مصنوعی نیست و اطلاعاتت جایی ذخیره نمی‌شود.",
    upsell:
      "در محصول، لحن برندت یک‌بار ثبت می‌شود و بعد هر متنی — بایو، کپشن، سناریو — با همان لحن نوشته می‌شود.",
    tips: [
      "بایو جای شعار نیست، جای جواب دادن به «اینجا چه می‌فروشند؟» است.",
      "شهر را بنویس اگر ارسال محلی داری — خیلی‌ها بر همین اساس تصمیم می‌گیرند.",
      "ایموجی به‌جای بولت خوب است، ولی سه تا در هر خط زیاد است.",
      "یک راه تماس مشخص بگذار؛ «دایرکت» اگر واقعاً جواب می‌دهی.",
    ],
  },
  {
    slug: "content-calendar-generator",
    icon: "🗓️",
    title: "تقویم محتوا",
    lead: "برنامه‌ی انتشار چند هفته‌ای با نوع پست و ایده — نه فقط یک جدول خالی.",
    metaDesc:
      "تقویم محتوای رایگان برای اینستاگرام فروشگاه‌ها. نوع پست و ایده برای هر روز.",
    intro:
      "بگو هفته‌ای چند پست می‌گذاری و برای چند هفته برنامه می‌خواهی؛ یک تقویم با نوع پست و ایده‌ی هر روز می‌گیری.",
    honesty:
      "در مرورگر خودت ساخته می‌شود. الگوی انتشاری است که برای فروشگاه‌های کوچک جواب داده، نه خروجی مدل.",
    upsell:
      "در محصول، تقویم به کاتالوگ واقعی‌ات وصل می‌شود: می‌داند کدام محصول را داری و برای همان محتوا می‌سازد.",
    tips: [
      "تنوع نوع پست مهم‌تر از تعداد پست است. سه پست متنوع بهتر از هفت پست معرفی محصول.",
      "اگر هفته‌ای دو پست را مرتب می‌گذاری، از هفته‌ای پنج‌تای نامرتب بهتر است.",
      "یک روز را برای پاسخ به سؤال‌های تکراری مشتری‌ها بگذار — همان‌ها بیشترین جستجو را دارند.",
      "پیشنهاد ویژه را کم ولی با مهلت مشخص بگذار.",
    ],
  },
];

const en: ToolMeta[] = [
  {
    slug: "instagram-caption-generator",
    icon: "✍️",
    title: "Instagram caption generator",
    lead: "Three caption lengths with hashtags and a call to action — free, no signup.",
    metaDesc:
      "A free Instagram caption generator for online shops. Three lengths, hashtags and a CTA. No signup.",
    intro:
      "Type the product, who it is for and why it is good; you get a short, a medium and a long version you can copy straight out.",
    honesty:
      "This runs in your own browser. It is not AI and nothing is sent to a server — it is structure and patterns that work, applied to what you typed.",
    upsell:
      "The AI version writes the caption from your real product photo and your own catalogue, and ties it to the exact image it was made for.",
    tips: [
      "The first line carries the post — Instagram folds the rest away.",
      "One call to action, not three. “DM us” plus “link in bio” plus “comment below” means none of them.",
      "Very broad hashtags are crowded; mix broad with specific.",
      "Write the benefit, not the feature: “lightweight” sells less than “doesn't bother you all day”.",
    ],
  },
  {
    slug: "instagram-bio-generator",
    icon: "📇",
    title: "Instagram bio generator",
    lead: "Three bios for your shop page — short, clear, ready to paste.",
    metaDesc:
      "A free Instagram bio generator for businesses. Three ready versions with location and a call to action.",
    intro:
      "Type your business name, what you sell and where you are; you get three bios that fit in 150 characters.",
    honesty: "It runs in your own browser. Not AI, and nothing you type is stored.",
    upsell:
      "In the product you set your brand voice once, and every piece of copy after that — bio, caption, script — is written in it.",
    tips: [
      "A bio is not a slogan; it answers “what do they sell here?”",
      "Name your city if you deliver locally — many people decide on that alone.",
      "Emoji as bullets is fine; three per line is not.",
      "Give one clear way to reach you, and only if you actually answer there.",
    ],
  },
  {
    slug: "content-calendar-generator",
    icon: "🗓️",
    title: "Content calendar generator",
    lead: "A multi-week posting plan with a post type and an idea for each slot.",
    metaDesc:
      "A free content calendar for shop Instagram accounts. Post type and idea for every day.",
    intro:
      "Say how many posts a week and how many weeks; you get a calendar with a post type and an idea for each one.",
    honesty:
      "Built in your browser. It is a posting pattern that works for small shops, not model output.",
    upsell:
      "In the product the calendar is wired to your real catalogue: it knows which products you have and builds content for those.",
    tips: [
      "Variety of post type matters more than volume. Three varied posts beat seven product shots.",
      "Two posts a week you actually keep to beats five you do not.",
      "Give one slot to the questions customers keep asking — those get the most search.",
      "Use offers sparingly, and always with a deadline.",
    ],
  },
];

const TOOLS: Record<Locale, ToolMeta[]> = { fa, en };

export function toolsFor(locale: Locale): ToolMeta[] {
  return TOOLS[locale];
}

export function getTool(slug: string, locale: Locale): ToolMeta | undefined {
  return TOOLS[locale].find((t) => t.slug === slug);
}

export const toolSlugs = fa.map((t) => t.slug);
