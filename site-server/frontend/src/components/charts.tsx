import { ReactNode, useId, useState } from "react";

import Icon from "./Icon";
import { Card, fa } from "./ui";

/**
 * نمودارهای پنل — یک بار نوشته، نه یک بار در هر صفحه.
 *
 * `DailyBarChart` و `StatTile` عیناً در `SalesPage` و `AnalyticsPage` تکرار
 * شده بودند، و کامنت بالای یکی‌شان خودش می‌گفت پالتش «همان پالت آن یکی»
 * است. دو کپی از یک نمودار یعنی هر اصلاحی باید دو بار انجام شود، و بار
 * دومش همان است که فراموش می‌شود.
 *
 * ── پالت ──────────────────────────────────────────────────────────
 * رنگ‌ها با اسکریپت شش‌سنجه‌ی dataviz اعتبارسنجی شده‌اند و **هر دو تم
 * پاس می‌دهند** — نه اینکه تم تیره وارونه‌ی خودکار تم روشن باشد:
 *
 *   تیره (روی #14161F): باند روشنایی ✓ · اشباع ✓ · جدایی کوررنگی ΔE ۱۲.۷ ✓
 *                        · دید عادی ΔE ۱۹.۳ ✓ · کنتراست ≥۳:۱ ✓
 *   روشن (روی #FAFBFE): باند ✓ · اشباع ✓ · ΔE ۹.۷ ✓ · ۱۸.۲ ✓ · ≥۳:۱ ✓
 *
 * **ترتیب رنگ‌ها تزئینی نیست.** با چیدمان بنفش/سرخابی/فیروزه‌ای، جفتِ
 * مجاورِ سرخابی↔فیروزه‌ای برای دوترانوپ ΔE ۲.۹ می‌داد — یعنی یک نفر از
 * هر دوازده مرد، دو سری را یک رنگ می‌دید. جابه‌جا کردن زرد به وسط،
 * همان ΔE را به ۱۲.۷ برد. پس ترتیب را عوض نکنید مگر با اجرای دوباره‌ی
 * اسکریپت.
 *
 * رنگ به **موجودیت** می‌چسبد نه به رتبه: درآمد همیشه بنفش است، سفارش
 * همیشه فیروزه‌ای — چه در صفحه‌ی فروش، چه در آمار.
 */

/** جای رنگ در پالت. اسم معنایی است تا کسی «رنگ سوم» را عوض نکند. */
export type Series = "revenue" | "orders" | "content" | "people";

const PALETTE: Record<Series, { dark: string; light: string; label: string }> = {
  revenue: { dark: "#7C6BF0", light: "#5B45D8", label: "درآمد" },
  orders: { dark: "#19A88F", light: "#12876F", label: "سفارش" },
  content: { dark: "#C98500", light: "#B07400", label: "محتوا" },
  people: { dark: "#D55181", light: "#C74070", label: "مشتری" },
};

/** رنگ سری در تم فعلی. از `data-theme` روی <html> خوانده می‌شود، همان
 *  جایی که ThemeToggle می‌نویسد. */
export function seriesColor(series: Series): string {
  const dark =
    typeof document === "undefined" ||
    document.documentElement.getAttribute("data-theme") !== "light";
  return dark ? PALETTE[series].dark : PALETTE[series].light;
}

const faDate = (iso: string) =>
  new Date(iso).toLocaleDateString("fa-IR", { month: "short", day: "numeric" });

const faNum = (n: number) => n.toLocaleString("fa-IR");

/* ------------------------------------------------------------------ کاشی */

/**
 * یک عدد با برچسبش.
 *
 * وقتی داده «یک عدد» است، نمودار کشیدنش کارِ اضافه روی چیزی است که
 * خودش گویاست — راهنمای فرم همین را می‌گوید.
 */
export function StatTile({
  label,
  value,
  hint,
  series,
  trend,
}: {
  label: string;
  value: string;
  hint?: string;
  /** اگر این کاشی به یک سری نمودار وصل است، همان رنگ را نشان می‌دهد تا
   *  چشم بداند کدام کاشی با کدام نمودار حرف می‌زند. */
  series?: Series;
  /** درصد تغییر. مثبت/منفی با آیکون هم نشان داده می‌شود نه فقط با رنگ. */
  trend?: number;
}) {
  return (
    <Card>
      <div className="flex items-center gap-2">
        {series && (
          <span
            className="inline-block h-2.5 w-2.5 shrink-0 rounded-sm"
            style={{ background: seriesColor(series) }}
          />
        )}
        <p className="text-xs" style={{ color: "var(--text-3)" }}>
          {label}
        </p>
      </div>
      <p
        className="u-num mt-1 text-2xl font-extrabold"
        style={{ color: "var(--text)" }}
        dir="ltr"
      >
        {value}
      </p>
      <div className="mt-1 flex items-center gap-2">
        {trend !== undefined && trend !== 0 && (
          <span
            className="inline-flex items-center gap-0.5 text-xs font-semibold"
            style={{ color: trend > 0 ? "var(--ok)" : "var(--bad)" }}
          >
            <Icon name={trend > 0 ? "up" : "down"} size={13} />
            {fa(Math.abs(Math.round(trend)))}٪
          </span>
        )}
        {hint && (
          <span className="text-xs" style={{ color: "var(--text-3)" }}>
            {hint}
          </span>
        )}
      </div>
    </Card>
  );
}

/* ---------------------------------------------------------------- نمودار */

export type Point = { date: string; value: number };

