import NotFoundView from "@/components/NotFoundView";

/**
 * 404 — rendered inside the `[locale]` layout (header, footer, `lang`, `dir`)
 * whenever a page calls `notFound()`. Unknown URLs reach it through
 * `[...rest]/page.tsx`, which exists only to do that. The body is a client
 * component because the locale of the dead URL is only known there.
 */
export default function NotFound() {
  return <NotFoundView />;
}
