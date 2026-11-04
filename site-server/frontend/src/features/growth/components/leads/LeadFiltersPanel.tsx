import { Button, Input, Select } from "../../../../components/ui";
import { useMeta } from "../../MetaContext";
import type { TagWithCount } from "../../types";
import FormField from "./FormField";
import ToggleChip from "./ToggleChip";
import type { LeadFilters } from "./queryState";

const HAS: { key: string; label: string }[] = [
  { key: "website", label: "وب‌سایت دارد" },
  { key: "instagram", label: "اینستاگرام دارد" },
  { key: "phone", label: "تلفن دارد" },
  { key: "email", label: "ایمیل دارد" },
];

const toggle = (list: string[], value: string) => (list.includes(value) ? list.filter((v) => v !== value) : [...list, value]);

/** Every filter of the lead list. Each change goes straight to the URL (the page owns the state). */
export default function LeadFiltersPanel({
  filters,
  tags,
  onChange,
  onClear,
}: {
  filters: LeadFilters;
  tags: TagWithCount[];
  onChange: (patch: Partial<LeadFilters>) => void;
  onClear: () => void;
}) {
  const { meta } = useMeta();
  return (
    <div className="space-y-4" data-testid="filters-panel">
      <div>
        <div className="mb-1.5 text-sm font-medium" style={{ color: "var(--text-2)" }}>
          وضعیت
        </div>
        <div className="flex flex-wrap gap-1.5">
          {(meta?.statuses ?? []).map((s) => (
            <ToggleChip key={s.value} active={filters.status.includes(s.value)} onClick={() => onChange({ status: toggle(filters.status, s.value) })} testId={`filter-status-${s.value}`}>
              {s.label}
            </ToggleChip>
          ))}
        </div>
      </div>

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <FormField label="روشِ کشف">
          <Select value={filters.origin} onChange={(e) => onChange({ origin: e.target.value })} data-testid="filter-origin">
            <option value="">همه</option>
            {(meta?.origins ?? []).map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </Select>
        </FormField>
        <FormField label="کشور">
          <Select value={filters.country} onChange={(e) => onChange({ country: e.target.value })} data-testid="filter-country">
            <option value="">همه</option>
            {(meta?.countries ?? []).map((c) => (
              <option key={c.code} value={c.code}>
                {c.name}
              </option>
            ))}
          </Select>
        </FormField>
        <FormField label="شهر">
          <Input value={filters.city} onChange={(e) => onChange({ city: e.target.value })} data-testid="filter-city" />
        </FormField>
        <FormField label="دسته">
          <Input value={filters.category} onChange={(e) => onChange({ category: e.target.value })} data-testid="filter-category" />
        </FormField>
        <FormField label="ثبت‌شده از تاریخ">
          <Input type="date" dir="ltr" value={filters.created_from} onChange={(e) => onChange({ created_from: e.target.value })} data-testid="filter-from" />
        </FormField>
        <FormField label="ثبت‌شده تا تاریخ">
          <Input type="date" dir="ltr" value={filters.created_to} onChange={(e) => onChange({ created_to: e.target.value })} data-testid="filter-to" />
        </FormField>
        <FormField label="بایگانی">
          <Select value={filters.archived} onChange={(e) => onChange({ archived: e.target.value as LeadFilters["archived"] })} data-testid="filter-archived">
            <option value="0">بدونِ بایگانی</option>
            <option value="1">فقط بایگانی</option>
            <option value="all">همه</option>
          </Select>
        </FormField>
        {filters.source_job && (
          <FormField label="فقط لیدهای ورودیِ شمارهٔ">
            <div className="flex items-center gap-2">
              <span className="u-badge u-badge-brand u-num">{filters.source_job}</span>
              <Button variant="ghost" size="sm" type="button" onClick={() => onChange({ source_job: "" })}>
                برداشتن
              </Button>
            </div>
          </FormField>
        )}
      </div>

      <div>
        <div className="mb-1.5 text-sm font-medium" style={{ color: "var(--text-2)" }}>
          دارد / ندارد
        </div>
        <div className="flex flex-wrap gap-1.5">
          {HAS.map((h) => (
            <ToggleChip key={h.key} active={filters.has.includes(h.key)} onClick={() => onChange({ has: toggle(filters.has, h.key) })} testId={`filter-has-${h.key}`}>
              {h.label}
            </ToggleChip>
          ))}
        </div>
      </div>

      {tags.length > 0 && (
        <div>
          <div className="mb-1.5 text-sm font-medium" style={{ color: "var(--text-2)" }}>
            برچسب (همهٔ انتخاب‌شده‌ها باید روی لید باشد)
          </div>
          <div className="flex flex-wrap gap-1.5">
            {tags.map((t) => (
              <ToggleChip key={t.id} active={filters.tag.includes(t.name)} onClick={() => onChange({ tag: toggle(filters.tag, t.name) })} testId={`filter-tag-${t.id}`}>
                {t.name} ({t.lead_count})
              </ToggleChip>
            ))}
          </div>
        </div>
      )}

      <div>
        <Button variant="secondary" size="sm" type="button" onClick={onClear} data-testid="filters-clear">
          پاک کردنِ فیلترها
        </Button>
      </div>
    </div>
  );
}
