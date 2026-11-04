import { Link } from "react-router-dom";

import Icon from "../../../../components/Icon";
import { Button } from "../../../../components/ui";
import { useMeta } from "../../MetaContext";
import type { DuplicateItem } from "../../types";
import Modal from "../Modal";
import { StatusBadge } from "../bits";

/**
 * Shown when an edit would take a website / Instagram / phone / e-mail that already belongs to another lead
 * (HTTP 409). The edit changed nothing; this says whose it is.
 */
export default function OwningLeadDialog({ open, duplicates, onClose }: { open: boolean; duplicates: DuplicateItem[]; onClose: () => void }) {
  const { kindLabel } = useMeta();
  return (
    <Modal
      open={open}
      title="این مقدار مالِ لیدِ دیگری است"
      onClose={onClose}
      size="md"
      testId="owner-dialog"
      footer={
        <Button variant="secondary" onClick={onClose}>
          فهمیدم
        </Button>
      }
    >
      <p className="mb-3 text-sm leading-7" style={{ color: "var(--text-2)" }}>
        هر آدرس، پیج، تلفن یا ایمیل فقط می‌تواند برای یک لید ثبت شود تا یک کسب‌وکار دوبار نیاید. تغییری ذخیره نشد.
      </p>
      <ul className="space-y-2">
        {duplicates.map((d) => (
          <li key={d.lead.id} className="rounded-xl p-3" style={{ background: "var(--surface-2)", border: "1px solid var(--line)" }}>
            <div className="flex flex-wrap items-center gap-2">
              <span className="font-bold" dir="auto" style={{ color: "var(--text)" }}>
                {d.lead.display_name}
              </span>
              <StatusBadge status={d.lead.status} label={d.lead.status_label} />
              <Link to={`/growth/leads/${d.lead.id}`} target="_blank" rel="noopener" className="mr-auto inline-flex items-center gap-1 text-sm">
                باز کردنِ لید
                <Icon name="link" size={13} />
              </Link>
            </div>
            <div className="mt-1.5 flex flex-wrap gap-1.5 text-xs">
              {d.matched_on.map((m) => (
                <span key={m.kind + m.normalized} className="u-badge u-badge-info" dir="ltr">
                  {kindLabel(m.kind)}: {m.value}
                </span>
              ))}
            </div>
          </li>
        ))}
      </ul>
    </Modal>
  );
}
