import Icon from "../../components/Icon";
import { Alert, Badge, Card, EmptyState, Table, fa } from "../../components/ui";
import { type ScheduledRow, useCampaigns } from "./CampaignsLayout";

/**
 * صف انتشار — چه چیزی رفت، چه چیزی می‌رود، چه چیزی گیر کرد.
 *
 * ترتیب عمدی است: **گیرکرده‌ها اول**. یک صف که به ترتیب زمان مرتب شود،
 * شکستِ سه روز پیش را زیر بیست ردیف موفق دفن می‌کند — و شکستی که دیده
 * نشود، همان پستی است که مشتری فکر می‌کند رفته و نرفته.
 */

const PLATFORM_LABEL: Record<string, string> = {
  instagram: "اینستاگرام",
  telegram: "تلگرام",
  linkedin: "لینکدین",
  whatsapp: "واتس‌اپ",
};

const TONE: Record<string, "info" | "ok" | "bad" | "warn" | "neutral"> = {
  PENDING: "info",
  SENT: "ok",
  FAILED: "bad",
  MISSED: "warn",
};

const when = (iso: string | null) =>
  iso
    ? new Date(iso).toLocaleString("fa-IR", {
        month: "short",
        day: "numeric",
        hour: "2-digit",
        minute: "2-digit",
      })
    : "—";

export default function PublishQueuePage() {
  const { scheduled } = useCampaigns();

  const rank = (r: ScheduledRow) =>
    r.status === "FAILED" ? 0 : r.status === "MISSED" ? 1 : r.status === "PENDING" ? 2 : 3;

  const rows = [...scheduled].sort(
    (a, b) =>
      rank(a) - rank(b) ||
      new Date(a.scheduled_for).getTime() - new Date(b.scheduled_for).getTime(),
  );

  const failed = rows.filter((r) => r.status === "FAILED");
  const missed = rows.filter((r) => r.status === "MISSED");

  if (rows.length === 0) {
    return (
      <Card>
        <EmptyState icon="upload" title="صف خالی است">
          هیچ انتشاری زمان‌بندی نشده. کمپینِ تأییدشده را از تب «کمپین‌ها» زمان‌بندی کنید.
        </EmptyState>
      </Card>
    );
  }

  return (
    <div className="space-y-4">
      {failed.length > 0 && (
        <Alert tone="bad" title={`${fa(failed.length)} انتشار شکست خورد`}>
          پیام خطای هر کدام در ستون آخر است. تا وقتی درست نشده، آن پست{" "}
          <strong>منتشر نشده</strong> — نه اینکه دیر منتشر شود.
        </Alert>
      )}
      {missed.length > 0 && (
        <Alert tone="warn" title={`${fa(missed.length)} انتشار پنجره‌اش را از دست داد`}>
          زمان‌بند دیر منتشر می‌کند ولی هرگز زود؛ وقتی تأخیر از حد بگذرد، به‌جای
          فرستادنِ یک پستِ بی‌موقع، آن را «از دست رفته» علامت می‌زند تا خودتان تصمیم
          بگیرید.
        </Alert>
      )}

      <Card padded={false}>
        <Table>
          <thead>
            <tr>
              <th>کمپین</th>
              <th>پلتفرم</th>
              <th>زمان مقرر</th>
              <th>وضعیت</th>
              <th>منتشر شد در</th>
              <th>خطا</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.id}>
                <td style={{ color: "var(--text)", fontWeight: 500 }}>{row.campaign}</td>
                <td>{PLATFORM_LABEL[row.platform] ?? row.platform}</td>
                <td className="u-num">{when(row.scheduled_for)}</td>
                <td>
                  <Badge tone={TONE[row.status] ?? "neutral"}>
                    {row.status === "FAILED" && <Icon name="warn" size={12} />}
                    {row.status === "SENT" && <Icon name="check" size={12} />}
                    {row.status_label}
                  </Badge>
                </td>
                <td className="u-num">{when(row.published_at)}</td>
                <td style={{ color: row.error ? "var(--bad)" : "var(--text-3)" }}>
                  {row.error || "—"}
                </td>
              </tr>
            ))}
          </tbody>
        </Table>
      </Card>

      <p className="text-xs leading-6" style={{ color: "var(--text-3)" }}>
        زمان‌بند هر دقیقه صف را نگاه می‌کند. هر کار با یک به‌روزرسانی شرطی «گرفته»
        می‌شود، پس اگر دو ورکر همزمان بیدار شوند، یک پست دو بار منتشر نمی‌شود.
      </p>
    </div>
  );
}
