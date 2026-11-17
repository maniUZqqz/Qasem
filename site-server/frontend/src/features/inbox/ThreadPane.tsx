import { useCallback, useEffect, useRef, useState } from "react";

import { api, errorMessage } from "../../api/client";
import Icon from "../../components/Icon";
import { Badge, Button, ErrorBox, Select, Spinner } from "../../components/ui";
import Composer from "./Composer";
import {
  Canned, ConvRow, Member, STATE_TITLE, Thread, ThreadItem, get, post,
} from "./api";
import { channelColor, clock, dateText, duration, faNum, minutesText, splitMentions } from "./format";

const KIND_TITLE: Record<string, string> = {
  BOT: "ربات",
  BROADCAST: "ارسال گروهی",
  FOLLOWUP: "پیگیری خودکار",
  PAYMENT: "یادآوری پرداخت",
  SURVEY: "نظرسنجی",
  SYSTEM: "سیستم",
  REPLY: "",
};

function Bubble({ item, onUseDraft }: { item: ThreadItem; onUseDraft: (text: string) => void }) {
  if (item.type === "note") {
    return (
      <div className="ib-msg note">
        <span className="by">یادداشت داخلی · {item.author || "؟"}</span>
        {splitMentions(item.text).map((part, i) =>
          part.mention ? (
            <bdi key={i} dir="ltr" className="ib-mention">
              {part.text}
            </bdi>
          ) : (
            <span key={i}>{part.text}</span>
          ),
        )}
        <time>{clock(item.at)}</time>
      </div>
    );
  }
  const system = item.role === "AI" && ["SYSTEM", "SURVEY", "FOLLOWUP", "PAYMENT", "BROADCAST"].includes(item.kind ?? "");
  const cls = item.role === "CUSTOMER" ? "customer" : item.role === "HUMAN" ? "human" : system ? "system" : "ai";
  const by =
    item.role === "CUSTOMER" ? "" : item.role === "HUMAN" ? item.author || "تیم" : KIND_TITLE[item.kind ?? ""] || "ربات";
  return (
    <div className={`ib-msg ${cls} ${item.withheld ? "withheld" : ""}`}>
      {by && <span className="by">{by}</span>}
      {item.withheld && (
        <span className="by" style={{ color: "var(--warn)" }}>
          پیش‌نویس ربات — چون مطمئن نبود برای مشتری فرستاده نشد
        </span>
      )}
      {item.text}
      {item.image && <span className="by">[تصویر پیوست‌شده]</span>}
      {item.delivered === false && (
        <span className="bad">
          {" "}
          ⚠ به مشتری نرسید{item.delivery_error ? `: ${item.delivery_error}` : ""}
        </span>
      )}
      <time>{clock(item.at)}</time>
      {item.withheld && (
        <Button size="sm" variant="secondary" onClick={() => onUseDraft(item.text)}>
          استفاده در پاسخ
        </Button>
      )}
    </div>
  );
}

function slaText(row: ConvRow): { tone: "warn" | "bad"; text: string } | null {
  if (row.sla === "breached") return { tone: "bad", text: "SLA رد شد" };
  if (row.sla === "warning" && row.sla_due_at) {
    const left = Math.max(0, Math.round((new Date(row.sla_due_at).getTime() - Date.now()) / 60000));
    return { tone: "warn", text: `SLA: ${faNum(left)} دقیقه مانده` };
  }
  return null;
}

