/**
 * Free tool engines.
 *
 * These run entirely in the visitor's browser. No model call, no server round
 * trip, no signup.
 *
 * That is a deliberate economic choice, not a shortcut. GPU time is this
 * product's binding constraint — the whole capacity model turns on it — and
 * the text models cost money per call. Handing anonymous strangers unlimited
 * generation would burn the exact resource the paid product sells, and would
 * be trivially abusable.
 *
 * So the tools are honest about what they are: structure, proven patterns and
 * good defaults, applied to what the visitor types. That is genuinely useful —
 * most people are stuck on *shape*, not on wording. The paid product is what
 * reads their actual product photo and their actual catalogue, and the tool
 * pages say exactly that rather than implying the free tool is the product.
 *
 * Rule for anything added here: it must produce output a person would actually
 * post. A tool that emits obvious filler is worse than no tool.
 */
import type { Locale } from "../i18n";

export type ToneKey = "friendly" | "professional" | "playful" | "calm";

/* ------------------------------------------------------------------ shared */

function pick<T>(list: readonly T[], seed: number): T {
  // Math.abs, because a signed shift on a large seed goes negative, and a
  // negative modulo indexes past the start of the array -> undefined.
  return list[Math.abs(seed) % list.length];
}

/** Small deterministic hash so the same input gives the same output — a
 *  generator that changes on every keystroke feels broken. */
function seedOf(text: string): number {
  let h = 0;
  for (let i = 0; i < text.length; i++) h = (h * 31 + text.charCodeAt(i)) >>> 0;
  return h;
}

function clean(s: string): string {
  return s.trim().replace(/\s+/g, " ");
}

/* ------------------------------------------------- 1. caption generator */

export type CaptionInput = {
  product: string;
  audience: string;
  benefit: string;
  tone: ToneKey;
  cta: string;
};

export type CaptionOutput = {
  short: string;
  medium: string;
  long: string;
  hashtags: string[];
};

const HOOKS: Record<Locale, Record<ToneKey, readonly string[]>> = {
  fa: {
    friendly: ["اینو ببین 👇", "یه چیز خوب برات داریم", "دنبال این نبودی؟"],
    professional: ["یک انتخاب درست", "چیزی که کم داشتید", "کیفیتی که می‌ماند"],
    playful: ["خب، اینو چی میگی؟ 😍", "ما که عاشقشیم", "بگو ببینم، کدومو برمی‌داری؟"],
    calm: ["ساده، ولی درست", "بدون شلوغی", "همین کافی است"],
  },
  en: {
    friendly: ["Take a look 👇", "We've got something for you", "Been looking for this?"],
    professional: ["A considered choice", "The piece you were missing", "Quality that lasts"],
    playful: ["Okay but how good is this 😍", "We're obsessed", "Which one are you taking?"],
    calm: ["Simple, and right", "No noise", "This is enough"],
  },
};

const BRIDGES: Record<Locale, readonly string[]> = {
  fa: ["برای", "مناسب", "ساخته شده برای"],
  en: ["For", "Made for", "Built for"],
};

export function generateCaption(input: CaptionInput, locale: Locale): CaptionOutput {
  const product = clean(input.product) || (locale === "fa" ? "محصول شما" : "your product");
  const audience = clean(input.audience);
  const benefit = clean(input.benefit);
  const cta = clean(input.cta) || (locale === "fa" ? "سفارش از دایرکت" : "DM to order");
  const seed = seedOf(product + audience + benefit + input.tone);

  const hook = pick(HOOKS[locale][input.tone], seed);
  const bridge = pick(BRIDGES[locale], seed >> 3);

  const forWho = audience ? `${bridge} ${audience}` : "";
  const because = benefit ? benefit : "";

  if (locale === "fa") {
    const short = [hook, product, cta].filter(Boolean).join(" · ");
    const medium = [
      hook,
      `${product}${forWho ? ` — ${forWho}` : ""}.`,
      because && `${because}.`,
      `${cta} 📩`,
    ]
      .filter(Boolean)
      .join("\n");
    const long = [
      hook,
      "",
      `${product}${forWho ? ` — ${forWho}` : ""}.`,
      because && `${because}`,
      "",
      "چرا این یکی:",
      benefit ? `• ${benefit}` : "• کیفیتی که سر قیمت کوتاه نمی‌آید",
      audience ? `• دقیقاً برای ${audience}` : "• انتخابی که پشیمانی ندارد",
      "• ارسال به سراسر ایران",
      "",
      `${cta} 📩`,
    ]
      // keep the "" spacers; only drop false/undefined
      .filter((l): l is string => typeof l === "string")
      .join("\n");
    return { short, medium, long, hashtags: hashtagsFor(product, audience, "fa") };
  }

  const short = [hook, product, cta].filter(Boolean).join(" · ");
  const medium = [
    hook,
    `${product}${forWho ? ` — ${forWho.toLowerCase()}` : ""}.`,
    because && `${because}.`,
    `${cta} 📩`,
  ]
    .filter(Boolean)
    .join("\n");
  const long = [
    hook,
    "",
    `${product}${forWho ? ` — ${forWho.toLowerCase()}` : ""}.`,
    because && `${because}`,
    "",
    "Why this one:",
    benefit ? `• ${benefit}` : "• Quality that does not cut corners on price",
    audience ? `• Made exactly for ${audience}` : "• A choice you will not regret",
    "• Shipping nationwide",
    "",
    `${cta} 📩`,
  ]
    // keep the "" spacers; only drop false/undefined
    .filter((l): l is string => typeof l === "string")
    .join("\n");
  return { short, medium, long, hashtags: hashtagsFor(product, audience, "en") };
}

