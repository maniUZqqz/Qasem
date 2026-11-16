import { useCallback, useEffect, useState } from "react";

import { errorMessage } from "../../api/client";
import Icon from "../../components/Icon";
import { Badge, Button, ErrorBox, Spinner } from "../../components/ui";
import { CHANNEL_TITLE, ContactPanel, get, patch, post } from "./api";
import { ago, channelColor, dateText, faNum, initials, money } from "./format";

/** پنل راستِ گفتگو: همهٔ آنچه دربارهٔ این آدم می‌دانیم، از همهٔ کانال‌ها. */
export default function CustomerPane({
  storeId,
  convId,
  canWrite,
  onOpenConversation,
  onClose,
}: {
  storeId: string;
  convId: number;
  canWrite: boolean;
  onOpenConversation: (id: number) => void;
  onClose: () => void;
}) {
  const [data, setData] = useState<ContactPanel | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [tag, setTag] = useState("");
  const [notes, setNotes] = useState("");
  const [name, setName] = useState("");
  const [phone, setPhone] = useState("");
  const [saved, setSaved] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const res = await get<ContactPanel>(storeId, `v2/${convId}/contact/`);
      setData(res);
      setNotes(res.notes);
      setName(res.name);
      setPhone(res.phone);
      setError(null);
    } catch (err) {
      setError(errorMessage(err));
    }
  }, [storeId, convId]);

  useEffect(() => {
    setData(null);
    void load();
  }, [load]);

  const save = async (body: Record<string, unknown>, message = "ذخیره شد.") => {
    if (!data) return;
    try {
      const res = await patch<ContactPanel>(storeId, `contacts/${data.id}/`, body);
      setData(res);
      setNotes(res.notes);
      setName(res.name);
      setPhone(res.phone);
      setSaved(message);
      setError(null);
      window.setTimeout(() => setSaved(null), 2500);
    } catch (err) {
      setError(errorMessage(err));
    }
  };

  if (!data) {
    return <div className="grid flex-1 place-items-center p-6 *:min-w-0">{error ? <ErrorBox message={error} /> : <Spinner />}</div>;
  }

  const addTag = () => {
    const t = tag.trim();
    if (!t || data.tags.includes(t)) return setTag("");
    setTag("");
    void save({ tags: [...data.tags, t] }, "برچسب افزوده شد.");
  };

  return (
    <div className="ib-side">
      <div className="flex items-start gap-3">
        <div className="ib-avatar lg" aria-hidden>
          {initials(data.name || data.usernames[0] || "")}
        </div>
        <div style={{ minWidth: 0, flex: 1 }}>
          <input
            className="u-input"
            value={name}
            disabled={!canWrite}
            placeholder="نام مشتری"
            aria-label="نام مشتری"
            onChange={(e) => setName(e.target.value)}
            onBlur={() => name !== data.name && void save({ name })}
          />
          <input
            className="u-input mt-1"
            dir="ltr"
            value={phone}
            disabled={!canWrite}
            placeholder="شمارهٔ موبایل"
            aria-label="شمارهٔ موبایل"
            onChange={(e) => setPhone(e.target.value)}
            onBlur={() => phone !== data.phone && void save({ phone })}
          />
        </div>
        <button type="button" className="u-btn u-btn-ghost u-btn-sm ib-back" onClick={onClose} aria-label="بستن">
          <Icon name="x" size={15} />
        </button>
      </div>
      <ErrorBox message={error} />
      {saved && <div className="text-xs" style={{ color: "var(--ok)" }}>{saved}</div>}

      <div className="flex flex-wrap gap-1.5">
        {data.is_test && <Badge tone="warn">آزمایشی</Badge>}
        {data.segments.map((s) => (
          <Badge key={s} tone="brand">{s}</Badge>
        ))}
        {data.segments.length === 0 && <span className="text-xs" style={{ color: "var(--text-3)" }}>در هیچ بخشی نیست</span>}
      </div>

      <section>
        <h3>خرید</h3>
        <dl className="ib-kv">
          <dt>خرید تأییدشده</dt><dd>{faNum(data.orders_count)}</dd>
          <dt>جمع خرید</dt><dd>{money(data.total_spent)}</dd>
          <dt>آخرین خرید</dt><dd>{dateText(data.last_purchase_at)}</dd>
          <dt>اولین پیام</dt><dd>{dateText(data.first_seen_at)}</dd>
          <dt>آخرین فعالیت</dt><dd>{ago(data.last_activity_at)}</dd>
        </dl>
        {data.orders.length > 0 && (
          <div className="mt-2 grid gap-1">
            {data.orders.slice(0, 5).map((o) => (
              <div key={o.id} className="flex items-center justify-between text-xs" style={{ color: "var(--text-2)" }}>
                <span>سفارش {faNum(o.id)} · {o.status_title}</span>
                <span className="u-num">{money(o.total)}</span>
              </div>
            ))}
          </div>
        )}
      </section>

      <section>
        <h3>برچسب‌ها</h3>
        <div className="flex flex-wrap gap-1.5">
          {data.tags.map((t) => (
            <span key={t} className="ib-tag">
              {t}
              {canWrite && (
                <button type="button" aria-label={`حذف برچسب ${t}`} onClick={() => void save({ tags: data.tags.filter((x) => x !== t) })}>
                  ×
                </button>
              )}
            </span>
          ))}
        </div>
        {canWrite && (
          <div className="mt-2 flex gap-1.5">
            <input
              className="u-input"
              value={tag}
              placeholder="برچسب تازه…"
              aria-label="برچسب تازه"
              onChange={(e) => setTag(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && (e.preventDefault(), addTag())}
            />
            <Button size="sm" variant="secondary" onClick={addTag}>افزودن</Button>
          </div>
        )}
      </section>

      <section>
        <h3>یادداشت دربارهٔ مشتری</h3>
        <textarea
          className="u-input"
          rows={3}
          value={notes}
          disabled={!canWrite}
          placeholder="مثلاً: ترجیح می‌دهد صبح تماس بگیرند"
          aria-label="یادداشت دربارهٔ مشتری"
          onChange={(e) => setNotes(e.target.value)}
          onBlur={() => notes !== data.notes && void save({ notes })}
        />
      </section>

      <section>
        <h3>کانال‌های این آدم ({faNum(data.customers.length)})</h3>
        <div className="grid gap-1.5 *:min-w-0">
          {data.customers.map((c) => (
            <div key={c.id} className="flex items-center justify-between gap-2 text-xs" style={{ color: "var(--text-2)" }}>
              <span className="ib-chan">
                <i style={{ background: channelColor(c.channel) }} />
                {CHANNEL_TITLE[c.channel] ?? c.channel}
                {c.matched_by && c.matched_by !== "new" && (
                  <span style={{ color: "var(--text-3)" }}>
                    {" "}· یکی شد با {c.matched_by === "phone" ? "شماره" : c.matched_by === "username" ? "نام‌کاربری" : "دست"}
                  </span>
                )}
              </span>
              {canWrite && data.customers.length > 1 && (
                <button
                  type="button"
                  className="u-btn u-btn-ghost u-btn-sm"
                  title="اگر این دو نفر یکی نیستند، جدایشان کنید"
                  onClick={async () => {
                    try {
                      await post(storeId, `customers/${c.id}/unlink/`);
                      await load();
                    } catch (err) {
                      setError(errorMessage(err));
                    }
                  }}
                >
                  جدا کن
                </button>
              )}
            </div>
          ))}
        </div>
        {data.usernames.length > 0 && (
          <div className="mt-1 text-xs" style={{ color: "var(--text-3)" }} dir="ltr">
            {data.usernames.map((u) => `@${u}`).join("  ")}
          </div>
        )}
      </section>

      {canWrite && (
        <section>
          <label className="flex items-center gap-2 text-xs" style={{ color: "var(--text-2)" }}>
            <input
              type="checkbox"
              checked={Boolean(data.opt_out.ALL)}
              onChange={(e) => void save({ opt_out: { ALL: e.target.checked } }, e.target.checked ? "از پیام‌های تبلیغاتی خارج شد." : "دوباره عضو شد.")}
            />
            پیام تبلیغاتی و ارسال گروهی نفرست
          </label>
        </section>
      )}

      <section>
        <h3>گفتگوهای این آدم</h3>
        <div className="grid gap-1 *:min-w-0">
          {data.conversations.map((c) => (
            <button key={c.id} type="button" className="u-btn u-btn-ghost u-btn-sm" style={{ justifyContent: "space-between" }} onClick={() => onOpenConversation(c.id)}>
              <span className="ib-chan"><i style={{ background: channelColor(c.channel) }} />{CHANNEL_TITLE[c.channel] ?? c.channel}</span>
              <span style={{ color: "var(--text-3)" }}>{c.id === convId ? "این گفتگو" : ago(c.updated_at)}</span>
            </button>
          ))}
        </div>
      </section>

      <section>
        <h3>تاریخچهٔ همهٔ کانال‌ها</h3>
        <div className="ib-hist">
          {data.history.length === 0 && <span className="text-xs" style={{ color: "var(--text-3)" }}>پیامی نیست.</span>}
          {[...data.history].reverse().slice(0, 40).map((h) => (
            <button key={h.id} type="button" onClick={() => onOpenConversation(h.conversation_id)}>
              <span className="ib-chan"><i style={{ background: channelColor(h.channel) }} />{h.role === "CUSTOMER" ? "مشتری" : h.role === "HUMAN" ? "تیم" : "ربات"} · {ago(h.at)}</span>
              <div style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{h.text}</div>
            </button>
          ))}
        </div>
      </section>
    </div>
  );
}
