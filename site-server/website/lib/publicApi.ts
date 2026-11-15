/**
 * URLs for code that runs in the VISITOR'S BROWSER (the contact form,
 * analytics).
 *
 * `NEXT_PUBLIC_*` values are inlined into the JavaScript sent to every visitor.
 * A loopback address there (http://127.0.0.1:8040) points at the visitor's OWN
 * computer: the contact form posted to nowhere and every lead was lost without
 * a single error on the server (0 leads were ever stored before this fix). So
 * the browser calls RELATIVE same-origin URLs (`/api/v1/leads/`) and the reverse
 * proxy in front of the site (nginx on :8040: `/api/` goes to Django, everything
 * else to this Next server) delivers them. Reaching the Next server directly on
 * :3001 bypasses that proxy and is not a supported way to use the forms; for
 * development, `.env.local` points NEXT_PUBLIC_API_BASE at the local Django.
 *
 * Set NEXT_PUBLIC_API_BASE only to a real PUBLIC origin of the API; leave it
 * empty otherwise. The server-side address is INTERNAL_API_BASE (lib/apiBase.ts).
 * `scripts/check-static-no-localhost.mjs` fails the build if a loopback address
 * ever reaches the browser bundle again.
 */
const PUBLIC_BASE = (process.env.NEXT_PUBLIC_API_BASE || "").trim().replace(/\/+$/, "");

export function publicApiUrl(path: string): string {
  return `${PUBLIC_BASE}${path.startsWith("/") ? path : `/${path}`}`;
}