/**
 * ستونی روزانه، با لایه‌ی هاور.
 *
 * دو چیز که در نسخه‌ی قبلی نبود و مهم‌اند:
 *
 * **فاصله‌ی ۲ پیکسلی بین ستون‌ها از جنس سطح است**، نه شفاف. روی پس‌زمینه‌ی
 * شیشه‌ای، فاصله‌ی شفاف یعنی هاله از لای ستون‌ها رد می‌شود و لبه‌ی ستون
 * گم می‌شود.
 *
 * **روز صفر با روزِ بی‌داده فرق دارد.** قبلاً هر دو یک میله‌ی خاکستری
 * می‌شدند. «صفر فروش» یک واقعیت است و «هنوز نرسیده» یک خلأ؛ یکی‌شان
 * نگران‌کننده است و آن یکی نه.
 */
export function DailyBarChart({
  title,
  series,
  caption,
  points,
  format = faNum,
}: {
  title: string;
  series: Series;
  caption?: string;
  points: Point[];
  format?: (value: number) => string;
}) {
  const [hover, setHover] = useState<number | null>(null);
  const color = seriesColor(series);
  const values = points.map((p) => p.value);
  const max = Math.max(...values, 1);
  const peak = values.indexOf(Math.max(...values));
  const total = values.reduce((a, b) => a + b, 0);

  return (
    <Card>
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <span
          className="inline-block h-3 w-3 shrink-0 rounded-sm"
          style={{ background: color }}
        />
        {/* عنوان خودش سری را نام می‌برد، پس یک سری لجند جدا لازم ندارد */}
        <span className="text-sm font-bold" style={{ color: "var(--text)" }}>
          {title}
        </span>
        {caption && (
          <span className="mr-auto text-xs" style={{ color: "var(--text-3)" }}>
            {caption}
          </span>
        )}
      </div>

      {total === 0 ? (
        <p className="py-8 text-center text-sm" style={{ color: "var(--text-3)" }}>
          در این بازه چیزی ثبت نشده.
        </p>
      ) : (
        <div
          className="relative flex h-32 items-end gap-[2px] pb-px"
          style={{ borderBottom: "1px solid var(--line)" }}
        >
          {points.map((point, i) => {
            const zero = point.value === 0;
            const height = zero ? 3 : Math.max(5, (point.value / max) * 100);
            // برچسب مستقیم فقط روی قله و روی چیزی که اشاره‌گر رویش است —
            // عدد روی هر ستون، نمودار را به جدولِ بدشکل تبدیل می‌کند
            const labelled = hover === i || (hover === null && i === peak && max > 0);
            return (
              <div
                key={point.date}
                className="relative flex h-full flex-1 items-end justify-center"
                onMouseEnter={() => setHover(i)}
                onMouseLeave={() => setHover(null)}
                onFocus={() => setHover(i)}
                onBlur={() => setHover(null)}
                tabIndex={0}
                role="img"
                aria-label={`${faDate(point.date)}: ${format(point.value)}`}
                style={{ outline: "none" }}
              >
                <div
                  className="w-full max-w-[15px] rounded-t-[4px] transition-opacity"
                  style={{
                    height: `${height}%`,
                    background: zero ? "var(--line-strong)" : color,
                    opacity: hover === null || hover === i ? 1 : 0.45,
                  }}
                />
                {labelled && (
                  <div
                    className="pointer-events-none absolute bottom-full z-10 mb-1.5 whitespace-nowrap rounded-lg px-2 py-1 text-[11px] font-semibold"
                    style={{
                      background: "var(--void-2)",
                      color: "var(--text)",
                      border: "1px solid var(--line-strong)",
                      boxShadow: "var(--shadow)",
                    }}
                  >
                    {faDate(point.date)} · {format(point.value)}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </Card>
  );
}

/**
 * نمای جدولی همان داده.
 *
 * نه به‌عنوان جایگزین نمودار، به‌عنوان همراهش: کسی که رنگ‌ها را تفکیک
 * نمی‌کند یا با صفحه‌خوان می‌خواند، عدد را از اینجا می‌گیرد.
 */
export function ChartTable({
  points,
  label,
  format = faNum,
}: {
  points: Point[];
  label: string;
  format?: (value: number) => string;
}) {
  const id = useId();
  const [open, setOpen] = useState(false);
  return (
    <div>
      <button
        onClick={() => setOpen((v) => !v)}
        className="u-btn u-btn-ghost u-btn-sm"
        aria-expanded={open}
        aria-controls={id}
      >
        <Icon name={open ? "up" : "down"} size={14} />
        {open ? "بستن جدول" : "نمای جدولی"}
      </button>
      {open && (
        <div id={id} className="mt-2 max-h-64 overflow-auto">
          <table className="u-table">
            <thead>
              <tr>
                <th>تاریخ</th>
                <th>{label}</th>
              </tr>
            </thead>
            <tbody>
              {points.map((p) => (
                <tr key={p.date}>
                  <td>{faDate(p.date)}</td>
                  <td className="u-num">{format(p.value)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

/** ردیف کاشی‌ها — چیدمانی که هر صفحه دوباره ننویسدش.
 *
 *  روی گوشی **دو ستون** است، نه یک. تک‌ستونی یعنی چهار کارت تمام‌عرض و
 *  بلند، که کل صفحه‌ی اول گوشی را برای نشان دادن چهار عدد مصرف می‌کرد —
 *  کسی که پنل را باز می‌کند تا ببیند «امروز چه خبر است» باید اسکرول
 *  می‌کرد تا به هر چیزی غیر از خلاصه برسد. */
export function StatRow({ children }: { children: ReactNode }) {
  return <div className="u-stat-row grid grid-cols-2 gap-2.5 sm:gap-3 lg:grid-cols-4">{children}</div>;
}
