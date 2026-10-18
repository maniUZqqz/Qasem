import { useCallback, useEffect, useState } from "react";
import { useParams } from "react-router-dom";

import { api, errorMessage } from "../../api/client";
import Icon from "../../components/Icon";
import {
  Alert,
  Badge,
  Button,
  Card,
  EmptyState,
  ErrorBox,
  Field,
  Input,
  PageHeader,
  SectionTitle,
  Select,
  Spinner,
  Stat,
  TextArea,
  fa,
} from "../../components/ui";
import CallPanel from "./CallPanel";

/**
 * صفحه ۷ — بازاریابی تلفنی.
 *
 * **خودِ فهرست** ستون فقرات صفحه است: با چه کسی حرف زده‌ای، چه گفت، و قدم
 * بعدی کِی است. چیزی که امروز در ذهن یا دفترچه است، و چیزی که معامله را
 * می‌بازد فراموش کردن زنگ سه‌شنبه است.
 *
 * **ضبط و تحلیل تماس هم ساخته شد** — با یک شرط که در مدل نشسته نه در این
 * صفحه: تا رضایت طرف مقابل ثبت نشود، فایلی ذخیره نمی‌شود. قید حقوقی، یک
 * قابلیتِ نساخته بود نه یک دلیلِ نساختن.
 *
 * **جست‌وجوی شماره ساخته نشد و کلیدی هم برای روشن کردنش نیست.** پیدا کردن
 * حساب‌های کسی از روی شماره‌اش، مکانیزم آزار آدم‌هاست و فقط با سوءاستفاده از
 * API پلتفرم‌ها کار می‌کند. آنچه واقعاً لازم است — «این شماره را می‌شناسیم؟» —
 * از روی داده‌های خودِ فروشگاه جواب داده می‌شود.
 *
 * پس صفحه با «امروز باید زنگ بزنی» باز می‌شود، نه با «آخرین اضافه‌شده‌ها».
 * فهرستی که با ترتیب ورود باز شود، فهرستی است که بار دوم باز نمی‌شود.
 */

type Prospect = {
  id: number;
  company: string;
  website: string;
  person: string;
  role: string;
  phone: string;
  email: string;
  social: string;
  stage: string;
  stage_label: string;
  notes: string;
  last_outcome: string;
  last_contact_at: string | null;
  next_action: string;
  next_action_at: string | null;
  is_due: boolean;
  is_closed: boolean;
};

type Payload = {
  prospects: Prospect[];
  due: Prospect[];
  counts: { total: number; due: number; open: number; by_stage: Record<string, number> };
  stages: { value: string; label: string }[];
  held: { title: string; why: string }[];
  built_since: { title: string; note: string }[];
};

const EMPTY = {
  company: "",
  person: "",
  role: "",
  phone: "",
  website: "",
  social: "",
  next_action: "",
  next_action_at: "",
};

/** `2026-09-20T10:00:00Z` → `2026-09-20T10:00`, which is what `datetime-local`
 *  wants. An ISO string with seconds silently renders as an empty box. */
function forInput(iso: string | null): string {
  return iso ? iso.slice(0, 16) : "";
}

