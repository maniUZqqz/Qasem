import { Alert, Badge, Button, Card, Input, SectionTitle, Select, Spinner, fa } from "../../../../components/ui";
import { num } from "../../format";
import { useMeta } from "../../MetaContext";
import type { CsvCheck, CsvUpload } from "../../types";
import FormField from "../leads/FormField";

export type MappingState = {
  mapping: Record<string, string>;
  country: string;
  city: string;
  tagsText: string;
  extractAfter: boolean;
};

/** Step 2: which CSV column feeds which field, defaults, and the live dry-run of every row. */
export default function CsvMappingStep({
  upload,
  state,
  onChange,
  check,
  checking,
  checkError,
  onBack,
  onNext,
}: {
  upload: CsvUpload;
  state: MappingState;
  onChange: (patch: Partial<MappingState>) => void;
  check: CsvCheck | null;
  checking: boolean;
  checkError: string | null;
  onBack: () => void;
  onNext: () => void;
}) {
  const { meta } = useMeta();
  const targets = upload.targets;
  const countries = meta?.countries ?? [{ code: "IR", name: "ایران" }];
  const setTarget = (header: string, target: string) => onChange({ mapping: { ...state.mapping, [header]: target } });
  const columnIndex = (header: string) => upload.headers.indexOf(header);
  const samples = (header: string) => {
    const i = columnIndex(header);
    return upload.sample_rows
      .map((r) => r.cells[i])
      .filter((v) => v && v.trim())
      .slice(0, 3);
  };
  const usable = !!check && check.total_rows > 0 && check.valid_rows > 0 && !checkError && !checking;

  return (
    <div className="space-y-5" data-testid="csv-step-2">
      <p className="text-sm leading-7" style={{ color: "var(--text-2)" }}>
        فایل <b dir="auto">{upload.file_name}</b> با {fa(upload.total_rows)} ردیف خوانده شد (کدگذاری {upload.encoding}). برای هر ستون بگویید به کدام فیلد برود؛ ستون‌هایی که لازم ندارید را «نادیده بگیر» بگذارید.
      </p>

      <Card padded={false}>
        <div className="overflow-x-auto">
          <table className="u-table" data-testid="mapping-table">
            <thead>
              <tr>
                <th>ستونِ فایل</th>
                <th>نمونهٔ مقدارها</th>
                <th>برود به</th>
              </tr>
            </thead>
            <tbody>
              {upload.headers.map((header) => (
                <tr key={header}>
                  <td className="font-medium" dir="auto" style={{ color: "var(--text)" }}>
                    {header}
                  </td>
                  <td dir="auto" style={{ maxWidth: 260 }}>
                    <span className="block truncate" style={{ color: "var(--text-3)" }}>
                      {samples(header).join(" ، ") || "—"}
                    </span>
                  </td>
                  <td style={{ minWidth: 190 }}>
                    <Select
                      value={state.mapping[header] ?? ""}
                      onChange={(e) => setTarget(header, e.target.value)}
                      aria-label={`مقصدِ ستونِ ${header}`}
                      data-testid={`map-${columnIndex(header)}`}
                    >
                      <option value="">— نادیده بگیر —</option>
                      {targets.map((t) => {
                        const takenByOther = !t.multi && Object.entries(state.mapping).some(([h, v]) => v === t.key && h !== header);
                        return (
                          <option key={t.key} value={t.key} disabled={takenByOther}>
                            {t.label}
                          </option>
                        );
                      })}
                    </Select>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>

      <div className="grid gap-4 sm:grid-cols-2">
        <FormField label="کشورِ پیش‌فرض" hint="برای ردیف‌هایی که ستونِ کشورشان خالی است (یا ستونِ کشور وصل نشده).">
          <Select value={state.country} onChange={(e) => onChange({ country: e.target.value })} data-testid="csv-country">
            <option value="">— نامشخص —</option>
            {countries.map((c) => (
              <option key={c.code} value={c.code}>
                {c.name}
              </option>
            ))}
          </Select>
        </FormField>
        <FormField label="شهرِ پیش‌فرض" hint="اختیاری؛ برای ردیف‌هایی که شهرشان خالی است.">
          <Input value={state.city} onChange={(e) => onChange({ city: e.target.value })} data-testid="csv-city" />
        </FormField>
        <FormField label="برچسبِ همهٔ لیدهای این ورودی" hint="اختیاری؛ با کاما جدا کنید. مثلاً: ورودی آبان، نمایشگاه">
          <Input value={state.tagsText} onChange={(e) => onChange({ tagsText: e.target.value })} data-testid="csv-tags" />
        </FormField>
        <div className="flex items-end">
          <label className="flex cursor-pointer items-start gap-2 text-sm leading-6" style={{ color: "var(--text-2)" }}>
            <input
              type="checkbox"
              className="mt-1.5"
              checked={state.extractAfter}
              onChange={(e) => onChange({ extractAfter: e.target.checked })}
              data-testid="csv-extract-after"
            />
            <span>
              پس از ورود، اطلاعاتِ تماس را از سایتِ لیدها بخوان
              <span className="block text-xs" style={{ color: "var(--text-3)" }}>
                فقط صفحه‌های تماس/دربارهٔ خودِ سایتِ لید، با رعایتِ robots.txt. برای لیدهای بدونِ سایت کاری نمی‌کند.
              </span>
            </span>
          </label>
        </div>
      </div>

      <Card>
        <SectionTitle>بررسیِ همهٔ ردیف‌ها (بدونِ ثبت)</SectionTitle>
        <div data-testid="csv-check">
          {checking && !check && (
            <div className="py-4 text-center">
              <Spinner />
            </div>
          )}
          {checkError && (
            <Alert tone="warn">
              <span data-testid="csv-check-error">{checkError}</span>
            </Alert>
          )}
          {check && !checkError && (
            <div className="space-y-3" style={{ opacity: checking ? 0.6 : 1 }}>
              <div className="flex flex-wrap items-center gap-2 text-sm">
                <Badge tone="ok">{num(check.valid_rows)} ردیفِ سالم</Badge>
                <Badge tone={check.error_rows ? "bad" : "neutral"}>{num(check.error_rows)} ردیفِ خطادار</Badge>
                <span style={{ color: "var(--text-3)" }}>از {num(check.total_rows)} ردیف</span>
                {check.error_rows > 0 && (
                  <span className="text-xs" style={{ color: "var(--text-3)" }}>
                    ردیف‌های خطادار ثبت نمی‌شوند؛ بعد از ورود فایلِ خطاها را می‌گیرید.
                  </span>
                )}
              </div>

              {check.errors.length > 0 && (
                <ul className="space-y-1 text-xs" style={{ color: "var(--bad)" }} data-testid="csv-check-errors">
                  {check.errors.slice(0, 6).map((e) => (
                    <li key={e.row}>
                      ردیف {fa(e.row)}: {e.errors.map((x) => x.message).join(" ؛ ")}
                    </li>
                  ))}
                  {check.errors.length > 6 && <li style={{ color: "var(--text-3)" }}>و {fa(check.errors.length - 6)} ردیفِ دیگر…</li>}
                </ul>
              )}

              <div className="overflow-x-auto">
                <table className="u-table" data-testid="csv-sample">
                  <thead>
                    <tr>
                      <th>ردیف</th>
                      <th>نام</th>
                      <th>وب‌سایت</th>
                      <th>اینستاگرام</th>
                      <th>تلفن</th>
                      <th>ایمیل</th>
                      <th>شهر</th>
                      <th>نتیجه</th>
                    </tr>
                  </thead>
                  <tbody>
                    {check.sample.map((row) => (
                      <tr key={row.row}>
                        <td className="u-num">{fa(row.row)}</td>
                        <td dir="auto">{row.summary.business_name || "—"}</td>
                        <td dir="ltr" style={{ textAlign: "left" }}>{row.summary.website.replace(/^https?:\/\//, "") || "—"}</td>
                        <td dir="ltr" style={{ textAlign: "left" }}>{row.summary.instagram.replace(/^https?:\/\/(www\.)?instagram\.com\//, "@").replace(/\/$/, "") || "—"}</td>
                        <td dir="ltr" style={{ textAlign: "left" }}>{row.summary.phones.join("، ") || "—"}</td>
                        <td dir="ltr" style={{ textAlign: "left" }}>{row.summary.emails.join("، ") || "—"}</td>
                        <td dir="auto">{row.summary.city || "—"}</td>
                        <td>{row.ok ? <Badge tone="ok">سالم</Badge> : <Badge tone="bad">خطا</Badge>}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </div>
      </Card>

      <div className="flex flex-wrap items-center justify-between gap-2">
        <Button variant="secondary" onClick={onBack} data-testid="csv-back">
          فایلِ دیگر
        </Button>
        <Button onClick={onNext} disabled={!usable} data-testid="csv-next">
          ادامه
        </Button>
      </div>
    </div>
  );
}
