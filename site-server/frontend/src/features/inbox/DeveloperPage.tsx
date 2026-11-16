import { Fragment, useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { errorMessage } from "../../api/client";
import { Alert, Badge, Button, Card, ErrorBox, Field, Input, SectionTitle, Spinner } from "../../components/ui";
import { ChannelInfo, WebhookRow, del, get, patch, post } from "./api";
import { copy, dateTimeText, faNum } from "./format";
import { useInbox } from "./InboxLayout";

type Docs = { markdown: string; base: string; header: string; scopes: string[]; events: { key: string; title: string }[] };

/** نمایش‌دهندهٔ کوچکِ Markdown (تیتر، فهرست، جدول، کد) — بدون هیچ وابستگیِ تازه. */
function Markdown({ text }: { text: string }) {
  const blocks: JSX.Element[] = [];
  const lines = text.split("\n");
  let i = 0;
  let key = 0;
  const inline = (s: string) =>
    s.split(/(`[^`]+`)/g).map((part, n) =>
      part.startsWith("`") && part.endsWith("`") ? <code key={n}>{part.slice(1, -1)}</code> : <Fragment key={n}>{part.replace(/\*\*(.+?)\*\*/g, "$1")}</Fragment>,
    );
  while (i < lines.length) {
    const line = lines[i];
    if (line.startsWith("```")) {
      const buf: string[] = [];
      i++;
      while (i < lines.length && !lines[i].startsWith("```")) buf.push(lines[i++]);
      i++;
      blocks.push(<div key={key++} className="ib-code">{buf.join("\n")}</div>);
    } else if (/^#{1,3} /.test(line)) {
      const level = line.match(/^#+/)![0].length;
      const Tag = (`h${level}` as unknown) as "h1";
      blocks.push(<Tag key={key++}>{line.replace(/^#+ /, "")}</Tag>);
      i++;
    } else if (line.startsWith("|")) {
      const rows: string[][] = [];
      while (i < lines.length && lines[i].startsWith("|")) {
        if (!/^\|[\s|:-]+\|$/.test(lines[i])) rows.push(lines[i].split("|").slice(1, -1).map((c) => c.trim()));
        i++;
      }
      blocks.push(
        <table key={key++}>
          <thead><tr>{rows[0].map((c, n) => <th key={n}>{inline(c)}</th>)}</tr></thead>
          <tbody>{rows.slice(1).map((r, n) => <tr key={n}>{r.map((c, m) => <td key={m}>{inline(c)}</td>)}</tr>)}</tbody>
        </table>,
      );
    } else if (line.startsWith("- ")) {
      const items: string[] = [];
      while (i < lines.length && lines[i].startsWith("- ")) items.push(lines[i++].slice(2));
      blocks.push(<ul key={key++}>{items.map((it, n) => <li key={n}>{inline(it)}</li>)}</ul>);
    } else if (line.trim()) {
      blocks.push(<p key={key++}>{inline(line)}</p>);
      i++;
    } else i++;
  }
  return <div className="ib-doc">{blocks}</div>;
}

function Webhooks({ storeId, events }: { storeId: string; events: Docs["events"] }) {
  const [rows, setRows] = useState<WebhookRow[] | null>(null);
  const [url, setUrl] = useState("");
  const [picked, setPicked] = useState<string[]>([]);
  const [created, setCreated] = useState<WebhookRow | null>(null);
  const [open, setOpen] = useState<number | null>(null);
  const [detail, setDetail] = useState<WebhookRow | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setRows((await get<{ webhooks: WebhookRow[] }>(storeId, "dev/webhooks/")).webhooks);
    } catch (err) {
      setError(errorMessage(err));
    }
  }, [storeId]);
  useEffect(() => {
    void load();
  }, [load]);

  const add = async () => {
    try {
      const row = await post<WebhookRow>(storeId, "dev/webhooks/", { url, events: picked });
      setCreated(row);
      setUrl("");
      setPicked([]);
      setError(null);
      await load();
    } catch (err) {
      setError(errorMessage(err));
    }
  };

  const openDetail = async (id: number) => {
    if (open === id) return setOpen(null);
    setOpen(id);
    setDetail(await get<WebhookRow>(storeId, `dev/webhooks/${id}/`));
  };

  return (
    <Card>
      <SectionTitle>وب‌هوک‌های خروجی</SectionTitle>
      <p className="mb-3 text-xs leading-6" style={{ color: "var(--text-3)" }}>
        هر رویداد صندوق (پیام تازه، واگذاری، بسته‌شدن، رد شدن SLA…) با یک POST امضاشده به نشانی شما می‌رسد. نشانی باید عمومی باشد؛ نشانی‌های شبکهٔ داخلی پذیرفته نمی‌شوند.
      </p>
      <ErrorBox message={error} />
      {created && (
        <Alert tone="ok" title="نشانی ثبت شد">
          رمز امضا را برای تأیید درخواست‌ها نگه دارید: <span className="ib-code" style={{ display: "inline-block" }}>{created.secret}</span>
        </Alert>
      )}
      <div className="grid gap-2 *:min-w-0">
        {(rows ?? []).map((w) => (
          <div key={w.id} className="rounded-xl p-3" style={{ background: "var(--surface-2)", border: "1px solid var(--line)" }}>
            <div className="flex flex-wrap items-center gap-2">
              <span dir="ltr" className="text-sm" style={{ flex: 1, minWidth: 0, overflowWrap: "anywhere" }}>{w.url}</span>
              <Badge tone={w.active ? "ok" : "bad"}>{w.active ? "فعال" : "خاموش"}</Badge>
              <span className="text-xs" style={{ color: "var(--text-3)" }}>{w.events.length ? `${faNum(w.events.length)} رویداد` : "همهٔ رویدادها"}</span>
              <Button size="sm" variant="ghost" onClick={() => void openDetail(w.id)}>جزئیات</Button>
            </div>
            {w.last_status && <div className="mt-1 text-xs" style={{ color: "var(--text-3)" }}>آخرین وضعیت: {w.last_status === "OK" ? "رسید" : w.last_status}{w.failure_count ? ` · ${faNum(w.failure_count)} خطای پشت‌سرهم` : ""}</div>}
            {open === w.id && detail && (
              <div className="mt-3 grid gap-2">
                <div className="text-xs" style={{ color: "var(--text-3)" }}>رمز امضا</div>
                <div className="ib-code">{detail.secret}</div>
                <div className="flex flex-wrap gap-2">
                  <Button size="sm" variant="secondary" onClick={async () => { const r = await post<{ ok: boolean; response_code: number | null; error: string }>(storeId, `dev/webhooks/${w.id}/test/`); setNote(r.ok ? `رسید (${r.response_code})` : `نرسید: ${r.error || r.response_code}`); setDetail(await get<WebhookRow>(storeId, `dev/webhooks/${w.id}/`)); }}>
                    آزمایش
                  </Button>
                  <Button size="sm" variant="ghost" onClick={async () => { await patch(storeId, `dev/webhooks/${w.id}/`, { active: !w.active }); await load(); }}>{w.active ? "خاموش کن" : "روشن کن"}</Button>
                  <Button size="sm" variant="danger" onClick={async () => { await del(storeId, `dev/webhooks/${w.id}/`); setOpen(null); await load(); }}>حذف</Button>
                </div>
                {note && <div className="text-sm" style={{ color: "var(--text-2)" }}>{note}</div>}
                <table className="u-table">
                  <thead><tr><th>رویداد</th><th>وضعیت</th><th>تلاش</th><th>کد</th><th>زمان</th></tr></thead>
                  <tbody>
                    {(detail.deliveries ?? []).map((d) => (
                      <tr key={d.id}><td dir="ltr">{d.event}</td><td>{d.status === "OK" ? "رسید" : d.status === "PENDING" ? "در صف" : "ناموفق"}{d.error ? ` — ${d.error}` : ""}</td><td className="u-num">{faNum(d.attempts)}</td><td className="u-num">{d.response_code ?? "—"}</td><td>{dateTimeText(d.created_at)}</td></tr>
                    ))}
                    {(detail.deliveries ?? []).length === 0 && <tr><td colSpan={5} style={{ color: "var(--text-3)" }}>هنوز چیزی فرستاده نشده.</td></tr>}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        ))}
        {rows && rows.length === 0 && <span className="text-sm" style={{ color: "var(--text-3)" }}>هنوز نشانی‌ای ثبت نشده.</span>}
      </div>
      <div className="mt-4 grid gap-3">
        <Field label="نشانی تازه (https)">
          <Input dir="ltr" value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://example.ir/hooks/inbox" />
        </Field>
        <Field label="رویدادها" hint="هیچ‌کدام = همهٔ رویدادها">
          <div className="flex flex-wrap gap-2">
            {events.map((e) => (
              <label key={e.key} className={`ib-pill ${picked.includes(e.key) ? "on" : ""}`} style={{ cursor: "pointer" }} title={e.title}>
                <input type="checkbox" className="sr-only" checked={picked.includes(e.key)} onChange={(ev) => setPicked(ev.target.checked ? [...picked, e.key] : picked.filter((x) => x !== e.key))} />
                <span dir="ltr">{e.key}</span>
              </label>
            ))}
          </div>
        </Field>
        <div><Button size="sm" disabled={!url.trim()} onClick={() => void add()}>افزودن نشانی</Button></div>
      </div>
    </Card>
  );
}

export default function DeveloperPage() {
  const { storeId, me } = useInbox();
  const [docs, setDocs] = useState<Docs | null>(null);
  const [widget, setWidget] = useState<ChannelInfo | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!me?.can_settings) return;
    get<Docs>(storeId, "dev/docs/").then(setDocs).catch((e) => setError(errorMessage(e)));
    get<{ channels: ChannelInfo[] }>(storeId, "channels/").then((r) => setWidget(r.channels.find((c) => c.kind === "WEBCHAT") ?? null)).catch(() => undefined);
  }, [storeId, me?.can_settings]);

  if (!me) return <div className="py-10 text-center"><Spinner /></div>;
  if (!me.can_settings) return <Alert tone="info">این بخش فقط برای مالک یا مدیر فروشگاه است.</Alert>;
  if (!docs) return <div className="py-10 text-center">{error ? <ErrorBox message={error} /> : <Spinner />}</div>;

  return (
    <div className="grid gap-6 *:min-w-0">
      <ErrorBox message={error} />
      <Card>
        <SectionTitle>کلید API</SectionTitle>
        <p className="text-sm leading-7" style={{ color: "var(--text-2)" }}>
          کلید همین فروشگاه را از صفحهٔ <Link to={`/stores/${storeId}/api`} style={{ color: "var(--brand-strong)" }}>کلیدهای API</Link> بسازید و دسترسی‌های
          <span dir="ltr"> inbox_read </span> (خواندن) و <span dir="ltr"> inbox_write </span> (نوشتن) را به آن بدهید. کلید را در هدر <span dir="ltr">{docs.header}</span> بفرستید.
          کلید «تست» همهٔ بررسی‌ها را انجام می‌دهد ولی چیزی را تغییر نمی‌دهد.
        </p>
        <div className="mt-3 text-xs" style={{ color: "var(--text-3)" }}>نشانی پایه</div>
        <div className="flex gap-2">
          <div className="ib-code" style={{ flex: 1 }}>{docs.base}</div>
          <Button size="sm" variant="secondary" onClick={() => void copy(docs.base)}>کپی</Button>
        </div>
      </Card>

      {widget?.snippet && (
        <Card>
          <SectionTitle>ویجت چت سایت</SectionTitle>
          <p className="mb-2 text-xs" style={{ color: "var(--text-3)" }}>
            {widget.enabled ? "کانال چت سایت روشن است." : "کانال چت سایت هنوز روشن نیست؛ اول از «کانال‌ها» روشنش کنید."}
          </p>
          <div className="flex gap-2">
            <div className="ib-code" style={{ flex: 1 }}>{widget.snippet}</div>
            <Button size="sm" variant="secondary" onClick={() => void copy(widget.snippet ?? "")}>کپی</Button>
          </div>
        </Card>
      )}

      <Webhooks storeId={storeId} events={docs.events} />

      <Card>
        <SectionTitle>مستندات</SectionTitle>
        <Markdown text={docs.markdown} />
      </Card>
    </div>
  );
}
