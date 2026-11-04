import type { ReactNode } from "react";
import { Link } from "react-router-dom";

import { Badge, Card, SectionTitle } from "../../../../components/ui";
import { faAgo, num } from "../../format";
import type { Dashboard } from "../../types";

/**
 * Blocks contributed by other modules (`dashboard.extra.<name>`). Each one is optional: a module that is not
 * installed simply has no key, and a provider that failed says `{error: true}`. Numbers are shown exactly as
 * received - never estimated here.
 */

type Block = Record<string, unknown> | undefined;

const n = (value: unknown): number => (typeof value === "number" && Number.isFinite(value) ? value : 0);

function Row({ label, value, testId }: { label: string; value: ReactNode; testId?: string }) {
  return (
    <div className="flex items-center justify-between gap-3 py-1.5 text-sm" data-testid={testId}>
      <span style={{ color: "var(--text-3)" }}>{label}</span>
      <span className="u-num font-bold" style={{ color: "var(--text)" }}>
        {value}
      </span>
    </div>
  );
}

function Broken() {
  return (
    <p className="text-sm" style={{ color: "var(--warn)" }}>
      این بخش الان نتوانست اعدادش را بدهد.
    </p>
  );
}

function ExtractionCard({ block }: { block: Block }) {
  const last = (block?.last_job ?? null) as Record<string, unknown> | null;
  return (
    <Card>
      <SectionTitle action={<Link to="/growth/leads" className="text-xs">لیدها</Link>}>استخراج اطلاعات تماس</SectionTitle>
      {block?.error ? (
        <Broken />
      ) : (
        <>
          <Row label="لیدهایی که سایتشان خوانده شد" value={num(n(block?.leads_extracted))} testId="extra-leads-extracted" />
          <Row label="دفعاتِ اجرا" value={num(n(block?.runs_total))} />
          <Row label="راه تماسِ پیداشده" value={num(n(block?.contacts_found))} />
          {last && (
            <p className="mt-2 text-xs" style={{ color: "var(--text-3)" }}>
              آخرین کار: {String(last.status_label ?? last.status ?? "")} {last.finished_at ? `· ${faAgo(String(last.finished_at))}` : ""}
            </p>
          )}
          {n(block?.runs_total) === 0 && (
            <p className="mt-2 text-xs" style={{ color: "var(--text-3)" }}>
              هنوز استخراجی انجام نشده. در «دیتابیس لیدها» چند لید را انتخاب کنید و «استخراج اطلاعات تماس» را بزنید.
            </p>
          )}
        </>
      )}
    </Card>
  );
}

function OutreachCard({ block }: { block: Block }) {
  const cap = n(block?.daily_cap);
  return (
    <Card>
      <SectionTitle action={<Link to="/growth/outreach" className="text-xs">پیام‌رسانی</Link>}>پیام‌رسانی</SectionTitle>
      {block?.error ? (
        <Broken />
      ) : (
        <>
          <Row label="ارسالِ امروز" value={cap ? `${num(n(block?.sent_today))} از ${num(cap)}` : num(n(block?.sent_today))} testId="extra-sent-today" />
          <Row label="کمپین‌های فعال" value={num(n(block?.campaigns_active))} />
          <Row label="آمادهٔ تأیید" value={num(n(block?.items_ready))} />
          <Row label="نیازمند ارسالِ دستی" value={num(n(block?.items_needs_manual))} />
          <Row label="مجموعِ ارسال‌شده" value={num(n(block?.sent_total))} />
        </>
      )}
    </Card>
  );
}

function ComplianceCard({ block }: { block: Block }) {
  return (
    <Card>
      <SectionTitle action={<Link to="/growth/settings" className="text-xs">تنظیمات</Link>}>ایمنی و «تماس نگیر»</SectionTitle>
      {block?.error ? (
        <Broken />
      ) : (
        <>
          <Row label="در فهرست «تماس نگیر»" value={num(n(block?.suppressed))} />
          <Row
            label="ارسال خودکار"
            value={<Badge tone={block?.sending_enabled ? "ok" : "neutral"}>{block?.sending_enabled ? "روشن" : "خاموش"}</Badge>}
          />
          <Row
            label="توقفِ اضطراری"
            value={<Badge tone={block?.emergency_stop ? "bad" : "ok"}>{block?.emergency_stop ? "فعال است" : "فعال نیست"}</Badge>}
            testId="extra-emergency"
          />
        </>
      )}
    </Card>
  );
}

export default function ExtraBlocks({ extra }: { extra: Dashboard["extra"] }) {
  const has = (key: string) => Object.prototype.hasOwnProperty.call(extra ?? {}, key);
  if (!has("extraction") && !has("outreach") && !has("compliance")) return null;
  return (
    <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3" data-testid="dashboard-extra">
      {has("extraction") && <ExtractionCard block={extra.extraction} />}
      {has("outreach") && <OutreachCard block={extra.outreach} />}
      {has("compliance") && <ComplianceCard block={extra.compliance} />}
    </div>
  );
}
