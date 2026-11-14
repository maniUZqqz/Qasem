import { fa } from "../../../../components/ui";
import type { ProjectRow } from "../api";

/** «۱:۰۵» — مدتِ آخرین خروجی */
export function lengthLabel(seconds: number | undefined | null): string {
  const s = Number(seconds);
  if (!Number.isFinite(s) || s <= 0) return "";
  const total = Math.round(s);
  return fa(`${Math.floor(total / 60)}:${String(total % 60).padStart(2, "0")}`);
}

/** «۲۳ آبان» (تقویمِ فارسی)؛ اگر تاریخ خوانده نشد، خالی */
export function dateLabel(iso: string | undefined | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  try {
    return d.toLocaleDateString("fa-IR", { month: "long", day: "numeric" });
  } catch {
    return "";
  }
}

/** برچسبِ یک گزینه در فهرستِ «پروژه‌های دیگر»: نام · تاریخِ آخرین ویرایش · مدت (اگر خروجی گرفته شده) */
export function projectOptionLabel(r: Pick<ProjectRow, "id" | "title" | "updated_at" | "render_info">): string {
  const parts = [r.title || `پروژه ${fa(r.id)}`, dateLabel(r.updated_at), lengthLabel(r.render_info?.seconds)];
  return parts.filter(Boolean).join(" · ");
}
