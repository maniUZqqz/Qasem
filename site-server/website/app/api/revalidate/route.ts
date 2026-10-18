/**
 * "I changed it in the Django admin and the site still shows the old text."
 *
 * It did change — the page just had up to `revalidate` seconds of cache left
 * (lib/api.ts, 120s by default). Anyone who edits and refreshes straight away
 * sees the old copy and reasonably concludes the site is not reading the
 * database at all.
 *
 * So Django tells the site the moment something is saved
 * (backend/apps/cms/revalidate.py) and the page rebuilds on the next visit.
 * The cache window stays as the safety net for anything that misses this.
 *
 * Guarded by a shared secret, because this endpoint is a way to make a
 * stranger's requests do work: without one, anything on the internet could
 * hold the cache open by calling it in a loop.
 */
import { revalidateTag } from "next/cache";
import { NextRequest, NextResponse } from "next/server";

/** Never prerendered, never cached — it exists to have side effects. */
export const dynamic = "force-dynamic";

/** What may be asked for. An open list would let a caller invalidate
 *  anything it could name, including tags we add later for other reasons. */
const KNOWN_TAGS = new Set([
  "articles",
  "categories",
  "plans",
  "showcase",
  "settings",
]);

export async function POST(request: NextRequest) {
  const secret = process.env.REVALIDATE_SECRET || "";
  if (!secret) {
    // Unset means the shop never wired this up. Refuse rather than accept
    // everyone: an endpoint with an empty password is not a protected one.
    return NextResponse.json(
      { ok: false, error: "REVALIDATE_SECRET is not set on the website" },
      { status: 503 },
    );
  }
  if (request.headers.get("x-revalidate-secret") !== secret) {
    return NextResponse.json({ ok: false }, { status: 403 });
  }

  let tags: string[] = [];
  try {
    const body = (await request.json()) as { tags?: unknown };
    if (Array.isArray(body.tags)) tags = body.tags.map(String);
  } catch {
    return NextResponse.json({ ok: false, error: "bad json" }, { status: 400 });
  }

  const accepted = tags.filter((tag) => KNOWN_TAGS.has(tag));
  accepted.forEach((tag) => revalidateTag(tag));
  return NextResponse.json({ ok: true, revalidated: accepted });
}
