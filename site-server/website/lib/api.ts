/**
 * One way to ask the backend, so every caller times out the same way.
 *
 * `lib/blog.ts` and `lib/plans.ts` each grew their own copy of this, with
 * different timeouts and different revalidate windows — which meant a slow
 * backend produced a site that was partly fresh and partly a month old, and
 * nothing in the build log said which parts.
 *
 * The rule everywhere: **a dead backend falls back to what is in the repo, it
 * never fails the build.** The public site is SEO surface. Shipping a page
 * with last week's FAQ beats shipping a page with no FAQ, and beats a red
 * build that ships nothing at all.
 */
const BASE = process.env.NEXT_PUBLIC_API_BASE || "http://127.0.0.1:8000";

/** Long enough to ride out a cold first query, short enough that a build does
 *  not hang on a sick backend. */
const TIMEOUT_MS = 8000;

/**
 * @param tag  names this data so Django can expire it the instant it changes
 *   (app/api/revalidate/route.ts). Without a tag the only way back is to wait
 *   out `revalidate`, which is what made an admin edit look like it had been
 *   ignored. The time window stays as the backstop.
 */
export async function ask<T>(
  pathname: string,
  revalidate = 120,
  tag?: string,
): Promise<T | null> {
  try {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), TIMEOUT_MS);
    const res = await fetch(`${BASE}/api/v1${pathname}`, {
      next: { revalidate, ...(tag ? { tags: [tag] } : {}) },
      signal: controller.signal,
    });
    clearTimeout(timer);
    if (!res.ok) return null;
    return (await res.json()) as T;
  } catch {
    return null;
  }
}

/** Said once per build per subject, not once per page that asks. */
const said = new Set<string>();

export function announce(subject: string, live: boolean, detail: string) {
  if (said.has(subject)) return;
  said.add(subject);
  if (live) {
    console.log(`[${subject}] ${detail} — from the API`);
  } else {
    console.warn(
      `[${subject}] backend unreachable — using the copy in this repo (${detail}). ` +
        `Edits made in the Django admin are NOT in this build.`,
    );
  }
}
