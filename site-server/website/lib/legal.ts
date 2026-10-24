/**
 * Legal pages.
 *
 * ⚠️ These are an honest first draft written from what the product actually
 * does — not legal advice, and not reviewed by a lawyer. Every page carries a
 * visible review notice for exactly that reason. Before taking real payments,
 * a lawyer has to read these.
 *
 * The rule followed here: describe only behaviour that exists in the code
 * today. Where the product sends data outside our servers, say so plainly
 * rather than claiming a blanket "everything stays local" — because the code
 * shows edge-tts (Microsoft) handles narration and competitor research hits
 * third-party sites.
 */

import type { Locale } from "./i18n";

export type LegalDoc = {
  slug: string;
  title: string;
  description: string;
  updated: string;
  sections: { heading: string; body: string[] }[];
};

const UPDATED = "۱۴۰۵/۰۶/۲۱";

const fa: LegalDoc[] = [
  {
    slug: "privacy-policy",
    title: "سیاست حریم خصوصی",
    description: "چه داده‌ای جمع می‌کنیم، کجا پردازش می‌شود و چه کسی به آن دسترسی دارد.",
    updated: UPDATED,
    sections: [
      {
        heading: "چه داده‌ای جمع می‌کنیم",
        body: [
          "اطلاعات حساب: نام کاربری، ایمیل و رمز عبور (رمز به شکل درهم‌ریخته ذخیره می‌شود، نه خام).",
          "اطلاعات فروشگاه: نام برند، لحن، سیاست‌ها و اطلاعات پرداختی که خودتان وارد می‌کنید.",
          "کاتالوگ محصول: عنوان، قیمت، موجودی، مشخصات و عکس‌هایی که آپلود می‌کنید.",
          "محتوای تولیدشده: پوستر، عکس، ویدیو، کپشن و سناریوهایی که سیستم می‌سازد.",
          "گفتگوها: پیام‌های مشتریان شما با ایجنت فروش و سفارش‌های ثبت‌شده.",
        ],
      },
      {
        heading: "کجا پردازش می‌شود",
        body: [
          "بخش عمده‌ی پردازش روی سرورهای خودمان انجام می‌شود.",
          "دو استثنا که باید بدانید: نریشن ویدیو برای تبدیل متن به گفتار به سرویس مایکروسافت فرستاده می‌شود، و تحلیل رقبا به سایت‌های عمومی مثل دیجی‌کالا و ترب و موتور جستجو وصل می‌شود.",
          "اگر تنظیمات فروشگاه شما روی استفاده از سرویس هوش مصنوعی بیرونی باشد، متن ارسالی به آن سرویس می‌رود. این تنظیم در پنل، صفحه‌ی فروشگاه، قابل مشاهده و تغییر است و سه حالت دارد: «فقط لوکال»، «فقط سرویس‌های تأییدشده»، و «ترکیبی».",
          "در حالت «فقط لوکال» هیچ داده‌ای از سرور ما خارج نمی‌شود. یعنی اگر مدل محلی در دسترس نباشد، کار با پیام روشن متوقف می‌شود — به سرویس بیرونی نمی‌رود. صداگذاری هم در این حالت کار نمی‌کند، چون هنوز صدای فارسی لوکال نداریم.",
          "پیام‌های خصوصی مشتریان شما به‌طور پیش‌فرض به هیچ سرویس بیرونی فرستاده نمی‌شوند، حتی در حالت «ترکیبی». این کار فقط با اجازه‌ی صریح خود شما انجام می‌شود.",
        ],
      },
      {
        heading: "آمار بازدید",
        body: [
          "برای اینکه بدانیم کدام صفحه‌ها کار می‌کنند، بازدید صفحه و کلیک روی دکمه‌ها را ثبت می‌کنیم.",
          "این آمار روی سرور خودمان می‌ماند — نه گوگل آنالیتیکس و نه هیچ سرویس شخص ثالثی.",
          "چیزی که ذخیره می‌شود: نشانی صفحه، زبان، و یک شناسه‌ی تصادفیِ مخصوص همین بازدید که با بستن تب از بین می‌رود.",
          "چیزی که ذخیره نمی‌شود: کوکی ردیابی، اثر انگشت مرورگر، و هیچ چیزی که شما را بین بازدیدهای مختلف بشناسد.",
        ],
      },
      {
        heading: "چه کاری با داده نمی‌کنیم",
        body: [
          "داده‌ی شما را به کسی نمی‌فروشیم.",
          "کاتالوگ یا گفتگوهای شما را برای آموزش مدل در اختیار دیگران نمی‌گذاریم.",
          "به محتوای فروشگاه شما جز برای رفع اشکالی که خودتان گزارش کرده‌اید سر نمی‌زنیم.",
        ],
      },
      {
        heading: "نگه‌داری و حذف",
        body: [
          "تا وقتی حساب فعال است، داده نگه داشته می‌شود.",
          "با درخواست حذف حساب، داده‌ی فروشگاه و محتوای تولیدشده پاک می‌شود.",
          "نسخه‌های پشتیبان ممکن است تا مدتی پس از حذف باقی بمانند و بعد بازنویسی شوند.",
        ],
      },
      {
        heading: "حقوق شما",
        body: [
          "می‌توانید داده‌ی خود را ببینید، اصلاح کنید یا حذفش را بخواهید.",
          "برای هر کدام از این‌ها از صفحه‌ی تماس به ما پیام بدهید.",
        ],
      },
    ],
  },
  {
    slug: "terms",
    title: "شرایط استفاده",
    description: "قواعد استفاده از NMarketing، مسئولیت‌ها و محدودیت‌ها.",
    updated: UPDATED,
    sections: [
      {
        heading: "حساب کاربری",
        body: [
          "مسئولیت حفظ رمز عبور و فعالیت‌های انجام‌شده با حساب شما با خودتان است.",
          "اطلاعاتی که موقع ثبت‌نام می‌دهید باید درست باشد.",
        ],
      },
      {
        heading: "محتوای شما",
        body: [
          "عکس‌ها و اطلاعات محصولی که آپلود می‌کنید مال خودتان می‌ماند.",
          "با آپلود، به ما اجازه می‌دهید از آن‌ها برای ارائه‌ی سرویس استفاده کنیم — یعنی پردازش و تولید محتوا.",
          "باید حق استفاده از آنچه آپلود می‌کنید را داشته باشید.",
        ],
      },
      {
        heading: "محتوای تولیدشده",
        body: [
          "محتوایی که سیستم برای شما می‌سازد مال شماست و می‌توانید تجاری استفاده‌اش کنید.",
          "خروجی هوش مصنوعی ممکن است خطا داشته باشد. پیش از انتشار، بازبینی با شماست.",
          "هیچ محتوایی بدون تأیید شما منتشر نمی‌شود.",
        ],
      },
      {
        heading: "آنچه تضمین نمی‌کنیم",
        body: [
          "افزایش فروش یا نتیجه‌ی تبلیغاتی مشخص را تضمین نمی‌کنیم.",
          "در دسترس بودن دائمی سرویس را تضمین نمی‌کنیم؛ قطعی برای نگه‌داری یا خرابی ممکن است.",
          "دقت اطلاعات تحلیل رقبا به منابع عمومی وابسته است و ممکن است کهنه یا ناقص باشد.",
        ],
      },
      {
        heading: "پرداخت و اشتراک",
        body: [
          "قیمت‌ها در صفحه‌ی قیمت‌ها اعلام می‌شوند و از همان مرجعی خوانده می‌شوند که در محصول اعمال می‌شود.",
          "تغییر قیمت با اطلاع قبلی انجام می‌شود و روی دوره‌ی جاری اثر ندارد.",
        ],
      },
      {
        heading: "خاتمه",
        body: [
          "هر زمان می‌توانید حسابتان را ببندید.",
          "در صورت نقض «سیاست استفاده‌ی مجاز»، ممکن است دسترسی را محدود کنیم.",
        ],
      },
    ],
  },
  {
    slug: "refund-policy",
    title: "سیاست بازگشت وجه",
    description: "دوره‌ی آزمایشی، بازگشت اعتبار و شرایط لغو اشتراک.",
    updated: UPDATED,
    sections: [
      {
        heading: "دوره‌ی آزمایشی",
        body: [
          "دو هفته رایگان، بدون نیاز به کارت بانکی.",
          "اگر در این دوره نتیجه نگرفتید، هیچ مبلغی پرداخت نمی‌کنید.",
        ],
      },
      {
        heading: "وقتی تولید شکست می‌خورد",
        body: [
          "اگر یک تولید به‌خاطر خطای سیستم انجام نشود، سهمیه یا اعتبار آن برمی‌گردد.",
          "اگر کیفیت خروجی زیر آستانه‌ی کنترل کیفیت باشد، دوباره تولید می‌شود و بابتش هزینه‌ای کم نمی‌شود.",
          "این یعنی هزینه‌ی خطای ما را شما نمی‌پردازید.",
        ],
      },
      {
        heading: "لغو اشتراک",
        body: [
          "هر زمان می‌توانید لغو کنید.",
          "سرویس تا پایان دوره‌ای که بابتش پرداخت کرده‌اید فعال می‌ماند.",
        ],
      },
      {
        heading: "درخواست بازگشت وجه",
        body: [
          "اگر مشکلی پیش آمده که با موارد بالا حل نمی‌شود، از صفحه‌ی تماس به ما بگویید.",
          "هر درخواست جداگانه بررسی می‌شود.",
        ],
      },
    ],
  },
  {
    slug: "cookie-policy",
    title: "سیاست کوکی‌ها",
    description: "چه چیزی در مرورگر شما ذخیره می‌شود و چرا.",
    updated: UPDATED,
    sections: [
      {
        heading: "چه چیزی ذخیره می‌کنیم",
        body: [
          "انتخاب تم روشن یا تیره، تا دفعه‌ی بعد همان‌طور بماند.",
          "توکن ورود، تا با هر بار رفرش دوباره وارد نشوید.",
          "یک شناسه‌ی تصادفی برای همین بازدید، تا بفهمیم کدام صفحه‌ها به ثبت‌نام می‌رسند. این شناسه کوکی نیست، با بستن تب پاک می‌شود، و به هویت شما وصل نیست.",
        ],
      },
      {
        heading: "چه چیزی ذخیره نمی‌کنیم",
        body: [
          "کوکی تبلیغاتی شخص ثالث برای ردیابی شما در سایت‌های دیگر نمی‌گذاریم.",
        ],
      },
      {
        heading: "مدیریت",
        body: [
          "می‌توانید کوکی‌ها را از تنظیمات مرورگرتان پاک کنید.",
          "با پاک کردن توکن ورود، از حساب خارج می‌شوید.",
        ],
      },
    ],
  },
  {
    slug: "acceptable-use",
    title: "سیاست استفاده‌ی مجاز",
    description: "چه کارهایی با NMarketing نباید انجام شود.",
    updated: UPDATED,
    sections: [
      {
        heading: "آنچه مجاز نیست",
        body: [
          "ساخت محتوای گمراه‌کننده درباره‌ی محصولی که وجود ندارد یا مشخصاتش را ندارد.",
          "جا زدن خود به‌جای شخص یا برند دیگر.",
          "ساخت نظر یا رضایت مشتری جعلی.",
          "محتوای مجرمانه، توهین‌آمیز یا تحریک‌کننده.",
          "استفاده از عکس یا محتوایی که حق استفاده‌اش را ندارید.",
          "تلاش برای دور زدن محدودیت سهمیه یا اختلال در سرویس.",
        ],
      },
      {
        heading: "درباره‌ی ایجنت فروش",
        body: [
          "ایجنت قیمت و موجودی را فقط از کاتالوگ خودتان می‌گوید — عدد نمی‌سازد.",
          "تأیید دریافت وجه همیشه با انسان است و این قابل تغییر نیست.",
          "نباید ایجنت را طوری تنظیم کنید که اطلاعات نادرست به مشتری بدهد.",
        ],
      },
      {
        heading: "پیامد نقض",
        body: [
          "در صورت گزارش یا مشاهده‌ی نقض، ابتدا تذکر می‌دهیم.",
          "در موارد جدی یا تکراری، دسترسی محدود یا حساب بسته می‌شود.",
        ],
      },
    ],
  },
];

