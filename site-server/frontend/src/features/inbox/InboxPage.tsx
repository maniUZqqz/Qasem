import { useCallback, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";

import { errorMessage } from "../../api/client";
import Icon from "../../components/Icon";
import { EmptyState, ErrorBox, Spinner } from "../../components/ui";
import CustomerPane from "./CustomerPane";
import ThreadPane from "./ThreadPane";
import { ConvRow, InboxList, STATE_TITLE, ThreadItem, get } from "./api";
import { ago, channelColor, faNum, initials, minutesText } from "./format";
import { useInbox } from "./InboxLayout";

type View = "all" | "waiting" | "mine" | "unassigned" | "unread" | "breached";

const VIEW_TITLE: Record<View, string> = {
  all: "همه",
  waiting: "منتظر پاسخ",
  mine: "مال من",
  unassigned: "بدون مسئول",
  unread: "نخوانده",
  breached: "SLA رد شده",
};

/** هر بار این‌قدر گفتگوی بیشتر نشان داده می‌شود («نمایش بیشتر»)؛ سرور برای هر درخواست سقف دارد. */
const PAGE = 50;

function queryFor(view: View, channel: string, q: string, tests: boolean, assignee: string, limit: number): Record<string, string> {
  const params: Record<string, string> = { limit: String(limit) };
  if (assignee) params.assigned = assignee;
  if (view === "waiting") params.state = "waiting";
  if (view === "mine") params.assigned = "me";
  if (view === "unassigned") {
    params.assigned = "nobody";
    params.state = "waiting";
  }
  if (view === "unread") params.unread = "1";
  if (view === "breached") params.sla = "breached";
  if (channel) params.channel = channel;
  if (q.trim()) params.q = q.trim();
  if (tests) params.test = "1";
  return params;
}

function Row({ row, selected, onClick }: { row: ConvRow; selected: boolean; onClick: () => void }) {
  const wait = row.waiting_minutes;
  return (
    <button type="button" className={`ib-row ${selected ? "sel" : ""}`} onClick={onClick} aria-current={selected ? "true" : undefined}>
      <div className="ib-avatar" aria-hidden>
        {initials(row.customer.name)}
        <span className="ch" style={{ background: channelColor(row.channel) }} />
      </div>
      <div style={{ minWidth: 0 }}>
        <div className="t">
          <span className="name">{row.customer.name}</span>
          {row.unread > 0 && <span className="ib-unread">{faNum(row.unread)}</span>}
          <span className="when">{ago(row.last_message?.at ?? row.updated_at)}</span>
        </div>
        <div className="snip">
          {row.last_message ? `${row.last_message.role === "CUSTOMER" ? "" : row.last_message.role === "HUMAN" ? "شما: " : "ربات: "}${row.last_message.text}` : "—"}
        </div>
        <div className="meta">
          <span className="ib-chan">
            <i style={{ background: channelColor(row.channel) }} />
            {row.channel_title}
          </span>
          <span className="ib-chan" style={{ color: row.state === "ESCALATED" ? "var(--warn)" : undefined }}>
            {STATE_TITLE[row.state]}
          </span>
          {row.assigned_to && <span className="ib-chan">· {row.assigned_to.name}</span>}
          {row.sla === "breached" && <span className="ib-sla breached">SLA رد شد</span>}
          {row.sla === "warning" && <span className="ib-sla warning">نزدیک SLA</span>}
          {wait !== null && wait > 0 && row.sla === "none" && <span className="ib-chan">⏱ {minutesText(wait)}</span>}
          {row.ai_failed && <span className="ib-sla breached">ربات جواب نداد</span>}
          {row.is_test && <span className="ib-sla warning">آزمایشی</span>}
        </div>
      </div>
    </button>
  );
}

export default function InboxPage() {
  const { storeId, refreshCounts } = useInbox();
  const [params, setParams] = useSearchParams();
  const selected = Number(params.get("c")) || null;
  const [view, setView] = useState<View>("all");
  const [channel, setChannel] = useState("");
  const [q, setQ] = useState("");
  const [debounced, setDebounced] = useState("");
  const [tests, setTests] = useState(false);
  const [assignee, setAssignee] = useState("");
  const [mentions, setMentions] = useState<(ThreadItem & { conversation_id: number; customer: string })[] | null>(null);
  const [showMentions, setShowMentions] = useState(false);
  const [data, setData] = useState<InboxList | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [info, setInfo] = useState(false);
  const [limit, setLimit] = useState(PAGE);

  // یک فیلتر یا جست‌وجوی تازه از اول شروع می‌شود، نه از «نمایش بیشترِ» فیلتر قبلی.
  useEffect(() => {
    setLimit(PAGE);
  }, [view, channel, debounced, tests, assignee]);

  useEffect(() => {
    const t = window.setTimeout(() => setDebounced(q), 300);
    return () => window.clearTimeout(t);
  }, [q]);

  const load = useCallback(async () => {
    try {
      const res = await get<InboxList>(storeId, "v2/", queryFor(view, channel, debounced, tests, assignee, limit));
      setData(res);
      setError(null);
    } catch (err) {
      setError(errorMessage(err));
    }
  }, [storeId, view, channel, debounced, tests, assignee, limit]);

  useEffect(() => {
    void load();
    const timer = window.setInterval(() => document.visibilityState === "visible" && void load(), 6000);
    return () => window.clearInterval(timer);
  }, [load]);

  useEffect(() => {
    get<{ mentions: (ThreadItem & { conversation_id: number; customer: string })[] }>(storeId, "mentions/")
      .then((r) => setMentions(r.mentions))
      .catch(() => setMentions([]));
  }, [storeId, data?.counts.waiting]);

  const select = (id: number | null) => {
    const next = new URLSearchParams(params);
    if (id) next.set("c", String(id));
    else next.delete("c");
    setParams(next, { replace: false });
    setInfo(false);
  };

  const changed = useCallback(() => {
    void load();
    refreshCounts();
  }, [load, refreshCounts]);

  const counts = data?.counts;
  const channelsInUse = useMemo(() => Object.entries(data?.by_channel ?? {}), [data?.by_channel]);
  const pills: { key: View; n?: number; bad?: boolean }[] = [
    { key: "all" },
    { key: "waiting", n: counts?.waiting },
    { key: "mine", n: counts?.mine },
    { key: "unassigned", n: counts?.unassigned },
    { key: "unread", n: counts?.unread },
    { key: "breached", n: counts?.breached, bad: true },
  ];

  return (
    <div>
      <ErrorBox message={error} />
      <div className="ib-shell" data-view={selected ? "thread" : "list"} data-info={info ? "1" : "0"}>
        {/* ---------------------------------------------------------- فهرست */}
        <section className="ib-pane list" aria-label="فهرست گفتگوها">
          <div className="ib-filters">
            <div className="relative">
              <input
                className="u-input"
                value={q}
                placeholder="جست‌وجو: نام، شماره، متن پیام…"
                aria-label="جست‌وجوی گفتگو"
                onChange={(e) => setQ(e.target.value)}
              />
            </div>
            <div className="ib-pills" role="tablist" aria-label="نمای گفتگوها">
              {pills.map((p) => (
                <button key={p.key} type="button" role="tab" aria-selected={view === p.key} className={`ib-pill ${view === p.key ? "on" : ""} ${p.bad ? "bad" : ""}`} onClick={() => setView(p.key)}>
                  {VIEW_TITLE[p.key]}
                  {p.n ? <span className="n">{faNum(p.n)}</span> : null}
                </button>
              ))}
            </div>
            <div className="flex gap-2">
              <select className="u-input" value={assignee} onChange={(e) => setAssignee(e.target.value)} aria-label="فیلتر مسئول">
                <option value="">همهٔ مسئول‌ها</option>
                <option value="nobody">بدون مسئول</option>
                {data?.members.map((m) => (
                  <option key={m.username} value={m.username}>{m.name}</option>
                ))}
              </select>
              <button type="button" className={`ib-pill ${showMentions ? "on" : ""}`} onClick={() => setShowMentions((v) => !v)} aria-expanded={showMentions}>
                @ اشاره‌ها{mentions && mentions.length ? <span className="n">{faNum(mentions.length)}</span> : null}
              </button>
            </div>
            {showMentions && (
              <div className="ib-hist" aria-label="اشاره‌ها به من">
                {(mentions ?? []).length === 0 && <span className="text-xs" style={{ color: "var(--text-3)" }}>کسی شما را در یادداشتی صدا نزده است.</span>}
                {(mentions ?? []).map((m) => (
                  <button key={m.id} type="button" onClick={() => { select(m.conversation_id); setShowMentions(false); }}>
                    <b>{m.author}</b> دربارهٔ «{m.customer}» · {ago(m.at)}
                    <div style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{m.text}</div>
                  </button>
                ))}
              </div>
            )}
            <div className="ib-pills" aria-label="فیلتر کانال">
              <button type="button" className={`ib-pill ${channel === "" ? "on" : ""}`} onClick={() => setChannel("")}>
                همهٔ کانال‌ها
              </button>
              {channelsInUse.map(([key, n]) => (
                <button key={key} type="button" className={`ib-pill ${channel === key ? "on" : ""}`} onClick={() => setChannel(channel === key ? "" : key)}>
                  <i style={{ width: 8, height: 8, borderRadius: "50%", background: channelColor(key), display: "inline-block" }} />
                  {data?.conversations.find((c) => c.channel === key)?.channel_title ?? key}
                  <span className="n">{faNum(n)}</span>
                </button>
              ))}
            </div>
            {(counts?.tests ?? 0) > 0 && (
              <label className="flex items-center gap-2 text-xs" style={{ color: "var(--text-3)" }}>
                <input type="checkbox" checked={tests} onChange={(e) => setTests(e.target.checked)} />
                گفتگوهای آزمایشی را هم نشان بده ({faNum(counts?.tests ?? 0)})
              </label>
            )}
          </div>
          <div className="ib-list">
            {!data && <div className="p-6 text-center"><Spinner /></div>}
            {data && data.conversations.length === 0 && (
              <div className="p-4">
                <EmptyState
                  icon="inbox"
                  title={q || view !== "all" || channel ? "گفتگویی با این فیلتر نیست" : "هنوز گفتگویی نیست"}
                  description={q || view !== "all" || channel ? "فیلتر را عوض کنید." : "از «کانال‌ها» یک کانال وصل کنید؛ پیام مشتری همین‌جا می‌آید."}
                />
              </div>
            )}
            {data?.conversations.map((row) => (
              <Row key={row.id} row={row} selected={row.id === selected} onClick={() => select(row.id)} />
            ))}
            {data && data.conversations.length > 0 && typeof data.total === "number" && (
              <div className="ib-more">
                <span className="text-xs" style={{ color: "var(--text-3)" }}>
                  {faNum(data.conversations.length)} از {faNum(data.total)} گفتگو
                </span>
                {data.has_more && (
                  <button type="button" className="ib-pill" onClick={() => setLimit((n) => n + PAGE)}>
                    نمایش بیشتر
                  </button>
                )}
              </div>
            )}
          </div>
        </section>

        {/* ---------------------------------------------------------- گفتگو */}
        <section className="ib-pane thread" aria-label="گفتگو">
          {selected && data ? (
            <ThreadPane
              key={selected}
              storeId={storeId}
              convId={selected}
              canWrite={data.me.can_write}
              members={data.members}
              onChanged={changed}
              onBack={() => select(null)}
              onInfo={() => setInfo((v) => !v)}
            />
          ) : (
            <div className="grid flex-1 place-items-center p-8 text-center *:min-w-0" style={{ color: "var(--text-3)" }}>
              <div>
                <Icon name="chat" size={36} />
                <p className="mt-2 text-sm">یک گفتگو را از فهرست انتخاب کنید.</p>
                <p className="mt-1 text-xs">گفتگوهای منتظر پاسخ، بالای فهرست و به ترتیبِ انتظار هستند.</p>
              </div>
            </div>
          )}
        </section>

        {/* ---------------------------------------------------------- مشتری */}
        <section className="ib-pane side" aria-label="اطلاعات مشتری">
          {selected && data ? (
            <CustomerPane
              key={selected}
              storeId={storeId}
              convId={selected}
              canWrite={data.me.can_write}
              onOpenConversation={(id) => select(id)}
              onClose={() => setInfo(false)}
            />
          ) : (
            <div className="grid flex-1 place-items-center p-6 text-center text-xs *:min-w-0" style={{ color: "var(--text-3)" }}>
              پروفایل، خریدها و تاریخچهٔ همهٔ کانال‌های مشتری این‌جا دیده می‌شود.
            </div>
          )}
        </section>
      </div>
    </div>
  );
}
