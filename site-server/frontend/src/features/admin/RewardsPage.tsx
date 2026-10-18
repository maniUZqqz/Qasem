import { useCallback, useEffect, useState } from "react";

import { api, errorMessage } from "../../api/client";
import Icon from "../../components/Icon";
import {
  Alert,
  Badge,
  Button,
  Card,
  EmptyState,
  ErrorBox,
  Spinner,
  Table,
  fa,
  toman,
} from "../../components/ui";

/**
 * صف پاداش معرفی — چه بدهکاریم و به چه کسی.
 *
 * **پرداخت، کار یک آدم است.** `Reward` عمداً یک ردیف است نه یک انتقال:
 * پرداخت خودکار روی رویدادِ «ثبت‌نام»، یک سطح حمله‌ی تقلب باز می‌کند —
 * کسی صد حساب می‌سازد و صد پاداش می‌گیرد. برای همین این صفحه دکمه دارد،
 * نه زمان‌بند.
 */

type Reward = {
  id: number;
  kind: string;
  state: string;
  amount_toman: number;
  to: string;
  store: string;
  because: string;
  created_at: string;
};

const STATES = [
  { key: "PENDING", label: "در انتظار" },
  { key: "APPROVED", label: "تأییدشده" },
  { key: "PAID", label: "پرداخت‌شده" },
  { key: "VOID", label: "باطل" },
] as const;

const TONE: Record<string, "warn" | "info" | "ok" | "neutral"> = {
  PENDING: "warn",
  APPROVED: "info",
  PAID: "ok",
  VOID: "neutral",
};

const when = (iso: string) => new Date(iso).toLocaleDateString("fa-IR");

export default function RewardsPage() {
  const [state, setState] = useState<string>("PENDING");
  const [rows, setRows] = useState<Reward[] | null>(null);
  const [total, setTotal] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<number | null>(null);

  const load = useCallback(async () => {
    try {
      const { data } = await api.get<{ rewards: Reward[]; total_toman: number }>(
        `/marketing/rewards/?state=${state}`,
      );
      setRows(data.rewards);
      setTotal(data.total_toman);
      setError(null);
    } catch (err) {
      setError(errorMessage(err));
    }
  }, [state]);

  useEffect(() => {
    void load();
  }, [load]);

  const act = async (id: number, action: "approve" | "pay" | "void") => {
    if (action === "pay" && !window.confirm("تأیید می‌کنید که این مبلغ واقعاً پرداخت شده؟")) {
      return;
    }
    setBusyId(id);
    setError(null);
    try {
      await api.post("/marketing/rewards/", { id, action });
      await load();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusyId(null);
    }
  };

  return (
    <div className="space-y-4">
      <ErrorBox message={error} />

      <Alert tone="info" title="این صفحه پول جابه‌جا نمی‌کند">
        «پرداخت شد» یعنی <strong>شما</strong> بیرون از سیستم پرداخت کرده‌اید و اینجا
        ثبتش می‌کنید. ردپای این تغییر فقط-افزودنی است.
      </Alert>

      <div className="flex flex-wrap items-center gap-1.5">
        {STATES.map((s) => (
          <button
            key={s.key}
            onClick={() => setState(s.key)}
            className={`u-btn u-btn-sm ${state === s.key ? "u-btn-secondary" : "u-btn-ghost"}`}
            aria-pressed={state === s.key}
          >
            {s.label}
          </button>
        ))}
        {total > 0 && (
          <span className="mr-auto text-sm" style={{ color: "var(--text-2)" }}>
            جمع:{" "}
            <strong className="u-num" style={{ color: "var(--text)" }}>
              {toman(total)} تومان
            </strong>
          </span>
        )}
      </div>

      {rows === null ? (
        <div className="py-10 text-center">
          <Spinner />
        </div>
      ) : rows.length === 0 ? (
        <Card>
          <EmptyState icon="wallet" title="چیزی در این دسته نیست">
            پاداش وقتی ساخته می‌شود که کسی از راه معرفی ثبت‌نام کند و اشتراک بخرد.
          </EmptyState>
        </Card>
      ) : (
        <Card padded={false}>
          <Table>
            <thead>
              <tr>
                <th>به</th>
                <th>بابت</th>
                <th>فروشگاه</th>
                <th>مبلغ</th>
                <th>وضعیت</th>
                <th>تاریخ</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.id}>
                  <td style={{ color: "var(--text)", fontWeight: 500 }}>{r.to}</td>
                  <td>{r.because || r.kind}</td>
                  <td>{r.store}</td>
                  <td className="u-num">{toman(r.amount_toman)}</td>
                  <td>
                    <Badge tone={TONE[r.state] ?? "neutral"}>{r.state}</Badge>
                  </td>
                  <td className="u-num">{when(r.created_at)}</td>
                  <td>
                    <div className="flex gap-1.5">
                      {r.state === "PENDING" && (
                        <Button
                          size="sm"
                          variant="secondary"
                          onClick={() => void act(r.id, "approve")}
                          disabled={busyId === r.id}
                        >
                          تأیید
                        </Button>
                      )}
                      {(r.state === "PENDING" || r.state === "APPROVED") && (
                        <>
                          <Button
                            size="sm"
                            onClick={() => void act(r.id, "pay")}
                            disabled={busyId === r.id}
                          >
                            <Icon name="check" size={13} />
                            پرداخت شد
                          </Button>
                          <Button
                            size="sm"
                            variant="ghost"
                            onClick={() => void act(r.id, "void")}
                            disabled={busyId === r.id}
                          >
                            باطل
                          </Button>
                        </>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </Table>
        </Card>
      )}
    </div>
  );
}
