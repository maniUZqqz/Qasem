import { FormEvent, useState } from "react";

import Icon from "../../../../components/Icon";
import { Alert, Badge, Button, Card, EmptyState, Input, Select } from "../../../../components/ui";
import { g, problem } from "../../api";
import { useMeta } from "../../MetaContext";
import type { Contact, DuplicateItem, LeadDetail } from "../../types";
import Modal, { ConfirmDialog } from "../Modal";
import FormField from "./FormField";
import OwningLeadDialog from "./OwningLeadDialog";
import { contactSourceText } from "./provenance";

const LINK_KINDS = ["website", "instagram", "telegram", "eitaa", "bale", "rubika", "linkedin", "contact_form"];
const ltr = { direction: "ltr", textAlign: "left", unicodeBidi: "plaintext" } as const;

function Confidence({ value }: { value: number | null }) {
  if (value === null || value === undefined) return null;
  return (
    <Badge tone={value >= 80 ? "ok" : value >= 60 ? "info" : "warn"}>
      <span data-testid="confidence">اطمینان {new Intl.NumberFormat("fa-IR").format(value)}٪</span>
    </Badge>
  );
}

function ContactRow({ contact, busy, onPrimary, onEdit, onRemove }: { contact: Contact; busy: boolean; onPrimary: () => void; onEdit: () => void; onRemove: () => void }) {
  const isLink = LINK_KINDS.includes(contact.kind) && /^https?:\/\//.test(contact.value);
  const source = contactSourceText(contact.source_ref);
  return (
    <li className="space-y-1.5 py-3" data-testid="contact-row" data-kind={contact.kind}>
      <div className="flex flex-wrap items-center gap-2">
        {isLink ? (
          <a href={contact.value} target="_blank" rel="noopener noreferrer" className="break-all font-medium" style={ltr}>
            {contact.value}
          </a>
        ) : (
          <span className="break-all font-medium" style={{ ...ltr, color: "var(--text)" }}>
            {contact.value}
          </span>
        )}
        {contact.is_primary && <Badge tone="brand">اصلی</Badge>}
        {contact.label && <Badge>{contact.label}</Badge>}
        <Confidence value={contact.confidence} />
        <span className="mr-auto flex gap-1">
          {!contact.is_primary && (
            <Button size="sm" variant="ghost" onClick={onPrimary} disabled={busy} data-testid="contact-primary">
              اصلی شود
            </Button>
          )}
          <Button size="sm" variant="ghost" onClick={onEdit} disabled={busy} aria-label="ویرایش" data-testid="contact-edit">
            <Icon name="edit" size={14} />
          </Button>
          <Button size="sm" variant="ghost" onClick={onRemove} disabled={busy} aria-label="حذف" data-testid="contact-remove">
            <Icon name="trash" size={14} />
          </Button>
        </span>
      </div>
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs" style={{ color: "var(--text-3)" }}>
        <span className="u-badge u-badge-neutral" style={{ fontWeight: 500 }} data-testid="contact-source">
          منبع: {source}
        </span>
        {contact.source_url && (
          <a href={contact.source_url} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1" data-testid="contact-source-url">
            صفحهٔ منبع
            <Icon name="link" size={12} />
          </a>
        )}
        {contact.evidence && <span dir="auto">مدرک: {contact.evidence}</span>}
      </div>
    </li>
  );
}

