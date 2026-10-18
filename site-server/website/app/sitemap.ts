import type { MetadataRoute } from "next";

import { getCategories, getPosts, getTags } from "@/lib/blog";
import { sitemapPages } from "@/lib/content";
import { DEFAULT_LOCALE, LOCALES, localePath, type Locale } from "@/lib/i18n";
import { toolSlugs } from "@/lib/tools/meta";
import { legalDocsFor } from "@/lib/legal";
import { SITE_URL } from "@/lib/seo";
import { getProof, getResources, RESOURCE_KINDS } from "@/lib/proof";
import {
  allComparisonSlugs,
  allFeatureSlugs,
  allSolutionSlugs,
  allUseCaseSlugs,
} from "@/lib/seoPages";

/**
 * Priorities reflect what actually earns traffic: the home page and pricing
 * convert, solution and use-case pages catch intent, articles bring people in,
 * legal pages just need to exist.
 *
 * This reads `sitemapPages` rather than the header nav on purpose — a
 * navigation tweak should never silently drop pages out of Google.
 *
 * Blog posts are listed once, under Persian only. They are written in Persian
 * and have no English counterpart; advertising `/en/blog/<persian-slug>` would
 * point Google at a page that does not exist.
 */
export default async function sitemap(): Promise<MetadataRoute.Sitemap> {
  const now = new Date();

  // Includes pages that exist only in the admin. A page Google cannot find is
  // a page nobody wrote — which is the whole point of being able to add one
  // without a deploy.
  const [solutionSlugs, useCaseSlugs, featureSlugs, comparisonSlugs] =
    await Promise.all([
      allSolutionSlugs(),
      allUseCaseSlugs(),
      allFeatureSlugs(),
      allComparisonSlugs(),
    ]);

  // §11–§13 and §19. These 404 while they are empty, so listing them
  // unconditionally would put four guaranteed 404s in the sitemap — which is
  // the one file Google reads as a promise that the URLs exist.
  const [{ caseStudies, customers, testimonials }, { resources }] =
    await Promise.all([getProof(), getResources()]);
  const filledKinds = RESOURCE_KINDS.filter((k) =>
    resources.some((r) => r.kind === k),
  );

  const entry = (
    locale: Locale,
    path: string,
    priority: number,
    changeFrequency: "weekly" | "monthly" | "yearly" = "monthly",
  ) => ({
    url: `${SITE_URL}${localePath(locale, path)}`,
    lastModified: now,
    changeFrequency,
    priority,
  });

  const perLocale = LOCALES.flatMap((locale) => [
    entry(locale, "/", 1, "weekly"),

    ...sitemapPages.map((path) =>
      entry(
        locale,
        path,
        path === "/pricing" ? 0.9 : 0.7,
        path === "/blog" ? "weekly" : "monthly",
      ),
    ),

    // Intent-capturing pages — the reason the SEO architecture exists.
    ...solutionSlugs.map((slug) => entry(locale, `/solutions/${slug}`, 0.8)),
    ...useCaseSlugs.map((slug) => entry(locale, `/use-cases/${slug}`, 0.8)),
    ...featureSlugs.map((slug) => entry(locale, `/features/${slug}`, 0.8)),
    // Free tools are an acquisition channel, so they rank as high as the
    // intent pages; comparisons catch late, high-value decision searches.
    ...toolSlugs.map((slug) => entry(locale, `/tools/${slug}`, 0.8)),
    ...comparisonSlugs.map((slug) => entry(locale, `/compare/${slug}`, 0.7)),

    // Proof pages convert better than they rank, so they sit just under the
    // intent pages rather than with the legal ones.
    ...(caseStudies.length ? [entry(locale, "/case-studies", 0.75)] : []),
    ...caseStudies.map((s2) =>
      entry(locale, `/case-studies/${encodeURIComponent(s2.slug)}`, 0.7),
    ),
    ...(customers.length ? [entry(locale, "/customers", 0.5)] : []),
    ...(testimonials.length ? [entry(locale, "/testimonials", 0.5)] : []),
    ...(resources.length ? [entry(locale, "/resources", 0.7)] : []),
    ...filledKinds.map((kind) => entry(locale, `/resources/${kind}`, 0.6)),

    ...legalDocsFor(locale).map((d) => entry(locale, `/${d.slug}`, 0.3, "yearly")),
  ]);

  const articles = [
    // Encoded like the tag and category entries below it. The sitemap spec
    // wants percent-encoded URLs, and an article slug is Persian.
    ...(await getPosts()).map((p) =>
      entry(DEFAULT_LOCALE, `/blog/${encodeURIComponent(p.slug)}`, 0.6),
    ),
    ...(await getTags()).map((tag) =>
      entry(DEFAULT_LOCALE, `/blog/tag/${encodeURIComponent(tag)}`, 0.5, "weekly"),
    ),
    // Categories rank above tags: one broad shelf per post, so these are the
    // pages with enough on them to be worth landing on.
    ...(await getCategories()).map(({ name }) =>
      entry(
        DEFAULT_LOCALE,
        `/blog/category/${encodeURIComponent(name)}`,
        0.55,
        "weekly",
      ),
    ),
  ];

  return [...perLocale, ...articles];
}
