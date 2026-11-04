import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import Icon from "../../../../components/Icon";
import { Alert, Button } from "../../../../components/ui";
import { StatusBadge } from "../bits";
import Modal from "../Modal";
import { useMeta } from "../../MetaContext";
import type { DuplicateItem, LeadRow } from "../../types";
import MergePreviewTable from "./MergePreviewTable";

/**
 * «این کسب‌وکار از قبل هست»: shows the existing lead(s), what a merge would change, and lets the person
 * merge or skip. Merging never replaces a stored value on its own - only ticked conflicts are replaced.
 */
export default function DuplicateDialog({
  open,
  duplicates,
  similar = [],
  busy = false,
  error,
  onMerge,
  onSkip,
  onClose,
}: {
  open: boolean;
  duplicates: DuplicateItem[];
  similar?: LeadRow[];
  busy?: boolean;
  error?: string | null;
  onMerge: (targetLeadId: number, overwriteFields: string[]) => void;
  onSkip: () => void;
  onClose: () => void;
}) {
  const { kindLabel } = useMeta();
  const [index, setIndex] = useState(0);
  const [overwrite, setOverwrite] = useState<string[]>([]);

  useEffect(() => {
    if (open) {
      setIndex(0);
      setOverwrite([]);
    }
  }, [open, duplicates]);

  const current = duplicates[index];
  if (!current) return <Modal open={false} title="" onClose={onClose}>{null}</Modal>;
  const lead = current.lead;
  const toggle = (field: string) => setOverwrite((list) => (list.includes(field) ? list.filter((f) => f !== field) : [...list, field]));
  const usable = overwrite.filter((f) => current.merge_preview?.fields.some((row) => row.field === f && row.state === "conflict"));

  return (
    <Modal
      open={open}
      title="این کسب‌وکار از قبل در دیتابیس هست"
      onClose={onClose}
      size="lg"
      busy={busy}
      testId="dup-dialog"
      footer={
        <>
          <Button variant="secondary" onClick={onSkip} disabled={busy} data-testid="dup-skip">
            رد کردن (چیزی ثبت نمی‌شود)
          </Button>
          <Button onClick={() => onMerge(lead.id, usable)} disabled={busy} data-testid="dup-merge">
            {busy ? "در حال ادغام…" : usable.length ? `ادغام و جایگزینیِ ${usable.length} مورد` : "ادغام (فقط جای خالی‌ها پر می‌شود)"}
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        {error && <Alert tone="bad">{error}</Alert>}
        <p className="text-sm leading-7" style={{ color: "var(--text-2)" }}>
          چیزی خودکار جایگزین نمی‌شود. اگر ادغام کنید، فقط خانه‌های خالیِ لیدِ فعلی پر می‌شوند و راه‌های تماسِ تازه اضافه می‌شوند؛ مقدارهای متفاوت همان‌طور که هستند می‌مانند، مگر اینکه خودتان تیکتِ «جایگزین شود» را بزنید.
        </p>

        {duplicates.length > 1 && (
          <div className="flex flex-wrap gap-2" role="radiogroup" aria-label="کدام لید؟">
            {duplicates.map((d, i) => (
              <button
                key={d.lead.id}
                type="button"
                role="radio"
                aria-checked={i === index}
                className={`u-badge ${i === index ? "u-badge-brand" : "u-badge-neutral"}`}
                style={{ cursor: "pointer", fontFamily: "inherit", padding: "5px 12px" }}
                onClick={() => {
                  setIndex(i);
                  setOverwrite([]);
                }}
              >
                {d.lead.display_name}
              </button>
            ))}
          </div>
        )}

        <div className="rounded-xl p-3" style={{ background: "var(--surface-2)", border: "1px solid var(--line)" }} data-testid="dup-existing">
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-bold" dir="auto" style={{ color: "var(--text)" }}>
              {lead.display_name}
            </span>
            <StatusBadge status={lead.status} label={lead.status_label} />
            {lead.is_archived && <span className="u-badge u-badge-warn">بایگانی‌شده</span>}
            <Link to={`/growth/leads/${lead.id}`} target="_blank" rel="noopener" className="mr-auto inline-flex items-center gap-1 text-sm">
              باز کردنِ لید
              <Icon name="link" size={13} />
            </Link>
          </div>
          <div className="mt-1.5 flex flex-wrap items-center gap-1.5 text-xs" style={{ color: "var(--text-3)" }}>
            <span>هم‌پوشانی در:</span>
            {current.matched_on.map((m) => (
              <span key={m.kind + m.normalized} className="u-badge u-badge-info" dir="ltr">
                {kindLabel(m.kind)}: {m.value}
              </span>
            ))}
          </div>
        </div>

        {current.merge_preview && <MergePreviewTable preview={current.merge_preview} overwrite={overwrite} onToggle={toggle} />}

        {similar.length > 0 && (
          <div className="text-sm" style={{ color: "var(--text-3)" }} data-testid="dup-similar">
            <span className="font-medium">لیدهای هم‌نام:</span>{" "}
            {similar.map((s, i) => (
              <span key={s.id}>
                {i > 0 && "، "}
                <Link to={`/growth/leads/${s.id}`} target="_blank" rel="noopener" dir="auto">
                  {s.display_name}
                </Link>
              </span>
            ))}
          </div>
        )}
      </div>
    </Modal>
  );
}
