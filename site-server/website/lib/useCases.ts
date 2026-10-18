/**
 * Use-case pages — "what can I *do* with this", not "what features exist".
 *
 * A feature page answers "what is the image studio". A use-case page answers
 * "I'm launching a product next week, walk me through it". Same product,
 * different question, different search intent.
 *
 * Every step here must be something the product actually does today, or be
 * marked `soon`. A use-case that quietly assumes an unbuilt feature turns into
 * a support ticket the day someone follows it.
 */

import type { Locale } from "./i18n";

export type UseCase = {
  slug: string;
  title: string;
  /** The user's own phrasing of the goal. */
  goal: string;
  icon: string;
  /** Why this is hard without the product. */
  pain: string;
  steps: { title: string; desc: string; soon?: boolean }[];
  /** What the user ends up holding. */
  output: string[];
  /** Roughly how long, stated honestly — renders take real time. */
  effort: string;
};

const fa: UseCase[] = [
  {
    slug: "create-social-media-content",
    title: "تولید محتوای شبکه‌های اجتماعی",
    goal: "این هفته باید چند پست بگذارم و چیزی آماده ندارم.",
    icon: "📅",
    pain:
      "هر پست یعنی یک عکس، یک متن و یک تصمیم درباره‌ی لحن. ضرب در هفت روز، " +
      "می‌شود کاری که یک نفر تمام‌وقت لازم دارد.",
    steps: [
      { title: "محصول را انتخاب کنید", desc: "از کاتالوگی که قبلاً وارد کرده‌اید." },
      { title: "نوع محتوا را بگویید", desc: "پوستر تبلیغاتی یا عکس نمایش محصول." },
      { title: "کپشن را بگیرید", desc: "برای اینستاگرام، تلگرام و لینکدین — هرکدام سه طول." },
      { title: "تأیید و انتشار", desc: "هیچ چیز بدون تأیید شما منتشر نمی‌شود." },
    ],
    output: ["پوستر یا عکس محصول", "کپشن سه‌پلتفرمی با هشتگ و CTA", "آماده‌ی انتشار"],
    effort: "چند دقیقه برای کپشن، و زمان رندر برای تصویر",
  },
  {
    slug: "launch-a-product",
    title: "معرفی محصول جدید",
    goal: "محصول جدیدی آمده و باید کامل معرفی‌اش کنم.",
    icon: "🚀",
    pain:
      "معرفی محصول فقط یک پست نیست — تحلیل، جایگاه‌یابی، چند قالب محتوا و یک " +
      "برنامه‌ی انتشار می‌خواهد.",
    steps: [
      { title: "محصول را وارد کنید", desc: "عکس، قیمت، موجودی و مشخصات." },
      { title: "تحلیل محصول بگیرید", desc: "نقاط فروش، مخاطب هدف، اعتراض‌های محتمل." },
      { title: "رقبا را ببینید", desc: "قیمت واقعی رقبا از دیجی‌کالا و ترب، با منبع." },
      { title: "بسته‌ی محتوا بسازید", desc: "پوستر، عکس نمایش، ویدیوی کوتاه و کپشن‌ها." },
      { title: "در کمپین گروه کنید", desc: "همه زیر یک کمپین، با تأیید یکجا." },
    ],
    output: ["پرونده‌ی بازاریابی محصول", "مقایسه با رقبا", "بسته‌ی کامل محتوا"],
    effort: "تحلیل چند دقیقه؛ ویدیو بسته به طول، در صف رندر",
  },
  {
    slug: "analyze-competitors",
    title: "فهمیدن اینکه رقبا چه می‌کنند",
    goal: "نمی‌دانم رقیبم چند می‌فروشد و چطور می‌فروشد.",
    icon: "🔍",
    pain:
      "بیشتر ابزارها از مدل می‌پرسند «رقبا کی‌اند» و مدل از خودش اسم و قیمت " +
      "درمی‌آورد. آن داده به درد تصمیم‌گیری نمی‌خورد.",
    steps: [
      { title: "محصول را انتخاب کنید", desc: "چیزی وارد نمی‌کنید؛ سیستم خودش می‌گردد." },
      { title: "جستجوی واقعی وب", desc: "دیجی‌کالا، ترب و جستجوی وب — نه حافظه‌ی مدل." },
      { title: "مشاهده از نتیجه‌گیری جدا می‌شود", desc: "هر عدد با لینک و تاریخ دریافت ثبت می‌شود." },
      { title: "جایگاه خودتان را ببینید", desc: "مقایسه‌ی مستقیم قیمت و موضع با هر رقیب." },
    ],
    output: ["کارت هر رقیب با منبع", "مقایسه‌ی قیمت", "شکاف‌ها و فرصت‌های تمایز"],
    effort: "چند دقیقه",
  },
  {
    slug: "create-promotional-videos",
    title: "ساخت ویدیوی تبلیغاتی",
    goal: "برای ریلز و استوری ویدیو لازم دارم ولی تدوینگر ندارم.",
    icon: "🎬",
    pain:
      "ویدیو گران‌ترین قالب محتواست — هم از نظر وقت، هم مهارت. و اگر بد دربیاید، " +
      "بدتر از نداشتنش است.",
    steps: [
      { title: "سناریو تولید می‌شود", desc: "صحنه‌بندی، مدت هر صحنه و نریشن." },
      { title: "قطعات ۵ ثانیه‌ای ساخته می‌شوند", desc: "هر قطعه از فریم آخر قبلی شروع می‌شود." },
      { title: "کیفیت هر قطعه سنجیده می‌شود", desc: "پیوستگی، ثبات محصول و طبیعی بودن حرکت.", soon: true },
      { title: "صداگذاری فارسی یا انگلیسی", desc: "طول صدا با طول واقعی هر صحنه جور می‌شود." },
      { title: "اتصال نهایی", desc: "قطعات با FFmpeg به هم چسبانده و صدا میکس می‌شود." },
    ],
    output: ["ویدیوی پیوسته با نریشن", "کپشن مخصوص همان ویدیو"],
    effort: "رندر واقعی زمان می‌برد — در صف انجام می‌شود، نه بی‌درنگ",
  },
  {
    slug: "answer-customers",
    title: "جواب دادن به مشتری‌ها",
    goal: "دایرکت و پیام زیاد می‌آید و نمی‌رسم.",
    icon: "💬",
    pain:
      "مشتری که جواب نگیرد می‌رود. ولی جواب دادن یعنی کسی باید تمام روز " +
      "آنلاین باشد و قیمت و موجودی را از حفظ بداند.",
    steps: [
      { title: "کاتالوگ را وصل کنید", desc: "قیمت و موجودی از همان‌جا خوانده می‌شود." },
      { title: "لحن و قوانین فروش را تنظیم کنید", desc: "چه بگوید، چه نگوید، تخفیف تا کجا.", soon: true },
      { title: "ایجنت جواب می‌دهد", desc: "پرسش محصول، قیمت، ارسال، مرجوعی، مقایسه و پیشنهاد." },
      { title: "سفارش ثبت می‌شود", desc: "مشتری رسید می‌فرستد و **شما** تأیید می‌کنید." },
      { title: "موارد حساس به شما ارجاع می‌شود", desc: "شکایت یا چیزی که از پس مدل برنمی‌آید." },
    ],
    output: ["پاسخ ۲۴ ساعته", "سفارش‌های ثبت‌شده", "اعلان موارد نیازمند دخالت شما"],
    effort: "بی‌درنگ",
  },
  {
    slug: "build-content-strategy",
    title: "ساختن استراتژی محتوا",
    goal: "نمی‌دانم درباره‌ی چه چیزی محتوا بسازم.",
    icon: "🧭",
    pain:
      "تولید محتوای بی‌هدف، وقت و بودجه را می‌سوزاند بدون اینکه فروش بیاورد.",
    steps: [
      { title: "محصولاتتان تحلیل می‌شوند", desc: "زاویه‌های تبلیغاتی و ایده‌های محتوا." },
      { title: "بازار و رقبا بررسی می‌شوند", desc: "شکاف‌های محتوایی که رقبا پر نکرده‌اند." },
      { title: "ترندها اضافه می‌شوند", desc: "چه چیزی الان داغ است و به محصول شما می‌خورد.", soon: true },
      { title: "برنامه‌ی انتشار", desc: "چه محتوایی، برای چه محصولی، چه زمانی.", soon: true },
    ],
    output: ["فهرست ایده‌های محتوا", "شکاف‌های بازار", "برنامه‌ی انتشار"],
    effort: "چند دقیقه",
  },
];

