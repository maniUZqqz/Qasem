/**
 * Prices come from the running backend, never from a constant in this repo.
 *
 * A price on the marketing page that the backend does not enforce is how a
 * customer ends up quoting a number nobody can honour — so the site reads
 * `/api/v1/plans/` and only falls back to a shipped snapshot when the API is
 * unreachable at build time (a preview deploy, an offline build).
 */
export type Plan = {
  id: number;
  slug: string;
  name: string;
  description: string;
  price_toman: number;
  video_seconds: number;
  images: number;
  captions: number;
  max_products: number;
  allows_publishing: boolean;
  allows_sales_agent: boolean;
  is_trial: boolean;
  trial_days: number;
  sort_order: number;
};

/** Mirrors دیتا/1-داده/data.json — used only when the API cannot be reached. */
const FALLBACK: Plan[] = [
  {
    id: -1, slug: "start", name: "استارت",
    description: "۱۵ ثانیه ویدیو · ۵ تصویر · ۵ کپشن در ماه",
    price_toman: 690000, video_seconds: 15, images: 5, captions: 5,
    max_products: 0, allows_publishing: true, allows_sales_agent: true,
    is_trial: false, trial_days: 0, sort_order: 1,
  },
  {
    id: -2, slug: "pro", name: "حرفه‌ای",
    description: "۴۵ ثانیه ویدیو · ۱۵ تصویر · ۱۵ کپشن در ماه",
    price_toman: 1490000, video_seconds: 45, images: 15, captions: 15,
    max_products: 0, allows_publishing: true, allows_sales_agent: true,
    is_trial: false, trial_days: 0, sort_order: 2,
  },
  {
    id: -3, slug: "unlimited", name: "بی‌نهایت",
    description: "۱۲۰ ثانیه ویدیو · ۴۰ تصویر · ۴۰ کپشن در ماه",
    price_toman: 3490000, video_seconds: 120, images: 40, captions: 40,
    max_products: 0, allows_publishing: true, allows_sales_agent: true,
    is_trial: false, trial_days: 0, sort_order: 3,
  },
];

export async function getPlans(): Promise<{ plans: Plan[]; live: boolean }> {
  const base = process.env.NEXT_PUBLIC_API_BASE || "http://127.0.0.1:8000";
  try {
    const res = await fetch(`${base}/api/v1/plans/`, {
      // Tagged so a price change in the Django admin reaches the pricing page
      // at once (app/api/revalidate/route.ts) instead of up to five minutes
      // later — pricing is the page where stale is most expensive.
      next: { revalidate: 300, tags: ["plans"] },
    });
    if (!res.ok) throw new Error(String(res.status));
    const plans = (await res.json()) as Plan[];
    if (!Array.isArray(plans) || plans.length === 0) throw new Error("empty");
    return { plans: plans.sort((a, b) => a.sort_order - b.sort_order), live: true };
  } catch {
    return { plans: FALLBACK, live: false };
  }
}

/** ۱۴۹۰۰۰۰ → «۱٬۴۹۰٬۰۰۰» */
export function toman(value: number): string {
  return value.toLocaleString("fa-IR").replace(/,/g, "٬");
}

export function fa(value: number | string): string {
  return String(value).replace(/[0-9]/g, (d) => "۰۱۲۳۴۵۶۷۸۹"[Number(d)]);
}

/** Locale-aware digits. Persian numerals read as noise to an English reader,
 *  and Latin digits look foreign in Persian copy — so the locale decides. */
export function num(value: number | string, locale: "fa" | "en"): string {
  return locale === "fa" ? fa(value) : String(value);
}

/** Locale-aware money. The unit word differs, so callers append their own. */
export function money(value: number, locale: "fa" | "en"): string {
  return locale === "fa"
    ? value.toLocaleString("fa-IR").replace(/,/g, "٬")
    : value.toLocaleString("en-US");
}
