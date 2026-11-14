import type { ProjectRow } from "../api";
import { projectOptionLabel } from "./projectLabel";

/**
 * «پروژه‌های دیگر» در تبِ خروجی: قبلاً یک جعبهٔ تمام‌عرضِ بی‌برچسب بود که نامِ همین پروژه را زیرِ خانهٔ «نام» دوباره نشان می‌داد.
 * حالا برچسب دارد، فقط پروژه‌های دیگر را فهرست می‌کند (با تاریخ و مدت)، و بعد از انتخاب همان‌جا سرِ جایش برمی‌گردد.
 */
export default function ProjectPicker({ projects, projectId, onOpen }: { projects: ProjectRow[]; projectId: number | null; onOpen: (id: number | null) => void }) {
  const others = projects.filter((r) => r.id !== projectId);
  if (others.length === 0 && projectId === null) return null;
  return (
    <label className="ws-field out-proj-others" data-testid="project-others">
      <span>پروژه‌های دیگر</span>
      <select
        className="u-input out-proj-select"
        value=""
        onChange={(e) => {
          const v = e.target.value;
          if (v === "new") onOpen(null);
          else if (v) onOpen(Number(v));
        }}
        aria-label="پروژه‌های دیگر"
        data-testid="project-select"
      >
        <option value="">{others.length ? "یک پروژهٔ دیگر را باز کنید…" : "پروژهٔ دیگری نیست"}</option>
        {projectId !== null && <option value="new">پروژهٔ تازهٔ خالی</option>}
        {others.map((r) => <option key={r.id} value={r.id}>{projectOptionLabel(r)}</option>)}
      </select>
    </label>
  );
}