export default function ThreadPane({
  storeId,
  convId,
  canWrite,
  members,
  onChanged,
  onBack,
  onInfo,
}: {
  storeId: string;
  convId: number;
  canWrite: boolean;
  members: Member[];
  onChanged: () => void;
  onBack: () => void;
  onInfo: () => void;
}) {
  const [data, setData] = useState<Thread | null>(null);
  const [canned, setCanned] = useState<Canned[]>([]);
  const [draft, setDraft] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [follow, setFollow] = useState(false);
  const bottom = useRef<HTMLDivElement>(null);
  const lastCount = useRef(0);
  const current = useRef(convId);
  current.current = convId;

  const load = useCallback(
    async (silent = true) => {
      try {
        const res = await get<Thread>(storeId, `v2/${convId}/`);
        if (current.current !== convId) return;
        setData(res);
        if (!silent) setError(null);
      } catch (err) {
        if (!silent) setError(errorMessage(err));
      }
    },
    [storeId, convId],
  );

  useEffect(() => {
    setData(null);
    setDraft("");
    setNotice(null);
    setError(null);
    lastCount.current = 0;
    void load(false);
    const timer = window.setInterval(() => document.visibilityState === "visible" && void load(), 4000);
    return () => window.clearInterval(timer);
  }, [load]);

  useEffect(() => {
    if (!data) return;
    get<{ replies: Canned[] }>(storeId, "canned/", { channel: data.conversation.channel })
      .then((res) => setCanned(res.replies))
      .catch(() => undefined);
  }, [storeId, data?.conversation.channel]); // eslint-disable-line react-hooks/exhaustive-deps

  // پایین‌ترین پیام را نشان بده، ولی فقط وقتی پیام تازه آمده (نه هر بار که تازه می‌شود).
  useEffect(() => {
    const count = data?.thread.length ?? 0;
    if (count !== lastCount.current) {
      lastCount.current = count;
      bottom.current?.scrollIntoView({ block: "end" });
    }
  }, [data?.thread.length]);

  const act = async (fn: () => Promise<unknown>, done?: string) => {
    setBusy(true);
    setError(null);
    try {
      await fn();
      if (done) setNotice(done);
      await load(false);
      onChanged();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const send = async (text: string, mode: "reply" | "note", cannedId?: number) => {
    setBusy(true);
    setError(null);
    try {
      if (mode === "note") {
        await post(storeId, `v2/${convId}/note/`, { text });
        setNotice("یادداشت ثبت شد؛ فقط تیم می‌بیند.");
      } else {
        const res = await post<{ delivered: boolean; reason: string; response_seconds: number | null }>(
          storeId, `v2/${convId}/reply/`, { text, canned_id: cannedId },
        );
        setNotice(res.delivered ? "پاسخ فرستاده شد." : `پاسخ ثبت شد ولی به مشتری نرسید: ${res.reason}`);
      }
      setDraft("");
      await load(false);
      onChanged();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  if (!data) {
    return (
      <div className="grid flex-1 place-items-center p-8 *:min-w-0">
        {error ? <ErrorBox message={error} /> : <Spinner />}
      </div>
    );
  }

  const row = data.conversation;
  const sla = slaText(row);
  const items = data.thread;
  let lastDay = "";

  return (
    <>
      <div className="ib-head">
        <button type="button" className="u-btn u-btn-ghost u-btn-sm ib-back" onClick={onBack} aria-label="بازگشت به فهرست">
          <Icon name="next" size={15} />
        </button>
        <div style={{ minWidth: 0 }}>
          <h2>{row.customer.name}</h2>
          <div className="flex flex-wrap items-center gap-2 text-xs" style={{ color: "var(--text-3)" }}>
            <span className="ib-chan">
              <i style={{ background: channelColor(row.channel) }} />
              {row.channel_title}
            </span>
            {row.customer.phone && <span dir="ltr">{row.customer.phone}</span>}
            <Badge tone={row.state === "ESCALATED" ? "warn" : row.state === "RESOLVED" ? "neutral" : row.state === "AI" ? "info" : "brand"}>
              {STATE_TITLE[row.state]}
            </Badge>
            {row.is_test && <Badge tone="warn">آزمایشی</Badge>}
            {sla && <span className={`ib-sla ${sla.tone === "bad" ? "breached" : "warning"}`}>{sla.text}</span>}
            {row.waiting_minutes !== null && row.waiting_minutes > 0 && (
              <span>منتظر: {minutesText(row.waiting_minutes)}</span>
            )}
          </div>
          {row.handoff_reason && (
            <div className="mt-1 text-[11px]" style={{ color: "var(--text-3)" }}>
              چرا به تیم رسید: {row.handoff_reason}
            </div>
          )}
        </div>
        <div className="ib-actions">
          {canWrite && (
            <>
              <Select
                aria-label="مسئول گفتگو"
                value={row.assigned_to?.username ?? ""}
                disabled={busy}
                style={{ width: 150 }}
                onChange={(e) =>
                  void act(() => post(storeId, `v2/${convId}/assign/`, { username: e.target.value || "nobody" }), "مسئول عوض شد.")
                }
              >
                <option value="">بدون مسئول</option>
                {members.map((m) => (
                  <option key={m.username} value={m.username}>
                    {m.name} {m.status === "ONLINE" ? "●" : ""}
                  </option>
                ))}
              </Select>
              {row.ai_failed && (
                <Button
                  size="sm"
                  variant="secondary"
                  disabled={busy}
                  onClick={() => void act(() => api.post(`/stores/${storeId}/inbox/${convId}/retry/`), "دوباره امتحان می‌شود؛ چند لحظه بعد تازه کنید.")}
                >
                  دوباره امتحان ربات
                </Button>
              )}
              {row.state === "AI" && (
                <Button size="sm" variant="secondary" disabled={busy} onClick={() => void act(() => post(storeId, `v2/${convId}/state/`, { action: "take_from_ai" }), "گفتگو با شماست.")}>
                  گرفتن از ربات
                </Button>
              )}
              {(row.state === "HUMAN" || row.state === "ESCALATED") && (
                <Button size="sm" variant="ghost" disabled={busy} onClick={() => void act(() => post(storeId, `v2/${convId}/state/`, { action: "give_to_ai" }), "دوباره دست ربات است.")}>
                  برگرداندن به ربات
                </Button>
              )}
              {row.state === "RESOLVED" ? (
                <Button size="sm" variant="secondary" disabled={busy} onClick={() => void act(() => post(storeId, `v2/${convId}/state/`, { action: "reopen" }), "گفتگو دوباره باز شد.")}>
                  باز کردن دوباره
                </Button>
              ) : (
                <Button size="sm" disabled={busy} onClick={() => void act(() => post(storeId, `v2/${convId}/state/`, { action: "close" }), "گفتگو بسته شد.")}>
                  بستن
                </Button>
              )}
              <Button size="sm" variant="ghost" onClick={() => setFollow((v) => !v)} aria-expanded={follow}>
                پیگیری
              </Button>
            </>
          )}
          <button type="button" className="u-btn u-btn-ghost u-btn-sm" onClick={onInfo} aria-label="اطلاعات مشتری">
            <Icon name="users" size={15} />
          </button>
        </div>
      </div>

      <TagsRow
        tags={row.tags}
        canWrite={canWrite}
        onChange={(tags) => void act(() => post(storeId, `v2/${convId}/tags/`, { tags }))}
      />

      {follow && canWrite && (
        <FollowForm
          onCancel={() => setFollow(false)}
          onSave={(body) =>
            act(async () => {
              await post(storeId, `v2/${convId}/followup/`, body);
              setFollow(false);
            }, "پیگیری ثبت شد.")
          }
        />
      )}

      {data.followups.length > 0 && (
        <div className="flex flex-wrap items-center gap-2 px-4 py-1.5 text-xs" style={{ background: "var(--info-soft)", color: "var(--info)" }}>
          <Icon name="clock" size={13} />
          {data.followups.map((f) => (
            <span key={f.id}>
              {f.target === "AGENT" ? "یادآوری" : "پیام"} در {new Date(f.due_at).toLocaleString("fa-IR", { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" })}
            </span>
          ))}
        </div>
      )}

      <div className="ib-thread" role="log" aria-live="polite" aria-label="پیام‌های گفتگو">
        {items.length === 0 && <div className="ib-msg system">هنوز پیامی نیست.</div>}
        {items.map((item) => {
          const day = dateText(item.at);
          const head = day !== lastDay ? <div key={`d${item.type}${item.id}`} className="ib-day">{day}</div> : null;
          lastDay = day;
          return (
            <div key={`${item.type}-${item.id}`} style={{ display: "contents" }}>
              {head}
              <Bubble item={item} onUseDraft={(text) => setDraft(text)} />
            </div>
          );
        })}
        <div ref={bottom} />
      </div>

      <div className="px-3">
        <ErrorBox message={error} />
        {notice && !error && (
          <div className="my-1 text-xs" style={{ color: "var(--ok)" }}>
            {notice}
          </div>
        )}
      </div>

      {data.meta.first_response_seconds !== null && (
        <div className="px-4 pb-1 text-[11px]" style={{ color: "var(--text-3)" }}>
          اولین پاسخ تیم: {duration(data.meta.first_response_seconds)}
          {data.meta.reopened_count ? ` · ${faNum(data.meta.reopened_count)} بار دوباره باز شده` : ""}
        </div>
      )}

      <Composer
        canWrite={canWrite}
        canned={canned}
        members={members}
        customerName={row.customer.name}
        draft={draft}
        setDraft={setDraft}
        busy={busy}
        onSend={send}
      />
    </>
  );
}

function TagsRow({ tags, canWrite, onChange }: { tags: string[]; canWrite: boolean; onChange: (tags: string[]) => void }) {
  const [text, setText] = useState("");
  if (!canWrite && tags.length === 0) return null;
  return (
    <div className="flex flex-wrap items-center gap-1.5 px-4 py-1.5" style={{ borderBlockEnd: "1px solid var(--line)" }}>
      <Icon name="tag" size={13} />
      {tags.map((t) => (
        <span key={t} className="ib-tag">
          {t}
          {canWrite && (
            <button type="button" aria-label={`حذف برچسب ${t}`} onClick={() => onChange(tags.filter((x) => x !== t))}>×</button>
          )}
        </span>
      ))}
      {canWrite && (
        <input
          className="u-input"
          style={{ width: 130, padding: "2px 8px", fontSize: ".75rem" }}
          value={text}
          placeholder="برچسب گفتگو…"
          aria-label="برچسب گفتگو"
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && text.trim()) {
              e.preventDefault();
              if (!tags.includes(text.trim())) onChange([...tags, text.trim()]);
              setText("");
            }
          }}
        />
      )}
    </div>
  );
}

function FollowForm({
  onSave,
  onCancel,
}: {
  onSave: (body: { text: string; in_hours?: number; due_at?: string; target: string }) => Promise<void>;
  onCancel: () => void;
}) {
  const [text, setText] = useState("");
  const [hours, setHours] = useState("24");
  const [target, setTarget] = useState("CUSTOMER");
  return (
    <div className="grid gap-2 px-4 py-2 *:min-w-0" style={{ background: "var(--surface-2)", borderBlockEnd: "1px solid var(--line)" }}>
      <div className="flex flex-wrap items-center gap-2 text-xs">
        <Select value={target} onChange={(e) => setTarget(e.target.value)} style={{ width: 190 }} aria-label="نوع پیگیری">
          <option value="CUSTOMER">پیام به مشتری</option>
          <option value="AGENT">فقط یادآوری به من و تیم</option>
        </Select>
        <span>بعد از</span>
        <Select value={hours} onChange={(e) => setHours(e.target.value)} style={{ width: 130 }} aria-label="زمان پیگیری">
          <option value="1">۱ ساعت</option>
          <option value="4">۴ ساعت</option>
          <option value="24">فردا</option>
          <option value="72">۳ روز</option>
          <option value="168">یک هفته</option>
        </Select>
      </div>
      <input
        className="u-input"
        value={text}
        placeholder={target === "CUSTOMER" ? "متن پیامی که فرستاده می‌شود…" : "چه چیزی یادم بماند؟"}
        onChange={(e) => setText(e.target.value)}
        aria-label="متن پیگیری"
      />
      <div className="flex gap-2">
        <Button size="sm" onClick={() => void onSave({ text, in_hours: Number(hours), target })}>
          ثبت پیگیری
        </Button>
        <Button size="sm" variant="ghost" onClick={onCancel}>
          انصراف
        </Button>
      </div>
    </div>
  );
}
