import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { errorMessage } from "../../api/client";
import { Badge, Button, Card, ErrorBox, Select, Spinner } from "../../components/ui";
import { FollowUp, del, get } from "./api";
import { dateTimeText, faNum } from "./format";
import { useInbox } from "./InboxLayout";

const TONE: Record<string, "neutral" | "ok" | "warn" | "bad"> = { PENDING: "warn", SENT: "ok", CANCELLED: "neutral", FAILED: "bad" };

export default function FollowUpsPage() {
  const { storeId, me } = useInbox();
  const [status, setStatus] = useState("PENDING");
  const [kind, setKind] = useState("");
  const [mine, setMine] = useState(false);
  const [rows, setRows] = useState<FollowUp[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const params: Record<string, string> = {};
      if (status) params.status = status;
      if (kind) params.kind = kind;
      if (mine) params.mine = "1";
      setRows((await get<{ followups: FollowUp[] }>(storeId, "followups/", params)).followups);
      setError(null);
    } catch (err) {
      setError(errorMessage(err));
    }
  }, [storeId, status, kind, mine]);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <div className="grid gap-4 *:min-w-0">
      <p className="text-sm" style={{ color: "var(--text-2)" }}>
        پیگیری‌هایی که خودتان از داخل گفتگو ثبت کرده‌اید، یادآوری‌های پرداخت و نظرسنجی‌های بعد از بستنِ گفتگو این‌جا یک‌جا دیده می‌شوند. برای ساختن پیگیری، گفتگو را باز کنید و «پیگیری» را بزنید.
      </p>
      <div className="flex flex-wrap items-center gap-3">
        <Select value={status} onChange={(e) => setStatus(e.target.value)} style={{ width: 150 }} aria-label="وضعیت">
          <option value="PENDING">در انتظار</option>
          <option value="SENT">انجام‌شده</option>
          <option value="FAILED">ناموفق</option>
          <option value="CANCELLED">لغوشده</option>
          <option value="">همه</option>
        </Select>
        <Select value={kind} onChange={(e) => setKind(e.target.value)} style={{ width: 170 }} aria-label="نوع">
          <option value="">همهٔ نوع‌ها</option>
          <option value="FOLLOWUP">پیگیری</option>
          <option value="PAYMENT">یادآوری پرداخت</option>
          <option value="SURVEY">نظرسنجی</option>
        </Select>
        {me?.can_write && (
          <label className="flex items-center gap-2 text-sm" style={{ color: "var(--text-2)" }}>
            <input type="checkbox" checked={mine} onChange={(e) => setMine(e.target.checked)} /> فقط مال من
          </label>
        )}
      </div>
      <ErrorBox message={error} />
      {!rows ? (
        <div className="py-8 text-center"><Spinner /></div>
      ) : (
        <Card padded={false}>
          <div className="ib-table-wrap">
            <table className="u-table">
              <thead><tr><th>نوع</th><th>مشتری</th><th>متن</th><th>زمان</th><th>وضعیت</th><th>مسئول</th><th /></tr></thead>
              <tbody>
                {rows.length === 0 && <tr><td colSpan={7} className="p-6 text-center" style={{ color: "var(--text-3)" }}>چیزی نیست.</td></tr>}
                {rows.map((f) => (
                  <tr key={f.id}>
                    <td>{f.kind_title}{f.target === "AGENT" && <div className="text-xs" style={{ color: "var(--text-3)" }}>یادآوری به همکار</div>}</td>
                    <td>{f.customer || "—"}</td>
                    <td style={{ maxWidth: 320 }}>{f.text}</td>
                    <td className="u-num">{dateTimeText(f.due_at)}</td>
                    <td><Badge tone={TONE[f.status] ?? "neutral"}>{f.status_title}</Badge>{f.error && <div className="text-xs" style={{ color: "var(--text-3)" }}>{f.error}</div>}</td>
                    <td>{f.assigned_to || "—"}</td>
                    <td className="whitespace-nowrap">
                      {f.conversation_id && <Link className="u-btn u-btn-ghost u-btn-sm" to={`/stores/${storeId}/inbox?c=${f.conversation_id}`}>گفتگو</Link>}
                      {f.status === "PENDING" && me?.can_write && (
                        <Button size="sm" variant="ghost" onClick={async () => { await del(storeId, `followups/${f.id}/`); await load(); }}>لغو</Button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="p-3 text-xs" style={{ color: "var(--text-3)" }}>{faNum(rows.length)} مورد · پیگیری‌ها هر دقیقه بررسی می‌شوند؛ پیامِ مشتری فقط در گفتگوی غیرآزمایشی فرستاده می‌شود.</p>
        </Card>
      )}
    </div>
  );
}
