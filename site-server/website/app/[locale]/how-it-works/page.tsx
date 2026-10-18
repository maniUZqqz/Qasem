import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";

import JsonLd from "@/components/JsonLd";
import SectionHead from "@/components/SectionHead";
import { contentFor } from "@/lib/content";
import { getSite } from "@/lib/site";
import { dict } from "@/lib/dict";
import { alternatesFor, isLocale, localePath, LOCALES, type Locale } from "@/lib/i18n";
import { breadcrumbs, howTo } from "@/lib/seo";

type Props = { params: Promise<{ locale: string }> };

export function generateStaticParams() {
  return LOCALES.map((locale) => ({ locale }));
}

const COPY = {
  fa: {
    eyebrow: "فرایند",
    title: "از ثبت محصول تا انتشار",
    lead: "یک‌بار تنظیم می‌کنید؛ بعد از آن فقط تأیید می‌کنید.",
    step: "قدم",
    end: "پایان",
    splitEyebrow: "تقسیم کار",
    splitTitle: "چه چیزی دست شماست، چه چیزی خودکار",
    splitLead: "هیچ تصمیم مهمی بدون شما گرفته نمی‌شود.",
    yours: "کاری که شما می‌کنید",
    system: "کاری که سیستم می‌کند",
    yoursItems: [
      "یک‌بار برند و لحن فروشگاه را ثبت می‌کنید",
      "محصول را با عکس واقعی اضافه می‌کنید",
      "خروجی را می‌بینید و تأیید یا رد می‌کنید",
      "پرداخت مشتری را تأیید می‌کنید",
    ],
    systemItems: [
      "عکس محصول را تحلیل می‌کند",
      "قیمت و موضع رقبا را از وب درمی‌آورد",
      "پوستر، ویدیو و کپشن می‌سازد",
      "به دایرکت مشتری پاسخ می‌دهد و سفارش ثبت می‌کند",
      "بعد از تأیید شما منتشر می‌کند",
    ],
    timeEyebrow: "زمان",
    timeTitle: "هر مرحله چقدر طول می‌کشد",
    timings: [
      { v: "چند دقیقه", l: "برای تحلیل محصول" },
      { v: "چند ثانیه", l: "برای هر کپشن" },
      { v: "در صف رندر", l: "برای هر تصویر" },
      { v: "در صف رندر", l: "برای ویدیو — پیشرفتش را زنده می‌بینید" },
    ],
    timeNote:
      "ویدیو سنگین‌ترین بخش است چون هر قطعه‌اش جداگانه رندر می‌شود و روی کارت گرافیک صف می‌بندد. لازم نیست منتظر بمانید — صفحه را ببندید و بعداً برگردید.",
    ctaTitle: "اولین بسته‌ی محتوا در همین جلسه",
    seeWork: "اول نمونه‌کارها را ببینم",
    metaDesc: "شش قدم از ثبت فروشگاه تا انتشار خودکار در اینستاگرام.",
  },
  en: {
    eyebrow: "The process",
    title: "From adding a product to publishing it",
    lead: "You set it up once; after that you only approve.",
    step: "Step",
    end: "Done",
    splitEyebrow: "Division of labour",
    splitTitle: "What stays yours, what runs itself",
    splitLead: "No decision that matters is made without you.",
    yours: "What you do",
    system: "What the system does",
    yoursItems: [
      "Set the brand and tone of voice, once",
      "Add products with real photos",
      "Look at the output and approve or reject it",
      "Confirm customer payments",
    ],
    systemItems: [
      "Reads your product photos",
      "Pulls competitor prices and positioning off the web",
      "Builds posters, video and captions",
      "Answers customer messages and records orders",
      "Publishes once you have approved",
    ],
    timeEyebrow: "Timing",
    timeTitle: "How long each stage takes",
    timings: [
      { v: "Minutes", l: "for product analysis" },
      { v: "Seconds", l: "per caption" },
      { v: "In the queue", l: "per image" },
      { v: "In the queue", l: "for video — progress shown live" },
    ],
    timeNote:
      "Video is the heavy part: each segment renders separately and queues on the GPU. You do not have to wait — close the tab and come back.",
    ctaTitle: "Your first content pack in this sitting",
    seeWork: "Show me the samples first",
    metaDesc: "Six steps, from adding your shop to publishing on Instagram.",
  },
} as const;

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { locale } = await params;
  if (!isLocale(locale)) return {};
  return {
    title: COPY[locale].title,
    description: COPY[locale].metaDesc,
    alternates: alternatesFor(locale, "/how-it-works"),
  };
}

