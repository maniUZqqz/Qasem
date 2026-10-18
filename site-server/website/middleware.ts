import { NextResponse, type NextRequest } from "next/server";

import { DEFAULT_LOCALE, LOCALES } from "@/lib/i18n";

/**
 * Serves Persian from the root.
 *
 * The App Router needs a `[locale]` segment to know which language to render,
 * but the primary market should not have to carry `/fa` in every URL. So the
 * request for `/pricing` is *rewritten* (not redirected) to `/fa/pricing`:
 * the visitor keeps the clean URL, and Next still gets its segment.
 *
 * `/en/...` passes through untouched. A request that already says `/fa/...`
 * is redirected back to the bare path so the same page never exists at two
 * URLs — duplicate content is the one thing an SEO rewrite must not create.
 */
const PREFIXED = LOCALES.filter((l) => l !== DEFAULT_LOCALE);

export function middleware(request: NextRequest) {
  const { pathname, search } = request.nextUrl;

  // Already an explicitly prefixed locale (/en/...) — nothing to do.
  if (PREFIXED.some((l) => pathname === `/${l}` || pathname.startsWith(`/${l}/`))) {
    return NextResponse.next();
  }

  // /fa/x is the internal form. If someone reaches it directly, send them to
  // the canonical /x so the page has exactly one address.
  if (pathname === `/${DEFAULT_LOCALE}` || pathname.startsWith(`/${DEFAULT_LOCALE}/`)) {
    const url = request.nextUrl.clone();
    url.pathname = pathname.slice(DEFAULT_LOCALE.length + 1) || "/";
    return NextResponse.redirect(url, 308);
  }

  // Everything else is Persian: rewrite, keeping the visible URL unchanged.
  const url = request.nextUrl.clone();
  url.pathname = `/${DEFAULT_LOCALE}${pathname === "/" ? "" : pathname}`;
  url.search = search;
  return NextResponse.rewrite(url);
}

export const config = {
  /**
   * Skip anything that is not a page: Next internals, and the metadata routes
   * that deliberately live outside `[locale]` (sitemap, robots, feed, icons).
   * Running the rewrite over those would hand Google a 404 for its sitemap.
   */
  matcher: [
    "/((?!_next/|api/|sitemap\\.xml|robots\\.txt|feed\\.xml|icon|apple-icon|opengraph-image|manifest\\.webmanifest|favicon\\.ico|.*\\.[\\w]+$).*)",
  ],
};
