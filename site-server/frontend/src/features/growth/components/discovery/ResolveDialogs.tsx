import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { Alert, Button } from "../../../../components/ui";
import type { JobRow } from "../../types";
import Modal from "../Modal";
import MergePreviewTable from "./MergePreviewTable";

/** Fields a person may choose to replace in bulk (names as the server's OVERWRITABLE list). */
export const OVERWRITABLE_FIELDS: { field: string; label: string }[] = [
  { field: "business_name", label: "نام کسب‌وکار" },
  { field: "category", label: "دسته" },
  { field: "description", label: "توضیحات" },
  { field: "country", label: "کشور" },
  { field: "city", label: "شهر" },
  { field: "website", label: "وب‌سایت" },
  { field: "instagram_url", label: "اینستاگرام" },
  { field: "language", label: "زبان" },
  { field: "business_type", label: "نوع کسب‌وکار" },
  { field: "address", label: "نشانی" },
];

/** Merge or skip ONE duplicate row of an import, with the per-field «جایگزین شود» choice. */
export function RowMergeDialog({
  row,
  busy,
  error,
  onMerge,
  onSkip,
  onClose,
}: {
  row: JobRow | null;
  busy: boolean;
  error: string | null;
  onMerge: (targetLeadId: number | undefined, overwrite: string[]) => void;
  onSkip: () => void;
  onClose: () => void;
}) {
  const [overwrite, setOverwrite] = useState<string[]>([]);
  useEffect(() => setOverwrite([]), [row?.id]);
  if (!row) return null;
  const first = row.matches[0];
  const toggle = (field: string) => setOverwrite((l) => (l.includes(field) ? l.filter((f) => f !== field) : [...l, field]));
  const usable = overwrite.filter((f) => row.merge_preview?.fields.some((r) => r.field === f && r.state === "conflict"));
  return (
    <Modal
      open
      title={`ردیف ${row.row_number}: تکراری`}
      onClose={onClose}
      size="lg"
      busy={busy}
      testId="row-merge-dialog"
      footer={
        <>
          <Button variant="secondary" onClick={onSkip} disabled={busy}>
            رد کردن
          </Button>
          <Button onClick={() => onMerge(first?.lead_id, usable)} disabled={busy} data-testid="row-merge-go">
            {busy ? "در حال ادغام…" : usable.length ? `ادغام و جایگزینیِ ${usable.length} مورد` : "ادغام (فقط جای خالی‌ها پر می‌شود)"}
          </Button>
        </>
      }
    >
      <div className="space-y-3">
        {error && <Alert tone="bad">{error}</Alert>}
        {first && (
          <p className="text-sm" style={{ color: "var(--text-2)" }}>
            لیدِ موجود:{" "}
            <Link to={`/growth/leads/${first.lead_id}`} target="_blank" rel="noopener" dir="auto" className="font-medium">
              {first.name}
            </Link>
            {row.matches.length > 1 && <span style={{ color: "var(--text-3)" }}> (با {row.matches.length - 1} لیدِ دیگر هم هم‌پوشانی دارد؛ ادغام با لیدِ اول انجام می‌شود)</span>}
          </p>
        )}
        {row.merge_preview ? (
          <MergePreviewTable preview={row.merge_preview} overwrite={overwrite} onToggle={toggle} />
        ) : (
          <p className="text-sm" style={{ color: "var(--text-3)" }}>
            مقایسه در دسترس نیست؛ ادغام فقط جای خالی‌ها را پر می‌کند.
          </p>
        )}
      </div>
    </Modal>
  );
}

/** Merge ALL waiting duplicates of an import. Nothing is replaced unless a field is ticked here. */
export function BulkMergeDialog({
  open,
  count,
  busy,
  error,
  onConfirm,
  onClose,
}: {
  open: boolean;
  count: number;
  busy: boolean;
  error: string | null;
  onConfirm: (overwrite: string[]) => void;
  onClose: () => void;
}) {
  const [overwrite, setOverwrite] = useState<string[]>([]);
  useEffect(() => {
    if (open) setOverwrite([]);
  }, [open]);
  const toggle = (field: string) => setOverwrite((l) => (l.includes(field) ? l.filter((f) => f !== field) : [...l, field]));
  return (
    <Modal
      open={open}
      title={`ادغامِ همهٔ ${count} تکراری`}
      onClose={onClose}
      size="md"
      busy={busy}
      testId="bulk-merge-dialog"
      footer={
        <>
          <Button variant="secondary" onClick={onClose} disabled={busy}>
            انصراف
          </Button>
          <Button onClick={() => onConfirm(overwrite)} disabled={busy} data-testid="bulk-merge-go">
            {busy ? "در حال ادغام…" : `ادغام ${count} ردیف`}
          </Button>
        </>
      }
    >
      <div className="space-y-3 text-sm leading-7" style={{ color: "var(--text-2)" }}>
        {error && <Alert tone="bad">{error}</Alert>}
        <p>
          پیش‌فرض: فقط خانه‌های خالیِ لیدهای موجود پر می‌شود و راه‌های تماسِ تازه اضافه می‌شود. هیچ مقدارِ ذخیره‌شده‌ای عوض نمی‌شود.
        </p>
        <p className="font-medium" style={{ color: "var(--text)" }}>
          اگر می‌خواهید در همهٔ ردیف‌ها مقدارِ فایل جای مقدارِ فعلی بنشیند، فیلدش را تیک بزنید:
        </p>
        <div className="grid grid-cols-2 gap-2">
          {OVERWRITABLE_FIELDS.map((f) => (
            <label key={f.field} className="flex cursor-pointer items-center gap-2">
              <input type="checkbox" checked={overwrite.includes(f.field)} onChange={() => toggle(f.field)} data-testid={`bulk-overwrite-${f.field}`} />
              {f.label}
            </label>
          ))}
        </div>
        {overwrite.length > 0 && (
          <Alert tone="warn">در همهٔ ردیف‌ها، «{overwrite.map((f) => OVERWRITABLE_FIELDS.find((x) => x.field === f)?.label ?? f).join("، ")}» با مقدارِ فایل جایگزین می‌شود.</Alert>
        )}
      </div>
    </Modal>
  );
}
