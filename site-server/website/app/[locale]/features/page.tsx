import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";

import JsonLd from "@/components/JsonLd";
import SectionHead from "@/components/SectionHead";
import { contentFor } from "@/lib/content";
import { getSite } from "@/lib/site";
import { getFeaturePages } from "@/lib/seoPages";
import { dict } from "@/lib/dict";
import { alternatesFor, isLocale, localePath, LOCALES, type Locale } from "@/lib/i18n";
import { breadcrumbs } from "@/lib/seo";

type Props = { params: Promise<{ locale: string }> };

export function generateStaticParams() {
  return LOCALES.map((locale) => ({ locale }));
}

/** Engineering decisions worth stating on a marketing page, because each one
 *  answers a doubt a careful buyer already has. */
const COPY = {
  fa: {
    eyebrow: "قابلیت‌ها",
    title: "کاری که آپ‌مارکت انجام می‌دهد",
    lead: "نه چند ابزار جدا — یک جریان که از محصول شما شروع می‌شود و به فروش می‌رسد.",
    deepEyebrow: "جزئیات هر قابلیت",
    deepTitle: "هرکدام را جداگانه ببینید",
    deepLead: "برای هر قابلیت یک صفحه‌ی مستقل هست: مشکل، کاری که می‌کند، و چطور.",
    gEyebrow: "تصمیم‌های مهندسی",
    gTitle: "چیزهایی که عمداً این‌طور ساخته شده‌اند",
    gLead: "هرکدام جواب یک نگرانی واقعی است، نه یک ویژگی تبلیغاتی.",
    ctaTitle: "امتحانش رایگان است",
    ctaLead: "دو هفته، بدون کارت بانکی.",
    seePricing: "دیدن قیمت‌ها",
    metaDesc:
      "هوش محصول، تحلیل رقبا، استودیوی تصویر و ویدیو، موتور کپشن و پشتیبان فروش — همه در یک جریان.",
    guarantees: [
      {
        icon: "🖼️",
        title: "از عکس واقعی، نه از صفر",
        desc: "پوستر روی عکس خود محصول ساخته می‌شود. مشتری همان چیزی را می‌بیند که می‌خرد.",
      },
      {
        icon: "🔤",
        title: "متن فارسی با کد، نه با مدل",
        desc: "حروف فارسی روی تصویر با کد نوشته می‌شوند تا هرگز به‌هم نریزند.",
      },
      {
        icon: "🔢",
        title: "عدد ساخته نمی‌شود",
        desc: "قیمت، موجودی و اطلاعات پرداخت فقط از دیتابیس خودتان خوانده می‌شود.",
      },
      {
        icon: "🔗",
        title: "ویدیوی پیوسته",
        desc: "هر قطعه از فریم آخر قبلی شروع می‌شود؛ نتیجه یک ویدیو است نه اسلایدشو.",
      },
      {
        icon: "🔁",
        title: "خطا کل کار را خراب نمی‌کند",
        desc: "اگر قطعه‌ای شکست بخورد فقط همان دوباره ساخته می‌شود و سهمیه‌اش برمی‌گردد.",
      },
      {
        icon: "👤",
        title: "انسان تصمیم می‌گیرد",
        desc: "انتشار و تأیید پرداخت هرگز خودکار نیست.",
      },
    ],
  },
  en: {
    eyebrow: "Features",
    title: "What UpMarket actually does",
    lead: "Not a set of separate tools — one flow that starts at your product and ends at a sale.",
    deepEyebrow: "Feature detail",
    deepTitle: "Look at each one on its own",
    deepLead: "Every capability has its own page: the problem, what it does, and how.",
    gEyebrow: "Engineering decisions",
    gTitle: "Things built this way on purpose",
    gLead: "Each one answers a real doubt, not a marketing checkbox.",
    ctaTitle: "Trying it costs nothing",
    ctaLead: "Two weeks, no card required.",
    seePricing: "See pricing",
    metaDesc:
      "Product intelligence, competitor analysis, image and video studio, caption engine and a sales assistant — in one flow.",
    guarantees: [
      {
        icon: "🖼️",
        title: "From the real photo, not from nothing",
        desc: "The poster is built on your own product photo. The buyer sees what they are buying.",
      },
      {
        icon: "🔤",
        title: "Text placed in code, not by the model",
        desc: "Persian letters are rendered in code so they never break apart on the image.",
      },
      {
        icon: "🔢",
        title: "No invented numbers",
        desc: "Price, stock and payment details are read only from your own database.",
      },
      {
        icon: "🔗",
        title: "One continuous video",
        desc: "Each segment starts from the last frame of the one before — a video, not a slideshow.",
      },
      {
        icon: "🔁",
        title: "One failure does not ruin the job",
        desc: "If a segment fails, only that segment is rebuilt and its quota comes back.",
      },
      {
        icon: "👤",
        title: "A person decides",
        desc: "Publishing and payment confirmation are never automatic.",
      },
    ],
  },
} as const;

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { locale } = await params;
  if (!isLocale(locale)) return {};
  return {
    title: COPY[locale].eyebrow,
    description: COPY[locale].metaDesc,
    alternates: alternatesFor(locale, "/features"),
  };
}

