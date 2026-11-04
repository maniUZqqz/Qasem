import { g, problem } from "../../api";
import type { ExtractionJobDetail } from "../../types";

/** Queue a contact-extraction job for these leads. Throws a Persian message when the module is absent. */
export async function startExtraction(leadIds: number[], force = false): Promise<ExtractionJobDetail> {
  try {
    return await g.post<ExtractionJobDetail>("/extraction/jobs/", { lead_ids: leadIds, force });
  } catch (err) {
    const p = problem(err);
    if (p.status === 404) throw new Error("بخشِ استخراجِ اطلاعاتِ تماس در این نسخه هنوز فعال نیست.");
    throw new Error(p.message);
  }
}

/** The reason an extraction of a field was or was not applied. */
export const REASON_LABEL: Record<string, string> = {
  added: "اضافه شد",
  already_known: "از قبل داشتیم",
  fill_empty: "جای خالی پر شد",
  kept_existing: "مقدارِ فعلی نگه داشته شد",
  owned_by_other_lead: "مالِ لیدِ دیگری است",
  invalid: "نامعتبر بود",
};

export const FIELD_LABEL: Record<string, string> = {
  phone: "تلفن",
  email: "ایمیل",
  instagram: "اینستاگرام",
  telegram: "تلگرام",
  whatsapp: "واتساپ",
  eitaa: "ایتا",
  bale: "بله",
  rubika: "روبیکا",
  linkedin: "لینکدین",
  contact_form: "فرم تماس / تیکت",
  address: "نشانی",
  city: "شهر",
  business_name: "نام کسب‌وکار",
  description: "توضیحات",
  language: "زبان",
};

export const PAGE_KIND_LABEL: Record<string, string> = {
  home: "صفحهٔ اصلی",
  contact: "تماس با ما",
  about: "دربارهٔ ما",
  support: "پشتیبانی / تیکت",
  guess: "مسیرِ حدسی",
  robots: "robots.txt",
};

export const ROBOTS_LABEL: Record<string, string> = {
  ok: "robots.txt خوانده و رعایت شد",
  none: "سایت robots.txt ندارد",
  disallow_all: "robots.txt همه‌چیز را ممنوع کرده",
  unavailable: "robots.txt خوانده نشد؛ برای احتیاط رد شد",
  off: "—",
};
