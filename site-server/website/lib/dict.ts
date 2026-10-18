/**
 * UI strings — the words that are not page content.
 *
 * Navigation, buttons, labels, the footer. Page *content* lives with its own
 * data (solutions.ts, useCases.ts, legal.ts) because a solution page is not a
 * string table; it is an article with a shape.
 *
 * The English here is written, not translated word-for-word. "دو هفته رایگان،
 * بدون کارت بانکی" becomes "Two weeks free — no card required", not "Two weeks
 * free, without a bank card", because the second is what a machine produces and
 * the first is what a person would actually write on a button.
 */
import type { Locale } from "./i18n";

type Dict = {
  nav: { href: string; label: string }[];
  footer: { title: string; links: { href: string; label: string }[] }[];
  legal: { href: string; label: string }[];
  cta: {
    primary: string;
    free: string;
    seeWork: string;
    features: string;
    contact: string;
    startFree: string;
    noCard: string;
  };
  common: {
    skipToContent: string;
    home: string;
    rights: string;
    themeToggle: string;
    languageToggle: string;
    soon: string;
    back: string;
    readMore: string;
  };
};

const fa: Dict = {
  nav: [
    { href: "/features", label: "قابلیت‌ها" },
    { href: "/solutions", label: "راه‌حل‌ها" },
    { href: "/use-cases", label: "کاربردها" },
    { href: "/showcase", label: "نمونه‌کار" },
    { href: "/pricing", label: "قیمت‌ها" },
    { href: "/blog", label: "وبلاگ" },
  ],
  footer: [
    {
      title: "محصول",
      links: [
        { href: "/features", label: "قابلیت‌ها" },
        { href: "/solutions", label: "راه‌حل‌ها" },
        { href: "/use-cases", label: "کاربردها" },
        { href: "/how-it-works", label: "چطور کار می‌کند" },
        { href: "/pricing", label: "قیمت‌ها" },
        { href: "/compare", label: "مقایسه" },
      ],
    },
    {
      title: "منابع",
      links: [
        { href: "/showcase", label: "نمونه‌کار" },
        { href: "/tools", label: "ابزار رایگان" },
        { href: "/blog", label: "وبلاگ" },
        { href: "/faq", label: "سؤالات متداول" },
      ],
    },
    {
      title: "شرکت",
      links: [
        { href: "/about", label: "درباره ما" },
        { href: "/contact", label: "تماس" },
      ],
    },
  ],
  legal: [
    { href: "/privacy-policy", label: "حریم خصوصی" },
    { href: "/terms", label: "شرایط استفاده" },
    { href: "/refund-policy", label: "بازگشت وجه" },
    { href: "/cookie-policy", label: "کوکی‌ها" },
    { href: "/acceptable-use", label: "استفاده‌ی مجاز" },
  ],
  cta: {
    primary: "شروع کنید",
    free: "دو هفته رایگان",
    seeWork: "نمونه‌کار را ببینید",
    features: "قابلیت‌ها",
    contact: "تماس با ما",
    startFree: "شروع رایگان",
    noCard: "دو هفته رایگان، بدون کارت بانکی.",
  },
  common: {
    skipToContent: "پرش به محتوا",
    home: "خانه",
    rights: "همه حقوق محفوظ است.",
    themeToggle: "تغییر تم",
    languageToggle: "تغییر زبان",
    soon: "به‌زودی",
    back: "بازگشت",
    readMore: "بیشتر بخوانید",
  },
};

const en: Dict = {
  nav: [
    { href: "/features", label: "Features" },
    { href: "/solutions", label: "Solutions" },
    { href: "/use-cases", label: "Use cases" },
    { href: "/showcase", label: "Showcase" },
    { href: "/pricing", label: "Pricing" },
    { href: "/blog", label: "Blog" },
  ],
  footer: [
    {
      title: "Product",
      links: [
        { href: "/features", label: "Features" },
        { href: "/solutions", label: "Solutions" },
        { href: "/use-cases", label: "Use cases" },
        { href: "/how-it-works", label: "How it works" },
        { href: "/pricing", label: "Pricing" },
        { href: "/compare", label: "Compare" },
      ],
    },
    {
      title: "Resources",
      links: [
        { href: "/showcase", label: "Showcase" },
        { href: "/tools", label: "Free tools" },
        { href: "/blog", label: "Blog" },
        { href: "/faq", label: "FAQ" },
      ],
    },
    {
      title: "Company",
      links: [
        { href: "/about", label: "About" },
        { href: "/contact", label: "Contact" },
      ],
    },
  ],
  legal: [
    { href: "/privacy-policy", label: "Privacy" },
    { href: "/terms", label: "Terms" },
    { href: "/refund-policy", label: "Refunds" },
    { href: "/cookie-policy", label: "Cookies" },
    { href: "/acceptable-use", label: "Acceptable use" },
  ],
  cta: {
    primary: "Get started",
    free: "Two weeks free",
    seeWork: "See real output",
    features: "Features",
    contact: "Contact us",
    startFree: "Start free",
    noCard: "Two weeks free — no card required.",
  },
  common: {
    skipToContent: "Skip to content",
    home: "Home",
    rights: "All rights reserved.",
    themeToggle: "Toggle theme",
    languageToggle: "Change language",
    soon: "Coming soon",
    back: "Back",
    readMore: "Read more",
  },
};

const DICTS: Record<Locale, Dict> = { fa, en };

export function dict(locale: Locale): Dict {
  return DICTS[locale];
}
