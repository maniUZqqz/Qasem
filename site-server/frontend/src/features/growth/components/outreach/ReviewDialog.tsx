import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import Icon from "../../../../components/Icon";
import { Alert, Badge, Button, Field, Input, fa } from "../../../../components/ui";
import { g, useGet } from "../../api";
import { faDateTime } from "../../format";
import { useAction } from "../../outreach/api";
import { itemLeadId, itemLeadName, reasonText } from "../../outreach/labels";
import type { ApproveResult, GrowthSettings, OutreachItem } from "../../outreach/types";
import Modal, { ConfirmDialog } from "../Modal";
import { AttemptBox, DryRunTable, PlanFacts } from "./DryRun";
import { Flash, ItemStatusBadge, Ltr } from "./shared";

/** Items whose text can still be changed (nothing has been sent for them). */
const EDITABLE = ["pending", "ready", "needs_manual", "approved"];

/**
 * Review one item: the exact final message, the target form, and the dry run of what will be POSTed.
 * Approving here approves only this item; editing the text or subject invalidates an approval (the server
 * recomputes the fingerprint) and the dialog says so.
 */
export default function ReviewDialog({
  open,
  campaignId,
  itemIds,
  index,
  onIndex,
  onClose,
  onChanged,
  settings,
  capRemaining,
}: {
  open: boolean;
  campaignId: number;
  itemIds: number[];
  index: number;
  onIndex: (i: number) => void;
  onClose: () => void;
  onChanged: () => void;
  settings: GrowthSettings | null;
  capRemaining: number;
}) {
  const itemId = itemIds[index];
  const detail = useGet<OutreachItem>(open && itemId ? `/outreach/campaigns/${campaignId}/items/${itemId}/` : null);
  const item = detail.data && detail.data.id === itemId ? detail.data : null;
  const [text, setText] = useState("");
  const [subject, setSubject] = useState("");
  const [flash, setFlash] = useState<{ tone: "ok" | "warn" | "bad"; text: string } | null>(null);
  const [askRerender, setAskRerender] = useState(false);
  const save = useAction();
  const approve = useAction();
  const rerender = useAction();

  useEffect(() => {
    if (item) {
      setText(item.rendered_text);
      setSubject(item.subject);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [item?.id, item?.rendered_text, item?.subject]);

  useEffect(() => {
    setFlash(null);
    save.clear();
    approve.clear();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [itemId, open]);

  const editable = !!item && EDITABLE.includes(item.status);
  const dirty = !!item && (text !== item.rendered_text || subject !== item.subject);
  const wasApproved = item?.status === "approved";

  const saveText = async () => {
    if (!item) return;
    const updated = await save.run(() => g.patch<OutreachItem>(`/outreach/campaigns/${campaignId}/items/${item.id}/`, { rendered_text: text, subject }));
    if (updated) {
      detail.setData(updated);
      onChanged();
      setFlash(
        wasApproved && updated.status !== "approved"
          ? { tone: "warn", text: "متن عوض شد، پس تأییدِ قبلیِ این مورد باطل شد. اگر درست است دوباره تأیید کنید." }
          : { tone: "ok", text: "متن ذخیره شد." },
      );
    }
  };

  const doRerender = async () => {
    if (!item) return;
    const updated = await rerender.run(() => g.post<OutreachItem>(`/outreach/campaigns/${campaignId}/items/${item.id}/rerender/`));
    if (updated) {
      setAskRerender(false);
      detail.reload();
      onChanged();
      setFlash({ tone: "ok", text: "متن دوباره از قالب و اطلاعاتِ فعلیِ لید ساخته شد." });
    }
  };

  const doApprove = async () => {
    if (!item) return;
    const result = await approve.run(() => g.post<ApproveResult>(`/outreach/campaigns/${campaignId}/approve/`, { item_ids: [item.id] }));
    if (!result) return;
    onChanged();
    detail.reload();
    setFlash(
      result.approved > 0
        ? { tone: "ok", text: `تأیید شد. این پیام در نوبتِ ارسال قرار گرفت (سقفِ باقی‌ماندهٔ امروز: ${fa(capRemaining)}).` }
        : { tone: "bad", text: result.refused[0]?.text ?? "تأیید نشد." },
    );
  };

  const doRevoke = async () => {
    if (!item) return;
    const result = await approve.run(() => g.post(`/outreach/campaigns/${campaignId}/revoke/`, { item_ids: [item.id] }));
    if (result !== undefined) {
      onChanged();
      detail.reload();
      setFlash({ tone: "ok", text: "تأیید لغو شد؛ این مورد دیگر ارسال نمی‌شود تا دوباره تأیید کنید." });
    }
  };

  const canApprove = !!item && item.status === "ready" && !dirty;
  const approval = item?.approval;
  const leadId = item ? itemLeadId(item) : null;

  return (
    <>
    <Modal
      open={open}
      onClose={onClose}
      size="xl"
      title={item ? `بررسیِ پیام برای ${itemLeadName(item)}` : "بررسیِ پیام"}
      testId="review-dialog"
      busy={save.busy || approve.busy || askRerender}
      footer={
        <>
          <div className="me-auto flex items-center gap-2">
            <Button variant="secondary" size="sm" onClick={() => onIndex(index - 1)} disabled={index <= 0} aria-label="موردِ قبلی" data-testid="review-prev">
              <Icon name="back" size={14} />
              قبلی
            </Button>
            <span className="u-num text-xs" style={{ color: "var(--text-3)" }}>
              {fa(index + 1)} از {fa(itemIds.length)}
            </span>
            <Button variant="secondary" size="sm" onClick={() => onIndex(index + 1)} disabled={index >= itemIds.length - 1} aria-label="موردِ بعدی" data-testid="review-next">
              بعدی
              <Icon name="next" size={14} />
            </Button>
          </div>
          {item?.status === "approved" && (
            <Button variant="secondary" onClick={doRevoke} disabled={approve.busy} data-testid="review-revoke">
              لغوِ تأیید
            </Button>
          )}
          {item?.status === "ready" && (
            <Button onClick={doApprove} disabled={!canApprove || approve.busy || !settings} data-testid="review-approve" title={dirty ? "اول متنِ ویرایش‌شده را ذخیره کنید" : undefined}>
              <Icon name="check" size={16} />
              تأییدِ این مورد
            </Button>
          )}
          <Button variant="secondary" onClick={onClose}>
            بستن
          </Button>
        </>
      }
    >
      {detail.loading && !item ? (
        <div className="py-8 text-center" style={{ color: "var(--text-3)" }}>
          در حال بارگذاری…
        </div>
      ) : detail.error ? (
        <Flash tone="bad">{detail.error}</Flash>
      ) : item ? (
        <div className="space-y-5">
          <div className="flex flex-wrap items-center gap-2 text-sm">
            <ItemStatusBadge status={item.status} label={item.status_label} />
            {approval && (
              <Badge tone={approval.valid && item.status === "approved" ? "ok" : "warn"}>
                {approval.valid && item.status === "approved" ? "تأییدِ معتبر" : "تأییدِ قبلی باطل شد"}
              </Badge>
            )}
            {item.forced && <Badge tone="info">اجباری (با وجودِ پیامِ قبلی)</Badge>}
            {leadId && (
              <Link to={`/growth/leads/${leadId}`} target="_blank" className="text-xs no-underline" style={{ color: "var(--brand-strong)" }}>
                صفحهٔ لید
              </Link>
            )}
            {approval?.at && (
              <span className="text-xs" style={{ color: "var(--text-3)" }}>
                {approval.by ? `${approval.by} · ` : ""}
                {faDateTime(approval.at)}
              </span>
            )}
          </div>

          {reasonText(item) && (
            <Alert tone="warn" title="چرا خودکار نمی‌شود">
              {reasonText(item)}
            </Alert>
          )}
          {flash && (
            <Flash tone={flash.tone} onClose={() => setFlash(null)}>
              {flash.text}
            </Flash>
          )}
          {approve.error && <Flash tone="bad">{approve.error.message}</Flash>}

          <div className="grid gap-5 lg:grid-cols-2">
            {/* --------------------------------------------------------- message */}
            <div className="space-y-3">
              <h3 className="text-sm font-extrabold" style={{ color: "var(--text)" }}>
                متنِ دقیقِ پیام
              </h3>
              <Field label="موضوع">
                <Input value={subject} onChange={(e) => setSubject(e.target.value)} disabled={!editable} maxLength={200} data-testid="review-subject" />
              </Field>
              <Field label="متن (با مشخصاتِ فرستنده و جملهٔ لغو)">
                <textarea className="u-input" rows={12} value={text} onChange={(e) => setText(e.target.value)} disabled={!editable} dir="auto" data-testid="review-text" />
              </Field>
              {editable && dirty && wasApproved && (
                <Alert tone="warn" title="این مورد تأیید شده است">
                  اگر ذخیره کنید تأییدِ این مورد باطل می‌شود و باید دوباره تأیید کنید.
                </Alert>
              )}
              {save.error && <Flash tone="bad">{save.error.message}</Flash>}
              {editable && (
                <div className="flex flex-wrap gap-2">
                  <Button size="sm" onClick={saveText} disabled={!dirty || save.busy || !text.trim()} data-testid="review-save">
                    {save.busy ? "…" : "ذخیرهٔ تغییرها"}
                  </Button>
                  <Button
                    size="sm"
                    variant="secondary"
                    onClick={() => (dirty ? setAskRerender(true) : void doRerender())}
                    disabled={rerender.busy}
                    title="متن را دوباره از قالب و اطلاعاتِ فعلیِ لید می‌سازد"
                  >
                    <Icon name="refresh" size={14} />
                    ساختنِ دوبارهٔ متن
                  </Button>
                </div>
              )}
              {rerender.error && <Flash tone="bad">{rerender.error.message}</Flash>}
            </div>

            {/* --------------------------------------------------------- the form */}
            <div className="space-y-3">
              <h3 className="text-sm font-extrabold" style={{ color: "var(--text)" }}>
                فرمِ مقصد و آنچه دقیقاً فرستاده می‌شود
              </h3>
              {item.target_url ? (
                <p className="text-sm">
                  <a href={item.target_url} target="_blank" rel="noopener noreferrer" style={{ color: "var(--brand-strong)" }} data-testid="review-target">
                    <Ltr>{item.target_url}</Ltr>
                  </a>
                </p>
              ) : (
                <p className="text-sm" style={{ color: "var(--text-3)" }}>
                  آدرسِ صفحهٔ تماس ندارد.
                </p>
              )}
              <PlanFacts plan={item.plan} />
              <DryRunTable plan={item.plan} />
              {item.plan_checked_at && (
                <p className="text-xs" style={{ color: "var(--text-3)" }}>
                  فرم در {faDateTime(item.plan_checked_at)} بررسی شد. هنگامِ ارسال، فرم دوباره خوانده می‌شود و اگر چیزی عوض شده باشد (مثلاً کپچا اضافه شده)، ارسال نمی‌شود.
                </p>
              )}
            </div>
          </div>

          {item.attempt && <AttemptBox attempt={item.attempt} />}
        </div>
      ) : null}
    </Modal>
    <ConfirmDialog
      open={askRerender}
      title="ویرایش‌های شما کنار گذاشته شود؟"
      confirmLabel="بله، دوباره بساز"
      busy={rerender.busy}
      onConfirm={doRerender}
      onClose={() => setAskRerender(false)}
      message="متنی که ویرایش کرده‌اید ذخیره نشده است و با ساختنِ دوبارهٔ متن از بین می‌رود."
    />
    </>
  );
}
