/**
 * Comparison pages.
 *
 * The spec is explicit that these must be fair and real, and must not be SEO
 * spam. So each page is written to be useful to someone who might legitimately
 * choose the alternative — and every one names cases where the alternative is
 * the better answer.
 *
 * A comparison page that concludes "we win at everything" convinces nobody and
 * deserves to rank for nothing. The `wins` field is not decoration: if a row
 * cannot honestly be given to the other side, the page should not exist.
 */
import type { Locale } from "./i18n";

export type Comparison = {
  slug: string;
  icon: string;
  /** The alternative, named as the reader would name it. */
  other: string;
  title: string;
  lead: string;
  metaDesc: string;
  /** Honest framing of what the alternative actually is. */
  intro: string;
  rows: { aspect: string; us: string; them: string }[];
  /** Where the alternative genuinely wins. Required. */
  theirWins: string[];
  /** Where we genuinely win. */
  ourWins: string[];
  /** Who should pick which — the sentence the reader came for. */
  verdict: string;
};

const fa: Comparison[] = [
  {
    slug: "upmarket-vs-marketing-agency",
    icon: "🏢",
    other: "آژانس بازاریابی",
    title: "آپ‌مارکت یا آژانس بازاریابی؟",
    lead: "کدام برای فروشگاه شما منطقی‌تر است — و کِی آژانس واقعاً بهتر است.",
    metaDesc:
      "مقایسه‌ی منصفانه‌ی آپ‌مارکت با آژانس بازاریابی: هزینه، سرعت، کنترل و اینکه هرکدام برای چه کسی بهتر است.",
    intro:
      "آژانس یعنی سپردن کار به تیمی که این کار را حرفه‌ای انجام می‌دهد. برای کسب‌وکاری که بودجه دارد و می‌خواهد اصلاً درگیر نشود، انتخاب درستی است. مقایسه‌ی زیر برای کسی است که هنوز تصمیم نگرفته.",
    rows: [
      { aspect: "هزینه‌ی ماهانه", us: "اشتراک مشخص", them: "قرارداد، معمولاً چند برابر" },
      { aspect: "سرعت شروع", us: "همان روز", them: "جلسه، بریف، قرارداد" },
      { aspect: "تعداد محتوا", us: "محدود به سهمیه‌ی پکیج", them: "محدود به قرارداد" },
      { aspect: "درک کسب‌وکار شما", us: "از داده‌ای که وارد می‌کنید", them: "از گفتگو و تجربه‌ی انسانی" },
      { aspect: "خلاقیت غیرمنتظره", us: "محدود", them: "نقطه‌ی قوتشان" },
      { aspect: "کنترل نهایی", us: "همه‌چیز با تأیید شما", them: "بسته به قرارداد" },
    ],
    theirWins: [
      "استراتژی بلندمدت برند — چیزی که از داده‌ی محصول درنمی‌آید.",
      "کمپین‌های بزرگ و چندکاناله با بودجه‌ی تبلیغاتی جدی.",
      "ایده‌ی خلاقانه‌ای که هیچ الگویی تولیدش نمی‌کند.",
      "وقتی اصلاً نمی‌خواهید درگیر شوید و بودجه‌اش را دارید.",
    ],
    ourWins: [
      "حجم بالای محتوای روزمره، که آژانس برایش گران است.",
      "پاسخ ۲۴ ساعته به مشتری — آژانس معمولاً این را نمی‌دهد.",
      "شروع بدون قرارداد و بدون جلسه.",
      "محتوا از عکس واقعی محصول خودتان.",
    ],
    verdict:
      "اگر مشکل شما «حجم محتوای روزمره و جواب دادن به مشتری» است، آپ‌مارکت. اگر مشکل شما «برند ما چه باید بگوید» است، آژانس.",
  },
  {
    slug: "upmarket-vs-freelancer",
    icon: "🧑‍💻",
    other: "فریلنسر",
    title: "آپ‌مارکت یا فریلنسر؟",
    lead: "یک نفر که کار را انجام می‌دهد، در برابر سیستمی که همیشه هست.",
    metaDesc:
      "مقایسه‌ی منصفانه‌ی آپ‌مارکت با استخدام فریلنسر برای تولید محتوا: هزینه، ثبات، کیفیت و مناسب چه کسی.",
    intro:
      "فریلنسر خوب، ترکیبی از مهارت و درک انسانی است که هیچ ابزاری جایش را نمی‌گیرد. ولی در دسترس بودنش، ثباتش و هزینه‌اش با حجم کار بالا می‌رود.",
    rows: [
      { aspect: "هزینه", us: "ثابت و قابل پیش‌بینی", them: "به ازای هر کار" },
      { aspect: "در دسترس بودن", us: "همیشه", them: "بسته به برنامه‌اش" },
      { aspect: "ثبات کیفیت", us: "یکنواخت", them: "بالا، ولی روزبه‌روز فرق می‌کند" },
      { aspect: "درک لحن برند", us: "از پروفایلی که ثبت می‌کنید", them: "بعد از چند پروژه عالی می‌شود" },
      { aspect: "ترک کار", us: "موضوعیت ندارد", them: "ریسک واقعی" },
      { aspect: "کار غیرتکراری", us: "ضعیف", them: "نقطه‌ی قوت" },
    ],
    theirWins: [
      "کاری که قالب ندارد — یک کمپین خاص، یک ایده‌ی متفاوت.",
      "درک ظرافت‌های فرهنگی و طنز، که مدل معمولاً نمی‌گیرد.",
      "بازخورد گرفتن و تکرار کردن تا نتیجه‌ی دقیق.",
      "وقتی حجم کم است و کیفیت هر قطعه خیلی مهم.",
    ],
    ourWins: [
      "وقتی حجم بالا می‌رود، هزینه‌ی فریلنسر خطی بالا می‌رود و اشتراک نه.",
      "نیمه‌شب هم جواب مشتری داده می‌شود.",
      "پیوستگی: کسی ترک نمی‌کند و دانش برند جایی نمی‌رود.",
    ],
    verdict:
      "برای کار کم و خاص، فریلنسر. برای کار زیاد و مستمر، آپ‌مارکت. خیلی‌ها هر دو را دارند: سیستم برای روزمره، فریلنسر برای کمپین‌های خاص.",
  },
  {
    slug: "upmarket-vs-doing-it-yourself",
    icon: "🙋",
    other: "خودتان انجام دهید",
    title: "آپ‌مارکت یا خودم انجام بدهم؟",
    lead: "صادقانه: خیلی از فروشگاه‌ها به هیچ ابزاری نیاز ندارند.",
    metaDesc:
      "آیا برای تولید محتوای فروشگاهتان به ابزار نیاز دارید؟ مقایسه‌ی منصفانه با انجام دادن خودتان.",
    intro:
      "اگر چند محصول دارید و هفته‌ای دو پست می‌گذارید، هیچ ابزاری لازم ندارید. این صفحه برای کسی است که وقتش کم آمده، نه برای فروختن به کسی که مشکلی ندارد.",
    rows: [
      { aspect: "هزینه‌ی پولی", us: "اشتراک ماهانه", them: "صفر" },
      { aspect: "هزینه‌ی زمانی", us: "کم", them: "بالا، و همیشگی" },
      { aspect: "کیفیت عکس", us: "اصلاح خودکار", them: "به مهارت شما بستگی دارد" },
      { aspect: "جواب دادن به دایرکت", us: "خودکار", them: "خودتان، هر ساعت" },
      { aspect: "شناخت محصول", us: "از داده‌ای که وارد می‌کنید", them: "شما بهتر از هرکسی می‌دانید" },
    ],
    theirWins: [
      "شما محصولتان را از هر سیستمی بهتر می‌شناسید.",
      "هیچ هزینه‌ای ندارد.",
      "اگر تعداد محصول کم است، سریع‌تر هم هست.",
      "لحن شخصی خودتان، که مشتری‌های قدیمی به آن عادت کرده‌اند.",
    ],
    ourWins: [
      "وقتی تعداد محصول از چند ده تا رد می‌شود.",
      "وقتی دایرکت‌ها بی‌جواب می‌مانند.",
      "وقتی عکس‌ها با موبایل گرفته شده و حرفه‌ای به نظر نمی‌رسند.",
    ],
    verdict:
      "اگر وقت دارید و تعداد محصول کم است، خودتان انجام دهید — جدی می‌گوییم. وقتی وقت کم آمد، آن‌وقت برگردید.",
  },
];