export default function OutreachPage() {
  const { id } = useParams<{ id: string }>();
  const [data, setData] = useState<Payload | null>(null);
  const [form, setForm] = useState({ ...EMPTY });
  const [adding, setAdding] = useState(false);
  const [editing, setEditing] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      const { data: body } = await api.get<Payload>(`/stores/${id}/prospects/`);
      setData(body);
      setError(null);
    } catch (err) {
      setError(errorMessage(err));
    }
  }, [id]);

  useEffect(() => {
    void load();
  }, [load]);

  if (!data) return error ? <ErrorBox message={error} /> : <Spinner />;

  const add = async () => {
    if (!form.company.trim()) return;
    setBusy(true);
    try {
      await api.post(`/stores/${id}/prospects/`, {
        ...form,
        next_action_at: form.next_action_at || null,
      });
      setForm({ ...EMPTY });
      setAdding(false);
      await load();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const patch = async (row: Prospect, changes: Partial<Prospect>) => {
    setBusy(true);
    try {
      await api.patch(`/stores/${id}/prospects/${row.id}/`, changes);
      await load();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const remove = async (row: Prospect) => {
    if (!window.confirm(`«${row.company}» از فهرست پاک شود؟`)) return;
    setBusy(true);
    try {
      await api.delete(`/stores/${id}/prospects/${row.id}/`);
      await load();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div>
      <PageHeader
        title="بازاریابی تلفنی"
        subtitle="با چه کسی حرف زده‌ای، چه گفت، و قدم بعدی کِی است."
        actions={
          <Button onClick={() => setAdding(!adding)}>
            <Icon name={adding ? "x" : "plus"} />
            {adding ? "انصراف" : "افزودن کسب‌وکار"}
          </Button>
        }
      />

      <ErrorBox message={error} />

      <div className="mb-4 grid gap-3 sm:grid-cols-3">
        <Stat value={fa(data.counts.due)} label="امروز باید زنگ بزنی" tone={data.counts.due ? "warn" : undefined} />
        <Stat value={fa(data.counts.open)} label="باز" />
        <Stat value={fa(data.counts.total)} label="کل فهرست" />
      </div>

      {/* --------------------------------------------------- فرم افزودن */}
      {adding && (
        <Card className="mb-4">
          <SectionTitle>کسب‌وکار تازه</SectionTitle>
          <div className="grid gap-4 md:grid-cols-2">
            <Field label="کسب‌وکار">
              <Input
                value={form.company}
                onChange={(e) => setForm({ ...form, company: e.target.value })}
                placeholder="اسم شرکت یا فروشگاه"
              />
            </Field>
            <Field label="سایت">
              <Input
                dir="ltr"
                value={form.website}
                onChange={(e) => setForm({ ...form, website: e.target.value })}
              />
            </Field>
            <Field label="شخص">
              <Input
                value={form.person}
                onChange={(e) => setForm({ ...form, person: e.target.value })}
              />
            </Field>
            <Field label="سمت">
              <Input
                value={form.role}
                onChange={(e) => setForm({ ...form, role: e.target.value })}
                placeholder="مثلاً مدیر بازاریابی"
              />
            </Field>
            <Field label="تلفن">
              <Input
                dir="ltr"
                value={form.phone}
                onChange={(e) => setForm({ ...form, phone: e.target.value })}
              />
            </Field>
            <Field label="آی‌دی شبکه‌ی اجتماعی" hint="اگر خودتان پیدا کردید">
              <Input
                dir="ltr"
                value={form.social}
                onChange={(e) => setForm({ ...form, social: e.target.value })}
              />
            </Field>
            <Field label="قدم بعدی">
              <Input
                value={form.next_action}
                onChange={(e) => setForm({ ...form, next_action: e.target.value })}
                placeholder="مثلاً زنگ بزن و نمونه بفرست"
              />
            </Field>
            <Field label="کِی" hint="بدون تاریخ، هیچ‌وقت یادآوری نمی‌شود.">
              <Input
                type="datetime-local"
                value={form.next_action_at}
                onChange={(e) => setForm({ ...form, next_action_at: e.target.value })}
              />
            </Field>
          </div>
          <div className="mt-4">
            <Button onClick={add} disabled={busy || !form.company.trim()}>
              <Icon name="check" /> اضافه کن
            </Button>
          </div>
        </Card>
      )}

      {/* ----------------------------------------------- امروز باید زنگ بزنی */}
      {data.due.length > 0 && (
        <Card className="mb-4">
          <SectionTitle>امروز باید زنگ بزنی</SectionTitle>
          <div className="grid gap-2">
            {data.due.map((row) => (
              <div
                key={row.id}
                className="flex flex-wrap items-center justify-between gap-2 rounded-xl px-3 py-2"
                style={{ background: "var(--warn-soft, var(--surface-2))" }}
              >
                <span>
                  <span className="font-bold">{row.company}</span>
                  {row.next_action && (
                    <span className="mr-2 text-sm" style={{ color: "var(--text-2)" }}>
                      — {row.next_action}
                    </span>
                  )}
                </span>
                <span className="flex items-center gap-2">
                  {row.phone && (
                    <a href={`tel:${row.phone}`} dir="ltr" className="text-sm">
                      {row.phone}
                    </a>
                  )}
                  <Button
                    variant="ghost"
                    onClick={() => setEditing(editing === row.id ? null : row.id)}
                  >
                    ثبت نتیجه
                  </Button>
                </span>
              </div>
            ))}
          </div>
        </Card>
      )}

      {/* -------------------------------------------------------- فهرست */}
      <Card className="mb-4">
        <SectionTitle>همه</SectionTitle>
        {data.prospects.length === 0 ? (
          <EmptyState
            icon="users"
            title="فهرست خالی است"
            description="کسب‌وکارهایی را که می‌خواهی به آن‌ها بفروشی اینجا بنویس. مهم‌ترین ستون، «قدم بعدی کِی» است."
          />
        ) : (
          <div className="grid gap-2">
            {data.prospects.map((row) => (
              <div key={row.id} className="rounded-xl p-3" style={{ background: "var(--surface-2)" }}>
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <span className="flex flex-wrap items-center gap-2">
                    <span className="font-bold">{row.company}</span>
                    {row.person && (
                      <span className="text-sm" style={{ color: "var(--text-2)" }}>
                        {row.person}
                        {row.role && ` — ${row.role}`}
                      </span>
                    )}
                    <Badge tone={row.is_due ? "warn" : row.is_closed ? "neutral" : "brand"}>
                      {row.stage_label}
                    </Badge>
                  </span>
                  <span className="flex items-center gap-2">
                    <Select
                      value={row.stage}
                      onChange={(e) => patch(row, { stage: e.target.value })}
                      disabled={busy}
                      // `.u-input` is `width: 100%`, which inside a flex row
                      // collapses to nothing and spills the label outside the
                      // box. Inline so it beats the stylesheet either way.
                      style={{ width: "auto", minWidth: "9.5rem" }}
                    >
                      {data.stages.map((s) => (
                        <option key={s.value} value={s.value}>
                          {s.label}
                        </option>
                      ))}
                    </Select>
                    <Button
                      variant="ghost"
                      onClick={() => setEditing(editing === row.id ? null : row.id)}
                    >
                      <Icon name={editing === row.id ? "up" : "down"} />
                    </Button>
                    <Button variant="ghost" onClick={() => remove(row)} disabled={busy}>
                      <Icon name="trash" />
                    </Button>
                  </span>
                </div>

                {row.last_outcome && (
                  <p className="mt-2 text-sm" style={{ color: "var(--text-2)" }}>
                    آخرین بار: {row.last_outcome}
                  </p>
                )}

                {editing === row.id && (
                  <>
                    <EditRow row={row} stages={data.stages} busy={busy} onSave={patch} />
                    <CallPanel storeId={id!} prospectId={row.id} />
                  </>
                )}
              </div>
            ))}
          </div>
        )}
      </Card>

      {/* --------------------------------------------- چه چیزی عمداً نیست */}
      {data.built_since?.length > 0 && (
        <Alert tone="ok" title="آنچه اضافه شد">
          <ul className="mt-1 grid gap-1 text-sm">
            {data.built_since.map((b) => (
              <li key={b.title}>
                <span className="font-medium">{b.title}</span> — {b.note}
              </li>
            ))}
          </ul>
        </Alert>
      )}

      <div className="mt-3">
        <Alert tone="info" title="آنچه عمداً ساخته نشده">
          <ul className="mt-1 grid gap-1 text-sm">
            {data.held.map((h) => (
              <li key={h.title}>
                <span className="font-medium">{h.title}</span> — {h.why}
              </li>
            ))}
          </ul>
        </Alert>
      </div>
    </div>
  );
}

function EditRow({
  row,
  stages,
  busy,
  onSave,
}: {
  row: Prospect;
  stages: { value: string; label: string }[];
  busy: boolean;
  onSave: (row: Prospect, changes: Partial<Prospect>) => Promise<void>;
}) {
  const [outcome, setOutcome] = useState(row.last_outcome);
  const [next, setNext] = useState(row.next_action);
  const [when, setWhen] = useState(forInput(row.next_action_at));
  const [notes, setNotes] = useState(row.notes);
  const [stage, setStage] = useState(row.stage);

  return (
    <div className="mt-3 grid gap-4 border-t pt-3" style={{ borderColor: "var(--line)" }}>
      <div className="grid gap-4 md:grid-cols-2">
        <Field label="نتیجه‌ی این تماس">
          <Input value={outcome} onChange={(e) => setOutcome(e.target.value)} />
        </Field>
        <Field label="مرحله">
          <Select value={stage} onChange={(e) => setStage(e.target.value)}>
            {stages.map((s) => (
              <option key={s.value} value={s.value}>
                {s.label}
              </option>
            ))}
          </Select>
        </Field>
        <Field label="قدم بعدی">
          <Input value={next} onChange={(e) => setNext(e.target.value)} />
        </Field>
        <Field label="کِی">
          <Input
            type="datetime-local"
            value={when}
            onChange={(e) => setWhen(e.target.value)}
          />
        </Field>
      </div>
      <Field label="یادداشت">
        <TextArea rows={2} value={notes} onChange={(e) => setNotes(e.target.value)} />
      </Field>
      <div>
        <Button
          disabled={busy}
          onClick={() =>
            onSave(row, {
              last_outcome: outcome,
              next_action: next,
              // Empty means "no follow-up", which is a real answer — sending
              // "" instead of null makes the date field reject it.
              next_action_at: when || null,
              notes,
              stage,
              last_contact_at: new Date().toISOString(),
            } as Partial<Prospect>)
          }
        >
          <Icon name="check" /> ثبت
        </Button>
      </div>
    </div>
  );
}