/** The «راه‌های تماس» tab: grouped by kind, each with where and how it was found; add, edit, remove. */
export default function ContactsTab({ lead, onChanged }: { lead: LeadDetail; onChanged: () => void }) {
  const { meta, kindLabel } = useMeta();
  const [kind, setKind] = useState("phone");
  const [value, setValue] = useState("");
  const [label, setLabel] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [owners, setOwners] = useState<DuplicateItem[]>([]);
  const [editing, setEditing] = useState<Contact | null>(null);
  const [editValue, setEditValue] = useState("");
  const [editLabel, setEditLabel] = useState("");
  const [editError, setEditError] = useState<string | null>(null);
  const [removing, setRemoving] = useState<Contact | null>(null);

  const kinds = meta?.contact_kinds ?? [];
  const grouped = kinds.map((k) => ({ ...k, items: lead.contacts.filter((c) => c.kind === k.value) })).filter((k) => k.items.length > 0);

  const call = async (fn: () => Promise<unknown>, onError: (message: string) => void): Promise<boolean> => {
    setBusy(true);
    try {
      await fn();
      onChanged();
      return true;
    } catch (err) {
      const p = problem(err);
      const duplicates = p.body?.duplicates;
      if (p.status === 409 && Array.isArray(duplicates)) setOwners(duplicates as DuplicateItem[]);
      else onError(p.message);
      return false;
    } finally {
      setBusy(false);
    }
  };

  const add = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    const ok = await call(() => g.post(`/leads/${lead.id}/contacts/`, { kind, value, label }), setError);
    if (ok) {
      setValue("");
      setLabel("");
    }
  };

  const save = async () => {
    if (!editing) return;
    setEditError(null);
    const body: Record<string, string> = {};
    if (editValue.trim() !== editing.value) body.value = editValue.trim();
    if (editLabel !== editing.label) body.label = editLabel;
    if (!Object.keys(body).length) {
      setEditing(null);
      return;
    }
    if (await call(() => g.patch(`/leads/${lead.id}/contacts/${editing.id}/`, body), setEditError)) setEditing(null);
  };

  const remove = async () => {
    if (!removing) return;
    if (await call(() => g.del(`/leads/${lead.id}/contacts/${removing.id}/`), setError)) setRemoving(null);
    else setRemoving(null);
  };

  return (
    <div className="space-y-4" data-testid="contacts-tab">
      <Card>
        <form onSubmit={add} className="grid items-end gap-3 sm:grid-cols-[10rem_1fr_12rem_auto]" data-testid="contact-add-form">
          <FormField label="نوع">
            <Select value={kind} onChange={(e) => setKind(e.target.value)} data-testid="contact-kind">
              {kinds.map((k) => (
                <option key={k.value} value={k.value}>
                  {k.label}
                </option>
              ))}
            </Select>
          </FormField>
          <FormField label="مقدار">
            <Input dir="ltr" style={{ textAlign: "left" }} value={value} onChange={(e) => setValue(e.target.value)} placeholder="09121234567 / info@shop.ir / https://…" data-testid="contact-value" />
          </FormField>
          <FormField label="برچسب (اختیاری)">
            <Input value={label} onChange={(e) => setLabel(e.target.value)} placeholder="مثلاً موبایلِ مدیر" data-testid="contact-label" />
          </FormField>
          <Button type="submit" disabled={busy || !value.trim()} data-testid="contact-add">
            <Icon name="plus" size={15} />
            افزودن
          </Button>
        </form>
        {error && (
          <div className="mt-3">
            <Alert tone="bad">
              <span data-testid="contact-error">{error}</span>
            </Alert>
          </div>
        )}
      </Card>

      {grouped.length === 0 ? (
        <Card>
          <EmptyState icon="inbox" title="هنوز راهِ تماسی ثبت نشده">از فرمِ بالا اضافه کنید، یا از تبِ «استخراج» بگذارید سایتِ لید خوانده شود.</EmptyState>
        </Card>
      ) : (
        grouped.map((group) => (
          <Card key={group.value}>
            <h3 className="mb-1 text-sm font-bold" style={{ color: "var(--text)" }}>
              {group.label} <span style={{ color: "var(--text-3)" }}>({new Intl.NumberFormat("fa-IR").format(group.items.length)})</span>
            </h3>
            <ul className="divide-y" style={{ borderColor: "var(--line)" }}>
              {group.items.map((c) => (
                <ContactRow
                  key={c.id}
                  contact={c}
                  busy={busy}
                  onPrimary={() => void call(() => g.patch(`/leads/${lead.id}/contacts/${c.id}/`, { is_primary: true }), setError)}
                  onEdit={() => {
                    setEditing(c);
                    setEditValue(c.value);
                    setEditLabel(c.label);
                    setEditError(null);
                  }}
                  onRemove={() => setRemoving(c)}
                />
              ))}
            </ul>
          </Card>
        ))
      )}

      <Modal
        open={editing !== null}
        title={editing ? `ویرایشِ ${kindLabel(editing.kind)}` : ""}
        onClose={() => !busy && setEditing(null)}
        size="sm"
        busy={busy}
        testId="contact-edit-dialog"
        footer={
          <>
            <Button variant="secondary" onClick={() => setEditing(null)} disabled={busy}>
              انصراف
            </Button>
            <Button onClick={save} disabled={busy} data-testid="contact-edit-save">
              ذخیره
            </Button>
          </>
        }
      >
        <div className="space-y-3">
          {editError && <Alert tone="bad">{editError}</Alert>}
          <FormField label="مقدار" hint="اگر عوض کنید، منبعش «ثبت دستی» می‌شود.">
            <Input dir="ltr" style={{ textAlign: "left" }} value={editValue} onChange={(e) => setEditValue(e.target.value)} data-testid="contact-edit-value" />
          </FormField>
          <FormField label="برچسب">
            <Input value={editLabel} onChange={(e) => setEditLabel(e.target.value)} />
          </FormField>
        </div>
      </Modal>

      <ConfirmDialog
        open={removing !== null}
        title="حذفِ راهِ تماس"
        message={removing ? <span dir="auto">«{removing.value}» از این لید برداشته می‌شود.</span> : ""}
        confirmLabel="حذف شود"
        danger
        busy={busy}
        onConfirm={remove}
        onClose={() => !busy && setRemoving(null)}
      />
      <OwningLeadDialog open={owners.length > 0} duplicates={owners} onClose={() => setOwners([])} />
    </div>
  );
}
