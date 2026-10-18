/**
 * Solutions, use cases, feature pages and comparisons — from the admin,
 * merged over the ones that ship in this repo.
 *
 * `سایت عمومی.md` §2 wants an architecture that reaches «۱۰۰ تا ۵۰۰+ صفحه»
 * without the front-end changing, and §34 forbids the shortcut that usually
 * follows: no near-identical pages spun up per keyword. Those two together
 * mean pages have to be **written**, and writing them cannot require a deploy.
 *
 * So each of the four `*For(locale)` helpers here does the same thing:
 *
 *   1. Start from the typed list in this repo.
 *   2. Ask the backend for rows of that kind.
 *   3. A row whose slug matches replaces that page; a row whose slug is new
 *      becomes a new page.
 *
 * **Replacing is field by field, and an empty field means "keep what shipped".**
 * Somebody who opens the admin to fix one sentence on the clothing page must
 * not blank the other eleven fields by not filling them in — which is exactly
 * what a whole-row replace would do.
 *
 * A dead backend leaves every shipped page exactly as it is.
 */
import { announce, ask } from "./api";
import { comparisonsFor, type Comparison } from "./compare";
import { featurePagesFor, type FeaturePage } from "./featurePages";
import type { Locale } from "./i18n";
import { solutionsFor, type Solution } from "./solutions";
import { useCasesFor, type UseCase } from "./useCases";

type Kind = "SOLUTION" | "USE_CASE" | "FEATURE" | "COMPARE";

type ApiPage = {
  kind: Kind;
  slug: string;
  locale: string;
  icon: string;
  title: string;
  lead: string;
  metaDescription: string;
  intro: string;
  problem: string;
  benefit: string;
  verdict: string;
  effort: string;
  example: { before: string; after: string } | null;
  bullets: Record<string, string[]>;
  steps: { title: string; desc: string; soon: boolean }[];
  rows: { aspect: string; us: string; them: string }[];
};

/** Empty means "not filled in", never "make it empty". */
function pick<T>(remote: T | undefined | null, local: T): T {
  if (remote === undefined || remote === null) return local;
  if (typeof remote === "string" && !remote.trim()) return local;
  if (Array.isArray(remote) && remote.length === 0) return local;
  return remote;
}

async function rowsOf(kind: Kind, locale: Locale): Promise<ApiPage[]> {
  const rows = await ask<ApiPage[]>(
    `/site/pages/?kind=${kind.toLowerCase()}&locale=${locale}`,
    300,
  );
  announce(`pages:${kind.toLowerCase()}`, Boolean(rows), `${rows?.length ?? 0} rows`);
  return rows ?? [];
}

/**
 * Merge rows over a shipped list, by slug.
 *
 * `blank` builds the skeleton for a page the repo has never seen, so a new row
 * is a whole page rather than a partial one that renders with holes in it.
 */
function merge<T extends { slug: string }>(
  shipped: T[],
  rows: ApiPage[],
  apply: (row: ApiPage, base: T) => T,
  blank: (row: ApiPage) => T,
): T[] {
  const out = [...shipped];
  for (const row of rows) {
    const at = out.findIndex((p) => p.slug === row.slug);
    if (at >= 0) out[at] = apply(row, out[at]);
    else out.push(apply(row, blank(row)));
  }
  return out;
}

// ------------------------------------------------------------------ solutions

export async function getSolutions(locale: Locale): Promise<Solution[]> {
  const rows = await rowsOf("SOLUTION", locale);
  if (!rows.length) return solutionsFor(locale);

  return merge<Solution>(
    solutionsFor(locale),
    rows,
    (row, base) => ({
      ...base,
      name: pick(row.title, base.name),
      tagline: pick(row.lead, base.tagline),
      icon: pick(row.icon, base.icon),
      problem: pick(row.bullets.PROBLEM, base.problem),
      answer: pick(
        row.steps.map((s) => ({ title: s.title, desc: s.desc })),
        base.answer,
      ),
      features: pick(row.bullets.FEATURES, base.features),
      example: pick(row.example, base.example),
      workflow: pick(row.bullets.WORKFLOW, base.workflow),
    }),
    (row) => ({
      slug: row.slug,
      name: row.title,
      tagline: row.lead,
      icon: row.icon || "🏷️",
      problem: [],
      answer: [],
      features: [],
      example: { before: "", after: "" },
      workflow: [],
    }),
  );
}

export async function getSolution(
  slug: string,
  locale: Locale,
): Promise<Solution | undefined> {
  return (await getSolutions(locale)).find((s) => s.slug === slug);
}

