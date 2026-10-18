/**
 * First-party analytics client.
 *
 * Design constraints, taken from what the site publicly promises:
 *   - no cookie (the cookie policy says we set no tracking cookie)
 *   - no third-party script (the privacy page says processing is ours)
 *   - nothing that identifies a person across visits
 *
 * So: a random id in `sessionStorage`, gone when the tab closes. Enough to
 * stitch one visit into a funnel, useless for following anybody.
 *
 * Events are buffered and flushed on a timer or when the page is hidden, so a
 * visit costs a couple of requests rather than one per click. Everything is
 * best-effort — analytics must never be why a visitor sees an error, so every
 * failure path is a silent no-op.
 */
const API_BASE = process.env.NEXT_PUBLIC_API_BASE || "http://127.0.0.1:8000";
const KEY = "upmarket.sid";
const FLUSH_MS = 3000;
const MAX_BUFFER = 20;

export type EventName =
  | "page_view"
  | "cta_click"
  | "pricing_view"
  | "plan_selected"
  | "contact_submitted"
  | "signup_started"
  | "signup_completed"
  | "tool_used";

type Payload = {
  name: EventName;
  session: string;
  path: string;
  locale: string;
  referrer: string;
  utm: Record<string, string>;
  props: Record<string, string>;
};

let buffer: Payload[] = [];
let timer: ReturnType<typeof setTimeout> | null = null;

function sessionId(): string {
  if (typeof window === "undefined") return "";
  try {
    let id = sessionStorage.getItem(KEY);
    if (!id) {
      id =
        typeof crypto !== "undefined" && "randomUUID" in crypto
          ? crypto.randomUUID()
          : `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`;
      sessionStorage.setItem(KEY, id);
    }
    return id;
  } catch {
    // Private mode or storage disabled. Without an id the event is useless,
    // so we simply do not record it — rather than inventing a new id per
    // event, which would inflate every session count.
    return "";
  }
}

/**
 * Campaign parameters, remembered for the visit.
 *
 * They only appear on the landing URL, but the signup that matters happens
 * three pages later — so the first sighting is stored for the session.
 */
function utm(): Record<string, string> {
  if (typeof window === "undefined") return {};
  const STORE = "upmarket.utm";
  try {
    const q = new URLSearchParams(window.location.search);
    const fresh: Record<string, string> = {};
    for (const key of ["source", "medium", "campaign", "term", "content"]) {
      const v = q.get(`utm_${key}`);
      if (v) fresh[key] = v;
    }
    if (Object.keys(fresh).length > 0) {
      sessionStorage.setItem(STORE, JSON.stringify(fresh));
      return fresh;
    }
    return JSON.parse(sessionStorage.getItem(STORE) || "{}");
  } catch {
    return {};
  }
}

function send(rows: Payload[]): void {
  if (rows.length === 0) return;
  const body = JSON.stringify({ events: rows });
  const url = `${API_BASE}/api/v1/events/`;

  try {
    // sendBeacon survives the page being closed, which is exactly when the
    // last and most interesting events fire. fetch would be cancelled.
    if (typeof navigator !== "undefined" && navigator.sendBeacon) {
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
    /* never surface */
  }
}

/** The current visit's id, for handing to the panel on a cross-origin link. */
export function currentSessionId(): string {
  return sessionId();
}

export function flush(): void {
  if (timer) {
    clearTimeout(timer);
    timer = null;
  }
  const rows = buffer;
  buffer = [];
  send(rows);
}

export function track(
  name: EventName,
  props: Record<string, string> = {},
  locale = "",
): void {
  if (typeof window === "undefined") return;
  const session = sessionId();
  if (!session) return;

  buffer.push({
    name,
    session,
    path: window.location.pathname,
    locale,
    referrer: document.referrer || "",
    utm: utm(),
    props,
  });

  if (buffer.length >= MAX_BUFFER) {
    flush();
    return;
  }
  if (!timer) timer = setTimeout(flush, FLUSH_MS);
}

/** Attach the flush-on-leave handlers once. */
export function installFlushHandlers(): () => void {
  if (typeof document === "undefined") return () => {};
  const onHide = () => {
    if (document.visibilityState === "hidden") flush();
  };
  document.addEventListener("visibilitychange", onHide);
  window.addEventListener("pagehide", flush);
  return () => {
    document.removeEventListener("visibilitychange", onHide);
    window.removeEventListener("pagehide", flush);
  };
}