export default async function Features({ params }: Props) {
  const { locale } = await params;
  if (!isLocale(locale)) notFound();
  const l = locale as Locale;
  const featurePages = await getFeaturePages(l);
  const c = COPY[l];
  const { capabilities, features } = contentFor(l);
  const site = await getSite(l);
  const t = dict(l);

  return (
    <>
      <JsonLd data={breadcrumbs([{ name: c.eyebrow, path: "/features" }], l)} />

      <section className="mesh">
        <div className="wrap">
          <SectionHead as="h1" eyebrow={c.eyebrow} title={c.title} lead={c.lead} />
          <div className="band-grid mt-lg">
            {capabilities.map((x) => (
              <div key={x.label} className="band-item">
                <div className="v gradient-text">{x.value}</div>
                <div className="l">{x.label}</div>
              </div>
            ))}
          </div>
        </div>
      </section>

      {features.map((f, index) => (
        <section
          key={f.id}
          id={f.id}
          className={index % 2 ? "section-soft" : ""}
          style={{ paddingBlock: "clamp(32px, 5vw, 64px)" }}
        >
          <div className="wrap">
            <div className="grid g2 in-view-stagger">
              <div className={index % 2 ? "" : "reveal"}>
                <div className="icon-xl">{f.icon}</div>
                <h2 className="mt">{f.title}</h2>
                <p className="lead mt-sm">{f.lead}</p>
              </div>
              <div className="card">
                <ul className="checks">
                  {f.bullets.map((b) => (
                    <li key={b}>{b}</li>
                  ))}
                </ul>
              </div>
            </div>
          </div>
        </section>
      ))}

      {/* Deep-dive pages. The overview answers "what does it do"; these answer
          "does it do this one thing, and how" — and they are what ranks. */}
      <section>
        <div className="wrap">
          <SectionHead eyebrow={c.deepEyebrow} title={c.deepTitle} lead={c.deepLead} />
          <div className="grid g3 in-view-stagger mt-lg">
            {featurePages.map((fp) => (
              <Link
                key={fp.slug}
                href={localePath(l, `/features/${fp.slug}`)}
                className="card card-hover glow-edge plain"
              >
                <div className="icon-lg">{fp.icon}</div>
                <h3 className="mt-sm">{fp.title}</h3>
                <p className="muted mt-sm">{fp.lead}</p>
              </Link>
            ))}
          </div>
        </div>
      </section>

      <section className="section-soft">
        <div className="wrap">
          <SectionHead eyebrow={c.gEyebrow} title={c.gTitle} lead={c.gLead} />
          <div className="grid g3 in-view-stagger mt-lg">
            {c.guarantees.map((g) => (
              <article key={g.title} className="card">
                <div className="icon-lg">{g.icon}</div>
                <h3 className="mt-sm">{g.title}</h3>
                <p className="muted mt-sm">{g.desc}</p>
              </article>
            ))}
          </div>
        </div>
      </section>

      <section>
        <div className="wrap">
          <div className="cta-band">
            <h2>{c.ctaTitle}</h2>
            <p className="lead mt narrower">{c.ctaLead}</p>
            <div className="row mt-md center-row">
              <a href={`${site.panelUrl}/register`} className="btn btn-primary">
                {t.cta.startFree}
              </a>
              <Link href={localePath(l, "/pricing")} className="btn btn-ghost">
                {c.seePricing}
              </Link>
            </div>
          </div>
        </div>
      </section>
    </>
  );
}
