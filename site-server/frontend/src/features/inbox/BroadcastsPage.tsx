import { useCallback, useEffect, useState } from "react";

import { errorMessage } from "../../api/client";
import { Alert, Badge, Button, Card, ErrorBox, Field, Input, SectionTitle, Select, Spinner } from "../../components/ui";
import {
  BroadcastPreview, BroadcastRow, CHANNEL_TITLE, RECIPIENT_STATUS_TITLE, SKIP_REASON_TITLE, Segment, del, get, patch, post,
} from "./api";
import { dateTimeText, faNum, toInt, toLocalInput } from "./format";
import { useInbox } from "./InboxLayout";

const STATUS_TONE: Record<string, "neutral" | "warn" | "ok" | "bad" | "info" | "brand"> = {
  DRAFT: "neutral", PENDING: "warn", APPROVED: "info", SENDING: "brand", SENT: "ok", REJECTED: "bad", CANCELLED: "neutral",
};

type Info = { broadcasts: BroadcastRow[]; can_approve: boolean; sendable_channels: string[]; rates: Record<string, number> };

function Preview({ data }: { data: BroadcastPreview }) {
  return (
    <div className="grid gap-3 *:min-w-0">
      <div className="flex flex-wrap gap-4 text-sm" style={{ color: "var(--text-2)" }}>
        <span><b>{faNum(data.recipients)}</b> گیرنده (از {faNum(data.people)} مخاطب)</span>
        {Object.entries(data.per_channel).map(([k, n]) => <span key={k}>{CHANNEL_TITLE[k] ?? k}: <b>{faNum(n)}</b></span>)}
        <span>زمان تقریبی: <b>{data.estimated_minutes ? `${faNum(data.estimated_minutes)} دقیقه` : "کمتر از یک دقیقه"}</b></span>
      </div>
      <div className="flex flex-wrap gap-3 text-xs" style={{ color: "var(--text-3)" }}>
        <span>لغوکرده: {faNum(data.skipped.opted_out)}</span>
        <span>بدون راه ارسال: {faNum(data.skipped.no_address)}</span>
        {data.channels_off.length > 0 && <span>کانال خاموش: {data.channels_off.map((k) => CHANNEL_TITLE[k] ?? k).join("، ")}</span>}
      </div>
      {data.warnings.map((w) => <Alert key={w} tone="warn">{w}</Alert>)}
      {data.samples.map((s, i) => (
        <div key={i}>
          <div className="mb-1 text-xs" style={{ color: "var(--text-3)" }}>نمونه برای «{s.to}» در {CHANNEL_TITLE[s.channel] ?? s.channel}</div>
          <div className="ib-preview">{s.text}</div>
        </div>
      ))}
    </div>
  );
}

