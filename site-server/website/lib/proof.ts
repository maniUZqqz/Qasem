/**
 * Case studies, customers, testimonials and resources — §11, §12, §13, §19.
 *
 * These four pages have **no shipped fallback, on purpose.** Every other part
 * of the site keeps a copy in this repo so a dead backend still renders it.
 * Not these: a fallback here would be invented proof, and §34 is explicit —
 * «نمونه‌کار ساختگی را به‌عنوان مشتری واقعی نمایش نده».
 *
 * So the rule is inverted: **empty means the page does not exist.** No rows →
 * `notFound()`, and the sitemap and footer leave it out. A page that answers
 * 200 with a heading and nothing under it gets indexed once and then sits in
 * Google looking abandoned; §18 says the same thing about thin tag pages.
 *
 * That also means a build with the backend down drops these pages rather than
 * shipping them blank, which is the right failure: they carry no traffic yet,
 * and a missing page recovers on the next build while an indexed empty one
 * does not.
 */
import { ask } from "./api";

export type Quote = {
  quote: string;
  name: string;
  business: string;
  role: string;
  photo: string | null;
  outcome: string;
  caseStudy: string | null;
};

export type CaseStudy = {
  slug: string;
  title: string;
  lead: string;
  cover: string | null;
  customer: string;
  problem: string;
  before: string;
  solution: string;
  process: string;
  outputs: string;
  results: string;
  conclusion: string;
  testimonials: Quote[];
};

export type Customer = {
  slug: string;
  name: string;
  description: string;
  logo: string | null;
  website: string;
  industry: string;
  caseStudy: string | null;
};

export type Proof = {
  caseStudies: CaseStudy[];
  customers: Customer[];
  testimonials: Quote[];
};

const EMPTY: Proof = { caseStudies: [], customers: [], testimonials: [] };

export async function getProof(): Promise<Proof> {
  return (await ask<Proof>("/site/proof/", 300)) ?? EMPTY;
}

export async function getCaseStudy(slug: string): Promise<CaseStudy | undefined> {
  const name = decodeURIComponent(slug);
  return (await getProof()).caseStudies.find((c) => c.slug === name);
}

// ------------------------------------------------------------------ resources

export type Resource = {
  slug: string;
  kind: string;
  kindLabel: string;
  title: string;
  description: string;
  icon: string;
  file: string | null;
  body: string;
};

export type ResourceKind = { value: string; label: string };

/** The four sections §19 names, in the order it names them. Kept here rather
 *  than read from the API so an empty library still renders its own headings
 *  in a stable order once the first row lands. */
export const RESOURCE_KINDS = ["guides", "templates", "checklists", "ebooks"];

export async function getResources(
  kind?: string,
): Promise<{ resources: Resource[]; kinds: ResourceKind[] }> {
  const rows = await ask<{ resources: Resource[]; kinds: ResourceKind[] }>(
    `/site/resources/${kind ? `?kind=${kind}` : ""}`,
    300,
  );
  return rows ?? { resources: [], kinds: [] };
}
