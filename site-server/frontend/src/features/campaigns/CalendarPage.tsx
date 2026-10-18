import { useMemo, useState } from "react";

import Icon from "../../components/Icon";
import { Alert, Badge, Card, EmptyState, fa } from "../../components/ui";
import { type ScheduledRow, useCampaigns } from "./CampaignsLayout";

/**
 * تقویم انتشار — ماه شمسی، با آنچه در هر روز می‌رود.
 *
 * ── چرا تقویم و نه فهرست ──────────────────────────────────────────
 * صف انتشار به سؤال «چه چیزی بعدی است» جواب می‌دهد. تقویم به سؤالی
 * جواب می‌دهد که فهرست هرگز نمی‌دهد: «کجا سوراخ دارم؟» — سه روز پشت سر
 * هم که هیچ پستی نمی‌رود، در یک فهرست *دیده نمی‌شود* چون چیزی برای
 * دیدن نیست؛ در تقویم یک شکاف است.
 *
 * ── تقویم شمسی با کد استاندارد ────────────────────────────────────
 * روزهای ماه با `Intl` فارسی ساخته می‌شوند، نه با یک کتابخانه‌ی تبدیل
 * تاریخ. حساب دستیِ تقویم جلالی جایی است که باگ‌های کبیسه در آن زندگی
 * می‌کنند، و مرورگر همین حساب را درست دارد.
 */

const WEEKDAYS = ["شنبه", "یک", "دو", "سه", "چهار", "پنج", "جمعه"];

const faDay = new Intl.DateTimeFormat("fa-IR-u-ca-persian", { day: "numeric" });
const faMonthYear = new Intl.DateTimeFormat("fa-IR-u-ca-persian", {
  month: "long",
  year: "numeric",
});
const faTime = new Intl.DateTimeFormat("fa-IR", { hour: "2-digit", minute: "2-digit" });

/** کلید روز به وقت محلی. `toISOString` اینجا غلط است: ساعت ۲ بامداد
 *  تهران، در UTC هنوز *دیروز* است و پست را یک خانه عقب می‌برد. */
function dayKey(d: Date): string {
  return `${d.getFullYear()}-${d.getMonth() + 1}-${d.getDate()}`;
}

const PLATFORM_LABEL: Record<string, string> = {
  instagram: "اینستاگرام",
  telegram: "تلگرام",
  linkedin: "لینکدین",
  whatsapp: "واتس‌اپ",
};

const STATUS_TONE: Record<string, "neutral" | "info" | "ok" | "bad" | "warn"> = {
  PENDING: "info",
  SENT: "ok",
  FAILED: "bad",
  MISSED: "warn",
};