function Editor({ storeId, info, segments, onDone, existing }: { storeId: string; info: Info; segments: Segment[]; onDone: () => void; existing?: BroadcastRow }) {
  const [name, setName] = useState(existing?.name ?? "");
  const [text, setText] = useState(existing?.text ?? "");
  const [channels, setChannels] = useState<string[]>(existing?.channels ?? []);
  const [segmentId, setSegmentId] = useState<string>(existing?.segment_id ? String(existing.segment_id) : "");
  const [dedupe, setDedupe] = useState(existing?.dedupe ?? true);
  // The server sends UTC («…T05:30:00Z»); the box shows the browser's own clock («09:00»), and
  // `new Date(when).toISOString()` below turns it back - so editing never shifts the time.
  const [when, setWhen] = useState(toLocalInput(existing?.scheduled_at));
  const [saved, setSaved] = useState<BroadcastRow | null>(existing ?? null);
  const [preview, setPreview] = useState<BroadcastPreview | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const body = () => ({
    name, text, channels, dedupe,
    segment_id: segmentId ? Number(segmentId) : null,
    scheduled_at: when ? new Date(when).toISOString() : null,
  });

  const save = async (): Promise<BroadcastRow | null> => {
    try {
      const row = saved ? await patch<BroadcastRow>(storeId, `broadcasts/${saved.id}/`, body()) : await post<BroadcastRow>(storeId, "broadcasts/", body());
      setSaved(row);
      setError(null);
      return row;
    } catch (err) {
      setError(errorMessage(err));
      return null;
    }
  };

  const doPreview = async () => {
    setBusy(true);
    const row = await save();
    if (row) {
      try {
        setPreview(await get<BroadcastPreview>(storeId, `broadcasts/${row.id}/preview/`));
      } catch (err) {
        setError(errorMessage(err));
      }
    }
    setBusy(false);
  };

  const submit = async () => {
    setBusy(true);
    const row = await save();
    if (row) {
      try {
        await post(storeId, `broadcasts/${row.id}/submit/`);
        onDone();
      } catch (err) {
        setError(errorMessage(err));
      }
    }
    setBusy(false);
  };

  return (
    <Card>
      <SectionTitle>{existing ? "ویرایش پیش‌نویس" : "ارسال گروهی تازه"}</SectionTitle>
      <div className="grid gap-3 *:min-w-0">
        <Field label="نام (فقط برای خودتان)"><Input value={name} onChange={(e) => setName(e.target.value)} placeholder="تخفیف آخر هفته" /></Field>
        <Field label="متن پیام" hint="«{name}» با نام مشتری پر می‌شود. «برای لغو، لغو را بفرستید» خودکار ته پیام می‌آید.">
          <textarea className="u-input" rows={4} value={text} onChange={(e) => setText(e.target.value)} aria-label="متن ارسال گروهی" />
        </Field>
        <Field label="به چه کسانی؟">
          <Select value={segmentId} onChange={(e) => setSegmentId(e.target.value)}>
            <option value="">همهٔ مخاطبان</option>
            {segments.map((s) => <option key={s.id} value={s.id}>{s.name} {s.count !== null ? `(${faNum(s.count)} نفر)` : ""}</option>)}
          </Select>
        </Field>
        <Field label="از کدام کانال‌ها؟" hint={info.sendable_channels.length ? "" : "هیچ کانالی روشن نیست؛ اول از «کانال‌ها» یکی را وصل کنید."}>
          <div className="flex flex-wrap gap-2">
            {info.sendable_channels.map((k) => (
              <label key={k} className={`ib-pill ${channels.includes(k) ? "on" : ""}`} style={{ cursor: "pointer" }}>
                <input type="checkbox" className="sr-only" checked={channels.includes(k)} onChange={(e) => setChannels(e.target.checked ? [...channels, k] : channels.filter((x) => x !== k))} />
                {CHANNEL_TITLE[k] ?? k} <span className="n">{faNum(info.rates[k] ?? 0)}/دقیقه</span>
              </label>
            ))}
          </div>
        </Field>
        <label className="flex items-center gap-2 text-sm" style={{ color: "var(--text-2)" }}>
          <input type="checkbox" checked={dedupe} onChange={(e) => setDedupe(e.target.checked)} />
          هر نفر فقط یک پیام بگیرد (روی بهترین کانالش)، نه یکی در هر کانال
        </label>
        <Field label="زمان‌بندی (اختیاری)" hint="بعد از تأیید، در این زمان شروع می‌شود؛ خالی = بلافاصله بعد از تأیید.">
          <input type="datetime-local" className="u-input" value={when} onChange={(e) => setWhen(e.target.value)} style={{ width: 230 }} />
        </Field>
        <ErrorBox message={error} />
        {preview && <Preview data={preview} />}
        <div className="flex flex-wrap gap-2">
          <Button size="sm" variant="secondary" disabled={busy || !text.trim() || !name.trim()} onClick={() => void doPreview()}>پیش‌نمایش گیرنده‌ها</Button>
          <Button size="sm" disabled={busy || !text.trim() || !name.trim()} onClick={() => void submit()}>فرستادن برای تأیید مالک</Button>
          <Button size="sm" variant="ghost" onClick={onDone}>بستن</Button>
        </div>
        <p className="text-xs" style={{ color: "var(--text-3)" }}>هیچ پیامی بدون تأیید مالک یا مدیر فرستاده نمی‌شود، و پیش‌نمایش چیزی نمی‌فرستد.</p>
      </div>
    </Card>
  );
}

