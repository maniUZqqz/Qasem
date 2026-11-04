import { Link } from "react-router-dom";

import Icon from "../../../../components/Icon";
import { Badge, Card } from "../../../../components/ui";
import { faDate, shortUrl } from "../../format";
import type { LeadRow } from "../../types";
import { StatusBadge, TagChips } from "../bits";

const SORTABLE: Record<string, string> = { name: "business_name", city: "city", category: "category", status: "status", created: "created_at" };

function instagramHandle(url: string): string {
  return "@" + url.replace(/^https?:\/\/(www\.)?instagram\.com\//, "").replace(/\/$/, "");
}

const ltr = { direction: "ltr", textAlign: "left", unicodeBidi: "plaintext" } as const;

function Dash() {
  return <span style={{ color: "var(--text-3)" }}>—</span>;
}

function SortHeader({ label, field, ordering, onSort }: { label: string; field: string; ordering: string; onSort: (field: string) => void }) {
  const active = ordering === field || ordering === `-${field}`;
  const desc = ordering === `-${field}`;
  return (
    <button type="button" className="inline-flex items-center gap-1 font-semibold" style={{ background: "none", border: 0, color: active ? "var(--text)" : "inherit", cursor: "pointer", font: "inherit", padding: 0 }} onClick={() => onSort(field)} data-testid={`sort-${field}`} aria-label={`مرتب‌سازی بر پایهٔ ${label}`}>
      {label}
      {active && <Icon name={desc ? "down" : "up"} size={12} />}
    </button>
  );
}

/**
 * The lead table (≥ 640 px) and the card list (phones). Selection is owned by the page; this only draws
 * and reports clicks. `data-testid="lead-row"` marks every lead.
 */
export default function LeadTable({
  rows,
  selected,
  onToggle,
  onTogglePage,
  ordering,
  onSort,
  busy,
}: {
  rows: LeadRow[];
  selected: number[];
  onToggle: (id: number) => void;
  onTogglePage: (all: boolean) => void;
  ordering: string;
  onSort: (field: string) => void;
  busy: boolean;
}) {
  const allSelected = rows.length > 0 && rows.every((r) => selected.includes(r.id));
  const someSelected = rows.some((r) => selected.includes(r.id));

  return (
    <div style={{ opacity: busy ? 0.6 : 1, transition: "opacity .15s" }}>
      {/* table: tablets and desktops */}
      <div className="hidden sm:block">
        <Card padded={false}>
          <div className="overflow-x-auto">
            <table className="u-table" data-testid="lead-table">
              <thead>
                <tr>
                  <th style={{ width: 34 }}>
                    <input
                      type="checkbox"
                      checked={allSelected}
                      ref={(el) => {
                        if (el) el.indeterminate = !allSelected && someSelected;
                      }}
                      onChange={(e) => onTogglePage(e.target.checked)}
                      aria-label={`انتخابِ همهٔ ${rows.length} موردِ این صفحه`}
                      data-testid="select-page"
                    />
                  </th>
                  <th>
                    <SortHeader label="نام" field={SORTABLE.name} ordering={ordering} onSort={onSort} />
                  </th>
                  <th>وب‌سایت</th>
                  <th>اینستاگرام</th>
                  <th>تلفن</th>
                  <th>ایمیل</th>
                  <th>
                    <SortHeader label="شهر" field={SORTABLE.city} ordering={ordering} onSort={onSort} />
                  </th>
                  <th>
                    <SortHeader label="دسته" field={SORTABLE.category} ordering={ordering} onSort={onSort} />
                  </th>
                  <th>
                    <SortHeader label="وضعیت" field={SORTABLE.status} ordering={ordering} onSort={onSort} />
                  </th>
                  <th>برچسب</th>
                  <th>
                    <SortHeader label="ثبت" field={SORTABLE.created} ordering={ordering} onSort={onSort} />
                  </th>
                </tr>
              </thead>
              <tbody>
                {rows.map((lead) => (
                  <tr key={lead.id} data-testid="lead-row" data-lead-id={lead.id} style={selected.includes(lead.id) ? { background: "var(--brand-soft)" } : undefined}>
                    <td>
                      <input type="checkbox" checked={selected.includes(lead.id)} onChange={() => onToggle(lead.id)} aria-label={`انتخابِ ${lead.display_name}`} data-testid="select-row" />
                    </td>
                    <td style={{ maxWidth: 220 }}>
                      <div className="flex flex-wrap items-center gap-1.5">
                        <Link to={`/growth/leads/${lead.id}`} className="font-bold" dir="auto" style={{ color: "var(--text)" }} data-testid="lead-link">
                          {lead.display_name}
                        </Link>
                        {lead.is_archived && <Badge tone="warn">بایگانی</Badge>}
                        {lead.do_not_contact && <Badge tone="bad">تماس نگیر</Badge>}
                      </div>
                    </td>
                    <td style={{ maxWidth: 170 }}>
                      {lead.website ? (
                        <a href={lead.website} target="_blank" rel="noopener noreferrer" className="block truncate" style={ltr}>
                          {shortUrl(lead.website)}
                        </a>
                      ) : (
                        <Dash />
                      )}
                    </td>
                    <td style={{ maxWidth: 150 }}>
                      {lead.instagram_url ? (
                        <a href={lead.instagram_url} target="_blank" rel="noopener noreferrer" className="block truncate" style={ltr}>
                          {instagramHandle(lead.instagram_url)}
                        </a>
                      ) : (
                        <Dash />
                      )}
                    </td>
                    <td className="u-num" style={ltr}>
                      {lead.phone || <Dash />}
                    </td>
                    <td style={{ maxWidth: 170 }}>
                      {lead.email ? (
                        <span className="block truncate" style={ltr}>
                          {lead.email}
                        </span>
                      ) : (
                        <Dash />
                      )}
                    </td>
                    <td dir="auto">{lead.city || <Dash />}</td>
                    <td dir="auto" style={{ maxWidth: 140 }}>
                      <span className="block truncate">{lead.category || <Dash />}</span>
                    </td>
                    <td>
                      <StatusBadge status={lead.status} label={lead.status_label} />
                    </td>
                    <td style={{ maxWidth: 170 }}>
                      <TagChips tags={lead.tags} max={2} />
                    </td>
                    <td className="u-num" style={{ color: "var(--text-3)" }}>
                      {faDate(lead.created_at)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      </div>

      {/* cards: phones */}
      <div className="space-y-2.5 sm:hidden" data-testid="lead-cards">
        <label className="flex items-center gap-2 px-1 text-sm" style={{ color: "var(--text-3)" }}>
          <input type="checkbox" checked={allSelected} onChange={(e) => onTogglePage(e.target.checked)} />
          انتخابِ همهٔ این صفحه
        </label>
        {rows.map((lead) => (
          <Card key={lead.id}>
            <div data-testid="lead-card" className="space-y-2">
              <div className="flex items-start gap-2.5">
                <input
                  type="checkbox"
                  className="mt-1.5"
                  checked={selected.includes(lead.id)}
                  onChange={() => onToggle(lead.id)}
                  aria-label={`انتخابِ ${lead.display_name}`}
                />
                <div className="min-w-0 flex-1">
                  <Link to={`/growth/leads/${lead.id}`} className="block break-words font-bold" dir="auto" style={{ color: "var(--text)" }}>
                    {lead.display_name}
                  </Link>
                  <div className="mt-1 flex flex-wrap items-center gap-1.5">
                    <StatusBadge status={lead.status} label={lead.status_label} />
                    {lead.is_archived && <Badge tone="warn">بایگانی</Badge>}
                    {lead.do_not_contact && <Badge tone="bad">تماس نگیر</Badge>}
                  </div>
                </div>
              </div>
              <div className="space-y-0.5 text-sm" style={{ color: "var(--text-2)" }}>
                {(lead.city || lead.category) && <div dir="auto">{[lead.city, lead.category].filter(Boolean).join(" · ")}</div>}
                {lead.phone && <div style={ltr}>{lead.phone}</div>}
                {lead.website && (
                  <a href={lead.website} target="_blank" rel="noopener noreferrer" className="block truncate" style={ltr}>
                    {shortUrl(lead.website)}
                  </a>
                )}
                {lead.instagram_url && (
                  <a href={lead.instagram_url} target="_blank" rel="noopener noreferrer" className="block truncate" style={ltr}>
                    {instagramHandle(lead.instagram_url)}
                  </a>
                )}
                {lead.email && <div className="truncate" style={ltr}>{lead.email}</div>}
              </div>
              {lead.tags.length > 0 && <TagChips tags={lead.tags} max={3} />}
            </div>
          </Card>
        ))}
      </div>
    </div>
  );
}
