"use client";

import { useMemo, useState } from "react";

import type { Locale } from "@/lib/i18n";
import { track } from "@/lib/track";
import {
  generateBios,
  generateCalendar,
  generateCaption,
  type ToneKey,
} from "@/lib/tools/engine";

const T = {
  fa: {
    product: "محصول",
    productPh: "مثلاً کت اورسایز کرم",
    audience: "مخاطب",
    audiencePh: "مثلاً خانم‌های ۲۵ تا ۴۰",
    benefit: "چرا خوب است",
    benefitPh: "مثلاً پارچه‌ی ضخیم، تمام فصل",
    tone: "لحن",
    cta: "دعوت به اقدام",
    ctaPh: "سفارش از دایرکت",
    business: "نام کسب‌وکار",
    businessPh: "مثلاً بوتیک آوا",
    offer: "چه می‌فروشی",
    offerPh: "مثلاً پوشاک دست‌دوز",
    city: "شهر",
    cityPh: "مثلاً تهران",
    perWeek: "پست در هفته",
    weeks: "چند هفته",
    build: "بساز",
    copy: "کپی",
    copied: "کپی شد ✓",
    short: "کوتاه",
    medium: "متوسط",
    long: "بلند",
    hashtags: "هشتگ‌ها",
    bios: "سه نسخه",
    day: "روز",
    empty: "فیلدها را پر کن و «بساز» را بزن.",
    tones: [
      { k: "friendly", label: "دوستانه" },
      { k: "professional", label: "حرفه‌ای" },
      { k: "playful", label: "شوخ" },
      { k: "calm", label: "آرام" },
    ],
  },
  en: {
    product: "Product",
    productPh: "e.g. cream oversized coat",
    audience: "Audience",
    audiencePh: "e.g. women 25–40",
    benefit: "Why it is good",
    benefitPh: "e.g. heavy fabric, all season",
    tone: "Tone",
    cta: "Call to action",
    ctaPh: "DM to order",
    business: "Business name",
    businessPh: "e.g. Ava Boutique",
    offer: "What you sell",
    offerPh: "e.g. handmade clothing",
    city: "City",
    cityPh: "e.g. Tehran",
    perWeek: "Posts per week",
    weeks: "How many weeks",
    build: "Generate",
    copy: "Copy",
    copied: "Copied ✓",
    short: "Short",
    medium: "Medium",
    long: "Long",
    hashtags: "Hashtags",
    bios: "Three versions",
    day: "Day",
    empty: "Fill the fields and press Generate.",
    tones: [
      { k: "friendly", label: "Friendly" },
      { k: "professional", label: "Professional" },
      { k: "playful", label: "Playful" },
      { k: "calm", label: "Calm" },
    ],
  },
} as const;

type Labels = { copy: string; copied: string };

function CopyBox({ text, label, t }: { text: string; label: string; t: Labels }) {
  const [done, setDone] = useState(false);
  return (
    <div className="card mt-sm">
      <div className="row-tight" style={{ justifyContent: "space-between" }}>
        <span className="eyebrow">{label}</span>
        <button
          type="button"
          className="btn btn-ghost"
          style={{ padding: "4px 12px", fontSize: ".8rem" }}
          onClick={() => {
            navigator.clipboard?.writeText(text).then(
              () => {
                setDone(true);
                setTimeout(() => setDone(false), 1600);
              },
              () => {},
            );
          }}
        >
          {done ? t.copied : t.copy}
        </button>
      </div>
      <pre className="caption-box mt-sm" style={{ whiteSpace: "pre-wrap", margin: 0 }}>
        {text}
      </pre>
    </div>
  );
}

