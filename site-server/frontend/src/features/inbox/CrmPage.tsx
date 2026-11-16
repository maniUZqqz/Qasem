import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { errorMessage } from "../../api/client";
import { Badge, Button, Card, ErrorBox, Field, Input, SectionTitle, Select, Spinner } from "../../components/ui";
import {
  CHANNEL_TITLE, ContactPanel, ContactRow, Segment, SegmentField, SegmentRule, SegmentRules, del, get, patch, post,
} from "./api";
import { ago, dateText, faNum, money } from "./format";
import { useInbox } from "./InboxLayout";

const OPS: Record<string, { key: string; label: string }[]> = {
  num: [
    { key: "gte", label: "حداقل" }, { key: "lte", label: "حداکثر" }, { key: "eq", label: "برابر" },
    { key: "gt", label: "بیشتر از" }, { key: "lt", label: "کمتر از" },
  ],
  tags: [{ key: "has", label: "دارد" }, { key: "not_has", label: "ندارد" }],
  set: [{ key: "has", label: "دارد" }, { key: "not_has", label: "ندارد" }],
  bool: [{ key: "is_true", label: "بله" }, { key: "is_false", label: "نه" }],
  text: [{ key: "contains", label: "شامل" }, { key: "eq", label: "برابر" }],
};

