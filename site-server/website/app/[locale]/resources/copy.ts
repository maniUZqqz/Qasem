/** Wording for `/resources` and its four sections.
 *
 * Beside the page rather than inside it because Next.js allows only its own
 * named exports from a `page.tsx` — the section page imports these, and
 * exporting them from the index page fails the build.
 */
export const COPY = {
  fa: {
    eyebrow: "منابع",
    title: "راهنما، قالب و چک‌لیست — رایگان",
    lead: "چیزهایی که می‌توانی همین حالا برداری و استفاده کنی.",
    metaDesc:
      "راهنماها، قالب‌ها، چک‌لیست‌ها و کتاب‌های رایگان بازاریابی برای فروشگاه‌های آنلاین.",
    download: "دانلود",
    open: "خواندن",
    kinds: {
      guides: "راهنماها",
      templates: "قالب‌ها",
      checklists: "چک‌لیست‌ها",
      ebooks: "کتاب‌ها",
    } as Record<string, string>,
    ctaTitle: "ابزاری که خودش کار را انجام می‌دهد",
    ctaLead: "این‌ها کمکت می‌کنند خودت بنویسی. محصول اصلی خودش می‌نویسد.",
    seePricing: "دیدن قیمت‌ها",
  },
  en: {
    eyebrow: "Resources",
    title: "Guides, templates and checklists — free",
    lead: "Things you can take and use right now.",
    metaDesc:
      "Free marketing guides, templates, checklists and e-books for online shops.",
    download: "Download",
    open: "Read",
    kinds: {
      guides: "Guides",
      templates: "Templates",
      checklists: "Checklists",
      ebooks: "E-books",
    } as Record<string, string>,
    ctaTitle: "The tool that does the work",
    ctaLead: "These help you write it yourself. The product writes it for you.",
    seePricing: "See pricing",
  },
} as const;
