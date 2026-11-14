import { useCallback, useEffect, useState } from "react";

import { api, errorMessage } from "../../../../api/client";
import { Badge, Button, Card, ErrorBox, Spinner, fa } from "../../../../components/ui";

type Step = {
  key: string;
  title: string;
  state: "ok" | "todo" | "wait" | "unknown";
  detail: string;
  how: string;
  marked: boolean;
  marked_at: string;
  markable: boolean;
};
type Resp = { steps: Step[]; open: number; total: number; checked_at: string };

const TONE: Record<Step["state"], "ok" | "bad" | "warn" | "neutral"> = { ok: "ok", todo: "bad", wait: "warn", unknown: "neutral" };
const TEXT: Record<Step["state"], string> = { ok: "انجام شده", todo: "مانده", wait: "منتظرِ تأییدِ شما", unknown: "هنوز معلوم نیست" };

/**
 * «کارهایی که فقط خودِ شما می‌توانید بکنید»: همه‌چیزِ دیگر (به‌روزرسانی، نصب، آزمون، اجرای کارهای منتظر) خودکار است؛ این‌ها حساب، اعتبار، مجوز و تأییدِ واقعیت‌اند.
 * وضعیتِ هر مورد زنده از آزمون‌ها و تنظیم‌ها خوانده می‌شود؛ مواردِ تصمیمی با تیکِ «انجام شد» بسته می‌شوند.
 */
export default function OwnerSteps() {
  const [data, setData] = useState<Resp | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setData((await api.get<Resp>("/compute/owner-steps/")).data);
      setErr(null);
    } catch (e) {
      setErr(errorMessage(e));
    }
  }, []);

  useEffect(() => {
    void load();
    const t = setInterval(() => void load(), 30000);
    return () => clearInterval(t);
  }, [load]);

  async function mark(key: string, done: boolean) {
    setBusy(key);
    try {
      setData((await api.post<Resp>("/compute/owner-steps/", { key, done })).data);
    } catch (e) {
      setErr(errorMessage(e));
    } finally {
      setBusy(null);
    }
  }

  return (
    <Card padded={false}>
      <div className="nmt-sec" data-testid="owner-steps">
        <div className="nmt-sec-title">
          <h2>کارهایی که فقط خودِ شما می‌توانید بکنید</h2>
          <span>{data ? (data.open ? `${fa(data.open)} مورد مانده از ${fa(data.total)}` : "همه انجام شده") : ""}</span>
        </div>
        <p className="nmt-small">همهٔ چیزهای دیگر (به‌روزرسانی، نصبِ نیازمندی‌ها، آزمون، اجرای کارهای منتظر) خودکار است؛ این‌ها به حساب، اعتبار، مجوز یا تأییدِ شما بسته‌اند.</p>
        <ErrorBox message={err} />
        {!data && !err && <Spinner size={16} />}
        {data && (
          <div className="nmt-list">
            {data.steps.map((s) => (
              <div key={s.key} className="nmt-test" data-step={s.key} data-state={s.state}>
                <div className="nmt-test-row">
                  <Badge tone={TONE[s.state]}>{TEXT[s.state]}</Badge>
                  <b className="nmt-wrap">{s.title}</b>
                  {s.markable && (
                    <Button size="sm" variant="secondary" disabled={busy !== null} onClick={() => void mark(s.key, !s.marked)}>
                      {busy === s.key ? "…" : s.marked ? "برگرداندنِ تیک" : "انجام شد"}
                    </Button>
                  )}
                </div>
                <p className="nmt-small nmt-wrap">{s.detail}</p>
                {s.state !== "ok" && <p className="nmt-small nmt-wrap"><b>چه کنید: </b>{s.how}</p>}
              </div>
            ))}
          </div>
        )}
      </div>
    </Card>
  );
}
