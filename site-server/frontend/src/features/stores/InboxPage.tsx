import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { api, errorMessage } from "../../api/client";
import Icon from "../../components/Icon";
import {
  Alert,
  Badge,
  Button,
  Card,
  EmptyState,
  ErrorBox,
  Input,
  PageHeader,
  SectionTitle,
  Select,
  Spinner,
  fa,
} from "../../components/ui";

type Conversation = {
  id: number;
  customer_name: string;
  state: string;
  channel: string;
  channel_title: string;
  assigned_to: number | null;
  assigned_username: string | null;
  tags: string[];
  waiting_minutes: number | null;
  last_message: { role: string; text: string; at: string } | null;
  can_reply: boolean;
};

type ChannelStatus = {
  key: string;
  title: string;
  can_receive: boolean;
  can_send: boolean;
  configured: boolean;
  reason: string;
};

type Inbox = {
  conversations: Conversation[];
  channels: ChannelStatus[];
  counts: { waiting: number; unassigned: number; mine: number };
};

const STATE_LABEL: Record<string, string> = {
  AI: "ایجنت جواب می‌دهد",
  HUMAN: "با شماست",
  ESCALATED: "ارجاع‌شده",
  RESOLVED: "بسته شده",
};

/**
 * Every conversation, from every channel, in one place.
 *
 * Ordered by **longest customer wait**, which is the only ordering a shared
 * queue can justify. The obvious alternative — most recently updated — puts
 * the threads we just answered on top and buries the person waiting since
 * morning, which is exactly backwards.
 *
 * Channels that cannot receive say so up front. A shop that discovers
 * Instagram DMs never arrive by waiting three days for one has been let down
 * by the interface, not by the integration.
 */