function RuleBuilder({
  value, fields, onChange, disabled,
}: { value: SegmentRules; fields: SegmentField[]; onChange: (v: SegmentRules) => void; disabled?: boolean }) {
  const rules = value.rules;
  const set = (i: number, patchRule: Partial<SegmentRule>) =>
    onChange({ ...value, rules: rules.map((r, j) => (j === i ? { ...r, ...patchRule } : r)) });
  const kindOf = (field: string) => fields.find((f) => f.key === field)?.kind ?? "num";
  return (
    <div className="grid gap-2 *:min-w-0">
      <div className="flex items-center gap-2 text-sm" style={{ color: "var(--text-2)" }}>
        مخاطبی که
        <Select value={value.match ?? "all"} disabled={disabled} onChange={(e) => onChange({ ...value, match: e.target.value as "all" | "any" })} style={{ width: 150 }} aria-label="ترکیب قاعده‌ها">
          <option value="all">همهٔ شرط‌ها را دارد</option>
          <option value="any">یکی از شرط‌ها را دارد</option>
        </Select>
      </div>
      {rules.map((r, i) => {
        const kind = kindOf(r.field);
        const ops = OPS[kind] ?? OPS.num;
        return (
          <div key={i} className="ib-rule">
            <Select value={r.field} disabled={disabled} aria-label="فیلد" onChange={(e) => {
              const k = kindOf(e.target.value);
              set(i, { field: e.target.value, op: (OPS[k] ?? OPS.num)[0].key, value: "" });
            }}>
              {fields.map((f) => <option key={f.key} value={f.key}>{f.label}</option>)}
            </Select>
            <Select value={r.op} disabled={disabled} aria-label="شرط" onChange={(e) => set(i, { op: e.target.value })}>
              {ops.map((o) => <option key={o.key} value={o.key}>{o.label}</option>)}
            </Select>
            {kind === "bool" ? <span /> : kind === "set" ? (
              <Select value={String(r.value ?? "")} disabled={disabled} aria-label="کانال" onChange={(e) => set(i, { value: e.target.value })}>
                <option value="">— کانال —</option>
                {Object.entries(CHANNEL_TITLE).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
              </Select>
            ) : (
              <Input value={String(r.value ?? "")} disabled={disabled} aria-label="مقدار" onChange={(e) => set(i, { value: kind === "num" ? Number(e.target.value.replace(/[^\d.]/g, "")) || 0 : e.target.value })} />
            )}
            {!disabled && <Button size="sm" variant="ghost" onClick={() => onChange({ ...value, rules: rules.filter((_, j) => j !== i) })} aria-label="حذف شرط">×</Button>}
          </div>
        );
      })}
      {!disabled && (
        <div>
          <Button size="sm" variant="secondary" onClick={() => onChange({ ...value, rules: [...rules, { field: fields[0]?.key ?? "orders_count", op: "gte", value: 1 }] })}>
            + شرط تازه
          </Button>
        </div>
      )}
    </div>
  );
}

function Segments({ storeId, canWrite }: { storeId: string; canWrite: boolean }) {
  const [data, setData] = useState<{ segments: Segment[]; total_contacts: number; fields: SegmentField[] } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [name, setName] = useState("");
  const [rules, setRules] = useState<SegmentRules>({ match: "all", rules: [{ field: "orders_count", op: "gte", value: 1 }] });
  const [count, setCount] = useState<number | null>(null);

  const load = useCallback(async () => {
    try {
      setData(await get(storeId, "segments/"));
      setError(null);
    } catch (err) {
      setError(errorMessage(err));
    }
  }, [storeId]);
  useEffect(() => {
    void load();
  }, [load]);

  // شمارندهٔ زنده: هر تغییرِ قاعده، تعدادِ آدم‌های منطبق را تازه می‌کند.
  useEffect(() => {
    const t = window.setTimeout(() => {
      post<{ count: number }>(storeId, "segments/preview/", { rules })
        .then((r) => setCount(r.count))
        .catch(() => setCount(null));
    }, 350);
    return () => window.clearTimeout(t);
  }, [storeId, rules]);

  if (!data) return <div className="py-6 text-center">{error ? <ErrorBox message={error} /> : <Spinner />}</div>;

  const create = async () => {
    try {
      await post(storeId, "segments/", { name, rules });
      setName("");
      await load();
    } catch (err) {
      setError(errorMessage(err));
    }
  };

  return (
    <div className="grid gap-4 *:min-w-0">
      <ErrorBox message={error} />
      <div className="ib-grid">
        {data.segments.map((s) => (
          <Card key={s.id}>
            <div className="flex items-start justify-between gap-2">
              <div>
                <h4 className="text-sm font-extrabold" style={{ color: "var(--text)" }}>{s.name}</h4>
                {s.description && <p className="text-xs" style={{ color: "var(--text-3)" }}>{s.description}</p>}
              </div>
              <Badge tone={s.builtin ? "brand" : "neutral"}>{s.count === null ? "؟" : `${faNum(s.count)} نفر`}</Badge>
            </div>
            {!s.builtin && canWrite && (
              <div className="mt-2">
                <Button size="sm" variant="ghost" onClick={async () => { await del(storeId, `segments/${s.id}/`); await load(); }}>حذف</Button>
              </div>
            )}
          </Card>
        ))}
      </div>
      {canWrite && (
        <Card>
          <SectionTitle>بخشِ تازه</SectionTitle>
          <div className="grid gap-3 *:min-w-0">
            <Field label="نام بخش"><Input value={name} onChange={(e) => setName(e.target.value)} placeholder="مثلاً: خریداران پروتئین" /></Field>
            <RuleBuilder value={rules} fields={data.fields} onChange={setRules} />
            <div className="flex items-center gap-3">
              <Button size="sm" disabled={!name.trim()} onClick={() => void create()}>ذخیرهٔ بخش</Button>
              <span className="text-sm" style={{ color: "var(--text-2)" }}>
                الان {count === null ? "…" : faNum(count)} نفر با این شرط‌ها می‌خوانند (از {faNum(data.total_contacts)} نفر)
              </span>
            </div>
          </div>
        </Card>
      )}
    </div>
  );
}

function ContactDrawer({ storeId, id, canWrite, onClose, onSaved }: { storeId: string; id: number; canWrite: boolean; onClose: () => void; onSaved: () => void }) {
  const [data, setData] = useState<ContactPanel | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [tags, setTags] = useState("");
  const [notes, setNotes] = useState("");
  useEffect(() => {
    get<ContactPanel>(storeId, `contacts/${id}/`).then((c) => { setData(c); setTags(c.tags.join("، ")); setNotes(c.notes); }).catch((e) => setError(errorMessage(e)));
  }, [storeId, id]);
  if (!data) return <Card>{error ? <ErrorBox message={error} /> : <Spinner />}</Card>;
  const save = async () => {
    try {
      const res = await patch<ContactPanel>(storeId, `contacts/${id}/`, { tags: tags.split(/[،,\n]/).map((t) => t.trim()).filter(Boolean), notes });
      setData(res);
      onSaved();
    } catch (err) {
      setError(errorMessage(err));
    }
  };
  return (
    <Card>
      <div className="flex items-start justify-between gap-2">
        <div>
          <h3 className="text-lg font-extrabold" style={{ color: "var(--text)" }}>{data.name || "بدون نام"}</h3>
          <div className="text-xs" style={{ color: "var(--text-3)" }} dir="ltr">{data.phone}</div>
        </div>
        <Button size="sm" variant="ghost" onClick={onClose}>بستن</Button>
      </div>
      <ErrorBox message={error} />
      <div className="mt-3 flex flex-wrap gap-1.5">
        {data.segments.map((s) => <Badge key={s} tone="brand">{s}</Badge>)}
        {data.customers.map((c) => <Badge key={c.id}>{CHANNEL_TITLE[c.channel] ?? c.channel}</Badge>)}
      </div>
      <dl className="ib-kv mt-3">
        <dt>خرید تأییدشده</dt><dd>{faNum(data.orders_count)}</dd>
        <dt>جمع خرید</dt><dd>{money(data.total_spent)}</dd>
        <dt>آخرین خرید</dt><dd>{dateText(data.last_purchase_at)}</dd>
        <dt>آخرین فعالیت</dt><dd>{ago(data.last_activity_at)}</dd>
      </dl>
      <div className="mt-3 grid gap-2">
        <Field label="برچسب‌ها (با ویرگول)"><Input value={tags} disabled={!canWrite} onChange={(e) => setTags(e.target.value)} /></Field>
        <Field label="یادداشت"><textarea className="u-input" rows={3} value={notes} disabled={!canWrite} onChange={(e) => setNotes(e.target.value)} /></Field>
        {canWrite && <div><Button size="sm" onClick={() => void save()}>ذخیره</Button></div>}
      </div>
      {data.conversations.length > 0 && (
        <div className="mt-3 flex flex-wrap gap-2">
          {data.conversations.slice(0, 6).map((c) => (
            <Link key={c.id} to={`/stores/${storeId}/inbox?c=${c.id}`} className="u-btn u-btn-secondary u-btn-sm">
              گفتگو در {CHANNEL_TITLE[c.channel] ?? c.channel}
            </Link>
          ))}
        </div>
      )}
    </Card>
  );
}

function Contacts({ storeId, canWrite }: { storeId: string; canWrite: boolean }) {
  const [rows, setRows] = useState<{ contacts: ContactRow[]; total: number } | null>(null);
  const [segments, setSegments] = useState<Segment[]>([]);
  const [q, setQ] = useState("");
  const [segment, setSegment] = useState("");
  const [tag, setTag] = useState("");
  const [open, setOpen] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [adding, setAdding] = useState({ name: "", phone: "" });

  const load = useCallback(async () => {
    try {
      const params: Record<string, unknown> = { q, limit: 100 };
      if (segment) params.segment = segment;
      if (tag.trim()) params.tag = tag.trim();
      setRows(await get(storeId, "contacts/", params));
      setError(null);
    } catch (err) {
      setError(errorMessage(err));
    }
  }, [storeId, q, segment, tag]);

  useEffect(() => {
    const t = window.setTimeout(() => void load(), 250);
    return () => window.clearTimeout(t);
  }, [load]);
  useEffect(() => {
    get<{ segments: Segment[] }>(storeId, "segments/").then((r) => setSegments(r.segments)).catch(() => undefined);
  }, [storeId]);

  const add = async () => {
    try {
      await post(storeId, "contacts/", adding);
      setAdding({ name: "", phone: "" });
      await load();
    } catch (err) {
      setError(errorMessage(err));
    }
  };

  return (
    <div className="grid gap-4 *:min-w-0">
      <div className="flex flex-wrap items-end gap-3">
        <Field label="جست‌وجو"><Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="نام یا شماره" style={{ width: 200 }} /></Field>
        <Field label="بخش">
          <Select value={segment} onChange={(e) => setSegment(e.target.value)} style={{ width: 180 }}>
            <option value="">همه</option>
            {segments.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
          </Select>
        </Field>
        <Field label="برچسب"><Input value={tag} onChange={(e) => setTag(e.target.value)} style={{ width: 140 }} /></Field>
        <span className="pb-2 text-sm" style={{ color: "var(--text-3)" }}>{rows ? `${faNum(rows.total)} مخاطب` : ""}</span>
      </div>
      <ErrorBox message={error} />
      {open && <ContactDrawer storeId={storeId} id={open} canWrite={canWrite} onClose={() => setOpen(null)} onSaved={() => void load()} />}
      <Card padded={false}>
        <div className="ib-table-wrap">
          <table className="u-table">
            <thead>
              <tr><th>نام</th><th>موبایل</th><th>کانال‌ها</th><th>برچسب</th><th>خرید</th><th>آخرین فعالیت</th><th /></tr>
            </thead>
            <tbody>
              {!rows && <tr><td colSpan={7} className="p-6 text-center"><Spinner /></td></tr>}
              {rows?.contacts.map((c) => (
                <tr key={c.id}>
                  <td><b>{c.name || "بدون نام"}</b>{c.opt_out.ALL && <Badge tone="bad">لغو کرده</Badge>}</td>
                  <td dir="ltr" className="u-num">{c.phone || "—"}</td>
                  <td>{(c.channels ?? []).map((k) => CHANNEL_TITLE[k] ?? k).join("، ") || "—"}</td>
                  <td>{c.tags.join("، ") || "—"}</td>
                  <td className="u-num">{faNum(c.orders_count)}</td>
                  <td>{ago(c.last_activity_at)}</td>
                  <td><Button size="sm" variant="ghost" onClick={() => setOpen(c.id)}>پروفایل</Button></td>
                </tr>
              ))}
              {rows && rows.contacts.length === 0 && <tr><td colSpan={7} className="p-6 text-center" style={{ color: "var(--text-3)" }}>مخاطبی پیدا نشد. با اولین پیام مشتری، مخاطب خودکار ساخته می‌شود.</td></tr>}
            </tbody>
          </table>
        </div>
      </Card>
      {canWrite && (
        <Card>
          <SectionTitle>افزودن مخاطب (با شمارهٔ موبایل)</SectionTitle>
          <div className="flex flex-wrap items-end gap-3">
            <Field label="نام"><Input value={adding.name} onChange={(e) => setAdding({ ...adding, name: e.target.value })} /></Field>
            <Field label="موبایل"><Input dir="ltr" value={adding.phone} onChange={(e) => setAdding({ ...adding, phone: e.target.value })} placeholder="09…" /></Field>
            <Button size="sm" disabled={!adding.phone.trim() && !adding.name.trim()} onClick={() => void add()}>افزودن</Button>
          </div>
          <p className="mt-2 text-xs" style={{ color: "var(--text-3)" }}>
            مخاطبِ دستی فقط وقتی پیامک یا ارسال گروهی می‌گیرد که شمارهٔ موبایلش ثبت و کانال پیامک روشن باشد. لغو (opt-out) هر مخاطب همیشه رعایت می‌شود.
          </p>
        </Card>
      )}
    </div>
  );
}

export default function CrmPage() {
  const { storeId, me } = useInbox();
  const [tab, setTab] = useState<"contacts" | "segments">("contacts");
  const canWrite = Boolean(me?.can_write);
  return (
    <div className="grid gap-4 *:min-w-0">
      <div className="ib-pills" role="tablist">
        <button type="button" role="tab" aria-selected={tab === "contacts"} className={`ib-pill ${tab === "contacts" ? "on" : ""}`} onClick={() => setTab("contacts")}>مخاطبان</button>
        <button type="button" role="tab" aria-selected={tab === "segments"} className={`ib-pill ${tab === "segments" ? "on" : ""}`} onClick={() => setTab("segments")}>بخش‌ها (مثل «مشتریِ دائمی»)</button>
      </div>
      {tab === "contacts" ? <Contacts storeId={storeId} canWrite={canWrite} /> : <Segments storeId={storeId} canWrite={canWrite} />}
    </div>
  );
}