const en: LegalDoc[] = [
  {
    slug: "privacy-policy",
    title: "Privacy policy",
    description: "What we collect, where it is processed, and who can reach it.",
    updated: "2026-09-12",
    sections: [
      {
        heading: "What we collect",
        body: [
          "Account details: username, email and password (stored hashed, never in the clear).",
          "Shop details: brand name, tone of voice, policies and the payment information you enter.",
          "Product catalogue: titles, prices, stock, specifications and the photos you upload.",
          "Generated content: posters, images, video, captions and scripts the system produces.",
          "Conversations: messages between your customers and the sales agent, and the orders placed.",
        ],
      },
      {
        heading: "Where it is processed",
        body: [
          "Most processing runs on our own servers.",
          "Two exceptions you should know about: video narration is sent to Microsoft text-to-speech, and competitor analysis reads public sites such as Digikala and Torob plus a search engine.",
          "If your shop is configured to use an external AI service, the text sent for generation goes to that service. The setting is visible and changeable.",
        ],
      },
      {
        heading: "Visit statistics",
        body: [
          "To know which pages actually work, we record page views and clicks on buttons.",
          "These statistics stay on our own servers — not Google Analytics, and no third-party service.",
          "What is stored: the page address, the language, and a random id for this visit that disappears when you close the tab.",
          "What is not stored: tracking cookies, browser fingerprints, or anything that recognises you between visits.",
        ],
      },
      {
        heading: "What we do not do",
        body: [
          "We do not sell your data.",
          "We do not hand your catalogue or conversations to anyone for model training.",
          "We do not look at your content except to fix a problem you reported.",
        ],
      },
      {
        heading: "Retention and deletion",
        body: [
          "Data is kept while the account is active.",
          "On an account deletion request, shop data and generated content are removed.",
          "Backups may retain copies for a period after deletion before being overwritten.",
        ],
      },
      {
        heading: "Your rights",
        body: [
          "You can see your data, correct it, or ask for it to be deleted.",
          "For any of these, message us through the contact page.",
        ],
      },
    ],
  },
  {
    slug: "terms",
    title: "Terms of use",
    description: "The rules for using NMarketing, responsibilities and limits.",
    updated: "2026-09-12",
    sections: [
      {
        heading: "Your account",
        body: [
          "Keeping your password safe, and whatever is done with your account, is your responsibility.",
          "The information you give at sign-up must be accurate.",
        ],
      },
      {
        heading: "Your content",
        body: [
          "The photos and product information you upload stay yours.",
          "By uploading, you allow us to use them to provide the service: to process them and generate content.",
          "You must hold the rights to whatever you upload.",
        ],
      },
      {
        heading: "Generated content",
        body: [
          "Content the system makes for you is yours, and you may use it commercially.",
          "AI output can be wrong. Reviewing it before publishing is your call.",
          "Nothing is published without your approval.",
        ],
      },
      {
        heading: "What we do not guarantee",
        body: [
          "We do not guarantee increased sales or any particular advertising result.",
          "We do not guarantee uninterrupted availability; maintenance and faults happen.",
          "Competitor analysis depends on public sources and may be stale or incomplete.",
        ],
      },
      {
        heading: "Payment and subscription",
        body: [
          "Prices are shown on the pricing page and read from the same source the product enforces.",
          "Price changes are announced in advance and do not affect the current period.",
        ],
      },
      {
        heading: "Ending it",
        body: [
          "You can close your account at any time.",
          "If the acceptable use policy is broken, we may restrict access.",
        ],
      },
    ],
  },
  {
    slug: "refund-policy",
    title: "Refund policy",
    description: "The trial, returned credit, and how cancellation works.",
    updated: "2026-09-12",
    sections: [
      {
        heading: "The trial",
        body: [
          "Two weeks free, no card required.",
          "If those two weeks bring you nothing, you pay nothing.",
        ],
      },
      {
        heading: "When a generation fails",
        body: [
          "If a generation fails because of a system error, its quota or credit is returned.",
          "If output falls below the quality threshold it is regenerated, and you are not charged for the attempt.",
          "In short: you do not pay for our mistakes.",
        ],
      },
      {
        heading: "Cancelling",
        body: [
          "You can cancel at any time.",
          "The service stays active until the end of the period you already paid for.",
        ],
      },
      {
        heading: "Asking for a refund",
        body: [
          "If something went wrong that the above does not cover, tell us through the contact page.",
          "Each request is looked at individually.",
        ],
      },
    ],
  },
  {
    slug: "cookie-policy",
    title: "Cookie policy",
    description: "What gets stored in your browser, and why.",
    updated: "2026-09-12",
    sections: [
      {
        heading: "What we store",
        body: [
          "Your light or dark theme choice, so it is still there next time.",
          "Your login token, so a refresh does not sign you out.",
          "A random id for this visit, so we can see which pages lead to signups. It is not a cookie, it is gone when you close the tab, and it is not tied to your identity.",
        ],
      },
      {
        heading: "What we do not store",
        body: [
          "No third-party advertising cookies that follow you around other sites.",
        ],
      },
      {
        heading: "Managing it",
        body: [
          "You can clear cookies from your browser settings.",
          "Clearing the login token signs you out.",
        ],
      },
    ],
  },
  {
    slug: "acceptable-use",
    title: "Acceptable use policy",
    description: "What NMarketing must not be used for.",
    updated: "2026-09-12",
    sections: [
      {
        heading: "Not allowed",
        body: [
          "Creating misleading content about a product that does not exist or does not have the stated specification.",
          "Passing yourself off as another person or brand.",
          "Fabricating reviews or customer testimonials.",
          "Criminal, abusive or inciting content.",
          "Using photos or content you do not hold the rights to.",
          "Trying to bypass quota limits or disrupt the service.",
        ],
      },
      {
        heading: "About the sales agent",
        body: [
          "The agent reads price and stock only from your own catalogue; it does not invent numbers.",
          "Payment confirmation is always done by a person, and that cannot be changed.",
          "You must not configure the agent to give customers false information.",
        ],
      },
      {
        heading: "If the policy is broken",
        body: [
          "On a report, or on noticing it, we warn you first.",
          "For serious or repeated cases, access is restricted or the account is closed.",
        ],
      },
    ],
  },
];

const DOCS: Record<Locale, LegalDoc[]> = { fa, en };

export function legalDocsFor(locale: Locale): LegalDoc[] {
  return DOCS[locale];
}

export function getLegalDoc(slug: string, locale: Locale): LegalDoc | undefined {
  return DOCS[locale].find((d) => d.slug === slug);
}
