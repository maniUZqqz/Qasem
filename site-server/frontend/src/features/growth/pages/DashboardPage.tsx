import { Link } from "react-router-dom";

import Icon from "../../../components/Icon";
import { DailyBarChart, StatRow, StatTile } from "../../../components/charts";
import { Alert, Badge, Button, Card, EmptyState, SectionTitle, fa } from "../../../components/ui";
import { useGet } from "../api";
import HBars from "../components/dashboard/Bars";
import ExtraBlocks from "../components/dashboard/ExtraBlocks";
import { JobBadge, LoadState } from "../components/bits";
import { faAgo, faDateTime, num } from "../format";
import type { Dashboard } from "../types";

const pct = (part: number, total: number) => (total > 0 ? `${fa(Math.round((part * 100) / total))}٪ از لیدها` : undefined);

/** «داشبورد جذب مشتری»: every number is a count from the database (GET /growth/dashboard/). */
export default function DashboardPage() {
  const { data, loading, error, reload } = useGet<Dashboard>("/dashboard/");

  return (
    <div className="space-y-5" data-testid="growth-dashboard">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-lg font-bold" style={{ color: "var(--text)" }}>
            وضعیتِ فعلی
          </h2>
          {data && (
            <p className="text-xs" style={{ color: "var(--text-3)" }}>
              به‌روز شد: {faDateTime(data.generated_at)}
            </p>
          )}
        </div>
        <div className="flex flex-wrap gap-2">
          <Link to="/growth/discovery" className="no-underline">
            <Button size="sm">
              <Icon name="plus" size={14} />
              ثبت لید یا ورود از فایل
            </Button>
          </Link>
          <Button variant="secondary" size="sm" onClick={reload} disabled={loading}>
            <Icon name="refresh" size={14} />
            به‌روزرسانی
          </Button>
        </div>
      </div>

      <LoadState loading={loading && !data} error={error} onRetry={reload}>
        {data && <Body data={data} />}
      </LoadState>
    </div>
  );
}

