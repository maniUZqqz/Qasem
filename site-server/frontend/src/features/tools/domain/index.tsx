import { useCallback, useEffect, useState } from "react";

import { api, errorMessage } from "../../../api/client";
import Icon from "../../../components/Icon";
import { Button, Card, ErrorBox, Field, Input, PageHeader, SectionTitle, Spinner } from "../../../components/ui";
import type { CheckResult, DomainStatus } from "./model";
import { CheckResultView, StatusCard, StepsCard } from "./parts";

/**
 * «دامنه و SSL» (فقط کارکنان، فقط خواندنی).
 *
 * وضعیتِ فعلی (فقط IP / دامنه + تاریخِ انقضای گواهی)، «بررسیِ DNS» ِ یک دامنه با رکوردهایی که باید ساخت، و راهنمای قدم‌به‌قدمِ ثبت‌کننده.
 * خودِ نصبِ دامنه از پنل انجام نمی‌شود (root لازم دارد): `/root/nm-domain.sh <دامنه> --www` روی سرور. بک‌اند: apps/panel/domain_status.py.
 */
export default function DomainPage() {
  const [status, setStatus] = useState<DomainStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const [domain, setDomain] = useState("");
  const [www, setWww] = useState(true);
  const [checking, setChecking] = useState(false);
  const [checkError, setCheckError] = useState<string | null>(null);
  const [result, setResult] = useState<CheckResult | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const r = await api.get<DomainStatus>("/panel/domain/");
      setStatus(r.data);
      setError(null);
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const check = async () => {
    setChecking(true);
    setCheckError(null);
    try {
      const r = await api.post<CheckResult>("/panel/domain/check/", { domain, www });
      setResult(r.data);
    } catch (e) {
      setResult(null);
      setCheckError(errorMessage(e));
    } finally {
      setChecking(false);
    }
  };

  return (
    <div className="u-rise space-y-5">
      <PageHeader
        title="دامنه و SSL"
        subtitle="NM الان روی نشانیِ IP است یا روی دامنهٔ شما؟ گواهیِ https تا کی معتبر است؟ دامنه را چطور وصل کنم؟"
        actions={
          <Button variant="secondary" size="sm" onClick={() => void load()} disabled={loading}>
            <span className="inline-flex items-center gap-1">
              <Icon name="refresh" size={14} />
              تازه‌سازی
            </span>
          </Button>
        }
      />

      {loading && !status && (
        <div className="flex justify-center py-10">
          <Spinner />
        </div>
      )}
      {error && <ErrorBox message={error} />}
      {status && <StatusCard status={status} />}

      <Card>
        <SectionTitle>بررسیِ DNS یک دامنه</SectionTitle>
        <p className="mb-3 text-sm" style={{ color: "var(--text-3)" }}>
          فقط DNS را می‌خواند و هیچ چیزی را عوض نمی‌کند. نشان می‌دهد دامنه به این سرور اشاره می‌کند یا نه و اگر نه، چه رکوردی بسازید.
        </p>
        <form
          className="flex flex-wrap items-end gap-3"
          onSubmit={(e) => {
            e.preventDefault();
            if (domain.trim() && !checking) void check();
          }}
        >
          <div className="min-w-[14rem] flex-1">
            <Field label="نامِ دامنه" hint="مثل example.ir (بدونِ http و بدونِ www)">
              <Input dir="ltr" placeholder="example.ir" value={domain} onChange={(e) => setDomain(e.target.value)} autoComplete="off" />
            </Field>
          </div>
          <label className="flex items-center gap-2 pb-2 text-sm" style={{ color: "var(--text-2)" }}>
            <input type="checkbox" checked={www} onChange={(e) => setWww(e.target.checked)} />
            www هم کار کند
          </label>
          <Button type="submit" disabled={checking || !domain.trim()}>
            {checking ? "در حال بررسی…" : "بررسیِ DNS"}
          </Button>
        </form>
        {checking && (
          <div className="mt-3 flex items-center gap-2 text-sm" style={{ color: "var(--text-3)" }}>
            <Spinner size={16} /> چند DNSِ مستقل پرسیده می‌شود؛ تا نیم دقیقه طول می‌کشد.
          </div>
        )}
        {checkError && (
          <div className="mt-3">
            <ErrorBox message={checkError} />
          </div>
        )}
        {result && <CheckResultView result={result} />}
      </Card>

      <StepsCard ip={status?.server_ip ?? result?.server_ip ?? "87.107.160.17"} />
    </div>
  );
}