function Detail({ storeId, row, canApprove, onChanged }: { storeId: string; row: BroadcastRow; canApprove: boolean; onChanged: () => void }) {
  const [detail, setDetail] = useState<BroadcastRow | null>(null);
  const [preview, setPreview] = useState<BroadcastPreview | null>(null);
  const [note, setNote] = useState("");
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    get<BroadcastRow>(storeId, `broadcasts/${row.id}/`).then(setDetail).catch((e) => setError(errorMessage(e)));
    if (row.status === "PENDING" || row.status === "DRAFT") get<BroadcastPreview>(storeId, `broadcasts/${row.id}/preview/`).then(setPreview).catch(() => undefined);
  }, [storeId, row.id, row.status]);
  const act = async (action: string, extra?: unknown) => {
    try {
      await post(storeId, `broadcasts/${row.id}/${action}/`, extra);
      onChanged();
    } catch (err) {
      setError(errorMessage(err));
    }
  };
  const stats = detail?.stats ?? row.stats;
  const n = (k: string) => (typeof stats[k] === "number" ? (stats[k] as number) : 0);
  return (
    <div className="grid gap-3 p-3 *:min-w-0" style={{ background: "var(--surface-2)", borderRadius: 12 }}>
      <div className="ib-preview">{row.text}</div>
      {(row.status === "SENDING" || row.status === "SENT") && (
        <div className="flex flex-wrap gap-4 text-sm" style={{ color: "var(--text-2)" }}>
          <span>فرستاده شد: <b>{faNum(n("sent"))}</b></span>
          <span>در صف: <b>{faNum(n("queued"))}</b></span>
          <span>ناموفق: <b style={{ color: n("failed") ? "var(--bad)" : undefined }}>{faNum(n("failed"))}</b></span>
          <span>ردشده (مثلاً لغو): <b>{faNum(n("skipped"))}</b></span>
          {n("fallback") > 0 && <span>رفته به کانال بعدی: <b>{faNum(n("fallback"))}</b></span>}
        </div>
      )}
      {preview && <Preview data={preview} />}
      {row.review_note && <Alert tone="warn" title="دلیل ردشدن">{row.review_note}</Alert>}
      {detail?.recipients_sample && detail.recipients_sample.length > 0 && (row.status === "SENDING" || row.status === "SENT") && (
        <details>
          <summary className="cursor-pointer text-xs" style={{ color: "var(--text-3)" }}>چند گیرنده</summary>
          <ul className="mt-1 text-xs" style={{ color: "var(--text-2)" }}>
            {detail.recipients_sample.map((r, i) => (
              <li key={i}>{r.contact__name || r.contact__phone || "—"} · {CHANNEL_TITLE[r.channel] ?? r.channel} · {r.status_title ?? RECIPIENT_STATUS_TITLE[r.status] ?? r.status}{r.skip_reason ? ` (${r.skip_reason_title || SKIP_REASON_TITLE[r.skip_reason] || r.skip_reason})` : ""}{r.error ? ` — ${r.error}` : ""}</li>
            ))}
          </ul>
        </details>
      )}
      <ErrorBox message={error} />
      <div className="flex flex-wrap items-center gap-2">
        {row.status === "PENDING" && canApprove && (
          <>
            <Button size="sm" onClick={() => void act("approve")}>تأیید و شروع ارسال</Button>
            <Input value={note} onChange={(e) => setNote(e.target.value)} placeholder="دلیل رد (اختیاری)" style={{ width: 220 }} aria-label="دلیل رد" />
            <Button size="sm" variant="danger" onClick={() => void act("reject", { note })}>رد کن</Button>
          </>
        )}
        {row.status === "PENDING" && !canApprove && (
          <span className="text-xs" style={{ color: "var(--text-3)" }}>{row.cannot_approve_reason || "منتظر تأیید مالک یا مدیر."}</span>
        )}
        {["DRAFT", "REJECTED"].includes(row.status) && <Button size="sm" onClick={() => void act("submit")}>فرستادن برای تأیید</Button>}
        {["APPROVED", "SENDING", "PENDING"].includes(row.status) && <Button size="sm" variant="ghost" onClick={() => void act("cancel")}>لغو</Button>}
        {["DRAFT", "REJECTED", "CANCELLED"].includes(row.status) && (
          <Button size="sm" variant="ghost" onClick={async () => { await del(storeId, `broadcasts/${row.id}/`); onChanged(); }}>حذف</Button>
        )}
      </div>
    </div>
  );
}

function RateLimits({ storeId, rates, canEdit, onSaved }: { storeId: string; rates: Record<string, number>; canEdit: boolean; onSaved: () => void }) {
  const [values, setValues] = useState<Record<string, string>>(() => Object.fromEntries(Object.entries(rates).map(([k, v]) => [k, String(v)])));
  const [note, setNote] = useState<string | null>(null);
  const save = async () => {
    const body = Object.fromEntries(Object.entries(values).map(([k, v]) => [k, toInt(v, 0)]));
    await patch(storeId, "settings/", { rate_limits: body });
    setNote("ذخیره شد.");
    onSaved();
  };
  return (
    <Card>
      <SectionTitle>سقفِ ارسال در دقیقه برای هر کانال</SectionTitle>
      <p className="mb-3 text-xs leading-6" style={{ color: "var(--text-3)" }}>
        پلتفرم‌ها ارسالِ پشت‌سرهمِ زیاد را اسپم می‌دانند و ربات را مسدود می‌کنند. این سقف برای همهٔ ارسال‌های گروهیِ فروشگاه روی هم حساب می‌شود (حداکثر ۱۲۰). پیش‌فرض‌ها محتاط‌اند.
      </p>
      <div className="flex flex-wrap gap-3">
        {Object.keys(values).map((k) => (
          <Field key={k} label={CHANNEL_TITLE[k] ?? k}>
            <Input value={values[k]} inputMode="numeric" disabled={!canEdit} style={{ width: 90 }} onChange={(e) => setValues({ ...values, [k]: e.target.value })} aria-label={`سقف ${CHANNEL_TITLE[k] ?? k}`} />
          </Field>
        ))}
      </div>
      {canEdit && <div className="mt-3 flex items-center gap-3"><Button size="sm" variant="secondary" onClick={() => void save()}>ذخیرهٔ سقف‌ها</Button>{note && <span className="text-xs" style={{ color: "var(--ok)" }}>{note}</span>}</div>}
    </Card>
  );
}

