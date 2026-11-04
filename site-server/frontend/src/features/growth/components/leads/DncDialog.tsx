import { useEffect, useState } from "react";

import { Alert, Button, Select, TextArea } from "../../../../components/ui";
import { g, problem } from "../../api";
import type { DncReason } from "../../types";
import Modal from "../Modal";
import FormField from "./FormField";

export const DNC_REASONS: { value: DncReason; label: string }[] = [
  { value: "opt_out", label: "خودش خواست پیام نگیرد (لغو)" },
  { value: "asked_not_to_contact", label: "گفت تماس نگیرید" },
  { value: "complaint", label: "شکایت کرد" },
  { value: "invalid_contact", label: "راهِ تماسش اشتباه یا بی‌اعتبار است" },
  { value: "other", label: "دلیلِ دیگر" },
];

/**
 * Put a lead on the do-not-contact list: every phone, e-mail, website and Instagram of the lead is
 * suppressed, so no campaign can pick it up (POST /growth/leads/<id>/do-not-contact/).
 */
export default function DncDialog({ open, leadId, leadName, onClose, onDone }: { open: boolean; leadId: number; leadName: string; onClose: () => void; onDone: () => void }) {
  const [reason, setReason] = useState<DncReason>("asked_not_to_contact");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (open) {
      setError(null);
      setNote("");
    }
  }, [open]);

  const submit = async () => {
    setBusy(true);
    setError(null);
    try {
      await g.post(`/leads/${leadId}/do-not-contact/`, { reason, note });
      onDone();
    } catch (err) {
      const p = problem(err);
      setError(p.status === 404 ? "بخشِ «تماس نگیر» در این نسخه هنوز فعال نیست." : p.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal
      open={open}
      title="افزودن به فهرستِ «تماس نگیر»"
      onClose={onClose}
      size="sm"
      busy={busy}
      testId="dnc-dialog"
      footer={
        <>
          <Button variant="secondary" onClick={onClose} disabled={busy}>
            انصراف
          </Button>
          <Button variant="danger" onClick={submit} disabled={busy} data-testid="dnc-confirm">
            {busy ? "در حال ثبت…" : "به فهرست اضافه شود"}
          </Button>
        </>
      }
    >
      <div className="space-y-3">
        <p className="text-sm leading-7" style={{ color: "var(--text-2)" }}>
          همهٔ تلفن‌ها، ایمیل‌ها، آدرسِ سایت و پیجِ «<b dir="auto">{leadName}</b>» در فهرستِ «تماس نگیر» ثبت می‌شود و هیچ کمپینی نمی‌تواند به او پیام بدهد. هر وقت خواستید می‌توانید برش دارید.
        </p>
        {error && <Alert tone="bad">{error}</Alert>}
        <FormField label="دلیل">
          <Select value={reason} onChange={(e) => setReason(e.target.value as DncReason)} data-testid="dnc-reason">
            {DNC_REASONS.map((r) => (
              <option key={r.value} value={r.value}>
                {r.label}
              </option>
            ))}
          </Select>
        </FormField>
        <FormField label="توضیح (اختیاری)">
          <TextArea rows={2} value={note} onChange={(e) => setNote(e.target.value)} data-testid="dnc-note" />
        </FormField>
      </div>
    </Modal>
  );
}
