import { ChangeEvent, FormEvent, useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";

import Icon from "../../components/Icon";
import { api, errorMessage, fetchAllPages } from "../../api/client";
import { Button, Card, Chip, ErrorBox, Input, Spinner } from "../../components/ui";
import {
  ChatMessage,
  ChatResponse,
  ConversationInfo,
  ConversationState,
  OpenOrder,
  OrderInfo,
  ProductCard,
  Store,
  TicketInfo,
} from "../../types";

interface Bubble {
  role: "CUSTOMER" | "AI" | "SYSTEM";
  text: string;
  products?: ProductCard[];
  order?: OrderInfo | null;
  orderError?: string | null;
  paymentRequest?: { order_id: number; payment_info: string } | null;
  ticket?: TicketInfo | null;
}

const STATE_LABEL: Record<ConversationState, string> = {
  AI: "پاسخ‌گویی خودکار AI",
  HUMAN: "پاسخ‌گویی انسانی",
  ESCALATED: "ارجاع‌شده به انسان",
  RESOLVED: "بسته‌شده",
};

export default function ChatPage() {
  const { id } = useParams<{ id: string }>();
  const [store, setStore] = useState<Store | null>(null);
  const [bubbles, setBubbles] = useState<Bubble[]>([]);
  const [conversationId, setConversationId] = useState<number | null>(null);
  const [state, setState] = useState<ConversationState>("AI");
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [openOrders, setOpenOrders] = useState<OpenOrder[]>([]);
  const [uploading, setUploading] = useState(false);
  const [history, setHistory] = useState<ConversationInfo[]>([]);
  const [showHistory, setShowHistory] = useState(false);
  const [loadingConversation, setLoadingConversation] = useState(false);
  // a local 30B model answers in 1-2 minutes; a silent spinner reads as a crash
  const [thinkingSeconds, setThinkingSeconds] = useState(0);
  const bottomRef = useRef<HTMLDivElement | null>(null);
  const fileRef = useRef<HTMLInputElement | null>(null);

  useEffect(() => {
    void api.get<Store>(`/stores/${id}/`).then((r) => setStore(r.data)).catch(() => {});
  }, [id]);

  // beter.md #1: previous conversations are stored on the server — list them
  const loadHistory = async () => {
    try {
      setHistory(await fetchAllPages<ConversationInfo>(`/stores/${id}/conversations/`));
    } catch {
      setHistory([]);
    }
  };

  useEffect(() => {
    void loadHistory();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id]);

  const openConversation = async (conversation: ConversationInfo) => {
    setLoadingConversation(true);
    setError(null);
    try {
      const { data } = await api.get<ChatMessage[]>(
        `/conversations/${conversation.id}/messages/`,
      );
      setBubbles(
        data.map((message) => ({
          role: message.role === "CUSTOMER" ? "CUSTOMER" : "AI",
          text: message.role === "HUMAN" ? `👤 پشتیبان: ${message.text}` : message.text,
        })),
      );
      setConversationId(conversation.id);
      setState(conversation.state);
      setOpenOrders([]);
      setShowHistory(false);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setLoadingConversation(false);
    }
  };

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [bubbles, busy]);

  useEffect(() => {
    if (!busy) {
      setThinkingSeconds(0);
      return;
    }
    const started = Date.now();
    const timer = window.setInterval(
      () => setThinkingSeconds(Math.floor((Date.now() - started) / 1000)),
      1000,
    );
    return () => window.clearInterval(timer);
  }, [busy]);

  const newConversation = () => {
    setBubbles([]);
    setConversationId(null);
    setState("AI");
    setError(null);
    setOpenOrders([]);
  };

  // the order the customer can currently pay for (receipt upload target)
  const payableOrder = openOrders.find(
    (o) => o.status === "AWAITING_RECEIPT" || o.status === "DRAFT",
  );

  /**
   * Move a conversation between AI / human / resolved.
   *
   * Without this the agent's own ESCALATE action was a one-way door: the AI
   * goes silent on that conversation and nothing in the UI could ever hand it
   * back, so an escalated customer could never be served again.
   */
  const changeState = async (next: ConversationState) => {
    if (!conversationId) return;
    setBusy(true);
    setError(null);
    try {
      const { data } = await api.post<ConversationInfo>(
        `/conversations/${conversationId}/handoff/`,
        { state: next },
      );
      setState(data.state);
      setBubbles((prev) => [
        ...prev,
        {
          role: "SYSTEM",
          text:
            next === "AI"
              ? "🤖 گفتگو به ایجنت AI برگردانده شد — پیام بعدی را دوباره AI جواب می‌دهد."
              : next === "HUMAN"
                ? "👤 گفتگو در اختیار پشتیبان انسانی قرار گرفت — AI دیگر جواب نمی‌دهد."
                : "✅ گفتگو بسته شد.",
        },
      ]);
      void loadHistory();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const uploadReceipt = async (e: ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file || !payableOrder) return;
    setUploading(true);
    setError(null);
    try {
      const form = new FormData();
      form.append("image", file);
      await api.post(`/orders/${payableOrder.order_id}/receipt/`, form, {
        headers: { "Content-Type": "multipart/form-data" },
      });
      setOpenOrders((prev) => prev.filter((o) => o.order_id !== payableOrder.order_id));
      setBubbles((prev) => [
        ...prev,
        {
          role: "SYSTEM",
          text: `🧾 رسید پرداخت سفارش #${payableOrder.order_id} ارسال شد — بعد از تأیید فروشنده، سفارش قطعی می‌شود.`,
        },
      ]);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setUploading(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  };

  const send = async (e: FormEvent) => {
    e.preventDefault();
    const text = input.trim();
    if (!text || busy) return;
    setInput("");
    setError(null);
    setBubbles((prev) => [...prev, { role: "CUSTOMER", text }]);
    setBusy(true);
    try {
      const { data } = await api.post<ChatResponse>(`/stores/${id}/chat/`, {
        message: text,
        conversation_id: conversationId ?? undefined,
      });
      if (data.conversation_id !== conversationId) void loadHistory();
      setConversationId(data.conversation_id);
      setState(data.state);
      setOpenOrders(data.open_orders ?? []);
      if (data.message) {
        const ai: ChatMessage = data.message;
        setBubbles((prev) => [
          ...prev,
          {
            role: "AI",
            text: ai.text,
            products: data.products,
            order: data.order ?? null,
            orderError: data.order_error ?? null,
            paymentRequest: data.payment_request ?? null,
            ticket: data.ticket ?? null,
          },
        ]);
      } else if (data.note) {
        setBubbles((prev) => [...prev, { role: "SYSTEM", text: data.note! }]);
      }
    } catch (err) {
      const reason = errorMessage(err);
      setError(reason);
      setBubbles((prev) => [
        ...prev,
        { role: "SYSTEM", text: `پاسخ AI دریافت نشد — ${reason}` },
      ]);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <Link to={`/stores/${id}`} className="u-back">
            <Icon name="back" size={15} />
            بازگشت به فروشگاه
          </Link>
          <h1
            className="mt-1 text-2xl font-extrabold"
            style={{ color: "var(--text)" }}
          >
            چت فروش {store ? `— ${store.name}` : ""}
          </h1>
          <p className="text-xs text-slate-400">
            این‌جا نقش مشتری را بازی کنید و پاسخ‌گویی ایجنت فروش AI را بسنجید.
          </p>
        </div>
        {/* flex-wrap, because this row holds a chip plus up to three buttons
            with Persian labels on them. Without it the row measured 333px on a
            320px phone and pushed the entire page sideways — the only page in
            the panel that did. */}
        <div className="flex flex-wrap items-center gap-2">
          <Chip>{STATE_LABEL[state]}</Chip>
          {/* the agent can escalate on its own, so the owner must always be able
              to take over and hand the conversation back */}
          {conversationId != null && state !== "AI" && (
            <Button variant="secondary" disabled={busy} onClick={() => void changeState("AI")}>
              🤖 بازگرداندن به AI
            </Button>
          )}
          {conversationId != null && state === "AI" && (
            <Button variant="secondary" disabled={busy} onClick={() => void changeState("HUMAN")}>
              👤 پاسخ‌گویی خودم
            </Button>
          )}
          {conversationId != null && state !== "RESOLVED" && (
            <Button
              variant="secondary"
              disabled={busy}
              onClick={() => void changeState("RESOLVED")}
            >
              ✅ بستن گفتگو
            </Button>
          )}
          <Button
            variant="secondary"
            onClick={() => {
              setShowHistory((v) => !v);
              if (!showHistory) void loadHistory();
            }}
          >
            🗂 گفتگوهای قبلی{history.length > 0 ? ` (${history.length})` : ""}
          </Button>
          <Button variant="secondary" onClick={newConversation}>
            گفتگوی جدید
          </Button>
        </div>
      </div>
      <ErrorBox message={error} />

      {showHistory && (
        <Card>
          <h3 className="mb-2 text-sm font-bold text-slate-700">گفتگوهای ذخیره‌شده</h3>
          {history.length === 0 && (
            <p className="py-4 text-center text-sm text-slate-400">
              هنوز گفتگویی ثبت نشده است.
            </p>
          )}
          <div className="max-h-64 space-y-1 overflow-y-auto">
            {history.map((conversation) => (
              <button
                key={conversation.id}
                onClick={() => void openConversation(conversation)}
                disabled={loadingConversation}
                className={`block w-full rounded-lg border px-3 py-2 text-right text-sm transition hover:bg-violet-50 ${
                  conversation.id === conversationId
                    ? "border-violet-400 bg-violet-50"
                    : "border-slate-100"
                }`}
              >
                <span className="flex items-center justify-between gap-2">
                  <span className="truncate text-slate-700">
                    {conversation.last_message || "(بدون پیام)"}
                  </span>
                  <span className="shrink-0 text-[10px] text-slate-400">
                    {STATE_LABEL[conversation.state]} ·{" "}
                    {new Date(conversation.updated_at).toLocaleString("fa-IR")}
                  </span>
                </span>
              </button>
            ))}
          </div>
        </Card>
      )}

      <Card className="flex h-[60vh] flex-col">
        <div className="flex-1 space-y-3 overflow-y-auto p-1">
          {bubbles.length === 0 && (
            <p className="py-10 text-center text-sm text-slate-400">
              مثلاً بپرسید: «این کفش برای دویدن خوبه؟» یا «سایز ۴۲ موجوده؟ می‌خوامش»
            </p>
          )}
          {bubbles.map((bubble, i) => (
            <div key={i}>
              {bubble.role === "SYSTEM" ? (
                <p className="text-center text-xs text-amber-600">{bubble.text}</p>
              ) : (
                <div
                  className={`max-w-[80%] whitespace-pre-wrap rounded-2xl px-4 py-2 text-sm leading-6 ${
                    bubble.role === "CUSTOMER"
                      ? "mr-auto bg-violet-600 text-white"
                      : "ml-auto bg-slate-100 text-slate-800"
                  }`}
                >
                  {bubble.text}
                </div>
              )}
              {bubble.products && bubble.products.length > 0 && (
                <div className="mt-2 flex flex-wrap gap-2">
                  {bubble.products.map((p) => (
                    <div
                      key={p.id}
                      className="flex items-center gap-2 rounded-lg px-3 py-2 text-xs"
                      style={{ background: "var(--surface-2)", border: "1px solid var(--line)" }}
                    >
                      {p.image && (
                        <img src={p.image} alt={p.name} className="h-8 w-8 rounded object-cover" />
                      )}
                      <div>
                        <div className="font-bold">{p.name}</div>
                        <div className="text-slate-500">
                          {Number(p.price).toLocaleString("fa-IR")} تومان · موجودی{" "}
                          {p.stock_quantity}
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              )}
              {bubble.order && (
                <div className="mt-2 rounded-lg border border-green-200 bg-green-50 px-4 py-2 text-sm text-green-800">
                  🧾 سفارش پیش‌نویس #{bubble.order.id} ثبت شد —{" "}
                  {bubble.order.items
                    .map((it) => `${it.quantity}× ${it.product_name}`)
                    .join("، ")}{" "}
                  — جمع: {Number(bubble.order.total).toLocaleString("fa-IR")} تومان
                </div>
              )}
              {bubble.orderError && (
                <div className="mt-2 rounded-lg border border-amber-200 bg-amber-50 px-4 py-2 text-xs text-amber-800">
                  ثبت سفارش انجام نشد: {bubble.orderError}
                </div>
              )}
              {bubble.paymentRequest && (
                <div className="mt-2 rounded-lg border border-sky-200 bg-sky-50 px-4 py-2 text-sm text-sky-900">
                  💳 اطلاعات پرداخت سفارش #{bubble.paymentRequest.order_id}:
                  <div className="mt-1 whitespace-pre-wrap text-xs">
                    {bubble.paymentRequest.payment_info}
                  </div>
                  <div className="mt-1 text-xs text-sky-700">
                    بعد از پرداخت، عکس رسید را با دکمه «🧾 ارسال رسید» بفرستید.
                  </div>
                </div>
              )}
              {bubble.ticket && (
                <div className="mt-2 rounded-lg border border-orange-200 bg-orange-50 px-4 py-2 text-xs text-orange-800">
                  🎫 تیکت پشتیبانی #{bubble.ticket.id} ثبت شد: {bubble.ticket.subject}
                  {bubble.ticket.priority === "URGENT" && " (فوری)"}
                </div>
              )}
            </div>
          ))}
          {busy && (
            <div className="ml-auto flex w-fit items-center gap-2 rounded-2xl bg-slate-100 px-4 py-2 text-sm text-slate-500">
              <Spinner /> در حال فکر کردن…
              <span className="text-xs text-slate-400">
                ({thinkingSeconds} ثانیه — مدل لوکال است و کمی طول می‌کشد)
              </span>
            </div>
          )}
          <div ref={bottomRef} />
        </div>
        <form onSubmit={send} className="mt-3 flex gap-2 border-t border-slate-100 pt-3">
          <Input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="پیام مشتری را بنویسید…"
            disabled={busy}
            autoFocus
          />
          {payableOrder && (
            <>
              <input
                ref={fileRef}
                type="file"
                accept="image/jpeg,image/png,image/webp"
                className="hidden"
                onChange={uploadReceipt}
              />
              <Button
                type="button"
                variant="secondary"
                disabled={uploading || busy}
                onClick={() => fileRef.current?.click()}
                title={`ارسال رسید پرداخت برای سفارش #${payableOrder.order_id}`}
              >
                {uploading ? "در حال ارسال…" : `🧾 ارسال رسید #${payableOrder.order_id}`}
              </Button>
            </>
          )}
          <Button type="submit" disabled={busy || !input.trim()}>
            ارسال
          </Button>
        </form>
      </Card>
    </div>
  );
}
