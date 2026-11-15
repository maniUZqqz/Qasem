import { Badge } from "../../../components/ui";
import { capabilityPills, technicalRows } from "./capabilities";
import "./capabilities.css";

/**
 * توانایی‌های یک سرورِ پردازش در ردیفِ «سرورها»: فقط برچسب‌های فارسیِ مجاز (ffmpeg، ویرایشگرِ ویدیو، حذفِ پس‌زمینه …)؛ کلیدهای فنیِ عامل
 * پشتِ «جزئیات فنی» (بسته) می‌مانند تا ردیف بلند نشود و هر فیلدِ تازهٔ عامل برچسبِ انگلیسیِ تازه نیاورد.
 */
export default function CapabilityPills({
  caps,
  hidden,
}: {
  caps: Record<string, unknown> | null | undefined;
  /** کلیدهایی که همین ردیف جای دیگری نشان می‌دهد (در جزئیات فنی تکرار نمی‌شوند) */
  hidden?: ReadonlySet<string>;
}) {
  const pills = capabilityPills(caps);
  const rows = technicalRows(caps, hidden);
  return (
    <>
      {pills.map((p) => (
        <Badge key={p.key} tone="brand">
          {p.label}
        </Badge>
      ))}
      {rows.length > 0 && (
        <details className="nmc-tech" data-testid="tech-details">
          <summary>جزئیات فنی</summary>
          <dl dir="ltr">
            {rows.map((r) => (
              <div key={r.key}>
                <dt>{r.key}</dt>
                <dd>{r.value}</dd>
              </div>
            ))}
          </dl>
        </details>
      )}
    </>
  );
}
