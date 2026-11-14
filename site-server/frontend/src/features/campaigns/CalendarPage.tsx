import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";

import Icon from "../../components/Icon";
import { Alert, Badge, Card, EmptyState, fa } from "../../components/ui";
import { type PlannedRow, type ScheduledRow, useCampaigns } from "./CampaignsLayout";

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

const jalaliParts = new Intl.DateTimeFormat("en-u-ca-persian-nu-latn", {
  year: "numeric",
  month: "numeric",
  day: "numeric",
});

/** سال/ماه/روزِ شمسیِ یک تاریخ. */
function jal(d: Date): { year: number; month: number; day: number } {
  const out = { year: 0, month: 0, day: 0 };
  for (const part of jalaliParts.formatToParts(d)) {
    if (part.type === "year" || part.type === "month" || part.type === "day") {
      out[part.type] = parseInt(part.value, 10);
    }
  }
  return out;
}

/** روزِ اولِ ماهِ شمسیِ «offset» ماه از ماهِ جاری. ماه‌های شمسی ۲۹ تا ۳۱ روزه‌اند؛
 *  هر قدم را از روزِ اول با +۳۱ (یا −۱) برمی‌داریم و دوباره به روزِ ۱ برمی‌گردانیم. */
function jalaliMonthStart(offset: number): Date {
  const now = new Date();
  const d = new Date(now.getFullYear(), now.getMonth(), now.getDate(), 12);
  d.setDate(d.getDate() - (jal(d).day - 1));
  for (let i = 0; i < Math.abs(offset); i++) {
    d.setDate(d.getDate() + (offset > 0 ? 31 : -1));
    d.setDate(d.getDate() - (jal(d).day - 1));
  }
  return d;
}

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
  const { storeId, scheduled, planned } = useCampaigns();
  const navigate = useNavigate();
  const [offset, setOffset] = useState(0);

  /** باز کردنِ کار در تختهٔ کمپین: متنِ کامل، موعد و دکمهٔ کپی همان‌جاست. */
  const openTask = (row: PlannedRow) =>
    navigate(`/stores/${storeId}/campaigns?campaign=${row.campaign_id}&task=${row.id}`);

  const { cells, label, byDay, plannedByDay, first } = useMemo(() => {
    // ماهِ شمسیِ واقعی (قبلاً ماهِ میلادی بود و فقط عنوانش شمسی بود: «آبان» با
    // روزهای آذر در همان جدول)
    const first = jalaliMonthStart(offset);
    const lead = (first.getDay() + 1) % 7;
    const start = new Date(first);
    start.setDate(first.getDate() - lead);

    const map = new Map<string, ScheduledRow[]>();
    for (const row of scheduled) {
      const key = dayKey(new Date(row.scheduled_for));
      map.set(key, [...(map.get(key) ?? []), row]);
    }
    const pmap = new Map<string, PlannedRow[]>();
    for (const row of planned) {
      const key = dayKey(new Date(row.due_at));
      pmap.set(key, [...(pmap.get(key) ?? []), row]);
    }

    return {
      first,
      label: faMonthYear.format(first),
      byDay: map,
      plannedByDay: pmap,
      cells: Array.from({ length: 42 }, (_, i) => {
        const date = new Date(start);
        date.setDate(start.getDate() + i);
        return date;
      }),
      // شش هفته ثابت است تا ارتفاع تقویم بین ماه‌ها نپرد و دکمه‌ی ماه
      // بعد زیر دست کاربر جابه‌جا نشود
    };
  }, [scheduled, planned, offset]);

  const monthJal = jal(first);
  const todayKey = dayKey(new Date());

  /** روی گوشی خانه‌ها فقط نقطه‌اند؛ زدن روی نقطه‌ها به فهرستِ همان روز می‌رود. */
  const showDayList = (key: string) => {
    const firstRow = plannedByDay.get(key)?.[0];
    if (firstRow) {
      document.getElementById(`plan-${firstRow.id}`)?.scrollIntoView({ behavior: "smooth", block: "center" });
    }
  };

  return (
    <div className="space-y-4">
      {scheduled.length === 0 && planned.length > 0 && (
        <Alert tone="info" title="برنامهٔ پیشنهادی روی تقویم است">
          خانه‌های خط‌چین موعدِ پیشنهادیِ کارهای کمپین‌اند — هنوز چیزی زمان‌بندی یا منتشر نشده.
          روی هر کار بزنید تا متنِ کاملش (کپشن، اسلایدها، موعد) در تختهٔ کمپین باز شود.
        </Alert>
      )}
      {scheduled.length === 0 && planned.length === 0 && (
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
            const plans = plannedByDay.get(key) ?? [];
            const jd = jal(date);
            const outside = jd.month !== monthJal.month || jd.year !== monthJal.year;
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
                {(rows.length > 0 || plans.length > 0) && (
                  <button
                    type="button"
                    disabled={plans.length === 0}
                    onClick={() => showDayList(key)}
                    aria-label={plans.length ? `${fa(plans.length)} کارِ پیشنهادی — دیدنِ فهرست` : undefined}
                    className="flex w-full flex-wrap justify-center gap-1 sm:hidden"
                    style={{ background: "none", border: 0, padding: "6px 0", cursor: plans.length ? "pointer" : "default" }}
                  >
                    {plans.slice(0, 3).map((row) => (
                      <span
                        key={`p${row.id}`}
                        className="block h-1.5 w-1.5 rounded-full"
                        style={{ border: "1px dashed var(--text-3)" }}
                      />
                    ))}
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
                  </button>
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
                  {plans.slice(0, Math.max(0, 3 - rows.length)).map((row) => (
                    <button
                      type="button"
                      key={`p${row.id}`}
                      onClick={() => openTask(row)}
                      className="block w-full cursor-pointer truncate rounded-md px-1.5 py-0.5 text-start text-[11px] hover:bg-[var(--surface-2)]"
                      style={{
                        background: "none",
                        border: "1px dashed var(--line)",
                        color: row.state === "DONE" ? "var(--text-3)" : "var(--text-2)",
                        textDecoration: row.state === "DONE" ? "line-through" : "none",
                      }}
                      title={`${row.campaign} — ${row.kind_label} — پیشنهادی (${row.state_label}). برای دیدنِ متنِ کار بزنید.`}
                    >
                      {row.title}
                    </button>
                  ))}
                  {rows.length + plans.length > 3 && (
                    <div className="text-center text-[11px]" style={{ color: "var(--text-3)" }}>
                      +{fa(rows.length + plans.length - 3)} مورد دیگر
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
            const j = jal(new Date(r.scheduled_for));
            return j.month === monthJal.month && j.year === monthJal.year;
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

      {/* برنامهٔ پیشنهادیِ همین ماه — روی گوشی خانه‌ها فقط نقطه‌اند */}
      {(() => {
        const month = planned.filter((r) => {
          const j = jal(new Date(r.due_at));
          return j.month === monthJal.month && j.year === monthJal.year;
        });
        if (!month.length) return null;
        return (
          <Card padded={false} className="sm:hidden">
            <ul>
              {month.map((row, i) => (
                <li
                  key={row.id}
                  id={`plan-${row.id}`}
                  style={{ borderTop: i ? "1px solid var(--line)" : "none" }}
                >
                  <button
                    type="button"
                    onClick={() => openTask(row)}
                    className="flex w-full cursor-pointer items-center gap-3 px-4 py-3 text-start"
                    style={{ background: "none", border: 0 }}
                    aria-label={`${row.title} — باز کردنِ متنِ کار`}
                  >
                    <span className="u-num w-12 shrink-0 text-center text-xs" style={{ color: "var(--text-3)" }}>
                      {new Intl.DateTimeFormat("fa-IR-u-ca-persian", { day: "numeric", month: "short" }).format(
                        new Date(row.due_at),
                      )}
                    </span>
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-sm" style={{ color: "var(--text)" }}>
                        {row.title}
                      </span>
                      <span className="text-xs" style={{ color: "var(--text-3)" }}>
                        {row.campaign} — پیشنهادی
                      </span>
                    </span>
                    <Badge tone="neutral">{row.state_label}</Badge>
                    <Icon name="next" size={14} />
                  </button>
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
        {planned.length > 0 && <Badge tone="neutral">خط‌چین = پیشنهادِ برنامه</Badge>}
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
