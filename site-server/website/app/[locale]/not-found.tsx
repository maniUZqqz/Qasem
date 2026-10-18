import Link from "next/link";

import { dict } from "@/lib/dict";
import { DEFAULT_LOCALE, localePath } from "@/lib/i18n";

/**
 * 404.
 *
 * Next renders this without route params, so the locale is not available
 * here — it falls back to Persian. An English visitor hitting a dead URL sees
 * Persian, which is not ideal but is better than the alternative: a catch-all
 * route that would swallow every unmatched path and never 404 at all.
 */
export default function NotFound() {
  const l = DEFAULT_LOCALE;
  const t = dict(l);

  return (
    <section>
      <div className="wrap narrow center">
        <div style={{ fontSize: "4rem" }}>🧭</div>
        <h1 className="mt">این صفحه پیدا نشد</h1>
        <p className="lead mt">شاید نشانی عوض شده باشد. از این‌ها امتحان کنید:</p>

        <div className="row mt-md center-row">
          {t.nav.map((item) => (
            <Link key={item.href} href={localePath(l, item.href)} className="tag-link">
              {item.label}
            </Link>
          ))}
        </div>

        <div className="mt-md">
          <Link href={localePath(l, "/")} className="btn btn-primary">
            بازگشت به صفحه‌ی اصلی
          </Link>
        </div>
      </div>
    </section>
  );
}
