/**
 * Carries a referral / discount code from the link through to store creation.
 *
 * The server side of this was complete: `POST /stores/` already accepts `code`
 * and writes an attribution row, `/codes/check/` already validates one before
 * an account exists, and `Reward` already records what we owe. The panel never
 * collected a code, so none of it could ever fire — the whole referral loop
 * had a server, a database and tests, and no way in.
 *
 * Same shape as `pendingPlan` on purpose: `/register?ref=ALI-4821` survives
 * registration and is spent on the first store, because attribution hangs off
 * a *store* and a store does not exist until after signup.
 *
 * sessionStorage, not localStorage: a code belongs to the visit it arrived in.
 * Being credited to a referrer weeks later because a string sat in storage is
 * exactly the kind of surprise attribution should not produce.
 */
const KEY = "upmarket.pendingCode";

/** Codes are short and printable; anything else is someone editing the URL. */
const LOOKS_LIKE_CODE = /^[A-Za-z0-9_-]{2,40}$/;

/** Reads `?ref=` or `?code=` — marketing links have used both. */
export function readCodeFromUrl(search: string): string | null {
  const params = new URLSearchParams(search);
  const raw = params.get("ref") ?? params.get("code");
  if (!raw) return null;
  const code = raw.trim();
  return LOOKS_LIKE_CODE.test(code) ? code.toUpperCase() : null;
}

export function setPendingCode(code: string): void {
  try {
    sessionStorage.setItem(KEY, code);
  } catch {
    // Private mode. Losing the code is acceptable; failing signup is not.
  }
}

export function getPendingCode(): string | null {
  try {
    return sessionStorage.getItem(KEY);
  } catch {
    return null;
  }
}

export function clearPendingCode(): void {
  try {
    sessionStorage.removeItem(KEY);
  } catch {
    /* see setPendingCode */
  }
}