export default function ToolRunner({
  slug,
  locale,
}: {
  slug: string;
  locale: Locale;
}) {
  const t = T[locale];
  const [ran, setRan] = useState(false);
  const [f, setF] = useState({
    product: "",
    audience: "",
    benefit: "",
    tone: "friendly" as ToneKey,
    cta: "",
    business: "",
    offer: "",
    city: "",
    perWeek: 3,
    weeks: 4,
  });

  const set = (k: keyof typeof f) => (v: string | number) =>
    setF((prev) => ({ ...prev, [k]: v }));

  const result = useMemo(() => {
    if (!ran) return null;
    if (slug === "instagram-caption-generator") {
      return { kind: "caption" as const, data: generateCaption(f, locale) };
    }
    if (slug === "instagram-bio-generator") {
      return { kind: "bio" as const, data: generateBios(f, locale) };
    }
    return {
        kind: "calendar" as const,
        data: generateCalendar(
          { business: f.business, postsPerWeek: f.perWeek, weeks: f.weeks },
          locale,
        ),
      };
  }, [ran, slug, f, locale]);

  function run() {
    setRan(true);
    // Which tool people actually use is the whole point of the channel.
    track("tool_used", { tool: slug }, locale);
  }

  return (
    <div>
      <div className="card">
        {slug === "instagram-caption-generator" && (
          <div className="grid g2">
            <Field label={t.product} ph={t.productPh} v={f.product} on={set("product")} />
            <Field label={t.audience} ph={t.audiencePh} v={f.audience} on={set("audience")} />
            <Field label={t.benefit} ph={t.benefitPh} v={f.benefit} on={set("benefit")} />
            <label className="stack-sm">
              <span>{t.tone}</span>
              <select
                value={f.tone}
                onChange={(e) => set("tone")(e.target.value)}
              >
                {t.tones.map((o) => (
                  <option key={o.k} value={o.k}>
                    {o.label}
                  </option>
                ))}
              </select>
            </label>
            <Field label={t.cta} ph={t.ctaPh} v={f.cta} on={set("cta")} />
          </div>
        )}

        {slug === "instagram-bio-generator" && (
          <div className="grid g2">
            <Field label={t.business} ph={t.businessPh} v={f.business} on={set("business")} />
            <Field label={t.offer} ph={t.offerPh} v={f.offer} on={set("offer")} />
            <Field label={t.city} ph={t.cityPh} v={f.city} on={set("city")} />
            <Field label={t.cta} ph={t.ctaPh} v={f.cta} on={set("cta")} />
          </div>
        )}

        {slug === "content-calendar-generator" && (
          <div className="grid g3">
            <Field label={t.business} ph={t.businessPh} v={f.business} on={set("business")} />
            <label className="stack-sm">
              <span>{t.perWeek}</span>
              <input
                type="number"
                min={1}
                max={7}
                value={f.perWeek}
                onChange={(e) => set("perWeek")(Number(e.target.value))}
              />
            </label>
            <label className="stack-sm">
              <span>{t.weeks}</span>
              <input
                type="number"
                min={1}
                max={8}
                value={f.weeks}
                onChange={(e) => set("weeks")(Number(e.target.value))}
              />
            </label>
          </div>
        )}

        <button type="button" className="btn btn-primary mt-sm" onClick={run}>
          {t.build}
        </button>
      </div>

      {!result && <p className="muted center mt-md">{t.empty}</p>}

      {result?.kind === "caption" && (
        <div className="mt-md">
          <CopyBox text={result.data.short} label={t.short} t={t} />
          <CopyBox text={result.data.medium} label={t.medium} t={t} />
          <CopyBox text={result.data.long} label={t.long} t={t} />
          <CopyBox text={result.data.hashtags.join(" ")} label={t.hashtags} t={t} />
        </div>
      )}

      {result?.kind === "bio" && (
        <div className="mt-md">
          {result.data.map((b, i) => (
            <CopyBox key={i} text={b} label={`${t.bios} ${i + 1}`} t={t} />
          ))}
        </div>
      )}

      {result?.kind === "calendar" && (
        <div className="mt-md">
          <CopyBox
            text={result.data
              .map((d) => `${t.day} ${d.day} — ${d.type}: ${d.idea}`)
              .join("\n")}
            label={t.build}
            t={t}
          />
          <div className="grid g3 mt-sm">
            {result.data.map((d, i) => (
              <div key={i} className="card">
                <span className="eyebrow">
                  {t.day} {d.day}
                </span>
                <h4 className="mt-sm">{d.type}</h4>
                <p className="muted mt-sm">{d.idea}</p>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function Field({
  label,
  ph,
  v,
  on,
}: {
  label: string;
  ph: string;
  v: string;
  on: (s: string) => void;
}) {
  return (
    <label className="stack-sm">
      <span>{label}</span>
      <input value={v} placeholder={ph} onChange={(e) => on(e.target.value)} />
    </label>
  );
}
