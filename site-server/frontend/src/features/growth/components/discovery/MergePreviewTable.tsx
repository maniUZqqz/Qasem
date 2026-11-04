import { Badge } from "../../../../components/ui";
import { useMeta } from "../../MetaContext";
import type { MergePreview } from "../../types";

/**
 * What a merge would do, field by field. Nothing is replaced unless the person ticks «جایگزین شود» on a
 * conflicting row; empty fields are filled, identical ones are left, different ones keep the stored value.
 */
export default function MergePreviewTable({
  preview,
  overwrite,
  onToggle,
}: {
  preview: MergePreview;
  overwrite: string[];
  onToggle: (field: string) => void;
}) {
  const { kindLabel } = useMeta();
  const rows = preview.fields;
  const hasContacts = preview.contacts_new.length + preview.contacts_known.length + preview.contacts_elsewhere.length > 0;

  return (
    <div className="space-y-3" data-testid="merge-preview">
      {rows.length > 0 && (
        <div className="overflow-x-auto">
          <table className="u-table" style={{ minWidth: 480 }}>
            <thead>
              <tr>
                <th>فیلد</th>
                <th>در دیتابیس</th>
                <th>ورودیِ تازه</th>
                <th>نتیجه</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.field} data-testid={`merge-row-${row.field}`}>
                  <td className="font-medium" style={{ color: "var(--text)" }}>
                    {row.label}
                  </td>
                  <td dir="auto">{row.existing || <span style={{ color: "var(--text-3)" }}>خالی</span>}</td>
                  <td dir="auto">{row.incoming}</td>
                  <td>
                    {row.state === "fill" && <Badge tone="ok">جای خالی پر می‌شود</Badge>}
                    {row.state === "same" && <Badge>یکسان است</Badge>}
                    {row.state === "conflict" && (
                      <div className="space-y-1">
                        <Badge tone="warn">فرق دارد</Badge>
                        <label className="flex cursor-pointer items-center gap-1.5 text-xs" style={{ color: "var(--text-2)" }}>
                          <input
                            type="checkbox"
                            checked={overwrite.includes(row.field)}
                            onChange={() => onToggle(row.field)}
                            data-testid={`overwrite-${row.field}`}
                          />
                          جایگزین شود
                        </label>
                        {!overwrite.includes(row.field) && (
                          <span className="block text-[11px]" style={{ color: "var(--text-3)" }}>
                            مقدارِ فعلی می‌ماند
                          </span>
                        )}
                      </div>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {hasContacts && (
        <div className="space-y-1.5 text-sm">
          {preview.contacts_new.length > 0 && (
            <div className="flex flex-wrap items-center gap-1.5">
              <Badge tone="ok">اضافه می‌شود</Badge>
              {preview.contacts_new.map((c) => (
                <span key={c.kind + c.value} className="u-badge u-badge-neutral" dir="ltr" title={kindLabel(c.kind)}>
                  {kindLabel(c.kind)}: {c.value}
                </span>
              ))}
            </div>
          )}
          {preview.contacts_known.length > 0 && (
            <div className="flex flex-wrap items-center gap-1.5">
              <Badge>از قبل دارد</Badge>
              {preview.contacts_known.map((c) => (
                <span key={c.kind + c.value} className="u-badge u-badge-neutral" dir="ltr">
                  {kindLabel(c.kind)}: {c.value}
                </span>
              ))}
            </div>
          )}
          {preview.contacts_elsewhere.length > 0 && (
            <div className="flex flex-wrap items-center gap-1.5">
              <Badge tone="warn">مالِ لیدِ دیگری است؛ منتقل نمی‌شود</Badge>
              {preview.contacts_elsewhere.map((c) => (
                <span key={c.kind + c.value} className="u-badge u-badge-neutral" dir="ltr">
                  {kindLabel(c.kind)}: {c.value}
                </span>
              ))}
            </div>
          )}
        </div>
      )}
      {preview.tags_new.length > 0 && (
        <div className="flex flex-wrap items-center gap-1.5 text-sm">
          <Badge tone="ok">برچسبِ تازه</Badge>
          {preview.tags_new.map((tag) => (
            <Badge key={tag} tone="brand">
              {tag}
            </Badge>
          ))}
        </div>
      )}
      {rows.length === 0 && !hasContacts && preview.tags_new.length === 0 && (
        <p className="text-sm" style={{ color: "var(--text-3)" }}>
          ورودیِ تازه چیزِ جدیدی ندارد؛ ادغام فقط یک «منبع» به لید اضافه می‌کند.
        </p>
      )}
    </div>
  );
}