const en: UseCase[] = [
  {
    slug: "create-social-media-content",
    title: "Making social media content",
    goal: "I need to post this week and I have nothing ready.",
    icon: "📅",
    pain:
      "Every post means an image, some copy and a decision about tone. " +
      "Multiply by seven days and it is a full-time job.",
    steps: [
      { title: "Pick the product", desc: "From the catalogue you already added." },
      { title: "Say what kind of content", desc: "An ad poster, or a product showcase shot." },
      { title: "Take the caption", desc: "Instagram, Telegram and LinkedIn — three lengths each." },
      { title: "Approve and publish", desc: "Nothing goes out without your approval." },
    ],
    output: ["A poster or product shot", "Captions for three platforms, with hashtags and a CTA", "Ready to publish"],
    effort: "Minutes for the caption, plus render time for the image",
  },
  {
    slug: "launch-a-product",
    title: "Launching a new product",
    goal: "Something new arrived and I need to introduce it properly.",
    icon: "🚀",
    pain:
      "A launch is not one post — it needs analysis, positioning, several " +
      "content formats and a publishing plan.",
    steps: [
      { title: "Add the product", desc: "Photo, price, stock and specifications." },
      { title: "Run product analysis", desc: "Selling points, target audience, likely objections." },
      { title: "Look at competitors", desc: "Real competitor prices from Digikala and Torob, with sources." },
      { title: "Build the content pack", desc: "Poster, showcase shot, short video and captions." },
      { title: "Group it into a campaign", desc: "Everything under one campaign, approved together." },
    ],
    output: ["A product marketing brief", "A comparison against competitors", "A full content pack"],
    effort: "Analysis in minutes; video depends on length and goes into the render queue",
  },
  {
    slug: "analyze-competitors",
    title: "Finding out what competitors are doing",
    goal: "I do not know what my competitor charges, or how they sell.",
    icon: "🔍",
    pain:
      "Most tools ask a model who the competitors are, and the model invents " +
      "names and prices. That data is useless for a decision.",
    steps: [
      { title: "Pick the product", desc: "You enter nothing; the system goes looking." },
      { title: "A real web search", desc: "Digikala, Torob and web search — not the model's memory." },
      { title: "Observation stays separate from conclusion", desc: "Every figure is stored with its link and the date it was read." },
      { title: "See where you stand", desc: "A direct price and positioning comparison against each competitor." },
    ],
    output: ["A card per competitor with sources", "A price comparison", "Gaps and room to differentiate"],
    effort: "A few minutes",
  },
  {
    slug: "create-promotional-videos",
    title: "Making a promotional video",
    goal: "I need video for reels and stories but I have no editor.",
    icon: "🎬",
    pain:
      "Video is the most expensive format — in time and in skill. And if it " +
      "comes out badly, it is worse than not having one.",
    steps: [
      { title: "A script is generated", desc: "Scene breakdown, duration per scene, and narration." },
      { title: "Five-second segments are built", desc: "Each one starts from the last frame of the one before." },
      { title: "Each segment is quality-checked", desc: "Continuity, product consistency, and natural motion.", soon: true },
      { title: "Persian or English narration", desc: "The audio is fitted to the real length of each scene." },
      { title: "Final assembly", desc: "Segments joined with FFmpeg and the audio mixed in." },
    ],
    output: ["One continuous video with narration", "A caption written for that specific video"],
    effort: "Real rendering takes real time — it runs in a queue, not instantly",
  },
  {
    slug: "answer-customers",
    title: "Answering customers",
    goal: "Messages keep coming and I cannot keep up.",
    icon: "💬",
    pain:
      "A customer who gets no answer leaves. But answering means someone " +
      "online all day who knows every price and stock level by heart.",
    steps: [
      { title: "Connect the catalogue", desc: "Price and stock are read from there." },
      { title: "Set the tone and the sales rules", desc: "What to say, what not to say, how far a discount can go.", soon: true },
      { title: "The agent answers", desc: "Product questions, price, shipping, returns, comparisons and recommendations." },
      { title: "Orders get recorded", desc: "The customer sends a receipt and **you** confirm it." },
      { title: "Sensitive cases come to you", desc: "A complaint, or anything the model cannot handle." },
    ],
    output: ["Round-the-clock replies", "Recorded orders", "Alerts for anything needing you"],
    effort: "Instant",
  },
  {
    slug: "build-content-strategy",
    title: "Building a content strategy",
    goal: "I do not know what to make content about.",
    icon: "🧭",
    pain:
      "Content made without a direction burns time and budget without bringing sales.",
    steps: [
      { title: "Your products get analysed", desc: "Advertising angles and content ideas." },
      { title: "Market and competitors are checked", desc: "Content gaps your competitors have not filled." },
      { title: "Trends are added", desc: "What is hot right now that actually fits your product.", soon: true },
      { title: "A publishing plan", desc: "What content, for which product, when.", soon: true },
    ],
    output: ["A list of content ideas", "Market gaps", "A publishing plan"],
    effort: "A few minutes",
  },
];

const USE_CASES: Record<Locale, UseCase[]> = { fa, en };

export function useCasesFor(locale: Locale): UseCase[] {
  return USE_CASES[locale];
}

export function getUseCase(slug: string, locale: Locale): UseCase | undefined {
  return USE_CASES[locale].find((u) => u.slug === slug);
}

/** Slugs are shared across locales, so static params only need one pass. */
export const useCaseSlugs = fa.map((u) => u.slug);
