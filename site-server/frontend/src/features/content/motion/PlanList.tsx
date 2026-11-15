import { useState } from "react";

import Icon from "../../../components/Icon";
import { Badge, Button, Card, SectionTitle, fa } from "../../../components/ui";
import { PlanRow } from "./api";

function when(iso: string): string {
  try {
    return new Date(iso).toLocaleString("fa-IR", { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
  } catch {
    return "";
  }
}

/**
 * طرح‌های ذخیره‌شدهٔ فروشگاه: بازکردن، حذف و شروعِ طرحِ تازه. طرح فقط با اولین ویرایش (یا چت/کنترلِ کیفیت/رندر) ساخته می‌شود؛
 * فقط دیدنِ صفحه دیگر طرحِ تازه نمی‌سازد، و مالکِ برگشته می‌تواند ادامهٔ کارش را باز کند.
 */
export default function PlanList({
  rows,
  currentId,
  busy,
  onOpen,
  onDelete,
  onNew,
}: {
  rows: PlanRow[];
  currentId: number | null;
  busy: boolean;
  onOpen: (r: PlanRow) => void;
  onDelete: (r: PlanRow) => void;
  onNew: () => void;
}) {
  const [open, setOpen] = useState(false);
  return (
    <Card>
      <SectionTitle
        action={
          <div className="flex items-center gap-2">
            <Button variant="secondary" size="sm" type="button" onClick={onNew} disabled={busy} title="از نمونهٔ آماده شروع کن؛ طرحِ فعلی در فهرست می‌ماند">
              <Icon name="plus" size={14} /> طرحِ تازه
            </Button>
            <Button variant="ghost" size="sm" type="button" onClick={() => setOpen((v) => !v)} aria-expanded={open}>
              <Icon name={open ? "up" : "down"} size={14} /> {open ? "بستن" : "باز کردن فهرست"}
            </Button>
          </div>
        }
      >
        طرح‌های ذخیره‌شده <Badge tone={rows.length ? "info" : "neutral"}>{fa(rows.length)}</Badge>
      </SectionTitle>
      {!open ? (
        <div className="text-xs leading-6" style={{ color: "var(--text-3)" }}>
          {rows.length ? "هر ویرایشِ شما خودکار ذخیره می‌شود؛ طرح‌های قبلی را از این فهرست دوباره باز یا پاک کنید." : "هنوز طرحی ذخیره نشده؛ با اولین ویرایش، طرح خودکار ذخیره می‌شود."}
        </div>
      ) : rows.length ? (
        <div className="max-h-72 space-y-1 overflow-auto" role="list">
          {rows.map((r) => (
            <div
              key={r.id}
              role="listitem"
              className="flex flex-wrap items-center gap-2 rounded-lg px-2 py-1.5"
              style={{ background: r.id === currentId ? "var(--brand-soft, var(--surface-2))" : "var(--surface-2)" }}
            >
              <div className="min-w-0 flex-1">
                <div className="truncate text-sm font-bold" style={{ color: "var(--text)" }}>
                  {r.title || "طرحِ بی‌نام"}
                  {r.id === currentId ? <span className="ms-2 text-xs font-normal" style={{ color: "var(--brand)" }}>(باز است)</span> : null}
                </div>
                <div className="text-xs leading-6" style={{ color: "var(--text-3)" }}>
                  {fa(r.scenes)} صحنه{r.aspect ? ` · ${fa(r.aspect)}` : ""}
                  {r.renders ? ` · ${fa(r.renders)} رندر` : ""} · {when(r.updated_at)}
                </div>
              </div>
              <Button variant="secondary" size="sm" type="button" onClick={() => onOpen(r)} disabled={busy || r.id === currentId}>
                <Icon name="edit" size={13} /> باز کردن
              </Button>
              <Button variant="ghost" size="sm" type="button" onClick={() => onDelete(r)} disabled={busy} aria-label={`حذفِ ${r.title || "طرح"}`} title="حذفِ طرح (ویدیوهای رندرشده می‌مانند)">
                <Icon name="trash" size={13} />
              </Button>
            </div>
          ))}
        </div>
      ) : (
        <div className="text-xs" style={{ color: "var(--text-3)" }}>
          طرحی نیست.
        </div>
      )}
    </Card>
  );
}
