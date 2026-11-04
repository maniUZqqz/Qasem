import { useState } from "react";
import { useNavigate } from "react-router-dom";

import Icon from "../../../../components/Icon";
import { Alert, Badge, Button, Card, Select } from "../../../../components/ui";
import { g, problem } from "../../api";
import { faAgo } from "../../format";
import { useMeta } from "../../MetaContext";
import type { LeadDetail } from "../../types";
import { ConfirmDialog } from "../Modal";
import { StatusBadge } from "../bits";
import DncDialog from "./DncDialog";
import TagEditor from "./TagEditor";

/** The top card of the lead page: name, status, tags, archive / do-not-contact / delete. */
export default function LeadHeader({ lead, onUpdated, onReload }: { lead: LeadDetail; onUpdated: (lead: LeadDetail) => void; onReload: () => void }) {
  const { meta } = useMeta();
  const navigate = useNavigate();
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<{ tone: "ok" | "bad"; text: string } | null>(null);
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [dncOpen, setDncOpen] = useState(false);
  const [undoDncOpen, setUndoDncOpen] = useState(false);

  const patch = async (body: Record<string, unknown>, okText?: string) => {
    setBusy(true);
    setMessage(null);
    try {
      const updated = await g.patch<LeadDetail>(`/leads/${lead.id}/`, body);
      onUpdated(updated);
      if (okText) setMessage({ tone: "ok", text: okText });
    } catch (err) {
      setMessage({ tone: "bad", text: problem(err).message });
    } finally {
      setBusy(false);
    }
  };

  const remove = async () => {
    setBusy(true);
    try {
      await g.del(`/leads/${lead.id}/`, { confirm: 1 });
      navigate("/growth/leads");
    } catch (err) {
      setMessage({ tone: "bad", text: problem(err).message });
      setDeleteOpen(false);
      setBusy(false);
    }
  };

  const undoDnc = async () => {
    setBusy(true);
    try {
      await g.del(`/leads/${lead.id}/do-not-contact/`);
      setUndoDncOpen(false);
      setMessage({ tone: "ok", text: "از فهرستِ «تماس نگیر» برداشته شد." });
      onReload();
    } catch (err) {
      const p = problem(err);
      setMessage({ tone: "bad", text: p.status === 404 ? "بخشِ «تماس نگیر» در این نسخه هنوز فعال نیست." : p.message });
      setUndoDncOpen(false);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card>
      <div className="space-y-3" data-testid="lead-header">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <h2 className="break-words text-xl font-extrabold" dir="auto" style={{ color: "var(--text)" }} data-testid="lead-title">
              {lead.display_name}
            </h2>
            <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
              <StatusBadge status={lead.status} label={lead.status_label} />
              {lead.is_archived && <Badge tone="warn">بایگانی‌شده</Badge>}
              {lead.do_not_contact && (
                <span data-testid="dnc-badge">
                  <Badge tone="bad">تماس نگیر</Badge>
                </span>
              )}
              <span className="text-xs" style={{ color: "var(--text-3)" }}>
                ثبت شد {faAgo(lead.created_at)}
              </span>
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <label className="flex items-center gap-1.5 text-sm" style={{ color: "var(--text-3)" }}>
              وضعیت
              <Select
                value={lead.status}
                onChange={(e) => void patch({ status: e.target.value }, "وضعیت عوض شد.")}
                disabled={busy}
                style={{ width: 160 }}
                data-testid="lead-status-select"
              >
                {(meta?.statuses ?? [{ value: lead.status, label: lead.status_label }]).map((s) => (
                  <option key={s.value} value={s.value}>
                    {s.label}
                  </option>
                ))}
              </Select>
            </label>
            <Button variant="secondary" size="sm" disabled={busy} onClick={() => void patch({ is_archived: !lead.is_archived }, lead.is_archived ? "از بایگانی درآمد." : "بایگانی شد.")} data-testid="lead-archive">
              {lead.is_archived ? "خارج از بایگانی" : "بایگانی"}
            </Button>
            {lead.do_not_contact ? (
              <Button variant="secondary" size="sm" disabled={busy} onClick={() => setUndoDncOpen(true)} data-testid="lead-dnc-undo">
                برداشتن از «تماس نگیر»
              </Button>
            ) : (
              <Button variant="secondary" size="sm" disabled={busy} onClick={() => setDncOpen(true)} data-testid="lead-dnc">
                <Icon name="ban" size={14} />
                تماس نگیر
              </Button>
            )}
            <Button variant="danger" size="sm" disabled={busy} onClick={() => setDeleteOpen(true)} data-testid="lead-delete">
              <Icon name="trash" size={14} />
              حذف
            </Button>
          </div>
        </div>

        <TagEditor tags={lead.tags} busy={busy} onChange={(names) => void patch({ tags: names })} />

        {message && (
          <Alert tone={message.tone}>
            <span data-testid="lead-message">{message.text}</span>
          </Alert>
        )}
      </div>

      <ConfirmDialog
        open={deleteOpen}
        title="حذفِ این لید؟"
        message="لید همراهِ یادداشت‌ها، راه‌های تماس و تاریخچه‌اش برای همیشه پاک می‌شود و برگشت ندارد. اگر فقط نمی‌خواهید ببینیدش، «بایگانی» بهتر است."
        confirmLabel="بله، حذف شود"
        danger
        busy={busy}
        onConfirm={remove}
        onClose={() => !busy && setDeleteOpen(false)}
      />
      <ConfirmDialog
        open={undoDncOpen}
        title="برداشتن از فهرستِ «تماس نگیر»؟"
        message="بعد از این، کمپین‌ها دوباره می‌توانند به این لید پیام بدهند."
        confirmLabel="بله، برداشته شود"
        busy={busy}
        onConfirm={undoDnc}
        onClose={() => !busy && setUndoDncOpen(false)}
      />
      <DncDialog
        open={dncOpen}
        leadId={lead.id}
        leadName={lead.display_name}
        onClose={() => setDncOpen(false)}
        onDone={() => {
          setDncOpen(false);
          setMessage({ tone: "ok", text: "به فهرستِ «تماس نگیر» اضافه شد." });
          onReload();
        }}
      />
    </Card>
  );
}