function Body({ data }: { data: Dashboard }) {
  const t = data.totals;
  const nothingYet = t.leads === 0 && t.archived === 0;

  return (
    <>
      {nothingYet && (
        <Card>
          <EmptyState
            icon="users"
            title="هنوز لیدی ثبت نشده"
            description="اولین لید را با آدرسِ سایت یا پیجِ اینستاگرام ثبت کنید، یا یک فایل CSV بیاورید. تا چیزی ثبت نشود، همهٔ عددهای این صفحه صفر می‌مانند."
            action={
              <Link to="/growth/discovery" className="no-underline">
                <Button>شروعِ کشف مشتری</Button>
              </Link>
            }
          />
        </Card>
      )}

      <StatRow>
        <StatTile label="لیدها" value={num(t.leads)} hint="بدونِ بایگانی" />
        <StatTile label="تازه در ۷ روز" value={num(t.new_7d)} hint="ثبت‌شده در هفتهٔ اخیر" />
        <StatTile label="با وب‌سایت" value={num(t.with_website)} hint={pct(t.with_website, t.leads)} />
        <StatTile label="با اینستاگرام" value={num(t.with_instagram)} hint={pct(t.with_instagram, t.leads)} />
      </StatRow>
      <StatRow>
        <StatTile label="با تلفن" value={num(t.with_phone)} hint={pct(t.with_phone, t.leads)} />
        <StatTile label="با ایمیل" value={num(t.with_email)} hint={pct(t.with_email, t.leads)} />
        <StatTile label="با فرم تماس / تیکت" value={num(t.with_contact_form)} hint={pct(t.with_contact_form, t.leads)} />
        <Link to="/growth/discovery" className="no-underline" aria-label="تکراری‌های منتظرِ تصمیم">
          <StatTile
            label="تکراریِ منتظرِ تصمیم"
            value={num(data.pending_duplicates)}
            hint={data.pending_duplicates > 0 ? "در ورودی‌های CSV؛ برای تصمیم بزنید" : "چیزی منتظر نیست"}
          />
        </Link>
      </StatRow>
      {t.archived > 0 && (
        <p className="text-xs" style={{ color: "var(--text-3)" }}>
          {num(t.archived)} لید هم بایگانی شده‌اند و در عددهای بالا نیستند.{" "}
          <Link to="/growth/leads?archived=1">دیدنِ بایگانی</Link>
        </p>
      )}

      <ExtraBlocks extra={data.extra} />

      <div className="grid gap-4 lg:grid-cols-2">
        <DailyBarChart
          title="لیدهای تازه در ۱۴ روز اخیر"
          series="people"
          caption={`مجموع ${num(data.daily.reduce((sum, d) => sum + d.value, 0))}`}
          points={data.daily}
          format={(v) => num(v)}
        />
        <Card>
          <SectionTitle>لیدها بر پایهٔ وضعیت</SectionTitle>
          <HBars items={data.by_status.map((s) => ({ key: s.status, label: s.label, count: s.count }))} empty="هنوز لیدی نیست." />
        </Card>
      </div>

      <div className="grid gap-4 lg:grid-cols-3">
        <Card>
          <SectionTitle>لیدها بر پایهٔ روشِ کشف</SectionTitle>
          <HBars items={data.by_origin.map((o) => ({ key: o.origin, label: o.label, count: o.count }))} empty="هنوز لیدی نیست." />
        </Card>
        <Card>
          <SectionTitle>شهرهای پرتکرار</SectionTitle>
          <HBars items={data.top_cities.map((c) => ({ key: c.city, label: c.city, count: c.count }))} empty="هنوز شهری ثبت نشده." />
        </Card>
        <Card>
          <SectionTitle action={<Link to="/growth/discovery" className="text-xs">همه</Link>}>ورودی‌های اخیر</SectionTitle>
          {data.recent_jobs.length === 0 ? (
            <p className="py-6 text-center text-sm" style={{ color: "var(--text-3)" }}>
              هنوز فایلی وارد نشده.
            </p>
          ) : (
            <ul className="space-y-2.5" data-testid="recent-jobs">
              {data.recent_jobs.map((job) => (
                <li key={job.id}>
                  <Link to={`/growth/discovery?tab=csv&job=${job.id}`} className="block no-underline">
                    <div className="flex items-center justify-between gap-2">
                      <span className="min-w-0 truncate text-sm font-medium" dir="auto" style={{ color: "var(--text)" }}>
                        {job.file_name || `ورودی ${fa(job.id)}`}
                      </span>
                      <JobBadge status={job.status} label={job.status_label} />
                    </div>
                    <div className="mt-0.5 text-xs" style={{ color: "var(--text-3)" }}>
                      {num(job.created_count)} لید تازه
                      {job.duplicate_count > 0 && ` · ${num(job.duplicate_count)} تکراری`}
                      {job.error_count > 0 && ` · ${num(job.error_count)} خطا`} · {faAgo(job.queued_at)}
                    </div>
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>

      <div className="grid gap-4 lg:grid-cols-3">
        <div className="lg:col-span-2">
          <Card>
            <SectionTitle action={<Link to="/growth/leads" className="text-xs">همهٔ لیدها</Link>}>آخرین رویدادها</SectionTitle>
            {data.recent_activity.length === 0 ? (
              <p className="py-6 text-center text-sm" style={{ color: "var(--text-3)" }}>
                هنوز رویدادی ثبت نشده.
              </p>
            ) : (
              <ul className="divide-y" style={{ borderColor: "var(--line)" }} data-testid="recent-activity">
                {data.recent_activity.map((a) => (
                  <li key={a.id} className="flex flex-wrap items-center gap-x-3 gap-y-1 py-2.5 text-sm">
                    <Link to={`/growth/leads/${a.lead_id}`} className="font-medium" dir="auto">
                      {a.lead_name}
                    </Link>
                    <Badge>{a.kind_label}</Badge>
                    {a.summary && (
                      <span className="min-w-0 truncate" style={{ color: "var(--text-3)" }} dir="auto">
                        {a.summary}
                      </span>
                    )}
                    <span className="mr-auto text-xs" style={{ color: "var(--text-3)" }}>
                      {a.actor_name ? `${a.actor_name} · ` : ""}
                      {faAgo(a.created_at)}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </Card>
        </div>
        <Card>
          <SectionTitle>به‌زودی</SectionTitle>
          <p className="mb-2 text-xs" style={{ color: "var(--text-3)" }}>
            این بخش‌ها هنوز ساخته نشده‌اند و عددی ندارند؛ وقتی آماده شوند همین‌جا می‌آیند.
          </p>
          <ul className="space-y-2" data-testid="coming-soon">
            {data.coming_soon.map((item) => (
              <li key={item.key} className="flex items-start justify-between gap-2 text-sm" style={{ color: "var(--text-2)" }}>
                <span>{item.title}</span>
                <Badge>{item.milestone}</Badge>
              </li>
            ))}
          </ul>
        </Card>
      </div>

      <Alert tone="info" title="یادآوری">
        هیچ پیامی بدونِ تأییدِ شما فرستاده نمی‌شود، و اینستاگرام هیچ‌وقت توسطِ سیستم خوانده نمی‌شود؛ فقط آدرسی که شما می‌دهید ذخیره می‌شود.
      </Alert>
    </>
  );
}