export default function BroadcastsPage() {
  const { storeId, me } = useInbox();
  const [info, setInfo] = useState<Info | null>(null);
  const [segments, setSegments] = useState<Segment[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [creating, setCreating] = useState<BroadcastRow | "new" | null>(null);
  const [open, setOpen] = useState<number | null>(null);

  const load = useCallback(async () => {
    try {
      setInfo(await get<Info>(storeId, "broadcasts/"));
      setError(null);
    } catch (err) {
      setError(errorMessage(err));
    }
  }, [storeId]);

  useEffect(() => {
    void load();
    get<{ segments: Segment[] }>(storeId, "segments/").then((r) => setSegments(r.segments)).catch(() => undefined);
    const timer = window.setInterval(() => document.visibilityState === "visible" && void load(), 10000);
    return () => window.clearInterval(timer);
  }, [load, storeId]);

  if (!info) return <div className="py-10 text-center">{error ? <ErrorBox message={error} /> : <Spinner />}</div>;

  return (
    <div className="grid gap-4 *:min-w-0">
      <ErrorBox message={error} />
      <Alert tone="info" title="چطور کار می‌کند">
        متن را بنویسید، بخشی از مشتری‌ها را انتخاب کنید و پیش‌نمایش بگیرید؛ بعد برای تأیید مالک بفرستید. بعد از تأیید، پیام‌ها با سقفِ هر کانال (پیام در دقیقه) فرستاده می‌شوند و هر کس که «لغو» بفرستد همان لحظه کنار گذاشته می‌شود.
      </Alert>
      <div>
        <Button onClick={() => setCreating("new")} disabled={!me?.can_write && !me?.can_settings}>+ ارسال گروهی تازه</Button>
      </div>
      {creating && (
        <Editor storeId={storeId} info={info} segments={segments} existing={creating === "new" ? undefined : creating} onDone={() => { setCreating(null); void load(); }} />
      )}
      <RateLimits storeId={storeId} rates={info.rates} canEdit={info.can_approve} onSaved={() => void load()} />
      <Card padded={false}>
        <div className="ib-table-wrap">
          <table className="u-table">
            <thead><tr><th>نام</th><th>بخش</th><th>کانال‌ها</th><th>وضعیت</th><th>سازنده</th><th>ساخته شد</th><th /></tr></thead>
            <tbody>
              {info.broadcasts.length === 0 && <tr><td colSpan={7} className="p-6 text-center" style={{ color: "var(--text-3)" }}>هنوز ارسال گروهی نساخته‌اید.</td></tr>}
              {info.broadcasts.map((b) => (
                <>
                  <tr key={b.id}>
                    <td><b>{b.name}</b>{b.is_test && <Badge tone="warn">آزمایشی</Badge>}</td>
                    <td>{b.segment_name}</td>
                    <td>{b.channels.map((k) => CHANNEL_TITLE[k] ?? k).join("، ") || "همه"}</td>
                    <td><Badge tone={STATUS_TONE[b.status] ?? "neutral"}>{b.status_title}</Badge>{b.scheduled_at && b.status !== "SENT" && <div className="text-xs" style={{ color: "var(--text-3)" }}>{dateTimeText(b.scheduled_at)}</div>}</td>
                    <td>{b.created_by || "API"}</td>
                    <td>{dateTimeText(b.created_at)}</td>
                    <td className="whitespace-nowrap">
                      <Button size="sm" variant="ghost" onClick={() => setOpen(open === b.id ? null : b.id)}>{open === b.id ? "بستن" : "جزئیات"}</Button>
                      {["DRAFT", "REJECTED"].includes(b.status) && <Button size="sm" variant="ghost" onClick={() => setCreating(b)}>ویرایش</Button>}
                    </td>
                  </tr>
                  {open === b.id && (
                    <tr key={`${b.id}-d`}><td colSpan={7}><Detail storeId={storeId} row={b} canApprove={b.can_approve ?? info.can_approve} onChanged={() => void load()} /></td></tr>
                  )}
                </>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  );
}