// ------------------------------------------------------------------ use cases

export async function getUseCases(locale: Locale): Promise<UseCase[]> {
  const rows = await rowsOf("USE_CASE", locale);
  if (!rows.length) return useCasesFor(locale);

  return merge<UseCase>(
    useCasesFor(locale),
    rows,
    (row, base) => ({
      ...base,
      title: pick(row.title, base.title),
      goal: pick(row.lead, base.goal),
      icon: pick(row.icon, base.icon),
      pain: pick(row.problem, base.pain),
      steps: pick(row.steps, base.steps),
      output: pick(row.bullets.OUTPUT, base.output),
      effort: pick(row.effort, base.effort),
    }),
    (row) => ({
      slug: row.slug,
      title: row.title,
      goal: row.lead,
      icon: row.icon || "🎯",
      pain: row.problem,
      steps: [],
      output: [],
      effort: row.effort,
    }),
  );
}

export async function getUseCase(
  slug: string,
  locale: Locale,
): Promise<UseCase | undefined> {
  return (await getUseCases(locale)).find((u) => u.slug === slug);
}

// --------------------------------------------------------------- feature pages

export async function getFeaturePages(locale: Locale): Promise<FeaturePage[]> {
  const rows = await rowsOf("FEATURE", locale);
  if (!rows.length) return featurePagesFor(locale);

  return merge<FeaturePage>(
    featurePagesFor(locale),
    rows,
    (row, base) => ({
      ...base,
      title: pick(row.title, base.title),
      lead: pick(row.lead, base.lead),
      icon: pick(row.icon, base.icon),
      problem: pick(row.problem, base.problem),
      does: pick(row.bullets.DOES, base.does),
      how: pick(
        row.steps.map((s) => ({ title: s.title, desc: s.desc })),
        base.how,
      ),
      example: pick(row.example, base.example),
      benefit: pick(row.benefit, base.benefit),
      planned: pick(row.bullets.PLANNED, base.planned),
    }),
    (row) => ({
      slug: row.slug,
      icon: row.icon || "✨",
      title: row.title,
      lead: row.lead,
      problem: row.problem,
      does: [],
      how: [],
      example: { before: "", after: "" },
      benefit: row.benefit,
      related: [],
    }),
  );
}

export async function getFeaturePage(
  slug: string,
  locale: Locale,
): Promise<FeaturePage | undefined> {
  return (await getFeaturePages(locale)).find((f) => f.slug === slug);
}

// -------------------------------------------------------------- comparisons

export async function getComparisons(locale: Locale): Promise<Comparison[]> {
  const rows = await rowsOf("COMPARE", locale);
  if (!rows.length) return comparisonsFor(locale);

  return merge<Comparison>(
    comparisonsFor(locale),
    rows,
    (row, base) => ({
      ...base,
      title: pick(row.title, base.title),
      lead: pick(row.lead, base.lead),
      icon: pick(row.icon, base.icon),
      metaDesc: pick(row.metaDescription, base.metaDesc),
      intro: pick(row.intro, base.intro),
      rows: pick(row.rows, base.rows),
      ourWins: pick(row.bullets.OUR_WINS, base.ourWins),
      theirWins: pick(row.bullets.THEIR_WINS, base.theirWins),
      verdict: pick(row.verdict, base.verdict),
    }),
    (row) => ({
      slug: row.slug,
      icon: row.icon || "⚖️",
      other: row.title,
      title: row.title,
      lead: row.lead,
      metaDesc: row.metaDescription,
      intro: row.intro,
      rows: [],
      theirWins: [],
      ourWins: [],
      verdict: row.verdict,
    }),
  );
}

export async function getComparison(
  slug: string,
  locale: Locale,
): Promise<Comparison | undefined> {
  return (await getComparisons(locale)).find((c) => c.slug === slug);
}

// ----------------------------------------------------------------- slugs
//
// `generateStaticParams` and the sitemap need the full slug list, including
// pages that only exist in the admin. Built from the Persian list — the two
// languages are the same pages, and a page that exists in one language only is
// a hreflang bug, not a feature.

export async function allSolutionSlugs(): Promise<string[]> {
  return (await getSolutions("fa")).map((s) => s.slug);
}

export async function allUseCaseSlugs(): Promise<string[]> {
  return (await getUseCases("fa")).map((u) => u.slug);
}

export async function allFeatureSlugs(): Promise<string[]> {
  return (await getFeaturePages("fa")).map((f) => f.slug);
}

export async function allComparisonSlugs(): Promise<string[]> {
  return (await getComparisons("fa")).map((c) => c.slug);
}