function hashtagsFor(product: string, audience: string, locale: Locale): string[] {
  const base =
    locale === "fa"
      ? ["#فروشگاه_آنلاین", "#خرید_اینترنتی", "#ارسال_به_سراسر_ایران"]
      : ["#onlineshop", "#smallbusiness", "#shopnow"];
  const fromWords = [product, audience]
    .join(" ")
    .split(/[\s،,]+/)
    .filter((w) => w.length > 2)
    .slice(0, 4)
    .map((w) => "#" + w.replace(/[^\p{L}\p{N}_]/gu, ""));
  return [...new Set([...fromWords, ...base])].filter((h) => h.length > 2).slice(0, 8);
}

/* ----------------------------------------------------- 2. bio generator */

export type BioInput = {
  business: string;
  offer: string;
  city: string;
  cta: string;
};

export function generateBios(input: BioInput, locale: Locale): string[] {
  const business = clean(input.business) || (locale === "fa" ? "کسب‌وکار شما" : "Your business");
  const offer = clean(input.offer);
  const city = clean(input.city);
  const cta = clean(input.cta) || (locale === "fa" ? "سفارش از دایرکت" : "DM to order");

  if (locale === "fa") {
    return [
      [business, offer && `✨ ${offer}`, city && `📍 ${city}`, `📩 ${cta}`]
        .filter(Boolean)
        .join("\n"),
      [`${business} | ${offer || "کیفیت، بدون شعار"}`, city && `📍 ${city}`, `👇 ${cta}`]
        .filter(Boolean)
        .join("\n"),
      [offer || business, `${business}${city ? ` · ${city}` : ""}`, `📩 ${cta}`]
        .filter(Boolean)
        .join("\n"),
    ];
  }
  return [
    [business, offer && `✨ ${offer}`, city && `📍 ${city}`, `📩 ${cta}`].filter(Boolean).join("\n"),
    [`${business} | ${offer || "Quality, no slogans"}`, city && `📍 ${city}`, `👇 ${cta}`]
      .filter(Boolean)
      .join("\n"),
    [offer || business, `${business}${city ? ` · ${city}` : ""}`, `📩 ${cta}`]
      .filter(Boolean)
      .join("\n"),
  ];
}

/* ------------------------------------------- 3. content calendar planner */

export type CalendarInput = {
  business: string;
  postsPerWeek: number;
  weeks: number;
};

export type CalendarDay = { day: number; type: string; idea: string };

type PostType = { type: string; idea: string };

const POST_TYPES: Record<Locale, readonly PostType[]> = {
  fa: [
    { type: "معرفی محصول", idea: "یک محصول را کامل نشان بده — عکس واقعی، قیمت، سایزبندی." },
    { type: "پشت صحنه", idea: "چطور آماده می‌شود، بسته‌بندی، یا یک روز کاری." },
    { type: "نظر مشتری", idea: "اسکرین‌شات یک پیام واقعی (با اجازه‌ی خودش)." },
    { type: "آموزشی", idea: "یک نکته‌ی کاربردی درباره‌ی دسته‌ی محصولت." },
    { type: "مقایسه", idea: "دو گزینه کنار هم — کدام برای چه کسی." },
    { type: "پرسش", idea: "یک سؤال ساده بپرس که جواب دادنش راحت باشد." },
    { type: "پیشنهاد ویژه", idea: "یک پیشنهاد با مهلت مشخص." },
  ],
  en: [
    { type: "Product feature", idea: "Show one product properly — real photo, price, sizes." },
    { type: "Behind the scenes", idea: "How it is made, packed, or a day in the shop." },
    { type: "Customer voice", idea: "A screenshot of a real message (with their permission)." },
    { type: "Educational", idea: "One practical tip about your product category." },
    { type: "Comparison", idea: "Two options side by side — which suits whom." },
    { type: "Question", idea: "Ask something simple that is easy to answer." },
    { type: "Offer", idea: "One offer with a clear deadline." },
  ],
};

export function generateCalendar(input: CalendarInput, locale: Locale): CalendarDay[] {
  const perWeek = Math.min(Math.max(input.postsPerWeek || 3, 1), 7);
  const weeks = Math.min(Math.max(input.weeks || 4, 1), 8);
  const types = POST_TYPES[locale];
  const seed = seedOf(clean(input.business));

  const out: CalendarDay[] = [];
  // Spread posts across the week rather than clumping them at the start —
  // a calendar that says "post 5 times on Saturday" is not a calendar.
  const step = Math.floor(7 / perWeek);
  for (let w = 0; w < weeks; w++) {
    for (let i = 0; i < perWeek; i++) {
      const n = out.length;
      out.push({
        day: w * 7 + i * step + 1,
        ...pick(types, seed + n * 3),
      });
    }
  }
  return out;
}