export default function InboxPage() {
  const { id } = useParams<{ id: string }>();
  const [inbox, setInbox] = useState<Inbox | null>(null);
  const [filter, setFilter] = useState("");
  const [selected, setSelected] = useState<Conversation | null>(null);
  const [tagDraft, setTagDraft] = useState("");
  const [reply, setReply] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const { data } = await api.get(`/stores/${id}/inbox/${filter}`);
      setInbox(data);
    } catch (err) {
      setError(errorMessage(err));
      setInbox({ conversations: [], channels: [], counts: { waiting: 0, unassigned: 0, mine: 0 } });
    }
  }, [id, filter]);

  useEffect(() => {
    load();
  }, [load]);

  async function take(conversation: Conversation) {
    setError(null);
    try {
      await api.post(`/stores/${id}/inbox/${conversation.id}/assign/`, { username: "me" });
      await load();
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  async function send() {
    if (!selected || !reply.trim()) return;
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const { data } = await api.post(`/stores/${id}/inbox/${selected.id}/reply/`, {
        text: reply,
      });
      setReply("");
      // Delivery and recording are separate outcomes, and the difference
      // matters: a recorded-but-undelivered reply still needs sending another way.
      setNotice(
        data.delivered
          ? "پیام فرستاده شد."
          : `پیام ثبت شد ولی تحویل نشد: ${data.reason}`,
      );
      await load();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  if (inbox === null) return <Spinner />;

  const oneWay = inbox.channels.filter((c) => c.configured && !c.can_receive);
  const unconfigured = inbox.channels.filter((c) => !c.configured);

  /** برچسب‌های یک گفتگو.
   *
   *  اندپوینتش از قبل بود و برچسب‌ها فقط *نمایش* داده می‌شدند — هیچ راهی
   *  برای گذاشتن یا برداشتنشان نبود. برچسبی که فقط خوانده شود، یک ستون
   *  همیشه‌خالی است.
   *
   *  سرور خودش تا ۱۲ برچسب را نگه می‌دارد، تکراری را می‌اندازد و هرکدام
   *  را به ۴۰ نویسه می‌بُرد؛ اینجا همان قرارداد را نمی‌شکنیم. */
  const setTags = async (conversation: Conversation, tags: string[]) => {
    setBusy(true);
    setError(null);
    try {
      await api.post(`/stores/${id}/inbox/${conversation.id}/tags/`, { tags });
      setTagDraft("");
      await load();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <PageHeader
        title="صندوق پیام"
        subtitle="همه‌ی کانال‌ها، یک‌جا — طولانی‌ترین انتظار اول"
        actions={
          <Link to={`/stores/${id}`}>
            <Button variant="secondary">بازگشت</Button>
          </Link>
        }
      />

      <ErrorBox message={error} />
      {notice && (
        <div className="mb-4">
          <Alert tone={notice.includes("تحویل نشد") ? "warn" : "ok"}>{notice}</Alert>
        </div>
      )}

      <div className="mb-4 flex flex-wrap items-center gap-2">
        <Select value={filter} onChange={(e) => setFilter(e.target.value)}>
          <option value="">همه</option>
          <option value="?assigned=nobody">بدون مسئول ({fa(inbox.counts.unassigned)})</option>
          <option value="?assigned=me">مال من ({fa(inbox.counts.mine)})</option>
          <option value="?state=ESCALATED">ارجاع‌شده</option>
          <option value="?state=HUMAN">با آدم</option>
        </Select>
        <Badge tone={inbox.counts.waiting > 0 ? "warn" : "ok"}>
          {fa(inbox.counts.waiting)} نفر منتظر جواب
        </Badge>
      </div>

      {(oneWay.length > 0 || unconfigured.length > 0) && (
        <div className="mb-4 flex flex-col gap-2">
          {oneWay.map((channel) => (
            <Alert key={channel.key} tone="info" title={`${channel.title}: یک‌طرفه`}>
              {channel.reason}
            </Alert>
          ))}
          {unconfigured.length > 0 && (
            <Alert tone="neutral" title="کانال‌های تنظیم‌نشده">
              {unconfigured.map((c) => c.title).join("، ")} — تا تنظیم نشوند، پیامی
              از آن‌ها نمی‌آید و به آن‌ها هم چیزی فرستاده نمی‌شود.
            </Alert>
          )}
        </div>
      )}

      {inbox.conversations.length === 0 ? (
        <EmptyState icon="empty" title="صندوق خالی است" />
      ) : (
        <div className="flex flex-col gap-2">
          {inbox.conversations.map((conversation) => (
            <Card key={conversation.id}>
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div className="min-w-0 flex-1">
                  <div className="mb-1 flex flex-wrap items-center gap-2">
                    <span className="font-bold" style={{ color: "var(--text)" }}>
                      {conversation.customer_name || "مشتری"}
                    </span>
                    <Badge tone="neutral">{conversation.channel_title}</Badge>
                    <Badge tone={conversation.state === "ESCALATED" ? "warn" : "info"}>
                      {STATE_LABEL[conversation.state] ?? conversation.state}
                    </Badge>
                    {conversation.waiting_minutes !== null && (
                      <Badge tone={conversation.waiting_minutes > 60 ? "bad" : "warn"}>
                        {fa(conversation.waiting_minutes)} دقیقه منتظر
                      </Badge>
                    )}
                    {conversation.tags.map((tag) => (
                      <Badge key={tag} tone="brand">
                        {tag}
                      </Badge>
                    ))}
                  </div>
                  {conversation.last_message && (
                    <p className="truncate text-sm" style={{ color: "var(--text-2)" }}>
                      {conversation.last_message.text}
                    </p>
                  )}
                  {conversation.assigned_username && (
                    <p className="text-xs" style={{ color: "var(--text-3)" }}>
                      مسئول: {conversation.assigned_username}
                    </p>
                  )}
                </div>
                <div className="flex gap-2">
                  {!conversation.assigned_to && (
                    <Button variant="secondary" onClick={() => take(conversation)}>
                      من جواب می‌دهم
                    </Button>
                  )}
                  <Button
                    onClick={() => {
                      setSelected(conversation);
                      setNotice(null);
                    }}
                    disabled={!conversation.can_reply}
                  >
                    {conversation.can_reply ? "پاسخ" : "این کانال ارسال ندارد"}
                  </Button>
                </div>
              </div>

              {selected?.id === conversation.id && (
                <div className="mt-3 flex flex-wrap items-end gap-2 border-t pt-3"
                     style={{ borderColor: "var(--line)" }}>
                  <div className="min-w-[14rem] flex-1">
                    <Input
                      id={`reply-${conversation.id}`}
                      value={reply}
                      onChange={(e) => setReply(e.target.value)}
                      placeholder="پاسخ شما…"
                    />
                  </div>
                  <Button onClick={send} disabled={busy || !reply.trim()}>
                    {busy ? "…" : "بفرست"}
                  </Button>
                  <Button variant="ghost" onClick={() => setSelected(null)}>
                    بستن
                  </Button>

                  <div className="w-full">
                    <div className="mb-1.5 text-xs" style={{ color: "var(--text-3)" }}>
                      برچسب‌ها ({fa(conversation.tags.length)} از ۱۲)
                    </div>
                    <div className="flex flex-wrap items-center gap-1.5">
                      {conversation.tags.map((tag) => (
                        <span key={tag} className="u-badge u-badge-brand">
                          {tag}
                          <button
                            onClick={() =>
                              void setTags(
                                conversation,
                                conversation.tags.filter((t) => t !== tag),
                              )
                            }
                            disabled={busy}
                            aria-label={`حذف برچسب ${tag}`}
                            title={`حذف برچسب ${tag}`}
                            style={{
                              background: "none",
                              border: "none",
                              cursor: "pointer",
                              color: "inherit",
                              padding: 0,
                              lineHeight: 0,
                            }}
                          >
                            <Icon name="x" size={11} />
                          </button>
                        </span>
                      ))}
                      {conversation.tags.length < 12 && (
                        <form
                          onSubmit={(e) => {
                            e.preventDefault();
                            const tag = tagDraft.trim();
                            if (!tag || conversation.tags.includes(tag)) return;
                            void setTags(conversation, [...conversation.tags, tag]);
                          }}
                          className="flex items-center gap-1"
                        >
                          <input
                            className="u-input"
                            style={{ width: 130, padding: "4px 9px", fontSize: ".78rem" }}
                            value={tagDraft}
                            onChange={(e) => setTagDraft(e.target.value)}
                            placeholder="برچسب جدید…"
                            maxLength={40}
                          />
                          <Button type="submit" variant="ghost" size="sm" disabled={busy}>
                            <Icon name="plus" size={13} />
                          </Button>
                        </form>
                      )}
                    </div>
                  </div>
                </div>
              )}
            </Card>
          ))}
        </div>
      )}

      <div className="mt-8">
        <SectionTitle>کانال‌ها</SectionTitle>
        <Card>
          <div className="flex flex-col gap-2">
            {inbox.channels.map((channel) => (
              <div key={channel.key} className="flex items-center justify-between gap-3">
                <span style={{ color: "var(--text)" }}>{channel.title}</span>
                <div className="flex gap-2">
                  <Badge tone={channel.can_receive ? "ok" : "neutral"}>
                    {channel.can_receive ? "دریافت ✓" : "دریافت ✗"}
                  </Badge>
                  <Badge tone={channel.can_send ? "ok" : "neutral"}>
                    {channel.can_send ? "ارسال ✓" : "ارسال ✗"}
                  </Badge>
                </div>
              </div>
            ))}
          </div>
        </Card>
      </div>
    </>
  );
}
