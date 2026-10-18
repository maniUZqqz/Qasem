/**
 * Carries the plan a visitor picked on the public site through signup.
 *
 * The marketing site links to `/register?plan=pro`, but a subscription hangs
 * off a *store*, and a store does not exist until after registration. So the
 * choice has to survive two navigations. Before this existed the parameter was
 * simply dropped: someone clicked "حرفه‌ای" on the pricing page and landed on a
 * blank form with no memory of what they chose.
 *
 * sessionStorage, not localStorage: the intent belongs to this visit. Coming
 * back a week later and silently getting a plan you picked once would be
 * surprising in the wrong direction.
 */
const KEY = "upmarket.pendingPlan";

/** Slugs are short and known; anything else is someone playing with the URL. */
const LOOKS_LIKE_SLUG = /^[a-z0-9-]{1,32}$/;

export function readPlanFromUrl(search: string): string | null {
  const raw = new URLSearchParams(search).get("plan");
  if (!raw) return null;
  const slug = raw.trim().toLowerCase();
  return LOOKS_LIKE_SLUG.test(slug) ? slug : null;
}

export function setPendingPlan(slug: string): void {
  try {
    sessionStorage.setItem(KEY, slug);
  } catch {
    // Private mode, or storage disabled. The signup itself must still work,
    // so losing the plan is acceptable; failing the page is not.
  }
}

export function getPendingPlan(): string | null {
  try {
    return sessionStorage.getItem(KEY);
  } catch {
    return null;
  }
}

export function clearPendingPlan(): void {
  try {
    sessionStorage.removeItem(KEY);
  } catch {
    /* see setPendingPlan */
  }
}
