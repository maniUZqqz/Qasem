/**
 * The site's name, tagline, contact details and keywords — from the admin.
 *
 * These used to be a constant in `lib/content.ts`, which made "change the
 * email address in the footer" a code edit, a build and a deploy, on a string
 * that appears on every page of the site.
 *
 * `lib/content.ts` keeps the same values as the fallback, and this merges the
 * backend's over them **field by field**: an admin who filled in a phone number
 * but left the Instagram link empty gets their phone number and the shipped
 * Instagram link, not a footer with half of it missing.
 *
 * `siteFor()` still exists and is still synchronous, for the places that
 * genuinely cannot await: the header (a client component, handed the name as a
 * prop), and the static routes Next builds outside a request — `manifest.ts`,
 * `feed.xml`, and the Open Graph image generators.
 */
import { announce, ask } from "./api";
import { siteFor } from "./content";
import type { Locale } from "./i18n";

export type Site = ReturnType<typeof siteFor>;

type ApiSettings = {
  name: string;
  nameEn: string;
  tagline: string;
  taglineEn: string;
  oneLiner: string;
  oneLinerEn: string;
  email: string;
  phone: string;
  instagram: string;
  telegram: string;
  address: string;
  keywords: string[];
  keywordsEn: string[];
};

/** Empty means "not filled in", and an unfilled field must not blank the page. */
function pick(remote: string | undefined, local: string): string {
  const value = (remote ?? "").trim();
  return value || local;
}

export async function getSite(locale: Locale): Promise<Site> {
  const local = siteFor(locale);
  const row = await ask<ApiSettings>("/site/settings/", 300, "settings");
  if (!row) {
    announce("site", false, "name, tagline, contact");
    return local;
  }
  announce("site", true, "name, tagline, contact");

  const en = locale === "en";
  const keywords = en ? row.keywordsEn : row.keywords;

  return {
    ...local,
    name: pick(en ? row.nameEn : row.name, local.name),
    nameEn: pick(row.nameEn, local.nameEn),
    tagline: pick(en ? row.taglineEn : row.tagline, local.tagline),
    oneLiner: pick(en ? row.oneLinerEn : row.oneLiner, local.oneLiner),
    email: pick(row.email, local.email),
    instagram: pick(row.instagram, local.instagram),
    keywords: keywords?.length ? keywords : local.keywords,
  };
}
