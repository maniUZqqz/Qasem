/**
 * The address the Next.js SERVER uses to reach Django (pricing, blog, version,
 * the `/api/*` rewrite in next.config.mjs). Server-side only: never import this
 * from a "use client" file. See lib/publicApi.ts for the browser's side and for
 * why the two must not be mixed up.
 *
 * It runs on the same machine as Django, so a loopback address such as
 * http://127.0.0.1:8040 is exactly right here. `INTERNAL_API_BASE` wins;
 * `NEXT_PUBLIC_API_BASE` is the older name that still works as a fallback.
 */
export function internalApiBase(): string {
  const value = (process.env.INTERNAL_API_BASE || process.env.NEXT_PUBLIC_API_BASE || "")
    .trim()
    .replace(/\/+$/, "");
  return value || "http://127.0.0.1:8000";
}