export default function CalendarPage() {
  const { scheduled } = useCampaigns();
  const [offset, setOffset] = useState(0);

  const { cells, label, byDay } = useMemo(() => {
    const today = new Date();
    const cursor = new Date(today.getFullYear(), today.getMonth() + offset, 1);

    // شنبه ابتدای هفته است: getDay() یکشنبه را صفر می‌گیرد، پس +1 و mod 7
    const first = new Date(cursor);
    const lead = (first.getDay() + 1) % 7;
    const start = new Date(first);
    start.setDate(first.getDate() - lead);

    const map = new Map<string, ScheduledRow[]>();
    for (const row of scheduled) {
      const key = dayKey(new Date(row.scheduled_for));
      map.set(key, [...(map.get(key) ?? []), row]);
    }

    return {
      label: faMonthYear.format(cursor),
      byDay: map,
      cells: Array.from({ length: 42 }, (_, i) => {
        const date = new Date(start);
        date.setDate(start.getDate() + i);
        return date;
      }),
      // شش هفته ثابت است تا ارتفاع تقویم بین ماه‌ها نپرد و دکمه‌ی ماه
      // بعد زیر دست کاربر جابه‌جا نشود
    };
  }, [scheduled, offset]);

  const monthOf = new Date(new Date().getFullYear(), new Date().getMonth() + offset, 1).getMonth();
  const todayKey = dayKey(new Date());

  return (
    <div className="space-y-4">
      {scheduled.length === 0 && (
        <Alert tone="info" title="هنوز چیزی زمان‌بندی نشده">
          در تب «کمپین‌ها» یک کمپین را تأیید کنید، بعد از همان‌جا زمان انتشارش را
          بگذارید. زمان‌بند هر دقیقه بررسی می‌کند — <strong>دیر منتشر می‌کند ولی هرگز
          زود</strong>.
        </Alert>
      )}

      <Card padded={false}>
        <div
          className="flex items-center justify-between gap-2 px-4 py-3"
          style={{ borderBottom: "1px solid var(--line)" }}
        >
          <button
            onClick={() => setOffset((v) => v - 1)}
            className="u-btn u-btn-ghost"
            style={{ padding: 9 }}
            aria-label="ماه قبل"
          >
            <Icon name="back" size={16} />
          </button>
          <div className="text-sm font-bold" style={{ color: "var(--text)" }}>
            {label}
          </div>
          <div className="flex gap-1">
            {offset !== 0 && (
              <button onClick={() => setOffset(0)} className="u-btn u-btn-ghost u-btn-sm">
                امروز
              </button>
            )}
            <button
              onClick={() => setOffset((v) => v + 1)}
              className="u-btn u-btn-ghost"
              style={{ padding: 9 }}
              aria-label="ماه بعد"
            >
              <Icon name="next" size={16} />
            </button>
          </div>
        </div>

        <div className="grid grid-cols-7">
          {WEEKDAYS.map((d) => (
            <div
              key={d}
              className="px-2 py-2 text-center text-[11px] font-semibold"
              style={{ color: "var(--text-3)", borderBottom: "1px solid var(--line)" }}
            >
              {d}
            </div>
          ))}

          {cells.map((date, i) => {
            const key = dayKey(date);
            const rows = byDay.get(key) ?? [];
            const outside = date.getMonth() !== monthOf;
            const isToday = key === todayKey;
            return (
              <div
                key={key}
                className="min-h-[52px] p-1.5 sm:min-h-[92px]"
                style={{
                  borderBottom: "1px solid var(--line)",
                  borderInlineStart: i % 7 === 6 ? "none" : "1px solid var(--line)",
                  opacity: outside ? 0.35 : 1,
                  background: isToday ? "var(--brand-soft)" : undefined,
                }}
              >
                <div
                  className="u-num mb-1 text-center text-[11px]"
                  style={{
                    color: isToday ? "var(--brand-strong)" : "var(--text-3)",
                    fontWeight: isToday ? 700 : 400,
                  }}
                >
                  {faDay.format(date)}
                </div>
                {/* روی گوشی هر خانه ~۵۰ پیکسل است و «۰۷:۵۶ کمپین پاییزه» به
                    «۰۷:…» می‌رسید. آنجا فقط نقطه‌ی رنگی نشان داده می‌شود و
                    جزئیات در فهرست زیر تقویم می‌آید. */}
                {rows.length > 0 && (
                  <div className="flex flex-wrap justify-center gap-1 sm:hidden">
                    {rows.slice(0, 4).map((row) => (
                      <span
                        key={row.id}
                        className="block h-1.5 w-1.5 rounded-full"
                        style={{
                          background: `var(--${
                            row.status === "FAILED" ? "bad" : row.status === "SENT" ? "ok" : "info"
                          })`,
                        }}
                      />
                    ))}
                  </div>
                )}
                <div className="hidden space-y-1 sm:block">
                  {rows.slice(0, 3).map((row) => (
                    <div
                      key={row.id}
                      className="truncate rounded-md px-1.5 py-0.5 text-[11px]"
                      style={{
                        background: `var(--${
                          row.status === "FAILED" ? "bad" : row.status === "SENT" ? "ok" : "info"
                        }-soft)`,
                        color: `var(--${
                          row.status === "FAILED" ? "bad" : row.status === "SENT" ? "ok" : "info"
                        })`,
                      }}
                      title={`${row.campaign} — ${
                        PLATFORM_LABEL[row.platform] ?? row.platform
                      } — ${row.status_label}${row.error ? ` — ${row.error}` : ""}`}
                    >
                      {faTime.format(new Date(row.scheduled_for))} {row.campaign}
                    </div>
                  ))}
                  {rows.length > 3 && (
                    <div className="text-center text-[11px]" style={{ color: "var(--text-3)" }}>
                      +{fa(rows.length - 3)} مورد دیگر
                    </div>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      </Card>

      {/* فهرست همین ماه — روی گوشی جای متنِ داخل خانه‌ها را می‌گیرد. */}
      {(() => {
        const month = scheduled
          .filter((r) => {
            const d = new Date(r.scheduled_for);
            return (
              d.getMonth() === monthOf &&
              d.getFullYear() ===
                new Date(new Date().getFullYear(), new Date().getMonth() + offset, 1).getFullYear()
            );
          })
          .sort(
            (a, b) => new Date(a.scheduled_for).getTime() - new Date(b.scheduled_for).getTime(),
          );
        if (!month.length) return null;
        return (
          <Card padded={false} className="sm:hidden">
            <ul>
              {month.map((row, i) => (
                <li
                  key={row.id}
                  className="flex items-center gap-3 px-4 py-3"
                  style={{ borderTop: i ? "1px solid var(--line)" : "none" }}
                >
                  <span
                    className="u-num w-12 shrink-0 text-center text-xs"
                    style={{ color: "var(--text-3)" }}
                  >
                    {new Intl.DateTimeFormat("fa-IR-u-ca-persian", {
                      day: "numeric",
                      month: "short",
                    }).format(new Date(row.scheduled_for))}
                    <br />
                    {faTime.format(new Date(row.scheduled_for))}
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-sm" style={{ color: "var(--text)" }}>
                      {row.campaign}
                    </span>
                    <span className="text-xs" style={{ color: "var(--text-3)" }}>
                      {PLATFORM_LABEL[row.platform] ?? row.platform}
                    </span>
                  </span>
                  <Badge tone={STATUS_TONE[row.status] ?? "neutral"}>{row.status_label}</Badge>
                </li>
              ))}
            </ul>
          </Card>
        );
      })()}

      {/* راهنما با برچسب، نه فقط رنگ */}
      <div className="flex flex-wrap items-center gap-2 text-xs">
        <Badge tone="info">زمان‌بندی‌شده</Badge>
        <Badge tone="ok">منتشر شد</Badge>
        <Badge tone="bad">شکست خورد</Badge>
        <span style={{ color: "var(--text-3)" }}>
          — جزئیات هر مورد در تب «صف انتشار» است.
        </span>
      </div>

      {scheduled.length > 0 && byDay.size === 0 && (
        <EmptyState icon="clock" title="در این ماه چیزی زمان‌بندی نشده">
          با دکمه‌های بالا ماه‌های دیگر را ببینید.
        </EmptyState>
      )}
    </div>
  );
}