const en: Comparison[] = [
  {
    slug: "upmarket-vs-marketing-agency",
    icon: "🏢",
    other: "a marketing agency",
    title: "UpMarket or a marketing agency?",
    lead: "Which makes sense for your shop — and when an agency is genuinely better.",
    metaDesc:
      "A fair comparison of UpMarket and a marketing agency: cost, speed, control, and who each one suits.",
    intro:
      "An agency means handing the work to people who do this professionally. For a business with budget that wants no involvement, that is the right call. This comparison is for someone still deciding.",
    rows: [
      { aspect: "Monthly cost", us: "A fixed subscription", them: "A contract, usually several times more" },
      { aspect: "Time to start", us: "Same day", them: "A meeting, a brief, a contract" },
      { aspect: "Content volume", us: "Capped by your plan", them: "Capped by the contract" },
      { aspect: "Understanding your business", us: "From the data you enter", them: "From conversation and human experience" },
      { aspect: "Unexpected creativity", us: "Limited", them: "Their strength" },
      { aspect: "Final control", us: "Everything waits for your approval", them: "Depends on the contract" },
    ],
    theirWins: [
      "Long-term brand strategy — which does not fall out of product data.",
      "Large multi-channel campaigns with a serious ad budget.",
      "The creative idea no template produces.",
      "When you want no involvement at all and can afford it.",
    ],
    ourWins: [
      "High volume day-to-day content, which agencies price steeply.",
      "Round-the-clock replies to customers — agencies rarely offer that.",
      "Starting without a contract or a meeting.",
      "Content built on your own real product photos.",
    ],
    verdict:
      "If your problem is “daily content volume and answering customers”, UpMarket. If your problem is “what should our brand say”, an agency.",
  },
  {
    slug: "upmarket-vs-freelancer",
    icon: "🧑‍💻",
    other: "a freelancer",
    title: "UpMarket or a freelancer?",
    lead: "One person who does the work, against a system that is always there.",
    metaDesc:
      "A fair comparison of UpMarket and hiring a freelancer for content: cost, consistency, quality and fit.",
    intro:
      "A good freelancer combines craft with human judgement that no tool replaces. But availability, consistency and cost all move with volume.",
    rows: [
      { aspect: "Cost", us: "Fixed and predictable", them: "Per piece of work" },
      { aspect: "Availability", us: "Always", them: "Their schedule" },
      { aspect: "Consistency", us: "Even", them: "High, but varies day to day" },
      { aspect: "Brand voice", us: "From the profile you set once", them: "Excellent after a few projects" },
      { aspect: "Them leaving", us: "Not a thing", them: "A real risk" },
      { aspect: "One-off creative work", us: "Weak", them: "Their strength" },
    ],
    theirWins: [
      "Work with no template — a special campaign, a different idea.",
      "Cultural nuance and humour, which models usually miss.",
      "Taking feedback and iterating to exactly the right result.",
      "When volume is low and each piece matters a lot.",
    ],
    ourWins: [
      "As volume rises, freelancer cost rises with it and a subscription does not.",
      "Customers get answered at midnight too.",
      "Continuity: nobody leaves and takes the brand knowledge with them.",
    ],
    verdict:
      "For small, special work, a freelancer. For high, continuous volume, UpMarket. Plenty of shops run both: the system for daily work, a freelancer for the campaigns that matter.",
  },
  {
    slug: "upmarket-vs-doing-it-yourself",
    icon: "🙋",
    other: "doing it yourself",
    title: "UpMarket or do it yourself?",
    lead: "Honestly: plenty of shops need no tool at all.",
    metaDesc:
      "Do you need a tool to make content for your shop? An honest comparison with doing it yourself.",
    intro:
      "If you have a handful of products and post twice a week, you need no tool. This page is for someone who has run out of time — not for selling to someone without a problem.",
    rows: [
      { aspect: "Money cost", us: "A monthly subscription", them: "Nothing" },
      { aspect: "Time cost", us: "Low", them: "High, and permanent" },
      { aspect: "Photo quality", us: "Corrected automatically", them: "Depends on your skill" },
      { aspect: "Answering DMs", us: "Automatic", them: "You, at every hour" },
      { aspect: "Product knowledge", us: "From the data you enter", them: "You know it better than anyone" },
    ],
    theirWins: [
      "You understand your product better than any system.",
      "It costs nothing.",
      "With few products it is faster too.",
      "Your own personal voice, which regulars are used to.",
    ],
    ourWins: [
      "Once the catalogue passes a few dozen products.",
      "Once DMs start going unanswered.",
      "Once phone photos stop looking professional enough.",
    ],
    verdict:
      "If you have the time and few products, do it yourself — we mean that. Come back when time runs short.",
  },
];

const COMPARISONS: Record<Locale, Comparison[]> = { fa, en };

export function comparisonsFor(locale: Locale): Comparison[] {
  return COMPARISONS[locale];
}

export function getComparison(slug: string, locale: Locale): Comparison | undefined {
  return COMPARISONS[locale].find((c) => c.slug === slug);
}

export const comparisonSlugs = fa.map((c) => c.slug);
