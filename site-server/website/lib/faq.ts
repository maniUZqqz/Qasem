/**
 * The FAQ, from the admin — with the shipped copy as the fallback.
 *
 * Grouped, because `سایت عمومی.md` §14 asks for sections (محصول، هوش مصنوعی،
 * قیمت، امنیت، فروش) and a flat list would have to guess them back from the
 * text. The fallback has no groups to guess with, so it renders as one
 * section — a page with every answer on it and no headings, rather than a page
 * with headings the backend never agreed to.
 *
 * The home page shows only the handful marked `on_home`: those are the
 * questions that decide whether somebody keeps reading, and they are picked in
 * the admin rather than by `slice(0, 4)` here.
 */
import { announce, ask } from "./api";
import { contentFor } from "./content";
import type { Locale } from "./i18n";

export type Question = { q: string; a: string };

export type FaqGroup = { key: string; label: string; items: Question[] };

type ApiFaq = {
  group: string;
  groupLabel: string;
  q: string;
  a: string;
  qEn: string;
  aEn: string;
  onHome: boolean;
};

const LABELS_EN: Record<string, string> = {
  PRODUCT: "Product",
  AI: "AI",
  PRICING: "Pricing",
  SECURITY: "Security",
  SALES: "Sales",
};

function localise(row: ApiFaq, locale: Locale): Question {
  const en = locale === "en";
  return { q: (en && row.qEn) || row.q, a: (en && row.aEn) || row.a };
}

async function rows(locale: Locale, homeOnly: boolean): Promise<ApiFaq[] | null> {
  const data = await ask<ApiFaq[]>(
    `/site/faq/${homeOnly ? "?home=1" : ""}`,
    300,
    "settings",
  );
  return data && data.length ? data : null;
}

/** Every published question, flat. Used for the FAQPage structured data, which
 *  has no notion of sections. */
export async function getFaq(locale: Locale): Promise<Question[]> {
  const data = await rows(locale, false);
  if (data) {
    announce("faq", true, `${data.length} questions`);
    return data.map((r) => localise(r, locale));
  }
  const local = contentFor(locale).faq;
  announce("faq", false, `${local.length} questions`);
  return local.map((f) => ({ q: f.q, a: f.a }));
}

/** The same questions, in the sections the FAQ page renders. */
export async function getFaqGroups(locale: Locale): Promise<FaqGroup[]> {
  const data = await rows(locale, false);
  if (!data) {
    // One unlabelled section: the fallback copy has no groups, and inventing
    // them here would put answers under headings nobody chose.
    return [{ key: "ALL", label: "", items: (await getFaq(locale)) }];
  }
  announce("faq", true, `${data.length} questions`);

  const out: FaqGroup[] = [];
  for (const row of data) {
    const label =
      locale === "en" ? LABELS_EN[row.group] ?? row.groupLabel : row.groupLabel;
    let group = out.find((g) => g.key === row.group);
    if (!group) {
      group = { key: row.group, label, items: [] };
      out.push(group);
    }
    group.items.push(localise(row, locale));
  }
  return out;
}

/** The few that belong on the home page, chosen in the admin. */
export async function getHomeFaq(locale: Locale): Promise<Question[]> {
  const data = await rows(locale, true);
  if (data) return data.map((r) => localise(r, locale));
  return contentFor(locale).faq.slice(0, 4).map((f) => ({ q: f.q, a: f.a }));
}
