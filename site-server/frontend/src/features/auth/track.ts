/**
 * Signup conversion, reported to the same first-party endpoint the public site
 * uses.
 *
 * The panel is a different origin from the marketing site, but the visitor's
 * session id lives in `sessionStorage`, which the browser scopes per origin —
 * so the id set on the website is not readable here. The link from the site
 * therefore carries it, and `adoptSessionFromUrl` picks it up. Without that,
 * a signup would start a brand-new session and the funnel would never join
 * "saw pricing" to "registered".
 */
// Same relative base the axios client uses, so the Vite proxy and any future
// deployment rewrite apply here too.
const EVENTS_URL = "/api/v1/events/";
const KEY = "upmarket.sid";

/** Take the session id the marketing site passed in `?s=`, if present. */
export function adoptSessionFromUrl(search: string): void {
  try {
    const sid = new URLSearchParams(search).get("s");
    if (sid && /^[A-Za-z0-9-]{8,40}$/.test(sid)) {
      sessionStorage.setItem(KEY, sid);
    }
  } catch {
    /* storage unavailable — the signup still works, we just lose the join */
  }
}

export function trackSignup(name: "signup_started" | "signup_completed"): void {
  let session = "";
  try {
    session = sessionStorage.getItem(KEY) || "";
  } catch {
    return;
  }
  if (!session) return; // no id means no funnel value; do not invent one

  const body = JSON.stringify({
    events: [
      {
        name,
        session,
        path: window.location.pathname,
        locale: "fa",
        referrer: document.referrer || "",
      },
    ],
  });

  try {
    const url = EVENTS_URL;
    if (navigator.sendBeacon) {
      navigator.sendBeacon(url, new Blob([body], { type: "application/json" }));
      return;
    }
    void fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body,
      keepalive: true,
    }).catch(() => {});
  } catch {
    /* analytics must never break signup */
  }
}
