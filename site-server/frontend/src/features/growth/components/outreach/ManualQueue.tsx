import { useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";

import Icon from "../../../../components/Icon";
import { Alert, Badge, Button, Card, EmptyState, Field, Input, Meter, Select, fa } from "../../../../components/ui";
import { g } from "../../api";
import { shortUrl } from "../../format";
import { fetchItems, problem, useAction } from "../../outreach/api";
import { itemLeadId, itemLeadName, MANUAL_QUEUE_STATUSES, reasonText, SUPPRESSION_REASONS } from "../../outreach/labels";
import type { Campaign, ManualOutcome, OutreachItem } from "../../outreach/types";
import { copyText, Kbd, LoadState } from "../bits";
import Modal from "../Modal";
import { Flash, ItemStatusBadge, Ltr } from "./shared";

const KEYS: { code: string; hint: string; label: string }[] = [
  { code: "KeyC", hint: "C", label: "کپیِ متنِ پیام" },
  { code: "KeyO", hint: "O", label: "کپیِ متن و بازکردنِ صفحهٔ تماس در زبانهٔ تازه" },
  { code: "KeyS", hint: "S", label: "فرستادم (ثبتِ «ارسال شد»)" },
  { code: "KeyN", hint: "N", label: "فرم نداشت" },
  { code: "KeyL", hint: "L", label: "نیاز به ورود داشت" },
  { code: "KeyK", hint: "K", label: "رد کردنِ این لید" },
  { code: "KeyD", hint: "D", label: "افزودن به «تماس نگیر»" },
  { code: "KeyE", hint: "E", label: "ویرایشِ متن" },
  { code: "ArrowLeft", hint: "←", label: "موردِ بعدی" },
  { code: "ArrowRight", hint: "→", label: "موردِ قبلی" },
  { code: "Slash", hint: "?", label: "همین راهنما" },
];

/**
 * The hand-work queue: one lead at a time, big message, one key per decision.
 * Shortcuts use the PHYSICAL key (`event.code`), so they work with the Persian keyboard layout too.
 * Nothing is ever sent by this view; the marketer opens the page, pastes the text and submits it, then records the outcome.
 */
export default function ManualQueue({ campaign, onChanged }: { campaign: Campaign; onChanged: () => void }) {
  const [items, setItems] = useState<OutreachItem[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [index, setIndex] = useState(0);
  const [handled, setHandled] = useState(0);
  const [sessionTotal, setSessionTotal] = useState(0);
  const [note, setNote] = useState("");
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState("");
  const [flash, setFlash] = useState<{ tone: "ok" | "warn" | "bad"; text: string } | null>(null);
  const [help, setHelp] = useState(false);
  const [suppress, setSuppress] = useState(false);
  const [reason, setReason] = useState("asked_not_to_contact");
  const [suppressNote, setSuppressNote] = useState("");
  const act = useAction();

  const load = useCallback(async () => {
    setLoadError(null);
    try {
      const list = await fetchItems(campaign.id, MANUAL_QUEUE_STATUSES(campaign.mode));
      setItems(list);
      setIndex(0);
      setHandled(0);
      setSessionTotal(list.length);
    } catch (err) {
      setLoadError(problem(err).message);
    }
  }, [campaign.id, campaign.mode]);

  useEffect(() => {
    void load();
  }, [load]);

  const current = items && items.length > 0 ? items[Math.min(index, items.length - 1)] : null;
  const position = items ? Math.min(index, Math.max(0, items.length - 1)) : 0;
  const leadId = current ? itemLeadId(current) : null;
  const openUrl = current ? current.target_url || current.lead?.website || "" : "";

  useEffect(() => {
    setEditing(false);
    setNote("");
  }, [current?.id]);

  // ------------------------------------------------------------------ actions
  const copy = async () => {
    if (!current) return;
    const ok = await copyText(current.rendered_text);
    setFlash(ok ? { tone: "ok", text: "متنِ پیام کپی شد." } : { tone: "bad", text: "کپی نشد؛ متن را دستی انتخاب و کپی کنید." });
  };

  const openPage = () => {
    if (!current) return;
    if (!openUrl) {
      setFlash({ tone: "bad", text: "این لید آدرسِ صفحهٔ تماس ندارد." });
      return;
    }
    window.open(openUrl, "_blank", "noopener");
    void copyText(current.rendered_text).then((ok) =>
      setFlash(ok ? { tone: "ok", text: "متن کپی شد و صفحه در زبانهٔ تازه باز شد؛ آن را در فرم بچسبانید." } : { tone: "warn", text: "صفحه باز شد ولی کپی نشد؛ متن را دستی کپی کنید." }),
    );
  };

  const removeCurrent = () => {
    setItems((list) => (list ? list.filter((i) => i.id !== current?.id) : list));
    setHandled((h) => h + 1);
    onChanged();
  };

  const outcome = async (kind: ManualOutcome, noteText?: string) => {
    if (!current || act.busy) return;
    const done = await act.run(() => g.post(`/outreach/campaigns/${campaign.id}/items/${current.id}/outcome/`, { outcome: kind, note: (noteText ?? note).trim() }));
    if (done !== undefined) {
      removeCurrent();
      setNote("");
      setFlash({ tone: "ok", text: { sent: "ثبت شد: ارسال شد.", no_form: "ثبت شد: فرم نداشت.", needs_login: "ثبت شد: نیاز به ورود داشت.", skipped: "ردش کردید." }[kind] });
    }
  };

  const doSuppress = async () => {
    if (!current || !leadId) return;
    const done = await act.run(async () => {
      await g.post(`/leads/${leadId}/do-not-contact/`, { reason, note: suppressNote.trim() });
      return g.post(`/outreach/campaigns/${campaign.id}/items/${current.id}/outcome/`, { outcome: "skipped", note: `تماس نگیر${suppressNote.trim() ? `: ${suppressNote.trim()}` : ""}` });
    });
    if (done !== undefined) {
      setSuppress(false);
      setSuppressNote("");
      removeCurrent();
      setFlash({ tone: "ok", text: "به فهرستِ «تماس نگیر» اضافه شد و از صف برداشته شد." });
    }
  };

  const saveEdit = async () => {
    if (!current) return;
    const updated = await act.run(() => g.patch<OutreachItem>(`/outreach/campaigns/${campaign.id}/items/${current.id}/`, { rendered_text: draft }));
    if (updated) {
      setItems((list) => (list ? list.map((i) => (i.id === updated.id ? { ...i, ...updated } : i)) : list));
      setEditing(false);
      setFlash({ tone: "ok", text: "متن ذخیره شد؛ همین متن ثبت می‌شود." });
    }
  };

  const go = (delta: number) => {
    if (!items || items.length === 0) return;
    setIndex(Math.max(0, Math.min(items.length - 1, position + delta)));
  };

  // ------------------------------------------------------------------ keyboard
  const handlers = useRef<Record<string, () => void>>({});
  handlers.current = {
    KeyC: () => void copy(),
    KeyO: openPage,
    KeyS: () => void outcome("sent"),
    KeyN: () => void outcome("no_form"),
    KeyL: () => void outcome("needs_login"),
    KeyK: () => void outcome("skipped"),
    KeyD: () => leadId && setSuppress(true),
    KeyE: () => {
      if (!current) return;
      setDraft(current.rendered_text);
      setEditing((v) => !v);
    },
    ArrowLeft: () => go(1),
    ArrowRight: () => go(-1),
    Slash: () => setHelp((v) => !v),
  };
  const blocked = useRef(false);
  blocked.current = help || suppress;
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.repeat || e.ctrlKey || e.metaKey || e.altKey || blocked.current) return;
      const el = e.target as HTMLElement | null;
      if (el && (el.tagName === "INPUT" || el.tagName === "TEXTAREA" || el.tagName === "SELECT" || el.isContentEditable)) return;
      const fn = handlers.current[e.code];
      if (fn) {
        e.preventDefault();
        fn();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  // ------------------------------------------------------------------ view
  return (
    <div className="space-y-4" data-testid="manual-queue">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="text-sm" style={{ color: "var(--text-2)" }}>
          برای هر لید: متن را کپی کنید، صفحهٔ تماس را باز کنید، پیام را بفرستید و نتیجه را با یک کلید ثبت کنید. این بخش هیچ‌چیزی را خودش نمی‌فرستد.
        </div>
        <div className="flex gap-2">
          <Button variant="secondary" size="sm" onClick={() => setHelp(true)} data-testid="manual-help">
            <Kbd>?</Kbd> کلیدها
          </Button>
          <Button variant="secondary" size="sm" onClick={() => void load()} disabled={act.busy}>
            <Icon name="refresh" size={14} />
            تازه‌سازیِ صف
          </Button>
        </div>
      </div>

      <LoadState loading={items === null && !loadError} error={loadError} onRetry={() => void load()}>
        {items && items.length === 0 ? (
          <Card>
            <EmptyState icon="ok" title={sessionTotal > 0 ? "صف تمام شد" : "صفِ دستی خالی است"}>
              {sessionTotal > 0 ? `${fa(handled)} مورد را در این نوبت انجام دادید.` : "لیدی که نیاز به ارسالِ دستی داشته باشد اینجا می‌آید."}
            </EmptyState>
          </Card>
        ) : (
          items &&
          current && (
            <div className="grid gap-4 lg:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]">
              <Card className="space-y-4" >
                <div>
                  <div className="mb-1 flex items-center justify-between text-xs" style={{ color: "var(--text-3)" }}>
                    <span data-testid="manual-progress">
                      انجام‌شده {fa(handled)} از {fa(sessionTotal)}
                    </span>
                    <span>
                      مورد {fa(position + 1)} از {fa(items.length)} باقی‌مانده
                    </span>
                  </div>
                  <Meter used={handled} total={Math.max(sessionTotal, 1)} />
                </div>

                <div data-testid="manual-card" data-item={current.id} className="space-y-4">
                  <div className="flex flex-wrap items-center gap-2">
                    <h3 className="text-lg font-extrabold" style={{ color: "var(--text)" }}>
                      {itemLeadName(current)}
                    </h3>
                    <ItemStatusBadge status={current.status} label={current.status_label} />
                    {current.forced && <Badge tone="info">اجباری</Badge>}
                    {leadId && (
                      <Link to={`/growth/leads/${leadId}`} target="_blank" className="text-xs no-underline" style={{ color: "var(--brand-strong)" }}>
                        صفحهٔ لید
                      </Link>
                    )}
                  </div>
                  {reasonText(current) && (
                    <Alert tone="warn" title="چرا دستی">
                      {reasonText(current)}
                    </Alert>
                  )}
                  <div className="text-sm" style={{ color: "var(--text-2)" }}>
                    صفحهٔ تماس:{" "}
                    {openUrl ? (
                      <a href={openUrl} target="_blank" rel="noopener noreferrer" style={{ color: "var(--brand-strong)" }}>
                        <Ltr>{shortUrl(openUrl)}</Ltr>
                      </a>
                    ) : (
                      <span style={{ color: "var(--text-3)" }}>ندارد</span>
                    )}
                    {!current.target_url && current.lead?.website && <span className="text-xs" style={{ color: "var(--text-3)" }}> (صفحهٔ اصلیِ سایت)</span>}
                  </div>

                  {current.subject && (
                    <div className="text-sm" style={{ color: "var(--text-2)" }}>
                      موضوع: <b style={{ color: "var(--text)" }}>{current.subject}</b>
                    </div>
                  )}

                  {editing ? (
                    <div className="space-y-2">
                      <textarea className="u-input" rows={12} value={draft} onChange={(e) => setDraft(e.target.value)} dir="auto" aria-label="متنِ پیام" data-testid="manual-edit" autoFocus />
                      <div className="flex gap-2">
                        <Button size="sm" onClick={() => void saveEdit()} disabled={act.busy || !draft.trim() || draft === current.rendered_text}>
                          ذخیره
                        </Button>
                        <Button size="sm" variant="ghost" onClick={() => setEditing(false)}>
                          انصراف
                        </Button>
                      </div>
                    </div>
                  ) : (
                    <pre
                      className="max-h-[22rem] overflow-y-auto whitespace-pre-wrap rounded-xl p-4 text-base leading-8"
                      dir="auto"
                      style={{ background: "var(--surface-2)", border: "1px solid var(--line)", color: "var(--text)", fontFamily: "inherit", margin: 0 }}
                      data-testid="manual-text"
                    >
                      {current.rendered_text}
                    </pre>
                  )}

                  <div className="flex flex-wrap gap-2">
                    <Button variant="secondary" onClick={() => void copy()} data-testid="manual-copy">
                      <Icon name="copy" size={15} /> کپیِ پیام <Kbd>C</Kbd>
                    </Button>
                    <Button variant="secondary" onClick={openPage} disabled={!openUrl} data-testid="manual-open">
                      <Icon name="link" size={15} /> باز کردنِ صفحه <Kbd>O</Kbd>
                    </Button>
                    <Button variant="ghost" onClick={() => handlers.current.KeyE()} data-testid="manual-edit-btn">
                      <Icon name="edit" size={15} /> ویرایشِ متن <Kbd>E</Kbd>
                    </Button>
                  </div>
                </div>

                {flash && (
                  <Flash tone={flash.tone} onClose={() => setFlash(null)}>
                    {flash.text}
                  </Flash>
                )}
                {act.error && <Flash tone="bad">{act.error.message}</Flash>}

                <Field label="یادداشت (اختیاری، همراهِ نتیجه ثبت می‌شود)">
                  <Input value={note} onChange={(e) => setNote(e.target.value)} maxLength={300} data-testid="manual-note" />
                </Field>

                <div className="flex flex-wrap gap-2" data-testid="manual-outcomes">
                  <Button onClick={() => void outcome("sent")} disabled={act.busy} data-testid="outcome-sent">
                    <Icon name="check" size={16} /> فرستادم <Kbd>S</Kbd>
                  </Button>
                  <Button variant="secondary" onClick={() => void outcome("no_form")} disabled={act.busy} data-testid="outcome-no_form">
                    فرم نداشت <Kbd>N</Kbd>
                  </Button>
                  <Button variant="secondary" onClick={() => void outcome("needs_login")} disabled={act.busy} data-testid="outcome-needs_login">
                    نیاز به ورود <Kbd>L</Kbd>
                  </Button>
                  <Button variant="secondary" onClick={() => void outcome("skipped")} disabled={act.busy} data-testid="outcome-skipped">
                    رد کردن <Kbd>K</Kbd>
                  </Button>
                  <Button variant="danger" onClick={() => leadId && setSuppress(true)} disabled={act.busy || !leadId} data-testid="outcome-suppress">
                    <Icon name="ban" size={15} /> تماس نگیر <Kbd>D</Kbd>
                  </Button>
                </div>

                <div className="flex items-center justify-between gap-2">
                  <Button variant="secondary" size="sm" onClick={() => go(-1)} disabled={position <= 0} data-testid="manual-prev">
                    <Icon name="back" size={14} /> قبلی <Kbd>→</Kbd>
                  </Button>
                  <Button variant="secondary" size="sm" onClick={() => go(1)} disabled={position >= items.length - 1} data-testid="manual-next">
                    بعدی <Kbd>←</Kbd> <Icon name="next" size={14} />
                  </Button>
                </div>
              </Card>

              <Card padded={false}>
                <div className="px-4 pt-4 text-sm font-extrabold" style={{ color: "var(--text)" }}>
                  باقی‌مانده‌ها ({fa(items.length)})
                </div>
                <ul className="max-h-[32rem] overflow-y-auto p-2" data-testid="manual-remaining">
                  {items.map((item, i) => (
                    <li key={item.id}>
                      <button
                        type="button"
                        onClick={() => setIndex(i)}
                        className="flex w-full items-center justify-between gap-2 rounded-lg px-3 py-2 text-start text-sm"
                        style={{ background: i === position ? "var(--brand-soft)" : "transparent", color: "var(--text)" }}
                        aria-current={i === position}
                      >
                        <span className="truncate">{itemLeadName(item)}</span>
                        <ItemStatusBadge status={item.status} label={item.status_label} />
                      </button>
                    </li>
                  ))}
                </ul>
              </Card>
            </div>
          )
        )}
      </LoadState>

      <Modal open={help} onClose={() => setHelp(false)} title="کلیدهای میانبر" size="md" testId="manual-help-dialog">
        <p className="mb-3 text-sm" style={{ color: "var(--text-3)" }}>
          با هر زبانِ کیبورد (فارسی یا انگلیسی) کار می‌کنند، به‌شرطی که داخلِ یک کادرِ نوشتاری نباشید.
        </p>
        <table className="w-full text-sm">
          <tbody>
            {KEYS.map((k) => (
              <tr key={k.code}>
                <td className="w-16 py-1.5">
                  <Kbd>{k.hint}</Kbd>
                </td>
                <td style={{ color: "var(--text-2)" }}>{k.label}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Modal>

      <Modal
        open={suppress}
        onClose={() => setSuppress(false)}
        title="افزودن به فهرستِ «تماس نگیر»"
        size="sm"
        busy={act.busy}
        testId="manual-suppress-dialog"
        footer={
          <>
            <Button variant="secondary" onClick={() => setSuppress(false)} disabled={act.busy}>
              انصراف
            </Button>
            <Button variant="danger" onClick={() => void doSuppress()} disabled={act.busy} data-autofocus data-testid="manual-suppress-confirm">
              {act.busy ? "…" : "بله، تماس نگیر"}
            </Button>
          </>
        }
      >
        <div className="space-y-3">
          <p className="text-sm leading-7" style={{ color: "var(--text-2)" }}>
            همهٔ راه‌های تماسِ «{current ? itemLeadName(current) : ""}» (تلفن، ایمیل، سایت، اینستاگرام) به فهرست می‌رود و دیگر هیچ پیامی برایش نمی‌رود. این مورد هم از صف برداشته می‌شود.
          </p>
          <Field label="دلیل">
            <Select value={reason} onChange={(e) => setReason(e.target.value)}>
              {SUPPRESSION_REASONS.map((r) => (
                <option key={r.value} value={r.value}>
                  {r.label}
                </option>
              ))}
            </Select>
          </Field>
          <Field label="یادداشت (اختیاری)">
            <Input value={suppressNote} onChange={(e) => setSuppressNote(e.target.value)} maxLength={300} />
          </Field>
          {act.error && <Flash tone="bad">{act.error.message}</Flash>}
        </div>
      </Modal>
    </div>
  );
}
