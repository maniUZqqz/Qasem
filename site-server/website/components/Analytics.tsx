"use client";

import { usePathname } from "next/navigation";
import { useEffect } from "react";

import type { Locale } from "@/lib/i18n";
import { currentSessionId, installFlushHandlers, track } from "@/lib/track";

/**
 * Page views and CTA clicks.
 *
 * CTA clicks are captured with one delegated listener rather than an onClick on
 * every button. Adding a handler to each link would mean every new CTA has to
 * remember to be tracked — and the ones that get forgotten are exactly the ones
 * whose numbers you later wish you had.
 */
export default function Analytics({ locale }: { locale: Locale }) {
  const pathname = usePathname();

  useEffect(() => installFlushHandlers(), []);

  useEffect(() => {
    track("page_view", {}, locale);
    // The pricing page is a funnel milestone, not just another page.
    if (pathname?.includes("/pricing")) track("pricing_view", {}, locale);
  }, [pathname, locale]);

  useEffect(() => {
    function onClick(e: MouseEvent) {
      const el = (e.target as HTMLElement | null)?.closest("a");
      if (!el) return;

      const href = el.getAttribute("href") || "";
      const label = (el.textContent || "").trim().slice(0, 60);

      // A link into the panel is the moment intent becomes action.
      if (href.includes("/register")) {
        const plan = /[?&]plan=([a-z0-9-]+)/i.exec(href)?.[1];
        if (plan) track("plan_selected", { plan, from: pathname || "" }, locale);

        // The panel is a different origin, so it cannot read the session id
        // from storage. Hand it over in the URL, otherwise the signup starts a
        // fresh session and the funnel never joins "saw pricing" to
        // "registered". Rewritten in place so the existing ?plan= survives.
        const sid = currentSessionId();
        if (sid && !/[?&]s=/.test(href)) {
          el.setAttribute("href", `${href}${href.includes("?") ? "&" : "?"}s=${sid}`);
        }
        return;
      }

      if (el.classList.contains("btn")) {
        track("cta_click", { href, label }, locale);
      }
    }

    document.addEventListener("click", onClick);
    return () => document.removeEventListener("click", onClick);
  }, [pathname, locale]);

  return null;
}
