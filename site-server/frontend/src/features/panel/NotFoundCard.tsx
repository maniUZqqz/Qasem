import { Link } from "react-router-dom";

import Icon from "../../components/Icon";
import { Card } from "../../components/ui";
import type { Suggestion } from "./notFound";

const linkBtn = (primary: boolean) => `u-btn ${primary ? "u-btn-primary" : "u-btn-secondary"} no-underline`;

/** خودِ کارتِ «پیدا نشد» — بدون هوکِ احراز هویت و بدون قاب، تا بی مرورگر رندر و آزموده شود. */
export function NotFoundCard({
  path,
  signedIn,
  storeId = null,
  suggestions = [],
  canGoBack = false,
  onBack,
}: {
  /** همان‌طور که در نوارِ آدرس است، مثلاً `/panel/stores/34/xyz`. */
  path: string;
  signedIn: boolean;
  storeId?: string | null;
  suggestions?: Suggestion[];
  canGoBack?: boolean;
  onBack?: () => void;
}) {
  return (
    <Card className="mx-auto w-full max-w-xl text-center">
      <div className="flex flex-col items-center gap-2 px-2 py-6" data-testid="not-found">
        <span
          className="mb-1 grid h-12 w-12 place-items-center rounded-2xl"
          style={{ background: "var(--surface-2)", border: "1px solid var(--line)", color: "var(--text-3)" }}
        >
          <Icon name="search" size={22} />
        </span>
        <h1 className="text-lg font-bold" style={{ color: "var(--text)" }}>
          صفحه‌ای که دنبالش بودید پیدا نشد
        </h1>
        <p className="max-w-md text-sm" style={{ color: "var(--text-3)" }}>
          این آدرس در پنل وجود ندارد؛ شاید پیوندِ قدیمی یا ناقص بوده یا نشانی را اشتباه تایپ کرده‌اید.
        </p>
        <p className="mt-1 text-xs" style={{ color: "var(--text-3)" }}>
          آدرسِ درخواستی
        </p>
        <code
          dir="ltr"
          className="max-w-full break-all rounded-lg px-2.5 py-1 text-xs"
          style={{ background: "var(--surface-2)", border: "1px solid var(--line)", color: "var(--text-2)" }}
          data-testid="not-found-path"
        >
          {path}
        </code>

        {signedIn ? (
          <div className="mt-4 flex flex-wrap items-center justify-center gap-2">
            <Link to="/" className={linkBtn(true)}>
              رفتن به داشبورد
            </Link>
            {storeId && (
              <Link to={`/stores/${storeId}`} className={linkBtn(false)}>
                صفحهٔ اصلیِ فروشگاه
              </Link>
            )}
            {canGoBack && (
              <button type="button" className="u-btn u-btn-ghost" onClick={onBack}>
                بازگشت
              </button>
            )}
          </div>
        ) : (
          <div className="mt-4 flex flex-col items-center gap-2">
            <p className="text-sm" style={{ color: "var(--text-2)" }}>
              برای استفاده از پنل ابتدا وارد شوید.
            </p>
            <Link to="/login" className={linkBtn(true)}>
              ورود به پنل
            </Link>
          </div>
        )}

        {signedIn && suggestions.length > 0 && (
          <div className="mt-5 w-full border-t pt-4" style={{ borderColor: "var(--line)" }}>
            <p className="mb-2 text-xs" style={{ color: "var(--text-3)" }}>
              شاید این صفحه‌ها را می‌خواستید
            </p>
            <ul className="flex flex-wrap items-center justify-center gap-2" data-testid="not-found-suggestions">
              {suggestions.map((s) => (
                <li key={s.key}>
                  <Link to={s.href} className="u-btn u-btn-ghost u-btn-sm no-underline">
                    {s.label}
                  </Link>
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </Card>
  );
}