export default async function HowItWorks({ params }: Props) {
  const { locale } = await params;
  if (!isLocale(locale)) notFound();
  const l = locale as Locale;
  const c = COPY[l];
  const { steps } = contentFor(l);
  const site = await getSite(l);
  const t = dict(l);

  const split = [
    { icon: "🙋", title: c.yours, items: c.yoursItems },
    { icon: "⚙️", title: c.system, items: c.systemItems },
  ];

  return (
    <>
      <JsonLd
        data={[breadcrumbs([{ name: c.title, path: "/how-it-works" }], l), howTo(steps)]}
      />

      <section className="mesh">
        <div className="wrap">
          <SectionHead as="h1" eyebrow={c.eyebrow} title={c.title} lead={c.lead} />
        </div>
      </section>

      <section style={{ paddingTop: 0 }}>
        <div className="wrap narrow">
          <div className="timeline">
            {steps.map((s, i) => (
              <div key={s.n} className={`tl-item reveal reveal-${(i % 3) + 1}`}>
                <div className="tl-dot">{s.icon}</div>
                <div className="tl-body">
                  <div className="row-tight">
                    <span className="eyebrow">
                      {c.step} {s.n}
                    </span>
                    {i === steps.length - 1 && <span className="muted">{c.end}</span>}
                  </div>
                  <h2 className="mt-sm" style={{ fontSize: "1.15rem" }}>
                    {s.title}
                  </h2>
                  <p className="mt-sm" style={{ color: "var(--text-2)", fontSize: ".95rem" }}>
                    {s.desc}
                  </p>
                  <p className="muted mt-sm">{s.detail}</p>
                </div>
              </div>
            ))}
          </div>
        </div>
      </section>

      <section className="section-soft">
        <div className="wrap">
          <SectionHead eyebrow={c.splitEyebrow} title={c.splitTitle} lead={c.splitLead} />
          <div className="grid g2 in-view-stagger mt-lg">
            {split.map((s) => (
              <article key={s.title} className="card">
                <div className="icon-lg">{s.icon}</div>
                <h3 className="mt-sm">{s.title}</h3>
                <ul className="checks mt">
                  {s.items.map((i) => (
                    <li key={i}>{i}</li>
                  ))}
                </ul>
              </article>
            ))}
          </div>
        </div>
      </section>

      {/* Timing used to promise "a few minutes" for video. Our own render
          figures put a full package at hours of GPU time, so that was a
          promise we would break on the first order. */}
      <section>
        <div className="wrap">
          <SectionHead eyebrow={c.timeEyebrow} title={c.timeTitle} />
          <div className="grid g4 in-view-stagger mt-lg">
            {c.timings.map((x) => (
              <div key={x.l} className="card stat">
                <div className="v gradient-text">{x.v}</div>
                <div className="l">{x.l}</div>
              </div>
            ))}
          </div>
          <p className="muted center mt-md narrow">{c.timeNote}</p>
        </div>
      </section>

      <section className="section-soft">
        <div className="wrap">
          <div className="cta-band">
            <h2>{c.ctaTitle}</h2>
            <p className="lead mt narrower">{t.cta.noCard}</p>
            <div className="row mt-md center-row">
              <a href={`${site.panelUrl}/register`} className="btn btn-primary">
                {t.cta.startFree}
              </a>
              <Link href={localePath(l, "/showcase")} className="btn btn-ghost">
                {c.seeWork}
              </Link>
            </div>
          </div>
        </div>
      </section>
    </>
  );
}
